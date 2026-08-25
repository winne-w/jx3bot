"""Mongo persistence boundary for rebuildable JJC match-fact projections."""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from src.infra.mongo import get_db as _get_db


_COLLECTION_NAME = "jjc_match_facts"
_MAX_BSON_INT = 2 ** 63 - 1
_SHA256_HEX = re.compile(r"[0-9a-fA-F]{64}\Z")
_TOMBSTONE_FIELDS = (
    "match_id",
    "active",
    "invalid_reason",
    "schema_version",
    "source_cached_at",
    "source_hash",
)
_ACTIVE_QUERY_FIELDS = (
    "match_time",
    "map",
    "duration",
    "match_type",
    "team1",
    "team2",
    "any_team_combo_keys",
    "min_team_score_sum",
    "max_team_score_sum",
)


@dataclass(frozen=True)
class JjcMatchFactRepo:
    """Apply source-versioned match facts without allowing stale overwrites.

    Correct first-write behavior requires the ``idx_match_id`` unique index
    created by the subsequent index task.
    """

    db: Optional[AsyncIOMotorDatabase] = None

    COLLECTION_NAME = _COLLECTION_NAME
    _MAX_CAS_RETRIES = 4

    def _db(self) -> AsyncIOMotorDatabase:
        return self.db if self.db is not None else _get_db()

    def _collection(self) -> Any:
        return getattr(self._db(), self.COLLECTION_NAME)

    @staticmethod
    def _is_bson_positive_int(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and 0 < value <= _MAX_BSON_INT

    @staticmethod
    def _is_positive_finite_number(value: Any) -> bool:
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return 0 < value <= _MAX_BSON_INT
        return isinstance(value, float) and math.isfinite(value) and value > 0

    @classmethod
    def _normalize_projection(cls, document: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and copy a projection, canonicalizing inactive documents."""
        if not isinstance(document, dict):
            raise ValueError("projection document must be a dict")
        if not cls._is_bson_positive_int(document.get("match_id")):
            raise ValueError("match_id must be a positive BSON integer")
        if not isinstance(document.get("active"), bool):
            raise ValueError("active must be a boolean")
        if not cls._is_bson_positive_int(document.get("schema_version")):
            raise ValueError("schema_version must be a positive integer")
        if not cls._is_positive_finite_number(document.get("source_cached_at")):
            raise ValueError("source_cached_at must be a positive finite number")
        source_hash = document.get("source_hash")
        if not isinstance(source_hash, str) or _SHA256_HEX.fullmatch(source_hash) is None:
            raise ValueError("source_hash must be a SHA-256 hex digest")

        if document["active"]:
            missing = [field for field in _ACTIVE_QUERY_FIELDS if field not in document]
            if missing:
                raise ValueError("active projection is missing query fields: %s" % ", ".join(missing))
            projection = copy.deepcopy(document)
            # ``_id`` belongs to a persisted Mongo document, never to a caller's
            # projection payload.  Keeping it in a replacement could attempt to
            # mutate an existing immutable ID or duplicate one during upsert.
            projection.pop("_id", None)
            return projection

        invalid_reason = document.get("invalid_reason")
        if not isinstance(invalid_reason, str) or not invalid_reason:
            raise ValueError("inactive projection requires invalid_reason")
        return {field: copy.deepcopy(document[field]) for field in _TOMBSTONE_FIELDS}

    @classmethod
    def _classify_success(cls, document: Dict[str, Any], inserted: bool) -> str:
        if not document["active"]:
            return "tombstoned"
        return "inserted" if inserted else "updated"

    @classmethod
    def _current_is_valid(cls, current: Dict[str, Any]) -> bool:
        return (
            cls._is_positive_finite_number(current.get("source_cached_at"))
            and isinstance(current.get("source_hash"), str)
            and _SHA256_HEX.fullmatch(current["source_hash"]) is not None
            and cls._is_bson_positive_int(current.get("schema_version"))
        )

    @staticmethod
    def _cas_filter(current: Dict[str, Any], match_id: int) -> Dict[str, Any]:
        return {
            "match_id": match_id,
            "source_cached_at": current.get("source_cached_at"),
            "source_hash": current.get("source_hash"),
            "schema_version": current.get("schema_version"),
        }

    async def _try_insert(self, document: Dict[str, Any]) -> Optional[str]:
        """Insert only if no versioned projection exists for the match key."""
        try:
            result = await self._collection().replace_one(
                {
                    "match_id": document["match_id"],
                    "source_cached_at": {"$exists": False},
                },
                document,
                upsert=True,
            )
        except DuplicateKeyError:
            return None

        if getattr(result, "upserted_id", None) is not None:
            return self._classify_success(document, inserted=True)
        if getattr(result, "matched_count", 0):
            # This only repairs a legacy document with no source version.
            return self._classify_success(document, inserted=False)
        return None

    async def apply_projection(self, document: Dict[str, Any]) -> str:
        """Conditionally persist one active fact or inactive tombstone.

        The first write is an atomic conditional upsert.  Once a unique-key
        collision proves a projection already exists, every replacement carries
        the exact source version/hash/schema observed by the read.  A competing
        writer can therefore make the CAS miss, but cannot be overwritten.
        """
        incoming = self._normalize_projection(document)
        match_id = incoming["match_id"]

        for _ in range(self._MAX_CAS_RETRIES):
            inserted = await self._try_insert(incoming)
            if inserted is not None:
                return inserted

            current = await self.get_projection_state(match_id)
            if current is None:
                continue
            if not self._current_is_valid(current):
                result = await self._collection().replace_one(
                    self._cas_filter(current, match_id), incoming, upsert=False
                )
                if getattr(result, "matched_count", 0):
                    return self._classify_success(incoming, inserted=False)
                continue

            current_cached_at = current["source_cached_at"]
            incoming_cached_at = incoming["source_cached_at"]
            if incoming_cached_at < current_cached_at:
                return "skipped_old"
            if incoming_cached_at == current_cached_at:
                if incoming["source_hash"] != current["source_hash"]:
                    return "conflict"
                if incoming["schema_version"] <= current["schema_version"]:
                    return "noop"

            result = await self._collection().replace_one(
                self._cas_filter(current, match_id), incoming, upsert=False
            )
            if getattr(result, "matched_count", 0):
                return self._classify_success(incoming, inserted=False)

        raise RuntimeError("unable to apply match-fact projection after CAS retries")

    async def get_projection_state(self, match_id: Any) -> Optional[Dict[str, Any]]:
        """Return the stored projection for one exact BSON-integer match ID."""
        if not self._is_bson_positive_int(match_id):
            raise ValueError("match_id must be a positive BSON integer")
        document = await self._collection().find_one({"match_id": match_id})
        return copy.deepcopy(document) if isinstance(document, dict) else None

    async def get_projection_states(
        self, match_ids: Iterable[Any]
    ) -> Dict[int, Dict[str, Any]]:
        """Read projection states for unique IDs with one Mongo ``find`` call."""
        unique_ids = []
        seen_ids = set()
        for match_id in match_ids:
            if not self._is_bson_positive_int(match_id):
                raise ValueError("match_id must be a positive BSON integer")
            if match_id not in seen_ids:
                seen_ids.add(match_id)
                unique_ids.append(match_id)
        if not unique_ids:
            return {}

        result: Dict[int, Dict[str, Any]] = {}
        cursor = self._collection().find({"match_id": {"$in": unique_ids}})
        async for document in cursor:
            if isinstance(document, dict) and self._is_bson_positive_int(document.get("match_id")):
                result[document["match_id"]] = copy.deepcopy(document)
        return result

"""Persistent per-role kungfu refresh tasks; successful results live on the role."""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import uuid4

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument, UpdateOne
from pymongo.errors import BulkWriteError

from src.infra.mongo import get_db


QUEUE_INDEXES = {
    "idx_kungfu_next_run": [("status", 1), ("next_run_at", 1), ("_id", 1)],
    "idx_kungfu_expired_lease": [("status", 1), ("lease_expires_at", 1)],
}
_SCOPE_FIELDS = ("season_id", "season_start", "pvp_type", "algorithm_version")


class QueueIntegrityError(RuntimeError):
    """A missing or regressed counter cannot safely be rebuilt while workers run."""


def _scope_filter(scope: Dict[str, Any]) -> Dict[str, Any]:
    return {"scope." + key: scope[key] for key in _SCOPE_FIELDS}


def _valid_generation(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _published_version(identity: Dict[str, Any]) -> int:
    if "jjc_kungfu" not in identity:
        return 0
    result = identity["jjc_kungfu"]
    version = result.get("publish_version") if isinstance(result, dict) else None
    if not _valid_generation(version) or version == 0:
        raise QueueIntegrityError("invalid role kungfu publication schema")
    return version


@dataclass(frozen=True)
class JjcKungfuRefreshRepo:
    db: Optional[AsyncIOMotorDatabase] = None

    def _database(self):
        return self.db if self.db is not None else get_db()

    def _col(self):
        return self._database().jjc_kungfu_refresh_queue

    async def ensure_indexes(self) -> None:
        """Do not silently run with a conflicting index or drop existing indexes."""
        indexes = await self._col().index_information()
        for name, keys in QUEUE_INDEXES.items():
            existing = indexes.get(name)
            if existing is not None and (
                existing.get("key") != keys or existing.get("unique", False)
                or "expireAfterSeconds" in existing or "partialFilterExpression" in existing
            ):
                raise QueueIntegrityError("conflicting kungfu queue index: " + name)
            await self._col().create_index(keys, name=name)
        actual = await self._col().index_information()
        for name, keys in QUEUE_INDEXES.items():
            if actual.get(name, {}).get("key") != keys:
                raise QueueIntegrityError("missing kungfu queue index: " + name)

    async def get_by_id(self, identity_id: ObjectId) -> Optional[Dict[str, Any]]:
        return await self._col().find_one({"_id": identity_id})

    async def register(
        self, identities: List[Dict[str, Any]], scope: Dict[str, Any], now: float,
        track_seconds: int = 172800,
    ) -> None:
        """Batch registration preserves existing attempts, retry time and counters.

        Online registration never recreates a disappeared queue for a role with a
        published result. Recovery of that case requires stopping old writers.
        """
        if not identities:
            return
        scope = {key: scope[key] for key in _SCOPE_FIELDS}
        by_id = {identity["_id"]: identity for identity in identities}
        if not all(isinstance(identity_id, ObjectId) for identity_id in by_id):
            raise ValueError("kungfu queue requires BSON identity ObjectId")
        for identity in by_id.values():
            _published_version(identity)
        # The retry loop only handles legitimate scope migration racing a claim.
        # Same-scope registrations need one read and one bulk write.
        for _ in range(3):
            rows = await self._col().find({"_id": {"$in": list(by_id)}}).to_list(None)
            existing = {row["_id"]: row for row in rows}
            missing = [identity_id for identity_id in by_id if identity_id not in existing]
            if any(_published_version(by_id[key]) for key in missing):
                raise QueueIntegrityError("queue missing for published role; stop workers before recovery")
            if missing:
                # A passed ranking snapshot may predate a successful publication.
                current_roles = await self._database().role_identities.find(
                    {"_id": {"$in": missing}}, {"jjc_kungfu": 1}
                ).to_list(None)
                if any(_published_version(role) for role in current_roles):
                    raise QueueIntegrityError("queue missing for published role; stop workers before recovery")
            for identity_id, row in existing.items():
                if (not _valid_generation(row.get("generation"))
                        or row["generation"] < _published_version(by_id[identity_id])):
                    raise QueueIntegrityError("queue generation is behind role publication")
            operations = []
            migrations = []
            tracking = {"last_seen_in_ranking_at": now, "active_until": now + track_seconds}
            for identity_id in by_id:
                row = existing.get(identity_id)
                if row is None:
                    operations.append(UpdateOne({"_id": identity_id}, {
                        "$setOnInsert": {"scope": scope, "status": "pending", "next_run_at": now,
                                         "generation": 0, "lease_token": None, "lease_expires_at": None,
                                         "consecutive_failures": 0, "last_error_code": None},
                        "$max": tracking,
                    }, upsert=True))
                elif row.get("scope") == scope:
                    operations.append(UpdateOne({"_id": identity_id}, {"$max": tracking}))
                else:
                    migrations.append(identity_id)
                    guard = {"_id": identity_id, "generation": row["generation"],
                             "status": row["status"], "lease_token": row.get("lease_token"),
                             **_scope_filter(row["scope"])}
                    operations.append(UpdateOne(guard, {
                        "$set": {"scope": scope, "status": "pending", "next_run_at": now,
                                 "lease_token": None, "lease_expires_at": None,
                                 "consecutive_failures": 0, "last_error_code": None},
                        "$inc": {"generation": 1}, "$max": tracking,
                    }))
            try:
                await self._col().bulk_write(operations, ordered=False)
            except BulkWriteError as exc:
                errors = exc.details.get("writeErrors", [])
                if not errors or any(item.get("code") != 11000 for item in errors) or exc.details.get("writeConcernErrors"):
                    raise
                # Concurrent insert won. Retry normal updates without an upsert.
                await self._col().bulk_write([
                    UpdateOne({"_id": key}, {"$max": tracking}) for key in by_id
                ], ordered=False)
            if not migrations:
                return
            after = await self._col().find({"_id": {"$in": migrations}}).to_list(None)
            remaining = [row["_id"] for row in after if row.get("scope") != scope]
            if not remaining:
                return
            by_id = {key: by_id[key] for key in remaining}
        raise QueueIntegrityError("scope migration repeatedly lost its compare-and-set")

    async def claim(
        self, scope: Dict[str, Any], now: float, lease_seconds: int = 90,
    ) -> Optional[Dict[str, Any]]:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        return await self._col().find_one_and_update(
            {"status": "pending", "next_run_at": {"$lte": now},
             "active_until": {"$gt": now}, **_scope_filter(scope)},
            {"$set": {"status": "running", "lease_token": uuid4().hex,
                      "lease_expires_at": now + lease_seconds}, "$inc": {"generation": 1}},
            sort=[("next_run_at", 1), ("_id", 1)], return_document=ReturnDocument.AFTER,
        )

    async def claim_identity(
        self, identity_id: ObjectId, scope: Dict[str, Any], now: float,
        lease_seconds: int = 90,
    ) -> Optional[Dict[str, Any]]:
        """Reserve a direct query now, fencing any background attempt for this role.

        Registration must precede this call. It deliberately ignores scheduling
        and retry time: the caller performs the query before returning.
        """
        if not isinstance(identity_id, ObjectId) or lease_seconds <= 0:
            raise ValueError("direct kungfu claim requires role ID and positive lease")
        return await self._col().find_one_and_update(
            {"_id": identity_id, "status": {"$in": ["pending", "running"]},
             **_scope_filter(scope)},
            {"$set": {"status": "running", "lease_token": uuid4().hex,
                      "lease_expires_at": now + lease_seconds}, "$inc": {"generation": 1}},
            return_document=ReturnDocument.AFTER,
        )

    async def complete(
        self, task: Dict[str, Any], now: float, next_run_at: float,
        error_code: Optional[str] = None,
    ) -> bool:
        if not task.get("lease_token") or not _valid_generation(task.get("generation")):
            return False
        guard = {"_id": task["_id"], "status": "running", "generation": task["generation"],
                 "lease_token": task["lease_token"], "lease_expires_at": {"$gt": now},
                 **_scope_filter(task["scope"])}
        update = {"$set": {"status": "pending", "next_run_at": next_run_at,
                           "lease_token": None, "lease_expires_at": None,
                           "last_error_code": error_code}}
        if error_code is None:
            update["$set"]["consecutive_failures"] = 0
        else:
            update["$inc"] = {"consecutive_failures": 1}
        result = await self._col().update_one(guard, update)
        return result.matched_count == 1

    async def recover_expired(self, now: float, limit: int = 100) -> int:
        if limit <= 0:
            return 0
        guard = {"status": "running", "lease_expires_at": {"$lte": now}}
        rows = await self._col().find(guard, {"_id": 1}).sort(
            [("lease_expires_at", 1)]
        ).limit(limit).to_list(limit)
        if not rows:
            return 0
        result = await self._col().update_many(
            {**guard, "_id": {"$in": [row["_id"] for row in rows]}},
            {"$set": {"status": "pending", "next_run_at": now,
                      "lease_token": None, "lease_expires_at": None}},
        )
        return result.modified_count

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.infra.mongo import get_db as _get_db

try:
    from nonebot import logger  # type: ignore
except Exception:  # pragma: no cover - fallback for isolated unit tests
    import logging

    logger = logging.getLogger(__name__)


COLLECTION_NAME = "jjc_match_participants"

DETAIL_SOURCE_MATCH_DETAIL = "match_detail"
DETAIL_SOURCE_SYNC_WORKER = "sync_worker"
DETAIL_SOURCE_RANKING_DETAIL = "ranking_detail"
DETAIL_SOURCE_WARMUP = "warmup"
DETAIL_SOURCE_MANUAL = "manual"
DETAIL_SOURCE_UNKNOWN = "unknown"
SYNC_STATUS_NOT_SYNCED = "not_synced"


@dataclass(frozen=True)
class JjcMatchParticipantRepo:
    """Read model for locally available JJC match-detail participants."""

    db: Optional[AsyncIOMotorDatabase] = None

    COLLECTION_NAME = COLLECTION_NAME
    DETAIL_SOURCE_MATCH_DETAIL = DETAIL_SOURCE_MATCH_DETAIL
    DETAIL_SOURCE_SYNC_WORKER = DETAIL_SOURCE_SYNC_WORKER
    DETAIL_SOURCE_RANKING_DETAIL = DETAIL_SOURCE_RANKING_DETAIL
    DETAIL_SOURCE_WARMUP = DETAIL_SOURCE_WARMUP
    DETAIL_SOURCE_MANUAL = DETAIL_SOURCE_MANUAL
    DETAIL_SOURCE_UNKNOWN = DETAIL_SOURCE_UNKNOWN
    SYNC_STATUS_NOT_SYNCED = SYNC_STATUS_NOT_SYNCED

    def _db(self) -> AsyncIOMotorDatabase:
        return self.db if self.db is not None else _get_db()

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str) and value.strip():
            try:
                return int(float(value))
            except ValueError:
                return None
        return None

    @staticmethod
    def _pick_str(*values: Any) -> Optional[str]:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    @classmethod
    def _extract_payload_data(cls, payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        if isinstance(data, dict):
            return data
        return payload

    @classmethod
    def _extract_detail(cls, payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        data = cls._extract_payload_data(payload)
        if not isinstance(data, dict) or data.get("unavailable"):
            return None
        detail = data.get("detail")
        if isinstance(detail, dict):
            return detail
        return None

    @classmethod
    def _iter_team_players(cls, detail: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any], Dict[str, Any], int]]:
        result: List[Tuple[str, Dict[str, Any], Dict[str, Any], int]] = []
        for team_key in ("team1", "team2"):
            team = detail.get(team_key)
            if not isinstance(team, dict):
                continue
            players = team.get("players_info") or []
            if not isinstance(players, list):
                continue
            for index, player in enumerate(players):
                if isinstance(player, dict):
                    result.append((team_key, team, player, index))
        return result

    @classmethod
    def _detect_3v3(cls, detail: Dict[str, Any], player_count: int) -> Tuple[bool, bool]:
        basic_info = detail.get("basic_info") if isinstance(detail.get("basic_info"), dict) else {}
        explicit_type = cls._coerce_int(
            basic_info.get("match_type")
            or basic_info.get("pvp_type")
            or basic_info.get("type")
            or detail.get("match_type")
            or detail.get("pvp_type")
            or detail.get("type")
        )
        if explicit_type is not None:
            return explicit_type == 3, False
        return player_count == 6, player_count == 6

    @classmethod
    def is_local_3v3_detail(cls, detail: Dict[str, Any]) -> bool:
        team_players = cls._iter_team_players(detail)
        is_3v3, _ = cls._detect_3v3(detail, len(team_players))
        return is_3v3

    @classmethod
    def _extract_match_time(cls, data: Dict[str, Any], detail: Dict[str, Any], seen_doc: Optional[Dict[str, Any]]) -> Optional[int]:
        basic_info = detail.get("basic_info") if isinstance(detail.get("basic_info"), dict) else {}
        for source in (seen_doc or {}, data, detail, basic_info):
            match_time = cls._coerce_int(
                source.get("match_time")
                or source.get("matchTime")
                or source.get("start_time")
                or source.get("startTime")
                or source.get("time")
            )
            if match_time is not None:
                return match_time
        return None

    @classmethod
    def _build_sync_fields(cls, seen_doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(seen_doc, dict) or not seen_doc:
            return {
                "sync_status": SYNC_STATUS_NOT_SYNCED,
                "detail_saved_at": None,
                "source_identity_id": None,
                "source_identity_key": None,
            }
        status = cls._pick_str(seen_doc.get("status")) or SYNC_STATUS_NOT_SYNCED
        source_identity_id = seen_doc.get("source_identity_id")
        return {
            "sync_status": status,
            "detail_saved_at": seen_doc.get("detail_saved_at"),
            "source_identity_id": str(source_identity_id) if source_identity_id is not None else None,
            "source_identity_key": seen_doc.get("source_identity_key"),
        }

    @classmethod
    def build_participants_from_match_detail(
        cls,
        match_id: Union[int, str, None],
        payload: Optional[Dict[str, Any]],
        seen_doc: Optional[Dict[str, Any]] = None,
        detail_source: str = DETAIL_SOURCE_MATCH_DETAIL,
    ) -> List[Dict[str, Any]]:
        """Build participant read-model rows from a cached match-detail payload.

        This method is intentionally pure and does not require MongoDB.
        """
        data = cls._extract_payload_data(payload)
        detail = cls._extract_detail(payload)
        if not isinstance(data, dict) or not isinstance(detail, dict):
            return []

        normalized_match_id = cls._coerce_int(match_id) or cls._coerce_int(data.get("match_id"))
        if normalized_match_id is None:
            return []

        team_players = cls._iter_team_players(detail)
        is_3v3, match_type_inferred = cls._detect_3v3(detail, len(team_players))
        if not is_3v3:
            return []

        basic_info = detail.get("basic_info") if isinstance(detail.get("basic_info"), dict) else {}
        match_time = cls._extract_match_time(data, detail, seen_doc)
        start_time = cls._coerce_int(basic_info.get("start_time") or detail.get("start_time")) or match_time
        cached_at = payload.get("cached_at") if isinstance(payload, dict) else None
        if cached_at is None:
            cached_at = data.get("cached_at")
        sync_fields = cls._build_sync_fields(seen_doc)
        now = time.time()

        participants: List[Dict[str, Any]] = []
        seen_global_ids = set()
        for team_key, team, player, player_index in team_players:
            global_id = cls._pick_str(player.get("global_id"), player.get("globalId"))
            if not global_id or global_id in seen_global_ids:
                continue
            seen_global_ids.add(global_id)

            role_name = cls._pick_str(player.get("role_name"), player.get("roleName"), player.get("name"))
            raw_mmr = cls._coerce_int(player.get("mmr"))
            raw_score = cls._coerce_int(player.get("score"))
            raw_total_score = cls._coerce_int(player.get("total_score"))
            if raw_total_score is None:
                raw_total_score = cls._coerce_int(player.get("totalScore"))
            game_score = raw_total_score
            game_score_source = "total_score" if raw_total_score is not None else None
            if game_score is None and raw_score is not None:
                game_score = raw_score
                game_score_source = "score"
            participant = {
                "match_id": normalized_match_id,
                "global_id": global_id,
                "team_key": team_key,
                "player_index": player_index,
                "role_name": role_name,
                "server": cls._pick_str(player.get("server"), player.get("server_name"), player.get("serverName")),
                "zone": cls._pick_str(player.get("zone")),
                "role_id": cls._pick_str(player.get("role_id"), player.get("roleId")),
                "game_role_id": cls._pick_str(player.get("game_role_id"), player.get("gameRoleId"), player.get("role_id"), player.get("roleId")),
                "global_role_id": cls._pick_str(player.get("global_role_id"), player.get("globalRoleId")),
                "person_id": cls._pick_str(player.get("person_id"), player.get("personId")),
                "kungfu": cls._pick_str(player.get("kungfu")),
                "kungfu_id": cls._pick_str(player.get("kungfu_id"), player.get("kungfuId")),
                "won": bool(team.get("won")),
                "mvp": bool(player.get("mvp")),
                "match_type": 3,
                "match_type_inferred": match_type_inferred,
                "match_time": match_time,
                "start_time": start_time,
                "duration": cls._coerce_int(basic_info.get("duration") or detail.get("duration")),
                "avg_grade": cls._coerce_int(basic_info.get("grade") or detail.get("avg_grade")),
                "tuilan_score": raw_mmr,
                "game_score": game_score,
                "game_score_source": game_score_source,
                "raw_mmr": raw_mmr,
                "raw_score": raw_score,
                "raw_total_score": raw_total_score,
                "total_mmr": cls._coerce_int(
                    player.get("total_mmr")
                    or player.get("totalMmr")
                    or player.get("total_score")
                    or player.get("score")
                    or player.get("mmr")
                    or team.get("total_mmr")
                    or detail.get("total_mmr")
                ),
                "mmr_delta": cls._coerce_int(
                    player.get("mmr_delta")
                    or player.get("mmrDelta")
                    or player.get("score_delta")
                    or player.get("scoreDelta")
                    or detail.get("mmr_delta")
                ),
                "cached_at": cached_at,
                "detail_available": True,
                "detail_source": detail_source,
                "updated_at": now,
            }
            participant.update(sync_fields)
            participants.append(participant)

        return participants

    async def replace_match_participants(
        self,
        match_id: Union[int, str],
        participants: List[Dict[str, Any]],
    ) -> int:
        normalized_match_id = self._coerce_int(match_id)
        if normalized_match_id is None:
            return 0
        db = self._db()
        try:
            if not participants:
                await db.jjc_match_participants.delete_many({"match_id": normalized_match_id})
                return 0
            now = time.time()
            current_global_ids = []
            for item in participants:
                doc = dict(item)
                doc["match_id"] = normalized_match_id
                doc["updated_at"] = doc.get("updated_at") or now
                global_id = self._pick_str(doc.get("global_id"))
                if not global_id:
                    continue
                current_global_ids.append(global_id)
                await db.jjc_match_participants.update_one(
                    {"match_id": normalized_match_id, "global_id": global_id},
                    {"$set": doc},
                    upsert=True,
                )
            await db.jjc_match_participants.delete_many({
                "match_id": normalized_match_id,
                "global_id": {"$nin": current_global_ids},
            })
            return len(current_global_ids)
        except Exception as exc:
            logger.warning(f"替换 JJC 对局参与者投影失败: match_id={normalized_match_id} error={exc}")
            raise

    async def clear_match_participants(self, match_id: Union[int, str]) -> int:
        normalized_match_id = self._coerce_int(match_id)
        if normalized_match_id is None:
            return 0
        db = self._db()
        try:
            result = await db.jjc_match_participants.delete_many({"match_id": normalized_match_id})
            return int(getattr(result, "deleted_count", 0) or 0)
        except Exception as exc:
            logger.warning(f"清理 JJC 对局参与者投影失败: match_id={normalized_match_id} error={exc}")
            raise

    async def refresh_sync_status(
        self,
        match_id: Union[int, str],
        seen_doc: Optional[Dict[str, Any]] = None,
    ) -> int:
        normalized_match_id = self._coerce_int(match_id)
        if normalized_match_id is None:
            return 0
        sync_fields = self._build_sync_fields(seen_doc)
        sync_fields["updated_at"] = time.time()
        db = self._db()
        try:
            result = await db.jjc_match_participants.update_many(
                {"match_id": normalized_match_id},
                {"$set": sync_fields},
            )
            return int(getattr(result, "modified_count", 0) or 0)
        except Exception as exc:
            logger.warning(f"刷新 JJC 对局参与者同步状态失败: match_id={normalized_match_id} error={exc}")
            raise

    async def list_local_3v3_matches_by_global_id(
        self,
        global_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        target_global_id = self._pick_str(global_id)
        safe_page = max(1, page)
        safe_page_size = min(max(1, page_size), 100)
        if not target_global_id:
            return {
                "items": [],
                "total": 0,
                "page": safe_page,
                "page_size": safe_page_size,
                "has_more": False,
            }

        query = {"global_id": target_global_id, "match_type": 3, "detail_available": True}
        skip = (safe_page - 1) * safe_page_size
        db = self._db()
        started_at = time.perf_counter()
        try:
            phase_started_at = time.perf_counter()
            total = await db.jjc_match_participants.count_documents(query)
            count_ms = int((time.perf_counter() - phase_started_at) * 1000)
            phase_started_at = time.perf_counter()
            cursor = (
                db.jjc_match_participants.find(query)
                .sort([("match_time", -1), ("match_id", -1)])
                .skip(skip)
                .limit(safe_page_size)
            )
            items = await cursor.to_list(length=safe_page_size)
            find_ms = int((time.perf_counter() - phase_started_at) * 1000)
        except Exception as exc:
            logger.warning(f"按 global_id 读取本地 JJC 参与者投影失败: global_id={target_global_id} error={exc}")
            raise
        logger.info(
            "JJC match_participants 查询完成: global_id={} elapsed_ms={} count_ms={} find_ms={} "
            "skip={} limit={} total={} items={}".format(
                target_global_id,
                int((time.perf_counter() - started_at) * 1000),
                count_ms,
                find_ms,
                skip,
                safe_page_size,
                total,
                len(items),
            )
        )

        return {
            "items": items,
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
            "has_more": safe_page * safe_page_size < total,
        }

    async def aggregate_peak_scores(
        self,
        *,
        window_start: int,
        window_end: int,
        score_type: str,
        max_items: Optional[int] = None,
        include_source_counts: bool = True,
    ) -> Dict[str, Any]:
        started_at = time.perf_counter()
        if score_type == "tuilan":
            score_field = "tuilan_score"
            score_source_expr: Any = "mmr"
        elif score_type == "game":
            score_field = "game_score"
            score_source_expr = "$game_score_source"
        else:
            raise ValueError("unsupported_score_type")

        match_query = {
            "match_type": 3,
            "detail_available": True,
            "match_time": {"$gte": int(window_start), "$lte": int(window_end)},
            "global_id": {"$type": "string", "$ne": ""},
            score_field: {"$exists": True, "$ne": None},
        }
        pipeline: List[Dict[str, Any]] = [
            {"$match": match_query},
            {
                "$sort": {
                    score_field: -1,
                    "match_time": -1,
                    "match_id": -1,
                }
            },
            {
                "$group": {
                    "_id": "$global_id",
                    "score": {"$first": "${}".format(score_field)},
                    "match_id": {"$first": "$match_id"},
                    "match_time": {"$first": "$match_time"},
                    "score_source": {"$first": score_source_expr},
                    "global_id": {"$first": "$global_id"},
                    "role_name": {"$first": "$role_name"},
                    "server": {"$first": "$server"},
                    "zone": {"$first": "$zone"},
                    "kungfu": {"$first": "$kungfu"},
                    "kungfu_id": {"$first": "$kungfu_id"},
                    "match_count": {"$sum": 1},
                }
            },
            {
                "$sort": {
                    "score": -1,
                    "match_time": -1,
                    "match_id": -1,
                }
            },
        ]
        if max_items is not None and max_items > 0:
            pipeline.append({"$limit": int(max_items)})

        db = self._db()
        try:
            source_match_count = 0
            source_participant_count = 0
            if include_source_counts:
                source_match_ids = await db.jjc_match_participants.distinct("match_id", match_query)
                source_match_count = len(source_match_ids)
                source_participant_count = await db.jjc_match_participants.count_documents(match_query)
            cursor = db.jjc_match_participants.aggregate(pipeline, allowDiskUse=True)
            docs = await cursor.to_list(length=max_items if max_items and max_items > 0 else None)
            items: List[Dict[str, Any]] = []
            for index, doc in enumerate(docs, start=1):
                item = {
                    "rank": index,
                    "score": self._coerce_int(doc.get("score")),
                    "match_id": self._coerce_int(doc.get("match_id")),
                    "match_time": self._coerce_int(doc.get("match_time")),
                    "score_source": self._pick_str(doc.get("score_source")),
                    "global_id": self._pick_str(doc.get("global_id")),
                    "role_name": self._pick_str(doc.get("role_name")),
                    "server": self._pick_str(doc.get("server")),
                    "zone": self._pick_str(doc.get("zone")),
                    "kungfu": self._pick_str(doc.get("kungfu")),
                    "kungfu_id": self._pick_str(doc.get("kungfu_id")),
                    "match_count": self._coerce_int(doc.get("match_count")) or 0,
                }
                items.append(item)
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info(
                "JJC peak-score aggregate participants done: score_type={} window_start={} window_end={} max_items={} include_source_counts={} elapsed_ms={} item_count={} source_matches={} source_participants={}".format(
                    score_type,
                    window_start,
                    window_end,
                    max_items,
                    include_source_counts,
                    elapsed_ms,
                    len(items),
                    source_match_count,
                    int(source_participant_count),
                )
            )
            return {
                "items": items,
                "item_count": len(items),
                "source_match_count": source_match_count,
                "source_participant_count": int(source_participant_count),
            }
        except Exception as exc:
            logger.warning(
                "聚合 JJC 历史最高分失败: score_type={} window_start={} window_end={} error={}".format(
                    score_type,
                    window_start,
                    window_end,
                    exc,
                )
            )
            raise

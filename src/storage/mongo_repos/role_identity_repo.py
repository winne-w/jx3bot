from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from nonebot import logger
from pymongo.errors import DuplicateKeyError

from src.infra.mongo import get_db as _get_db
from src.services.jx3.role_identity_matching import (
    build_guarded_profile_set_fields,
    build_identity_key as _build_role_identity_key,
    coerce_match_time,
    legacy_identity_keys,
    should_overwrite_profile_fields,
)

SCHEMA_VERSION = 1

_LEVEL_ORDER = {"name": 0, "game_role": 1, "global": 2, "global_id": 3}

MATCH_DETAIL_IDENTITY_PROJECTION: Dict[str, int] = {
    "_id": 1,
    "identity_key": 1,
    "identity_level": 1,
    "server": 1,
    "normalized_server": 1,
    "name": 1,
    "normalized_name": 1,
    "zone": 1,
    "game_role_id": 1,
    "role_id": 1,
    "person_id": 1,
    "global_role_id": 1,
    "global_id": 1,
    "aliases": 1,
    "sources": 1,
    "profile_observed_at": 1,
    "role_info_observed_match_time": 1,
    "last_seen_at": 1,
    "updated_at": 1,
}


def _normalize(value: str) -> str:
    return (value or "").strip().lower()


def _coerce_object_id(value: Any) -> Optional[ObjectId]:
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    return None


def _global_id_string_filter(global_id: str) -> Dict[str, str]:
    return {"$eq": global_id, "$type": "string"}


def _identity_strength(doc: Dict[str, Any]) -> int:
    identity_level = str(doc.get("identity_level") or "").strip()
    if identity_level in _LEVEL_ORDER:
        return _LEVEL_ORDER[identity_level]
    identity_key = str(doc.get("identity_key") or "")
    if doc.get("global_id") or identity_key.startswith("global_id:"):
        return _LEVEL_ORDER["global_id"]
    if doc.get("global_role_id") or identity_key.startswith("global:"):
        return _LEVEL_ORDER["global"]
    if doc.get("game_role_id") or doc.get("role_id") or identity_key.startswith("game:"):
        return _LEVEL_ORDER["game_role"]
    return _LEVEL_ORDER["name"]


def _timestamp_value(value: Any) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _candidate_role_key(doc: Dict[str, Any]) -> Tuple[str, str]:
    normalized_server = doc.get("normalized_server")
    normalized_name = doc.get("normalized_name")
    server = normalized_server if normalized_server else doc.get("server")
    name = normalized_name if normalized_name else doc.get("name")
    return (
        _normalize(str(server or "")),
        _normalize(str(name or "")),
    )


def build_identity_key(
    global_role_id: Optional[str] = None,
    zone: Optional[str] = None,
    game_role_id: Optional[str] = None,
    server: Optional[str] = None,
    name: Optional[str] = None,
    global_id: Optional[str] = None,
) -> Tuple[str, str]:
    """根据可用外部 ID 生成 (identity_key, identity_level)。

    优先级：global_id > global_role_id > zone + game_role_id > server + name。
    """
    return _build_role_identity_key(
        global_role_id=global_role_id,
        zone=zone,
        game_role_id=game_role_id,
        server=server,
        name=name,
        global_id=global_id,
    )


@dataclass(frozen=True)
class RoleIdentityRepo:
    """游戏角色身份统一模型仓储。

    不存心法缓存结果，只维护角色在不同来源中的身份标识及关联关系。
    """

    db: Optional[AsyncIOMotorDatabase] = None

    def _col(self):
        db = self.db if self.db is not None else _get_db()
        return db.role_identities

    def _history_col(self):
        db = self.db if self.db is not None else _get_db()
        return db.role_identities_history

    @staticmethod
    def _strip_id(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if doc:
            doc.pop("_id", None)
        return doc

    # ---- 查询 ----

    async def find_by_global_role_id(self, global_role_id: str) -> Optional[Dict[str, Any]]:
        doc = await self._col().find_one({
            "$or": [
                {"global_role_id": global_role_id},
                {"identity_key": f"global:{global_role_id}"},
            ]
        })
        return self._strip_id(doc)

    async def find_by_global_id(self, global_id: str) -> Optional[Dict[str, Any]]:
        doc = await self._col().find_one({
            "$or": [
                {"global_id": _global_id_string_filter(global_id)},
                {"identity_key": f"global_id:{global_id}"},
            ]
        })
        return self._strip_id(doc)

    async def find_by_game_role_id(self, zone: str, game_role_id: str) -> Optional[Dict[str, Any]]:
        doc = await self._col().find_one({
            "$or": [
                {"zone": zone, "game_role_id": game_role_id},
                {"zone": zone, "role_id": game_role_id},
                {"identity_key": f"game:{zone}:{game_role_id}"},
            ]
        })
        return self._strip_id(doc)

    async def find_by_name(self, server: str, name: str) -> List[Dict[str, Any]]:
        """按规范化服务器+角色名查询，可能返回多条（同名同服不同来源的旧记录）。"""
        ns = _normalize(server)
        nn = _normalize(name)
        cursor = self._col().find({"normalized_server": ns, "normalized_name": nn})
        docs = await cursor.to_list(None)
        for doc in docs:
            doc.pop("_id", None)
        return docs

    async def find_best_by_name_with_id(
        self,
        server: str,
        name: str,
        projection: Optional[Dict[str, int]] = None,
    ) -> Optional[Dict[str, Any]]:
        """按名称查询最佳身份，返回保留原生 _id 的文档。

        同服同名多身份时，优先身份强度 global_id > global > game_role > name，
        再按 last_seen_at/updated_at 最新记录排序。
        """
        ns = _normalize(server)
        nn = _normalize(name)
        query = {"normalized_server": ns, "normalized_name": nn}
        cursor = self._col().find(query, projection) if projection is not None else self._col().find(query)
        docs = await cursor.to_list(None)
        if not docs:
            return None
        docs.sort(
            key=lambda doc: (
                _identity_strength(doc),
                max(
                    _timestamp_value(doc.get("last_seen_at")),
                    _timestamp_value(doc.get("updated_at")),
                ),
            ),
            reverse=True,
        )
        return docs[0]

    async def find_synced_match_page_candidates(
        self,
        server: str,
        name: str,
        *,
        limit: int = 8,
    ) -> List[Dict[str, Any]]:
        """Find local role identities that can help users recover from an exact miss.

        Candidates are limited to local identities: same normalized name on other
        servers, or names with an @ suffix based on the queried base name.
        """
        ns = _normalize(server)
        nn = _normalize(name)
        if not nn:
            return []

        suffix_pattern = "^" + re.escape(nn + "@")
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        pipeline = [
            {
                "$match": {
                    "$or": [
                        {"normalized_name": nn, "normalized_server": {"$ne": ns}},
                        {"normalized_name": {"$regex": suffix_pattern}},
                    ]
                }
            },
            {
                "$addFields": {
                    "_candidate_same_server": {
                        "$cond": [{"$eq": ["$normalized_server", ns]}, 1, 0]
                    },
                    "_candidate_identity_strength": {
                        "$switch": {
                            "branches": [
                                {"case": {"$eq": ["$identity_level", "global_id"]}, "then": 3},
                                {"case": {"$eq": ["$identity_level", "global"]}, "then": 2},
                                {"case": {"$eq": ["$identity_level", "game_role"]}, "then": 1},
                                {"case": {"$ne": ["$global_id", None]}, "then": 3},
                                {"case": {"$ne": ["$global_role_id", None]}, "then": 2},
                                {"case": {"$ne": ["$game_role_id", None]}, "then": 1},
                                {"case": {"$ne": ["$role_id", None]}, "then": 1},
                            ],
                            "default": 0,
                        }
                    },
                    "_candidate_freshness": {
                        "$max": [
                            {"$ifNull": ["$last_seen_at", epoch]},
                            {"$ifNull": ["$updated_at", epoch]},
                        ]
                    },
                    "_candidate_role_server": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$ne": ["$normalized_server", None]},
                                    {"$ne": ["$normalized_server", ""]},
                                ]
                            },
                            "$normalized_server",
                            {
                                "$toLower": {
                                    "$trim": {"input": {"$ifNull": ["$server", ""]}}
                                }
                            },
                        ]
                    },
                    "_candidate_role_name": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$ne": ["$normalized_name", None]},
                                    {"$ne": ["$normalized_name", ""]},
                                ]
                            },
                            "$normalized_name",
                            {
                                "$toLower": {
                                    "$trim": {"input": {"$ifNull": ["$name", ""]}}
                                }
                            },
                        ]
                    },
                }
            },
            {
                "$sort": {
                    "_candidate_same_server": -1,
                    "_candidate_identity_strength": -1,
                    "_candidate_freshness": -1,
                    "_candidate_role_server": 1,
                    "_candidate_role_name": 1,
                    "_id": 1,
                }
            },
            {
                "$group": {
                    "_id": {
                        "server": "$_candidate_role_server",
                        "name": "$_candidate_role_name",
                    },
                    "doc": {"$first": "$$ROOT"},
                }
            },
            {"$replaceRoot": {"newRoot": "$doc"}},
            {
                "$sort": {
                    "_candidate_same_server": -1,
                    "_candidate_identity_strength": -1,
                    "_candidate_freshness": -1,
                    "_candidate_role_server": 1,
                    "_candidate_role_name": 1,
                    "_id": 1,
                }
            },
            {"$limit": limit},
            {
                "$project": {
                    "_candidate_same_server": 0,
                    "_candidate_identity_strength": 0,
                    "_candidate_freshness": 0,
                    "_candidate_role_server": 0,
                    "_candidate_role_name": 0,
                }
            },
        ]
        cursor = self._col().aggregate(pipeline)
        docs = await cursor.to_list(limit)
        deduped: List[Dict[str, Any]] = []
        seen_role_keys = set()
        for doc in docs:
            candidate_server, candidate_name = _candidate_role_key(doc)
            if candidate_server == ns and candidate_name == nn:
                continue
            dedupe_key = (candidate_server, candidate_name)
            if dedupe_key in seen_role_keys:
                continue
            seen_role_keys.add(dedupe_key)
            deduped.append(doc)
            if len(deduped) >= limit:
                break
        return deduped

    async def get_by_id(self, identity_id: Any) -> Optional[Dict[str, Any]]:
        """按 role_identities._id 查询身份，返回保留原生 _id 的文档。"""
        object_id = _coerce_object_id(identity_id)
        if object_id is None:
            return None
        return await self._col().find_one({"_id": object_id})

    async def resolve_best_identity(
        self,
        server: str,
        name: str,
        zone: Optional[str] = None,
        game_role_id: Optional[str] = None,
        global_role_id: Optional[str] = None,
        global_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """按优先级查找最佳匹配身份：global_id > global_role_id > zone+game_role_id > server+name。"""
        replay_gid = (global_id or "").strip()
        if replay_gid:
            doc = await self.find_by_global_id(replay_gid)
            if doc:
                return doc

        gid = (global_role_id or "").strip()
        if gid:
            doc = await self.find_by_global_role_id(gid)
            if doc:
                return doc

        z = (zone or "").strip()
        grid = (game_role_id or "").strip()
        if z and grid:
            doc = await self.find_by_game_role_id(z, grid)
            if doc:
                return doc

        docs = await self.find_by_name(server, name)
        return docs[0] if docs else None

    async def resolve_best_identity_with_id(
        self,
        server: str,
        name: str,
        zone: Optional[str] = None,
        game_role_id: Optional[str] = None,
        global_role_id: Optional[str] = None,
        global_id: Optional[str] = None,
        projection: Optional[Dict[str, int]] = None,
    ) -> Optional[Dict[str, Any]]:
        """按优先级查找最佳匹配身份，返回保留原生 _id 的文档。"""
        replay_gid = (global_id or "").strip()
        if replay_gid:
            doc = await self._col().find_one({
                "$or": [
                    {"global_id": _global_id_string_filter(replay_gid)},
                    {"identity_key": f"global_id:{replay_gid}"},
                ]
            }, projection)
            if doc:
                return doc

        gid = (global_role_id or "").strip()
        if gid:
            doc = await self._col().find_one({
                "$or": [
                    {"global_role_id": gid},
                    {"identity_key": f"global:{gid}"},
                ]
            }, projection)
            if doc:
                return doc

        z = (zone or "").strip()
        grid = (game_role_id or "").strip()
        if z and grid:
            doc = await self._col().find_one({
                "$or": [
                    {"zone": z, "game_role_id": grid},
                    {"zone": z, "role_id": grid},
                    {"identity_key": f"game:{z}:{grid}"},
                ]
            }, projection)
            if doc:
                return doc

        ns = _normalize(server)
        nn = _normalize(name)
        return await self.find_best_by_name_with_id(ns, nn, projection)

    # ---- upsert 入口 ----

    async def upsert_from_ranking(
        self,
        server: str,
        name: str,
        zone: str,
        game_role_id: str,
        global_role_id: Optional[str] = None,
        role_id: Optional[str] = None,
        person_id: Optional[str] = None,
        global_id: Optional[str] = None,
        cache_repo: Any = None,
    ) -> Dict[str, Any]:
        """从排行榜数据写入或升级身份。"""
        return await self._upsert_identity(
            server=server, name=name, zone=zone, game_role_id=game_role_id,
            global_role_id=global_role_id, role_id=role_id, person_id=person_id,
            global_id=global_id, source="ranking", cache_repo=cache_repo,
        )

    async def upsert_from_ranking_with_id(
        self,
        server: str,
        name: str,
        zone: str,
        game_role_id: str,
        global_role_id: Optional[str] = None,
        role_id: Optional[str] = None,
        person_id: Optional[str] = None,
        global_id: Optional[str] = None,
        cache_repo: Any = None,
    ) -> Dict[str, Any]:
        """从排行榜数据写入或升级身份，返回保留原生 _id 的文档。"""
        return await self._upsert_identity(
            server=server, name=name, zone=zone, game_role_id=game_role_id,
            global_role_id=global_role_id, role_id=role_id, person_id=person_id,
            global_id=global_id, source="ranking", cache_repo=cache_repo,
            preserve_id=True,
        )

    async def upsert_from_indicator(
        self,
        server: str,
        name: str,
        zone: Optional[str] = None,
        game_role_id: Optional[str] = None,
        global_role_id: Optional[str] = None,
        role_id: Optional[str] = None,
        person_id: Optional[str] = None,
        global_id: Optional[str] = None,
        cache_repo: Any = None,
    ) -> Dict[str, Any]:
        """从 indicator 接口数据写入或升级身份。"""
        return await self._upsert_identity(
            server=server, name=name, zone=zone, game_role_id=game_role_id,
            global_role_id=global_role_id, role_id=role_id, person_id=person_id,
            global_id=global_id,
            source="indicator", cache_repo=cache_repo,
        )

    async def upsert_from_match_detail(
        self,
        server: str,
        name: str,
        zone: Optional[str] = None,
        game_role_id: Optional[str] = None,
        global_role_id: Optional[str] = None,
        role_id: Optional[str] = None,
        person_id: Optional[str] = None,
        observed_at: Optional[datetime] = None,
        observed_match_time: Optional[int] = None,
        global_id: Optional[str] = None,
        cache_repo: Any = None,
    ) -> Dict[str, Any]:
        """从对局详情数据写入或升级身份。"""
        return await self._upsert_identity(
            server=server, name=name, zone=zone, game_role_id=game_role_id,
            global_role_id=global_role_id, role_id=role_id, person_id=person_id,
            global_id=global_id, source="match_detail", observed_at=observed_at,
            observed_match_time=observed_match_time, cache_repo=cache_repo,
        )

    async def upsert_from_match_detail_with_id(
        self,
        server: str,
        name: str,
        zone: Optional[str] = None,
        game_role_id: Optional[str] = None,
        global_role_id: Optional[str] = None,
        role_id: Optional[str] = None,
        person_id: Optional[str] = None,
        observed_at: Optional[datetime] = None,
        observed_match_time: Optional[int] = None,
        global_id: Optional[str] = None,
        cache_repo: Any = None,
    ) -> Dict[str, Any]:
        """从对局详情数据写入或升级身份，返回保留原生 _id 的文档。"""
        return await self._upsert_identity(
            server=server, name=name, zone=zone, game_role_id=game_role_id,
            global_role_id=global_role_id, role_id=role_id, person_id=person_id,
            global_id=global_id, source="match_detail", observed_at=observed_at,
            observed_match_time=observed_match_time, cache_repo=cache_repo,
            preserve_id=True,
        )

    async def refresh_indicator_fields_by_id(
        self,
        identity_id: Any,
        global_role_id: str,
        refresh_source: str = "indicator",
        zone: Optional[str] = None,
        game_role_id: Optional[str] = None,
        role_id: Optional[str] = None,
        person_id: Optional[str] = None,
        server: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """按 _id 刷新 indicator 解析出的身份字段，返回保留原生 _id 的文档。"""
        object_id = _coerce_object_id(identity_id)
        if object_id is None:
            return None

        now = datetime.now(timezone.utc)
        set_fields: Dict[str, Any] = {
            "global_role_id": global_role_id,
            "global_role_id_refreshed_at": now,
            "global_role_id_refresh_source": refresh_source,
            "updated_at": now,
        }
        optional_fields = {
            "zone": zone,
            "game_role_id": game_role_id,
            "role_id": role_id,
            "person_id": person_id,
            "server": server,
            "name": name,
        }
        for field_name, value in optional_fields.items():
            if value is not None:
                set_fields[field_name] = value
        if server is not None:
            set_fields["normalized_server"] = _normalize(server)
        if name is not None:
            set_fields["normalized_name"] = _normalize(name)

        await self._col().update_one({"_id": object_id}, {"$set": set_fields})
        return await self.get_by_id(object_id)

    # ---- 显式升级 ----

    async def upgrade_identity(
        self,
        current_identity_key: str,
        global_role_id: Optional[str] = None,
        zone: Optional[str] = None,
        game_role_id: Optional[str] = None,
        global_id: Optional[str] = None,
        cache_repo: Any = None,
    ) -> Optional[Dict[str, Any]]:
        """显式升级身份：当获得更高级别外部 ID 时调用。

        若新 key 与当前 key 同级或更低，不做任何操作并返回现有文档。
        升级后将旧 identity_key 推入 aliases。
        若提供 cache_repo，升级成功时同步迁移 role_jjc_cache 中的 identity_key。
        """
        existing = await self._col().find_one({"identity_key": current_identity_key})
        if not existing:
            return None

        new_key, new_level = build_identity_key(
            global_id=global_id,
            global_role_id=global_role_id,
            zone=zone or existing.get("zone"),
            game_role_id=game_role_id or existing.get("game_role_id"),
            server=existing.get("server", ""),
            name=existing.get("name", ""),
        )

        current_level = existing.get("identity_level", "name")
        if _LEVEL_ORDER.get(new_level, 0) <= _LEVEL_ORDER.get(current_level, 0):
            existing.pop("_id", None)
            return existing

        now = datetime.now(timezone.utc)
        set_fields: Dict[str, Any] = {
            "identity_key": new_key,
            "identity_level": new_level,
            "updated_at": now,
        }
        if global_role_id:
            set_fields["global_role_id"] = global_role_id
        if global_id:
            set_fields["global_id"] = global_id
        if zone:
            set_fields["zone"] = zone
        if game_role_id:
            set_fields["game_role_id"] = game_role_id

        try:
            await self._col().update_one(
                {"identity_key": current_identity_key},
                {
                    "$set": set_fields,
                    "$push": {"aliases": current_identity_key},
                },
            )
        except DuplicateKeyError:
            logger.warning(
                "身份升级冲突: old_key={} new_key={} 目标已存在，跳过升级",
                current_identity_key, new_key,
            )
            existing.pop("_id", None)
            return existing

        if cache_repo is not None:
            await cache_repo.migrate_identity_key(current_identity_key, new_key)

        doc = await self._col().find_one({"identity_key": new_key})
        if doc:
            doc.pop("_id", None)
        return doc

    # ---- 内部实现 ----

    async def _upsert_identity(
        self,
        server: str,
        name: str,
        source: str,
        zone: Optional[str] = None,
        game_role_id: Optional[str] = None,
        global_role_id: Optional[str] = None,
        global_id: Optional[str] = None,
        role_id: Optional[str] = None,
        person_id: Optional[str] = None,
        observed_at: Optional[datetime] = None,
        observed_match_time: Optional[int] = None,
        cache_repo: Any = None,
        preserve_id: bool = False,
    ) -> Dict[str, Any]:
        """通用 upsert：查找已有身份 → 可能升级 → 新建或更新。"""
        started_at = time.perf_counter()
        now = datetime.now(timezone.utc)
        profile_observed_at = observed_at or now
        profile_observed_match_time = (
            coerce_match_time(observed_match_time)
            if observed_match_time is not None
            else coerce_match_time(observed_at)
        )
        effective_game_role_id = game_role_id or role_id
        ns = _normalize(server)
        nn = _normalize(name)

        phase_started_at = time.perf_counter()
        if preserve_id:
            projection = MATCH_DETAIL_IDENTITY_PROJECTION if source == "match_detail" else None
            existing = await self.resolve_best_identity_with_id(
                server=server, name=name,
                zone=zone, game_role_id=effective_game_role_id,
                global_role_id=global_role_id, global_id=global_id,
                projection=projection,
            )
        else:
            existing = await self.resolve_best_identity(
                server=server, name=name,
                zone=zone, game_role_id=effective_game_role_id,
                global_role_id=global_role_id, global_id=global_id,
            )
        resolve_ms = int((time.perf_counter() - phase_started_at) * 1000)

        if existing:
            result = await self._update_existing(
                existing, server, name, ns, nn,
                zone, effective_game_role_id, global_role_id, global_id, role_id, person_id,
                source, now, profile_observed_at, profile_observed_match_time,
                cache_repo=cache_repo, preserve_id=preserve_id,
            )
            if source == "match_detail":
                logger.info(
                    "JJC role_identities match_detail upsert 完成: path=existing identity_key={} global_id={} "
                    "server={} name={} resolve_ms={} total_ms={}".format(
                        result.get("identity_key") if isinstance(result, dict) else existing.get("identity_key"),
                        global_id,
                        server,
                        name,
                        resolve_ms,
                        int((time.perf_counter() - started_at) * 1000),
                    )
                )
            return result

        # 无已有身份 → 新建
        identity_key, identity_level = build_identity_key(
            global_role_id=global_role_id, zone=zone, game_role_id=effective_game_role_id,
            server=server, name=name, global_id=global_id,
        )
        doc = {
            "identity_key": identity_key,
            "identity_level": identity_level,
            "server": server,
            "normalized_server": ns,
            "name": name,
            "normalized_name": nn,
            "role_id": role_id or None,
            "person_id": person_id or None,
            "aliases": [],
            "sources": [source],
            "profile_observed_at": profile_observed_at,
            "first_seen_at": now,
            "last_seen_at": now,
            "updated_at": now,
            "schema_version": SCHEMA_VERSION,
        }
        if profile_observed_match_time is not None:
            doc["role_info_observed_match_time"] = profile_observed_match_time
            doc["role_info_source"] = source
            doc["role_info_updated_at"] = now.timestamp()
        # 只写入有实际值的字段，避免 null 参与 partial unique 索引导致冲突
        if zone:
            doc["zone"] = zone
        if effective_game_role_id:
            doc["game_role_id"] = effective_game_role_id
        if global_role_id:
            doc["global_role_id"] = global_role_id
        if global_id:
            doc["global_id"] = global_id

        try:
            phase_started_at = time.perf_counter()
            insert_result = await self._col().insert_one(doc)
            insert_ms = int((time.perf_counter() - phase_started_at) * 1000)
            if preserve_id and "_id" not in doc:
                doc["_id"] = insert_result.inserted_id
        except DuplicateKeyError:
            logger.warning("插入身份冲突（并发写入），重新查找: key={}", identity_key)
            existing = await self._col().find_one({"identity_key": identity_key})
            if existing:
                if not preserve_id:
                    existing.pop("_id", None)
                return await self._update_existing(
                    existing, server, name, ns, nn,
                    zone, effective_game_role_id, global_role_id, global_id, role_id, person_id,
                    source, now, profile_observed_at, profile_observed_match_time,
                    cache_repo=cache_repo, preserve_id=preserve_id,
                )
            raise

        if source == "match_detail":
            logger.info(
                "JJC role_identities match_detail upsert 完成: path=insert identity_key={} global_id={} "
                "server={} name={} resolve_ms={} insert_ms={} total_ms={}".format(
                    identity_key,
                    global_id,
                    server,
                    name,
                    resolve_ms,
                    insert_ms,
                    int((time.perf_counter() - started_at) * 1000),
                )
            )
        if not preserve_id:
            doc.pop("_id", None)
        return doc

    async def _update_existing(
        self,
        existing: Dict[str, Any],
        server: str,
        name: str,
        ns: str,
        nn: str,
        zone: Optional[str],
        game_role_id: Optional[str],
        global_role_id: Optional[str],
        global_id: Optional[str],
        role_id: Optional[str],
        person_id: Optional[str],
        source: str,
        now: datetime,
        profile_observed_at: datetime,
        observed_match_time: Optional[int],
        cache_repo: Any = None,
        preserve_id: bool = False,
    ) -> Dict[str, Any]:
        """更新已有身份记录，必要时执行身份升级。"""
        started_at = time.perf_counter()
        current_key: str = existing["identity_key"]
        current_level: str = existing.get("identity_level", "name")
        existing_global_id = (existing.get("global_id") or "").strip()
        incoming_global_id = (global_id or "").strip()
        if existing_global_id and incoming_global_id and existing_global_id != incoming_global_id:
            logger.warning(
                "身份 global_id 冲突，跳过更新: identity_key={} existing_global_id={} incoming_global_id={}",
                current_key,
                existing_global_id,
                incoming_global_id,
            )
            if not preserve_id:
                existing.pop("_id", None)
            return existing

        new_key, new_level = build_identity_key(
            global_id=global_id, global_role_id=global_role_id, zone=zone, game_role_id=game_role_id,
            server=server, name=name,
        )

        needs_upgrade = _LEVEL_ORDER.get(new_level, 0) > _LEVEL_ORDER.get(current_level, 0)

        set_fields: Dict[str, Any] = {
            "last_seen_at": now,
            "updated_at": now,
        }
        should_update_profile = should_overwrite_profile_fields(
            existing,
            observed_match_time=observed_match_time,
            force_profile_update=False,
        )
        incoming_profile_fields = {
            "server": server,
            "normalized_server": ns,
            "name": name,
            "normalized_name": nn,
            "zone": zone,
            "game_role_id": game_role_id,
            "global_role_id": global_role_id,
            "role_id": role_id,
            "person_id": person_id,
        }
        set_fields.update(build_guarded_profile_set_fields(
            existing,
            incoming_profile_fields,
            observed_match_time=observed_match_time,
            force_profile_update=False,
        ))
        if should_update_profile:
            set_fields["profile_observed_at"] = profile_observed_at
            if observed_match_time is not None:
                set_fields["role_info_observed_match_time"] = observed_match_time
                set_fields["role_info_source"] = source
                set_fields["role_info_updated_at"] = now.timestamp()
        if global_id and not existing_global_id:
            set_fields["global_id"] = global_id

        if needs_upgrade:
            set_fields["identity_key"] = new_key
            set_fields["identity_level"] = new_level
            if global_id:
                set_fields["global_id"] = global_id

        update_op: Dict[str, Any] = {
            "$set": set_fields,
            "$addToSet": {
                "sources": source,
            },
        }
        if needs_upgrade:
            aliases = [current_key]
            aliases.extend(legacy_identity_keys(
                global_role_id=global_role_id,
                zone=zone,
                game_role_id=game_role_id,
                server=server,
                name=name,
            ))
            update_op["$addToSet"]["aliases"] = {"$each": sorted(set(aliases))}

        should_archive = self._should_archive_profile_change(existing, set_fields)
        if should_archive:
            phase_started_at = time.perf_counter()
            archived = await self._archive_profile_snapshot(
                existing,
                replaced_by_identity_key=new_key if needs_upgrade else current_key,
                archive_reason="role_identity_profile_updated",
                source=source,
                observed_match_time=observed_match_time,
                archived_at=now,
            )
            archive_ms = int((time.perf_counter() - phase_started_at) * 1000)
            if not archived:
                if not preserve_id:
                    existing.pop("_id", None)
                return existing
        else:
            archive_ms = 0

        try:
            phase_started_at = time.perf_counter()
            await self._col().update_one(
                {"identity_key": current_key},
                update_op,
            )
            update_ms = int((time.perf_counter() - phase_started_at) * 1000)
        except DuplicateKeyError:
            logger.warning(
                "身份升级冲突: old_key={} new_key={} 目标已存在，保留当前记录",
                current_key, new_key,
            )
            if not preserve_id:
                existing.pop("_id", None)
            return existing

        if needs_upgrade and cache_repo is not None:
            await cache_repo.migrate_identity_key(current_key, new_key)

        lookup_key = new_key if needs_upgrade else current_key
        phase_started_at = time.perf_counter()
        projection = MATCH_DETAIL_IDENTITY_PROJECTION if source == "match_detail" and preserve_id else None
        doc = await self._col().find_one({"identity_key": lookup_key}, projection)
        reload_ms = int((time.perf_counter() - phase_started_at) * 1000)
        if source == "match_detail":
            global_id_same = bool(existing_global_id and incoming_global_id and existing_global_id == incoming_global_id)
            logger.info(
                "JJC role_identities match_detail 更新阶段耗时: identity_key={} new_key={} existing_global_id={} incoming_global_id={} "
                "global_id_same={} needs_upgrade={} should_archive={} set_fields={} archive_ms={} update_ms={} reload_ms={} total_ms={}".format(
                    current_key,
                    new_key,
                    existing_global_id,
                    global_id,
                    global_id_same,
                    needs_upgrade,
                    should_archive,
                    sorted(set_fields.keys()),
                    archive_ms,
                    update_ms,
                    reload_ms,
                    int((time.perf_counter() - started_at) * 1000),
                )
            )
        if doc and not preserve_id:
            doc.pop("_id", None)
        return doc or existing

    def _should_archive_profile_change(
        self,
        existing: Dict[str, Any],
        set_fields: Dict[str, Any],
    ) -> bool:
        for field_name in ("server", "name", "global_role_id"):
            if field_name not in set_fields:
                continue
            old_value = str(existing.get(field_name) or "").strip()
            new_value = str(set_fields.get(field_name) or "").strip()
            if old_value and new_value and old_value != new_value:
                return True
        return False

    async def _archive_profile_snapshot(
        self,
        existing: Dict[str, Any],
        replaced_by_identity_key: str,
        archive_reason: str,
        source: str,
        observed_match_time: Optional[int],
        archived_at: datetime,
    ) -> bool:
        archive_doc = dict(existing)
        archive_doc.pop("_id", None)
        archive_doc["archived_at"] = archived_at
        archive_doc["archive_reason"] = archive_reason
        archive_doc["replaced_by_identity_key"] = replaced_by_identity_key
        archive_doc["archive_source"] = source
        if observed_match_time is not None:
            archive_doc["replaced_by_observed_match_time"] = observed_match_time
        try:
            await self._history_col().insert_one(archive_doc)
            return True
        except Exception as exc:
            logger.warning(
                "归档角色身份旧画像失败: identity_key={} replaced_by={} error={}".format(
                    existing.get("identity_key"),
                    replaced_by_identity_key,
                    exc,
                )
            )
            return False

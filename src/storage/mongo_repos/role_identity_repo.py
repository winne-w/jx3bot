from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorDatabase
from nonebot import logger
from pymongo.errors import DuplicateKeyError

from src.infra.mongo import get_db as _get_db
from src.services.jx3.role_identity_matching import (
    build_guarded_profile_set_fields,
    build_identity_key as _build_role_identity_key,
    build_profile_history_entry,
    coerce_match_time,
    legacy_identity_keys,
    should_overwrite_profile_fields,
)

SCHEMA_VERSION = 1

_LEVEL_ORDER = {"name": 0, "game_role": 1, "global": 2, "global_id": 3}


def _normalize(value: str) -> str:
    return (value or "").strip().lower()


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

    # ---- 查询 ----

    async def find_by_global_role_id(self, global_role_id: str) -> Optional[Dict[str, Any]]:
        doc = await self._col().find_one({
            "$or": [
                {"global_role_id": global_role_id},
                {"identity_key": f"global:{global_role_id}"},
            ]
        })
        if doc:
            doc.pop("_id", None)
        return doc

    async def find_by_global_id(self, global_id: str) -> Optional[Dict[str, Any]]:
        doc = await self._col().find_one({
            "$or": [
                {"global_id": global_id},
                {"identity_key": f"global_id:{global_id}"},
            ]
        })
        if doc:
            doc.pop("_id", None)
        return doc

    async def find_by_game_role_id(self, zone: str, game_role_id: str) -> Optional[Dict[str, Any]]:
        doc = await self._col().find_one({
            "$or": [
                {"zone": zone, "game_role_id": game_role_id},
                {"zone": zone, "role_id": game_role_id},
                {"identity_key": f"game:{zone}:{game_role_id}"},
            ]
        })
        if doc:
            doc.pop("_id", None)
        return doc

    async def find_by_name(self, server: str, name: str) -> List[Dict[str, Any]]:
        """按规范化服务器+角色名查询，可能返回多条（同名同服不同来源的旧记录）。"""
        ns = _normalize(server)
        nn = _normalize(name)
        cursor = self._col().find({"normalized_server": ns, "normalized_name": nn})
        docs = await cursor.to_list(None)
        for doc in docs:
            doc.pop("_id", None)
        return docs

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
    ) -> Dict[str, Any]:
        """通用 upsert：查找已有身份 → 可能升级 → 新建或更新。"""
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

        existing = await self.resolve_best_identity(
            server=server, name=name,
            zone=zone, game_role_id=effective_game_role_id,
            global_role_id=global_role_id, global_id=global_id,
        )

        if existing:
            return await self._update_existing(
                existing, server, name, ns, nn,
                zone, effective_game_role_id, global_role_id, global_id, role_id, person_id,
                source, now, profile_observed_at, profile_observed_match_time,
                cache_repo=cache_repo,
            )

        # 无已有身份 → 新建
        identity_key, identity_level = build_identity_key(
            global_role_id=global_role_id, zone=zone, game_role_id=effective_game_role_id,
            server=server, name=name, global_id=global_id,
        )
        history_entry = build_profile_history_entry(
            server=server, name=name, zone=zone, role_id=role_id,
            game_role_id=effective_game_role_id, global_role_id=global_role_id,
            global_id=global_id, person_id=person_id, source=source,
            observed_at=profile_observed_at,
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
            "profile_history": [history_entry],
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
            await self._col().insert_one(doc)
        except DuplicateKeyError:
            logger.warning("插入身份冲突（并发写入），重新查找: key={}", identity_key)
            existing = await self._col().find_one({"identity_key": identity_key})
            if existing:
                existing.pop("_id", None)
                return await self._update_existing(
                    existing, server, name, ns, nn,
                    zone, effective_game_role_id, global_role_id, global_id, role_id, person_id,
                    source, now, profile_observed_at, profile_observed_match_time,
                    cache_repo=cache_repo,
                )
            raise

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
    ) -> Dict[str, Any]:
        """更新已有身份记录，必要时执行身份升级。"""
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
                "profile_history": build_profile_history_entry(
                    server=server, name=name, zone=zone, role_id=role_id,
                    game_role_id=game_role_id, global_role_id=global_role_id,
                    global_id=global_id, person_id=person_id, source=source,
                    observed_at=profile_observed_at,
                ),
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
            archived = await self._archive_profile_snapshot(
                existing,
                replaced_by_identity_key=new_key if needs_upgrade else current_key,
                archive_reason="role_identity_profile_updated",
                source=source,
                observed_match_time=observed_match_time,
                archived_at=now,
            )
            if not archived:
                existing.pop("_id", None)
                return existing

        try:
            await self._col().update_one(
                {"identity_key": current_key},
                update_op,
            )
        except DuplicateKeyError:
            logger.warning(
                "身份升级冲突: old_key={} new_key={} 目标已存在，保留当前记录",
                current_key, new_key,
            )
            existing.pop("_id", None)
            return existing

        if needs_upgrade and cache_repo is not None:
            await cache_repo.migrate_identity_key(current_key, new_key)

        lookup_key = new_key if needs_upgrade else current_key
        doc = await self._col().find_one({"identity_key": lookup_key})
        if doc:
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

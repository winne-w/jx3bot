from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorDatabase
from nonebot import logger
from pymongo.errors import DuplicateKeyError

from src.infra.mongo import get_db as _get_db

SCHEMA_VERSION = 1

_LEVEL_ORDER = {"name": 0, "game_role": 1, "global": 2}


def _normalize(value: str) -> str:
    return (value or "").strip().lower()


def build_identity_key(
    global_role_id: Optional[str] = None,
    zone: Optional[str] = None,
    game_role_id: Optional[str] = None,
    server: Optional[str] = None,
    name: Optional[str] = None,
) -> Tuple[str, str]:
    """根据可用外部 ID 生成 (identity_key, identity_level)。

    优先级：global_role_id > zone + game_role_id > server + name。
    """
    gid = (global_role_id or "").strip()
    if gid:
        return f"global:{gid}", "global"

    z = (zone or "").strip()
    grid = (game_role_id or "").strip()
    if z and grid:
        return f"game:{z}:{grid}", "game_role"

    ns = _normalize(server or "")
    nn = _normalize(name or "")
    return f"name:{ns}:{nn}", "name"


@dataclass(frozen=True)
class RoleIdentityRepo:
    """游戏角色身份统一模型仓储。

    不存心法缓存结果，只维护角色在不同来源中的身份标识及关联关系。
    """

    db: Optional[AsyncIOMotorDatabase] = None

    def _col(self):
        db = self.db if self.db is not None else _get_db()
        return db.role_identities

    # ---- 查询 ----

    async def find_by_global_role_id(self, global_role_id: str) -> Optional[Dict[str, Any]]:
        doc = await self._col().find_one({"global_role_id": global_role_id})
        if doc:
            doc.pop("_id", None)
        return doc

    async def find_by_game_role_id(self, zone: str, game_role_id: str) -> Optional[Dict[str, Any]]:
        doc = await self._col().find_one({"zone": zone, "game_role_id": game_role_id})
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
    ) -> Optional[Dict[str, Any]]:
        """按优先级查找最佳匹配身份：global_role_id > zone+game_role_id > server+name。"""
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
        cache_repo: Any = None,
    ) -> Dict[str, Any]:
        """从排行榜数据写入或升级身份。"""
        return await self._upsert_identity(
            server=server, name=name, zone=zone, game_role_id=game_role_id,
            global_role_id=global_role_id, role_id=role_id, person_id=person_id,
            source="ranking", cache_repo=cache_repo,
        )

    async def upsert_from_indicator(
        self,
        server: str,
        name: str,
        zone: Optional[str] = None,
        game_role_id: Optional[str] = None,
        global_role_id: Optional[str] = None,
        role_id: Optional[str] = None,
        cache_repo: Any = None,
    ) -> Dict[str, Any]:
        """从 indicator 接口数据写入或升级身份。"""
        return await self._upsert_identity(
            server=server, name=name, zone=zone, game_role_id=game_role_id,
            global_role_id=global_role_id, role_id=role_id,
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
        cache_repo: Any = None,
    ) -> Dict[str, Any]:
        """从对局详情数据写入或升级身份。"""
        return await self._upsert_identity(
            server=server, name=name, zone=zone, game_role_id=game_role_id,
            global_role_id=global_role_id, role_id=role_id, person_id=person_id,
            source="match_detail", cache_repo=cache_repo,
        )

    # ---- 显式升级 ----

    async def upgrade_identity(
        self,
        current_identity_key: str,
        global_role_id: Optional[str] = None,
        zone: Optional[str] = None,
        game_role_id: Optional[str] = None,
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
        role_id: Optional[str] = None,
        person_id: Optional[str] = None,
        cache_repo: Any = None,
    ) -> Dict[str, Any]:
        """通用 upsert：查找已有身份 → 可能升级 → 新建或更新。"""
        now = datetime.now(timezone.utc)
        ns = _normalize(server)
        nn = _normalize(name)

        existing = await self.resolve_best_identity(
            server=server, name=name,
            zone=zone, game_role_id=game_role_id,
            global_role_id=global_role_id,
        )

        if existing:
            return await self._update_existing(
                existing, server, name, ns, nn,
                zone, game_role_id, global_role_id, role_id, person_id,
                source, now, cache_repo=cache_repo,
            )

        # 无已有身份 → 新建
        identity_key, identity_level = build_identity_key(
            global_role_id=global_role_id, zone=zone, game_role_id=game_role_id,
            server=server, name=name,
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
            "first_seen_at": now,
            "last_seen_at": now,
            "updated_at": now,
            "schema_version": SCHEMA_VERSION,
        }
        # 只写入有实际值的字段，避免 null 参与 partial unique 索引导致冲突
        if zone:
            doc["zone"] = zone
        if game_role_id:
            doc["game_role_id"] = game_role_id
        if global_role_id:
            doc["global_role_id"] = global_role_id

        try:
            await self._col().insert_one(doc)
        except DuplicateKeyError:
            logger.warning("插入身份冲突（并发写入），重新查找: key={}", identity_key)
            existing = await self._col().find_one({"identity_key": identity_key})
            if existing:
                existing.pop("_id", None)
                return await self._update_existing(
                    existing, server, name, ns, nn,
                    zone, game_role_id, global_role_id, role_id, person_id,
                    source, now, cache_repo=cache_repo,
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
        role_id: Optional[str],
        person_id: Optional[str],
        source: str,
        now: datetime,
        cache_repo: Any = None,
    ) -> Dict[str, Any]:
        """更新已有身份记录，必要时执行身份升级。"""
        current_key: str = existing["identity_key"]
        current_level: str = existing.get("identity_level", "name")

        new_key, new_level = build_identity_key(
            global_role_id=global_role_id, zone=zone, game_role_id=game_role_id,
            server=server, name=name,
        )

        needs_upgrade = _LEVEL_ORDER.get(new_level, 0) > _LEVEL_ORDER.get(current_level, 0)

        set_fields: Dict[str, Any] = {
            "server": server,
            "normalized_server": ns,
            "name": name,
            "normalized_name": nn,
            "last_seen_at": now,
            "updated_at": now,
        }

        # 更新非空外部 ID 字段（传了就用新值，否则保留已有值）
        for field_name, value in [
            ("zone", zone),
            ("game_role_id", game_role_id),
            ("global_role_id", global_role_id),
            ("role_id", role_id),
            ("person_id", person_id),
        ]:
            if value:
                set_fields[field_name] = value

        if needs_upgrade:
            set_fields["identity_key"] = new_key
            set_fields["identity_level"] = new_level

        update_op: Dict[str, Any] = {
            "$set": set_fields,
            "$addToSet": {"sources": source},
        }
        if needs_upgrade:
            update_op["$push"] = {"aliases": current_key}

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

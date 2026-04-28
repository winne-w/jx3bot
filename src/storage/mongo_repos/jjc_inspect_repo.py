from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional, Union

from motor.motor_asyncio import AsyncIOMotorDatabase
from nonebot import logger

from src.infra.mongo import get_db as _get_db


@dataclass(frozen=True)
class JjcInspectRepo:
    db: Optional[AsyncIOMotorDatabase] = None

    async def load_role_recent(self, server: str, name: str, *, ttl_seconds: int) -> Optional[dict[str, Any]]:
        db = self.db if self.db is not None else _get_db()
        try:
            doc = await db.jjc_role_recent.find_one({"server": server, "name": name})
        except Exception as exc:
            logger.warning("读取 JJC 角色近期缓存失败: server={} name={} error={}", server, name, exc)
            return None
        if doc is None:
            logger.info("JJC 角色近期缓存未命中: server={} name={}", server, name)
            return None
        cached_at = doc.get("cached_at")
        if not isinstance(cached_at, (int, float)):
            return None
        if time.time() - float(cached_at) > ttl_seconds:
            logger.info("JJC 角色近期缓存已过期: server={} name={}", server, name)
            return None
        return {"cached_at": cached_at, "data": doc.get("data")}

    async def save_role_recent(self, server: str, name: str, payload: dict[str, Any]) -> None:
        db = self.db if self.db is not None else _get_db()
        try:
            await db.jjc_role_recent.update_one(
                {"server": server, "name": name},
                {"$set": {
                    "cached_at": payload.get("cached_at") or time.time(),
                    "data": payload.get("data") or payload,
                }},
                upsert=True,
            )
        except Exception as exc:
            logger.warning("保存 JJC 角色近期缓存失败: server={} name={} error={}", server, name, exc)

    async def load_match_detail(self, match_id: Union[int, str]) -> Optional[dict[str, Any]]:
        try:
            normalized_id = int(match_id)
        except (ValueError, TypeError):
            return None
        db = self.db if self.db is not None else _get_db()
        try:
            doc = await db.jjc_match_detail.find_one({"match_id": normalized_id})
        except Exception as exc:
            logger.warning("读取 JJC 对局详情缓存失败: match_id={} error={}", match_id, exc)
            return None
        return doc

    async def save_match_detail(self, match_id: Union[int, str], payload: dict[str, Any]) -> None:
        try:
            normalized_id = int(match_id)
        except (ValueError, TypeError):
            return
        db = self.db if self.db is not None else _get_db()
        try:
            await db.jjc_match_detail.update_one(
                {"match_id": normalized_id},
                {"$set": {
                    "cached_at": payload.get("cached_at") or time.time(),
                    "data": payload.get("data") or payload,
                }},
                upsert=True,
            )
        except Exception as exc:
            logger.warning("保存 JJC 对局详情缓存失败: match_id={} error={}", match_id, exc)

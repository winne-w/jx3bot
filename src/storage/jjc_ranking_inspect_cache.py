from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional, Union
from urllib.parse import quote

from motor.motor_asyncio import AsyncIOMotorDatabase
from nonebot import logger

from src.infra.mongo import get_db as _get_db


@dataclass(frozen=True)
class JjcRankingInspectCacheRepo:
    base_dir: str
    db: Optional[AsyncIOMotorDatabase] = None

    def _match_detail_path(self, match_id: Union[int, str]) -> str:
        return os.path.join(self.base_dir, "match_detail", f"{int(match_id)}.json")

    @staticmethod
    def _load_json(file_path: str) -> Optional[dict[str, Any]]:
        try:
            with open(file_path, "r", encoding="utf-8") as file_handle:
                payload = json.load(file_handle)
        except FileNotFoundError:
            return None
        except Exception as exc:
            logger.warning("读取 JJC 下钻缓存失败: file={} error={}", file_path, exc)
            return None
        return payload if isinstance(payload, dict) else None

    async def load_role_recent(self, server: str, name: str, *, ttl_seconds: int) -> Optional[dict[str, Any]]:
        db = self.db if self.db is not None else _get_db()
        doc = await db.jjc_role_recent.find_one({"server": server, "name": name})
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
                    "cached_at": payload.get("cached_at", time.time()),
                    "data": payload.get("data", payload),
                }},
                upsert=True,
            )
        except Exception as exc:
            logger.warning("保存 JJC 角色近期缓存失败: server={} name={} error={}", server, name, exc)

    def load_match_detail(self, match_id: Union[int, str]) -> Optional[dict[str, Any]]:
        return self._load_json(self._match_detail_path(match_id))

    def save_match_detail(self, match_id: Union[int, str], payload: dict[str, Any]) -> None:
        file_path = self._match_detail_path(match_id)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        try:
            with open(file_path, "w", encoding="utf-8") as file_handle:
                json.dump(payload, file_handle, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("保存 JJC 对局详情缓存失败: file={} error={}", file_path, exc)

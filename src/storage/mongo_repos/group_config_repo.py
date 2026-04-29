from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from nonebot import logger

from src.infra.mongo import get_db as _get_db


@dataclass(frozen=True)
class GroupConfigRepo:
    db: Optional[AsyncIOMotorDatabase] = None

    async def load(self, path: Optional[str] = None) -> dict[str, dict[str, Any]]:
        """返回 {group_id: {config}} 格式，兼容旧 API。path 参数保留但不再使用。"""
        db = self.db if self.db is not None else _get_db()
        result: dict[str, dict[str, Any]] = {}
        try:
            docs = await db.group_configs.find().to_list(None)
            for doc in docs:
                doc.pop("_id", None)
                group_id = doc.pop("group_id", "")
                if group_id:
                    result[group_id] = doc
        except Exception as exc:
            logger.warning("加载群配置失败: {}", exc)
        return result

    async def save(self, data: dict[str, Any], path: Optional[str] = None) -> None:
        """保存全量群配置，兼容旧 API。path 参数保留但不再使用。"""
        db = self.db if self.db is not None else _get_db()
        try:
            for group_id, config in data.items():
                if not isinstance(config, dict):
                    continue
                doc = {"group_id": str(group_id), **config}
                await db.group_configs.update_one(
                    {"group_id": str(group_id)},
                    {"$set": doc},
                    upsert=True,
                )
        except Exception as exc:
            logger.warning("保存群配置失败: {}", exc)

    async def find_by_group(self, group_id: int | str) -> Optional[dict[str, Any]]:
        """查询单个群的配置，返回不含 _id/group_id 的 dict。"""
        db = self.db if self.db is not None else _get_db()
        try:
            doc = await db.group_configs.find_one({"group_id": str(group_id)})
            if doc:
                doc.pop("_id", None)
                doc.pop("group_id", None)
                return doc
        except Exception as exc:
            logger.warning("查询群配置失败: group_id={} error={}", group_id, exc)
        return None

    async def delete_group(self, group_id: int | str) -> bool:
        db = self.db if self.db is not None else _get_db()
        try:
            result = await db.group_configs.delete_one({"group_id": str(group_id)})
            return result.deleted_count > 0
        except Exception as exc:
            logger.warning("删除群配置失败: group_id={} error={}", group_id, exc)
            return False

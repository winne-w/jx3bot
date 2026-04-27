from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional, Union
from urllib.parse import quote

from nonebot import logger


@dataclass(frozen=True)
class JjcRankingInspectCacheRepo:
    base_dir: str

    def _role_recent_path(self, server: str, name: str) -> str:
        server_key = quote(str(server), safe="")
        name_key = quote(str(name), safe="")
        return os.path.join(self.base_dir, "role_recent", server_key, f"{name_key}.json")

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

    def load_role_recent(self, server: str, name: str, *, ttl_seconds: int) -> Optional[dict[str, Any]]:
        payload = self._load_json(self._role_recent_path(server, name))
        if not payload:
            return None
        cached_at = payload.get("cached_at")
        if not isinstance(cached_at, (int, float)):
            return None
        if time.time() - float(cached_at) > ttl_seconds:
            return None
        return payload

    def save_role_recent(self, server: str, name: str, payload: dict[str, Any]) -> None:
        file_path = self._role_recent_path(server, name)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        try:
            with open(file_path, "w", encoding="utf-8") as file_handle:
                json.dump(payload, file_handle, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("保存 JJC 角色近期缓存失败: file={} error={}", file_path, exc)

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

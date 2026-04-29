from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from src.infra.mongo import get_db as _get_db

try:
    from nonebot import logger  # type: ignore
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JjcCacheRepo:
    jjc_ranking_cache_duration: int
    kungfu_cache_duration: int
    db: Optional[AsyncIOMotorDatabase] = None

    # ---- helpers (lazy repo access to avoid circular imports) ----

    def _get_identity_repo(self):
        from src.storage.mongo_repos.role_identity_repo import RoleIdentityRepo
        return RoleIdentityRepo(db=self.db if self.db is not None else _get_db())

    def _get_jjc_cache_repo(self):
        from src.storage.mongo_repos.role_jjc_cache_repo import RoleJjcCacheRepo
        return RoleJjcCacheRepo(db=self.db if self.db is not None else _get_db())

    @staticmethod
    def _new_doc_to_compat(doc: dict[str, Any]) -> dict[str, Any]:
        """将 role_jjc_cache 文档转为 kungfu_cache 兼容结构，补充 cache_time。"""
        result = dict(doc)
        checked_at = result.get("checked_at")
        if isinstance(checked_at, datetime):
            result["cache_time"] = checked_at.timestamp()
        elif "cache_time" not in result:
            result["cache_time"] = 0.0
        return result

    def _check_freshness(
        self,
        cached_data: dict[str, Any],
        server: str,
        name: str,
        source: str = "",
    ) -> Optional[dict[str, Any]]:
        cache_time = cached_data.get("cache_time", 0)
        kungfu_value = cached_data.get("kungfu")
        weapon_checked = cached_data.get("weapon_checked", False)
        teammates_checked = cached_data.get("teammates_checked", False)
        teammates = cached_data.get("teammates")
        teammates_ok = (
            isinstance(teammates, list)
            and len(teammates) > 0
            and all(isinstance(item, dict) and item.get("kungfu_id") not in (None, "") for item in teammates)
        )

        if kungfu_value not in [None, ""]:
            current_time = time.time()
            cache_age = current_time - cache_time if cache_time else None
            cache_fresh = (
                cache_time
                and cache_age is not None
                and cache_age < self.kungfu_cache_duration
                and weapon_checked
                and teammates_checked
                and teammates_ok
            )
            if cache_fresh:
                logger.info(
                    "使用心法缓存{}: server={} name={} cache_time={}",
                    source, server, name, cache_time,
                )
                return cached_data

            reasons = []
            if not cache_time:
                reasons.append("missing_cache_time")
            elif cache_age is not None and cache_age >= self.kungfu_cache_duration:
                reasons.append("cache_time_expired")
            if not weapon_checked:
                reasons.append("weapon_not_checked")
            if not teammates_checked:
                reasons.append("teammates_not_checked")
            if not teammates_ok:
                reasons.append("teammates_kungfu_id_missing")
            cache_dt = datetime.fromtimestamp(cache_time).strftime("%Y-%m-%d %H:%M:%S") if cache_time else "未知"
            reason_text = ",".join(reasons) if reasons else "unknown"
            logger.info(
                "心法缓存不命中{}: server={} name={} cache_time={} reason={}",
                source, server, name, cache_dt, reason_text,
            )
        else:
            logger.info(
                "心法缓存不命中{}: server={} name={} reason=kungfu_empty",
                source, server, name,
            )

        return None

    # ---- 排行榜缓存 (不变) ----

    async def load_ranking_cache(self) -> Optional[dict[str, Any]]:
        db = self.db if self.db is not None else _get_db()
        try:
            doc = await db.jjc_ranking_cache.find_one({"cache_key": "ranking"})
        except Exception as exc:
            logger.warning("读取竞技场排行榜缓存失败: {}", exc)
            return None
        if doc is None:
            logger.info("竞技场排行榜缓存未命中 (MongoDB)")
            return None
        cache_time = doc.get("cache_time", 0)
        if time.time() - cache_time >= self.jjc_ranking_cache_duration:
            logger.info("竞技场排行榜缓存已过期 (MongoDB)")
            return None
        logger.info("使用 MongoDB 缓存的竞技场排行榜数据")
        return doc.get("data")

    async def save_ranking_cache(self, ranking_result: dict[str, Any]) -> None:
        db = self.db if self.db is not None else _get_db()
        try:
            await db.jjc_ranking_cache.update_one(
                {"cache_key": "ranking"},
                {"$set": {
                    "cache_time": ranking_result.get("cache_time") or time.time(),
                    "data": ranking_result,
                    "created_at": datetime.now(timezone.utc),
                }},
                upsert=True,
            )
            logger.info("竞技场排行榜数据已保存到 MongoDB 缓存")
        except Exception as exc:
            logger.warning("保存竞技场排行榜缓存失败: {}", exc)

    # ---- 心法/JJC 角色缓存 (灰度接入新集合) ----

    async def load_kungfu_cache_raw(self, server: str, name: str) -> Optional[dict[str, Any]]:
        # 优先从新集合 role_jjc_cache 按 server/name 读取
        try:
            jjc_repo = self._get_jjc_cache_repo()
            doc = await jjc_repo.load_by_best_identity(server=server, name=name)
            if doc is not None:
                return self._new_doc_to_compat(doc)
        except Exception as exc:
            logger.warning("从 role_jjc_cache 读取缓存失败，回退旧集合: {}", exc)

        # 回退旧 kungfu_cache
        db = self.db if self.db is not None else _get_db()
        doc = await db.kungfu_cache.find_one({"server": server, "name": name})
        if doc is None:
            return None
        return dict(doc)

    async def load_kungfu_cache(self, server: str, name: str) -> Optional[dict[str, Any]]:
        # 优先从新集合 role_jjc_cache 按 server/name 读取
        try:
            jjc_repo = self._get_jjc_cache_repo()
            doc = await jjc_repo.load_by_best_identity(server=server, name=name)
            if doc is not None:
                cached_data = self._new_doc_to_compat(doc)
                return self._check_freshness(cached_data, server, name, source="(新集合)")
        except Exception as exc:
            logger.warning("从 role_jjc_cache 读取缓存失败，回退旧集合: {}", exc)

        # 回退旧 kungfu_cache
        db = self.db if self.db is not None else _get_db()
        doc = await db.kungfu_cache.find_one({"server": server, "name": name})
        if doc is None:
            logger.info("心法缓存未命中: server={} name={} reason=cache_miss", server, name)
            return None

        cached_data = dict(doc)
        return self._check_freshness(cached_data, server, name, source="(旧集合)")

    async def save_kungfu_cache(self, server: str, name: str, result: dict[str, Any]) -> None:
        # 1) 写入新集合 role_identities + role_jjc_cache
        try:
            identity_repo = self._get_identity_repo()
            jjc_repo = self._get_jjc_cache_repo()

            zone = result.get("zone")
            game_role_id = result.get("game_role_id")
            global_role_id = result.get("global_role_id")
            role_id = result.get("role_id")

            identity = await identity_repo.upsert_from_indicator(
                server=server,
                name=name,
                zone=zone,
                game_role_id=game_role_id,
                global_role_id=global_role_id,
                role_id=role_id,
                cache_repo=jjc_repo,
            )
            identity_key = identity["identity_key"]

            cache_data: dict[str, Any] = {
                "server": server,
                "name": name,
                "source": "ranking",
            }
            _copy_if_present(result, cache_data, [
                "zone", "game_role_id", "role_id", "global_role_id",
                "kungfu", "kungfu_id", "kungfu_pinyin",
                "kungfu_indicator", "kungfu_match_history",
                "kungfu_selected_source",
                "weapon", "weapon_icon", "weapon_quality",
                "teammates",
            ])
            cache_data["weapon_checked"] = result.get("weapon_checked", False)
            cache_data["teammates_checked"] = result.get("teammates_checked", False)
            if "match_history_checked" in result:
                cache_data["match_history_checked"] = result["match_history_checked"]
            if "match_history_win_samples" in result:
                cache_data["match_history_win_samples"] = result["match_history_win_samples"]

            await jjc_repo.save(identity_key, cache_data)
            logger.info(
                "心法缓存已写入新集合: server={} name={} identity_key={}",
                server, name, identity_key,
            )
        except Exception as exc:
            logger.warning(
                "写入新集合 (role_identities / role_jjc_cache) 失败，继续旧集合 shadow write: {}",
                exc,
            )

        # 2) 旧 kungfu_cache shadow write (保留)
        db = self.db if self.db is not None else _get_db()
        try:
            await db.kungfu_cache.update_one(
                {"server": server, "name": name},
                {"$set": {**result, "cache_time": result.get("cache_time", time.time())}},
                upsert=True,
            )
            logger.info("心法信息已更新缓存到 MongoDB: server={} name={}", server, name)
        except Exception as exc:
            logger.warning("保存心法缓存失败: server={} name={} error={}", server, name, exc)


def _copy_if_present(src: dict[str, Any], dst: dict[str, Any], keys: list) -> None:
    for k in keys:
        v = src.get(k)
        if v is not None:
            dst[k] = v

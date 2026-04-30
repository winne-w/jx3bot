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

    async def resolve_role_identity(
        self,
        *,
        server: str,
        name: str,
        zone: Optional[str] = None,
        game_role_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        identity_repo = self._get_identity_repo()
        return await identity_repo.resolve_best_identity(
            server=server,
            name=name,
            zone=zone,
            game_role_id=game_role_id,
        )

    async def upsert_role_identity_from_indicator(
        self,
        *,
        server: str,
        name: str,
        zone: Optional[str],
        game_role_id: Optional[str],
        global_role_id: Optional[str],
        role_id: Optional[str],
    ) -> dict[str, Any]:
        identity_repo = self._get_identity_repo()
        jjc_repo = self._get_jjc_cache_repo()
        return await identity_repo.upsert_from_indicator(
            server=server,
            name=name,
            zone=zone,
            game_role_id=game_role_id,
            global_role_id=global_role_id,
            role_id=role_id,
            cache_repo=jjc_repo,
        )

    async def load_new_kungfu_cache_raw(self, server: str, name: str) -> Optional[dict[str, Any]]:
        jjc_repo = self._get_jjc_cache_repo()
        return await jjc_repo.load_by_best_identity(server=server, name=name)

    async def load_legacy_kungfu_cache_raw(self, server: str, name: str) -> Optional[dict[str, Any]]:
        db = self.db if self.db is not None else _get_db()
        doc = await db.kungfu_cache.find_one({"server": server, "name": name})
        if doc is None:
            return None
        return dict(doc)

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

    @staticmethod
    def _ensure_found_flag(cached_data: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not isinstance(cached_data, dict):
            return cached_data
        if "found" not in cached_data:
            cached_data["found"] = cached_data.get("kungfu") not in (None, "")
        return cached_data

    @staticmethod
    def _summarize_cache_doc(cached_data: Optional[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(cached_data, dict):
            return {}
        teammates = cached_data.get("teammates")
        teammate_kungfu_missing = 0
        if isinstance(teammates, list):
            teammate_kungfu_missing = sum(
                1
                for item in teammates
                if not isinstance(item, dict) or item.get("kungfu_id") in (None, "")
            )
        return {
            "identity_key": cached_data.get("identity_key"),
            "global_role_id": cached_data.get("global_role_id"),
            "game_role_id": cached_data.get("game_role_id"),
            "role_id": cached_data.get("role_id"),
            "zone": cached_data.get("zone"),
            "kungfu": cached_data.get("kungfu"),
            "kungfu_id": cached_data.get("kungfu_id"),
            "kungfu_indicator": cached_data.get("kungfu_indicator"),
            "kungfu_match_history": cached_data.get("kungfu_match_history"),
            "kungfu_selected_source": cached_data.get("kungfu_selected_source"),
            "weapon_checked": cached_data.get("weapon_checked"),
            "teammates_checked": cached_data.get("teammates_checked"),
            "match_history_checked": cached_data.get("match_history_checked"),
            "teammates_count": len(teammates) if isinstance(teammates, list) else None,
            "teammates_missing_kungfu_id_count": teammate_kungfu_missing,
            "cache_time": cached_data.get("cache_time"),
            "checked_at": cached_data.get("checked_at"),
        }

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
                    "使用心法缓存{}: server={} name={} cache_time={} cache_age={} summary={}",
                    source,
                    server,
                    name,
                    cache_time,
                    round(cache_age, 1) if cache_age is not None else None,
                    self._summarize_cache_doc(cached_data),
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
                "心法缓存不命中{}: server={} name={} cache_time={} cache_age={} reason={} summary={}",
                source,
                server,
                name,
                cache_dt,
                round(cache_age, 1) if cache_age is not None else None,
                reason_text,
                self._summarize_cache_doc(cached_data),
            )
        else:
            logger.info(
                "心法缓存不命中{}: server={} name={} reason=kungfu_empty summary={}",
                source,
                server,
                name,
                self._summarize_cache_doc(cached_data),
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
            doc = await self.load_new_kungfu_cache_raw(server, name)
            if doc is not None:
                compat_doc = self._ensure_found_flag(self._new_doc_to_compat(doc))
                logger.info(
                    "读取心法原始缓存命中(新集合): server={} name={} summary={}",
                    server,
                    name,
                    self._summarize_cache_doc(compat_doc),
                )
                return compat_doc
        except Exception as exc:
            logger.warning("从 role_jjc_cache 读取缓存失败，回退旧集合: {}", exc)

        # 回退旧 kungfu_cache
        doc = await self.load_legacy_kungfu_cache_raw(server, name)
        if doc is None:
            return None
        self._ensure_found_flag(doc)
        logger.info(
            "读取心法原始缓存命中(旧集合): server={} name={} summary={}",
            server,
            name,
            self._summarize_cache_doc(doc),
        )
        return doc

    async def load_kungfu_cache(self, server: str, name: str) -> Optional[dict[str, Any]]:
        # 优先从新集合 role_jjc_cache 按 server/name 读取
        try:
            doc = await self.load_new_kungfu_cache_raw(server, name)
            if doc is not None:
                cached_data = self._ensure_found_flag(self._new_doc_to_compat(doc))
                if "found" not in doc:
                    logger.debug(
                        "新集合缓存缺少 found 字段，已按 kungfu 自动补齐: server={} name={} kungfu={} found={}",
                        server,
                        name,
                        cached_data.get("kungfu"),
                        cached_data.get("found"),
                    )
                result = self._check_freshness(cached_data, server, name, source="(新集合)")
                if result is None:
                    logger.info(
                        "新集合缓存未通过 freshness 校验，准备回退旧集合: server={} name={}",
                        server,
                        name,
                    )
                return result
        except Exception as exc:
            logger.warning("从 role_jjc_cache 读取缓存失败，回退旧集合: {}", exc)

        # 回退旧 kungfu_cache
        doc = await self.load_legacy_kungfu_cache_raw(server, name)
        if doc is None:
            logger.info("心法缓存未命中: server={} name={} reason=cache_miss", server, name)
            return None

        cached_data = self._ensure_found_flag(doc)
        return self._check_freshness(cached_data, server, name, source="(旧集合)")

    async def save_kungfu_cache(self, server: str, name: str, result: dict[str, Any]) -> None:
        # 1) 写入新集合 role_identities + role_jjc_cache
        try:
            jjc_repo = self._get_jjc_cache_repo()

            zone = result.get("zone")
            game_role_id = result.get("game_role_id")
            global_role_id = result.get("global_role_id")
            role_id = result.get("role_id")

            identity = await self.upsert_role_identity_from_indicator(
                server=server,
                name=name,
                zone=zone,
                game_role_id=game_role_id,
                global_role_id=global_role_id,
                role_id=role_id,
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
            cache_data["found"] = result.get("found", result.get("kungfu") not in (None, ""))
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

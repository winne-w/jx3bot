from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from motor.motor_asyncio import AsyncIOMotorDatabase
from nonebot import logger
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from src.infra.mongo import get_db as _get_db


@dataclass(frozen=True)
class JjcSyncRepo:
    """JJC 对局数据同步的 MongoDB 仓储层。

    维护角色同步队列 (jjc_sync_role_queue) 和对局 seen 集合 (jjc_sync_match_seen)，
    不包含同步编排逻辑。
    """

    db: Optional[AsyncIOMotorDatabase] = None

    # ---- internal helpers ----

    def _db(self) -> AsyncIOMotorDatabase:
        return self.db if self.db is not None else _get_db()

    @staticmethod
    def _build_identity_key(
        global_role_id: Optional[str] = None,
        zone: Optional[str] = None,
        role_id: Optional[str] = None,
        normalized_server: Optional[str] = None,
        normalized_name: Optional[str] = None,
    ) -> str:
        """按优先级构建 identity_key。

        优先级：global:{global_role_id} > game:{zone}:{role_id} > name:{normalized_server}:{normalized_name}
        """
        gid = (global_role_id or "").strip()
        if gid:
            return f"global:{gid}"

        z = (zone or "").strip()
        rid = (role_id or "").strip()
        if z and rid:
            return f"game:{z}:{rid}"

        ns = (normalized_server or "").strip()
        nn = (normalized_name or "").strip()
        return f"name:{ns}:{nn}"

    @staticmethod
    def _coerce_int(value: object) -> Optional[int]:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except (ValueError, TypeError):
                return None
        return None

    # ---- 角色队列操作 ----

    async def upsert_role(
        self,
        server: str,
        name: str,
        normalized_server: str,
        normalized_name: str,
        global_role_id: Optional[str] = None,
        role_id: Optional[str] = None,
        person_id: Optional[str] = None,
        zone: Optional[str] = None,
        source: str = 'manual',
        priority: int = 0,
        season_id: Optional[str] = None,
        season_start_time: int = 0,
    ) -> str:
        """将角色加入同步队列，已存在时更新身份字段但**不重置**同步水位。

        - 已存在角色：更新身份字段、来源（仅 manual 覆盖）、优先级（不降低），
          不重置 full_synced_until_time、oldest_synced_match_time、history_exhausted。
        - 新角色：设置 status='pending'、created_at 等默认字段。
        """
        db = self._db()
        identity_key = self._build_identity_key(
            global_role_id=global_role_id,
            zone=zone,
            role_id=role_id,
            normalized_server=normalized_server,
            normalized_name=normalized_name,
        )
        now = time.time()

        existing = await db.jjc_sync_role_queue.find_one({"identity_key": identity_key})

        if existing:
            # 已有角色：更新身份字段，不重置同步水位
            set_fields: Dict[str, Any] = {
                "server": server,
                "name": name,
                "normalized_server": normalized_server,
                "normalized_name": normalized_name,
                "updated_at": now,
            }

            # 可选字段：仅在有值时更新
            if zone is not None:
                set_fields["zone"] = zone
            if role_id is not None:
                set_fields["role_id"] = role_id
            if person_id is not None:
                set_fields["person_id"] = person_id
            if global_role_id is not None:
                set_fields["global_role_id"] = global_role_id
            if season_id is not None:
                set_fields["season_id"] = season_id
            set_fields["season_start_time"] = season_start_time

            # 来源：仅 manual 覆盖
            if source == 'manual':
                set_fields["source"] = 'manual'

            update_op: Dict[str, Any] = {
                "$set": set_fields,
                "$max": {"priority": priority},
            }

            try:
                await db.jjc_sync_role_queue.update_one(
                    {"identity_key": identity_key},
                    update_op,
                )
                return identity_key
            except Exception as exc:
                logger.warning(
                    "更新同步队列角色失败: identity_key={} error={}",
                    identity_key, exc,
                )
        else:
            # 新角色
            doc: Dict[str, Any] = {
                "identity_key": identity_key,
                "server": server,
                "name": name,
                "normalized_server": normalized_server,
                "normalized_name": normalized_name,
                "source": source,
                "priority": priority,
                "season_start_time": season_start_time or 0,
                "status": "pending",
                "next_sync_after": None,
                "fail_count": 0,
                "last_cursor": 0,
                "created_at": now,
                "updated_at": now,
            }

            # 仅写入有实际值的可选字段
            if zone is not None:
                doc["zone"] = zone
            if role_id is not None:
                doc["role_id"] = role_id
            if person_id is not None:
                doc["person_id"] = person_id
            if global_role_id is not None:
                doc["global_role_id"] = global_role_id
            if season_id is not None:
                doc["season_id"] = season_id

            try:
                await db.jjc_sync_role_queue.insert_one(doc)
                return identity_key
            except DuplicateKeyError:
                # 并发写入，已有记录则转为更新
                set_fields = {
                    "server": server,
                    "name": name,
                    "normalized_server": normalized_server,
                    "normalized_name": normalized_name,
                    "updated_at": now,
                }
                if zone is not None:
                    set_fields["zone"] = zone
                if role_id is not None:
                    set_fields["role_id"] = role_id
                if person_id is not None:
                    set_fields["person_id"] = person_id
                if global_role_id is not None:
                    set_fields["global_role_id"] = global_role_id
                if season_id is not None:
                    set_fields["season_id"] = season_id
                set_fields["season_start_time"] = season_start_time

                # 来源：仅 manual 覆盖
                if source == 'manual':
                    set_fields["source"] = 'manual'

                update_op = {
                    "$set": set_fields,
                    "$max": {"priority": priority},
                }

                try:
                    await db.jjc_sync_role_queue.update_one(
                        {"identity_key": identity_key},
                        update_op,
                    )
                    return identity_key
                except Exception as exc:
                    logger.warning(
                        "并发写入后更新同步队列角色失败: identity_key={} error={}",
                        identity_key, exc,
                    )

    async def claim_next_roles(
        self,
        limit: int = 3,
        lease_owner: str = 'default',
        lease_seconds: int = 600,
    ) -> List[Dict[str, Any]]:
        """原子领取可执行角色，按 priority 降序排序。

        查找 pending/cooldown/exhausted 且 next_sync_after <= now（或 None）的角色，
        逐个原子更新为 status='syncing'，设置租约信息。
        返回成功领取的角色列表。
        """
        db = self._db()
        now = time.time()
        claimed: List[Dict[str, Any]] = []

        for _ in range(limit):
            doc = await db.jjc_sync_role_queue.find_one_and_update(
                filter={
                    "status": {"$in": ["pending", "cooldown", "exhausted"]},
                    "$or": [
                        {"next_sync_after": None},
                        {"next_sync_after": {"$lte": now}},
                    ],
                },
                update={"$set": {
                    "status": "syncing",
                    "lease_owner": lease_owner,
                    "lease_expires_at": now + lease_seconds,
                }},
                sort=[("priority", -1)],
                return_document=ReturnDocument.AFTER,
            )
            if doc is None:
                break
            claimed.append(doc)

        return claimed

    async def claim_specific_role(
        self,
        identity_key: str,
        lease_owner: str = 'default',
        lease_seconds: int = 600,
    ) -> Optional[Dict[str, Any]]:
        """原子领取指定角色。

        仅当角色处于 pending/cooldown/exhausted（且 next_sync_after <= now）时领取成功，
        返回更新后的文档；否则返回 None。
        """
        db = self._db()
        now = time.time()
        return await db.jjc_sync_role_queue.find_one_and_update(
            filter={
                "identity_key": identity_key,
                "status": {"$in": ["pending", "cooldown", "exhausted"]},
                "$or": [
                    {"next_sync_after": None},
                    {"next_sync_after": {"$lte": now}},
                ],
            },
            update={"$set": {
                "status": "syncing",
                "lease_owner": lease_owner,
                "lease_expires_at": now + lease_seconds,
            }},
            return_document=ReturnDocument.AFTER,
        )

    async def release_role_success(
        self,
        identity_key: str,
        full_synced_until_time: Optional[int] = None,
        oldest_synced_match_time: Optional[int] = None,
        latest_seen_match_time: Optional[int] = None,
        history_exhausted: Optional[bool] = None,
        season_id: Optional[str] = None,
        last_cursor: int = 0,
    ) -> None:
        """释放角色（同步成功）。

        如果 history_exhausted=True: status='exhausted', next_sync_after=now+6h
        否则: status='cooldown', next_sync_after=now+1h
        清除租约，重置 fail_count/error，更新水位字段。
        """
        db = self._db()
        now = time.time()

        set_fields: Dict[str, Any] = {
            "status": "exhausted" if history_exhausted else "cooldown",
            "next_sync_after": now + (21600 if history_exhausted else 3600),
            "last_synced_at": now,
            "fail_count": 0,
            "last_error": None,
            "last_cursor": last_cursor,
            "lease_owner": None,
            "lease_expires_at": None,
            "updated_at": now,
        }

        if full_synced_until_time is not None:
            set_fields["full_synced_until_time"] = full_synced_until_time
        if oldest_synced_match_time is not None:
            set_fields["oldest_synced_match_time"] = oldest_synced_match_time
        if latest_seen_match_time is not None:
            set_fields["latest_seen_match_time"] = latest_seen_match_time
        if season_id is not None:
            set_fields["season_id"] = season_id
        if history_exhausted is not None:
            set_fields["history_exhausted"] = history_exhausted

        try:
            await db.jjc_sync_role_queue.update_one(
                {"identity_key": identity_key},
                {"$set": set_fields},
            )
        except Exception as exc:
            logger.warning(
                "释放同步角色(成功)失败: identity_key={} error={}",
                identity_key, exc,
            )

    async def release_role_failure(
        self,
        identity_key: str,
        error_message: str = '',
    ) -> None:
        """释放角色（同步失败）。

        累加 fail_count。fail_count >= 3 时状态变为 failed，next_sync_after=now+30min，
        否则恢复为 pending。清除租约，记录错误信息。
        """
        db = self._db()
        now = time.time()

        existing = await db.jjc_sync_role_queue.find_one(
            {"identity_key": identity_key},
            {"fail_count": 1},
        )
        current_fail_count: int = 0
        if existing is not None:
            current_fail_count = existing.get("fail_count", 0) or 0

        new_fail_count = current_fail_count + 1

        if new_fail_count >= 3:
            new_status = "failed"
            next_sync = now + 1800  # 30 分钟
        else:
            new_status = "pending"
            next_sync = None

        try:
            await db.jjc_sync_role_queue.update_one(
                {"identity_key": identity_key},
                {"$set": {
                    "status": new_status,
                    "next_sync_after": next_sync,
                    "fail_count": new_fail_count,
                    "last_error": error_message,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "updated_at": now,
                }},
            )
        except Exception as exc:
            logger.warning(
                "释放同步角色(失败)失败: identity_key={} error={}",
                identity_key, exc,
            )

    async def update_role_identity_fields(
        self,
        identity_key: str,
        global_role_id: Optional[str] = None,
        role_id: Optional[str] = None,
        person_id: Optional[str] = None,
        zone: Optional[str] = None,
        identity_source: Optional[str] = None,
    ) -> bool:
        """补充同步队列角色的外部身份字段，不改变同步水位或 identity_key。"""
        db = self._db()
        now = time.time()
        set_fields: Dict[str, Any] = {"updated_at": now}

        if global_role_id:
            set_fields["global_role_id"] = global_role_id
        if role_id:
            set_fields["role_id"] = role_id
        if person_id:
            set_fields["person_id"] = person_id
        if zone:
            set_fields["zone"] = zone
        if identity_source:
            set_fields["identity_source"] = identity_source

        if len(set_fields) == 1:
            return False

        try:
            result = await db.jjc_sync_role_queue.update_one(
                {"identity_key": identity_key},
                {"$set": set_fields},
            )
            return result.matched_count > 0
        except Exception as exc:
            logger.warning(
                "补充同步角色身份字段失败: identity_key={} error={}",
                identity_key, exc,
            )
            return False

    async def reset_role_progress(self, identity_key: str) -> bool:
        """重置角色同步进度。

        将指定角色 status 设为 pending，清空同步水位字段、租约信息和错误信息，
        fail_count 和 last_cursor 归零。
        成功返回 True。
        """
        db = self._db()
        now = time.time()

        try:
            result = await db.jjc_sync_role_queue.update_one(
                {"identity_key": identity_key},
                {"$set": {
                    "status": "pending",
                    "full_synced_until_time": None,
                    "oldest_synced_match_time": None,
                    "latest_seen_match_time": None,
                    "history_exhausted": None,
                    "last_error": None,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "fail_count": 0,
                    "last_cursor": 0,
                    "next_sync_after": None,
                    "updated_at": now,
                }},
            )
            return result.matched_count > 0
        except Exception as exc:
            logger.warning(
                "重置角色同步进度失败: identity_key={} error={}",
                identity_key, exc,
            )
            return False

    async def recover_expired_leases(self) -> int:
        """恢复过期的角色租约和 match_detail 租约。

        - 角色：status='syncing' 且 lease_expires_at < now → status='pending'，清除租约
        - 对局：status='detail_syncing' 且 lease_expires_at < now → status='discovered'，清除租约
        返回恢复的文档总数。
        """
        db = self._db()
        now = time.time()
        total_recovered = 0

        # 恢复超时角色租约
        try:
            role_result = await db.jjc_sync_role_queue.update_many(
                filter={
                    "status": "syncing",
                    "lease_expires_at": {"$lt": now},
                },
                update={"$set": {
                    "status": "pending",
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "updated_at": now,
                }},
            )
            total_recovered += role_result.modified_count
        except Exception as exc:
            logger.warning("恢复角色过期租约失败: error={}", exc)

        # 恢复超时对局 detail 租约
        try:
            match_result = await db.jjc_sync_match_seen.update_many(
                filter={
                    "status": "detail_syncing",
                    "lease_expires_at": {"$lt": now},
                },
                update={"$set": {
                    "status": "discovered",
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "updated_at": now,
                }},
            )
            total_recovered += match_result.modified_count
        except Exception as exc:
            logger.warning("恢复对局过期租约失败: error={}", exc)

        return total_recovered

    # ---- 对局 seen 操作 ----

    async def mark_match_discovered(
        self,
        match_id: Union[int, str],
        match_time: Optional[int] = None,
        source_identity_key: Optional[str] = None,
        source_server: Optional[str] = None,
        source_role_name: Optional[str] = None,
    ) -> bool:
        """标记对局为已发现（jjc_sync_match_seen）。

        幂等写入：已存在的对局不做任何更新。
        成功写入返回 True，match_id 无法转为 int 或写入异常时返回 False。
        """
        _match_id = self._coerce_int(match_id)
        if _match_id is None:
            return False

        db = self._db()
        now = time.time()

        try:
            result = await db.jjc_sync_match_seen.update_one(
                {"match_id": _match_id},
                {"$setOnInsert": {
                    "match_id": _match_id,
                    "match_time": match_time,
                    "source_identity_key": source_identity_key,
                    "source_server": source_server,
                    "source_role_name": source_role_name,
                    "status": "discovered",
                    "discovered_at": now,
                    "fail_count": 0,
                    "last_error": None,
                    "updated_at": now,
                }},
                upsert=True,
            )
            return getattr(result, "upserted_id", None) is not None
        except Exception as exc:
            logger.warning(
                "标记对局已发现失败: match_id={} error={}",
                _match_id, exc,
            )
            return False

    async def claim_match_detail(
        self,
        match_id: Union[int, str],
        lease_owner: str = 'default',
        lease_seconds: int = 600,
    ) -> Optional[Dict[str, Any]]:
        """原子领取一个 discovered 对局用于同步详情。

        查找 status='discovered' 或上一轮失败的对局，更新为 status='detail_syncing'。
        返回成功领取的 match 文档，match_id 无法转为 int 或无可用对局时返回 None。
        """
        _match_id = self._coerce_int(match_id)
        if _match_id is None:
            return None

        db = self._db()
        now = time.time()

        doc = await db.jjc_sync_match_seen.find_one_and_update(
            filter={
                "match_id": _match_id,
                "$or": [
                    {"status": "discovered"},
                    {
                        "status": "failed",
                        "$or": [
                            {"detail_retry_after": None},
                            {"detail_retry_after": {"$lte": now}},
                        ],
                    },
                ],
            },
            update={"$set": {
                "status": "detail_syncing",
                "lease_owner": lease_owner,
                "lease_expires_at": now + lease_seconds,
                "updated_at": now,
            }},
            return_document=ReturnDocument.AFTER,
        )

        return doc

    async def mark_match_detail_saved(
        self,
        match_id: Union[int, str],
    ) -> bool:
        """标记对局详情已保存。

        更新 status='detail_saved', detail_saved_at=now，
        清除租约，重置 fail_count。
        成功写入返回 True，match_id 无法转为 int 或写入异常时返回 False。
        """
        _match_id = self._coerce_int(match_id)
        if _match_id is None:
            return False

        db = self._db()
        now = time.time()

        try:
            await db.jjc_sync_match_seen.update_one(
                {"match_id": _match_id},
                {"$set": {
                    "status": "detail_saved",
                    "detail_saved_at": now,
                    "fail_count": 0,
                    "last_error": None,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "updated_at": now,
                }},
            )
            return True
        except Exception as exc:
            logger.warning(
                "标记对局详情已保存失败: match_id={} error={}",
                _match_id, exc,
            )
            return False

    async def mark_match_detail_unavailable(
        self,
        match_id: Union[int, str],
        reason: str = '',
        code: Union[int, str] = 0,
    ) -> bool:
        """标记对局详情不可用（如接口返回 code!=0 的确定性不可用）。

        更新 status='detail_unavailable'，写入不可用原因和代码，
        清除租约和重试字段。
        成功写入返回 True，match_id 无法转为 int 或写入异常时返回 False。
        """
        _match_id = self._coerce_int(match_id)
        if _match_id is None:
            return False

        _code = self._coerce_int(code)
        db = self._db()
        now = time.time()

        try:
            await db.jjc_sync_match_seen.update_one(
                {"match_id": _match_id},
                {"$set": {
                    "status": "detail_unavailable",
                    "detail_unavailable_reason": reason,
                    "detail_unavailable_code": _code,
                    "detail_unavailable_at": now,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "detail_retry_after": None,
                    "updated_at": now,
                }},
            )
            return True
        except Exception as exc:
            logger.warning(
                "标记对局详情不可用失败: match_id={} error={}",
                _match_id, exc,
            )
            return False

    async def mark_match_detail_failed(
        self,
        match_id: Union[int, str],
        error_message: str = '',
    ) -> bool:
        """标记对局详情同步失败。

        更新 status='failed'，累加 fail_count，按递增退避策略设置 detail_retry_after：
        fail_count=1 → 5min, 2 → 30min, 3 → 2h, >=4 → 6h（封顶）。
        清除租约。
        成功写入返回 True，match_id 无法转为 int 或写入异常时返回 False。
        """
        _match_id = self._coerce_int(match_id)
        if _match_id is None:
            return False

        db = self._db()
        now = time.time()

        existing = await db.jjc_sync_match_seen.find_one(
            {"match_id": _match_id},
            {"fail_count": 1},
        )
        current_fail_count: int = 0
        if existing is not None:
            current_fail_count = existing.get("fail_count", 0) or 0

        new_fail_count = current_fail_count + 1

        # 递增退避：1=5min, 2=30min, 3=2h, 4+=6h（封顶）
        if new_fail_count <= 1:
            retry_delay = 300
        elif new_fail_count == 2:
            retry_delay = 1800
        elif new_fail_count == 3:
            retry_delay = 7200
        else:
            retry_delay = 21600

        try:
            await db.jjc_sync_match_seen.update_one(
                {"match_id": _match_id},
                {"$set": {
                    "status": "failed",
                    "fail_count": new_fail_count,
                    "last_error": error_message,
                    "detail_retry_after": now + retry_delay,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "updated_at": now,
                }},
            )
            return True
        except Exception as exc:
            logger.warning(
                "标记对局详情失败: match_id={} error={}",
                _match_id, exc,
            )
            return False

    # ---- 查询操作 ----

    async def count_by_status(self) -> Dict[str, int]:
        """按 status 分组统计角色队列数量。"""
        db = self._db()
        result: Dict[str, int] = {}

        try:
            pipeline = [
                {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            ]
            cursor = db.jjc_sync_role_queue.aggregate(pipeline)
            async for doc in cursor:
                status_key: str = doc.get("_id") or "unknown"
                result[status_key] = doc.get("count", 0)
        except Exception as exc:
            logger.warning("统计同步队列状态失败: error={}", exc)

        return result

    async def get_recent_errors(self, limit: int = 10) -> List[Dict[str, Any]]:
        """返回最近有 last_error 的角色列表，按 updated_at 降序排列。"""
        db = self._db()
        docs: List[Dict[str, Any]] = []

        try:
            cursor = (
                db.jjc_sync_role_queue
                .find(
                    {"last_error": {"$exists": True, "$nin": [None, ""]}},
                )
                .sort("updated_at", -1)
                .limit(limit)
            )
            async for doc in cursor:
                docs.append(doc)
        except Exception as exc:
            logger.warning("查询同步队列最近错误失败: error={}", exc)

        return docs

    async def get_role_by_name(
        self,
        normalized_server: str,
        normalized_name: str,
    ) -> Optional[Dict[str, Any]]:
        """按规范化服务器和角色名查询同步队列角色。"""
        db = self._db()
        try:
            return await db.jjc_sync_role_queue.find_one(
                {
                    "normalized_server": normalized_server,
                    "normalized_name": normalized_name,
                }
            )
        except Exception as exc:
            logger.warning(
                "查询同步队列角色失败: server={} name={} error={}",
                normalized_server, normalized_name, exc,
            )
            return None

    # ---- 全局状态操作 ----

    async def set_paused(self, paused: bool, reason: str = '') -> bool:
        """设置全局暂停状态。

        upsert jjc_sync_state key='global'，写入 paused/reason/updated_at。
        成功返回 True。
        """
        db = self._db()
        now = time.time()

        try:
            await db.jjc_sync_state.update_one(
                {"key": "global"},
                {"$set": {
                    "paused": paused,
                    "reason": reason,
                    "updated_at": now,
                }},
                upsert=True,
            )
            return True
        except Exception as exc:
            logger.warning("设置全局暂停状态失败: paused={} error={}", paused, exc)
            return False

    async def get_paused(self) -> bool:
        """读取全局暂停状态。

        读取 jjc_sync_state key='global' 的 paused 字段，
        异常或不存在时返回 False。
        """
        db = self._db()

        try:
            doc = await db.jjc_sync_state.find_one({"key": "global"})
            if doc is None:
                return False
            return bool(doc.get("paused", False))
        except Exception as exc:
            logger.warning("读取全局暂停状态失败: error={}", exc)
            return False

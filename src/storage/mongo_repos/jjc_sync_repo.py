from __future__ import annotations

import time
from dataclasses import dataclass
from re import escape as escape_regex
from typing import Any, Dict, List, Optional, Union

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from nonebot import logger
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from src.infra.mongo import get_db as _get_db
from src.services.jx3.role_identity_matching import (
    build_guarded_profile_set_fields,
    build_identity_key as _build_role_identity_key,
    coerce_match_time,
    legacy_identity_keys,
    should_overwrite_profile_fields,
)


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

    def _queue_col(self) -> Any:
        """Return the active role sync queue collection.

        Production uses the identity-id queue. The fallback keeps focused tests
        and migration-time fakes that only expose the legacy collection usable.
        """
        db = self._db()
        if hasattr(db, "jjc_sync_identity_queue"):
            return db.jjc_sync_identity_queue
        return db.jjc_sync_role_queue

    @staticmethod
    def _coerce_object_id(value: Any) -> Optional[ObjectId]:
        if isinstance(value, ObjectId):
            return value
        if isinstance(value, str) and ObjectId.is_valid(value):
            return ObjectId(value)
        return None

    @staticmethod
    def _build_identity_key(
        global_role_id: Optional[str] = None,
        zone: Optional[str] = None,
        role_id: Optional[str] = None,
        normalized_server: Optional[str] = None,
        normalized_name: Optional[str] = None,
        global_id: Optional[str] = None,
    ) -> str:
        """按优先级构建 identity_key。

        优先级：global_id:{global_id} > global:{global_role_id} > game:{zone}:{role_id} > name:{normalized_server}:{normalized_name}
        """
        key, _ = _build_role_identity_key(
            global_id=global_id,
            global_role_id=global_role_id,
            zone=zone,
            game_role_id=role_id,
            server=normalized_server,
            name=normalized_name,
        )
        return key

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

    @classmethod
    def _priority_at_least(cls, doc: Optional[Dict[str, Any]], priority: int) -> bool:
        if not doc:
            return False
        current_priority = cls._coerce_int(doc.get("priority"))
        return current_priority is not None and current_priority >= priority

    @staticmethod
    def _profile_update_fields(
        existing: Dict[str, Any],
        incoming: Dict[str, Any],
        source: Optional[str],
        now: float,
        observed_match_time: Optional[int] = None,
    ) -> Dict[str, Any]:
        observed = coerce_match_time(observed_match_time)
        set_fields = build_guarded_profile_set_fields(
            existing,
            incoming,
            observed_match_time=observed,
            force_profile_update=False,
        )
        if should_overwrite_profile_fields(existing, observed_match_time=observed) and observed is not None:
            set_fields["role_info_observed_match_time"] = observed
            if source:
                set_fields["role_info_source"] = source
            set_fields["role_info_updated_at"] = now
        return set_fields

    # ---- 角色队列操作 ----

    @staticmethod
    def _leased_role_filter(
        identity_key: str,
        lease_owner: Optional[str] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        filter_doc: Dict[str, Any] = {"identity_key": identity_key}
        if lease_owner is not None:
            filter_doc["status"] = "syncing"
            filter_doc["lease_owner"] = lease_owner
            if now is not None:
                filter_doc["lease_expires_at"] = {"$gt": now}
        return filter_doc

    @staticmethod
    def _leased_identity_filter(
        identity_id: ObjectId,
        lease_owner: Optional[str] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        filter_doc: Dict[str, Any] = {"identity_id": identity_id}
        if lease_owner is not None:
            filter_doc["status"] = "syncing"
            filter_doc["lease_owner"] = lease_owner
            if now is not None:
                filter_doc["lease_expires_at"] = {"$gt": now}
        return filter_doc

    async def _resolve_identity_id_by_key(self, identity_key: str) -> Optional[ObjectId]:
        """Best-effort migration helper for legacy identity_key callers."""
        try:
            queue_doc = await self._queue_col().find_one(
                {"identity_key": identity_key},
                {"identity_id": 1},
            )
        except Exception:
            queue_doc = None
        if queue_doc:
            identity_id = self._coerce_object_id(queue_doc.get("identity_id"))
            if identity_id is not None:
                return identity_id

        db = self._db()
        try:
            identity_doc = await db.role_identities.find_one(
                {"identity_key": identity_key},
                {"_id": 1},
            )
        except Exception:
            return None
        if not identity_doc:
            return None
        return self._coerce_object_id(identity_doc.get("_id"))

    @staticmethod
    def _leased_match_detail_filter(
        match_id: int,
        lease_owner: Optional[str] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        filter_doc: Dict[str, Any] = {"match_id": match_id}
        if lease_owner is not None:
            filter_doc["status"] = "detail_syncing"
            filter_doc["lease_owner"] = lease_owner
            if now is not None:
                filter_doc["lease_expires_at"] = {"$gt": now}
        return filter_doc

    async def _update_existing_role_from_upsert(
        self,
        existing: Dict[str, Any],
        existing_key: str,
        identity_key: str,
        legacy_keys: List[str],
        *,
        server: str,
        name: str,
        normalized_server: str,
        normalized_name: str,
        global_role_id: Optional[str],
        role_id: Optional[str],
        person_id: Optional[str],
        zone: Optional[str],
        source: str,
        priority: int,
        season_id: Optional[str],
        season_start_time: int,
        global_id: Optional[str],
        observed_match_time: Optional[int],
        now: float,
    ) -> str:
        """Update an existing queue role without touching syncing non-owner rows."""
        db = self._db()
        existing_status = str(existing.get("status") or "")
        if existing_status == "syncing":
            logger.info(
                "同步队列角色正在同步，跳过非租约 upsert 写入: identity_key={} new_key={}".format(
                    existing_key,
                    identity_key,
                )
            )
            return existing_key

        set_fields: Dict[str, Any] = {"updated_at": now}
        set_fields.update(self._profile_update_fields(
            existing,
            {
                "server": server,
                "name": name,
                "normalized_server": normalized_server,
                "normalized_name": normalized_name,
                "zone": zone,
                "role_id": role_id,
                "game_role_id": role_id,
                "global_role_id": global_role_id,
                "person_id": person_id,
            },
            source,
            now,
            observed_match_time=observed_match_time,
        ))
        existing_global_id = str(existing.get("global_id") or "").strip()
        incoming_global_id = str(global_id or "").strip()
        if existing_global_id and incoming_global_id and existing_global_id != incoming_global_id:
            logger.warning(
                "同步队列 global_id 冲突，跳过角色 upsert: identity_key={} existing_global_id={} incoming_global_id={}".format(
                    existing_key,
                    existing_global_id,
                    incoming_global_id,
                )
            )
            return existing_key
        if global_id is not None and (not existing_global_id or existing_global_id == global_id):
            set_fields["global_id"] = global_id
        if season_id is not None:
            set_fields["season_id"] = season_id
        set_fields["season_start_time"] = season_start_time
        if source == 'manual':
            set_fields["source"] = 'manual'

        migrate_identity_key = existing_key != identity_key
        if migrate_identity_key:
            set_fields["identity_key"] = identity_key

        update_op: Dict[str, Any] = {
            "$set": set_fields,
            "$max": {"priority": priority},
        }
        if migrate_identity_key:
            aliases = list(legacy_keys)
            aliases.append(existing_key)
            update_op["$addToSet"] = {"aliases": {"$each": sorted(set(aliases))}}

        try:
            update_result = await self._queue_col().update_one(
                {"identity_key": existing_key, "status": {"$ne": "syncing"}},
                update_op,
            )
        except Exception as exc:
            logger.warning(
                "更新同步队列角色失败: identity_key={} error={}",
                identity_key, exc,
            )
            return existing_key

        if update_result.matched_count <= 0:
            logger.info(
                "同步队列角色 upsert 时租约状态变化，跳过非租约写入: existing_key={} new_key={}".format(
                    existing_key,
                    identity_key,
                )
            )
            return existing_key
        return identity_key if migrate_identity_key else existing_key

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
        global_id: Optional[str] = None,
        observed_match_time: Optional[int] = None,
    ) -> str:
        """将角色加入同步队列，已存在时更新身份字段但**不重置**同步水位。

        - 已存在角色：更新身份字段、来源（仅 manual 覆盖）、优先级（不降低），
          不重置 full_synced_until_time、oldest_synced_match_time、history_exhausted。
        - 新角色：设置 status='pending'、created_at 等默认字段。
        """
        db = self._db()
        identity_key = self._build_identity_key(
            global_id=global_id,
            global_role_id=global_role_id,
            zone=zone,
            role_id=role_id,
            normalized_server=normalized_server,
            normalized_name=normalized_name,
        )
        now = time.time()

        legacy_keys = legacy_identity_keys(
            global_role_id=global_role_id,
            zone=zone,
            game_role_id=role_id,
            server=normalized_server,
            name=normalized_name,
        )
        existing = await self._queue_col().find_one({"identity_key": identity_key})
        existing_key = identity_key
        if existing is None and global_id and legacy_keys:
            existing = await self._queue_col().find_one({"identity_key": {"$in": legacy_keys}})
            if existing is not None:
                existing_key = existing.get("identity_key") or identity_key

        if existing:
            return await self._update_existing_role_from_upsert(
                existing,
                existing_key,
                identity_key,
                legacy_keys,
                server=server,
                name=name,
                normalized_server=normalized_server,
                normalized_name=normalized_name,
                global_role_id=global_role_id,
                role_id=role_id,
                person_id=person_id,
                zone=zone,
                source=source,
                priority=priority,
                season_id=season_id,
                season_start_time=season_start_time,
                global_id=global_id,
                observed_match_time=observed_match_time,
                now=now,
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
            if global_id is not None:
                doc["global_id"] = global_id
            if season_id is not None:
                doc["season_id"] = season_id
            observed = coerce_match_time(observed_match_time)
            if observed is not None:
                doc["role_info_observed_match_time"] = observed
                doc["role_info_source"] = source
                doc["role_info_updated_at"] = now

            try:
                await self._queue_col().insert_one(doc)
                return identity_key
            except DuplicateKeyError:
                existing = await self._queue_col().find_one({"identity_key": identity_key})
                existing_key = identity_key
                if existing is None and global_id and legacy_keys:
                    existing = await self._queue_col().find_one({"identity_key": {"$in": legacy_keys}})
                    if existing is not None:
                        existing_key = existing.get("identity_key") or identity_key
                if existing is not None:
                    return await self._update_existing_role_from_upsert(
                        existing,
                        existing_key,
                        identity_key,
                        legacy_keys,
                        server=server,
                        name=name,
                        normalized_server=normalized_server,
                        normalized_name=normalized_name,
                        global_role_id=global_role_id,
                        role_id=role_id,
                        person_id=person_id,
                        zone=zone,
                        source=source,
                        priority=priority,
                        season_id=season_id,
                        season_start_time=season_start_time,
                        global_id=global_id,
                        observed_match_time=observed_match_time,
                        now=now,
                    )
                logger.warning("并发写入后未找到同步队列角色: identity_key={}", identity_key)
                return identity_key


    async def claim_next_roles(
        self,
        limit: int = 3,
        lease_owner: str = 'default',
        lease_seconds: int = 600,
    ) -> List[Dict[str, Any]]:
        """兼容旧调用：只从 queued 队列领取角色。"""
        claimed: List[Dict[str, Any]] = []

        for _ in range(limit):
            doc = await self.claim_queued_role(
                lease_owner=lease_owner,
                lease_seconds=lease_seconds,
            )
            if doc is None:
                break
            claimed.append(doc)

        return claimed

    async def upsert_identity_queue_candidate(
        self,
        identity_id: Any,
        identity_key: Optional[str] = None,
        server: Optional[str] = None,
        name: Optional[str] = None,
        normalized_server: Optional[str] = None,
        normalized_name: Optional[str] = None,
        global_id: Optional[str] = None,
        global_role_id: Optional[str] = None,
        role_id: Optional[str] = None,
        game_role_id: Optional[str] = None,
        person_id: Optional[str] = None,
        zone: Optional[str] = None,
        source: str = "match_detail",
        priority: int = 0,
        season_id: Optional[str] = None,
        season_start_time: int = 0,
    ) -> bool:
        """Create or refresh a queue candidate associated with role_identities._id."""
        _identity_id = self._coerce_object_id(identity_id)
        if _identity_id is None:
            return False

        now = time.time()
        set_fields: Dict[str, Any] = {"updated_at": now}
        for field, value in {
            "identity_key": identity_key,
            "server": server,
            "name": name,
            "normalized_server": normalized_server,
            "normalized_name": normalized_name,
            "global_id": global_id,
            "global_role_id": global_role_id,
            "role_id": role_id,
            "game_role_id": game_role_id or role_id,
            "person_id": person_id,
            "zone": zone,
            "season_id": season_id,
        }.items():
            if value is not None:
                set_fields[field] = value
        if season_start_time:
            set_fields["season_start_time"] = season_start_time
        set_on_insert: Dict[str, Any] = {
            "identity_id": _identity_id,
            "source": source,
            "status": "pending",
            "next_sync_after": None,
            "fail_count": 0,
            "last_cursor": 0,
            "created_at": now,
        }
        if not season_start_time:
            set_on_insert["season_start_time"] = 0

        try:
            result = await self._queue_col().update_one(
                {"identity_id": _identity_id},
                {
                    "$set": set_fields,
                    "$setOnInsert": set_on_insert,
                    "$max": {"priority": priority},
                },
                upsert=True,
            )
            return bool(getattr(result, "matched_count", 0)) or getattr(result, "upserted_id", None) is not None
        except Exception as exc:
            logger.warning(
                "写入 identity 同步队列候选失败: identity_id={} error={}",
                identity_id, exc,
            )
            return False

    async def upsert_identity_candidate(self, *args: Any, **kwargs: Any) -> bool:
        """Alias for migration callers using the shorter method name."""
        return await self.upsert_identity_queue_candidate(*args, **kwargs)

    async def enqueue_identity(
        self,
        identity_id: Any,
        mode: str,
        source: str,
        batch_id: Optional[str] = None,
        queue_sync_until_time: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Queue one identity-id candidate unless it is disabled or currently leased."""
        _identity_id = self._coerce_object_id(identity_id)
        if _identity_id is None:
            return None
        now = time.time()
        try:
            return await self._queue_col().find_one_and_update(
                filter={
                    "identity_id": _identity_id,
                    "status": {"$nin": ["disabled", "syncing"]},
                },
                update={"$set": {
                    "status": "queued",
                    "queued_at": now,
                    "queue_batch_id": batch_id,
                    "queue_mode": mode,
                    "queue_source": source,
                    "queue_sync_until_time": queue_sync_until_time,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "updated_at": now,
                }},
                return_document=ReturnDocument.AFTER,
            )
        except Exception as exc:
            logger.warning("指定 identity 同步角色入队失败: identity_id={} error={}", identity_id, exc)
            return None

    async def get_queue_state_by_identity_id(self, identity_id: Any) -> Optional[Dict[str, Any]]:
        """Read the current queue row for a role identity without side effects."""
        _identity_id = self._coerce_object_id(identity_id)
        if _identity_id is None:
            return None
        try:
            return await self._queue_col().find_one({"identity_id": _identity_id})
        except Exception as exc:
            logger.warning("读取 identity 同步队列状态失败: identity_id={} error={}", identity_id, exc)
            return None

    async def get_queue_position(self, queue_doc: Dict[str, Any]) -> Optional[int]:
        """Return the one-based queued position using the worker claim order."""
        if not queue_doc or str(queue_doc.get("status") or "") != "queued":
            return None
        identity_id = self._coerce_object_id(queue_doc.get("identity_id"))
        if identity_id is None:
            return None
        priority = queue_doc.get("priority")
        queued_at = queue_doc.get("queued_at")
        if priority is None or queued_at is None:
            return None
        try:
            ahead_count = await self._queue_col().count_documents({
                "status": "queued",
                "identity_id": {"$ne": identity_id},
                "$or": [
                    {"priority": {"$gt": priority}},
                    {"priority": priority, "queued_at": {"$lt": queued_at}},
                ],
            })
            return int(ahead_count) + 1
        except Exception as exc:
            logger.warning("计算 identity 同步队列位置失败: identity_id={} error={}", identity_id, exc)
            return None

    async def enqueue_existing_identity(
        self,
        identity: Dict[str, Any],
        *,
        priority: int,
        source: str,
        mode: str,
        batch_id: Optional[str] = None,
        queue_sync_until_time: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Create/refresh and queue an existing role identity.

        This path is for UI-triggered queueing of an already known
        role_identities row. It writes the caller-provided priority exactly and
        returns a currently syncing row unchanged instead of stealing its lease.
        """
        identity_id = self._coerce_object_id(identity.get("_id") or identity.get("identity_id"))
        if identity_id is None:
            return None

        now = time.time()
        existing = await self.get_queue_state_by_identity_id(identity_id)
        if existing and str(existing.get("status") or "") == "syncing":
            return existing

        set_fields: Dict[str, Any] = {
            "identity_id": identity_id,
            "identity_key": identity.get("identity_key"),
            "server": identity.get("server"),
            "name": identity.get("name"),
            "normalized_server": identity.get("normalized_server"),
            "normalized_name": identity.get("normalized_name"),
            "global_id": identity.get("global_id"),
            "global_role_id": identity.get("global_role_id"),
            "role_id": identity.get("role_id"),
            "game_role_id": identity.get("game_role_id") or identity.get("role_id"),
            "person_id": identity.get("person_id"),
            "zone": identity.get("zone"),
            "priority": priority,
            "status": "queued",
            "queued_at": now,
            "queue_batch_id": batch_id,
            "queue_mode": mode,
            "queue_source": source,
            "queue_sync_until_time": queue_sync_until_time,
            "lease_owner": None,
            "lease_expires_at": None,
            "updated_at": now,
        }
        set_fields = {key: value for key, value in set_fields.items() if value is not None}
        set_fields["queue_sync_until_time"] = queue_sync_until_time
        set_on_insert: Dict[str, Any] = {
            "source": source,
            "next_sync_after": None,
            "fail_count": 0,
            "last_cursor": 0,
            "season_start_time": 0,
            "created_at": now,
        }
        try:
            return await self._queue_col().find_one_and_update(
                filter={
                    "identity_id": identity_id,
                    "status": {"$nin": ["disabled", "syncing"]},
                },
                update={
                    "$set": set_fields,
                    "$setOnInsert": set_on_insert,
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except Exception as exc:
            logger.warning("已知 identity 入队失败: identity_id={} error={}", identity_id, exc)
            return None

    async def claim_queued_identity(
        self,
        lease_owner: str,
        lease_seconds: int,
    ) -> Optional[Dict[str, Any]]:
        """Claim the next queued identity candidate."""
        return await self.claim_queued_role(lease_owner=lease_owner, lease_seconds=lease_seconds)

    async def claim_specific_identity(
        self,
        identity_id: Any,
        lease_owner: str = "default",
        lease_seconds: int = 600,
    ) -> Optional[Dict[str, Any]]:
        _identity_id = self._coerce_object_id(identity_id)
        if _identity_id is None:
            return None
        now = time.time()
        return await self._queue_col().find_one_and_update(
            filter={
                "identity_id": _identity_id,
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
                "updated_at": now,
            }},
            return_document=ReturnDocument.AFTER,
        )

    async def renew_identity_lease(
        self,
        identity_id: Any,
        lease_owner: str,
        lease_seconds: int,
    ) -> bool:
        _identity_id = self._coerce_object_id(identity_id)
        if _identity_id is None:
            return False
        now = time.time()
        try:
            result = await self._queue_col().update_one(
                self._leased_identity_filter(_identity_id, lease_owner, now=now),
                {"$set": {"lease_expires_at": now + lease_seconds, "updated_at": now}},
            )
            return result.matched_count > 0
        except Exception as exc:
            logger.warning("续租 identity 同步角色失败: identity_id={} owner={} error={}", identity_id, lease_owner, exc)
            return False

    async def release_identity_interrupted(
        self,
        identity_id: Any,
        reason: str,
        requeue: bool = True,
        lease_owner: Optional[str] = None,
    ) -> bool:
        _identity_id = self._coerce_object_id(identity_id)
        if _identity_id is None:
            return False
        now = time.time()
        set_fields: Dict[str, Any] = {
            "status": "queued" if requeue else "pending",
            "next_sync_after": None,
            "lease_owner": None,
            "lease_expires_at": None,
            "interrupted_reason": reason,
            "interrupted_at": now,
            "updated_at": now,
        }
        if requeue:
            set_fields["queued_at"] = now
            set_fields["queue_batch_id"] = None
            set_fields["queue_source"] = "interrupted"
        else:
            set_fields["queued_at"] = None
            set_fields["queue_batch_id"] = None
            set_fields["queue_mode"] = None
            set_fields["queue_source"] = None
        try:
            result = await self._queue_col().update_one(
                self._leased_identity_filter(_identity_id, lease_owner, now=now),
                {"$set": set_fields},
            )
            return result.matched_count > 0
        except Exception as exc:
            logger.warning("释放中断 identity 同步角色失败: identity_id={} error={}", identity_id, exc)
            return False

    async def release_identity_success(
        self,
        identity_id: Any,
        full_synced_until_time: Optional[int] = None,
        oldest_synced_match_time: Optional[int] = None,
        latest_seen_match_time: Optional[int] = None,
        history_exhausted: Optional[bool] = None,
        season_id: Optional[str] = None,
        last_cursor: int = 0,
        lease_owner: Optional[str] = None,
    ) -> bool:
        _identity_id = self._coerce_object_id(identity_id)
        if _identity_id is None:
            return False
        now = time.time()
        set_fields: Dict[str, Any] = {
            "status": "exhausted" if history_exhausted else "cooldown",
            "next_sync_after": now + (21600 if history_exhausted else 3600),
            "last_synced_at": now,
            "fail_count": 0,
            "last_error": None,
            "last_cursor": last_cursor,
            "priority": 0,
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
            result = await self._queue_col().update_one(
                self._leased_identity_filter(_identity_id, lease_owner, now=now),
                {"$set": set_fields},
            )
            return result.matched_count > 0
        except Exception as exc:
            logger.warning("释放 identity 同步角色(成功)失败: identity_id={} error={}", identity_id, exc)
            return False

    async def release_identity_failure(
        self,
        identity_id: Any,
        error_message: str = "",
        lease_owner: Optional[str] = None,
    ) -> bool:
        _identity_id = self._coerce_object_id(identity_id)
        if _identity_id is None:
            return False
        now = time.time()
        role_filter = self._leased_identity_filter(_identity_id, lease_owner, now=now)
        existing = await self._queue_col().find_one(role_filter, {"fail_count": 1})
        if existing is None and lease_owner is not None:
            return False
        current_fail_count = 0
        if existing is not None:
            current_fail_count = existing.get("fail_count", 0) or 0
        new_fail_count = current_fail_count + 1
        new_status = "failed" if new_fail_count >= 3 else "pending"
        next_sync = now + 1800 if new_fail_count >= 3 else None
        try:
            result = await self._queue_col().update_one(
                role_filter,
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
            return result.matched_count > 0
        except Exception as exc:
            logger.warning("释放 identity 同步角色(失败)失败: identity_id={} error={}", identity_id, exc)
            return False

    async def reset_identity_progress(self, identity_id: Any) -> bool:
        _identity_id = self._coerce_object_id(identity_id)
        if _identity_id is None:
            return False
        now = time.time()
        try:
            result = await self._queue_col().update_one(
                {"identity_id": _identity_id},
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
            logger.warning("重置 identity 同步进度失败: identity_id={} error={}", identity_id, exc)
            return False

    async def update_identity_priority(
        self,
        identity_id: Any,
        priority: int,
        updated_by: Optional[str] = None,
    ) -> bool:
        _identity_id = self._coerce_object_id(identity_id)
        if _identity_id is None:
            return False
        now = time.time()
        set_fields: Dict[str, Any] = {
            "priority": priority,
            "priority_updated_at": now,
            "updated_at": now,
        }
        if updated_by is not None:
            set_fields["priority_updated_by"] = updated_by
        try:
            result = await self._queue_col().update_one(
                {"identity_id": _identity_id},
                {"$set": set_fields},
            )
            return result.matched_count > 0
        except Exception as exc:
            logger.warning("更新 identity 同步角色优先级失败: identity_id={} error={}", identity_id, exc)
            return False

    async def enqueue_next_roles(
        self,
        limit: int,
        mode: str,
        source: str,
        batch_id: Optional[str],
        queue_sync_until_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """将下一批可同步角色原子转入 queued 状态。

        候选角色来自 pending/cooldown/exhausted/failed，且 next_sync_after 为空或已到期。
        每次用 find_one_and_update 领取一个候选，保证多入口并发入队时不会重复处理同一角色。
        """
        if limit < 1:
            return []

        db = self._db()
        enqueued: List[Dict[str, Any]] = []

        for _ in range(limit):
            now = time.time()
            try:
                doc = await self._queue_col().find_one_and_update(
                    filter={
                        "status": {"$in": ["pending", "cooldown", "exhausted", "failed"]},
                        "$or": [
                            {"next_sync_after": None},
                            {"next_sync_after": {"$lte": now}},
                        ],
                    },
                    update={"$set": {
                        "status": "queued",
                        "queued_at": now,
                        "queue_batch_id": batch_id,
                        "queue_mode": mode,
                        "queue_source": source,
                        "queue_sync_until_time": queue_sync_until_time,
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "updated_at": now,
                    }},
                    sort=[("priority", -1), ("updated_at", 1)],
                    return_document=ReturnDocument.AFTER,
                )
            except Exception as exc:
                logger.warning("批量入队同步角色失败: error={}", exc)
                break

            if doc is None:
                break
            enqueued.append(doc)

        return enqueued

    async def enqueue_role(
        self,
        identity_key: str,
        mode: str,
        source: str,
        batch_id: Optional[str] = None,
        queue_sync_until_time: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """将指定的非 disabled、非 syncing 角色转入 queued 状态。"""
        identity_id = await self._resolve_identity_id_by_key(identity_key)
        if identity_id is not None:
            return await self.enqueue_identity(
                identity_id,
                mode=mode,
                source=source,
                batch_id=batch_id,
                queue_sync_until_time=queue_sync_until_time,
            )

        now = time.time()

        try:
            return await self._queue_col().find_one_and_update(
                filter={
                    "identity_key": identity_key,
                    "status": {"$nin": ["disabled", "syncing"]},
                },
                update={"$set": {
                    "status": "queued",
                    "queued_at": now,
                    "queue_batch_id": batch_id,
                    "queue_mode": mode,
                    "queue_source": source,
                    "queue_sync_until_time": queue_sync_until_time,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "updated_at": now,
                }},
                return_document=ReturnDocument.AFTER,
            )
        except Exception as exc:
            logger.warning(
                "指定同步角色入队失败: identity_key={} error={}",
                identity_key, exc,
            )
            return None

    async def claim_queued_role(
        self,
        lease_owner: str,
        lease_seconds: int,
    ) -> Optional[Dict[str, Any]]:
        """原子领取一个 queued 角色，按 priority 降序、queued_at 升序。"""
        db = self._db()
        now = time.time()

        try:
            return await self._queue_col().find_one_and_update(
                filter={"status": "queued"},
                update={"$set": {
                    "status": "syncing",
                    "lease_owner": lease_owner,
                    "lease_expires_at": now + lease_seconds,
                    "updated_at": now,
                }},
                sort=[("priority", -1), ("queued_at", 1)],
                return_document=ReturnDocument.AFTER,
            )
        except Exception as exc:
            logger.warning("领取 queued 同步角色失败: owner={} error={}", lease_owner, exc)
            return None

    async def release_role_interrupted(
        self,
        identity_key: str,
        reason: str,
        requeue: bool = True,
        lease_owner: Optional[str] = None,
    ) -> bool:
        """释放被中断的角色，不增加 fail_count。"""
        identity_id = await self._resolve_identity_id_by_key(identity_key)
        if identity_id is not None:
            return await self.release_identity_interrupted(
                identity_id,
                reason=reason,
                requeue=requeue,
                lease_owner=lease_owner,
            )

        now = time.time()
        set_fields: Dict[str, Any] = {
            "status": "queued" if requeue else "pending",
            "next_sync_after": None,
            "lease_owner": None,
            "lease_expires_at": None,
            "interrupted_reason": reason,
            "interrupted_at": now,
            "updated_at": now,
        }
        if requeue:
            set_fields["queued_at"] = now
            set_fields["queue_batch_id"] = None
            set_fields["queue_source"] = "interrupted"
        else:
            set_fields["queued_at"] = None
            set_fields["queue_batch_id"] = None
            set_fields["queue_mode"] = None
            set_fields["queue_source"] = None

        try:
            result = await self._queue_col().update_one(
                self._leased_role_filter(identity_key, lease_owner, now=now),
                {"$set": set_fields},
            )
            return result.matched_count > 0
        except Exception as exc:
            logger.warning(
                "释放中断同步角色失败: identity_key={} error={}",
                identity_key, exc,
            )
            return False

    async def update_role_priority(
        self,
        identity_key: str,
        priority: int,
        updated_by: Optional[str] = None,
    ) -> bool:
        """更新角色调度优先级。"""
        identity_id = await self._resolve_identity_id_by_key(identity_key)
        if identity_id is not None:
            return await self.update_identity_priority(identity_id, priority, updated_by=updated_by)

        now = time.time()
        set_fields: Dict[str, Any] = {
            "priority": priority,
            "priority_updated_at": now,
            "updated_at": now,
        }
        if updated_by is not None:
            set_fields["priority_updated_by"] = updated_by

        try:
            result = await self._queue_col().update_one(
                {"identity_key": identity_key},
                {"$set": set_fields},
            )
            return result.matched_count > 0
        except Exception as exc:
            logger.warning(
                "更新同步角色优先级失败: identity_key={} error={}",
                identity_key, exc,
            )
            return False

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
        identity_id = await self._resolve_identity_id_by_key(identity_key)
        if identity_id is not None:
            return await self.claim_specific_identity(
                identity_id,
                lease_owner=lease_owner,
                lease_seconds=lease_seconds,
            )

        now = time.time()
        return await self._queue_col().find_one_and_update(
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
        lease_owner: Optional[str] = None,
    ) -> bool:
        """释放角色（同步成功）。

        如果 history_exhausted=True: status='exhausted', next_sync_after=now+6h
        否则: status='cooldown', next_sync_after=now+1h
        清除租约，重置 fail_count/error，更新水位字段。
        """
        identity_id = await self._resolve_identity_id_by_key(identity_key)
        if identity_id is not None:
            return await self.release_identity_success(
                identity_id,
                full_synced_until_time=full_synced_until_time,
                oldest_synced_match_time=oldest_synced_match_time,
                latest_seen_match_time=latest_seen_match_time,
                history_exhausted=history_exhausted,
                season_id=season_id,
                last_cursor=last_cursor,
                lease_owner=lease_owner,
            )

        now = time.time()

        set_fields: Dict[str, Any] = {
            "status": "exhausted" if history_exhausted else "cooldown",
            "next_sync_after": now + (21600 if history_exhausted else 3600),
            "last_synced_at": now,
            "fail_count": 0,
            "last_error": None,
            "last_cursor": last_cursor,
            "priority": 0,
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
            result = await self._queue_col().update_one(
                self._leased_role_filter(identity_key, lease_owner, now=now),
                {"$set": set_fields},
            )
            return result.matched_count > 0
        except Exception as exc:
            logger.warning(
                "释放同步角色(成功)失败: identity_key={} error={}",
                identity_key, exc,
            )
            return False

    async def enqueue_ranking_member(
        self,
        member: Dict[str, Any],
        *,
        season_id: Optional[str] = None,
        season_start_time: int = 0,
        priority: int = 1,
        mode: str = "full",
        source: str = "ranking_stats",
        batch_id: Optional[str] = None,
        queue_sync_until_time: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Upsert a ranking-stat member into the sync queue and mark it queued."""
        server = str(member.get("server") or "").strip()
        name = str(member.get("name") or member.get("role_name") or "").strip()
        if not server or not name or server == "未知" or name == "未知":
            return None

        role_id = str(
            member.get("role_id")
            or member.get("game_role_id")
            or member.get("gameRoleId")
            or ""
        ).strip() or None
        zone = str(member.get("zone") or "").strip() or None
        global_role_id = str(
            member.get("global_role_id")
            or member.get("globalRoleId")
            or ""
        ).strip() or None
        global_id = str(member.get("global_id") or "").strip() or None
        normalized_server = server.lower()
        normalized_name = name.lower()

        db = self._db()
        if hasattr(db, "role_identities"):
            try:
                from src.storage.mongo_repos.role_identity_repo import RoleIdentityRepo

                identity = await RoleIdentityRepo(db=db).upsert_from_ranking_with_id(
                    server=server,
                    name=name,
                    zone=zone or "",
                    game_role_id=role_id or "",
                    global_role_id=global_role_id,
                    role_id=role_id,
                    global_id=global_id,
                )
                identity_id = self._coerce_object_id(identity.get("_id")) if isinstance(identity, dict) else None
                if identity_id is not None:
                    existing_queue = await self._queue_col().find_one({"identity_id": identity_id})
                    if self._priority_at_least(existing_queue, priority):
                        return None
                    queued = await self.upsert_identity_queue_candidate(
                        identity_id=identity_id,
                        identity_key=identity.get("identity_key"),
                        server=identity.get("server") or server,
                        name=identity.get("name") or name,
                        normalized_server=identity.get("normalized_server") or normalized_server,
                        normalized_name=identity.get("normalized_name") or normalized_name,
                        global_id=identity.get("global_id") or global_id,
                        global_role_id=identity.get("global_role_id") or global_role_id,
                        role_id=identity.get("role_id") or role_id,
                        game_role_id=identity.get("game_role_id") or role_id,
                        person_id=identity.get("person_id"),
                        zone=identity.get("zone") or zone,
                        source=source,
                        priority=priority,
                        season_id=season_id,
                        season_start_time=season_start_time,
                    )
                    if queued:
                        await self.update_identity_priority(
                            identity_id,
                            priority=priority,
                            updated_by=source,
                        )
                        return await self.enqueue_identity(
                            identity_id,
                            mode=mode,
                            source=source,
                            batch_id=batch_id,
                            queue_sync_until_time=queue_sync_until_time,
                        )
            except Exception as exc:
                logger.warning(
                    "排行榜成员写入 identity 同步队列失败，尝试 legacy 队列: server={} name={} error={}",
                    server,
                    name,
                    exc,
                )

        identity_key = self._build_identity_key(
            global_id=global_id,
            global_role_id=global_role_id,
            zone=zone,
            role_id=role_id,
            normalized_server=normalized_server,
            normalized_name=normalized_name,
        )
        lookup_keys = [identity_key]
        lookup_keys.extend(legacy_identity_keys(
            global_role_id=global_role_id,
            zone=zone,
            game_role_id=role_id,
            server=normalized_server,
            name=normalized_name,
        ))
        existing_queue = await self._queue_col().find_one({"identity_key": {"$in": sorted(set(lookup_keys))}})
        if self._priority_at_least(existing_queue, priority):
            return None

        identity_key = await self.upsert_role(
            server=server,
            name=name,
            normalized_server=normalized_server,
            normalized_name=normalized_name,
            global_id=global_id,
            global_role_id=global_role_id,
            role_id=role_id,
            zone=zone,
            source=source,
            priority=priority,
            season_id=season_id,
            season_start_time=season_start_time,
        )
        await self.update_role_priority(
            identity_key,
            priority=priority,
            updated_by=source,
        )
        return await self.enqueue_role(
            identity_key,
            mode=mode,
            source=source,
            batch_id=batch_id,
            queue_sync_until_time=queue_sync_until_time,
        )

    async def release_role_failure(
        self,
        identity_key: str,
        error_message: str = '',
        lease_owner: Optional[str] = None,
    ) -> bool:
        """释放角色（同步失败）。

        累加 fail_count。fail_count >= 3 时状态变为 failed，next_sync_after=now+30min，
        否则恢复为 pending。清除租约，记录错误信息。
        """
        identity_id = await self._resolve_identity_id_by_key(identity_key)
        if identity_id is not None:
            return await self.release_identity_failure(
                identity_id,
                error_message=error_message,
                lease_owner=lease_owner,
            )

        now = time.time()

        role_filter = self._leased_role_filter(identity_key, lease_owner, now=now)
        existing = await self._queue_col().find_one(
            role_filter,
            {"fail_count": 1},
        )
        if existing is None and lease_owner is not None:
            return False

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
            result = await self._queue_col().update_one(
                role_filter,
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
            return result.matched_count > 0
        except Exception as exc:
            logger.warning(
                "释放同步角色(失败)失败: identity_key={} error={}",
                identity_key, exc,
            )
            return False

    async def renew_role_lease(
        self,
        identity_key: str,
        lease_owner: str,
        lease_seconds: int,
    ) -> bool:
        """续租正在同步的角色；仅当前租约 owner 可以续租。"""
        identity_id = await self._resolve_identity_id_by_key(identity_key)
        if identity_id is not None:
            return await self.renew_identity_lease(
                identity_id,
                lease_owner=lease_owner,
                lease_seconds=lease_seconds,
            )

        now = time.time()

        try:
            result = await self._queue_col().update_one(
                self._leased_role_filter(identity_key, lease_owner, now=now),
                {"$set": {
                    "lease_expires_at": now + lease_seconds,
                    "updated_at": now,
                }},
            )
            return result.matched_count > 0
        except Exception as exc:
            logger.warning(
                "续租同步角色失败: identity_key={} owner={} error={}",
                identity_key,
                lease_owner,
                exc,
            )
            return False

    async def update_role_identity_fields(
        self,
        identity_key: str,
        global_role_id: Optional[str] = None,
        role_id: Optional[str] = None,
        person_id: Optional[str] = None,
        zone: Optional[str] = None,
        identity_source: Optional[str] = None,
        global_id: Optional[str] = None,
        observed_match_time: Optional[int] = None,
        lease_owner: Optional[str] = None,
    ) -> bool:
        """补充同步队列角色的外部身份字段，不改变同步水位或 identity_key。"""
        db = self._db()
        now = time.time()
        role_filter = self._leased_role_filter(identity_key, lease_owner, now=now)
        set_fields: Dict[str, Any] = {"updated_at": now}
        existing = await self._queue_col().find_one(role_filter) or {}
        if lease_owner is not None and not existing:
            return False

        existing_global_id = str(existing.get("global_id") or "").strip()
        if global_id and (not existing_global_id or existing_global_id == global_id):
            set_fields["global_id"] = global_id
        set_fields.update(self._profile_update_fields(
            existing,
            {
                "global_role_id": global_role_id,
                "role_id": role_id,
                "game_role_id": role_id,
                "person_id": person_id,
                "zone": zone,
            },
            identity_source,
            now,
            observed_match_time=observed_match_time,
        ))
        if identity_source:
            set_fields["identity_source"] = identity_source

        if len(set_fields) == 1:
            return False

        try:
            result = await self._queue_col().update_one(
                role_filter,
                {"$set": set_fields},
            )
            return result.matched_count > 0
        except Exception as exc:
            logger.warning(
                "补充同步角色身份字段失败: identity_key={} error={}",
                identity_key, exc,
            )
            return False

    async def update_role_identity_fields_and_key(
        self,
        identity_key: str,
        global_role_id: Optional[str] = None,
        role_id: Optional[str] = None,
        person_id: Optional[str] = None,
        zone: Optional[str] = None,
        identity_source: Optional[str] = None,
        global_id: Optional[str] = None,
        observed_match_time: Optional[int] = None,
        lease_owner: Optional[str] = None,
    ) -> Optional[str]:
        """补充同步队列身份字段；拿到 global_id 时迁移 identity_key 并保留水位。"""
        db = self._db()
        now = time.time()
        role_filter = self._leased_role_filter(identity_key, lease_owner, now=now)
        existing = await self._queue_col().find_one(role_filter)
        if not existing:
            return None
        existing_global_id = str(existing.get("global_id") or "").strip()
        incoming_global_id = str(global_id or "").strip()
        if existing_global_id and incoming_global_id and existing_global_id != incoming_global_id:
            logger.warning(
                "同步队列 global_id 冲突，跳过身份字段更新: identity_key={} existing_global_id={} incoming_global_id={}",
                identity_key,
                existing_global_id,
                incoming_global_id,
            )
            return identity_key

        new_key = identity_key
        if global_id:
            new_key = self._build_identity_key(
                global_id=global_id,
                global_role_id=global_role_id or existing.get("global_role_id"),
                zone=zone or existing.get("zone"),
                role_id=role_id or existing.get("role_id"),
                normalized_server=existing.get("normalized_server"),
                normalized_name=existing.get("normalized_name"),
            )

        set_fields: Dict[str, Any] = {"updated_at": now}
        if new_key != identity_key:
            set_fields["identity_key"] = new_key
        if global_id:
            set_fields["global_id"] = global_id
        set_fields.update(self._profile_update_fields(
            existing,
            {
                "global_role_id": global_role_id,
                "role_id": role_id,
                "game_role_id": role_id,
                "person_id": person_id,
                "zone": zone,
            },
            identity_source,
            now,
            observed_match_time=observed_match_time,
        ))
        if identity_source:
            set_fields["identity_source"] = identity_source
        if new_key != identity_key:
            if global_role_id:
                set_fields["global_role_id"] = global_role_id
            if role_id:
                set_fields["role_id"] = role_id
                set_fields["game_role_id"] = role_id
            if zone:
                set_fields["zone"] = zone

        update_op: Dict[str, Any] = {"$set": set_fields}
        if new_key != identity_key:
            legacy_keys = legacy_identity_keys(
                global_role_id=global_role_id or existing.get("global_role_id"),
                zone=zone or existing.get("zone"),
                game_role_id=role_id or existing.get("role_id"),
                server=existing.get("normalized_server"),
                name=existing.get("normalized_name"),
            )
            aliases = sorted(set([identity_key] + legacy_keys))
            update_op["$addToSet"] = {"aliases": {"$each": aliases}}

        try:
            result = await self._queue_col().update_one(
                role_filter,
                update_op,
            )
            if result.matched_count <= 0:
                return None
            return new_key
        except Exception as exc:
            logger.warning(
                "补充同步角色身份字段并迁移 key 失败: identity_key={} new_key={} error={}",
                identity_key,
                new_key,
                exc,
            )
            return None

    async def reset_role_progress(self, identity_key: str) -> bool:
        """重置角色同步进度。

        将指定角色 status 设为 pending，清空同步水位字段、租约信息和错误信息，
        fail_count 和 last_cursor 归零。
        成功返回 True。
        """
        identity_id = await self._resolve_identity_id_by_key(identity_key)
        if identity_id is not None:
            return await self.reset_identity_progress(identity_id)

        now = time.time()

        try:
            result = await self._queue_col().update_one(
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

        - 角色：status='syncing' 且 lease_expires_at < now → status='queued'，清除租约
        - 对局：status='detail_syncing' 且 lease_expires_at < now → status='discovered'，清除租约
        返回恢复的文档总数。
        """
        db = self._db()
        now = time.time()
        total_recovered = 0

        # 恢复超时角色租约
        try:
            role_result = await self._queue_col().update_many(
                filter={
                    "status": "syncing",
                    "lease_expires_at": {"$lt": now},
                },
                update={"$set": {
                    "status": "queued",
                    "queued_at": now,
                    "interrupted_reason": "lease_expired",
                    "interrupted_at": now,
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
        source_identity_id: Any = None,
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
        _source_identity_id = self._coerce_object_id(source_identity_id)

        try:
            result = await db.jjc_sync_match_seen.update_one(
                {"match_id": _match_id},
                {"$setOnInsert": {
                    "match_id": _match_id,
                    "match_time": match_time,
                    "source_identity_key": source_identity_key,
                    "source_identity_id": _source_identity_id,
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

    async def get_match_detail_sync_state(self, match_id: Union[int, str]) -> Dict[str, Any]:
        """返回对局详情同步决策状态。

        action 是 service 的必需合同：
        - skip：详情已处于终态，当前角色可跳过该对局。
        - claimable：记录理论上可领取；claim 未命中通常代表并发竞争，当前角色应中断重试。
        - interrupt：记录处于非终态且当前 worker 不应继续推进角色水位。
        """
        _match_id = self._coerce_int(match_id)
        if _match_id is None:
            return {
                "exists": False,
                "status": "invalid_match_id",
                "action": "interrupt",
                "terminal": False,
                "claimable": False,
            }

        db = self._db()
        doc = await db.jjc_sync_match_seen.find_one(
            {"match_id": _match_id},
            {"status": 1, "detail_retry_after": 1, "lease_owner": 1, "lease_expires_at": 1},
        )
        if not doc:
            return {
                "exists": False,
                "status": "missing",
                "action": "interrupt",
                "terminal": False,
                "claimable": False,
            }

        status = str(doc.get("status") or "")
        now = time.time()
        retry_after = doc.get("detail_retry_after")
        terminal = status in ("detail_saved", "detail_unavailable")
        claimable = status == "discovered" or (
            status == "failed"
            and (retry_after is None or retry_after <= now)
        )
        if terminal:
            action = "skip"
        elif claimable:
            action = "claimable"
        else:
            action = "interrupt"
        return {
            "exists": True,
            "status": status,
            "action": action,
            "terminal": terminal,
            "claimable": claimable,
            "detail_retry_after": retry_after,
            "lease_owner": doc.get("lease_owner"),
            "lease_expires_at": doc.get("lease_expires_at"),
        }

    async def get_match_seen_doc(self, match_id: Union[int, str]) -> Optional[Dict[str, Any]]:
        """Return the full match-seen document used by read-model projections."""
        _match_id = self._coerce_int(match_id)
        if _match_id is None:
            return None
        db = self._db()
        try:
            doc = await db.jjc_sync_match_seen.find_one({"match_id": _match_id})
        except Exception as exc:
            logger.warning("读取对局 seen 文档失败: match_id={} error={}", _match_id, exc)
            return None
        return doc if isinstance(doc, dict) else None

    async def release_match_detail_interrupted(
        self,
        match_id: Union[int, str],
        reason: str = "",
        lease_owner: Optional[str] = None,
    ) -> bool:
        """当前处理被全局暂停/中断时，owner-fenced 地把详情释放回 discovered。"""
        _match_id = self._coerce_int(match_id)
        if _match_id is None:
            return False
        db = self._db()
        now = time.time()
        try:
            result = await db.jjc_sync_match_seen.update_one(
                self._leased_match_detail_filter(_match_id, lease_owner, now=now),
                {
                    "$set": {
                        "status": "discovered",
                        "interrupted_reason": reason,
                        "interrupted_at": now,
                        "updated_at": now,
                    },
                    "$unset": {"lease_owner": "", "lease_expires_at": ""},
                },
            )
            return bool(getattr(result, "matched_count", 0))
        except Exception as exc:
            logger.warning(
                "释放对局详情中断状态失败: match_id={} owner={} error={}",
                _match_id, lease_owner, exc,
            )
            return False

    async def mark_match_detail_saved(
        self,
        match_id: Union[int, str],
        lease_owner: Optional[str] = None,
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
            result = await db.jjc_sync_match_seen.update_one(
                self._leased_match_detail_filter(_match_id, lease_owner, now=now),
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
            return result.matched_count > 0
        except Exception as exc:
            logger.warning(
                "标记对局详情已保存失败: match_id={} error={}",
                _match_id, exc,
            )
            return False

    async def renew_match_detail_lease(
        self,
        match_id: Union[int, str],
        lease_owner: str,
        lease_seconds: int,
    ) -> bool:
        """续租正在同步的对局详情；仅当前租约 owner 可以续租。"""
        _match_id = self._coerce_int(match_id)
        if _match_id is None:
            return False

        db = self._db()
        now = time.time()

        try:
            result = await db.jjc_sync_match_seen.update_one(
                self._leased_match_detail_filter(_match_id, lease_owner, now=now),
                {"$set": {
                    "lease_expires_at": now + lease_seconds,
                    "updated_at": now,
                }},
            )
            return result.matched_count > 0
        except Exception as exc:
            logger.warning(
                "续租对局详情失败: match_id={} owner={} error={}",
                _match_id,
                lease_owner,
                exc,
            )
            return False

    async def mark_match_detail_unavailable(
        self,
        match_id: Union[int, str],
        reason: str = '',
        code: Union[int, str] = 0,
        lease_owner: Optional[str] = None,
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
            result = await db.jjc_sync_match_seen.update_one(
                self._leased_match_detail_filter(_match_id, lease_owner, now=now),
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
            return result.matched_count > 0
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
        lease_owner: Optional[str] = None,
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
        match_filter = self._leased_match_detail_filter(_match_id, lease_owner, now=now)

        existing = await db.jjc_sync_match_seen.find_one(
            match_filter,
            {"fail_count": 1},
        )
        if existing is None and lease_owner is not None:
            return False
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
            result = await db.jjc_sync_match_seen.update_one(
                match_filter,
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
            return result.matched_count > 0
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
            cursor = self._queue_col().aggregate(pipeline)
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
                self._queue_col()
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
            return await self._queue_col().find_one(
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

    async def get_identity_by_name(
        self,
        normalized_server: str,
        normalized_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Identity-queue alias for lookup by normalized server/name."""
        return await self.get_role_by_name(normalized_server, normalized_name)

    async def get_identity_queue_by_name(
        self,
        normalized_server: str,
        normalized_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Explicit identity queue lookup by normalized server/name."""
        return await self.get_role_by_name(normalized_server, normalized_name)

    async def list_queue(
        self,
        status: Optional[str] = None,
        mode: Optional[str] = None,
        server: Optional[str] = None,
        name: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """分页返回角色队列文档，供状态页/API 展示。"""
        db = self._db()
        safe_page = max(1, page)
        safe_page_size = min(max(1, page_size), 200)
        skip = (safe_page - 1) * safe_page_size
        query: Dict[str, Any] = {}
        if status:
            query["status"] = status
        if mode:
            query["queue_mode"] = mode
        if server:
            server_pattern = {"$regex": escape_regex(server), "$options": "i"}
            query["$or"] = [
                {"server": server_pattern},
                {"normalized_server": server_pattern},
            ]
        if name:
            name_pattern = {"$regex": escape_regex(name), "$options": "i"}
            query.setdefault("$and", []).append({
                "$or": [
                    {"name": name_pattern},
                    {"normalized_name": name_pattern},
                ]
            })

        docs: List[Dict[str, Any]] = []
        total = 0
        try:
            total = await self._queue_col().count_documents(query)
            cursor = (
                self._queue_col()
                .find(query)
                .sort([
                    ("status", 1),
                    ("priority", -1),
                    ("queued_at", 1),
                    ("updated_at", -1),
                ])
                .skip(skip)
                .limit(safe_page_size)
            )
            async for doc in cursor:
                docs.append(doc)
        except Exception as exc:
            logger.warning(
                "分页查询同步队列失败: status={} mode={} server={} name={} error={}",
                status, mode, server, name, exc,
            )

        return {
            "items": docs,
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
            "has_more": safe_page * safe_page_size < total,
        }

    async def list_identity_queue(
        self,
        status: Optional[str] = None,
        mode: Optional[str] = None,
        server: Optional[str] = None,
        name: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """Identity-queue alias for paginated queue listing."""
        return await self.list_queue(
            status=status,
            mode=mode,
            server=server,
            name=name,
            page=page,
            page_size=page_size,
        )

    # ---- worker 状态操作 ----

    async def register_worker(
        self,
        worker_id: str,
        mode: str,
        pid: Optional[int] = None,
        host: Optional[str] = None,
        status: str = "running",
    ) -> bool:
        """注册或刷新一个同步 worker。"""
        db = self._db()
        now = time.time()
        set_fields: Dict[str, Any] = {
            "worker_id": worker_id,
            "mode": mode,
            "status": status,
            "pid": pid,
            "host": host,
            "current_identity_id": None,
            "current_identity_key": None,
            "current_server": None,
            "current_name": None,
            "last_error": "",
            "heartbeat_at": now,
            "started_at": now,
            "updated_at": now,
        }

        try:
            result = await db.jjc_sync_workers.update_one(
                {"worker_id": worker_id},
                {"$set": set_fields},
                upsert=True,
            )
            return result.matched_count > 0 or getattr(result, "upserted_id", None) is not None
        except Exception as exc:
            logger.warning("注册 JJC 同步 worker 失败: worker_id={} error={}", worker_id, exc)
            return False

    async def heartbeat_worker(
        self,
        worker_id: str,
        status: str = "running",
        current_identity_id: Any = None,
        current_identity_key: Optional[str] = None,
        current_server: Optional[str] = None,
        current_name: Optional[str] = None,
        last_result: Optional[Dict[str, Any]] = None,
        last_error: Optional[str] = None,
    ) -> bool:
        """更新 worker 心跳和当前处理状态。"""
        db = self._db()
        now = time.time()
        _current_identity_id = self._coerce_object_id(current_identity_id)
        set_fields: Dict[str, Any] = {
            "status": status,
            "current_identity_id": _current_identity_id,
            "current_identity_key": current_identity_key,
            "current_server": current_server,
            "current_name": current_name,
            "heartbeat_at": now,
            "updated_at": now,
        }
        if last_result is not None:
            set_fields["last_result"] = last_result
        if last_error is not None:
            set_fields["last_error"] = last_error

        try:
            result = await db.jjc_sync_workers.update_one(
                {"worker_id": worker_id},
                {"$set": set_fields},
            )
            return result.matched_count > 0
        except Exception as exc:
            logger.warning("更新 JJC 同步 worker 心跳失败: worker_id={} error={}", worker_id, exc)
            return False

    async def stop_worker(
        self,
        worker_id: str,
        reason: str = '',
    ) -> bool:
        """标记 worker 已停止。"""
        db = self._db()
        now = time.time()

        try:
            result = await db.jjc_sync_workers.update_one(
                {"worker_id": worker_id},
                {"$set": {
                    "status": "stopped",
                    "current_identity_id": None,
                    "current_identity_key": None,
                    "current_server": None,
                    "current_name": None,
                    "stop_reason": reason,
                    "heartbeat_at": now,
                    "updated_at": now,
                }},
            )
            return result.matched_count > 0
        except Exception as exc:
            logger.warning("停止 JJC 同步 worker 失败: worker_id={} error={}", worker_id, exc)
            return False

    async def list_workers(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """返回 worker 状态列表，按最近心跳倒序。"""
        db = self._db()
        safe_limit = min(max(1, limit), 200)
        query: Dict[str, Any] = {}
        if status:
            query["status"] = status

        docs: List[Dict[str, Any]] = []
        try:
            cursor = (
                db.jjc_sync_workers
                .find(query)
                .sort("heartbeat_at", -1)
                .limit(safe_limit)
            )
            async for doc in cursor:
                docs.append(doc)
        except Exception as exc:
            logger.warning("查询 JJC 同步 worker 列表失败: status={} error={}", status, exc)

        return docs

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

    async def get_pause_state(self) -> Dict[str, Any]:
        """读取全局暂停状态详情。"""
        db = self._db()

        try:
            doc = await db.jjc_sync_state.find_one({"key": "global"})
            if doc is None:
                return {"paused": False, "reason": "", "updated_at": None}
            return {
                "paused": bool(doc.get("paused", False)),
                "reason": doc.get("reason") or "",
                "updated_at": doc.get("updated_at"),
            }
        except Exception as exc:
            logger.warning("读取全局暂停状态详情失败: error={}", exc)
            return {"paused": False, "reason": "", "updated_at": None}

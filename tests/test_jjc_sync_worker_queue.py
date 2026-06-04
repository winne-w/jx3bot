import time
import unittest
import re
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional

from src.storage.mongo_repos.jjc_sync_repo import JjcSyncRepo


class AsyncMemoryCursor:
    def __init__(self, docs: Iterable[Dict[str, Any]]) -> None:
        self._docs = list(docs)

    @staticmethod
    def _sort_value(doc: Dict[str, Any], field: str, direction: int) -> Any:
        value = doc.get(field)
        if value is None:
            return float("-inf") if direction < 0 else float("inf")
        return value

    def sort(self, key_or_list: Any, direction: Optional[int] = None) -> "AsyncMemoryCursor":
        if isinstance(key_or_list, list):
            sort_spec = key_or_list
        else:
            sort_spec = [(key_or_list, direction if direction is not None else 1)]

        for field, sort_direction in reversed(sort_spec):
            self._docs.sort(
                key=lambda doc: self._sort_value(doc, field, sort_direction),
                reverse=sort_direction < 0,
            )
        return self

    def skip(self, count: int) -> "AsyncMemoryCursor":
        self._docs = self._docs[count:]
        return self

    def limit(self, count: int) -> "AsyncMemoryCursor":
        self._docs = self._docs[:count]
        return self

    def __aiter__(self) -> "AsyncMemoryCursor":
        self._iter = iter(self._docs)
        return self

    async def __anext__(self) -> Dict[str, Any]:
        try:
            return dict(next(self._iter))
        except StopIteration:
            raise StopAsyncIteration


class MemoryCollection:
    def __init__(self, docs: Optional[List[Dict[str, Any]]] = None) -> None:
        self.docs = [dict(doc) for doc in (docs or [])]

    @staticmethod
    def _matches_operator(value: Any, operator: str, expected: Any) -> bool:
        if operator == "$in":
            return value in expected
        if operator == "$ne":
            return value != expected
        if operator == "$gt":
            return value is not None and isinstance(value, (int, float)) and value > expected
        if operator == "$lte":
            return value is not None and value <= expected
        if operator == "$lt":
            return value is not None and value < expected
        if operator == "$exists":
            return (value is not None) is bool(expected)
        if operator == "$nin":
            return value not in expected
        raise AssertionError("unsupported operator: {}".format(operator))

    @classmethod
    def _matches(cls, doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
        for field, expected in query.items():
            if field == "$or":
                if not any(cls._matches(doc, condition) for condition in expected):
                    return False
                continue
            if field == "$and":
                if not all(cls._matches(doc, condition) for condition in expected):
                    return False
                continue

            value = doc.get(field)
            if isinstance(expected, dict):
                if "$regex" in expected:
                    flags = re.IGNORECASE if "i" in str(expected.get("$options") or "") else 0
                    if re.search(str(expected["$regex"]), str(value or ""), flags) is None:
                        return False
                    continue
                for operator, operator_expected in expected.items():
                    if not cls._matches_operator(value, operator, operator_expected):
                        return False
            elif value != expected:
                return False
        return True

    @staticmethod
    def _apply_update(doc: Dict[str, Any], update: Dict[str, Any], insert: bool = False) -> None:
        for field, value in update.get("$set", {}).items():
            doc[field] = value
        for field, value in update.get("$max", {}).items():
            current = doc.get(field)
            if current is None or current < value:
                doc[field] = value
        for field in update.get("$unset", {}):
            doc.pop(field, None)
        if insert:
            for field, value in update.get("$setOnInsert", {}).items():
                doc[field] = value

    def _sorted_matches(
        self,
        query: Dict[str, Any],
        sort_spec: Optional[List[Any]] = None,
    ) -> List[Dict[str, Any]]:
        matched = [doc for doc in self.docs if self._matches(doc, query)]
        if sort_spec:
            cursor = AsyncMemoryCursor(matched).sort(sort_spec)
            return cursor._docs
        return matched

    async def find_one(self, query: Dict[str, Any], projection: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        del projection
        for doc in self.docs:
            if self._matches(doc, query):
                return dict(doc)
        return None

    async def find_one_and_update(
        self,
        filter: Dict[str, Any],
        update: Dict[str, Any],
        sort: Optional[List[Any]] = None,
        return_document: Any = None,
    ) -> Optional[Dict[str, Any]]:
        del return_document
        matched = self._sorted_matches(filter, sort)
        if not matched:
            return None
        doc = matched[0]
        self._apply_update(doc, update)
        return dict(doc)

    async def update_one(
        self,
        filter: Dict[str, Any],
        update: Dict[str, Any],
        upsert: bool = False,
    ) -> Any:
        for doc in self.docs:
            if self._matches(doc, filter):
                self._apply_update(doc, update)
                return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)

        if upsert:
            inserted = dict(filter)
            self._apply_update(inserted, update, insert=True)
            self.docs.append(inserted)
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id="upserted")

        return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)

    async def insert_one(self, doc: Dict[str, Any]) -> Any:
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=len(self.docs))

    async def update_many(self, filter: Dict[str, Any], update: Dict[str, Any]) -> Any:
        modified_count = 0
        for doc in self.docs:
            if self._matches(doc, filter):
                self._apply_update(doc, update)
                modified_count += 1
        return SimpleNamespace(modified_count=modified_count)

    async def count_documents(self, query: Dict[str, Any]) -> int:
        return len([doc for doc in self.docs if self._matches(doc, query)])

    def find(self, query: Dict[str, Any]) -> AsyncMemoryCursor:
        return AsyncMemoryCursor(dict(doc) for doc in self.docs if self._matches(doc, query))


class MemoryDb:
    def __init__(
        self,
        roles: Optional[List[Dict[str, Any]]] = None,
        matches: Optional[List[Dict[str, Any]]] = None,
        workers: Optional[List[Dict[str, Any]]] = None,
        states: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.jjc_sync_role_queue = MemoryCollection(roles)
        self.jjc_sync_match_seen = MemoryCollection(matches)
        self.jjc_sync_workers = MemoryCollection(workers)
        self.jjc_sync_state = MemoryCollection(states)


class TestJjcSyncWorkerQueue(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_next_roles_sorts_and_filters_due_roles(self) -> None:
        now = time.time()
        db = MemoryDb(roles=[
            {"identity_key": "a", "status": "pending", "priority": 10, "updated_at": 20, "next_sync_after": None},
            {"identity_key": "b", "status": "cooldown", "priority": 20, "updated_at": 30, "next_sync_after": 0},
            {"identity_key": "c", "status": "failed", "priority": 10, "updated_at": 10, "next_sync_after": 0},
            {"identity_key": "future", "status": "pending", "priority": 99, "updated_at": 1, "next_sync_after": now + 3600},
            {"identity_key": "disabled", "status": "disabled", "priority": 100, "updated_at": 1, "next_sync_after": None},
        ])
        repo = JjcSyncRepo(db=db)

        enqueued = await repo.enqueue_next_roles(
            limit=3,
            mode="incremental",
            source="qq_start",
            batch_id="batch-1",
        )

        self.assertEqual([doc["identity_key"] for doc in enqueued], ["b", "c", "a"])
        self.assertEqual([doc["status"] for doc in enqueued], ["queued", "queued", "queued"])
        self.assertEqual(enqueued[0]["queue_mode"], "incremental")
        self.assertEqual(enqueued[0]["queue_source"], "qq_start")
        self.assertEqual(enqueued[0]["queue_batch_id"], "batch-1")
        self.assertIsNone(enqueued[0]["lease_owner"])

    async def test_enqueue_role_sets_specific_non_disabled_role_to_queued(self) -> None:
        db = MemoryDb(roles=[
            {
                "identity_key": "role-1",
                "status": "pending",
                "priority": 1,
                "fail_count": 4,
            },
            {
                "identity_key": "syncing",
                "status": "syncing",
                "lease_owner": "old-worker",
                "lease_expires_at": 123.0,
            },
            {"identity_key": "disabled", "status": "disabled"},
        ])
        repo = JjcSyncRepo(db=db)

        queued = await repo.enqueue_role(
            "role-1",
            mode="full",
            source="manual_add",
            batch_id="batch-2",
        )
        syncing = await repo.enqueue_role("syncing", mode="full", source="manual_add")
        disabled = await repo.enqueue_role("disabled", mode="full", source="manual_add")

        self.assertIsNotNone(queued)
        assert queued is not None
        self.assertEqual(queued["status"], "queued")
        self.assertEqual(queued["queue_source"], "manual_add")
        self.assertEqual(queued["queue_batch_id"], "batch-2")
        self.assertIsNone(queued["lease_owner"])
        self.assertIsNone(queued["lease_expires_at"])
        self.assertEqual(queued["fail_count"], 4)
        self.assertIsNone(syncing)
        syncing_doc = db.jjc_sync_role_queue.docs[1]
        self.assertEqual(syncing_doc["status"], "syncing")
        self.assertEqual(syncing_doc["lease_owner"], "old-worker")
        self.assertEqual(syncing_doc["lease_expires_at"], 123.0)
        self.assertIsNone(disabled)

    async def test_recover_expired_role_lease_requeues_for_workers(self) -> None:
        now = time.time()
        db = MemoryDb(
            roles=[
                {
                    "identity_key": "expired",
                    "status": "syncing",
                    "lease_owner": "worker-old",
                    "lease_expires_at": now - 1,
                },
                {
                    "identity_key": "active",
                    "status": "syncing",
                    "lease_owner": "worker-live",
                    "lease_expires_at": now + 3600,
                },
            ],
            matches=[
                {
                    "match_id": 1,
                    "status": "detail_syncing",
                    "lease_owner": "worker-old",
                    "lease_expires_at": now - 1,
                }
            ],
        )
        repo = JjcSyncRepo(db=db)

        recovered = await repo.recover_expired_leases()

        self.assertEqual(recovered, 2)
        expired_role = db.jjc_sync_role_queue.docs[0]
        active_role = db.jjc_sync_role_queue.docs[1]
        expired_match = db.jjc_sync_match_seen.docs[0]
        self.assertEqual(expired_role["status"], "queued")
        self.assertIsNone(expired_role["lease_owner"])
        self.assertIsNone(expired_role["lease_expires_at"])
        self.assertEqual(expired_role["interrupted_reason"], "lease_expired")
        self.assertIn("queued_at", expired_role)
        self.assertEqual(active_role["status"], "syncing")
        self.assertEqual(active_role["lease_owner"], "worker-live")
        self.assertEqual(expired_match["status"], "discovered")
        self.assertIsNone(expired_match["lease_owner"])

    async def test_claim_queued_role_sorts_by_priority_then_queued_at(self) -> None:
        db = MemoryDb(roles=[
            {"identity_key": "low", "status": "queued", "priority": 1, "queued_at": 1},
            {"identity_key": "newer-high", "status": "queued", "priority": 9, "queued_at": 20},
            {"identity_key": "older-high", "status": "queued", "priority": 9, "queued_at": 10},
        ])
        repo = JjcSyncRepo(db=db)

        claimed = await repo.claim_queued_role(lease_owner="worker-1", lease_seconds=60)

        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed["identity_key"], "older-high")
        self.assertEqual(claimed["status"], "syncing")
        self.assertEqual(claimed["lease_owner"], "worker-1")
        self.assertGreater(claimed["lease_expires_at"], time.time())

    async def test_release_role_interrupted_preserves_fail_count(self) -> None:
        db = MemoryDb(roles=[
            {
                "identity_key": "role-1",
                "status": "syncing",
                "fail_count": 7,
                "lease_owner": "worker-1",
                "lease_expires_at": 123.0,
                "queue_source": "cli",
                "queue_batch_id": "batch-old",
            }
        ])
        repo = JjcSyncRepo(db=db)

        released = await repo.release_role_interrupted("role-1", "ticket expired", requeue=True)

        self.assertTrue(released)
        doc = db.jjc_sync_role_queue.docs[0]
        self.assertEqual(doc["status"], "queued")
        self.assertEqual(doc["fail_count"], 7)
        self.assertIsNone(doc["lease_owner"])
        self.assertIsNone(doc["lease_expires_at"])
        self.assertEqual(doc["interrupted_reason"], "ticket expired")
        self.assertEqual(doc["queue_source"], "interrupted")
        self.assertIsNone(doc["queue_batch_id"])

    async def test_release_success_requires_matching_lease_owner_when_provided(self) -> None:
        db = MemoryDb(roles=[
            {
                "identity_key": "role-1",
                "status": "syncing",
                "lease_owner": "worker-new",
                "lease_expires_at": time.time() + 300,
            }
        ])
        repo = JjcSyncRepo(db=db)

        stale_released = await repo.release_role_success(
            "role-1",
            full_synced_until_time=100,
            lease_owner="worker-old",
        )
        fresh_released = await repo.release_role_success(
            "role-1",
            full_synced_until_time=100,
            lease_owner="worker-new",
        )

        self.assertFalse(stale_released)
        self.assertTrue(fresh_released)
        doc = db.jjc_sync_role_queue.docs[0]
        self.assertEqual(doc["status"], "cooldown")
        self.assertIsNone(doc["lease_owner"])
        self.assertEqual(doc["full_synced_until_time"], 100)
        self.assertEqual(doc["priority"], 0)

    async def test_enqueue_ranking_member_sets_priority_one_and_queues_role(self) -> None:
        db = MemoryDb()
        repo = JjcSyncRepo(db=db)

        queued = await repo.enqueue_ranking_member(
            {
                "server": "梦江南",
                "name": "角色A",
                "global_role_id": "SK01-A",
                "role_id": "rid-a",
                "zone": "zone-a",
            },
            season_id="赛季",
            season_start_time=1776960000,
            priority=1,
            source="ranking_stats",
            batch_id="ranking_stats:1",
        )

        self.assertIsNotNone(queued)
        assert queued is not None
        self.assertEqual(queued["status"], "queued")
        self.assertEqual(queued["priority"], 1)
        self.assertEqual(queued["queue_source"], "ranking_stats")
        self.assertEqual(queued["queue_batch_id"], "ranking_stats:1")
        self.assertEqual(queued["season_id"], "赛季")

    async def test_enqueue_ranking_member_skips_existing_priority_at_least_one(self) -> None:
        db = MemoryDb(roles=[
            {
                "identity_key": "global:SK01-A",
                "server": "梦江南",
                "name": "角色A",
                "normalized_server": "梦江南",
                "normalized_name": "角色a",
                "global_role_id": "SK01-A",
                "status": "cooldown",
                "priority": 100,
                "next_sync_after": None,
            }
        ])
        repo = JjcSyncRepo(db=db)

        queued = await repo.enqueue_ranking_member(
            {
                "server": "梦江南",
                "name": "角色A",
                "global_role_id": "SK01-A",
            },
            priority=1,
            source="ranking_stats",
            batch_id="ranking_stats:2",
        )

        self.assertIsNone(queued)
        doc = db.jjc_sync_role_queue.docs[0]
        self.assertEqual(doc["status"], "cooldown")
        self.assertEqual(doc["priority"], 100)
        self.assertNotIn("priority_updated_by", doc)

    async def test_enqueue_ranking_member_raises_existing_zero_priority_to_one(self) -> None:
        db = MemoryDb(roles=[
            {
                "identity_key": "global:SK01-A",
                "server": "梦江南",
                "name": "角色A",
                "normalized_server": "梦江南",
                "normalized_name": "角色a",
                "global_role_id": "SK01-A",
                "status": "cooldown",
                "priority": 0,
                "next_sync_after": None,
            }
        ])
        repo = JjcSyncRepo(db=db)

        queued = await repo.enqueue_ranking_member(
            {
                "server": "梦江南",
                "name": "角色A",
                "global_role_id": "SK01-A",
            },
            priority=1,
            source="ranking_stats",
            batch_id="ranking_stats:3",
        )

        self.assertIsNotNone(queued)
        doc = db.jjc_sync_role_queue.docs[0]
        self.assertEqual(doc["status"], "queued")
        self.assertEqual(doc["priority"], 1)
        self.assertEqual(doc["priority_updated_by"], "ranking_stats")

    async def test_renew_role_lease_requires_current_owner(self) -> None:
        now = time.time()
        db = MemoryDb(roles=[
            {
                "identity_key": "role-1",
                "status": "syncing",
                "lease_owner": "worker-new",
                "lease_expires_at": now + 300,
            }
        ])
        repo = JjcSyncRepo(db=db)

        stale_renewed = await repo.renew_role_lease(
            identity_key="role-1",
            lease_owner="worker-old",
            lease_seconds=60,
        )
        fresh_renewed = await repo.renew_role_lease(
            identity_key="role-1",
            lease_owner="worker-new",
            lease_seconds=60,
        )

        self.assertFalse(stale_renewed)
        self.assertTrue(fresh_renewed)
        self.assertGreater(db.jjc_sync_role_queue.docs[0]["lease_expires_at"], now)

    async def test_expired_lease_cannot_renew(self) -> None:
        now = time.time()
        db = MemoryDb(roles=[
            {
                "identity_key": "role-1",
                "status": "syncing",
                "lease_owner": "worker-new",
                "lease_expires_at": now - 1,
            }
        ])
        repo = JjcSyncRepo(db=db)

        renewed = await repo.renew_role_lease(
            identity_key="role-1",
            lease_owner="worker-new",
            lease_seconds=60,
        )

        self.assertFalse(renewed)

    async def test_expired_lease_cannot_release_success(self) -> None:
        now = time.time()
        db = MemoryDb(roles=[
            {
                "identity_key": "role-1",
                "status": "syncing",
                "lease_owner": "worker-new",
                "lease_expires_at": now - 1,
            }
        ])
        repo = JjcSyncRepo(db=db)

        released = await repo.release_role_success(
            "role-1",
            full_synced_until_time=100,
            lease_owner="worker-new",
        )

        self.assertFalse(released)

    async def test_expired_lease_cannot_release_failure(self) -> None:
        now = time.time()
        db = MemoryDb(roles=[
            {
                "identity_key": "role-1",
                "status": "syncing",
                "lease_owner": "worker-new",
                "lease_expires_at": now - 1,
                "fail_count": 0,
            }
        ])
        repo = JjcSyncRepo(db=db)

        released = await repo.release_role_failure(
            "role-1",
            "boom",
            lease_owner="worker-new",
        )

        self.assertFalse(released)

    async def test_expired_lease_cannot_mark_detail_saved(self) -> None:
        now = time.time()
        db = MemoryDb(matches=[
            {
                "match_id": 1001,
                "status": "detail_syncing",
                "lease_owner": "worker-new",
                "lease_expires_at": now - 1,
            }
        ])
        repo = JjcSyncRepo(db=db)

        result = await repo.mark_match_detail_saved(1001, lease_owner="worker-new")

        self.assertFalse(result)

    async def test_expired_lease_cannot_mark_detail_unavailable(self) -> None:
        now = time.time()
        db = MemoryDb(matches=[
            {
                "match_id": 1001,
                "status": "detail_syncing",
                "lease_owner": "worker-new",
                "lease_expires_at": now - 1,
            }
        ])
        repo = JjcSyncRepo(db=db)

        result = await repo.mark_match_detail_unavailable(1001, reason="x", code=1, lease_owner="worker-new")

        self.assertFalse(result)

    async def test_expired_lease_cannot_renew_match_detail(self) -> None:
        now = time.time()
        db = MemoryDb(matches=[
            {
                "match_id": 1001,
                "status": "detail_syncing",
                "lease_owner": "worker-new",
                "lease_expires_at": now - 1,
            }
        ])
        repo = JjcSyncRepo(db=db)

        result = await repo.renew_match_detail_lease(1001, lease_owner="worker-new", lease_seconds=60)

        self.assertFalse(result)

    async def test_expired_lease_cannot_update_identity_fields_and_key(self) -> None:
        now = time.time()
        db = MemoryDb(roles=[
            {
                "identity_key": "name:梦江南:角色A",
                "normalized_server": "梦江南",
                "normalized_name": "角色A",
                "status": "syncing",
                "lease_owner": "worker-new",
                "lease_expires_at": now - 1,
            }
        ])
        repo = JjcSyncRepo(db=db)

        result = await repo.update_role_identity_fields_and_key(
            identity_key="name:梦江南:角色A",
            global_id="99999",
            lease_owner="worker-new",
        )

        self.assertIsNone(result)

    async def test_expired_lease_cannot_update_identity_fields(self) -> None:
        now = time.time()
        db = MemoryDb(roles=[
            {
                "identity_key": "name:梦江南:角色A",
                "status": "syncing",
                "lease_owner": "worker-new",
                "lease_expires_at": now - 1,
            }
        ])
        repo = JjcSyncRepo(db=db)

        result = await repo.update_role_identity_fields(
            identity_key="name:梦江南:角色A",
            global_role_id="SK01-abc",
            lease_owner="worker-new",
        )

        self.assertFalse(result)
        self.assertNotIn("global_role_id", db.jjc_sync_role_queue.docs[0])

    async def test_expired_lease_cannot_mark_detail_failed(self) -> None:
        now = time.time()
        db = MemoryDb(matches=[
            {
                "match_id": 1001,
                "status": "detail_syncing",
                "lease_owner": "worker-new",
                "lease_expires_at": now - 1,
                "fail_count": 0,
            }
        ])
        repo = JjcSyncRepo(db=db)

        result = await repo.mark_match_detail_failed(1001, "err", lease_owner="worker-new")

        self.assertFalse(result)

    async def test_update_role_priority_records_actor(self) -> None:
        db = MemoryDb(roles=[{"identity_key": "role-1", "status": "queued", "priority": 1}])
        repo = JjcSyncRepo(db=db)

        updated = await repo.update_role_priority("role-1", 500, updated_by="admin")

        self.assertTrue(updated)
        doc = db.jjc_sync_role_queue.docs[0]
        self.assertEqual(doc["priority"], 500)
        self.assertEqual(doc["priority_updated_by"], "admin")
        self.assertIn("priority_updated_at", doc)

    async def test_list_queue_paginates_and_filters_status(self) -> None:
        db = MemoryDb(roles=[
            {
                "identity_key": "a",
                "status": "queued",
                "queue_mode": "full",
                "priority": 1,
                "queued_at": 1,
                "updated_at": 1,
            },
            {
                "identity_key": "b",
                "status": "queued",
                "queue_mode": "incremental",
                "priority": 9,
                "queued_at": 2,
                "updated_at": 2,
            },
            {
                "identity_key": "c",
                "status": "pending",
                "queue_mode": "incremental",
                "priority": 99,
                "queued_at": None,
                "updated_at": 3,
            },
        ])
        repo = JjcSyncRepo(db=db)

        page = await repo.list_queue(status="queued", page=1, page_size=1)

        self.assertEqual(page["total"], 2)
        self.assertEqual(page["page"], 1)
        self.assertEqual(page["page_size"], 1)
        self.assertTrue(page["has_more"])
        self.assertEqual([doc["identity_key"] for doc in page["items"]], ["b"])

    async def test_list_queue_filters_mode(self) -> None:
        db = MemoryDb(roles=[
            {
                "identity_key": "a",
                "status": "queued",
                "queue_mode": "full",
                "priority": 1,
                "queued_at": 1,
                "updated_at": 1,
            },
            {
                "identity_key": "b",
                "status": "queued",
                "queue_mode": "incremental",
                "priority": 9,
                "queued_at": 2,
                "updated_at": 2,
            },
            {
                "identity_key": "c",
                "status": "pending",
                "queue_mode": "incremental",
                "priority": 99,
                "queued_at": None,
                "updated_at": 3,
            },
        ])
        repo = JjcSyncRepo(db=db)

        page = await repo.list_queue(mode="incremental")

        self.assertEqual(page["total"], 2)
        self.assertEqual([doc["identity_key"] for doc in page["items"]], ["c", "b"])

    async def test_list_queue_filters_server_and_name(self) -> None:
        db = MemoryDb(roles=[
            {
                "identity_key": "a",
                "server": "梦江南",
                "normalized_server": "梦江南",
                "name": "角色A",
                "normalized_name": "角色a",
                "status": "queued",
                "priority": 1,
                "queued_at": 1,
                "updated_at": 1,
            },
            {
                "identity_key": "b",
                "server": "唯我独尊",
                "normalized_server": "唯我独尊",
                "name": "角色B",
                "normalized_name": "角色b",
                "status": "queued",
                "priority": 9,
                "queued_at": 2,
                "updated_at": 2,
            },
        ])
        repo = JjcSyncRepo(db=db)

        page = await repo.list_queue(status="queued", server="梦江", name="角色A")

        self.assertEqual(page["total"], 1)
        self.assertEqual([doc["identity_key"] for doc in page["items"]], ["a"])

    async def test_worker_register_heartbeat_stop_and_list(self) -> None:
        db = MemoryDb()
        repo = JjcSyncRepo(db=db)

        registered = await repo.register_worker(
            worker_id="worker-1",
            mode="incremental",
            pid=123,
            host="host-a",
        )
        heartbeat = await repo.heartbeat_worker(
            worker_id="worker-1",
            status="syncing",
            current_identity_key="role-1",
            current_server="server-a",
            current_name="role-a",
            last_result={"ok": True},
        )
        workers = await repo.list_workers()
        stopped = await repo.stop_worker("worker-1", reason="done")

        self.assertTrue(registered)
        self.assertTrue(heartbeat)
        self.assertEqual(len(workers), 1)
        self.assertEqual(workers[0]["status"], "syncing")
        self.assertEqual(workers[0]["current_identity_key"], "role-1")
        self.assertTrue(stopped)
        self.assertEqual(db.jjc_sync_workers.docs[0]["status"], "stopped")
        self.assertEqual(db.jjc_sync_workers.docs[0]["stop_reason"], "done")

    async def test_worker_reregister_refreshes_stable_worker_slot(self) -> None:
        db = MemoryDb()
        repo = JjcSyncRepo(db=db)

        await repo.register_worker(
            worker_id="bot:host-a:0",
            mode="incremental_or_full",
            pid=100,
            host="host-a",
        )
        first_started_at = db.jjc_sync_workers.docs[0]["started_at"]
        await repo.heartbeat_worker(
            worker_id="bot:host-a:0",
            status="syncing",
            current_identity_key="role-1",
            current_server="server-a",
            current_name="role-a",
            last_error="old-error",
        )

        await repo.register_worker(
            worker_id="bot:host-a:0",
            mode="incremental_or_full",
            pid=101,
            host="host-a",
        )

        self.assertEqual(len(db.jjc_sync_workers.docs), 1)
        worker = db.jjc_sync_workers.docs[0]
        self.assertEqual(worker["worker_id"], "bot:host-a:0")
        self.assertEqual(worker["status"], "running")
        self.assertEqual(worker["pid"], 101)
        self.assertGreaterEqual(worker["started_at"], first_started_at)
        self.assertIsNone(worker["current_identity_key"])
        self.assertIsNone(worker["current_server"])
        self.assertIsNone(worker["current_name"])
        self.assertEqual(worker["last_error"], "")

    async def test_get_pause_state_returns_details_without_changing_get_paused(self) -> None:
        db = MemoryDb(states=[
            {"key": "global", "paused": True, "reason": "maintenance", "updated_at": 123.0}
        ])
        repo = JjcSyncRepo(db=db)

        state = await repo.get_pause_state()
        paused = await repo.get_paused()

        self.assertEqual(state, {"paused": True, "reason": "maintenance", "updated_at": 123.0})
        self.assertTrue(paused)

    async def test_expired_owner_cannot_release_role_interrupted_with_lease_owner(self) -> None:
        now = time.time()
        db = MemoryDb(roles=[
            {
                "identity_key": "role-1",
                "status": "syncing",
                "lease_owner": "worker-new",
                "lease_expires_at": now - 1,
            }
        ])
        repo = JjcSyncRepo(db=db)

        released = await repo.release_role_interrupted(
            "role-1",
            "ticket expired",
            requeue=True,
            lease_owner="worker-new",
        )

        self.assertFalse(released)

    async def test_expired_owner_cannot_release_match_detail_interrupted_with_lease_owner(self) -> None:
        now = time.time()
        db = MemoryDb(matches=[
            {
                "match_id": 1001,
                "status": "detail_syncing",
                "lease_owner": "worker-new",
                "lease_expires_at": now - 1,
            }
        ])
        repo = JjcSyncRepo(db=db)

        released = await repo.release_match_detail_interrupted(
            1001,
            reason="global pause",
            lease_owner="worker-new",
        )

        self.assertFalse(released)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
import time
from typing import Any, Dict, List
from unittest.mock import MagicMock, AsyncMock, patch

from src.services.jx3.jjc_ranking import JjcRankingService
from src.storage.mongo_repos.jjc_ranking_stats_repo import JjcRankingStatsRepo


class _MockCursor:
    """Async-iterable mock cursor with Motor-style chaining (sort/skip/limit)."""

    def __init__(self, items: List[Dict[str, Any]]):
        self._items = list(items)

    def sort(self, *args: Any, **kwargs: Any) -> "_MockCursor":
        return self

    def skip(self, n: int) -> "_MockCursor":
        return self

    def limit(self, n: int) -> "_MockCursor":
        return self

    def __aiter__(self):
        self._iter = iter(self._items)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


def _make_mock_collection(
    find_results: object = None,
    count: object = None,
) -> MagicMock:
    col = MagicMock()
    col.update_one = AsyncMock()
    col.find_one = AsyncMock()
    if find_results is not None:
        col.find = MagicMock(return_value=_MockCursor(find_results))
    if count is not None:
        col.count_documents = AsyncMock(return_value=count)
    return col


class TestListTimestampsUnpaged(unittest.IsolatedAsyncioTestCase):
    async def test_returns_timestamps_sorted_newest_first(self):
        docs = [{"timestamp": 300}, {"timestamp": 200}, {"timestamp": 100}]
        col = _make_mock_collection(find_results=docs)
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.list_timestamps()

        assert result == [300, 200, 100]

    async def test_empty_collection_returns_empty_list(self):
        col = _make_mock_collection(find_results=[])
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.list_timestamps()

        assert result == []

    async def test_failure_returns_empty_list(self):
        col = MagicMock()
        col.find = MagicMock(side_effect=RuntimeError("boom"))
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.list_timestamps()

        assert result == []


class TestListTimestampsPaged(unittest.IsolatedAsyncioTestCase):
    async def test_first_page_returns_correct_structure(self):
        docs = [{"timestamp": 500}, {"timestamp": 400}]
        col = _make_mock_collection(find_results=docs, count=5)
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.list_timestamps(page=1, page_size=2)

        assert result["items"] == [500, 400]
        assert result["page"] == 1
        assert result["page_size"] == 2
        assert result["total"] == 5
        assert result["has_more"] is True

    async def test_last_page_has_more_false(self):
        docs = [{"timestamp": 200}]
        col = _make_mock_collection(find_results=docs, count=5)
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.list_timestamps(page=3, page_size=2)

        assert result["items"] == [200]
        assert result["total"] == 5
        assert result["has_more"] is False

    async def test_failure_returns_empty_page_dict(self):
        col = MagicMock()
        col.find = MagicMock(side_effect=RuntimeError("boom"))
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.list_timestamps(page=1, page_size=10)

        assert result["items"] == []
        assert result["page"] == 1
        assert result["page_size"] == 10
        assert result["total"] == 0
        assert result["has_more"] is False


class TestListTimestampsWithMeta(unittest.IsolatedAsyncioTestCase):
    async def test_with_meta_returns_paged_dict_with_item_dicts(self):
        docs = [
            {
                "timestamp": 300,
                "generated_at": 1000.0,
                "ranking_cache_time": 1000.5,
                "default_week": 3,
                "current_season": "S3",
                "week_info": "第3周",
            },
            {
                "timestamp": 200,
                "generated_at": 900.0,
                "ranking_cache_time": 900.5,
                "default_week": 2,
                "current_season": "S2",
                "week_info": "第2周",
            },
        ]
        col = _make_mock_collection(find_results=docs, count=2)
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.list_timestamps(with_meta=True)

        assert isinstance(result, dict)
        assert result["page"] == 1
        assert result["page_size"] == 100
        assert result["total"] == 2
        assert result["has_more"] is False
        assert len(result["items"]) == 2
        assert result["items"][0]["timestamp"] == 300
        assert result["items"][0]["generated_at"] == 1000.0
        assert result["items"][0]["is_settlement"] is False
        assert result["items"][0]["snapshot_kind"] == "daily"

    async def test_with_meta_derives_is_settlement_from_week_info(self):
        docs = [
            {
                "timestamp": 100,
                "generated_at": 500.0,
                "ranking_cache_time": 500.5,
                "default_week": 1,
                "current_season": "S1",
                "week_info": "第1周（结算周）",
            },
        ]
        col = _make_mock_collection(find_results=docs, count=1)
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.list_timestamps(with_meta=True)

        item = result["items"][0]
        assert item["is_settlement"] is True
        assert item["snapshot_kind"] == "settlement"

    async def test_with_meta_daily_week_info(self):
        docs = [
            {
                "timestamp": 200,
                "generated_at": 600.0,
                "ranking_cache_time": 600.5,
                "default_week": 2,
                "current_season": "S2",
                "week_info": "第2周",
            },
        ]
        col = _make_mock_collection(find_results=docs, count=1)
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.list_timestamps(with_meta=True)

        item = result["items"][0]
        assert item["is_settlement"] is False
        assert item["snapshot_kind"] == "daily"

    async def test_with_meta_tolerates_missing_fields(self):
        docs = [
            {
                "timestamp": 400,
            },
        ]
        col = _make_mock_collection(find_results=docs, count=1)
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.list_timestamps(with_meta=True)

        item = result["items"][0]
        assert item["timestamp"] == 400
        assert item["generated_at"] is None
        assert item["ranking_cache_time"] is None
        assert item["default_week"] is None
        assert item["current_season"] is None
        assert item["week_info"] is None
        assert item["is_settlement"] is False
        assert item["snapshot_kind"] == "daily"

    async def test_with_meta_null_week_info_treated_as_empty(self):
        docs = [
            {
                "timestamp": 500,
                "week_info": None,
            },
        ]
        col = _make_mock_collection(find_results=docs, count=1)
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.list_timestamps(with_meta=True)

        item = result["items"][0]
        assert item["is_settlement"] is False
        assert item["snapshot_kind"] == "daily"

    async def test_with_meta_respects_custom_pagination(self):
        docs = [{"timestamp": 500}]
        col = _make_mock_collection(find_results=docs, count=10)
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.list_timestamps(page=2, page_size=5, with_meta=True)

        assert result["page"] == 2
        assert result["page_size"] == 5
        assert result["total"] == 10

    async def test_with_meta_failure_returns_empty_page(self):
        col = MagicMock()
        col.find = MagicMock(side_effect=RuntimeError("boom"))
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.list_timestamps(with_meta=True)

        assert result["items"] == []
        assert result["page"] == 1
        assert result["page_size"] == 100
        assert result["total"] == 0
        assert result["has_more"] is False

    async def test_with_meta_false_unpaged_still_returns_int_list(self):
        docs = [{"timestamp": 300}, {"timestamp": 200}]
        col = _make_mock_collection(find_results=docs)
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.list_timestamps(with_meta=False)

        assert result == [300, 200]

    async def test_with_meta_false_paged_still_returns_int_items(self):
        docs = [{"timestamp": 500}]
        col = _make_mock_collection(find_results=docs, count=1)
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.list_timestamps(page=1, page_size=10, with_meta=False)

        assert result["items"] == [500]


class TestSaveAndLoadSummary(unittest.IsolatedAsyncioTestCase):
    async def test_save_snapshot_calls_upsert_summary_and_details(self):
        summary_col = _make_mock_collection()
        detail_col = _make_mock_collection()
        db = MagicMock()
        db.jjc_ranking_stat_summaries = summary_col
        db.jjc_ranking_stat_details = detail_col

        repo = JjcRankingStatsRepo(db=db)
        summary_payload = {
            "generated_at": 1234567890.0,
            "ranking_cache_time": 1234567890.5,
            "default_week": 12,
            "current_season": "S12",
            "week_info": "第12周",
            "kungfu_statistics": {"花间游": {"count": 5}},
        }
        detail_payloads = [
            {
                "range": "top_200",
                "lane": "dps",
                "kungfu": "花间游",
                "members": [{"name": "Alice", "score": 2800}],
            }
        ]

        await repo.save_snapshot(1777426656, summary_payload, detail_payloads)

        summary_col.update_one.assert_called_once()
        summary_args, _ = summary_col.update_one.call_args
        assert summary_args[0] == {"timestamp": 1777426656}
        assert summary_args[1]["$set"]["source"] == "ranking_job"
        assert summary_args[1]["$set"]["schema_version"] == 1

        detail_col.update_one.assert_called_once()
        detail_args, _ = detail_col.update_one.call_args
        assert detail_args[0] == {
            "timestamp": 1777426656,
            "range": "top_200",
            "lane": "dps",
            "kungfu": "花间游",
        }
        assert detail_args[1]["$set"]["members"] == [{"name": "Alice", "score": 2800}]

    async def test_upsert_summary_uses_update_one_with_upsert(self):
        col = _make_mock_collection()
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        payload = {
            "generated_at": 1234567890.0,
            "ranking_cache_time": 1234567890.5,
            "default_week": 1,
            "current_season": "S1",
            "week_info": "第1周",
            "kungfu_statistics": {},
        }
        await repo.upsert_summary(100, payload, source="migration")

        col.update_one.assert_called_once()
        call_args, call_kwargs = col.update_one.call_args
        assert call_args[0] == {"timestamp": 100}
        assert call_kwargs.get("upsert") is True

    async def test_upsert_summary_suppresses_errors_by_default(self):
        col = _make_mock_collection()
        col.update_one = AsyncMock(side_effect=RuntimeError("boom"))
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)

        await repo.upsert_summary(100, {})

    async def test_upsert_summary_strict_mode_raises_errors(self):
        col = _make_mock_collection()
        col.update_one = AsyncMock(side_effect=RuntimeError("boom"))
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db, suppress_errors=False)

        with self.assertRaises(RuntimeError):
            await repo.upsert_summary(100, {})

    async def test_load_summary_returns_doc_without_id(self):
        doc = {"_id": "abc123", "timestamp": 100, "default_week": 1, "current_season": "S1"}
        col = _make_mock_collection()
        col.find_one = AsyncMock(return_value=dict(doc))
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.load_summary(100)

        assert result is not None
        assert "_id" not in result
        assert result["timestamp"] == 100
        assert result["default_week"] == 1

    async def test_load_summary_not_found_returns_none(self):
        col = _make_mock_collection()
        col.find_one = AsyncMock(return_value=None)
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.load_summary(999)

        assert result is None

    async def test_load_summary_failure_returns_none(self):
        col = MagicMock()
        col.find_one = AsyncMock(side_effect=RuntimeError("boom"))
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.load_summary(100)

        assert result is None

    async def test_load_summary_strict_mode_raises_errors(self):
        col = MagicMock()
        col.find_one = AsyncMock(side_effect=RuntimeError("boom"))
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db, suppress_errors=False)

        with self.assertRaises(RuntimeError):
            await repo.load_summary(100)


class TestSaveAndLoadDetail(unittest.IsolatedAsyncioTestCase):
    async def test_upsert_detail_uses_update_one_with_upsert(self):
        col = _make_mock_collection()
        db = MagicMock()
        db.jjc_ranking_stat_details = col

        repo = JjcRankingStatsRepo(db=db)
        await repo.upsert_detail(200, "top_200", "dps", "花间游", [{"name": "Bob"}])

        col.update_one.assert_called_once()
        call_args, call_kwargs = col.update_one.call_args
        assert call_args[0] == {
            "timestamp": 200,
            "range": "top_200",
            "lane": "dps",
            "kungfu": "花间游",
        }
        assert call_args[1]["$set"]["members"] == [{"name": "Bob"}]
        assert call_kwargs.get("upsert") is True

    async def test_load_detail_returns_doc_without_id(self):
        doc = {
            "_id": "xyz789",
            "timestamp": 200,
            "range": "top_200",
            "lane": "dps",
            "kungfu": "花间游",
            "members": [{"name": "Carol"}],
        }
        col = _make_mock_collection()
        col.find_one = AsyncMock(return_value=dict(doc))
        db = MagicMock()
        db.jjc_ranking_stat_details = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.load_detail(200, "top_200", "dps", "花间游")

        assert result is not None
        assert "_id" not in result
        assert result["members"] == [{"name": "Carol"}]
        col.find_one.assert_called_once_with(
            {
                "timestamp": 200,
                "range": "top_200",
                "lane": "dps",
                "kungfu": "花间游",
            }
        )

    async def test_load_detail_not_found_returns_none(self):
        col = _make_mock_collection()
        col.find_one = AsyncMock(return_value=None)
        db = MagicMock()
        db.jjc_ranking_stat_details = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.load_detail(999, "top_200", "dps", "花间游")

        assert result is None

    async def test_load_detail_failure_returns_none(self):
        col = MagicMock()
        col.find_one = AsyncMock(side_effect=RuntimeError("boom"))
        db = MagicMock()
        db.jjc_ranking_stat_details = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.load_detail(100, "top_200", "dps", "花间游")

        assert result is None


class TestStripId(unittest.IsolatedAsyncioTestCase):
    async def test_id_removed_from_load_summary(self):
        doc = {"_id": "fake_object_id", "timestamp": 100, "default_week": 1}
        col = _make_mock_collection()
        col.find_one = AsyncMock(return_value=dict(doc))
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.load_summary(100)

        assert result is not None
        assert "_id" not in result
        assert "timestamp" in result

    async def test_id_removed_from_load_detail(self):
        doc = {
            "_id": "fake_object_id",
            "timestamp": 200,
            "range": "top_200",
            "lane": "dps",
            "kungfu": "花间游",
            "members": [{"name": "Dan"}],
        }
        col = _make_mock_collection()
        col.find_one = AsyncMock(return_value=dict(doc))
        db = MagicMock()
        db.jjc_ranking_stat_details = col

        repo = JjcRankingStatsRepo(db=db)
        result = await repo.load_detail(200, "top_200", "dps", "花间游")

        assert result is not None
        assert "_id" not in result

    async def test_strip_id_does_not_mutate_source_buffer(self):
        doc = {"_id": "abc", "timestamp": 100, "value": "hello"}
        col = _make_mock_collection()
        col.find_one = AsyncMock(return_value=dict(doc))
        db = MagicMock()
        db.jjc_ranking_stat_summaries = col

        repo = JjcRankingStatsRepo(db=db)
        result1 = await repo.load_summary(100)
        assert result1 is not None
        assert "_id" not in result1

        col.find_one = AsyncMock(return_value=dict(doc))
        result2 = await repo.load_summary(100)
        assert result2 is not None
        assert "_id" not in result2


class TestSaveSnapshotBatch(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_details_all_upserted(self):
        summary_col = _make_mock_collection()
        detail_col = _make_mock_collection()
        db = MagicMock()
        db.jjc_ranking_stat_summaries = summary_col
        db.jjc_ranking_stat_details = detail_col

        repo = JjcRankingStatsRepo(db=db)
        summary_payload = {
            "generated_at": 1234567890.0,
            "ranking_cache_time": 1234567890.5,
            "default_week": 12,
            "current_season": "S12",
            "week_info": "第12周",
            "kungfu_statistics": {},
        }
        detail_payloads = [
            {
                "range": "top_200",
                "lane": "dps",
                "kungfu": "花间游",
                "members": [{"name": "Alice"}],
            },
            {
                "range": "top_200",
                "lane": "dps",
                "kungfu": "傲血战意",
                "members": [{"name": "Bob"}],
            },
            {
                "range": "top_200",
                "lane": "heal",
                "kungfu": "离经易道",
                "members": [{"name": "Carol"}],
            },
        ]

        await repo.save_snapshot(1777426656, summary_payload, detail_payloads)

        assert summary_col.update_one.call_count == 1
        assert detail_col.update_one.call_count == 3


class TestRankingStatsSyncQueue(unittest.IsolatedAsyncioTestCase):
    async def test_save_ranking_stats_task_enqueues_members_for_sync(self):
        saved_snapshots: List[Dict[str, Any]] = []
        sync_instances: List[Any] = []

        class FakeStatsRepo:
            async def save_snapshot(self, **kwargs: Any) -> None:
                saved_snapshots.append(kwargs)

        class FakeSyncRepo:
            def __init__(self) -> None:
                self.calls: List[Dict[str, Any]] = []
                sync_instances.append(self)

            async def enqueue_ranking_member(self, member: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
                self.calls.append({"member": member, "kwargs": kwargs})
                return {"status": "queued"}

        service = JjcRankingService(
            token="",
            ticket="",
            jjc_query_url="",
            arena_time_tag_url="",
            arena_ranking_url="",
            match_detail_url="",
            jjc_ranking_cache_duration=0,
            kungfu_cache_duration=0,
            current_season="S12",
            current_season_start="2026-04-24",
            kungfu_healer_list=[],
            kungfu_dps_list=[],
            kungfu_pinyin_to_chinese={},
            tuilan_request=lambda url, payload: {},
            defget_get=AsyncMock(),
        )
        detail_payloads = [
            {
                "range": "top_200",
                "lane": "dps",
                "kungfu": "花间游",
                "members": [
                    {
                        "server": "梦江南",
                        "name": "角色A",
                        "global_role_id": "SK01-A",
                        "role_id": "rid-a",
                        "zone": "zone-a",
                    }
                ],
            }
        ]

        with patch("src.services.jx3.jjc_ranking.JjcRankingStatsRepo", FakeStatsRepo), patch(
            "src.services.jx3.jjc_ranking.JjcSyncRepo",
            FakeSyncRepo,
        ):
            task = service._save_ranking_stats_to_mongo(
                timestamp=1777426656,
                summary_payload={"generated_at": 1},
                detail_payloads=detail_payloads,
            )
            assert task is not None
            await task

        assert len(saved_snapshots) == 1
        assert len(sync_instances) == 1
        assert sync_instances[0].calls[0]["member"]["name"] == "角色A"
        assert sync_instances[0].calls[0]["kwargs"]["priority"] == 1
        assert sync_instances[0].calls[0]["kwargs"]["source"] == "ranking_stats"
        assert sync_instances[0].calls[0]["kwargs"]["mode"] == "full"
        cutoff = sync_instances[0].calls[0]["kwargs"]["queue_sync_until_time"]
        assert isinstance(cutoff, int)
        assert abs(cutoff - int(time.time() - 7 * 86400)) < 10
        assert sync_instances[0].calls[0]["kwargs"]["season_id"] == "S12"
        assert sync_instances[0].calls[0]["kwargs"]["season_start_time"] > 0


if __name__ == "__main__":
    unittest.main()

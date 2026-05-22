from __future__ import annotations

import unittest
from typing import Any, Dict, List
from unittest.mock import MagicMock, AsyncMock

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


if __name__ == "__main__":
    unittest.main()

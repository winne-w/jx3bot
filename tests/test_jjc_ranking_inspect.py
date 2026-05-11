import unittest
from typing import Any, Callable, Dict, List
from unittest.mock import MagicMock

from src.services.jx3.jjc_ranking_inspect import JjcRankingInspectService


class FakeMatchHistoryClient:
    def __init__(self, history: List[Dict[str, Any]]) -> None:
        self.history = history
        self.calls: List[Dict[str, Any]] = []

    def get_mine_match_history(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(kwargs)
        return {"code": 0, "msg": "success", "data": self.history}


class DirectJjcRankingInspectService(JjcRankingInspectService):
    async def _run_serialized_tuilan_query(
        self,
        label: str,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        return func(*args, **kwargs)


class FakeJjcInspectRepo:
    """Fake repo that returns preconfigured cached_detail_summaries without Mongo."""

    def __init__(self, summaries=None):
        self.summaries = summaries or {}
        self.load_role_recent_result: Any = None
        self.saved_role_recent: list = []

    async def load_role_recent(self, server, name, *, ttl_seconds):
        return self.load_role_recent_result

    async def save_role_recent(self, server, name, payload):
        self.saved_role_recent.append((server, name, payload))

    async def load_match_detail(self, match_id):
        return None

    async def save_match_detail(self, match_id, payload):
        pass

    async def batch_load_cached_detail_summaries(self, match_ids):
        result = {}
        for mid in match_ids:
            mid_int = int(mid)
            if mid_int in self.summaries:
                result[mid_int] = self.summaries[mid_int]
        return result


class TestHydrateRecentMatchesWithCachedDetails(unittest.IsolatedAsyncioTestCase):
    async def test_adds_summary_when_cached_detail_exists(self):
        cache_repo = FakeJjcInspectRepo(
            summaries={
                1001: {
                    "match_id": 1001,
                    "cached_at": 1778000000,
                    "team1": {"won": True, "players": [{"kungfu_id": 10021, "kungfu": "花间游", "role_name": "角色A", "server": "梦江南"}]},
                    "team2": {"won": False, "players": [{"kungfu_id": 10081, "kungfu": "冰心诀", "role_name": "角色B"}]},
                }
            }
        )
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
        )
        recent_matches = [
            {"match_id": 1001, "won": True},
            {"match_id": 1002, "won": False},
        ]
        await service._hydrate_recent_matches_with_cached_details(recent_matches)
        self.assertIn("cached_detail_summary", recent_matches[0])
        self.assertEqual(recent_matches[0]["cached_detail_summary"]["match_id"], 1001)
        self.assertNotIn("cached_detail_summary", recent_matches[1])

    async def test_removes_stale_summary_when_not_cached(self):
        cache_repo = FakeJjcInspectRepo(summaries={})
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
        )
        recent_matches = [
            {"match_id": 1001, "won": True, "cached_detail_summary": {"stale": True}},
        ]
        await service._hydrate_recent_matches_with_cached_details(recent_matches)
        self.assertNotIn("cached_detail_summary", recent_matches[0])

    async def test_empty_matches_is_noop(self):
        cache_repo = FakeJjcInspectRepo(summaries={1001: {"match_id": 1001, "cached_at": 1, "team1": {"won": True, "players": []}, "team2": {"won": False, "players": []}}})
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
        )
        await service._hydrate_recent_matches_with_cached_details([])

    async def test_skips_rows_without_match_id(self):
        cache_repo = FakeJjcInspectRepo(summaries={})
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
        )
        recent_matches = [
            {"won": True},  # no match_id
            {"match_id": None, "won": False},
        ]
        await service._hydrate_recent_matches_with_cached_details(recent_matches)
        self.assertNotIn("cached_detail_summary", recent_matches[0])
        self.assertNotIn("cached_detail_summary", recent_matches[1])

    async def test_coerces_string_match_id(self):
        cache_repo = FakeJjcInspectRepo(
            summaries={
                1001: {
                    "match_id": 1001,
                    "cached_at": 1778000000,
                    "team1": {"won": True, "players": [{"kungfu_id": 10021, "kungfu": "花间游"}]},
                    "team2": {"won": False, "players": []},
                }
            }
        )
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
        )
        recent_matches = [{"match_id": "1001", "won": True}]
        await service._hydrate_recent_matches_with_cached_details(recent_matches)
        self.assertEqual(recent_matches[0]["cached_detail_summary"]["match_id"], 1001)


class TestJjcRankingInspectRoleRecent(unittest.IsolatedAsyncioTestCase):
    async def test_role_recent_default_window_returns_20_3v3_matches(self) -> None:
        history = [
            {
                "pvpType": 3,
                "match_id": 1000 + index,
                "won": index % 2 == 0,
                "kungfu": "huajian",
                "avgGrade": 12,
                "totalMmr": 1800 + index,
                "mmr": 10,
                "mvp": False,
                "match_time": 1778000000 + index,
                "duration": 180,
            }
            for index in range(40)
        ]
        history.extend(
            {
                "pvpType": 2,
                "match_id": 2000 + index,
                "won": True,
                "match_time": 1779000000 + index,
            }
            for index in range(5)
        )
        match_history_client = FakeMatchHistoryClient(history)
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=match_history_client,
            match_detail_client=MagicMock(),
            cache_repo=MagicMock(),
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={"huajian": "花间游"},
        )

        payload = await service._build_role_recent_payload(
            server="梦江南",
            name="示例角色",
            identity={"global_role_id": "global-1", "source": "test", "identity_key": "global:global-1"},
        )

        self.assertEqual(match_history_client.calls[0]["size"], 20)
        self.assertEqual(len(payload["recent_matches"]), 20)
        self.assertEqual(payload["recent_matches"][0]["match_id"], 1039)
        self.assertEqual(payload["recent_matches"][0]["kungfu"], "花间游")
        self.assertTrue(payload["pagination"]["has_more"])

    async def test_role_recent_cache_hit_hydrates_cached_details(self) -> None:
        cache_repo = FakeJjcInspectRepo(
            summaries={
                1001: {
                    "match_id": 1001,
                    "cached_at": 1778000000,
                    "team1": {"won": True, "players": [{"kungfu_id": 10021, "kungfu": "花间游"}]},
                    "team2": {"won": False, "players": [{"kungfu_id": 10081, "kungfu": "冰心诀"}]},
                }
            }
        )
        cache_repo.load_role_recent_result = {
            "cached_at": 1778000000,
            "data": {
                "recent_matches": [
                    {"match_id": 1001, "won": True, "kungfu": "花间游"},
                    {"match_id": 1002, "won": False, "kungfu": "冰心诀"},
                ],
            },
        }
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
        )
        result = await service.get_role_recent(server="梦江南", name="示例角色")
        recent_matches = result.get("recent_matches", [])
        self.assertEqual(len(recent_matches), 2)
        self.assertIn("cached_detail_summary", recent_matches[0])
        self.assertEqual(recent_matches[0]["cached_detail_summary"]["match_id"], 1001)
        self.assertNotIn("cached_detail_summary", recent_matches[1])
        self.assertTrue(result["cache"]["hit"])

    async def test_role_recent_cache_hit_removes_stale_cached_detail_summary(self) -> None:
        cache_repo = FakeJjcInspectRepo(summaries={})
        cache_repo.load_role_recent_result = {
            "cached_at": 1778000000,
            "data": {
                "recent_matches": [
                    {"match_id": 1001, "won": True, "cached_detail_summary": {"stale": True}},
                ],
            },
        }
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
        )
        result = await service.get_role_recent(server="梦江南", name="示例角色")
        recent_matches = result.get("recent_matches", [])
        self.assertNotIn("cached_detail_summary", recent_matches[0])
        self.assertTrue(result["cache"]["hit"])

    async def test_role_recent_fresh_response_does_not_save_detail_summary(self) -> None:
        cache_repo = FakeJjcInspectRepo(
            summaries={
                1001: {
                    "match_id": 1001,
                    "cached_at": 1778000000,
                    "team1": {"won": True, "players": [{"kungfu_id": 10021, "kungfu": "花间游"}]},
                    "team2": {"won": False, "players": [{"kungfu_id": 10081, "kungfu": "冰心诀"}]},
                }
            }
        )
        match_history_client = FakeMatchHistoryClient(
            [
                {
                    "pvpType": 3,
                    "match_id": 1001,
                    "won": True,
                    "kungfu": "huajian",
                    "avgGrade": 12,
                    "match_time": 1778000000,
                }
            ]
        )
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=match_history_client,
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={"huajian": "花间游"},
        )
        result = await service.get_role_recent(
            server="梦江南",
            name="示例角色",
            identity_hints={"global_role_id": "global-1"},
        )
        self.assertIn("cached_detail_summary", result["recent_matches"][0])
        saved_data = cache_repo.saved_role_recent[0][2]["data"]
        self.assertNotIn("cached_detail_summary", saved_data["recent_matches"][0])

    async def test_role_recent_late_hydration_when_detail_cached_after_initial_request(self) -> None:
        cache_repo = FakeJjcInspectRepo(summaries={})
        cache_repo.load_role_recent_result = {
            "cached_at": 1778000000,
            "data": {
                "recent_matches": [
                    {"match_id": 1001, "won": True, "kungfu": "花间游"},
                    {"match_id": 1002, "won": False, "kungfu": "冰心诀"},
                ],
            },
        }
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
        )
        result1 = await service.get_role_recent(server="梦江南", name="示例角色")
        recent1 = result1["recent_matches"]
        self.assertNotIn("cached_detail_summary", recent1[0])
        self.assertNotIn("cached_detail_summary", recent1[1])

        cache_repo.summaries[1001] = {
            "match_id": 1001,
            "cached_at": 1779000000,
            "team1": {"won": True, "players": [{"kungfu_id": 10021, "kungfu": "花间游", "role_name": "角色A"}]},
            "team2": {"won": False, "players": [{"kungfu_id": 10081, "kungfu": "冰心诀", "role_name": "角色B"}]},
        }

        result2 = await service.get_role_recent(server="梦江南", name="示例角色")
        recent2 = result2["recent_matches"]
        self.assertIn("cached_detail_summary", recent2[0])
        self.assertEqual(recent2[0]["cached_detail_summary"]["match_id"], 1001)
        self.assertNotIn("cached_detail_summary", recent2[1])


if __name__ == "__main__":
    unittest.main()

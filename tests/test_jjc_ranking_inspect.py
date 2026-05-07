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
        self.assertEqual(payload["summary"]["total_matches"], 20)
        self.assertTrue(payload["pagination"]["has_more"])


if __name__ == "__main__":
    unittest.main()

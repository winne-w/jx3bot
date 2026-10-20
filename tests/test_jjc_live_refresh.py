import unittest
import time
from unittest.mock import AsyncMock

from src.services.jx3.jjc_live_refresh import normalize_history, JjcLiveRefreshService


class TestLiveSummary(unittest.TestCase):
    def test_only_valid_current_season_three_v_three_and_score_semantics(self):
        rows = normalize_history([
            {"match_id": 17, "pvp_type": 3, "start_time": 200, "won": False,
             "kungfu": "huajian", "total_mmr": 2300, "mmr": -12},
            {"match_id": 18, "pvp_type": 2, "start_time": 210},
            {"match_id": 19, "pvp_type": 3, "start_time": 90},
            {"match_id": 20, "start_time": 220},
            {"match_id": True, "pvp_type": 3, "start_time": 220},
        ], season_start=100, observed_at=300)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["match_id"], 17)
        self.assertEqual(rows[0]["total_mmr"], 2300)
        self.assertEqual(rows[0]["mmr_delta"], -12)
        self.assertFalse(rows[0]["won"])


if __name__ == "__main__":
    unittest.main()


class TestLiveRefreshExecution(unittest.IsolatedAsyncioTestCase):
    async def test_first_page_merges_previous_summary_instead_of_discarding_it(self):
        stamp = int(time.time()) - 100
        previous = [{"match_id": i, "match_time": stamp - i} for i in range(1, 41)]
        repo = unittest.mock.Mock()
        repo.read = AsyncMock(return_value={"latest_matches": previous})
        repo.publish = AsyncMock(return_value=True)
        repo.finish = AsyncMock()
        class History:
            def get_mine_match_history(self, **kwargs):
                return {"code": 0, "data": [{"match_id": i, "pvp_type": 3,
                    "start_time": stamp - i} for i in range(1, 21)]}
        service = JjcLiveRefreshService(identity_repo=None, history_client=History(),
            indicator_client=None, season="test", season_start=0, repo=repo)
        task = {"identity": {"global_role_id": "SK01-test"}, "task_key": "known", "until": time.time() + 120}
        await service.execute(task)
        saved = repo.publish.call_args.args[1]
        self.assertEqual(40, len(saved))
        self.assertEqual(40, saved[-1]["match_id"])

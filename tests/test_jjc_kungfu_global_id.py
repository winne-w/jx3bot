import unittest
from typing import Any, Dict, List

from src.services.jx3.kungfu import get_kungfu_detail_by_role_info


class FakeTuilanRequest:
    def __init__(self, indicator_global_role_id: str = "SK01-role") -> None:
        self.calls: List[Dict[str, Any]] = []
        self.indicator_global_role_id = indicator_global_role_id

    def __call__(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append({"url": url, "params": params})
        if url.endswith("/role/indicator"):
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "role_info": {
                        "role_id": "30284767",
                        "global_role_id": self.indicator_global_role_id,
                    },
                    "indicator": [
                        {
                            "type": "3c",
                            "metrics": [
                                {
                                    "pvp_type": 3,
                                    "kungfu": "huajian",
                                    "win_count": 20,
                                    "total_count": 30,
                                    "items": [{"name": "sample"}],
                                }
                            ],
                        }
                    ],
                },
            }
        if url.endswith("/3c/mine/match/history"):
            return {
                "code": 0,
                "msg": "success",
                "data": [
                    {
                        "match_id": 1001,
                        "won": True,
                        "kungfu": "huajian",
                    }
                ],
            }
        if url == "replay":
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "players": [
                        {
                            "role_id": "30284767",
                            "role_name": "示例角色·梦江南",
                            "global_role_id": "987654321",
                        }
                    ]
                },
            }
        if url == "detail":
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "team1": {
                        "players_info": [
                            {
                                "role_name": "示例角色",
                                "server": "梦江南",
                                "role_id": "30284767",
                                "global_role_id": "SK01-role",
                                "kungfu_id": 10021,
                                "armors": [{"name": "武器", "icon": "i", "quality": "5"}],
                            }
                        ]
                    },
                    "team2": {"players_info": []},
                },
            }
        return {}


class TestKungfuGlobalId(unittest.TestCase):
    def test_kungfu_detail_fetches_replay_global_id_without_overwriting_sk01(self) -> None:
        request = FakeTuilanRequest()

        result = get_kungfu_detail_by_role_info(
            "30284767",
            "电信区",
            "梦江南",
            tuilan_request=request,
            kungfu_pinyin_to_chinese={"huajian": "花间游"},
            match_detail_url="detail",
            match_replay_url="replay",
            role_name="示例角色",
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["global_role_id"], "SK01-role")
        self.assertEqual(result["global_id"], "987654321")
        self.assertEqual(result["_cache_warmup"]["role_indicator"]["global_role_id"], "SK01-role")
        self.assertEqual(result["_cache_warmup"]["role_indicator"]["global_id"], "987654321")
        self.assertEqual(result["_cache_warmup"]["match_detail"]["raw"]["data"]["team1"]["players_info"][0]["global_id"], "987654321")
        self.assertTrue(any(call["url"] == "replay" for call in request.calls))

    def test_kungfu_detail_ignores_non_sk01_indicator_global_role_id(self) -> None:
        request = FakeTuilanRequest(indicator_global_role_id="987654321")

        result = get_kungfu_detail_by_role_info(
            "30284767",
            "电信区",
            "梦江南",
            tuilan_request=request,
            kungfu_pinyin_to_chinese={"huajian": "花间游"},
            match_detail_url="detail",
            match_replay_url="replay",
            role_name="示例角色",
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIsNone(result["global_role_id"])
        self.assertFalse(any(call["url"].endswith("/3c/mine/match/history") for call in request.calls))


if __name__ == "__main__":
    unittest.main()

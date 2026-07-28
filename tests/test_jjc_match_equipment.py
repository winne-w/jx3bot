import unittest
from typing import Any, Dict, List
from unittest.mock import AsyncMock

from src.services.jx3.match_detail import (
    MatchDetailArmor,
    MatchDetailBasicInfo,
    MatchDetailBodyQuality,
    MatchDetailData,
    MatchDetailMetric,
    MatchDetailPlayerInfo,
    MatchDetailResponse,
    MatchDetailTeamInfo,
)
from src.services.jx3.jjc_match_equipment import JjcMatchEquipmentService


def make_player(server: str = "唯我独尊", name: str = "桃桃白糖", armors: bool = True) -> MatchDetailPlayerInfo:
    return MatchDetailPlayerInfo(
        role_name=name, global_role_id="SK01-target", role_id="29528125", person_id="", person_name="",
        person_avatar="", zone="电信区", server=server, total_count=None, win_count=None,
        win_rate=None, mvp_count=None, mmr=None, score=None, total_score=None, ranking="", kungfu="冰心诀",
        kungfu_id=None, mvp=False, equip_score=12345, equip_strength_score=2345, stone_score=345,
        max_hp=None, metrics=[MatchDetailMetric(1, "会心", 123, "", None)],
        armors=[MatchDetailArmor("1", "精良", "破军", "6", "", "", "", "", "", "", 1, "icon", "")]
        if armors else [],
        talents=[], body_qualities=[MatchDetailBodyQuality("体质", "100")], odd=False, fight_seconds=None,
    )


def make_detail(*players: MatchDetailPlayerInfo) -> MatchDetailResponse:
    return MatchDetailResponse(
        code=0, msg="success",
        data=MatchDetailData(
            match_id=102, match_time=1780000000, query_backend=False,
            basic_info=MatchDetailBasicInfo("", "", 1780000000, 180, "", 3, None),
            team1=MatchDetailTeamInfo(False, "", list(players)), team2=MatchDetailTeamInfo(False, "", []),
            videos=[], hidden=False,
        ),
    )


class FakeIdentityRepo:
    def __init__(self, identity: Any) -> None:
        self.identity = identity
        self.upserts: List[Dict[str, Any]] = []

    async def find_best_by_name_with_id(self, server: str, name: str) -> Any:
        return self.identity

    async def upsert_from_jx3api_role_detail(self, server: str, name: str, **kwargs: Any) -> Dict[str, Any]:
        self.upserts.append({"server": server, "name": name, **kwargs})
        self.identity = {"server": server, "name": name, "role_id": kwargs["role_id"], "zone": kwargs["zone"]}
        return self.identity


class FakeHistoryClient:
    def __init__(self, items: List[Dict[str, Any]]) -> None:
        self.items = items
        self.calls: List[Dict[str, Any]] = []

    def get_mine_match_history(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(kwargs)
        return {"code": 0, "msg": "success", "data": self.items}


class FakeDetailClient:
    def __init__(self, response: MatchDetailResponse) -> None:
        self.response = response
        self.calls: List[int] = []

    def get_match_detail_obj(self, *, match_id: int) -> MatchDetailResponse:
        self.calls.append(match_id)
        return self.response


class TestJjcMatchEquipmentService(unittest.IsolatedAsyncioTestCase):
    def make_service(self, identity: Any, history: List[Dict[str, Any]], detail: MatchDetailResponse) -> Any:
        self.repo = FakeIdentityRepo(identity)
        self.history = FakeHistoryClient(history)
        self.detail = FakeDetailClient(detail)
        self.role_detail_fetcher = AsyncMock()
        self.indicator_calls: List[Dict[str, Any]] = []

        def indicator(role_id: str, zone: str, server: str, **kwargs: Any) -> Dict[str, Any]:
            self.indicator_calls.append({"role_id": role_id, "zone": zone, "server": server, **kwargs})
            return {"code": 0, "data": {"role_info": {"global_role_id": "SK01-target"}}}

        return JjcMatchEquipmentService(
            identity_repo=self.repo,
            role_detail_fetcher=self.role_detail_fetcher,
            role_indicator_fetcher=indicator,
            match_history_client=self.history,
            match_detail_client=self.detail,
            tuilan_request=lambda url, params: {},
        )

    async def test_query_uses_local_identity_and_latest_3v3_detail(self) -> None:
        service = self.make_service(
            {"role_id": "29528125", "zone": "电信区"},
            [{"pvpType": 2, "match_id": 999, "startTime": 9999}, {"pvp_type": 3, "match_id": 101, "match_time": "10"}, {"type": 3, "match_id": 102, "start_time": 20}],
            make_detail(make_player()),
        )

        result = await service.query(server="唯我独尊", name="桃桃白糖")

        self.assertTrue(result["ok"])
        self.assertEqual(result["snapshot"]["match_id"], 102)
        self.assertEqual(result["snapshot"]["equip_score"], 12345)
        self.assertEqual(result["snapshot"]["armors"][0]["name"], "破军")
        self.role_detail_fetcher.assert_not_awaited()
        self.assertEqual(self.history.calls, [{"global_role_id": "SK01-target", "size": 20, "cursor": 0}])
        self.assertEqual(self.detail.calls, [102])

    async def test_query_backfills_missing_identity_from_jx3api_role_detail(self) -> None:
        service = self.make_service(None, [{"pvp_type": 3, "match_id": 102, "match_time": 20}], make_detail(make_player()))
        self.role_detail_fetcher.return_value = {
            "code": 0, "msg": "success",
            "data": {"roleId": "29528125", "zoneName": "电信区", "globalId": "270215977651548656"},
        }

        result = await service.query(server="唯我独尊", name="桃桃白糖")

        self.assertTrue(result["ok"])
        self.assertEqual(self.repo.upserts[0]["role_id"], "29528125")
        self.assertEqual(self.repo.upserts[0]["global_id"], "270215977651548656")
        self.assertEqual(self.indicator_calls[0]["zone"], "电信区")

    async def test_query_requires_exact_server_and_name_and_nonempty_equipment(self) -> None:
        service = self.make_service(
            {"role_id": "29528125", "zone": "电信区"}, [{"pvp_type": 3, "match_id": 102, "match_time": 20}],
            make_detail(make_player(server="其他服"), make_player(armors=False)),
        )

        result = await service.query(server="唯我独尊", name="桃桃白糖")

        self.assertEqual(result, {"ok": False, "code": "equipment_unavailable", "message": "最近 3v3 对局未找到可用装备快照"})

    async def test_query_returns_stable_errors_for_missing_identity_history_and_detail(self) -> None:
        service = self.make_service(None, [], make_detail(make_player()))
        self.role_detail_fetcher.return_value = {"code": 1, "msg": "not found", "data": {}}
        self.assertEqual((await service.query(server="唯我独尊", name="桃桃白糖"))["code"], "role_identity_unavailable")

        service = self.make_service({"role_id": "29528125", "zone": "电信区"}, [], make_detail(make_player()))
        self.assertEqual((await service.query(server="唯我独尊", name="桃桃白糖"))["code"], "no_recent_3v3")

        service = self.make_service({"role_id": "29528125", "zone": "电信区"}, [{"pvp_type": 3, "match_id": 102, "match_time": 20}], MatchDetailResponse(1, "bad", None))
        self.assertEqual((await service.query(server="唯我独尊", name="桃桃白糖"))["code"], "match_detail_unavailable")

    async def test_query_ignores_3v3_rows_without_a_positive_match_id(self) -> None:
        service = self.make_service(
            {"role_id": "29528125", "zone": "电信区"},
            [{"pvp_type": 3, "match_id": -1, "match_time": 100}, {"pvp_type": 3, "match_id": "bad", "match_time": 90}],
            make_detail(make_player()),
        )

        result = await service.query(server="唯我独尊", name="桃桃白糖")

        self.assertEqual(result["code"], "no_recent_3v3")
        self.assertEqual(self.detail.calls, [])

    async def test_query_ignores_3v3_rows_without_a_numeric_match_time(self) -> None:
        service = self.make_service(
            {"role_id": "29528125", "zone": "电信区"},
            [{"pvp_type": 3, "match_id": 102, "match_time": "not-a-time"}],
            make_detail(make_player()),
        )

        result = await service.query(server="唯我独尊", name="桃桃白糖")

        self.assertEqual(result["code"], "no_recent_3v3")
        self.assertEqual(self.detail.calls, [])

    async def test_query_returns_identity_error_when_role_detail_fetcher_raises(self) -> None:
        service = self.make_service(None, [], make_detail(make_player()))
        self.role_detail_fetcher.side_effect = RuntimeError("upstream unavailable")

        result = await service.query(server="唯我独尊", name="桃桃白糖")

        self.assertEqual(result, {"ok": False, "code": "role_identity_unavailable", "message": "未找到可用的角色身份信息"})

    async def test_query_rejects_fractional_match_time(self) -> None:
        service = self.make_service(
            {"role_id": "29528125", "zone": "电信区"},
            [{"pvp_type": 3, "match_id": 102, "match_time": "20.5"}],
            make_detail(make_player()),
        )

        result = await service.query(server="唯我独尊", name="桃桃白糖")

        self.assertEqual(result["code"], "no_recent_3v3")
        self.assertEqual(self.detail.calls, [])

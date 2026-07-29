import unittest
import sys
import types
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

from jinja2 import Environment, FileSystemLoader

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
from src.services.jx3.query_context import build_latest_match_equipment_spec

try:
    from nonebot.adapters.onebot.v11 import Bot, Event, Message, MessageSegment  # noqa: F401
    from nonebot.params import RegexGroup  # noqa: F401
except ModuleNotFoundError:
    onebot_module = types.ModuleType("nonebot.adapters.onebot.v11")
    onebot_module.Bot = type("Bot", (), {})
    onebot_module.Event = type("Event", (), {})
    onebot_module.Message = type("Message", (), {})
    onebot_module.MessageSegment = type("MessageSegment", (), {})
    params_module = types.ModuleType("nonebot.params")
    params_module.RegexGroup = lambda: None
    sys.modules["nonebot.adapters.onebot.v11"] = onebot_module
    sys.modules["nonebot.params"] = params_module

from src.plugins.jx3bot_handlers import queries as query_handlers


SNAPSHOT = {
    "server": "唯我独尊",
    "role_name": "桃桃白糖",
    "match_id": 102,
    "match_time": 1780000000,
    "kungfu": "冰心诀",
    "equip_score": 12345,
    "equip_strength_score": 2345,
    "stone_score": 345,
    "max_hp": 3350711,
    "armors": [],
    "metrics": [],
    "body_qualities": [],
}


def make_player(server: str = "唯我独尊", name: str = "桃桃白糖", armors: bool = True) -> MatchDetailPlayerInfo:
    return MatchDetailPlayerInfo(
        role_name=name, global_role_id="SK01-target", role_id="29528125", person_id="", person_name="",
        person_avatar="", zone="电信区", server=server, total_count=None, win_count=None,
        win_rate=None, mvp_count=None, mmr=None, score=None, total_score=None, ranking="", kungfu="冰心诀",
        kungfu_id=None, mvp=False, equip_score=12345, equip_strength_score=2345, stone_score=345,
        max_hp=3350711, metrics=[MatchDetailMetric(1, "会心", 123, "", None)],
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


class TestEquipmentRenderSpec(unittest.TestCase):
    def test_build_latest_match_equipment_spec_marks_snapshot_time_and_scores(self) -> None:
        spec = build_latest_match_equipment_spec(
            snapshot=SNAPSHOT,
            random_text="x",
            time_filter=lambda timestamp: "2026-05-28 12:00:00",
        )

        self.assertEqual(spec.template_name, "装备查询.html")
        self.assertEqual(spec.width, 1180)
        self.assertEqual(spec.height, "ck")
        self.assertEqual(spec.context["title"], "最近 3v3 对局装备快照")
        self.assertEqual(spec.context["snapshot"]["match_id"], 102)
        self.assertEqual(spec.context["snapshot"]["total_score"], 15035)
        self.assertIn("对局时间", spec.context["match_time_label"])
        self.assertEqual(
            set(spec.context),
            {"title", "snapshot", "match_time_label", "text"},
        )

    def test_equipment_template_renders_total_score_and_requested_attributes_only(self) -> None:
        snapshot = {
            **SNAPSHOT,
            "equip_score": 675224,
            "equip_strength_score": 57297,
            "stone_score": 78019,
            "armors": [{
                "icon": "https://example.com/armor.png",
                "name": "测试破军甲",
                "quality": "精良",
                "strength_evel": "8",
                "permanent_enchant": "永久附魔测试",
                "temporary_enchant": "临时附魔测试",
                "mount1": "五彩石一",
                "mount2": "五彩石二",
                "mount3": "五彩石三",
                "mount4": "五彩石四",
            }],
            "metrics": [{"name": "战斗效率", "value": 1, "grade": "S"}],
            "body_qualities": [
                {"name": "会心", "value": "53.55%"},
                {"name": "无双", "value": "0%"},
                {"name": "破招", "value": "0"},
                {"name": "会心效果", "value": "176.81%"},
                {"name": "加速", "value": "25%"},
                {"name": "内功防御", "value": "15.54%"},
                {"name": "外功防御", "value": "13.16%"},
                {"name": "化劲", "value": "76.2%"},
                {"name": "根骨", "value": "21881"},
                {"name": "治疗量", "value": "285525"},
            ],
        }
        spec = build_latest_match_equipment_spec(
            snapshot=snapshot,
            random_text="x",
            time_filter=lambda timestamp: "2026年05月28日 12:00:00",
        )

        html = Environment(loader=FileSystemLoader("templates")).get_template(
            spec.template_name
        ).render(**spec.context)

        for expected in (
            "最近 3v3 对局装备快照", "桃桃白糖", "唯我独尊", "冰心诀",
            "对局时间：2026年05月28日 12:00:00",
            "数据为最近 3v3 对局发生时的装备快照，不代表当前实时面板",
            "总装分", "810540",
            "https://example.com/armor.png", "测试破军甲", "精良", "精炼：8",
            "永久附魔：永久附魔测试", "临时附魔：临时附魔测试",
            "基础属性", "会心", "53.55%", "无双", "破招",
            "详细属性", "气血", "3350711", "会心效果", "加速", "内功防御",
            "外功防御", "化劲", "根骨",
        ):
            self.assertIn(expected, html)
        for hidden in (
            "装备分", "精炼分", "五彩石分", "五彩石 1", "五彩石二",
            "战斗效率", "治疗量", "破防", "基础攻击力",
        ):
            self.assertNotIn(hidden, html)

    def test_equipment_template_escapes_untrusted_snapshot_text(self) -> None:
        malicious_text = '<script>alert("x")</script>'
        malicious_icon = 'https://example.com/armor.png" onerror="alert(1)'
        snapshot = {
            **SNAPSHOT,
            "role_name": malicious_text,
            "armors": [{
                "icon": malicious_icon,
                "name": malicious_text,
                "quality": malicious_text,
                "strength_evel": malicious_text,
                "permanent_enchant": malicious_text,
                "temporary_enchant": malicious_text,
                "mount1": malicious_text,
                "mount2": malicious_text,
                "mount3": malicious_text,
                "mount4": malicious_text,
            }],
            "metrics": [{"name": malicious_text, "value": malicious_text, "grade": malicious_text}],
            "body_qualities": [{"name": malicious_text, "value": malicious_text}],
        }
        spec = build_latest_match_equipment_spec(
            snapshot=snapshot,
            random_text=malicious_text,
            time_filter=lambda timestamp: malicious_text,
        )

        html = Environment(loader=FileSystemLoader("templates")).get_template(
            spec.template_name
        ).render(**spec.context)

        self.assertNotIn(malicious_text, html)
        self.assertNotIn('" onerror="alert(1)', html)
        self.assertIn("&lt;script&gt;alert(&#34;x&#34;)&lt;/script&gt;", html)
        self.assertIn("&#34; onerror=&#34;alert(1)", html)

    def test_builder_normalizes_missing_snapshot_collections_for_template_rendering(self) -> None:
        spec = build_latest_match_equipment_spec(
            snapshot={**SNAPSHOT, "armors": None, "metrics": "invalid", "body_qualities": None},
            random_text="x",
            time_filter=lambda timestamp: "2026年05月28日 12:00:00",
        )

        self.assertEqual(spec.context["snapshot"]["armors"], [])
        self.assertEqual(spec.context["snapshot"]["metrics"], [])
        self.assertEqual(spec.context["snapshot"]["body_qualities"], [])
        html = Environment(loader=FileSystemLoader("templates")).get_template(
            spec.template_name
        ).render(**spec.context)
        self.assertIn("该对局没有可展示的装备。", html)
        self.assertIn("暂无基础属性", html)
        self.assertIn("气血", html)
        self.assertIn("3350711", html)


class CapturingMatcher:
    def __init__(self) -> None:
        self.handlers: List[Any] = []

    def handle(self) -> Any:
        def register_handler(handler: Any) -> Any:
            self.handlers.append(handler)
            return handler

        return register_handler


class TestEquipmentQueryHandler(unittest.IsolatedAsyncioTestCase):
    async def test_zhuangfen_handler_handles_service_errors_and_malformed_results(self) -> None:
        zhuangfen_matcher = CapturingMatcher()
        query_handlers.register(
            env=Environment(loader=FileSystemLoader("templates")),
            yanhua_matcher=CapturingMatcher(),
            qiyu_matcher=CapturingMatcher(),
            zhuangfen_matcher=zhuangfen_matcher,
            jjc_matcher=CapturingMatcher(),
            fuben_matcher=CapturingMatcher(),
        )
        handler = zhuangfen_matcher.handlers[0]
        bot = MagicMock()
        event = MagicMock(user_id=123, group_id=456)

        for result in (
            RuntimeError("upstream down"),
            None,
            {"ok": True, "snapshot": None},
            {"ok": True, "snapshot": {"match_time": "not-a-timestamp"}},
        ):
            with self.subTest(result=result), patch.object(
                query_handlers,
                "resolve_server_and_name",
                new=AsyncMock(return_value=("唯我独尊", "桃桃白糖")),
            ), patch.object(query_handlers, "send_text", new=AsyncMock()) as send_text_mock, patch.object(
                query_handlers, "logger"
            ) as logger_mock:
                query_mock = AsyncMock(side_effect=result) if isinstance(result, Exception) else AsyncMock(return_value=result)
                with patch.object(query_handlers.jjc_match_equipment_service, "query", query_mock):
                    await handler(bot, event, ())

                send_text_mock.assert_awaited_once_with(
                    bot, event, "装备快照查询失败，请稍后重试", at_user=True
                )
                if isinstance(result, Exception) or result == {
                    "ok": True, "snapshot": {"match_time": "not-a-timestamp"}
                }:
                    logger_mock.exception.assert_called_once()
                else:
                    logger_mock.warning.assert_called_once()

    async def test_zhuangfen_handler_renders_when_snapshot_collections_are_invalid(self) -> None:
        zhuangfen_matcher = CapturingMatcher()
        query_handlers.register(
            env=Environment(loader=FileSystemLoader("templates")),
            yanhua_matcher=CapturingMatcher(),
            qiyu_matcher=CapturingMatcher(),
            zhuangfen_matcher=zhuangfen_matcher,
            jjc_matcher=CapturingMatcher(),
            fuben_matcher=CapturingMatcher(),
        )
        handler = zhuangfen_matcher.handlers[0]
        result = {"ok": True, "snapshot": {**SNAPSHOT, "armors": None, "metrics": {}, "body_qualities": None}}
        render_mock = AsyncMock()

        with patch.object(
            query_handlers,
            "resolve_server_and_name",
            new=AsyncMock(return_value=("唯我独尊", "桃桃白糖")),
        ), patch.object(query_handlers.jjc_match_equipment_service, "query", AsyncMock(return_value=result)), patch.object(
            query_handlers, "render_and_send_template_image", render_mock
        ), patch.object(query_handlers, "send_text", new=AsyncMock()) as send_text_mock:
            await handler(MagicMock(), MagicMock(user_id=123, group_id=456), ())

        render_mock.assert_awaited_once()
        send_text_mock.assert_not_awaited()


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
        self.assertEqual(result["snapshot"]["max_hp"], 3350711)
        self.assertEqual(result["snapshot"]["armors"][0]["name"], "破军")
        self.role_detail_fetcher.assert_not_awaited()
        self.assertEqual(self.history.calls, [{"global_role_id": "SK01-target", "size": 20, "cursor": 0}])
        self.assertEqual(self.detail.calls, [102])

    async def test_query_matches_detail_role_name_with_verified_server_suffix(self) -> None:
        service = self.make_service(
            {"role_id": "29528125", "zone": "电信区"},
            [{"pvp_type": 3, "match_id": 102, "match_time": 20}],
            make_detail(make_player(name="桃桃白糖·唯我独尊")),
        )

        result = await service.query(server="唯我独尊", name="桃桃白糖")

        self.assertTrue(result["ok"])
        self.assertEqual(result["snapshot"]["role_name"], "桃桃白糖·唯我独尊")

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

    async def test_query_returns_history_error_when_upstream_returns_error(self) -> None:
        service = self.make_service(
            {"role_id": "29528125", "zone": "电信区"}, [], make_detail(make_player())
        )
        self.history.get_mine_match_history = lambda **kwargs: {"error": "upstream down"}

        result = await service.query(server="唯我独尊", name="桃桃白糖")

        self.assertEqual(result, {"ok": False, "code": "match_history_unavailable", "message": "最近 3v3 对局历史查询失败"})

    async def test_query_returns_history_error_when_history_call_raises(self) -> None:
        service = self.make_service(
            {"role_id": "29528125", "zone": "电信区"}, [], make_detail(make_player())
        )

        def raise_history_error(**kwargs: Any) -> Dict[str, Any]:
            raise RuntimeError("upstream down")

        self.history.get_mine_match_history = raise_history_error
        result = await service.query(server="唯我独尊", name="桃桃白糖")

        self.assertEqual(result, {"ok": False, "code": "match_history_unavailable", "message": "最近 3v3 对局历史查询失败"})

    async def test_query_returns_history_error_for_non_success_response(self) -> None:
        service = self.make_service(
            {"role_id": "29528125", "zone": "电信区"}, [], make_detail(make_player())
        )
        self.history.get_mine_match_history = lambda **kwargs: {"code": 1, "msg": "failed", "data": []}

        result = await service.query(server="唯我独尊", name="桃桃白糖")

        self.assertEqual(result, {"ok": False, "code": "match_history_unavailable", "message": "最近 3v3 对局历史查询失败"})

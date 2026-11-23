import copy
import re
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from jinja2 import Environment, FileSystemLoader
import config
from src.services.jx3.role_queries import build_equipment_spec_or_text, format_online_status
from src.infra.jx3api_online import fetch_role_online


class TestRoleQueries(unittest.TestCase):
    def test_equipment_and_online_aliases(self):
        for word in ("装备", "属性", "装分"):
            self.assertIsNotNone(re.fullmatch(config.REGEX_PATTERNS["装备查询"], word+" 测试角色"))
            self.assertIsNotNone(re.fullmatch(config.REGEX_PATTERNS["装备查询"], word+" 测试服 测试角色"))
        for word in ("在线", "在线状态", "角色在线"):
            self.assertIsNotNone(re.fullmatch(config.REGEX_PATTERNS["在线查询"], word+" 测试角色"))
            self.assertIsNotNone(re.fullmatch(config.REGEX_PATTERNS["在线查询"], word+" 测试服 测试角色"))

    def test_equipment_projects_real_fields_and_renders_every_item(self):
        payload = {"equipScore": 18000, "cacheTime": 1795438546, "kungfuName": "冰心诀",
                   "panelList": [{"name":"会心", "value":38.5}],
                   "equipList":[{"itemName":"装备<%s>" % i,"itemQuality":4,"itemLevel":26000,
                                 "strengthLevel":6,"maxStrengthLevel":6,"itemSource":"测试来源",
                                 "itemAttrib":[{"name":"基础攻击","value":1159}],
                                 "mountDiamond":[{"itemName":"五行石（七级）"}],
                                 "colorDiamond":{"itemName":"测试五彩石"},
                                 "minEnchant":{"itemName":"测试附魔"}} for i in range(13)]}
        before=copy.deepcopy(payload)
        spec,error=build_equipment_spec_or_text(data={"msg":"success","data":payload},server="测试服",role_name="测试角色",random_text="")
        self.assertIsNone(error)
        self.assertEqual("ck",spec.height)
        self.assertEqual(13,len(spec.context["equipment"]))
        env=Environment(loader=FileSystemLoader(str(Path(__file__).resolve().parents[1]/"templates")))
        html=env.get_template(spec.template_name).render(**spec.context)
        self.assertIn("装备&lt;12&gt;",html)
        self.assertIn("38.5",html)
        self.assertIn("18000",html)
        self.assertIn("基础攻击",html)
        self.assertIn("1159",html)
        self.assertIn("五行石（七级）",html)
        self.assertIn("测试五彩石",html)
        self.assertIn("测试附魔",html)
        self.assertIn("已收录",html)
        self.assertEqual(before,payload)

    def test_empty_equipment_and_panel_are_explained(self):
        for payload in ({},{"equipList":[],"panelList":[]}):
            with self.subTest(payload=payload):
                spec,error=build_equipment_spec_or_text(data={"data":payload},server="测试服",role_name="测试角色",random_text="")
                self.assertIsNone(spec)
                self.assertIn("未收录",error)

    def test_equipment_with_no_panel_still_displays_equipment(self):
        spec,error=build_equipment_spec_or_text(data={"data":{"equipList":[{"itemName":"测试武器"}],"panelList":[]}},server="测试服",role_name="测试角色",random_text="")
        self.assertIsNone(error)
        self.assertEqual(1,len(spec.context["equipment"]))

    def test_online_game_status_is_separate_from_app_login(self):
        row={"serverName":"测试服","roleName":"测试角色","onlineStatus":False,"appLogin":True}
        self.assertIn("游戏离线",format_online_status({"msg":"success","data":[row]},server="测试服",name="测试角色"))
        row["onlineStatus"]=True
        self.assertIn("游戏在线",format_online_status({"msg":"success","data":[row]},server="测试服",name="测试角色"))

    def test_online_unknown_never_becomes_offline(self):
        for rows in ([],{},[{"serverName":"别服","roleName":"测试角色","onlineStatus":False}],
                     [{"serverName":"测试服","roleName":"别人","onlineStatus":False}],
                     [{"serverName":"测试服","roleName":"测试角色","appLogin":True}],
                     [{"serverName":"测试服","roleName":"测试角色","onlineStatus":"false"}]):
            with self.subTest(rows=rows):
                text=format_online_status({"msg":"success","data":rows},server="测试服",name="测试角色")
                self.assertIn("未知",text)
                self.assertNotIn("游戏离线",text)

    def test_online_falls_back_only_to_boolean_game_login(self):
        row={"serverName":"测试服","roleName":"测试角色","gameLogin":True}
        self.assertIn("游戏在线",format_online_status({"msg":"success","data":[row]},server="测试服",name="测试角色"))

    def test_online_ambiguous_matches_are_unknown(self):
        rows=[{"serverName":"测试服","roleName":"测试角色","onlineStatus":x} for x in (True,False)]
        self.assertIn("未知",format_online_status({"msg":"success","data":rows},server="测试服",name="测试角色"))

    def test_online_upstream_error_is_not_offline(self):
        text=format_online_status({"error":"upstream_error","msg":"票据已失效"},server="测试服",name="测试角色")
        self.assertIn("票据已失效",text)
        self.assertNotIn("游戏离线",text)


class TestOnlineTransport(unittest.IsolatedAsyncioTestCase):
    async def test_post_json_token_header_and_no_query_cache(self):
        request=AsyncMock(return_value={"status":200,"detail":[]})
        with patch("src.infra.jx3api_online.HttpClient.arequest_json",request):
            for _ in range(2):
                await fetch_role_online(url="https://www.jx3api.com/role/online/status",server="测试服",name="测试角色",token="test-token",ticket="test-ticket")
        self.assertEqual(2,request.await_count)
        args,kwargs=request.call_args
        self.assertEqual(("POST","https://www.jx3api.com/role/online/status"),args)
        self.assertEqual({"token":"test-token"},kwargs["headers"])
        self.assertEqual({"ticket":"test-ticket","query":[{"server":"测试服","name":"测试角色"}]},kwargs["json_body"])
        self.assertNotIn("params",kwargs)

    async def test_missing_credentials_does_not_call_upstream(self):
        request=AsyncMock()
        with patch("src.infra.jx3api_online.HttpClient.arequest_json",request):
            result=await fetch_role_online(url="https://www.jx3api.com/role/online/status",server="测试服",name="测试角色",token="",ticket="")
        self.assertTrue(result.get("error"))
        request.assert_not_called()


class FakeMatcher:
    def __init__(self):
        self.handler = None
    def handle(self):
        def register(fn):
            self.handler = fn
            return fn
        return register


class TestRoleQueryHandlers(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from src.plugins.jx3bot_handlers import queries
        self.module = queries
        self.matchers = {key: FakeMatcher() for key in ("yanhua", "qiyu", "zhuangfen", "jjc", "fuben", "online")}
        queries.register(env=Environment(), **{key+"_matcher": value for key,value in self.matchers.items()})
        self.bot = AsyncMock()
        self.event = type("Event", (), {"group_id":123,"user_id":456})()

    async def test_equipment_handler_resolves_parameters_and_renders(self):
        data={"msg":"success","data":{"equipScore":100,"panelList":[],"equipList":[{"itemName":"武器"}]}}
        resolve=AsyncMock(return_value=("测试服","测试角色"))
        fetch=AsyncMock(return_value=data)
        render=AsyncMock()
        with patch.object(self.module,"resolve_server_and_name",resolve), patch.object(self.module,"fetch_jx3api_or_raise",fetch), patch.object(self.module,"render_and_send_template_image",render):
            await self.matchers["zhuangfen"].handler(self.bot,self.event,("测试角色",None,None))
        resolve.assert_awaited_once_with(("测试角色",None,None),group_id=123)
        self.assertEqual(config.API_URLS["装备查询"],fetch.call_args.kwargs["url"])
        self.assertEqual("ck",render.call_args.kwargs["height"])
        self.assertEqual("武器",render.call_args.kwargs["context"]["equipment"][0]["name"])
        self.bot.send.assert_not_called()

    async def test_equipment_failure_sends_explanation_without_render(self):
        resolve=AsyncMock(return_value=("测试服","测试角色"))
        fetch=AsyncMock(side_effect=self.module.CommandContextError("查询失败",at_user=True))
        send=AsyncMock()
        render=AsyncMock()
        with patch.object(self.module,"resolve_server_and_name",resolve), patch.object(self.module,"fetch_jx3api_or_raise",fetch), patch.object(self.module,"send_text",send), patch.object(self.module,"render_and_send_template_image",render):
            await self.matchers["zhuangfen"].handler(self.bot,self.event,("测试角色",None,None))
        self.assertEqual("查询失败",send.call_args.args[2])
        render.assert_not_called()

    async def test_online_handler_registered_and_calls_current_query(self):
        resolve=AsyncMock(return_value=("测试服","测试角色"))
        query=AsyncMock(return_value="测试服，测试角色：游戏在线")
        send=AsyncMock()
        with patch.object(self.module,"resolve_server_and_name",resolve), patch.object(self.module,"query_online_status",query), patch.object(self.module,"send_text",send):
            await self.matchers["online"].handler(self.bot,self.event,(None,"测试服","测试角色"))
        resolve.assert_awaited_once_with((None,"测试服","测试角色"),group_id=123)
        self.assertEqual(config.API_URLS["在线查询"],query.call_args.kwargs["url"])
        self.assertEqual("测试角色",query.call_args.kwargs["name"])
        self.assertEqual("测试服，测试角色：游戏在线",send.call_args.args[2])
        self.bot.send.assert_not_called()

    async def test_online_missing_group_binding_does_not_query(self):
        resolve=AsyncMock(side_effect=self.module.CommandContextError("本群未绑定服务器"))
        query=AsyncMock()
        send=AsyncMock()
        with patch.object(self.module,"resolve_server_and_name",resolve), patch.object(self.module,"query_online_status",query), patch.object(self.module,"send_text",send):
            await self.matchers["online"].handler(self.bot,self.event,("测试角色",None,None))
        self.assertEqual("本群未绑定服务器",send.call_args.args[2])
        query.assert_not_called()


class MalformedOnlineResponseTests(unittest.TestCase):
    def test_non_object_response_reports_failure_without_crashing(self):
        for response in (None, [], "", 123):
            with self.subTest(response=response):
                self.assertIn("查询失败", format_online_status(response, server="测试服", name="测试角色"))


if __name__=="__main__": unittest.main()

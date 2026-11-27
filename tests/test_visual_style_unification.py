import ast
import re
import sys
import types
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from unittest.mock import patch

try:
    import jinja2  # type: ignore
except ImportError:  # pragma: no cover
    jinja2 = None  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "templates"

ACTIVE_QQ_TEMPLATES = (
    "竞技场心法排名统计.html",
    "竞技场心法排名_前1000奶妈.html",
    "竞技场心法排名_前1000DPS.html",
    "竞技场心法排名_前200奶妈.html",
    "竞技场心法排名_前200DPS.html",
    "竞技场心法排名_前100奶妈.html",
    "竞技场心法排名_前100DPS.html",
    "竞技场心法排名_前50奶妈.html",
    "竞技场心法排名_前50DPS.html",
    "竞技查询.html",
    "jjc.html",
    "装备查询.html",
    "奇遇查询.html",
    "万宝楼查询.html",
    "订阅列表.html",
    "交易行查询.html",
    "烟花查询.html",
    "资历查询.html",
    "百战角色查询.html",
    "百战查询.html",
    "副本查询.html",
    "qun.html",
)

FORBIDDEN_LEGACY_TOKENS = (
    "#89f7fe",
    "#87ceeb",
    "#261e2c",
    "#1c2130",
    "#a3e4d7",
    "#abebc6",
    "127.0.0.1:8000/img/bg.jpg",
    "127.0.0.1:8000/img/baizhan/logo.png",
)

LEGACY_QUERY_CONTEXT_DIMENSIONS = {1194, 870, 1119, 1300, 800, 955, 1500, 640}

_INCLUDE_RE = re.compile(r"\{%\s*(?:include|extends)\s+[\"']([^\"']+)[\"'][^%]*%\}")


def _expand_template_source(template_name: str, seen: Optional[Set[str]] = None) -> str:
    visited = set(seen or set())
    if template_name in visited:
        return ""
    visited.add(template_name)
    path = TEMPLATES_DIR / template_name
    raw = path.read_text(encoding="utf-8")
    parts = [raw]
    for included in _INCLUDE_RE.findall(raw):
        inc_path = TEMPLATES_DIR / included
        if inc_path.is_file():
            parts.append(_expand_template_source(included, visited))
    return "\n".join(parts)


def _sample_jinja_context(template_name: str) -> Dict[str, Any]:
    rank_rows = [("冰心诀", 12, "24.0%", 2500, 25.0)]
    if template_name == "竞技场心法排名统计.html":
        return {
            "current_season": "测试赛季",
            "week_info": "第1周",
            "scope_desc": "前1000、前200、前100、前50",
            "top_1000_healer": rank_rows,
            "top_1000_dps": rank_rows,
            "top_200_healer": rank_rows,
            "top_200_dps": rank_rows,
            "top_100_healer": rank_rows,
            "top_100_dps": rank_rows,
            "top_50_healer": rank_rows,
            "top_50_dps": rank_rows,
            "has_top_1000": True,
            "show_legendary": True,
            "coverage_labels": {"top_50": "心法覆盖 100.0% · 未知 0"},
            "equipment_incomplete": False,
        }
    if template_name.startswith("竞技场心法排名_前"):
        return {
            "current_season": "测试赛季",
            "week_info": "第1周",
            "top_1000_healer": rank_rows,
            "top_1000_dps": rank_rows,
            "top_200_healer": rank_rows,
            "top_200_dps": rank_rows,
            "top_100_healer": rank_rows,
            "top_100_dps": rank_rows,
            "top_50_healer": rank_rows,
            "top_50_dps": rank_rows,
            "show_legendary": True,
            "coverage_label": "心法覆盖 100.0% · 未知 0",
            "equipment_incomplete": False,
        }
    if template_name == "竞技查询.html":
        perf_lane = {
            "mmr": 2400,
            "grade": 13,
            "totalCount": 20,
            "winCount": 12,
            "winRate": 60,
            "mvpCount": 5,
            "ranking": "100",
        }
        return {
            "qufu": "梦江南",
            "id": "测试侠士",
            "text": "测试文案",
            "items": {
                "performance": {"2v2": perf_lane, "3v3": perf_lane, "5v5": perf_lane},
                "history": [
                    {
                        "kungfu": "冰心诀",
                        "avgGrade": 13,
                        "totalMmr": 2400,
                        "mmr": 25,
                        "pvpType": 3,
                        "startTime": 1700000000,
                        "endTime": 1700000180,
                        "won": True,
                        "mvp": True,
                    }
                ],
                "trend": [],
            },
        }
    if template_name == "装备查询.html":
        return {
            "id": "测试侠士",
            "qufu": "梦江南",
            "kungfu": "冰心诀",
            "score": 28000,
            "equip_type": "竞技对抗",
            "season": "测试赛季",
            "collected_at": "2026-01-01 12:00:00",
            "text": "测试文案",
            "core_stats": [{"name": "装分", "value": "28000"}],
            "panel": [{"name": "气血", "value": 60000, "percent": 0}],
            "equipment": [
                {
                    "name": "测试装备",
                    "icon": {"name": "测试装备", "image_src": ""},
                    "attribute_names": ["根骨", "会心"],
                    "source": "名剑大会",
                    "refinement": {"stars": "★★★★★★", "text": "精炼 6/6"},
                    "stone_icons": [],
                    "stones": [],
                    "color_stone_icon": None,
                    "color_stone": "",
                    "enchant_icons": [],
                    "enchants": [],
                }
            ],
        }
    if template_name == "奇遇查询.html":
        return {
            "qufu": "梦江南",
            "id": "测试侠士",
            "zcslist": 1,
            "ptqiyu": 1,
            "jsqiyu": 0,
            "cwqiyu": 0,
            "text": "测试文案",
            "items": [{"event": "雪山恩仇", "level": 1, "time": 1700000000}],
        }
    if template_name == "万宝楼查询.html":
        return {
            "header_image": "",
            "sale_total": 1,
            "public_total": 0,
            "sale_items": [
                {
                    "name": "故梦",
                    "price": 500,
                    "remaining_time": "20小时",
                    "follow_count": 3,
                    "seller": "测试卖家",
                }
            ],
            "public_items": [],
            "is_subscribed": False,
            "subscribed_price": 0,
            "text": "测试文案",
        }
    if template_name == "订阅列表.html":
        grouped = {
            "10001": [{"user_id": "10001", "item_name": "故梦", "price_threshold": 500}]
        }
        return {
            "grouped": grouped,
            "groups": [{"user_id": "10001", "count": 1, "subscriptions": grouped["10001"], "items": grouped["10001"]}],
            "users": [{"user_id": "10001", "count": 1, "subscriptions": grouped["10001"], "items": grouped["10001"]}],
            "subscriptions": grouped["10001"],
            "items": grouped["10001"],
            "user_count": 1,
            "total_users": 1,
            "total_subs": 1,
            "total_subscriptions": 1,
            "message": "所有用户订阅信息",
            "text": "测试文案",
        }
    if template_name == "交易行查询.html":
        return {
            "qufu": "梦江南",
            "mz": "五行石（六级）",
            "ico": "",
            "Desc": "测试物品描述",
            "text": "测试文案",
            "newxs": {"LowestPrice": 10000, "AvgPrice": 12000, "HighestPrice": 15000},
            "newpm": [{"unit_price": 10000, "n_count": 10, "created": 1700000000}],
        }
    if template_name == "烟花查询.html":
        return {
            "qufu": "梦江南",
            "id": "测试侠士",
            "zcslist": 1,
            "csid": 1,
            "jieshou": 0,
            "text": "测试文案",
            "items": [
                {
                    "sender": "测试侠士",
                    "receive": "亲友",
                    "map_name": "扬州",
                    "name": "真橙之心",
                    "time": 1700000000,
                }
            ],
        }
    if template_name == "资历查询.html":
        return {
            "qufu": "梦江南",
            "tongji": [50.0, 100, 100, 50000, 100000, "测试侠士"],
            "zilizonglan": "资历总览",
            "is_second_level": False,
            "text": "测试文案",
            "items": {
                "秘境分布": {"jindu": 50.0, "ydcj": 10, "wdcj": 10, "ydzl": 5000, "wdzl": 10000}
            },
        }
    if template_name == "百战角色查询.html":
        return {
            "zone_name": "电信五区",
            "server_name": "梦江南",
            "role_name": "测试侠士",
            "role_id": "12345",
            "global_role_id": "67890",
            "game_energy": 10000,
            "game_stamina": 10000,
            "skill_count": 1,
            "skills": [{"name": "帝骖龙翔", "level": 5, "icon": ""}],
            "update_time": "2026-01-01 12:00:00",
            "text": "测试文案",
        }
    if template_name == "百战查询.html":
        return {
            "start_date": "2026-01-01",
            "end_date": "2026-01-07",
            "text": "测试文案",
            "items": [
                {
                    "level": i + 1,
                    "name": "首领%d" % (i + 1),
                    "skill": "技能",
                    "data": {},
                    "list_result": [],
                }
                for i in range(10)
            ],
        }
    if template_name == "副本查询.html":
        return {
            "qufu": "梦江南",
            "id": "测试侠士",
            "text": "测试文案",
            "items": {
                "roleId": "12345",
                "data": [
                    {
                        "mapName": "一之窟",
                        "mapType": "25人英雄",
                        "bossProgress": [{"name": "一号首领", "finished": True}],
                    }
                ],
            },
        }
    if template_name == "qun.html":
        return {
            "server": "梦江南",
            "server_push": "开启",
            "news_push": "开启",
            "records_push": "关闭",
            "daily_push": "开启",
            "ranking_push": "开启",
            "group_name": "测试群",
            "group_avatar_url": "",
            "startup_time": "2026-01-01",
            "uptime": "1天",
            "connection_count": 1,
            "last_offline": "无记录",
            "offline_duration": "无记录",
            "last_connect": "2026-01-01",
        }
    return {"text": "测试文案"}


def _func_name(call: ast.Call) -> Optional[str]:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _resolve_ast_scalar(node: Optional[ast.AST], scope_bindings: Dict[str, ast.AST]) -> Any:
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in scope_bindings:
        bound = scope_bindings[node.id]
        if bound is not node:
            return _resolve_ast_scalar(bound, scope_bindings)
    return ast.dump(node)


def _collect_scope_bindings(tree: ast.AST) -> Dict[int, Dict[str, ast.AST]]:
    """Map AST Call id() -> simple scalar variable assignments visible in its enclosing scope."""
    call_scopes: Dict[int, Dict[str, ast.AST]] = {}

    def visit_block(nodes: List[ast.stmt], inherited: Dict[str, ast.AST]) -> None:
        local_bindings = dict(inherited)
        for stmt in nodes:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                local_bindings[stmt.targets[0].id] = stmt.value
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
                local_bindings[stmt.target.id] = stmt.value

            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Call) and id(sub) not in call_scopes:
                    call_scopes[id(sub)] = dict(local_bindings)

            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Override calls inside nested function with inner scope bindings
                for sub in ast.walk(stmt):
                    if isinstance(sub, ast.Call):
                        call_scopes.pop(id(sub), None)
                visit_block(stmt.body, local_bindings)
            elif isinstance(stmt, (ast.If, ast.For, ast.AsyncFor, ast.While)):
                visit_block(stmt.body, local_bindings)
                visit_block(stmt.orelse, local_bindings)
            elif isinstance(stmt, ast.Try):
                visit_block(stmt.body, local_bindings)
                for handler in stmt.handlers:
                    visit_block(handler.body, local_bindings)
                visit_block(stmt.orelse, local_bindings)
                visit_block(stmt.finalbody, local_bindings)
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                visit_block(stmt.body, local_bindings)

    if isinstance(tree, ast.Module):
        visit_block(tree.body, {})
    return call_scopes


def _extract_render_calls(rel_path: str, target_names: Set[str]) -> List[Tuple[str, int, Any, Any]]:
    source = (ROOT / rel_path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=rel_path)
    call_scopes = _collect_scope_bindings(tree)
    results: List[Tuple[str, int, Any, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _func_name(node)
        if name not in target_names:
            continue
        scope = call_scopes.get(id(node), {})
        kw_map = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}

        width_node: Optional[ast.AST] = kw_map.get("width")
        height_node: Optional[ast.AST] = kw_map.get("height")

        if name == "jietu":
            if width_node is None and len(node.args) >= 2:
                width_node = node.args[1]
            if height_node is None and len(node.args) >= 3:
                height_node = node.args[2]
        elif name == "RenderSpec":
            if width_node is None and len(node.args) >= 3:
                width_node = node.args[2]
            if height_node is None and len(node.args) >= 4:
                height_node = node.args[3]
        elif name == "render_template_image":
            if width_node is None and len(node.args) >= 4:
                width_node = node.args[3]
            if height_node is None and len(node.args) >= 5:
                height_node = node.args[4]

        width_val = _resolve_ast_scalar(width_node, scope)
        height_val = "ck" if height_node is None else _resolve_ast_scalar(height_node, scope)
        results.append((name, getattr(node, "lineno", 0), width_val, height_val))

    return sorted(results, key=lambda item: item[1])


class DesignSystemTokenContractTest(unittest.TestCase):
    def test_base_card_style_partial_defines_light_design_tokens(self):
        partial_path = TEMPLATES_DIR / "_partials" / "base_card_style.html"
        self.assertTrue(
            partial_path.is_file(),
            "缺少统一浅色设计系统 partial: %s" % partial_path,
        )
        content = partial_path.read_text(encoding="utf-8")
        expected_tokens = {
            "--jx3-bg": "#f3f6fb",
            "--jx3-surface": "#ffffff",
            "--jx3-ink": "#1e293b",
            "--jx3-primary": "#4f6ef7",
        }
        for var_name, hex_value in expected_tokens.items():
            pattern = r"%s\s*:\s*%s\b" % (re.escape(var_name), re.escape(hex_value))
            self.assertIsNotNone(
                re.search(pattern, content, re.IGNORECASE),
                "base_card_style.html 必须定义 %s: %s" % (var_name, hex_value.upper()),
            )
        self.assertTrue("tabular-nums" in content, "base_card_style.html 必须包含 tabular-nums 数字对齐声明")

    def test_jjc_site_css_adopts_light_tokens_and_removes_stripe_overlay(self):
        css_path = ROOT / "public" / "jjc-site.css"
        self.assertTrue(css_path.is_file(), "缺少站点公共样式: %s" % css_path)
        css_source = css_path.read_text(encoding="utf-8")
        self.assertIsNotNone(
            re.search(r"--jx3-bg\s*:\s*#f3f6fb\b", css_source, re.IGNORECASE),
            "public/jjc-site.css 必须定义浅色变量 --jx3-bg (#F3F6FB)",
        )
        self.assertIsNotNone(
            re.search(r"--jx3-primary\s*:\s*#4f6ef7\b", css_source, re.IGNORECASE),
            "public/jjc-site.css 必须定义浅色变量 --jx3-primary (#4F6EF7)",
        )
        self.assertFalse(
            "repeating-linear-gradient" in css_source.lower(),
            "public/jjc-site.css 不得再包含 .page::before 斜纹 repeating-linear-gradient 遮罩",
        )


class ActiveQqTemplatesVisualUnificationTest(unittest.TestCase):
    def test_all_active_templates_adopt_light_design_system_and_brand(self):
        for template_name in ACTIVE_QQ_TEMPLATES:
            with self.subTest(template=template_name):
                path = TEMPLATES_DIR / template_name
                self.assertTrue(path.is_file(), "缺少活跃模板: %s" % template_name)
                raw = path.read_text(encoding="utf-8")
                expanded = _expand_template_source(template_name)
                has_light_system = ("base_card_style.html" in raw) or ("--jx3-bg" in expanded)
                self.assertTrue(
                    has_light_system,
                    "%s 未接入统一浅色设计体系（缺少 base_card_style.html 引用或 --jx3-bg）" % template_name,
                )
                self.assertTrue(
                    "夏鸥" in expanded,
                    "%s 缺少统一品牌标识『夏鸥』" % template_name,
                )
                self.assertRegex(
                    raw,
                    r"\{%\s*autoescape\s+true\s*%\}",
                    "%s 必须显式启用 {%% autoescape true %%} 防止外部可控文本触发 HTML 注入或吞字" % template_name,
                )

    def test_templates_escape_untrusted_text_and_tolerate_null_edge_fields(self):
        if jinja2 is None:
            return
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)))
        env.filters["time"] = lambda v: "%d秒前" % (v // 1)
        env.filters["timejjc"] = lambda v: "2026-01-01"
        env.filters["jjctime"] = lambda v: "十三" if v == 13 else None
        env.filters["duration"] = lambda v: "%d秒" % (v // 1)
        env.filters["timego"] = lambda v: "" if (v // 100) == 0 else ("1<img src='x.png' alt='金'>")

        # 1. XSS / angle-bracket escaping in qun.html (autoescape=False default env)
        qun_ctx = _sample_jinja_context("qun.html")
        qun_ctx["group_name"] = "剑三<梦江南>亲友群<script>alert(1)</script>"
        qun_html = env.get_template("qun.html").render(**qun_ctx)
        self.assertIn("&lt;梦江南&gt;", qun_html)
        self.assertNotIn("<script>alert(1)</script>", qun_html)

        # 2. Ranking macro must not double-escape its own HTML tags
        rank_ctx = _sample_jinja_context("竞技场心法排名统计.html")
        rank_html = env.get_template("竞技场心法排名统计.html").render(**rank_ctx)
        self.assertIn('<div class="jx3-lane-block">', rank_html)
        self.assertNotIn("&lt;div class=\"jx3-lane-block\"&gt;", rank_html)

        # 3. Trade partial None prices & <100 copper price
        trade_ctx = _sample_jinja_context("交易行查询.html")
        trade_ctx["mz"] = "五行石<测试>"
        trade_ctx["newxs"] = {"LowestPrice": 50, "AvgPrice": None, "HighestPrice": 10000}
        trade_ctx["newpm"] = [{"unit_price": None, "n_count": 5, "created": None}, {"unit_price": 50, "n_count": 2, "created": 1700000000}]
        trade_html = env.get_template("交易行查询.html").render(**trade_ctx)
        self.assertIn("&lt;测试&gt;", trade_html)
        self.assertIn("50<span class=\"currency-unit\">铜</span>", trade_html)
        self.assertIn("<img src='x.png' alt='金'>", trade_html)

        # 4. JJC missing startTime/endTime & unknown grade
        jjc_ctx = _sample_jinja_context("竞技查询.html")
        jjc_ctx["items"]["performance"]["3v3"]["grade"] = 99
        jjc_ctx["items"]["history"] = [{"kungfu": "冰心诀", "avgGrade": None, "totalMmr": 2200, "mmr": -10, "pvpType": 3, "startTime": None, "endTime": None, "won": False}]
        jjc_html = env.get_template("竞技查询.html").render(**jjc_ctx)
        self.assertNotIn("None段", jjc_html)

        # 5. Baizhan numeric list_1 & None skill.level
        bz_ctx = _sample_jinja_context("百战查询.html")
        bz_ctx["items"][0]["list_items"] = {"list_0": "精神提高", "list_1": 100}
        env.get_template("百战查询.html").render(**bz_ctx)

        bz_role_ctx = _sample_jinja_context("百战角色查询.html")
        bz_role_ctx["skills"] = [{"name": "帝骖龙翔", "level": None, "icon": ""}]
        env.get_template("百战角色查询.html").render(**bz_role_ctx)

    def test_all_active_templates_purge_legacy_colors_and_dead_local_assets(self):
        env = None
        if jinja2 is not None:
            env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)))
            env.filters["time"] = lambda v: "1分钟前"
            env.filters["timejjc"] = lambda v: "2026-01-01"
            env.filters["jjctime"] = lambda v: "十三段"
            env.filters["duration"] = lambda v: "3分00秒"
            env.filters["timego"] = lambda v: "1砖"

        for template_name in ACTIVE_QQ_TEMPLATES:
            with self.subTest(template=template_name):
                path = TEMPLATES_DIR / template_name
                self.assertTrue(path.is_file(), "缺少活跃模板: %s" % template_name)
                expanded_lower = _expand_template_source(template_name).lower()
                for forbidden in FORBIDDEN_LEGACY_TOKENS:
                    self.assertFalse(
                        forbidden.lower() in expanded_lower,
                        "%s 残留旧版割裂色值或死链: %s" % (template_name, forbidden),
                    )

                if env is not None:
                    rendered = env.get_template(template_name).render(**_sample_jinja_context(template_name))
                    self.assertTrue("--jx3-bg" in rendered, "%s 渲染结果未包含 --jx3-bg" % template_name)
                    self.assertTrue("夏鸥" in rendered, "%s 渲染结果未包含品牌标识『夏鸥』" % template_name)
                    rendered_lower = rendered.lower()
                    for forbidden in FORBIDDEN_LEGACY_TOKENS:
                        self.assertFalse(
                            forbidden.lower() in rendered_lower,
                            "%s 渲染结果残留旧版割裂色值或死链: %s" % (template_name, forbidden),
                        )


class CanvasWidthUnificationContractTest(unittest.TestCase):
    def test_query_context_render_specs_all_use_760_width_and_ck_height(self):
        rel_path = "src/services/jx3/query_context.py"
        calls = _extract_render_calls(rel_path, {"RenderSpec"})
        self.assertGreaterEqual(len(calls), 6, "%s 中未找到预期的 RenderSpec 调用" % rel_path)
        for name, lineno, width_val, height_val in calls:
            with self.subTest(line=lineno):
                self.assertNotIn(
                    width_val,
                    LEGACY_QUERY_CONTEXT_DIMENSIONS,
                    "%s:%d 仍残留旧版宽度 %r" % (rel_path, lineno, width_val),
                )
                self.assertNotIn(
                    height_val,
                    LEGACY_QUERY_CONTEXT_DIMENSIONS,
                    "%s:%d 仍残留旧版固定高度 %r" % (rel_path, lineno, height_val),
                )
                self.assertEqual(760, width_val, "%s:%d %s width 必须为 760" % (rel_path, lineno, name))
                self.assertEqual("ck", height_val, "%s:%d %s height 必须为 'ck'" % (rel_path, lineno, name))

        # query_context 仅依赖标准库，同时做真实函数调用校验
        from src.services.jx3 import query_context as qc

        self.assertEqual("ck", qc.RenderSpec(template_name="x.html", context={}, width=760).height)
        noop = lambda x: x
        specs = [
            qc.build_yanhua_spec(data={"data": []}, role_name="侠士", server="梦江南", time_filter=noop, random_text=""),
            qc.build_qiyu_spec(
                data={"data": []},
                role_name="侠士",
                server="梦江南",
                time_filter=noop,
                jjc_time_filter=noop,
                random_text="",
            ),
            qc.build_fuben_spec(
                data={"data": {"data": [{"mapName": "一之窟", "mapType": "25人英雄", "bossProgress": []}]}},
                role_name="侠士",
                server="梦江南",
                random_text="",
            ),
            qc.build_jjc_spec_or_text(
                data={"data": {"performance": {"3v3": {"mmr": 2400}}, "history": [], "trend": []}},
                role_name="侠士",
                server="梦江南",
                time_filter=noop,
                jjc_time_filter=noop,
                duration_filter=noop,
                random_text="",
            )[0],
            qc.build_baizhan_spec(
                result={"start_date": "2026-01-01", "end_date": "2026-01-07", "items": []},
                random_text="",
            ),
            qc.build_role_baizhan_spec(
                result={
                    "zone_name": "电信五区",
                    "server_name": "梦江南",
                    "role_name": "侠士",
                    "role_id": "1",
                    "global_role_id": "2",
                    "game_energy": 100,
                    "game_stamina": 100,
                    "skill_count": 0,
                    "skills": [],
                    "update_time": "2026-01-01",
                },
                random_text="",
            ),
        ]
        if hasattr(qc, "build_zhuangfen_spec"):
            specs.append(
                qc.build_zhuangfen_spec(
                    data={"data": {"panelList": {"panel": [{"name": "气血"}]}}},
                    role_name="侠士",
                    server="梦江南",
                    random_text="",
                    mpimg="",
                )
            )
        for spec in specs:
            self.assertIsNotNone(spec)
            self.assertEqual(760, spec.width, "%s width 必须为 760" % spec.template_name)
            self.assertEqual("ck", spec.height, "%s height 必须为 'ck'" % spec.template_name)

        role_calls = _extract_render_calls("src/services/jx3/role_queries.py", {"RenderSpec"})
        self.assertGreaterEqual(len(role_calls), 1)
        for _, lineno, width_val, height_val in role_calls:
            self.assertEqual(760, width_val, "role_queries.py:%d width 必须为 760" % lineno)
            self.assertEqual("ck", height_val, "role_queries.py:%d height 必须为 'ck'" % lineno)

    def test_jjc_ranking_combined_and_split_renders_use_760_width(self):
        rel_path = "src/renderers/jx3/jjc_ranking.py"
        calls = _extract_render_calls(rel_path, {"render_template_image"})
        self.assertGreaterEqual(len(calls), 2, "%s 必须包含合图与拆分图两处 render_template_image 调用" % rel_path)
        for name, lineno, width_val, height_val in calls:
            with self.subTest(line=lineno):
                self.assertEqual(760, width_val, "%s:%d %s width 必须为 760" % (rel_path, lineno, name))
                self.assertEqual("ck", height_val, "%s:%d %s height 必须为 'ck'" % (rel_path, lineno, name))

    def test_trade_help_and_zili_handlers_use_760_width_without_dynamic_horizontal_sizing(self):
        target_funcs = {"render_template_image", "render_and_send_template_image", "jietu"}
        for rel_path in (
            "src/plugins/jx3bot_handlers/trade.py",
            "src/plugins/jx3bot_handlers/help.py",
            "src/plugins/jx3bot_handlers/zili.py",
        ):
            calls = _extract_render_calls(rel_path, target_funcs)
            self.assertGreaterEqual(len(calls), 1, "%s 中未找到模板渲染调用" % rel_path)
            for name, lineno, width_val, height_val in calls:
                with self.subTest(file=rel_path, line=lineno):
                    self.assertEqual(760, width_val, "%s:%d %s width 必须为 760" % (rel_path, lineno, name))
                    self.assertEqual("ck", height_val, "%s:%d %s height 必须为 'ck'" % (rel_path, lineno, name))

        zili_source = (ROOT / "src/plugins/jx3bot_handlers/zili.py").read_text(encoding="utf-8")
        self.assertIsNone(
            re.search(r"225\s*\*\s*len", zili_source),
            "zili.py 不得再使用 225 * len(...) 动态横向宽度",
        )
        self.assertIsNone(
            re.search(r"height\s*=\s*.*?\b390\b", zili_source),
            "zili.py 不得再使用固定高度 390",
        )

    def test_wanbaolou_renders_and_subscription_overflow_use_760_width_and_template(self):
        rel_path = "src/plugins/wanbaolou/__init__.py"
        calls = _extract_render_calls(
            rel_path,
            {"jietu", "render_template_image", "render_and_send_template_image"},
        )
        self.assertGreaterEqual(len(calls), 3, "%s 中应包含外观查询与超长订阅截图调用" % rel_path)
        for name, lineno, width_val, height_val in calls:
            with self.subTest(line=lineno):
                self.assertEqual(760, width_val, "%s:%d %s width 必须为 760" % (rel_path, lineno, name))
                self.assertEqual("ck", height_val, "%s:%d %s height 必须为 'ck'" % (rel_path, lineno, name))

        source = (ROOT / rel_path).read_text(encoding="utf-8")
        self.assertFalse(
            "<pre>" in source,
            "wanbaolou/__init__.py 超长订阅不得再使用裸 f'<pre>{message}</pre>'",
        )
        self.assertTrue(
            "订阅列表.html" in source,
            "wanbaolou/__init__.py 超长订阅必须接入 订阅列表.html 模板",
        )


class ScreenshotViewportTimingAndFooterContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_jietu_sets_target_width_loads_content_waits_images_before_measuring_scroll_height(self):
        from src.infra import screenshot

        events: List[Tuple[Any, ...]] = []
        state: Dict[str, Any] = {
            "viewport_width": 1280,
            "viewport_height": 720,
            "content_loaded": False,
        }

        class FakePage:
            async def set_viewport_size(self, viewport: Dict[str, Any]) -> None:
                state["viewport_width"] = viewport["width"]
                state["viewport_height"] = viewport["height"]
                events.append(("set_viewport_size", viewport["width"], viewport["height"]))

            async def set_content(self, html_content: str, **kwargs: Any) -> None:
                state["content_loaded"] = True
                events.append(("set_content", state["viewport_width"]))

            async def evaluate(self, script: str, *args: Any) -> Any:
                if "scrollHeight" in script:
                    events.append(
                        ("measure_scroll_height", state["content_loaded"], state["viewport_width"])
                    )
                    return 1480
                if ("img" in script and "querySelectorAll" in script) or (
                    "images" in script and "complete" in script
                ):
                    events.append(("wait_images", state["content_loaded"], state["viewport_width"]))
                    return True
                events.append(("evaluate_other", script))
                return None

            async def wait_for_load_state(self, *args: Any, **kwargs: Any) -> None:
                events.append(("wait_for_load_state",))

            async def wait_for_timeout(self, *args: Any, **kwargs: Any) -> None:
                events.append(("wait_for_timeout",))

            async def screenshot(self, **kwargs: Any) -> bytes:
                events.append(("screenshot", state["viewport_width"], state["viewport_height"]))
                return b"fake-card-png"

        class FakeBrowser:
            async def new_page(self, **kwargs: Any) -> FakePage:
                viewport = kwargs.get("viewport") or {}
                if "width" in viewport:
                    state["viewport_width"] = viewport["width"]
                if "height" in viewport:
                    state["viewport_height"] = viewport["height"]
                events.append(("new_page", state["viewport_width"], state["viewport_height"]))
                return FakePage()

            async def close(self) -> None:
                events.append(("close",))

        class FakePlaywrightContext:
            def __init__(self) -> None:
                self.chromium = types.SimpleNamespace(launch=self._launch)

            async def _launch(self, **kwargs: Any) -> FakeBrowser:
                return FakeBrowser()

            async def __aenter__(self) -> "FakePlaywrightContext":
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

        fake_pw_pkg = types.ModuleType("playwright")
        fake_pw_async = types.ModuleType("playwright.async_api")
        fake_pw_async.async_playwright = lambda: FakePlaywrightContext()  # type: ignore[attr-defined]
        fake_pw_pkg.async_api = fake_pw_async  # type: ignore[attr-defined]

        with patch.dict(
            sys.modules,
            {"playwright": fake_pw_pkg, "playwright.async_api": fake_pw_async},
        ):
            result = await screenshot.jietu("<html><body><img src='x.png'></body></html>", 760, "ck")

        self.assertEqual(b"fake-card-png", result)

        event_names = [item[0] for item in events]
        self.assertIn("set_content", event_names, "jietu 必须调用 page.set_content")
        self.assertIn("wait_images", event_names, "jietu 必须执行等待 <img> 加载的 evaluate 脚本")
        self.assertIn("measure_scroll_height", event_names, "jietu 必须测量 scrollHeight")

        idx_set_content = event_names.index("set_content")
        idx_wait_images = event_names.index("wait_images")
        idx_scroll_height = event_names.index("measure_scroll_height")

        self.assertLess(
            idx_set_content,
            idx_scroll_height,
            "set_content 必须在读取 scrollHeight 之前执行，当前顺序: %r" % event_names,
        )
        self.assertLess(
            idx_set_content,
            idx_wait_images,
            "等待 <img> 加载的 evaluate 脚本必须在 set_content 之后执行，当前顺序: %r" % event_names,
        )
        self.assertLess(
            idx_wait_images,
            idx_scroll_height,
            "等待 <img> 加载的 evaluate 脚本必须在读取 scrollHeight 之前执行，当前顺序: %r" % event_names,
        )

        measure_event = events[idx_scroll_height]
        measured_viewport_width = measure_event[2]
        self.assertEqual(
            760,
            measured_viewport_width,
            "读取 scrollHeight 前视口宽度必须已设为目标 width (760)，而非 %r" % measured_viewport_width,
        )

    async def test_jx3web_footer_uses_brand_and_light_surface_color(self):
        from src.infra import screenshot

        evaluated_scripts: List[str] = []

        class FakeElement:
            async def screenshot(self, **kwargs: Any) -> bytes:
                return b"fake-web-png"

        class FakePage:
            async def goto(self, *args: Any, **kwargs: Any) -> None:
                return None

            async def wait_for_selector(self, *args: Any, **kwargs: Any) -> FakeElement:
                return FakeElement()

            async def wait_for_timeout(self, *args: Any, **kwargs: Any) -> None:
                return None

            async def evaluate(self, script: str, *args: Any) -> None:
                evaluated_scripts.append(script)

        class FakeBrowser:
            async def new_page(self, **kwargs: Any) -> FakePage:
                return FakePage()

            async def close(self) -> None:
                return None

        class FakePlaywrightContext:
            def __init__(self) -> None:
                self.chromium = types.SimpleNamespace(launch=self._launch)

            async def _launch(self, **kwargs: Any) -> FakeBrowser:
                return FakeBrowser()

            async def __aenter__(self) -> "FakePlaywrightContext":
                return self

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

        fake_pw_pkg = types.ModuleType("playwright")
        fake_pw_async = types.ModuleType("playwright.async_api")
        fake_pw_async.async_playwright = lambda: FakePlaywrightContext()  # type: ignore[attr-defined]
        fake_pw_pkg.async_api = fake_pw_async  # type: ignore[attr-defined]

        with patch.dict(
            sys.modules,
            {"playwright": fake_pw_pkg, "playwright.async_api": fake_pw_async},
        ):
            result = await screenshot.jx3web("https://example.com", "#main")

        self.assertEqual(b"fake-web-png", result)
        combined_js = "\n".join(evaluated_scripts)
        self.assertIn("夏鸥", combined_js, "jx3web 注入的页脚必须包含『夏鸥』品牌标识")
        self.assertIn(
            "#f3f6fb",
            combined_js.lower(),
            "jx3web 注入的页脚必须采用浅色规范色值 #f3f6fb",
        )


if __name__ == "__main__":
    unittest.main()

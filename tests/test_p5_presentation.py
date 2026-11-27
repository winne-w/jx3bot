import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

from jinja2 import Environment, FileSystemLoader

from src.renderers.jx3.jjc_ranking import (
    _SPLIT_RANKING_LANES,
    _SPLIT_RANKING_TEMPLATE,
    send_split_ranking_images,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "templates"
PUBLIC_DIR = ROOT / "public"


def _make_sample_scope(min_score: int) -> Dict[str, Any]:
    return {
        "total_valid_count": 100,
        "kungfu_cache": {"coverage": 0.95, "unknown": 2},
        "healer": {
            "list": [("离经易道", 12)],
            "valid_count": 20,
            "min_score": min_score,
            "members": {"离经易道": [{"weapon_quality": 5}]},
        },
        "dps": {
            "list": [("冰心诀", 24)],
            "valid_count": 80,
            "min_score": min_score,
            "members": {"冰心诀": [{"weapon_quality": 5}]},
        },
    }


class SplitRankingTemplateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

    def test_parameterized_template_renders_healer_and_dps(self) -> None:
        template = self.env.get_template("竞技场心法排名_分段.html")

        healer_html = template.render(
            current_season="测试赛季",
            week_info="第3周",
            page_title="前50奶妈心法排名",
            pill_label="前50 奶妈心法分布",
            section_title="前50 奶妈心法",
            lane_items=[("离经易道", 12, "60.0%", 2500, 25.0)],
            is_healer=True,
            show_legendary=True,
            coverage_label="心法覆盖 95.0% · 未知 2",
            equipment_incomplete=False,
        )
        self.assertIn("<title>前50奶妈心法排名</title>", healer_html)
        self.assertIn("前50 奶妈心法分布（测试赛季第3周）", healer_html)
        self.assertIn("前50 奶妈心法", healer_html)
        self.assertIn("is-healer", healer_html)
        self.assertIn("离经易道", healer_html)
        self.assertIn("夏鸥", healer_html)
        self.assertIn("--jx3-bg", healer_html)

        dps_html = template.render(
            current_season="测试赛季",
            week_info="第3周",
            page_title="前50DPS心法排名",
            pill_label="前50 DPS心法分布",
            section_title="前50 DPS心法",
            lane_items=[("冰心诀", 24, "30.0%", 2600, 12.5)],
            is_healer=False,
            show_legendary=True,
            coverage_label="心法覆盖 95.0% · 未知 2",
            equipment_incomplete=False,
        )
        self.assertIn("<title>前50DPS心法排名</title>", dps_html)
        self.assertIn("前50 DPS心法分布（测试赛季第3周）", dps_html)
        self.assertIn("前50 DPS心法", dps_html)
        self.assertIn("is-dps", dps_html)
        self.assertIn("冰心诀", dps_html)

    def test_parameterized_template_escapes_untrusted_text(self) -> None:
        template = self.env.get_template("竞技场心法排名_分段.html")
        rendered = template.render(
            current_season="<script>alert(1)</script>",
            week_info="第1周",
            page_title="前50<DPS>心法排名",
            pill_label="前50 DPS心法分布",
            section_title="前50 DPS心法",
            lane_items=[("冰心<诀>", 10, "50.0%", 2400, 0.0)],
            is_healer=False,
            show_legendary=False,
            coverage_label="覆盖<测试>",
            equipment_incomplete=False,
        )
        self.assertNotIn("<script>alert(1)</script>", rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertIn("前50&lt;DPS&gt;心法排名", rendered)
        self.assertIn("冰心&lt;诀&gt;", rendered)
        self.assertIn("覆盖&lt;测试&gt;", rendered)


class SplitRankingRendererTest(unittest.IsolatedAsyncioTestCase):
    async def test_send_split_ranking_images_renders_6_without_top_1000(self) -> None:
        stats = {
            "top_200": _make_sample_scope(2400),
            "top_100": _make_sample_scope(2500),
            "top_50": _make_sample_scope(2600),
        }
        bot = AsyncMock()
        render = AsyncMock(return_value=b"png-bytes")
        env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await send_split_ranking_images(
                bot,
                None,
                env=env,
                render_template_image=render,
                current_season="测试赛季",
                stats=stats,
                week_info="第2周",
                show_legendary=True,
            )

        self.assertEqual(render.await_count, 6)
        self.assertEqual(
            _SPLIT_RANKING_LANES,
            (("healer", "奶妈", True), ("dps", "DPS", False)),
        )
        expected_pairs: List[Any] = [
            ("top_200_healer", "前200奶妈心法排名", "前200 奶妈心法分布", "前200 奶妈心法", True),
            ("top_200_dps", "前200DPS心法排名", "前200 DPS心法分布", "前200 DPS心法", False),
            ("top_100_healer", "前100奶妈心法排名", "前100 奶妈心法分布", "前100 奶妈心法", True),
            ("top_100_dps", "前100DPS心法排名", "前100 DPS心法分布", "前100 DPS心法", False),
            ("top_50_healer", "前50奶妈心法排名", "前50 奶妈心法分布", "前50 奶妈心法", True),
            ("top_50_dps", "前50DPS心法排名", "前50 DPS心法分布", "前50 DPS心法", False),
        ]
        for call, (data_key, page_title, pill_label, section_title, is_healer) in zip(
            render.call_args_list, expected_pairs
        ):
            self.assertEqual(call.args[1], _SPLIT_RANKING_TEMPLATE)
            ctx = call.args[2]
            self.assertEqual(ctx["page_title"], page_title)
            self.assertEqual(ctx["pill_label"], pill_label)
            self.assertEqual(ctx["section_title"], section_title)
            self.assertEqual(ctx["is_healer"], is_healer)
            self.assertIn(data_key, ctx)
            self.assertEqual(ctx["lane_items"], ctx[data_key])
            self.assertEqual(call.kwargs["width"], 760)
            self.assertEqual(call.kwargs["height"], "ck")
            html = env.get_template(call.args[1]).render(**ctx)
            self.assertIn(section_title, html)

    async def test_send_split_ranking_images_renders_8_with_top_1000(self) -> None:
        stats = {
            "top_1000": _make_sample_scope(2200),
            "top_200": _make_sample_scope(2400),
            "top_100": _make_sample_scope(2500),
            "top_50": _make_sample_scope(2600),
        }
        bot = AsyncMock()
        render = AsyncMock(return_value=b"png-bytes")
        env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await send_split_ranking_images(
                bot,
                None,
                env=env,
                render_template_image=render,
                current_season="测试赛季",
                stats=stats,
                week_info="第2周",
                show_legendary=True,
            )

        self.assertEqual(render.await_count, 8)
        first_ctx = render.call_args_list[0].args[2]
        second_ctx = render.call_args_list[1].args[2]
        self.assertEqual(first_ctx["page_title"], "前1000奶妈心法排名")
        self.assertIn("top_1000_healer", first_ctx)
        self.assertTrue(first_ctx["is_healer"])
        self.assertEqual(second_ctx["page_title"], "前1000DPS心法排名")
        self.assertIn("top_1000_dps", second_ctx)
        self.assertFalse(second_ctx["is_healer"])


class PublicJjcCommonTest(unittest.TestCase):
    def test_jjc_common_js_exists_and_exposes_helpers(self) -> None:
        common_js = PUBLIC_DIR / "jjc-common.js"
        self.assertTrue(common_js.is_file(), "缺少公共脚本 public/jjc-common.js")
        content = common_js.read_text(encoding="utf-8")
        self.assertIn("JjcCommon", content)
        self.assertIn("escapeHtml", content)
        self.assertIn("formatTime", content)
        self.assertIn("fetchJson", content)

    def test_four_public_pages_reference_jjc_common_and_delegate_escape_html(self) -> None:
        pages = (
            "index.html",
            "jjc-ranking-stats.html",
            "jjc-synced-matches.html",
            "jjc-sync-queue.html",
        )
        for filename in pages:
            with self.subTest(page=filename):
                content = (PUBLIC_DIR / filename).read_text(encoding="utf-8")
                self.assertIn('<script src="jjc-common.js"></script>', content)
                self.assertIn("window.JjcCommon", content)

    def test_index_and_ranking_stats_are_byte_identical(self) -> None:
        index_bytes = (PUBLIC_DIR / "index.html").read_bytes()
        ranking_bytes = (PUBLIC_DIR / "jjc-ranking-stats.html").read_bytes()
        self.assertEqual(index_bytes, ranking_bytes)


if __name__ == "__main__":
    unittest.main()

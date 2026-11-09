import json
import shutil
import subprocess
import unittest
from pathlib import Path


class TestJjcRankingStatsFrontendCopy(unittest.TestCase):
    def test_history_requests_seasons_then_selected_season_history(self) -> None:
        content = Path("public/jjc-ranking-stats.html").read_text(encoding="utf-8")

        self.assertIn('const SEASONS_API = `${BASE_API}?action=seasons`;', content)
        self.assertIn('function buildSeasonHistoryUrl(season)', content)
        self.assertIn('url.searchParams.set("action", "season-history")', content)
        self.assertIn('async function loadSeasonHistory(season)', content)
        self.assertIn('let seasonHistoryRequestId = 0;', content)
        self.assertIn('if (requestId !== seasonHistoryRequestId)', content)
        self.assertIn('function setSeasonHistoryLoading()', content)
        self.assertIn('[weekSelect, typeSelect, snapshotSelect]', content)
        self.assertIn('function restoreLoadedSeasonControls()', content)
        self.assertIn('let statsRequestId = 0;', content)
        self.assertIn('暂无可用赛季快照数据', content)
        self.assertIn('获取赛季历史失败：', content)
        self.assertNotIn('const DEFAULT_LIST_API = `${BASE_API}?action=list&page=1&page_size=100&with_meta=1`;', content)

    def test_peak_game_labels_use_14_day_window(self) -> None:
        content = Path("public/jjc-ranking-stats.html").read_text(encoding="utf-8")

        self.assertIn("14日游戏内分数排名", content)
        self.assertIn("14日游戏最高分排名", content)
        self.assertIn("回溯前 14 天本地已收录的 3v3 对局", content)
        self.assertIn("正在加载14日最高分心法分布...", content)
        self.assertIn("14日最高分心法分布加载完成", content)
        self.assertIn("加载14日最高分心法分布失败", content)
        self.assertIn("_14日游戏最高分排名", content)

    def test_peak_game_detail_uses_dedicated_details_api(self) -> None:
        content = Path("public/jjc-ranking-stats.html").read_text(encoding="utf-8")

        self.assertIn("function buildPeakDetailsUrl(timestamp, scoreType, rangeKey, kungfu)", content)
        self.assertIn("currentOuterTab === \"peak-game\"", content)
        self.assertIn("buildPeakDetailsUrl(currentStatsTimestamp, \"game\", rangeKey, kungfu)", content)

    def test_peak_scope_copy_preserves_legacy_and_displays_actual_season_window(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is required to verify frontend scope behavior")
        content = Path("public/jjc-ranking-stats.html").read_text(encoding="utf-8")
        function = "function getRankingScopeText(" + content.split("function getRankingScopeText(", 1)[1].split("function syncScopeInlineText(", 1)[0]
        source = """
const PEAK_SCOPE_CACHE_KEY = "season_bounded_v1";
const peakScopeByTimestamp = new Map();
let currentStatsTimestamp = "123";
function formatTime(value) { return `time:${value}`; }
""" + function + """
const bounded = { aggregation_scope: PEAK_SCOPE_CACHE_KEY, window_start: 100, window_end: 123 };
peakScopeByTimestamp.set("123", bounded);
const mapped = getRankingScopeText("peak-game");
const legacy = getRankingScopeText("peak-game", {});
const exported = getRankingScopeText("peak-game", bounded);
currentStatsTimestamp = "older";
const otherSnapshot = getRankingScopeText("peak-game");
console.log(JSON.stringify({mapped, legacy, exported, otherSnapshot}));
"""
        result = subprocess.run([node, "-e", source], check=True, text=True, capture_output=True)
        texts = json.loads(result.stdout)
        self.assertIn("最多至所选赛季开赛时间", texts["mapped"])
        self.assertIn("不足 14 天按实际天数统计", texts["mapped"])
        self.assertIn("实际窗口：time:100 至 time:123", texts["mapped"])
        self.assertEqual(texts["mapped"], texts["exported"])
        self.assertNotIn("所选赛季开赛时间", texts["legacy"])
        self.assertNotIn("实际窗口", texts["legacy"])
        self.assertEqual(texts["legacy"], texts["otherSnapshot"])

    def test_peak_distribution_and_cache_keys_keep_the_scope_metadata(self) -> None:
        content = Path("public/jjc-ranking-stats.html").read_text(encoding="utf-8")
        self.assertIn('const PEAK_SCOPE_CACHE_KEY = "season_bounded_v1";', content)
        self.assertIn('["peak-game", PEAK_SCOPE_CACHE_KEY, timestamp, "distribution"]', content)
        self.assertIn('["peak-game", PEAK_SCOPE_CACHE_KEY, currentStatsTimestamp, "distribution"]', content)
        self.assertIn('source === "peak-game" ? PEAK_SCOPE_CACHE_KEY', content)
        self.assertIn('isPeakTab(outerTab) ? PEAK_SCOPE_CACHE_KEY', content)
        self.assertIn('aggregation_scope: firstResult.aggregation_scope', content)
        self.assertIn('window_start: firstResult.window_start', content)
        self.assertIn('window_end: firstResult.window_end', content)
        self.assertIn('getRankingScopeText(exportTab, payload)', content)

    def test_full_page_export_rebuilds_only_the_clone(self) -> None:
        content = Path("public/jjc-ranking-stats.html").read_text(encoding="utf-8")
        export = content.split("async function exportFullPageImage(modeOverride)", 1)[1]
        export = export.split("if (legendaryToggle)", 1)[0]

        self.assertIn("onclone(clonedDocument, clonedPage)", export)
        self.assertIn("prepareDistributionExportClone(clonedDocument, clonedPage, exportMarkup)", export)
        self.assertIn("windowWidth: 1120", export)
        self.assertIn("getPeakDistributionStats(timestamp)", export)
        self.assertIn("fullPageExportInProgress = false;", export)
        self.assertNotIn("currentOuterTab =", export)
        self.assertNotIn("renderCurrentView()", export)
        self.assertNotIn("pageNode.classList", export)
        self.assertNotIn('removeAttribute("open")', export)

    def test_distribution_export_has_paired_lanes_and_no_live_controls(self) -> None:
        content = Path("public/jjc-ranking-stats.html").read_text(encoding="utf-8")
        markup = content.split("function buildDistributionExportMarkup(", 1)[1]
        markup = markup.split("function prepareDistributionExportClone(", 1)[0]
        clone = content.split("function prepareDistributionExportClone(", 1)[1]
        clone = clone.split("let fullPageExportInProgress", 1)[0]

        self.assertIn('[["healer", "奶妈"], ["dps", "DPS"]]', markup)
        self.assertIn('class="export-range-row"', markup)
        self.assertIn('class="export-image-header"', markup)
        self.assertIn('class="export-image-source"', markup)
        self.assertIn("${seasonText}", markup)
        self.assertIn("escapeHtml(description)", markup)
        self.assertNotIn("<input", markup)
        self.assertNotIn("<nav", markup)
        self.assertNotIn("<select", markup)
        self.assertIn('clonedPage.className = "export-image";', clone)
        self.assertIn("clonedPage.innerHTML = exportMarkup;", clone)
        self.assertIn("grid-template-columns:repeat(2,minmax(0,1fr))", clone)
        self.assertIn("clonedDocument.head.appendChild(style)", clone)

    def test_export_captures_overlay_without_changing_the_live_setting(self) -> None:
        content = Path("public/jjc-ranking-stats.html").read_text(encoding="utf-8")
        self.assertIn("legendaryCountMap, overlayEnabled = showLegendaryOverlay)", content)
        self.assertIn("const overlayPercent = overlayEnabled ? legendaryPercent : 0;", content)
        self.assertIn("const overlayEnabled = showLegendaryOverlay;", content)

    def test_synced_matches_role_indicator_preserves_global_id_and_error_message(self) -> None:
        content = Path("public/jjc-synced-matches.html").read_text(encoding="utf-8")

        self.assertIn('["game_role_id", "global_role_id", "global_id", "role_id", "zone"]', content)
        self.assertIn("const errorMessage = indicatorData.message || \"稍后再试\";", content)
        self.assertIn("escapeHtml(errorMessage)", content)


if __name__ == "__main__":
    unittest.main()

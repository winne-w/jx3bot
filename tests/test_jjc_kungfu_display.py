"""Snapshot coverage must remain visible; missing equipment is not purple gear."""
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from jinja2 import Environment, FileSystemLoader
from src.renderers.jx3.jjc_ranking import render_combined_ranking_image


class KungfuDisplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_snapshot_labels_coverage_and_suppresses_incomplete_equipment(self):
        stats = {"top_50": {
            "kungfu_cache": {"total": 4, "fresh": 1, "stale": 1, "unknown": 2, "coverage": .5},
            "healer": {"list": [], "valid_count": 0, "equipment_incomplete": True},
            "dps": {"list": [["冰心诀", 2]], "valid_count": 2, "equipment_incomplete": True,
                    "members": {"冰心诀": [{"weapon_quality": None}]}}}}
        render = AsyncMock(return_value=b"image")
        await render_combined_ranking_image(env=None, render_template_image=render,
            current_season="season", stats=stats, week_info="week", show_legendary=True)
        template, context = render.call_args.args[1:]
        self.assertFalse(context["show_legendary"])
        html = Environment(loader=FileSystemLoader("templates")).get_template(template).render(**context)
        self.assertIn("未知 2", html)
        self.assertIn("50.0%", html)
        self.assertIn("装备数据不完整", html)

    async def test_legacy_snapshot_explicitly_labels_unrecorded_freshness(self):
        render = AsyncMock(return_value=b"image")
        await render_combined_ranking_image(env=None, render_template_image=render,
            current_season="season", stats={}, week_info="week", show_legendary=True)
        context = render.call_args.args[2]
        self.assertTrue(context["show_legendary"])
        html = Environment(loader=FileSystemLoader("templates")).get_template(render.call_args.args[1]).render(**context)
        self.assertIn("未记录时效", html)

    def test_web_pages_match_and_equipment_filter_handles_incomplete_samples(self):
        page = Path("public/jjc-ranking-stats.html").read_text()
        self.assertEqual(page, Path("public/index.html").read_text())
        self.assertIn("function renderKungfuCoverage(", page)
        self.assertIn("装备数据不完整", page)

    def test_purple_list_does_not_request_or_label_unchecked_equipment(self):
        import shutil
        import subprocess
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required to execute the frontend list branch")
        page = Path("public/index.html").read_text()
        functions = page[page.index("        function renderListView("):page.index("        function syncOuterTabUI(")]
        equipment = page[page.index("        function hasIncompleteEquipment("):page.index("        function renderKungfuCoverage(")]
        harness = """
const assert = require('node:assert/strict');
let currentStats = {kungfu_statistics:{top_50:{healer:{equipment_incomplete:true},dps:{equipment_incomplete:true}}}};
let currentStatsTimestamp = 1793923200;
let grid = {innerHTML:''};
let calls = 0;
let rankingListCache = new Map();
const getListSourceConfig = () => ({api:'flat-members'});
const buildFlatMembersUrl = () => 'fixture';
const buildPeakScoreUrl = () => 'fixture';
const setStatus = () => {};
const unwrapResponse = x => x;
const fetch = async () => {calls++;return {ok:true,json:async()=>({items:[]})};};
const isPeakTab = () => false;
const rangeConfigs = [{key:'top_50',label:'前50'}];
const getOuterTabLabel = () => '推栏排名-紫武';
const formatTime = () => 'fixture time';
const escapeHtml = x => String(x);
"""
        check = """
(async () => {
  await loadRankingListView('purple','top_50');
  assert.equal(calls, 0, 'unchecked equipment must not load a purple list');
  assert.match(grid.innerHTML, /装备数据不完整/);
  renderListView({items:[]},'purple','top_50');
  assert.match(grid.innerHTML, /装备数据不完整/);
})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run([node,"-e",harness+equipment+functions+check], capture_output=True, text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_equipment_decision_is_pure_and_shared_by_distribution_filter_and_export(self):
        import shutil
        import subprocess
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required for frontend behavior tests")
        page = Path("public/index.html").read_text()
        distribution = page[page.index("        function renderList("):page.index("        function buildFilteredStats(")]
        export = page[page.index("        function buildDistributionExportMarkup("):page.index("        function prepareDistributionExportClone(")]
        harness = """
const assert = require('node:assert/strict');
const window = {currentSeasonLabel:'fixture season'};
const rangeConfigs = [{key:'top_50',label:'前50'}];
const getOuterTabLabel = () => 'fixture';
const escapeHtml = x => String(x);
const showLegendaryOverlay = true;
const grid = {innerHTML:'unchanged'};
"""
        check = """
const lane = Object.freeze({list:[['冰心诀',2]],valid_count:2,legendary_count_map:{'冰心诀':1},equipment_incomplete:true});
const range = Object.freeze({healer:{list:[],valid_count:0},dps:lane,kungfu_cache:{coverage:1,fresh:2,stale:0,unknown:0}});
const before = JSON.stringify(range);
assert.equal(typeof hasIncompleteEquipment, 'function', 'equipment decision must be callable without rendering');
assert.equal(hasIncompleteEquipment(range.healer,range.dps),true);
assert.equal(hasIncompleteEquipment(undefined,null,{}),false, 'legacy snapshots retain old behavior');
assert.equal(hasIncompleteEquipment({equipment_incomplete:false}),false);
assert.equal(grid.innerHTML,'unchanged','decision must not write the DOM');
assert.match(renderKungfuCoverage(range),/装备数据不完整/);
const card = renderRangeCard('top_50','前50',range,'all');
assert.match(card,/class="bar-legendary" style="width:0%"/);
assert.deepEqual(buildFilteredLane(lane,'purple').list,[]);
const markup = buildDistributionExportMarkup({kungfu_statistics:{top_50:range}},'all','fixture','fixture',true);
assert.match(markup,/装备数据不完整/);
assert.match(markup,/class="bar-legendary" style="width:0%"/);
const legacy = {list:[['冰心诀',2]],valid_count:2,legendary_count_map:{'冰心诀':1}};
assert.equal(buildFilteredLane(legacy,'purple').valid_count,1);
assert.equal(JSON.stringify(range),before,'rendering and filtering must not mutate snapshot input');
"""
        result = subprocess.run([node,"-e",harness+distribution+export+check],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

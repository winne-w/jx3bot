"""Stable static contracts for the standalone JJC matchup page.

These checks intentionally cover only page structure and nearby request/display
semantics; they do not prove runtime state propagation or interaction results.
Those browser behaviours belong to the later frontend test stage.
"""

import re
import unittest
from pathlib import Path
from typing import Iterable


PAGE_PATH = Path("public/jjc-matchups.html")


class TestJjcMatchupsFrontendContract(unittest.TestCase):
    def _page_source(self) -> str:
        if not PAGE_PATH.is_file():
            self.fail(
                "JJC matchup frontend is missing: expected "
                "public/jjc-matchups.html"
            )
        return PAGE_PATH.read_text(encoding="utf-8")

    def _assert_contains_all(self, source: str, values: Iterable[str]) -> None:
        for value in values:
            with self.subTest(value=value):
                self.assertIn(value, source)

    def _near(self, source: str, term: str, distance: int = 900) -> str:
        regions = []
        for match in re.finditer(re.escape(term), source, re.I):
            regions.append(source[max(0, match.start() - distance):match.end() + distance])
        return "\n".join(regions)

    def _endpoint_expression_regions(self, source: str, suffix: str) -> list:
        """Return regions around production-default or configured endpoint expressions."""
        regions = []
        full_route = re.compile(
            r"/jx3bot/api/jjc/matchups/" + re.escape(suffix),
        )
        for match in full_route.finditer(source):
            regions.append(source[max(0, match.start() - 400):match.end() + 1800])

        base_names = []
        base_declaration = re.compile(
            r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
            r"[^;]{0,800}/jx3bot/api/jjc/matchups",
            re.DOTALL,
        )
        for match in base_declaration.finditer(source):
            base_names.append(match.group(1))
        if base_names:
            composed_route = re.compile(
                r"(?:\$\{\s*(?:" + "|".join(map(re.escape, base_names))
                + r")\s*\}|(?:" + "|".join(map(re.escape, base_names)) + r"))"
                r"[^;\n]{0,800}/" + re.escape(suffix),
                re.DOTALL,
            )
            for match in composed_route.finditer(source):
                regions.append(source[max(0, match.start() - 400):match.end() + 1800])
        return regions

    def _has_meta_get_semantics(self, endpoint_region: str) -> bool:
        """Accept explicit GET, or only the native single-argument fetch default."""
        if re.search(r"method\s*:\s*[\"']GET[\"']", endpoint_region):
            return True
        return re.search(
            r"fetch\s*\(\s*(?:[A-Za-z_$][\w$]*|[\"'`][^\"'`]*?/meta[^\"'`]*[\"'`])\s*\)",
            endpoint_region,
        ) is not None

    def _local_kungfu_directory_declarations(self, source: str) -> list:
        """Read one array/object declaration at a time; never scan across it."""
        declarations = []
        pattern = re.compile(
            r"(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*([\[{])",
        )
        for match in pattern.finditer(source):
            opening = match.group(1)
            closing = "]" if opening == "[" else "}"
            depth = 0
            quote = ""
            escaped = False
            end = match.end()
            for index in range(match.end() - 1, min(len(source), match.end() + 6000)):
                character = source[index]
                if quote:
                    if escaped:
                        escaped = False
                    elif character == "\\":
                        escaped = True
                    elif character == quote:
                        quote = ""
                    continue
                if character in "\"'`":
                    quote = character
                elif character == opening:
                    depth += 1
                elif character == closing:
                    depth -= 1
                    if depth == 0:
                        end = index + 1
                        break
            declarations.append(source[match.start():end])
        return declarations

    def _has_large_local_kungfu_directory(self, source: str) -> bool:
        for declaration in self._local_kungfu_directory_declarations(source):
            id_count = len(re.findall(
                r"(?:\b|[\"'])(?:id|kungfu_id)(?:\b|[\"'])\s*:\s*\d{3,}",
                declaration,
            ))
            has_metadata = re.search(
                r"(?:\b|[\"'])(?:name|icon(?:_id)?)(?:\b|[\"'])\s*:",
                declaration,
            )
            if id_count >= 4 and has_metadata:
                return True
        return False

    def test_endpoint_helper_accepts_production_forms_and_rejects_invalid_defaults(self) -> None:
        inline_source = (
            'const API_BASE = "/jx3bot/api/jjc/matchups"; '
            'fetch(`${API_BASE}/meta`); '
            'fetch(`${API_BASE}/search`, {method: "POST", '
            'headers: {"Content-Type": "application/json"}});'
        )
        direct_source = 'fetch("/jx3bot/api/jjc/matchups/meta");'
        wrong_suffix = 'const API_BASE = "/jx3bot/api/jjc/matchups"; fetch(`${API_BASE}/details`);'
        bare_default = 'const API_BASE = "/api/jjc/matchups"; fetch(`${API_BASE}/meta`);'

        self.assertTrue(self._endpoint_expression_regions(inline_source, "meta"))
        self.assertTrue(self._endpoint_expression_regions(inline_source, "search"))
        self.assertTrue(self._endpoint_expression_regions(direct_source, "meta"))
        self.assertFalse(self._endpoint_expression_regions(wrong_suffix, "meta"))
        self.assertFalse(self._endpoint_expression_regions(bare_default, "meta"))
        self.assertTrue(self._has_meta_get_semantics(
            self._endpoint_expression_regions(inline_source, "meta")[0]
        ))
        self.assertTrue(self._has_meta_get_semantics(
            'request("/jx3bot/api/jjc/matchups/meta", {method: "GET"})'
        ))
        self.assertFalse(self._has_meta_get_semantics(
            'request("/jx3bot/api/jjc/matchups/meta")'
        ))

    def test_local_kungfu_directory_helper_handles_quoted_and_small_catalogs(self) -> None:
        quoted_roster = (
            'const roster = [{"id":1001,"name":"a"},{"id":1002,"name":"b"},'
            '{"id":1003,"icon_id":3},{"kungfu_id":1004,"name":"d"}];'
        )
        small_roster = (
            'const roster = [{"id":1001,"name":"a"},{"id":1002,"name":"b"},'
            '{"id":1003,"name":"c"}];'
        )

        self.assertTrue(self._has_large_local_kungfu_directory(quoted_roster))
        self.assertFalse(self._has_large_local_kungfu_directory(small_roster))

    def test_page_exists_at_the_standalone_public_path(self) -> None:
        self._page_source()

    def test_identifies_meta_and_search_routes_with_deployable_api_base(self) -> None:
        source = self._page_source()

        self.assertTrue(self._endpoint_expression_regions(source, "meta"))
        self.assertTrue(self._endpoint_expression_regions(source, "search"))

    def test_keeps_meta_get_and_search_json_post_semantics_locally_visible(self) -> None:
        source = self._page_source()

        meta_regions = self._endpoint_expression_regions(source, "meta")
        search_regions = self._endpoint_expression_regions(source, "search")
        self.assertTrue(meta_regions, "meta endpoint expression is required")
        self.assertTrue(search_regions, "search endpoint expression is required")
        self.assertTrue(
            any(self._has_meta_get_semantics(region) for region in meta_regions),
            "meta endpoint expression must have local native-fetch GET or explicit GET semantics",
        )
        self.assertTrue(
            any(re.search(r"method\s*:\s*[\"']POST[\"']", region) for region in search_regions),
            "search endpoint expression must have a local POST description",
        )
        self.assertTrue(
            any(
                re.search(
                    r"content-type\s*[\"']?\s*:\s*[\"']application/json",
                    region,
                    re.I,
                )
                for region in search_regions
            ),
            "search endpoint expression must have a local JSON content type",
        )

    def test_declares_all_search_request_fields(self) -> None:
        source = self._page_source()

        self._assert_contains_all(source, (
            "start_time",
            "end_time",
            "score_min",
            "score_max",
            "team_a_kungfu_ids",
            "team_b_kungfu_ids",
            "page",
            "page_size",
        ))

    def test_exposes_default_seven_day_absolute_time_and_url_query_semantics(self) -> None:
        source = self._page_source()

        self.assertRegex(source, r"(?:default|initial|selected|data-days)[^;\n]{0,160}\b7\b")
        self.assertRegex(source, r"(?:7|days|preset)[^;\n]{0,80}\*\s*24\s*\*\s*60\s*\*\s*60")
        self._assert_contains_all(source, ("start_time", "end_time"))
        self.assertRegex(
            source,
            r"(?:URLSearchParams|location\.(?:search|href)|history\.|new\s+URL\s*\()",
        )

    def test_exposes_shanghai_end_date_next_day_midnight_semantics(self) -> None:
        source = self._page_source()

        self.assertIn("Asia/Shanghai", source)
        self.assertRegex(source, r"(?:end[-_]?date|endDate|结束日期)")
        self.assertRegex(
            source,
            r"(?:次日|next\s*day|\+\s*1|addDays\s*\([^)]*,\s*1)",
        )
        self.assertRegex(source, r"(?:00:00(?::00)?|T00:00:00|午夜)")

    def test_declares_meta_kungfus_and_two_bounded_empty_array_team_filters(self) -> None:
        source = self._page_source()

        self._assert_contains_all(source, (
            "kungfus",
            "team_a_kungfu_ids",
            "team_b_kungfu_ids",
            "[]",
        ))
        self.assertRegex(source, r"(?:max_team_kungfus|maxTeamKungfus|length)[^;\n]{0,180}\b3\b")
        self.assertFalse(
            self._has_large_local_kungfu_directory(source),
            "page must consume meta rather than keep a second large kungfu directory",
        )

    def test_exposes_exchange_and_source_team_semantics_and_does_not_explicitly_set_dedupe(self) -> None:
        source = self._page_source()

        self.assertRegex(source, r"(?:交换|互换|swap)")
        self._assert_contains_all(source, ("team1", "team2"))
        request_regions = (
            self._near(source, "team_a_kungfu_ids", 500)
            + self._near(source, "team_b_kungfu_ids", 500)
        )
        self.assertNotRegex(
            request_regions,
            r"new\s+Set\s*\([^)]*(?:team[A-B]|team_[ab]|kungfu)",
        )

    def test_exposes_score_bounds_and_disabled_strict_range_semantics(self) -> None:
        source = self._page_source()

        self._assert_contains_all(source, ("score_min", "score_max"))
        self.assertRegex(source, r"(?:disabled|aria-disabled)")
        self.assertRegex(
            source,
            r"(?:score[_-]?min|scoreMin|minimum)[\s\S]{0,260}<"
            r"[\s\S]{0,260}(?:score[_-]?max|scoreMax|maximum)",
        )

    def test_exposes_meta_page_sizes_and_search_page_size(self) -> None:
        source = self._page_source()

        self._assert_contains_all(source, ("page_sizes", "page_size"))

    def test_exposes_raw_statistics_orientation_and_existing_detail_contracts(self) -> None:
        source = self._page_source()

        self._assert_contains_all(source, (
            "match_count",
            "orientation_sample_count",
            "team_a_wins",
            "team_b_wins",
            "team_a_win_rate",
            "team_b_win_rate",
            "bidirectional_match_count",
            "missing_score_match_count",
            "matched_orientations",
            "forward",
            "reverse",
            "match_id",
            "/api/jjc/ranking-stats/match-detail",
        ))
        self.assertRegex(source, r"(?:forward\+reverse|bidirectional|双向)")
        self.assertRegex(source, r"(?:all-empty|全量|无方向|不限|\[\])")
        self.assertNotRegex(
            source,
            r"(?i)(?:advantage|disadvantage|confidence(?:_interval)?|"
            r"sample_sufficien|优势|劣势|均势|置信(?:区间)?|样本充分)",
        )

    def test_hidden_detail_modal_cannot_intercept_page_pointer_events(self) -> None:
        source = self._page_source()

        self.assertRegex(
            source,
            r"(?:\.match-detail-overlay\s*)?\[hidden\]\s*\{[^}]*"
            r"display\s*:\s*none\s*!important\s*;?[^}]*\}",
            "the class display rule must not override the modal's hidden state",
        )

    def test_results_use_a_match_list_and_win_rate_split_layout(self) -> None:
        source = self._page_source()

        self._assert_contains_all(source, (
            'class="results-workspace"',
            'class="match-column"',
            'id="win-rate-panel"',
            'id="team-a-rate-bar"',
            'id="team-b-rate-bar"',
        ))
        self.assertRegex(
            source,
            r"\.results-workspace\s*\{[^}]*display\s*:\s*grid[^}]*"
            r"grid-template-columns\s*:\s*minmax\([^)]*\)\s+minmax\(",
        )

    def test_match_rows_are_full_card_detail_triggers_with_kungfu_icons(self) -> None:
        source = self._page_source()

        self._assert_contains_all(source, (
            'className = "match-card"',
            'renderKungfuPortrait',
            'data-match-id',
            '查看完整对局',
            'https://img.jx3box.com/image/xf/',
        ))

    def test_picker_groups_healers_and_dps_and_exposes_icon_options(self) -> None:
        source = self._page_source()

        self._assert_contains_all(source, (
            'class="kungfu-picker"',
            'class="kungfu-picker-menu"',
            '输出 DPS',
            '奶妈',
            'data-picker-id',
            'renderKungfuPicker',
            'https://img.jx3box.com/image/xf/',
        ))

    def test_detail_modal_matches_synced_match_team_and_player_structure(self) -> None:
        source = self._page_source()

        self._assert_contains_all(source, (
            'className = "team-grid"',
            'className = `team-card',
            'className = "team-player"',
            'className = "team-kungfu-icons"',
            'className = "player-section"',
            'className = "icon-grid"',
            'className = "talent-grid"',
            'data-detail-item',
            'data-detail-item-type", "equipment"',
            'data-detail-item-type", "talent"',
        ))


if __name__ == "__main__":
    unittest.main()

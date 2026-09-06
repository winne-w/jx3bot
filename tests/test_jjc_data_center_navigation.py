import html
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGES = {
    "index.html": "ranking",
    "jjc-ranking-stats.html": "ranking",
    "jjc-synced-matches.html": "matches",
    "jjc-matchups.html": "matchups",
}
NAV_HREFS = {"index.html", "jjc-synced-matches.html", "jjc-matchups.html"}
SHELL_RULES = (".page", ".site-header", ".site-brand", ".site-nav", ".site-nav a")


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.attrs_by_tag = []
        self.text_parts = []

    def handle_starttag(self, tag, attrs):
        self.attrs_by_tag.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text_parts.append(data)


class JjcDataCenterNavigationTest(unittest.TestCase):
    def _load(self, filename):
        path = ROOT / "public" / filename
        self.assertTrue(path.exists(), "missing page: %s" % path)
        source = path.read_text(encoding="utf-8")
        parser = _PageParser()
        parser.feed(source)
        return source, parser, " ".join(parser.text_parts)

    def test_pages_expose_common_brand_and_navigation(self):
        for filename in PAGES:
            _, parser, text = self._load(filename)
            self.assertIn("JJC 数据中心", html.unescape(text), filename)
            links = {
                attrs.get("href")
                for tag, attrs in parser.attrs_by_tag
                if tag == "a" and attrs.get("href") in NAV_HREFS
            }
            self.assertEqual(NAV_HREFS, links, filename)

    def test_each_page_marks_current_navigation_item(self):
        for filename, expected in PAGES.items():
            _, parser, _ = self._load(filename)
            current = [
                attrs.get("href")
                for tag, attrs in parser.attrs_by_tag
                if tag == "a" and attrs.get("aria-current") == "page"
            ]
            self.assertEqual(1, len(current), filename)
            expected_href = {
                "ranking": "index.html",
                "matches": "jjc-synced-matches.html",
                "matchups": "jjc-matchups.html",
            }[expected]
            self.assertEqual(expected_href, current[0], filename)

    def test_existing_business_dom_remains_available(self):
        expectations = {
            "index.html": (r'id=["\']grid["\']',),
            "jjc-ranking-stats.html": (r'id=["\']grid["\']',),
            "jjc-synced-matches.html": (r'id=["\']search-form["\']',),
            "jjc-matchups.html": (r'id=["\']submit-search["\']',),
        }
        for filename, patterns in expectations.items():
            source, _, _ = self._load(filename)
            for pattern in patterns:
                self.assertRegex(source, pattern, filename)

    def test_shared_shell_styles_load_after_page_styles(self):
        self.assertTrue((ROOT / "public/jjc-site.css").is_file())
        for filename in PAGES:
            source, parser, _ = self._load(filename)
            links = [attrs for tag, attrs in parser.attrs_by_tag
                     if tag == "link" and attrs.get("href") == "jjc-site.css"]
            self.assertEqual(1, len(links), filename)
            self.assertEqual("stylesheet", links[0].get("rel"))
            self.assertGreater(source.index('href="jjc-site.css"'), source.rindex("</style>"))

    def test_synced_matches_header_stacks_on_narrow_screens(self):
        source, _, _ = self._load("jjc-synced-matches.html")
        mobile_rule = re.search(r"@media\s*\(max-width:\s*(?:700|720)px\)[\s\S]*", source)
        self.assertIsNotNone(mobile_rule)
        header_rule = re.search(r"\.site-header\s*\{([^}]*)\}", mobile_rule.group(0))
        self.assertIsNotNone(header_rule)
        self.assertRegex(header_rule.group(1), r"flex-direction\s*:\s*column")

    def test_pages_share_the_visual_shell_contract(self):
        shell_rules = {}
        for filename in PAGES:
            source, _, _ = self._load(filename)
            self.assertRegex(source, r"\.page\s*\{[^}]*max-width\s*:\s*1280px", filename)
            self.assertRegex(source, r'class=["\'][^"\']*\bpage-title-region\b[^"\']*["\']', filename)
            self.assertRegex(source, r"@media\s*\(max-width:\s*(?:700|760|720)px\)[\s\S]*?\.site-header\s*\{[^}]*flex-direction\s*:\s*column", filename)
            shell_rules[filename] = {
                selector: re.sub(r"\s+", " ", re.search(r"%s\s*\{([^}]*)\}" % re.escape(selector), source).group(1)).strip()
                for selector in SHELL_RULES
            }

        expected = shell_rules["index.html"]
        for filename, rules in shell_rules.items():
            self.assertEqual(expected, rules, filename)

    def test_pages_offer_announcement_and_feedback_entry_points(self):
        for filename in PAGES:
            source, parser, _ = self._load(filename)
            ids = {
                attrs.get("id")
                for _, attrs in parser.attrs_by_tag
                if attrs.get("id")
            }
            self.assertTrue(
                {"announcement-modal", "announcement-modal-body", "floating-feedback", "floating-feedback-close"} <= ids,
                filename,
            )
            self.assertIn('ANNOUNCEMENT_API = "/jx3bot/api/announcements"', source, filename)


if __name__ == "__main__":
    unittest.main()

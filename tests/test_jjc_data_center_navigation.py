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

    def test_synced_matches_header_stacks_on_narrow_screens(self):
        source, _, _ = self._load("jjc-synced-matches.html")
        mobile_rule = re.search(
            r"@media\s*\(max-width:\s*720px\)(.*?)(?:\n\s*}\s*</style>)",
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(mobile_rule)
        header_rule = re.search(r"\.site-header\s*\{([^}]*)\}", mobile_rule.group(1))
        self.assertIsNotNone(header_rule)
        self.assertRegex(header_rule.group(1), r"flex-direction\s*:\s*column")


if __name__ == "__main__":
    unittest.main()

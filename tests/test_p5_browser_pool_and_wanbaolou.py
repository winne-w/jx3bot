import ast
import asyncio
from pathlib import Path
import tempfile
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from src.infra import screenshot as screenshot_mod


ROOT = Path(__file__).resolve().parents[1]


class _FakeWrapper:
    def __init__(self, payload: bytes = b"wrapper-png") -> None:
        self.payload = payload

    async def screenshot(self) -> bytes:
        return self.payload


class _FakePage:
    def __init__(self, tracker: "_FakePlaywrightHarness", kwargs: Dict[str, Any]) -> None:
        self.tracker = tracker
        self.kwargs = kwargs
        self.closed = False
        self.viewport_sizes: List[Dict[str, int]] = []
        self.contents: List[str] = []
        self.gotos: List[str] = []

    async def set_viewport_size(self, size: Dict[str, int]) -> None:
        self.viewport_sizes.append(size)

    async def set_content(self, html: str) -> None:
        self.contents.append(html)

    async def evaluate(self, script: str, arg: Any = None) -> Any:
        if "scrollHeight" in script:
            return 900
        return True

    async def screenshot(self, full_page: bool = False) -> bytes:
        return b"fake-png-bytes"

    async def goto(self, url: str, wait_until: str = "load") -> None:
        self.gotos.append(url)

    async def wait_for_selector(self, selector: str) -> _FakeWrapper:
        return _FakeWrapper()

    async def wait_for_timeout(self, ms: int) -> None:
        return None

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.tracker.page_close_count += 1


class _FakeBrowser:
    def __init__(self, tracker: "_FakePlaywrightHarness") -> None:
        self.tracker = tracker
        self.connected = True
        self.closed = False
        self.pages: List[_FakePage] = []

    def is_connected(self) -> bool:
        return self.connected and not self.closed

    async def new_page(self, **kwargs: Any) -> _FakePage:
        self.tracker.new_page_count += 1
        page = _FakePage(self.tracker, kwargs)
        self.pages.append(page)
        return page

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.connected = False
            self.tracker.browser_close_count += 1


class _FakeChromium:
    def __init__(self, tracker: "_FakePlaywrightHarness") -> None:
        self.tracker = tracker

    async def launch(self, headless: bool = True) -> _FakeBrowser:
        if self.tracker.launch_delay > 0:
            await asyncio.sleep(self.tracker.launch_delay)
        self.tracker.launch_count += 1
        browser = _FakeBrowser(self.tracker)
        self.tracker.browsers.append(browser)
        return browser


class _FakePlaywright:
    def __init__(self, tracker: "_FakePlaywrightHarness") -> None:
        self.tracker = tracker
        self.chromium = _FakeChromium(tracker)
        self.stopped = False

    async def stop(self) -> None:
        if not self.stopped:
            self.stopped = True
            self.tracker.playwright_stop_count += 1


class _FakePlaywrightManager:
    def __init__(self, tracker: "_FakePlaywrightHarness") -> None:
        self.tracker = tracker

    async def start(self) -> _FakePlaywright:
        self.tracker.playwright_start_count += 1
        pw = _FakePlaywright(self.tracker)
        self.tracker.playwrights.append(pw)
        return pw


class _FakePlaywrightHarness:
    def __init__(self, launch_delay: float = 0.0) -> None:
        self.launch_delay = launch_delay
        self.playwright_start_count = 0
        self.playwright_stop_count = 0
        self.launch_count = 0
        self.browser_close_count = 0
        self.new_page_count = 0
        self.page_close_count = 0
        self.browsers: List[_FakeBrowser] = []
        self.playwrights: List[_FakePlaywright] = []

    def factory(self) -> _FakePlaywrightManager:
        return _FakePlaywrightManager(self)


class BrowserPoolAndWanbaolouTest(unittest.TestCase):
    def test_jietu_reuses_single_browser_and_closes_each_page(self) -> None:
        harness = _FakePlaywrightHarness()
        pool = screenshot_mod.BrowserPool(playwright_factory=harness.factory)

        async def scenario() -> None:
            with patch.object(screenshot_mod, "_BROWSER_POOL", pool):
                img1 = await screenshot_mod.jietu("<html><body>1</body></html>", 760, "ck")
                img2 = await screenshot_mod.jietu("<html><body>2</body></html>", 760, 600)
                self.assertEqual(img1, b"fake-png-bytes")
                self.assertEqual(img2, b"fake-png-bytes")
                self.assertEqual(harness.launch_count, 1)
                self.assertEqual(harness.new_page_count, 2)
                self.assertEqual(harness.page_close_count, 2)
                self.assertEqual(harness.browser_close_count, 0)
                await screenshot_mod.close_browser_pool()

        asyncio.run(scenario())

        self.assertEqual(harness.browser_close_count, 1)
        self.assertEqual(harness.playwright_stop_count, 1)

    def test_close_browser_pool_closes_and_resets_pool(self) -> None:
        harness = _FakePlaywrightHarness()
        pool = screenshot_mod.BrowserPool(playwright_factory=harness.factory)

        async def scenario() -> None:
            with patch.object(screenshot_mod, "_BROWSER_POOL", pool):
                await screenshot_mod.jietu("<html><body>first</body></html>", 760, 400)
                self.assertEqual(harness.launch_count, 1)

                await screenshot_mod.close_browser_pool()
                self.assertEqual(harness.browser_close_count, 1)
                self.assertEqual(harness.playwright_stop_count, 1)
                self.assertIsNone(pool._browser)
                self.assertIsNone(pool._playwright)

                # Calling close again is an idempotent no-op.
                await screenshot_mod.close_browser_pool()
                self.assertEqual(harness.browser_close_count, 1)
                self.assertEqual(harness.playwright_stop_count, 1)

                # Subsequent call relaunches a fresh browser.
                await screenshot_mod.jietu("<html><body>second</body></html>", 760, 400)
                self.assertEqual(harness.launch_count, 2)
                self.assertEqual(harness.new_page_count, 2)
                self.assertEqual(harness.page_close_count, 2)
                await screenshot_mod.close_browser_pool()

        asyncio.run(scenario())

        self.assertEqual(harness.browser_close_count, 2)
        self.assertEqual(harness.playwright_stop_count, 2)

    def test_disconnected_browser_triggers_automatic_reconnect(self) -> None:
        harness = _FakePlaywrightHarness()
        pool = screenshot_mod.BrowserPool(playwright_factory=harness.factory)

        async def scenario() -> None:
            with patch.object(screenshot_mod, "_BROWSER_POOL", pool):
                await screenshot_mod.jietu("<html><body>before</body></html>", 760, 400)
                self.assertEqual(harness.launch_count, 1)

                # Simulate unexpected Chromium disconnect.
                harness.browsers[0].connected = False

                await screenshot_mod.jietu("<html><body>after</body></html>", 760, 400)
                self.assertEqual(harness.launch_count, 2)
                self.assertEqual(harness.browser_close_count, 1)
                self.assertEqual(harness.playwright_stop_count, 1)
                self.assertEqual(harness.new_page_count, 2)
                self.assertEqual(harness.page_close_count, 2)
                await screenshot_mod.close_browser_pool()

        asyncio.run(scenario())

        self.assertEqual(harness.browser_close_count, 2)
        self.assertEqual(harness.playwright_stop_count, 2)

    def test_concurrent_acquire_launches_browser_only_once_and_no_page_leak_on_error(self) -> None:
        harness = _FakePlaywrightHarness(launch_delay=0.02)
        pool = screenshot_mod.BrowserPool(playwright_factory=harness.factory)

        async def failing_worker() -> None:
            async with pool.acquire_page():
                raise RuntimeError("boom")

        async def ok_worker() -> bytes:
            return await screenshot_mod.jietu("<html><body>ok</body></html>", 760, 300)

        async def scenario() -> None:
            with patch.object(screenshot_mod, "_BROWSER_POOL", pool):
                results = await asyncio.gather(ok_worker(), ok_worker(), failing_worker(), return_exceptions=True)
                self.assertEqual(results[0], b"fake-png-bytes")
                self.assertEqual(results[1], b"fake-png-bytes")
                self.assertIsInstance(results[2], RuntimeError)
                self.assertEqual(harness.launch_count, 1)
                self.assertEqual(harness.new_page_count, 3)
                self.assertEqual(harness.page_close_count, 3)
                await screenshot_mod.close_browser_pool()

        asyncio.run(scenario())

    def test_jx3web_uses_pooled_browser_and_saves_file(self) -> None:
        harness = _FakePlaywrightHarness()
        pool = screenshot_mod.BrowserPool(playwright_factory=harness.factory)

        async def scenario(out_path: str) -> None:
            with patch.object(screenshot_mod, "_BROWSER_POOL", pool):
                saved = await screenshot_mod.jx3web("https://example.com", "#main", adjust_top="10px", save_path=out_path)
                raw = await screenshot_mod.jx3web("https://example.com", "#main")
                self.assertEqual(saved, out_path)
                self.assertEqual(raw, b"wrapper-png")
                self.assertEqual(harness.launch_count, 1)
                self.assertEqual(harness.new_page_count, 2)
                self.assertEqual(harness.page_close_count, 2)
                await screenshot_mod.close_browser_pool()

        with tempfile.TemporaryDirectory() as tmpdir:
            target = str(Path(tmpdir) / "out.png")
            asyncio.run(scenario(target))
            self.assertEqual(Path(target).read_bytes(), b"wrapper-png")

    def test_wanbaolou_has_no_duplicate_handle_my_subscriptions(self) -> None:
        source_path = ROOT / "src" / "plugins" / "wanbaolou" / "__init__.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(source_path))

        func_names = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self.assertEqual(func_names.count("handle_my_subscriptions"), 1)
        self.assertIn("handle_my_subscription_prices", func_names)
        self.assertNotIn("搜索结果有效期5分钟", source)
        self.assertIn("src.services.jx3.singletons", source)

    def test_bot_shutdown_calls_close_browser_pool(self) -> None:
        bot_source = (ROOT / "bot.py").read_text(encoding="utf-8")
        self.assertIn("close_browser_pool", bot_source)


if __name__ == "__main__":
    unittest.main()

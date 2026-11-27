from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
from typing import Any, AsyncIterator, Callable, Optional


def _load_async_playwright() -> Any:
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("缺少依赖 playwright：请安装 playwright 并执行 playwright install") from exc
    return async_playwright


def _is_browser_connected(browser: Any) -> bool:
    if browser is None:
        return False
    checker = getattr(browser, "is_connected", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    return True


class BrowserPool:
    """按当前事件循环维护单个常驻 Playwright + Chromium 实例的浏览器池。"""

    def __init__(self, playwright_factory: Optional[Callable[[], Any]] = None) -> None:
        self._playwright_factory = playwright_factory
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock: Optional[asyncio.Lock] = None
        self._playwright: Any = None
        self._playwright_cm: Any = None
        self._browser: Any = None
        self._active_factory: Any = None

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._loop is not loop or self._lock is None:
            self._loop = loop
            self._lock = asyncio.Lock()
            self._playwright = None
            self._playwright_cm = None
            self._browser = None
            self._active_factory = None
        return self._lock

    async def _close_unlocked(self) -> None:
        browser = self._browser
        playwright = self._playwright
        playwright_cm = self._playwright_cm
        self._browser = None
        self._playwright = None
        self._playwright_cm = None
        self._active_factory = None

        if browser is not None:
            close_fn = getattr(browser, "close", None)
            if callable(close_fn):
                try:
                    await close_fn()
                except Exception:
                    pass

        if playwright_cm is not None:
            aexit = getattr(playwright_cm, "__aexit__", None)
            if callable(aexit):
                try:
                    await aexit(None, None, None)
                except Exception:
                    pass
        elif playwright is not None:
            stop_fn = getattr(playwright, "stop", None)
            if callable(stop_fn):
                try:
                    await stop_fn()
                except Exception:
                    pass

    async def _ensure_browser(self) -> Any:
        lock = self._get_lock()
        async with lock:
            factory = self._playwright_factory or _load_async_playwright()
            if _is_browser_connected(self._browser) and self._active_factory is factory:
                return self._browser

            if self._browser is not None or self._playwright is not None or self._playwright_cm is not None:
                await self._close_unlocked()

            manager = factory()
            start_fn = getattr(manager, "start", None)
            if callable(start_fn):
                playwright = await start_fn()
                playwright_cm = None
            else:
                playwright = await manager.__aenter__()
                playwright_cm = manager

            try:
                browser = await playwright.chromium.launch(headless=True)
            except BaseException:
                if playwright_cm is not None:
                    aexit = getattr(playwright_cm, "__aexit__", None)
                    if callable(aexit):
                        try:
                            await aexit(None, None, None)
                        except Exception:
                            pass
                else:
                    stop_fn = getattr(playwright, "stop", None)
                    if callable(stop_fn):
                        try:
                            await stop_fn()
                        except Exception:
                            pass
                raise

            self._playwright = playwright
            self._playwright_cm = playwright_cm
            self._browser = browser
            self._active_factory = factory
            return browser

    @asynccontextmanager
    async def acquire_page(self, **new_page_kwargs: Any) -> AsyncIterator[Any]:
        browser = await self._ensure_browser()
        page = await browser.new_page(**new_page_kwargs)
        try:
            yield page
        finally:
            close_fn = getattr(page, "close", None)
            if callable(close_fn):
                try:
                    await close_fn()
                except Exception:
                    pass

    async def close(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._browser = None
            self._playwright = None
            self._playwright_cm = None
            self._active_factory = None
            self._loop = None
            self._lock = None
            return

        if self._loop is not None and self._loop is not loop:
            self._browser = None
            self._playwright = None
            self._playwright_cm = None
            self._active_factory = None
            self._loop = None
            self._lock = None
            return

        lock = self._lock
        if lock is None:
            await self._close_unlocked()
        else:
            async with lock:
                await self._close_unlocked()

        self._loop = None
        self._lock = None


_BROWSER_POOL = BrowserPool()


async def close_browser_pool() -> None:
    await _BROWSER_POOL.close()


async def jietu(html_content, width, height):
    target_width = int(width)
    initial_height = 1080 if height == "ck" else max(1, int(height))

    async with _BROWSER_POOL.acquire_page(
        viewport={"width": target_width, "height": initial_height},
        device_scale_factor=2,
    ) as page:
        await page.set_viewport_size({"width": target_width, "height": initial_height})
        await page.set_content(html_content)
        await page.evaluate(
            """() => {
                 return new Promise((resolve) => {
                     const images = Array.from(document.querySelectorAll('img'));
                     if (images.length === 0) return resolve(true);

                     let settled = false;
                     let loaded = 0;
                     const finish = () => {
                         if (!settled) {
                             settled = true;
                             resolve(true);
                         }
                     };
                     const timer = setTimeout(finish, 3000);
                     const checkLoaded = () => {
                         loaded++;
                         if (loaded >= images.length) {
                             clearTimeout(timer);
                             finish();
                         }
                     };

                     images.forEach(img => {
                         if (img.complete) checkLoaded();
                         else {
                             img.addEventListener('load', checkLoaded, { once: true });
                             img.addEventListener('error', checkLoaded, { once: true });
                         }
                     });
                 });
             }"""
        )

        if height == "ck":
            page_height = await page.evaluate(
                "() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
            )
            final_height = max(1, int(page_height))
        else:
            final_height = max(1, int(height))

        await page.set_viewport_size({"width": target_width, "height": final_height})
        screenshot_bytes = await page.screenshot(full_page=True)
        return screenshot_bytes


async def jx3web(url, selector, adjust_top=None, save_path=None):
    async with _BROWSER_POOL.acquire_page() as page:
        await page.goto(url, wait_until="networkidle")
        await page.wait_for_selector(selector)

        if adjust_top is not None:
            await page.evaluate(
                """(arg) => {
                const element = document.querySelector(arg.selector);
                if (element) {
                    const currentPosition = window.getComputedStyle(element).position;
                    if (currentPosition === 'static') {
                        element.style.position = 'relative';
                    }
                    element.style.top = arg.topValue;
                }
            }""",
                {"selector": selector, "topValue": adjust_top},
            )
            await page.wait_for_timeout(300)

        await page.evaluate(
            """(arg) => {
            const element = document.querySelector(arg.selector);
            if (!element) return;

            const wrapper = document.createElement('div');
            wrapper.id = 'capture-wrapper';
            wrapper.style.width = element.offsetWidth + 'px';
            wrapper.style.background = '#F3F6FB';

            element.parentNode.insertBefore(wrapper, element);
            wrapper.appendChild(element);

            const footer = document.createElement('div');
            footer.style.width = '100%';
            footer.style.padding = '15px 18px';
            footer.style.marginTop = '10px';
            footer.style.background = '#F3F6FB';
            footer.style.borderTop = '1px solid rgba(148, 163, 184, 0.22)';
            footer.style.fontFamily = "'PingFang SC', 'Microsoft YaHei', sans-serif";
            footer.style.fontSize = '14px';
            footer.style.color = '#64748B';
            footer.style.textAlign = 'center';

            const line1 = document.createElement('div');
            line1.textContent = '【夏鸥】bot';
            line1.style.fontWeight = '700';
            line1.style.color = '#3B5BDB';
            line1.style.marginBottom = '4px';
            footer.appendChild(line1);

            const line2 = document.createElement('div');
            line2.textContent = '人间最美，不过鲸落，一念百草生，一念山河成。';
            footer.appendChild(line2);

            wrapper.appendChild(footer);
        }""",
            {"selector": selector},
        )

        await page.wait_for_timeout(200)
        wrapper = await page.wait_for_selector("#capture-wrapper")
        screenshot = await wrapper.screenshot()

    if save_path:
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(screenshot)
        return save_path
    return screenshot

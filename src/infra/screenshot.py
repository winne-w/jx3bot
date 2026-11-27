from __future__ import annotations

import os


async def jietu(html_content, width, height):
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("缺少依赖 playwright：请安装 playwright 并执行 playwright install") from exc

    target_width = int(width)
    initial_height = 1080 if height == "ck" else max(1, int(height))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            viewport={"width": target_width, "height": initial_height},
            device_scale_factor=2,
        )

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
        await browser.close()
        return screenshot_bytes


async def jx3web(url, selector, adjust_top=None, save_path=None):
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("缺少依赖 playwright：请安装 playwright 并执行 playwright install") from exc

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

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
        await browser.close()

        if save_path:
            os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(screenshot)
            return save_path
        return screenshot

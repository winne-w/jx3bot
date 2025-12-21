from __future__ import annotations

import os

from playwright.async_api import async_playwright


async def jietu(html_content, width, height):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
        )

        await page.evaluate(
            """() => {
                 return new Promise((resolve) => {
                     const images = document.querySelectorAll('img');
                     if (images.length === 0) return resolve(true);

                     let loaded = 0;
                     const checkLoaded = () => {
                         loaded++;
                         if (loaded === images.length) resolve(true);
                     };

                     images.forEach(img => {
                         if (img.complete) checkLoaded();
                         else {
                             img.addEventListener('load', checkLoaded);
                             img.addEventListener('error', checkLoaded);
                         }
                     });
                 });
             }"""
        )

        await page.set_content(html_content)
        page_height = await page.evaluate("() => document.body.scrollHeight")
        if height == "ck":
            height = page_height
        await page.set_viewport_size({"width": width, "height": height})
        screenshot_path = await page.screenshot(full_page=True)
        await browser.close()
        return screenshot_path


async def jx3web(url, selector, adjust_top=None, save_path=None):
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

            element.parentNode.insertBefore(wrapper, element);
            wrapper.appendChild(element);

            const footer = document.createElement('div');
            footer.style.width = '100%';
            footer.style.padding = '15px';
            footer.style.marginTop = '10px';
            footer.style.background = '#f8f9fa';
            footer.style.borderTop = '1px solid #eaeaea';
            footer.style.fontFamily = \"'Microsoft YaHei', sans-serif\";
            footer.style.fontSize = '14px';
            footer.style.color = '#555';
            footer.style.textAlign = 'center';

            const line1 = document.createElement('div');
            line1.textContent = '【夏鸥】bot:';
            line1.style.fontWeight = 'bold';
            line1.style.marginBottom = '5px';
            footer.appendChild(line1);

            const line2 = document.createElement('div');
            line2.textContent = '人间最美，不过鲸落，一念百草生，一念山河成。';
            line2.style.fontStyle = 'italic';
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


from __future__ import annotations

import asyncio
import json
import os

from playwright.async_api import async_playwright


async def download_json_from_local_storage(
    *,
    url: str = "https://jx3.seasunwbl.com/buyer?t=skin",
    key_name: str = "skin_appearance_cache_key",
    output_filename: str = "waiguan.json",
) -> bool:
    """
    从指定网站的 localStorage 中下载指定 key 的 JSON 数据，并保存到文件。
    """
    print(f"开始从 {url} 获取 {key_name} 数据...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle")

            await asyncio.sleep(3)

            result = await page.evaluate(f"localStorage.getItem('{key_name}')")
            if not result:
                print(f"错误: localStorage中未找到键 '{key_name}'")
                return False

            try:
                data = json.loads(result)
                with open(output_filename, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                print(f"✅ 数据已成功保存到 {os.path.abspath(output_filename)}")
                return True
            except json.JSONDecodeError:
                print("错误: 无法解析JSON数据")
                with open(output_filename, "w", encoding="utf-8") as f:
                    f.write(result)
                print(f"原始数据已保存到 {output_filename}")
                return False
        except Exception as e:
            print(f"错误: {e}")
            return False
        finally:
            await browser.close()


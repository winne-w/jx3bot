from __future__ import annotations

import asyncio
import json
import os

try:
    from nonebot import logger  # type: ignore
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)


async def download_json_from_local_storage(
    *,
    url: str = "https://jx3.seasunwbl.com/buyer?t=skin",
    key_name: str = "skin_appearance_cache_key",
    output_filename: str = "waiguan.json",
) -> bool:
    """
    从指定网站的 localStorage 中下载指定 key 的 JSON 数据，并保存到文件。
    """
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("缺少依赖 playwright：请安装 playwright 并执行 playwright install") from exc

    logger.info(f"browser_storage 开始从 {url} 获取 {key_name} 数据")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle")

            await asyncio.sleep(3)

            result = await page.evaluate(f"localStorage.getItem('{key_name}')")
            if not result:
                logger.warning(f"browser_storage localStorage 未找到 key={key_name}")
                return False

            try:
                data = json.loads(result)
                with open(output_filename, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.info(f"browser_storage 数据已保存到 {os.path.abspath(output_filename)}")
                return True
            except json.JSONDecodeError:
                logger.warning(f"browser_storage 无法解析 JSON，保存原始数据到 {output_filename}")
                with open(output_filename, "w", encoding="utf-8") as f:
                    f.write(result)
                return False
        except Exception as e:
            logger.warning(f"browser_storage 执行失败: {e}")
            return False
        finally:
            await browser.close()

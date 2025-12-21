from __future__ import annotations

import os
from typing import Optional

import aiofiles
import httpx

from config import IMAGE_CACHE_DIR


async def mp_image(url: str, name: str) -> Optional[bytes]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/58.0.3029.110 Safari/537.3"
        )
    }

    file_path = os.path.join(IMAGE_CACHE_DIR, f"{name}.png")
    if os.path.exists(file_path):
        try:
            async with aiofiles.open(file_path, "rb") as f:
                return await f.read()
        except Exception as exc:
            print(f"读取已缓存名片失败: {exc}")
            return None

    if not url:
        print("未找到图片URL")
        return None

    async with httpx.AsyncClient(headers=headers, verify=False, timeout=30.0) as client:
        image_response = await client.get(url)
        if image_response.status_code != 200:
            print(f"无法下载图片，状态码：{image_response.status_code}")
            return None
        image_content = image_response.content

    os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(image_content)
    print("图片已下载并保存")
    return image_content

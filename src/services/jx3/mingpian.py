from __future__ import annotations

from typing import Any

from src.utils.defget import mp_image


def extract_avatar_meta(items: dict[str, Any], *, server: str, role_name: str) -> tuple[str | None, str | None]:
    """
    从名片查询 API 响应中提取 (avatar_url, image_name)。
    """
    data = (items or {}).get("data") or {}
    avatar_url = data.get("showAvatar")
    show_hash = data.get("showHash")
    if not avatar_url or not show_hash:
        return None, None
    image_name = f"{server}-{role_name}-{show_hash}"
    return avatar_url, image_name


async def download_avatar_if_needed(avatar_url: str | None, image_name: str | None) -> bytes | None:
    if not avatar_url or not image_name:
        return None
    return await mp_image(url=avatar_url, name=image_name)


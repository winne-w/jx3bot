from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from urllib import error, request
from urllib.parse import quote


SKILL_API_URL = "https://node.jx3box.com/monster/skills"
ICON_URL_TEMPLATE = "https://icon.jx3box.com/icon/{icon_id}.png"
DEFAULT_OUTPUT_DIR = os.path.join("mpimg", "img", "baizhan", "skills")
INVALID_FILENAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


@dataclass(frozen=True)
class SkillIconSyncResult:
    total: int
    downloaded: int
    skipped_exists: int
    skipped_invalid: int
    failed: int


def _sanitize_filename(name: str) -> str:
    normalized = INVALID_FILENAME_RE.sub("_", name).strip()
    normalized = re.sub(r"\s+", "", normalized).strip(".")
    return normalized or "未命名技能"


def build_skill_icon_index(output_dir: str = DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    """
    读取本地技能图标目录并建立“技能名 -> 文件名”索引。
    """
    if not os.path.isdir(output_dir):
        return {}

    index: dict[str, str] = {}
    for file_name in os.listdir(output_dir):
        if not file_name.lower().endswith(".png"):
            continue
        stem = os.path.splitext(file_name)[0]
        if stem not in index:
            index[stem] = file_name

        # 同时写入去除“_数字”后缀的兜底键，便于命中重复名技能的首张图。
        base_stem = re.sub(r"_\d+$", "", stem)
        if base_stem not in index:
            index[base_stem] = file_name
    return index


def get_skill_icon_url(
    skill_name: str,
    *,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    static_base_url: str = "http://127.0.0.1:8000",
    skill_icon_index: dict[str, str] | None = None,
) -> str | None:
    if not skill_name:
        return None

    safe_name = _sanitize_filename(skill_name)
    index = skill_icon_index if skill_icon_index is not None else build_skill_icon_index(output_dir)
    file_name = index.get(safe_name)
    if not file_name:
        return None

    rel_path = os.path.join("img", "baizhan", "skills", file_name).replace(os.sep, "/")
    return f"{static_base_url.rstrip('/')}/{quote(rel_path)}"


def ensure_baizhan_skill_icons(output_dir: str = DEFAULT_OUTPUT_DIR) -> SkillIconSyncResult:
    os.makedirs(output_dir, exist_ok=True)

    req = request.Request(SKILL_API_URL, headers={"User-Agent": "jx3bot/skill-icon-sync"})
    with request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    skills = (payload.get("data") or {}).get("list") or []
    name_counter: Counter[str] = Counter()
    downloaded = 0
    skipped_exists = 0
    skipped_invalid = 0
    failed = 0

    for item in skills:
        raw_name = (item.get("szSkillName") or "").strip()
        icon_id = ((item.get("Skill") or {}).get("IconID"))
        if not raw_name or not icon_id:
            skipped_invalid += 1
            continue

        base_name = _sanitize_filename(raw_name)
        name_counter[base_name] += 1
        suffix = "" if name_counter[base_name] == 1 else f"_{name_counter[base_name]}"
        file_name = f"{base_name}{suffix}.png"
        file_path = os.path.join(output_dir, file_name)

        if os.path.exists(file_path):
            skipped_exists += 1
            continue

        icon_url = ICON_URL_TEMPLATE.format(icon_id=int(icon_id))
        icon_req = request.Request(icon_url, headers={"User-Agent": "jx3bot/skill-icon-sync"})
        try:
            with request.urlopen(icon_req, timeout=15) as resp:
                data = resp.read()
            if not data.startswith(b"\x89PNG"):
                failed += 1
                continue
            with open(file_path, "wb") as f:
                f.write(data)
            downloaded += 1
        except (error.URLError, TimeoutError, ValueError, OSError):
            failed += 1

    return SkillIconSyncResult(
        total=len(skills),
        downloaded=downloaded,
        skipped_exists=skipped_exists,
        skipped_invalid=skipped_invalid,
        failed=failed,
    )

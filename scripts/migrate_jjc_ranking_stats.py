#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote


ROOT = Path("data/jjc_ranking_stats")


def build_summary_payload(payload: dict) -> dict:
    summary_payload = {
        key: value
        for key, value in payload.items()
        if key != "kungfu_statistics"
    }
    summary_payload["kungfu_statistics"] = {}

    kungfu_statistics = payload.get("kungfu_statistics") or {}
    for range_key, range_stats in kungfu_statistics.items():
        if not isinstance(range_stats, dict):
            summary_payload["kungfu_statistics"][range_key] = range_stats
            continue

        summary_range = {
            key: value
            for key, value in range_stats.items()
            if key not in {"healer", "dps"}
        }

        for lane_name in ("healer", "dps"):
            lane = range_stats.get(lane_name) or {}
            if not isinstance(lane, dict):
                summary_range[lane_name] = lane
                continue

            members_map = lane.get("members") or {}
            legendary_count_map: dict[str, int] = {}
            for kungfu, members in members_map.items():
                legendary_count_map[kungfu] = sum(
                    1 for member in (members or []) if str((member or {}).get("weapon_quality")) == "5"
                )

            summary_lane = {
                key: value
                for key, value in lane.items()
                if key != "members"
            }
            summary_lane["legendary_count_map"] = legendary_count_map
            summary_range[lane_name] = summary_lane

        summary_payload["kungfu_statistics"][range_key] = summary_range

    return summary_payload


def write_details_files(details_root_dir: Path, stats: dict) -> int:
    written = 0
    for range_key, range_stats in (stats or {}).items():
        if not isinstance(range_stats, dict):
            continue
        for lane_name in ("healer", "dps"):
            lane = range_stats.get(lane_name) or {}
            members_map = lane.get("members") or {}
            if not isinstance(members_map, dict):
                continue

            lane_dir = details_root_dir / range_key / lane_name
            lane_dir.mkdir(parents=True, exist_ok=True)
            for kungfu, members in members_map.items():
                detail_path = lane_dir / f"{quote(str(kungfu), safe='')}.json"
                detail_payload = {
                    "range": range_key,
                    "lane": lane_name,
                    "kungfu": kungfu,
                    "members": members or [],
                }
                detail_path.write_text(json.dumps(detail_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                written += 1
    return written


def migrate_file(file_path: Path) -> tuple[bool, str]:
    timestamp = file_path.stem
    if not timestamp.isdigit():
        return False, f"skip non-timestamp file: {file_path.name}"

    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return False, f"skip invalid json object: {file_path.name}"

    target_dir = ROOT / timestamp
    summary_path = target_dir / "summary.json"
    details_root_dir = target_dir / "details"
    target_dir.mkdir(parents=True, exist_ok=True)

    summary_payload = build_summary_payload(payload)
    summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    detail_count = write_details_files(details_root_dir, payload.get("kungfu_statistics") or {})
    return True, f"migrated {file_path.name} -> {target_dir} ({detail_count} detail files)"


def main() -> None:
    if not ROOT.exists():
        print(f"stats dir not found: {ROOT}")
        return

    files = sorted(path for path in ROOT.glob("*.json") if path.is_file())
    if not files:
        print("no legacy json files found")
        return

    success = 0
    skipped = 0
    for file_path in files:
        try:
            migrated, message = migrate_file(file_path)
            print(message)
            if migrated:
                success += 1
            else:
                skipped += 1
        except Exception as exc:
            skipped += 1
            print(f"failed {file_path.name}: {exc}")

    print(f"done: migrated={success} skipped={skipped}")


if __name__ == "__main__":
    main()

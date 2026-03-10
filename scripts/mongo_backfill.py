from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.singletons import (
    cache_entry_storage,
    jjc_cache_storage,
    jjc_ranking_stats_storage,
    mongo_provider,
    reminder_storage,
    subscription_storage,
)

STATUS_MONITOR_FILES = [
    "status_history",
    "server_status",
    "news_ids",
    "records_ids",
    "event_codes_ids",
    "server_open_history",
    "server_maintenance_history",
]


@dataclass
class ImportReport:
    scanned_files: int = 0
    imported_documents: int = 0
    skipped_missing_files: int = 0
    parse_failed_files: int = 0
    bad_records: int = 0
    details: dict[str, dict[str, int]] = field(default_factory=dict)

    def bump(self, section: str, field_name: str, amount: int = 1) -> None:
        section_stats = self.details.setdefault(section, {})
        section_stats[field_name] = section_stats.get(field_name, 0) + amount


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill legacy JSON/cache files into Mongo.")
    parser.add_argument("--root", default=".", help="Project root, default current directory")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report only, do not write Mongo")
    return parser.parse_args()


def read_json(path: Path, report: ImportReport, section: str) -> Any | None:
    report.scanned_files += 1
    if not path.exists():
        report.skipped_missing_files += 1
        report.bump(section, "missing")
        return None
    try:
        with path.open("r", encoding="utf-8") as file_handle:
            return json.load(file_handle)
    except Exception:
        report.parse_failed_files += 1
        report.bump(section, "parse_failed")
        return None


def backfill_cache_entries(root: Path, report: ImportReport, dry_run: bool) -> None:
    for cache_name in STATUS_MONITOR_FILES:
        path = root / "data" / "cache" / f"{cache_name}.json"
        payload = read_json(path, report, "cache_entries")
        if payload is None:
            continue
        if not dry_run:
            cache_entry_storage.upsert_payload(
                "status_monitor",
                cache_name,
                payload,
                meta={"source_file": str(path.relative_to(root))},
            )
        report.imported_documents += 1
        report.bump("cache_entries", "imported")

    for key, relative_path in {
        "server_data": "server_data.json",
        "server_master_aliases": os.path.join("data", "cache", "server_master_cache.json"),
        "alias_cache": os.path.join("data", "wanbaolou_alias_cache.json"),
        "latest_meta": os.path.join("data", "baizhan_images", "baizhan_data.json"),
    }.items():
        path = root / relative_path
        payload = read_json(path, report, "cache_entries")
        if payload is None:
            continue
        namespace = "jx3"
        if key == "alias_cache":
            namespace = "wanbaolou"
        elif key == "latest_meta":
            namespace = "baizhan"
        if not dry_run:
            cache_entry_storage.upsert_payload(
                namespace,
                key,
                payload,
                meta={"source_file": str(path.relative_to(root))},
            )
        report.imported_documents += 1
        report.bump("cache_entries", "imported")


def backfill_jjc_ranking_cache(root: Path, report: ImportReport, dry_run: bool) -> None:
    path = root / "data" / "cache" / "jjc_ranking_cache.json"
    payload = read_json(path, report, "jjc_ranking_cache")
    if not isinstance(payload, dict):
        return
    ranking_result = payload.get("data")
    if not isinstance(ranking_result, dict):
        report.bad_records += 1
        report.bump("jjc_ranking_cache", "bad_records")
        return
    if "cache_time" not in ranking_result and "cache_time" in payload:
        ranking_result["cache_time"] = payload["cache_time"]
    if not dry_run:
        jjc_cache_storage.save_ranking_cache(ranking_result, ttl_seconds=7200)
    report.imported_documents += 1
    report.bump("jjc_ranking_cache", "imported")


def backfill_jjc_kungfu_cache(root: Path, report: ImportReport, dry_run: bool) -> None:
    cache_dir = root / "data" / "cache" / "kungfu"
    report.scanned_files += 1
    if not cache_dir.exists():
        report.skipped_missing_files += 1
        report.bump("jjc_kungfu_cache", "missing_dir")
        return

    for path in sorted(cache_dir.glob("*.json")):
        report.scanned_files += 1
        try:
            with path.open("r", encoding="utf-8") as file_handle:
                payload = json.load(file_handle)
        except Exception:
            report.parse_failed_files += 1
            report.bump("jjc_kungfu_cache", "parse_failed")
            continue
        if not isinstance(payload, dict):
            report.bad_records += 1
            report.bump("jjc_kungfu_cache", "bad_records")
            continue

        filename = path.stem
        server, _, name = filename.partition("_")
        server = str(payload.get("server") or server).strip()
        name = str(payload.get("name") or name).strip()
        if not server or not name:
            report.bad_records += 1
            report.bump("jjc_kungfu_cache", "bad_records")
            continue

        payload["server"] = server
        payload["name"] = name
        if not dry_run:
            jjc_cache_storage.save_kungfu_cache(server, name, payload, ttl_seconds=7 * 24 * 60 * 60)
        report.imported_documents += 1
        report.bump("jjc_kungfu_cache", "imported")


def backfill_reminders(root: Path, report: ImportReport, dry_run: bool) -> None:
    path = root / "data" / "group_reminders.json"
    payload = read_json(path, report, "group_reminders")
    if not isinstance(payload, dict):
        return
    for group_id, reminders in payload.items():
        if not isinstance(reminders, list):
            report.bad_records += 1
            report.bump("group_reminders", "bad_records")
            continue
        for reminder in reminders:
            if not isinstance(reminder, dict) or not reminder.get("id"):
                report.bad_records += 1
                report.bump("group_reminders", "bad_records")
                continue
            reminder.setdefault("group_id", str(group_id))
            reminder["group_id"] = str(reminder["group_id"])
            reminder["creator_user_id"] = str(reminder.get("creator_user_id", ""))
            if not dry_run:
                reminder_storage.create(reminder)
            report.imported_documents += 1
            report.bump("group_reminders", "imported")


def backfill_subscriptions(root: Path, report: ImportReport, dry_run: bool) -> None:
    path = root / "data" / "wanbaolou_subscriptions.json"
    payload = read_json(path, report, "wanbaolou_subscriptions")
    if not isinstance(payload, dict):
        return
    normalized: dict[str, list[dict[str, Any]]] = {}
    for user_id, subscriptions in payload.items():
        if not isinstance(subscriptions, list):
            report.bad_records += 1
            report.bump("wanbaolou_subscriptions", "bad_records")
            continue
        normalized[str(user_id)] = []
        for item in subscriptions:
            if not isinstance(item, dict) or not item.get("item_name"):
                report.bad_records += 1
                report.bump("wanbaolou_subscriptions", "bad_records")
                continue
            normalized[str(user_id)].append(
                {
                    "item_name": item.get("item_name"),
                    "price_threshold": item.get("price_threshold", 0),
                    "group_id": item.get("group_id"),
                    "created_at": item.get("created_at"),
                    "updated_at": item.get("created_at"),
                    "enabled": True,
                    "source": "legacy_json",
                }
            )
            report.imported_documents += 1
            report.bump("wanbaolou_subscriptions", "imported")
    if not dry_run:
        subscription_storage.replace_grouped_by_user(normalized)


def backfill_jjc_ranking_stats(root: Path, report: ImportReport, dry_run: bool) -> None:
    stats_dir = root / "data" / "jjc_ranking_stats"
    report.scanned_files += 1
    if not stats_dir.exists():
        report.skipped_missing_files += 1
        report.bump("jjc_ranking_stats", "missing_dir")
        return
    for path in sorted(stats_dir.glob("*.json")):
        report.scanned_files += 1
        if not path.stem.isdigit():
            report.bad_records += 1
            report.bump("jjc_ranking_stats", "bad_filename")
            continue
        try:
            with path.open("r", encoding="utf-8") as file_handle:
                payload = json.load(file_handle)
        except Exception:
            report.parse_failed_files += 1
            report.bump("jjc_ranking_stats", "parse_failed")
            continue
        if not isinstance(payload, dict):
            report.bad_records += 1
            report.bump("jjc_ranking_stats", "bad_records")
            continue
        if not dry_run:
            jjc_ranking_stats_storage.save(int(path.stem), payload)
        report.imported_documents += 1
        report.bump("jjc_ranking_stats", "imported")


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()

    if mongo_provider.database() is None:
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": "mongo_not_available",
                    "hint": "Set JX3BOT_MONGO_ENABLED=1, JX3BOT_MONGO_URI and JX3BOT_MONGO_DB before running.",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    mongo_provider.ensure_indexes()
    report = ImportReport()
    backfill_cache_entries(root, report, args.dry_run)
    backfill_jjc_ranking_cache(root, report, args.dry_run)
    backfill_jjc_kungfu_cache(root, report, args.dry_run)
    backfill_reminders(root, report, args.dry_run)
    backfill_subscriptions(root, report, args.dry_run)
    backfill_jjc_ranking_stats(root, report, args.dry_run)

    print(
        json.dumps(
            {
                "status": "ok",
                "dry_run": args.dry_run,
                "scanned_files": report.scanned_files,
                "imported_documents": report.imported_documents,
                "skipped_missing_files": report.skipped_missing_files,
                "parse_failed_files": report.parse_failed_files,
                "bad_records": report.bad_records,
                "details": report.details,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

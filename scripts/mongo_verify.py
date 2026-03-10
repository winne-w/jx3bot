from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.singletons import mongo_provider


def count_json_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.glob("*.json") if item.is_file())


def main() -> int:
    db = mongo_provider.database()
    if db is None:
        print(json.dumps({"status": "error", "message": "mongo_not_available"}, ensure_ascii=False, indent=2))
        return 1

    now = time.time()
    payload = {
        "status": "ok",
        "file_counts": {
            "status_monitor_cache_files": sum(
                1
                for name in [
                    "status_history",
                    "server_status",
                    "news_ids",
                    "records_ids",
                    "event_codes_ids",
                    "server_open_history",
                    "server_maintenance_history",
                ]
                if (PROJECT_ROOT / "data" / "cache" / f"{name}.json").exists()
            ),
            "jjc_ranking_cache_files": 1 if (PROJECT_ROOT / "data" / "cache" / "jjc_ranking_cache.json").exists() else 0,
            "jjc_kungfu_cache_files": count_json_files(PROJECT_ROOT / "data" / "cache" / "kungfu"),
            "group_reminders_files": 1 if (PROJECT_ROOT / "data" / "group_reminders.json").exists() else 0,
            "wanbaolou_subscriptions_files": 1
            if (PROJECT_ROOT / "data" / "wanbaolou_subscriptions.json").exists()
            else 0,
            "wanbaolou_alias_cache_files": 1
            if (PROJECT_ROOT / "data" / "wanbaolou_alias_cache.json").exists()
            else 0,
            "jjc_ranking_stats_files": count_json_files(PROJECT_ROOT / "data" / "jjc_ranking_stats"),
            "server_data_files": 1 if (PROJECT_ROOT / "server_data.json").exists() else 0,
            "server_master_cache_files": 1
            if (PROJECT_ROOT / "data" / "cache" / "server_master_cache.json").exists()
            else 0,
            "baizhan_meta_files": 1
            if (PROJECT_ROOT / "data" / "baizhan_images" / "baizhan_data.json").exists()
            else 0,
        },
        "mongo_counts": {
            "cache_entries": db["cache_entries"].count_documents({}),
            "jjc_ranking_cache": db["jjc_ranking_cache"].count_documents({}),
            "jjc_kungfu_cache_total": db["jjc_kungfu_cache"].count_documents({}),
            "jjc_kungfu_cache_active": db["jjc_kungfu_cache"].count_documents({"expires_at": {"$gt": now}}),
            "group_reminders": db["group_reminders"].count_documents({}),
            "wanbaolou_subscriptions": db["wanbaolou_subscriptions"].count_documents({}),
            "jjc_ranking_stats": db["jjc_ranking_stats"].count_documents({}),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

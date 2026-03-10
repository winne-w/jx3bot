from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import mongo_backfill, mongo_verify


class MongoBackfillScriptTests(unittest.TestCase):
    def test_backfill_subscriptions_normalizes_legacy_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            data_dir.mkdir(parents=True)
            (data_dir / "wanbaolou_subscriptions.json").write_text(
                json.dumps(
                    {
                        "10001": [
                            {
                                "item_name": "天选风不欺·无执",
                                "price_threshold": 1,
                                "group_id": 12345,
                                "created_at": 1745631849.2131052,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            report = mongo_backfill.ImportReport()
            with patch("scripts.mongo_backfill.subscription_storage.replace_grouped_by_user") as replace_mock:
                mongo_backfill.backfill_subscriptions(root, report, dry_run=False)

        replace_mock.assert_called_once()
        normalized = replace_mock.call_args.args[0]
        self.assertEqual(normalized["10001"][0]["source"], "legacy_json")
        self.assertEqual(report.imported_documents, 1)

    def test_backfill_jjc_kungfu_uses_filename_when_fields_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache_dir = root / "data" / "cache" / "kungfu"
            cache_dir.mkdir(parents=True)
            (cache_dir / "梦江南_测试角色.json").write_text(
                json.dumps({"kungfu": "莫问", "cache_time": 1_900_000_000}, ensure_ascii=False),
                encoding="utf-8",
            )
            report = mongo_backfill.ImportReport()
            with patch("scripts.mongo_backfill.jjc_cache_storage.save_kungfu_cache") as save_mock:
                mongo_backfill.backfill_jjc_kungfu_cache(root, report, dry_run=False)

        save_mock.assert_called_once()
        self.assertEqual(save_mock.call_args.args[0:2], ("梦江南", "测试角色"))
        self.assertEqual(report.imported_documents, 1)


class MongoVerifyScriptTests(unittest.TestCase):
    def test_count_json_files_only_counts_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            root.mkdir(exist_ok=True)
            (root / "a.json").write_text("{}", encoding="utf-8")
            (root / "b.json").write_text("{}", encoding="utf-8")
            (root / "c.txt").write_text("x", encoding="utf-8")
            self.assertEqual(mongo_verify.count_json_files(root), 2)


if __name__ == "__main__":
    unittest.main()

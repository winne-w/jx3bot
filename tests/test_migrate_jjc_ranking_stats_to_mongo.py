from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from scripts.migrate_jjc_ranking_stats_to_mongo import (
    discover_snapshots,
    migrate_snapshots,
)


class FakeRankingStatsRepo:
    def __init__(self, existing: Optional[Set[int]] = None, fail_on_upsert: bool = False) -> None:
        self.existing = existing or set()
        self.fail_on_upsert = fail_on_upsert
        self.saved: List[Dict[str, Any]] = []

    async def load_summary(self, timestamp: int) -> Optional[Dict[str, Any]]:
        if timestamp in self.existing:
            return {"timestamp": timestamp}
        return None

    async def upsert_summary(
        self,
        timestamp: int,
        payload: Dict[str, Any],
        source: str = "migration",
    ) -> None:
        if self.fail_on_upsert:
            raise RuntimeError("save failed")
        self.saved.append({
            "timestamp": timestamp,
            "summary": payload,
            "details": [],
            "source": source,
        })

    async def upsert_detail(
        self,
        timestamp: int,
        range_key: str,
        lane: str,
        kungfu: str,
        members: List[Dict[str, Any]],
        source: str = "migration",
    ) -> None:
        if self.fail_on_upsert:
            raise RuntimeError("save failed")
        self.saved[-1]["details"].append({
            "range": range_key,
            "lane": lane,
            "kungfu": kungfu,
            "members": members,
        })

    async def save_snapshot(
        self,
        timestamp: int,
        summary_payload: Dict[str, Any],
        detail_payloads: List[Dict[str, Any]],
        source: str = "migration",
    ) -> None:
        self.saved.append({
            "timestamp": timestamp,
            "summary": summary_payload,
            "details": detail_payloads,
            "source": source,
        })


class TestDiscoverSnapshots(unittest.TestCase):
    def test_reads_new_summary_and_url_decoded_detail_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = root / "1777426656"
            detail_dir = entry / "details" / "top_200" / "dps"
            detail_dir.mkdir(parents=True)
            (entry / "summary.json").write_text(
                json.dumps({"generated_at": 1, "kungfu_statistics": {}}),
                encoding="utf-8",
            )
            (detail_dir / "%E8%8A%B1%E9%97%B4%E6%B8%B8.json").write_text(
                json.dumps({"members": [{"name": "A"}]}),
                encoding="utf-8",
            )

            snapshots = discover_snapshots(root)

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].timestamp, 1777426656)
        self.assertEqual(snapshots[0].details[0]["range"], "top_200")
        self.assertEqual(snapshots[0].details[0]["lane"], "dps")
        self.assertEqual(snapshots[0].details[0]["kungfu"], "花间游")

    def test_reads_legacy_file_and_removes_members_from_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_payload = {
                "generated_at": 2,
                "kungfu_statistics": {
                    "top_50": {
                        "dps": {
                            "total": 1,
                            "members": {
                                "花间游": [{"name": "A", "weapon_quality": "5", "weapon_name": "钗蝶语双"}]
                            },
                        }
                    }
                },
            }
            (root / "1777426000.json").write_text(json.dumps(legacy_payload), encoding="utf-8")

            snapshots = discover_snapshots(root)

        self.assertEqual(len(snapshots), 1)
        summary_lane = snapshots[0].summary["kungfu_statistics"]["top_50"]["dps"]
        self.assertNotIn("members", summary_lane)
        self.assertEqual(summary_lane["legendary_count_map"]["花间游"], 1)
        self.assertEqual(snapshots[0].details[0]["members"][0]["name"], "A")

    def test_new_directory_wins_over_legacy_same_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = root / "100"
            entry.mkdir()
            (entry / "summary.json").write_text(json.dumps({"generated_at": "new"}), encoding="utf-8")
            (root / "100.json").write_text(json.dumps({"generated_at": "old"}), encoding="utf-8")

            snapshots = discover_snapshots(root)

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].summary["generated_at"], "new")


class TestMigrateSnapshots(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_counts_writes_without_saving(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = root / "100"
            detail_dir = entry / "details" / "top_200" / "dps"
            detail_dir.mkdir(parents=True)
            (entry / "summary.json").write_text(json.dumps({"generated_at": 1}), encoding="utf-8")
            (detail_dir / "test.json").write_text(json.dumps({"members": []}), encoding="utf-8")
            snapshots = discover_snapshots(root)

        repo = FakeRankingStatsRepo()
        stats = await migrate_snapshots(snapshots, repo, dry_run=True, overwrite=False)

        self.assertEqual(stats.summary_writes, 1)
        self.assertEqual(stats.detail_writes, 1)
        self.assertEqual(repo.saved, [])

    async def test_existing_snapshot_skipped_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = root / "100"
            detail_dir = entry / "details" / "top_200" / "dps"
            detail_dir.mkdir(parents=True)
            (entry / "summary.json").write_text(json.dumps({"generated_at": 1}), encoding="utf-8")
            (detail_dir / "test.json").write_text(json.dumps({"members": []}), encoding="utf-8")
            snapshots = discover_snapshots(root)

        repo = FakeRankingStatsRepo(existing={100})
        stats = await migrate_snapshots(snapshots, repo, dry_run=False, overwrite=False)

        self.assertEqual(stats.summary_skips, 1)
        self.assertEqual(stats.detail_skips, 1)
        self.assertEqual(stats.summary_writes, 0)
        self.assertEqual(stats.detail_writes, 0)
        self.assertEqual(repo.saved, [])

    async def test_overwrite_saves_existing_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = root / "100"
            entry.mkdir()
            (entry / "summary.json").write_text(json.dumps({"generated_at": 1}), encoding="utf-8")
            snapshots = discover_snapshots(root)

        repo = FakeRankingStatsRepo(existing={100})
        stats = await migrate_snapshots(snapshots, repo, dry_run=False, overwrite=True)

        self.assertEqual(stats.summary_writes, 1)
        self.assertEqual(repo.saved[0]["timestamp"], 100)
        self.assertEqual(repo.saved[0]["source"], "migration")

    async def test_save_failure_records_failure_without_false_write_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = root / "100"
            detail_dir = entry / "details" / "top_200" / "dps"
            detail_dir.mkdir(parents=True)
            (entry / "summary.json").write_text(json.dumps({"generated_at": 1}), encoding="utf-8")
            (detail_dir / "test.json").write_text(json.dumps({"members": []}), encoding="utf-8")
            snapshots = discover_snapshots(root)

        repo = FakeRankingStatsRepo(fail_on_upsert=True)
        stats = await migrate_snapshots(snapshots, repo, dry_run=False, overwrite=False)

        self.assertEqual(stats.summary_writes, 0)
        self.assertEqual(stats.detail_writes, 0)
        self.assertEqual(stats.summary_skips, 0)
        self.assertEqual(stats.detail_skips, 0)
        self.assertEqual(len(stats.failures), 1)
        self.assertIn("save failed", stats.failures[0])
        self.assertEqual(repo.saved, [])


if __name__ == "__main__":
    unittest.main()

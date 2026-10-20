from __future__ import annotations

import copy
import hashlib
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from bson import ObjectId

from scripts import recover_jjc_role_identities as cli


class RecoveryOperationFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_atomic_backup_roundtrips_bson_and_missing_fields(self):
        before = {"_id": ObjectId(), "role_id": None,
                  "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}
        path = self.root / "backup.json"
        cli.atomic_write_json(path, before)
        actual = cli.read_json(path)
        self.assertEqual(before, actual)
        self.assertNotIn("game_role_id", actual)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_fsync_failure_never_replaces_existing_operation(self):
        path = self.root / "state.json"
        cli.atomic_write_json(path, {"old": True})
        with patch.object(cli.os, "fsync", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                cli.atomic_write_json(path, {"new": True})
        self.assertEqual(cli.read_json(path), {"old": True})

    def test_budget_persists_across_subcommands_and_reserves_before_call(self):
        for _ in range(2):
            cli.charge_calls(self.root, count=1, max_calls=3, min_interval=0)
        self.assertEqual(cli.read_json(self.root / "budget.json")["logical_calls"], 2)
        with self.assertRaisesRegex(ValueError, "budget"):
            cli.charge_calls(self.root, count=2, max_calls=3, min_interval=0)
        self.assertEqual(cli.read_json(self.root / "budget.json")["logical_calls"], 2)
        cli.charge_calls(self.root, count=1, max_calls=120, min_interval=0)
        with self.assertRaisesRegex(ValueError, "budget"):
            cli.charge_calls(self.root, count=1, max_calls=120, min_interval=0)

    def test_public_api_reservation_counts_as_five_and_no_reset(self):
        cli.charge_calls(self.root, count=5, max_calls=5, min_interval=0)
        with self.assertRaisesRegex(ValueError, "budget"):
            cli.charge_calls(self.root, count=1, max_calls=120, min_interval=0)

    def test_conservative_operation_cap_includes_public_api_reservations(self):
        cli.charge_calls(self.root, count=100, max_calls=120, min_interval=0)
        with self.assertRaisesRegex(ValueError, "budget"):
            cli.charge_calls(self.root, count=5, max_calls=120, min_interval=0)

    def test_manifest_hash_mismatch_rejected_before_loading_records(self):
        path = self.root / "manifest.json"
        cli.atomic_write_json(path, {"records": []})
        with self.assertRaisesRegex(ValueError, "hash"):
            cli.load_manifest(path, "0" * 64)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(cli.load_manifest(path, digest)["records"], [])

    def test_write_requires_exact_redacted_target_confirmation(self):
        uri = "mongodb://127.0.0.1:27029/jjc_test_role_identity"
        self.assertEqual(cli.validate_target(uri, None, write=False),
                         "127.0.0.1:27029/jjc_test_role_identity")
        with self.assertRaisesRegex(ValueError, "target"):
            cli.validate_target(uri, "different/database", write=True)
        cli.validate_target(uri, "127.0.0.1:27029/jjc_test_role_identity", write=True)

    def test_run_directory_rejects_relative_path_and_symlink(self):
        with self.assertRaises(ValueError):
            cli.validate_run_directory(Path("relative"))
        link = self.root / "link"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            cli.validate_run_directory(link)

    def test_resume_selects_twenty_first_role_instead_of_repeating_first_batch(self):
        rows = [{"identity": {"_id": ObjectId(), "name": "role-%s" % i}, "candidates": []}
                for i in range(21)]
        progress = {"apply": {str(row["identity"]["_id"]): {"status": "healthy" if i % 2 else "unresolved"}
                               for i, row in enumerate(rows[:20])}}
        selected = list(cli.select_records(rows, progress, command="apply", resume=True))
        self.assertEqual(selected, rows[20:])
        # Verify reports are not authority to skip a freshly validated apply.
        self.assertEqual(len(list(cli.select_records(rows, progress, command="verify", resume=True))), 21)

    def test_explicit_named_resume_can_reverify_but_uncommitted_crash_is_not_skipped(self):
        identity = {"_id": ObjectId(), "name": "chosen", "server": "server"}
        row = {"identity": identity, "candidates": []}
        progress = {"apply": {str(identity["_id"]): {"status": "applied_unverified"}}}
        self.assertEqual(list(cli.select_records([row], progress, command="apply", resume=True,
                                                name="chosen", server="server")), [row])
        self.assertEqual(list(cli.select_records([row], {}, command="apply", resume=True)), [row])


class RecoveryRoleOperationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.before = {"_id": ObjectId(), "identity_key": "global_id:12345",
                       "global_id": "12345", "global_role_id": "SK01-example",
                       "server": "server", "name": "role", "zone": "zone",
                       "game_role_id": "old", "role_id": "old"}
        now = datetime.now(timezone.utc)
        self.when = now.replace(microsecond=(now.microsecond // 1000) * 1000)
        self.ready = {"status": "ready", "candidate": {"role_id": "new"},
                      "observed_at": self.when, "raw": {"code": 0},
                      "replay_data": {"code": 0}, "logical_calls": 3}
        self.repo = AsyncMock()
        self.probe = AsyncMock(return_value=copy.deepcopy(self.ready))

    async def call(self, **kwargs):
        return await cli.process_role(self.repo, self.before, [], self.probe,
                                      run_dir=self.root, **kwargs)

    async def test_verify_ready_is_zero_database_write(self):
        result = await self.call(apply=False)
        self.assertEqual(result["status"], "ready")
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_apply_revalidates_and_flushes_backup_before_cas(self):
        async def replace(expected, **kwargs):
            record = cli.read_json(self.root / (str(self.before["_id"]) + ".json"))
            self.assertEqual(record["before"], self.before)
            self.assertEqual(record["status"], "prepared")
            self.assertEqual(record["expected_after"]["role_id"], "new")
            self.assertEqual(kwargs["observed_at"], self.when)
            self.repo.get_by_id.return_value = record["expected_after"]
            return True
        self.repo.replace_query_ids_if_unchanged.side_effect = replace
        result = await self.call(apply=True)
        self.probe.assert_awaited_once()
        self.assertEqual(result["status"], "applied_unverified")
        self.assertEqual(result["before"], self.before)

    async def test_backup_failure_means_no_cas(self):
        with patch.object(cli, "atomic_write_json", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                await self.call(apply=True)
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_evidence_expired_during_backup_does_not_publish(self):
        self.probe.return_value = dict(self.ready, observed_at=self.when - timedelta(seconds=16))
        result = await self.call(apply=True)
        self.assertEqual(result["status"], "unresolved")
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_conflict_is_not_recovered(self):
        self.repo.replace_query_ids_if_unchanged.return_value = False
        result = await self.call(apply=True)
        self.assertEqual(result["status"], "conflict")

    async def test_crash_after_cas_detected_without_reapplying_or_losing_before(self):
        after = cli.expected_after_image(self.before, self.ready)
        cli.atomic_write_json(self.root / (str(self.before["_id"]) + ".json"),
                              {"before": self.before, "expected_after": after,
                               "status": "prepared"})
        self.repo.get_by_id.return_value = after
        result = await self.call(apply=True)
        self.assertEqual(result["status"], "applied_unverified")
        self.probe.assert_not_awaited()
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()
        self.assertEqual(result["before"], self.before)

    async def test_resume_does_not_overwrite_later_legal_change(self):
        after = cli.expected_after_image(self.before, self.ready)
        cli.atomic_write_json(self.root / (str(self.before["_id"]) + ".json"),
                              {"before": self.before, "expected_after": after,
                               "status": "prepared"})
        self.repo.get_by_id.return_value = dict(after, name="later")
        result = await self.call(apply=True)
        self.assertEqual(result["status"], "conflict")
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()

    async def test_apply_does_not_treat_stale_ready_file_as_authority(self):
        self.probe.return_value = {"status": "unresolved"}
        cli.atomic_write_json(self.root / "verify.json", self.ready)
        result = await self.call(apply=True)
        self.assertEqual(result["status"], "unresolved")
        self.probe.assert_awaited_once()
        self.repo.replace_query_ids_if_unchanged.assert_not_awaited()


@unittest.skipUnless(os.environ.get("JJC_TEST_MONGO_URI"), "explicit isolated Mongo URI required")
class RecoveryCliMongoTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from motor.motor_asyncio import AsyncIOMotorClient
        from tests.test_role_identity_recovery_mongo import checked_test_uri
        self.source_uri = checked_test_uri(os.environ["JJC_TEST_MONGO_URI"])
        self.db_name = "jjc_test_role_identity_" + uuid4().hex
        self.client = AsyncIOMotorClient(self.source_uri, tz_aware=True)
        self.db = self.client[self.db_name]
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.uri = "mongodb://127.0.0.1:27029/" + self.db_name
        self.target = "127.0.0.1:27029/" + self.db_name
        self.identity = {"_id": ObjectId(), "identity_key": "global_id:12345",
                         "global_id": "12345", "global_role_id": "SK01-example",
                         "server": "server", "name": "role", "zone": "zone",
                         "role_id": "100", "game_role_id": "100"}
        await self.db.role_identities.insert_one(copy.deepcopy(self.identity))
        self.raw = {"code": 0, "data": {
            "role_info": {"role_id": "200", "zone": "zone", "server": "server",
                          "name": "role", "global_role_id": "SK01-example"},
            "indicator": [{"type": "3c", "total_count": 12}]}}
        await self.db.jjc_role_indicator.insert_one({
            "cache_key": self.identity["identity_key"], "global_id": "12345", "raw": self.raw})
        await self.db.jjc_ranking_stat_details.insert_one({"timestamp": 1, "members": [
            dict(self.identity, role_id="300", game_role_id="300")]})
        await self.db.jjc_ranking_stat_details.insert_one({"timestamp": 2, "members": [self.identity]})

    async def asyncTearDown(self):
        self.assertTrue(self.db_name.startswith("jjc_test_role_identity_"))
        self.assertEqual(len(self.db_name), len("jjc_test_role_identity_") + 32)
        await self.client.drop_database(self.db_name)
        self.client.close()

    def upstream(self, url, params):
        if "indicator" in url:
            return self.raw if params["role_id"] == "200" else {"code": 0, "data": {"role_info": {}}}
        if "replay" in url:
            return {"code": 0, "data": {"players": [
                {"global_role_id": "12345", "role_id": "200", "role_name": "role", "server": "server"}]}}
        return {"code": 0, "data": [{"match_id": 700}]}

    async def execute(self, *arguments):
        import config
        args = cli.make_parser().parse_args(list(arguments))
        with patch.object(config, "MONGO_URI", self.uri), \
                patch("src.utils.tuilan_request.tuilan_request", side_effect=self.upstream):
            return await cli.run(args)

    async def test_inventory_verify_apply_resume_and_conditional_rollback(self):
        inventory_dir = self.root / "inventory"
        result = await self.execute("inventory", "--output", str(inventory_dir))
        manifest = inventory_dir / "manifest.json"
        rows = cli.read_json(manifest)["records"]
        self.assertEqual(result["input_count"], 1)
        self.assertEqual({r["role_id"] for r in rows[0]["candidates"]}, {"100", "200", "300"})
        self.assertFalse(await self.db.role_identities_history.count_documents({}))
        operation_dir, backup_dir = self.root / "operation", self.root / "backup"
        common = ["--manifest", str(manifest), "--manifest-sha256", result["manifest_sha256"],
                  "--run-dir", str(operation_dir), "--limit", "1"]
        verified = await self.execute("verify", *common)
        self.assertEqual(verified["counts"], {"ready": 1})
        self.assertEqual((await self.db.role_identities.find_one({}))["role_id"], "100")
        applied = await self.execute("apply", *common, "--backup-dir", str(backup_dir),
                                     "--yes", "--confirm-target", self.target)
        self.assertEqual(applied["counts"], {"applied_unverified": 1})
        self.assertEqual((await self.db.role_identities.find_one({}))["role_id"], "200")
        path = operation_dir / (str(self.identity["_id"]) + ".json")
        record = cli.read_json(path)
        self.assertEqual(len(record["caches_before"]), 1)
        self.assertTrue((backup_dir / path.name).is_file())
        record["status"] = "prepared"
        cli.atomic_write_json(path, record)
        budget = cli.read_json(operation_dir / "budget.json")["logical_calls"]
        await self.execute("apply", *common, "--backup-dir", str(backup_dir),
                           "--yes", "--confirm-target", self.target)
        self.assertEqual(cli.read_json(operation_dir / "budget.json")["logical_calls"], budget)
        preview = await self.execute("rollback", "--run-dir", str(operation_dir))
        self.assertEqual(preview["counts"], {"rollback_ready": 1})
        self.assertEqual((await self.db.role_identities.find_one({}))["role_id"], "200")
        restored = await self.execute("rollback", "--run-dir", str(operation_dir),
                                     "--apply", "--yes", "--confirm-target", self.target)
        self.assertEqual(restored["counts"], {"rolled_back": 1})
        self.assertEqual(await self.db.role_identities.find_one({}), self.identity)

    async def test_explicit_bounded_replay_scan_keeps_replay_only_locator(self):
        await self.db.jjc_match_detail.insert_one({"match_id": 800, "data": {"replay": {
            "code": 0, "data": {"players": [
                {"global_role_id": "12345", "role_id": "400", "role_name": "role", "server": "server"}]}}}})
        result = await cli.inventory(self.db, replay_scan_limit=10)
        self.assertIn("400", {row["role_id"] for row in result["records"][0]["candidates"]})
        self.assertEqual(result["replay_coverage"]["scanned"], 1)
        self.assertFalse(result["replay_coverage"]["may_be_truncated"])
        default = await cli.inventory(self.db)
        self.assertFalse(default["replay_coverage"]["requested"])

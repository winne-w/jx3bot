import unittest

from scripts.migrate_jjc_sync_identity_queue import (
    build_identity_insert_doc,
    build_identity_queue_update,
    build_reverse_role_queue_update,
    has_identity_anchor,
    identity_lookup_queries,
    legacy_identity_keys,
    main,
    maybe_upgrade_identity_doc,
    merge_legacy_queue_docs,
    resolve_or_create_identity,
    should_skip_doc,
)


class TestMigrateJjcSyncIdentityQueue(unittest.TestCase):
    def test_lookup_queries_prefer_global_id_then_legacy_keys(self) -> None:
        doc = {
            "identity_key": "global:SK01-old",
            "global_id": "gid-a",
            "global_role_id": "SK01-a",
            "zone": "电信区",
            "role_id": "rid-a",
            "normalized_server": "梦江南",
            "normalized_name": "角色a",
        }

        queries = identity_lookup_queries(doc)

        self.assertEqual(
            queries[0],
            {"$or": [{"global_id": "gid-a"}, {"identity_key": "global_id:gid-a"}]},
        )
        self.assertEqual(
            queries[1],
            {"$or": [{"global_role_id": "SK01-a"}, {"identity_key": "global:SK01-a"}]},
        )
        self.assertEqual(
            queries[2],
            {
                "$or": [
                    {"zone": "电信区", "game_role_id": "rid-a"},
                    {"zone": "电信区", "role_id": "rid-a"},
                    {"identity_key": "game:电信区:rid-a"},
                ]
            },
        )
        self.assertEqual(
            queries[3],
            {"normalized_server": "梦江南", "normalized_name": "角色a"},
        )
        self.assertEqual(queries[4], {"identity_key": "global:SK01-old"})

    def test_identity_insert_doc_uses_global_id_key_and_aliases(self) -> None:
        old = {
            "identity_key": "global:SK01-a",
            "global_id": "gid-a",
            "global_role_id": "SK01-a",
            "server": "梦江南",
            "name": "角色A",
            "normalized_server": "梦江南",
            "normalized_name": "角色a",
            "zone": "电信区",
            "role_id": "rid-a",
        }

        insert_doc = build_identity_insert_doc(old, 1779210000.0)

        self.assertEqual(insert_doc["identity_key"], "global_id:gid-a")
        self.assertEqual(insert_doc["identity_level"], "global_id")
        self.assertEqual(insert_doc["game_role_id"], "rid-a")
        self.assertEqual(
            legacy_identity_keys(old),
            ["global_id:gid-a", "global:SK01-a", "game:电信区:rid-a", "name:梦江南:角色a"],
        )
        self.assertEqual(insert_doc["aliases"], legacy_identity_keys(old))

    def test_build_identity_insert_doc_prefers_stronger_fields_over_legacy_name_key(self) -> None:
        insert_doc = build_identity_insert_doc({
            "identity_key": "name:梦江南:角色a",
            "global_role_id": "SK01-a",
            "server": "梦江南",
            "name": "角色A",
        }, 1779210000.0)

        self.assertEqual(insert_doc["identity_key"], "global:SK01-a")
        self.assertIn("name:梦江南:角色a", insert_doc["aliases"])

    def test_identity_queue_update_copies_watermarks_and_lease_fields(self) -> None:
        old = {
            "identity_key": "global_id:gid-a",
            "status": "cooldown",
            "priority": 10,
            "full_synced_until_time": 1779000000,
            "oldest_synced_match_time": 1778000000,
            "latest_seen_match_time": 1779100000,
            "history_exhausted": True,
            "last_cursor": 20,
            "lease_owner": "worker-a",
            "lease_expires_at": 1779210100.0,
            "next_sync_after": 1779210300.0,
            "fail_count": 2,
            "created_at": 1779200000.0,
        }
        identity = {
            "_id": "identity-a",
            "identity_key": "global_id:gid-a",
            "server": "梦江南",
            "name": "角色A",
        }

        update = build_identity_queue_update(old, identity, 1779210000.0)

        self.assertEqual(update["$set"]["identity_id"], "identity-a")
        self.assertEqual(update["$set"]["status"], "cooldown")
        self.assertEqual(update["$set"]["full_synced_until_time"], 1779000000)
        self.assertEqual(update["$set"]["oldest_synced_match_time"], 1778000000)
        self.assertEqual(update["$set"]["lease_owner"], "worker-a")
        self.assertEqual(update["$set"]["created_at"], 1779200000.0)
        self.assertEqual(update["$set"]["last_cursor"], 20)

    def test_reverse_update_requires_identity_key_and_omits_identity_id(self) -> None:
        new_doc = {
            "identity_id": "identity-a",
            "identity_key": "global_id:gid-a",
            "status": "queued",
            "full_synced_until_time": 1779000000,
            "last_cursor": 10,
        }

        update = build_reverse_role_queue_update(new_doc, 1779210000.0)

        self.assertIsNotNone(update)
        assert update is not None
        self.assertEqual(update["$set"]["identity_key"], "global_id:gid-a")
        self.assertNotIn("identity_id", update["$set"])
        self.assertEqual(update["$set"]["full_synced_until_time"], 1779000000)
        self.assertIsNone(build_reverse_role_queue_update({"identity_id": "identity-a"}, 1779210000.0))

    def test_skip_syncing_default(self) -> None:
        self.assertTrue(should_skip_doc({"status": "syncing"}, include_syncing=False))
        self.assertFalse(should_skip_doc({"status": "syncing"}, include_syncing=True))

    def test_unresolvable_doc_has_no_anchor_and_insert_raises(self) -> None:
        self.assertFalse(has_identity_anchor({"identity_key": "bad-key"}))
        with self.assertRaises(ValueError):
            build_identity_insert_doc({"identity_key": "bad-key"}, 1779210000.0)

    def test_duplicate_legacy_rows_merge_conservative_watermarks(self) -> None:
        existing = {
            "identity_key": "global_id:gid-a",
            "priority": 1,
            "full_synced_until_time": 100,
            "oldest_synced_match_time": 50,
            "latest_seen_match_time": 100,
            "last_cursor": 3,
            "history_exhausted": False,
        }
        incoming = {
            "identity_key": "global:SK01-a",
            "priority": 10,
            "full_synced_until_time": 90,
            "oldest_synced_match_time": 20,
            "latest_seen_match_time": 120,
            "last_cursor": 1,
            "history_exhausted": True,
        }

        merged = merge_legacy_queue_docs(existing, incoming)

        self.assertEqual(merged["priority"], 10)
        self.assertEqual(merged["full_synced_until_time"], 100)
        self.assertEqual(merged["oldest_synced_match_time"], 20)
        self.assertEqual(merged["latest_seen_match_time"], 120)
        self.assertEqual(merged["last_cursor"], 3)
        self.assertTrue(merged["history_exhausted"])

    def test_merge_existing_identity_queue_preserves_runtime_state(self) -> None:
        existing = {
            "identity_key": "global_id:gid-a",
            "status": "disabled",
            "lease_owner": "new-worker",
            "next_sync_after": 200.0,
            "full_synced_until_time": 100,
            "oldest_synced_match_time": 50,
        }
        incoming = {
            "status": "queued",
            "lease_owner": "old-worker",
            "next_sync_after": 10.0,
            "full_synced_until_time": 120,
            "oldest_synced_match_time": 20,
        }

        merged = merge_legacy_queue_docs(
            existing,
            incoming,
            preserve_existing_runtime_state=True,
        )

        self.assertEqual(merged["status"], "disabled")
        self.assertEqual(merged["lease_owner"], "new-worker")
        self.assertEqual(merged["next_sync_after"], 200.0)
        self.assertEqual(merged["full_synced_until_time"], 120)
        self.assertEqual(merged["oldest_synced_match_time"], 20)

    def test_cli_requires_explicit_subcommand(self) -> None:
        self.assertEqual(main([]), 2)

    def test_dry_run_preview_ids_are_stable_per_identity_key(self) -> None:
        db = FakeDb()
        first, _ = resolve_or_create_identity(
            db,
            {"global_id": "gid-a", "server": "梦江南", "name": "角色A"},
            1779210000.0,
            dry_run=True,
        )
        second, _ = resolve_or_create_identity(
            db,
            {"global_id": "gid-b", "server": "梦江南", "name": "角色B"},
            1779210000.0,
            dry_run=True,
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        self.assertNotEqual(first["_id"], second["_id"])

    def test_maybe_upgrade_identity_doc_promotes_weaker_matched_identity(self) -> None:
        db = FakeDb()
        upgraded = maybe_upgrade_identity_doc(
            db,
            {"_id": "identity-a", "identity_key": "name:梦江南:角色a", "aliases": []},
            {
                "global_role_id": "SK01-a",
                "server": "梦江南",
                "name": "角色A",
            },
            1779210000.0,
            dry_run=True,
        )

        self.assertEqual(upgraded["identity_key"], "global:SK01-a")
        self.assertEqual(upgraded["identity_level"], "global")
        self.assertIn("name:梦江南:角色a", upgraded["aliases"])


class FakeCollection:
    def find_one(self, query):  # type: ignore[no-untyped-def]
        return None


class FakeDb:
    def __init__(self) -> None:
        self.role_identities = FakeCollection()


if __name__ == "__main__":
    unittest.main()

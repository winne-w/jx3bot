import unittest

from scripts.limit_existing_jjc_queue_to_7d import (
    MIGRATION_BY,
    build_query,
    build_update,
    parse_statuses,
)


class TestLimitExistingJjcQueueTo7d(unittest.TestCase):
    def test_parse_statuses_rejects_syncing_and_disabled(self) -> None:
        with self.assertRaises(ValueError):
            parse_statuses("queued,syncing")
        with self.assertRaises(ValueError):
            parse_statuses("disabled")

    def test_build_query_targets_given_statuses(self) -> None:
        self.assertEqual(
            build_query(["pending", "queued"]),
            {"status": {"$in": ["pending", "queued"]}},
        )

    def test_build_update_sets_one_time_window_fields(self) -> None:
        update = build_update(cutoff=1770000000, now=1770600000.5)

        self.assertEqual(update["$set"]["queue_mode"], "full")
        self.assertEqual(update["$set"]["queue_sync_until_time"], 1770000000)
        self.assertEqual(update["$set"]["updated_at"], 1770600000.5)
        self.assertEqual(update["$set"]["queue_window_migrated_at"], 1770600000.5)
        self.assertEqual(update["$set"]["queue_window_migrated_by"], MIGRATION_BY)


if __name__ == "__main__":
    unittest.main()

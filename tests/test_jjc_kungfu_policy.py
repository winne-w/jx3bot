"""A05/A06/A08: public cache policy contract, no external IO."""
import copy
import unittest

from src.services.jx3.jjc_kungfu_policy import KungfuPolicy, make_scope, retry_delay


class KungfuPolicyTests(unittest.TestCase):
    def setUp(self):
        self.scope = make_scope("season-a", 1000)
        self.policy = KungfuPolicy(self.scope, refresh_seconds=100, max_stale_seconds=300,
                                   track_seconds=500)
        self.now = 2000.0
        self.result = dict(self.scope, kungfu_id=10081, name="冰心诀", source="indicator",
                           requested_at=1900.0, verified_at=1900.0, publish_version=1,
                           win_sample_count=0)

    def evaluate(self, **changes):
        result = dict(self.result, **changes)
        return self.policy.evaluate(result, self.now, valid_names={"冰心诀", "云裳心经"})

    def test_make_scope_identifies_current_3v3_and_algorithm(self):
        self.assertEqual(self.scope, {"season_id": "season-a", "season_start": 1000,
                                     "pvp_type": 3, "algorithm_version": 1})
        self.assertEqual(make_scope("season-a", 1000, 2)["algorithm_version"], 2)

    def test_refresh_boundary_is_fresh_and_does_not_mutate_input(self):
        before = copy.deepcopy(self.result)
        actual = self.policy.evaluate(self.result, self.now, valid_names={"冰心诀"})
        self.assertEqual(actual["freshness"], "fresh")
        self.assertIsNone(actual["reason"])
        self.assertEqual(self.result, before)

    def test_past_refresh_until_max_age_is_stale_and_usable(self):
        for verified_at in (1899.999, 1700.0):
            with self.subTest(verified_at=verified_at):
                actual = self.evaluate(verified_at=verified_at, requested_at=verified_at - 1)
                self.assertEqual(actual["freshness"], "stale")
                self.assertIsNone(actual["reason"])

    def test_past_max_age_is_unknown(self):
        actual = self.evaluate(verified_at=1699.999, requested_at=1698.0)
        self.assertEqual(actual["freshness"], "unknown")
        self.assertTrue(actual["reason"])

    def test_missing_or_null_result_is_unknown(self):
        for value in (None, {}):
            with self.subTest(value=value):
                actual = self.policy.evaluate(value, self.now, valid_names={"冰心诀"})
                self.assertEqual(actual["freshness"], "unknown")
                self.assertTrue(actual["reason"])

    def test_each_scope_dimension_must_match(self):
        for key, wrong in (("season_id", "season-b"), ("season_start", 1001),
                           ("pvp_type", 2), ("algorithm_version", 2)):
            with self.subTest(key=key):
                self.assertEqual(self.evaluate(**{key: wrong})["freshness"], "unknown")

    def test_future_or_inverted_or_nonfinite_times_are_unknown(self):
        for changes in ({"verified_at": 2000.1}, {"requested_at": 1901.0},
                        {"verified_at": None}, {"requested_at": None},
                        {"verified_at": float("nan")}, {"verified_at": float("inf")},
                        {"verified_at": True}, {"requested_at": "not-time"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.evaluate(**changes)["freshness"], "unknown")

    def test_missing_independent_time_is_unknown(self):
        for field in ("requested_at", "verified_at"):
            result = dict(self.result)
            del result[field]
            self.assertEqual(self.policy.evaluate(result, self.now)["freshness"], "unknown")

    def test_nonpositive_or_noninteger_publish_version_is_unknown(self):
        for value in (None, 0, -1, True, "1", 1.5):
            with self.subTest(value=value):
                self.assertEqual(self.evaluate(publish_version=value)["freshness"], "unknown")

    def test_unknown_name_or_missing_canonical_id_is_not_a_hit(self):
        for changes in ({"name": "unmapped"}, {"name": None}, {"kungfu_id": None}):
            with self.subTest(changes=changes):
                self.assertEqual(self.evaluate(**changes)["freshness"], "unknown")

    def test_invalid_intervals_raise_clear_configuration_error(self):
        for kwargs in ({"refresh_seconds": 0}, {"refresh_seconds": -1},
                       {"refresh_seconds": 400, "max_stale_seconds": 300},
                       {"track_seconds": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                KungfuPolicy(self.scope, **kwargs)

    def test_retry_is_exponential_with_a_fixed_cap(self):
        self.assertEqual([retry_delay(n) for n in range(1, 9)],
                         [60, 120, 240, 480, 960, 1920, 3600, 3600])
        self.assertEqual(retry_delay(100000), 3600)

    def test_bson_long_publication_version_is_a_valid_integer(self):
        from bson.int64 import Int64
        self.assertEqual(self.evaluate(publish_version=Int64(7))["freshness"], "fresh")

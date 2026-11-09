import os
import unittest
from unittest import mock

import config


class TestConfigEnvInt(unittest.TestCase):
    def test_env_int_uses_default_for_missing_blank_and_invalid_values(self) -> None:
        invalid_values = [None, "", "  ", "abc", "1.5", "true", "--", "0x1"]
        for raw_value in invalid_values:
            with self.subTest(raw_value=raw_value):
                env = {}
                if raw_value is not None:
                    env["JJC_SYNC_WORKER_COUNT"] = raw_value
                with mock.patch.dict(os.environ, env, clear=True):
                    self.assertEqual(config._env_int("JJC_SYNC_WORKER_COUNT", 7), 7)

    def test_env_int_accepts_integer_strings(self) -> None:
        for raw_value, expected in [("0", 0), ("3", 3), ("-1", -1)]:
            with self.subTest(raw_value=raw_value):
                with mock.patch.dict(os.environ, {"JJC_SYNC_WORKER_COUNT": raw_value}, clear=True):
                    self.assertEqual(config._env_int("JJC_SYNC_WORKER_COUNT", 7), expected)

    def test_dispatcher_env_defaults_are_ints(self) -> None:
        keys = [
            ("JJC_SYNC_DISPATCHER_ENABLED", 1),
            ("JJC_SYNC_DISPATCHER_IDLE_SLEEP", 10),
            ("JJC_SYNC_DISPATCHER_BATCH_SIZE", 20),
            ("JJC_SYNC_DISPATCHER_TARGET_PER_WORKER", 3),
        ]
        for key, expected in keys:
            with self.subTest(key=key):
                with mock.patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(config._env_int(key, expected), expected)


if __name__ == "__main__":
    unittest.main()

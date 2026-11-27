"""Unit tests for shared script MongoDB helpers and script compilation."""

from __future__ import annotations

import os
import py_compile
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scripts._common.mongo import (
    DEFAULT_DB_NAME,
    DEFAULT_MONGO_URI,
    open_async_client,
    open_sync_client,
    resolve_database,
    resolve_db_name,
    resolve_mongo_uri,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

SCRIPT_FILES = (
    "scripts/_common/__init__.py",
    "scripts/_common/mongo.py",
    "scripts/backfill_jjc_match_participant_season.py",
    "scripts/backfill_jjc_match_participants.py",
    "scripts/backfill_jjc_match_participants_for_role.py",
    "scripts/backfill_jjc_role_id_from_match_replay.py",
    "scripts/cleanup_role_identity_profile_history.py",
    "scripts/limit_existing_jjc_queue_to_7d.py",
    "scripts/migrate_jjc_sync_identity_queue.py",
    "scripts/rebuild_jjc_peak_score_rankings.py",
    "scripts/recover_jjc_role_identities.py",
)


class TestScriptsCommonMongo(unittest.TestCase):
    def test_resolve_mongo_uri_prefers_explicit_over_env_and_config(self) -> None:
        with patch.dict(os.environ, {"MONGO_URI": "mongodb://env-host:27017/envdb"}):
            uri = resolve_mongo_uri("  mongodb://explicit-host:27017/expdb  ")
        self.assertEqual(uri, "mongodb://explicit-host:27017/expdb")

    def test_resolve_mongo_uri_prefers_env_over_config(self) -> None:
        fake_cfg = SimpleNamespace(MONGO_URI="mongodb://cfg-host:27017/cfgdb")
        with patch.dict(os.environ, {"MONGO_URI": "mongodb://env-host:27017/envdb"}), \
                patch.dict(sys.modules, {"config": fake_cfg}):
            uri = resolve_mongo_uri()
        self.assertEqual(uri, "mongodb://env-host:27017/envdb")

    def test_resolve_mongo_uri_reads_config_when_env_missing(self) -> None:
        fake_cfg = SimpleNamespace(MONGO_URI="mongodb://cfg-host:27017/cfgdb")
        env = dict(os.environ)
        env.pop("MONGO_URI", None)
        with patch.dict(os.environ, env, clear=True), \
                patch.dict(sys.modules, {"config": fake_cfg}):
            uri = resolve_mongo_uri()
        self.assertEqual(uri, "mongodb://cfg-host:27017/cfgdb")

    def test_resolve_mongo_uri_falls_back_to_default_when_config_unavailable(self) -> None:
        env = dict(os.environ)
        env.pop("MONGO_URI", None)
        with patch.dict(os.environ, env, clear=True), \
                patch.dict(sys.modules, {"config": None}):
            uri = resolve_mongo_uri("")
        self.assertEqual(uri, DEFAULT_MONGO_URI)

    def test_resolve_db_name_handles_standard_query_auth_missing_and_override(self) -> None:
        self.assertEqual(
            resolve_db_name("mongodb://127.0.0.1:27017/my_db"),
            "my_db",
        )
        self.assertEqual(
            resolve_db_name("mongodb://127.0.0.1:27017/query_db?authSource=admin&retryWrites=true"),
            "query_db",
        )
        self.assertEqual(
            resolve_db_name("mongodb://user:pass@127.0.0.1:27017/auth_db?authSource=admin"),
            "auth_db",
        )
        self.assertEqual(
            resolve_db_name("mongodb://127.0.0.1:27017"),
            DEFAULT_DB_NAME,
        )
        self.assertEqual(
            resolve_db_name("mongodb://127.0.0.1:27017/?authSource=admin"),
            DEFAULT_DB_NAME,
        )
        self.assertEqual(
            resolve_db_name("mongodb://127.0.0.1:27017", default="custom_default"),
            "custom_default",
        )

    def test_resolve_database_selects_expected_database(self) -> None:
        client = MagicMock()
        client.__getitem__.side_effect = lambda name: "db:{}".format(name)

        self.assertEqual(
            resolve_database(client, "mongodb://user:pass@127.0.0.1:27017/target_db?authSource=admin"),
            "db:target_db",
        )
        self.assertEqual(
            resolve_database(client, "mongodb://127.0.0.1:27017", default="fallback_db"),
            "db:fallback_db",
        )
        self.assertEqual(
            resolve_database(client, "mongodb://127.0.0.1:27017/target_db", db_name="override_db"),
            "db:override_db",
        )

    def test_open_clients_forward_resolved_uri_and_timeout(self) -> None:
        fake_sync_cls = MagicMock(return_value="sync_client")
        fake_async_cls = MagicMock(return_value="async_client")
        with patch("pymongo.MongoClient", fake_sync_cls):
            client = open_sync_client(
                "mongodb://127.0.0.1:27017/sync_db",
                server_selection_timeout_ms=5000,
                appName="test-sync",
            )
        self.assertEqual(client, "sync_client")
        fake_sync_cls.assert_called_once_with(
            "mongodb://127.0.0.1:27017/sync_db",
            serverSelectionTimeoutMS=5000,
            appName="test-sync",
        )

        with patch("motor.motor_asyncio.AsyncIOMotorClient", fake_async_cls):
            async_client = open_async_client(
                "mongodb://127.0.0.1:27017/async_db",
                maxPoolSize=4,
            )
        self.assertEqual(async_client, "async_client")
        fake_async_cls.assert_called_once_with(
            "mongodb://127.0.0.1:27017/async_db",
            serverSelectionTimeoutMS=8000,
            maxPoolSize=4,
        )

    def test_all_refactored_scripts_py_compile_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            for rel_path in SCRIPT_FILES:
                src = REPO_ROOT / rel_path
                self.assertTrue(src.is_file(), "Missing script: {}".format(rel_path))
                cfile = Path(tmp_dir) / (rel_path.replace("/", "_") + "c")
                compiled = py_compile.compile(str(src), cfile=str(cfile), doraise=True)
                self.assertTrue(bool(compiled))


if __name__ == "__main__":
    unittest.main()

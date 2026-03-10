from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services.jx3.jjc_cache_repo import JjcCacheRepo


class JjcCacheRepoTests(unittest.TestCase):
    def test_load_ranking_cache_falls_back_to_file_and_backfills_mongo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "jjc_ranking_cache.json"
            cache_file.write_text(
                json.dumps({"cache_time": 1_900_000_000, "data": {"foo": "bar"}}, ensure_ascii=False),
                encoding="utf-8",
            )
            repo = JjcCacheRepo(
                jjc_ranking_cache_file=str(cache_file),
                jjc_ranking_cache_duration=7200,
                kungfu_cache_duration=7 * 24 * 60 * 60,
            )
            with (
                patch("src.services.jx3.jjc_cache_repo.jjc_cache_storage.load_ranking_cache", return_value=None),
                patch("src.services.jx3.jjc_cache_repo.jjc_cache_storage.save_ranking_cache") as save_mock,
                patch("src.services.jx3.jjc_cache_repo.time.time", return_value=1_900_000_100),
            ):
                payload = repo.load_ranking_cache()

            self.assertEqual(payload, {"foo": "bar", "cache_time": 1_900_000_000})
            save_mock.assert_called_once()

    def test_load_kungfu_cache_falls_back_to_file_and_backfills_mongo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = Path.cwd()
            try:
                tmp_path = Path(tmpdir)
                (tmp_path / "data" / "cache" / "kungfu").mkdir(parents=True)
                cache_file = tmp_path / "data" / "cache" / "kungfu" / "梦江南_测试角色.json"
                payload = {
                    "server": "梦江南",
                    "name": "测试角色",
                    "kungfu": "莫问",
                    "cache_time": 1_900_000_000,
                    "weapon_checked": True,
                    "teammates_checked": True,
                    "teammates": [{"name": "队友", "kungfu_id": "10014"}],
                }
                cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                repo = JjcCacheRepo(
                    jjc_ranking_cache_file=str(tmp_path / "data" / "cache" / "jjc_ranking_cache.json"),
                    jjc_ranking_cache_duration=7200,
                    kungfu_cache_duration=7 * 24 * 60 * 60,
                )
                import os

                os.chdir(tmp_path)
                with (
                    patch("src.services.jx3.jjc_cache_repo.jjc_cache_storage.load_kungfu_cache", return_value=None),
                    patch("src.services.jx3.jjc_cache_repo.jjc_cache_storage.save_kungfu_cache") as save_mock,
                    patch("src.services.jx3.jjc_cache_repo.time.time", return_value=1_900_000_100),
                ):
                    result = repo.load_kungfu_cache("梦江南", "测试角色")
            finally:
                import os

                os.chdir(old_cwd)

            self.assertIsNotNone(result)
            self.assertEqual(result["kungfu"], "莫问")
            save_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()

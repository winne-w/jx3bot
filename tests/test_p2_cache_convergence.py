from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId

from src.services.jx3.jjc_cache_repo import JjcCacheRepo
from src.storage.mongo_repos.jjc_ranking_cache_repo import JjcRankingCacheRepo
from src.storage.mongo_repos.role_jjc_cache_repo import RoleJjcCacheRepo


class _AsyncCursor:
    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self._docs = list(docs)
        self._index = 0

    def __aiter__(self) -> "_AsyncCursor":
        return self

    async def __anext__(self) -> Dict[str, Any]:
        if self._index >= len(self._docs):
            raise StopAsyncIteration
        doc = self._docs[self._index]
        self._index += 1
        return doc


class _InMemoryCollection:
    def __init__(self) -> None:
        self.docs: List[Dict[str, Any]] = []
        self.find_one_queries: List[Dict[str, Any]] = []

    async def find_one(self, query: Dict[str, Any]) -> Any:
        self.find_one_queries.append(dict(query))
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    async def update_one(self, query: Dict[str, Any], update: Dict[str, Any], upsert: bool = False) -> None:
        set_fields = dict(update.get("$set") or {})
        for idx, doc in enumerate(self.docs):
            if all(doc.get(k) == v for k, v in query.items()):
                updated = dict(doc)
                updated.update(set_fields)
                self.docs[idx] = updated
                return
        if upsert:
            new_doc = dict(query)
            new_doc.update(set_fields)
            new_doc.setdefault("_id", ObjectId())
            self.docs.append(new_doc)


class JjcRankingCacheRepoTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_and_load_fresh_ranking_cache(self) -> None:
        col = _InMemoryCollection()
        db = SimpleNamespace(jjc_ranking_cache=col)
        repo = JjcRankingCacheRepo(db=db, cache_duration=3600)

        now = time.time()
        payload = {"code": 0, "data": [{"rank": 1}], "cache_time": now}
        await repo.save_ranking_cache(payload)

        loaded = await repo.load_ranking_cache()
        self.assertEqual(loaded, payload)
        self.assertEqual(len(col.docs), 1)
        self.assertEqual(col.docs[0]["cache_key"], "ranking")
        self.assertIn("created_at", col.docs[0])

    async def test_load_expired_ranking_cache_returns_none(self) -> None:
        col = _InMemoryCollection()
        db = SimpleNamespace(jjc_ranking_cache=col)
        repo = JjcRankingCacheRepo(db=db, cache_duration=60)

        expired_payload = {"code": 0, "data": [], "cache_time": time.time() - 120}
        await repo.save_ranking_cache(expired_payload)

        loaded = await repo.load_ranking_cache()
        self.assertIsNone(loaded)

    async def test_load_missing_ranking_cache_returns_none(self) -> None:
        col = _InMemoryCollection()
        db = SimpleNamespace(jjc_ranking_cache=col)
        repo = JjcRankingCacheRepo(db=db, cache_duration=3600)

        self.assertIsNone(await repo.load_ranking_cache())


class RoleJjcCacheRepoIdentityIdTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_by_identity_id_and_save_preserves_identity_id(self) -> None:
        col = _InMemoryCollection()
        db = SimpleNamespace(role_jjc_cache=col)
        repo = RoleJjcCacheRepo(db=db)
        oid = ObjectId()

        await repo.save(
            "global_id:1001",
            {
                "identity_id": oid,
                "server": "蝶恋花",
                "name": "测试角色",
                "global_id": "1001",
                "kungfu": "冰心诀",
            },
        )

        self.assertEqual(col.docs[0]["identity_id"], oid)
        doc = await repo.load_by_identity_id(oid)
        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertNotIn("_id", doc)
        self.assertEqual(doc["identity_id"], oid)
        self.assertEqual(doc["kungfu"], "冰心诀")
        self.assertIsNone(await repo.load_by_identity_id(None))

    async def test_save_drops_none_identity_id(self) -> None:
        col = _InMemoryCollection()
        db = SimpleNamespace(role_jjc_cache=col)
        repo = RoleJjcCacheRepo(db=db)

        await repo.save(
            "name:蝶恋花:测试角色",
            {"identity_id": None, "server": "蝶恋花", "name": "测试角色", "kungfu": "花间游"},
        )
        self.assertNotIn("identity_id", col.docs[0])

    async def test_load_by_best_identity_prefers_identity_id_first(self) -> None:
        col = _InMemoryCollection()
        db = SimpleNamespace(role_jjc_cache=col)
        repo = RoleJjcCacheRepo(db=db)
        oid = ObjectId()

        await repo.save(
            "old:key",
            {
                "identity_id": oid,
                "server": "旧服",
                "name": "旧名",
                "global_id": "old-gid",
                "kungfu": "孤锋诀",
            },
        )
        col.find_one_queries.clear()

        doc = await repo.load_by_best_identity(
            server="新服",
            name="新名",
            global_id="new-gid",
            identity_id=oid,
        )
        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertEqual(doc["kungfu"], "孤锋诀")
        self.assertEqual(col.find_one_queries, [{"identity_id": oid}])

    async def test_load_by_best_identity_falls_back_when_identity_id_misses(self) -> None:
        col = _InMemoryCollection()
        db = SimpleNamespace(role_jjc_cache=col)
        repo = RoleJjcCacheRepo(db=db)
        missing_oid = ObjectId()

        await repo.save(
            "global_id:2002",
            {
                "server": "蝶恋花",
                "name": "测试角色",
                "global_id": "2002",
                "kungfu": "云裳心经",
            },
        )
        col.find_one_queries.clear()

        doc = await repo.load_by_best_identity(
            server="蝶恋花",
            name="测试角色",
            global_id="2002",
            identity_id=missing_oid,
        )
        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertEqual(doc["kungfu"], "云裳心经")
        self.assertEqual(
            col.find_one_queries,
            [{"identity_id": missing_oid}, {"global_id": "2002"}],
        )


class JjcCacheRepoConvergenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_ranking_cache_delegates_to_jjc_ranking_cache_repo(self) -> None:
        db = SimpleNamespace(jjc_ranking_cache=_InMemoryCollection())
        cache_repo = JjcCacheRepo(
            jjc_ranking_cache_duration=1800,
            kungfu_cache_duration=3600,
            db=db,
        )
        expected = {"code": 0, "data": [{"rank": 1}]}

        with patch(
            "src.storage.mongo_repos.jjc_ranking_cache_repo.JjcRankingCacheRepo",
        ) as mock_cls:
            mock_instance = MagicMock()
            mock_instance.load_ranking_cache = AsyncMock(return_value=expected)
            mock_instance.save_ranking_cache = AsyncMock()
            mock_cls.return_value = mock_instance

            loaded = await cache_repo.load_ranking_cache()
            await cache_repo.save_ranking_cache(expected)

        self.assertEqual(loaded, expected)
        self.assertEqual(mock_cls.call_count, 2)
        for call_args in mock_cls.call_args_list:
            self.assertEqual(call_args.kwargs, {"db": db, "cache_duration": 1800})
        mock_instance.load_ranking_cache.assert_awaited_once_with()
        mock_instance.save_ranking_cache.assert_awaited_once_with(expected)

    async def test_load_and_save_kungfu_cache_propagate_identity_id(self) -> None:
        oid = ObjectId()
        role_cache_col = _InMemoryCollection()
        db = SimpleNamespace(role_jjc_cache=role_cache_col)
        cache_repo = JjcCacheRepo(
            jjc_ranking_cache_duration=3600,
            kungfu_cache_duration=3600,
            db=db,
        )

        mock_identity_repo = MagicMock()
        mock_identity_repo.upsert_from_indicator = AsyncMock(
            return_value={
                "_id": oid,
                "identity_key": "global_id:5005",
                "server": "蝶恋花",
                "name": "测试角色",
            }
        )

        with patch(
            "src.storage.mongo_repos.role_identity_repo.RoleIdentityRepo",
            return_value=mock_identity_repo,
        ):
            await cache_repo.save_kungfu_cache(
                "蝶恋花",
                "测试角色",
                {"kungfu": "冰心诀", "found": True, "global_id": "5005"},
            )

        self.assertEqual(role_cache_col.docs[0]["identity_id"], oid)
        self.assertEqual(role_cache_col.docs[0]["identity_key"], "global_id:5005")

        role_cache_col.find_one_queries.clear()
        loaded = await cache_repo.load_new_kungfu_cache_raw(
            "新服",
            "新名",
            identity={"_id": oid, "identity_key": "global_id:5005"},
        )
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded["kungfu"], "冰心诀")
        self.assertEqual(role_cache_col.find_one_queries, [{"identity_id": oid}])

    async def test_win_history_prefers_participants_aggregate_without_scanning_match_detail(self) -> None:
        mock_detail_col = MagicMock()
        mock_detail_col.find.side_effect = AssertionError("should not scan jjc_match_detail")
        db = SimpleNamespace(
            jjc_match_participants=MagicMock(),
            jjc_match_detail=mock_detail_col,
        )
        cache_repo = JjcCacheRepo(
            jjc_ranking_cache_duration=3600,
            kungfu_cache_duration=3600,
            db=db,
        )

        mock_participant_repo = MagicMock()
        mock_participant_repo.aggregate_winning_kungfu = AsyncMock(
            return_value=[
                {
                    "kungfu": "花间游",
                    "wins": 2,
                    "total": 3,
                    "latest_win_time": 1700000500,
                    "latest_win_match_id": 99,
                    "kungfu_id": 10021,
                },
                {
                    "kungfu": "孤锋诀",
                    "wins": 4,
                    "total": 6,
                    "latest_win_time": 1700000400,
                    "latest_win_match_id": 88,
                    "kungfu_id": 10698,
                },
            ]
        )

        with patch(
            "src.storage.mongo_repos.jjc_match_participant_repo.JjcMatchParticipantRepo",
            return_value=mock_participant_repo,
        ):
            result = await cache_repo.get_kungfu_from_cached_match_detail_win_history(
                server="蝶恋花",
                name="测试角色",
                season_start="2023-01-01",
                global_id="99999",
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["found"])
        self.assertEqual(result["kungfu"], "孤锋诀")
        self.assertEqual(result["kungfu_id"], 10698)
        self.assertEqual(result["cached_match_detail_win_count"], 4)
        self.assertEqual(result["cached_match_detail_total_count"], 6)
        self.assertEqual(result["cached_match_detail_latest_win_match_id"], 88)
        self.assertEqual(result["cached_match_detail_latest_win_time"], 1700000400)
        self.assertEqual(result["kungfu_selected_source"], "cached_match_detail_win_history")
        mock_participant_repo.aggregate_winning_kungfu.assert_awaited_once()
        mock_detail_col.find.assert_not_called()

    async def test_win_history_integrates_with_real_participant_repo_aggregate(self) -> None:
        mock_detail_col = MagicMock()
        mock_detail_col.find.side_effect = AssertionError("should not scan jjc_match_detail")

        agg_cursor = SimpleNamespace(
            to_list=AsyncMock(
                return_value=[
                    {
                        "_id": "孤锋诀",
                        "wins": 5,
                        "latest_match_time": 1700000900,
                        "latest_match_id": 505,
                    }
                ]
            )
        )
        participants_col = SimpleNamespace(aggregate=MagicMock(return_value=agg_cursor))
        db = SimpleNamespace(
            jjc_match_participants=participants_col,
            jjc_match_detail=mock_detail_col,
        )
        cache_repo = JjcCacheRepo(
            jjc_ranking_cache_duration=3600,
            kungfu_cache_duration=3600,
            db=db,
        )

        result = await cache_repo.get_kungfu_from_cached_match_detail_win_history(
            server="蝶恋花",
            name="测试角色",
            season_start="2023-01-01",
            global_id="99999",
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["found"])
        self.assertEqual(result["kungfu"], "孤锋诀")
        self.assertEqual(result["cached_match_detail_win_count"], 5)
        self.assertEqual(result["cached_match_detail_total_count"], 5)
        self.assertEqual(result["cached_match_detail_latest_win_match_id"], 505)
        self.assertEqual(result["cached_match_detail_latest_win_time"], 1700000900)
        participants_col.aggregate.assert_called_once()
        mock_detail_col.find.assert_not_called()

    async def test_win_history_falls_back_to_match_detail_when_participants_empty_or_error(self) -> None:
        detail_docs = [
            {
                "match_id": i,
                "data": {
                    "detail": {
                        "match_time": 1700000000 + i * 100,
                        "team1": {
                            "won": True,
                            "players_info": [
                                {
                                    "server": "蝶恋花",
                                    "role_name": "测试角色",
                                    "kungfu": "孤锋诀",
                                    "global_id": "99999",
                                }
                            ],
                        },
                        "team2": {"won": False, "players_info": []},
                    }
                },
            }
            for i in (1, 2, 3)
        ]

        for side_effect in (
            AsyncMock(return_value=[]),
            AsyncMock(side_effect=RuntimeError("aggregate unsupported")),
        ):
            mock_detail_col = MagicMock()
            mock_detail_col.find.return_value = _AsyncCursor(detail_docs)
            db = SimpleNamespace(
                jjc_match_participants=MagicMock(),
                jjc_match_detail=mock_detail_col,
            )
            cache_repo = JjcCacheRepo(
                jjc_ranking_cache_duration=3600,
                kungfu_cache_duration=3600,
                db=db,
            )
            mock_participant_repo = MagicMock()
            mock_participant_repo.aggregate_winning_kungfu = side_effect

            with patch(
                "src.storage.mongo_repos.jjc_match_participant_repo.JjcMatchParticipantRepo",
                return_value=mock_participant_repo,
            ):
                result = await cache_repo.get_kungfu_from_cached_match_detail_win_history(
                    server="蝶恋花",
                    name="测试角色",
                    global_id="99999",
                )

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result["kungfu"], "孤锋诀")
            self.assertEqual(result["cached_match_detail_win_count"], 3)
            mock_detail_col.find.assert_called_once()


if __name__ == "__main__":
    unittest.main()

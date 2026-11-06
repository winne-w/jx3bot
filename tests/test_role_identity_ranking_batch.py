"""Batch ranking identity resolution preserves IDs and rejects ambiguous links."""
import os
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from src.storage.mongo_repos.role_identity_repo import RoleIdentityRepo
from tests.test_jjc_kungfu_refresh_mongo import checked_test_uri


def identity(**fields):
    return {"_id": ObjectId(), "server": "server", "name": "name", "zone": "zone",
            "normalized_server": "server", "normalized_name": "name", **fields}


class Cursor:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self, length):
        return deepcopy(self.docs)


class TestRankingIdentityBatch(unittest.IsolatedAsyncioTestCase):
    def repo(self, docs):
        self.col = SimpleNamespace(find=Mock(side_effect=lambda query: Cursor(docs)))
        return RoleIdentityRepo(db=SimpleNamespace(role_identities=self.col))

    async def test_known_roles_keep_order_and_kungfu_in_bounded_queries(self):
        docs = [identity(name=str(i), normalized_name=str(i), game_role_id=str(i),
                         jjc_kungfu={"publish_version": 2}) for i in range(1000)]
        repo = self.repo(list(reversed(docs)))
        players = [{k: d[k] for k in ("server", "name", "zone", "game_role_id")} for d in docs]
        with patch.object(RoleIdentityRepo, "upsert_from_ranking_with_id", new_callable=AsyncMock) as upsert:
            result = await repo.resolve_ranking_identities_batch(players)
        self.assertEqual([d["_id"] for d in result], [d["_id"] for d in docs])
        self.assertTrue(all(d["jjc_kungfu"]["publish_version"] == 2 for d in result))
        self.assertLessEqual(self.col.find.call_count, 4)
        upsert.assert_not_awaited()

    async def test_strong_id_wins_over_same_name_candidate(self):
        expected = identity(name="old-name", normalized_name="old-name", global_id="stable", game_role_id="7")
        other = identity(global_id="different", game_role_id="8")
        repo = self.repo([other, expected])
        result = await repo.resolve_ranking_identities_batch([
            {"server": "server", "name": "name", "global_id": "stable", "game_role_id": "7", "zone": "zone"}])
        self.assertEqual(result[0]["_id"], expected["_id"])

    async def test_every_known_id_conflict_rejects_without_upsert(self):
        cases = [({"global_id": "g", "global_role_id": "SK-a"}, {"global_id": "g", "global_role_id": "SK-b"}),
                 ({"global_id": "g", "game_role_id": "1"}, {"global_id": "g", "game_role_id": "2"}),
                 ({"global_id": "g", "zone": "other"}, {"global_id": "g", "zone": "zone"}),
                 ({"game_role_id": "1"}, {"game_role_id": "2"}),
                 ({"game_role_id": "1"}, {"game_role_id": "1", "role_id": "2"})]
        for incoming, stored in cases:
            repo = self.repo([identity(**stored)])
            with patch.object(RoleIdentityRepo, "upsert_from_ranking_with_id", new_callable=AsyncMock) as upsert:
                self.assertEqual(await repo.resolve_ranking_identities_batch([
                    {"server": "server", "name": "name", "zone": "zone", **incoming}]), [None])
                upsert.assert_not_awaited()

    async def test_ambiguous_name_or_strong_id_does_not_pick_latest(self):
        for extras in ({}, {"global_id": "g"}):
            repo = self.repo([identity(**extras), identity(**extras)])
            with patch.object(RoleIdentityRepo, "upsert_from_ranking_with_id", new_callable=AsyncMock) as upsert:
                self.assertEqual(await repo.resolve_ranking_identities_batch([
                    {"server": "server", "name": "name", **extras}]), [None])
                upsert.assert_not_awaited()

    async def test_split_strong_id_matches_do_not_bridge_two_existing_roles(self):
        repo = self.repo([identity(global_id="g"), identity(global_id="other", game_role_id="7")])
        with patch.object(RoleIdentityRepo, "upsert_from_ranking_with_id", new_callable=AsyncMock) as upsert:
            self.assertEqual(await repo.resolve_ranking_identities_batch([
                {"server": "server", "name": "name", "global_id": "g", "zone": "zone", "game_role_id": "7"}]), [None])
            upsert.assert_not_awaited()

    async def test_unique_name_fallback_validates_supplied_ids(self):
        doc = identity(game_role_id="7")
        repo = self.repo([doc])
        self.assertEqual((await repo.resolve_ranking_identities_batch([
            {"server": " SERVER ", "name": " NAME ", "game_role_id": "7"}]))[0]["_id"], doc["_id"])

    async def test_legacy_identity_key_resolves_without_namespace_confusion(self):
        doc = identity(identity_key="global:SK-a")
        repo = self.repo([doc])
        self.assertEqual((await repo.resolve_ranking_identities_batch([
            {"server": "else", "name": "else", "global_role_id": "SK-a"}]))[0]["_id"], doc["_id"])
        self.assertIsNone((await repo.resolve_ranking_identities_batch([
            {"server": "server", "name": "name", "global_role_id": "SK-b"}]))[0])

    async def test_missing_upsert_once_for_duplicates_and_revalidates(self):
        player = {"server": "server", "name": "name", "zone": "zone", "game_role_id": "7"}
        for valid in (True, False):
            repo = self.repo([])
            created = identity(game_role_id="7" if valid else "wrong")
            with patch.object(RoleIdentityRepo, "upsert_from_ranking_with_id", new_callable=AsyncMock, return_value=created) as upsert:
                result = await repo.resolve_ranking_identities_batch([player, dict(player)])
            upsert.assert_awaited_once()
            self.assertEqual(result, [created, created] if valid else [None, None])

    async def test_incomplete_candidate_upsert_is_revalidated_and_duplicates_share_work(self):
        original = identity(jjc_kungfu={"publish_version": 3})
        original.pop("zone")
        complete = {**original, "zone": "zone", "game_role_id": "7"}
        alternatives = [complete, {**complete, "_id": ObjectId()},
                        {**complete, "game_role_id": "wrong"}, original, {**original, "zone": "zone"},
                        {key: value for key, value in complete.items() if key != "jjc_kungfu"}]
        for enriched in alternatives:
            with self.subTest(enriched=enriched):
                repo = self.repo([original])
                with patch.object(RoleIdentityRepo, "upsert_from_ranking_with_id", new_callable=AsyncMock,
                                  return_value=enriched) as upsert:
                    player = {"server": "server", "name": "name", "zone": "zone",
                              "game_role_id": " ", "role_id": "7"}
                    result = await repo.resolve_ranking_identities_batch([player, dict(player)])
                self.assertEqual(result, [complete, complete] if enriched == complete else [None, None])
                upsert.assert_awaited_once()

    async def test_invalid_input_and_empty_batch_never_write(self):
        repo = self.repo([])
        with patch.object(RoleIdentityRepo, "upsert_from_ranking_with_id", new_callable=AsyncMock) as upsert:
            self.assertEqual(await repo.resolve_ranking_identities_batch([]), [])
            self.assertEqual(await repo.resolve_ranking_identities_batch([
                {}, {"server": "server", "name": "name", "game_role_id": "1", "role_id": "2"}]), [None, None])
            upsert.assert_not_awaited()


@unittest.skipUnless(os.environ.get("JJC_TEST_MONGO_URI"), "explicit local Mongo URI required")
class TestRankingIdentityBatchMongo(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = AsyncIOMotorClient(checked_test_uri(os.environ["JJC_TEST_MONGO_URI"]), serverSelectionTimeoutMS=3000)
        self.db_name = "jjc_kungfu_test_" + uuid4().hex
        self.db = self.client[self.db_name]
        self.repo = RoleIdentityRepo(db=self.db)

    async def asyncTearDown(self):
        self.assertTrue(self.db_name.startswith("jjc_kungfu_test_"))
        await self.client.drop_database(self.db_name)
        self.client.close()

    async def test_actual_query_returns_full_known_and_legacy_docs_and_creates_only_missing(self):
        docs = [identity(name="known", normalized_name="known", global_id="g", jjc_kungfu={"publish_version": 3}),
                identity(name="legacy", normalized_name="legacy", identity_key="game:zone:8")]
        await self.db.role_identities.insert_many(deepcopy(docs))
        result = await self.repo.resolve_ranking_identities_batch([
            {"server": "server", "name": "known", "global_id": "g"},
            {"server": "server", "name": "legacy", "zone": "zone", "game_role_id": "8"},
            {"server": "server", "name": "new", "zone": "zone", "game_role_id": "9"}])
        self.assertEqual([d["_id"] for d in result[:2]], [d["_id"] for d in docs])
        self.assertEqual(result[0]["jjc_kungfu"]["publish_version"], 3)
        self.assertEqual(result[2]["game_role_id"], "9")
        self.assertEqual(await self.db.role_identities.count_documents({}), 3)

    async def assert_incomplete_identity_is_enriched(self, global_only):
        original = identity(identity_key="global_id:g" if global_only else "name:server:name",
                            identity_level="global_id" if global_only else "name",
                            jjc_kungfu={"publish_version": 3, "name": "云裳心经"})
        original.pop("zone")
        if global_only:
            original["global_id"] = "g"
        await self.db.role_identities.insert_one(deepcopy(original))
        player = {"server": "server", "name": "name", "zone": "zone", "game_role_id": "7"}
        if global_only:
            player["global_id"] = "g"
        results = await self.repo.resolve_ranking_identities_batch([player, dict(player)])
        self.assertEqual([doc["_id"] for doc in results], [original["_id"]] * 2)
        for doc in results:
            self.assertEqual((doc.get("zone"), doc.get("game_role_id")), ("zone", "7"))
            self.assertEqual(doc["jjc_kungfu"], original["jjc_kungfu"])
        stored = await self.db.role_identities.find_one({"_id": original["_id"]})
        self.assertEqual(stored["jjc_kungfu"], original["jjc_kungfu"])
        self.assertEqual(stored["game_role_id"], "7")
        self.assertEqual(await self.db.role_identities.count_documents({}), 1)

    async def test_name_only_existing_role_gains_query_locator_without_new_identity(self):
        await self.assert_incomplete_identity_is_enriched(global_only=False)

    async def test_global_only_existing_role_gains_query_locator_without_losing_kungfu(self):
        await self.assert_incomplete_identity_is_enriched(global_only=True)

    async def test_actual_conflicts_and_ambiguities_preserve_database(self):
        docs = [identity(global_id="g", game_role_id="7"), identity(name="duplicate", normalized_name="duplicate"),
                identity(name="duplicate", normalized_name="duplicate")]
        await self.db.role_identities.insert_many(deepcopy(docs))
        result = await self.repo.resolve_ranking_identities_batch([
            {"server": "server", "name": "name", "global_id": "g", "zone": "zone", "game_role_id": "8"},
            {"server": "server", "name": "duplicate"}])
        self.assertEqual(result, [None, None])
        self.assertEqual(await self.db.role_identities.count_documents({}), 3)
        self.assertEqual((await self.db.role_identities.find_one({"global_id": "g"}))["game_role_id"], "7")

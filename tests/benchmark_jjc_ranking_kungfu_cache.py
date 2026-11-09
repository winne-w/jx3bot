"""Opt-in isolated Mongo benchmark; run as python -m tests.benchmark_jjc_ranking_kungfu_cache.

Requires explicit safe JJC_TEST_MONGO_URI. Only random test databases are created.
No upstream calls; full-history sync is mocked and excluded from the timings.
"""
import asyncio
from dataclasses import replace
import json
import math
import os
import time
from statistics import median
from uuid import uuid4
from motor.motor_asyncio import AsyncIOMotorClient
from tests.test_jjc_kungfu_refresh_mongo import checked_test_uri
from tests.test_jjc_ranking_kungfu_cache import RankingKungfuCacheTests, identity, player, NOW, SCOPE
from src.storage.mongo_repos.role_identity_repo import RoleIdentityRepo
from src.storage.mongo_repos.jjc_kungfu_refresh_repo import JjcKungfuRefreshRepo

async def run():
    client = AsyncIOMotorClient(checked_test_uri(os.environ["JJC_TEST_MONGO_URI"]), serverSelectionTimeoutMS=3000)
    await client.admin.command("ping")
    results = []
    try:
        for case in ("hot", "cold", "half_missing", "other_scope"):
            db_name = "jjc_kungfu_test_" + uuid4().hex
            assert db_name.startswith("jjc_kungfu_test_") and len(db_name) == len("jjc_kungfu_test_") + 32
            db = client[db_name]
            fixture = RankingKungfuCacheTests(methodName="test_thousand_hot_roles_are_resolved_in_one_batch_and_registered_without_foreground_queries")
            fixture.setUp()
            try:
                for keys in ["identity_key", "global_role_id", [("zone", 1), ("game_role_id", 1)], [("zone", 1), ("role_id", 1)], [("normalized_server", 1), ("normalized_name", 1)]]:
                    await db.role_identities.create_index(keys)
                docs = [identity(i, include_result=(case != "cold" and (case != "half_missing" or i % 2 == 0))) for i in range(1000)]
                if case == "other_scope":
                    for doc in docs:
                        doc["jjc_kungfu"]["season_id"] = "previous-season"
                for doc in docs:
                    doc["normalized_server"] = doc["server"].lower()
                    doc["normalized_name"] = doc["name"].lower()
                queue = JjcKungfuRefreshRepo(db=db)
                await queue.ensure_indexes()
                # Offline fixture initialization, no worker exists for this disposable DB.
                await queue.register([{k: v for k, v in doc.items() if k != "jjc_kungfu"} for doc in docs], SCOPE, NOW)
                if case != "cold":
                    await db.jjc_kungfu_refresh_queue.update_many({}, {"$set": {"generation": 1}})
                await db.role_identities.insert_many(docs)
                fixture.service = replace(fixture.service, identity_repo=RoleIdentityRepo(db=db), kungfu_refresh_repo=queue)
                ranking = {"data": [player(i) for i in range(1000)], "cache_time": NOW}
                durations = []
                for _ in range(30):
                    started = time.perf_counter()
                    actual = await fixture.service.get_ranking_kungfu_data(ranking)
                    durations.append((time.perf_counter() - started) * 1000)
                    assert "error" not in actual, actual
                    assert actual["refresh_degraded"] is False, actual
                    counts = actual["kungfu_statistics"]["top_1000"]["kungfu_cache"]
                    assert counts["total"] == 1000 and counts["coverage"] == ({"hot":1.0,"half_missing":0.5}.get(case,0.0)), counts
                fixture.service.tuilan_request.assert_not_called()
                fixture.service.defget_get.assert_not_awaited()
                results.append({"case": case, "members": 1000, "runs": 30,
                    "p50_ms": round(median(durations), 3),
                    "p95_ms": round(sorted(durations)[math.ceil(.95 * len(durations)) - 1], 3),
                    "upstream_calls": 0})
            finally:
                fixture.doCleanups()
                await client.drop_database(db_name)
    finally:
        client.close()
    print(json.dumps({"backend": "real isolated Mongo loopback port 27029; real identity batch and queue register",
        "includes": "Mongo identity batch reads, real queue registration, validation, aggregation",
        "excludes": "leaderboard fetch, full history synchronization (AsyncMock), render/send; no production scale collection background",
        "results": results}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    asyncio.run(run())

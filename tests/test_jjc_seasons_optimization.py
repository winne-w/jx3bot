from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.services.jx3.jjc_seasons_cache import JjcSeasonsCacheService
from src.storage.mongo_repos.jjc_ranking_stats_repo import (
    EquipmentSnapshotError,
    JjcRankingStatsRepo,
)


class _AsyncCursor:
    def __init__(self, rows, *, delay=0.0, error=None, blocked=False):
        self._rows = list(rows)
        self._delay = delay
        self._error = error
        self._blocked = blocked
        self.closed = False
        self.max_time = None
        self.batch = None
        self.started = asyncio.Event()

    def max_time_ms(self, ms):
        self.max_time = ms
        return self

    def batch_size(self, count):
        self.batch = count
        return self

    def sort(self, *args, **kwargs):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.started.set()
        if self._blocked:
            await asyncio.Event().wait()
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        if not self._rows:
            raise StopAsyncIteration
        return self._rows.pop(0)

    async def close(self):
        self.closed = True


class _AggregateCollection:
    def __init__(self, agg_factory, find_factory=None, *, accept_kwargs=True):
        self.agg_calls = []
        self.find_calls = []
        self._agg_factory = agg_factory
        self._find_factory = find_factory or (lambda query: _AsyncCursor([]))
        self._accept_kwargs = accept_kwargs

    def find(self, query, *args, **kwargs):
        self.find_calls.append((query, args, kwargs))
        return self._find_factory(query)

    def aggregate(self, pipeline, **kwargs):
        if kwargs and not self._accept_kwargs:
            raise TypeError("aggregate() does not accept kwargs")
        self.agg_calls.append((pipeline, kwargs))
        return self._agg_factory(pipeline, kwargs)


class TestJjcRankingStatsRepoSeasonsAggregate(unittest.IsolatedAsyncioTestCase):
    async def test_list_seasons_uses_server_aggregate_and_normalizes_seasons(self):
        cursors = []

        def agg_factory(pipeline, kwargs):
            if pipeline and "$project" in pipeline[-1]:
                return _AsyncCursor([])
            cursor = _AsyncCursor([
                {"_id": "苍生铸世", "latest_timestamp": 500},
                {"_id": 17, "latest_timestamp": 300},
                {"_id": "17", "latest_timestamp": 250},
                {"_id": True, "latest_timestamp": 999},
                {"_id": "", "latest_timestamp": 888},
            ])
            cursors.append(cursor)
            return cursor

        col = _AggregateCollection(agg_factory)
        db = SimpleNamespace(name="test_agg_db", jjc_ranking_stat_summaries=col)
        repo = JjcRankingStatsRepo(db=db, suppress_errors=False)

        result = await repo.list_seasons()

        self.assertEqual(result, {
            "seasons": [
                {"name": "苍生铸世", "latest_timestamp": 500},
                {"name": "17", "latest_timestamp": 300},
            ],
            "default_season": "苍生铸世",
        })
        self.assertEqual(len(col.agg_calls), 2)
        pipeline, kwargs = col.agg_calls[-1]
        self.assertEqual(kwargs.get("maxTimeMS"), 1500)
        self.assertEqual(kwargs.get("batchSize"), 512)
        self.assertEqual(pipeline[-2], {"$group": {"_id": "$current_season", "latest_timestamp": {"$max": "$timestamp"}}})
        self.assertTrue(cursors[0].closed)

    async def test_list_seasons_aggregate_type_error_fallback(self):
        col = _AggregateCollection(
            lambda p, k: _AsyncCursor([]) if (p and "$project" in p[-1]) else _AsyncCursor([{"_id": "苍生铸世", "latest_timestamp": 400}]),
            accept_kwargs=False,
        )
        db = SimpleNamespace(name="test_agg_no_kwargs", jjc_ranking_stat_summaries=col)
        repo = JjcRankingStatsRepo(db=db, suppress_errors=False)

        result = await repo.list_seasons()
        self.assertEqual(result["default_season"], "苍生铸世")
        self.assertEqual(len(col.agg_calls), 2)
        self.assertEqual(col.agg_calls[-1][1], {})

    async def test_v2_metadata_projection_validation_accepts_valid_and_rejects_corrupt(self):
        from tests.test_jjc_ranking_equipment_publish import candidate
        from tests.jjc_equipment_fixtures import TIMESTAMP

        valid_doc = candidate(timestamp=TIMESTAMP)
        ev = valid_doc["equipment_view"]
        projected = {
            "timestamp": valid_doc["timestamp"],
            "schema_version": valid_doc["schema_version"],
            "equipment_complete": valid_doc["equipment_complete"],
            "equipment_source": valid_doc["equipment_source"],
            "ranking_display_kind": valid_doc["ranking_display_kind"],
            "current_season": valid_doc["current_season"],
            "kungfu_cache_scope": valid_doc["kungfu_cache_scope"],
            "equipment_view_revision": valid_doc["equipment_view_revision"],
            "member_revision": valid_doc["member_revision"],
            "doc_bson_size": 1024,
            "ev_is_obj": True,
            "ev_timestamp": ev["timestamp"],
            "ev_source": ev["source"],
            "ev_scope": ev["scope"],
            "ev_member_revision": ev["member_revision"],
            "ev_view_revision": ev["equipment_view_revision"],
            "ev_range_counts": {k: v["N"] for k, v in ev["ranges"].items()},
            "ev_member_count": len(ev["members"]),
        }
        self.assertEqual(JjcRankingStatsRepo._validate_equipment_metadata_projection(projected), TIMESTAMP)
        for field, bad_value in (
            ("equipment_complete", False),
            ("equipment_source", "legacy_v1"),
            ("ev_is_obj", False),
            ("equipment_view_revision", "damaged"),
            ("ev_member_count", len(ev["members"]) - 1),
            ("current_season", "wrong-season"),
            ("doc_bson_size", 9 * 1024 * 1024),
        ):
            broken = dict(projected)
            broken[field] = bad_value
            self.assertIsNone(JjcRankingStatsRepo._validate_equipment_metadata_projection(broken), msg=field)

    async def test_list_seasons_fallback_to_find_when_aggregate_absent(self):
        find_calls = []

        def find(query, *args, **kwargs):
            find_calls.append(query)
            if query == {"schema_version": 2}:
                return _AsyncCursor([])
            return _AsyncCursor([
                {"current_season": "苍生铸世", "timestamp": 300},
                {"current_season": "山海源流", "timestamp": 100},
            ])

        col = SimpleNamespace(find=find)
        db = SimpleNamespace(name="test_find_fallback", jjc_ranking_stat_summaries=col)
        repo = JjcRankingStatsRepo(db=db, suppress_errors=False)

        result = await repo.list_seasons()
        self.assertEqual(result["default_season"], "苍生铸世")
        self.assertEqual(len(find_calls), 2)

    async def test_readable_snapshot_query_reuses_bson_size_without_double_encode(self):
        from tests.test_jjc_ranking_equipment_publish import candidate
        from tests.jjc_equipment_fixtures import TIMESTAMP

        doc = candidate(timestamp=TIMESTAMP)
        col = SimpleNamespace(find=lambda query: _AsyncCursor([doc]))
        db = SimpleNamespace(name="test_bson_reuse", jjc_ranking_stat_summaries=col)
        repo = JjcRankingStatsRepo(db=db, suppress_errors=False)

        with patch("src.storage.mongo_repos.jjc_ranking_stats_repo.BSON.encode", wraps=__import__("bson").BSON.encode) as spy:
            query = await repo._readable_snapshot_query(db)
        self.assertEqual(spy.call_count, 1)
        self.assertIn(TIMESTAMP, query["$or"][2]["timestamp"]["$in"])


class TestJjcSeasonsCacheService(unittest.IsolatedAsyncioTestCase):
    async def test_caches_within_ttl_returns_defensive_copy_and_expires(self):
        now = [100.0]
        calls = 0

        async def fetcher():
            nonlocal calls
            calls += 1
            return {
                "seasons": [{"name": f"season-{calls}", "latest_timestamp": 100 * calls}],
                "default_season": f"season-{calls}",
            }

        service = JjcSeasonsCacheService(ttl_seconds=30.0, monotonic=lambda: now[0])

        first = await service.get_seasons(fetcher, cache_key="prod")
        first["seasons"].append({"name": "mutated", "latest_timestamp": 1})
        second = await service.get_seasons(fetcher, cache_key="prod")

        self.assertEqual(calls, 1)
        self.assertEqual(second["default_season"], "season-1")
        self.assertEqual(len(second["seasons"]), 1)

        now[0] += 30.1
        third = await service.get_seasons(fetcher, cache_key="prod")
        self.assertEqual(calls, 2)
        self.assertEqual(third["default_season"], "season-2")

    async def test_global_invalidate_clears_all_keys_across_read_write_db_wrappers(self):
        calls = 0

        async def fetcher():
            nonlocal calls
            calls += 1
            return {
                "seasons": [{"name": f"season-{calls}", "latest_timestamp": 100 * calls}],
                "default_season": f"season-{calls}",
            }

        service = JjcSeasonsCacheService(ttl_seconds=30.0)
        await service.get_seasons(fetcher, cache_key="jx3bot")
        await service.get_seasons(fetcher, cache_key="default")
        self.assertEqual(calls, 2)

        service.invalidate()

        refreshed = await service.get_seasons(fetcher, cache_key="jx3bot")
        self.assertEqual(calls, 3)
        self.assertEqual(refreshed["default_season"], "season-3")

    async def test_inflight_read_does_not_write_stale_cache_after_invalidate(self):
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def fetcher():
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                await release.wait()
                return {"seasons": [{"name": "stale", "latest_timestamp": 100}], "default_season": "stale"}
            return {"seasons": [{"name": "fresh", "latest_timestamp": 200}], "default_season": "fresh"}

        service = JjcSeasonsCacheService(ttl_seconds=30.0)
        task = asyncio.create_task(service.get_seasons(fetcher, cache_key="prod"))
        await asyncio.wait_for(started.wait(), timeout=1.0)
        service.invalidate()
        release.set()

        first = await task
        self.assertEqual(first["default_season"], "stale")

        second = await service.get_seasons(fetcher, cache_key="prod")
        self.assertEqual(calls, 2)
        self.assertEqual(second["default_season"], "fresh")

    async def test_invalidate_detaches_old_inflight_so_new_reader_fetches_fresh(self):
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def fetcher():
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                await release.wait()
                return {"seasons": [{"name": "stale", "latest_timestamp": 100}], "default_season": "stale"}
            return {"seasons": [{"name": "fresh", "latest_timestamp": 200}], "default_season": "fresh"}

        service = JjcSeasonsCacheService(ttl_seconds=30.0)
        old_reader = asyncio.create_task(service.get_seasons(fetcher, cache_key="prod"))
        await asyncio.wait_for(started.wait(), timeout=1.0)
        service.invalidate()

        new_result = await service.get_seasons(fetcher, cache_key="prod")
        self.assertEqual(new_result["default_season"], "fresh")
        self.assertEqual(calls, 2)

        release.set()
        old_result = await old_reader
        self.assertEqual(old_result["default_season"], "stale")

    async def test_router_seasons_cache_key_does_not_trigger_lazy_equipment_db_proxy(self):
        from src.api.routers import jjc_ranking_stats as router_module

        class _EquipmentReadDatabase:
            def __getattr__(self, name):
                raise RuntimeError("lazy equipment db should not be touched for cache key")

        proxy_repo = JjcRankingStatsRepo(db=_EquipmentReadDatabase(), suppress_errors=False)
        self.assertEqual(router_module._seasons_cache_key(proxy_repo), "equipment_read")

        class _GenericLazyProxy:
            def __getattr__(self, name):
                raise RuntimeError("generic proxy should not be touched")

        generic_repo = JjcRankingStatsRepo(db=_GenericLazyProxy(), suppress_errors=False)
        key = router_module._seasons_cache_key(generic_repo)
        self.assertIn("_GenericLazyProxy:", key)

    async def test_singleflight_coalesces_concurrent_requests_and_stores_once(self):
        calls = 0

        async def fetcher():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.02)
            return {"seasons": [{"name": "苍生铸世", "latest_timestamp": 600}], "default_season": "苍生铸世"}

        service = JjcSeasonsCacheService(ttl_seconds=30.0)
        with patch.object(service, "_store_if_fresh", wraps=service._store_if_fresh) as store_spy:
            results = await asyncio.gather(*(service.get_seasons(fetcher, cache_key="prod") for _ in range(5)))

        self.assertEqual(calls, 1)
        self.assertEqual(store_spy.call_count, 1)
        for item in results:
            self.assertEqual(item["default_season"], "苍生铸世")

    async def test_empty_seasons_result_is_not_cached(self):
        calls = 0

        async def fetcher():
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"seasons": [], "default_season": None}
            return {"seasons": [{"name": "苍生铸世", "latest_timestamp": 700}], "default_season": "苍生铸世"}

        service = JjcSeasonsCacheService(ttl_seconds=30.0)
        first = await service.get_seasons(fetcher, cache_key="prod")
        second = await service.get_seasons(fetcher, cache_key="prod")
        self.assertEqual(first["seasons"], [])
        self.assertEqual(second["default_season"], "苍生铸世")
        self.assertEqual(calls, 2)

    async def test_concurrent_failure_propagates_to_all_waiters_and_is_not_cached(self):
        attempts = 0
        loop = asyncio.get_running_loop()
        unhandled = []
        prev_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, ctx: unhandled.append(ctx))
        self.addCleanup(loop.set_exception_handler, prev_handler)

        async def fetcher():
            nonlocal attempts
            attempts += 1
            await asyncio.sleep(0.02)
            if attempts == 1:
                raise EquipmentSnapshotError("read_failed")
            return {"seasons": [{"name": "苍生铸世", "latest_timestamp": 700}], "default_season": "苍生铸世"}

        service = JjcSeasonsCacheService(ttl_seconds=30.0)
        outcomes = await asyncio.gather(
            *(service.get_seasons(fetcher, cache_key="prod") for _ in range(4)),
            return_exceptions=True,
        )
        self.assertEqual(attempts, 1)
        for outcome in outcomes:
            self.assertIsInstance(outcome, EquipmentSnapshotError)
            self.assertEqual(outcome.code, "read_failed")

        recovered = await service.get_seasons(fetcher, cache_key="prod")
        self.assertEqual(attempts, 2)
        self.assertEqual(recovered["default_season"], "苍生铸世")
        await asyncio.sleep(0)
        self.assertEqual(unhandled, [])

    async def test_sole_waiter_cancellation_cancels_underlying_fetch(self):
        started = asyncio.Event()
        cancelled_inner = asyncio.Event()

        async def fetcher():
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled_inner.set()
                raise

        service = JjcSeasonsCacheService(ttl_seconds=30.0)
        task = asyncio.create_task(service.get_seasons(fetcher, cache_key="prod"))
        await asyncio.wait_for(started.wait(), timeout=1.0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(cancelled_inner.is_set())

    async def test_cancelling_one_waiter_preserves_other_waiters(self):
        started = asyncio.Event()

        async def fetcher():
            started.set()
            await asyncio.sleep(0.04)
            return {"seasons": [{"name": "苍生铸世", "latest_timestamp": 800}], "default_season": "苍生铸世"}

        service = JjcSeasonsCacheService(ttl_seconds=30.0)
        first = asyncio.create_task(service.get_seasons(fetcher, cache_key="prod"))
        second = asyncio.create_task(service.get_seasons(fetcher, cache_key="prod"))
        await asyncio.wait_for(started.wait(), timeout=1.0)
        first.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await first
        result = await second
        self.assertEqual(result["default_season"], "苍生铸世")


class TestSeasonsIndexesAndFrontendRetry(unittest.TestCase):
    def test_mongo_init_registers_season_and_schema_version_indexes(self):
        content = Path("src/infra/mongo.py").read_text(encoding="utf-8")
        self.assertIn('name="idx_schema_version_season_timestamp"', content)
        self.assertIn('[("schema_version", 1), ("current_season", 1), ("timestamp", -1)]', content)
        self.assertIn('name="idx_current_season_timestamp"', content)
        self.assertIn('[("current_season", 1), ("timestamp", -1)]', content)

    def test_frontend_retry_behaviors_and_request_id_guard(self):
        stats_html = Path("public/jjc-ranking-stats.html").read_text(encoding="utf-8")
        index_html = Path("public/index.html").read_text(encoding="utf-8")
        self.assertEqual(stats_html, index_html)
        self.assertIn("const SEASONS_RETRY_DELAYS_MS = [400, 1000];", stats_html)
        self.assertIn("let seasonsRequestId = 0;", stats_html)
        self.assertIn("function isRetryableSeasonsStatus(status)", stats_html)
        self.assertIn("async function fetchSeasonsWithRetry(requestId)", stats_html)

        node = shutil.which("node")
        if not node:
            self.skipTest("Node is required to execute frontend retry logic")

        snippet = stats_html.split("const SEASONS_RETRY_DELAYS_MS = [400, 1000];", 1)[1]
        snippet = "const SEASONS_RETRY_DELAYS_MS = [1, 1];" + snippet.split("function renderCachedTeamIcons(", 1)[0]
        script = f"""
const seasonsApiUrl = "/api/jjc/ranking-stats?action=seasons";
let availableSeasons = [];
let loadedSeason = null;
const appended = [];
const classes = new Set();
const listContainer = {{
    classList: {{
        remove(c) {{ classes.delete(c); }},
        add(c) {{ classes.add(c); }},
    }},
    innerHTML: "",
    textContent: "",
    appendChild(node) {{ appended.push(node); }},
}};
global.document = {{
    createElement(tag) {{
        return {{ tag, className: "", textContent: "", type: "", listeners: {{}}, addEventListener(ev, fn) {{ this.listeners[ev] = fn; }} }};
    }},
}};
function unwrapResponse(payload) {{
    if (payload.status_code !== 0) throw new Error(payload.status_msg || "业务失败");
    return payload.data;
}}
async function loadSeasonHistory(season) {{ loadedSeason = season; }}
{snippet}

async function run() {{
    // 1) 503 -> 503 -> 200 recovers on 3rd attempt
    let calls = 0;
    global.fetch = async () => {{
        calls += 1;
        if (calls < 3) return {{ ok: false, status: 503, json: async () => ({{}}) }};
        return {{ ok: true, status: 200, json: async () => ({{ status_code: 0, data: {{ seasons: [{{ name: "苍生铸世", latest_timestamp: 900 }}], default_season: "苍生铸世" }} }}) }};
    }};
    await loadDateList();
    const case1 = {{ calls, loadedSeason, hasError: classes.has("error") }};

    // 2) HTTP 400 does NOT retry
    calls = 0;
    appended.length = 0;
    global.fetch = async () => {{
        calls += 1;
        return {{ ok: false, status: 400, json: async () => ({{}}) }};
    }};
    await loadDateList();
    const case2 = {{ calls, hasError: classes.has("error"), hasRetryBtn: appended.some(n => n.className === "status-retry-btn") }};

    // 3) HTTP 200 business error does NOT retry
    calls = 0;
    global.fetch = async () => {{
        calls += 1;
        return {{ ok: true, status: 200, json: async () => ({{ status_code: 1, status_msg: "invalid_action" }}) }};
    }};
    await loadDateList();
    const case3 = {{ calls, hasError: classes.has("error") }};

    // 4) Exhausted 503 renders retry button and clicking it retries
    calls = 0;
    appended.length = 0;
    global.fetch = async () => {{
        calls += 1;
        return {{ ok: false, status: 503, json: async () => ({{}}) }};
    }};
    await loadDateList();
    const case4 = {{ calls, hasError: classes.has("error"), retryText: (appended.find(n => n.className === "status-retry-btn") || {{}}).textContent }};

    // 5) Concurrent loadDateList() discards stale first request via seasonsRequestId
    loadedSeason = null;
    let resolveFirst;
    let seq = 0;
    global.fetch = async () => {{
        seq += 1;
        if (seq === 1) {{
            await new Promise(r => {{ resolveFirst = r; }});
            return {{ ok: true, status: 200, json: async () => ({{ status_code: 0, data: {{ seasons: [{{ name: "stale-season", latest_timestamp: 1 }}], default_season: "stale-season" }} }}) }};
        }}
        return {{ ok: true, status: 200, json: async () => ({{ status_code: 0, data: {{ seasons: [{{ name: "latest-season", latest_timestamp: 2 }}], default_season: "latest-season" }} }}) }};
    }};
    const p1 = loadDateList();
    const p2 = loadDateList();
    await p2;
    resolveFirst();
    await p1;
    const case5 = {{ loadedSeason }};

    console.log(JSON.stringify({{ case1, case2, case3, case4, case5 }}));
}}
run().catch(err => {{ console.error(err); process.exit(1); }});
"""
        proc = subprocess.run([node, "-e", script], check=True, text=True, capture_output=True)
        out = json.loads(proc.stdout)
        self.assertEqual(out["case1"], {"calls": 3, "loadedSeason": "苍生铸世", "hasError": False})
        self.assertEqual(out["case2"], {"calls": 1, "hasError": True, "hasRetryBtn": True})
        self.assertEqual(out["case3"], {"calls": 1, "hasError": True})
        self.assertEqual(out["case4"], {"calls": 3, "hasError": True, "retryText": "重试"})
        self.assertEqual(out["case5"], {"loadedSeason": "latest-season"})


if __name__ == "__main__":
    unittest.main()

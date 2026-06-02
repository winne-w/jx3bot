import asyncio
import time
import unittest
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock
from bson import ObjectId

from src.services.jx3.jjc_ranking_inspect import JjcRankingInspectService
from src.services.jx3.jjc_ranking import JjcRankingService
from src.services.jx3.match_detail import (
    MatchDetailBasicInfo,
    MatchDetailData,
    MatchDetailPlayerInfo,
    MatchDetailResponse,
    MatchDetailTeamInfo,
)
from src.services.jx3.match_detail_identity_projection import MatchDetailIdentityProjectionService
from src.storage.mongo_repos.jjc_inspect_repo import JjcInspectRepo


class FakeMatchHistoryClient:
    def __init__(self, history: List[Dict[str, Any]]) -> None:
        self.history = history
        self.calls: List[Dict[str, Any]] = []

    def get_mine_match_history(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(kwargs)
        return {"code": 0, "msg": "success", "data": self.history}


class FakeMatchReplayClient:
    def __init__(self, replay: Dict[str, Any]) -> None:
        self.replay = replay
        self.calls: List[int] = []

    def get_match_replay(self, *, match_id: int) -> Dict[str, Any]:
        self.calls.append(match_id)
        return self.replay


class FakeMatchDetailClient:
    def __init__(self, response: MatchDetailResponse) -> None:
        self.response = response
        self.calls: List[int] = []

    def get_match_detail_obj(self, *, match_id: int) -> MatchDetailResponse:
        self.calls.append(match_id)
        return self.response


class FakeProjectionService:
    def __init__(self, error: Optional[Exception] = None) -> None:
        self.error = error
        self.calls: List[Dict[str, Any]] = []

    async def project_payload(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {"projected": 1}


class DirectJjcRankingInspectService(JjcRankingInspectService):
    async def _run_serialized_tuilan_query(
        self,
        endpoint_key: str,
        label: str,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        return func(*args, **kwargs)


def make_service(
    *,
    cache_repo: Any = None,
    service_cls: Any = JjcRankingInspectService,
) -> JjcRankingInspectService:
    return service_cls(
        ranking_service=MagicMock(),
        kungfu_cache_repo=MagicMock(),
        match_history_client=MagicMock(),
        match_detail_client=MagicMock(),
        cache_repo=cache_repo or FakeJjcInspectRepo(),
        tuilan_request=MagicMock(),
        role_indicator_fetcher=MagicMock(),
        kungfu_pinyin_to_chinese={},
    )


class FakeJjcInspectRepo:
    """Fake repo that returns preconfigured cached_detail_summaries without Mongo."""

    def __init__(self, summaries=None):
        self.summaries = summaries or {}
        self.load_role_recent_result: Any = None
        self.load_role_recent_calls: list = []
        self.saved_role_recent: list = []
        self.role_indicator_cache: Dict[str, Dict[str, Any]] = {}
        self.saved_role_indicator: list = []
        self.loaded_role_indicator_ttls: list = []
        self.saved_match_detail: list = []
        self.synced_matches_result: Dict[str, Any] = {
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": 20,
            "has_more": False,
        }
        self.synced_matches_calls: list = []

    async def load_role_recent(self, server, name, *, ttl_seconds):
        self.load_role_recent_calls.append((server, name, ttl_seconds))
        return self.load_role_recent_result

    async def save_role_recent(self, server, name, payload):
        self.saved_role_recent.append((server, name, payload))

    async def load_match_detail(self, match_id):
        return None

    async def save_match_detail(self, match_id, payload):
        self.saved_match_detail.append((match_id, payload))

    async def batch_load_cached_detail_summaries(self, match_ids):
        result = {}
        for mid in match_ids:
            mid_int = int(mid)
            if mid_int in self.summaries:
                result[mid_int] = self.summaries[mid_int]
        return result

    async def save_role_indicator(self, cache_key, payload):
        self.saved_role_indicator.append((cache_key, payload))
        self.role_indicator_cache[cache_key] = payload

    async def load_role_indicator(self, cache_key, *, ttl_seconds):
        self.loaded_role_indicator_ttls.append(ttl_seconds)
        return self.role_indicator_cache.get(cache_key)

    async def list_saved_local_3v3_matches_for_identity(self, **kwargs):
        self.synced_matches_calls.append(kwargs)
        if isinstance(self.synced_matches_result, Exception):
            raise self.synced_matches_result
        return self.synced_matches_result


class FakeRoleIdentityRepo:
    def __init__(
        self,
        identity: Optional[Dict[str, Any]],
        candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.identity = identity
        self.candidates = candidates or []
        self.calls: List[Dict[str, Any]] = []
        self.candidate_calls: List[Dict[str, Any]] = []

    async def find_best_by_name_with_id(self, server: str, name: str) -> Optional[Dict[str, Any]]:
        self.calls.append({"server": server, "name": name})
        return self.identity

    async def find_synced_match_page_candidates(
        self,
        server: str,
        name: str,
        *,
        limit: int = 8,
    ) -> List[Dict[str, Any]]:
        self.candidate_calls.append({"server": server, "name": name, "limit": limit})
        return self.candidates[:limit]


class FakeSyncRepo:
    def __init__(
        self,
        sync_state: Optional[Dict[str, Any]] = None,
        enqueue_result: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.sync_state = sync_state
        self.enqueue_result = enqueue_result
        self.state_calls: List[Any] = []
        self.position_calls: List[Dict[str, Any]] = []
        self.enqueue_calls: List[Dict[str, Any]] = []

    async def get_queue_state_by_identity_id(self, identity_id: Any) -> Optional[Dict[str, Any]]:
        self.state_calls.append(identity_id)
        return self.sync_state

    async def get_queue_position(self, queue_doc: Dict[str, Any]) -> Optional[int]:
        self.position_calls.append(queue_doc)
        return queue_doc.get("queue_position")

    async def enqueue_existing_identity(self, identity: Dict[str, Any], **kwargs: Any) -> Optional[Dict[str, Any]]:
        self.enqueue_calls.append({"identity": identity, "kwargs": kwargs})
        return self.enqueue_result


class FakeChainCursor:
    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self.docs = docs

    def sort(self, *args: Any, **kwargs: Any) -> "FakeChainCursor":
        return self

    def skip(self, *args: Any, **kwargs: Any) -> "FakeChainCursor":
        return self

    def limit(self, *args: Any, **kwargs: Any) -> "FakeChainCursor":
        return self

    async def to_list(self, length: Any = None) -> List[Dict[str, Any]]:
        return list(self.docs)


class FakeFindCollection:
    def __init__(self, docs: List[Dict[str, Any]]) -> None:
        self.docs = docs
        self.find_calls: List[Dict[str, Any]] = []
        self.count_calls: List[Dict[str, Any]] = []

    async def count_documents(self, query: Dict[str, Any]) -> int:
        self.count_calls.append(query)
        return len(self.docs)

    def find(self, query: Dict[str, Any]) -> FakeChainCursor:
        self.find_calls.append(query)
        return FakeChainCursor(self.docs)


class FakeParticipantRepo:
    def __init__(self, result: Optional[Dict[str, Any]] = None, error: Optional[Exception] = None) -> None:
        self.result = result or {
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": 20,
            "has_more": False,
        }
        self.error = error
        self.calls: List[Dict[str, Any]] = []

    async def list_local_3v3_matches_by_global_id(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


class FakeWarmupInspectRepo:
    def __init__(self) -> None:
        self.saved_role_indicator: list = []
        self.saved_match_detail: list = []
        self.saved_role_recent: list = []

    async def save_role_indicator(self, cache_key, payload):
        self.saved_role_indicator.append((cache_key, payload))

    async def save_role_recent(self, server, name, payload):
        self.saved_role_recent.append((server, name, payload))

    async def save_match_detail(self, match_id, payload):
        self.saved_match_detail.append((match_id, payload))


class WarmupJjcRankingService(JjcRankingService):
    def __init__(self, inspect_repo: FakeWarmupInspectRepo, projection_service: Any = None) -> None:
        super().__init__(
            token="",
            ticket="",
            jjc_query_url="",
            arena_time_tag_url="",
            arena_ranking_url="",
            match_detail_url="",
            jjc_ranking_cache_duration=1,
            kungfu_cache_duration=1,
            current_season="",
            current_season_start="",
            kungfu_healer_list=[],
            kungfu_dps_list=[],
            kungfu_pinyin_to_chinese={"huajian": "花间游"},
            tuilan_request=MagicMock(),
            defget_get=MagicMock(),
            match_detail_projection_service=projection_service,
        )
        object.__setattr__(self, "inspect_repo", inspect_repo)

    def _inspect_cache(self):
        return self.inspect_repo


def make_match_detail_response() -> MatchDetailResponse:
    player = MatchDetailPlayerInfo(
        role_name="示例角色",
        global_role_id="SK01-1",
        role_id="100",
        person_id="person-1",
        person_name="",
        person_avatar="",
        zone="电信区",
        server="梦江南",
        total_count=None,
        win_count=None,
        win_rate=None,
        mvp_count=None,
        mmr=None,
        score=None,
        total_score=None,
        ranking="",
        kungfu="huajian",
        kungfu_id=None,
        mvp=False,
        equip_score=None,
        equip_strength_score=None,
        stone_score=None,
        max_hp=None,
        metrics=[],
        armors=[],
        talents=[],
        body_qualities=[],
        odd=False,
        fight_seconds=None,
    )
    return MatchDetailResponse(
        code=0,
        msg="success",
        data=MatchDetailData(
            match_id=12345,
            match_time=1778000000,
            query_backend=False,
            basic_info=MatchDetailBasicInfo(
                video_url="",
                screen_shot_url="",
                start_time=1778000000,
                duration=180,
                map="",
                match_type=3,
                grade=12,
            ),
            team1=MatchDetailTeamInfo(won=True, team_name="", players_info=[player]),
            team2=MatchDetailTeamInfo(won=False, team_name="", players_info=[]),
            videos=[],
            hidden=False,
        ),
    )


class TestTuilanEndpointLocks(unittest.IsolatedAsyncioTestCase):
    async def test_same_endpoint_uses_same_lock(self):
        service = make_service()

        lock1 = service._get_tuilan_query_lock("match_detail")
        lock2 = service._get_tuilan_query_lock("match_detail")

        self.assertIs(lock1, lock2)

    async def test_different_endpoint_uses_different_locks(self):
        service = make_service()

        match_detail_lock = service._get_tuilan_query_lock("match_detail")
        role_indicator_lock = service._get_tuilan_query_lock("role_indicator")

        self.assertIsNot(match_detail_lock, role_indicator_lock)
        async with match_detail_lock:
            self.assertTrue(match_detail_lock.locked())
            self.assertFalse(role_indicator_lock.locked())

    async def test_same_endpoint_serializes_concurrent_requests(self):
        service = make_service(service_cls=JjcRankingInspectService)
        running = 0
        max_concurrent = 0

        def slow_func() -> str:
            nonlocal running, max_concurrent
            running += 1
            max_concurrent = max(max_concurrent, running)
            time.sleep(0.15)
            running -= 1
            return "ok"

        t1 = asyncio.create_task(
            service._run_serialized_tuilan_query("match_detail", "t1", slow_func)
        )
        await asyncio.sleep(0.03)
        t2 = asyncio.create_task(
            service._run_serialized_tuilan_query("match_detail", "t2", slow_func)
        )
        await asyncio.sleep(0.03)

        self.assertFalse(t2.done(), "t2 应等待锁，尚未完成")
        self.assertEqual(max_concurrent, 1, "同一端点不应并发执行")

        await asyncio.gather(t1, t2)
        self.assertEqual(max_concurrent, 1)

    async def test_different_endpoints_run_concurrently(self):
        service = make_service(service_cls=JjcRankingInspectService)
        running = 0
        max_concurrent = 0

        def slow_func() -> str:
            nonlocal running, max_concurrent
            running += 1
            max_concurrent = max(max_concurrent, running)
            time.sleep(0.15)
            running -= 1
            return "ok"

        t1 = asyncio.create_task(
            service._run_serialized_tuilan_query("match_detail", "t1", slow_func)
        )
        await asyncio.sleep(0.03)
        t2 = asyncio.create_task(
            service._run_serialized_tuilan_query("role_indicator", "t2", slow_func)
        )
        await asyncio.sleep(0.03)

        self.assertEqual(max_concurrent, 2, "不同端点应可并发执行")

        await asyncio.gather(t1, t2)


class TestRankingWarmupInspectCache(unittest.IsolatedAsyncioTestCase):
    async def test_warmup_writes_indicator_and_match_detail_cache(self):
        inspect_repo = FakeWarmupInspectRepo()
        service = WarmupJjcRankingService(inspect_repo)

        await service._warmup_inspect_cache_from_kungfu_detail(
            server="梦江南",
            name="示例角色",
            kungfu_detail={
                "_cache_warmup": {
                    "role_indicator": {
                        "game_role_id": "100",
                        "global_role_id": "global-100",
                        "zone": "电信区",
                        "raw": {
                            "code": 0,
                            "msg": "success",
                            "data": {
                                "role_info": {"global_role_id": "global-100"},
                                "indicator": [
                                    {
                                        "type": "3c",
                                        "metrics": [{"pvp_type": 3, "win_count": 6, "total_count": 10}],
                                        "performance": {"mmr": 2500, "grade": 14},
                                    }
                                ],
                            },
                        },
                    },
                    "match_detail": {
                        "match_id": 12345,
                        "raw": {
                            "code": 0,
                            "msg": "success",
                            "data": {
                                "match_id": 12345,
                                "team1": {
                                    "players_info": [
                                        {"role_name": "示例角色", "server": "梦江南", "kungfu": "huajian"}
                                    ]
                                },
                                "team2": {"players_info": []},
                            },
                        },
                    },
                }
            },
        )

        self.assertEqual(len(inspect_repo.saved_role_indicator), 1)
        cache_key, indicator_payload = inspect_repo.saved_role_indicator[0]
        self.assertEqual(cache_key, "global:global-100")
        self.assertEqual(indicator_payload["indicator"]["score"], 2500)

        self.assertEqual(len(inspect_repo.saved_match_detail), 1)
        match_id, detail_payload = inspect_repo.saved_match_detail[0]
        self.assertEqual(match_id, 12345)
        detail = detail_payload["data"]["detail"]
        self.assertEqual(detail["team1"]["players_info"][0]["kungfu"], "花间游")

    async def test_warmup_projects_match_detail_after_save(self):
        inspect_repo = FakeWarmupInspectRepo()
        projection_service = FakeProjectionService()
        service = WarmupJjcRankingService(inspect_repo, projection_service=projection_service)

        await service._warmup_inspect_cache_from_kungfu_detail(
            server="梦江南",
            name="示例角色",
            kungfu_detail={
                "_cache_warmup": {
                    "match_detail": {
                        "match_id": 12345,
                        "raw": {
                            "code": 0,
                            "msg": "success",
                            "data": {
                                "match_id": 12345,
                                "match_time": 1778000000,
                                "team1": {
                                    "players_info": [
                                        {"role_name": "示例角色", "server": "梦江南", "kungfu": "huajian"}
                                    ]
                                },
                                "team2": {"players_info": []},
                            },
                        },
                    },
                }
            },
        )

        self.assertEqual(len(inspect_repo.saved_match_detail), 1)
        self.assertEqual(len(projection_service.calls), 1)
        self.assertEqual(projection_service.calls[0]["match_id"], 12345)
        self.assertEqual(projection_service.calls[0]["source"], "ranking_warmup")


class TestMatchDetailIdentityProjection(unittest.IsolatedAsyncioTestCase):
    async def test_projects_players_to_identity_and_queue(self):
        identity_repo = MagicMock()
        sync_repo = MagicMock()
        identity_doc = {
            "_id": "identity-1",
            "identity_key": "global_id:987",
            "server": "梦江南",
            "name": "示例角色",
            "global_id": "987",
            "game_role_id": "100",
        }
        identity_repo.upsert_from_match_detail_with_id = AsyncMock(return_value=identity_doc)
        sync_repo.upsert_identity_queue_candidate = AsyncMock()
        service = MatchDetailIdentityProjectionService(
            identity_repo=identity_repo,
            sync_repo=sync_repo,
            kungfu_pinyin_to_chinese={"huajian": "花间游"},
        )

        result = await service.project_payload(
            match_id=12345,
            payload={
                "match_id": 12345,
                "match_time": 1778000000,
                "detail": {
                    "team1": {
                        "players_info": [
                            {
                                "role_name": "示例角色·梦江南",
                                "server": "梦江南",
                                "role_id": "100",
                                "global_id": "987",
                                "kungfu": "huajian",
                            }
                        ]
                    },
                    "team2": {"players_info": []},
                },
            },
            source="test",
            priority=2,
        )

        self.assertEqual(result["projected"], 1)
        identity_repo.upsert_from_match_detail_with_id.assert_awaited_once()
        kwargs = identity_repo.upsert_from_match_detail_with_id.await_args.kwargs
        self.assertEqual(kwargs["name"], "示例角色")
        self.assertEqual(kwargs["game_role_id"], "100")
        self.assertEqual(kwargs["global_id"], "987")
        self.assertEqual(kwargs["observed_match_time"], 1778000000)
        sync_repo.upsert_identity_queue_candidate.assert_awaited_once()
        queue_kwargs = sync_repo.upsert_identity_queue_candidate.await_args.kwargs
        self.assertEqual(queue_kwargs["identity_id"], "identity-1")
        self.assertEqual(queue_kwargs["identity_key"], "global_id:987")
        self.assertEqual(queue_kwargs["server"], "梦江南")
        self.assertEqual(queue_kwargs["name"], "示例角色")
        self.assertEqual(queue_kwargs["global_id"], "987")
        self.assertEqual(queue_kwargs["game_role_id"], "100")
        self.assertEqual(queue_kwargs["source"], "test")
        self.assertEqual(queue_kwargs["priority"], 2)

    async def test_tolerates_missing_detail_and_missing_queue_method(self):
        identity_repo = MagicMock()
        sync_repo = MagicMock(spec=[])
        service = MatchDetailIdentityProjectionService(identity_repo=identity_repo, sync_repo=sync_repo)

        missing = await service.project_payload(match_id=1, payload=None)
        empty = await service.project_payload(
            match_id=1,
            payload={"detail": {"team1": {"players_info": []}, "team2": {"players_info": []}}},
        )

        self.assertTrue(missing["skipped"])
        self.assertTrue(empty["skipped"])
        identity_repo.upsert_from_match_detail_with_id.assert_not_called()

    async def test_does_not_require_queue_method(self):
        identity_repo = MagicMock()
        identity_repo.upsert_from_match_detail_with_id = AsyncMock(return_value={"_id": "identity-1"})
        sync_repo = MagicMock(spec=[])
        service = MatchDetailIdentityProjectionService(identity_repo=identity_repo, sync_repo=sync_repo)

        result = await service.project_payload(
            match_id=1,
            payload={
                "detail": {
                    "team1": {"players_info": [{"role_name": "示例角色", "server": "梦江南"}]},
                    "team2": {"players_info": []},
                }
            },
        )

        self.assertEqual(result["projected"], 1)
        self.assertEqual(result["queued"], 0)


class TestHydrateRecentMatchesWithCachedDetails(unittest.IsolatedAsyncioTestCase):
    async def test_adds_summary_when_cached_detail_exists(self):
        cache_repo = FakeJjcInspectRepo(
            summaries={
                1001: {
                    "match_id": 1001,
                    "cached_at": 1778000000,
                    "team1": {"won": True, "players": [{"kungfu_id": 10021, "kungfu": "花间游", "role_name": "角色A", "server": "梦江南"}]},
                    "team2": {"won": False, "players": [{"kungfu_id": 10081, "kungfu": "冰心诀", "role_name": "角色B"}]},
                }
            }
        )
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
        )
        recent_matches = [
            {"match_id": 1001, "won": True},
            {"match_id": 1002, "won": False},
        ]
        await service._hydrate_recent_matches_with_cached_details(recent_matches)
        self.assertIn("cached_detail_summary", recent_matches[0])
        self.assertEqual(recent_matches[0]["cached_detail_summary"]["match_id"], 1001)
        self.assertNotIn("cached_detail_summary", recent_matches[1])

    async def test_removes_stale_summary_when_not_cached(self):
        cache_repo = FakeJjcInspectRepo(summaries={})
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
        )
        recent_matches = [
            {"match_id": 1001, "won": True, "cached_detail_summary": {"stale": True}},
        ]
        await service._hydrate_recent_matches_with_cached_details(recent_matches)
        self.assertNotIn("cached_detail_summary", recent_matches[0])

    async def test_empty_matches_is_noop(self):
        cache_repo = FakeJjcInspectRepo(summaries={1001: {"match_id": 1001, "cached_at": 1, "team1": {"won": True, "players": []}, "team2": {"won": False, "players": []}}})
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
        )
        await service._hydrate_recent_matches_with_cached_details([])

    async def test_skips_rows_without_match_id(self):
        cache_repo = FakeJjcInspectRepo(summaries={})
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
        )
        recent_matches = [
            {"won": True},  # no match_id
            {"match_id": None, "won": False},
        ]
        await service._hydrate_recent_matches_with_cached_details(recent_matches)
        self.assertNotIn("cached_detail_summary", recent_matches[0])
        self.assertNotIn("cached_detail_summary", recent_matches[1])

    async def test_coerces_string_match_id(self):
        cache_repo = FakeJjcInspectRepo(
            summaries={
                1001: {
                    "match_id": 1001,
                    "cached_at": 1778000000,
                    "team1": {"won": True, "players": [{"kungfu_id": 10021, "kungfu": "花间游"}]},
                    "team2": {"won": False, "players": []},
                }
            }
        )
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
        )
        recent_matches = [{"match_id": "1001", "won": True}]
        await service._hydrate_recent_matches_with_cached_details(recent_matches)
        self.assertEqual(recent_matches[0]["cached_detail_summary"]["match_id"], 1001)


class TestJjcRankingInspectRoleRecent(unittest.IsolatedAsyncioTestCase):
    async def test_role_recent_default_window_returns_20_3v3_matches(self) -> None:
        history = [
            {
                "pvpType": 3,
                "match_id": 1000 + index,
                "won": index % 2 == 0,
                "kungfu": "huajian",
                "avgGrade": 12,
                "totalMmr": 1800 + index,
                "mmr": 10,
                "mvp": False,
                "match_time": 1778000000 + index,
                "duration": 180,
            }
            for index in range(40)
        ]
        history.extend(
            {
                "pvpType": 2,
                "match_id": 2000 + index,
                "won": True,
                "match_time": 1779000000 + index,
            }
            for index in range(5)
        )
        match_history_client = FakeMatchHistoryClient(history)
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=match_history_client,
            match_detail_client=MagicMock(),
            cache_repo=MagicMock(),
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={"huajian": "花间游"},
        )

        payload = await service._build_role_recent_payload(
            server="梦江南",
            name="示例角色",
            identity={"global_role_id": "global-1", "source": "test", "identity_key": "global:global-1"},
        )

        self.assertEqual(match_history_client.calls[0]["size"], 20)
        self.assertEqual(len(payload["recent_matches"]), 20)
        self.assertEqual(payload["recent_matches"][0]["match_id"], 1039)
        self.assertEqual(payload["recent_matches"][0]["kungfu"], "花间游")
        self.assertTrue(payload["pagination"]["has_more"])

    async def test_match_detail_projection_error_is_nonblocking_after_save(self) -> None:
        cache_repo = FakeJjcInspectRepo()
        projection_service = FakeProjectionService(error=RuntimeError("projection failed"))
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=FakeMatchDetailClient(make_match_detail_response()),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={"huajian": "花间游"},
            match_detail_projection_service=projection_service,
        )

        result = await service.get_match_detail(match_id=12345)

        self.assertFalse(result.get("error", False))
        self.assertTrue(result["projection_error"])
        self.assertEqual(result["projection_message"], "projection failed")
        self.assertEqual(len(cache_repo.saved_match_detail), 1)
        self.assertEqual(len(projection_service.calls), 1)
        saved_player = cache_repo.saved_match_detail[0][1]["data"]["detail"]["team1"]["players_info"][0]
        self.assertEqual(saved_player["kungfu"], "花间游")

    async def test_role_recent_resolves_replay_global_id_into_identity_hints(self) -> None:
        match_history_client = FakeMatchHistoryClient(
            [
                {
                    "pvpType": 3,
                    "match_id": 1001,
                    "won": True,
                    "kungfu": "huajian",
                    "avgGrade": 12,
                    "match_time": 1778000000,
                }
            ]
        )
        replay_client = FakeMatchReplayClient(
            {
                "code": 0,
                "msg": "success",
                "data": {
                    "players": [
                        {
                            "role_id": "30284767",
                            "role_name": "示例角色·梦江南",
                            "global_role_id": "987654321",
                        }
                    ]
                },
            }
        )
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=match_history_client,
            match_detail_client=MagicMock(),
            cache_repo=MagicMock(),
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={"huajian": "花间游"},
            match_replay_client=replay_client,
        )

        payload = await service._build_role_recent_payload(
            server="梦江南",
            name="示例角色",
            identity={
                "global_role_id": "SK01-a",
                "role_id": "30284767",
                "source": "test",
                "identity_key": "global:SK01-a",
            },
        )

        self.assertEqual(replay_client.calls, [1001])
        self.assertEqual(payload["identity"]["global_id"], "987654321")
        self.assertEqual(payload["identity"]["identity_hints"]["global_id"], "987654321")
        self.assertEqual(payload["identity"]["global_role_id"], "SK01-a")

    async def test_role_recent_cache_hit_hydrates_cached_details(self) -> None:
        cache_repo = FakeJjcInspectRepo(
            summaries={
                1001: {
                    "match_id": 1001,
                    "cached_at": 1778000000,
                    "team1": {"won": True, "players": [{"kungfu_id": 10021, "kungfu": "花间游"}]},
                    "team2": {"won": False, "players": [{"kungfu_id": 10081, "kungfu": "冰心诀"}]},
                }
            }
        )
        cache_repo.load_role_recent_result = {
            "cached_at": 1778000000,
            "data": {
                "recent_matches": [
                    {"match_id": 1001, "won": True, "kungfu": "花间游"},
                    {"match_id": 1002, "won": False, "kungfu": "冰心诀"},
                ],
            },
        }
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
        )
        result = await service.get_role_recent(server="梦江南", name="示例角色")
        recent_matches = result.get("recent_matches", [])
        self.assertEqual(len(recent_matches), 2)
        self.assertIn("cached_detail_summary", recent_matches[0])
        self.assertEqual(recent_matches[0]["cached_detail_summary"]["match_id"], 1001)
        self.assertNotIn("cached_detail_summary", recent_matches[1])
        self.assertTrue(result["cache"]["hit"])

    async def test_cached_match_detail_is_enriched_with_replay_global_id(self) -> None:
        cache_repo = FakeJjcInspectRepo()
        cache_repo.load_match_detail = AsyncMock(
            return_value={
                "cached_at": 1778000000,
                "data": {
                    "match_id": 1001,
                    "detail": {
                        "team1": {
                            "players_info": [
                                {"role_name": "示例角色", "server": "梦江南", "role_id": "30284767"}
                            ]
                        },
                        "team2": {"players_info": []},
                    },
                },
            }
        )
        replay_client = FakeMatchReplayClient(
            {
                "code": 0,
                "msg": "success",
                "data": {
                    "players": [
                        {
                            "role_id": "30284767",
                            "role_name": "示例角色·梦江南",
                            "global_role_id": "987654321",
                        }
                    ]
                },
            }
        )
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
            match_replay_client=replay_client,
        )

        result = await service.get_match_detail(match_id=1001)

        player = result["detail"]["team1"]["players_info"][0]
        self.assertEqual(player["global_id"], "987654321")
        self.assertNotEqual(player.get("global_role_id"), "987654321")
        self.assertTrue(result["cache"]["hit"])
        self.assertEqual(len(cache_repo.saved_match_detail), 1)
        self.assertEqual(cache_repo.saved_match_detail[0][0], 1001)
        saved_player = cache_repo.saved_match_detail[0][1]["data"]["detail"]["team1"]["players_info"][0]
        self.assertEqual(saved_player["global_id"], "987654321")
        self.assertEqual(cache_repo.saved_match_detail[0][1]["data"]["replay"]["data"]["players"][0]["global_role_id"], "987654321")

    async def test_cached_match_detail_uses_saved_replay_without_requesting_replay_api(self) -> None:
        cache_repo = FakeJjcInspectRepo()
        cache_repo.load_match_detail = AsyncMock(
            return_value={
                "cached_at": 1778000000,
                "data": {
                    "match_id": 1001,
                    "detail": {
                        "team1": {
                            "players_info": [
                                {"role_name": "示例角色", "server": "梦江南", "role_id": "30284767"}
                            ]
                        },
                        "team2": {"players_info": []},
                    },
                    "replay": {
                        "code": 0,
                        "msg": "success",
                        "data": {
                            "players": [
                                {
                                    "role_id": "30284767",
                                    "role_name": "示例角色·梦江南",
                                    "global_role_id": "987654321",
                                }
                            ]
                        },
                    },
                },
            }
        )
        replay_client = FakeMatchReplayClient({"error": "should_not_call"})
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
            match_replay_client=replay_client,
        )

        result = await service.get_match_detail(match_id=1001)

        player = result["detail"]["team1"]["players_info"][0]
        self.assertEqual(player["global_id"], "987654321")
        self.assertEqual(replay_client.calls, [])
        self.assertEqual(len(cache_repo.saved_match_detail), 1)
        saved_player = cache_repo.saved_match_detail[0][1]["data"]["detail"]["team1"]["players_info"][0]
        self.assertEqual(saved_player["global_id"], "987654321")

    async def test_role_recent_force_refresh_bypasses_cached_first_page(self) -> None:
        cache_repo = FakeJjcInspectRepo()
        cache_repo.load_role_recent_result = {
            "cached_at": 1778000000,
            "data": {
                "recent_matches": [
                    {"match_id": 1001, "won": True, "kungfu": "花间游"},
                ],
            },
        }
        match_history_client = FakeMatchHistoryClient(
            [
                {
                    "pvpType": 3,
                    "match_id": 2001,
                    "won": False,
                    "kungfu": "huajian",
                    "avgGrade": 12,
                    "match_time": 1779000000,
                }
            ]
        )
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=match_history_client,
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={"huajian": "花间游"},
        )
        result = await service.get_role_recent(
            server="梦江南",
            name="示例角色",
            identity_hints={"global_role_id": "global-1"},
            force_refresh=True,
        )
        self.assertEqual(cache_repo.load_role_recent_calls, [])
        self.assertEqual(result["recent_matches"][0]["match_id"], 2001)
        self.assertFalse(result["cache"]["hit"])
        self.assertTrue(result["cache"]["force_refresh"])
        self.assertEqual(len(cache_repo.saved_role_recent), 1)

    async def test_role_recent_cache_hit_removes_stale_cached_detail_summary(self) -> None:
        cache_repo = FakeJjcInspectRepo(summaries={})
        cache_repo.load_role_recent_result = {
            "cached_at": 1778000000,
            "data": {
                "recent_matches": [
                    {"match_id": 1001, "won": True, "cached_detail_summary": {"stale": True}},
                ],
            },
        }
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
        )
        result = await service.get_role_recent(server="梦江南", name="示例角色")
        recent_matches = result.get("recent_matches", [])
        self.assertNotIn("cached_detail_summary", recent_matches[0])
        self.assertTrue(result["cache"]["hit"])

    async def test_role_recent_fresh_response_does_not_save_detail_summary(self) -> None:
        cache_repo = FakeJjcInspectRepo(
            summaries={
                1001: {
                    "match_id": 1001,
                    "cached_at": 1778000000,
                    "team1": {"won": True, "players": [{"kungfu_id": 10021, "kungfu": "花间游"}]},
                    "team2": {"won": False, "players": [{"kungfu_id": 10081, "kungfu": "冰心诀"}]},
                }
            }
        )
        match_history_client = FakeMatchHistoryClient(
            [
                {
                    "pvpType": 3,
                    "match_id": 1001,
                    "won": True,
                    "kungfu": "huajian",
                    "avgGrade": 12,
                    "match_time": 1778000000,
                }
            ]
        )
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=match_history_client,
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={"huajian": "花间游"},
        )
        result = await service.get_role_recent(
            server="梦江南",
            name="示例角色",
            identity_hints={"global_role_id": "global-1"},
        )
        self.assertIn("cached_detail_summary", result["recent_matches"][0])
        saved_data = cache_repo.saved_role_recent[0][2]["data"]
        self.assertNotIn("cached_detail_summary", saved_data["recent_matches"][0])

    async def test_role_recent_late_hydration_when_detail_cached_after_initial_request(self) -> None:
        cache_repo = FakeJjcInspectRepo(summaries={})
        cache_repo.load_role_recent_result = {
            "cached_at": 1778000000,
            "data": {
                "recent_matches": [
                    {"match_id": 1001, "won": True, "kungfu": "花间游"},
                    {"match_id": 1002, "won": False, "kungfu": "冰心诀"},
                ],
            },
        }
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
        )
        result1 = await service.get_role_recent(server="梦江南", name="示例角色")
        recent1 = result1["recent_matches"]
        self.assertNotIn("cached_detail_summary", recent1[0])
        self.assertNotIn("cached_detail_summary", recent1[1])

        cache_repo.summaries[1001] = {
            "match_id": 1001,
            "cached_at": 1779000000,
            "team1": {"won": True, "players": [{"kungfu_id": 10021, "kungfu": "花间游", "role_name": "角色A"}]},
            "team2": {"won": False, "players": [{"kungfu_id": 10081, "kungfu": "冰心诀", "role_name": "角色B"}]},
        }

        result2 = await service.get_role_recent(server="梦江南", name="示例角色")
        recent2 = result2["recent_matches"]
        self.assertIn("cached_detail_summary", recent2[0])
        self.assertEqual(recent2[0]["cached_detail_summary"]["match_id"], 1001)
        self.assertNotIn("cached_detail_summary", recent2[1])

    async def test_role_indicator_parses_nested_metrics_and_caches(self) -> None:
        cache_repo = FakeJjcInspectRepo()
        fetch_calls: List[Dict[str, Any]] = []
        kungfu_cache_repo = MagicMock()
        kungfu_cache_repo.upsert_role_identity_from_indicator = AsyncMock()

        def fake_fetch(role_id: str, zone: str, server: str, **kwargs: Any) -> Dict[str, Any]:
            fetch_calls.append({"role_id": role_id, "zone": zone, "server": server, "kwargs": kwargs})
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "role_info": {"global_role_id": "16648966321772809985", "role_id": "30284767"},
                    "person_info": {"person_id": "person-30284767"},
                    "indicator": [
                        {"type": "3c", "metrics": [{"pvp_type": 3, "win_count": 160, "total_count": 245, "level": 95}], "performance": {"mmr": 2752, "grade": 15}},
                    ],
                },
            }

        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=kungfu_cache_repo,
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=fake_fetch,
            kungfu_pinyin_to_chinese={},
        )

        result1 = await service.get_role_indicator(
            server="梦江南",
            name="示例角色",
            game_role_id="30284767",
            global_role_id="16648966321772809985",
            zone="电信区",
        )
        self.assertFalse(result1.get("error"))
        self.assertEqual(result1["indicator"]["total_matches"], 245)
        self.assertEqual(result1["indicator"]["win_rate"], 65.3)
        self.assertEqual(result1["indicator"]["score"], 2752)
        self.assertEqual(result1["indicator"]["grade"], 15)
        self.assertEqual(len(fetch_calls), 1)
        self.assertEqual(len(cache_repo.saved_role_indicator), 1)
        kungfu_cache_repo.upsert_role_identity_from_indicator.assert_awaited_once()
        upsert_kwargs = kungfu_cache_repo.upsert_role_identity_from_indicator.await_args.kwargs
        self.assertEqual(upsert_kwargs["person_id"], "person-30284767")
        self.assertEqual(cache_repo.saved_role_indicator[0][1]["person_id"], "person-30284767")
        self.assertEqual(cache_repo.saved_role_indicator[0][1]["global_role_id"], "16648966321772809985")
        self.assertEqual(cache_repo.saved_role_indicator[0][1]["role_id"], "30284767")

        result2 = await service.get_role_indicator(
            server="梦江南",
            name="示例角色",
            game_role_id="30284767",
            global_role_id="16648966321772809985",
            zone="电信区",
        )
        self.assertFalse(result2.get("error"))
        self.assertEqual(result2["cache"]["hit"], True)
        self.assertEqual(result2["cache"]["ttl_seconds"], 86400)
        self.assertEqual(cache_repo.loaded_role_indicator_ttls[-1], 86400)
        self.assertEqual(len(fetch_calls), 1)

        result3 = await service.get_role_indicator(
            server="梦江南",
            name="示例角色",
            game_role_id="30284767",
            global_role_id="16648966321772809985",
            zone="电信区",
            force_refresh=True,
        )
        self.assertFalse(result3.get("error"))
        self.assertEqual(result3["cache"]["hit"], False)
        self.assertEqual(result3["cache"]["ttl_seconds"], 86400)
        self.assertEqual(result3["cache"]["force_refresh"], True)
        self.assertEqual(len(fetch_calls), 2)

    async def test_resolve_identity_from_indicator_writes_person_id(self) -> None:
        kungfu_cache_repo = MagicMock()
        kungfu_cache_repo.upsert_role_identity_from_indicator = AsyncMock()

        def fake_fetch(role_id: str, zone: str, server: str, **kwargs: Any) -> Dict[str, Any]:
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "role_info": {"global_role_id": "SK01-abc", "role_id": "rid-a"},
                    "person_info": {"person_id": "person-a"},
                },
            }

        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=kungfu_cache_repo,
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=FakeJjcInspectRepo(),
            tuilan_request=MagicMock(),
            role_indicator_fetcher=fake_fetch,
            kungfu_pinyin_to_chinese={},
        )

        result = await service._resolve_identity_from_indicator(
            server="梦江南",
            name="角色A",
            game_role_id="rid-a",
            zone="电信区",
            role_id=None,
            global_id=None,
            source="test",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["person_id"], "person-a")
        kungfu_cache_repo.upsert_role_identity_from_indicator.assert_awaited_once()
        upsert_kwargs = kungfu_cache_repo.upsert_role_identity_from_indicator.await_args.kwargs
        self.assertEqual(upsert_kwargs["person_id"], "person-a")

    async def test_role_indicator_saves_cache_with_upgraded_identity_key(self) -> None:
        cache_repo = FakeJjcInspectRepo()
        kungfu_cache_repo = MagicMock()
        kungfu_cache_repo.upsert_role_identity_from_indicator = AsyncMock(return_value={
            "identity_key": "global:SK01-upgraded",
            "identity_level": "global",
            "server": "梦江南",
            "name": "角色A",
            "game_role_id": "rid-a",
            "role_id": "rid-a",
            "global_role_id": "SK01-upgraded",
            "person_id": "person-a",
            "zone": "电信区",
        })

        def fake_fetch(role_id: str, zone: str, server: str, **kwargs: Any) -> Dict[str, Any]:
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "role_info": {"global_role_id": "SK01-upgraded", "role_id": "rid-a"},
                    "person_info": {"person_id": "person-a"},
                    "indicator": [
                        {"type": "3c", "metrics": [{"pvp_type": 3, "win_count": 1, "total_count": 2, "level": 1}], "performance": {"mmr": 1000}},
                    ],
                },
            }

        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=kungfu_cache_repo,
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=fake_fetch,
            kungfu_pinyin_to_chinese={},
        )

        result = await service.get_role_indicator(
            server="梦江南",
            name="角色A",
            game_role_id="rid-a",
            global_role_id="SK01-old",
            zone="电信区",
        )

        self.assertFalse(result.get("error"))
        self.assertEqual(result["identity"]["identity_key"], "global:SK01-upgraded")
        self.assertEqual(cache_repo.saved_role_indicator[0][0], "global:SK01-upgraded")
        self.assertEqual(cache_repo.saved_role_indicator[0][1]["global_role_id"], "SK01-upgraded")
        self.assertEqual(cache_repo.saved_role_indicator[0][1]["role_id"], "rid-a")

    async def test_role_indicator_accepts_3d_indicator_type(self) -> None:
        cache_repo = FakeJjcInspectRepo()

        def fake_fetch(role_id: str, zone: str, server: str, **kwargs: Any) -> Dict[str, Any]:
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "indicator": [
                        {"type": "2d", "metrics": None, "performance": None},
                        {
                            "type": "3d",
                            "metrics": [{"pvp_type": 3, "win_count": 240, "total_count": 389, "level": 95}],
                            "performance": {"mmr": 2793, "grade": 15, "win_count": 242, "total_count": 391},
                        },
                    ],
                },
            }

        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=fake_fetch,
            kungfu_pinyin_to_chinese={},
        )

        result = await service.get_role_indicator(
            server="天鹅坪",
            name="凭本事躺赢",
            game_role_id="34912400",
            global_role_id="SK01-IRDUAS-DYITXJ7CSE2K722ED5OIQGIZ5Q",
            role_id="34912400",
            zone="双线区",
        )

        self.assertFalse(result.get("error"))
        self.assertEqual(result["indicator"]["type"], "3d")
        self.assertEqual(result["indicator"]["total_matches"], 391)
        self.assertEqual(result["indicator"]["win_rate"], 61.9)
        self.assertEqual(result["indicator"]["score"], 2793)
        self.assertEqual(result["indicator"]["grade"], 15)

    async def test_role_indicator_invalid_parse_does_not_cache(self) -> None:
        cache_repo = FakeJjcInspectRepo()
        fetch_calls: List[Dict[str, Any]] = []

        def fake_fetch(role_id: str, zone: str, server: str, **kwargs: Any) -> Dict[str, Any]:
            fetch_calls.append({"role_id": role_id, "zone": zone, "server": server, "kwargs": kwargs})
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "indicator": [
                        {"type": "3c", "metrics": None, "performance": {}},
                    ],
                },
            }

        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=fake_fetch,
            kungfu_pinyin_to_chinese={},
        )

        result = await service.get_role_indicator(
            server="梦江南",
            name="示例角色",
            game_role_id="30284767",
            global_role_id="16648966321772809985",
            zone="电信区",
        )
        self.assertTrue(result.get("error"))
        self.assertEqual(result["message"], "indicator_3c_empty_fields")
        self.assertEqual(len(fetch_calls), 1)
        self.assertEqual(len(cache_repo.saved_role_indicator), 0)


class TestJjcSyncedRoleInspect(unittest.IsolatedAsyncioTestCase):
    async def _list_saved_matches_from_detail(
        self,
        repo: JjcInspectRepo,
        *,
        identity_id: Any = None,
        identity_key: Optional[str] = None,
        server: Optional[str] = None,
        name: Optional[str] = None,
        global_id: str,
        global_role_id: Optional[str] = None,
        role_id: Optional[str] = None,
        game_role_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        return await repo._list_saved_matches_from_detail(
            identity_id=identity_id,
            identity_key=identity_key,
            server=server,
            name=name,
            global_id=global_id,
            global_role_id=global_role_id,
            role_id=role_id,
            game_role_id=game_role_id,
            page=page,
            page_size=page_size,
        )

    async def test_resolve_synced_role_missing_identity_does_not_call_live_sources(self) -> None:
        ranking_service = MagicMock()
        match_history_client = MagicMock()
        role_identity_repo = FakeRoleIdentityRepo(None)
        service = DirectJjcRankingInspectService(
            ranking_service=ranking_service,
            kungfu_cache_repo=MagicMock(),
            match_history_client=match_history_client,
            match_detail_client=MagicMock(),
            cache_repo=FakeJjcInspectRepo(),
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
            role_identity_repo=role_identity_repo,
            sync_repo=FakeSyncRepo(),
        )

        result = await service.resolve_synced_role(server="梦江南", name="示例角色")

        self.assertTrue(result["error"])
        self.assertEqual(result["message"], "role_identity_not_found")
        self.assertEqual(role_identity_repo.candidate_calls, [{"server": "梦江南", "name": "示例角色", "limit": 8}])
        ranking_service.query_jjc_ranking.assert_not_called()
        match_history_client.get_mine_match_history.assert_not_called()

    async def test_resolve_synced_role_missing_identity_returns_local_candidates(self) -> None:
        candidate_id = ObjectId()
        sync_repo = FakeSyncRepo(sync_state={
            "identity_id": candidate_id,
            "identity_key": "global_id:888",
            "status": "cooldown",
            "last_synced_at": 1778000000,
        })
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=FakeJjcInspectRepo(),
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
            role_identity_repo=FakeRoleIdentityRepo(None, candidates=[{
                "_id": candidate_id,
                "identity_key": "global_id:888",
                "server": "唯我独尊",
                "name": "示例角色@old",
                "global_id": "888",
                "debug_extra": "must-not-leak",
            }]),
            sync_repo=sync_repo,
        )

        result = await service.resolve_synced_role(server="梦江南", name="示例角色")

        self.assertTrue(result["error"])
        self.assertEqual(result["message"], "role_identity_not_found")
        self.assertEqual(len(result["candidates"]), 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["player"], {"server": "唯我独尊", "name": "示例角色@old"})
        self.assertEqual(candidate["identity"]["identity_id"], str(candidate_id))
        self.assertEqual(candidate["identity"]["global_id"], "888")
        self.assertNotIn("debug_extra", candidate["identity"])
        self.assertEqual(candidate["reason"], "name_with_suffix")
        self.assertEqual(candidate["sync_status"]["status"], "cooldown")
        self.assertEqual(sync_repo.state_calls, [candidate_id])

    async def test_get_synced_role_matches_returns_local_rows_with_sync_metadata(self) -> None:
        identity_id = ObjectId()
        identity = {
            "_id": identity_id,
            "identity_key": "global_id:987",
            "server": "梦江南",
            "name": "示例角色",
            "global_id": "987",
            "debug_extra": "must-not-leak",
        }
        cache_repo = FakeJjcInspectRepo()
        cache_repo.synced_matches_result = {
            "items": [
                {
                    "match_id": 1001,
                    "cached_detail_summary": {"match_id": 1001},
                    "sync": {"status": "detail_saved", "detail_saved_at": 1778000001},
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 20,
            "has_more": False,
        }
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
            role_identity_repo=FakeRoleIdentityRepo(identity),
            sync_repo=FakeSyncRepo(sync_state={
                "identity_id": identity_id,
                "identity_key": "global_id:987",
                "status": "cooldown",
                "last_synced_at": 1778000000,
            }),
        )

        result = await service.get_synced_role_matches(server="梦江南", name="示例角色")

        self.assertEqual(result["identity"]["identity_id"], str(identity_id))
        self.assertNotIn("_id", result["identity"])
        self.assertNotIn("debug_extra", result["identity"])
        self.assertEqual(result["sync_status"]["status"], "cooldown")
        self.assertEqual(result["recent_matches"][0]["sync"]["status"], "detail_saved")
        self.assertEqual(cache_repo.synced_matches_calls[0]["identity_id"], str(identity_id))
        self.assertEqual(cache_repo.synced_matches_calls[0]["identity_key"], "global_id:987")
        self.assertEqual(cache_repo.synced_matches_calls[0]["server"], "梦江南")
        self.assertEqual(cache_repo.synced_matches_calls[0]["name"], "示例角色")
        self.assertEqual(cache_repo.synced_matches_calls[0]["global_id"], "987")

    async def test_get_synced_role_matches_projection_error_returns_standard_error(self) -> None:
        identity_id = ObjectId()
        identity = {
            "_id": identity_id,
            "identity_key": "global_id:987",
            "server": "梦江南",
            "name": "示例角色",
            "global_id": "987",
        }
        cache_repo = FakeJjcInspectRepo()
        cache_repo.synced_matches_result = RuntimeError("projection_down")
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=cache_repo,
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
            role_identity_repo=FakeRoleIdentityRepo(identity),
            sync_repo=FakeSyncRepo(sync_state={"identity_id": identity_id, "status": "queued"}),
        )

        result = await service.get_synced_role_matches(server="梦江南", name="示例角色")

        self.assertTrue(result["error"])
        self.assertEqual(result["message"], "match_participants_query_failed")
        self.assertEqual(result["identity"]["identity_id"], str(identity_id))
        self.assertEqual(result["sync_status"]["status"], "queued")
        self.assertEqual(cache_repo.synced_matches_calls[0]["global_id"], "987")

    async def test_resolve_synced_role_adds_queue_position_for_queued_status(self) -> None:
        identity_id = ObjectId()
        identity = {
            "_id": identity_id,
            "identity_key": "global_id:987",
            "server": "梦江南",
            "name": "示例角色",
        }
        sync_repo = FakeSyncRepo(sync_state={
            "identity_id": identity_id,
            "identity_key": "global_id:987",
            "status": "queued",
            "priority": 2,
            "queued_at": 1778000000,
            "queue_position": 3,
        })
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=FakeJjcInspectRepo(),
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
            role_identity_repo=FakeRoleIdentityRepo(identity),
            sync_repo=sync_repo,
        )

        result = await service.resolve_synced_role(server="梦江南", name="示例角色")

        self.assertEqual(result["sync_status"]["status"], "queued")
        self.assertEqual(result["sync_status"]["queue_position"], 3)
        self.assertEqual(sync_repo.position_calls[0]["identity_id"], identity_id)

    async def test_identity_only_indicator_missing_identity_does_not_call_live_sources(self) -> None:
        ranking_service = MagicMock()
        indicator_fetcher = MagicMock()
        service = DirectJjcRankingInspectService(
            ranking_service=ranking_service,
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=FakeJjcInspectRepo(),
            tuilan_request=MagicMock(),
            role_indicator_fetcher=indicator_fetcher,
            kungfu_pinyin_to_chinese={},
            role_identity_repo=FakeRoleIdentityRepo(None),
            sync_repo=FakeSyncRepo(),
        )

        result = await service.get_role_indicator(
            server="梦江南",
            name="未收录",
            identity_only=True,
        )

        self.assertTrue(result["error"])
        self.assertEqual(result["message"], "role_identity_not_found")
        ranking_service.query_jjc_ranking.assert_not_called()
        indicator_fetcher.assert_not_called()

    async def test_identity_only_indicator_missing_params_does_not_fetch_indicator(self) -> None:
        identity = {
            "_id": ObjectId(),
            "identity_key": "global_id:987",
            "server": "梦江南",
            "name": "示例角色",
            "global_id": "987",
        }
        indicator_fetcher = MagicMock()
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=FakeJjcInspectRepo(),
            tuilan_request=MagicMock(),
            role_indicator_fetcher=indicator_fetcher,
            kungfu_pinyin_to_chinese={},
            role_identity_repo=FakeRoleIdentityRepo(identity),
            sync_repo=FakeSyncRepo(),
        )

        result = await service.get_role_indicator(
            server="梦江南",
            name="示例角色",
            identity_only=True,
        )

        self.assertTrue(result["error"])
        self.assertEqual(result["message"], "indicator_params_missing")
        self.assertEqual(result["identity"], {
            "identity_id": str(identity["_id"]),
            "identity_key": "global_id:987",
            "server": "梦江南",
            "name": "示例角色",
            "global_id": "987",
        })
        indicator_fetcher.assert_not_called()

    async def test_enqueue_synced_role_uses_fixed_page_priority_and_source(self) -> None:
        identity_id = ObjectId()
        identity = {
            "_id": identity_id,
            "identity_key": "global_id:987",
            "server": "梦江南",
            "name": "示例角色",
        }
        sync_repo = FakeSyncRepo(enqueue_result={
            "identity_id": identity_id,
            "identity_key": "global_id:987",
            "status": "queued",
            "priority": 2,
            "queue_source": "synced_match_page",
            "queue_mode": "incremental_or_full",
        })
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=FakeJjcInspectRepo(),
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
            role_identity_repo=FakeRoleIdentityRepo(identity),
            sync_repo=sync_repo,
        )

        result = await service.enqueue_synced_role(server="梦江南", name="示例角色")

        self.assertTrue(result["queued"])
        call = sync_repo.enqueue_calls[0]
        self.assertIs(call["identity"], identity)
        self.assertEqual(call["kwargs"]["priority"], 2)
        self.assertEqual(call["kwargs"]["source"], "synced_match_page")
        self.assertEqual(call["kwargs"]["mode"], "incremental_or_full")

    async def test_enqueue_synced_role_skips_same_priority_queued_role(self) -> None:
        identity_id = ObjectId()
        identity = {
            "_id": identity_id,
            "identity_key": "global_id:987",
            "server": "梦江南",
            "name": "示例角色",
        }
        sync_repo = FakeSyncRepo(
            sync_state={
                "identity_id": identity_id,
                "identity_key": "global_id:987",
                "status": "queued",
                "priority": 2,
                "queue_position": 4,
            },
            enqueue_result={
                "identity_id": identity_id,
                "identity_key": "global_id:987",
                "status": "queued",
                "priority": 2,
            },
        )
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=FakeJjcInspectRepo(),
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
            role_identity_repo=FakeRoleIdentityRepo(identity),
            sync_repo=sync_repo,
        )

        result = await service.enqueue_synced_role(server="梦江南", name="示例角色")

        self.assertTrue(result["queued"])
        self.assertTrue(result["already_queued"])
        self.assertEqual(result["sync_status"]["queue_position"], 4)
        self.assertEqual(sync_repo.enqueue_calls, [])

    async def test_enqueue_synced_role_allows_different_priority_queued_role(self) -> None:
        identity_id = ObjectId()
        identity = {
            "_id": identity_id,
            "identity_key": "global_id:987",
            "server": "梦江南",
            "name": "示例角色",
        }
        sync_repo = FakeSyncRepo(
            sync_state={
                "identity_id": identity_id,
                "identity_key": "global_id:987",
                "status": "queued",
                "priority": 9,
            },
            enqueue_result={
                "identity_id": identity_id,
                "identity_key": "global_id:987",
                "status": "queued",
                "priority": 2,
            },
        )
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=FakeJjcInspectRepo(),
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
            role_identity_repo=FakeRoleIdentityRepo(identity),
            sync_repo=sync_repo,
        )

        result = await service.enqueue_synced_role(server="梦江南", name="示例角色")

        self.assertTrue(result["queued"])
        self.assertNotIn("already_queued", result)
        self.assertEqual(len(sync_repo.enqueue_calls), 1)
        self.assertEqual(sync_repo.enqueue_calls[0]["kwargs"]["priority"], 2)

    async def test_enqueue_synced_role_reports_failed_update_instead_of_silent_pending(self) -> None:
        identity_id = ObjectId()
        identity = {
            "_id": identity_id,
            "identity_key": "global_id:987",
            "server": "梦江南",
            "name": "示例角色",
        }
        service = DirectJjcRankingInspectService(
            ranking_service=MagicMock(),
            kungfu_cache_repo=MagicMock(),
            match_history_client=MagicMock(),
            match_detail_client=MagicMock(),
            cache_repo=FakeJjcInspectRepo(),
            tuilan_request=MagicMock(),
            role_indicator_fetcher=MagicMock(),
            kungfu_pinyin_to_chinese={},
            role_identity_repo=FakeRoleIdentityRepo(identity),
            sync_repo=FakeSyncRepo(
                sync_state={
                    "identity_id": identity_id,
                    "identity_key": "global_id:987",
                    "status": "pending",
                    "priority": 0,
                },
                enqueue_result=None,
            ),
        )

        result = await service.enqueue_synced_role(server="梦江南", name="示例角色")

        self.assertTrue(result["error"])
        self.assertEqual(result["message"], "enqueue_failed")
        self.assertEqual(result["sync_status"]["status"], "pending")

    async def test_inspect_repo_lists_only_available_local_details(self) -> None:
        identity_id = ObjectId()
        seen = [
            {
                "match_id": 1001,
                "status": "queued",
                "source_identity_id": identity_id,
                "source_identity_key": "global_id:987",
                "match_time": 1778000000,
                "detail_saved_at": 1778000100,
            },
            {
                "match_id": 1002,
                "status": "detail_saved",
                "source_identity_id": identity_id,
                "source_identity_key": "global_id:987",
                "match_time": 1777000000,
                "detail_saved_at": 1777000100,
            },
            {
                "match_id": 1003,
                "status": "detail_saved",
                "source_identity_id": identity_id,
                "source_identity_key": "global_id:987",
                "match_time": 1776000000,
                "detail_saved_at": 1776000100,
            },
        ]
        details = [
            {
                "match_id": 1001,
                "cached_at": 1778000200,
                "data": {
                    "detail": {
                        "match_time": 1778000000,
                        "basic_info": {"match_type": 3, "start_time": 1778000000, "duration": 180, "grade": 12},
                        "team1": {"won": True, "players_info": [{"role_name": "示例角色", "server": "梦江南", "global_id": "987", "kungfu": "花间游"}]},
                        "team2": {"won": False, "players_info": []},
                    }
                },
            },
            {"match_id": 1002, "cached_at": 1777000200, "data": {"unavailable": True}},
            {
                "match_id": 1003,
                "cached_at": 1776000200,
                "data": {
                    "detail": {
                        "basic_info": {"match_type": 2},
                        "team1": {"won": True, "players_info": [{"role_name": "示例角色", "server": "梦江南", "global_id": "987"}]},
                        "team2": {"won": False, "players_info": []},
                    }
                },
            },
        ]
        db = MagicMock()
        db.jjc_sync_match_seen = FakeFindCollection(seen)
        db.jjc_match_detail = FakeFindCollection(details)
        repo = JjcInspectRepo(db=db, snapshot_repo=None)

        result = await self._list_saved_matches_from_detail(
            repo,
            identity_id=str(identity_id),
            identity_key="global_id:987",
            server="梦江南",
            name="示例角色",
            global_id="987",
        )

        self.assertEqual([item["match_id"] for item in result["items"]], [1001])
        self.assertEqual(result["items"][0]["sync"]["status"], "queued")
        self.assertEqual(result["items"][0]["cached_detail_summary"]["match_id"], 1001)
        detail_query = db.jjc_match_detail.find_calls[0]
        self.assertEqual(detail_query["data.unavailable"], {"$ne": True})
        self.assertIn({"data.detail.team1.players_info.global_id": "987"}, detail_query["$or"])
        seen_query = db.jjc_sync_match_seen.find_calls[0]
        self.assertNotIn("status", seen_query)
        self.assertEqual(seen_query["match_id"], {"$in": [1001, 1002, 1003]})

    async def test_inspect_repo_paginates_after_filtering_invalid_details(self) -> None:
        identity_id = ObjectId()
        seen = [
            {
                "match_id": 1001,
                "status": "detail_saved",
                "source_identity_id": identity_id,
                "source_identity_key": "global_id:987",
                "match_time": 1778000000,
            },
            {
                "match_id": 1002,
                "status": "detail_saved",
                "source_identity_id": identity_id,
                "source_identity_key": "global_id:987",
                "match_time": 1777000000,
            },
            {
                "match_id": 1003,
                "status": "detail_saved",
                "source_identity_id": identity_id,
                "source_identity_key": "global_id:987",
                "match_time": 1776000000,
            },
        ]
        details = [
            {"match_id": 1001, "cached_at": 1, "data": {"unavailable": True}},
            {
                "match_id": 1002,
                "cached_at": 2,
                "data": {
                    "detail": {
                        "basic_info": {"match_type": 3, "start_time": 1777000000},
                        "team1": {"won": True, "players_info": [{"role_name": "示例角色", "server": "梦江南", "global_id": "987"}]},
                        "team2": {"won": False, "players_info": []},
                    }
                },
            },
            {
                "match_id": 1003,
                "cached_at": 3,
                "data": {
                    "detail": {
                        "basic_info": {"match_type": 3, "start_time": 1776000000},
                        "team1": {"won": False, "players_info": [{"role_name": "示例角色", "server": "梦江南", "global_id": "987"}]},
                        "team2": {"won": True, "players_info": []},
                    }
                },
            },
        ]
        db = MagicMock()
        db.jjc_sync_match_seen = FakeFindCollection(seen)
        db.jjc_match_detail = FakeFindCollection(details)
        repo = JjcInspectRepo(db=db, snapshot_repo=None)

        result = await self._list_saved_matches_from_detail(
            repo,
            identity_id=str(identity_id),
            identity_key="global_id:987",
            server="梦江南",
            name="示例角色",
            global_id="987",
            page=1,
            page_size=1,
        )

        self.assertEqual(result["total"], 2)
        self.assertTrue(result["has_more"])
        self.assertEqual([item["match_id"] for item in result["items"]], [1002])

    async def test_inspect_repo_derives_row_from_matched_player_not_first_player(self) -> None:
        identity_id = ObjectId()
        seen = [{
            "match_id": 2001,
            "status": "detail_saved",
            "source_identity_id": identity_id,
            "source_identity_key": "global_id:target",
            "match_time": 1779000000,
        }]
        details = [{
            "match_id": 2001,
            "cached_at": 1779000100,
            "data": {
                "detail": {
                    "match_time": 1779000000,
                    "basic_info": {"match_type": 3, "start_time": 1779000000, "duration": 200, "grade": 14},
                    "team1": {
                        "won": False,
                        "players_info": [
                            {
                                "role_name": "队友",
                                "server": "梦江南",
                                "global_id": "other",
                                "kungfu": "冰心诀",
                                "mvp": True,
                                "score": 2400,
                            },
                            {
                                "role_name": "目标角色",
                                "server": "梦江南",
                                "global_id": "target",
                                "kungfu": "花间游",
                                "mvp": False,
                                "score": 2500,
                                "mmr_delta": -12,
                            },
                        ],
                    },
                    "team2": {"won": True, "players_info": []},
                }
            },
        }]
        db = MagicMock()
        db.jjc_sync_match_seen = FakeFindCollection(seen)
        db.jjc_match_detail = FakeFindCollection(details)
        repo = JjcInspectRepo(db=db, snapshot_repo=None)

        result = await self._list_saved_matches_from_detail(
            repo,
            identity_id=str(identity_id),
            identity_key="global_id:target",
            server="梦江南",
            name="目标角色",
            global_id="target",
        )

        self.assertEqual(result["total"], 1)
        row = result["items"][0]
        self.assertFalse(row["won"])
        self.assertEqual(row["kungfu"], "花间游")
        self.assertEqual(row["total_mmr"], 2500)
        self.assertEqual(row["mmr_delta"], -12)
        self.assertFalse(row["mvp"])

    async def test_inspect_repo_requires_global_id(self) -> None:
        db = MagicMock()
        db.jjc_sync_match_seen = FakeFindCollection([])
        db.jjc_match_detail = FakeFindCollection([])
        repo = JjcInspectRepo(db=db, snapshot_repo=None)

        result = await repo.list_saved_local_3v3_matches_for_identity(
            identity_id=None,
            identity_key=None,
            server="天鹅坪",
            name="海苔小饼",
        )

        self.assertEqual(result["total"], 0)
        self.assertEqual(db.jjc_match_detail.find_calls, [])
        self.assertEqual(db.jjc_sync_match_seen.find_calls, [])

    async def test_inspect_repo_finds_participant_match_by_global_id_without_source_identity(self) -> None:
        seen = [{
            "match_id": 3001,
            "status": "detail_saved",
            "source_identity_key": "global:other-source",
            "match_time": 1779100000,
            "detail_saved_at": 1779100100,
        }]
        details = [{
            "match_id": 3001,
            "cached_at": 1779100200,
            "data": {
                "detail": {
                    "match_time": 1779100000,
                    "basic_info": {"match_type": 3, "start_time": 1779100000, "duration": 160, "grade": 13},
                    "team1": {
                        "won": True,
                        "players_info": [
                            {
                                "role_name": "海苔小饼·天鹅坪",
                                "server": "天鹅坪",
                                "global_id": "432345564261473917",
                                "kungfu": "花间游",
                                "score": 2300,
                                "mvp": True,
                            }
                        ],
                    },
                    "team2": {"won": False, "players_info": []},
                }
            },
        }]
        db = MagicMock()
        db.jjc_sync_match_seen = FakeFindCollection(seen)
        db.jjc_match_detail = FakeFindCollection(details)
        repo = JjcInspectRepo(db=db, snapshot_repo=None)

        result = await self._list_saved_matches_from_detail(
            repo,
            identity_id=None,
            identity_key=None,
            server="天鹅坪",
            name="海苔小饼",
            global_id="432345564261473917",
        )

        self.assertEqual(result["total"], 1)
        row = result["items"][0]
        self.assertEqual(row["match_id"], 3001)
        self.assertTrue(row["won"])
        self.assertEqual(row["kungfu"], "花间游")
        self.assertEqual(row["total_mmr"], 2300)
        self.assertEqual(row["sync"]["source_identity_key"], "global:other-source")
        participant_query = db.jjc_match_detail.find_calls[0]
        self.assertEqual(participant_query["data.unavailable"], {"$ne": True})
        self.assertIn({"data.detail.team1.players_info.global_id": "432345564261473917"}, participant_query["$or"])

    async def test_inspect_repo_allows_missing_seen_as_not_synced(self) -> None:
        details = [{
            "match_id": 4001,
            "cached_at": 1779200200,
            "data": {
                "detail": {
                    "match_time": 1779200000,
                    "basic_info": {"match_type": 3, "start_time": 1779200000},
                    "team1": {
                        "won": True,
                        "players_info": [
                            {"role_name": "目标角色", "server": "梦江南", "global_id": "target", "kungfu": "花间游"}
                        ],
                    },
                    "team2": {"won": False, "players_info": []},
                }
            },
        }]
        db = MagicMock()
        db.jjc_sync_match_seen = FakeFindCollection([])
        db.jjc_match_detail = FakeFindCollection(details)
        repo = JjcInspectRepo(db=db, snapshot_repo=None)

        result = await self._list_saved_matches_from_detail(
            repo,
            identity_id=None,
            identity_key=None,
            server="梦江南",
            name="目标角色",
            global_id="target",
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["sync"]["status"], "not_synced")
        self.assertEqual(result["items"][0]["match_time"], 1779200000)

    async def test_inspect_repo_infers_3v3_when_match_type_missing_and_six_players(self) -> None:
        players = [
            {"role_name": f"队员{index}", "server": "梦江南", "global_id": "target" if index == 0 else f"other-{index}"}
            for index in range(6)
        ]
        details = [{
            "match_id": 4002,
            "cached_at": 1779300200,
            "data": {
                "detail": {
                    "match_time": 1779300000,
                    "basic_info": {"start_time": 1779300000},
                    "team1": {"won": True, "players_info": players[:3]},
                    "team2": {"won": False, "players_info": players[3:]},
                }
            },
        }]
        db = MagicMock()
        db.jjc_sync_match_seen = FakeFindCollection([])
        db.jjc_match_detail = FakeFindCollection(details)
        repo = JjcInspectRepo(db=db, snapshot_repo=None)

        result = await self._list_saved_matches_from_detail(
            repo,
            identity_id=None,
            identity_key=None,
            server="梦江南",
            name="队员0",
            global_id="target",
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["match_id"], 4002)

    async def test_inspect_repo_uses_projection_and_hydrates_summary(self) -> None:
        details = [{
            "match_id": 5001,
            "cached_at": 1779400200,
            "data": {
                "detail": {
                    "basic_info": {"match_type": 3},
                    "team1": {"won": True, "players_info": [{"role_name": "目标角色", "server": "梦江南", "kungfu": "花间游"}]},
                    "team2": {"won": False, "players_info": []},
                }
            },
        }]
        participant_repo = FakeParticipantRepo({
            "items": [{
                "match_id": 5001,
                "won": True,
                "kungfu": "花间游",
                "avg_grade": 13,
                "total_mmr": 2400,
                "mmr_delta": 10,
                "mvp": False,
                "match_time": 1779400000,
                "start_time": 1779400000,
                "duration": 180,
                "sync_status": "detail_saved",
                "detail_saved_at": 1779400100,
                "source_identity_id": ObjectId("64b64c9f6df2d096edcd67a1"),
                "source_identity_key": "global_id:target",
            }],
            "total": 1,
            "page": 1,
            "page_size": 20,
            "has_more": False,
        })
        db = MagicMock()
        db.jjc_sync_match_seen = FakeFindCollection([])
        db.jjc_match_detail = FakeFindCollection(details)
        repo = JjcInspectRepo(db=db, snapshot_repo=None, participant_repo=participant_repo)
        result = await repo.list_saved_local_3v3_matches_for_identity(
            identity_id=None,
            identity_key=None,
            server="梦江南",
            name="目标角色",
            global_id="target",
        )

        self.assertEqual(db.jjc_sync_match_seen.find_calls, [])
        self.assertEqual(participant_repo.calls[0]["global_id"], "target")
        row = result["items"][0]
        self.assertEqual(row["match_id"], 5001)
        self.assertEqual(row["total_mmr"], 2400)
        self.assertEqual(row["sync"]["source_identity_id"], "64b64c9f6df2d096edcd67a1")
        self.assertEqual(row["cached_detail_summary"]["match_id"], 5001)

    async def test_inspect_repo_empty_projection_does_not_fallback(self) -> None:
        participant_repo = FakeParticipantRepo({
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": 20,
            "has_more": False,
        })
        db = MagicMock()
        db.jjc_sync_match_seen = FakeFindCollection([])
        db.jjc_match_detail = FakeFindCollection([{
            "match_id": 5002,
            "cached_at": 1,
            "data": {
                "detail": {
                    "basic_info": {"match_type": 3},
                    "team1": {"won": True, "players_info": [{"global_id": "target"}]},
                    "team2": {"won": False, "players_info": []},
                }
            },
        }])
        repo = JjcInspectRepo(db=db, snapshot_repo=None, participant_repo=participant_repo)
        result = await repo.list_saved_local_3v3_matches_for_identity(
            identity_id=None,
            identity_key=None,
            server="梦江南",
            name="目标角色",
            global_id="target",
        )

        self.assertEqual(result["total"], 0)
        self.assertEqual(db.jjc_match_detail.find_calls, [])

    async def test_inspect_repo_projection_error_does_not_fallback(self) -> None:
        db = MagicMock()
        db.jjc_sync_match_seen = FakeFindCollection([])
        db.jjc_match_detail = FakeFindCollection([{
            "match_id": 5003,
            "cached_at": 1,
            "data": {
                "detail": {
                    "match_time": 1779500000,
                    "basic_info": {"match_type": 3},
                    "team1": {"won": True, "players_info": [{"global_id": "target"}]},
                    "team2": {"won": False, "players_info": []},
                }
            },
        }])
        repo = JjcInspectRepo(
            db=db,
            snapshot_repo=None,
            participant_repo=FakeParticipantRepo(error=RuntimeError("projection_down")),
        )
        with self.assertRaisesRegex(RuntimeError, "projection_down"):
            result = await repo.list_saved_local_3v3_matches_for_identity(
                identity_id=None,
                identity_key=None,
                server="梦江南",
                name="目标角色",
                global_id="target",
            )
        self.assertEqual(db.jjc_match_detail.find_calls, [])


class TestNormalizeRecentMatches(unittest.TestCase):
    """Tests for the normalize_recent_matches() pure function."""

    def test_filter_3v3_only(self):
        from src.services.jx3.jjc_ranking_inspect import normalize_recent_matches

        raw = [
            {"pvpType": 3, "match_id": 1, "won": True, "match_time": 1000},
            {"pvpType": 2, "match_id": 2, "won": False, "match_time": 2000},
            {"type": 3, "match_id": 3, "won": True, "match_time": 3000},
            {"pvp_type": 3, "match_id": 4, "won": True, "match_time": 4000},
            {"pvpType": 1, "match_id": 5, "won": False, "match_time": 5000},
        ]
        result = normalize_recent_matches(
            raw,
            kungfu_pinyin_to_chinese={"huajian": "花间游"},
            max_recent_matches=20,
        )
        match_ids = [item["match_id"] for item in result]
        self.assertEqual(match_ids, [4, 3, 1])

    def test_kungfu_chinese_translation(self):
        from src.services.jx3.jjc_ranking_inspect import normalize_recent_matches

        raw = [
            {"pvpType": 3, "match_id": 1, "won": True, "kungfu": "huajian", "match_time": 1000},
            {"pvpType": 3, "match_id": 2, "won": False, "kungfu": "bingxinjue", "match_time": 2000},
        ]
        result = normalize_recent_matches(
            raw,
            kungfu_pinyin_to_chinese={"huajian": "花间游", "bingxinjue": "冰心诀"},
            max_recent_matches=20,
        )
        self.assertEqual(result[1]["kungfu"], "花间游")
        self.assertEqual(result[0]["kungfu"], "冰心诀")

    def test_field_aliases(self):
        from src.services.jx3.jjc_ranking_inspect import normalize_recent_matches

        raw = [
            {
                "pvpType": 3,
                "matchId": 100,
                "won": True,
                "kungfu_name": "huajian",
                "startTime": 1700000100,
                "endTime": 1700000280,
                "totalMmr": 2000,
                "mmr": 15,
                "avgGrade": 12,
                "mvp": True,
                "duration": 180,
            }
        ]
        result = normalize_recent_matches(
            raw,
            kungfu_pinyin_to_chinese={"huajian": "花间游"},
            max_recent_matches=20,
        )
        item = result[0]
        self.assertEqual(item["match_id"], 100)
        self.assertEqual(item["kungfu"], "花间游")
        self.assertEqual(item["total_mmr"], 2000)
        self.assertEqual(item["mmr_delta"], 15)
        self.assertEqual(item["avg_grade"], 12)
        self.assertTrue(item["mvp"])
        self.assertEqual(item["match_time"], 1700000100)
        self.assertEqual(item["start_time"], 1700000100)
        self.assertEqual(item["end_time"], 1700000280)
        self.assertEqual(item["duration"], 180)

    def test_sort_descending_by_match_time(self):
        from src.services.jx3.jjc_ranking_inspect import normalize_recent_matches

        raw = [
            {"pvpType": 3, "match_id": 1, "won": True, "match_time": 1000},
            {"pvpType": 3, "match_id": 3, "won": True, "match_time": 3000},
            {"pvpType": 3, "match_id": 2, "won": True, "match_time": 2000},
        ]
        result = normalize_recent_matches(
            raw,
            kungfu_pinyin_to_chinese={},
            max_recent_matches=20,
        )
        times = [item["match_time"] for item in result]
        self.assertEqual(times, [3000, 2000, 1000])

    def test_truncate_to_max_recent_matches(self):
        from src.services.jx3.jjc_ranking_inspect import normalize_recent_matches

        raw = [
            {"pvpType": 3, "match_id": i, "won": True, "match_time": 1000 + i}
            for i in range(50)
        ]
        result = normalize_recent_matches(
            raw,
            kungfu_pinyin_to_chinese={},
            max_recent_matches=10,
        )
        self.assertEqual(len(result), 10)

    def test_missing_fields_graceful(self):
        from src.services.jx3.jjc_ranking_inspect import normalize_recent_matches

        raw = [
            {"pvpType": 3, "match_id": 1},
        ]
        result = normalize_recent_matches(
            raw,
            kungfu_pinyin_to_chinese={},
            max_recent_matches=20,
        )
        item = result[0]
        self.assertEqual(item["match_id"], 1)
        self.assertFalse(item["won"])
        self.assertEqual(item["kungfu"], "")
        self.assertIsNone(item["avg_grade"])
        self.assertIsNone(item["total_mmr"])
        self.assertIsNone(item["mmr_delta"])
        self.assertFalse(item["mvp"])
        self.assertIsNone(item["match_time"])

    def test_non_dict_items_skipped(self):
        from src.services.jx3.jjc_ranking_inspect import normalize_recent_matches

        raw = [
            {"pvpType": 3, "match_id": 1, "won": True, "match_time": 1000},
            None,
            "not_a_dict",
            {"pvpType": 3, "match_id": 2, "won": False, "match_time": 2000},
        ]
        result = normalize_recent_matches(
            raw,
            kungfu_pinyin_to_chinese={},
            max_recent_matches=20,
        )
        self.assertEqual(len(result), 2)

    def test_untyped_matches_included(self):
        """Entries without pvpType/type are included (compatible)."""
        from src.services.jx3.jjc_ranking_inspect import normalize_recent_matches

        raw = [
            {"match_id": 1, "won": True, "match_time": 1000},
        ]
        result = normalize_recent_matches(
            raw,
            kungfu_pinyin_to_chinese={},
            max_recent_matches=20,
        )
        self.assertEqual(len(result), 1)

    def test_explicit_zero_pvpType_filtered(self):
        """pvpType=0 is an explicit non-3 value and must be filtered out."""
        from src.services.jx3.jjc_ranking_inspect import normalize_recent_matches

        raw = [
            {"pvpType": 3, "match_id": 1, "won": True, "match_time": 3000},
            {"pvpType": 0, "match_id": 2, "won": False, "match_time": 2000},
            {"pvpType": 3, "match_id": 3, "won": True, "match_time": 1000},
        ]
        result = normalize_recent_matches(
            raw,
            kungfu_pinyin_to_chinese={},
            max_recent_matches=20,
        )
        match_ids = [item["match_id"] for item in result]
        self.assertEqual(match_ids, [1, 3])

    def test_pvpType_false_filtered(self):
        """pvpType=False is present but not 3 → must be filtered."""
        from src.services.jx3.jjc_ranking_inspect import normalize_recent_matches

        raw = [
            {"pvpType": False, "match_id": 1, "won": True, "match_time": 3000},
            {"pvpType": 3, "match_id": 2, "won": True, "match_time": 2000},
        ]
        result = normalize_recent_matches(
            raw,
            kungfu_pinyin_to_chinese={},
            max_recent_matches=20,
        )
        match_ids = sorted([item["match_id"] for item in result])
        self.assertEqual(match_ids, [2])

    def test_pvpType_leftmost_wins_over_later_fields(self):
        """When pvpType is present (even 0), later pvp_type/type must not override it."""
        from src.services.jx3.jjc_ranking_inspect import normalize_recent_matches

        raw = [
            {"pvpType": 0, "pvp_type": 3, "match_id": 1, "won": True, "match_time": 1000},
            {"pvpType": 3, "type": 0, "match_id": 2, "won": True, "match_time": 2000},
        ]
        result = normalize_recent_matches(
            raw,
            kungfu_pinyin_to_chinese={},
            max_recent_matches=20,
        )
        # Only item 2 should survive; item 1 has pvpType=0 which is not 3
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["match_id"], 2)


class TestWarmupRoleRecentCache(unittest.IsolatedAsyncioTestCase):
    """Tests for role_recent warmup in _warmup_inspect_cache_from_kungfu_detail()."""

    async def test_warmup_saves_role_recent(self):
        from src.services.jx3.jjc_ranking_inspect import normalize_recent_matches

        matches = [
            {"pvpType": 3, "match_id": i, "won": True, "kungfu": "huajian", "match_time": 1700000000 + i}
            for i in range(25)
        ]
        service = WarmupJjcRankingService(MagicMock())
        object.__setattr__(service, "inspect_repo", MagicMock())
        repo = service._inspect_cache()
        repo.save_role_recent = AsyncMock()
        repo.save_role_indicator = AsyncMock()
        repo.save_match_detail = AsyncMock()

        await service._warmup_inspect_cache_from_kungfu_detail(
            server="梦江南",
            name="示例角色",
            kungfu_detail={
                "_cache_warmup": {
                    "role_indicator": {
                        "game_role_id": "100",
                        "global_role_id": "global-100",
                        "global_id": "99999",
                        "role_id": "100",
                        "zone": "电信区",
                    },
                    "role_recent": {
                        "raw_matches": matches,
                        "request_size": 40,
                    },
                }
            },
        )

        repo.save_role_recent.assert_awaited_once()
        args = repo.save_role_recent.await_args[0]
        self.assertEqual(args[0], "梦江南")
        self.assertEqual(args[1], "示例角色")
        payload = args[2]
        self.assertIn("cached_at", payload)
        self.assertIn("data", payload)
        data = payload["data"]
        self.assertEqual(data["player"], {"server": "梦江南", "name": "示例角色"})
        self.assertEqual(data["identity"]["source"], "ranking_warmup")
        self.assertEqual(data["identity_key"], "global_id:99999")
        self.assertEqual(data["pagination"]["cursor"], 0)
        self.assertTrue(data["pagination"]["has_more"])
        self.assertEqual(data["pagination"]["next_cursor"], 20)
        self.assertEqual(len(data["recent_matches"]), 20)

    async def test_warmup_identity_key_global_role_id_fallback(self):
        matches = [
            {"pvpType": 3, "match_id": 1, "won": True, "kungfu": "huajian", "match_time": 1700000000}
        ]
        service = WarmupJjcRankingService(MagicMock())
        object.__setattr__(service, "inspect_repo", MagicMock())
        repo = service._inspect_cache()
        repo.save_role_recent = AsyncMock()
        repo.save_role_indicator = AsyncMock()
        repo.save_match_detail = AsyncMock()

        await service._warmup_inspect_cache_from_kungfu_detail(
            server="梦江南",
            name="示例角色",
            kungfu_detail={
                "_cache_warmup": {
                    "role_indicator": {
                        "game_role_id": "100",
                        "global_role_id": "global-100",
                        "global_id": None,
                        "role_id": "100",
                        "zone": "电信区",
                    },
                    "role_recent": {
                        "raw_matches": matches,
                        "request_size": 40,
                    },
                }
            },
        )

        repo.save_role_recent.assert_awaited_once()
        data = repo.save_role_recent.await_args[0][2]["data"]
        self.assertEqual(data["identity_key"], "global:global-100")

    async def test_warmup_identity_key_none_fallback(self):
        """When both global_id and global_role_id are missing, identity_key is None."""
        matches = [
            {"pvpType": 3, "match_id": 1, "won": True, "kungfu": "huajian", "match_time": 1700000000}
        ]
        service = WarmupJjcRankingService(MagicMock())
        object.__setattr__(service, "inspect_repo", MagicMock())
        repo = service._inspect_cache()
        repo.save_role_recent = AsyncMock()
        repo.save_role_indicator = AsyncMock()
        repo.save_match_detail = AsyncMock()

        await service._warmup_inspect_cache_from_kungfu_detail(
            server="梦江南",
            name="示例角色",
            kungfu_detail={
                "_cache_warmup": {
                    "role_indicator": {
                        "game_role_id": "100",
                        "global_role_id": None,
                        "global_id": None,
                        "role_id": "100",
                        "zone": "电信区",
                    },
                    "role_recent": {
                        "raw_matches": matches,
                        "request_size": 40,
                    },
                }
            },
        )

        repo.save_role_recent.assert_awaited_once()
        data = repo.save_role_recent.await_args[0][2]["data"]
        self.assertIsNone(data["identity_key"])
        self.assertEqual(data["identity"]["server"], "梦江南")
        self.assertEqual(data["identity"]["source"], "ranking_warmup")
        self.assertEqual(len(data["recent_matches"]), 1)

    async def test_warmup_request_size_has_more_true(self):
        """When raw matches count reaches request_size, has_more is True."""
        matches = [
            {"pvpType": 3, "match_id": i, "won": True, "match_time": 1700000000 + i}
            for i in range(20)
        ]
        service = WarmupJjcRankingService(MagicMock())
        object.__setattr__(service, "inspect_repo", MagicMock())
        repo = service._inspect_cache()
        repo.save_role_recent = AsyncMock()
        repo.save_role_indicator = AsyncMock()
        repo.save_match_detail = AsyncMock()

        await service._warmup_inspect_cache_from_kungfu_detail(
            server="梦江南",
            name="示例角色",
            kungfu_detail={
                "_cache_warmup": {
                    "role_indicator": {
                        "game_role_id": "100",
                        "global_role_id": "global-100",
                        "role_id": "100",
                        "zone": "电信区",
                    },
                    "role_recent": {
                        "raw_matches": matches,
                        "request_size": 20,
                    },
                }
            },
        )

        data = repo.save_role_recent.await_args[0][2]["data"]
        self.assertTrue(data["pagination"]["has_more"])
        self.assertEqual(data["pagination"]["next_cursor"], 20)

    async def test_warmup_request_size_has_more_false(self):
        """When raw matches count < request_size, has_more is False."""
        matches = [
            {"pvpType": 3, "match_id": i, "won": True, "match_time": 1700000000 + i}
            for i in range(5)
        ]
        service = WarmupJjcRankingService(MagicMock())
        object.__setattr__(service, "inspect_repo", MagicMock())
        repo = service._inspect_cache()
        repo.save_role_recent = AsyncMock()
        repo.save_role_indicator = AsyncMock()
        repo.save_match_detail = AsyncMock()

        await service._warmup_inspect_cache_from_kungfu_detail(
            server="梦江南",
            name="示例角色",
            kungfu_detail={
                "_cache_warmup": {
                    "role_indicator": {
                        "game_role_id": "100",
                        "global_role_id": "global-100",
                        "role_id": "100",
                        "zone": "电信区",
                    },
                    "role_recent": {
                        "raw_matches": matches,
                        "request_size": 40,
                    },
                }
            },
        )

        data = repo.save_role_recent.await_args[0][2]["data"]
        self.assertFalse(data["pagination"]["has_more"])
        self.assertIsNone(data["pagination"]["next_cursor"])

    async def test_warmup_40_raw_matches_first_page_20_has_more_and_next_cursor_20(self):
        """raw_matches=40, max_recent_matches=20: has_more=True, next_cursor=20."""
        matches = [
            {"pvpType": 3, "match_id": i, "won": True, "match_time": 1700000000 + i}
            for i in range(40)
        ]
        service = WarmupJjcRankingService(MagicMock())
        object.__setattr__(service, "inspect_repo", MagicMock())
        repo = service._inspect_cache()
        repo.save_role_recent = AsyncMock()
        repo.save_role_indicator = AsyncMock()
        repo.save_match_detail = AsyncMock()

        await service._warmup_inspect_cache_from_kungfu_detail(
            server="梦江南",
            name="示例角色",
            kungfu_detail={
                "_cache_warmup": {
                    "role_indicator": {
                        "game_role_id": "100",
                        "global_role_id": "global-100",
                        "role_id": "100",
                        "zone": "电信区",
                    },
                    "role_recent": {
                        "raw_matches": matches,
                        "request_size": 40,
                    },
                }
            },
        )

        data = repo.save_role_recent.await_args[0][2]["data"]
        self.assertTrue(data["pagination"]["has_more"])
        self.assertEqual(data["pagination"]["next_cursor"], 20)
        self.assertEqual(len(data["recent_matches"]), 20)

    async def test_warmup_filtered_first_page_keeps_next_cursor_20(self):
        """When raw first 20 are all non-3v3 (filtered to zero), next_cursor still 20."""
        matches = [
            {"pvpType": 2, "match_id": i, "won": True, "match_time": 1700000000 + i}
            for i in range(20)
        ]
        # Add 5 more 3v3 entries beyond the first page (offset 20-24)
        for i in range(20, 25):
            matches.append(
                {"pvpType": 3, "match_id": i, "won": True, "match_time": 1700000000 + i}
            )

        service = WarmupJjcRankingService(MagicMock())
        object.__setattr__(service, "inspect_repo", MagicMock())
        repo = service._inspect_cache()
        repo.save_role_recent = AsyncMock()
        repo.save_role_indicator = AsyncMock()
        repo.save_match_detail = AsyncMock()

        await service._warmup_inspect_cache_from_kungfu_detail(
            server="梦江南",
            name="示例角色",
            kungfu_detail={
                "_cache_warmup": {
                    "role_indicator": {
                        "game_role_id": "100",
                        "global_role_id": "global-100",
                        "role_id": "100",
                        "zone": "电信区",
                    },
                    "role_recent": {
                        "raw_matches": matches,
                        "request_size": 40,
                    },
                }
            },
        )

        data = repo.save_role_recent.await_args[0][2]["data"]
        self.assertTrue(data["pagination"]["has_more"])
        self.assertEqual(data["pagination"]["next_cursor"], 20)
        self.assertEqual(len(data["recent_matches"]), 0)

    async def test_warmup_no_role_indicator_still_writes_role_recent(self):
        """role_recent can be written even without role_indicator in warmup."""
        matches = [
            {"pvpType": 3, "match_id": 1, "won": True, "match_time": 1700000000}
        ]
        service = WarmupJjcRankingService(MagicMock())
        object.__setattr__(service, "inspect_repo", MagicMock())
        repo = service._inspect_cache()
        repo.save_role_recent = AsyncMock()
        repo.save_role_indicator = AsyncMock()
        repo.save_match_detail = AsyncMock()

        await service._warmup_inspect_cache_from_kungfu_detail(
            server="梦江南",
            name="示例角色",
            kungfu_detail={
                "_cache_warmup": {
                    "role_recent": {
                        "raw_matches": matches,
                        "request_size": 40,
                    },
                }
            },
        )

        repo.save_role_recent.assert_awaited_once()
        data = repo.save_role_recent.await_args[0][2]["data"]
        self.assertIsNone(data["identity_key"])
        self.assertEqual(data["identity"]["server"], "梦江南")
        self.assertEqual(data["identity"]["source"], "ranking_warmup")

    async def test_warmup_empty_raw_matches_does_not_write(self):
        """Empty raw_matches list skips save_role_recent."""
        service = WarmupJjcRankingService(MagicMock())
        object.__setattr__(service, "inspect_repo", MagicMock())
        repo = service._inspect_cache()
        repo.save_role_recent = AsyncMock()
        repo.save_role_indicator = AsyncMock()
        repo.save_match_detail = AsyncMock()

        await service._warmup_inspect_cache_from_kungfu_detail(
            server="梦江南",
            name="示例角色",
            kungfu_detail={
                "_cache_warmup": {
                    "role_indicator": {
                        "game_role_id": "100",
                        "global_role_id": "global-100",
                        "role_id": "100",
                        "zone": "电信区",
                    },
                    "role_recent": {
                        "raw_matches": [],
                        "request_size": 40,
                    },
                }
            },
        )

        repo.save_role_recent.assert_not_awaited()

    async def test_warmup_recent_matches_uses_shared_normalization(self):
        """Verify warmup path uses the same normalize_recent_matches as live path."""
        raw_matches = [
            {"pvpType": 2, "match_id": 1, "won": True, "kungfu": "huajian", "match_time": 2000},
            {"pvpType": 3, "match_id": 2, "won": True, "kungfu": "huajian", "match_time": 1000},
        ]
        service = WarmupJjcRankingService(MagicMock())
        object.__setattr__(service, "inspect_repo", MagicMock())
        repo = service._inspect_cache()
        repo.save_role_recent = AsyncMock()
        repo.save_role_indicator = AsyncMock()
        repo.save_match_detail = AsyncMock()

        await service._warmup_inspect_cache_from_kungfu_detail(
            server="梦江南",
            name="示例角色",
            kungfu_detail={
                "_cache_warmup": {
                    "role_indicator": {
                        "game_role_id": "100",
                        "global_role_id": "global-100",
                        "role_id": "100",
                        "zone": "电信区",
                    },
                    "role_recent": {
                        "raw_matches": raw_matches,
                        "request_size": 40,
                    },
                }
            },
        )

        data = repo.save_role_recent.await_args[0][2]["data"]
        recent = data["recent_matches"]
        self.assertEqual(len(recent), 1)  # pvpType=2 filtered out
        self.assertEqual(recent[0]["match_id"], 2)

    async def test_pipeline_kungfu_detail_to_warmup_recent(self):
        """Pipeline: get_kungfu_detail_by_role_info → _warmup_inspect_cache_from_kungfu_detail."""
        from src.services.jx3.kungfu import get_kungfu_detail_by_role_info

        matches = [
            {"pvpType": 3, "matchId": 10, "won": True, "kungfu": "huajian", "match_time": 1700000100, "avgGrade": 12, "totalMmr": 1800},
            {"pvpType": 0, "matchId": 11, "won": False, "kungfu": "bingxinjue", "match_time": 1700000200},
            {"pvpType": 2, "matchId": 12, "won": True, "kungfu": "huajian", "match_time": 1700000300},
            {"pvpType": 3, "matchId": 13, "won": True, "kungfu": "huajian", "match_time": 1700000400, "avgGrade": 14},
        ]
        responses = [
            {
                "code": 0, "msg": "success",
                "data": {
                    "role_info": {"role_id": "rid_1", "global_role_id": "SK01-g"},
                    "indicator": [
                        {"type": "3c", "metrics": [{"pvp_type": 3, "win_count": 10, "total_count": 20}], "performance": {"mmr": 2500}},
                    ],
                },
            },
            {"code": 0, "msg": "success", "data": matches},
        ]
        call_count = [0]

        def fake_request(url, params):
            idx = call_count[0]
            call_count[0] += 1
            return responses[idx]

        kungfu_detail = get_kungfu_detail_by_role_info(
            "rid_1", "zone1", "server1",
            tuilan_request=fake_request,
            kungfu_pinyin_to_chinese={"huajian": "花间游"},
        )

        self.assertIsNotNone(kungfu_detail)
        cache_warmup = kungfu_detail.get("_cache_warmup")
        self.assertIsInstance(cache_warmup, dict)
        self.assertIn("role_recent", cache_warmup)

        inspect_repo = FakeWarmupInspectRepo()
        service = WarmupJjcRankingService(inspect_repo)

        await service._warmup_inspect_cache_from_kungfu_detail(
            server="梦江南",
            name="示例角色",
            kungfu_detail=kungfu_detail,
        )

        self.assertEqual(len(inspect_repo.saved_role_recent), 1)
        server, name, payload = inspect_repo.saved_role_recent[0]
        self.assertEqual(server, "梦江南")
        self.assertEqual(name, "示例角色")
        data = payload["data"]
        self.assertIn("recent_matches", data)
        recent = data["recent_matches"]
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0]["match_id"], 13)
        self.assertEqual(recent[1]["match_id"], 10)
        self.assertEqual(recent[0]["kungfu"], "花间游")
        self.assertEqual(recent[0]["avg_grade"], 14)
        self.assertFalse(data["pagination"]["has_more"])


if __name__ == "__main__":
    unittest.main()

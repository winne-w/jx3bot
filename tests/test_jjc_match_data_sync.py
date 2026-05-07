import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from src.services.jx3.jjc_match_data_sync import (
    JjcMatchDataSyncService,
    extract_identity_from_person_history,
    extract_history_items,
    extract_players_from_detail,
)


async def _noop_sleep() -> None:
    return None


class SleepCounter:
    def __init__(self) -> None:
        self.count = 0

    async def __call__(self) -> None:
        self.count += 1


class FakeRepo:
    def __init__(self) -> None:
        self.paused = False
        self.roles: List[Dict[str, Any]] = []
        self.saved_matches: List[int] = []
        self.failed_matches: List[int] = []
        self.unavailable_matches: List[int] = []
        self.failed_messages: Dict[int, str] = {}
        self.upserted_roles: List[Dict[str, Any]] = []
        self.discovered_matches: List[Dict[str, Any]] = []
        self.success_release: Optional[Dict[str, Any]] = None
        self.failure_release: Optional[Dict[str, Any]] = None
        self.identity_updates: List[Dict[str, Any]] = []
        self.claim_detail_skips: set = set()

    async def get_paused(self) -> bool:
        return self.paused

    async def recover_expired_leases(self) -> int:
        return 2

    async def claim_next_roles(self, **kwargs: Any) -> List[Dict[str, Any]]:
        return self.roles

    async def mark_match_discovered(self, **kwargs: Any) -> bool:
        self.discovered_matches.append(kwargs)
        return True

    async def claim_match_detail(self, match_id: int, **kwargs: Any) -> Optional[Dict[str, Any]]:
        if match_id in self.saved_matches or match_id in self.claim_detail_skips:
            return None
        return {"match_id": match_id}

    async def mark_match_detail_saved(self, match_id: int) -> bool:
        self.saved_matches.append(match_id)
        return True

    async def mark_match_detail_failed(self, match_id: int, error_message: str = "") -> bool:
        self.failed_matches.append(match_id)
        self.failed_messages[match_id] = error_message
        return True

    async def mark_match_detail_unavailable(self, match_id: int, reason: str = "", code: int = 0) -> bool:
        self.unavailable_matches.append(match_id)
        return True

    async def upsert_role(self, **kwargs: Any) -> str:
        self.upserted_roles.append(kwargs)
        return "global:" + str(kwargs.get("global_role_id"))

    async def release_role_success(self, **kwargs: Any) -> None:
        self.success_release = kwargs

    async def release_role_failure(self, identity_key: str, error_message: str = "") -> None:
        self.failure_release = {"identity_key": identity_key, "error_message": error_message}

    async def update_role_identity_fields(self, **kwargs: Any) -> bool:
        self.identity_updates.append(kwargs)
        return True


class FakeHistoryClient:
    def __init__(self, pages: List[Dict[str, Any]]) -> None:
        self.pages = pages
        self.calls: List[Dict[str, Any]] = []

    def get_mine_match_history(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        return self.pages[index] if index < len(self.pages) else {"data": []}


class FakePersonHistoryClient:
    def __init__(self, pages: List[Dict[str, Any]]) -> None:
        self.pages = pages
        self.calls: List[Dict[str, Any]] = []

    def get_person_match_history(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        return self.pages[index] if index < len(self.pages) else {"data": []}


class FakeInspectService:
    def __init__(self, errors: Optional[set] = None, unavailable: Optional[set] = None,
                 transient_failures: Optional[Dict[int, int]] = None) -> None:
        self.errors = errors or set()
        self.unavailable = unavailable or set()
        self.transient_failures = transient_failures or {}
        self.calls: List[int] = []
        self.call_counts: Dict[int, int] = {}
        self.identity_calls: List[Dict[str, Any]] = []
        self.identity_result: Optional[Dict[str, Any]] = None

    async def _resolve_role_identity(
        self,
        *,
        server: str,
        name: str,
        identity_hints: Dict[str, Any],
    ) -> Dict[str, Any]:
        self.identity_calls.append({
            "server": server,
            "name": name,
            "identity_hints": identity_hints,
        })
        return self.identity_result or {"error": True, "message": "role_identity_not_found"}

    async def get_match_detail(self, *, match_id: int) -> Dict[str, Any]:
        self.calls.append(match_id)
        self.call_counts[match_id] = self.call_counts.get(match_id, 0) + 1
        call_num = self.call_counts[match_id]
        transient_remaining = self.transient_failures.get(match_id, 0)
        if call_num <= transient_remaining:
            raise RuntimeError("transient_detail_down")
        if match_id in self.errors:
            return {"error": True, "message": "detail down"}
        if match_id in self.unavailable:
            return {"match_id": match_id, "detail": None}
        return {
            "match_id": match_id,
            "detail": {
                "team1": {
                    "players_info": [
                        {
                            "role_name": "角色A",
                            "global_role_id": "gid-a",
                            "role_id": "rid-a",
                            "zone": "zone-a",
                            "server": "梦江南",
                        }
                    ]
                },
                "team2": {"players_info": []},
            },
        }


class FakeIdentityRepo:
    def __init__(self) -> None:
        self.upserted: List[Dict[str, Any]] = []

    async def upsert_from_match_detail(self, **kwargs: Any) -> Dict[str, Any]:
        self.upserted.append(kwargs)
        return kwargs


class TestExtractHistoryItems(unittest.TestCase):
    def test_extracts_nested_list_shapes(self) -> None:
        self.assertEqual(extract_history_items({"data": [{"id": 1}]}), [{"id": 1}])
        self.assertEqual(extract_history_items({"data": {"list": [{"id": 2}]}}), [{"id": 2}])
        self.assertEqual(extract_history_items({"data": {"items": [{"id": 3}]}}), [{"id": 3}])

    def test_extract_players_uses_identity_fallbacks(self) -> None:
        players = extract_players_from_detail({
            "team1": {
                "players_info": [
                    {"role_name": "A", "server": "梦江南", "zone": "z1", "role_id": "r1"},
                    {"role_name": "A", "server": "梦江南", "zone": "z1", "role_id": "r1"},
                    {"role_name": "B", "server": "梦江南"},
                ]
            }
        })

        self.assertEqual(len(players), 2)
        self.assertEqual(players[0]["role_id"], "r1")
        self.assertEqual(players[1]["role_name"], "B")

    def test_extract_identity_from_person_history_prefers_matching_person(self) -> None:
        identity = extract_identity_from_person_history(
            {
                "data": [
                    {"person_id": "other", "global_role_id": "gid-other"},
                    {
                        "person_id": "pid-a",
                        "global_role_id": "gid-a",
                        "role_name": "角色A",
                        "server": "梦江南",
                        "zone": "电信区",
                    },
                ]
            },
            "pid-a",
        )

        self.assertEqual(identity["global_role_id"], "gid-a")
        self.assertEqual(identity["role_name"], "角色A")
        self.assertEqual(identity["source"], "person_history")


class TestJjcMatchDataSyncService(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        patcher = patch(
            "src.services.jx3.jjc_match_data_sync.asyncio.to_thread",
            new=self._run_to_thread_inline,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _run_to_thread_inline(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    async def test_run_once_paused_does_not_claim_roles(self) -> None:
        repo = FakeRepo()
        repo.paused = True
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=FakeHistoryClient([]),
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        result = await service.run_once()

        self.assertFalse(result["error"])
        self.assertTrue(result["paused"])
        self.assertEqual(result["processed_roles"], 0)
        self.assertEqual(result["recovered_leases"], 0)

    async def test_enqueue_players_from_detail_uses_match_detail_source(self) -> None:
        repo = FakeRepo()
        identity_repo = FakeIdentityRepo()
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            identity_repo=identity_repo,
            sleep_func=_noop_sleep,
        )

        await service._enqueue_players_from_detail({
            "team1": {
                "players_info": [
                    {
                        "role_name": "角色A",
                        "global_role_id": "gid-a",
                        "role_id": "rid-a",
                        "zone": "zone-a",
                        "server": "梦江南",
                    }
                ]
            },
            "team2": {"players_info": []},
        })

        self.assertEqual(repo.upserted_roles[0]["source"], "match_detail")
        self.assertEqual(repo.upserted_roles[0]["global_role_id"], "gid-a")
        self.assertEqual(repo.upserted_roles[0]["priority"], -10)
        self.assertEqual(identity_repo.upserted[0]["global_role_id"], "gid-a")
        self.assertEqual(identity_repo.upserted[0]["role_id"], "rid-a")

    async def test_enqueue_players_from_detail_backfills_global_role_id_from_person_history(self) -> None:
        repo = FakeRepo()
        identity_repo = FakeIdentityRepo()
        person_history = FakePersonHistoryClient([
            {
                "data": [
                    {
                        "person_id": "pid-a",
                        "global_role_id": "gid-a",
                        "role_name": "角色A",
                        "server": "梦江南",
                        "zone": "电信区",
                    }
                ]
            }
        ])
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            identity_repo=identity_repo,
            person_match_history_client=person_history,
            sleep_func=_noop_sleep,
        )

        await service._enqueue_players_from_detail({
            "team1": {
                "players_info": [
                    {
                        "role_name": "角色A",
                        "global_role_id": "",
                        "role_id": "",
                        "person_id": "pid-a",
                        "server": "梦江南",
                    }
                ]
            }
        })

        self.assertEqual(person_history.calls[0]["person_id"], "pid-a")
        self.assertEqual(repo.upserted_roles[0]["global_role_id"], "gid-a")
        self.assertEqual(repo.upserted_roles[0]["person_id"], "pid-a")
        self.assertEqual(identity_repo.upserted[0]["global_role_id"], "gid-a")
        self.assertEqual(identity_repo.upserted[0]["person_id"], "pid-a")

    async def test_full_sync_reaches_season_start_and_releases_success(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "identity_key": "global:seed",
            "server": "梦江南",
            "name": "种子",
            "global_role_id": "seed",
        }]
        history = FakeHistoryClient([
            {"data": [
                {"match_id": 1, "match_time": 1810000000, "pvpType": 3},
                {"match_id": 2, "match_time": 1776959999, "pvpType": 3},
            ]}
        ])
        sleep = SleepCounter()
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(),
            sleep_func=sleep,
        )

        result = await service.run_once(mode="full")

        self.assertFalse(result["error"])
        self.assertEqual(result["processed_roles"], 1)
        self.assertEqual(result["discovered_matches"], 1)
        self.assertEqual(result["saved_details"], 1)
        self.assertIsNotNone(repo.success_release)
        self.assertEqual(repo.success_release["identity_key"], "global:seed")
        self.assertTrue(repo.success_release["full_synced_until_time"])
        self.assertTrue(repo.success_release["history_exhausted"])
        self.assertIsNone(repo.failure_release)
        self.assertGreaterEqual(sleep.count, 2)

    async def test_incremental_sync_stops_at_watermark(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "identity_key": "global:seed",
            "server": "梦江南",
            "name": "种子",
            "global_role_id": "seed",
            "full_synced_until_time": 1810000000,
        }]
        history = FakeHistoryClient([
            {"data": [
                {"match_id": 10, "match_time": 1810000100, "pvpType": 3},
                {"match_id": 11, "match_time": 1810000000, "pvpType": 3},
            ]}
        ])
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        result = await service.run_once(mode="incremental")

        self.assertFalse(result["error"])
        self.assertEqual([item["match_id"] for item in repo.discovered_matches], [10])
        self.assertEqual(result["saved_details"], 1)
        self.assertIsNotNone(repo.success_release)
        self.assertEqual(repo.success_release["oldest_synced_match_time"], 1810000000)
        self.assertEqual(len(history.calls), 1)

    async def test_detail_failure_does_not_fail_role_continues_to_success(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "identity_key": "global:seed",
            "server": "梦江南",
            "name": "种子",
            "global_role_id": "seed",
        }]
        history = FakeHistoryClient([
            {"data": [{"match_id": 20, "match_time": 1810000000, "pvpType": 3}]}
        ])
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(errors={20}),
            sleep_func=_noop_sleep,
        )

        result = await service.run_once()

        self.assertFalse(result["error"])
        self.assertEqual(result["failed_roles"], 0)
        self.assertEqual(result["failed_details"], 1)
        self.assertIsNotNone(repo.success_release)
        self.assertIsNone(repo.failure_release)
        self.assertIn(20, repo.failed_matches)

    async def test_detail_transient_failure_retries_then_succeeds(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "identity_key": "global:seed",
            "server": "梦江南",
            "name": "种子",
            "global_role_id": "seed",
        }]
        history = FakeHistoryClient([
            {"data": [{"match_id": 50, "match_time": 1810000000, "pvpType": 3}]}
        ])
        sleep = SleepCounter()
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(transient_failures={50: 2}),
            sleep_func=sleep,
        )

        result = await service.run_once()

        self.assertFalse(result["error"])
        self.assertEqual(result["failed_roles"], 0)
        self.assertEqual(result["saved_details"], 1)
        self.assertEqual(result["failed_details"], 0)
        self.assertEqual(50, repo.saved_matches[0])
        self.assertIsNotNone(repo.success_release)
        self.assertIsNone(repo.failure_release)

    async def test_detail_transient_failure_exhausted_marks_failed(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "identity_key": "global:seed",
            "server": "梦江南",
            "name": "种子",
            "global_role_id": "seed",
        }]
        history = FakeHistoryClient([
            {"data": [{"match_id": 55, "match_time": 1810000000, "pvpType": 3}]}
        ])
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(transient_failures={55: 3}),
            sleep_func=_noop_sleep,
        )

        result = await service.run_once()

        self.assertFalse(result["error"])
        self.assertEqual(result["failed_roles"], 0)
        self.assertEqual(result["failed_details"], 1)
        self.assertEqual(result["saved_details"], 0)
        self.assertIn(55, repo.failed_matches)
        self.assertIn("transient_detail_down", repo.failed_messages.get(55, ""))
        self.assertIsNotNone(repo.success_release)
        self.assertIsNone(repo.failure_release)

    async def test_unavailable_detail_marks_unavailable_without_player_enqueue(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "identity_key": "global:seed",
            "server": "梦江南",
            "name": "种子",
            "global_role_id": "seed",
        }]
        history = FakeHistoryClient([
            {"data": [{"match_id": 60, "match_time": 1810000000, "pvpType": 3}]}
        ])
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(unavailable={60}),
            sleep_func=_noop_sleep,
        )

        result = await service.run_once()

        self.assertFalse(result["error"])
        self.assertEqual(result["failed_roles"], 0)
        self.assertEqual(result["unavailable_details"], 1)
        self.assertEqual(result["saved_details"], 0)
        self.assertEqual(repo.upserted_roles, [])
        self.assertIn(60, repo.unavailable_matches)
        self.assertNotIn(60, repo.failed_matches)
        self.assertIsNotNone(repo.success_release)
        self.assertIsNone(repo.failure_release)

    async def test_run_once_aggregates_failed_and_unavailable_details(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "identity_key": "global:seed",
            "server": "梦江南",
            "name": "种子",
            "global_role_id": "seed",
        }]
        history = FakeHistoryClient([
            {"data": [
                {"match_id": 70, "match_time": 1810003000, "pvpType": 3},
                {"match_id": 71, "match_time": 1810002000, "pvpType": 3},
                {"match_id": 72, "match_time": 1810001000, "pvpType": 3},
            ]}
        ])
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(errors={70}, unavailable={71}),
            sleep_func=_noop_sleep,
        )

        result = await service.run_once()

        self.assertFalse(result["error"])
        self.assertEqual(result["failed_roles"], 0)
        self.assertEqual(result["failed_details"], 1)
        self.assertEqual(result["unavailable_details"], 1)
        self.assertEqual(result["saved_details"], 1)
        self.assertEqual(result["discovered_matches"], 3)
        self.assertIsNotNone(repo.success_release)

    async def test_failed_detail_continues_to_next_page(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "identity_key": "global:seed",
            "server": "梦江南",
            "name": "种子",
            "global_role_id": "seed",
        }]
        history = FakeHistoryClient([
            {"data": [
                {"match_id": 80, "match_time": 1810003000, "pvpType": 3},
                {"match_id": 81, "match_time": 1810002000, "pvpType": 3},
            ]},
            {"data": [
                {"match_id": 82, "match_time": 1810001000, "pvpType": 3},
            ]}
        ])
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(errors={80}),
            sleep_func=_noop_sleep,
            page_size=2,
        )

        result = await service.run_once()

        self.assertFalse(result["error"])
        self.assertEqual(result["failed_roles"], 0)
        self.assertEqual(result["failed_details"], 1)
        self.assertEqual(result["saved_details"], 2)
        self.assertEqual(len(history.calls), 2)
        self.assertIsNotNone(repo.success_release)
        self.assertIsNone(repo.failure_release)

    async def test_existing_detail_claim_is_skipped(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "identity_key": "global:seed",
            "server": "梦江南",
            "name": "种子",
            "global_role_id": "seed",
        }]
        repo.claim_detail_skips.add(30)
        inspect_service = FakeInspectService()
        history = FakeHistoryClient([
            {"data": [{"match_id": 30, "match_time": 1810000000, "pvpType": 3}]}
        ])
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=inspect_service,
            sleep_func=_noop_sleep,
        )

        result = await service.run_once()

        self.assertFalse(result["error"])
        self.assertEqual(result["skipped_details"], 1)
        self.assertEqual(inspect_service.calls, [])
        self.assertIsNotNone(repo.success_release)

    async def test_history_error_fails_role(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "identity_key": "global:seed",
            "server": "梦江南",
            "name": "种子",
            "global_role_id": "seed",
        }]
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=FakeHistoryClient([{"error": "history down"}]),
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        result = await service.run_once()

        self.assertFalse(result["error"])
        self.assertEqual(result["failed_roles"], 1)
        self.assertIsNone(repo.success_release)
        self.assertIn("history down", repo.failure_release["error_message"])

    async def test_missing_global_role_id_is_resolved_before_history_request(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "identity_key": "name:梦江南:种子",
            "server": "梦江南",
            "name": "种子",
            "role_id": "rid",
            "zone": "zone-a",
        }]
        history = FakeHistoryClient([
            {"data": [{"match_id": 40, "match_time": 1810000000, "pvpType": 3}]}
        ])
        inspect_service = FakeInspectService()
        identity_repo = FakeIdentityRepo()
        inspect_service.identity_result = {
            "global_role_id": "gid-resolved",
            "role_id": "rid",
            "game_role_id": "rid",
            "zone": "zone-a",
            "source": "test_identity",
        }
        sleep = SleepCounter()
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=inspect_service,
            identity_repo=identity_repo,
            sleep_func=sleep,
        )

        result = await service.run_once()

        self.assertFalse(result["error"])
        self.assertEqual(result["failed_roles"], 0)
        self.assertEqual(history.calls[0]["global_role_id"], "gid-resolved")
        self.assertEqual(repo.identity_updates[0]["global_role_id"], "gid-resolved")
        self.assertEqual(repo.identity_updates[0]["identity_key"], "name:梦江南:种子")
        self.assertEqual(identity_repo.upserted[0]["global_role_id"], "gid-resolved")
        self.assertGreaterEqual(sleep.count, 3)

    async def test_missing_global_role_id_uses_person_history_before_inspect_resolver(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "identity_key": "name:梦江南:种子",
            "server": "梦江南",
            "name": "种子",
            "person_id": "pid-a",
        }]
        history = FakeHistoryClient([
            {"data": [{"match_id": 41, "match_time": 1810000000, "pvpType": 3}]}
        ])
        person_history = FakePersonHistoryClient([
            {
                "data": [
                    {
                        "person_id": "pid-a",
                        "global_role_id": "gid-person",
                        "role_name": "种子",
                        "server": "梦江南",
                        "zone": "电信区",
                    }
                ]
            }
        ])
        inspect_service = FakeInspectService()
        identity_repo = FakeIdentityRepo()
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            person_match_history_client=person_history,
            inspect_service=inspect_service,
            identity_repo=identity_repo,
            sleep_func=_noop_sleep,
        )

        result = await service.run_once()

        self.assertFalse(result["error"])
        self.assertEqual(history.calls[0]["global_role_id"], "gid-person")
        self.assertEqual(inspect_service.identity_calls, [])
        self.assertEqual(repo.identity_updates[0]["global_role_id"], "gid-person")
        self.assertEqual(repo.identity_updates[0]["person_id"], "pid-a")

    async def test_match_detail_identity_uses_match_time_as_observed_at(self) -> None:
        repo = FakeRepo()
        identity_repo = FakeIdentityRepo()
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            identity_repo=identity_repo,
            sleep_func=_noop_sleep,
        )

        await service._enqueue_players_from_detail(
            {
                "match_time": 1810000000,
                "team1": {
                    "players_info": [
                        {
                            "role_name": "角色A",
                            "global_role_id": "gid-a",
                            "role_id": "rid-a",
                            "zone": "zone-a",
                            "server": "梦江南",
                        }
                    ]
                },
            }
        )

        self.assertEqual(
            int(identity_repo.upserted[0]["observed_at"].timestamp()),
            1810000000,
        )

    async def test_identity_resolution_failure_fails_role_before_history_request(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "identity_key": "name:梦江南:种子",
            "server": "梦江南",
            "name": "种子",
        }]
        history = FakeHistoryClient([])
        inspect_service = FakeInspectService()
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=inspect_service,
            sleep_func=_noop_sleep,
        )

        result = await service.run_once()

        self.assertFalse(result["error"])
        self.assertEqual(result["failed_roles"], 1)
        self.assertEqual(history.calls, [])
        self.assertIn("缺少 global_role_id", repo.failure_release["error_message"])

    async def test_add_role_with_identity_fields_writes_role_identity_table(self) -> None:
        repo = FakeRepo()
        identity_repo = FakeIdentityRepo()
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            identity_repo=identity_repo,
            sleep_func=_noop_sleep,
        )

        result = await service.add_role(
            server="梦江南",
            name="角色A",
            global_role_id="gid-a",
            role_id="rid-a",
            zone="zone-a",
        )

        self.assertFalse(result["error"])
        self.assertEqual(identity_repo.upserted[0]["server"], "梦江南")
        self.assertEqual(identity_repo.upserted[0]["name"], "角色A")
        self.assertEqual(identity_repo.upserted[0]["global_role_id"], "gid-a")
        self.assertEqual(identity_repo.upserted[0]["game_role_id"], "rid-a")


if __name__ == "__main__":
    unittest.main()

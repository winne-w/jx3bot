import asyncio
import time
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from src.services.jx3.jjc_match_data_sync import (
    JjcSyncMatchDetailClaimError,
    JjcSyncStaleLeaseError,
    JjcMatchDataSyncService,
    extract_history_items,
    extract_players_from_detail,
    normalize_role_name,
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
        self.enqueued_roles: List[Dict[str, Any]] = []
        self.claimed_queued_role: Optional[Dict[str, Any]] = None
        self.enqueue_next_roles_calls: List[Dict[str, Any]] = []
        self.interrupted_release: Optional[Dict[str, Any]] = None
        self.pause_reason: str = ""
        self.worker_heartbeats: List[Dict[str, Any]] = []
        self.role_lease_renewals: List[Dict[str, Any]] = []
        self.renew_role_lease_result = True
        self.identity_update_result: Any = ...
        self.detail_saved_calls: List[Dict[str, Any]] = []
        self.detail_failed_calls: List[Dict[str, Any]] = []
        self.detail_unavailable_calls: List[Dict[str, Any]] = []
        self.mark_detail_saved_result = True
        self.mark_detail_failed_result = True
        self.mark_detail_unavailable_result = True
        self.detail_lease_renewals: List[Dict[str, Any]] = []
        self.renew_match_detail_lease_result = True
        self.upsert_role_exception: Optional[Exception] = None
        self.events: List[str] = []
        self.workers: List[Dict[str, Any]] = []
        self.claim_match_detail_exception: Optional[Exception] = None
        self.registered_workers: List[Dict[str, Any]] = []
        self.stopped_workers: List[Dict[str, Any]] = []
        self.detail_states: Dict[int, Dict[str, Any]] = {}
        self.released_match_details: List[Dict[str, Any]] = []
        self.identity_lease_renewals: List[Dict[str, Any]] = []
        self.identity_success_release: Optional[Dict[str, Any]] = None
        self.identity_failure_release: Optional[Dict[str, Any]] = None
        self.identity_interrupted_release: Optional[Dict[str, Any]] = None
        self.renew_identity_lease_result = True

    def _find_role(self, identity_key: str) -> Optional[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        if self.claimed_queued_role is not None:
            candidates.append(self.claimed_queued_role)
        candidates.extend(self.roles)
        for role in candidates:
            if role.get("identity_key") == identity_key:
                return role
        return None

    def _role_lease_allows(self, identity_key: str, lease_owner: Optional[str]) -> bool:
        if lease_owner is None:
            return True
        role = self._find_role(identity_key)
        if role is None:
            return False
        if role.get("status") != "syncing" or role.get("lease_owner") != lease_owner:
            return False
        expires_at = role.get("lease_expires_at")
        if expires_at is not None and expires_at <= time.time():
            return False
        return True

    def _detail_lease_allows(self, match_id: int, lease_owner: Optional[str]) -> bool:
        if lease_owner is None:
            return True
        state = self.detail_states.get(match_id)
        if state is None:
            return False
        if state.get("status") != "detail_syncing" or state.get("lease_owner") != lease_owner:
            return False
        expires_at = state.get("lease_expires_at")
        if expires_at is not None and expires_at <= time.time():
            return False
        return True

    async def get_paused(self) -> bool:
        return self.paused

    async def get_pause_state(self) -> Dict[str, Any]:
        return {"paused": self.paused, "reason": self.pause_reason, "updated_at": 123.0}

    async def set_paused(self, paused: bool, reason: str = "") -> bool:
        self.paused = paused
        self.pause_reason = reason
        return True

    async def recover_expired_leases(self) -> int:
        return 2

    async def list_workers(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self.workers[:limit]

    async def claim_next_roles(self, **kwargs: Any) -> List[Dict[str, Any]]:
        return self.roles

    async def count_by_status(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for role in self.roles:
            status = role.get("status") or "pending"
            counts[status] = counts.get(status, 0) + 1
        if self.claimed_queued_role:
            counts["syncing"] = counts.get("syncing", 0) + 1
        return counts

    async def get_recent_errors(self, limit: int = 5) -> List[Dict[str, Any]]:
        return []

    async def enqueue_next_roles(self, **kwargs: Any) -> List[Dict[str, Any]]:
        self.enqueue_next_roles_calls.append(kwargs)
        self.enqueued_roles = self.roles[:kwargs.get("limit", len(self.roles))]
        return self.enqueued_roles

    async def claim_queued_role(self, **kwargs: Any) -> Optional[Dict[str, Any]]:
        lease_owner = kwargs.get("lease_owner")
        lease_seconds = kwargs.get("lease_seconds", 600)
        if self.claimed_queued_role is not None:
            role = self.claimed_queued_role
            if role.get("status") != "queued":
                return None
            role["status"] = "syncing"
            role["lease_owner"] = lease_owner
            role["lease_expires_at"] = time.time() + lease_seconds
            return role
        for role in self.roles:
            if role.get("status") == "queued":
                role["status"] = "syncing"
                role["lease_owner"] = lease_owner
                role["lease_expires_at"] = time.time() + lease_seconds
                return role
        return None

    async def release_role_interrupted(
        self,
        identity_key: str,
        reason: str,
        requeue: bool = True,
        lease_owner: Optional[str] = None,
    ) -> bool:
        self.interrupted_release = {
            "identity_key": identity_key,
            "reason": reason,
            "requeue": requeue,
            "lease_owner": lease_owner,
        }
        if not self._role_lease_allows(identity_key, lease_owner):
            return False
        role = self._find_role(identity_key)
        if role is not None:
            role["status"] = "queued" if requeue else "pending"
            role["lease_owner"] = None
            role["lease_expires_at"] = None
        return True

    async def renew_role_lease(self, **kwargs: Any) -> bool:
        self.role_lease_renewals.append(kwargs)
        if not self.renew_role_lease_result:
            return False
        identity_key = kwargs.get("identity_key")
        lease_owner = kwargs.get("lease_owner")
        if identity_key and not self._role_lease_allows(identity_key, lease_owner):
            return False
        role = self._find_role(identity_key) if identity_key else None
        if role is not None:
            role["lease_expires_at"] = time.time() + kwargs.get("lease_seconds", 600)
        return True

    async def renew_identity_lease(self, **kwargs: Any) -> bool:
        self.identity_lease_renewals.append(kwargs)
        return self.renew_identity_lease_result

    async def renew_match_detail_lease(self, **kwargs: Any) -> bool:
        self.detail_lease_renewals.append(kwargs)
        if not self.renew_match_detail_lease_result:
            return False
        match_id = kwargs.get("match_id")
        lease_owner = kwargs.get("lease_owner")
        if match_id is not None and not self._detail_lease_allows(match_id, lease_owner):
            return False
        state = self.detail_states.get(match_id)
        if state is not None:
            state["lease_expires_at"] = time.time() + kwargs.get("lease_seconds", 600)
        return True

    async def register_worker(self, **kwargs: Any) -> bool:
        self.registered_workers.append(kwargs)
        return True

    async def heartbeat_worker(self, **kwargs: Any) -> bool:
        self.worker_heartbeats.append(kwargs)
        return True

    async def stop_worker(self, **kwargs: Any) -> bool:
        self.stopped_workers.append(kwargs)
        return True

    async def mark_match_discovered(self, **kwargs: Any) -> bool:
        self.discovered_matches.append(kwargs)
        return True

    async def claim_match_detail(self, match_id: int, **kwargs: Any) -> Optional[Dict[str, Any]]:
        if self.claim_match_detail_exception is not None:
            raise self.claim_match_detail_exception
        if match_id in self.saved_matches or match_id in self.claim_detail_skips:
            return None
        state = self.detail_states.get(match_id)
        if state is not None:
            status = state.get("status")
            retry_after = state.get("detail_retry_after")
            claimable = status == "discovered" or (
                status == "failed" and (retry_after is None or retry_after <= time.time())
            )
            if not claimable:
                return None
        else:
            state = {"match_id": match_id, "status": "discovered"}
            self.detail_states[match_id] = state
        state["status"] = "detail_syncing"
        state["lease_owner"] = kwargs.get("lease_owner")
        state["lease_expires_at"] = time.time() + kwargs.get("lease_seconds", 600)
        return dict(state)

    async def get_match_detail_sync_state(self, match_id: int) -> Dict[str, Any]:
        if match_id in self.detail_states:
            state = dict(self.detail_states[match_id])
            status = str(state.get("status") or "")
            terminal = bool(state.get("terminal")) or status in ("detail_saved", "detail_unavailable")
            retry_after = state.get("detail_retry_after")
            claimable = status == "discovered" or (
                status == "failed" and (retry_after is None or retry_after <= time.time())
            )
            state["terminal"] = terminal
            state["claimable"] = claimable
            state.setdefault("action", "skip" if terminal else "claimable" if claimable else "interrupt")
            return state
        if match_id in self.saved_matches:
            return {"exists": True, "status": "detail_saved", "action": "skip", "terminal": True, "claimable": False}
        if match_id in self.unavailable_matches:
            return {"exists": True, "status": "detail_unavailable", "action": "skip", "terminal": True, "claimable": False}
        if match_id in self.claim_detail_skips:
            return {"exists": True, "status": "detail_syncing", "action": "interrupt", "terminal": False, "claimable": False}
        return {"exists": False, "status": "missing", "action": "interrupt", "terminal": False, "claimable": False}

    async def release_match_detail_interrupted(
        self,
        match_id: int,
        reason: str = "",
        lease_owner: Optional[str] = None,
    ) -> bool:
        self.released_match_details.append({
            "match_id": match_id,
            "reason": reason,
            "lease_owner": lease_owner,
        })
        if not self._detail_lease_allows(match_id, lease_owner):
            return False
        state = self.detail_states.get(match_id)
        if state is not None:
            state["status"] = "discovered"
            state["lease_owner"] = None
            state["lease_expires_at"] = None
        return True

    async def mark_match_detail_saved(self, match_id: int, lease_owner: Optional[str] = None) -> bool:
        self.events.append("mark_saved")
        self.detail_saved_calls.append({"match_id": match_id, "lease_owner": lease_owner})
        if not self.mark_detail_saved_result or not self._detail_lease_allows(match_id, lease_owner):
            return False
        state = self.detail_states.setdefault(match_id, {"match_id": match_id})
        state["status"] = "detail_saved"
        state["lease_owner"] = None
        state["lease_expires_at"] = None
        self.saved_matches.append(match_id)
        return True

    async def mark_match_detail_failed(
        self,
        match_id: int,
        error_message: str = "",
        lease_owner: Optional[str] = None,
    ) -> bool:
        self.events.append("mark_failed")
        self.detail_failed_calls.append({
            "match_id": match_id,
            "error_message": error_message,
            "lease_owner": lease_owner,
        })
        if not self.mark_detail_failed_result or not self._detail_lease_allows(match_id, lease_owner):
            return False
        state = self.detail_states.setdefault(match_id, {"match_id": match_id})
        state["status"] = "failed"
        state["lease_owner"] = None
        state["lease_expires_at"] = None
        self.failed_matches.append(match_id)
        self.failed_messages[match_id] = error_message
        return True

    async def mark_match_detail_unavailable(
        self,
        match_id: int,
        reason: str = "",
        code: int = 0,
        lease_owner: Optional[str] = None,
    ) -> bool:
        self.events.append("mark_unavailable")
        self.detail_unavailable_calls.append({
            "match_id": match_id,
            "reason": reason,
            "code": code,
            "lease_owner": lease_owner,
        })
        if not self.mark_detail_unavailable_result or not self._detail_lease_allows(match_id, lease_owner):
            return False
        state = self.detail_states.setdefault(match_id, {"match_id": match_id})
        state["status"] = "detail_unavailable"
        state["lease_owner"] = None
        state["lease_expires_at"] = None
        self.unavailable_matches.append(match_id)
        return True

    async def upsert_role(self, **kwargs: Any) -> str:
        self.events.append("upsert_role")
        if self.upsert_role_exception is not None:
            raise self.upsert_role_exception
        self.upserted_roles.append(kwargs)
        return "global:" + str(kwargs.get("global_role_id"))

    async def release_role_success(self, **kwargs: Any) -> bool:
        self.success_release = kwargs
        identity_key = kwargs.get("identity_key")
        lease_owner = kwargs.get("lease_owner")
        if identity_key and not self._role_lease_allows(identity_key, lease_owner):
            return False
        role = self._find_role(identity_key) if identity_key else None
        if role is not None:
            role["status"] = "exhausted" if kwargs.get("history_exhausted") else "cooldown"
            role["lease_owner"] = None
            role["lease_expires_at"] = None
        return True

    async def release_identity_success(self, **kwargs: Any) -> bool:
        self.identity_success_release = kwargs
        return True

    async def release_role_failure(
        self,
        identity_key: str,
        error_message: str = "",
        lease_owner: Optional[str] = None,
    ) -> bool:
        self.failure_release = {
            "identity_key": identity_key,
            "error_message": error_message,
            "lease_owner": lease_owner,
        }
        if not self._role_lease_allows(identity_key, lease_owner):
            return False
        role = self._find_role(identity_key)
        if role is not None:
            role["status"] = "pending"
            role["lease_owner"] = None
            role["lease_expires_at"] = None
        return True

    async def release_identity_failure(
        self,
        identity_id: Any,
        error_message: str = "",
        lease_owner: Optional[str] = None,
    ) -> bool:
        self.identity_failure_release = {
            "identity_id": identity_id,
            "error_message": error_message,
            "lease_owner": lease_owner,
        }
        return True

    async def release_identity_interrupted(
        self,
        identity_id: Any,
        reason: str,
        requeue: bool = True,
        lease_owner: Optional[str] = None,
    ) -> bool:
        self.identity_interrupted_release = {
            "identity_id": identity_id,
            "reason": reason,
            "requeue": requeue,
            "lease_owner": lease_owner,
        }
        return True

    async def update_role_identity_fields(self, **kwargs: Any) -> bool:
        self.identity_updates.append(kwargs)
        return True

    async def update_role_identity_fields_and_key(self, **kwargs: Any) -> Optional[str]:
        self.identity_updates.append(kwargs)
        if self.identity_update_result is not ...:
            return self.identity_update_result
        global_id = str(kwargs.get("global_id") or "").strip()
        new_key = "global_id:" + global_id if global_id else kwargs.get("identity_key")
        old_key = kwargs.get("identity_key")
        role = self._find_role(old_key)
        if role is not None and new_key:
            role["identity_key"] = new_key
        return new_key


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
        self.resolve_calls: List[Dict[str, Any]] = []
        self.resolve_results: Any = {}
        self.resolve_error: Optional[Exception] = None
        self.docs_by_id: Dict[Any, Dict[str, Any]] = {}
        self.get_by_id_calls: List[Any] = []
        self.refresh_indicator_calls: List[Dict[str, Any]] = []

    async def upsert_from_match_detail(self, **kwargs: Any) -> Dict[str, Any]:
        self.upserted.append(kwargs)
        return kwargs

    async def get_by_id(self, identity_id: Any) -> Optional[Dict[str, Any]]:
        self.get_by_id_calls.append(identity_id)
        doc = self.docs_by_id.get(identity_id)
        return dict(doc) if doc is not None else None

    async def refresh_indicator_fields_by_id(self, **kwargs: Any) -> Optional[Dict[str, Any]]:
        self.refresh_indicator_calls.append(kwargs)
        identity_id = kwargs.get("identity_id")
        doc = dict(self.docs_by_id.get(identity_id) or {"_id": identity_id})
        for field_name in (
            "global_role_id",
            "zone",
            "game_role_id",
            "role_id",
            "person_id",
            "server",
            "name",
        ):
            if kwargs.get(field_name) is not None:
                doc[field_name] = kwargs.get(field_name)
        doc["global_role_id_refreshed_at"] = time.time()
        self.docs_by_id[identity_id] = doc
        return dict(doc)

    async def resolve_best_identity(
        self,
        *,
        server: str = "",
        name: str = "",
        zone: str = "",
        game_role_id: str = "",
        global_id: str = "",
        global_role_id: str = "",
    ) -> Dict[str, Any]:
        self.resolve_calls.append({
            "server": server,
            "name": name,
            "zone": zone,
            "game_role_id": game_role_id,
            "global_id": global_id,
            "global_role_id": global_role_id,
        })
        if self.resolve_error is not None:
            raise self.resolve_error
        if isinstance(self.resolve_results, list):
            idx = len(self.resolve_calls) - 1
            return self.resolve_results[idx] if idx < len(self.resolve_results) else {}
        return self.resolve_results


class FakeReplayClient:
    def __init__(self, replay_data: Optional[Dict[str, Any]] = None, error_on_call: bool = False) -> None:
        self.replay_data = replay_data
        self.error_on_call = error_on_call
        self.calls: List[int] = []

    def get_match_replay(self, *, match_id: int) -> Dict[str, Any]:
        self.calls.append(match_id)
        if self.error_on_call:
            raise RuntimeError("replay_down")
        if self.replay_data is not None:
            return self.replay_data
        return {"data": {"players": []}}


class FakeIndicatorClient:
    def __init__(
        self,
        indicator_results: Optional[Dict[str, Dict[str, Any]]] = None,
        error_on_call: bool = False,
    ) -> None:
        self.indicator_results = indicator_results or {}
        self.error_on_call = error_on_call
        self.calls: List[Dict[str, Any]] = []

    def get_role_indicator(self, *, role_id: str, zone: str, server: str) -> Dict[str, Any]:
        key = f"{zone}:{role_id}:{server}"
        self.calls.append({"role_id": role_id, "zone": zone, "server": server})
        if self.error_on_call:
            raise RuntimeError("indicator_down")
        return self.indicator_results.get(key, {})


class FakeProjectionService:
    def __init__(self, events: Optional[List[str]] = None, error: Optional[Exception] = None) -> None:
        self.events = events
        self.error = error
        self.calls: List[Dict[str, Any]] = []

    async def project_payload(self, **kwargs: Any) -> Dict[str, Any]:
        if self.events is not None:
            self.events.append("project_payload")
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {"projected": 1, "queued": 1}


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

    def test_normalize_role_name(self) -> None:
        self.assertEqual(
            normalize_role_name("奈川寺·梦江南", "梦江南"),
            "奈川寺",
        )
        self.assertEqual(
            normalize_role_name("奈川寺", "梦江南"),
            "奈川寺",
        )
        self.assertEqual(
            normalize_role_name("发神鲸@龙争虎斗·龙争虎斗", "龙争虎斗"),
            "发神鲸@龙争虎斗",
        )
        self.assertEqual(
            normalize_role_name("角色A·别的服", "梦江南"),
            "角色A·别的服",
        )

    def test_extract_players_normalizes_role_name_by_server_suffix(self) -> None:
        players = extract_players_from_detail({
            "team1": {
                "players_info": [
                    {"role_name": "奈川寺·梦江南", "server": "梦江南"},
                    {"role_name": "奈川寺", "server": "梦江南"},
                    {"role_name": "角色A·别的服", "server": "梦江南"},
                ]
            }
        })

        self.assertEqual(len(players), 2)
        self.assertEqual(players[0]["role_name"], "奈川寺")
        self.assertEqual(players[1]["role_name"], "角色A·别的服")


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

    async def test_run_until_idle_aggregates_multiple_rounds(self) -> None:
        service = JjcMatchDataSyncService(
            repo=FakeRepo(),
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=FakeHistoryClient([]),
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )
        results = [
            {
                "error": False,
                "processed_roles": 2,
                "discovered_matches": 3,
                "saved_details": 4,
                "skipped_details": 0,
                "failed_details": 1,
                "unavailable_details": 0,
                "failed_roles": 0,
                "recovered_leases": 1,
                "errors": [],
            },
            {
                "error": False,
                "processed_roles": 0,
                "discovered_matches": 0,
                "saved_details": 0,
                "skipped_details": 0,
                "failed_details": 0,
                "unavailable_details": 0,
                "failed_roles": 0,
                "recovered_leases": 0,
                "errors": [],
            },
        ]
        calls: List[Dict[str, Any]] = []

        async def _run_once(mode: str = "incremental_or_full", limit: int = 3) -> Dict[str, Any]:
            calls.append({"mode": mode, "limit": limit})
            return results.pop(0)

        service.run_once = _run_once  # type: ignore[method-assign]

        result = await service.run_until_idle(mode="full", limit=50, max_rounds=10, max_seconds=60)

        self.assertFalse(result["error"])
        self.assertEqual(result["rounds"], 2)
        self.assertEqual(result["processed_roles"], 2)
        self.assertEqual(result["saved_details"], 4)
        self.assertEqual(result["failed_details"], 1)
        self.assertEqual(result["recovered_leases"], 1)
        self.assertEqual(result["stopped_reason"], "idle")
        self.assertEqual(calls, [{"mode": "full", "limit": 50}, {"mode": "full", "limit": 50}])

    async def test_start_background_run_rejects_duplicate_running_task(self) -> None:
        service = JjcMatchDataSyncService(
            repo=FakeRepo(),
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=FakeHistoryClient([]),
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )
        release = asyncio.Event()

        async def _run_until_idle(**kwargs: Any) -> Dict[str, Any]:
            await release.wait()
            return {
                "error": False,
                "rounds": 1,
                "processed_roles": 0,
                "stopped_reason": "idle",
                "elapsed_seconds": 0.0,
            }

        service.run_until_idle = _run_until_idle  # type: ignore[method-assign]

        first = await service.start_background_run(limit=50)
        second = await service.start_background_run(limit=50)
        release.set()
        if service._background_task is not None:
            await service._background_task

        self.assertFalse(first["error"])
        self.assertTrue(second["error"])
        self.assertEqual(second["message"], "background_sync_already_running")
        self.assertIsNotNone(service._last_background_summary)
        self.assertEqual(service._last_background_summary["stopped_reason"], "idle")

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
        self.assertEqual(result["recovered_leases"], 2)

    async def test_enqueue_roles_moves_candidates_to_queue(self) -> None:
        repo = FakeRepo()
        repo.roles = [
            {"identity_key": "global:g1", "server": "梦江南", "name": "角色A"},
            {"identity_key": "global:g2", "server": "梦江南", "name": "角色B"},
        ]
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=FakeHistoryClient([]),
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        result = await service.enqueue_roles(mode="full", limit=10, source="test")

        self.assertFalse(result["error"])
        self.assertEqual(result["enqueued_roles"], 2)
        self.assertEqual(result["mode"], "full")
        self.assertEqual(result["recovered_leases"], 2)

    async def test_enqueue_roles_when_paused_still_queues_roles(self) -> None:
        repo = FakeRepo()
        repo.paused = True
        repo.pause_reason = "更换 ticket"
        repo.roles = [
            {"identity_key": "global:g1", "server": "梦江南", "name": "角色A"},
        ]
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=FakeHistoryClient([]),
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        result = await service.enqueue_roles(mode="full", limit=10, source="test")

        self.assertFalse(result["error"])
        self.assertTrue(result["paused"])
        self.assertEqual(result["pause_reason"], "更换 ticket")
        self.assertEqual(result["enqueued_roles"], 1)

    async def test_enqueue_roles_rejects_incremental_mode(self) -> None:
        service = JjcMatchDataSyncService(
            repo=FakeRepo(),
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=FakeHistoryClient([]),
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        result = await service.enqueue_roles(mode="incremental", limit=10, source="test")

        self.assertTrue(result["error"])
        self.assertEqual(result["message"], "invalid_mode")

    async def test_worker_tick_claims_queued_role(self) -> None:
        repo = FakeRepo()
        repo.claimed_queued_role = {
            "status": "queued",
            "identity_key": "global:gid-a",
            "server": "梦江南",
            "name": "角色A",
            "global_role_id": "gid-a",
        }
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=FakeHistoryClient([{"data": []}]),
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        result = await service.worker_tick(mode="incremental_or_full", worker_id="worker-1")

        self.assertTrue(result["processed"])
        self.assertEqual(repo.success_release["identity_key"], "global:gid-a")
        self.assertEqual(repo.worker_heartbeats[0]["status"], "syncing")
        self.assertEqual(repo.worker_heartbeats[-1]["status"], "idle")

    async def test_sync_one_role_refreshes_worker_heartbeat_during_role_processing(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "status": "syncing",
            "identity_key": "global:gid-a",
            "lease_owner": "worker-1",
            "lease_expires_at": time.time() + 3600,
        }]
        history = FakeHistoryClient([
            {"data": [{"match_id": 19, "match_time": 1810000000, "pvpType": 3}]}
        ])
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )
        heartbeat_calls: List[Dict[str, Any]] = []

        async def fake_heartbeat_if_due(
            worker_id: str,
            current_role: Dict[str, Any],
            last_heartbeat_at: float,
            force: bool = False,
        ) -> float:
            heartbeat_calls.append({
                "worker_id": worker_id,
                "identity_key": current_role.get("identity_key"),
                "force": force,
            })
            return last_heartbeat_at + 1

        service._heartbeat_worker_if_due = fake_heartbeat_if_due

        result = await service._sync_one_role(
            role={
                "identity_key": "global:gid-a",
                "server": "梦江南",
                "name": "角色A",
                "global_role_id": "gid-a",
            },
            mode="incremental_or_full",
            lease_owner="worker-1",
        )

        self.assertFalse(result["error"])
        self.assertGreaterEqual(len(heartbeat_calls), 2)
        self.assertTrue(heartbeat_calls[0]["force"])
        self.assertTrue(all(call["worker_id"] == "worker-1" for call in heartbeat_calls))
        self.assertTrue(all(call["identity_key"] == "global:gid-a" for call in heartbeat_calls))

    async def test_worker_tick_paused_recovers_expired_leases_without_claiming(self) -> None:
        repo = FakeRepo()
        repo.paused = True
        repo.pause_reason = "维护"
        repo.claimed_queued_role = {
            "status": "queued",
            "identity_key": "global:gid-a",
            "server": "梦江南",
            "name": "角色A",
            "global_role_id": "gid-a",
        }
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=FakeHistoryClient([]),
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        result = await service.worker_tick(mode="incremental_or_full", worker_id="worker-1")

        self.assertTrue(result["paused"])
        self.assertEqual(result["pause_reason"], "维护")
        self.assertEqual(result["recovered_leases"], 2)
        self.assertIsNotNone(repo.claimed_queued_role)
        self.assertIsNone(repo.success_release)
        self.assertIsNone(repo.failure_release)
        self.assertEqual(repo.worker_heartbeats[-1]["status"], "paused")

    async def test_queue_status_reports_worker_running_from_worker_list(self) -> None:
        repo = FakeRepo()
        repo.workers = [
            {"worker_id": "worker-stopped", "status": "stopped", "heartbeat_at": 1.0},
            {"worker_id": "worker-idle", "status": "idle", "heartbeat_at": time.time()},
        ]
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=FakeHistoryClient([]),
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        result = await service.queue_status()

        self.assertFalse(result["error"])
        self.assertTrue(result["worker_running"])
        self.assertTrue(result["background_running"])
        self.assertFalse(result["workers"][0]["online"])
        self.assertEqual(result["workers"][0]["effective_status"], "stopped")
        self.assertTrue(result["workers"][1]["online"])
        self.assertEqual(result["workers"][1]["effective_status"], "idle")

    async def test_queue_status_ignores_stale_worker_heartbeat(self) -> None:
        repo = FakeRepo()
        repo.workers = [
            {"worker_id": "worker-old", "status": "idle", "heartbeat_at": time.time() - 3600},
        ]
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=FakeHistoryClient([]),
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        result = await service.queue_status()

        self.assertFalse(result["error"])
        self.assertFalse(result["worker_running"])
        self.assertFalse(result["background_running"])
        self.assertFalse(result["workers"][0]["online"])
        self.assertEqual(result["workers"][0]["effective_status"], "offline")

    async def test_dispatch_queue_once_skips_when_queue_is_sufficient(self) -> None:
        repo = FakeRepo()
        repo.roles = [
            {"identity_key": "queued-1", "status": "queued"},
            {"identity_key": "queued-2", "status": "queued"},
            {"identity_key": "queued-3", "status": "queued"},
        ]
        repo.workers = [
            {"worker_id": "worker-idle", "status": "idle", "heartbeat_at": time.time()},
        ]
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=FakeHistoryClient([]),
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
            dispatcher_target_per_worker=3,
        )

        result = await service.dispatch_queue_once()

        self.assertFalse(result["error"])
        self.assertEqual(result["action"], "skipped")
        self.assertEqual(result["reason"], "queue_sufficient")
        self.assertEqual(repo.enqueue_next_roles_calls, [])

    async def test_dispatch_queue_once_enqueues_recent_fourteen_day_window(self) -> None:
        repo = FakeRepo()
        repo.roles = [
            {"identity_key": "pending-1", "status": "pending"},
            {"identity_key": "pending-2", "status": "pending"},
        ]
        repo.workers = [
            {"worker_id": "worker-idle", "status": "idle", "heartbeat_at": time.time()},
        ]
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=FakeHistoryClient([]),
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
            dispatcher_batch_size=5,
            dispatcher_target_per_worker=3,
        )

        before = int(time.time())
        result = await service.dispatch_queue_once()
        after = int(time.time())

        self.assertFalse(result["error"])
        self.assertEqual(result["action"], "enqueued")
        self.assertEqual(result["reason"], "queue_refilled")
        self.assertEqual(result["enqueued_roles"], 2)
        self.assertEqual(len(repo.enqueue_next_roles_calls), 1)
        call = repo.enqueue_next_roles_calls[0]
        self.assertEqual(call["source"], "auto_dispatcher")
        self.assertEqual(call["mode"], "full")
        self.assertEqual(call["limit"], 3)
        lower_bound = before - 14 * 86400
        upper_bound = after - 14 * 86400
        self.assertGreaterEqual(call["queue_sync_until_time"], lower_bound)
        self.assertLessEqual(call["queue_sync_until_time"], upper_bound)
        self.assertEqual(result["queue_sync_until_time"], call["queue_sync_until_time"])

    async def test_fake_repo_claim_and_release_enforces_role_lease_owner(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "status": "queued",
            "identity_key": "global:gid-a",
            "server": "梦江南",
            "name": "角色A",
        }]

        claimed = await repo.claim_queued_role(lease_owner="worker-1", lease_seconds=60)

        self.assertIsNotNone(claimed)
        self.assertEqual(repo.roles[0]["status"], "syncing")
        self.assertEqual(repo.roles[0]["lease_owner"], "worker-1")
        self.assertFalse(await repo.release_role_success(
            identity_key="global:gid-a",
            lease_owner="worker-2",
        ))
        self.assertEqual(repo.roles[0]["status"], "syncing")
        self.assertTrue(await repo.release_role_success(
            identity_key="global:gid-a",
            lease_owner="worker-1",
        ))
        self.assertEqual(repo.roles[0]["status"], "cooldown")

    async def test_run_worker_treats_zero_max_roles_as_unlimited(self) -> None:
        repo = FakeRepo()
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=FakeHistoryClient([]),
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )
        tick_calls: List[Dict[str, Any]] = []

        async def fake_tick(mode: str, worker_id: str) -> Dict[str, Any]:
            tick_calls.append({"mode": mode, "worker_id": worker_id})
            return {"error": False, "paused": True, "auto_paused": True, "recovered_leases": 0}

        service.worker_tick = fake_tick

        result = await service.run_worker(
            mode="incremental_or_full",
            worker_id="worker-zero",
            idle_sleep=1,
            max_roles=0,
        )

        self.assertFalse(result["error"])
        self.assertEqual(result["stopped_reason"], "auto_paused")
        self.assertEqual(tick_calls, [{"mode": "incremental_or_full", "worker_id": "worker-zero"}])

    async def test_run_worker_stale_tick_does_not_count_as_processed(self) -> None:
        repo = FakeRepo()
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=FakeHistoryClient([]),
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )
        ticks = [
            {
                "error": False,
                "processed": False,
                "result": {"error": True, "stale_lease": True, "message": "stale_role_lease"},
                "recovered_leases": 0,
            },
            {"error": False, "paused": True, "auto_paused": True, "recovered_leases": 0},
        ]
        slept: List[int] = []

        async def fake_tick(mode: str, worker_id: str) -> Dict[str, Any]:
            return ticks.pop(0)

        async def fake_sleep(seconds: int) -> None:
            slept.append(seconds)

        service.worker_tick = fake_tick

        with patch("src.services.jx3.jjc_match_data_sync.asyncio.sleep", new=fake_sleep):
            result = await service.run_worker(
                mode="incremental_or_full",
                worker_id="worker-stale",
                idle_sleep=7,
                max_roles=1,
            )

        self.assertFalse(result["error"])
        self.assertEqual(result["processed_roles"], 0)
        self.assertEqual(result["interrupted_ticks"], 1)
        self.assertEqual(result["stopped_reason"], "auto_paused")
        self.assertEqual(result["errors"], ["stale_role_lease"])
        self.assertEqual(slept, [7])

    async def test_run_worker_one_shot_stale_tick_stops_interrupted(self) -> None:
        repo = FakeRepo()
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=FakeHistoryClient([]),
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )
        slept: List[int] = []

        async def fake_tick(mode: str, worker_id: str) -> Dict[str, Any]:
            return {
                "error": False,
                "processed": False,
                "result": {"error": True, "stale_detail_lease": True, "message": "stale_detail_lease"},
                "recovered_leases": 0,
            }

        async def fake_sleep(seconds: int) -> None:
            slept.append(seconds)

        service.worker_tick = fake_tick

        with patch("src.services.jx3.jjc_match_data_sync.asyncio.sleep", new=fake_sleep):
            result = await service.run_worker(
                mode="incremental_or_full",
                worker_id="worker-one-shot",
                idle_sleep=7,
                stop_when_idle=True,
            )

        self.assertFalse(result["error"])
        self.assertEqual(result["processed_roles"], 0)
        self.assertEqual(result["interrupted_ticks"], 1)
        self.assertEqual(result["stopped_reason"], "interrupted")
        self.assertEqual(result["errors"], ["stale_detail_lease"])
        self.assertEqual(slept, [])

    async def test_worker_tick_auth_error_auto_pauses_without_fail_count(self) -> None:
        repo = FakeRepo()
        repo.claimed_queued_role = {
            "status": "queued",
            "identity_key": "global:gid-a",
            "server": "梦江南",
            "name": "角色A",
            "global_role_id": "gid-a",
        }
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=FakeHistoryClient([{"error": "ticket expired"}]),
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        result = await service.worker_tick(mode="incremental_or_full", worker_id="worker-1")

        self.assertTrue(result["paused"])
        self.assertTrue(result["auto_paused"])
        self.assertTrue(repo.paused)
        self.assertIn("ticket expired", repo.pause_reason)
        self.assertEqual(repo.interrupted_release["identity_key"], "global:gid-a")
        self.assertIsNone(repo.failure_release)

    async def test_worker_tick_stale_role_lease_does_not_release_role(self) -> None:
        repo = FakeRepo()
        repo.renew_role_lease_result = False
        repo.claimed_queued_role = {
            "status": "queued",
            "identity_key": "global:gid-a",
            "server": "梦江南",
            "name": "角色A",
            "global_role_id": "gid-a",
        }
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=FakeHistoryClient([{"data": []}]),
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        result = await service.worker_tick(mode="incremental_or_full", worker_id="worker-1")

        self.assertFalse(result["processed"])
        self.assertTrue(result["result"]["stale_lease"])
        self.assertIsNone(repo.success_release)
        self.assertIsNone(repo.failure_release)

    async def test_worker_tick_stale_identity_migration_does_not_release_role(self) -> None:
        repo = FakeRepo()
        repo.identity_update_result = None
        repo.claimed_queued_role = {
            "status": "queued",
            "identity_key": "name:梦江南:种子",
            "server": "梦江南",
            "name": "种子",
            "role_id": "rid",
            "zone": "zone-a",
        }
        inspect_service = FakeInspectService()
        inspect_service.identity_result = {
            "global_id": "global-resolved",
            "global_role_id": "gid-resolved",
            "role_id": "rid",
            "game_role_id": "rid",
            "zone": "zone-a",
            "source": "test_identity",
        }
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=FakeHistoryClient([{"data": []}]),
            inspect_service=inspect_service,
            sleep_func=_noop_sleep,
        )

        result = await service.worker_tick(mode="incremental_or_full", worker_id="worker-1")

        self.assertFalse(result["processed"])
        self.assertTrue(result["result"]["stale_lease"])
        self.assertEqual(repo.identity_updates[0]["lease_owner"], "worker-1")
        self.assertIsNone(repo.success_release)
        self.assertIsNone(repo.failure_release)

    async def test_worker_tick_identity_id_loads_refreshes_and_uses_identity_queue_methods(self) -> None:
        repo = FakeRepo()
        repo.claimed_queued_role = {
            "status": "queued",
            "identity_id": "identity-1",
            "identity_key": "game:zone-a:rid-a",
            "server": "梦江南",
            "name": "种子",
        }
        identity_repo = FakeIdentityRepo()
        identity_repo.docs_by_id["identity-1"] = {
            "_id": "identity-1",
            "identity_key": "game:zone-a:rid-a",
            "server": "梦江南",
            "name": "种子",
            "zone": "zone-a",
            "game_role_id": "rid-a",
        }
        indicator = FakeIndicatorClient({
            "zone-a:rid-a:梦江南": {
                "data": {
                    "role_info": {
                        "global_role_id": "SK01-from-indicator",
                        "role_id": "rid-a",
                        "zone": "zone-a",
                    },
                    "person_info": {"person_id": "pid-a"},
                }
            }
        })
        history = FakeHistoryClient([
            {"data": [{"match_id": 31, "match_time": 1810000000, "pvpType": 3}]}
        ])
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(),
            identity_repo=identity_repo,
            role_indicator_client=indicator,
            sleep_func=_noop_sleep,
        )

        result = await service.worker_tick(mode="incremental_or_full", worker_id="worker-1")

        self.assertFalse(result["result"]["error"])
        self.assertEqual(identity_repo.get_by_id_calls, ["identity-1"])
        self.assertEqual(len(identity_repo.refresh_indicator_calls), 1)
        self.assertEqual(indicator.calls[0], {"role_id": "rid-a", "zone": "zone-a", "server": "梦江南"})
        self.assertEqual(history.calls[0]["global_role_id"], "SK01-from-indicator")
        self.assertTrue(repo.identity_lease_renewals)
        self.assertEqual(repo.identity_lease_renewals[0]["identity_id"], "identity-1")
        self.assertEqual(repo.identity_success_release["identity_id"], "identity-1")
        self.assertEqual(repo.discovered_matches[0]["source_identity_id"], "identity-1")
        self.assertEqual(repo.discovered_matches[0]["source_identity_key"], "game:zone-a:rid-a")
        self.assertEqual(repo.worker_heartbeats[0]["current_identity_id"], "identity-1")

    async def test_sync_match_detail_passes_lease_owner_to_saved_marker(self) -> None:
        repo = FakeRepo()
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            inspect_service=FakeInspectService(),
            match_detail_projection_service=FakeProjectionService(repo.events),
            sleep_func=_noop_sleep,
        )

        result = await service._sync_match_detail(
            match_id=11,
            match_time=1810000000,
            lease_owner="worker-1",
        )

        self.assertEqual(result, "saved")
        self.assertEqual(repo.detail_saved_calls[0]["lease_owner"], "worker-1")

    async def test_sync_match_detail_claim_error_interrupts_role(self) -> None:
        repo = FakeRepo()
        repo.claim_match_detail_exception = RuntimeError("mongo_claim_down")
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            inspect_service=FakeInspectService(),
            match_detail_projection_service=FakeProjectionService(repo.events),
            sleep_func=_noop_sleep,
        )

        with self.assertRaises(JjcSyncMatchDetailClaimError):
            await service._sync_match_detail(
                match_id=18,
                match_time=1810000000,
                lease_owner="worker-1",
            )

        self.assertEqual(repo.detail_saved_calls, [])
        self.assertEqual(repo.detail_failed_calls, [])

    async def test_sync_match_detail_renews_role_lease_during_saved_detail_postprocessing(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "status": "syncing",
            "identity_key": "global:seed",
            "lease_owner": "worker-1",
            "lease_expires_at": time.time() + 3600,
        }]
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            inspect_service=FakeInspectService(),
            match_detail_projection_service=FakeProjectionService(repo.events),
            sleep_func=_noop_sleep,
        )

        result = await service._sync_match_detail(
            match_id=14,
            match_time=1810000000,
            lease_owner="worker-1",
            role_identity_key="global:seed",
        )

        self.assertEqual(result, "saved")
        self.assertGreaterEqual(len(repo.role_lease_renewals), 4)
        self.assertTrue(all(call["lease_owner"] == "worker-1" for call in repo.role_lease_renewals))
        self.assertGreaterEqual(len(repo.detail_lease_renewals), 4)
        self.assertTrue(all(call["lease_owner"] == "worker-1" for call in repo.detail_lease_renewals))
        self.assertLess(repo.events.index("project_payload"), repo.events.index("mark_saved"))

    async def test_sync_match_detail_stale_role_lease_bubbles_without_marking_failed(self) -> None:
        repo = FakeRepo()
        repo.renew_role_lease_result = False
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            inspect_service=FakeInspectService(),
            match_detail_projection_service=FakeProjectionService(repo.events),
            sleep_func=_noop_sleep,
        )

        with self.assertRaises(JjcSyncStaleLeaseError):
            await service._sync_match_detail(
                match_id=12,
                match_time=1810000000,
                lease_owner="worker-1",
                role_identity_key="global:seed",
            )

        self.assertEqual(repo.failed_matches, [])
        self.assertEqual(repo.detail_failed_calls, [])

    async def test_sync_match_detail_stale_role_lease_before_claim_prevents_detail_lease(self) -> None:
        repo = FakeRepo()
        repo.renew_role_lease_result = False
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            inspect_service=FakeInspectService(),
            match_detail_projection_service=FakeProjectionService(repo.events),
            sleep_func=_noop_sleep,
        )

        with self.assertRaises(JjcSyncStaleLeaseError):
            await service._sync_match_detail(
                match_id=100,
                match_time=1810000000,
                lease_owner="worker-1",
                role_identity_key="global:seed",
            )

        self.assertNotIn(100, repo.detail_states)
        self.assertEqual(repo.detail_saved_calls, [])
        self.assertEqual(repo.detail_failed_calls, [])
        self.assertEqual(repo.saved_matches, [])
        self.assertEqual(repo.failed_matches, [])

    async def test_sync_match_detail_stale_detail_save_bubbles_after_player_enqueue(self) -> None:
        repo = FakeRepo()
        repo.mark_detail_saved_result = False
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            inspect_service=FakeInspectService(),
            match_detail_projection_service=FakeProjectionService(repo.events),
            sleep_func=_noop_sleep,
        )

        with self.assertRaises(JjcSyncStaleLeaseError):
            await service._sync_match_detail(
                match_id=13,
                match_time=1810000000,
                lease_owner="worker-1",
            )

        self.assertEqual(repo.detail_saved_calls[0]["lease_owner"], "worker-1")
        self.assertEqual(repo.upserted_roles, [])
        self.assertLess(repo.events.index("project_payload"), repo.events.index("mark_saved"))

    async def test_sync_match_detail_projection_failure_is_nonblocking(self) -> None:
        repo = FakeRepo()
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            inspect_service=FakeInspectService(),
            match_detail_projection_service=FakeProjectionService(repo.events, RuntimeError("projection_down")),
            sleep_func=_noop_sleep,
        )

        result = await service._sync_match_detail(
            match_id=16,
            match_time=1810000000,
            lease_owner="worker-1",
            max_attempts=1,
        )

        self.assertEqual(result, "saved")
        self.assertEqual(repo.detail_saved_calls[0]["match_id"], 16)
        self.assertEqual(repo.failed_matches, [])
        self.assertIn("project_payload", repo.events)
        self.assertLess(repo.events.index("project_payload"), repo.events.index("mark_saved"))

    async def test_sync_match_detail_stale_detail_lease_before_postprocess_does_not_mark_saved(self) -> None:
        repo = FakeRepo()
        repo.renew_match_detail_lease_result = False
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        with self.assertRaises(JjcSyncStaleLeaseError):
            await service._sync_match_detail(
                match_id=17,
                match_time=1810000000,
                lease_owner="worker-1",
            )

        self.assertEqual(repo.detail_saved_calls, [])
        self.assertEqual(repo.upserted_roles, [])

    async def test_worker_tick_stale_detail_lease_requeues_role_without_failure_release(self) -> None:
        repo = FakeRepo()
        repo.mark_detail_saved_result = False
        repo.claimed_queued_role = {
            "status": "queued",
            "identity_key": "global:seed",
            "server": "梦江南",
            "name": "种子",
            "global_role_id": "seed",
        }
        history = FakeHistoryClient([
            {"data": [{"match_id": 15, "match_time": 1810000000, "pvpType": 3}]}
        ])
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        result = await service.worker_tick(mode="incremental_or_full", worker_id="worker-1")

        self.assertFalse(result["processed"])
        self.assertTrue(result["result"]["stale_detail_lease"])
        self.assertEqual(repo.interrupted_release["identity_key"], "global:seed")
        self.assertTrue(repo.interrupted_release["requeue"])
        self.assertEqual(repo.interrupted_release["lease_owner"], "worker-1")
        self.assertIsNone(repo.success_release)
        self.assertIsNone(repo.failure_release)

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
                        "global_id": "global-a",
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
        self.assertEqual(repo.upserted_roles[0]["global_id"], "global-a")
        self.assertEqual(repo.upserted_roles[0]["global_role_id"], "gid-a")
        self.assertEqual(repo.upserted_roles[0]["priority"], -10)
        self.assertEqual(identity_repo.upserted[0]["global_id"], "global-a")
        self.assertEqual(identity_repo.upserted[0]["global_role_id"], "gid-a")
        self.assertEqual(identity_repo.upserted[0]["role_id"], "rid-a")

    async def test_enqueue_players_from_detail_does_not_backfill_global_role_id_from_person_history(self) -> None:
        repo = FakeRepo()
        identity_repo = FakeIdentityRepo()
        person_history = FakePersonHistoryClient([])
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

        self.assertEqual(person_history.calls, [])
        self.assertEqual(repo.upserted_roles, [])
        self.assertEqual(identity_repo.upserted[0]["global_role_id"], None)
        self.assertEqual(identity_repo.upserted[0]["person_id"], "pid-a")

    async def test_enqueue_players_from_detail_normalizes_written_role_name(self) -> None:
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
                        "role_name": "发神鲸@龙争虎斗·龙争虎斗",
                        "global_role_id": "gid-a",
                        "role_id": "rid-a",
                        "zone": "zone-a",
                        "server": "龙争虎斗",
                    }
                ]
            },
            "team2": {"players_info": []},
        })

        self.assertEqual(repo.upserted_roles[0]["name"], "发神鲸@龙争虎斗")
        self.assertEqual(repo.upserted_roles[0]["normalized_name"], "发神鲸@龙争虎斗")
        self.assertEqual(identity_repo.upserted[0]["name"], "发神鲸@龙争虎斗")

    async def test_full_sync_reaches_season_start_and_releases_success(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "status": "queued",
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
            "status": "queued",
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

    async def test_queue_sync_until_time_stops_full_sync_at_task_window(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "status": "queued",
            "identity_key": "global:seed",
            "server": "梦江南",
            "name": "种子",
            "global_role_id": "seed",
            "queue_mode": "full",
            "queue_sync_until_time": 1810000000,
        }]
        history = FakeHistoryClient([
            {"data": [
                {"match_id": 12, "match_time": 1810000100, "pvpType": 3},
                {"match_id": 13, "match_time": 1810000000, "pvpType": 3},
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

        result = await service.run_once(mode="full")

        self.assertFalse(result["error"])
        self.assertEqual([item["match_id"] for item in repo.discovered_matches], [12])
        self.assertEqual(result["saved_details"], 1)

    async def test_detail_failure_does_not_fail_role_continues_to_success(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "status": "queued",
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

    async def test_detail_claim_error_requeues_role_without_advancing_waterline(self) -> None:
        repo = FakeRepo()
        repo.claim_match_detail_exception = RuntimeError("mongo_claim_down")
        repo.roles = [{
            "status": "queued",
            "identity_key": "global:seed",
            "server": "梦江南",
            "name": "种子",
            "global_role_id": "seed",
        }]
        history = FakeHistoryClient([
            {"data": [{"match_id": 21, "match_time": 1810000000, "pvpType": 3}]}
        ])
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        result = await service.run_once()

        self.assertFalse(result["error"])
        self.assertEqual(result["processed_roles"], 0)
        self.assertEqual(result["failed_roles"], 0)
        self.assertEqual(result["failed_details"], 0)
        self.assertEqual(repo.interrupted_release["identity_key"], "global:seed")
        self.assertIn("mongo_claim_down", repo.interrupted_release["reason"])
        self.assertTrue(repo.interrupted_release["requeue"])
        self.assertIsNone(repo.success_release)
        self.assertIsNone(repo.failure_release)

    async def test_worker_tick_detail_claim_error_requeues_role_without_counting_processed(self) -> None:
        repo = FakeRepo()
        repo.claim_match_detail_exception = RuntimeError("mongo_claim_down")
        repo.claimed_queued_role = {
            "status": "queued",
            "identity_key": "global:seed",
            "server": "梦江南",
            "name": "种子",
            "global_role_id": "seed",
        }
        history = FakeHistoryClient([
            {"data": [{"match_id": 22, "match_time": 1810000000, "pvpType": 3}]}
        ])
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(),
            sleep_func=_noop_sleep,
        )

        result = await service.worker_tick(mode="incremental_or_full", worker_id="worker-1")

        self.assertFalse(result["processed"])
        self.assertTrue(result["result"]["interrupted"])
        self.assertEqual(result["result"]["error_type"], "match_detail_claim_failed")
        self.assertEqual(repo.interrupted_release["identity_key"], "global:seed")
        self.assertIsNone(repo.success_release)
        self.assertIsNone(repo.failure_release)

    async def test_detail_transient_failure_retries_then_succeeds(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "status": "queued",
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
            "status": "queued",
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
            "status": "queued",
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
        self.assertTrue(repo.detail_unavailable_calls[0]["lease_owner"])
        self.assertNotIn(60, repo.failed_matches)
        self.assertIsNotNone(repo.success_release)
        self.assertIsNone(repo.failure_release)

    async def test_run_once_aggregates_failed_and_unavailable_details(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "status": "queued",
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
            "status": "queued",
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
            "status": "queued",
            "identity_key": "global:seed",
            "server": "梦江南",
            "name": "种子",
            "global_role_id": "seed",
        }]
        repo.saved_matches.append(30)
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
            "status": "queued",
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
            "status": "queued",
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
            "global_id": "global-resolved",
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
        self.assertEqual(repo.identity_updates[0]["global_id"], "global-resolved")
        self.assertEqual(repo.identity_updates[0]["global_role_id"], "gid-resolved")
        self.assertEqual(repo.identity_updates[0]["identity_key"], "name:梦江南:种子")
        self.assertTrue(str(repo.identity_updates[0]["lease_owner"]).startswith("jjc-sync-worker:"))
        self.assertEqual(identity_repo.upserted[0]["global_id"], "global-resolved")
        self.assertEqual(identity_repo.upserted[0]["global_role_id"], "gid-resolved")
        self.assertGreaterEqual(sleep.count, 3)

    async def test_missing_global_role_id_skips_person_history_and_uses_inspect_resolver(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "status": "queued",
            "identity_key": "name:梦江南:种子",
            "server": "梦江南",
            "name": "种子",
            "person_id": "pid-a",
        }]
        history = FakeHistoryClient([
            {"data": [{"match_id": 41, "match_time": 1810000000, "pvpType": 3}]}
        ])
        person_history = FakePersonHistoryClient([])
        inspect_service = FakeInspectService()
        inspect_service.identity_result = {
            "global_role_id": "gid-inspect",
            "role_id": "rid-a",
            "game_role_id": "rid-a",
            "zone": "zone-a",
            "source": "test_identity",
        }
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
        self.assertEqual(person_history.calls, [])
        self.assertEqual(len(inspect_service.identity_calls), 1)
        self.assertEqual(history.calls[0]["global_role_id"], "gid-inspect")
        self.assertEqual(repo.identity_updates[0]["global_role_id"], "gid-inspect")
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
            "status": "queued",
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
            global_id="global-a",
            global_role_id="gid-a",
            role_id="rid-a",
            zone="zone-a",
        )

        self.assertFalse(result["error"])
        self.assertEqual(identity_repo.upserted[0]["server"], "梦江南")
        self.assertEqual(identity_repo.upserted[0]["name"], "角色A")
        self.assertEqual(identity_repo.upserted[0]["global_id"], "global-a")
        self.assertEqual(identity_repo.upserted[0]["global_role_id"], "gid-a")
        self.assertEqual(identity_repo.upserted[0]["game_role_id"], "rid-a")
        self.assertEqual(repo.upserted_roles[0]["global_id"], "global-a")

    # --- local identity priority tests (planned resolve_best_identity flow) ---

    async def test_enqueue_player_local_identity_hit_backfills_global_role_id_and_skips_person_history(self) -> None:
        repo = FakeRepo()
        identity_repo = FakeIdentityRepo()
        identity_repo.resolve_results = {
            "global_role_id": "gid-local",
            "role_id": "rid-a",
            "game_role_id": "rid-a",
            "zone": "zone-a",
            "server": "梦江南",
            "role_name": "角色A",
        }
        person_history = FakePersonHistoryClient([])
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

        self.assertEqual(len(identity_repo.resolve_calls), 1)
        self.assertEqual(identity_repo.resolve_calls[0]["server"], "梦江南")
        self.assertEqual(identity_repo.resolve_calls[0]["name"], "角色A")
        self.assertEqual(person_history.calls, [])
        self.assertEqual(repo.upserted_roles[0]["global_role_id"], "gid-local")
        self.assertEqual(repo.upserted_roles[0]["person_id"], "pid-a")

    async def test_enqueue_player_local_identity_hit_can_use_zone_and_role_id_without_name(self) -> None:
        repo = FakeRepo()
        identity_repo = FakeIdentityRepo()
        identity_repo.resolve_results = {
            "global_role_id": "gid-local",
            "role_id": "rid-a",
            "zone": "zone-a",
            "server": "梦江南",
            "name": "角色A",
        }
        person_history = FakePersonHistoryClient([])
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
                        "role_name": "",
                        "global_role_id": "",
                        "role_id": "rid-a",
                        "zone": "zone-a",
                        "server": "",
                    }
                ]
            }
        })

        self.assertEqual(len(identity_repo.resolve_calls), 1)
        self.assertEqual(identity_repo.resolve_calls[0]["zone"], "zone-a")
        self.assertEqual(identity_repo.resolve_calls[0]["game_role_id"], "rid-a")
        self.assertEqual(person_history.calls, [])
        self.assertEqual(repo.upserted_roles[0]["server"], "梦江南")
        self.assertEqual(repo.upserted_roles[0]["name"], "角色A")
        self.assertEqual(repo.upserted_roles[0]["global_role_id"], "gid-local")

    async def test_enqueue_player_zone_role_lookup_ignores_mismatched_local_identity(self) -> None:
        repo = FakeRepo()
        identity_repo = FakeIdentityRepo()
        identity_repo.resolve_results = {
            "global_role_id": "gid-other",
            "role_id": "rid-other",
            "zone": "zone-other",
            "server": "梦江南",
            "name": "其他角色",
        }
        person_history = FakePersonHistoryClient([])
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
                        "role_name": "",
                        "global_role_id": "",
                        "role_id": "rid-a",
                        "zone": "zone-a",
                        "server": "",
                    }
                ]
            }
        })

        self.assertEqual(len(identity_repo.resolve_calls), 1)
        self.assertEqual(person_history.calls, [])
        self.assertEqual(repo.upserted_roles, [])

    async def test_enqueue_player_local_identity_miss_does_not_call_person_history(self) -> None:
        repo = FakeRepo()
        identity_repo = FakeIdentityRepo()
        identity_repo.resolve_results = {}
        person_history = FakePersonHistoryClient([])
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

        self.assertEqual(len(identity_repo.resolve_calls), 1)
        self.assertEqual(person_history.calls, [])
        self.assertEqual(repo.upserted_roles, [])
        self.assertEqual(identity_repo.upserted[0]["global_role_id"], None)
        self.assertEqual(identity_repo.upserted[0]["person_id"], "pid-a")

    async def test_enqueue_player_with_existing_global_role_id_skips_local_repo_and_person_history(self) -> None:
        repo = FakeRepo()
        identity_repo = FakeIdentityRepo()
        person_history = FakePersonHistoryClient([])
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
                        "global_role_id": "gid-existing",
                        "role_id": "rid-a",
                        "zone": "zone-a",
                        "server": "梦江南",
                    }
                ]
            },
            "team2": {"players_info": []},
        })

        self.assertEqual(identity_repo.resolve_calls, [])
        self.assertEqual(person_history.calls, [])
        self.assertEqual(repo.upserted_roles[0]["global_role_id"], "gid-existing")

    async def test_enqueue_player_local_identity_exception_does_not_call_person_history(self) -> None:
        repo = FakeRepo()
        identity_repo = FakeIdentityRepo()
        identity_repo.resolve_error = RuntimeError("db down")
        person_history = FakePersonHistoryClient([])
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

        self.assertEqual(len(identity_repo.resolve_calls), 1)
        self.assertEqual(person_history.calls, [])
        self.assertEqual(repo.upserted_roles, [])
        self.assertEqual(identity_repo.upserted[0]["global_role_id"], None)
        self.assertEqual(identity_repo.upserted[0]["person_id"], "pid-a")

    async def test_backfill_player_normalizes_role_name(self) -> None:
        player: Dict[str, Any] = {"server": "梦江南"}
        identity = {
            "role_name": "奈川寺·梦江南",
            "server": "梦江南",
            "global_role_id": "gid-a",
        }
        JjcMatchDataSyncService._backfill_player_from_identity(player, identity)
        self.assertEqual(player["role_name"], "奈川寺")

    async def test_backfill_player_keeps_existing_role_name(self) -> None:
        player: Dict[str, Any] = {
            "role_name": "已有角色名",
            "server": "梦江南",
        }
        identity = {"role_name": "奈川寺·梦江南", "server": "梦江南"}
        JjcMatchDataSyncService._backfill_player_from_identity(player, identity)
        self.assertEqual(player["role_name"], "已有角色名")

    async def test_enqueue_player_with_no_local_identity_skips_person_history(self) -> None:
        """person-history is not used to fill SK01 global_role_id."""
        repo = FakeRepo()
        identity_repo = FakeIdentityRepo()
        identity_repo.resolve_results = {}
        person_history = FakePersonHistoryClient([])
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
                        "role_id": "rid-a",
                        "zone": "zone-a",
                        "person_id": "pid-a",
                        "server": "梦江南",
                    }
                ]
            }
        })

        self.assertEqual(person_history.calls, [])
        self.assertEqual(repo.upserted_roles, [])
        self.assertEqual(identity_repo.upserted[0]["server"], "梦江南")
        self.assertEqual(identity_repo.upserted[0]["name"], "角色A")

    async def test_queue_role_missing_global_role_id_skips_person_history_and_uses_inspect(self) -> None:
        """role missing global_role_id goes directly to inspect resolver."""
        repo = FakeRepo()
        repo.roles = [{
            "status": "queued",
            "identity_key": "name:梦江南:种子",
            "server": "梦江南",
            "name": "种子",
            "person_id": "pid-a",
            "zone": "zone-a",
            "role_id": "rid-a",
        }]
        history = FakeHistoryClient([
            {"data": [{"match_id": 42, "match_time": 1810000000, "pvpType": 3}]}
        ])
        person_history = FakePersonHistoryClient([])
        inspect_service = FakeInspectService()
        inspect_service.identity_result = {
            "global_role_id": "gid-inspect",
            "role_id": "rid-a",
            "game_role_id": "rid-a",
            "zone": "zone-a",
            "source": "test_identity",
        }
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
        self.assertEqual(result["failed_roles"], 0)
        self.assertEqual(person_history.calls, [])
        self.assertEqual(len(inspect_service.identity_calls), 1)
        self.assertEqual(history.calls[0]["global_role_id"], "gid-inspect")
        self.assertEqual(repo.identity_updates[0]["global_role_id"], "gid-inspect")

    async def test_enqueue_normalizes_role_name_in_identity_repo_and_queue(self) -> None:
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
                        "role_name": "奈川寺·梦江南",
                        "global_role_id": "gid-a",
                        "role_id": "rid-a",
                        "server": "梦江南",
                    }
                ]
            },
            "team2": {"players_info": []},
        })

        self.assertEqual(identity_repo.upserted[0]["name"], "奈川寺")
        self.assertEqual(repo.upserted_roles[0]["name"], "奈川寺")
        self.assertEqual(repo.upserted_roles[0]["normalized_name"], "奈川寺")

    # --- replay + indicator enrichment tests ---

    async def test_replay_merges_role_id_zone_into_detail_players(self) -> None:
        replay = FakeReplayClient({
            "data": {
                "players": [
                    {
                        "role_name": "角色A·梦江南",
                        "role_id": "rid-replay",
                        "zone": "zone-replay",
                        "global_role_id": "99999",
                    }
                ]
            }
        })
        repo = FakeRepo()
        identity_repo = FakeIdentityRepo()
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_replay_client=replay,
            identity_repo=identity_repo,
            sleep_func=_noop_sleep,
        )

        detail = {
            "team1": {
                "players_info": [
                    {
                        "role_name": "角色A",
                        "server": "梦江南",
                        "role_id": "",
                        "zone": "",
                    }
                ]
            },
        }
        await service._enrich_detail_with_replay(detail, 123)

        player = detail["team1"]["players_info"][0]
        self.assertEqual(player["global_id"], "99999")
        self.assertEqual(player["role_id"], "rid-replay")
        self.assertEqual(player["zone"], "zone-replay")

    async def test_replay_enrich_uses_cached_replay_payload_without_requesting_api(self) -> None:
        replay = FakeReplayClient({"error": "should_not_call"})
        service = JjcMatchDataSyncService(
            repo=FakeRepo(),
            current_season="赛季",
            current_season_start="2026-04-24",
            match_replay_client=replay,
            sleep_func=_noop_sleep,
        )
        detail = {
            "team1": {
                "players_info": [
                    {
                        "role_name": "角色A",
                        "server": "梦江南",
                        "role_id": "rid-replay",
                    }
                ]
            },
        }
        cached_replay = {
            "data": {
                "players": [
                    {
                        "role_name": "角色A·梦江南",
                        "role_id": "rid-replay",
                        "global_role_id": "99999",
                    }
                ]
            }
        }

        await service._enrich_detail_with_replay(detail, 123, replay_data=cached_replay)

        self.assertEqual(detail["team1"]["players_info"][0]["global_id"], "99999")
        self.assertEqual(replay.calls, [])

    async def test_replay_numeric_global_role_id_written_as_global_id_only(self) -> None:
        replay = FakeReplayClient({
            "data": {
                "players": [
                    {
                        "role_name": "角色A·梦江南",
                        "role_id": "rid-replay",
                        "zone": "zone-replay",
                        "global_role_id": "99999",
                    }
                ]
            }
        })
        service = JjcMatchDataSyncService(
            repo=FakeRepo(),
            current_season="赛季",
            current_season_start="2026-04-24",
            match_replay_client=replay,
            sleep_func=_noop_sleep,
        )

        detail = {
            "team1": {
                "players_info": [
                    {
                        "role_name": "角色A",
                        "server": "梦江南",
                        "global_role_id": "",
                    }
                ]
            },
        }
        await service._enrich_detail_with_replay(detail, 123)

        player = detail["team1"]["players_info"][0]
        self.assertEqual(player["global_id"], "99999")
        self.assertEqual(player["global_role_id"], "")

    async def test_replay_merge_prefers_global_id_then_role_id_then_name(self) -> None:
        replay = FakeReplayClient({
            "data": {
                "players": [
                    {
                        "role_name": "名字匹配但不是本人·梦江南",
                        "role_id": "rid-name",
                        "zone": "zone-name",
                        "global_role_id": "global-name",
                    },
                    {
                        "role_name": "角色A·梦江南",
                        "role_id": "rid-role",
                        "zone": "zone-role",
                        "global_role_id": "global-role",
                    },
                    {
                        "role_name": "旧名·梦江南",
                        "role_id": "rid-global",
                        "zone": "zone-global",
                        "global_role_id": "global-current",
                    },
                ]
            }
        })
        service = JjcMatchDataSyncService(
            repo=FakeRepo(),
            current_season="赛季",
            current_season_start="2026-04-24",
            match_replay_client=replay,
            sleep_func=_noop_sleep,
        )

        detail = {
            "team1": {
                "players_info": [
                    {
                        "role_name": "角色A",
                        "server": "梦江南",
                        "global_id": "global-current",
                        "role_id": "rid-role",
                        "zone": "",
                    },
                    {
                        "role_name": "名字匹配但不是本人",
                        "server": "梦江南",
                        "role_id": "rid-role",
                        "zone": "",
                    },
                    {
                        "role_name": "名字匹配但不是本人",
                        "server": "梦江南",
                        "role_id": "",
                        "zone": "",
                    },
                ]
            },
        }
        await service._enrich_detail_with_replay(detail, 123)

        players = detail["team1"]["players_info"]
        self.assertEqual(players[0]["zone"], "zone-global")
        self.assertEqual(players[0]["global_id"], "global-current")
        self.assertEqual(players[1]["zone"], "zone-name")
        self.assertEqual(players[1]["global_id"], "global-name")
        self.assertEqual(players[2]["zone"], "zone-name")
        self.assertEqual(players[2]["global_id"], "global-name")

    async def test_replay_merge_matches_by_normalized_name(self) -> None:
        replay = FakeReplayClient({
            "data": {
                "players": [
                    {
                        "role_name": "奈川寺·梦江南",
                        "role_id": "rid-replay",
                    }
                ]
            }
        })
        service = JjcMatchDataSyncService(
            repo=FakeRepo(),
            current_season="赛季",
            current_season_start="2026-04-24",
            match_replay_client=replay,
            sleep_func=_noop_sleep,
        )

        detail = {
            "team1": {
                "players_info": [
                    {
                        "role_name": "奈川寺·梦江南",
                        "server": "梦江南",
                        "role_id": "",
                    }
                ]
            },
        }
        await service._enrich_detail_with_replay(detail, 123)

        player = detail["team1"]["players_info"][0]
        self.assertEqual(player["role_id"], "rid-replay")

    async def test_indicator_backfills_sk01_global_role_id(self) -> None:
        indicator = FakeIndicatorClient({
            "zone-a:rid-a:梦江南": {
                "data": {
                    "role_info": {"global_role_id": "SK01-abc", "role_id": "rid-a"},
                    "person_info": {"person_id": "pid-ind"},
                }
            }
        })
        repo = FakeRepo()
        identity_repo = FakeIdentityRepo()
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            role_indicator_client=indicator,
            identity_repo=identity_repo,
            sleep_func=_noop_sleep,
        )

        detail = {
            "team1": {
                "players_info": [
                    {
                        "role_name": "角色A",
                        "server": "梦江南",
                        "global_role_id": "",
                        "role_id": "rid-a",
                        "zone": "zone-a",
                        "person_id": "",
                    }
                ]
            },
        }
        await service._enrich_detail_with_indicator(detail)

        player = detail["team1"]["players_info"][0]
        self.assertEqual(player["global_role_id"], "SK01-abc")
        self.assertEqual(player["person_id"], "pid-ind")

    async def test_indicator_skips_when_global_role_id_already_present(self) -> None:
        indicator = FakeIndicatorClient({
            "zone-a:rid-a:梦江南": {
                "role_info": {"global_role_id": "SK01-new"},
            }
        })
        service = JjcMatchDataSyncService(
            repo=FakeRepo(),
            current_season="赛季",
            current_season_start="2026-04-24",
            role_indicator_client=indicator,
            sleep_func=_noop_sleep,
        )

        detail = {
            "team1": {
                "players_info": [
                    {
                        "role_name": "角色A",
                        "server": "梦江南",
                        "global_role_id": "SK01-existing",
                        "role_id": "rid-a",
                        "zone": "zone-a",
                    }
                ]
            },
        }
        await service._enrich_detail_with_indicator(detail)

        self.assertEqual(indicator.calls, [])
        player = detail["team1"]["players_info"][0]
        self.assertEqual(player["global_role_id"], "SK01-existing")

    async def test_indicator_uses_fresh_local_identity_and_skips_request(self) -> None:
        indicator = FakeIndicatorClient({
            "zone-a:rid-a:梦江南": {
                "role_info": {"global_role_id": "SK01-from-api"},
                "person_info": {"person_id": "pid-api"},
            }
        })
        identity_repo = FakeIdentityRepo()
        identity_repo.resolve_results = {
            "global_role_id": "SK01-local",
            "global_id": "99999",
            "role_id": "rid-a",
            "zone": "zone-a",
            "server": "梦江南",
            "role_name": "角色A",
            "person_id": "pid-local",
            "role_info_observed_match_time": 1810000000,
        }
        service = JjcMatchDataSyncService(
            repo=FakeRepo(),
            current_season="赛季",
            current_season_start="2026-04-24",
            role_indicator_client=indicator,
            identity_repo=identity_repo,
            sleep_func=_noop_sleep,
        )

        detail = {
            "team1": {
                "players_info": [
                    {
                        "role_name": "角色A",
                        "server": "梦江南",
                        "global_role_id": "",
                        "role_id": "rid-a",
                        "zone": "zone-a",
                        "person_id": "",
                    }
                ]
            },
        }
        await service._enrich_detail_with_indicator(detail, match_time=1810000000)

        player = detail["team1"]["players_info"][0]
        self.assertEqual(indicator.calls, [])
        self.assertEqual(player["global_role_id"], "SK01-local")
        self.assertEqual(player["person_id"], "pid-local")

    async def test_indicator_requests_when_local_identity_missing_global_role_id(self) -> None:
        indicator = FakeIndicatorClient({
            "zone-a:rid-a:梦江南": {
                "role_info": {"global_role_id": "SK01-api", "role_id": "rid-a"},
                "person_info": {"person_id": "pid-api"},
            }
        })
        identity_repo = FakeIdentityRepo()
        identity_repo.resolve_results = {
            "global_id": "99999",
            "role_id": "rid-a",
            "zone": "zone-a",
            "server": "梦江南",
            "role_name": "角色A",
            "person_id": "pid-local",
            "role_info_observed_match_time": 1810000000,
        }
        service = JjcMatchDataSyncService(
            repo=FakeRepo(),
            current_season="赛季",
            current_season_start="2026-04-24",
            role_indicator_client=indicator,
            identity_repo=identity_repo,
            sleep_func=_noop_sleep,
        )

        detail = {
            "team1": {
                "players_info": [
                    {
                        "role_name": "角色A",
                        "server": "梦江南",
                        "global_role_id": "",
                        "role_id": "rid-a",
                        "zone": "zone-a",
                        "person_id": "",
                    }
                ]
            },
        }
        await service._enrich_detail_with_indicator(detail, match_time=1810000000)

        player = detail["team1"]["players_info"][0]
        self.assertEqual(len(indicator.calls), 1)
        self.assertEqual(player["global_role_id"], "SK01-api")
        self.assertEqual(player["person_id"], "pid-api")

    async def test_indicator_requests_when_match_is_newer_than_local_identity(self) -> None:
        indicator = FakeIndicatorClient({
            "zone-a:rid-a:梦江南": {
                "role_info": {"global_role_id": "SK01-new", "role_id": "rid-a"},
                "person_info": {"person_id": "pid-new"},
            }
        })
        identity_repo = FakeIdentityRepo()
        identity_repo.resolve_results = {
            "global_role_id": "SK01-old",
            "global_id": "99999",
            "role_id": "rid-a",
            "zone": "zone-a",
            "server": "梦江南",
            "role_name": "角色A",
            "person_id": "pid-old",
            "role_info_observed_match_time": 1809999999,
        }
        service = JjcMatchDataSyncService(
            repo=FakeRepo(),
            current_season="赛季",
            current_season_start="2026-04-24",
            role_indicator_client=indicator,
            identity_repo=identity_repo,
            sleep_func=_noop_sleep,
        )

        detail = {
            "team1": {
                "players_info": [
                    {
                        "role_name": "角色A",
                        "server": "梦江南",
                        "global_role_id": "",
                        "role_id": "rid-a",
                        "zone": "zone-a",
                        "person_id": "",
                    }
                ]
            },
        }
        await service._enrich_detail_with_indicator(detail, match_time=1810000000)

        player = detail["team1"]["players_info"][0]
        self.assertEqual(len(indicator.calls), 1)
        self.assertEqual(player["global_role_id"], "SK01-new")
        self.assertEqual(player["person_id"], "pid-new")

    async def test_indicator_person_id_conflict_keeps_detail_person_id(self) -> None:
        indicator = FakeIndicatorClient({
            "zone-a:rid-a:梦江南": {
                "role_info": {"global_role_id": "SK01-abc"},
                "person_info": {"person_id": "pid-ind"},
            }
        })
        service = JjcMatchDataSyncService(
            repo=FakeRepo(),
            current_season="赛季",
            current_season_start="2026-04-24",
            role_indicator_client=indicator,
            sleep_func=_noop_sleep,
        )

        detail = {
            "team1": {
                "players_info": [
                    {
                        "role_name": "角色A",
                        "server": "梦江南",
                        "global_role_id": "",
                        "role_id": "rid-a",
                        "zone": "zone-a",
                        "person_id": "pid-detail",
                    }
                ]
            },
        }
        await service._enrich_detail_with_indicator(detail)

        player = detail["team1"]["players_info"][0]
        self.assertEqual(player["global_role_id"], "SK01-abc")
        self.assertEqual(player["person_id"], "pid-detail")

    async def test_replay_failure_does_not_fail_detail_save(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "status": "queued",
            "identity_key": "global:seed",
            "server": "梦江南",
            "name": "种子",
            "global_role_id": "seed",
        }]
        history = FakeHistoryClient([
            {"data": [{"match_id": 100, "match_time": 1810000000, "pvpType": 3}]}
        ])
        replay = FakeReplayClient(error_on_call=True)
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(),
            match_replay_client=replay,
            sleep_func=_noop_sleep,
        )

        result = await service.run_once()

        self.assertFalse(result["error"])
        self.assertEqual(result["saved_details"], 1)
        self.assertEqual(result["failed_roles"], 0)  # detail save succeeded

    async def test_indicator_failure_does_not_fail_detail_save(self) -> None:
        repo = FakeRepo()
        repo.roles = [{
            "status": "queued",
            "identity_key": "global:seed",
            "server": "梦江南",
            "name": "种子",
            "global_role_id": "seed",
        }]
        history = FakeHistoryClient([
            {"data": [{"match_id": 101, "match_time": 1810000000, "pvpType": 3}]}
        ])
        indicator = FakeIndicatorClient(error_on_call=True)
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(),
            role_indicator_client=indicator,
            sleep_func=_noop_sleep,
        )

        result = await service.run_once()

        self.assertFalse(result["error"])
        self.assertEqual(result["saved_details"], 1)
        self.assertEqual(result["failed_roles"], 0)

    async def test_replay_and_indicator_chain_enriches_then_enqueues(self) -> None:
        """End-to-end: replay merges role_id/zone, then indicator backfills SK01 global_role_id."""
        replay = FakeReplayClient({
            "data": {
                "players": [
                    {
                        "role_name": "角色A·梦江南",
                        "role_id": "rid-replay",
                        "zone": "zone-replay",
                        "global_role_id": "99999",
                    }
                ]
            }
        })
        indicator = FakeIndicatorClient({
            "zone-replay:rid-replay:梦江南": {
                "role_info": {"global_role_id": "SK01-chain"},
                "person_info": {"person_id": "pid-chain"},
            }
        })
        repo = FakeRepo()
        identity_repo = FakeIdentityRepo()
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_replay_client=replay,
            role_indicator_client=indicator,
            identity_repo=identity_repo,
            sleep_func=_noop_sleep,
        )

        detail = {
            "team1": {
                "players_info": [
                    {
                        "role_name": "角色A",
                        "server": "梦江南",
                        "global_role_id": "",
                        "role_id": "",
                        "zone": "",
                        "person_id": "",
                    }
                ]
            },
        }
        await service._enrich_detail_with_replay(detail, 1)
        await service._enrich_detail_with_indicator(detail)
        await service._enqueue_players_from_detail(detail)

        self.assertEqual(replay.calls, [1])
        self.assertEqual(len(indicator.calls), 1)
        self.assertEqual(indicator.calls[0]["role_id"], "rid-replay")
        self.assertEqual(indicator.calls[0]["zone"], "zone-replay")
        self.assertEqual(identity_repo.upserted[0]["global_id"], "99999")
        self.assertEqual(repo.upserted_roles[0]["global_id"], "99999")
        self.assertEqual(repo.upserted_roles[0]["global_role_id"], "SK01-chain")
        self.assertEqual(repo.upserted_roles[0]["person_id"], "pid-chain")

    async def test_replay_and_indicator_none_clients_do_not_crash(self) -> None:
        """Service works fine when replay/indicator clients are None (backwards compat)."""
        repo = FakeRepo()
        repo.roles = [{
            "status": "queued",
            "identity_key": "global:seed",
            "server": "梦江南",
            "name": "种子",
            "global_role_id": "seed",
        }]
        history = FakeHistoryClient([
            {"data": [{"match_id": 102, "match_time": 1810000000, "pvpType": 3}]}
        ])
        service = JjcMatchDataSyncService(
            repo=repo,
            current_season="赛季",
            current_season_start="2026-04-24",
            match_history_client=history,
            inspect_service=FakeInspectService(),
            match_replay_client=None,
            role_indicator_client=None,
            sleep_func=_noop_sleep,
        )

        result = await service.run_once()

        self.assertFalse(result["error"])
        self.assertEqual(result["saved_details"], 1)
        self.assertEqual(result["failed_roles"], 0)


if __name__ == "__main__":
    unittest.main()

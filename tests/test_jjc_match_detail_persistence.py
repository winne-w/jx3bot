from __future__ import annotations

import copy
import unittest
from typing import Any, Dict, List, Optional

from src.services.jx3.match_detail_persistence import MatchDetailPersistenceService


class FakeInspectRepo:
    def __init__(self, events: List[str], save_result: Any = True, error: Optional[Exception] = None) -> None:
        self.events = events
        self.save_result = save_result
        self.error = error
        self.calls: List[Dict[str, Any]] = []

    async def save_match_detail(self, match_id: Any, payload: Dict[str, Any]) -> Any:
        self.events.append("main")
        self.calls.append({"match_id": match_id, "payload": payload})
        if self.error is not None:
            raise self.error
        return self.save_result


class FakeIdentityProjector:
    def __init__(self, events: List[str], result: Optional[Dict[str, Any]] = None,
                 error: Optional[Exception] = None, mutate_payload: bool = False) -> None:
        self.events = events
        self.result = result if result is not None else {"projected": 1}
        self.error = error
        self.mutate_payload = mutate_payload
        self.calls: List[Dict[str, Any]] = []

    async def project_payload(self, **kwargs: Any) -> Dict[str, Any]:
        self.events.append("identity")
        self.calls.append(copy.deepcopy(kwargs))
        if self.mutate_payload and isinstance(kwargs.get("payload"), dict):
            kwargs["payload"]["identity_mutated"] = True
        if self.error is not None:
            raise self.error
        return self.result


class FakeParticipantProjector:
    def __init__(self, events: List[str], project_error: Optional[Exception] = None,
                 clear_result: Optional[Dict[str, Any]] = None, clear_error: Optional[Exception] = None,
                 mutate_payload: bool = False, mutate_seen_doc: bool = False) -> None:
        self.events = events
        self.project_error = project_error
        self.clear_result = clear_result if clear_result is not None else {"deleted": 6}
        self.clear_error = clear_error
        self.mutate_payload = mutate_payload
        self.mutate_seen_doc = mutate_seen_doc
        self.project_calls: List[Dict[str, Any]] = []
        self.clear_calls: List[Any] = []

    async def project_payload(self, **kwargs: Any) -> Dict[str, Any]:
        self.events.append("participant_project")
        self.project_calls.append(copy.deepcopy(kwargs))
        if self.mutate_payload and isinstance(kwargs.get("payload"), dict):
            kwargs["payload"]["participant_mutated"] = True
        if self.mutate_seen_doc and isinstance(kwargs.get("seen_doc"), dict):
            kwargs["seen_doc"]["participant_mutated"] = True
        if self.project_error is not None:
            raise self.project_error
        return {"projected": 6}

    async def clear_match(self, match_id: Any) -> Dict[str, Any]:
        self.events.append("participant_clear")
        self.clear_calls.append(match_id)
        if self.clear_error is not None:
            raise self.clear_error
        return self.clear_result


class FakeFactProjector:
    def __init__(self, events: List[str], result: Optional[Dict[str, Any]] = None,
                 error: Optional[Exception] = None, mutate_payload: bool = False) -> None:
        self.events = events
        self.result = result if result is not None else {"status": "updated"}
        self.error = error
        self.mutate_payload = mutate_payload
        self.calls: List[Dict[str, Any]] = []

    async def project_payload(self, **kwargs: Any) -> Dict[str, Any]:
        self.events.append("fact")
        self.calls.append(copy.deepcopy(kwargs))
        if self.mutate_payload and isinstance(kwargs.get("payload"), dict):
            kwargs["payload"]["fact_mutated"] = True
        if self.error is not None:
            raise self.error
        return self.result


def build_payload(*, unavailable: bool = False) -> Dict[str, Any]:
    data: Dict[str, Any] = {"match_id": 987, "detail": {"team1": {}, "team2": {}}}
    if unavailable:
        data["unavailable"] = True
    return {"cached_at": 1234, "data": data}


class TestMatchDetailPersistenceService(unittest.IsolatedAsyncioTestCase):
    def build_service(
        self,
        *,
        save_result: Any = True,
        main_error: Optional[Exception] = None,
        identity_error: Optional[Exception] = None,
        participant_error: Optional[Exception] = None,
        participant_clear_result: Optional[Dict[str, Any]] = None,
        participant_clear_error: Optional[Exception] = None,
        fact_error: Optional[Exception] = None,
        fact_result: Optional[Dict[str, Any]] = None,
        fact_projector: bool = True,
        identity_mutates_payload: bool = False,
        participant_mutates_payload: bool = False,
        participant_mutates_seen_doc: bool = False,
        fact_mutates_payload: bool = False,
    ) -> Any:
        self.events: List[str] = []
        self.repo = FakeInspectRepo(self.events, save_result=save_result, error=main_error)
        self.identity = FakeIdentityProjector(
            self.events,
            error=identity_error,
            mutate_payload=identity_mutates_payload,
        )
        self.participant = FakeParticipantProjector(
            self.events,
            project_error=participant_error,
            clear_result=participant_clear_result,
            clear_error=participant_clear_error,
            mutate_payload=participant_mutates_payload,
            mutate_seen_doc=participant_mutates_seen_doc,
        )
        self.fact = (
            FakeFactProjector(
                self.events,
                result=fact_result,
                error=fact_error,
                mutate_payload=fact_mutates_payload,
            )
            if fact_projector
            else None
        )
        return MatchDetailPersistenceService(
            inspect_repo=self.repo,
            identity_projector=self.identity,
            participant_projector=self.participant,
            fact_projector=self.fact,
        )

    async def test_persist_saves_main_then_each_projection_in_order(self) -> None:
        service = self.build_service()
        payload = build_payload()

        result = await service.persist(987, payload, "test_source", seen_doc={"status": "seen"})

        self.assertEqual(self.events, ["main", "identity", "participant_project", "fact"])
        self.assertTrue(result.main_saved)
        self.assertIsNone(result.main_error)
        self.assertTrue(result.identity_attempted)
        self.assertEqual(result.identity_result, {"projected": 1})
        self.assertTrue(result.participant_attempted)
        self.assertEqual(result.participant_result, {"projected": 6})
        self.assertTrue(result.fact_attempted)
        self.assertEqual(result.fact_result, {"status": "updated"})

    async def test_persist_does_not_project_when_main_save_is_not_strictly_true(self) -> None:
        for save_result in (False, None, 1):
            with self.subTest(save_result=save_result):
                service = self.build_service(save_result=save_result)

                result = await service.persist(987, build_payload(), "test_source")

                self.assertFalse(result.main_saved)
                self.assertEqual(self.events, ["main"])
                self.assertFalse(result.identity_attempted)
                self.assertFalse(result.participant_attempted)
                self.assertFalse(result.fact_attempted)

    async def test_persist_records_main_exception_without_projecting(self) -> None:
        service = self.build_service(main_error=RuntimeError("mongo offline"))

        result = await service.persist(987, build_payload(), "test_source")

        self.assertFalse(result.main_saved)
        self.assertEqual(result.main_error, "mongo offline")
        self.assertEqual(self.events, ["main"])
        self.assertFalse(result.identity_attempted)
        self.assertFalse(result.participant_attempted)
        self.assertFalse(result.fact_attempted)

    async def test_identity_exception_does_not_block_participant_or_fact(self) -> None:
        service = self.build_service(identity_error=RuntimeError("identity failed"))

        result = await service.persist(987, build_payload(), "test_source")

        self.assertEqual(self.events, ["main", "identity", "participant_project", "fact"])
        self.assertEqual(result.identity_error, "identity failed")
        self.assertEqual(result.participant_result, {"projected": 6})
        self.assertEqual(result.fact_result, {"status": "updated"})

    async def test_participant_exception_does_not_block_fact(self) -> None:
        service = self.build_service(participant_error=RuntimeError("participant failed"))

        result = await service.persist(987, build_payload(), "test_source")

        self.assertEqual(self.events, ["main", "identity", "participant_project", "fact"])
        self.assertEqual(result.participant_error, "participant failed")
        self.assertEqual(result.fact_result, {"status": "updated"})

    async def test_fact_exception_is_recorded(self) -> None:
        service = self.build_service(fact_error=RuntimeError("fact failed"))

        result = await service.persist(987, build_payload(), "test_source")

        self.assertEqual(self.events, ["main", "identity", "participant_project", "fact"])
        self.assertTrue(result.fact_attempted)
        self.assertEqual(result.fact_error, "fact failed")

    async def test_fact_projector_is_optional(self) -> None:
        service = self.build_service(fact_projector=False)

        result = await service.persist(987, build_payload(), "test_source")

        self.assertEqual(self.events, ["main", "identity", "participant_project"])
        self.assertFalse(result.fact_attempted)
        self.assertIsNone(result.fact_error)

    async def test_unavailable_clears_participants_and_still_projects_fact(self) -> None:
        service = self.build_service()

        result = await service.persist(987, build_payload(unavailable=True), "unavailable_source")

        self.assertEqual(self.events, ["main", "identity", "participant_clear", "fact"])
        self.assertEqual(self.participant.clear_calls, [987])
        self.assertEqual(self.participant.project_calls, [])
        self.assertEqual(result.participant_result, {"deleted": 6})
        self.assertTrue(result.fact_attempted)

    async def test_unwrapped_unavailable_payload_is_passed_to_identity_and_fact(self) -> None:
        service = self.build_service()
        payload = {"unavailable": True, "detail": {"reason": "not found"}}

        result = await service.persist(987, payload, "unwrapped_unavailable")

        self.assertEqual(self.events, ["main", "identity", "participant_clear", "fact"])
        self.assertEqual(self.participant.project_calls, [])
        self.assertEqual(self.participant.clear_calls, [987])
        self.assertEqual(self.identity.calls[0]["payload"], payload)
        self.assertEqual(self.fact.calls[0]["payload"], payload)
        self.assertEqual(result.participant_result, {"deleted": 6})

    async def test_unavailable_clear_error_result_is_recorded_without_blocking_fact(self) -> None:
        service = self.build_service(participant_clear_result={"error": "clear pending retry"})

        result = await service.persist(987, build_payload(unavailable=True), "unavailable_source")

        self.assertEqual(self.events, ["main", "identity", "participant_clear", "fact"])
        self.assertEqual(result.participant_result, {"error": "clear pending retry"})
        self.assertEqual(result.participant_error, "clear pending retry")
        self.assertEqual(result.fact_result, {"status": "updated"})

    async def test_unavailable_clear_exception_is_recorded_without_blocking_fact(self) -> None:
        service = self.build_service(participant_clear_error=RuntimeError("clear failed"))

        result = await service.persist(987, build_payload(unavailable=True), "unavailable_source")

        self.assertEqual(self.events, ["main", "identity", "participant_clear", "fact"])
        self.assertEqual(result.participant_error, "clear failed")
        self.assertEqual(result.fact_result, {"status": "updated"})

    async def test_persist_passes_contract_arguments_without_mutating_input(self) -> None:
        service = self.build_service(
            fact_result={"error": "pending retry"},
            identity_mutates_payload=True,
            participant_mutates_payload=True,
            participant_mutates_seen_doc=True,
            fact_mutates_payload=True,
        )
        payload = build_payload()
        seen_doc = {"status": "detail_saved", "nested": {"value": 1}}
        original_payload = copy.deepcopy(payload)
        original_seen_doc = copy.deepcopy(seen_doc)

        result = await service.persist(987, payload, "contract_source", seen_doc=seen_doc)

        self.assertEqual(payload, original_payload)
        self.assertEqual(seen_doc, original_seen_doc)
        self.assertEqual(self.repo.calls[0], {"match_id": 987, "payload": original_payload})
        self.assertEqual(
            self.identity.calls[0],
            {"match_id": 987, "payload": original_payload["data"], "source": "contract_source"},
        )
        self.assertEqual(
            self.participant.project_calls[0],
            {
                "match_id": 987,
                "payload": original_payload,
                "seen_doc": original_seen_doc,
                "source": "contract_source",
            },
        )
        self.assertEqual(
            self.fact.calls[0],
            {"match_id": 987, "payload": original_payload, "source": "contract_source"},
        )
        self.assertEqual(result.fact_result, {"error": "pending retry"})
        self.assertEqual(result.fact_error, "pending retry")


if __name__ == "__main__":
    unittest.main()

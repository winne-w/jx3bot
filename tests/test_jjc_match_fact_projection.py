from __future__ import annotations

import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from src.services.jx3 import match_detail_fact_projection
from src.services.jx3.match_detail_fact_projection import MatchDetailFactProjectionService
from src.services.jx3.singletons import (
    jjc_match_fact_repo,
    match_detail_persistence_service,
)


def _player(kungfu_id: int, **overrides: Any) -> Dict[str, Any]:
    player: Dict[str, Any] = {
        "role_name": "角色%s" % kungfu_id,
        "server": "梦江南",
        "kungfu_id": kungfu_id,
        "kungfu": "心法%s" % kungfu_id,
        "total_score": 1000,
        "score": 900,
    }
    player.update(overrides)
    return player


def _payload() -> Dict[str, Any]:
    return {
        "cached_at": 1700000200,
        "data": {
            "detail": {
                "match_time": 1700000100,
                "basic_info": {"match_type": 3},
                "team1": {
                    "won": True,
                    "players_info": [_player(10001), _player(10002), _player(10003)],
                },
                "team2": {
                    "won": False,
                    "players_info": [_player(10004), _player(10005), _player(10006)],
                },
            }
        },
    }


class _FakeFactRepo:
    def __init__(self, status: str = "inserted", error: Optional[Exception] = None) -> None:
        self.status = status
        self.error = error
        self.documents: List[Dict[str, Any]] = []

    async def apply_projection(self, document: Dict[str, Any]) -> str:
        self.documents.append(document)
        if self.error is not None:
            raise self.error
        return self.status


class TestMatchDetailFactProjectionService(unittest.IsolatedAsyncioTestCase):
    async def test_singleton_wires_fact_projector_into_shared_persistence_service(self) -> None:
        projector = match_detail_persistence_service.fact_projector

        self.assertIsInstance(projector, MatchDetailFactProjectionService)
        self.assertIs(projector.fact_repo, jjc_match_fact_repo)

    async def test_projects_active_fact_through_repo_cas(self) -> None:
        repo = _FakeFactRepo()
        service = MatchDetailFactProjectionService(fact_repo=repo)

        result = await service.project_payload(
            match_id=123,
            payload=_payload(),
            source="ranking_warmup",
        )

        self.assertEqual(result["status"], "inserted")
        self.assertTrue(repo.documents[0]["active"])
        self.assertEqual(repo.documents[0]["match_id"], 123)

    async def test_reuses_build_match_fact_for_the_cas_document(self) -> None:
        repo = _FakeFactRepo(status="updated")
        service = MatchDetailFactProjectionService(fact_repo=repo, schema_version=2)
        expected_fact = {"match_id": 123, "active": True, "invalid_reason": None}

        with patch.object(
            match_detail_fact_projection,
            "build_match_fact",
            return_value=expected_fact,
        ) as build:
            result = await service.project_payload(
                match_id=123,
                payload={"cached_at": 1},
                source="sync_worker",
            )

        build.assert_called_once_with(123, {"cached_at": 1}, 2)
        self.assertEqual(repo.documents, [expected_fact])
        self.assertEqual(result, {"status": "updated", "active": True, "invalid_reason": None})

    async def test_projects_unavailable_payload_as_tombstone(self) -> None:
        repo = _FakeFactRepo()
        payload = _payload()
        payload["data"]["unavailable"] = True

        result = await MatchDetailFactProjectionService(fact_repo=repo).project_payload(
            match_id=123,
            payload=payload,
            source="inspect_cache_miss",
        )

        self.assertEqual(result["status"], "inserted")
        self.assertFalse(repo.documents[0]["active"])
        self.assertEqual(repo.documents[0]["invalid_reason"], "unavailable")

    async def test_projects_structurally_invalid_payload_as_tombstone(self) -> None:
        repo = _FakeFactRepo()
        payload = _payload()
        payload["data"]["detail"]["team1"]["players_info"].pop()

        result = await MatchDetailFactProjectionService(fact_repo=repo).project_payload(
            match_id=123,
            payload=payload,
            source="ranking_warmup",
        )

        self.assertEqual(result["status"], "inserted")
        self.assertFalse(repo.documents[0]["active"])
        self.assertEqual(repo.documents[0]["invalid_reason"], "invalid_team_structure")

    async def test_keeps_structurally_valid_payload_active_when_score_is_missing(self) -> None:
        repo = _FakeFactRepo()
        payload = _payload()
        payload["data"]["detail"]["team1"]["players_info"][0].update(
            total_score="bad",
            score="also bad",
        )

        result = await MatchDetailFactProjectionService(fact_repo=repo).project_payload(
            match_id=123,
            payload=payload,
            source="sync_worker",
        )

        self.assertEqual(result["status"], "inserted")
        self.assertTrue(repo.documents[0]["active"])
        self.assertFalse(repo.documents[0]["team1"]["score_complete"])
        self.assertEqual(repo.documents[0]["team1"]["score_count"], 2)

    async def test_preserves_skipped_old_status_for_late_old_source(self) -> None:
        repo = _FakeFactRepo(status="skipped_old")

        result = await MatchDetailFactProjectionService(fact_repo=repo).project_payload(
            match_id=123,
            payload=_payload(),
            source="historical_backfill",
        )

        self.assertEqual(result["status"], "skipped_old")
        self.assertTrue(result["active"])

    async def test_propagates_repo_projection_error(self) -> None:
        repo = _FakeFactRepo(error=RuntimeError("cas unavailable"))

        with self.assertRaisesRegex(RuntimeError, "cas unavailable"):
            await MatchDetailFactProjectionService(fact_repo=repo).project_payload(
                match_id=123,
                payload=_payload(),
                source="sync_worker",
            )


if __name__ == "__main__":
    unittest.main()

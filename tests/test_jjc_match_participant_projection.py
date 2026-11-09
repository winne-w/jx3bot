from __future__ import annotations

import unittest
from typing import Any, Dict, List

from src.services.jx3.match_detail_participant_projection import (
    MatchDetailParticipantProjectionService,
)


class _FakeParticipantRepo:
    def __init__(self) -> None:
        self.build_calls: List[Dict[str, Any]] = []
        self.replace_calls: List[Any] = []

    def build_participants_from_match_detail(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        self.build_calls.append({"args": args, "kwargs": kwargs})
        return [{"match_id": args[0], "global_id": "g1"}]

    async def replace_match_participants(self, match_id: Any, participants: List[Dict[str, Any]]) -> int:
        self.replace_calls.append((match_id, participants))
        return len(participants)


class TestMatchDetailParticipantProjectionService(unittest.IsolatedAsyncioTestCase):
    async def test_projects_with_current_season_configuration(self) -> None:
        repo = _FakeParticipantRepo()
        service = MatchDetailParticipantProjectionService(
            participant_repo=repo,
            current_season="暗影千机",
            season_start_time=1777228800,
        )

        result = await service.project_payload(
            match_id=1001,
            payload={"detail": {"team1": {}, "team2": {}}},
        )

        self.assertEqual(result["projected"], 1)
        self.assertEqual(repo.build_calls[0]["kwargs"]["current_season"], "暗影千机")
        self.assertEqual(repo.build_calls[0]["kwargs"]["season_start_time"], 1777228800)


if __name__ == "__main__":
    unittest.main()

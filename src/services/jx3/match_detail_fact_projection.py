"""Project persisted JJC match-detail payloads into rebuildable match facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from src.services.jx3.jjc_match_fact import build_match_fact
from src.storage.mongo_repos.jjc_match_fact_repo import JjcMatchFactRepo


MATCH_FACT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MatchDetailFactProjectionService:
    """Build one match fact or tombstone and persist it through the CAS repo."""

    fact_repo: JjcMatchFactRepo
    schema_version: int = MATCH_FACT_SCHEMA_VERSION

    async def project_payload(
        self,
        *,
        match_id: Any,
        payload: Dict[str, Any],
        source: str,
    ) -> Dict[str, Any]:
        fact = build_match_fact(match_id, payload, self.schema_version)
        status = await self.fact_repo.apply_projection(fact)
        return {
            "status": status,
            "active": fact["active"],
            "invalid_reason": fact.get("invalid_reason"),
        }

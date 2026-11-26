from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

try:
    from nonebot import logger  # type: ignore
except Exception:  # pragma: no cover - fallback for isolated unit tests
    import logging

    logger = logging.getLogger(__name__)


PERSIST_MATCH_DETAIL_SCHEMA = "jjc_match_detail_persistence.v1"
PARTICIPANT_DETAIL_SOURCE_BY_EVENT_SOURCE = {
    "inspect_cache_miss": "ranking_detail",
    "inspect_cache_hit_replay_enrich": "ranking_detail",
    "ranking_warmup": "warmup",
    "sync_worker": "sync_worker",
}
IDENTITY_PROJECTION_CONTEXT_BY_EVENT_SOURCE = {
    "sync_worker": {"source": "match_detail_sync", "priority": -10},
}


@dataclass(frozen=True)
class PersistMatchDetailResult:
    """Outcome of persisting a JJC detail and its independent projections."""

    match_id: Any
    source: str
    schema: str
    main_saved: bool
    main_error: Optional[str] = None
    identity_attempted: bool = False
    identity_result: Any = None
    identity_error: Optional[str] = None
    participant_attempted: bool = False
    participant_result: Any = None
    participant_error: Optional[str] = None
    fact_attempted: bool = False
    fact_result: Any = None
    fact_error: Optional[str] = None


def _result_error(result: Any) -> Optional[str]:
    if not isinstance(result, dict):
        return None
    error = result.get("error")
    if error is None:
        return None
    return str(error)


def _is_unavailable(payload: Dict[str, Any]) -> bool:
    data = payload.get("data")
    candidate = data if isinstance(data, dict) else payload
    return candidate.get("unavailable") is True


def participant_detail_source(event_source: str) -> str:
    """Map persistence events to the participant projection's stable source contract."""
    return PARTICIPANT_DETAIL_SOURCE_BY_EVENT_SOURCE.get(event_source, event_source)


def identity_projection_context(event_source: str) -> Dict[str, Any]:
    """Preserve identity projection provenance used by pre-unification callers."""
    return dict(IDENTITY_PROJECTION_CONTEXT_BY_EVENT_SOURCE.get(event_source, {"source": event_source}))


@dataclass(frozen=True)
class MatchDetailPersistenceService:
    """Persist the match-detail source of truth before independent projections."""

    inspect_repo: Any
    identity_projector: Optional[Any]
    participant_projector: Optional[Any]
    fact_projector: Optional[Any] = None
    schema: str = PERSIST_MATCH_DETAIL_SCHEMA

    def _log_error(self, *, match_id: Any, source: str, stage: str, error: Any) -> None:
        context = {
            "match_id": match_id,
            "source": source,
            "schema": self.schema,
            "stage": stage,
            "error": str(error),
        }
        bind = getattr(logger, "bind", None)
        if callable(bind):
            try:
                bind(**context).warning("JJC 对局详情持久化阶段失败")
                return
            except Exception:
                pass
        logger.warning(
            "JJC 对局详情持久化阶段失败: "
            "match_id=%r source=%r schema=%r stage=%r error=%r"
            % (match_id, source, self.schema, stage, str(error))
        )

    async def _run_projection_stage(
        self,
        *,
        match_id: Any,
        source: str,
        stage: str,
        runner: Callable[[], Awaitable[Any]],
    ) -> Tuple[Any, Optional[str]]:
        try:
            result = await runner()
            error = _result_error(result)
            if error is not None:
                self._log_error(
                    match_id=match_id,
                    source=source,
                    stage=stage,
                    error=error,
                )
            return result, error
        except Exception as exc:
            error = str(exc)
            self._log_error(
                match_id=match_id,
                source=source,
                stage=stage,
                error=error,
            )
            return None, error

    async def persist(
        self,
        match_id: Any,
        payload: Dict[str, Any],
        source: str,
        seen_doc: Optional[Dict[str, Any]] = None,
    ) -> PersistMatchDetailResult:
        """Save the source detail, then best-effort project each read model in order."""
        try:
            main_saved = await self.inspect_repo.save_match_detail(
                match_id,
                copy.deepcopy(payload),
            )
        except Exception as exc:
            main_error = str(exc)
            self._log_error(
                match_id=match_id,
                source=source,
                stage="main",
                error=main_error,
            )
            return PersistMatchDetailResult(
                match_id=match_id,
                source=source,
                schema=self.schema,
                main_saved=False,
                main_error=main_error,
            )

        if main_saved is not True:
            main_error = "save_match_detail returned {!r}".format(main_saved)
            self._log_error(
                match_id=match_id,
                source=source,
                stage="main",
                error=main_error,
            )
            return PersistMatchDetailResult(
                match_id=match_id,
                source=source,
                schema=self.schema,
                main_saved=False,
                main_error=main_error,
            )

        async def _run_identity() -> Any:
            wrapped_data = payload.get("data")
            identity_payload = wrapped_data if isinstance(wrapped_data, dict) else payload
            identity_context = identity_projection_context(source)
            return await self.identity_projector.project_payload(
                match_id=match_id,
                payload=copy.deepcopy(identity_payload),
                **identity_context,
            )

        async def _run_participant() -> Any:
            if _is_unavailable(payload):
                return await self.participant_projector.clear_match(match_id)
            return await self.participant_projector.project_payload(
                match_id=match_id,
                payload=copy.deepcopy(payload),
                seen_doc=copy.deepcopy(seen_doc),
                source=participant_detail_source(source),
            )

        async def _run_fact() -> Any:
            return await self.fact_projector.project_payload(
                match_id=match_id,
                payload=copy.deepcopy(payload),
                source=source,
            )

        stage_specs = (
            ("identity", self.identity_projector, _run_identity),
            ("participant", self.participant_projector, _run_participant),
            ("fact", self.fact_projector, _run_fact),
        )
        outcomes: Dict[str, Tuple[bool, Any, Optional[str]]] = {}
        for stage_name, projector, runner in stage_specs:
            if projector is None:
                outcomes[stage_name] = (False, None, None)
            else:
                stage_result, stage_error = await self._run_projection_stage(
                    match_id=match_id,
                    source=source,
                    stage=stage_name,
                    runner=runner,
                )
                outcomes[stage_name] = (True, stage_result, stage_error)

        identity_attempted, identity_result, identity_error = outcomes["identity"]
        participant_attempted, participant_result, participant_error = outcomes["participant"]
        fact_attempted, fact_result, fact_error = outcomes["fact"]

        return PersistMatchDetailResult(
            match_id=match_id,
            source=source,
            schema=self.schema,
            main_saved=True,
            identity_attempted=identity_attempted,
            identity_result=identity_result,
            identity_error=identity_error,
            participant_attempted=participant_attempted,
            participant_result=participant_result,
            participant_error=participant_error,
            fact_attempted=fact_attempted,
            fact_result=fact_result,
            fact_error=fact_error,
        )

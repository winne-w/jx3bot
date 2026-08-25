from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
    from nonebot import logger  # type: ignore
except Exception:  # pragma: no cover - fallback for isolated unit tests
    import logging

    logger = logging.getLogger(__name__)


PERSIST_MATCH_DETAIL_SCHEMA = "jjc_match_detail_persistence.v1"


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

        identity_result = None
        identity_error = None
        identity_attempted = self.identity_projector is not None
        if self.identity_projector is not None:
            try:
                wrapped_data = payload.get("data")
                identity_payload = wrapped_data if isinstance(wrapped_data, dict) else payload
                identity_result = await self.identity_projector.project_payload(
                    match_id=match_id,
                    payload=copy.deepcopy(identity_payload),
                    source=source,
                )
                identity_error = _result_error(identity_result)
                if identity_error is not None:
                    self._log_error(
                        match_id=match_id,
                        source=source,
                        stage="identity",
                        error=identity_error,
                    )
            except Exception as exc:
                identity_error = str(exc)
                self._log_error(
                    match_id=match_id,
                    source=source,
                    stage="identity",
                    error=identity_error,
                )

        participant_result = None
        participant_error = None
        participant_attempted = self.participant_projector is not None
        if self.participant_projector is not None:
            try:
                if _is_unavailable(payload):
                    participant_result = await self.participant_projector.clear_match(match_id)
                else:
                    participant_result = await self.participant_projector.project_payload(
                        match_id=match_id,
                        payload=copy.deepcopy(payload),
                        seen_doc=copy.deepcopy(seen_doc),
                        source=source,
                    )
                participant_error = _result_error(participant_result)
                if participant_error is not None:
                    self._log_error(
                        match_id=match_id,
                        source=source,
                        stage="participant",
                        error=participant_error,
                    )
            except Exception as exc:
                participant_error = str(exc)
                self._log_error(
                    match_id=match_id,
                    source=source,
                    stage="participant",
                    error=participant_error,
                )

        fact_result = None
        fact_error = None
        fact_attempted = self.fact_projector is not None
        if self.fact_projector is not None:
            try:
                fact_result = await self.fact_projector.project_payload(
                    match_id=match_id,
                    payload=copy.deepcopy(payload),
                    source=source,
                )
                fact_error = _result_error(fact_result)
                if fact_error is not None:
                    self._log_error(
                        match_id=match_id,
                        source=source,
                        stage="fact",
                        error=fact_error,
                    )
            except Exception as exc:
                fact_error = str(exc)
                self._log_error(
                    match_id=match_id,
                    source=source,
                    stage="fact",
                    error=fact_error,
                )

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

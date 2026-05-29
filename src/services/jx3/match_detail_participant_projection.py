from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.storage.mongo_repos.jjc_match_participant_repo import JjcMatchParticipantRepo

try:
    from nonebot import logger  # type: ignore
except Exception:  # pragma: no cover - fallback for isolated unit tests
    import logging

    logger = logging.getLogger(__name__)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


@dataclass(frozen=True)
class MatchDetailParticipantProjectionService:
    """Project cached JJC match detail into the participant read model."""

    participant_repo: JjcMatchParticipantRepo
    sync_repo: Optional[Any] = None

    async def _load_seen_doc(self, match_id: Any) -> Optional[Dict[str, Any]]:
        if self.sync_repo is None:
            return None

        method = getattr(self.sync_repo, "get_match_seen_doc", None)
        if method is not None:
            doc = await _maybe_await(method(match_id))
            if isinstance(doc, dict):
                return doc

        state_method = getattr(self.sync_repo, "get_match_detail_sync_state", None)
        if state_method is None:
            return None
        state = await _maybe_await(state_method(match_id))
        if not isinstance(state, dict) or not state.get("exists"):
            return None
        status = state.get("status")
        if status in (None, "", "missing", "invalid_match_id"):
            return None
        logger.warning("JJC 对局 seen 文档读取接口缺失，使用同步状态兜底: match_id=%s", match_id)
        return {
            "match_id": match_id,
            "status": status,
            "match_time": state.get("match_time"),
            "detail_saved_at": state.get("detail_saved_at"),
            "source_identity_id": state.get("source_identity_id"),
            "source_identity_key": state.get("source_identity_key"),
        }

    async def project_payload(
        self,
        *,
        match_id: Any,
        payload: Optional[Dict[str, Any]],
        seen_doc: Optional[Dict[str, Any]] = None,
        source: str = JjcMatchParticipantRepo.DETAIL_SOURCE_MATCH_DETAIL,
    ) -> Dict[str, Any]:
        try:
            actual_seen_doc = seen_doc
            if actual_seen_doc is None:
                actual_seen_doc = await self._load_seen_doc(match_id)
            participants = self.participant_repo.build_participants_from_match_detail(
                match_id,
                payload,
                seen_doc=actual_seen_doc,
                detail_source=source,
            )
            inserted = await self.participant_repo.replace_match_participants(match_id, participants)
            return {
                "projected": inserted,
                "skipped": not bool(participants),
                "sync_status": (
                    actual_seen_doc.get("status")
                    if isinstance(actual_seen_doc, dict) and actual_seen_doc.get("status")
                    else JjcMatchParticipantRepo.SYNC_STATUS_NOT_SYNCED
                ),
            }
        except Exception as exc:
            logger.warning("JJC 对局参与者投影失败: match_id=%s error=%s", match_id, exc)
            return {
                "projected": 0,
                "skipped": True,
                "error": str(exc),
            }

    async def clear_match(self, match_id: Any) -> Dict[str, Any]:
        try:
            deleted = await self.participant_repo.clear_match_participants(match_id)
            return {"deleted": deleted}
        except Exception as exc:
            logger.warning("JJC 对局参与者投影清理失败: match_id=%s error=%s", match_id, exc)
            return {"deleted": 0, "error": str(exc)}

    async def refresh_sync_status(
        self,
        match_id: Any,
        seen_doc: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            actual_seen_doc = seen_doc
            if actual_seen_doc is None:
                actual_seen_doc = await self._load_seen_doc(match_id)
            modified = await self.participant_repo.refresh_sync_status(match_id, actual_seen_doc)
            return {"modified": modified}
        except Exception as exc:
            logger.warning("JJC 对局参与者同步状态投影失败: match_id=%s error=%s", match_id, exc)
            return {"modified": 0, "error": str(exc)}

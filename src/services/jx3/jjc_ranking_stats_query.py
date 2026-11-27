"""Query and pure statistics helpers extracted from the JJC ranking-stats router."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.domain.kungfu_catalog import category_for_name

try:
    from nonebot import logger  # type: ignore
except Exception:  # pragma: no cover - fallback for isolated unit tests
    import logging

    logger = logging.getLogger(__name__)


RANGE_LIMITS: Dict[str, int] = {
    "top_1000": 1000,
    "top_200": 200,
    "top_100": 100,
    "top_50": 50,
}


def normalize_optional_text(value: Any) -> Optional[str]:
    """Strip an optional text parameter and collapse blank values to None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def build_peak_kungfu_statistics(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate peak-score ranking items into healer/dps/tank kungfu statistics."""
    lanes: Dict[str, Dict[str, Any]] = {
        "healer": {"distribution": {}, "valid_count": 0, "min_score": None},
        "dps": {"distribution": {}, "valid_count": 0, "min_score": None},
        "tank": {"distribution": {}, "valid_count": 0, "min_score": None},
    }
    for item in items:
        if not isinstance(item, dict):
            continue
        kungfu = normalize_optional_text(item.get("kungfu")) or "未知心法"
        category = category_for_name(kungfu)
        lane_key = category if category in lanes else "dps"
        lane = lanes[lane_key]
        lane["distribution"][kungfu] = int(lane["distribution"].get(kungfu, 0)) + 1
        lane["valid_count"] += 1
        score = item.get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            lane["min_score"] = (
                score if lane["min_score"] is None else min(lane["min_score"], score)
            )

    for lane in lanes.values():
        lane["list"] = sorted(
            lane["distribution"].items(),
            key=lambda pair: pair[1],
            reverse=True,
        )
        lane["legendary_count_map"] = {}
        if lane["min_score"] is None:
            lane["min_score"] = "-"
    return lanes


async def load_peak_score_doc(
    *,
    timestamp: str,
    score_type: str,
    range_key: str,
    version: int,
    range_limits: Optional[Dict[str, int]] = None,
    ranking_stats_repo: Optional[Any] = None,
    participant_repo: Optional[Any] = None,
    peak_repo: Optional[Any] = None,
    service_cls: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Load the peak-score ranking document for a given anchor timestamp and range."""
    limits = RANGE_LIMITS if range_limits is None else range_limits
    limit = limits.get(range_key)
    if limit is None:
        return None
    try:
        if service_cls is None:
            from src.services.jx3.jjc_peak_score_ranking import JjcPeakScoreRankingService

            service_cls = JjcPeakScoreRankingService
        if ranking_stats_repo is None:
            from src.storage.mongo_repos.jjc_ranking_stats_repo import JjcRankingStatsRepo

            ranking_stats_repo = JjcRankingStatsRepo()
        if participant_repo is None:
            from src.storage.mongo_repos.jjc_match_participant_repo import JjcMatchParticipantRepo

            participant_repo = JjcMatchParticipantRepo()
        if peak_repo is None:
            from src.storage.mongo_repos.jjc_peak_score_ranking_repo import JjcPeakScoreRankingRepo

            peak_repo = JjcPeakScoreRankingRepo(suppress_errors=False)
        return await service_cls(
            ranking_stats_repo=ranking_stats_repo,
            participant_repo=participant_repo,
            peak_repo=peak_repo,
        ).load_for_anchor(
            anchor_timestamp=int(timestamp),
            score_type=score_type,
            version=version,
            max_items=limit,
        )
    except Exception as exc:
        logger.warning(
            "JJC peak-score season read failed: anchor={} score_type={} error={}",
            timestamp,
            score_type,
            type(exc).__name__,
        )
        return None

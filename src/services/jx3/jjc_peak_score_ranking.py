from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from nonebot import logger
from pymongo.errors import ExecutionTimeout

from src.storage.mongo_repos.jjc_match_participant_repo import JjcMatchParticipantRepo
from src.storage.mongo_repos.jjc_peak_score_ranking_repo import JjcPeakScoreRankingRepo
from src.storage.mongo_repos.jjc_ranking_stats_repo import JjcRankingStatsRepo


SCORE_TYPES = ("tuilan", "game")
DEFAULT_MAX_ITEMS = 1000
AGGREGATION_SCOPE = "season_bounded_v1"


def _current_season() -> str:
    from config import CURRENT_SEASON
    return str(CURRENT_SEASON)


def _season_start_time() -> int:
    from config import CURRENT_SEASON_START
    return int(datetime.strptime(CURRENT_SEASON_START, "%Y-%m-%d").replace(
        tzinfo=timezone(timedelta(hours=8)),
    ).timestamp())


@dataclass
class JjcPeakScoreRankingService:
    ranking_stats_repo: Any = field(default_factory=JjcRankingStatsRepo)
    participant_repo: Any = field(default_factory=JjcMatchParticipantRepo)
    peak_repo: Any = field(default_factory=lambda: JjcPeakScoreRankingRepo(suppress_errors=False))
    window_days: int = 14
    version: int = 1
    max_items: Optional[int] = DEFAULT_MAX_ITEMS
    current_season: str = field(default_factory=_current_season)
    season_start_time: int = field(default_factory=_season_start_time)

    async def _context(self, anchor: int, cached: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        summary = await self.ranking_stats_repo.load_summary(anchor)
        season = str((summary or {}).get("current_season") or "").strip()
        if not season:
            return None
        if season == self.current_season:
            start = self.season_start_time
        elif anchor >= self.season_start_time:
            return None
        elif cached and cached.get("aggregation_scope") == AGGREGATION_SCOPE:
            start = cached.get("season_start_time")
            if cached.get("season_id") != season or (not isinstance(start, int) or isinstance(start, bool)) or start <= 0:
                return None
        else:
            # Historical legacy documents remain readable, but cannot be regenerated
            # without their own known season boundary.
            return {"season_id": season, "legacy": True}
        if (not isinstance(start, int) or isinstance(start, bool)) or start <= 0 or anchor < start:
            return None
        return {
            "aggregation_scope": AGGREGATION_SCOPE,
            "season_id": season,
            "season_start_time": start,
            "window_start": max(anchor - int(self.window_days) * 86400, start),
            "window_end": anchor,
            "window_days": self.window_days,
        }

    @staticmethod
    def _valid_cached(doc: Optional[Dict[str, Any]], context: Dict[str, Any]) -> bool:
        if not doc or doc.get("status") != "done":
            return False
        if context.get("legacy"):
            return not doc.get("aggregation_scope")
        return all(doc.get(key) == value for key, value in context.items())

    async def _load_cached(self, anchor: int, score_type: str, version: int, limit: Optional[int]) -> Optional[Dict[str, Any]]:
        try:
            return await asyncio.wait_for(self.peak_repo.load_result(
                anchor_timestamp=anchor, score_type=score_type, version=version,
                items_limit=limit, max_time_ms=1500,
            ), timeout=2.0)
        except (asyncio.TimeoutError, ExecutionTimeout):
            return None

    async def _aggregate(self, anchor: int, score_type: str, version: int,
                         context: Dict[str, Any], limit: Optional[int],
                         include_source_counts: bool) -> Dict[str, Any]:
        aggregate = await self.participant_repo.aggregate_peak_scores(
            window_start=context["window_start"], window_end=context["window_end"],
            score_type=score_type, max_items=limit,
            include_source_counts=include_source_counts,
        )
        items = aggregate.get("items") or []
        # Guard against a broken query adapter before publishing or serving a result.
        if any((not isinstance(item.get("match_time"), int) or isinstance(item.get("match_time"), bool)) or not (
            context["window_start"] <= item["match_time"] <= anchor
        ) for item in items):
            raise ValueError("peak_result_outside_season_window")
        return dict(context, anchor_timestamp=anchor, score_type=score_type,
                    version=version, status="done", items=items,
                    item_count=int(aggregate.get("item_count") or 0),
                    source_match_count=int(aggregate.get("source_match_count") or 0),
                    source_participant_count=int(aggregate.get("source_participant_count") or 0),
                    generated_at=time.time())

    async def load_for_anchor(self, *, anchor_timestamp: int, score_type: str,
                              version: Optional[int] = None,
                              max_items: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Read a validated snapshot, or aggregate its known season window without writes."""
        if score_type not in SCORE_TYPES:
            raise ValueError("unsupported_score_type")
        version = self.version if version is None else int(version)
        # There is currently one algorithm version; do not label arbitrary requests
        # as supported results merely because an on-demand aggregate is possible.
        if version != self.version:
            return None
        anchor = int(anchor_timestamp)
        limit = self.max_items if max_items is None else max_items
        cached = await self._load_cached(anchor, score_type, version, limit)
        context = await self._context(anchor, cached)
        if context is None:
            return None
        if self._valid_cached(cached, context):
            return cached
        if context.get("legacy"):
            return None
        result = await self._aggregate(anchor, score_type, version, context, limit, False)
        result["fallback_aggregate"] = True
        return result

    async def load_latest_anchor_timestamps(self, limit: int = 2) -> List[int]:
        result = await self.ranking_stats_repo.list_timestamps(
            page=1,
            page_size=max(1, int(limit)),
            with_meta=True,
        )
        items: Sequence[Any]
        if isinstance(result, dict):
            items = result.get("items") or []
        elif isinstance(result, list):
            items = result
        else:
            items = []

        timestamps: List[int] = []
        for item in items:
            value = item.get("timestamp") if isinstance(item, dict) else item
            try:
                timestamp = int(value)
            except (TypeError, ValueError):
                continue
            timestamps.append(timestamp)
            if len(timestamps) >= limit:
                break
        return timestamps

    async def run_latest_two_snapshots(self) -> Dict[str, Any]:
        anchors = await self.load_latest_anchor_timestamps(limit=2)
        results: List[Dict[str, Any]] = []
        for anchor in anchors:
            for score_type in SCORE_TYPES:
                results.append(
                    await self.generate_for_anchor(
                        anchor_timestamp=anchor,
                        score_type=score_type,
                    )
                )
        return {
            "anchors": anchors,
            "results": results,
            "generated": sum(1 for item in results if item.get("status") == "done" and not item.get("skipped")),
            "skipped": sum(1 for item in results if item.get("skipped")),
            "failed": sum(1 for item in results if item.get("status") == "failed"),
        }

    async def generate_for_anchor(
        self,
        *,
        anchor_timestamp: int,
        score_type: str,
        force: bool = False,
    ) -> Dict[str, Any]:
        if score_type not in SCORE_TYPES:
            raise ValueError("unsupported_score_type")

        window_end = int(anchor_timestamp)
        try:
            cached = await self._load_cached(window_end, score_type, self.version, self.max_items)
            context = await self._context(window_end, cached)
            if context is None:
                raise ValueError("unknown_or_invalid_snapshot_season")
            valid = self._valid_cached(cached, context)
            if valid and (not force or context.get("legacy")):
                return dict(cached, skipped=True)
            if context.get("legacy"):
                raise ValueError("historical_season_boundary_unavailable")
            result = await self._aggregate(window_end, score_type, self.version,
                                           context, self.max_items, True)
            # One atomic publication; computation/write failures leave the previous
            # document intact. The production repo must propagate write errors.
            await self.peak_repo.save_done(result)
            logger.info(
                "JJC 最高分排名生成完成: anchor={} score_type={} items={} source_matches={} source_participants={}".format(
                    window_end,
                    score_type,
                    result["item_count"],
                    result["source_match_count"],
                    result["source_participant_count"],
                )
            )
            return result
        except Exception as exc:
            safe_errors = {"unknown_or_invalid_snapshot_season", "historical_season_boundary_unavailable",
                           "peak_result_outside_season_window"}
            error = str(exc) if isinstance(exc, ValueError) and str(exc) in safe_errors else type(exc).__name__
            logger.warning(
                "JJC 最高分排名生成失败: anchor={} score_type={} error={}".format(
                    window_end,
                    score_type,
                    error,
                )
            )
            return {
                "anchor_timestamp": window_end,
                "score_type": score_type,
                "version": self.version,
                "status": "failed",
                "error": error,
            }

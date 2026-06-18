from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from nonebot import logger

from src.storage.mongo_repos.jjc_match_participant_repo import JjcMatchParticipantRepo
from src.storage.mongo_repos.jjc_peak_score_ranking_repo import JjcPeakScoreRankingRepo
from src.storage.mongo_repos.jjc_ranking_stats_repo import JjcRankingStatsRepo


SCORE_TYPES = ("tuilan", "game")


@dataclass
class JjcPeakScoreRankingService:
    ranking_stats_repo: Any = field(default_factory=JjcRankingStatsRepo)
    participant_repo: Any = field(default_factory=JjcMatchParticipantRepo)
    peak_repo: Any = field(default_factory=JjcPeakScoreRankingRepo)
    window_days: int = 7
    version: int = 1
    max_items: Optional[int] = None

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
    ) -> Dict[str, Any]:
        if score_type not in SCORE_TYPES:
            raise ValueError("unsupported_score_type")

        window_end = int(anchor_timestamp)
        window_start = window_end - int(self.window_days) * 86400
        if await self.peak_repo.is_done(
            anchor_timestamp=window_end,
            score_type=score_type,
            version=self.version,
        ):
            return {
                "anchor_timestamp": window_end,
                "score_type": score_type,
                "version": self.version,
                "status": "done",
                "skipped": True,
            }

        await self.peak_repo.mark_processing(
            anchor_timestamp=window_end,
            score_type=score_type,
            window_start=window_start,
            window_end=window_end,
            window_days=self.window_days,
            version=self.version,
        )

        try:
            aggregate = await self.participant_repo.aggregate_peak_scores(
                window_start=window_start,
                window_end=window_end,
                score_type=score_type,
                max_items=self.max_items,
            )
            result = {
                "anchor_timestamp": window_end,
                "window_start": window_start,
                "window_end": window_end,
                "score_type": score_type,
                "window_days": self.window_days,
                "version": self.version,
                "status": "done",
                "items": aggregate.get("items") or [],
                "item_count": int(aggregate.get("item_count") or 0),
                "source_match_count": int(aggregate.get("source_match_count") or 0),
                "source_participant_count": int(aggregate.get("source_participant_count") or 0),
                "generated_at": time.time(),
            }
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
            error = str(exc)
            await self.peak_repo.mark_failed(
                anchor_timestamp=window_end,
                score_type=score_type,
                window_start=window_start,
                window_end=window_end,
                window_days=self.window_days,
                version=self.version,
                error=error,
            )
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

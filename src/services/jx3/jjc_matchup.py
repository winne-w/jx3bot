"""Service contracts for JJC kungfu matchup queries."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import math
from typing import Any, Dict, List

from src.services.jx3.jjc_kungfu_meta import get_jjc_kungfu_catalog


_MAX_DAYS = 90
_MAX_TIME_SPAN_SECONDS = _MAX_DAYS * 24 * 60 * 60
_SCORE_MIN = 0
_SCORE_MAX = 1_000_000
_MAX_TEAM_KUNGFUS = 3
_MAX_PAGE = 100_000
_SUPPORTED_PAGE_SIZES = (20, 50, 100)


@dataclass
class JjcMatchupFilters:
    """Validated, canonical query filters passed to the matchup repository."""

    start_time: int
    end_time: int
    score_min: int
    score_max: int
    team_a_kungfu_ids: List[int]
    team_b_kungfu_ids: List[int]
    page: int
    page_size: int

    def to_dict(self) -> Dict[str, Any]:
        """Return a fresh dictionary suitable for repository calls and echoing."""
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "score_min": self.score_min,
            "score_max": self.score_max,
            "team_a_kungfu_ids": list(self.team_a_kungfu_ids),
            "team_b_kungfu_ids": list(self.team_b_kungfu_ids),
            "page": self.page,
            "page_size": self.page_size,
        }


class JjcMatchupService:
    """Validate matchup queries and delegate raw lookup data to a repository."""

    def __init__(self, matchup_repo: Any) -> None:
        self._matchup_repo = matchup_repo

    @staticmethod
    def _require_int(request: Dict[str, Any], field: str) -> int:
        value = request.get(field)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("{} must be an integer".format(field))
        return value

    @classmethod
    def _require_positive_int(cls, request: Dict[str, Any], field: str) -> int:
        value = cls._require_int(request, field)
        if value <= 0:
            raise ValueError("{} must be positive".format(field))
        return value

    @staticmethod
    def _normalize_kungfu_ids(request: Dict[str, Any], field: str) -> List[int]:
        values = request.get(field, [])
        if not isinstance(values, list) or len(values) > _MAX_TEAM_KUNGFUS:
            raise ValueError("{} must be a list with at most {} items".format(
                field,
                _MAX_TEAM_KUNGFUS,
            ))
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
               for value in values):
            raise ValueError("{} items must be positive integers".format(field))
        return sorted(values)

    def normalize_filters(self, request: Dict[str, Any]) -> JjcMatchupFilters:
        """Validate a request without invoking persistence and canonicalize its lists."""
        if not isinstance(request, dict):
            raise ValueError("request must be an object")

        start_time = self._require_positive_int(request, "start_time")
        end_time = self._require_positive_int(request, "end_time")
        if start_time >= end_time or end_time - start_time > _MAX_TIME_SPAN_SECONDS:
            raise ValueError("time range must be positive and no longer than {} days".format(
                _MAX_DAYS,
            ))

        score_min = self._require_int(request, "score_min")
        score_max = self._require_int(request, "score_max")
        if (score_min < _SCORE_MIN or score_min > _SCORE_MAX
                or score_max < _SCORE_MIN or score_max > _SCORE_MAX
                or score_min >= score_max):
            raise ValueError("score range must be within bounds and strictly increasing")

        page = request.get("page", 1)
        if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= _MAX_PAGE:
            raise ValueError("page must be an integer between 1 and {}".format(_MAX_PAGE))

        page_size = request.get("page_size", 20)
        if (isinstance(page_size, bool) or not isinstance(page_size, int)
                or page_size not in _SUPPORTED_PAGE_SIZES):
            raise ValueError("page_size must be one of {}".format(_SUPPORTED_PAGE_SIZES))

        return JjcMatchupFilters(
            start_time=start_time,
            end_time=end_time,
            score_min=score_min,
            score_max=score_max,
            team_a_kungfu_ids=self._normalize_kungfu_ids(request, "team_a_kungfu_ids"),
            team_b_kungfu_ids=self._normalize_kungfu_ids(request, "team_b_kungfu_ids"),
            page=page,
            page_size=page_size,
        )

    def get_meta(self) -> Dict[str, Any]:
        """Return fresh service metadata; HTTP response wrapping belongs to the router."""
        return {
            "kungfus": get_jjc_kungfu_catalog(),
            "time_presets": [1, 3, 7, 14, 30],
            "page_sizes": list(_SUPPORTED_PAGE_SIZES),
            "limits": {
                "max_days": _MAX_DAYS,
                "score_min": _SCORE_MIN,
                "score_max": _SCORE_MAX,
                "max_team_kungfus": _MAX_TEAM_KUNGFUS,
                "max_page": _MAX_PAGE,
            },
        }

    @staticmethod
    def _require_raw_count(statistics: Dict[str, Any], field: str) -> int:
        value = statistics.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("raw matchup statistics are invalid")
        return value

    @staticmethod
    def _win_rate(wins: int, orientation_sample_count: int) -> float:
        return float((
            Decimal(wins) * Decimal(100) / Decimal(orientation_sample_count)
        ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))

    @classmethod
    def _build_statistics(
        cls, raw_statistics: Any, has_directions: bool
    ) -> Dict[str, Any]:
        if not isinstance(raw_statistics, dict):
            raise ValueError("raw matchup statistics are invalid")

        match_count = cls._require_raw_count(raw_statistics, "match_count")
        bidirectional_match_count = cls._require_raw_count(
            raw_statistics, "bidirectional_match_count"
        )
        team_a_wins = cls._require_raw_count(raw_statistics, "team_a_wins")
        team_b_wins = cls._require_raw_count(raw_statistics, "team_b_wins")
        missing_score_match_count = cls._require_raw_count(
            raw_statistics, "missing_score_match_count"
        )

        if not has_directions:
            if bidirectional_match_count or team_a_wins or team_b_wins:
                raise ValueError("raw matchup statistics are inconsistent")
            return {
                "match_count": match_count,
                "orientation_sample_count": 0,
                "bidirectional_match_count": 0,
                "team_a_wins": None,
                "team_b_wins": None,
                "team_a_win_rate": None,
                "team_b_win_rate": None,
                "missing_score_match_count": missing_score_match_count,
            }

        orientation_sample_count = match_count + bidirectional_match_count
        if (bidirectional_match_count > match_count
                or team_a_wins + team_b_wins != orientation_sample_count):
            raise ValueError("raw matchup statistics are inconsistent")

        team_a_win_rate = None
        team_b_win_rate = None
        if orientation_sample_count:
            team_a_win_rate = cls._win_rate(team_a_wins, orientation_sample_count)
            team_b_win_rate = cls._win_rate(team_b_wins, orientation_sample_count)

        return {
            "match_count": match_count,
            "orientation_sample_count": orientation_sample_count,
            "bidirectional_match_count": bidirectional_match_count,
            "team_a_wins": team_a_wins,
            "team_b_wins": team_b_wins,
            "team_a_win_rate": team_a_win_rate,
            "team_b_win_rate": team_b_win_rate,
            "missing_score_match_count": missing_score_match_count,
        }

    @staticmethod
    def _require_summary_positive_int(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("raw matchup item is invalid")
        return value

    @staticmethod
    def _require_summary_game_score(value: Any) -> int:
        if (isinstance(value, bool) or not isinstance(value, int)
                or value < _SCORE_MIN or value > _SCORE_MAX):
            raise ValueError("raw matchup item is invalid")
        return value

    @staticmethod
    def _require_summary_string(value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("raw matchup item is invalid")
        return value

    @staticmethod
    def _require_summary_number(value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("raw matchup item is invalid")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("raw matchup item is invalid")
        return value

    @classmethod
    def _build_player_summary(cls, raw_player: Any) -> Dict[str, Any]:
        if not isinstance(raw_player, dict):
            raise ValueError("raw matchup item is invalid")
        return {
            "role_name": cls._require_summary_string(raw_player.get("role_name")),
            "server": cls._require_summary_string(raw_player.get("server")),
            "kungfu_id": cls._require_summary_positive_int(raw_player.get("kungfu_id")),
            "kungfu": cls._require_summary_string(raw_player.get("kungfu")),
            "game_score": cls._require_summary_game_score(raw_player.get("game_score")),
        }

    @classmethod
    def _build_team_summary(cls, raw_team: Any) -> Dict[str, Any]:
        if not isinstance(raw_team, dict) or not isinstance(raw_team.get("won"), bool):
            raise ValueError("raw matchup item is invalid")
        raw_players = raw_team.get("players")
        if not isinstance(raw_players, list) or len(raw_players) != 3:
            raise ValueError("raw matchup item is invalid")
        return {
            "won": raw_team["won"],
            "players": [cls._build_player_summary(player) for player in raw_players],
            "score_avg": cls._require_summary_number(raw_team.get("score_avg")),
        }

    @classmethod
    def _build_item_summary(cls, raw_item: Any, has_directions: bool) -> Dict[str, Any]:
        if not isinstance(raw_item, dict):
            raise ValueError("raw matchup item is invalid")
        duration = raw_item.get("duration")
        if (duration is not None and (isinstance(duration, bool)
                                     or not isinstance(duration, int)
                                     or duration < 0)):
            raise ValueError("raw matchup item is invalid")

        orientations = raw_item.get("matched_orientations")
        allowed_orientations = (
            (["forward"], ["reverse"], ["forward", "reverse"])
            if has_directions else ([],)
        )
        if not any(orientations == allowed for allowed in allowed_orientations):
            raise ValueError("raw matchup item is invalid")

        return {
            "match_id": cls._require_summary_positive_int(raw_item.get("match_id")),
            "match_time": cls._require_summary_positive_int(raw_item.get("match_time")),
            "map": cls._require_summary_string(raw_item.get("map")),
            "duration": duration,
            "team1": cls._build_team_summary(raw_item.get("team1")),
            "team2": cls._build_team_summary(raw_item.get("team2")),
            "matched_orientations": list(orientations),
        }

    async def search(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Return a validated statistics response around one raw repository page."""
        filters = self.normalize_filters(request)
        normalized_filters = filters.to_dict()
        raw_result = await self._matchup_repo.search_matchups(normalized_filters)
        if not isinstance(raw_result, dict):
            raise ValueError("raw matchup result is invalid")
        items = raw_result.get("items")
        if not isinstance(items, list):
            raise ValueError("raw matchup result is invalid")

        has_directions = bool(filters.team_a_kungfu_ids or filters.team_b_kungfu_ids)
        statistics = self._build_statistics(
            raw_result.get("statistics"),
            has_directions,
        )
        total = statistics["match_count"]
        return {
            "normalized_filters": filters.to_dict(),
            "statistics": statistics,
            "items": [
                self._build_item_summary(item, has_directions)
                for item in items
            ],
            "page": filters.page,
            "page_size": filters.page_size,
            "total": total,
            "has_more": filters.page * filters.page_size < total,
        }

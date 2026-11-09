"""Cache validity and retry policy for the current 3v3 role attribute."""
from dataclasses import dataclass
import math
from typing import Any, Dict, Iterable, Optional


def make_scope(season_id: str, season_start: int, algorithm_version: int = 1) -> Dict[str, Any]:
    if not str(season_id).strip() or type(season_start) is not int or season_start <= 0:
        raise ValueError("invalid kungfu season scope")
    if type(algorithm_version) is not int or algorithm_version <= 0:
        raise ValueError("invalid kungfu algorithm version")
    return {"season_id": str(season_id), "season_start": season_start,
            "pvp_type": 3, "algorithm_version": algorithm_version}


def retry_delay(failures: int) -> int:
    return min(60 * (2 ** min(max(int(failures) - 1, 0), 6)), 3600)


def positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def valid_timestamp(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


@dataclass(frozen=True)
class KungfuPolicy:
    scope: Dict[str, Any]
    refresh_seconds: int = 21600
    max_stale_seconds: int = 86400
    track_seconds: int = 172800

    def __post_init__(self) -> None:
        for value in (self.refresh_seconds, self.max_stale_seconds, self.track_seconds):
            if type(value) is not int or value <= 0:
                raise ValueError("kungfu cache intervals must be positive integers")
        if self.max_stale_seconds < self.refresh_seconds:
            raise ValueError("kungfu maximum age must cover refresh interval")
        expected = make_scope(self.scope.get("season_id", ""), self.scope.get("season_start"),
                              self.scope.get("algorithm_version", 1))
        if self.scope != expected:
            raise ValueError("kungfu cache supports current 3v3 scope only")
        object.__setattr__(self, "scope", dict(expected))

    def evaluate(self, result: Any, now: float,
                 valid_names: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        reason = None
        if not isinstance(result, dict) or not result:
            reason = "missing"
        elif any(type(result.get(k)) is not type(v) or result.get(k) != v
                 for k, v in self.scope.items()):
            reason = "scope_mismatch"
        elif not positive_integer(result.get("publish_version")):
            reason = "invalid_version"
        elif not result.get("name") or not result.get("kungfu_id") or (
                valid_names is not None and result["name"] not in valid_names):
            reason = "unknown_kungfu"
        elif not valid_timestamp(result.get("verified_at")) or not valid_timestamp(result.get("requested_at")):
            reason = "invalid_time"
        elif result["requested_at"] > result["verified_at"] or result["verified_at"] > now:
            reason = "invalid_time"
        elif now - result["verified_at"] > self.max_stale_seconds:
            reason = "expired"
        if reason:
            return {"freshness": "unknown", "reason": reason}
        freshness = "fresh" if now - result["verified_at"] <= self.refresh_seconds else "stale"
        return {"freshness": freshness, "reason": None}


def policy_from_config() -> KungfuPolicy:
    """Resolve and validate only when this optional feature is used."""
    import config as cfg
    from src.services.jx3.jjc_match_data_sync import parse_season_start_timestamp
    return KungfuPolicy(
        make_scope(cfg.CURRENT_SEASON, parse_season_start_timestamp(cfg.CURRENT_SEASON_START)),
        refresh_seconds=cfg.JJC_KUNGFU_REFRESH_SECONDS,
        max_stale_seconds=cfg.JJC_KUNGFU_MAX_STALE_SECONDS,
        track_seconds=cfg.JJC_KUNGFU_TRACK_SECONDS,
    )

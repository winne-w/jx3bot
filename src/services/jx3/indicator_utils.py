from __future__ import annotations

from typing import Any, Optional


def coerce_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def find_3v3_indicator(indicators: Any) -> Optional[dict[str, Any]]:
    if not isinstance(indicators, list):
        return None
    for indicator in indicators:
        if not isinstance(indicator, dict):
            continue
        indicator_type = str(indicator.get("type") or "")
        if indicator_type in {"3c", "3d"}:
            return indicator
        if find_3v3_metrics(indicator):
            return indicator
    return None


def find_3v3_metrics(indicator: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = indicator.get("metrics") or []
    if not isinstance(metrics, list):
        return []
    result = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        pvp_type = coerce_int(metric.get("pvp_type") or metric.get("pvpType") or metric.get("type"))
        if pvp_type is None or pvp_type == 3:
            result.append(metric)
    return result


def parse_3v3_indicator(raw: dict[str, Any]) -> dict[str, Any]:
    data = raw.get("data")
    if not isinstance(data, dict):
        return {"error": "indicator_data_missing"}
    indicators = data.get("indicator") or []
    if not isinstance(indicators, list):
        return {"error": "indicator_array_missing"}

    target = find_3v3_indicator(indicators)
    if target is None:
        return {"error": "indicator_3c_missing"}

    performance = target.get("performance")
    if not isinstance(performance, dict):
        performance = {}
    metrics = find_3v3_metrics(target)
    metric_3v3 = next(
        (
            item
            for item in metrics
            if isinstance(item, dict)
            and (coerce_int(item.get("pvp_type") or item.get("pvpType") or item.get("type")) in (None, 3))
            and (
                item.get("total_count") is not None
                or item.get("win_count") is not None
                or item.get("level") is not None
                or item.get("total") is not None
            )
        ),
        {},
    )

    total_matches = coerce_int(
        target.get("total_matches")
        or target.get("total_count")
        or target.get("total")
        or target.get("match_count")
        or performance.get("total_count")
        or performance.get("total")
        or performance.get("match_count")
        or metric_3v3.get("total_count")
        or metric_3v3.get("total")
        or metric_3v3.get("match_count")
    )
    win_rate = None
    raw_win_rate = (
        target.get("win_rate")
        or target.get("winRate")
        or target.get("win_percent")
        or performance.get("win_rate")
        or performance.get("winRate")
        or performance.get("win_percent")
        or metric_3v3.get("win_rate")
        or metric_3v3.get("winRate")
        or metric_3v3.get("win_percent")
    )
    if raw_win_rate is not None:
        try:
            win_rate = round(float(raw_win_rate), 1)
        except (ValueError, TypeError):
            pass
    if win_rate is None:
        win_count = coerce_int(
            target.get("win_count")
            or target.get("wins")
            or performance.get("win_count")
            or performance.get("wins")
            or metric_3v3.get("win_count")
            or metric_3v3.get("wins")
        )
        if win_count is not None and total_matches is not None and total_matches > 0:
            win_rate = round((win_count / total_matches) * 100, 1)

    score = coerce_int(
        target.get("score")
        or target.get("rating")
        or target.get("mmr")
        or target.get("current_score")
        or performance.get("score")
        or performance.get("rating")
        or performance.get("mmr")
        or performance.get("current_score")
        or metric_3v3.get("score")
        or metric_3v3.get("rating")
        or metric_3v3.get("mmr")
    )
    best_score = coerce_int(
        target.get("best_score")
        or target.get("bestScore")
        or target.get("best_rating")
        or target.get("max_score")
        or target.get("max_rating")
        or performance.get("best_score")
        or performance.get("bestScore")
        or performance.get("best_rating")
        or performance.get("max_score")
        or performance.get("max_rating")
        or metric_3v3.get("best_score")
        or metric_3v3.get("bestScore")
        or metric_3v3.get("best_rating")
        or metric_3v3.get("max_score")
    )
    grade = coerce_int(
        target.get("grade")
        or target.get("rank")
        or target.get("segment")
        or target.get("level")
        or performance.get("grade")
        or performance.get("rank")
        or performance.get("segment")
        or performance.get("level")
        or metric_3v3.get("grade")
        or metric_3v3.get("rank")
        or metric_3v3.get("segment")
        or metric_3v3.get("level")
    )

    if total_matches is None and score is None and grade is None:
        return {"error": "indicator_3c_empty_fields"}

    return {
        "source": "indicator",
        "type": str(target.get("type") or "3c"),
        "total_matches": total_matches,
        "win_rate": win_rate,
        "score": score,
        "best_score": best_score,
        "grade": grade,
    }


def select_best_3v3_metric(indicator: dict[str, Any], *, require_items: bool = False) -> Optional[dict[str, Any]]:
    best_metric = None
    best_win_count = -1
    best_total_count = -1
    for metric in find_3v3_metrics(indicator):
        if require_items and not metric.get("items"):
            continue
        win_count = coerce_int(metric.get("win_count") or metric.get("wins")) or 0
        total_count = coerce_int(metric.get("total_count") or metric.get("total") or metric.get("match_count")) or 0
        if (win_count, total_count) > (best_win_count, best_total_count):
            best_win_count = win_count
            best_total_count = total_count
            best_metric = metric
    return best_metric

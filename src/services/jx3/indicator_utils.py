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


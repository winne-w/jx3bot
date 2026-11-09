"""Shared pure main-kungfu decision; preserves the legacy sampling contract."""
from collections import Counter
from typing import Any, Dict, List

from src.services.jx3.indicator_utils import find_3v3_indicator, find_3v3_metrics


def select_kungfu(indicator_data: Dict[str, Any], matches: List[Dict[str, Any]],
                  mapping: Dict[str, str]) -> Dict[str, Any]:
    indicator = find_3v3_indicator(indicator_data.get("indicator") or [])
    best = None
    best_wins = -1
    if indicator:
        for metric in find_3v3_metrics(indicator):
            if metric.get("items") and (metric.get("win_count", 0) or 0) > best_wins:
                best = metric
                best_wins = metric.get("win_count", 0) or 0
    indicator_pinyin = best.get("kungfu") if best else None
    indicator_name = mapping.get(indicator_pinyin, indicator_pinyin)
    window = [m for m in matches if isinstance(m, dict)][:40]
    won = [m["kungfu"] for m in window if m.get("won") is True and m.get("kungfu")][:10]
    history_pinyin = None
    samples = []
    if len(won) == 10:
        counts = Counter(won)
        history_pinyin = max(counts, key=lambda k: (counts[k], -won.index(k)))
        samples = won
    history_name = mapping.get(history_pinyin, history_pinyin)
    use_history = bool(history_name and history_name != indicator_name)
    chosen_pinyin = history_pinyin if use_history else indicator_pinyin
    return {
        "kungfu": history_name if use_history else indicator_name,
        "kungfu_pinyin": chosen_pinyin,
        "kungfu_selected_source": "match_history" if use_history else "indicator",
        "kungfu_indicator": indicator_name,
        "kungfu_match_history": history_name,
        "kungfu_match_history_pinyin": history_pinyin,
        "match_history_checked": len(window),
        "match_history_win_samples": samples,
    }

from __future__ import annotations

from typing import Any, Iterable


def sum_specified_keys(data: Any, keys_to_sum: Iterable[str], keys_to_sum2: Iterable[str]):
    total_sum1 = 0
    speed_sum1 = 0
    total_sum2 = 0
    speed_sum2 = 0

    def recurse(value: Any) -> None:
        nonlocal total_sum1, speed_sum1, total_sum2, speed_sum2

        if isinstance(value, dict):
            for key, child in value.items():
                if key in keys_to_sum and isinstance(child, dict):
                    if "total" in child and isinstance(child["total"], (int, float)):
                        total_sum1 += child["total"]
                    if "speed" in child and isinstance(child["speed"], (int, float)):
                        speed_sum1 += child["speed"]
                elif key in keys_to_sum2 and isinstance(child, dict):
                    if "total" in child and isinstance(child["total"], (int, float)):
                        total_sum2 += child["total"]
                    if "speed" in child and isinstance(child["speed"], (int, float)):
                        speed_sum2 += child["speed"]
                recurse(child)
        elif isinstance(value, list):
            for item in value:
                recurse(item)

    recurse(data)
    return speed_sum1, total_sum1, speed_sum2, total_sum2


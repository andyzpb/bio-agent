from __future__ import annotations


def rate(values: list[bool]) -> float:
    if not values:
        return 0.0
    return round(sum(1 for value in values if value) / len(values), 4)

"""Shared answer selection helpers."""

from __future__ import annotations

import math
import random
from typing import Any, Optional


def coerce_positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except Exception:
        number = int(default)
    return max(0, number)


def valid_forced_choice_index(raw_value: Any, option_count: int) -> Optional[int]:
    try:
        candidate = int(raw_value)
    except Exception:
        return None
    if 0 <= candidate < option_count:
        return candidate
    return None


def format_weight_value(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return str(value or "").strip() or "随机"
    if math.isnan(number) or math.isinf(number):
        return "随机"
    text = f"{number:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def resolve_selected_weight_text(
    selected_index: int,
    resolved_probabilities: Any,
    raw_probabilities: Any,
) -> str:
    if isinstance(resolved_probabilities, list) and 0 <= selected_index < len(resolved_probabilities):
        return format_weight_value(resolved_probabilities[selected_index])
    if isinstance(raw_probabilities, list) and 0 <= selected_index < len(raw_probabilities):
        return format_weight_value(raw_probabilities[selected_index])
    return "随机"


def positive_multiple_indexes(weights: Any, option_count: int) -> list[int]:
    count = max(0, int(option_count or 0))
    if count <= 0:
        return []
    if not isinstance(weights, list) or not weights:
        return [random.randrange(count)]
    normalized: list[float] = []
    for idx in range(count):
        raw = weights[idx] if idx < len(weights) else 0.0
        try:
            normalized.append(max(0.0, float(raw)))
        except Exception:
            normalized.append(0.0)
    selected = [idx for idx, weight in enumerate(normalized) if weight > 0 and random.uniform(0, 100) <= weight]
    if not selected:
        positive = [idx for idx, weight in enumerate(normalized) if weight > 0]
        selected = [random.choice(positive)] if positive else [random.randrange(count)]
    return selected


def positive_multiple_indexes_with_limits(
    weights: Any,
    option_count: int,
    *,
    min_limit: Optional[int] = None,
    max_limit: Optional[int] = None,
) -> list[int]:
    count = max(0, int(option_count or 0))
    if count <= 0:
        return []

    resolved_min = max(0, min(count, int(min_limit or 0)))
    resolved_max = count if max_limit is None else max(0, min(count, int(max_limit or 0)))
    if resolved_max <= 0:
        resolved_max = count
    if resolved_min > resolved_max:
        resolved_min = resolved_max

    selected = list(dict.fromkeys(positive_multiple_indexes(weights, count)))
    if resolved_max < len(selected):
        selected = random.sample(selected, resolved_max)

    remaining_positive: list[int] = []
    if isinstance(weights, list) and weights:
        for idx in range(count):
            raw = weights[idx] if idx < len(weights) else 0.0
            try:
                weight = max(0.0, float(raw))
            except Exception:
                weight = 0.0
            if idx not in selected and weight > 0:
                remaining_positive.append(idx)
    remaining_any = [idx for idx in range(count) if idx not in selected and idx not in remaining_positive]
    random.shuffle(remaining_positive)
    random.shuffle(remaining_any)

    while len(selected) < resolved_min and (remaining_positive or remaining_any):
        source = remaining_positive if remaining_positive else remaining_any
        selected.append(source.pop(0))
    return selected[:resolved_max]

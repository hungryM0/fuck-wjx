"""腾讯问卷 HTTP 答案构造规则。"""

from __future__ import annotations

from typing import Sequence


def normalize_selected_indices(indices: Sequence[int], option_count: int) -> list[int]:
    result: list[int] = []
    seen = set()
    for raw in indices:
        try:
            idx = int(raw)
        except Exception:
            continue
        if idx < 0 or idx >= option_count or idx in seen:
            continue
        seen.add(idx)
        result.append(idx)
    return sorted(result)


def apply_multiple_constraints(
    selected_indices: Sequence[int],
    option_count: int,
    min_required: int,
    max_allowed: int,
    required_indices: Sequence[int],
    blocked_indices: Sequence[int],
    positive_priority_indices: Sequence[int],
) -> list[int]:
    blocked = set(normalize_selected_indices(blocked_indices, option_count))
    required = normalize_selected_indices(required_indices, option_count)
    selected = [idx for idx in normalize_selected_indices(selected_indices, option_count) if idx not in blocked]
    for idx in required:
        if idx not in selected:
            selected.append(idx)
    selected = normalize_selected_indices(selected, option_count)
    max_allowed = max(1, min(max_allowed, option_count))
    min_required = max(1, min(min_required, option_count))
    if len(selected) > max_allowed:
        kept = list(required[:max_allowed])
        for idx in selected:
            if idx in kept:
                continue
            if len(kept) >= max_allowed:
                break
            kept.append(idx)
        selected = normalize_selected_indices(kept, option_count)
    if len(selected) < min_required:
        for idx in list(positive_priority_indices) + list(range(option_count)):
            if idx in blocked or idx in selected:
                continue
            selected.append(idx)
            if len(selected) >= min_required:
                break
    if len(selected) > max_allowed:
        selected = selected[:max_allowed]
    return normalize_selected_indices(selected, option_count)


__all__ = ["apply_multiple_constraints", "normalize_selected_indices"]

"""问卷星多选题规则与约束。"""
import logging
import random
from typing import List, Optional, Set, Tuple

_WARNED_PROB_MISMATCH: Set[int] = set()

def _normalize_selected_indices(indices: List[int], option_count: int) -> List[int]:
    """去重并过滤越界索引，保持原始顺序。"""
    normalized: List[int] = []
    seen: Set[int] = set()
    for idx in indices:
        if idx in seen:
            continue
        if idx < 0 or idx >= option_count:
            continue
        seen.add(idx)
        normalized.append(idx)
    return normalized

def _resolve_rule_sets(
    must_select_indices: Set[int],
    must_not_select_indices: Set[int],
    option_count: int,
    current: int,
    rule_id: Optional[str],
) -> Tuple[List[int], Set[int]]:
    required = sorted(idx for idx in must_select_indices if 0 <= idx < option_count)
    blocked = {idx for idx in must_not_select_indices if 0 <= idx < option_count}
    overlap = blocked.intersection(required)
    if overlap:
        blocked -= set(required)
        logging.warning(
            "第%d题（多选）：条件规则[%s]同时将选项%s标记为必选和禁选，已按必选优先处理。",
            current,
            rule_id or "-",
            sorted(overlap),
        )
    return required, blocked

def _apply_rule_constraints(
    selected_indices: List[int],
    option_count: int,
    min_required: int,
    max_allowed: int,
    required_indices: List[int],
    blocked_indices: Set[int],
    positive_priority_indices: Optional[List[int]],
    current: int,
    rule_id: Optional[str],
) -> List[int]:
    required = _normalize_selected_indices(required_indices, option_count)
    if len(required) > max_allowed:
        logging.warning(
            "第%d题（多选）：条件规则[%s]要求必选 %d 项，但题目最多只能选 %d 项，已截断必选集合。",
            current,
            rule_id or "-",
            len(required),
            max_allowed,
        )
        required = required[:max_allowed]

    base_selected = _normalize_selected_indices(selected_indices, option_count)
    filtered_selected = [
        idx for idx in base_selected
        if idx not in blocked_indices and idx not in required
    ]
    available = [
        idx for idx in range(option_count)
        if idx not in blocked_indices and idx not in required
    ]

    extra_capacity = max(0, max_allowed - len(required))
    if len(filtered_selected) > extra_capacity:
        random.shuffle(filtered_selected)
        filtered_selected = filtered_selected[:extra_capacity]

    resolved = list(required)
    resolved.extend(filtered_selected)

    if len(resolved) < min_required:
        needed = min_required - len(resolved)
        priority: List[int] = []
        seen: Set[int] = set()
        for idx in positive_priority_indices or []:
            if idx in seen or idx in required or idx in blocked_indices:
                continue
            if idx < 0 or idx >= option_count:
                continue
            if idx in filtered_selected:
                continue
            seen.add(idx)
            priority.append(idx)
        fallback = [
            idx for idx in available
            if idx not in seen and idx not in filtered_selected
        ]
        random.shuffle(fallback)
        fill_pool = priority + fallback
        resolved.extend(fill_pool[:needed])
        if len(resolved) < min_required:
            logging.warning(
                "第%d题（多选）：条件规则[%s]生效后可用选项不足，要求最少选 %d 项，实际最多可选 %d 项。",
                current,
                rule_id or "-",
                min_required,
                len(resolved),
            )

    if len(resolved) > max_allowed:
        keep_required = [idx for idx in resolved if idx in required]
        keep_optional = [idx for idx in resolved if idx not in required]
        optional_capacity = max(0, max_allowed - len(keep_required))
        resolved = keep_required[:max_allowed] + keep_optional[:optional_capacity]

    return _normalize_selected_indices(resolved, option_count)

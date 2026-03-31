"""严格自定义比例约束工具。"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Sequence


def has_positive_weight_values(raw: Any) -> bool:
    """判断权重配置里是否存在正值，支持嵌套列表。"""
    if isinstance(raw, (int, float)):
        try:
            value = float(raw)
        except Exception:
            return False
        return math.isfinite(value) and value > 0.0

    if not isinstance(raw, (list, tuple)):
        return False

    stack: List[Any] = list(raw)
    while stack:
        item = stack.pop()
        if isinstance(item, (list, tuple)):
            stack.extend(item)
            continue
        try:
            value = float(item)
        except Exception:
            continue
        if math.isfinite(value) and value > 0.0:
            return True
    return False


def is_strict_custom_ratio_mode(
    distribution_mode: Any,
    probabilities: Any,
    custom_weights: Any,
) -> bool:
    """自定义配比题进入严格模式：手动比例为硬约束。"""
    mode = str(distribution_mode or "").strip().lower()
    if mode != "custom":
        return False
    return has_positive_weight_values(custom_weights) or has_positive_weight_values(probabilities)


def is_strict_ratio_question(task_ctx: Any, question_number: Any) -> bool:
    if task_ctx is None or question_number is None:
        return False
    try:
        q_num = int(question_number)
    except Exception:
        return False
    strict_map = getattr(task_ctx, "question_strict_ratio_map", {})
    if not isinstance(strict_map, dict):
        return False
    return bool(strict_map.get(q_num, False))


def stochastic_round(value: float) -> int:
    """按小数部分做随机取整，避免固定向上/向下偏差。"""
    if not math.isfinite(value) or value <= 0.0:
        return 0
    lower = int(math.floor(value))
    fraction = max(0.0, min(1.0, value - lower))
    return lower + 1 if random.random() < fraction else lower


def weighted_sample_without_replacement(
    indices: Sequence[int],
    weights: Sequence[float],
    count: int,
) -> List[int]:
    """按权重不放回抽样。"""
    if count <= 0:
        return []

    pool: List[List[float]] = []
    for idx, raw_weight in zip(indices, weights):
        try:
            weight = float(raw_weight)
        except Exception:
            weight = 0.0
        if not math.isfinite(weight) or weight <= 0.0:
            continue
        pool.append([int(idx), weight])

    if not pool:
        return []

    selected: List[int] = []
    target_count = min(int(count), len(pool))
    while pool and len(selected) < target_count:
        total = sum(item[1] for item in pool)
        if total <= 0.0:
            break
        pivot = random.random() * total
        running = 0.0
        chosen_idx = len(pool) - 1
        for pool_idx, (_, weight) in enumerate(pool):
            running += weight
            if pivot < running:
                chosen_idx = pool_idx
                break
        selected.append(int(pool.pop(chosen_idx)[0]))
    return selected


def build_rank_groups(probabilities: Sequence[float]) -> List[List[int]]:
    """按权重值分组，返回从高到低的索引层级。"""
    buckets: Dict[float, List[int]] = {}
    for idx, raw_weight in enumerate(probabilities):
        try:
            weight = float(raw_weight)
        except Exception:
            weight = 0.0
        if not math.isfinite(weight) or weight <= 0.0:
            continue
        buckets.setdefault(weight, []).append(idx)
    return [buckets[weight] for weight in sorted(buckets.keys(), reverse=True)]


def enforce_reference_rank_order(
    probabilities: Sequence[float],
    reference: Sequence[float],
) -> List[float]:
    """按参考权重的层级约束结果，避免低权重层反超高权重层。"""
    adjusted = [max(0.0, float(value)) if isinstance(value, (int, float)) else 0.0 for value in probabilities]
    groups = build_rank_groups(reference)
    if len(groups) <= 1:
        return adjusted

    previous_floor: Optional[float] = None
    for group in groups:
        group_values = [adjusted[idx] for idx in group if 0 <= idx < len(adjusted)]
        if not group_values:
            continue
        if previous_floor is not None:
            clamped_floor = max(0.0, previous_floor)
            for idx in group:
                if 0 <= idx < len(adjusted):
                    adjusted[idx] = min(adjusted[idx], clamped_floor)
            group_values = [adjusted[idx] for idx in group if 0 <= idx < len(adjusted)]
        if group_values:
            current_min = min(group_values)
            previous_floor = current_min if previous_floor is None else min(previous_floor, current_min)

    total = sum(adjusted)
    if total <= 0.0:
        return adjusted
    return [value / total for value in adjusted]

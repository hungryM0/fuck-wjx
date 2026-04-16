import math
from typing import Any, List, Optional, Tuple, Union

from software.core.questions.reliability_mode import get_reliability_profile
from software.core.questions.utils import normalize_droplist_probs

_STANDARD_CORRECTION_PARAMS = (12, 4.2, 0.45, 2.2, 0.42)


def build_distribution_stat_key(question_index: int, row_index: Optional[int] = None) -> str:
    if row_index is None:
        return f"q:{int(question_index)}"
    return f"matrix:{int(question_index)}:{int(row_index)}"


def _normalize_distribution_target(
    probabilities: Union[List[float], int, float, None],
    option_count: int,
) -> List[float]:
    if option_count <= 0:
        return []
    return normalize_droplist_probs(probabilities, option_count)


def _resolve_runtime_counts(
    ctx: Optional[Any],
    stat_key: str,
    option_count: int,
) -> Tuple[int, List[int]]:
    if ctx is None or not hasattr(ctx, "snapshot_distribution_stats"):
        return (0, [0] * max(0, int(option_count or 0)))
    try:
        total, counts = ctx.snapshot_distribution_stats(stat_key, option_count)
    except Exception:
        return (0, [0] * max(0, int(option_count or 0)))
    return (max(0, int(total or 0)), list(counts or []))


def _has_active_runtime_dimension(ctx: Optional[Any], question_index: Optional[int]) -> bool:
    if ctx is None or question_index is None or not hasattr(ctx, "question_dimension_map"):
        return False
    try:
        dimension = getattr(ctx, "question_dimension_map", {}).get(question_index)
    except Exception:
        return False
    return isinstance(dimension, str) and bool(str(dimension).strip())


def _psycho_plan_covers_question(
    psycho_plan: Optional[Any],
    question_index: Optional[int],
    row_index: Optional[int],
) -> bool:
    if psycho_plan is None or question_index is None or not hasattr(psycho_plan, "get_choice"):
        return False
    try:
        return psycho_plan.get_choice(question_index, row_index) is not None
    except Exception:
        return False


def _resolve_correction_params(
    *,
    use_priority_profile: bool,
) -> Tuple[int, float, float, float, float]:
    if not use_priority_profile:
        return _STANDARD_CORRECTION_PARAMS
    profile = get_reliability_profile()
    return (
        int(profile.distribution_warmup_samples),
        float(profile.distribution_gain),
        float(profile.distribution_min_factor),
        float(profile.distribution_max_factor),
        float(profile.distribution_gap_limit),
    )


def resolve_distribution_probabilities(
    probabilities: Union[List[float], int, float, None],
    option_count: int,
    ctx: Optional[Any],
    question_index: Optional[int],
    *,
    row_index: Optional[int] = None,
    psycho_plan: Optional[Any] = None,
) -> List[float]:
    target = _normalize_distribution_target(probabilities, option_count)
    if option_count <= 0 or not target or question_index is None or ctx is None:
        return target

    stat_key = build_distribution_stat_key(question_index, row_index)
    total, counts = _resolve_runtime_counts(ctx, stat_key, option_count)
    if total <= 0:
        return target

    use_priority_profile = (
        _has_active_runtime_dimension(ctx, question_index)
        or _psycho_plan_covers_question(psycho_plan, question_index, row_index)
    )
    warmup_samples, gain, min_factor, max_factor, gap_limit = _resolve_correction_params(
        use_priority_profile=use_priority_profile,
    )
    sample_factor = min(1.0, float(total) / float(max(1, warmup_samples)))
    if sample_factor <= 0.0:
        return target

    adjusted: List[float] = []
    for idx, target_ratio in enumerate(target):
        if target_ratio <= 0.0:
            adjusted.append(0.0)
            continue
        actual_ratio = float(counts[idx]) / float(total) if idx < len(counts) and total > 0 else 0.0
        gap = max(-gap_limit, min(gap_limit, target_ratio - actual_ratio))
        factor = math.exp(gain * sample_factor * gap)
        factor = max(min_factor, min(max_factor, factor))
        adjusted.append(target_ratio * factor)

    adjusted_total = sum(adjusted)
    if adjusted_total <= 0.0:
        return target
    return [value / adjusted_total for value in adjusted]


def record_pending_distribution_choice(
    ctx: Optional[Any],
    question_index: Optional[int],
    option_index: int,
    option_count: int,
    *,
    row_index: Optional[int] = None,
) -> None:
    if ctx is None or question_index is None or option_count <= 0:
        return
    if option_index < 0 or option_index >= option_count:
        return
    if not hasattr(ctx, "append_pending_distribution_choice"):
        return
    try:
        ctx.append_pending_distribution_choice(
            build_distribution_stat_key(question_index, row_index),
            option_index,
            option_count,
        )
    except Exception:
        return


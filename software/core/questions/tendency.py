"""
答题倾向模块 - 保证同一份问卷内量表类题目的前后一致性
"""
import random
import threading
import math
from typing import Any, Dict, List, Optional, Union
import logging
from software.logging.log_utils import log_suppressed_exception

from software.core.questions.reliability_mode import get_reliability_profile
from software.core.questions.utils import weighted_index
from software.app.config import DIMENSION_UNGROUPED

# 线程局部存储：每个浏览器线程有自己独立的答题倾向
_thread_local = threading.local()

_SMALL_SCALE_STATIC_MAX_OPTIONS = 3


def reset_tendency() -> None:
    """在每份问卷开始填写前调用，清除上一份的答题倾向。

    这样每份问卷会重新生成倾向，不同问卷之间仍然是随机的。
    """
    _thread_local.dimension_bases = {}


def _generate_base_ratio(
    option_count: int,
    probabilities: Union[List[float], int, None],
) -> float:
    """生成本份问卷的基准偏好比例（0.0~1.0），与具体选项数无关。

    base_ratio 语义始终是当前维度的基准偏好：0.0=偏左侧选项，1.0=偏右侧选项。
    它只根据当前题目的实际权重生成，不再额外解释题干语义方向。
    """
    if probabilities == -1 or probabilities is None:
        # 尝试从画像获取满意度倾向
        try:
            from software.core.persona.generator import get_current_persona
            persona = get_current_persona()
            if persona is not None:
                # satisfaction_tendency 本身已是 0.0~1.0，加少许扰动（约±10%量程）
                raw = persona.satisfaction_tendency
                jitter = random.gauss(0, 0.1)
                return max(0.0, min(1.0, raw + jitter))
        except Exception as exc:
            log_suppressed_exception("_generate_base_ratio: get_current_persona", exc, level=logging.ERROR)
        return random.random()
    if isinstance(probabilities, list) and probabilities:
        idx = weighted_index(probabilities)
        ratio = idx / max(option_count - 1, 1)
        return ratio
    return random.random()


def _is_ungrouped(dimension: Optional[str]) -> bool:
    """判断维度是否为"未分组"（不应用一致性约束）。"""
    return dimension is None or dimension == DIMENSION_UNGROUPED


def _random_by_probabilities(option_count: int, probabilities: Union[List[float], int, None]) -> int:
    """纯随机选择（不带一致性约束），用于未分组的题目。"""
    if isinstance(probabilities, list) and len(probabilities) == option_count:
        return weighted_index(probabilities)
    return random.randrange(option_count)


def _normalize_probabilities_for_zero_guard(
    option_count: int,
    probabilities: Union[List[float], int, None],
) -> Optional[List[float]]:
    """将概率配置对齐到选项数，供“0 权重禁选”约束使用。"""
    if option_count <= 0 or not isinstance(probabilities, list):
        return None

    normalized: List[float] = []
    for idx in range(option_count):
        raw = probabilities[idx] if idx < len(probabilities) else 0.0
        try:
            weight = float(raw)
        except Exception:
            weight = 0.0
        if math.isnan(weight) or math.isinf(weight) or weight <= 0.0:
            weight = 0.0
        normalized.append(weight)
    return normalized


def _enforce_zero_weight_guard(
    selected_index: int,
    option_count: int,
    probabilities: Union[List[float], int, None],
    anchor_index: Optional[int] = None,
) -> int:
    """硬约束：若某选项权重为 0，则最终结果绝不落在该选项。"""
    if option_count <= 0:
        return 0

    selected = max(0, min(option_count - 1, int(selected_index)))
    normalized = _normalize_probabilities_for_zero_guard(option_count, probabilities)
    if not normalized:
        return selected

    positive_indices = [idx for idx, weight in enumerate(normalized) if weight > 0.0]
    if not positive_indices:
        raise ValueError("当前题目所有选项权重均为 0，无法在“0 权重禁选”约束下作答，请至少保留一个非 0 选项。")
    if selected in positive_indices:
        return selected

    if anchor_index is None:
        target = selected
    else:
        target = max(0, min(option_count - 1, int(anchor_index)))

    # 选离目标最近的正权重项；同距离时优先更高权重，再按索引稳定排序
    best = positive_indices[0]
    best_distance = abs(best - target)
    best_weight = normalized[best]
    for idx in positive_indices[1:]:
        distance = abs(idx - target)
        weight = normalized[idx]
        if (
            distance < best_distance
            or (distance == best_distance and weight > best_weight)
            or (distance == best_distance and weight == best_weight and idx < best)
        ):
            best = idx
            best_distance = distance
            best_weight = weight

    return best


def _blend_psychometric_choice(
    anchor_index: int,
    option_count: int,
    probabilities: Union[List[float], int, None],
) -> int:
    anchor = max(0, min(option_count - 1, int(anchor_index)))
    if option_count <= 0 or not isinstance(probabilities, list) or len(probabilities) != option_count:
        return anchor

    fluctuation_window = _resolve_fluctuation_window(option_count)
    if fluctuation_window <= 0:
        return anchor
    profile = get_reliability_profile()

    low = max(0, anchor - fluctuation_window)
    high = min(option_count - 1, anchor + fluctuation_window)
    adjusted_probs: List[float] = []
    for idx in range(option_count):
        try:
            weight = float(probabilities[idx])
        except Exception:
            weight = 0.0
        if math.isnan(weight) or math.isinf(weight) or weight <= 0.0:
            adjusted_probs.append(0.0)
            continue
        if low <= idx <= high:
            distance = abs(idx - anchor)
            adjusted_probs.append(weight * _window_decay(distance, fluctuation_window))
        else:
            adjusted_probs.append(weight * (profile.consistency_outside_decay * 0.5))

    total = sum(adjusted_probs)
    if total <= 0.0:
        return anchor
    normalized = [value / total for value in adjusted_probs]
    return weighted_index(normalized)


def get_tendency_index(
    option_count: int,
    probabilities: Union[List[float], int, None],
    dimension: Optional[str] = None,
    # 可选：按心理测量计划直接取答案
    psycho_plan: Optional[Any] = None,
    question_index: Optional[int] = None,
    row_index: Optional[int] = None,
) -> int:
    """获取带有一致性倾向的选项索引。"""
    if option_count <= 0:
        return 0

    def _finalize_choice(choice: int, anchor: Optional[int] = None) -> int:
        return _enforce_zero_weight_guard(
            choice,
            option_count,
            probabilities,
            anchor_index=anchor,
        )

    # 传入心理测量计划时，优先按计划取答案
    if psycho_plan is not None and question_index is not None:
        choice = _get_psychometric_answer(psycho_plan, question_index, row_index, option_count)
        if choice is not None:
            if _is_distribution_locked_plan(psycho_plan, question_index, row_index):
                return _finalize_choice(choice, anchor=choice)
            blended_choice = _blend_psychometric_choice(
                choice,
                option_count,
                probabilities,
            )
            return _finalize_choice(blended_choice, anchor=choice)
        # 计划未命中时，回退到常规倾向逻辑
        logging.info(
            "心理测量计划未命中答案（题%d 行%s），回退到常规倾向逻辑",
            question_index, row_index
        )

    # 未分组 → 纯随机/纯概率，不做一致性约束
    if _is_ungrouped(dimension):
        result = _random_by_probabilities(option_count, probabilities)
        return _finalize_choice(result, anchor=result)

    # 获取该维度的基准偏好
    assert dimension is not None  # 已通过 _is_ungrouped 过滤，此处 dimension 必为 str
    bases: Dict[str, float] = getattr(_thread_local, 'dimension_bases', {})
    if not isinstance(bases, dict):
        bases = {}
        _thread_local.dimension_bases = bases

    base_ratio = bases.get(dimension)

    if base_ratio is None:
        # 该维度首次遇到：生成归一化比例（0.0~1.0）并存入
        base_ratio = _generate_base_ratio(option_count, probabilities)
        bases[dimension] = base_ratio

    # 将归一化比例还原为当前题的绝对索引，避免不同量程题目语义错位
    base = int(round(base_ratio * (option_count - 1)))
    base = max(0, min(option_count - 1, base))

    selected = _apply_consistency(base, option_count, probabilities)
    return _finalize_choice(selected, anchor=base)


def _apply_consistency(
    base: int,
    option_count: int,
    probabilities: Union[List[float], int, None],
) -> int:
    """在基准附近的自适应窗口内应用一致性约束选择选项。"""
    # 当前题目选项数可能与生成 base 时不同，需要夹到合法范围
    effective_base = min(base, option_count - 1)
    fluctuation_window = _resolve_fluctuation_window(option_count)
    if fluctuation_window <= 0:
        return effective_base

    # 在基准附近按量程自适应波动
    low = max(0, effective_base - fluctuation_window)
    high = min(option_count - 1, effective_base + fluctuation_window)

    # 如果有显式概率配置，需要结合原概率和距离衰减
    if isinstance(probabilities, list) and len(probabilities) == option_count:
        adjusted_probs = []
        for i in range(option_count):
            if low <= i <= high:
                distance = abs(i - effective_base)
                decay = _window_decay(distance, fluctuation_window)
                adjusted_probs.append(probabilities[i] * decay)
            else:
                adjusted_probs.append(
                    probabilities[i] * get_reliability_profile().consistency_outside_decay
                )

        total = sum(adjusted_probs)
        if total > 0:
            adjusted_probs = [p / total for p in adjusted_probs]
            return weighted_index(adjusted_probs)

    # 随机模式或无有效概率：在约束范围内按距离衰减抽样，偏向基准
    candidates = list(range(low, high + 1))
    weights = []
    for c in candidates:
        distance = abs(c - effective_base)
        weights.append(_window_decay(distance, fluctuation_window))

    total = sum(weights)
    pivot = random.random() * total
    running = 0.0
    for i, w in enumerate(weights):
        running += w
        if pivot <= running:
            return candidates[i]
    return candidates[-1]


def _resolve_fluctuation_window(option_count: int) -> int:
    """根据量程动态计算波动窗口。"""
    if option_count <= _SMALL_SCALE_STATIC_MAX_OPTIONS:
        # 3级及以下量表不做波动，避免语义直接翻转
        return 0

    profile = get_reliability_profile()
    span = max(option_count, 1)
    window = int(round(span * profile.consistency_window_ratio))
    if window < 1:
        window = 1
    return min(window, profile.consistency_window_max)


def _window_decay(distance: int, window: int) -> float:
    """窗口内距离衰减：中心最高，边缘次之。"""
    profile = get_reliability_profile()
    if distance <= 0:
        return profile.consistency_center_weight
    if window <= 0:
        return 0.0

    normalized = min(1.0, float(distance) / float(window))
    center = profile.consistency_center_weight
    edge = min(center, profile.consistency_edge_weight)
    return max(edge, center - (center - edge) * normalized)


def _get_psychometric_answer(
    plan: Any,
    question_index: int,
    row_index: Optional[int],
    option_count: int,
) -> Optional[int]:
    """从潜变量计划中获取答案"""
    try:
        choice = plan.get_choice(question_index, row_index)
        if choice is None:
            return None
        
        # 确保选项索引在有效范围内
        choice = max(0, min(option_count - 1, choice))
        
        return choice
    except Exception as exc:
        log_suppressed_exception(
            f"_get_psychometric_answer: question_index={question_index}, row_index={row_index}",
            exc,
            level=logging.WARNING
        )
        return None


def _is_distribution_locked_plan(
    plan: Any,
    question_index: int,
    row_index: Optional[int],
) -> bool:
    if plan is None or not hasattr(plan, "is_distribution_locked"):
        return False
    try:
        return bool(plan.is_distribution_locked(question_index, row_index))
    except Exception as exc:
        log_suppressed_exception(
            f"_is_distribution_locked_plan: question_index={question_index}, row_index={row_index}",
            exc,
            level=logging.WARNING,
        )
        return False





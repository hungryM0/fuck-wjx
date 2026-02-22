"""答题倾向模块 - 保证同一份问卷内量表类题目的前后一致性

问题：原来每道量表题完全独立随机，可能出现前面给5分后面给1分的情况，
导致 Cronbach's Alpha 信效度极低，一看就是假数据。

方案：每次填写问卷时，按维度（dimension）独立生成"基准偏好"，
同维度内的量表题围绕该基准 ±1 波动，不同维度之间互不干扰。
未分组的题目走纯随机，不受一致性约束。

增强（画像融合）：当存在虚拟画像时，基准偏好由画像的 satisfaction_tendency
决定，而非完全随机。这样画像越"满意"的人物，量表题越倾向选高分。
"""
import random
import threading
from typing import Dict, List, Optional, Union
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception

from wjx.core.questions.utils import weighted_index
from wjx.utils.app.config import DIMENSION_UNGROUPED

# 线程局部存储：每个浏览器线程有自己独立的答题倾向
_thread_local = threading.local()

# 波动范围（基准 ±1）
_FLUCTUATION = 1


def reset_tendency() -> None:
    """在每份问卷开始填写前调用，清除上一份的答题倾向。

    这样每份问卷会重新生成倾向，不同问卷之间仍然是随机的。
    """
    _thread_local.dimension_bases = {}


def _generate_base_index(option_count: int, probabilities: Union[List[float], int, None]) -> int:
    """根据概率配置生成本份问卷的基准偏好索引。

    如果有概率配置，按概率选择基准；否则参考画像的满意度倾向。
    当画像存在时，基准偏好 = satisfaction_tendency * (option_count - 1)，
    再加上少许随机扰动，让不同问卷间仍有差异。
    """
    if probabilities == -1 or probabilities is None:
        # 尝试从画像获取满意度倾向
        try:
            from wjx.core.persona.generator import get_current_persona
            persona = get_current_persona()
            if persona is not None:
                # 根据满意度倾向计算基准，加少许扰动
                raw = persona.satisfaction_tendency * (option_count - 1)
                jitter = random.gauss(0, 0.5)
                base = int(round(max(0, min(option_count - 1, raw + jitter))))
                return base
        except Exception as exc:
            log_suppressed_exception("_generate_base_index: from wjx.core.persona.generator import get_current_persona", exc, level=logging.ERROR)
        return random.randrange(option_count)
    if isinstance(probabilities, list) and probabilities:
        return weighted_index(probabilities)
    return random.randrange(option_count)


def _is_ungrouped(dimension: Optional[str]) -> bool:
    """判断维度是否为"未分组"（不应用一致性约束）。"""
    return dimension is None or dimension == DIMENSION_UNGROUPED


def _random_by_probabilities(option_count: int, probabilities: Union[List[float], int, None]) -> int:
    """纯随机选择（不带一致性约束），用于未分组的题目。"""
    if isinstance(probabilities, list) and len(probabilities) == option_count:
        return weighted_index(probabilities)
    return random.randrange(option_count)


def get_tendency_index(
    option_count: int,
    probabilities: Union[List[float], int, None],
    dimension: Optional[str] = None,
    is_reverse: bool = False,
) -> int:
    """获取带有一致性倾向的选项索引。

    按维度隔离基准偏好：同维度内的题目共享基准 ±1 波动，
    不同维度之间独立生成基准。未分组的题目走纯随机。

    Args:
        option_count: 该题的选项数量（比如5分量表就是5）
        probabilities: 概率配置列表，或 -1 表示随机
        dimension: 题目所属维度，None 或 DIMENSION_UNGROUPED 表示未分组
        is_reverse: 是否为反向题，True 时翻转基准偏好

    Returns:
        选中的选项索引（0-based）
    """
    if option_count <= 0:
        return 0

    # 未分组 → 纯随机/纯概率，不做一致性约束
    if _is_ungrouped(dimension):
        return _random_by_probabilities(option_count, probabilities)

    # 获取该维度的基准偏好
    assert dimension is not None  # 已通过 _is_ungrouped 过滤，此处 dimension 必为 str
    bases: Dict[str, int] = getattr(_thread_local, 'dimension_bases', {})
    if not isinstance(bases, dict):
        bases = {}
        _thread_local.dimension_bases = bases

    base = bases.get(dimension)

    if base is None:
        # 该维度首次遇到：生成基准偏好并存入
        base = _generate_base_index(option_count, probabilities)
        if is_reverse:
            base = (option_count - 1) - base
        bases[dimension] = base
        return base

    # 后续调用：反向题翻转基准后再应用一致性约束
    effective_base = base
    if is_reverse:
        effective_base = (option_count - 1) - min(base, option_count - 1)
    return _apply_consistency(effective_base, option_count, probabilities)


def _apply_consistency(
    base: int,
    option_count: int,
    probabilities: Union[List[float], int, None],
) -> int:
    """在基准 ±1 范围内应用一致性约束选择选项。"""
    # 当前题目选项数可能与生成 base 时不同，需要夹到合法范围
    effective_base = min(base, option_count - 1)

    # 在基准附近 ±1 波动
    low = max(0, effective_base - _FLUCTUATION)
    high = min(option_count - 1, effective_base + _FLUCTUATION)

    # 如果有显式概率配置，需要结合原概率和距离衰减
    if isinstance(probabilities, list) and len(probabilities) == option_count:
        adjusted_probs = []
        for i in range(option_count):
            if low <= i <= high:
                distance = abs(i - effective_base)
                decay = 2.0 if distance == 0 else (1.0 if distance == 1 else 0.1)
                adjusted_probs.append(probabilities[i] * decay)
            else:
                adjusted_probs.append(probabilities[i] * 0.05)

        total = sum(adjusted_probs)
        if total > 0:
            adjusted_probs = [p / total for p in adjusted_probs]
            return weighted_index(adjusted_probs)

    # 随机模式或无有效概率：在约束范围内均匀波动，但偏向基准
    candidates = list(range(low, high + 1))
    weights = []
    for c in candidates:
        if c == effective_base:
            weights.append(2.0)
        else:
            weights.append(1.0)

    total = sum(weights)
    pivot = random.random() * total
    running = 0.0
    for i, w in enumerate(weights):
        running += w
        if pivot <= running:
            return candidates[i]
    return candidates[-1]

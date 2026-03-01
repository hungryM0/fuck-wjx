"""答题倾向模块 - 保证同一份问卷内量表类题目的前后一致性

问题：原来每道量表题完全独立随机，可能出现前面给5分后面给1分的情况，
导致 Cronbach's Alpha 信效度极低，一看就是假数据。

方案：每次填写问卷时，按维度（dimension）独立生成"基准偏好"，
同维度内的量表题围绕该基准 ±1 波动，不同维度之间互不干扰。
未分组的题目走纯随机，不受一致性约束。

增强（画像融合）：当存在虚拟画像时，基准偏好由画像的 satisfaction_tendency
决定，而非完全随机。这样画像越"满意"的人物，量表题越倾向选高分。

潜变量模式：支持基于心理测量学的潜变量模型，可精确控制 Cronbach's Alpha。
"""
import random
import threading
from typing import Any, Dict, List, Optional, Union
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


def _generate_base_ratio(
    option_count: int,
    probabilities: Union[List[float], int, None],
    is_reverse: bool = False,
) -> float:
    """生成本份问卷的基准偏好比例（0.0~1.0），与具体选项数无关。

    base_ratio 语义始终是"真实满意度"：0.0=极不满意，1.0=极满意。
    对于反向题，用户配置的概率指向的是"反向选项索引"，必须翻转后才能
    还原为真实满意度，否则会把"极其不满"的人误记成"极其满意"，
    污染同维度后续所有正向题的作答。

    画像的 satisfaction_tendency 本身已是真实满意度，无需翻转。
    """
    if probabilities == -1 or probabilities is None:
        # 尝试从画像获取满意度倾向
        try:
            from wjx.core.persona.generator import get_current_persona
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
        # 反向题：索引越高代表越不满意，需翻转才能还原真实满意度
        if is_reverse:
            ratio = 1.0 - ratio
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


def get_tendency_index(
    option_count: int,
    probabilities: Union[List[float], int, None],
    dimension: Optional[str] = None,
    is_reverse: bool = False,
    # 新增：潜变量模式支持
    psycho_plan: Optional[Any] = None,
    question_index: Optional[int] = None,
    row_index: Optional[int] = None,
) -> int:
    """获取带有一致性倾向的选项索引。

    支持两种模式：
    1. 简单倾向模式（默认）：同维度内的题目共享基准 ±1 波动
    2. 潜变量模式：基于心理测量学模型，可精确控制 Cronbach's Alpha

    按维度隔离基准偏好：同维度内的题目共享基准 ±1 波动，
    不同维度之间独立生成基准。未分组的题目走纯随机。

    Args:
        option_count: 该题的选项数量（比如5分量表就是5）
        probabilities: 概率配置列表，或 -1 表示随机
        dimension: 题目所属维度，None 或 DIMENSION_UNGROUPED 表示未分组
        is_reverse: 是否为反向题，True 时翻转基准偏好
        psycho_plan: 潜变量计划（可选），如果提供则使用潜变量模式
        question_index: 题目索引（潜变量模式需要）
        row_index: 矩阵题行索引（可选，仅矩阵题需要）

    Returns:
        选中的选项索引（0-based）
    """
    if option_count <= 0:
        return 0

    # 优先使用潜变量模式（如果提供了计划）
    if psycho_plan is not None and question_index is not None:
        choice = _get_psychometric_answer(
            psycho_plan, question_index, row_index, option_count, is_reverse
        )
        if choice is not None:
            return choice
        # 如果潜变量模式失败，回退到简单模式
        logging.debug(
            "潜变量模式未找到答案（题%d 行%s），回退到简单模式",
            question_index, row_index
        )

    # 未分组 → 纯随机/纯概率，不做一致性约束，但仍需处理反向题
    if _is_ungrouped(dimension):
        result = _random_by_probabilities(option_count, probabilities)
        if is_reverse:
            return (option_count - 1) - result
        return result

    # 获取该维度的基准偏好
    assert dimension is not None  # 已通过 _is_ungrouped 过滤，此处 dimension 必为 str
    bases: Dict[str, float] = getattr(_thread_local, 'dimension_bases', {})
    if not isinstance(bases, dict):
        bases = {}
        _thread_local.dimension_bases = bases

    base_ratio = bases.get(dimension)

    if base_ratio is None:
        # 该维度首次遇到：生成归一化比例（0.0~1.0）并存入
        # 必须透传 is_reverse，否则反向题会把"极不满意"误记成"极满意"
        base_ratio = _generate_base_ratio(option_count, probabilities, is_reverse=is_reverse)
        bases[dimension] = base_ratio

    # 将归一化比例还原为当前题的绝对索引，避免不同量程题目语义错位
    base = int(round(base_ratio * (option_count - 1)))
    base = max(0, min(option_count - 1, base))

    # 反向题翻转基准后再应用一致性约束
    effective_base = base
    if is_reverse:
        effective_base = (option_count - 1) - base
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


def _get_psychometric_answer(
    plan: Any,
    question_index: int,
    row_index: Optional[int],
    option_count: int,
    is_reverse: bool,
) -> Optional[int]:
    """从潜变量计划中获取答案
    
    Args:
        plan: PsychometricPlan 对象
        question_index: 题目索引（0-based，配置列表中的索引）
        row_index: 矩阵题行索引（可选）
        option_count: 选项数量
        is_reverse: 是否为反向题
        
    Returns:
        选项索引（0-based），如果未找到则返回 None
    """
    try:
        choice = plan.get_choice(question_index, row_index)
        if choice is None:
            return None
        
        # 确保选项索引在有效范围内
        choice = max(0, min(option_count - 1, choice))
        
        # 反向题翻转
        if is_reverse:
            choice = (option_count - 1) - choice
        
        return choice
    except Exception as exc:
        log_suppressed_exception(
            f"_get_psychometric_answer: question_index={question_index}, row_index={row_index}",
            exc,
            level=logging.WARNING
        )
        return None


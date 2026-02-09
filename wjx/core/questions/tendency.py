"""答题倾向模块 - 保证同一份问卷内量表类题目的前后一致性

问题：原来每道量表题完全独立随机，可能出现前面给5分后面给1分的情况，
导致 Cronbach's Alpha 信效度极低，一看就是假数据。

方案：每次填写问卷时，先生成一个"基准偏好"（倾向于选高分/中分/低分），
之后所有量表类题目都围绕这个基准 ±1 波动，模拟真人的答题一致性。

增强（画像融合）：当存在虚拟画像时，基准偏好由画像的 satisfaction_tendency
决定，而非完全随机。这样画像越"满意"的人物，量表题越倾向选高分。
"""
import random
import threading
from typing import List, Optional, Union

from wjx.core.questions.utils import weighted_index

# 线程局部存储：每个浏览器线程有自己独立的答题倾向
_thread_local = threading.local()

# 波动范围（基准 ±1）
_FLUCTUATION = 1


def reset_tendency() -> None:
    """在每份问卷开始填写前调用，清除上一份的答题倾向。

    这样每份问卷会重新生成倾向，不同问卷之间仍然是随机的。
    """
    _thread_local.base_index = None


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
        except Exception:
            pass
        return random.randrange(option_count)
    if isinstance(probabilities, list) and probabilities:
        return weighted_index(probabilities)
    return random.randrange(option_count)


def get_tendency_index(option_count: int, probabilities: Union[List[float], int, None]) -> int:
    """获取带有一致性倾向的选项索引。

    当概率配置为 -1（随机模式）时：
        第一次调用会生成基准偏好，之后每次调用在基准附近 ±1 波动，
        保持同一份问卷内量表类答案的逻辑一致性。

    当概率配置为显式列表时：
        严格按用户设定的概率分布选择，不应用一致性波动。
        这样用户把某选项概率设为 0 时就绝不会被选中。

    Args:
        option_count: 该题的选项数量（比如5分量表就是5）
        probabilities: 概率配置列表，或 -1 表示随机

    Returns:
        选中的选项索引（0-based）
    """
    if option_count <= 0:
        return 0

    # 显式概率配置：严格按用户设定的权重选择，不做一致性波动
    if isinstance(probabilities, list) and probabilities:
        return weighted_index(probabilities)

    # 随机模式（-1 或 None）：使用一致性倾向机制
    base = getattr(_thread_local, 'base_index', None)

    if base is None:
        # 首次调用：完全随机生成基准偏好
        base = random.randrange(option_count)
        _thread_local.base_index = base

    # 当前题目选项数可能与生成 base 时不同，需要夹到合法范围
    effective_base = min(base, option_count - 1)

    # 在基准附近 ±1 波动
    low = max(0, effective_base - _FLUCTUATION)
    high = min(option_count - 1, effective_base + _FLUCTUATION)

    # 在 [low, high] 范围内随机选一个，但偏向基准值
    candidates = list(range(low, high + 1))
    # 给基准值更高的权重（2倍），让结果更集中
    weights = []
    for c in candidates:
        if c == effective_base:
            weights.append(2.0)
        else:
            weights.append(1.0)

    # 加权随机选择
    total = sum(weights)
    pivot = random.random() * total
    running = 0.0
    for i, w in enumerate(weights):
        running += w
        if pivot <= running:
            return candidates[i]
    return candidates[-1]

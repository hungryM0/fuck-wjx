"""
信效度生成核心逻辑 - 从 demo/wjx/core/statistics/psychometric.py 移植

用于生成符合 Cronbach's Alpha 信度要求的问卷答案。
核心思想：所有题目共享一个潜变量 theta，通过添加误差来生成各题答案，
误差大小由目标 Alpha 值决定。
"""
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from wjx.core.stats.utils import randn, z_to_category

logger = logging.getLogger(__name__)


def compute_rho_from_alpha(alpha: float, k: int) -> float:
    """
    根据目标 Cronbach's Alpha 计算题目间的平均相关系数
    
    基于 Spearman-Brown 公式的逆运算：
    alpha = k * rho / (1 + (k-1) * rho)
    解出 rho = alpha / (k - alpha * (k - 1))
    
    Args:
        alpha: 目标 Cronbach's Alpha 值 (0, 1)
        k: 题目数量
        
    Returns:
        题目间的平均相关系数 rho
    """
    if not (0 < alpha < 1):
        return 0.2
    if k < 2:
        return 0.2
    
    denom = k - alpha * (k - 1)
    if denom <= 0:
        return 0.2
    
    rho = alpha / denom
    return max(1e-6, min(0.999999, rho))


def compute_sigma_e_from_alpha(alpha: float, k: int) -> float:
    """
    根据目标 Cronbach's Alpha 计算误差标准差
    
    在潜变量模型中：X_i = theta + e_i
    其中 theta ~ N(0,1), e_i ~ N(0, sigma_e^2)
    题目间相关系数 rho = 1 / (1 + sigma_e^2)
    因此 sigma_e = sqrt(1/rho - 1)
    
    Args:
        alpha: 目标 Cronbach's Alpha 值
        k: 题目数量
        
    Returns:
        误差标准差 sigma_e
    """
    import math
    rho = compute_rho_from_alpha(alpha, k)
    return math.sqrt((1 / rho) - 1)


def generate_psycho_answer(
    theta: float,
    option_count: int,
    bias: str = "center",
    sigma_e: float = 0.5,
) -> int:
    """
    从潜变量生成单个题目的答案
    
    Args:
        theta: 潜变量（代表被试的真实水平）
        option_count: 选项数量
        bias: 偏向设置
            - "left": 偏向低分（选项1方向）
            - "center": 中立（默认）
            - "right": 偏向高分（选项N方向）
        sigma_e: 误差标准差
        
    Returns:
        选项索引（0-based）
    """
    # 偏向处理：使用 ±0.5 标准差的偏移
    # 这样可以产生明显的偏向效果，但不会导致极端的分布集中
    # 对于标准正态分布，±0.5 约等于 19% 的分位点偏移
    bias_shift = -0.5 if bias == "left" else 0.5 if bias == "right" else 0.0
    
    # 生成带误差的观测值
    z = theta + bias_shift + sigma_e * randn()
    
    # 转换为离散选项
    return z_to_category(z, option_count)


@dataclass
class PsychometricItem:
    """信效度题目项"""
    kind: str  # "single", "scale", "dropdown", "matrix_row"
    question_index: int  # 题目在列表中的索引
    row_index: Optional[int] = None  # 矩阵题的行索引
    option_count: int = 5  # 选项数量
    bias: str = "center"  # 偏向


@dataclass
class PsychometricPlan:
    """信效度生成计划"""
    items: List[PsychometricItem]  # 参与信效度的题目列表
    theta: float  # 当前样本的潜变量
    sigma_e: float  # 误差标准差
    choices: Dict[str, int]  # 预生成的答案 {key: choice_index}
    
    def get_choice(self, question_index: int, row_index: Optional[int] = None) -> Optional[int]:
        """获取指定题目的预生成答案"""
        if row_index is not None:
            key = f"matrix:{question_index}:{row_index}"
        else:
            key = f"q:{question_index}"
        return self.choices.get(key)


def build_psychometric_plan(
    psycho_items: List[Tuple[int, str, int, str, Optional[int]]],
    target_alpha: float = 0.85,
) -> Optional[PsychometricPlan]:
    """
    构建信效度生成计划
    
    Args:
        psycho_items: 启用信效度的题目列表，每项为:
            (question_index, question_type, option_count, bias, row_index)
            - question_index: 题目索引（从配置列表中的索引，0-based）
            - question_type: 题型 ("single", "scale", "dropdown", "matrix")
            - option_count: 选项数量
            - bias: 偏向 ("left", "center", "right")
            - row_index: 矩阵题的行索引（非矩阵题为 None）
        target_alpha: 目标 Cronbach's Alpha 值
        
    Returns:
        PsychometricPlan 或 None（如果题目数不足）
    """
    if not psycho_items:
        return None
    
    # 构建题目项列表
    items: List[PsychometricItem] = []
    
    for q_idx, q_type, opt_count, bias, row_idx in psycho_items:
        if q_type == "matrix" and row_idx is not None:
            items.append(PsychometricItem(
                kind="matrix_row",
                question_index=q_idx,
                row_index=row_idx,
                option_count=opt_count,
                bias=bias,
            ))
        else:
            items.append(PsychometricItem(
                kind=q_type,
                question_index=q_idx,
                option_count=opt_count,
                bias=bias,
            ))
    
    k = len(items)
    if k < 2:
        logger.warning("潜变量模式需要至少2道题目，当前只有 %d 道", k)
        return None
    
    # 计算误差标准差
    sigma_e = compute_sigma_e_from_alpha(target_alpha, k)
    
    # 生成潜变量
    theta = randn()
    
    # 为每个题目生成答案
    choices: Dict[str, int] = {}
    
    for item in items:
        choice = generate_psycho_answer(
            theta=theta,
            option_count=item.option_count,
            bias=item.bias,
            sigma_e=sigma_e,
        )
        
        if item.row_index is not None:
            key = f"matrix:{item.question_index}:{item.row_index}"
        else:
            key = f"q:{item.question_index}"
        
        choices[key] = choice
    
    logger.debug(
        "潜变量模式已启用 | 目标α=%.2f 题数=%d θ=%.2f σ_e=%.2f",
        target_alpha, k, theta, sigma_e
    )
    
    return PsychometricPlan(
        items=items,
        theta=theta,
        sigma_e=sigma_e,
        choices=choices,
    )

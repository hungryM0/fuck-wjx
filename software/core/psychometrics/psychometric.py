"""
信效度生成核心逻辑
"""
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from software.core.psychometrics.utils import randn, z_to_category

logger = logging.getLogger(__name__)


def _build_choice_key(question_index: int, row_index: Optional[int] = None) -> str:
    if row_index is not None:
        return f"matrix:{question_index}:{row_index}"
    return f"q:{question_index}"


def compute_rho_from_alpha(alpha: float, k: int) -> float:
    """根据目标 Cronbach's Alpha 计算题目间的平均相关系数"""
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
    """根据目标 Cronbach's Alpha 计算误差标准差"""
    import math
    rho = compute_rho_from_alpha(alpha, k)
    return math.sqrt((1 / rho) - 1)


def generate_psycho_answer(
    theta: float,
    option_count: int,
    bias: str = "center",
    sigma_e: float = 0.5,
) -> int:
    """从潜变量生成单个题目的答案"""
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
        key = _build_choice_key(question_index, row_index)
        return self.choices.get(key)


@dataclass
class DimensionPsychometricPlan:
    """按维度拆分的心理测量计划。"""

    plans: Dict[str, PsychometricPlan]
    item_dimension_map: Dict[str, str]
    skipped_dimensions: Dict[str, int]
    items: List[PsychometricItem]

    def get_choice(self, question_index: int, row_index: Optional[int] = None) -> Optional[int]:
        key = _build_choice_key(question_index, row_index)
        dimension = self.item_dimension_map.get(key)
        if not dimension:
            return None
        plan = self.plans.get(dimension)
        if plan is None:
            return None
        return plan.get_choice(question_index, row_index)


def build_psychometric_plan(
    psycho_items: List[Tuple[int, str, int, str, Optional[int]]],
    target_alpha: float = 0.9,
) -> Optional[PsychometricPlan]:
    """构建信效度生成计划"""
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
        logger.warning("心理测量计划需要至少2道题目，当前只有 %d 道", k)
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
        
        choices[_build_choice_key(item.question_index, item.row_index)] = choice
    
    logger.info(
        "心理测量计划已启用 | 目标α=%.2f 题数=%d θ=%.2f σ_e=%.2f",
        target_alpha, k, theta, sigma_e
    )
    
    return PsychometricPlan(
        items=items,
        theta=theta,
        sigma_e=sigma_e,
        choices=choices,
    )


def build_dimension_psychometric_plan(
    grouped_items: Dict[str, List[Tuple[int, str, int, str, Optional[int]]]],
    target_alpha: float = 0.9,
) -> Optional[DimensionPsychometricPlan]:
    """按维度分别构建心理测量计划。"""
    if not grouped_items:
        return None

    plans: Dict[str, PsychometricPlan] = {}
    item_dimension_map: Dict[str, str] = {}
    skipped_dimensions: Dict[str, int] = {}
    merged_items: List[PsychometricItem] = []

    for dimension, items in grouped_items.items():
        normalized_dimension = str(dimension or "").strip()
        if not normalized_dimension:
            continue
        item_count = len(items or [])
        if item_count < 2:
            skipped_dimensions[normalized_dimension] = item_count
            logger.info("维度[%s]题目数不足 2，道数=%d，已回退常规逻辑", normalized_dimension, item_count)
            continue

        plan = build_psychometric_plan(items, target_alpha=target_alpha)
        if plan is None:
            skipped_dimensions[normalized_dimension] = item_count
            continue

        plans[normalized_dimension] = plan
        merged_items.extend(plan.items)
        for item in plan.items:
            item_dimension_map[_build_choice_key(item.question_index, item.row_index)] = normalized_dimension
        logger.info("维度[%s]已启用心理测量计划，道数=%d", normalized_dimension, len(plan.items))

    if not plans:
        return None

    return DimensionPsychometricPlan(
        plans=plans,
        item_dimension_map=item_dimension_map,
        skipped_dimensions=skipped_dimensions,
        items=merged_items,
    )



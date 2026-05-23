"""
信效度生成核心逻辑
"""
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from software.core.psychometrics.orientation import build_bias_target_probabilities, infer_dimension_orientation
from software.core.psychometrics.utils import randn, z_to_category

logger = logging.getLogger(__name__)

DEFAULT_TARGET_ALPHA = 0.85
MIN_TARGET_ALPHA = 0.60
MAX_TARGET_ALPHA = 0.95


def _build_choice_key(question_index: int, row_index: Optional[int] = None) -> str:
    if row_index is not None:
        return f"q:{question_index}:row:{row_index}"
    return f"q:{question_index}"


def normalize_target_alpha(value: Any, default: float = DEFAULT_TARGET_ALPHA) -> float:
    """规范化目标 Alpha，统一处理默认值、NaN 和上下限。"""
    try:
        fallback = float(default)
    except Exception:
        fallback = DEFAULT_TARGET_ALPHA

    try:
        alpha = float(value)
    except Exception:
        alpha = fallback

    if alpha != alpha:
        alpha = fallback
    return max(MIN_TARGET_ALPHA, min(MAX_TARGET_ALPHA, alpha))


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
    is_reversed: bool = False,
) -> int:
    """从潜变量生成单个题目的答案。

    is_reversed=True 时先取反 theta，再叠加 bias 对应的左右偏移。
    """
    bias_shift = -0.5 if bias == "left" else 0.5 if bias == "right" else 0.0
    effective_theta = -theta if is_reversed else theta
    z = effective_theta + bias_shift + sigma_e * randn()
    return z_to_category(z, option_count)


@dataclass
class PsychometricItem:
    """信效度题目项"""
    kind: str  # "single", "scale", "dropdown", "matrix_row"
    question_index: int  # 题目在列表中的索引
    row_index: Optional[int] = None  # 矩阵题的行索引
    option_count: int = 5  # 选项数量
    bias: str = "center"  # 偏向
    target_probabilities: Optional[List[float]] = None  # 最终目标配比（无则按预设补）
    score_by_choice_index: Optional[List[int]] = None

    @property
    def choice_key(self) -> str:
        return _build_choice_key(self.question_index, self.row_index)

    def choice_index_for_score(self, score_index: int) -> int:
        if not isinstance(self.score_by_choice_index, list) or not self.score_by_choice_index:
            return max(0, min(self.option_count - 1, int(score_index or 0)))
        try:
            target_score = int(score_index or 0)
        except Exception:
            target_score = 0
        for choice_index, mapped_score in enumerate(self.score_by_choice_index):
            try:
                if int(mapped_score) == target_score:
                    return max(0, min(self.option_count - 1, choice_index))
            except Exception:
                continue
        return max(0, min(self.option_count - 1, target_score))

    def score_for_choice_index(self, choice_index: int) -> int:
        if not isinstance(self.score_by_choice_index, list) or not self.score_by_choice_index:
            return max(0, min(self.option_count - 1, int(choice_index or 0)))
        try:
            index = int(choice_index or 0)
        except Exception:
            index = 0
        if 0 <= index < len(self.score_by_choice_index):
            try:
                return max(0, min(self.option_count - 1, int(self.score_by_choice_index[index])))
            except Exception:
                return max(0, min(self.option_count - 1, index))
        return max(0, min(self.option_count - 1, index))


def _coerce_psychometric_item(raw_item: Any) -> Optional[PsychometricItem]:
    if isinstance(raw_item, PsychometricItem):
        probabilities = raw_item.target_probabilities
        if not isinstance(probabilities, list) or not probabilities:
            probabilities = build_bias_target_probabilities(raw_item.option_count, raw_item.bias)
        return PsychometricItem(
            kind=raw_item.kind,
            question_index=raw_item.question_index,
            row_index=raw_item.row_index,
            option_count=raw_item.option_count,
            bias=raw_item.bias,
            target_probabilities=list(probabilities),
            score_by_choice_index=list(raw_item.score_by_choice_index or []) or None,
        )

    if isinstance(raw_item, (tuple, list)) and len(raw_item) >= 5:
        q_idx, q_type, opt_count, bias, row_idx = raw_item[:5]
        probabilities = raw_item[5] if len(raw_item) >= 6 else None
        if not isinstance(probabilities, list) or not probabilities:
            probabilities = build_bias_target_probabilities(int(opt_count or 5), str(bias or "center"))
        kind = "matrix_row" if q_type == "matrix" and row_idx is not None else q_type
        return PsychometricItem(
            kind=str(kind or "scale"),
            question_index=int(q_idx or 0),
            row_index=row_idx if row_idx is None else int(row_idx),
            option_count=max(2, int(opt_count or 5)),
            bias=str(bias or "center"),
            target_probabilities=list(probabilities),
            score_by_choice_index=None,
        )

    to_runtime_item = getattr(raw_item, "to_runtime_item", None)
    if callable(to_runtime_item):
        runtime_item = to_runtime_item()
        return _coerce_psychometric_item(runtime_item)

    question_index = getattr(raw_item, "question_index", None)
    if question_index is None:
        return None
    row_index = getattr(raw_item, "row_index", None)
    kind = getattr(raw_item, "kind", getattr(raw_item, "question_type", "scale"))
    if kind == "matrix" and row_index is not None:
        kind = "matrix_row"
    option_count = max(2, int(getattr(raw_item, "option_count", 5) or 5))
    bias = str(getattr(raw_item, "bias", "center") or "center")
    probabilities = getattr(raw_item, "target_probabilities", None)
    if not isinstance(probabilities, list) or not probabilities:
        probabilities = build_bias_target_probabilities(option_count, bias)
    return PsychometricItem(
        kind=str(kind or "scale"),
        question_index=int(question_index or 0),
        row_index=row_index if row_index is None else int(row_index),
        option_count=option_count,
        bias=bias,
        target_probabilities=list(probabilities),
        score_by_choice_index=list(getattr(raw_item, "score_by_choice_index", None) or []) or None,
    )


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

    def is_distribution_locked(self, question_index: int, row_index: Optional[int] = None) -> bool:
        _ = question_index, row_index
        return False


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

    def is_distribution_locked(self, question_index: int, row_index: Optional[int] = None) -> bool:
        _ = question_index, row_index
        return False


def build_psychometric_plan(
    psycho_items: List[Any],
    target_alpha: float = 0.85,
) -> Optional[PsychometricPlan]:
    """构建信效度生成计划"""
    if not psycho_items:
        return None
    
    # 构建题目项列表
    items: List[PsychometricItem] = []
    
    for raw_item in psycho_items:
        item = _coerce_psychometric_item(raw_item)
        if item is not None:
            items.append(item)

    k = len(items)
    if k < 2:
        logger.warning("心理测量计划需要至少2道题目，当前只有 %d 道", k)
        return None
    
    target_alpha = normalize_target_alpha(target_alpha)

    # 计算误差标准差
    sigma_e = compute_sigma_e_from_alpha(target_alpha, k)
    
    # 生成潜变量
    theta = randn()
    
    # 为每个题目生成答案
    choices: Dict[str, int] = {}
    dimension_orientation = infer_dimension_orientation(items)
    reversed_keys = set(dimension_orientation.reversed_keys)

    for item in items:
        item_orientation = dimension_orientation.item_orientations.get(item.choice_key)
        effective_bias = item_orientation.direction if item_orientation is not None else item.bias
        score_index = generate_psycho_answer(
            theta=theta,
            option_count=item.option_count,
            bias=effective_bias,
            sigma_e=sigma_e,
            is_reversed=item.choice_key in reversed_keys,
        )

        choices[_build_choice_key(item.question_index, item.row_index)] = item.choice_index_for_score(score_index)

    logger.info(
        "心理测量计划已启用 | 目标α=%.2f 题数=%d θ=%.2f σ_e=%.2f 主方向=%s 反向题=%d",
        target_alpha,
        k,
        theta,
        sigma_e,
        getattr(dimension_orientation, "anchor_direction", "center"),
        len(reversed_keys),
    )
    
    return PsychometricPlan(
        items=items,
        theta=theta,
        sigma_e=sigma_e,
        choices=choices,
    )


def build_dimension_psychometric_plan(
    grouped_items: Dict[str, List[Any]],
    target_alpha: float = 0.85,
) -> Optional[DimensionPsychometricPlan]:
    """按维度分别构建心理测量计划。"""
    if not grouped_items:
        return None

    target_alpha = normalize_target_alpha(target_alpha)

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



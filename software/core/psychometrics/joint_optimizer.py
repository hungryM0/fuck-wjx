"""信效度题型的整批联合比例优化。"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from software.core.psychometrics.psychometric import PsychometricItem, compute_sigma_e_from_alpha
from software.core.psychometrics.utils import cronbach_alpha, randn
from software.core.questions.utils import normalize_droplist_probs

if TYPE_CHECKING:
    from software.core.task import ExecutionConfig

logger = logging.getLogger(__name__)

JOINT_PSYCHOMETRIC_SUPPORTED_TYPES = frozenset({"scale", "score", "dropdown", "matrix"})
_PSYCHO_BIAS_CHOICES = {"left", "center", "right"}
_MICRO_JITTER_SIGMA = 0.03


def build_psychometric_choice_key(question_index: int, row_index: Optional[int] = None) -> str:
    if row_index is None:
        return f"q:{int(question_index)}"
    return f"q:{int(question_index)}:row:{int(row_index)}"


def _resolve_option_count(probability_config: Any, metadata_fallback: int, default_value: int = 5) -> int:
    if isinstance(probability_config, list) and probability_config:
        return max(2, len(probability_config))
    if metadata_fallback > 0:
        return max(2, int(metadata_fallback))
    return max(2, int(default_value))


def _infer_bias_from_probabilities(probability_config: Any, option_count: int) -> str:
    if not isinstance(probability_config, list) or not probability_config:
        return "center"

    weights: List[float] = []
    for raw in probability_config:
        try:
            weights.append(max(0.0, float(raw)))
        except Exception:
            weights.append(0.0)

    total = sum(weights)
    if total <= 0:
        return "center"

    denom = max(1, option_count - 1)
    weighted_mean = sum(idx * weight for idx, weight in enumerate(weights)) / total
    ratio = weighted_mean / denom
    if ratio <= 0.4:
        return "left"
    if ratio >= 0.6:
        return "right"
    return "center"


def _resolve_bias(raw_bias: Any, probability_config: Any, option_count: int) -> str:
    if isinstance(raw_bias, str):
        normalized = raw_bias.strip().lower()
        if normalized in _PSYCHO_BIAS_CHOICES:
            return normalized
    return _infer_bias_from_probabilities(probability_config, option_count)


def _normalize_probability_list(values: List[float]) -> List[float]:
    cleaned: List[float] = []
    for raw in values:
        try:
            value = max(0.0, float(raw))
        except Exception:
            value = 0.0
        if math.isnan(value) or math.isinf(value):
            value = 0.0
        cleaned.append(value)
    total = sum(cleaned)
    if total <= 0.0:
        if not cleaned:
            return []
        return [1.0 / len(cleaned)] * len(cleaned)
    return [item / total for item in cleaned]


def _build_bias_probabilities(option_count: int, bias: str) -> List[float]:
    count = max(2, int(option_count or 2))
    if count == 2:
        if bias == "left":
            return [0.75, 0.25]
        if bias == "right":
            return [0.25, 0.75]
        return [0.5, 0.5]

    if bias == "left":
        linear = [1.0 - i / (count - 1) for i in range(count)]
    elif bias == "right":
        linear = [i / (count - 1) for i in range(count)]
    else:
        center = (count - 1) / 2.0
        linear = [1.0 - abs(i - center) / max(center, 1.0) for i in range(count)]

    power = 3 if bias == "center" else 8
    raw = [math.pow(max(value, 0.0), power) for value in linear]
    return _normalize_probability_list(raw)


def _resolve_target_probabilities(
    probability_config: Any,
    option_count: int,
    bias: str,
) -> List[float]:
    if probability_config == -1 or probability_config is None:
        if bias in _PSYCHO_BIAS_CHOICES:
            return _build_bias_probabilities(option_count, bias)
        return [1.0 / max(1, option_count)] * max(1, option_count)
    return normalize_droplist_probs(probability_config, option_count)


@dataclass(frozen=True)
class PsychometricBlueprintItem:
    question_index: int
    question_type: str
    option_count: int
    bias: str
    target_probabilities: List[float]
    row_index: Optional[int] = None

    @property
    def choice_key(self) -> str:
        return build_psychometric_choice_key(self.question_index, self.row_index)

    def to_runtime_item(self) -> PsychometricItem:
        if self.question_type == "matrix" and self.row_index is not None:
            return PsychometricItem(
                kind="matrix_row",
                question_index=self.question_index,
                row_index=self.row_index,
                option_count=self.option_count,
                bias=self.bias,
            )
        return PsychometricItem(
            kind=self.question_type,
            question_index=self.question_index,
            option_count=self.option_count,
            bias=self.bias,
        )


@dataclass(frozen=True)
class JointPsychometricDimensionDiagnostic:
    dimension: str
    item_count: int
    sample_count: int
    target_alpha: float
    actual_alpha: float
    degraded_for_ratio: bool
    skipped: bool = False
    reason: str = ""


@dataclass
class JointPsychometricSamplePlan:
    sample_index: int
    choices: Dict[str, int]
    diagnostics_by_dimension: Dict[str, JointPsychometricDimensionDiagnostic]
    items: List[PsychometricItem] = field(default_factory=list)

    def get_choice(self, question_index: int, row_index: Optional[int] = None) -> Optional[int]:
        return self.choices.get(build_psychometric_choice_key(question_index, row_index))

    def is_distribution_locked(self, question_index: int, row_index: Optional[int] = None) -> bool:
        return build_psychometric_choice_key(question_index, row_index) in self.choices


@dataclass
class JointPsychometricAnswerPlan:
    answers_by_sample: Dict[int, Dict[str, int]]
    diagnostics_by_dimension: Dict[str, JointPsychometricDimensionDiagnostic]
    item_dimension_map: Dict[str, str]
    items: List[PsychometricItem]
    sample_count: int

    def get_choice(
        self,
        sample_index: int,
        question_index: int,
        row_index: Optional[int] = None,
    ) -> Optional[int]:
        bucket = self.answers_by_sample.get(int(sample_index))
        if not isinstance(bucket, dict):
            return None
        return bucket.get(build_psychometric_choice_key(question_index, row_index))

    def build_sample_plan(self, sample_index: int) -> Optional[JointPsychometricSamplePlan]:
        key = int(sample_index)
        if key < 0 or key >= self.sample_count:
            return None
        choices = dict(self.answers_by_sample.get(key) or {})
        return JointPsychometricSamplePlan(
            sample_index=key,
            choices=choices,
            diagnostics_by_dimension=dict(self.diagnostics_by_dimension),
            items=list(self.items),
        )


@dataclass
class CombinedPsychometricPlan:
    primary: Optional[Any] = None
    fallback: Optional[Any] = None

    def get_choice(self, question_index: int, row_index: Optional[int] = None) -> Optional[int]:
        if self.primary is not None and hasattr(self.primary, "get_choice"):
            try:
                choice = self.primary.get_choice(question_index, row_index)
            except Exception:
                choice = None
            if choice is not None:
                return choice
        if self.fallback is not None and hasattr(self.fallback, "get_choice"):
            try:
                return self.fallback.get_choice(question_index, row_index)
            except Exception:
                return None
        return None

    def is_distribution_locked(self, question_index: int, row_index: Optional[int] = None) -> bool:
        if self.primary is not None and hasattr(self.primary, "is_distribution_locked"):
            try:
                return bool(self.primary.is_distribution_locked(question_index, row_index))
            except Exception:
                return False
        return False


def build_psychometric_blueprint(config: "ExecutionConfig") -> Dict[str, List[PsychometricBlueprintItem]]:
    grouped_items: Dict[str, List[PsychometricBlueprintItem]] = {}

    for question_num in sorted(config.question_config_index_map.keys()):
        config_entry = config.question_config_index_map.get(question_num)
        if not config_entry:
            continue

        question_type, start_index = config_entry
        if question_type not in JOINT_PSYCHOMETRIC_SUPPORTED_TYPES:
            continue

        dimension = str(config.question_dimension_map.get(question_num) or "").strip()
        if not dimension:
            continue

        question_meta = config.questions_metadata.get(question_num) or {}
        meta_option_count = int(question_meta.get("options") or 0)
        saved_bias = config.question_psycho_bias_map.get(question_num, "custom")

        if question_type in {"scale", "score"}:
            probability_config = config.scale_prob[start_index] if start_index < len(config.scale_prob) else -1
            option_count = _resolve_option_count(probability_config, meta_option_count, default_value=5)
            bias = _resolve_bias(saved_bias, probability_config, option_count)
            grouped_items.setdefault(dimension, []).append(
                PsychometricBlueprintItem(
                    question_index=question_num,
                    question_type=question_type,
                    option_count=option_count,
                    bias=bias,
                    target_probabilities=_resolve_target_probabilities(probability_config, option_count, bias),
                )
            )
            continue

        if question_type == "dropdown":
            probability_config = config.droplist_prob[start_index] if start_index < len(config.droplist_prob) else -1
            option_count = _resolve_option_count(
                probability_config,
                meta_option_count,
                default_value=max(meta_option_count, 2),
            )
            bias = _resolve_bias(saved_bias, probability_config, option_count)
            grouped_items.setdefault(dimension, []).append(
                PsychometricBlueprintItem(
                    question_index=question_num,
                    question_type=question_type,
                    option_count=option_count,
                    bias=bias,
                    target_probabilities=_resolve_target_probabilities(probability_config, option_count, bias),
                )
            )
            continue

        if question_type == "matrix":
            row_count = int(question_meta.get("rows") or 0)
            if row_count <= 0:
                row_count = 1

            for row_index in range(row_count):
                matrix_prob_index = start_index + row_index
                probability_config = config.matrix_prob[matrix_prob_index] if matrix_prob_index < len(config.matrix_prob) else -1
                option_count = _resolve_option_count(
                    probability_config,
                    meta_option_count,
                    default_value=max(meta_option_count, 5),
                )
                row_bias = saved_bias[row_index] if isinstance(saved_bias, list) and row_index < len(saved_bias) else saved_bias
                bias = _resolve_bias(row_bias, probability_config, option_count)
                grouped_items.setdefault(dimension, []).append(
                    PsychometricBlueprintItem(
                        question_index=question_num,
                        question_type="matrix",
                        option_count=option_count,
                        bias=bias,
                        target_probabilities=_resolve_target_probabilities(probability_config, option_count, bias),
                        row_index=row_index,
                    )
                )

    return grouped_items


def _build_integer_quotas(target_probabilities: List[float], sample_count: int) -> List[int]:
    if sample_count <= 0:
        return [0] * len(target_probabilities)

    normalized = _normalize_probability_list(target_probabilities)
    raw_targets = [value * sample_count for value in normalized]
    quotas = [int(math.floor(value)) for value in raw_targets]
    remainders = [raw_targets[idx] - quotas[idx] for idx in range(len(raw_targets))]
    remaining = sample_count - sum(quotas)
    if remaining > 0:
        ranked = sorted(
            range(len(normalized)),
            key=lambda idx: (remainders[idx], normalized[idx], -idx),
            reverse=True,
        )
        for idx in ranked[:remaining]:
            quotas[idx] += 1
    elif remaining < 0:
        ranked = sorted(
            range(len(normalized)),
            key=lambda idx: (remainders[idx], normalized[idx], -idx),
        )
        for idx in ranked[:abs(remaining)]:
            quotas[idx] = max(0, quotas[idx] - 1)
    return quotas


def _assign_choices_from_scores(scores: List[float], quotas: List[int]) -> List[int]:
    sample_count = len(scores)
    ordered_choices: List[int] = []
    for option_index, quota in enumerate(quotas):
        ordered_choices.extend([option_index] * max(0, int(quota or 0)))
    if len(ordered_choices) < sample_count:
        ordered_choices.extend([max(0, len(quotas) - 1)] * (sample_count - len(ordered_choices)))
    elif len(ordered_choices) > sample_count:
        ordered_choices = ordered_choices[:sample_count]

    ranked_samples = sorted(range(sample_count), key=lambda index: scores[index])
    assigned = [0] * sample_count
    for order_index, sample_index in enumerate(ranked_samples):
        assigned[sample_index] = ordered_choices[order_index]
    return assigned


def _build_sigma_candidates(target_alpha: float, item_count: int) -> List[float]:
    base_sigma = max(0.0, float(compute_sigma_e_from_alpha(target_alpha, item_count)))
    candidates = [
        base_sigma,
        base_sigma * 0.8,
        base_sigma * 0.6,
        base_sigma * 0.4,
        base_sigma * 0.2,
        0.1,
        0.05,
    ]
    normalized: List[float] = []
    seen: set[float] = set()
    for raw in candidates:
        sigma = round(max(0.0, float(raw)), 6)
        if sigma in seen:
            continue
        seen.add(sigma)
        normalized.append(sigma)
    return normalized


def _evaluate_dimension_plan(
    items: List[PsychometricBlueprintItem],
    sample_count: int,
    sigma_e: float,
) -> tuple[float, Dict[str, List[int]]]:
    theta = [randn() for _ in range(sample_count)]
    choices_by_item: Dict[str, List[int]] = {}
    response_rows = [[0.0] * len(items) for _ in range(sample_count)]

    for item_index, item in enumerate(items):
        quotas = _build_integer_quotas(item.target_probabilities, sample_count)
        scores = [
            theta[sample_index] + (sigma_e * randn()) + (_MICRO_JITTER_SIGMA * randn())
            for sample_index in range(sample_count)
        ]
        assigned = _assign_choices_from_scores(scores, quotas)
        choices_by_item[item.choice_key] = assigned
        for sample_index, choice in enumerate(assigned):
            response_rows[sample_index][item_index] = float(choice + 1)

    return cronbach_alpha(response_rows), choices_by_item


def build_joint_psychometric_answer_plan(config: "ExecutionConfig") -> Optional[JointPsychometricAnswerPlan]:
    sample_count = max(0, int(getattr(config, "target_num", 0) or 0))
    if sample_count <= 0:
        return None

    grouped_items = build_psychometric_blueprint(config)
    if not grouped_items:
        return None

    try:
        target_alpha = float(getattr(config, "psycho_target_alpha", 0.9) or 0.9)
    except Exception:
        target_alpha = 0.9
    target_alpha = max(0.70, min(0.95, target_alpha))

    answers_by_sample: Dict[int, Dict[str, int]] = {sample_index: {} for sample_index in range(sample_count)}
    diagnostics_by_dimension: Dict[str, JointPsychometricDimensionDiagnostic] = {}
    item_dimension_map: Dict[str, str] = {}
    runtime_items: List[PsychometricItem] = []
    has_locked_items = False

    for dimension, items in grouped_items.items():
        normalized_dimension = str(dimension or "").strip()
        if not normalized_dimension:
            continue
        item_count = len(items or [])
        if item_count < 2:
            diagnostics_by_dimension[normalized_dimension] = JointPsychometricDimensionDiagnostic(
                dimension=normalized_dimension,
                item_count=item_count,
                sample_count=sample_count,
                target_alpha=target_alpha,
                actual_alpha=0.0,
                degraded_for_ratio=False,
                skipped=True,
                reason="维度题数不足 2，已回退常规信效度逻辑",
            )
            logger.info("维度[%s]题数不足 2，联合优化已跳过", normalized_dimension)
            continue

        best_alpha = -1.0
        best_choices_by_item: Dict[str, List[int]] = {}
        for sigma_e in _build_sigma_candidates(target_alpha, item_count):
            current_alpha, current_choices = _evaluate_dimension_plan(items, sample_count, sigma_e)
            if current_alpha > best_alpha:
                best_alpha = current_alpha
                best_choices_by_item = current_choices

        actual_alpha = max(0.0, float(best_alpha))
        degraded_for_ratio = actual_alpha + 1e-6 < target_alpha
        diagnostics_by_dimension[normalized_dimension] = JointPsychometricDimensionDiagnostic(
            dimension=normalized_dimension,
            item_count=item_count,
            sample_count=sample_count,
            target_alpha=target_alpha,
            actual_alpha=actual_alpha,
            degraded_for_ratio=degraded_for_ratio,
        )
        if degraded_for_ratio:
            logger.warning(
                "维度[%s]已保比例优先，实际α=%.3f 低于目标α=%.3f",
                normalized_dimension,
                actual_alpha,
                target_alpha,
            )
        else:
            logger.info(
                "维度[%s]联合优化完成，实际α=%.3f，目标α=%.3f",
                normalized_dimension,
                actual_alpha,
                target_alpha,
            )

        for item in items:
            runtime_item = item.to_runtime_item()
            runtime_items.append(runtime_item)
            item_dimension_map[item.choice_key] = normalized_dimension
            assigned = list(best_choices_by_item.get(item.choice_key) or [])
            if not assigned:
                continue
            has_locked_items = True
            for sample_index, choice in enumerate(assigned):
                answers_by_sample.setdefault(sample_index, {})[item.choice_key] = int(choice)

    if not has_locked_items:
        return None

    return JointPsychometricAnswerPlan(
        answers_by_sample=answers_by_sample,
        diagnostics_by_dimension=diagnostics_by_dimension,
        item_dimension_map=item_dimension_map,
        items=runtime_items,
        sample_count=sample_count,
    )


__all__ = [
    "CombinedPsychometricPlan",
    "JOINT_PSYCHOMETRIC_SUPPORTED_TYPES",
    "JointPsychometricAnswerPlan",
    "JointPsychometricDimensionDiagnostic",
    "JointPsychometricSamplePlan",
    "PsychometricBlueprintItem",
    "build_joint_psychometric_answer_plan",
    "build_psychometric_blueprint",
    "build_psychometric_choice_key",
]

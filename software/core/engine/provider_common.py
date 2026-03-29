"""Provider 运行时共享预处理与中立工具。"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlparse

from software.core.persona.context import reset_context as _reset_answer_context
from software.core.persona.generator import generate_persona, reset_persona, set_current_persona
from software.core.psychometrics import build_dimension_psychometric_plan
from software.core.questions.consistency import reset_consistency_context
from software.core.questions.strict_ratio import is_strict_ratio_question
from software.core.task import TaskContext
from software.core.questions.tendency import reset_tendency

_PSYCHO_BIAS_CHOICES = {"left", "center", "right"}


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


def build_psychometric_plan_for_run(ctx: TaskContext) -> Optional[Any]:
    """根据当前任务配置构建本轮问卷的心理测量作答计划。"""
    grouped_items: Dict[str, List[Tuple[int, str, int, str, Optional[int]]]] = {}

    for question_num in sorted(ctx.question_config_index_map.keys()):
        config_entry = ctx.question_config_index_map.get(question_num)
        if not config_entry:
            continue

        question_type, start_index = config_entry
        dimension = str(ctx.question_dimension_map.get(question_num) or "").strip()
        if not dimension:
            continue
        if is_strict_ratio_question(ctx, question_num):
            continue

        question_meta = ctx.questions_metadata.get(question_num) or {}
        meta_option_count = int(question_meta.get("options") or 0)
        saved_bias = ctx.question_psycho_bias_map.get(question_num, "custom")

        if question_type in ("scale", "score"):
            probability_config = ctx.scale_prob[start_index] if start_index < len(ctx.scale_prob) else -1
            option_count = _resolve_option_count(probability_config, meta_option_count, default_value=5)
            bias = _resolve_bias(saved_bias, probability_config, option_count)
            grouped_items.setdefault(dimension, []).append((question_num, question_type, option_count, bias, None))
            continue

        if question_type == "matrix":
            row_count = int(question_meta.get("rows") or 0)
            if row_count <= 0:
                row_count = 1

            for row_idx in range(row_count):
                matrix_prob_idx = start_index + row_idx
                probability_config = ctx.matrix_prob[matrix_prob_idx] if matrix_prob_idx < len(ctx.matrix_prob) else -1
                option_count = _resolve_option_count(
                    probability_config,
                    meta_option_count,
                    default_value=max(meta_option_count, 5),
                )
                row_bias = saved_bias[row_idx] if isinstance(saved_bias, list) and row_idx < len(saved_bias) else saved_bias
                bias = _resolve_bias(row_bias, probability_config, option_count)
                grouped_items.setdefault(dimension, []).append((question_num, "matrix", option_count, bias, row_idx))

    if not grouped_items:
        return None

    try:
        target_alpha = float(getattr(ctx, "psycho_target_alpha", 0.9) or 0.9)
    except Exception:
        target_alpha = 0.9
    target_alpha = max(0.70, min(0.95, target_alpha))

    return build_dimension_psychometric_plan(
        grouped_items=grouped_items,
        target_alpha=target_alpha,
    )


@contextmanager
def provider_run_context(ctx: TaskContext, *, psycho_plan: Optional[Any] = None) -> Iterator[Optional[Any]]:
    """在 provider 运行前统一初始化画像、上下文与心理测量计划。"""
    persona = generate_persona()
    set_current_persona(persona)
    _reset_answer_context()
    reset_tendency()
    reset_consistency_context(ctx.answer_rules, list((ctx.questions_metadata or {}).values()))

    resolved_plan = psycho_plan
    if resolved_plan is None:
        resolved_plan = build_psychometric_plan_for_run(ctx)
    if resolved_plan is not None:
        dimension_count = len(getattr(resolved_plan, "plans", {}) or {})
        logging.info(
            "本轮启用心理测量计划：维度数=%d，题目数=%d，目标α=%.2f",
            dimension_count,
            len(getattr(resolved_plan, "items", []) or []),
            float(getattr(ctx, "psycho_target_alpha", 0.9) or 0.9),
        )

    try:
        yield resolved_plan
    finally:
        reset_persona()


def normalize_url_for_compare(value: str) -> str:
    """用于比较的 URL 归一化：去掉 fragment，去掉首尾空白。"""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except Exception:
        return text
    try:
        if parsed.fragment:
            parsed = parsed._replace(fragment="")
        return parsed.geturl()
    except Exception:
        return text


__all__ = [
    "build_psychometric_plan_for_run",
    "normalize_url_for_compare",
    "provider_run_context",
]

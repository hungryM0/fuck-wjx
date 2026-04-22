"""Provider 运行时共享预处理与中立工具。"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from software.core.persona.context import reset_context as _reset_answer_context
from software.core.persona.generator import generate_persona, reset_persona, set_current_persona
from software.core.psychometrics import (
    CombinedPsychometricPlan,
    build_dimension_psychometric_plan,
    build_joint_psychometric_answer_plan,
    build_psychometric_blueprint,
)
from software.core.psychometrics.psychometric import normalize_target_alpha
from software.core.questions.config import GLOBAL_RELIABILITY_DIMENSION
from software.core.questions.consistency import reset_consistency_context
from software.core.task import ExecutionConfig, ExecutionState
from software.core.questions.tendency import reset_tendency


def _build_grouped_runtime_items(
    config: ExecutionConfig,
) -> Dict[str, List[Any]]:
    grouped_items: Dict[str, List[Any]] = {}
    for dimension, items in build_psychometric_blueprint(config).items():
        normalized_dimension = str(dimension or "").strip()
        if not normalized_dimension:
            continue
        bucket = grouped_items.setdefault(normalized_dimension, [])
        for item in items:
            bucket.append(item.to_runtime_item())
    return grouped_items


def build_psychometric_plan_for_run(config: ExecutionConfig) -> Optional[Any]:
    """根据当前任务配置构建本轮问卷的心理测量作答计划。"""
    grouped_items = _build_grouped_runtime_items(config)

    if not grouped_items:
        return None

    try:
        target_alpha = normalize_target_alpha(getattr(config, "psycho_target_alpha", None))
    except Exception:
        target_alpha = normalize_target_alpha(None)

    return build_dimension_psychometric_plan(
        grouped_items=grouped_items,
        target_alpha=target_alpha,
    )


def ensure_joint_psychometric_answer_plan(config: ExecutionConfig) -> Optional[Any]:
    cached = getattr(config, "joint_psychometric_answer_plan", None)
    if cached is not None:
        return cached
    plan = build_joint_psychometric_answer_plan(config)
    config.joint_psychometric_answer_plan = plan
    return plan


@contextmanager
def provider_run_context(
    config: ExecutionConfig,
    *,
    state: Optional[ExecutionState] = None,
    thread_name: str = "",
    psycho_plan: Optional[Any] = None,
) -> Iterator[Optional[Any]]:
    """在 provider 运行前统一初始化画像、上下文与心理测量计划。"""
    persona = generate_persona()
    set_current_persona(persona)
    _reset_answer_context()
    reset_tendency()
    reset_consistency_context(config.answer_rules, list((config.questions_metadata or {}).values()))

    resolved_plan = psycho_plan
    fallback_plan: Optional[Any] = None
    joint_sample_plan: Optional[Any] = None
    reserved_sample_index: Optional[int] = None
    if resolved_plan is None:
        fallback_plan = build_psychometric_plan_for_run(config)
        joint_answer_plan = ensure_joint_psychometric_answer_plan(config)
        if joint_answer_plan is not None and state is not None:
            reserved_sample_index = state.peek_reserved_joint_sample(thread_name)
            if reserved_sample_index is not None:
                joint_sample_plan = joint_answer_plan.build_sample_plan(reserved_sample_index)
            else:
                logging.warning("线程[%s]存在联合信效度计划但未预留样本槽位，已回退常规逻辑", thread_name or "Worker-?")
        if joint_sample_plan is not None and fallback_plan is not None:
            resolved_plan = CombinedPsychometricPlan(primary=joint_sample_plan, fallback=fallback_plan)
        elif joint_sample_plan is not None:
            resolved_plan = joint_sample_plan
        else:
            resolved_plan = fallback_plan

    if joint_sample_plan is not None:
        diagnostics = dict(getattr(joint_sample_plan, "diagnostics_by_dimension", {}) or {})
        active_dimensions = [
            name
            for name, diagnostic in diagnostics.items()
            if not bool(getattr(diagnostic, "skipped", False))
        ]
        logging.info(
            "本轮启用联合信效度计划：样本槽位=%d，维度数=%d，锁定题目数=%d，目标α=%.2f，维度=%s",
            int(reserved_sample_index or 0) + 1,
            len(active_dimensions),
            len(getattr(joint_sample_plan, "choices", {}) or {}),
            float(getattr(config, "psycho_target_alpha", 0.9) or 0.9),
            ",".join(active_dimensions[:5]) if active_dimensions else "无",
        )
        for diagnostic in diagnostics.values():
            if bool(getattr(diagnostic, "skipped", False)):
                continue
            if not bool(getattr(diagnostic, "degraded_for_ratio", False)):
                continue
            logging.warning(
                "维度[%s]已保比例优先，实际α=%.3f 低于目标α=%.3f，主方向=%s，反向题=%d，锚点明确=%s",
                getattr(diagnostic, "dimension", ""),
                float(getattr(diagnostic, "actual_alpha", 0.0) or 0.0),
                float(getattr(diagnostic, "target_alpha", 0.0) or 0.0),
                str(getattr(diagnostic, "anchor_direction", "center") or "center"),
                int(getattr(diagnostic, "reverse_item_count", 0) or 0),
                "否" if bool(getattr(diagnostic, "ambiguous_anchor", False)) else "是",
            )
    elif resolved_plan is not None:
        dimension_count = len(getattr(resolved_plan, "plans", {}) or {})
        plan_names = list((getattr(resolved_plan, "plans", {}) or {}).keys())
        if plan_names == [GLOBAL_RELIABILITY_DIMENSION]:
            dimension_summary = "全局未分组问卷"
        else:
            dimension_summary = ",".join(plan_names[:5]) if plan_names else "无"
        logging.info(
            "本轮启用心理测量计划：维度数=%d，题目数=%d，目标α=%.2f，维度=%s",
            dimension_count,
            len(getattr(resolved_plan, "items", []) or []),
            float(getattr(config, "psycho_target_alpha", 0.9) or 0.9),
            dimension_summary,
        )

    try:
        yield resolved_plan
    finally:
        reset_persona()
__all__ = [
    "build_psychometric_plan_for_run",
    "ensure_joint_psychometric_answer_plan",
    "provider_run_context",
]

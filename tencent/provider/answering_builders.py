"""Tencent batch answer action builders."""

from __future__ import annotations

import random
from typing import Any, List, Optional, Sequence

from software.app.config import DEFAULT_FILL_TEXT
from software.core.ai.runtime import AIRuntimeError, agenerate_ai_answer
from software.core.persona.context import apply_persona_boost
from software.core.questions.consistency import (
    apply_matrix_row_consistency,
    apply_single_like_consistency,
    get_multiple_rule_constraint,
)
from software.core.questions.distribution import (
    resolve_distribution_probabilities,
)
from software.core.questions.text_values import (
    resolve_option_fill_text_from_config,
    resolve_text_values_from_config,
)
from software.core.questions.strict_ratio import (
    enforce_reference_rank_order,
    is_strict_ratio_question,
    stochastic_round,
    weighted_sample_without_replacement,
)
from software.core.questions.tendency import get_tendency_index
from software.core.questions.utils import (
    normalize_droplist_probs,
    weighted_index,
)
from software.core.task import ExecutionState
from software.providers.answering import AnswerAction
from software.providers.contracts import SurveyQuestionMeta

from .answering_rules import apply_multiple_constraints, normalize_selected_indices


async def _build_qq_single_action(
    driver: Any | None,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any] = None,
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    question_id = str(question.provider_question_id or "")
    option_texts = list(question.option_texts or [])
    raw_option_count = len(option_texts) or int(question.options or 0)
    if raw_option_count <= 0:
        return None
    option_count = max(1, raw_option_count)
    probabilities = config.single_prob[config_index] if config_index < len(config.single_prob) else -1
    probabilities = normalize_droplist_probs(probabilities, option_count)
    strict_ratio = is_strict_ratio_question(ctx, current)
    dimension = config.question_dimension_map.get(current)
    has_reliability_dimension = isinstance(dimension, str) and bool(str(dimension).strip())
    if not strict_ratio:
        probabilities = apply_persona_boost(option_texts, probabilities)
    if not has_reliability_dimension:
        probabilities = apply_single_like_consistency(probabilities, current)
    if strict_ratio or has_reliability_dimension:
        strict_reference = list(probabilities)
        probabilities = resolve_distribution_probabilities(
            probabilities,
            option_count,
            ctx,
            current,
            psycho_plan=psycho_plan,
        )
        probabilities = enforce_reference_rank_order(probabilities, strict_reference)
    selected_index = (
        get_tendency_index(
            option_count,
            probabilities,
            dimension=dimension,
            psycho_plan=psycho_plan,
            question_index=current,
        )
        if has_reliability_dimension
        else weighted_index(probabilities)
    )
    selected_text = option_texts[selected_index] if selected_index < len(option_texts) else ""
    fill_entries = config.single_option_fill_texts[config_index] if config_index < len(config.single_option_fill_texts) else None
    fill_value = await resolve_option_fill_text_from_config(
        fill_entries,
        selected_index,
        driver=driver,
        question_title=str(question.title or ""),
        question_number=current,
        option_text=selected_text,
    )
    selected_texts = [f"{selected_text} / {fill_value}" if selected_text and fill_value else (fill_value or selected_text)]
    return AnswerAction(
        question_num=current,
        question_id=question_id,
        kind="choice",
        input_type="radio",
        selected_indices=(selected_index,),
        option_fill_texts=((selected_index, fill_value),) if fill_value else (),
        selected_texts=tuple(selected_texts),
        record_type="single",
        pending_distribution_choices=((selected_index, option_count, None),) if strict_ratio or has_reliability_dimension else (),
    )


async def _build_qq_text_action(
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    blank_count = max(1, int(getattr(question, "text_inputs", 1) or 1))
    text_entry_types = list(getattr(ctx.config, "text_entry_types", []) or [])
    multi_text_blank_modes = list(getattr(ctx.config, "multi_text_blank_modes", []) or [])
    multi_text_blank_ranges = list(getattr(ctx.config, "multi_text_blank_int_ranges", []) or [])
    text_values = resolve_text_values_from_config(
        config.texts[config_index] if config_index < len(config.texts) else [DEFAULT_FILL_TEXT],
        config.texts_prob[config_index] if config_index < len(config.texts_prob) else [1.0],
        blank_count=blank_count,
        entry_type=str(text_entry_types[config_index] if config_index < len(text_entry_types) else "text"),
        blank_modes=multi_text_blank_modes[config_index] if config_index < len(multi_text_blank_modes) else [],
        blank_int_ranges=multi_text_blank_ranges[config_index] if config_index < len(multi_text_blank_ranges) else [],
    )
    ai_enabled = bool(config.text_ai_flags[config_index]) if config_index < len(config.text_ai_flags) else False
    if ai_enabled:
        title = str(question.title or "")
        description = str(question.description or "").strip()
        ai_prompt = title.strip()
        if description and description not in ai_prompt:
            ai_prompt = f"{ai_prompt}\n补充说明：{description}"
        try:
            generated = await agenerate_ai_answer(ai_prompt, question_type="fill_blank", blank_count=1)
        except AIRuntimeError as exc:
            raise AIRuntimeError(f"腾讯问卷第{current}题 AI 生成失败：{exc}") from exc
        text_values = (
            [str(item or "").strip() or DEFAULT_FILL_TEXT for item in list(generated or [])]
            if isinstance(generated, list)
            else [str(generated or "").strip() or DEFAULT_FILL_TEXT]
        )
    if len(text_values) < blank_count:
        text_values.extend([text_values[-1] if text_values else DEFAULT_FILL_TEXT] * (blank_count - len(text_values)))
    return AnswerAction(
        question_num=current,
        question_id=str(question.provider_question_id or ""),
        kind="text",
        text_values=tuple(str(item or "").strip() or DEFAULT_FILL_TEXT for item in text_values[:blank_count]),
        record_type="text",
    )


async def _build_qq_dropdown_action(
    driver: Any | None,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    question_id = str(question.provider_question_id or "")
    option_texts = list(question.option_texts or [])
    raw_option_count = len(option_texts) or int(question.options or 0)
    if raw_option_count <= 0:
        return None
    option_count = max(1, raw_option_count)
    probabilities = config.droplist_prob[config_index] if config_index < len(config.droplist_prob) else -1
    probabilities = normalize_droplist_probs(probabilities, option_count)
    strict_ratio = is_strict_ratio_question(ctx, current)
    dimension = config.question_dimension_map.get(current)
    has_reliability_dimension = isinstance(dimension, str) and bool(str(dimension).strip())
    if not strict_ratio:
        probabilities = apply_persona_boost(option_texts, probabilities)
    if strict_ratio or has_reliability_dimension:
        strict_reference = list(probabilities)
        probabilities = resolve_distribution_probabilities(
            probabilities,
            option_count,
            ctx,
            current,
            psycho_plan=psycho_plan,
        )
        if strict_ratio:
            probabilities = enforce_reference_rank_order(probabilities, strict_reference)
    selected_index = (
        get_tendency_index(
            option_count,
            probabilities,
            dimension=dimension,
            psycho_plan=psycho_plan,
            question_index=current,
        )
        if has_reliability_dimension
        else weighted_index(probabilities)
    )
    selected_text = option_texts[selected_index] if selected_index < len(option_texts) else ""
    fill_entries = config.droplist_option_fill_texts[config_index] if config_index < len(config.droplist_option_fill_texts) else None
    fill_value = await resolve_option_fill_text_from_config(
        fill_entries,
        selected_index,
        driver=driver,
        question_title=str(question.title or ""),
        question_number=current,
        option_text=selected_text,
    )
    selected_texts = [f"{selected_text} / {fill_value}" if selected_text and fill_value else (fill_value or selected_text)]
    return AnswerAction(
        question_num=current,
        question_id=question_id,
        kind="select",
        selected_indices=(selected_index,),
        option_fill_texts=((selected_index, fill_value),) if fill_value else (),
        selected_texts=tuple(selected_texts),
        record_type="dropdown",
        pending_distribution_choices=((selected_index, option_count, None),) if strict_ratio or has_reliability_dimension else (),
    )


async def _build_qq_score_like_action(
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    raw_option_count = int(question.options or 0)
    if raw_option_count <= 0:
        return None
    option_count = max(2, raw_option_count)
    probabilities = config.scale_prob[config_index] if config_index < len(config.scale_prob) else -1
    probs = normalize_droplist_probs(probabilities, option_count)
    probs = apply_single_like_consistency(probs, current)
    probs = resolve_distribution_probabilities(
        probs,
        option_count,
        ctx,
        current,
        psycho_plan=psycho_plan,
    )
    selected_index = get_tendency_index(
        option_count,
        probs,
        dimension=config.question_dimension_map.get(current),
        psycho_plan=psycho_plan,
        question_index=current,
    )
    return AnswerAction(
        question_num=current,
        question_id=str(question.provider_question_id or ""),
        kind="choice",
        input_type="radio",
        selected_indices=(selected_index,),
        record_type="score",
        pending_distribution_choices=((selected_index, option_count, None),),
    )


async def _build_qq_multiple_action(
    driver: Any | None,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    option_texts = list(question.option_texts or [])
    raw_option_count = len(option_texts) or int(question.options or 0)
    if raw_option_count <= 0:
        return None
    option_count = max(1, raw_option_count)
    min_required = int(question.multi_min_limit or 1)
    max_allowed = int(question.multi_max_limit or option_count or 1)
    min_required = max(1, min(min_required, option_count))
    max_allowed = max(1, min(max_allowed, option_count))
    if min_required > max_allowed:
        min_required = max_allowed

    must_select_indices, must_not_select_indices, _ = get_multiple_rule_constraint(current, option_count)
    required_indices = normalize_selected_indices(sorted(must_select_indices or []), option_count)
    blocked_indices = normalize_selected_indices(sorted(must_not_select_indices or []), option_count)

    async def _finalize(selected_indices: Sequence[int]) -> Optional[AnswerAction]:
        selected = normalize_selected_indices(selected_indices, option_count)
        if not selected:
            return None
        fill_entries = config.multiple_option_fill_texts[config_index] if config_index < len(config.multiple_option_fill_texts) else None
        fill_texts: list[tuple[int, str]] = []
        selected_texts: list[str] = []
        for option_idx in selected:
            selected_text = option_texts[option_idx] if option_idx < len(option_texts) else ""
            fill_value = await resolve_option_fill_text_from_config(
                fill_entries,
                option_idx,
                driver=driver,
                question_title=str(question.title or ""),
                question_number=current,
                option_text=selected_text,
            )
            if fill_value:
                fill_texts.append((option_idx, fill_value))
                selected_text = f"{selected_text} / {fill_value}" if selected_text else fill_value
            selected_texts.append(selected_text)
        return AnswerAction(
            question_num=current,
            question_id=str(question.provider_question_id or ""),
            kind="choice",
            input_type="checkbox",
            selected_indices=tuple(selected),
            option_fill_texts=tuple(fill_texts),
            selected_texts=tuple(selected_texts),
            record_type="multiple",
        )

    selection_probabilities = config.multiple_prob[config_index] if config_index < len(config.multiple_prob) else [50.0] * option_count
    if selection_probabilities == -1 or (
        isinstance(selection_probabilities, list)
        and len(selection_probabilities) == 1
        and selection_probabilities[0] == -1
    ):
        available_pool = [idx for idx in range(option_count) if idx not in blocked_indices and idx not in required_indices]
        min_total = max(min_required, len(required_indices))
        max_total = min(max_allowed, len(required_indices) + len(available_pool))
        if min_total > max_total:
            min_total = max_total
        extra_min = max(0, min_total - len(required_indices))
        extra_max = max(0, max_total - len(required_indices))
        extra_count = random.randint(extra_min, extra_max) if extra_max >= extra_min else 0
        sampled = random.sample(available_pool, extra_count) if extra_count > 0 else []
        selected = apply_multiple_constraints(
            list(required_indices) + sampled,
            option_count,
            min_required,
            max_allowed,
            required_indices,
            blocked_indices,
            available_pool,
        )
        return await _finalize(selected)

    sanitized_probabilities: List[float] = []
    for raw_prob in selection_probabilities:
        try:
            prob_value = float(raw_prob)
        except Exception:
            prob_value = 0.0
        sanitized_probabilities.append(max(0.0, min(100.0, prob_value)))
    if len(sanitized_probabilities) < option_count:
        sanitized_probabilities.extend([0.0] * (option_count - len(sanitized_probabilities)))
    elif len(sanitized_probabilities) > option_count:
        sanitized_probabilities = sanitized_probabilities[:option_count]

    strict_ratio = is_strict_ratio_question(ctx, current)
    if not strict_ratio:
        boosted = apply_persona_boost(option_texts, sanitized_probabilities)
        sanitized_probabilities = [min(100.0, prob) for prob in boosted]
    for idx in blocked_indices:
        sanitized_probabilities[idx] = 0.0
    for idx in required_indices:
        sanitized_probabilities[idx] = 0.0

    if strict_ratio:
        positive_optional = [
            idx for idx, prob in enumerate(sanitized_probabilities)
            if prob > 0 and idx not in blocked_indices and idx not in required_indices
        ]
        required_selected = normalize_selected_indices(required_indices, option_count)
        if len(required_selected) > max_allowed:
            required_selected = required_selected[:max_allowed]
        min_total = max(min_required, len(required_selected))
        max_total = min(max_allowed, len(required_selected) + len(positive_optional))
        if min_total > max_total:
            min_total = max_total
        expected_optional = sum(sanitized_probabilities[idx] for idx in positive_optional) / 100.0
        total_target = len(required_selected) + stochastic_round(expected_optional)
        total_target = max(min_total, min(max_total, total_target))
        optional_target = max(0, total_target - len(required_selected))
        sampled_optional = weighted_sample_without_replacement(
            positive_optional,
            [sanitized_probabilities[idx] for idx in positive_optional],
            optional_target,
        )
        return await _finalize(required_selected + sampled_optional)

    positive_indices = [idx for idx, prob in enumerate(sanitized_probabilities) if prob > 0]
    if not positive_indices and not required_indices:
        return None
    selection_mask: List[int] = []
    attempts = 0
    max_attempts = 32
    if positive_indices:
        while sum(selection_mask) == 0 and attempts < max_attempts:
            selection_mask = [1 if random.random() < (prob / 100.0) else 0 for prob in sanitized_probabilities]
            attempts += 1
        if sum(selection_mask) == 0:
            selection_mask = [0] * option_count
            selection_mask[random.choice(positive_indices)] = 1
    selected = [
        idx for idx, selected_flag in enumerate(selection_mask)
        if selected_flag == 1 and sanitized_probabilities[idx] > 0
    ]
    selected = apply_multiple_constraints(
        selected,
        option_count,
        min_required,
        max_allowed,
        required_indices,
        blocked_indices,
        positive_indices,
    )
    if not selected and positive_indices:
        selected = [random.choice(positive_indices)]
    return await _finalize(selected)


async def _build_qq_matrix_action(
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    row_count = max(1, int(question.rows or 1))
    raw_option_count = int(question.options or 0)
    if raw_option_count <= 0:
        return None
    option_count = max(2, raw_option_count)
    strict_ratio_question = is_strict_ratio_question(ctx, current)
    next_index = config_index
    selected_indices: list[int] = []
    pending: list[tuple[int, int, Optional[int]]] = []
    for row_index in range(row_count):
        raw_probabilities = config.matrix_prob[next_index] if next_index < len(config.matrix_prob) else -1
        next_index += 1
        strict_reference: Optional[List[float]] = None
        row_probabilities: Any = -1
        if isinstance(raw_probabilities, list):
            try:
                probs = [float(value) for value in raw_probabilities]
            except Exception:
                probs = []
            if len(probs) != option_count:
                probs = [1.0] * option_count
            strict_reference = list(probs)
            probs = apply_matrix_row_consistency(probs, current, row_index)
            if any(prob > 0 for prob in probs):
                row_probabilities = resolve_distribution_probabilities(
                    probs,
                    option_count,
                    ctx,
                    current,
                    row_index=row_index,
                    psycho_plan=psycho_plan,
                )
        else:
            uniform_probs = apply_matrix_row_consistency([1.0] * option_count, current, row_index)
            if any(prob > 0 for prob in uniform_probs):
                row_probabilities = resolve_distribution_probabilities(
                    uniform_probs,
                    option_count,
                    ctx,
                    current,
                    row_index=row_index,
                    psycho_plan=psycho_plan,
                )
        if strict_ratio_question and isinstance(row_probabilities, list):
            row_probabilities = enforce_reference_rank_order(row_probabilities, strict_reference or row_probabilities)
        selected_index = get_tendency_index(
            option_count,
            row_probabilities,
            dimension=config.question_dimension_map.get(current),
            psycho_plan=psycho_plan,
            question_index=current,
            row_index=row_index,
        )
        selected_indices.append(selected_index)
        pending.append((selected_index, option_count, row_index))
    return AnswerAction(
        question_num=current,
        question_id=str(question.provider_question_id or ""),
        kind="matrix",
        matrix_indices=tuple(selected_indices),
        record_type="matrix",
        pending_distribution_choices=tuple(pending),
    )


async def build_answer_action(
    driver: Any | None,
    question: SurveyQuestionMeta,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> Optional[AnswerAction]:
    question_id = str(getattr(question, "provider_question_id", "") or "").strip()
    if not question_id:
        return None
    config_entry = ctx.config.question_config_index_map.get(int(question.num or 0))
    if not config_entry:
        return None
    entry_type, config_index = config_entry
    required_config_fields = {
        "single": ("single_prob", "single_option_fill_texts"),
        "multiple": ("multiple_prob", "multiple_option_fill_texts"),
        "dropdown": ("droplist_prob", "droplist_option_fill_texts"),
        "text": ("texts", "texts_prob", "text_ai_flags"),
        "multi_text": ("texts", "texts_prob", "text_ai_flags"),
        "scale": ("scale_prob",),
        "score": ("scale_prob",),
        "matrix": ("matrix_prob",),
    }.get(entry_type)
    if not required_config_fields or not all(hasattr(ctx.config, field_name) for field_name in required_config_fields):
        return None
    if entry_type == "single":
        return await _build_qq_single_action(driver, question, config_index, ctx, psycho_plan=psycho_plan)
    if entry_type == "multiple":
        return await _build_qq_multiple_action(driver, question, config_index, ctx)
    if entry_type == "dropdown":
        return await _build_qq_dropdown_action(driver, question, config_index, ctx, psycho_plan=psycho_plan)
    if entry_type in {"text", "multi_text"}:
        return await _build_qq_text_action(question, config_index, ctx)
    if entry_type in {"scale", "score"}:
        return await _build_qq_score_like_action(question, config_index, ctx, psycho_plan=psycho_plan)
    if entry_type == "matrix":
        return await _build_qq_matrix_action(question, config_index, ctx, psycho_plan=psycho_plan)
    return None


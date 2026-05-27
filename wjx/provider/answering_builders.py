"""WJX batch answer action builders."""

from __future__ import annotations

import math
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
from software.core.reverse_fill.runtime import resolve_current_reverse_fill_answer
from software.core.reverse_fill.schema import (
    REVERSE_FILL_KIND_CHOICE,
    REVERSE_FILL_KIND_MATRIX,
    REVERSE_FILL_KIND_MULTI_TEXT,
    REVERSE_FILL_KIND_TEXT,
)
from software.core.task import ExecutionState
from software.providers.answering import AnswerAction
from software.providers.answering.selection import (
    coerce_positive_int as _coerce_positive_int,
    valid_forced_choice_index as _valid_forced_choice_index,
)
from software.providers.contracts import SurveyQuestionMeta
from wjx.provider.questions.multiple_rules import _normalize_selected_indices


async def _resolve_runtime_option_texts(
    _driver: Any,
    question: SurveyQuestionMeta,
) -> list[str]:
    return [str(item or "").strip() for item in list(question.option_texts or []) if str(item or "").strip()]

async def _build_wjx_single_action(
    driver: Any,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any] = None,
    thread_name: str = "",
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    option_texts = await _resolve_runtime_option_texts(driver, question)
    option_count = max(1, len(option_texts) or int(question.options or 0))
    reverse_fill_answer = resolve_current_reverse_fill_answer(
        ctx,
        current,
        thread_name=thread_name,
    )
    forced_index: Optional[int] = None
    if reverse_fill_answer is not None and reverse_fill_answer.kind == REVERSE_FILL_KIND_CHOICE:
        forced_index = _valid_forced_choice_index(reverse_fill_answer.choice_index, option_count)
    if forced_index is None:
        forced_index = _valid_forced_choice_index(question.forced_option_index, option_count)

    strict_ratio = False
    dimension = config.question_dimension_map.get(current)
    has_reliability_dimension = isinstance(dimension, str) and bool(str(dimension).strip())
    if forced_index is None:
        probabilities = config.single_prob[config_index] if config_index < len(config.single_prob) else -1
        probabilities = normalize_droplist_probs(probabilities, option_count)
        strict_ratio = is_strict_ratio_question(ctx, current)
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
    else:
        selected_index = forced_index

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
        kind="choice",
        input_type="radio",
        selected_indices=(selected_index,),
        option_fill_texts=((selected_index, fill_value),) if fill_value else (),
        selected_texts=tuple(selected_texts),
        record_type="single",
        pending_distribution_choices=((selected_index, option_count, None),) if forced_index is None and (strict_ratio or has_reliability_dimension) else (),
    )


async def _build_wjx_dropdown_action(
    driver: Any,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
    thread_name: str = "",
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    option_texts = await _resolve_runtime_option_texts(driver, question)
    option_count = max(1, len(option_texts) or int(question.options or 0))
    reverse_fill_answer = resolve_current_reverse_fill_answer(
        ctx,
        current,
        thread_name=thread_name,
    )
    forced_index: Optional[int] = None
    if reverse_fill_answer is not None and reverse_fill_answer.kind == REVERSE_FILL_KIND_CHOICE:
        forced_index = _valid_forced_choice_index(reverse_fill_answer.choice_index, option_count)
    if forced_index is None:
        forced_index = _valid_forced_choice_index(question.forced_option_index, option_count)

    dimension = config.question_dimension_map.get(current)
    has_reliability_dimension = isinstance(dimension, str) and bool(str(dimension).strip())
    strict_ratio = False
    if forced_index is None:
        probabilities = config.droplist_prob[config_index] if config_index < len(config.droplist_prob) else -1
        probabilities = normalize_droplist_probs(probabilities, option_count)
        strict_ratio = is_strict_ratio_question(ctx, current)
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
    else:
        selected_index = forced_index

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
        kind="select",
        selected_indices=(selected_index,),
        option_fill_texts=((selected_index, fill_value),) if fill_value else (),
        selected_texts=tuple(selected_texts),
        record_type="dropdown",
        pending_distribution_choices=((selected_index, option_count, None),) if forced_index is None and (strict_ratio or has_reliability_dimension) else (),
    )


async def _build_wjx_text_action(
    driver: Any,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    thread_name: str = "",
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    blank_count = max(1, int(question.text_inputs or 0))
    reverse_fill_answer = resolve_current_reverse_fill_answer(
        ctx,
        current,
        thread_name=thread_name,
    )

    if reverse_fill_answer is not None and reverse_fill_answer.kind == REVERSE_FILL_KIND_MULTI_TEXT:
        text_values = [str(item or "").strip() or DEFAULT_FILL_TEXT for item in list(reverse_fill_answer.text_values or [])]
    elif reverse_fill_answer is not None and reverse_fill_answer.kind == REVERSE_FILL_KIND_TEXT:
        text_values = [str(reverse_fill_answer.text_value or "").strip() or DEFAULT_FILL_TEXT]
    else:
        ai_enabled = bool(config.text_ai_flags[config_index]) if config_index < len(config.text_ai_flags) else False
        title = str(question.title or "").strip()
        description = str(question.description or "").strip()
        if ai_enabled:
            ai_prompt = title or f"第{current}题"
            if description and description not in ai_prompt:
                ai_prompt = f"{ai_prompt}\n补充说明：{description}"
            try:
                generated = await agenerate_ai_answer(ai_prompt, question_type="fill_blank", blank_count=blank_count)
            except AIRuntimeError as exc:
                raise AIRuntimeError(f"问卷星第{current}题 AI 生成失败：{exc}") from exc
            text_values = (
                [str(item or "").strip() or DEFAULT_FILL_TEXT for item in list(generated or [])]
                if isinstance(generated, list)
                else [str(generated or "").strip() or DEFAULT_FILL_TEXT]
            )
        else:
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

    if not text_values:
        text_values = [DEFAULT_FILL_TEXT]
    if len(text_values) < blank_count:
        text_values.extend([text_values[-1]] * (blank_count - len(text_values)))
    return AnswerAction(
        question_num=current,
        kind="text",
        text_values=tuple(str(text_values[index] if index < len(text_values) else text_values[-1] or "").strip() or DEFAULT_FILL_TEXT for index in range(blank_count)),
        record_type="text",
    )


async def _build_wjx_score_like_action(
    driver: Any,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
    answer_type: str,
    thread_name: str = "",
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    option_texts = await _resolve_runtime_option_texts(driver, question)
    option_count = max(2, len(option_texts) or int(question.options or 0))
    reverse_fill_answer = resolve_current_reverse_fill_answer(
        ctx,
        current,
        thread_name=thread_name,
    )
    forced_index: Optional[int] = None
    if reverse_fill_answer is not None and reverse_fill_answer.kind == REVERSE_FILL_KIND_CHOICE:
        forced_index = _valid_forced_choice_index(reverse_fill_answer.choice_index, option_count)
    if forced_index is None:
        forced_index = _valid_forced_choice_index(question.forced_option_index, option_count)

    if forced_index is None:
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
    else:
        selected_index = forced_index
    return AnswerAction(
        question_num=current,
        kind="choice",
        input_type="radio",
        selected_indices=(selected_index,),
        selected_texts=(option_texts[selected_index] if selected_index < len(option_texts) else "",),
        record_type=answer_type,
        pending_distribution_choices=((selected_index, option_count, None),) if forced_index is None else (),
    )


async def _build_wjx_multiple_action(
    driver: Any,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    thread_name: str = "",
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    option_texts = await _resolve_runtime_option_texts(driver, question)
    option_count = max(1, len(option_texts) or int(question.options or 0))
    min_required = max(1, min(_coerce_positive_int(question.multi_min_limit, 1), option_count))
    max_allowed = max(1, min(_coerce_positive_int(question.multi_max_limit, option_count) or option_count, option_count))
    if min_required > max_allowed:
        min_required = max_allowed

    must_select_indices, must_not_select_indices, _ = get_multiple_rule_constraint(current, option_count)
    required_indices = _normalize_selected_indices(sorted(must_select_indices or []), option_count)
    blocked_indices = _normalize_selected_indices(sorted(must_not_select_indices or []), option_count)

    async def _finalize(selected_indices: Sequence[int]) -> Optional[AnswerAction]:
        selected = _normalize_selected_indices(list(selected_indices), option_count)
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
            kind="choice",
            input_type="checkbox",
            selected_indices=tuple(selected),
            option_fill_texts=tuple(fill_texts),
            selected_texts=tuple(selected_texts),
            record_type="multiple",
        )

    reverse_fill_answer = resolve_current_reverse_fill_answer(
        ctx,
        current,
        thread_name=thread_name,
    )
    if reverse_fill_answer is not None and reverse_fill_answer.kind == REVERSE_FILL_KIND_CHOICE:
        forced_index = reverse_fill_answer.choice_index
        if forced_index is not None:
            return await _finalize(_normalize_selected_indices([forced_index], option_count))

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
        return await _finalize(list(required_indices) + sampled)

    sanitized_probabilities: List[float] = []
    for raw_prob in selection_probabilities:
        try:
            prob_value = float(raw_prob)
        except Exception:
            prob_value = 0.0
        if math.isnan(prob_value) or math.isinf(prob_value):
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
        required_selected = _normalize_selected_indices(required_indices, option_count)
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
    selected = [idx for idx, selected_flag in enumerate(selection_mask) if selected_flag == 1 and sanitized_probabilities[idx] > 0]
    selected = _normalize_selected_indices(required_indices + selected, option_count)
    if len(selected) < min_required:
        missing = [idx for idx in positive_indices if idx not in selected and idx not in blocked_indices]
        while len(selected) < min_required and missing:
            selected.append(missing.pop(0))
    return await _finalize(selected[:max_allowed])


async def _build_wjx_matrix_action(
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
    thread_name: str = "",
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    row_count = max(1, int(question.rows or 1))
    option_count = max(2, len(question.option_texts or []) or int(question.options or 0))
    reverse_fill_answer = resolve_current_reverse_fill_answer(
        ctx,
        current,
        thread_name=thread_name,
    )
    forced_indices: list[int] = []
    if reverse_fill_answer is not None and reverse_fill_answer.kind == REVERSE_FILL_KIND_MATRIX:
        forced_indices = [int(item) for item in list(reverse_fill_answer.matrix_choice_indexes or []) if int(item) >= 0]
    strict_ratio_question = is_strict_ratio_question(ctx, current)
    selected_indices: list[int] = []
    pending: list[tuple[int, int, Optional[int]]] = []
    next_index = config_index
    for row_index in range(row_count):
        if row_index < len(forced_indices):
            selected_index = min(max(0, forced_indices[row_index]), option_count - 1)
        else:
            raw_probabilities = config.matrix_prob[next_index] if next_index < len(config.matrix_prob) else -1
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
            pending.append((selected_index, option_count, row_index))
        selected_indices.append(selected_index)
        next_index += 1
    return AnswerAction(
        question_num=current,
        kind="matrix",
        matrix_indices=tuple(selected_indices),
        record_type="matrix",
        pending_distribution_choices=tuple(pending),
    )


async def _build_wjx_slider_action(
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> Optional[AnswerAction]:
    target_value = 50.0
    if config_index < len(ctx.config.slider_targets):
        try:
            target_value = float(ctx.config.slider_targets[config_index])
        except Exception:
            target_value = 50.0
    return AnswerAction(
        question_num=int(question.num or 0),
        kind="slider",
        slider_value=target_value,
        record_type="slider",
    )


async def _build_wjx_order_action(
    driver: Any,
    question: SurveyQuestionMeta,
) -> AnswerAction:
    option_texts = await _resolve_runtime_option_texts(driver, question)
    option_count = max(1, len(option_texts) or int(question.options or 0))
    ordered_indices = list(range(option_count))
    random.shuffle(ordered_indices)
    return AnswerAction(
        question_num=int(question.num or 0),
        kind="order",
        selected_indices=tuple(ordered_indices),
        selected_texts=tuple(option_texts[index] for index in ordered_indices if index < len(option_texts)),
        record_type="order",
    )


async def build_answer_action(
    driver: Any,
    question: SurveyQuestionMeta,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
    thread_name: str = "",
) -> Optional[AnswerAction]:
    config_entry = ctx.config.question_config_index_map.get(int(question.num or 0))
    if not config_entry:
        return None
    entry_type, config_index = config_entry
    if entry_type == "single":
        return await _build_wjx_single_action(
            driver,
            question,
            config_index,
            ctx,
            psycho_plan=psycho_plan,
            thread_name=thread_name,
        )
    if entry_type == "multiple":
        return await _build_wjx_multiple_action(
            driver,
            question,
            config_index,
            ctx,
            thread_name=thread_name,
        )
    if entry_type == "dropdown":
        return await _build_wjx_dropdown_action(
            driver,
            question,
            config_index,
            ctx,
            psycho_plan=psycho_plan,
            thread_name=thread_name,
        )
    if entry_type in {"text", "multi_text"}:
        return await _build_wjx_text_action(
            driver,
            question,
            config_index,
            ctx,
            thread_name=thread_name,
        )
    if entry_type == "location":
        return None
    if entry_type == "matrix":
        return await _build_wjx_matrix_action(
            question,
            config_index,
            ctx,
            psycho_plan=psycho_plan,
            thread_name=thread_name,
        )
    if entry_type == "scale":
        return await _build_wjx_score_like_action(
            driver,
            question,
            config_index,
            ctx,
            psycho_plan=psycho_plan,
            answer_type="scale",
            thread_name=thread_name,
        )
    if entry_type == "score":
        return await _build_wjx_score_like_action(
            driver,
            question,
            config_index,
            ctx,
            psycho_plan=psycho_plan,
            answer_type="score",
            thread_name=thread_name,
        )
    if entry_type == "slider":
        return await _build_wjx_slider_action(question, config_index, ctx)
    if entry_type == "order":
        return await _build_wjx_order_action(driver, question)
    return None


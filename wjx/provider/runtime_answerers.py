"""WJX 题型执行逻辑。"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

from software.app.config import DEFAULT_FILL_TEXT
from software.core.ai.runtime import AIRuntimeError, agenerate_ai_answer
from software.core.persona.context import apply_persona_boost, record_answer
from software.core.questions.consistency import (
    apply_matrix_row_consistency,
    apply_single_like_consistency,
    get_multiple_rule_constraint,
)
from software.core.questions.distribution import (
    record_pending_distribution_choice,
    resolve_distribution_probabilities,
)
from software.core.questions.runtime_async import (
    resolve_runtime_option_fill_text_from_config,
    resolve_runtime_text_values_from_config,
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
from software.network.browser.runtime_async import BrowserDriver
from software.providers.contracts import SurveyQuestionMeta
from wjx.provider.questions.multiple_rules import _normalize_selected_indices

from .runtime_interactions import (
    _click_choice_input,
    _click_matrix_cell,
    _click_reorder_sequence,
    _fill_choice_option_additional_text,
    _fill_text_input,
    _prepare_question_interaction,
    _question_option_texts,
    _select_location_input,
    _set_select_value,
    _set_slider_value,
)


def _coerce_positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except Exception:
        number = int(default)
    return max(0, number)


@dataclass(frozen=True)
class AnswerAction:
    question_num: int
    kind: str
    input_type: str = ""
    selected_indices: tuple[int, ...] = ()
    matrix_indices: tuple[int, ...] = ()
    text_values: tuple[str, ...] = ()
    slider_value: Optional[float] = None
    option_fill_texts: tuple[tuple[int, str], ...] = ()
    selected_texts: tuple[str, ...] = ()
    record_type: str = ""
    pending_distribution_choices: tuple[tuple[int, int, Optional[int]], ...] = ()


@dataclass(frozen=True)
class BatchFillResult:
    applied: tuple[int, ...] = ()
    failed: tuple[int, ...] = ()
    skipped: tuple[int, ...] = ()


async def _resolve_runtime_option_texts(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
) -> list[str]:
    option_texts = [str(item or "").strip() for item in list(question.option_texts or []) if str(item or "").strip()]
    if option_texts:
        return option_texts
    return await _question_option_texts(driver, int(question.num or 0))


def _valid_forced_choice_index(raw_value: Any, option_count: int) -> Optional[int]:
    try:
        candidate = int(raw_value)
    except Exception:
        return None
    if 0 <= candidate < option_count:
        return candidate
    return None


def _action_payload(action: AnswerAction) -> dict[str, Any]:
    return {
        "questionNum": int(action.question_num),
        "kind": str(action.kind or ""),
        "inputType": str(action.input_type or ""),
        "selectedIndices": [int(item) for item in action.selected_indices],
        "matrixIndices": [int(item) for item in action.matrix_indices],
        "textValues": [str(item or "") for item in action.text_values],
        "sliderValue": action.slider_value,
        "optionFillTexts": [
            {"optionIndex": int(option_index), "value": str(value or "")}
            for option_index, value in action.option_fill_texts
            if str(value or "").strip()
        ],
    }


def _record_answer_action(ctx: ExecutionState, action: AnswerAction) -> None:
    current = int(action.question_num or 0)
    if current <= 0:
        return
    record_type = str(action.record_type or action.kind or "").strip()
    for option_index, option_count, row_index in action.pending_distribution_choices:
        record_pending_distribution_choice(
            ctx,
            current,
            int(option_index),
            int(option_count),
            row_index=row_index,
        )
    if record_type == "matrix":
        for row_index, selected_index in enumerate(action.matrix_indices):
            record_answer(current, "matrix", selected_indices=[int(selected_index)], row_index=row_index)
        return
    if record_type == "text":
        text_values = [str(item or "").strip() or DEFAULT_FILL_TEXT for item in action.text_values]
        if not text_values:
            text_values = [DEFAULT_FILL_TEXT]
        record_answer(current, "text", text_answer=" | ".join(text_values) if len(text_values) > 1 else text_values[0])
        return
    if record_type == "slider":
        record_answer(current, "slider", text_answer=str(action.slider_value if action.slider_value is not None else ""))
        return
    record_answer(
        current,
        record_type,
        selected_indices=[int(item) for item in action.selected_indices],
        selected_texts=[str(item or "") for item in action.selected_texts],
    )


async def _answer_wjx_single(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> bool:
    config = ctx.config
    current = int(question.num or 0)
    option_texts = await _resolve_runtime_option_texts(driver, question)
    option_count = max(1, len(option_texts) or int(question.options or 0))
    reverse_fill_answer = resolve_current_reverse_fill_answer(ctx, current)
    forced_index: Optional[int] = None
    if reverse_fill_answer is not None and reverse_fill_answer.kind == REVERSE_FILL_KIND_CHOICE:
        try:
            raw_choice_index = reverse_fill_answer.choice_index
            forced_index = int(raw_choice_index) if raw_choice_index is not None else None
        except Exception:
            forced_index = None
    if forced_index is not None and (forced_index < 0 or forced_index >= option_count):
        forced_index = None

    if forced_index is None and question.forced_option_index is not None:
        try:
            candidate = int(question.forced_option_index)
        except Exception:
            candidate = -1
        if 0 <= candidate < option_count:
            forced_index = candidate

    if forced_index is None:
        probabilities = config.single_prob[config_index] if config_index < len(config.single_prob) else -1
        probabilities = normalize_droplist_probs(probabilities, option_count)
        strict_ratio = is_strict_ratio_question(ctx, current)
        if not strict_ratio:
            probabilities = apply_persona_boost(option_texts, probabilities)
        probabilities = apply_single_like_consistency(probabilities, current)
        if strict_ratio:
            strict_reference = list(probabilities)
            probabilities = resolve_distribution_probabilities(probabilities, option_count, ctx, current)
            probabilities = enforce_reference_rank_order(probabilities, strict_reference)
        selected_index = weighted_index(probabilities)
    else:
        selected_index = forced_index
        strict_ratio = False

    if not await _click_choice_input(driver, current, "radio", selected_index):
        logging.warning("问卷星第%d题（单选）点击未生效。", current)
        return False

    selected_text = option_texts[selected_index] if selected_index < len(option_texts) else ""
    fill_entries = config.single_option_fill_texts[config_index] if config_index < len(config.single_option_fill_texts) else None
    fill_value = await resolve_runtime_option_fill_text_from_config(
        fill_entries,
        selected_index,
        driver=driver,
        question_number=current,
        option_text=selected_text,
    )
    if fill_value and await _fill_choice_option_additional_text(
        driver,
        current,
        selected_index,
        fill_value,
        input_type="radio",
    ):
        selected_text = f"{selected_text} / {fill_value}" if selected_text else fill_value

    if forced_index is None and strict_ratio:
        record_pending_distribution_choice(ctx, current, selected_index, option_count)
    record_answer(current, "single", selected_indices=[selected_index], selected_texts=[selected_text])
    return True


async def _answer_wjx_dropdown(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> bool:
    config = ctx.config
    current = int(question.num or 0)
    option_texts = await _resolve_runtime_option_texts(driver, question)
    option_count = max(1, len(option_texts) or int(question.options or 0))
    reverse_fill_answer = resolve_current_reverse_fill_answer(ctx, current)
    forced_index: Optional[int] = None
    if reverse_fill_answer is not None and reverse_fill_answer.kind == REVERSE_FILL_KIND_CHOICE:
        try:
            raw_choice_index = reverse_fill_answer.choice_index
            forced_index = int(raw_choice_index) if raw_choice_index is not None else None
        except Exception:
            forced_index = None
    if forced_index is not None and (forced_index < 0 or forced_index >= option_count):
        forced_index = None
    if forced_index is None and question.forced_option_index is not None:
        try:
            candidate = int(question.forced_option_index)
        except Exception:
            candidate = -1
        if 0 <= candidate < option_count:
            forced_index = candidate

    dimension = config.question_dimension_map.get(current)
    has_reliability_dimension = isinstance(dimension, str) and bool(str(dimension).strip())
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
        if has_reliability_dimension:
            selected_index = get_tendency_index(
                option_count,
                probabilities,
                dimension=dimension,
                psycho_plan=psycho_plan,
                question_index=current,
            )
        else:
            selected_index = weighted_index(probabilities)
    else:
        selected_index = forced_index
        strict_ratio = False

    selected_text = option_texts[selected_index] if selected_index < len(option_texts) else ""
    if not await _set_select_value(driver, current, selected_text, option_index=selected_index):
        logging.warning("问卷星第%d题（下拉）无法选中选项：%s", current, selected_text)
        return False

    fill_entries = config.droplist_option_fill_texts[config_index] if config_index < len(config.droplist_option_fill_texts) else None
    fill_value = await resolve_runtime_option_fill_text_from_config(
        fill_entries,
        selected_index,
        driver=driver,
        question_number=current,
        option_text=selected_text,
    )
    if fill_value and await _fill_choice_option_additional_text(
        driver,
        current,
        selected_index,
        fill_value,
        input_type="select",
    ):
        selected_text = f"{selected_text} / {fill_value}" if selected_text else fill_value

    if forced_index is None and (strict_ratio or has_reliability_dimension):
        record_pending_distribution_choice(ctx, current, selected_index, option_count)
    record_answer(current, "dropdown", selected_indices=[selected_index], selected_texts=[selected_text])
    return True


async def _answer_wjx_text(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> bool:
    config = ctx.config
    current = int(question.num or 0)
    blank_count = max(1, int(question.text_inputs or 0))
    reverse_fill_answer = resolve_current_reverse_fill_answer(ctx, current)

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
            if isinstance(generated, list):
                text_values = [str(item or "").strip() or DEFAULT_FILL_TEXT for item in list(generated or [])]
            else:
                text_values = [str(generated or "").strip() or DEFAULT_FILL_TEXT]
        else:
            text_entry_types = list(getattr(ctx.config, "text_entry_types", []) or [])
            entry_type = str(text_entry_types[config_index] if config_index < len(text_entry_types) else "text")
            multi_text_blank_modes = list(getattr(ctx.config, "multi_text_blank_modes", []) or [])
            multi_text_blank_ranges = list(getattr(ctx.config, "multi_text_blank_int_ranges", []) or [])
            text_values = resolve_runtime_text_values_from_config(
                config.texts[config_index] if config_index < len(config.texts) else [DEFAULT_FILL_TEXT],
                config.texts_prob[config_index] if config_index < len(config.texts_prob) else [1.0],
                blank_count=blank_count,
                entry_type=entry_type,
                blank_modes=multi_text_blank_modes[config_index] if config_index < len(multi_text_blank_modes) else [],
                blank_int_ranges=multi_text_blank_ranges[config_index] if config_index < len(multi_text_blank_ranges) else [],
            )

    if not text_values:
        text_values = [DEFAULT_FILL_TEXT]
    if len(text_values) < blank_count:
        text_values.extend([text_values[-1]] * (blank_count - len(text_values)))

    applied_values: list[str] = []
    for blank_index in range(blank_count):
        value = str(text_values[blank_index] if blank_index < len(text_values) else text_values[-1] or "").strip() or DEFAULT_FILL_TEXT
        if await _fill_text_input(driver, current, value, blank_index=blank_index):
            applied_values.append(value)

    if not applied_values:
        logging.warning("问卷星第%d题（文本）填写失败。", current)
        return False
    if blank_count > 1:
        record_answer(current, "text", text_answer=" | ".join(applied_values))
    else:
        record_answer(current, "text", text_answer=applied_values[0])
    return True


async def _answer_wjx_location(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    ctx: ExecutionState,
) -> bool:
    current = int(question.num or 0)
    location_parts = getattr(ctx.config, "location_parts", {}).get(current, [])
    value = await _select_location_input(driver, current, location_parts)
    if not value:
        logging.warning("问卷星第%d题（地区）选择失败。", current)
        return False
    record_answer(current, "text", text_answer=value)
    return True


def _format_matrix_weight_value(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return str(value or "").strip() or "随机"
    if math.isnan(number) or math.isinf(number):
        return "随机"
    text = f"{number:.6f}".rstrip("0").rstrip(".")
    return text or "0"


async def _answer_wjx_score_like(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
    answer_type: str,
) -> bool:
    config = ctx.config
    current = int(question.num or 0)
    option_texts = await _resolve_runtime_option_texts(driver, question)
    option_count = max(2, len(option_texts) or int(question.options or 0))
    reverse_fill_answer = resolve_current_reverse_fill_answer(ctx, current)
    forced_index: Optional[int] = None
    if reverse_fill_answer is not None and reverse_fill_answer.kind == REVERSE_FILL_KIND_CHOICE:
        try:
            raw_choice_index = reverse_fill_answer.choice_index
            forced_index = int(raw_choice_index) if raw_choice_index is not None else None
        except Exception:
            forced_index = None
    if forced_index is not None and (forced_index < 0 or forced_index >= option_count):
        forced_index = None
    if forced_index is None and question.forced_option_index is not None:
        try:
            candidate = int(question.forced_option_index)
        except Exception:
            candidate = -1
        if 0 <= candidate < option_count:
            forced_index = candidate

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

    if not await _click_choice_input(driver, current, "radio", selected_index):
        logging.warning("问卷星第%d题（%s）点击未生效。", current, answer_type)
        return False
    if forced_index is None:
        record_pending_distribution_choice(ctx, current, selected_index, option_count)
    record_answer(current, answer_type, selected_indices=[selected_index], selected_texts=[option_texts[selected_index] if selected_index < len(option_texts) else ""])
    return True


async def _answer_wjx_multiple(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> bool:
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

    async def _apply(selected_indices: Sequence[int]) -> List[int]:
        applied: List[int] = []
        fill_entries = config.multiple_option_fill_texts[config_index] if config_index < len(config.multiple_option_fill_texts) else None
        for option_idx in selected_indices:
            if not await _click_choice_input(driver, current, "checkbox", option_idx):
                continue
            fill_value = await resolve_runtime_option_fill_text_from_config(
                fill_entries,
                option_idx,
                driver=driver,
                question_number=current,
                option_text=option_texts[option_idx] if option_idx < len(option_texts) else "",
            )
            if fill_value:
                await _fill_choice_option_additional_text(
                    driver,
                    current,
                    option_idx,
                    fill_value,
                    input_type="checkbox",
                )
            applied.append(option_idx)
        return applied

    reverse_fill_answer = resolve_current_reverse_fill_answer(ctx, current)
    if reverse_fill_answer is not None and reverse_fill_answer.kind == REVERSE_FILL_KIND_CHOICE:
        forced_index = reverse_fill_answer.choice_index
        if forced_index is not None:
            normalized = _normalize_selected_indices([forced_index], option_count)
            confirmed = await _apply(normalized)
            if confirmed:
                selected_texts = [option_texts[i] for i in confirmed if i < len(option_texts)]
                record_answer(current, "multiple", selected_indices=confirmed, selected_texts=selected_texts)
                return True

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
        selected = _normalize_selected_indices(list(required_indices) + sampled, option_count)
        confirmed = await _apply(selected)
        if not confirmed:
            return False
        selected_texts = [option_texts[i] for i in confirmed if i < len(option_texts)]
        record_answer(current, "multiple", selected_indices=confirmed, selected_texts=selected_texts)
        return True

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
        selected = _normalize_selected_indices(required_selected + sampled_optional, option_count)
        confirmed = await _apply(selected)
        if not confirmed:
            return False
        selected_texts = [option_texts[i] for i in confirmed if i < len(option_texts)]
        record_answer(current, "multiple", selected_indices=confirmed, selected_texts=selected_texts)
        return True

    positive_indices = [idx for idx, prob in enumerate(sanitized_probabilities) if prob > 0]
    if not positive_indices and not required_indices:
        return False
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
    selected = selected[:max_allowed]
    confirmed = await _apply(selected)
    if not confirmed:
        return False
    selected_texts = [option_texts[i] for i in confirmed if i < len(option_texts)]
    record_answer(current, "multiple", selected_indices=confirmed, selected_texts=selected_texts)
    return True


async def _answer_wjx_matrix(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> bool:
    config = ctx.config
    current = int(question.num or 0)
    row_count = max(1, int(question.rows or 1))
    option_count = max(2, len(question.option_texts or []) or int(question.options or 0))
    reverse_fill_answer = resolve_current_reverse_fill_answer(ctx, current)
    forced_indices: list[int] = []
    if reverse_fill_answer is not None and reverse_fill_answer.kind == REVERSE_FILL_KIND_MATRIX:
        forced_indices = [int(item) for item in list(reverse_fill_answer.matrix_choice_indexes or []) if int(item) >= 0]
    strict_ratio_question = is_strict_ratio_question(ctx, current)
    answered_any = False
    answered_rows = 0
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
        if await _click_matrix_cell(driver, current, row_index, selected_index):
            if row_index >= len(forced_indices):
                record_pending_distribution_choice(ctx, current, selected_index, option_count, row_index=row_index)
            record_answer(current, "matrix", selected_indices=[selected_index], row_index=row_index)
            answered_any = True
            answered_rows += 1
        next_index += 1
    return answered_any and answered_rows == row_count


async def _answer_wjx_slider(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> bool:
    target_value = 50.0
    if config_index < len(ctx.config.slider_targets):
        try:
            target_value = float(ctx.config.slider_targets[config_index])
        except Exception:
            target_value = 50.0
    if await _set_slider_value(driver, int(question.num or 0), target_value):
        record_answer(int(question.num or 0), "slider", text_answer=str(target_value))
        return True
    return False


async def _answer_wjx_order(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
) -> bool:
    current = int(question.num or 0)
    option_texts = await _resolve_runtime_option_texts(driver, question)
    option_count = max(1, len(option_texts) or int(question.options or 0))
    ordered_indices = list(range(option_count))
    random.shuffle(ordered_indices)
    if await _click_reorder_sequence(driver, current, ordered_indices):
        selected_texts = [option_texts[index] for index in ordered_indices if index < len(option_texts)]
        record_answer(current, "order", selected_indices=ordered_indices, selected_texts=selected_texts)
        return True
    return False


async def _build_wjx_single_action(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    option_texts = await _resolve_runtime_option_texts(driver, question)
    option_count = max(1, len(option_texts) or int(question.options or 0))
    reverse_fill_answer = resolve_current_reverse_fill_answer(ctx, current)
    forced_index: Optional[int] = None
    if reverse_fill_answer is not None and reverse_fill_answer.kind == REVERSE_FILL_KIND_CHOICE:
        forced_index = _valid_forced_choice_index(reverse_fill_answer.choice_index, option_count)
    if forced_index is None:
        forced_index = _valid_forced_choice_index(question.forced_option_index, option_count)

    strict_ratio = False
    if forced_index is None:
        probabilities = config.single_prob[config_index] if config_index < len(config.single_prob) else -1
        probabilities = normalize_droplist_probs(probabilities, option_count)
        strict_ratio = is_strict_ratio_question(ctx, current)
        if not strict_ratio:
            probabilities = apply_persona_boost(option_texts, probabilities)
        probabilities = apply_single_like_consistency(probabilities, current)
        if strict_ratio:
            strict_reference = list(probabilities)
            probabilities = resolve_distribution_probabilities(probabilities, option_count, ctx, current)
            probabilities = enforce_reference_rank_order(probabilities, strict_reference)
        selected_index = weighted_index(probabilities)
    else:
        selected_index = forced_index

    selected_text = option_texts[selected_index] if selected_index < len(option_texts) else ""
    fill_entries = config.single_option_fill_texts[config_index] if config_index < len(config.single_option_fill_texts) else None
    fill_value = await resolve_runtime_option_fill_text_from_config(
        fill_entries,
        selected_index,
        driver=driver,
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
        pending_distribution_choices=((selected_index, option_count, None),) if forced_index is None and strict_ratio else (),
    )


async def _build_wjx_dropdown_action(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    option_texts = await _resolve_runtime_option_texts(driver, question)
    option_count = max(1, len(option_texts) or int(question.options or 0))
    reverse_fill_answer = resolve_current_reverse_fill_answer(ctx, current)
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
    fill_value = await resolve_runtime_option_fill_text_from_config(
        fill_entries,
        selected_index,
        driver=driver,
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
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    blank_count = max(1, int(question.text_inputs or 0))
    reverse_fill_answer = resolve_current_reverse_fill_answer(ctx, current)

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
            text_values = resolve_runtime_text_values_from_config(
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
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
    answer_type: str,
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    option_texts = await _resolve_runtime_option_texts(driver, question)
    option_count = max(2, len(option_texts) or int(question.options or 0))
    reverse_fill_answer = resolve_current_reverse_fill_answer(ctx, current)
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
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
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
            fill_value = await resolve_runtime_option_fill_text_from_config(
                fill_entries,
                option_idx,
                driver=driver,
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

    reverse_fill_answer = resolve_current_reverse_fill_answer(ctx, current)
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
) -> Optional[AnswerAction]:
    config = ctx.config
    current = int(question.num or 0)
    row_count = max(1, int(question.rows or 1))
    option_count = max(2, len(question.option_texts or []) or int(question.options or 0))
    reverse_fill_answer = resolve_current_reverse_fill_answer(ctx, current)
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
    driver: BrowserDriver,
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
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> Optional[AnswerAction]:
    if bool(getattr(question, "has_jump", False)) or bool(getattr(question, "has_dependent_display_logic", False)):
        return None
    config_entry = ctx.config.question_config_index_map.get(int(question.num or 0))
    if not config_entry:
        return None
    entry_type, config_index = config_entry
    if entry_type == "single":
        return await _build_wjx_single_action(driver, question, config_index, ctx)
    if entry_type == "multiple":
        return await _build_wjx_multiple_action(driver, question, config_index, ctx)
    if entry_type == "dropdown":
        return await _build_wjx_dropdown_action(driver, question, config_index, ctx, psycho_plan=psycho_plan)
    if entry_type in {"text", "multi_text"}:
        return await _build_wjx_text_action(driver, question, config_index, ctx)
    if entry_type == "location":
        return None
    if entry_type == "matrix":
        return await _build_wjx_matrix_action(question, config_index, ctx, psycho_plan=psycho_plan)
    if entry_type == "scale":
        return await _build_wjx_score_like_action(driver, question, config_index, ctx, psycho_plan=psycho_plan, answer_type="scale")
    if entry_type == "score":
        return await _build_wjx_score_like_action(driver, question, config_index, ctx, psycho_plan=psycho_plan, answer_type="score")
    if entry_type == "slider":
        return await _build_wjx_slider_action(question, config_index, ctx)
    if entry_type == "order":
        return await _build_wjx_order_action(driver, question)
    return None


async def apply_answer_actions(driver: BrowserDriver, actions: Sequence[AnswerAction]) -> BatchFillResult:
    unsupported_actions = [
        action
        for action in list(actions or [])
        if int(action.question_num or 0) > 0 and str(action.kind or "").strip() in {"location", "order"}
    ]
    normalized_actions = [
        action
        for action in list(actions or [])
        if int(action.question_num or 0) > 0 and str(action.kind or "").strip() not in {"location", "order"}
    ]
    if not normalized_actions:
        return BatchFillResult(failed=tuple(int(action.question_num) for action in unsupported_actions))
    payload = [_action_payload(action) for action in normalized_actions]
    script = r"""
        return (() => {
            const actions = Array.isArray(arguments[0]) ? arguments[0] : [];
            const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (!style || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };
            const dispatch = (target, names = ['input', 'change', 'click']) => {
                for (const name of names) {
                    try { target.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
                }
            };
            const setNativeValue = (target, value) => {
                const nextValue = String(value ?? '');
                try {
                    const proto = target.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement?.prototype : window.HTMLInputElement?.prototype;
                    const descriptor = proto ? Object.getOwnPropertyDescriptor(proto, 'value') : null;
                    if (descriptor && descriptor.set) descriptor.set.call(target, nextValue);
                    else target.value = nextValue;
                } catch (e) {
                    try { target.value = nextValue; } catch (err) {}
                }
                try { target.setAttribute('value', nextValue); } catch (e) {}
                dispatch(target, ['beforeinput', 'input', 'change', 'blur']);
            };
            const isTextInput = (el) => {
                if (!el) return false;
                const tag = String(el.tagName || '').toLowerCase();
                if (tag === 'textarea') return true;
                if (tag !== 'input') return false;
                const type = String(el.getAttribute('type') || '').toLowerCase();
                return !type || ['text', 'search', 'tel', 'number'].includes(type);
            };
            const clickChoice = (root, inputType, optionIndex) => {
                const inputs = Array.from(root.querySelectorAll(`input[type="${inputType}"]`)).filter(visible);
                const target = inputs[optionIndex] || null;
                const listCandidates = [
                    ...Array.from(root.querySelectorAll('.ui-controlgroup > div')),
                    ...Array.from(root.querySelectorAll("ul[tp='d'] li")),
                    ...Array.from(root.querySelectorAll('.scale-rating ul li')),
                ].filter(visible);
                const visualTarget = listCandidates[optionIndex] || null;
                if (!target && !visualTarget) return false;
                const labelByFor = target && target.id ? root.querySelector(`label[for="${target.id}"]`) : null;
                const candidates = [
                    labelByFor,
                    target?.closest('label'),
                    target?.closest('.ui-controlgroup > div'),
                    target?.closest('li'),
                    target?.parentElement,
                    target,
                    visualTarget?.querySelector('a'),
                    visualTarget,
                ].filter(Boolean);
                for (const node of candidates) {
                    try { node.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                    try { node.click(); } catch (e) {}
                    if (!target || target.checked) return true;
                }
                if (target) {
                    try { target.checked = true; } catch (e) {}
                    dispatch(target);
                    return !!target.checked;
                }
                return !!visualTarget;
            };
            const fillOptionText = (root, optionIndex, value) => {
                const text = String(value || '').trim();
                if (!text) return true;
                const optionRoots = Array.from(root.querySelectorAll('.ui-controlgroup > div'));
                const optionRoot = optionRoots[optionIndex] || null;
                const target = optionRoot
                    ? Array.from(optionRoot.querySelectorAll('input, textarea')).find((el) => visible(el) && isTextInput(el))
                    : null;
                if (!target) return false;
                setNativeValue(target, text);
                return String(target.value || '') === text;
            };
            const applyText = (root, values) => {
                const textValues = Array.isArray(values) && values.length ? values.map((item) => String(item ?? '')) : [''];
                const editableNodes = Array.from(root.querySelectorAll('.textEdit .textCont[contenteditable="true"], .textCont[contenteditable="true"], [contenteditable="true"]'))
                    .filter((el) => visible(el) || visible(el.closest('.textEdit')));
                const textInputs = Array.from(root.querySelectorAll('textarea, input')).filter((el) => visible(el) && isTextInput(el));
                const targets = editableNodes.length ? editableNodes : textInputs;
                if (!targets.length) return false;
                let applied = 0;
                targets.forEach((target, index) => {
                    const value = textValues[index] ?? textValues[textValues.length - 1] ?? '';
                    try { target.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                    try { target.focus(); } catch (e) {}
                    if (target.isContentEditable) {
                        try { target.textContent = value; } catch (e) {}
                        try { target.innerText = value; } catch (e) {}
                        dispatch(target, ['beforeinput', 'input', 'change', 'blur']);
                        const hidden = textInputs[index] || null;
                        if (hidden) setNativeValue(hidden, value);
                        const actual = String((hidden && hidden.value) || target.textContent || target.innerText || '');
                        if (actual === value) applied += 1;
                    } else {
                        setNativeValue(target, value);
                        if (String(target.value || '') === value) applied += 1;
                    }
                });
                return applied > 0 && applied >= Math.min(targets.length, textValues.length);
            };
            const applyMatrix = (root, indices) => {
                const rows = Array.from(root.querySelectorAll('tr')).filter((node) => {
                    const id = String(node.getAttribute('id') || '');
                    return /^drv\d+_\d+$/.test(id) && visible(node);
                });
                if (!rows.length) return false;
                let applied = 0;
                indices.forEach((rawIndex, rowIndex) => {
                    const colIndex = Number(rawIndex);
                    const row = rows[rowIndex];
                    if (!row || colIndex < 0) return;
                    const anchors = Array.from(row.querySelectorAll('a[dval]')).filter(visible);
                    const anchor = anchors[colIndex] || null;
                    if (anchor) {
                        const value = String(anchor.getAttribute('dval') || colIndex + 1);
                        try { anchor.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
                        try { anchor.click(); } catch (e) {}
                        try { anchor.classList.add('rate-on'); } catch (e) {}
                        const fid = String(row.getAttribute('fid') || '');
                        const hidden = fid ? document.getElementById(fid) : null;
                        if (hidden) {
                            setNativeValue(hidden, value);
                            if (String(hidden.value || '') === value) applied += 1;
                        } else {
                            applied += 1;
                        }
                        return;
                    }
                    const inputs = Array.from(row.querySelectorAll("input[type='radio'], input[type='checkbox']")).filter(visible);
                    const target = inputs[colIndex] || null;
                    if (!target) return;
                    const candidates = [target.closest('label'), target.closest('td'), target.parentElement, target].filter(Boolean);
                    for (const node of candidates) {
                        try { node.click(); } catch (e) {}
                        if (target.checked) break;
                    }
                    if (!target.checked) {
                        try { target.checked = true; } catch (e) {}
                        dispatch(target);
                    }
                    if (target.checked) applied += 1;
                });
                return applied === indices.length;
            };
            const applySlider = (root, questionNum, rawValue) => {
                const input = root.querySelector(`#q${questionNum}, input.ui-slider-input, input[type="range"]`);
                const targetValue = Number(rawValue);
                if (!input || Number.isNaN(targetValue)) return false;
                const minValue = Number(input.getAttribute('min') || 0);
                const maxValue = Number(input.getAttribute('max') || 100);
                const stepValue = Math.abs(Number(input.getAttribute('step') || 1)) || 1;
                let nextValue = Math.max(minValue, Math.min(maxValue, targetValue));
                nextValue = minValue + Math.round((nextValue - minValue) / stepValue) * stepValue;
                if (Math.abs(nextValue - Math.round(nextValue)) < 1e-6) nextValue = Math.round(nextValue);
                setNativeValue(input, String(nextValue));
                return String(input.value || '') === String(nextValue);
            };
            const applied = [];
            const failed = [];
            for (const action of actions) {
                const questionNum = Number(action.questionNum || 0);
                const root = document.querySelector(`#div${questionNum}`);
                if (!root || !visible(root)) {
                    failed.push(questionNum);
                    continue;
                }
                let ok = false;
                try {
                    if (action.kind === 'choice') {
                        const selected = Array.isArray(action.selectedIndices) ? action.selectedIndices : [];
                        ok = selected.length > 0 && selected.every((index) => clickChoice(root, action.inputType || 'radio', Number(index)));
                        if (ok && Array.isArray(action.optionFillTexts)) {
                            ok = action.optionFillTexts.every((item) => fillOptionText(root, Number(item.optionIndex), item.value));
                        }
                    } else if (action.kind === 'select') {
                        const select = root.querySelector(`#q${questionNum}, select`);
                        const selectedIndex = Number((action.selectedIndices || [])[0] ?? -1);
                        if (select && selectedIndex >= 0) {
                            const options = Array.from(select.options || []);
                            const validOptions = options.filter((opt, idx) => {
                                const text = String(opt.textContent || opt.innerText || '').replace(/\s+/g, ' ').trim();
                                const value = String(opt.value || '').trim();
                                if (idx !== 0) return true;
                                if (!text || value === '' || value === '0' || value === '-1' || value === '-2') return false;
                                return !text.replace(/\s+/g, '').startsWith('请选择');
                            });
                            const target = validOptions[selectedIndex] || null;
                            if (target) {
                                target.selected = true;
                                select.value = target.value;
                                dispatch(select, ['input', 'change', 'blur']);
                                ok = String(select.value || '') === String(target.value || '');
                            }
                        }
                        if (ok && Array.isArray(action.optionFillTexts)) {
                            ok = action.optionFillTexts.every((item) => fillOptionText(root, Number(item.optionIndex), item.value));
                        }
                    } else if (action.kind === 'text') {
                        ok = applyText(root, action.textValues);
                    } else if (action.kind === 'matrix') {
                        ok = applyMatrix(root, action.matrixIndices || []);
                    } else if (action.kind === 'slider') {
                        ok = applySlider(root, questionNum, action.sliderValue);
                    }
                } catch (e) {
                    ok = false;
                }
                if (ok) applied.push(questionNum);
                else failed.push(questionNum);
            }
            return { applied, failed };
        })();
    """
    try:
        raw_result = await driver.execute_script(script, payload) or {}
    except Exception:
        return BatchFillResult(failed=tuple(int(action.question_num) for action in normalized_actions))
    applied = tuple(int(item) for item in list(raw_result.get("applied") or []) if int(item or 0) > 0) if isinstance(raw_result, dict) else ()
    failed = tuple(int(item) for item in list(raw_result.get("failed") or []) if int(item or 0) > 0) if isinstance(raw_result, dict) else tuple(int(action.question_num) for action in normalized_actions)
    return BatchFillResult(
        applied=applied,
        failed=failed + tuple(int(action.question_num) for action in unsupported_actions),
    )


async def answer_page_batch(
    driver: BrowserDriver,
    questions: Sequence[SurveyQuestionMeta],
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> BatchFillResult:
    actions: list[AnswerAction] = []
    skipped: list[int] = []
    direct_questions: list[SurveyQuestionMeta] = []
    order_questions: list[SurveyQuestionMeta] = []
    for question in list(questions or []):
        question_num = int(getattr(question, "num", 0) or 0)
        if question_num <= 0:
            continue
        config_entry = ctx.config.question_config_index_map.get(question_num)
        if config_entry:
            entry_type = str(config_entry[0] or "")
            if entry_type == "location":
                direct_questions.append(question)
                continue
            if entry_type == "order":
                order_questions.append(question)
                continue
        action = await build_answer_action(driver, question, ctx, psycho_plan=psycho_plan)
        if action is None:
            skipped.append(question_num)
            continue
        actions.append(action)
    result = await apply_answer_actions(driver, actions) if actions else BatchFillResult()
    action_by_num = {int(action.question_num): action for action in actions}
    for question_num in result.applied:
        action = action_by_num.get(int(question_num))
        if action is not None:
            _record_answer_action(ctx, action)
    direct_applied: list[int] = []
    direct_failed: list[int] = []
    for question in direct_questions:
        question_num = int(getattr(question, "num", 0) or 0)
        await _prepare_question_interaction(driver, question_num)
        if await answer_question_by_meta(driver, question, ctx, psycho_plan=psycho_plan):
            direct_applied.append(question_num)
        else:
            direct_failed.append(question_num)
    order_applied: list[int] = []
    order_failed: list[int] = []
    for question in order_questions:
        question_num = int(getattr(question, "num", 0) or 0)
        await _prepare_question_interaction(driver, question_num)
        if await _answer_wjx_order(driver, question):
            order_applied.append(question_num)
        else:
            order_failed.append(question_num)
    return BatchFillResult(
        applied=tuple(result.applied) + tuple(direct_applied) + tuple(order_applied),
        failed=tuple(result.failed) + tuple(direct_failed) + tuple(order_failed),
        skipped=tuple(skipped),
    )


async def answer_question_by_meta(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> bool:
    config_entry = ctx.config.question_config_index_map.get(int(question.num or 0))
    if not config_entry:
        logging.warning("问卷星第%d题缺少配置映射，已跳过。", int(question.num or 0))
        return False
    entry_type, config_index = config_entry
    await _prepare_question_interaction(driver, int(question.num or 0))
    if entry_type == "single":
        return bool(await _answer_wjx_single(driver, question, config_index, ctx))
    if entry_type == "multiple":
        return bool(await _answer_wjx_multiple(driver, question, config_index, ctx))
    if entry_type == "dropdown":
        return bool(await _answer_wjx_dropdown(driver, question, config_index, ctx, psycho_plan=psycho_plan))
    if entry_type in {"text", "multi_text"}:
        return bool(await _answer_wjx_text(driver, question, config_index, ctx))
    if entry_type == "location":
        return bool(await _answer_wjx_location(driver, question, ctx))
    if entry_type == "matrix":
        return bool(await _answer_wjx_matrix(driver, question, config_index, ctx, psycho_plan=psycho_plan))
    if entry_type == "scale":
        return bool(
            await _answer_wjx_score_like(
                driver,
                question,
                config_index,
                ctx,
                psycho_plan=psycho_plan,
                answer_type="scale",
            )
        )
    if entry_type == "score":
        return bool(
            await _answer_wjx_score_like(
                driver,
                question,
                config_index,
                ctx,
                psycho_plan=psycho_plan,
                answer_type="score",
            )
        )
    if entry_type == "slider":
        return bool(await _answer_wjx_slider(driver, question, config_index, ctx))
    if entry_type == "order":
        return bool(await _answer_wjx_order(driver, question))
    logging.warning("问卷星第%d题暂未接入运行时题型：%s", int(question.num or 0), entry_type)
    return False


__all__ = [
    "AnswerAction",
    "BatchFillResult",
    "answer_page_batch",
    "answer_question_by_meta",
    "apply_answer_actions",
    "build_answer_action",
]

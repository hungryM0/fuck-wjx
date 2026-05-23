"""Direct Tencent question answering helpers."""

from __future__ import annotations

import logging
import random
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
from software.core.task import ExecutionState
from software.network.browser.runtime_async import BrowserDriver
from software.providers.contracts import SurveyQuestionMeta

from .runtime_interactions import (
    _apply_multiple_constraints,
    _click_choice_input,
    _click_matrix_cell,
    _click_star_cell,
    _describe_dropdown_state,
    _fill_choice_option_additional_text,
    _fill_text_question,
    _normalize_selected_indices,
    _open_dropdown,
    _prepare_question_interaction,
    _select_dropdown_option,
)

def _log_qq_matrix_row_choice(
    current: int,
    row_number: int,
    selected_index: int,
    option_texts: List[str],
    resolved_probabilities: Any,
    raw_probabilities: Any,
) -> None:
    _ = current, row_number, selected_index, option_texts, resolved_probabilities, raw_probabilities



async def _answer_qq_single(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any] = None,
) -> None:
    config = ctx.config
    current = int(question.num or 0)
    option_texts = list(question.option_texts or [])
    option_count = max(1, len(option_texts) or int(question.options or 0))
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
    if not await _click_choice_input(driver, str(question.provider_question_id or ""), "radio", selected_index):
        logging.warning("腾讯问卷第%d题（单选）点击未生效，已跳过。", current)
        return
    if strict_ratio or has_reliability_dimension:
        record_pending_distribution_choice(ctx, current, selected_index, option_count)
    selected_text = option_texts[selected_index] if selected_index < len(option_texts) else ""
    fill_entries = (
        config.single_option_fill_texts[config_index]
        if config_index < len(config.single_option_fill_texts)
        else None
    )
    fill_value = await resolve_runtime_option_fill_text_from_config(
        fill_entries,
        selected_index,
        driver=driver,
        question_number=current,
        option_text=selected_text,
    )
    if fill_value and await _fill_choice_option_additional_text(
            driver,
            str(question.provider_question_id or ""),
            selected_index,
            fill_value,
            input_type="radio",
        ):
        selected_text = f"{selected_text} / {fill_value}" if selected_text else fill_value
    record_answer(current, "single", selected_indices=[selected_index], selected_texts=[selected_text])

async def _answer_qq_dropdown(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> None:
    config = ctx.config
    current = int(question.num or 0)
    option_texts = list(question.option_texts or [])
    option_count = max(1, len(option_texts) or int(question.options or 0))
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
    selected_text = option_texts[selected_index] if selected_index < len(option_texts) else ""
    question_id = str(question.provider_question_id or "")
    selected_ok = False
    for attempt in range(2):
        await _prepare_question_interaction(
            driver,
            question_id,
            control_selectors=("input.t-input__inner", ".t-input", ".t-select__wrap"),
            settle_ms=220,
        )
        if not await _open_dropdown(driver, question_id):
            if attempt == 0:
                continue
            logging.warning(
                "腾讯问卷第%d题（下拉）无法打开选项面板。state=%s",
                current,
                await _describe_dropdown_state(driver, question_id),
            )
            return
        if await _select_dropdown_option(driver, question_id, selected_text):
            selected_ok = True
            break
    if not selected_ok:
        logging.warning(
            "腾讯问卷第%d题（下拉）无法选中选项：%s | state=%s",
            current,
            selected_text,
            await _describe_dropdown_state(driver, question_id),
        )
        return
    fill_entries = (
        config.droplist_option_fill_texts[config_index]
        if config_index < len(config.droplist_option_fill_texts)
        else None
    )
    fill_value = await resolve_runtime_option_fill_text_from_config(
        fill_entries,
        selected_index,
        driver=driver,
        question_number=current,
        option_text=selected_text,
    )
    if fill_value and await _fill_choice_option_additional_text(
            driver,
            question_id,
            selected_index,
            fill_value,
            input_type=None,
        ):
        selected_text = f"{selected_text} / {fill_value}" if selected_text else fill_value
    if strict_ratio or has_reliability_dimension:
        record_pending_distribution_choice(ctx, current, selected_index, option_count)
    record_answer(current, "dropdown", selected_indices=[selected_index], selected_texts=[selected_text])

async def _answer_qq_text(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> None:
    config = ctx.config
    current = int(question.num or 0)
    blank_count = max(1, int(getattr(question, "text_inputs", 1) or 1))
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
    selected_answer: str | list[str] = text_values if blank_count > 1 else (text_values[0] if text_values else DEFAULT_FILL_TEXT)
    ai_enabled = bool(config.text_ai_flags[config_index]) if config_index < len(config.text_ai_flags) else False
    title = str(question.title or "")
    description = str(question.description or "").strip()
    ai_prompt = title.strip()
    if description and description not in ai_prompt:
        ai_prompt = f"{ai_prompt}\n补充说明：{description}"
    if ai_enabled:
        try:
            generated = await agenerate_ai_answer(ai_prompt, question_type="fill_blank", blank_count=1)
        except AIRuntimeError as exc:
            raise AIRuntimeError(f"腾讯问卷第{current}题 AI 生成失败：{exc}") from exc
        if isinstance(generated, list):
            if blank_count > 1:
                selected_answer = [str(item or "").strip() or DEFAULT_FILL_TEXT for item in list(generated or [])]
            else:
                selected_answer = str(generated[0]).strip() if generated else DEFAULT_FILL_TEXT
        else:
            selected_answer = str(generated or "").strip() or DEFAULT_FILL_TEXT
    if not await _fill_text_question(driver, str(question.provider_question_id or ""), selected_answer):
        logging.warning("腾讯问卷第%d题（文本）填写失败。", current)
        return
    if isinstance(selected_answer, list):
        record_answer(current, "text", text_answer=" | ".join(selected_answer))
    else:
        record_answer(current, "text", text_answer=selected_answer)

async def _answer_qq_score_like(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> None:
    config = ctx.config
    current = int(question.num or 0)
    option_count = max(2, int(question.options or 0))
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
    if not await _click_choice_input(driver, str(question.provider_question_id or ""), "radio", selected_index):
        logging.warning("腾讯问卷第%d题（评分）点击未生效。", current)
        return
    record_pending_distribution_choice(ctx, current, selected_index, option_count)
    record_answer(current, "score", selected_indices=[selected_index])

async def _answer_qq_matrix(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> int:
    config = ctx.config
    current = int(question.num or 0)
    question_id = str(question.provider_question_id or "")
    row_count = max(1, int(question.rows or 1))
    option_count = max(2, int(question.options or 0))
    option_texts = list(question.option_texts or [])
    strict_ratio_question = is_strict_ratio_question(ctx, current)
    next_index = config_index
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
        if not await _click_matrix_cell(driver, question_id, row_index, selected_index):
            logging.warning("腾讯问卷第%d题（矩阵）第%d行点击失败。", current, row_index + 1)
            continue
        record_pending_distribution_choice(ctx, current, selected_index, option_count, row_index=row_index)
        _log_qq_matrix_row_choice(
            current,
            row_index + 1,
            selected_index,
            option_texts,
            row_probabilities,
            raw_probabilities,
        )
        record_answer(current, "matrix", selected_indices=[selected_index], row_index=row_index)
    return next_index

async def _answer_qq_multiple(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> None:
    config = ctx.config
    current = int(question.num or 0)
    option_texts = list(question.option_texts or [])
    option_count = max(1, len(option_texts) or int(question.options or 0))
    min_required = int(question.multi_min_limit or 1)
    max_allowed = int(question.multi_max_limit or option_count or 1)
    min_required = max(1, min(min_required, option_count))
    max_allowed = max(1, min(max_allowed, option_count))
    if min_required > max_allowed:
        min_required = max_allowed

    must_select_indices, must_not_select_indices, _ = get_multiple_rule_constraint(current, option_count)
    required_indices = _normalize_selected_indices(sorted(must_select_indices or []), option_count)
    blocked_indices = _normalize_selected_indices(sorted(must_not_select_indices or []), option_count)

    async def _apply(selected_indices: Sequence[int]) -> List[int]:
        applied = []
        question_id = str(question.provider_question_id or "")
        fill_entries = (
            config.multiple_option_fill_texts[config_index]
            if config_index < len(config.multiple_option_fill_texts)
            else None
        )
        for option_idx in selected_indices:
            if await _click_choice_input(driver, question_id, "checkbox", option_idx):
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
                        question_id,
                        option_idx,
                        fill_value,
                        input_type="checkbox",
                    )
                applied.append(option_idx)
        return applied

    selection_probabilities = (
        config.multiple_prob[config_index]
        if config_index < len(config.multiple_prob)
        else [50.0] * option_count
    )
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
        selected = _apply_multiple_constraints(
            list(required_indices) + sampled,
            option_count,
            min_required,
            max_allowed,
            required_indices,
            blocked_indices,
            available_pool,
        )
        confirmed = await _apply(selected)
        if confirmed:
            selected_texts = [option_texts[i] for i in confirmed if i < len(option_texts)]
            record_answer(current, "multiple", selected_indices=confirmed, selected_texts=selected_texts)
        return

    sanitized_probabilities: List[float] = []
    for raw_prob in selection_probabilities:
        try:
            prob_value = float(raw_prob)
        except Exception:
            prob_value = 0.0
        prob_value = max(0.0, min(100.0, prob_value))
        sanitized_probabilities.append(prob_value)
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
        if confirmed:
            selected_texts = [option_texts[i] for i in confirmed if i < len(option_texts)]
            record_answer(current, "multiple", selected_indices=confirmed, selected_texts=selected_texts)
        return

    positive_indices = [idx for idx, prob in enumerate(sanitized_probabilities) if prob > 0]
    if not positive_indices and not required_indices:
        return
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
    selected = _apply_multiple_constraints(
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
    confirmed = await _apply(selected)
    if confirmed:
        selected_texts = [option_texts[i] for i in confirmed if i < len(option_texts)]
        record_answer(current, "multiple", selected_indices=confirmed, selected_texts=selected_texts)


async def _answer_qq_matrix_star(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> int:
    """处理腾讯问卷矩阵星级题（matrix_star）。

    逻辑与普通矩阵题相同，但用 _click_star_cell 代替 _click_matrix_cell，
    因为星级组件基于 TDesign t-rate，不含 input[type="radio"]。
    """
    config = ctx.config
    current = int(question.num or 0)
    question_id = str(question.provider_question_id or "")
    row_count = max(1, int(question.rows or 1))
    option_count = max(2, int(question.options or 0))
    option_texts = list(question.option_texts or [])
    strict_ratio_question = is_strict_ratio_question(ctx, current)
    next_index = config_index
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
        clicked = await _click_star_cell(driver, question_id, row_index, selected_index)
        if not clicked:
            clicked = await _click_matrix_cell(driver, question_id, row_index, selected_index)
            if not clicked:
                logging.warning("腾讯问卷第%d题（矩阵星级）第%d行点击失败。", current, row_index + 1)
                continue
        record_pending_distribution_choice(ctx, current, selected_index, option_count, row_index=row_index)
        _log_qq_matrix_row_choice(
            current,
            row_index + 1,
            selected_index,
            option_texts,
            row_probabilities,
            raw_probabilities,
        )
        record_answer(current, "matrix", selected_indices=[selected_index], row_index=row_index)
    return next_index


"""Credamo choice answering helpers."""

from __future__ import annotations

from typing import Any, Optional

from software.core.questions.utils import (
    normalize_droplist_probs,
    weighted_index,
)
from software.providers.answering.selection import positive_multiple_indexes_with_limits as _positive_multiple_indexes_with_limits

from .runtime_dom import (
    _click_element,
    _element_text,
    _is_checked,
    _option_click_targets,
    _option_inputs,
    _question_title_text,
    _root_text,
)

async def _resolve_forced_choice_index(page: Any, root: Any, option_texts: list[str]) -> Optional[int]:
    if not option_texts:
        return None
    try:
        from credamo.provider import parser as credamo_parser
    except Exception:
        return None

    title_text = await _question_title_text(page, root)
    extra_fragments = [await _root_text(page, root)]
    forced_index, _forced_text = credamo_parser._extract_force_select_option(
        title_text,
        option_texts,
        extra_fragments=extra_fragments,
    )
    if forced_index is None:
        forced_index, _forced_text = credamo_parser._extract_arithmetic_option(
            title_text,
            option_texts,
            extra_fragments=extra_fragments,
        )
    if forced_index is None or forced_index < 0:
        return None
    if forced_index >= len(option_texts):
        return None
    return forced_index


async def _single_choice_options(page: Any, root: Any) -> list[tuple[Any, Any, str]]:
    row_selectors = (
        ".single-choice .choice-row",
        ".single-choice .choice",
        ".choice-row",
        ".choice",
    )
    options: list[tuple[Any, Any, str]] = []

    for selector in row_selectors:
        try:
            rows = await root.query_selector_all(selector)
        except Exception:
            rows = []
        if not rows:
            continue
        for row in rows:
            try:
                input_element = await row.query_selector("input[type='radio'], [role='radio']")
            except Exception:
                input_element = None
            row_text = await _element_text(page, row)
            if input_element is None and not row_text:
                continue
            click_target = row if row is not None else input_element
            if click_target is None:
                continue
            options.append((input_element, click_target, row_text))
        if options:
            return options

    for input_element in await _option_inputs(root, "radio"):
        row_text = await _element_text(page, input_element)
        options.append((input_element, input_element, row_text))
    return options


async def _click_single_choice_option(page: Any, option: tuple[Any, Any, str]) -> bool:
    input_element, click_target, _text = option
    for candidate in (click_target, input_element):
        if candidate is None:
            continue
        if await _click_element(page, candidate):
            if input_element is None or await _is_checked(page, input_element):
                return True
    if input_element is not None:
        try:
            if bool(await page.evaluate("el => { el.click(); return !!el.checked; }", input_element)):
                return True
        except Exception:
            pass
    return False


async def _answer_single_like(page: Any, root: Any, weights: Any, option_count: int) -> bool:
    del option_count
    options = await _single_choice_options(page, root)
    target_count = len(options)
    if target_count <= 0:
        return False
    forced_option_texts = [text for _input, _target, text in options]
    forced_index = await _resolve_forced_choice_index(page, root, forced_option_texts)
    if forced_index is not None and forced_index < target_count and await _click_single_choice_option(page, options[forced_index]):
        return True
    probabilities = normalize_droplist_probs(weights, target_count)
    target_index = weighted_index(probabilities)
    return await _click_single_choice_option(page, options[min(target_index, target_count - 1)])


async def _resolve_multi_select_limits(page: Any, root: Any, option_count: int) -> tuple[Optional[int], Optional[int]]:
    try:
        from credamo.provider import parser as credamo_parser
    except Exception:
        return None, None

    title_text = await _question_title_text(page, root)
    extra_fragments = [await _root_text(page, root)]
    try:
        return credamo_parser._extract_multi_select_limits(
            title_text,
            option_count=option_count,
            extra_fragments=extra_fragments,
        )
    except Exception:
        return None, None


async def _answer_multiple(
    page: Any,
    root: Any,
    weights: Any,
    *,
    min_limit: Optional[int] = None,
    max_limit: Optional[int] = None,
) -> bool:
    inputs = await _option_inputs(root, "checkbox")
    targets = await _option_click_targets(root, "checkbox")
    total = len(inputs) if inputs else len(targets)
    if total <= 0:
        return False
    live_min_limit, live_max_limit = await _resolve_multi_select_limits(page, root, total)
    resolved_min_limit = min_limit if min_limit is not None else live_min_limit
    resolved_max_limit = max_limit if max_limit is not None else live_max_limit
    clicked = False
    for index in _positive_multiple_indexes_with_limits(
        weights,
        total,
        min_limit=resolved_min_limit,
        max_limit=resolved_max_limit,
    ):
        if index < len(inputs):
            clicked_now = await _click_element(page, inputs[index]) and await _is_checked(page, inputs[index])
            if not clicked_now:
                try:
                    clicked_now = bool(await page.evaluate("el => { el.click(); return !!el.checked; }", inputs[index]))
                except Exception:
                    clicked_now = False
            clicked = clicked_now or clicked
            continue
        if targets and index < len(targets):
            if await _click_element(page, targets[index]):
                refreshed_inputs = await _option_inputs(root, "checkbox")
                if index < len(refreshed_inputs) and await _is_checked(page, refreshed_inputs[index]):
                    clicked = True
    return clicked


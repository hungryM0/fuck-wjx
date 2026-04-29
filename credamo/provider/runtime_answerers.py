"""Credamo 见数运行时各题型作答实现。"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, List, Optional, Tuple

from software.app.config import DEFAULT_FILL_TEXT
from software.core.questions.utils import (
    get_fill_text_from_config,
    normalize_droplist_probs,
    weighted_index,
)

from .runtime_dom import (
    _click_element,
    _element_text,
    _input_value,
    _is_checked,
    _option_click_targets,
    _option_inputs,
    _question_title_text,
    _root_text,
    _text_inputs,
)


def _resolve_forced_choice_index(page: Any, root: Any, option_texts: List[str]) -> Optional[int]:
    if not option_texts:
        return None
    try:
        from credamo.provider import parser as credamo_parser
    except Exception:
        return None

    title_text = _question_title_text(page, root)
    extra_fragments = [_root_text(page, root)]
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


def _single_choice_options(page: Any, root: Any) -> List[Tuple[Any, Any, str]]:
    row_selectors = (
        ".single-choice .choice-row",
        ".single-choice .choice",
        ".choice-row",
        ".choice",
    )
    options: List[Tuple[Any, Any, str]] = []

    for selector in row_selectors:
        try:
            rows = root.query_selector_all(selector)
        except Exception:
            rows = []
        if not rows:
            continue
        for row in rows:
            try:
                input_element = row.query_selector("input[type='radio'], [role='radio']")
            except Exception:
                input_element = None
            row_text = _element_text(page, row)
            if input_element is None and not row_text:
                continue
            click_target = row if row is not None else input_element
            if click_target is None:
                continue
            options.append((input_element, click_target, row_text))
        if options:
            return options

    for input_element in _option_inputs(root, "radio"):
        row_text = _element_text(page, input_element)
        options.append((input_element, input_element, row_text))
    return options


def _click_single_choice_option(page: Any, option: Tuple[Any, Any, str]) -> bool:
    input_element, click_target, _text = option
    for candidate in (click_target, input_element):
        if candidate is None:
            continue
        if _click_element(page, candidate):
            if input_element is None or _is_checked(page, input_element):
                return True
    if input_element is not None:
        try:
            if bool(page.evaluate("el => { el.click(); return !!el.checked; }", input_element)):
                return True
        except Exception:
            pass
    return False


def _answer_single_like(page: Any, root: Any, weights: Any, option_count: int) -> bool:
    del option_count
    options = _single_choice_options(page, root)
    target_count = len(options)
    if target_count <= 0:
        return False
    forced_option_texts = [text for _input, _target, text in options]
    forced_index = _resolve_forced_choice_index(page, root, forced_option_texts)
    if forced_index is not None and forced_index < target_count and _click_single_choice_option(page, options[forced_index]):
        return True
    probabilities = normalize_droplist_probs(weights, target_count)
    target_index = weighted_index(probabilities)
    return _click_single_choice_option(page, options[min(target_index, target_count - 1)])


def _positive_multiple_indexes(weights: Any, option_count: int) -> List[int]:
    count = max(0, int(option_count or 0))
    if count <= 0:
        return []
    if not isinstance(weights, list) or not weights:
        return [random.randrange(count)]
    normalized: List[float] = []
    for idx in range(count):
        raw = weights[idx] if idx < len(weights) else 0.0
        try:
            normalized.append(max(0.0, float(raw)))
        except Exception:
            normalized.append(0.0)
    selected = [idx for idx, weight in enumerate(normalized) if weight > 0 and random.uniform(0, 100) <= weight]
    if not selected:
        positive = [idx for idx, weight in enumerate(normalized) if weight > 0]
        selected = [random.choice(positive)] if positive else [random.randrange(count)]
    return selected


def _resolve_multi_select_limits(page: Any, root: Any, option_count: int) -> Tuple[Optional[int], Optional[int]]:
    try:
        from credamo.provider import parser as credamo_parser
    except Exception:
        return None, None

    title_text = _question_title_text(page, root)
    extra_fragments = [_root_text(page, root)]
    try:
        return credamo_parser._extract_multi_select_limits(
            title_text,
            option_count=option_count,
            extra_fragments=extra_fragments,
        )
    except Exception:
        return None, None


def _positive_multiple_indexes_with_limits(
    weights: Any,
    option_count: int,
    *,
    min_limit: Optional[int] = None,
    max_limit: Optional[int] = None,
) -> List[int]:
    count = max(0, int(option_count or 0))
    if count <= 0:
        return []

    resolved_min = max(0, min(count, int(min_limit or 0)))
    resolved_max = count if max_limit is None else max(0, min(count, int(max_limit or 0)))
    if resolved_max <= 0:
        resolved_max = count
    if resolved_min > resolved_max:
        resolved_min = resolved_max

    selected = list(dict.fromkeys(_positive_multiple_indexes(weights, count)))
    if resolved_max < len(selected):
        selected = random.sample(selected, resolved_max)

    remaining_positive: List[int] = []
    remaining_any: List[int] = []
    if isinstance(weights, list) and weights:
        for idx in range(count):
            raw = weights[idx] if idx < len(weights) else 0.0
            try:
                weight = max(0.0, float(raw))
            except Exception:
                weight = 0.0
            if idx not in selected and weight > 0:
                remaining_positive.append(idx)
    remaining_any = [idx for idx in range(count) if idx not in selected and idx not in remaining_positive]
    random.shuffle(remaining_positive)
    random.shuffle(remaining_any)

    while len(selected) < resolved_min and (remaining_positive or remaining_any):
        if remaining_positive:
            selected.append(remaining_positive.pop())
            continue
        selected.append(remaining_any.pop())

    return sorted(dict.fromkeys(selected))


def _answer_multiple(
    page: Any,
    root: Any,
    weights: Any,
    *,
    min_limit: Optional[int] = None,
    max_limit: Optional[int] = None,
) -> bool:
    inputs = _option_inputs(root, "checkbox")
    targets = _option_click_targets(root, "checkbox")
    total = len(inputs) if inputs else len(targets)
    if total <= 0:
        return False
    live_min_limit, live_max_limit = _resolve_multi_select_limits(page, root, total)
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
            clicked_now = _click_element(page, inputs[index]) and _is_checked(page, inputs[index])
            if not clicked_now:
                try:
                    clicked_now = bool(page.evaluate("el => { el.click(); return !!el.checked; }", inputs[index]))
                except Exception:
                    clicked_now = False
            clicked = clicked_now or clicked
            continue
        if targets and index < len(targets):
            if _click_element(page, targets[index]):
                refreshed_inputs = _option_inputs(root, "checkbox")
                if index < len(refreshed_inputs) and _is_checked(page, refreshed_inputs[index]):
                    clicked = True
    return clicked


def _answer_text(root: Any, text_config: Any) -> bool:
    inputs = _text_inputs(root)
    if not inputs:
        return False
    values = text_config if isinstance(text_config, list) and text_config else [DEFAULT_FILL_TEXT]
    changed = False
    for index, input_element in enumerate(inputs):
        value = get_fill_text_from_config(values, index) or DEFAULT_FILL_TEXT
        try:
            input_element.fill(str(value), timeout=3000)
            changed = True
        except Exception:
            try:
                input_element.type(str(value), timeout=3000)
                changed = True
            except Exception:
                logging.info("Credamo 填空输入失败", exc_info=True)
    return changed


def _answer_dropdown(page: Any, root: Any, weights: Any) -> bool:
    trigger = None
    for selector in (".pc-dropdown .el-input", ".pc-dropdown .el-select", ".el-input", ".el-select", ".el-input__inner"):
        try:
            trigger = root.query_selector(selector)
        except Exception:
            trigger = None
        if trigger is not None:
            break
    try:
        value_input = root.query_selector(".el-input__inner")
    except Exception:
        value_input = None
    if trigger is None or value_input is None:
        return False
    previous_value = _input_value(page, value_input)
    try:
        trigger.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    if not _click_element(page, trigger):
        return False
    try:
        page.wait_for_timeout(120)
    except Exception:
        time.sleep(0.12)
    options = page.locator(".el-select-dropdown__item")
    try:
        option_count = int(options.count())
    except Exception:
        option_count = 0
    if option_count <= 0:
        try:
            option_count = max(1, len(root.query_selector_all(".el-select-dropdown__item, option")))
        except Exception:
            option_count = 1
    probabilities = normalize_droplist_probs(weights, option_count)
    target_index = min(weighted_index(probabilities), option_count - 1)

    def visible_dropdown_options() -> List[Any]:
        script = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = el.getBoundingClientRect();
    return rect.width >= 4 && rect.height >= 4;
  };
        return Array.from(document.querySelectorAll('.el-select-dropdown__item')).filter(visible);
}
"""
        try:
            handle = page.evaluate_handle(script)
        except Exception:
            return []
        try:
            properties = handle.get_properties()
            return [prop.as_element() for prop in properties.values() if prop.as_element() is not None]
        finally:
            try:
                handle.dispose()
            except Exception:
                pass

    visible_options = visible_dropdown_options()
    if visible_options:
        forced_option_texts = [_element_text(page, item) for item in visible_options]
        forced_index = _resolve_forced_choice_index(page, root, forced_option_texts)
        if forced_index is not None and forced_index < len(visible_options):
            target = visible_options[forced_index]
            if _click_element(page, target):
                try:
                    page.wait_for_timeout(120)
                except Exception:
                    time.sleep(0.12)
                current_value = _input_value(page, value_input)
                if current_value and current_value != previous_value:
                    return True
        target = visible_options[min(target_index, len(visible_options) - 1)]
        if _click_element(page, target):
            try:
                page.wait_for_timeout(120)
            except Exception:
                time.sleep(0.12)
            current_value = _input_value(page, value_input)
            if current_value and current_value != previous_value:
                return True

    try:
        value_input.focus()
    except Exception:
        pass
    try:
        for _ in range(target_index + 1):
            page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        try:
            page.wait_for_timeout(120)
        except Exception:
            time.sleep(0.12)
        current_value = _input_value(page, value_input)
        if current_value and current_value != previous_value:
            return True
    except Exception:
        pass
    target = options.nth(target_index)
    try:
        target.click(timeout=3000, force=True)
    except Exception:
        try:
            handle = target.element_handle(timeout=1000)
            if handle is None:
                return False
            page.evaluate("el => { el.click(); return true; }", handle)
        except Exception:
            return False
    current_value = _input_value(page, value_input)
    return bool(current_value and current_value != previous_value)


def _answer_scale(page: Any, root: Any, weights: Any) -> bool:
    try:
        options = root.query_selector_all(".scale .nps-item, .nps-item, .el-rate__item")
    except Exception:
        options = []
    if not options:
        return False
    probabilities = normalize_droplist_probs(weights, len(options))
    target_index = min(weighted_index(probabilities), len(options) - 1)
    return _click_element(page, options[target_index])


def _answer_order(page: Any, root: Any) -> bool:
    try:
        items = root.query_selector_all(".rank-order .choice-row, .choice-row")
    except Exception:
        items = []
    if not items:
        return False
    order = list(range(len(items)))
    random.shuffle(order)
    clicked = False
    for index in order:
        clicked = _click_element(page, items[index]) or clicked
        time.sleep(random.uniform(0.05, 0.12))
    return clicked

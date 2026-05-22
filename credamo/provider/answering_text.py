"""Credamo text and dropdown answering helpers."""

from __future__ import annotations

import logging
from typing import Any, Optional

from software.app.config import DEFAULT_FILL_TEXT
from software.core.engine.async_wait import sleep_or_stop
from software.core.questions.runtime_async import resolve_runtime_text_values_from_config
from software.core.questions.utils import (
    normalize_droplist_probs,
    weighted_index,
)

from .runtime_dom import (
    _click_element,
    _element_text,
    _input_value,
    _text_inputs,
)
from .answering_choices import _resolve_forced_choice_index

async def _answer_text(
    root: Any,
    text_config: Any,
    text_probabilities: Any = None,
    *,
    entry_type: str = "text",
    blank_modes: Optional[list[Any]] = None,
    blank_int_ranges: Optional[list[Any]] = None,
) -> bool:
    inputs = await _text_inputs(root)
    if not inputs:
        return False
    values = resolve_runtime_text_values_from_config(
        text_config if isinstance(text_config, list) and text_config else [DEFAULT_FILL_TEXT],
        text_probabilities if isinstance(text_probabilities, list) else None,
        blank_count=len(inputs),
        entry_type=entry_type,
        blank_modes=blank_modes,
        blank_int_ranges=blank_int_ranges,
    )
    changed = False
    for index, input_element in enumerate(inputs):
        value = values[index] if index < len(values) else values[-1]
        try:
            await input_element.fill(str(value), timeout=3000)
            changed = True
        except Exception:
            try:
                await input_element.type(str(value), timeout=3000)
                changed = True
            except Exception:
                logging.info("Credamo 填空输入失败", exc_info=True)
    return changed


async def _answer_dropdown(page: Any, root: Any, weights: Any) -> bool:
    trigger = None
    for selector in (".pc-dropdown .el-input", ".pc-dropdown .el-select", ".el-input", ".el-select", ".el-input__inner"):
        try:
            trigger = await root.query_selector(selector)
        except Exception:
            trigger = None
        if trigger is not None:
            break
    try:
        value_input = await root.query_selector(".el-input__inner")
    except Exception:
        value_input = None
    if trigger is None or value_input is None:
        return False
    def _dropdown_value_selected(current_value: Any) -> bool:
        return bool(str(current_value or "").strip())
    try:
        await trigger.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    if not await _click_element(page, trigger):
        return False
    await sleep_or_stop(None, 0.12)
    options = page.locator(".el-select-dropdown__item")
    try:
        option_count = int(await options.count())
    except Exception:
        option_count = 0
    if option_count <= 0:
        try:
            option_count = max(1, len(await root.query_selector_all(".el-select-dropdown__item, option")))
        except Exception:
            option_count = 1
    probabilities = normalize_droplist_probs(weights, option_count)
    target_index = min(weighted_index(probabilities), option_count - 1)

    async def visible_dropdown_options() -> list[Any]:
        try:
            handles = await page.query_selector_all(".el-select-dropdown__item")
        except Exception:
            return []
        visible_items: list[Any] = []
        for handle in handles:
            try:
                box = await handle.bounding_box()
            except Exception:
                box = None
            if not box:
                continue
            if float(box.get("width") or 0) < 4 or float(box.get("height") or 0) < 4:
                continue
            visible_items.append(handle)
        return visible_items

    visible_options = await visible_dropdown_options()
    if visible_options:
        forced_option_texts = [await _element_text(page, item) for item in visible_options]
        forced_index = await _resolve_forced_choice_index(page, root, forced_option_texts)
        if forced_index is not None and forced_index < len(visible_options):
            target = visible_options[forced_index]
            if await _click_element(page, target):
                await sleep_or_stop(None, 0.12)
                current_value = await _input_value(page, value_input)
                if _dropdown_value_selected(current_value):
                    return True
        target = visible_options[min(target_index, len(visible_options) - 1)]
        if await _click_element(page, target):
            await sleep_or_stop(None, 0.12)
            current_value = await _input_value(page, value_input)
            if _dropdown_value_selected(current_value):
                return True

    try:
        await value_input.focus()
    except Exception:
        pass
    try:
        for _ in range(target_index + 1):
            await page.keyboard.press("ArrowDown")
        await page.keyboard.press("Enter")
        await sleep_or_stop(None, 0.12)
        current_value = await _input_value(page, value_input)
        if _dropdown_value_selected(current_value):
            return True
    except Exception:
        pass
    target = options.nth(target_index)
    try:
        await target.click(timeout=3000, force=True)
    except Exception:
        try:
            handle = await target.element_handle(timeout=1000)
            if handle is None:
                return False
            await page.evaluate("el => { el.click(); return true; }", handle)
        except Exception:
            return False
    current_value = await _input_value(page, value_input)
    return _dropdown_value_selected(current_value)


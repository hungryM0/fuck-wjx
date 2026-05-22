"""Credamo matrix, scale, and order answering helpers."""

from __future__ import annotations

import random
from typing import Any

from software.core.engine.async_wait import sleep_or_stop
from software.core.questions.utils import (
    normalize_droplist_probs,
    weighted_index,
)
from software.providers.answering.selection import (
    positive_multiple_indexes_with_limits as _positive_multiple_indexes_with_limits,
)

from .runtime_dom import (
    _click_element,
)

async def _answer_scale(page: Any, root: Any, weights: Any) -> bool:
    try:
        options = await root.query_selector_all(".scale .nps-item, .nps-item, .el-rate__item")
    except Exception:
        options = []
    if not options:
        return False
    probabilities = normalize_droplist_probs(weights, len(options))
    target_index = min(weighted_index(probabilities), len(options) - 1)
    if not await _click_element(page, options[target_index]):
        return False
    try:
        selected = await page.evaluate(
            "el => !!el.querySelector('.scale .nps-item.selected, .nps-item.selected')",
            root,
        )
    except Exception:
        selected = None
    if selected is None:
        return True
    return bool(selected)


async def _matrix_rows(root: Any) -> list[tuple[Any, list[Any]]]:
    row_selectors = ("tbody tr", ".matrix-row", ".el-table__row")
    rows: list[tuple[Any, list[Any]]] = []
    for selector in row_selectors:
        try:
            row_nodes = await root.query_selector_all(selector)
        except Exception:
            row_nodes = []
        for row in row_nodes:
            try:
                controls = await row.query_selector_all("input[type='radio'], [role='radio'], .el-radio, .el-radio__input")
            except Exception:
                controls = []
            if len(controls) >= 2:
                rows.append((row, controls))
        if rows:
            return rows
    return rows


async def _answer_matrix(page: Any, root: Any, weights: Any, start_index: int = 0) -> bool:
    del start_index
    rows = await _matrix_rows(root)
    if not rows:
        return False
    clicked = False
    for row_offset, (_row, controls) in enumerate(rows):
        if not controls:
            continue
        row_weights = weights
        if isinstance(weights, list) and weights and any(isinstance(item, (list, tuple)) for item in weights):
            source_index = min(row_offset, len(weights) - 1)
            row_weights = weights[source_index]
        probabilities = normalize_droplist_probs(row_weights, len(controls))
        target_index = min(weighted_index(probabilities), len(controls) - 1)
        target = controls[target_index]
        clicked_now = await _click_element(page, target)
        if not clicked_now:
            try:
                clicked_now = bool(await page.evaluate("el => { el.click(); return true; }", target))
            except Exception:
                clicked_now = False
        clicked = clicked_now or clicked
        await sleep_or_stop(None, random.uniform(0.03, 0.08))
    return clicked


async def _answer_order(page: Any, root: Any) -> bool:
    try:
        items = await root.query_selector_all(".rank-order .choice-row, .choice-row")
    except Exception:
        items = []
    if not items:
        return False
    order = list(range(len(items)))
    random.shuffle(order)
    clicked = False
    for index in order:
        clicked = await _click_element(page, items[index]) or clicked
        await sleep_or_stop(None, random.uniform(0.05, 0.12))
    return clicked


def _normalize_positive_indices(weights: Any, option_count: int) -> list[int]:
    return _positive_multiple_indexes_with_limits(weights, option_count)


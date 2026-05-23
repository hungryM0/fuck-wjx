"""Credamo 见数运行时各题型作答兼容出口。"""

from __future__ import annotations

from typing import Any, Optional

from software.providers.answering import AnswerAction, BatchFillResult
from software.providers.answering.selection import (
    positive_multiple_indexes as _shared_positive_multiple_indexes,
    positive_multiple_indexes_with_limits as _shared_positive_multiple_indexes_with_limits,
)

from . import answering_applier as _applier
from . import answering_builders as _builders
from . import answering_choices as _choices
from . import answering_matrix as _matrix
from . import answering_text as _text

_PATCH_TARGETS = (_choices, _text, _matrix, _builders, _applier)
_ORIGINAL_TARGETS = {
    (module, name): getattr(module, name)
    for module in _PATCH_TARGETS
    for name in dir(module)
    if not name.startswith("__")
}
_WRAPPER_OBJECTS: dict[str, object] = {}
_MISSING = object()


def __getattr__(name: str) -> object:
    for module in _PATCH_TARGETS:
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _sync_patch_targets() -> None:
    names = {name for _module, name in _ORIGINAL_TARGETS}
    for name in names:
        facade_value = globals().get(name, _MISSING)
        patched = facade_value is not _MISSING and _WRAPPER_OBJECTS.get(name) is not facade_value
        for module in _PATCH_TARGETS:
            key = (module, name)
            if key not in _ORIGINAL_TARGETS:
                continue
            setattr(module, name, facade_value if patched else _ORIGINAL_TARGETS[key])


async def _resolve_forced_choice_index(page: Any, root: Any, option_texts: list[str]) -> Optional[int]:
    _sync_patch_targets()
    return await _choices._resolve_forced_choice_index(page, root, option_texts)


async def _single_choice_options(page: Any, root: Any) -> list[tuple[Any, Any, str]]:
    _sync_patch_targets()
    return await _choices._single_choice_options(page, root)


async def _click_single_choice_option(page: Any, option: tuple[Any, Any, str]) -> bool:
    _sync_patch_targets()
    return await _choices._click_single_choice_option(page, option)


async def _answer_single_like(page: Any, root: Any, weights: Any, option_count: int) -> bool:
    _sync_patch_targets()
    return await _choices._answer_single_like(page, root, weights, option_count)


def _positive_multiple_indexes(weights: Any, option_count: int) -> list[int]:
    return _shared_positive_multiple_indexes(weights, option_count)


async def _resolve_multi_select_limits(
    page: Any,
    root: Any,
    option_count: int,
) -> tuple[Optional[int], Optional[int]]:
    _sync_patch_targets()
    return await _choices._resolve_multi_select_limits(page, root, option_count)


def _positive_multiple_indexes_with_limits(
    weights: Any,
    option_count: int,
    *,
    min_limit: Optional[int] = None,
    max_limit: Optional[int] = None,
) -> list[int]:
    return _shared_positive_multiple_indexes_with_limits(
        weights,
        option_count,
        min_limit=min_limit,
        max_limit=max_limit,
    )


async def _answer_multiple(
    page: Any,
    root: Any,
    weights: Any,
    *,
    min_limit: Optional[int] = None,
    max_limit: Optional[int] = None,
) -> bool:
    _sync_patch_targets()
    return await _choices._answer_multiple(
        page,
        root,
        weights,
        min_limit=min_limit,
        max_limit=max_limit,
    )


async def _answer_text(
    root: Any,
    texts: Any,
    text_prob: Any,
    *,
    entry_type: str = "text",
    blank_modes: Any = None,
    blank_int_ranges: Any = None,
) -> bool:
    _sync_patch_targets()
    return await _text._answer_text(
        root,
        texts,
        text_prob,
        entry_type=entry_type,
        blank_modes=blank_modes,
        blank_int_ranges=blank_int_ranges,
    )


async def _answer_dropdown(page: Any, root: Any, weights: Any) -> bool:
    _sync_patch_targets()
    return await _text._answer_dropdown(page, root, weights)


async def _answer_scale(page: Any, root: Any, weights: Any) -> bool:
    _sync_patch_targets()
    return await _matrix._answer_scale(page, root, weights)


async def _matrix_rows(root: Any) -> list[tuple[Any, list[Any]]]:
    _sync_patch_targets()
    return await _matrix._matrix_rows(root)


async def _answer_matrix(page: Any, root: Any, weights: Any, start_index: int = 0) -> bool:
    _sync_patch_targets()
    return await _matrix._answer_matrix(page, root, weights, start_index=start_index)


async def _answer_order(page: Any, root: Any) -> bool:
    _sync_patch_targets()
    return await _matrix._answer_order(page, root)


def _normalize_positive_indices(weights: Any, option_count: int) -> list[int]:
    _sync_patch_targets()
    return _matrix._normalize_positive_indices(weights, option_count)


def build_answer_action(
    *,
    root_index: int,
    question_num: int,
    entry_type: str,
    config_index: int,
    config: Any,
    question_meta: Any,
    psycho_plan: Any = None,
) -> Optional[AnswerAction]:
    _sync_patch_targets()
    return _builders.build_answer_action(
        root_index=root_index,
        question_num=question_num,
        entry_type=entry_type,
        config_index=config_index,
        config=config,
        question_meta=question_meta,
        psycho_plan=psycho_plan,
    )


async def apply_answer_actions(page: Any, actions: list[AnswerAction]) -> BatchFillResult:
    _sync_patch_targets()
    return await _applier.apply_answer_actions(page, actions)


for _name in [
    "_resolve_forced_choice_index",
    "_single_choice_options",
    "_click_single_choice_option",
    "_answer_single_like",
    "_positive_multiple_indexes",
    "_resolve_multi_select_limits",
    "_positive_multiple_indexes_with_limits",
    "_answer_multiple",
    "_answer_text",
    "_answer_dropdown",
    "_answer_scale",
    "_matrix_rows",
    "_answer_matrix",
    "_answer_order",
    "_normalize_positive_indices",
    "build_answer_action",
    "apply_answer_actions",
]:
    _WRAPPER_OBJECTS[_name] = globals()[_name]


__all__ = [
    "AnswerAction",
    "BatchFillResult",
    "apply_answer_actions",
    "build_answer_action",
]

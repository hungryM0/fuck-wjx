"""腾讯问卷题型执行逻辑兼容出口。"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from software.core.task import ExecutionState
from software.network.browser.runtime_async import BrowserDriver
from software.providers.answering import AnswerAction, BatchFillResult
from software.providers.answering.selection import (
    format_weight_value as _shared_format_weight_value,
    resolve_selected_weight_text as _shared_resolve_selected_weight_text,
)
from software.providers.contracts import SurveyQuestionMeta

from . import answering_applier as _applier
from . import answering_batch as _batch
from . import answering_builders as _builders
from . import answering_direct as _direct

_PATCH_TARGETS = (_direct, _builders, _applier, _batch)
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


def _log_qq_matrix_row_choice(
    current: int,
    row_number: int,
    selected_index: int,
    option_texts: list[str],
    resolved_probabilities: Any,
    raw_probabilities: Any,
) -> None:
    _sync_patch_targets()
    return _direct._log_qq_matrix_row_choice(
        current,
        row_number,
        selected_index,
        option_texts,
        resolved_probabilities,
        raw_probabilities,
    )


def _format_matrix_weight_value(value: Any) -> str:
    return _shared_format_weight_value(value)


def _resolve_selected_weight_text(
    selected_index: int,
    resolved_probabilities: Any,
    raw_probabilities: Any,
) -> str:
    return _shared_resolve_selected_weight_text(
        selected_index,
        resolved_probabilities,
        raw_probabilities,
    )


async def _answer_qq_single(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any] = None,
) -> None:
    _sync_patch_targets()
    await _direct._answer_qq_single(driver, question, config_index, ctx, psycho_plan=psycho_plan)


async def _answer_qq_dropdown(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> None:
    _sync_patch_targets()
    await _direct._answer_qq_dropdown(driver, question, config_index, ctx, psycho_plan=psycho_plan)


async def _answer_qq_text(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> None:
    _sync_patch_targets()
    await _direct._answer_qq_text(driver, question, config_index, ctx)


async def _answer_qq_score_like(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> None:
    _sync_patch_targets()
    await _direct._answer_qq_score_like(driver, question, config_index, ctx, psycho_plan=psycho_plan)


async def _answer_qq_matrix(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    matrix_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> int:
    _sync_patch_targets()
    return await _direct._answer_qq_matrix(driver, question, matrix_index, ctx, psycho_plan=psycho_plan)


async def _answer_qq_multiple(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> None:
    _sync_patch_targets()
    await _direct._answer_qq_multiple(driver, question, config_index, ctx)


async def _answer_qq_matrix_star(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    matrix_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> int:
    _sync_patch_targets()
    return await _direct._answer_qq_matrix_star(
        driver,
        question,
        matrix_index,
        ctx,
        psycho_plan=psycho_plan,
    )


async def _build_qq_single_action(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any] = None,
) -> Optional[AnswerAction]:
    _sync_patch_targets()
    return await _builders._build_qq_single_action(driver, question, config_index, ctx, psycho_plan=psycho_plan)


async def _build_qq_text_action(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> Optional[AnswerAction]:
    del driver
    _sync_patch_targets()
    return await _builders._build_qq_text_action(question, config_index, ctx)


async def _build_qq_score_like_action(
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> Optional[AnswerAction]:
    _sync_patch_targets()
    return await _builders._build_qq_score_like_action(
        question,
        config_index,
        ctx,
        psycho_plan=psycho_plan,
    )


async def _build_qq_multiple_action(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> Optional[AnswerAction]:
    _sync_patch_targets()
    return await _builders._build_qq_multiple_action(driver, question, config_index, ctx)


async def _build_qq_matrix_action(
    question: SurveyQuestionMeta,
    matrix_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> Optional[AnswerAction]:
    _sync_patch_targets()
    return await _builders._build_qq_matrix_action(
        question,
        matrix_index,
        ctx,
        psycho_plan=psycho_plan,
    )


async def build_answer_action(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> Optional[AnswerAction]:
    _sync_patch_targets()
    return await _builders.build_answer_action(driver, question, ctx, psycho_plan=psycho_plan)


async def apply_answer_actions(
    driver: BrowserDriver,
    actions: Sequence[AnswerAction],
) -> BatchFillResult:
    _sync_patch_targets()
    return await _applier.apply_answer_actions(driver, actions)


def _record_answer_action(ctx: ExecutionState, action: AnswerAction) -> None:
    _sync_patch_targets()
    _batch._record_answer_action(ctx, action)


async def answer_page_batch(
    driver: BrowserDriver,
    questions: Sequence[SurveyQuestionMeta],
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> BatchFillResult:
    _sync_patch_targets()
    return await _batch.answer_page_batch(driver, questions, ctx, psycho_plan=psycho_plan)


for _name in [
    "_log_qq_matrix_row_choice",
    "_answer_qq_single",
    "_answer_qq_dropdown",
    "_answer_qq_text",
    "_answer_qq_score_like",
    "_answer_qq_matrix",
    "_answer_qq_multiple",
    "_answer_qq_matrix_star",
    "_format_matrix_weight_value",
    "_resolve_selected_weight_text",
    "_build_qq_single_action",
    "_build_qq_text_action",
    "_build_qq_score_like_action",
    "_build_qq_multiple_action",
    "_build_qq_matrix_action",
    "build_answer_action",
    "apply_answer_actions",
    "_record_answer_action",
    "answer_page_batch",
]:
    _WRAPPER_OBJECTS[_name] = globals()[_name]


__all__ = [
    "AnswerAction",
    "BatchFillResult",
    "answer_page_batch",
    "apply_answer_actions",
    "build_answer_action",
]

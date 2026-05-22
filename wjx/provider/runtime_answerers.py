"""WJX 题型执行逻辑兼容出口。"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from software.core.task import ExecutionState
from software.network.browser.runtime_async import BrowserDriver
from software.providers.answering import AnswerAction, BatchFillResult
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


async def _resolve_runtime_option_texts(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
) -> list[str]:
    _sync_patch_targets()
    return await _direct._resolve_runtime_option_texts(driver, question)


async def _answer_wjx_single(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> bool:
    _sync_patch_targets()
    return await _direct._answer_wjx_single(driver, question, config_index, ctx)


async def _answer_wjx_dropdown(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> bool:
    _sync_patch_targets()
    return await _direct._answer_wjx_dropdown(driver, question, config_index, ctx, psycho_plan=psycho_plan)


async def _answer_wjx_text(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> bool:
    _sync_patch_targets()
    return await _direct._answer_wjx_text(driver, question, config_index, ctx)


async def _answer_wjx_location(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    ctx: ExecutionState,
) -> bool:
    _sync_patch_targets()
    return await _direct._answer_wjx_location(driver, question, ctx)


async def _answer_wjx_score_like(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
    answer_type: str,
) -> bool:
    _sync_patch_targets()
    return await _direct._answer_wjx_score_like(
        driver,
        question,
        config_index,
        ctx,
        psycho_plan=psycho_plan,
        answer_type=answer_type,
    )


async def _answer_wjx_multiple(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> bool:
    _sync_patch_targets()
    return await _direct._answer_wjx_multiple(driver, question, config_index, ctx)


async def _answer_wjx_matrix(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> bool:
    _sync_patch_targets()
    return await _direct._answer_wjx_matrix(driver, question, config_index, ctx, psycho_plan=psycho_plan)


async def _answer_wjx_slider(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> bool:
    _sync_patch_targets()
    return await _direct._answer_wjx_slider(driver, question, config_index, ctx)


async def _answer_wjx_order(driver: BrowserDriver, question: SurveyQuestionMeta) -> bool:
    _sync_patch_targets()
    return await _direct._answer_wjx_order(driver, question)


async def _build_wjx_single_action(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> Optional[AnswerAction]:
    _sync_patch_targets()
    return await _builders._build_wjx_single_action(driver, question, config_index, ctx)


async def _build_wjx_dropdown_action(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> Optional[AnswerAction]:
    _sync_patch_targets()
    return await _builders._build_wjx_dropdown_action(
        driver,
        question,
        config_index,
        ctx,
        psycho_plan=psycho_plan,
    )


async def _build_wjx_text_action(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> Optional[AnswerAction]:
    _sync_patch_targets()
    return await _builders._build_wjx_text_action(driver, question, config_index, ctx)


async def _build_wjx_score_like_action(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
    answer_type: str,
) -> Optional[AnswerAction]:
    _sync_patch_targets()
    return await _builders._build_wjx_score_like_action(
        driver,
        question,
        config_index,
        ctx,
        psycho_plan=psycho_plan,
        answer_type=answer_type,
    )


async def _build_wjx_multiple_action(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> Optional[AnswerAction]:
    _sync_patch_targets()
    return await _builders._build_wjx_multiple_action(driver, question, config_index, ctx)


async def _build_wjx_matrix_action(
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> Optional[AnswerAction]:
    _sync_patch_targets()
    return await _builders._build_wjx_matrix_action(
        question,
        config_index,
        ctx,
        psycho_plan=psycho_plan,
    )


async def _build_wjx_slider_action(
    question: SurveyQuestionMeta,
    config_index: int,
    ctx: ExecutionState,
) -> Optional[AnswerAction]:
    _sync_patch_targets()
    return await _builders._build_wjx_slider_action(question, config_index, ctx)


async def _build_wjx_order_action(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
) -> AnswerAction:
    _sync_patch_targets()
    return await _builders._build_wjx_order_action(driver, question)


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


async def answer_question_by_meta(
    driver: BrowserDriver,
    question: SurveyQuestionMeta,
    ctx: ExecutionState,
    *,
    psycho_plan: Optional[Any],
) -> bool:
    _sync_patch_targets()
    return await _batch.answer_question_by_meta(driver, question, ctx, psycho_plan=psycho_plan)


for _name in [
    "_resolve_runtime_option_texts",
    "_answer_wjx_single",
    "_answer_wjx_dropdown",
    "_answer_wjx_text",
    "_answer_wjx_location",
    "_answer_wjx_score_like",
    "_answer_wjx_multiple",
    "_answer_wjx_matrix",
    "_answer_wjx_slider",
    "_answer_wjx_order",
    "_build_wjx_single_action",
    "_build_wjx_dropdown_action",
    "_build_wjx_text_action",
    "_build_wjx_score_like_action",
    "_build_wjx_multiple_action",
    "_build_wjx_matrix_action",
    "_build_wjx_slider_action",
    "_build_wjx_order_action",
    "build_answer_action",
    "apply_answer_actions",
    "_record_answer_action",
    "answer_page_batch",
    "answer_question_by_meta",
]:
    _WRAPPER_OBJECTS[_name] = globals()[_name]


__all__ = [
    "AnswerAction",
    "BatchFillResult",
    "answer_page_batch",
    "answer_question_by_meta",
    "apply_answer_actions",
    "build_answer_action",
]

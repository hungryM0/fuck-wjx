"""WJX batch answering orchestration."""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

from software.app.config import DEFAULT_FILL_TEXT
from software.core.persona.context import record_answer
from software.core.questions.distribution import record_pending_distribution_choice
from software.core.task import ExecutionState
from software.network.browser.runtime_async import BrowserDriver
from software.providers.answering import AnswerAction, BatchFillResult
from software.providers.answering.recording import record_answer_action as _record_common_answer_action
from software.providers.contracts import SurveyQuestionMeta

from .answering_applier import apply_answer_actions
from .answering_builders import build_answer_action
from .answering_direct import (
    _answer_wjx_dropdown,
    _answer_wjx_location,
    _answer_wjx_matrix,
    _answer_wjx_multiple,
    _answer_wjx_order,
    _answer_wjx_score_like,
    _answer_wjx_single,
    _answer_wjx_slider,
    _answer_wjx_text,
)
from .runtime_interactions import _prepare_question_interaction


def _record_answer_action(ctx: ExecutionState, action: AnswerAction) -> None:
    _record_common_answer_action(
        ctx,
        action,
        record_answer_fn=record_answer,
        record_pending_distribution_choice_fn=record_pending_distribution_choice,
        default_fill_text=DEFAULT_FILL_TEXT,
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
        return bool(await _answer_wjx_single(driver, question, config_index, ctx, psycho_plan=psycho_plan))
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



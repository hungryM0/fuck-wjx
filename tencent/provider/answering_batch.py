"""Tencent batch answering orchestration."""

from __future__ import annotations

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
    for question in list(questions or []):
        question_num = int(getattr(question, "num", 0) or 0)
        if question_num <= 0:
            continue
        action = await build_answer_action(driver, question, ctx, psycho_plan=psycho_plan)
        if action is None:
            skipped.append(question_num)
            continue
        actions.append(action)
    if not actions:
        return BatchFillResult(skipped=tuple(skipped))
    result = await apply_answer_actions(driver, actions)
    action_by_num = {int(action.question_num): action for action in actions}
    for question_num in result.applied:
        action = action_by_num.get(int(question_num))
        if action is not None:
            _record_answer_action(ctx, action)
    return BatchFillResult(
        applied=tuple(result.applied),
        failed=tuple(result.failed),
        skipped=tuple(skipped),
    )

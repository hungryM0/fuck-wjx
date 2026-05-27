"""HTTP 提交链路的问卷逻辑执行器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Sequence

from software.providers.answering import AnswerAction
from software.providers.contracts import LOGIC_PARSE_STATUS_COMPLETE, SurveyQuestionMeta

BuildHttpAnswerAction = Callable[[SurveyQuestionMeta], Awaitable[Optional[AnswerAction]]]
_SUPPORTED_CONDITION_MODES = {"selected", "not_selected"}


@dataclass(frozen=True)
class HttpLogicPlan:
    actions: tuple[AnswerAction, ...]
    skipped_question_nums: tuple[int, ...] = ()
    terminated_early: bool = False


def _ordered_questions(questions: Sequence[SurveyQuestionMeta]) -> list[SurveyQuestionMeta]:
    return sorted(
        [item for item in questions if item is not None and int(getattr(item, "num", 0) or 0) > 0],
        key=lambda item: (int(getattr(item, "page", 1) or 1), int(getattr(item, "num", 0) or 0)),
    )


def question_has_survey_logic(question: SurveyQuestionMeta) -> bool:
    return bool(
        getattr(question, "has_jump", False)
        or getattr(question, "has_display_condition", False)
        or getattr(question, "has_dependent_display_logic", False)
    )


def get_http_logic_fallback_reason(questions: Sequence[SurveyQuestionMeta]) -> str:
    ordered_questions = _ordered_questions(questions)
    max_question_num = max((int(getattr(item, "num", 0) or 0) for item in ordered_questions), default=0)
    for question in ordered_questions:
        question_num = int(getattr(question, "num", 0) or 0)
        if question_num <= 0 or not question_has_survey_logic(question):
            continue

        logic_status = str(getattr(question, "logic_parse_status", "") or "").strip().lower()
        if logic_status != LOGIC_PARSE_STATUS_COMPLETE:
            return f"第{question_num}题逻辑规则未完整解析"

        for condition in list(getattr(question, "display_conditions", []) or []):
            if not isinstance(condition, dict):
                return f"第{question_num}题显隐条件格式异常"
            try:
                source_question_num = int(condition.get("condition_question_num") or 0)
            except Exception:
                source_question_num = 0
            condition_mode = str(condition.get("condition_mode") or "selected").strip() or "selected"
            if source_question_num <= 0:
                return f"第{question_num}题显隐条件缺少来源题号"
            if source_question_num >= question_num:
                return f"第{question_num}题显隐条件依赖未来题目"
            if condition_mode not in _SUPPORTED_CONDITION_MODES:
                return f"第{question_num}题显隐条件模式不支持：{condition_mode}"

        for target in list(getattr(question, "controls_display_targets", []) or []):
            if not isinstance(target, dict):
                return f"第{question_num}题控制显示规则格式异常"
            try:
                target_question_num = int(target.get("target_question_num") or 0)
            except Exception:
                target_question_num = 0
            condition_mode = str(target.get("condition_mode") or "selected").strip() or "selected"
            if target_question_num <= question_num:
                return f"第{question_num}题控制显示规则存在回跳"
            if condition_mode not in _SUPPORTED_CONDITION_MODES:
                return f"第{question_num}题控制显示模式不支持：{condition_mode}"

        for rule in list(getattr(question, "jump_rules", []) or []):
            if not isinstance(rule, dict):
                return f"第{question_num}题跳题规则格式异常"
            try:
                jump_target = int(rule.get("jumpto") or 0)
            except Exception:
                jump_target = 0
            if jump_target <= question_num:
                return f"第{question_num}题跳题目标回跳到已过题目"
            if max_question_num > 0 and jump_target > max_question_num + 1:
                return f"第{question_num}题跳题目标超出问卷范围"
    return ""


def _action_selected_indices(action: AnswerAction) -> set[int]:
    if action.kind == "matrix":
        return {int(item) for item in action.matrix_indices if int(item) >= 0}
    return {int(item) for item in action.selected_indices if int(item) >= 0}


def _condition_is_met(
    action_by_question_num: dict[int, AnswerAction],
    condition: dict[str, Any],
) -> bool:
    try:
        source_question_num = int(condition.get("condition_question_num") or 0)
    except Exception:
        source_question_num = 0
    if source_question_num <= 0:
        return False

    source_action = action_by_question_num.get(source_question_num)
    if source_action is None:
        return False

    condition_mode = str(condition.get("condition_mode") or "selected").strip() or "selected"
    option_indices = condition.get("condition_option_indices")
    normalized_indices = {
        int(item)
        for item in list(option_indices or [])
        if str(item).strip() and int(item) >= 0
    } if isinstance(option_indices, list) else set()
    selected_indices = _action_selected_indices(source_action)

    if not normalized_indices:
        return condition_mode == "selected"
    if condition_mode == "selected":
        return bool(selected_indices.intersection(normalized_indices))
    if condition_mode == "not_selected":
        return bool(selected_indices.isdisjoint(normalized_indices))
    return False


def _question_is_visible(
    question: SurveyQuestionMeta,
    action_by_question_num: dict[int, AnswerAction],
) -> bool:
    conditions = list(getattr(question, "display_conditions", []) or [])
    if not conditions:
        return not bool(getattr(question, "has_display_condition", False))

    grouped_conditions: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        try:
            source_question_num = int(condition.get("condition_question_num") or 0)
        except Exception:
            source_question_num = 0
        if source_question_num <= 0:
            continue
        condition_mode = str(condition.get("condition_mode") or "selected").strip() or "selected"
        grouped_conditions.setdefault((source_question_num, condition_mode), []).append(condition)
    if not grouped_conditions:
        return not bool(getattr(question, "has_display_condition", False))

    for grouped in grouped_conditions.values():
        if not any(_condition_is_met(action_by_question_num, condition) for condition in grouped):
            return False
    return True


def _resolve_jump_target(
    question: SurveyQuestionMeta,
    action: AnswerAction,
) -> Optional[int]:
    selected_indices = _action_selected_indices(action)
    unconditional_target: Optional[int] = None
    for rule in list(getattr(question, "jump_rules", []) or []):
        if not isinstance(rule, dict):
            continue
        try:
            jump_target = int(rule.get("jumpto") or 0)
        except Exception:
            jump_target = 0
        if jump_target <= 0:
            continue
        try:
            option_index = int(rule.get("option_index") or 0)
        except Exception:
            option_index = 0
        if option_index < 0:
            if unconditional_target is None:
                unconditional_target = jump_target
            continue
        if option_index in selected_indices:
            return jump_target
    return unconditional_target


async def build_http_logic_plan(
    questions: Sequence[SurveyQuestionMeta],
    *,
    build_action: BuildHttpAnswerAction,
    respect_jump_logic: bool = True,
) -> HttpLogicPlan:
    ordered_questions = _ordered_questions(questions)
    fallback_reason = get_http_logic_fallback_reason(ordered_questions)
    if fallback_reason:
        raise RuntimeError(f"{fallback_reason}，暂不支持纯 HTTP 提交")

    max_question_num = max((int(getattr(item, "num", 0) or 0) for item in ordered_questions), default=0)
    action_by_question_num: dict[int, AnswerAction] = {}
    actions: list[AnswerAction] = []
    skipped_question_nums: list[int] = []
    jump_target_num: Optional[int] = None

    for question in ordered_questions:
        question_num = int(getattr(question, "num", 0) or 0)
        if question_num <= 0:
            continue

        if jump_target_num is not None:
            if question_num < jump_target_num:
                skipped_question_nums.append(question_num)
                continue
            jump_target_num = None

        if not _question_is_visible(question, action_by_question_num):
            skipped_question_nums.append(question_num)
            continue

        action = await build_action(question)
        if action is None:
            raise RuntimeError(f"第{question_num}题暂不支持纯 HTTP 提交")
        action_by_question_num[question_num] = action
        actions.append(action)

        if respect_jump_logic:
            jump_target = _resolve_jump_target(question, action)
            if jump_target is None:
                continue
            if jump_target > max_question_num:
                return HttpLogicPlan(
                    actions=tuple(actions),
                    skipped_question_nums=tuple(skipped_question_nums),
                    terminated_early=True,
                )
            jump_target_num = jump_target

    return HttpLogicPlan(
        actions=tuple(actions),
        skipped_question_nums=tuple(skipped_question_nums),
        terminated_early=False,
    )


__all__ = [
    "HttpLogicPlan",
    "build_http_logic_plan",
    "get_http_logic_fallback_reason",
    "question_has_survey_logic",
]

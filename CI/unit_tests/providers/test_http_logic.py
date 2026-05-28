from __future__ import annotations

import pytest

from software.providers.answering import AnswerAction
from software.providers.contracts import (
    LOGIC_PARSE_STATUS_UNKNOWN,
    SurveyQuestionMeta,
)
from software.providers.http_logic import build_http_logic_plan, get_http_logic_fallback_reason


async def _choice_action(question: SurveyQuestionMeta):
    return AnswerAction(
        question_num=question.num,
        kind="choice",
        selected_indices=(0,),
        record_type="single",
    )


def _question(num: int, **kwargs) -> SurveyQuestionMeta:
    return SurveyQuestionMeta(num=num, title=f"Q{num}", type_code="3", options=2, **kwargs)


def test_http_logic_rejects_unknown_unparsed_jump_rules() -> None:
    question = _question(
        1,
        has_jump=True,
        logic_parse_status=LOGIC_PARSE_STATUS_UNKNOWN,
        jump_rules=[],
    )

    assert get_http_logic_fallback_reason([question]) == "第1题逻辑规则未完整解析"


def test_http_logic_rejects_future_display_dependency() -> None:
    question = _question(
        2,
        has_display_condition=True,
        display_conditions=[
            {
                "condition_question_num": 3,
                "condition_mode": "selected",
                "condition_option_indices": [0],
            }
        ],
    )

    assert get_http_logic_fallback_reason([question]) == "第2题显隐条件依赖未来题目"


def test_http_logic_rejects_jump_backwards() -> None:
    question = _question(
        3,
        has_jump=True,
        jump_rules=[{"option_index": 0, "jumpto": 2}],
    )

    assert get_http_logic_fallback_reason([question]) == "第3题跳题目标回跳到已过题目"


def test_http_logic_allows_terminate_jump_marker() -> None:
    question = _question(
        1,
        has_jump=True,
        jump_rules=[{"option_index": 1, "jumpto": 1, "terminates_survey": True}],
    )

    assert get_http_logic_fallback_reason([question]) == ""


@pytest.mark.asyncio
async def test_http_logic_skips_hidden_questions() -> None:
    questions = [
        _question(1),
        _question(
            2,
            has_display_condition=True,
            display_conditions=[
                {
                    "condition_question_num": 1,
                    "condition_mode": "not_selected",
                    "condition_option_indices": [0],
                }
            ],
        ),
        _question(3),
    ]

    plan = await build_http_logic_plan(questions, build_action=_choice_action)

    assert [action.question_num for action in plan.actions] == [1, 3]
    assert plan.skipped_question_nums == (2,)
    assert plan.terminated_early is False


@pytest.mark.asyncio
async def test_http_logic_jump_can_terminate_early() -> None:
    questions = [
        _question(1, has_jump=True, jump_rules=[{"option_index": 0, "jumpto": 4}]),
        _question(2),
        _question(3),
    ]

    plan = await build_http_logic_plan(questions, build_action=_choice_action)

    assert [action.question_num for action in plan.actions] == [1]
    assert plan.terminated_early is True


@pytest.mark.asyncio
async def test_http_logic_terminate_marker_can_end_on_submit_page() -> None:
    async def _second_option_action(question: SurveyQuestionMeta):
        return AnswerAction(
            question_num=question.num,
            kind="choice",
            selected_indices=(1,),
            record_type="single",
        )

    questions = [
        _question(1, has_jump=True, jump_rules=[{"option_index": 1, "jumpto": 1, "terminates_survey": True}]),
        _question(2),
    ]

    plan = await build_http_logic_plan(questions, build_action=_second_option_action)

    assert [action.question_num for action in plan.actions] == [1]
    assert plan.terminated_early is True

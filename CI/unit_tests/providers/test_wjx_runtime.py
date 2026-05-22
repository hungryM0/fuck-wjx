from __future__ import annotations

from types import SimpleNamespace

import pytest

from software.core.task import ExecutionConfig, ExecutionState
from software.providers.contracts import SurveyQuestionMeta
from wjx.provider import runtime


class _FakeDriver:
    def __init__(self) -> None:
        self.browser_name = "edge"
        self.session_id = "test-session"
        self.browser_pid = None
        self.browser_pids: set[int] = set()


async def _return_async(value):
    return value


def _make_state(
    questions_metadata: dict[int, SurveyQuestionMeta],
    question_config_index_map: dict[int, tuple[str, int]],
) -> ExecutionState:
    config = ExecutionConfig(survey_provider="wjx")
    config.questions_metadata = dict(questions_metadata)
    config.question_config_index_map = dict(question_config_index_map)
    return ExecutionState(config=config)


class WjxRuntimeTests:
    def test_group_questions_by_page_sorts_and_filters_invalid_metadata(self) -> None:
        ctx = _make_state(
            {
                2: SurveyQuestionMeta(num=2, title="Q2", type_code="3", page=2),
                1: SurveyQuestionMeta(num=1, title="Q1", type_code="3", page=1),
                3: SurveyQuestionMeta(num=3, title="Q3", type_code="3", page=2),
            },
            {},
        )

        groups = runtime._group_questions_by_page(ctx)

        assert [[question.num for question in group] for group in groups] == [[1], [2, 3]]

    @pytest.mark.asyncio
    async def test_refill_required_questions_on_current_page_only_refills_visible_questions(self, monkeypatch) -> None:
        driver = _FakeDriver()
        ctx = _make_state(
            {
                1: SurveyQuestionMeta(num=1, title="Q1", type_code="3", page=1, required=True),
                2: SurveyQuestionMeta(num=2, title="Q2", type_code="3", page=1, required=True),
            },
            {
                1: ("single", 0),
                2: ("single", 1),
            },
        )
        calls: list[int] = []
        async def _snapshot(_driver):
            return {1: {"visible": True, "type": "3", "text": "Q1"}, 2: {"visible": False, "type": "3", "text": "Q2"}}

        async def _visible(_driver, question_num):
            return question_num == 1

        monkeypatch.setattr(runtime, "_collect_visible_question_snapshot", _snapshot)
        monkeypatch.setattr(runtime, "_is_question_visible", _visible)
        async def _answer(_driver, question, _ctx, *, psycho_plan):
            assert psycho_plan == "plan"
            calls.append(int(question.num))
            return int(question.num) == 1

        monkeypatch.setattr(runtime, "answer_question_by_meta", _answer)

        filled = await runtime.refill_required_questions_on_current_page(
            driver,
            ctx,
            question_numbers=[1, 2, 1],
            thread_name="Worker-1",
            psycho_plan="plan",
        )

        assert filled == 1
        assert calls == [1]

    @pytest.mark.asyncio
    async def test_brush_blocks_unsupported_questions_before_runtime_starts(self) -> None:
        ctx = _make_state(
            {1: SurveyQuestionMeta(num=1, title="Q1", type_code="3", page=1, unsupported=True)},
            {1: ("single", 0)},
        )

        with pytest.raises(RuntimeError, match="未支持题型"):
            await runtime.brush(_FakeDriver(), ctx, thread_name="Worker-1")

    @pytest.mark.asyncio
    async def test_brush_answers_visible_questions_and_submits(self, monkeypatch) -> None:
        driver = _FakeDriver()
        q1 = SurveyQuestionMeta(num=1, title="Q1", type_code="3", page=1)
        q2 = SurveyQuestionMeta(num=2, title="Q2", type_code="1", page=1)
        ctx = _make_state(
            {1: q1, 2: q2},
            {1: ("single", 0), 2: ("text", 0)},
        )
        answered: list[int] = []
        submitted: list[str] = []
        async def _gate(*_args, **_kwargs):
            return True

        async def _snapshot(_driver, _questions):
            return {
                1: {"visible": True, "type": "3", "text": "Q1"},
                2: {"visible": True, "type": "1", "text": "Q2"},
            }

        monkeypatch.setattr(runtime, "_prepare_runtime_entry_gate", _gate)
        monkeypatch.setattr(runtime, "_resolve_page_snapshot", _snapshot)
        async def _answer(_driver, question, _ctx, *, psycho_plan):
            assert psycho_plan == "plan"
            answered.append(int(question.num))
            return None

        monkeypatch.setattr(runtime, "answer_question_by_meta", _answer)
        async def _finalize(*_args, **_kwargs):
            return True

        monkeypatch.setattr(runtime, "_finalize_page", _finalize)
        async def _submit(_driver, *, ctx=None, stop_signal=None):
            del stop_signal
            submitted.append(ctx.config.survey_provider if ctx else "")

        monkeypatch.setattr(runtime, "submit", _submit)

        result = await runtime.brush(driver, ctx, thread_name="Worker-1", psycho_plan="plan")

        assert result is True
        assert answered == [1, 2]
        assert submitted == ["wjx"]
        assert runtime.get_wjx_runtime_state(driver).page_number == 1

    @pytest.mark.asyncio
    async def test_brush_no_submit_test_answers_without_submit(self, monkeypatch) -> None:
        driver = _FakeDriver()
        q1 = SurveyQuestionMeta(num=1, title="Q1", type_code="3", page=1)
        ctx = _make_state({1: q1}, {1: ("single", 0)})
        ctx.config.submit_enabled = False
        status_updates: list[tuple[str, bool]] = []
        ctx.update_thread_status = lambda _thread, text, *, running: status_updates.append((text, running))
        submitted: list[str] = []

        async def _gate(*_args, **_kwargs):
            return True

        async def _snapshot(*_args, **_kwargs):
            return {1: {"visible": True, "type": "3", "text": "Q1"}}

        async def _answer(*_args, **_kwargs):
            return None

        async def _finalize(*_args, **_kwargs):
            return True

        async def _submit(*_args, **_kwargs):
            submitted.append("submit")

        monkeypatch.setattr(runtime, "_prepare_runtime_entry_gate", _gate)
        monkeypatch.setattr(
            runtime,
            "_resolve_page_snapshot",
            _snapshot,
        )
        monkeypatch.setattr(runtime, "answer_question_by_meta", _answer)
        monkeypatch.setattr(runtime, "_finalize_page", _finalize)
        monkeypatch.setattr(runtime, "submit", _submit)

        result = await runtime.brush(driver, ctx, thread_name="Worker-1")

        assert result is True
        assert submitted == []
        assert ("单测完成", False) in status_updates

    @pytest.mark.asyncio
    async def test_brush_skips_hidden_questions_and_updates_abort_status(self, monkeypatch) -> None:
        driver = _FakeDriver()
        q1 = SurveyQuestionMeta(num=1, title="Q1", type_code="3", page=1)
        ctx = _make_state({1: q1}, {1: ("single", 0)})
        stop_signal = SimpleNamespace(is_set=lambda: True)
        calls: list[str] = []
        monkeypatch.setattr(runtime, "_update_abort_status", lambda _ctx, name: calls.append(name))

        result = await runtime.brush(driver, ctx, stop_signal=stop_signal, thread_name="Worker-9")

        assert result is False
        assert calls == ["Worker-9"]

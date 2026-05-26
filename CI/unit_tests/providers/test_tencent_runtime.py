from __future__ import annotations

import threading

import pytest

from software.providers.contracts import SurveyQuestionMeta
from tencent.provider import runtime
from tencent.provider import runtime_answerers


def _meta(
    num: int,
    *,
    page: int = 1,
    provider_question_id: str | None = None,
    provider_type: str = "",
    unsupported: bool = False,
) -> SurveyQuestionMeta:
    return SurveyQuestionMeta(
        num=num,
        title=f"Q{num}",
        page=page,
        provider="tencent",
        type_code="single",
        provider_question_id=provider_question_id or f"q{num}",
        provider_page_id=f"p{page}",
        provider_type=provider_type,
        unsupported=unsupported,
    )


def _async_return(value=None):
    async def _runner(*_args, **_kwargs):
        return value

    return _runner


def _async_append(calls: list[object], value: object, *, result=None):
    async def _runner(*_args, **_kwargs):
        calls.append(value)
        return result

    return _runner


class TencentRuntimeTests:
    @pytest.mark.asyncio
    async def test_brush_qq_blocks_unsupported_question_before_runtime_starts(self, make_runtime_state) -> None:
        ctx = make_runtime_state({1: _meta(1, unsupported=True)}, {1: ("single", 0)})
        with pytest.raises(RuntimeError, match="未支持题型"):
            await runtime.brush_qq(
                object(),
                object(),
                ctx,
                stop_signal=threading.Event(),
                thread_name="Worker-1",
                psycho_plan=None,
            )

    @pytest.mark.asyncio
    async def test_brush_qq_routes_matrix_star_to_star_handler(self, make_runtime_state, patch_attrs) -> None:
        question = _meta(1, provider_type="matrix_star")
        ctx = make_runtime_state({1: question}, {1: ("matrix", 0)})
        calls: list[str] = []
        patch_attrs(
            (runtime, "_wait_for_question_visible", _async_return(True)),
            (runtime, "_is_question_visible", _async_return(True)),
            (runtime, "_human_scroll_after_question", _async_return(None)),
            (runtime, "dismiss_resume_dialog_if_present", _async_return(None)),
            (runtime, "_is_headless_mode", lambda _ctx: True),
            (runtime, "HEADLESS_PAGE_BUFFER_DELAY", 0.0),
            (runtime, "_answer_question_by_meta", _async_append(calls, "star", result=True)),
            (runtime, "submit", _async_append(calls, "submit")),
        )

        result = await runtime.brush_qq(
            object(),
            object(),
            ctx,
            stop_signal=threading.Event(),
            thread_name="Worker-1",
            psycho_plan=None,
        )

        assert result
        assert calls == ["star", "submit"]

    @pytest.mark.asyncio
    async def test_matrix_star_falls_back_to_plain_matrix_cell(self, make_runtime_state, patch_attrs) -> None:
        question = _meta(1, provider_type="matrix_star", provider_question_id="matrix-star-q1")
        ctx = make_runtime_state(
            {1: question},
            {1: ("matrix", 0)},
            config_defaults={
                "matrix_prob": [-1],
                "question_dimension_map": {},
            },
        )
        calls: list[object] = []

        async def _star_click(*_args, **_kwargs):
            calls.append("star")
            return False

        async def _plain_click(*_args, **_kwargs):
            calls.append(("plain", _args[2], _args[3]))
            return True

        patch_attrs(
            (runtime, "_wait_for_question_visible", _async_return(True)),
            (runtime, "_is_question_visible", _async_return(True)),
            (runtime, "_human_scroll_after_question", _async_return(None)),
            (runtime, "dismiss_resume_dialog_if_present", _async_return(None)),
            (runtime, "_is_headless_mode", lambda _ctx: True),
            (runtime, "HEADLESS_PAGE_BUFFER_DELAY", 0.0),
            (runtime_answerers, "_click_star_cell", _star_click),
            (runtime_answerers, "_click_matrix_cell", _plain_click),
            (runtime, "submit", _async_append(calls, "submit")),
        )

        result = await runtime.brush_qq(
            object(),
            object(),
            ctx,
            stop_signal=threading.Event(),
            thread_name="Worker-1",
            psycho_plan=None,
        )

        assert result
        assert "star" in calls
        assert any(call[0] == "plain" for call in calls if isinstance(call, tuple))
        assert calls[-1] == "submit"

    @pytest.mark.asyncio
    async def test_brush_qq_walks_pages_then_submits(self, make_runtime_state, patch_attrs) -> None:
        ctx = make_runtime_state(
            {
                1: _meta(1, page=1, provider_question_id="page1-q1"),
                2: _meta(2, page=2, provider_question_id="page2-q1"),
            },
            {1: ("single", 0), 2: ("text", 0)},
        )
        calls: list[object] = []

        async def _wait_transition(*_args, **_kwargs):
            calls.append(("transition", _args[1], _args[2]))
            return None

        patch_attrs(
            (runtime, "_wait_for_question_visible", _async_return(True)),
            (runtime, "_is_question_visible", _async_return(True)),
            (runtime, "_human_scroll_after_question", _async_append(calls, "scroll")),
            (runtime, "dismiss_resume_dialog_if_present", _async_return(None)),
            (runtime, "_is_headless_mode", lambda _ctx: True),
            (runtime, "HEADLESS_PAGE_BUFFER_DELAY", 0.0),
            (runtime, "HEADLESS_PAGE_CLICK_DELAY", 0.0),
            (runtime, "_answer_qq_single", _async_append(calls, "single")),
            (runtime, "_answer_qq_text", _async_append(calls, "text")),
            (runtime, "_click_next_page_button", _async_append(calls, "next", result=True)),
            (runtime, "_wait_for_page_transition", _wait_transition),
            (runtime, "submit", _async_append(calls, "submit")),
        )

        result = await runtime.brush_qq(
            object(),
            object(),
            ctx,
            stop_signal=threading.Event(),
            thread_name="Worker-1",
            psycho_plan=None,
        )

        assert result
        assert "single" in calls
        assert "text" in calls
        assert "next" in calls
        assert ("transition", "page1-q1", "page2-q1") in calls
        assert calls[-1] == "submit"
        assert ("提交中", True) in ctx.status_updates

    @pytest.mark.asyncio
    async def test_brush_qq_uses_description_page_anchor_when_transitioning(self, make_runtime_state, patch_attrs) -> None:
        ctx = make_runtime_state(
            {
                1: SurveyQuestionMeta(
                    num=1,
                    title="说明页",
                    page=1,
                    provider="qq",
                    type_code="0",
                    provider_question_id="desc-page-1",
                    is_description=True,
                ),
                2: _meta(2, page=2, provider_question_id="page2-q1"),
            },
            {2: ("single", 0)},
        )
        calls: list[object] = []

        async def _wait_snapshot(_driver, question_ids, *, timeout_ms, require_any_visible):
            calls.append(("snapshot", list(question_ids), timeout_ms, require_any_visible))
            return {}

        async def _wait_transition(*_args, **_kwargs):
            calls.append(("transition", _args[1], _args[2]))
            return None

        patch_attrs(
            (runtime, "_supports_page_snapshot", _async_return(True)),
            (runtime, "_wait_for_question_visibility_map", _wait_snapshot),
            (runtime, "_wait_for_question_visible", _async_return(True)),
            (runtime, "_is_question_visible", _async_return(True)),
            (runtime, "_human_scroll_after_question", _async_append(calls, "scroll")),
            (runtime, "dismiss_resume_dialog_if_present", _async_return(None)),
            (runtime, "_is_headless_mode", lambda _ctx: True),
            (runtime, "HEADLESS_PAGE_BUFFER_DELAY", 0.0),
            (runtime, "HEADLESS_PAGE_CLICK_DELAY", 0.0),
            (runtime, "has_configured_answer_duration", lambda _value: False),
            (runtime, "simulate_answer_duration_delay", _async_return(False)),
            (runtime, "_answer_qq_single", _async_append(calls, "single")),
            (runtime, "_click_next_page_button", _async_append(calls, "next", result=True)),
            (runtime, "_wait_for_page_transition", _wait_transition),
            (runtime, "submit", _async_append(calls, "submit")),
        )

        result = await runtime.brush_qq(
            object(),
            object(),
            ctx,
            stop_signal=threading.Event(),
            thread_name="Worker-1",
            psycho_plan=None,
        )

        assert result
        assert ("transition", "desc-page-1", "page2-q1") in calls

    @pytest.mark.asyncio
    async def test_brush_qq_no_submit_test_answers_without_submit(self, make_runtime_state, patch_attrs) -> None:
        ctx = make_runtime_state({1: _meta(1)}, {1: ("single", 0)})
        ctx.config.submit_enabled = False
        calls: list[object] = []
        patch_attrs(
            (runtime, "_wait_for_question_visible", _async_return(True)),
            (runtime, "_is_question_visible", _async_return(True)),
            (runtime, "_human_scroll_after_question", _async_return(None)),
            (runtime, "dismiss_resume_dialog_if_present", _async_return(None)),
            (runtime, "_is_headless_mode", lambda _ctx: True),
            (runtime, "HEADLESS_PAGE_BUFFER_DELAY", 0.0),
            (runtime, "_answer_question_by_meta", _async_append(calls, "answer", result=True)),
            (runtime, "submit", _async_append(calls, "submit")),
        )

        result = await runtime.brush_qq(
            object(),
            object(),
            ctx,
            stop_signal=threading.Event(),
            thread_name="Worker-1",
            psycho_plan=None,
        )

        assert result
        assert calls == ["answer"]
        assert ("单测完成", False) in ctx.status_updates

    @pytest.mark.asyncio
    async def test_answer_question_by_meta_returns_false_when_mapping_missing(self, make_runtime_state) -> None:
        ctx = make_runtime_state({}, {})
        question = _meta(9, provider_question_id="q9")

        assert not await runtime._answer_question_by_meta(object(), question, ctx, psycho_plan=None)

    @pytest.mark.asyncio
    async def test_brush_qq_prefers_page_snapshot_over_per_question_wait(self, make_runtime_state, patch_attrs) -> None:
        ctx = make_runtime_state(
            {
                1: _meta(1, page=1, provider_question_id="page1-q1"),
                2: _meta(2, page=1, provider_question_id="page1-q2"),
            },
            {1: ("single", 0), 2: ("text", 0)},
        )
        calls: list[object] = []
        patch_attrs(
            (runtime, "_supports_page_snapshot", _async_return(True)),
            (
                runtime,
                "_wait_for_question_visibility_map",
                _async_return(
                    {
                        "page1-q1": {"attached": True, "visible": True},
                        "page1-q2": {"attached": True, "visible": True},
                    }
                ),
            ),
            (runtime, "_wait_for_question_visible", _async_append(calls, "fallback-wait", result=True)),
            (runtime, "_human_scroll_after_question", _async_return(None)),
            (runtime, "dismiss_resume_dialog_if_present", _async_return(None)),
            (runtime, "_is_headless_mode", lambda _ctx: True),
            (runtime, "HEADLESS_PAGE_BUFFER_DELAY", 0.0),
            (runtime, "_answer_question_by_meta", _async_append(calls, "answer", result=True)),
            (runtime, "submit", _async_append(calls, "submit")),
        )

        result = await runtime.brush_qq(
            object(),
            object(),
            ctx,
            stop_signal=threading.Event(),
            thread_name="Worker-1",
            psycho_plan=None,
        )

        assert result
        assert "fallback-wait" not in calls
        assert calls == ["answer", "answer", "submit"]

    @pytest.mark.asyncio
    async def test_brush_qq_static_page_still_uses_sequential_answering_for_visible_questions(self, make_runtime_state, patch_attrs) -> None:
        class _FakePage:
            async def evaluate(self, *_args, **_kwargs):
                return {"applied": [1, 2], "failed": []}

        class _FakeDriver:
            async def page(self):
                return _FakePage()

        ctx = make_runtime_state(
            {
                1: _meta(1, page=1, provider_question_id="page1-q1"),
                2: _meta(2, page=1, provider_question_id="page1-q2"),
            },
            {1: ("scale", 0), 2: ("matrix", 1)},
        )
        calls: list[str] = []

        async def _answer_question_by_meta(_driver, question, _ctx, *, psycho_plan):
            assert psycho_plan == "plan"
            calls.append(str(question.provider_question_id))
            return True

        patch_attrs(
            (runtime, "_supports_page_snapshot", _async_return(True)),
            (
                runtime,
                "_wait_for_question_visibility_map",
                _async_return(
                    {
                        "page1-q1": {"attached": True, "visible": True},
                        "page1-q2": {"attached": True, "visible": True},
                    }
                ),
            ),
            (runtime, "_wait_for_question_visible", _async_return(True)),
            (runtime, "_human_scroll_after_question", _async_return(None)),
            (runtime, "dismiss_resume_dialog_if_present", _async_return(None)),
            (runtime, "_is_headless_mode", lambda _ctx: True),
            (runtime, "HEADLESS_PAGE_BUFFER_DELAY", 0.0),
            (runtime, "_answer_question_by_meta", _answer_question_by_meta),
            (runtime, "submit", _async_append(calls, "submit")),
        )

        result = await runtime.brush_qq(
            _FakeDriver(),
            object(),
            ctx,
            stop_signal=threading.Event(),
            thread_name="Worker-1",
            psycho_plan="plan",
        )

        assert result
        assert calls == ["page1-q1", "page1-q2", "submit"]

    @pytest.mark.asyncio
    async def test_brush_qq_skips_final_duration_wait_even_when_configured(self, make_runtime_state, patch_attrs) -> None:
        ctx = make_runtime_state({1: _meta(1)}, {1: ("single", 0)})
        ctx.config.answer_duration_range_seconds = (300, 300)
        calls: list[str] = []
        patch_attrs(
            (runtime, "_wait_for_question_visible", _async_return(True)),
            (runtime, "_is_question_visible", _async_return(True)),
            (runtime, "_human_scroll_after_question", _async_return(None)),
            (runtime, "dismiss_resume_dialog_if_present", _async_return(None)),
            (runtime, "_is_headless_mode", lambda _ctx: True),
            (runtime, "HEADLESS_PAGE_BUFFER_DELAY", 0.0),
            (runtime, "_answer_question_by_meta", _async_append(calls, "single", result=True)),
            (runtime, "submit", _async_append(calls, "submit")),
        )

        result = await runtime.brush_qq(
            object(),
            object(),
            ctx,
            stop_signal=threading.Event(),
            thread_name="Worker-1",
            psycho_plan=None,
        )

        assert result
        assert calls == ["single", "submit"]
        assert ("等待时长中", True) not in ctx.status_updates

    @pytest.mark.asyncio
    async def test_brush_qq_skips_question_when_snapshot_says_not_visible_and_no_mapping(self, make_runtime_state, patch_attrs) -> None:
        ctx = make_runtime_state(
            {1: _meta(1, provider_question_id="page1-q1"), 2: _meta(2, provider_question_id="page1-q2")},
            {1: ("single", 0)},
        )
        calls: list[object] = []
        patch_attrs(
            (runtime, "_supports_page_snapshot", _async_return(True)),
            (
                runtime,
                "_wait_for_question_visibility_map",
                _async_return({"page1-q1": {"visible": True}, "page1-q2": {"visible": False}}),
            ),
            (runtime, "_wait_for_question_visible", _async_append(calls, "fallback-visible", result=True)),
            (runtime, "_is_question_visible", _async_return(True)),
            (runtime, "_human_scroll_after_question", _async_return(None)),
            (runtime, "dismiss_resume_dialog_if_present", _async_return(None)),
            (runtime, "_is_headless_mode", lambda _ctx: True),
            (runtime, "HEADLESS_PAGE_BUFFER_DELAY", 0.0),
            (runtime, "_answer_question_by_meta", _async_append(calls, "single", result=True)),
            (runtime, "submit", _async_append(calls, "submit")),
        )

        result = await runtime.brush_qq(
            object(),
            object(),
            ctx,
            stop_signal=threading.Event(),
            thread_name="Worker-1",
            psycho_plan=None,
        )

        assert result
        assert calls == ["single", "submit"]

    @pytest.mark.asyncio
    async def test_brush_qq_uses_fallback_visibility_and_routes_multiple_dropdown_score_matrix(self, make_runtime_state, patch_attrs) -> None:
        ctx = make_runtime_state(
            {
                1: _meta(1, provider_question_id="q1"),
                2: _meta(2, provider_question_id="q2"),
                3: _meta(3, provider_question_id="q3"),
                4: _meta(4, provider_question_id="q4", provider_type="matrix"),
            },
            {1: ("multiple", 0), 2: ("dropdown", 1), 3: ("score", 2), 4: ("matrix", 3)},
        )
        calls: list[str] = []

        async def _answer_question_by_meta(_driver, question, _ctx, *, psycho_plan):
            assert psycho_plan == "plan"
            calls.append(str(question.provider_question_id))
            return True

        patch_attrs(
            (runtime, "_supports_page_snapshot", _async_return(False)),
            (runtime, "_wait_for_question_visible", _async_return(True)),
            (runtime, "_human_scroll_after_question", _async_return(None)),
            (runtime, "dismiss_resume_dialog_if_present", _async_return(None)),
            (runtime, "_is_headless_mode", lambda _ctx: True),
            (runtime, "HEADLESS_PAGE_BUFFER_DELAY", 0.0),
            (runtime, "_answer_question_by_meta", _answer_question_by_meta),
            (runtime, "submit", _async_append(calls, "submit")),
        )

        result = await runtime.brush_qq(
            object(),
            object(),
            ctx,
            stop_signal=threading.Event(),
            thread_name="Worker-1",
            psycho_plan="plan",
        )

        assert result
        assert calls == ["q1", "q2", "q3", "q4", "submit"]

    @pytest.mark.asyncio
    async def test_brush_qq_aborts_before_question_and_on_page_delay_and_raises_when_next_missing(self, make_runtime_state, patch_attrs) -> None:
        ctx = make_runtime_state(
            {
                1: _meta(1, page=1, provider_question_id="page1-q1"),
                2: _meta(2, page=2, provider_question_id="page2-q1"),
            },
            {1: ("single", 0), 2: ("single", 1)},
        )
        stop_signal = threading.Event()
        stop_signal.set()
        patch_attrs(
            (runtime, "_wait_for_question_visible", _async_return(True)),
            (runtime, "_human_scroll_after_question", _async_return(None)),
            (runtime, "dismiss_resume_dialog_if_present", _async_return(None)),
            (runtime, "_is_headless_mode", lambda _ctx: True),
        )
        assert not await runtime.brush_qq(
            object(),
            object(),
            ctx,
            stop_signal=stop_signal,
            thread_name="Worker-1",
            psycho_plan=None,
        )
        assert ctx.status_updates[-1] == ("已中断", False)

        ctx2 = make_runtime_state({1: _meta(1)}, {1: ("single", 0)})
        wait_stop = threading.Event()
        setattr(wait_stop, "wait", lambda _timeout: True)
        patch_attrs(
            (runtime, "_wait_for_question_visible", _async_return(True)),
            (runtime, "_human_scroll_after_question", _async_return(None)),
            (runtime, "dismiss_resume_dialog_if_present", _async_return(None)),
            (runtime, "_is_headless_mode", lambda _ctx: True),
            (runtime, "HEADLESS_PAGE_BUFFER_DELAY", 0.1),
            (runtime, "_answer_question_by_meta", _async_return(True)),
        )
        assert not await runtime.brush_qq(
            object(),
            object(),
            ctx2,
            stop_signal=wait_stop,
            thread_name="Worker-2",
            psycho_plan=None,
        )
        assert ctx2.status_updates[-1] == ("已中断", False)

        ctx3 = make_runtime_state(
            {
                1: _meta(1, page=1, provider_question_id="page1-q1"),
                2: _meta(2, page=2, provider_question_id="page2-q1"),
            },
            {1: ("single", 0), 2: ("single", 1)},
        )
        patch_attrs(
            (runtime, "_wait_for_question_visible", _async_return(True)),
            (runtime, "_human_scroll_after_question", _async_return(None)),
            (runtime, "dismiss_resume_dialog_if_present", _async_return(None)),
            (runtime, "_is_headless_mode", lambda _ctx: True),
            (runtime, "HEADLESS_PAGE_BUFFER_DELAY", 0.0),
            (runtime, "_answer_question_by_meta", _async_return(True)),
            (runtime, "_click_next_page_button", _async_return(False)),
        )
        with pytest.raises(Exception, match="下一页按钮未找到"):
            await runtime.brush_qq(
                object(),
                object(),
                ctx3,
                stop_signal=threading.Event(),
                thread_name="Worker-3",
                psycho_plan=None,
            )

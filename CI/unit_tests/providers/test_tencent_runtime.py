from __future__ import annotations

import threading
import unittest
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace

from software.providers.contracts import SurveyQuestionMeta
from tencent.provider import runtime


@contextmanager
def _patched_attr(target, name: str, value):
    original = getattr(target, name)
    setattr(target, name, value)
    try:
        yield
    finally:
        setattr(target, name, original)


class _FakeState:
    def __init__(self, questions_metadata, question_config_index_map=None):
        self.config = SimpleNamespace(
            questions_metadata=dict(questions_metadata or {}),
            question_config_index_map=dict(question_config_index_map or {}),
            answer_duration_range_seconds=[0, 0],
        )
        self.stop_event = threading.Event()
        self.step_updates: list[tuple[int, int, str, bool]] = []
        self.status_updates: list[tuple[str, bool]] = []

    def update_thread_step(self, _thread_name: str, current: int, total: int, *, status_text: str, running: bool) -> None:
        self.step_updates.append((current, total, status_text, running))

    def update_thread_status(self, _thread_name: str, status_text: str, *, running: bool) -> None:
        self.status_updates.append((status_text, running))


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


class TencentRuntimeTests(unittest.TestCase):
    def test_brush_qq_blocks_unsupported_question_before_runtime_starts(self) -> None:
        ctx = _FakeState({1: _meta(1, unsupported=True)}, {1: ("single", 0)})

        with self.assertRaisesRegex(RuntimeError, "未支持题型"):
            runtime.brush_qq(
                object(),
                object(),
                ctx,
                stop_signal=threading.Event(),
                thread_name="Worker-1",
                psycho_plan=None,
            )

    def test_brush_qq_routes_matrix_star_to_star_handler(self) -> None:
        question = _meta(1, provider_type="matrix_star")
        ctx = _FakeState({1: question}, {1: ("matrix", 0)})
        calls: list[str] = []

        with ExitStack() as stack:
            stack.enter_context(_patched_attr(runtime, "_wait_for_question_visible", lambda *_args, **_kwargs: True))
            stack.enter_context(_patched_attr(runtime, "_is_question_visible", lambda *_args, **_kwargs: True))
            stack.enter_context(_patched_attr(runtime, "_human_scroll_after_question", lambda *_args, **_kwargs: None))
            stack.enter_context(_patched_attr(runtime, "dismiss_resume_dialog_if_present", lambda *_args, **_kwargs: None))
            stack.enter_context(_patched_attr(runtime, "_is_headless_mode", lambda _ctx: True))
            stack.enter_context(_patched_attr(runtime, "HEADLESS_PAGE_BUFFER_DELAY", 0.0))
            stack.enter_context(_patched_attr(runtime, "has_configured_answer_duration", lambda _value: False))
            stack.enter_context(_patched_attr(runtime, "simulate_answer_duration_delay", lambda *_args, **_kwargs: False))
            stack.enter_context(_patched_attr(runtime, "_answer_qq_matrix_star", lambda *_args, **_kwargs: calls.append("star")))
            stack.enter_context(_patched_attr(runtime, "_answer_qq_matrix", lambda *_args, **_kwargs: calls.append("plain")))
            stack.enter_context(_patched_attr(runtime, "submit", lambda *_args, **_kwargs: calls.append("submit")))
            result = runtime.brush_qq(
                object(),
                object(),
                ctx,
                stop_signal=threading.Event(),
                thread_name="Worker-1",
                psycho_plan=None,
            )

        self.assertTrue(result)
        self.assertEqual(calls, ["star", "submit"])

    def test_brush_qq_walks_pages_then_submits(self) -> None:
        ctx = _FakeState(
            {
                1: _meta(1, page=1, provider_question_id="page1-q1"),
                2: _meta(2, page=2, provider_question_id="page2-q1"),
            },
            {
                1: ("single", 0),
                2: ("text", 0),
            },
        )
        calls: list[object] = []

        with ExitStack() as stack:
            stack.enter_context(_patched_attr(runtime, "_wait_for_question_visible", lambda *_args, **_kwargs: True))
            stack.enter_context(_patched_attr(runtime, "_is_question_visible", lambda *_args, **_kwargs: True))
            stack.enter_context(_patched_attr(runtime, "_human_scroll_after_question", lambda *_args, **_kwargs: calls.append("scroll")))
            stack.enter_context(_patched_attr(runtime, "dismiss_resume_dialog_if_present", lambda *_args, **_kwargs: None))
            stack.enter_context(_patched_attr(runtime, "_is_headless_mode", lambda _ctx: True))
            stack.enter_context(_patched_attr(runtime, "HEADLESS_PAGE_BUFFER_DELAY", 0.0))
            stack.enter_context(_patched_attr(runtime, "HEADLESS_PAGE_CLICK_DELAY", 0.0))
            stack.enter_context(_patched_attr(runtime, "has_configured_answer_duration", lambda _value: False))
            stack.enter_context(_patched_attr(runtime, "simulate_answer_duration_delay", lambda *_args, **_kwargs: False))
            stack.enter_context(_patched_attr(runtime, "_answer_qq_single", lambda *_args, **_kwargs: calls.append("single")))
            stack.enter_context(_patched_attr(runtime, "_answer_qq_text", lambda *_args, **_kwargs: calls.append("text")))
            stack.enter_context(_patched_attr(runtime, "_click_next_page_button", lambda *_args, **_kwargs: calls.append("next") or True))
            stack.enter_context(_patched_attr(runtime, "_wait_for_page_transition", lambda *_args: calls.append(("transition", _args[1], _args[2]))))
            stack.enter_context(_patched_attr(runtime, "submit", lambda *_args, **_kwargs: calls.append("submit")))
            result = runtime.brush_qq(
                object(),
                object(),
                ctx,
                stop_signal=threading.Event(),
                thread_name="Worker-1",
                psycho_plan=None,
            )

        self.assertTrue(result)
        self.assertIn("single", calls)
        self.assertIn("text", calls)
        self.assertIn("next", calls)
        self.assertIn(("transition", "page1-q1", "page2-q1"), calls)
        self.assertEqual(calls[-1], "submit")
        self.assertIn(("提交中", True), ctx.status_updates)

    def test_brush_qq_aborts_during_final_duration_wait_before_submit(self) -> None:
        ctx = _FakeState({1: _meta(1)}, {1: ("single", 0)})
        calls: list[str] = []

        with ExitStack() as stack:
            stack.enter_context(_patched_attr(runtime, "_wait_for_question_visible", lambda *_args, **_kwargs: True))
            stack.enter_context(_patched_attr(runtime, "_is_question_visible", lambda *_args, **_kwargs: True))
            stack.enter_context(_patched_attr(runtime, "_human_scroll_after_question", lambda *_args, **_kwargs: None))
            stack.enter_context(_patched_attr(runtime, "dismiss_resume_dialog_if_present", lambda *_args, **_kwargs: None))
            stack.enter_context(_patched_attr(runtime, "_is_headless_mode", lambda _ctx: True))
            stack.enter_context(_patched_attr(runtime, "HEADLESS_PAGE_BUFFER_DELAY", 0.0))
            stack.enter_context(_patched_attr(runtime, "has_configured_answer_duration", lambda _value: True))
            stack.enter_context(_patched_attr(runtime, "simulate_answer_duration_delay", lambda *_args, **_kwargs: True))
            stack.enter_context(_patched_attr(runtime, "_answer_qq_single", lambda *_args, **_kwargs: calls.append("single")))
            stack.enter_context(_patched_attr(runtime, "submit", lambda *_args, **_kwargs: calls.append("submit")))
            result = runtime.brush_qq(
                object(),
                object(),
                ctx,
                stop_signal=threading.Event(),
                thread_name="Worker-1",
                psycho_plan=None,
            )

        self.assertFalse(result)
        self.assertEqual(calls, ["single"])
        self.assertIn(("等待时长中", True), ctx.status_updates)
        self.assertEqual(ctx.status_updates[-1], ("已中断", False))


if __name__ == "__main__":
    unittest.main()

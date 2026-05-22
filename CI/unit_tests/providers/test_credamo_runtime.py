from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from credamo.provider import runtime


def _async_return(value=None):
    async def _runner(*_args, **_kwargs):
        return value

    return _runner


def _async_append(calls: list[object], value: object, *, result=None):
    async def _runner(*_args, **_kwargs):
        calls.append(value)
        return result

    return _runner


class CredamoRuntimeTests:
    class _FakeQuestionRoot:
        def __init__(self, question_num: int) -> None:
            self.question_num = question_num

    @pytest.mark.asyncio
    async def test_click_submit_waits_until_dynamic_button_appears(self, restore_credamo_runtime_patchpoints, patch_attrs) -> None:
        _ = restore_credamo_runtime_patchpoints
        attempts = iter([False, False, True])

        async def _click_once(_page):
            return next(attempts)

        patch_attrs((runtime, "_click_submit_once", _click_once))
        clicked = await runtime._click_submit(object(), timeout_ms=2000)
        assert clicked

    @pytest.mark.asyncio
    async def test_click_submit_stops_waiting_when_abort_requested(self, restore_credamo_runtime_patchpoints, patch_attrs) -> None:
        _ = restore_credamo_runtime_patchpoints
        stop_signal = threading.Event()

        def abort_after_first_wait(_seconds: float | None = None) -> bool:
            stop_signal.set()
            return True

        setattr(stop_signal, "wait", abort_after_first_wait)
        patch_attrs((runtime, "_click_submit_once", _async_return(False)))
        clicked = await runtime._click_submit(object(), stop_signal, timeout_ms=2000)
        assert not clicked

    @pytest.mark.asyncio
    async def test_brush_credamo_walks_next_pages_before_submit(self, restore_credamo_runtime_patchpoints, patch_attrs) -> None:
        _ = restore_credamo_runtime_patchpoints
        stop_signal = threading.Event()
        state = SimpleNamespace(
            stop_event=stop_signal,
            update_thread_step=lambda *args, **kwargs: None,
            update_thread_status=lambda *args, **kwargs: None,
        )
        config = SimpleNamespace(
            question_config_index_map={1: ("single", 0), 2: ("dropdown", 0), 3: ("order", -1)},
            single_prob=[-1],
            droplist_prob=[-1],
            scale_prob=[],
            multiple_prob=[],
            texts=[],
            answer_duration_range_seconds=[0, 0],
        )
        driver = object()
        page = object()
        roots_page1 = [self._FakeQuestionRoot(1), self._FakeQuestionRoot(2)]
        roots_page2 = [self._FakeQuestionRoot(3)]
        calls: list[object] = []
        pending_iter = iter(
            [
                [(roots_page1[0], 1, "k1"), (roots_page1[1], 2, "k2")],
                [],
                [(roots_page2[0], 3, "k3")],
                [],
            ]
        )

        async def _pending(*_args, **_kwargs):
            return next(pending_iter)

        patch_attrs(
            (runtime, "_page", _async_return(page)),
            (runtime, "_wait_for_question_roots", _async_return(roots_page1)),
            (runtime, "_has_answerable_question_roots", _async_return(True)),
            (runtime, "_wait_for_dynamic_question_roots", _async_return(roots_page2)),
            (runtime, "_unanswered_question_roots", _pending),
            (runtime, "_question_number_from_root", lambda _page, root, _fallback: _async_return(root.question_num)()),
            (runtime, "_root_text", _async_return("Q")),
            (runtime, "_navigation_action", _async_return("next")),
            (runtime, "_question_signature", _async_return((("question-1", "page1"),))),
            (runtime, "_wait_for_page_change", _async_return(True)),
            (runtime, "_click_navigation", _async_append(calls, "next", result=True)),
            (runtime, "_click_submit", _async_append(calls, "submit", result=True)),
            (runtime, "_answer_single_like", _async_append(calls, "single", result=True)),
            (runtime, "_answer_dropdown", _async_append(calls, "dropdown", result=True)),
            (runtime, "_answer_order", _async_append(calls, "order", result=True)),
            (runtime, "simulate_answer_duration_delay", _async_return(False)),
            (runtime, "_human_scroll_after_question", _async_return(None)) if hasattr(runtime, "_human_scroll_after_question") else (runtime, "_click_submit_once", _async_return(True)),
        )

        navigation_actions = iter(["next", "submit"])

        async def _navigation(_page):
            return next(navigation_actions)

        async def _roots(*_args, **_kwargs):
            if calls.count("next") == 0:
                return roots_page1
            return roots_page2

        patch_attrs(
            (runtime, "_navigation_action", _navigation),
            (runtime, "_wait_for_question_roots", _roots),
            (runtime, "_has_answerable_question_roots", _async_return(True)),
            (runtime, "_wait_for_dynamic_question_roots", _async_return([])),
        )

        result = await runtime.brush_credamo(driver, config, state, stop_signal=stop_signal, thread_name="Worker-1")
        assert result
        assert calls == ["single", "dropdown", "next", "order", "submit"]

    @pytest.mark.asyncio
    async def test_brush_credamo_no_submit_test_answers_without_submit(self, restore_credamo_runtime_patchpoints, patch_attrs) -> None:
        _ = restore_credamo_runtime_patchpoints
        stop_signal = threading.Event()
        status_updates: list[tuple[str, bool]] = []
        state = SimpleNamespace(
            stop_event=stop_signal,
            update_thread_step=lambda *args, **kwargs: None,
            update_thread_status=lambda _thread, text, *, running: status_updates.append((text, running)),
        )
        config = SimpleNamespace(
            question_config_index_map={1: ("single", 0)},
            single_prob=[-1],
            droplist_prob=[],
            scale_prob=[],
            multiple_prob=[],
            texts=[],
            answer_duration_range_seconds=[0, 0],
            submit_enabled=False,
        )
        root = self._FakeQuestionRoot(1)
        pending_iter = iter([[(root, 1, "k1")], []])
        calls: list[object] = []
        patch_attrs(
            (runtime, "_page", _async_return(object())),
            (runtime, "_wait_for_question_roots", _async_return([root])),
            (runtime, "_has_answerable_question_roots", _async_return(True)),
            (runtime, "_unanswered_question_roots", lambda *_args, **_kwargs: _async_return(next(pending_iter))()),
            (runtime, "_wait_for_dynamic_question_roots", _async_return([])),
            (runtime, "_question_number_from_root", lambda _page, item, _fallback: _async_return(item.question_num)()),
            (runtime, "_root_text", _async_return("Q")),
            (runtime, "_navigation_action", _async_return("submit")),
            (runtime, "_answer_single_like", _async_append(calls, "single", result=True)),
            (runtime, "simulate_answer_duration_delay", _async_return(False)),
            (runtime, "_click_submit", _async_append(calls, "submit", result=True)),
        )

        result = await runtime.brush_credamo(object(), config, state, stop_signal=stop_signal, thread_name="Worker-1")

        assert result
        assert calls == ["single"]
        assert ("单测完成", False) in status_updates

    @pytest.mark.asyncio
    async def test_brush_credamo_answers_revealed_questions_and_matrix_and_multiple(self, restore_credamo_runtime_patchpoints, patch_attrs) -> None:
        _ = restore_credamo_runtime_patchpoints
        stop_signal = threading.Event()
        state = SimpleNamespace(
            stop_event=stop_signal,
            update_thread_step=lambda *args, **kwargs: None,
            update_thread_status=lambda *args, **kwargs: None,
        )
        root8 = self._FakeQuestionRoot(8)
        root9 = self._FakeQuestionRoot(9)
        root11 = self._FakeQuestionRoot(11)
        root5 = self._FakeQuestionRoot(5)
        config = SimpleNamespace(
            question_config_index_map={8: ("single", 0), 9: ("scale", 0), 11: ("matrix", 0), 5: ("multiple", 0)},
            questions_metadata={
                11: SimpleNamespace(rows=3),
                5: SimpleNamespace(multi_min_limit=2, multi_max_limit=3),
            },
            single_prob=[[0.0, 1.0]],
            droplist_prob=[],
            scale_prob=[[100.0, 0.0, 0.0]],
            matrix_prob=[[100.0, 0.0, 0.0], [0.0, 100.0, 0.0], [0.0, 0.0, 100.0]],
            multiple_prob=[[100.0, 100.0, 100.0, 100.0]],
            texts=[],
            answer_duration_range_seconds=[0, 0],
        )
        calls: list[object] = []
        page = object()
        root_groups = {
            tuple([root8]): [(root8, 8, "k8")],
            tuple([root8, root9]): [(root9, 9, "k9")],
            tuple([root11]): [(root11, 11, "k11")],
            tuple([root5]): [(root5, 5, "k5")],
        }
        page_signatures = iter(["page-1", "page-2", "page-3"])
        navigation_iter = iter(["next", "next", "submit"])

        async def _wait_roots(*_args, **_kwargs):
            if calls.count("next") == 0:
                return [root8]
            if calls.count("next") == 1:
                return [root11]
            return [root5]

        async def _pending(_page, roots, answered_keys, **_kwargs):
            root_tuple = tuple(roots)
            if root_tuple == (root8,) and "k8" not in answered_keys:
                return [(root8, 8, "k8")]
            if root_tuple == (root8, root9) and "k9" not in answered_keys:
                return [(root9, 9, "k9")]
            if root_tuple == (root11,) and "k11" not in answered_keys:
                return [(root11, 11, "k11")]
            if root_tuple == (root5,) and "k5" not in answered_keys:
                return [(root5, 5, "k5")]
            return []

        async def _revealed(_page, answered_keys, _stop_signal, **_kwargs):
            if "k8" in answered_keys and "k9" not in answered_keys and calls.count("next") == 0:
                return [root8, root9]
            return []

        async def _navigation(*_args, **_kwargs):
            return next(navigation_iter)

        patch_attrs(
            (runtime, "_page", _async_return(page)),
            (runtime, "_wait_for_question_roots", _wait_roots),
            (runtime, "_has_answerable_question_roots", _async_return(True)),
            (runtime, "_unanswered_question_roots", _pending),
            (runtime, "_wait_for_dynamic_question_roots", _revealed),
            (runtime, "_navigation_action", _navigation),
            (runtime, "_question_signature", lambda *_args, **_kwargs: _async_return(next(page_signatures))()),
            (runtime, "_click_navigation", _async_append(calls, "next", result=True)),
            (runtime, "_wait_for_page_change", _async_return(True)),
            (runtime, "_click_submit", _async_append(calls, "submit", result=True)),
            (runtime, "_answer_single_like", _async_append(calls, "single", result=True)),
            (runtime, "_answer_scale", _async_append(calls, "scale", result=True)),
            (runtime, "_answer_matrix", _async_append(calls, "matrix", result=True)),
            (runtime, "_answer_multiple", _async_append(calls, "multiple", result=True)),
            (runtime, "simulate_answer_duration_delay", _async_return(False)),
        )

        result = await runtime.brush_credamo(object(), config, state, stop_signal=stop_signal, thread_name="Worker-1")
        assert result
        assert calls == ["single", "scale", "next", "matrix", "next", "multiple", "submit"]

    @pytest.mark.asyncio
    async def test_brush_credamo_missing_config_does_not_advance_progress(self, restore_credamo_runtime_patchpoints, patch_attrs) -> None:
        _ = restore_credamo_runtime_patchpoints
        stop_signal = threading.Event()
        step_updates: list[int] = []
        state = SimpleNamespace(
            stop_event=stop_signal,
            update_thread_step=lambda _thread, step, _total, **_kwargs: step_updates.append(step),
            update_thread_status=lambda *args, **kwargs: None,
        )
        root1 = self._FakeQuestionRoot(1)
        root2 = self._FakeQuestionRoot(2)
        config = SimpleNamespace(
            question_config_index_map={2: ("single", 0), 3: ("single", 1)},
            single_prob=[-1, -1],
            droplist_prob=[],
            scale_prob=[],
            multiple_prob=[],
            texts=[],
            answer_duration_range_seconds=[0, 0],
        )

        pending_iter = iter([
            [(root1, 1, "k1"), (root2, 2, "k2")],
            [],
        ])

        async def _pending(*_args, **_kwargs):
            return next(pending_iter)

        patch_attrs(
            (runtime, "_page", _async_return(object())),
            (runtime, "_wait_for_question_roots", _async_return([root1, root2])),
            (runtime, "_has_answerable_question_roots", _async_return(True)),
            (runtime, "_unanswered_question_roots", _pending),
            (runtime, "_wait_for_dynamic_question_roots", _async_return([])),
            (runtime, "_navigation_action", _async_return("submit")),
            (runtime, "_answer_single_like", _async_return(True)),
            (runtime, "_click_submit", _async_return(True)),
            (runtime, "simulate_answer_duration_delay", _async_return(False)),
        )

        result = await runtime.brush_credamo(object(), config, state, stop_signal=stop_signal, thread_name="Worker-1")

        assert result
        assert step_updates[:2] == [0, 1]

    @pytest.mark.asyncio
    async def test_patchpoint_wrappers_delegate(self, restore_credamo_runtime_patchpoints, patch_attrs) -> None:
        _ = restore_credamo_runtime_patchpoints
        page = object()
        root = object()
        patch_attrs(
            (runtime, "_DOM_WAIT_FOR_QUESTION_ROOTS", _async_return(["r1"])),
            (runtime, "_DOM_UNANSWERED_QUESTION_ROOTS", _async_return(["r2"])),
            (runtime, "_DOM_WAIT_FOR_DYNAMIC_QUESTION_ROOTS", _async_return(["r3"])),
            (runtime, "_DOM_WAIT_FOR_PAGE_CHANGE", _async_return(True)),
            (runtime, "_click_submit_once", _async_return(True)),
            (runtime, "_ANSWER_SINGLE_LIKE", _async_return(True)),
            (runtime, "_ANSWER_MULTIPLE", _async_return(True)),
            (runtime, "_ANSWER_TEXT", _async_return(True)),
            (runtime, "_ANSWER_DROPDOWN", _async_return(True)),
            (runtime, "_ANSWER_SCALE", _async_return(True)),
            (runtime, "_ANSWER_MATRIX", _async_return(True)),
            (runtime, "_ANSWER_ORDER", _async_return(True)),
        )

        assert await runtime._wait_for_question_roots(page, threading.Event(), timeout_ms=1) == ["r1"]
        assert await runtime._unanswered_question_roots(page, ["a"], {"b"}, fallback_start=2) == ["r2"]
        assert await runtime._wait_for_dynamic_question_roots(page, {"a"}, threading.Event(), fallback_start=2) == ["r3"]
        assert await runtime._wait_for_page_change(page, "sig", threading.Event(), timeout_ms=1)
        assert await runtime._click_submit(page, threading.Event(), timeout_ms=1)
        assert await runtime._answer_single_like(page, root, [1], 0)
        assert await runtime._answer_multiple(page, root, [1], min_limit=1, max_limit=2)
        assert await runtime._answer_text(root, ["x"])
        assert await runtime._answer_dropdown(page, root, [1])
        assert await runtime._answer_scale(page, root, [1])
        assert await runtime._answer_matrix(page, root, [[1]], 3)
        assert await runtime._answer_order(page, root)

    @pytest.mark.asyncio
    async def test_attempt_answer_current_root_prefers_provider_question_mapping(self, restore_credamo_runtime_patchpoints, patch_attrs) -> None:
        _ = restore_credamo_runtime_patchpoints

        class _FakeRoot:
            async def get_attribute(self, name: str):
                if name == "data-id":
                    return "question-1"
                return None

        class _FakePage:
            async def evaluate(self, _script, _root):
                return "4"

        calls: list[object] = []
        config = SimpleNamespace(
            question_config_index_map={2: ("scale", 1)},
            provider_question_config_index_map={"credamo:4:question-1": ("scale", 0)},
            provider_question_metadata_map={"credamo:4:question-1": SimpleNamespace(num=2, rows=1)},
            questions_metadata={2: SimpleNamespace(num=2, rows=1)},
            scale_prob=[[100.0, 0.0, 0.0], [0.0, 0.0, 100.0]],
            matrix_prob=[],
            multiple_prob=[],
            texts=[],
            single_prob=[],
            droplist_prob=[],
        )
        patch_attrs(
            (runtime, "_answer_scale", _async_append(calls, "scale", result=True)),
        )

        result = await runtime._attempt_answer_current_root(_FakePage(), _FakeRoot(), 2, config)

        assert result
        assert calls == ["scale"]

    @pytest.mark.asyncio
    async def test_attempt_answer_current_root_uses_fallback_page_id_when_dom_page_id_missing(self, restore_credamo_runtime_patchpoints, patch_attrs) -> None:
        _ = restore_credamo_runtime_patchpoints

        class _FakeRoot:
            async def get_attribute(self, name: str):
                if name == "data-id":
                    return "question-1"
                return None

        class _FakePage:
            async def evaluate(self, _script, _root):
                return ""

        calls: list[object] = []
        config = SimpleNamespace(
            question_config_index_map={2: ("scale", 1)},
            provider_question_config_index_map={"credamo:6:question-1": ("single", 0)},
            provider_question_metadata_map={"credamo:6:question-1": SimpleNamespace(num=2, rows=1)},
            questions_metadata={2: SimpleNamespace(num=2, rows=1)},
            scale_prob=[[100.0, 0.0, 0.0], [0.0, 0.0, 100.0]],
            matrix_prob=[],
            multiple_prob=[],
            texts=[],
            single_prob=[[100.0, 0.0]],
            droplist_prob=[],
        )
        patch_attrs(
            (runtime, "_answer_single_like", _async_append(calls, "single", result=True)),
        )

        result = await runtime._attempt_answer_current_root(
            _FakePage(),
            _FakeRoot(),
            2,
            config,
            fallback_page_id=6,
        )

        assert result
        assert calls == ["single"]

    @pytest.mark.asyncio
    async def test_brush_credamo_handles_missing_roots_abort_unknown_type_and_submit_failures(self, restore_credamo_runtime_patchpoints, patch_attrs) -> None:
        _ = restore_credamo_runtime_patchpoints
        stop_signal = threading.Event()
        state = SimpleNamespace(
            stop_event=stop_signal,
            update_thread_step=lambda *args, **kwargs: None,
            update_thread_status=lambda *args, **kwargs: None,
        )
        page = object()
        patch_attrs(
            (runtime, "_page", _async_return(page)),
            (runtime, "_wait_for_question_roots", _async_return([])),
        )
        config_missing = SimpleNamespace(
            question_config_index_map={1: ("single", 0)},
            single_prob=[-1],
            droplist_prob=[],
            scale_prob=[],
            multiple_prob=[],
            texts=[],
            answer_duration_range_seconds=[0, 0],
        )
        with pytest.raises(RuntimeError, match="未识别到题目"):
            await runtime.brush_credamo(object(), config_missing, state, stop_signal=stop_signal, thread_name="Worker-1")

        root = self._FakeQuestionRoot(9)
        status_updates: list[tuple[str, bool]] = []
        state2 = SimpleNamespace(
            stop_event=threading.Event(),
            update_thread_step=lambda *args, **kwargs: None,
            update_thread_status=lambda _thread, status_text, *, running: status_updates.append((status_text, running)),
        )
        config_unknown = SimpleNamespace(
            question_config_index_map={9: ("mystery", 0)},
            single_prob=[],
            droplist_prob=[],
            scale_prob=[],
            multiple_prob=[],
            texts=[],
            answer_duration_range_seconds=[0, 0],
        )
        pending_iter = iter([[(root, 9, "k9")], []])
        patch_attrs(
            (runtime, "_page", _async_return(page)),
            (runtime, "_wait_for_question_roots", _async_return([root])),
            (runtime, "_has_answerable_question_roots", _async_return(True)),
            (runtime, "_unanswered_question_roots", lambda *_args, **_kwargs: _async_return(next(pending_iter))()),
            (runtime, "_wait_for_dynamic_question_roots", _async_return([])),
            (runtime, "_navigation_action", _async_return("submit")),
            (runtime, "simulate_answer_duration_delay", _async_return(True)),
        )
        assert not await runtime.brush_credamo(object(), config_unknown, state2, stop_signal=state2.stop_event, thread_name="Worker-2")
        assert ("提交中", True) not in status_updates

        config_submit_fail = SimpleNamespace(
            question_config_index_map={9: ("text", 0)},
            single_prob=[],
            droplist_prob=[],
            scale_prob=[],
            multiple_prob=[],
            texts=[["x"]],
            answer_duration_range_seconds=[0, 0],
        )
        pending_iter2 = iter([[(root, 9, "k9")], []])
        patch_attrs(
            (runtime, "_page", _async_return(page)),
            (runtime, "_wait_for_question_roots", _async_return([root])),
            (runtime, "_has_answerable_question_roots", _async_return(True)),
            (runtime, "_unanswered_question_roots", lambda *_args, **_kwargs: _async_return(next(pending_iter2))()),
            (runtime, "_wait_for_dynamic_question_roots", _async_return([])),
            (runtime, "_navigation_action", _async_return("submit")),
            (runtime, "_answer_text", _async_return(True)),
            (runtime, "simulate_answer_duration_delay", _async_return(False)),
            (runtime, "_click_submit", _async_return(False)),
        )
        with pytest.raises(RuntimeError, match="提交按钮未找到"):
            await runtime.brush_credamo(object(), config_submit_fail, state, stop_signal=stop_signal, thread_name="Worker-3")

    @pytest.mark.asyncio
    async def test_brush_credamo_skips_intro_page_without_answerable_questions(self, restore_credamo_runtime_patchpoints, patch_attrs) -> None:
        _ = restore_credamo_runtime_patchpoints
        stop_signal = threading.Event()
        state = SimpleNamespace(
            stop_event=stop_signal,
            update_thread_step=lambda *args, **kwargs: None,
            update_thread_status=lambda *args, **kwargs: None,
        )
        config = SimpleNamespace(
            question_config_index_map={2: ("single", 0)},
            single_prob=[-1],
            droplist_prob=[],
            scale_prob=[],
            multiple_prob=[],
            texts=[],
            answer_duration_range_seconds=[0, 0],
        )
        intro_root = self._FakeQuestionRoot(1)
        question_root = self._FakeQuestionRoot(2)
        page = object()
        calls: list[str] = []
        roots_iter = iter([[intro_root], [question_root]])
        pending_iter = iter([[(question_root, 2, "k2")], []])
        nav_iter = iter(["next", "submit"])

        async def _wait_roots(*_args, **_kwargs):
            return next(roots_iter)

        async def _pending(*_args, **_kwargs):
            return next(pending_iter)

        async def _nav(*_args, **_kwargs):
            return next(nav_iter)

        async def _has_answerable(_page, roots):
            return roots == [question_root]

        patch_attrs(
            (runtime, "_page", _async_return(page)),
            (runtime, "_wait_for_question_roots", _wait_roots),
            (runtime, "_has_answerable_question_roots", _has_answerable),
            (runtime, "_question_signature", _async_return((("intro", "说明页"),))),
            (runtime, "_click_navigation", _async_append(calls, "next", result=True)),
            (runtime, "_wait_for_page_change", _async_return(True)),
            (runtime, "_unanswered_question_roots", _pending),
            (runtime, "_wait_for_dynamic_question_roots", _async_return([])),
            (runtime, "_navigation_action", _nav),
            (runtime, "_answer_single_like", _async_append(calls, "single", result=True)),
            (runtime, "_click_submit", _async_append(calls, "submit", result=True)),
            (runtime, "simulate_answer_duration_delay", _async_return(False)),
        )

        result = await runtime.brush_credamo(object(), config, state, stop_signal=stop_signal, thread_name="Worker-1")
        assert result
        assert calls == ["next", "single", "submit"]

    @pytest.mark.asyncio
    async def test_brush_credamo_retries_question_when_answer_not_confirmed(self, restore_credamo_runtime_patchpoints, patch_attrs) -> None:
        _ = restore_credamo_runtime_patchpoints
        stop_signal = threading.Event()
        state = SimpleNamespace(
            stop_event=stop_signal,
            update_thread_step=lambda *args, **kwargs: None,
            update_thread_status=lambda *args, **kwargs: None,
        )
        root = self._FakeQuestionRoot(9)
        calls: list[str] = []
        config = SimpleNamespace(
            question_config_index_map={9: ("scale", 0)},
            scale_prob=[[100.0, 0.0, 0.0]],
            single_prob=[],
            droplist_prob=[],
            multiple_prob=[],
            texts=[],
            answer_duration_range_seconds=[0, 0],
        )

        async def _pending(_page, _roots, answered_keys, **_kwargs):
            if "k9" in answered_keys:
                return []
            return [(root, 9, "k9")]

        scale_attempts = iter([False, True])

        async def _answer_scale(*_args, **_kwargs):
            calls.append("scale")
            return next(scale_attempts)

        patch_attrs(
            (runtime, "_page", _async_return(object())),
            (runtime, "_wait_for_question_roots", _async_return([root])),
            (runtime, "_has_answerable_question_roots", _async_return(True)),
            (runtime, "_unanswered_question_roots", _pending),
            (runtime, "_wait_for_dynamic_question_roots", _async_return([])),
            (runtime, "_navigation_action", _async_return("submit")),
            (runtime, "_answer_scale", _answer_scale),
            (runtime, "_click_submit", _async_append(calls, "submit", result=True)),
            (runtime, "simulate_answer_duration_delay", _async_return(False)),
        )

        result = await runtime.brush_credamo(object(), config, state, stop_signal=stop_signal, thread_name="Worker-1")

        assert result
        assert calls == ["scale", "scale", "submit"]

    @pytest.mark.asyncio
    async def test_refill_required_questions_on_current_page_skips_invalid_and_updates_status(self, restore_credamo_runtime_patchpoints, patch_attrs) -> None:
        _ = restore_credamo_runtime_patchpoints
        status_updates: list[tuple[str, bool]] = []
        state = SimpleNamespace(
            update_thread_status=lambda _thread, status_text, *, running: status_updates.append((status_text, running)),
        )
        runtime_state = SimpleNamespace(page_index=6)
        page = object()
        root2 = self._FakeQuestionRoot(2)
        root5 = self._FakeQuestionRoot(5)
        config = SimpleNamespace()
        patch_attrs(
            (runtime, "_page", _async_return(page)),
            (runtime, "get_credamo_runtime_state", lambda _driver: runtime_state),
            (runtime, "_question_roots", _async_return([root2, root5])),
            (runtime, "_question_number_from_root", lambda _page, root, _fallback: _async_return(root.question_num)()),
            (runtime, "_resolve_config_binding", _async_return((2, ("single", 0), None))),
            (
                runtime,
                "_attempt_answer_current_root",
                lambda _page, root, _question_num, _config, fallback_page_id=0: _async_return(root is root2 and fallback_page_id == 6)(),
            ),
        )

        filled = await runtime.refill_required_questions_on_current_page(
            object(),
            config,
            question_numbers=[0, "2", 2, "x", 7, 5],
            thread_name="Worker-1",
            state=state,
        )

        assert filled == 1
        assert status_updates == [("补答第2题", True), ("补答第2题", True)]

    @pytest.mark.asyncio
    async def test_refill_required_questions_on_current_page_returns_zero_for_empty_cases(self, restore_credamo_runtime_patchpoints, patch_attrs) -> None:
        _ = restore_credamo_runtime_patchpoints
        config = SimpleNamespace()
        patch_attrs(
            (runtime, "_page", _async_return(object())),
            (runtime, "get_credamo_runtime_state", lambda _driver: SimpleNamespace(page_index=1)),
            (runtime, "_question_roots", _async_return([])),
        )

        assert await runtime.refill_required_questions_on_current_page(object(), config, question_numbers=[], thread_name="Worker") == 0
        assert await runtime.refill_required_questions_on_current_page(object(), config, question_numbers=["bad"], thread_name="Worker") == 0
        assert await runtime.refill_required_questions_on_current_page(object(), config, question_numbers=[1], thread_name="Worker") == 0

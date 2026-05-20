from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

import pytest

from credamo.provider import submission
from software.core.engine.runtime_actions import RuntimeActionResult
from software.core.task import ExecutionConfig, ExecutionState


class _FakeDriver:
    def __init__(self, body_text: str = "", current_url: str = "https://example.com/form") -> None:
        self.browser_name = "edge"
        self.session_id = "test-session"
        self.browser_pid: int | None = None
        self.browser_pids: set[int] = set()
        self.body_text = body_text
        self._current_url = current_url
        self.page_obj: Any = None
        self._page_source = ""
        self._title = ""

    async def execute_script(self, script: str, *args: Any):
        del args
        if "document.body ? document.body.innerText" in script:
            return self.body_text
        if "document.querySelectorAll" in script:
            return False
        return ""

    def set_execute_script_result(self, value: Any) -> None:
        self.execute_script = _async_return(value)

    async def find_element(self, *_args, **_kwargs):
        raise RuntimeError("unused")

    async def find_elements(self, *_args, **_kwargs):
        return []

    async def get(self, *_args, **_kwargs) -> None:
        return None

    async def current_url(self) -> str:
        return self._current_url

    async def page(self) -> Any:
        return self.page_obj

    async def page_source(self) -> str:
        return self._page_source

    async def title(self) -> str:
        return self._title

    async def set_window_size(self, *_args, **_kwargs) -> None:
        return None

    async def refresh(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    def mark_cleanup_done(self) -> bool:
        return True

    def quit(self) -> None:
        return None


def _async_return(value=None) -> Callable[..., Any]:
    async def _runner(*_args, **_kwargs):
        return value

    return _runner


class CredamoSubmissionTests:
    @pytest.mark.asyncio
    async def test_runtime_context_summary_formats_page_and_answer_counts(self, patch_attrs) -> None:
        driver = _FakeDriver()
        patch_attrs(
            (
                submission,
                "peek_credamo_runtime_state",
                lambda _driver: SimpleNamespace(page_index=2, answered_question_keys=["a", " ", "", "b"]),
            ),
        )
        assert submission._runtime_context_summary(driver) == "page=2 answered=2"

        patch_attrs((submission, "peek_credamo_runtime_state", lambda _driver: None))
        assert submission._runtime_context_summary(driver) == ""

    @pytest.mark.asyncio
    async def test_body_and_feedback_text_return_empty_on_driver_error(self) -> None:
        class _BrokenDriver(_FakeDriver):
            async def execute_script(self, script: str, *args: Any):
                del script, args
                raise RuntimeError("boom")

        driver = _BrokenDriver()
        assert await submission._body_text(driver) == ""
        assert await submission._visible_feedback_text(driver) == ""

    def test_marker_helpers_cover_selection_completion_and_verification(self) -> None:
        assert submission._looks_like_selection_validation("请至少选择 2 项后继续")
        assert not submission._looks_like_selection_validation("")
        assert submission._contains_completion_marker("感谢您的参与，已提交")
        assert submission._contains_verification_marker("请完成滑块验证")

    @pytest.mark.asyncio
    async def test_extract_submission_recovery_hint_uses_dom_messages_and_pending_questions(self, patch_attrs) -> None:
        driver = _FakeDriver()
        payload = {
            "questionNumbers": ["2", "2", "x"],
            "messages": ["请填写必填项", "请至少选择2项", "普通提示"],
        }
        patch_attrs(
            (submission, "_page", _async_return("page")),
            (submission, "peek_credamo_runtime_state", lambda _driver: SimpleNamespace(answered_question_keys=["k1"])),
            (submission, "_question_roots", _async_return(["root-1", "root-2"])),
            (submission, "_unanswered_question_roots", _async_return([("root-2", 5, "k5")])),
            (submission, "_question_number_from_root", _async_return(5)),
        )
        driver.set_execute_script_result(payload)

        hint = await submission._extract_submission_recovery_hint(driver)

        assert hint == submission.SubmissionRecoveryHint((2, 5), "请填写必填项 | 请至少选择2项")

    @pytest.mark.asyncio
    async def test_extract_submission_recovery_hint_returns_none_when_nothing_found(self, patch_attrs) -> None:
        driver = _FakeDriver()
        driver.set_execute_script_result({"questionNumbers": [], "messages": []})
        patch_attrs(
            (submission, "_page", _async_return(None)),
            (submission, "peek_credamo_runtime_state", lambda _driver: None),
        )
        assert await submission._extract_submission_recovery_hint(driver) is None

    @pytest.mark.asyncio
    async def test_has_visible_action_controls_handles_true_and_error(self) -> None:
        driver = _FakeDriver()
        driver.set_execute_script_result(True)
        assert await submission._has_visible_action_controls(driver)

        class _BrokenDriver(_FakeDriver):
            async def execute_script(self, script: str, *args: Any):
                del script, args
                raise RuntimeError("boom")

        assert not await submission._has_visible_action_controls(_BrokenDriver())

    @pytest.mark.asyncio
    async def test_submission_requires_verification_reads_runtime_state_when_feedback_hits(self, patch_attrs) -> None:
        driver = _FakeDriver(body_text="问卷正文")
        reads: list[str] = []
        patch_attrs(
            (
                submission,
                "peek_credamo_runtime_state",
                lambda _driver: reads.append("peek") or type("State", (), {"page_index": 3, "answered_question_keys": ["q1", "q2"]})(),
            ),
            (submission, "_visible_feedback_text", _async_return("请完成验证码验证后继续提交")),
        )
        assert await submission.submission_requires_verification(driver)
        assert reads == ["peek"]

    @pytest.mark.asyncio
    async def test_submission_validation_message_reads_runtime_state_when_driver_is_given(self, patch_attrs) -> None:
        driver = _FakeDriver(body_text="问卷正文")
        reads: list[str] = []
        patch_attrs(
            (submission, "peek_credamo_runtime_state", lambda _driver: reads.append("peek") or None),
        )
        assert "暂不支持自动处理" in await submission.submission_validation_message(driver)
        assert reads == ["peek"]

    @pytest.mark.asyncio
    async def test_submission_requires_verification_ignores_selection_validation_feedback(self, patch_attrs) -> None:
        driver = _FakeDriver(body_text="问卷正文")
        patch_attrs((submission, "_visible_feedback_text", _async_return("本题至少选择2项后才能继续")))
        assert not await submission.submission_requires_verification(driver)

    @pytest.mark.asyncio
    async def test_submission_requires_verification_detects_real_verification_feedback(self, patch_attrs) -> None:
        driver = _FakeDriver(body_text="问卷正文")
        patch_attrs((submission, "_visible_feedback_text", _async_return("请完成验证码验证后继续提交")))
        assert await submission.submission_requires_verification(driver)

    @pytest.mark.asyncio
    async def test_submission_requires_verification_can_fall_back_to_body_text(self, patch_attrs) -> None:
        driver = _FakeDriver(body_text="系统提示：请先完成滑块验证")
        patch_attrs((submission, "_visible_feedback_text", _async_return("")))
        assert await submission.submission_requires_verification(driver)

    @pytest.mark.asyncio
    async def test_submission_requires_verification_does_not_treat_completion_text_as_verification(self, patch_attrs) -> None:
        driver = _FakeDriver(body_text="感谢您的参与，答卷已经提交")
        patch_attrs((submission, "_visible_feedback_text", _async_return("")))
        assert not await submission.submission_requires_verification(driver)

    @pytest.mark.asyncio
    async def test_is_completion_page_accepts_body_completion_text_without_special_url(self, patch_attrs) -> None:
        driver = _FakeDriver(body_text="感谢您的宝贵时间，问卷已完成")
        patch_attrs((submission, "_visible_feedback_text", _async_return("")))
        assert await submission.is_completion_page(driver)

    @pytest.mark.asyncio
    async def test_is_completion_page_ignores_completion_text_when_submit_controls_still_visible(self, patch_attrs) -> None:
        driver = _FakeDriver(body_text="感谢您的参与")
        patch_attrs(
            (submission, "_visible_feedback_text", _async_return("")),
            (submission, "_has_visible_action_controls", _async_return(True)),
        )
        assert not await submission.is_completion_page(driver)

    @pytest.mark.asyncio
    async def test_is_completion_page_accepts_completion_url_and_feedback_marker(self, patch_attrs) -> None:
        driver = _FakeDriver(current_url="https://example.com/success")
        assert await submission.is_completion_page(driver)

        driver2 = _FakeDriver(body_text="问卷正文")
        patch_attrs((submission, "_visible_feedback_text", _async_return("答卷已经提交")))
        assert await submission.is_completion_page(driver2)

    @pytest.mark.asyncio
    async def test_wait_for_submission_verification_covers_stop_and_final_check(self, patch_attrs) -> None:
        driver = _FakeDriver()
        stop_signal = SimpleNamespace(is_set=lambda: True)
        assert not await submission.wait_for_submission_verification(driver, timeout=1, stop_signal=stop_signal)

        checks = iter([False, False, True])
        patch_attrs((submission, "submission_requires_verification", lambda *_args, **_kwargs: _async_return(next(checks))()))
        assert await submission.wait_for_submission_verification(driver, timeout=1, stop_signal=None)

    @pytest.mark.asyncio
    async def test_handle_consume_and_device_quota_helpers(self, patch_attrs) -> None:
        driver = _FakeDriver(body_text="设备次数已满")
        patch_attrs((submission, "is_completion_page", _async_return(True)))

        result = await submission.handle_submission_verification_detected(object(), object())
        assert isinstance(result, RuntimeActionResult)
        assert result.actions == ()
        assert not result.should_stop

        assert await submission.consume_submission_success_signal(driver)
        assert await submission.is_device_quota_limit_page(driver)

    @pytest.mark.asyncio
    async def test_attempt_submission_recovery_refills_questions_and_resubmits_once(self, patch_attrs) -> None:
        driver = _FakeDriver(body_text="请填写必答题")
        driver.page_obj = object()
        state = ExecutionState(config=ExecutionConfig(survey_provider="credamo"))
        runtime_state = SimpleNamespace(submission_recovery_attempts=0)
        refill_calls: list[list[int]] = []
        submit_calls: list[Any] = []
        patch_attrs(
            (submission, "submission_requires_verification", _async_return(False)),
            (submission, "get_credamo_runtime_state", lambda _driver: runtime_state),
            (
                submission,
                "_extract_submission_recovery_hint",
                _async_return(submission.SubmissionRecoveryHint((2, 5), "当前页存在未作答题目")),
            ),
            (submission, "_page", _async_return("page")),
        )

        from credamo.provider import runtime as credamo_runtime

        with pytest.MonkeyPatch.context() as mp:
            async def _refill(_driver, config, *, question_numbers, thread_name, state=None):
                del config, thread_name, state
                refill_calls.append(list(question_numbers))
                return 2

            async def _click_submit(page, stop_signal=None):
                submit_calls.append((page, stop_signal))
                return True

            mp.setattr(credamo_runtime, "refill_required_questions_on_current_page", _refill)
            mp.setattr(credamo_runtime, "_click_submit", _click_submit)
            recovered = await submission.attempt_submission_recovery(driver, state, None, None, thread_name="Worker-2")

        assert recovered is True
        assert int(runtime_state.submission_recovery_attempts) == 1
        assert refill_calls == [[2, 5]]
        assert submit_calls == [("page", None)]

    @pytest.mark.asyncio
    async def test_attempt_submission_recovery_stops_when_refill_failed(self, patch_attrs) -> None:
        driver = _FakeDriver(body_text="请填写必答题")
        driver.page_obj = object()
        state = ExecutionState(config=ExecutionConfig(survey_provider="credamo"))
        runtime_state = SimpleNamespace(submission_recovery_attempts=0)
        patch_attrs(
            (submission, "submission_requires_verification", _async_return(False)),
            (submission, "get_credamo_runtime_state", lambda _driver: runtime_state),
            (
                submission,
                "_extract_submission_recovery_hint",
                _async_return(submission.SubmissionRecoveryHint((2,), "当前页存在未作答题目")),
            ),
            (submission, "_page", _async_return("page")),
        )

        from credamo.provider import runtime as credamo_runtime

        with pytest.MonkeyPatch.context() as mp:
            submit_mock = []

            async def _click_submit(*_args, **_kwargs):
                submit_mock.append(True)
                return True

            mp.setattr(credamo_runtime, "refill_required_questions_on_current_page", _async_return(0))
            mp.setattr(credamo_runtime, "_click_submit", _click_submit)
            recovered = await submission.attempt_submission_recovery(driver, state, None, None, thread_name="Worker-2")

        assert recovered is False
        assert int(runtime_state.submission_recovery_attempts) == 0
        assert submit_mock == []

    @pytest.mark.asyncio
    async def test_attempt_submission_recovery_stops_for_stop_signal_verification_limit_and_missing_targets(self, patch_attrs) -> None:
        driver = _FakeDriver()
        state = ExecutionState(config=ExecutionConfig(survey_provider="credamo"))

        stop_signal = SimpleNamespace(is_set=lambda: True)
        assert not await submission.attempt_submission_recovery(driver, state, None, stop_signal, thread_name="Worker-1")

        patch_attrs((submission, "submission_requires_verification", _async_return(True)))
        assert not await submission.attempt_submission_recovery(driver, state, None, None, thread_name="Worker-1")

        patch_attrs(
            (submission, "submission_requires_verification", _async_return(False)),
            (submission, "get_credamo_runtime_state", lambda _driver: SimpleNamespace(submission_recovery_attempts=1)),
        )
        assert not await submission.attempt_submission_recovery(driver, state, None, None, thread_name="Worker-1")

        patch_attrs(
            (submission, "get_credamo_runtime_state", lambda _driver: SimpleNamespace(submission_recovery_attempts=0)),
            (submission, "_extract_submission_recovery_hint", _async_return(submission.SubmissionRecoveryHint((), "提示"))),
        )
        assert not await submission.attempt_submission_recovery(driver, state, None, None, thread_name="Worker-1")

    @pytest.mark.asyncio
    async def test_attempt_submission_recovery_handles_missing_page_or_submit_failure(self, patch_attrs) -> None:
        driver = _FakeDriver()
        state = ExecutionState(config=ExecutionConfig(survey_provider="credamo"))
        runtime_state = SimpleNamespace(submission_recovery_attempts=0)
        patch_attrs(
            (submission, "submission_requires_verification", _async_return(False)),
            (submission, "get_credamo_runtime_state", lambda _driver: runtime_state),
            (
                submission,
                "_extract_submission_recovery_hint",
                _async_return(submission.SubmissionRecoveryHint((3,), "当前页存在未作答题目")),
            ),
        )

        from credamo.provider import runtime as credamo_runtime

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(credamo_runtime, "refill_required_questions_on_current_page", _async_return(1))
            mp.setattr(credamo_runtime, "_click_submit", _async_return(False))
            patch_attrs((submission, "_page", _async_return(None)))
            assert not await submission.attempt_submission_recovery(driver, state, None, None, thread_name="Worker-1")
            assert runtime_state.submission_recovery_attempts == 1

            patch_attrs((submission, "_page", _async_return("page")))
            runtime_state.submission_recovery_attempts = 0
            assert not await submission.attempt_submission_recovery(driver, state, None, None, thread_name="Worker-1")
            assert runtime_state.submission_recovery_attempts == 1

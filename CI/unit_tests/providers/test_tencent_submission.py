from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest

from software.core.task import ExecutionConfig, ExecutionState
from software.providers.contracts import SurveyQuestionMeta
from tencent.provider import submission


class _FakeDriver:
    def __init__(self) -> None:
        self.browser_name = "edge"
        self.session_id = "test-session"
        self.browser_pid: int | None = None
        self.browser_pids: set[int] = set()
        self._current_url = ""
        self.page = None
        self.page_source = ""
        self.title = ""

    async def find_element(self, *_args, **_kwargs):
        raise RuntimeError("unused")

    async def find_elements(self, *_args, **_kwargs):
        return []

    async def execute_script(self, script: str, *args: Any):
        del script, args
        return None

    async def get(self, *_args, **_kwargs) -> None:
        return None

    async def current_url(self) -> str:
        return self._current_url

    async def page(self) -> Any:
        return self.page

    async def page_source(self) -> str:
        return self.page_source

    async def title(self) -> str:
        return self.title

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


def _async_return(value=None):
    async def _runner(*_args, **_kwargs):
        return value

    return _runner


class TencentSubmissionTests:
    @pytest.mark.asyncio
    async def test_prepare_submit_duration_override_installs_hook_when_configured(self, patch_attrs) -> None:
        driver = _FakeDriver()
        executed: list[tuple[str, tuple[Any, ...]]] = []
        state = ExecutionState(config=ExecutionConfig(survey_provider="qq", answer_duration_range_seconds=(300, 300)))

        async def _execute_script(script: str, *args: Any):
            executed.append((script, args))
            return {"ok": True, "targetSeconds": 300, "hooked": True}

        driver.execute_script = _execute_script
        patch_attrs((submission, "sample_answer_duration_seconds", lambda *_args, **_kwargs: 300.0))

        await submission._prepare_submit_duration_override(driver, state)

        assert len(executed) == 1
        assert "__surveyControllerQqDurationHookInstalled" in executed[0][0]
        assert executed[0][1] == (300,)

    @pytest.mark.asyncio
    async def test_submit_skips_duration_override_when_unconfigured(self, patch_attrs) -> None:
        driver = _FakeDriver()
        execute_calls: list[tuple[str, tuple[Any, ...]]] = []

        async def _execute_script(script: str, *args: Any):
            execute_calls.append((script, args))
            return None

        driver.execute_script = _execute_script
        patch_attrs(
            (submission, "_click_submit_button", _async_return(True)),
            (submission, "_click_submit_confirm_button", _async_return(None)),
            (submission, "_is_headless_mode", lambda _ctx: True),
            (submission, "HEADLESS_SUBMIT_INITIAL_DELAY", 0.0),
            (submission, "HEADLESS_SUBMIT_CLICK_SETTLE_DELAY", 0.0),
        )

        await submission.submit(
            driver,
            ctx=ExecutionState(config=ExecutionConfig(survey_provider="qq", answer_duration_range_seconds=(0, 0))),
            stop_signal=threading.Event(),
        )

        assert execute_calls == []

    @pytest.mark.asyncio
    async def test_submit_reads_runtime_state_when_submit_button_missing(self, patch_attrs) -> None:
        driver = _FakeDriver()
        reads: list[str] = []
        patch_attrs(
            (submission, "_click_submit_button", _async_return(False)),
            (submission, "_is_headless_mode", lambda _ctx: True),
            (submission, "HEADLESS_SUBMIT_INITIAL_DELAY", 0.0),
            (submission, "HEADLESS_SUBMIT_CLICK_SETTLE_DELAY", 0.0),
            (
                submission,
                "peek_qq_runtime_state",
                lambda _driver: reads.append("peek") or SimpleNamespace(page_index=2, page_question_ids=["q1"]),
            ),
        )

        with pytest.raises(Exception, match="Submit button not found"):
            await submission.submit(driver, ctx=None, stop_signal=threading.Event())

        assert reads == ["peek"]

    @pytest.mark.asyncio
    async def test_runtime_context_summary_reads_runtime_state_for_status_helpers(self, patch_attrs) -> None:
        driver = _FakeDriver()
        reads: list[str] = []
        patch_attrs(
            (submission, "peek_qq_runtime_state", lambda _driver: reads.append("peek") or None),
            (submission, "qq_is_completion_page", _async_return(True)),
        )

        async def _device_quota_script(_script: str, *_args):
            return True

        driver.execute_script = _device_quota_script

        assert await submission.consume_submission_success_signal(driver)
        assert await submission.is_device_quota_limit_page(driver)
        assert reads == ["peek", "peek"]

    @pytest.mark.asyncio
    async def test_status_helpers_return_false_when_detection_fails(self, patch_attrs) -> None:
        driver = _FakeDriver()
        reads: list[str] = []
        patch_attrs(
            (submission, "peek_qq_runtime_state", lambda _driver: reads.append("peek") or None),
            (submission, "qq_is_completion_page", _async_return(False)),
        )

        async def _device_quota_script(_script: str, *_args):
            raise RuntimeError("js failed")

        driver.execute_script = _device_quota_script

        assert not await submission.consume_submission_success_signal(driver)
        assert not await submission.is_device_quota_limit_page(driver)
        assert reads == ["peek", "peek"]

    @pytest.mark.asyncio
    async def test_attempt_submission_recovery_refills_questions_and_resubmits_once(self, patch_attrs) -> None:
        driver = _FakeDriver()
        state = ExecutionState(config=ExecutionConfig(survey_provider="qq"))
        state.config.questions_metadata = {
            3: SurveyQuestionMeta(num=3, title="Q3", provider="qq", provider_question_id="q3", required=True),
            4: SurveyQuestionMeta(num=4, title="Q4", provider="qq", provider_question_id="q4", required=True),
        }
        runtime_state = SimpleNamespace(
            page_index=1,
            page_question_ids=["q3", "q4"],
            psycho_plan="plan",
            submission_recovery_attempts=0,
        )
        refill_calls: list[tuple[list[int], str, Any]] = []
        submit_calls: list[str] = []
        patch_attrs(
            (submission, "qq_submission_requires_verification", _async_return(False)),
            (submission, "peek_qq_runtime_state", lambda _driver: runtime_state),
            (
                submission,
                "_extract_submission_recovery_hint",
                _async_return(submission.SubmissionRecoveryHint((3, 4), "请填写")),
            ),
            (
                submission,
                "submit",
                _async_return(None),
            ),
        )

        async def _submit(_driver, ctx=None, stop_signal=None):
            del stop_signal
            submit_calls.append(ctx.config.survey_provider if ctx else "")

        patch_attrs((submission, "submit", _submit))

        from tencent.provider import runtime as qq_runtime

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                qq_runtime,
                "refill_required_questions_on_current_page",
                _async_return(2),
            )

            async def _refill(_driver, ctx, *, question_numbers, thread_name, psycho_plan):
                refill_calls.append((list(question_numbers), thread_name, psycho_plan))
                return 2

            mp.setattr(qq_runtime, "refill_required_questions_on_current_page", _refill)
            recovered = await submission.attempt_submission_recovery(
                driver,
                state,
                None,
                threading.Event(),
                thread_name="Worker-1",
            )

        assert recovered is True
        assert runtime_state.submission_recovery_attempts == 1
        assert refill_calls == [([3, 4], "Worker-1", "plan")]
        assert submit_calls == ["qq"]

    @pytest.mark.asyncio
    async def test_attempt_submission_recovery_falls_back_to_current_page_required_questions(self, patch_attrs) -> None:
        driver = _FakeDriver()
        state = ExecutionState(config=ExecutionConfig(survey_provider="qq"))
        state.config.questions_metadata = {
            3: SurveyQuestionMeta(num=3, title="Q3", provider="qq", provider_question_id="q3", required=True),
            4: SurveyQuestionMeta(num=4, title="Q4", provider="qq", provider_question_id="q4", required=False),
        }
        runtime_state = SimpleNamespace(
            page_index=1,
            page_question_ids=["q3", "q4"],
            psycho_plan=None,
            submission_recovery_attempts=0,
        )
        refill_calls: list[list[int]] = []
        patch_attrs(
            (submission, "qq_submission_requires_verification", _async_return(False)),
            (submission, "peek_qq_runtime_state", lambda _driver: runtime_state),
            (
                submission,
                "_extract_submission_recovery_hint",
                _async_return(submission.SubmissionRecoveryHint((), "此题必填")),
            ),
            (submission, "submit", _async_return(None)),
        )

        from tencent.provider import runtime as qq_runtime

        with pytest.MonkeyPatch.context() as mp:
            async def _refill(_driver, ctx, *, question_numbers, thread_name, psycho_plan):
                del ctx, thread_name, psycho_plan
                refill_calls.append(list(question_numbers))
                return 1

            mp.setattr(qq_runtime, "refill_required_questions_on_current_page", _refill)
            recovered = await submission.attempt_submission_recovery(
                driver,
                state,
                None,
                threading.Event(),
                thread_name="Worker-1",
            )

        assert recovered is True
        assert refill_calls == [[3]]

    @pytest.mark.asyncio
    async def test_attempt_submission_recovery_stops_when_no_question_was_refilled(self, patch_attrs) -> None:
        driver = _FakeDriver()
        state = ExecutionState(config=ExecutionConfig(survey_provider="qq"))
        runtime_state = SimpleNamespace(
            page_index=1,
            page_question_ids=["q3"],
            psycho_plan=None,
            submission_recovery_attempts=0,
        )
        submit_calls: list[str] = []
        async def _submit(*_args, **_kwargs):
            submit_calls.append("submit")

        patch_attrs(
            (submission, "qq_submission_requires_verification", _async_return(False)),
            (submission, "peek_qq_runtime_state", lambda _driver: runtime_state),
            (
                submission,
                "_extract_submission_recovery_hint",
                _async_return(submission.SubmissionRecoveryHint((3,), "请填写")),
            ),
            (submission, "submit", _submit),
        )

        from tencent.provider import runtime as qq_runtime

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                qq_runtime,
                "refill_required_questions_on_current_page",
                _async_return(0),
            )
            recovered = await submission.attempt_submission_recovery(
                driver,
                state,
                None,
                threading.Event(),
                thread_name="Worker-1",
            )

        assert recovered is False
        assert runtime_state.submission_recovery_attempts == 0
        assert submit_calls == []

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from software.core.engine.failure_reason import FailureReason
from software.core.engine.runtime_actions import RuntimeActionKind, RuntimeActionRequest, RuntimeActionResult
from software.core.engine.submission_service import SubmissionService
from software.core.task import ExecutionConfig, ExecutionState


class _FakeDriver:
    def __init__(self, current_url: str = "https://example.com/form") -> None:
        self.browser_name = "edge"
        self.session_id = "test-session"
        self.browser_pid: int | None = None
        self.browser_pids: set[int] = set()
        self._current_url = current_url
        self.session_proxy_address = ""
        self.submit_proxy_address = ""
        self.thread_name = ""

    async def current_url(self) -> str:
        return self._current_url


class _RuntimeActionAdapter:
    def __init__(self) -> None:
        self.results: list[RuntimeActionResult] = []

    def handle_runtime_actions(self, result: RuntimeActionResult) -> None:
        self.results.append(result)


class SubmissionServiceTests:
    @pytest.mark.asyncio
    async def test_wait_for_completion_page_stops_immediately_when_stop_requested(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(headless_mode=False, survey_provider="wjx")
        state = ExecutionState(config=config)
        service = SubmissionService(config, state, make_stop_policy_mock())
        stop_signal = make_mock_event(is_set=True)

        completed = await service._wait_for_completion_page(
            driver=_FakeDriver("https://example.com/form"),
            stop_signal=stop_signal,
            max_wait_seconds=3,
            poll_interval=0.1,
        )

        assert not completed

    @pytest.mark.asyncio
    async def test_finalize_after_submit_returns_fast_success_when_completion_is_detected_immediately(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(headless_mode=True, random_proxy_ip_enabled=True, survey_provider="wjx")
        state = ExecutionState(config=config)
        stop_policy = make_stop_policy_mock(record_success_return=False)
        service = SubmissionService(config, state, stop_policy)
        stop_signal = make_mock_event()
        driver = _FakeDriver()
        driver.session_proxy_address = "http://1.1.1.1:8000"
        driver.thread_name = "Worker-1"

        with (
            patch.object(service, "_detect_completion_once", new=AsyncMock(return_value=True)) as detect_mock,
            patch("software.core.engine.submission_service.random.uniform", return_value=0.2),
        ):
            outcome = await service.finalize_after_submit(driver, stop_signal=stop_signal, gui_instance=None, thread_name="Worker-1")

        assert outcome.status == "success"
        assert outcome.completion_detected
        assert outcome.should_rotate_proxy
        assert state.is_successful_proxy_address("http://1.1.1.1:8000")
        detect_mock.assert_awaited_once()
        stop_policy.record_success.assert_called_once_with(stop_signal, thread_name="Worker-1")

    @pytest.mark.asyncio
    async def test_finalize_after_submit_returns_aborted_when_user_stops_during_initial_wait(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(headless_mode=False, survey_provider="wjx")
        state = ExecutionState(config=config)
        stop_policy = make_stop_policy_mock()
        service = SubmissionService(config, state, stop_policy)
        stop_signal = make_mock_event(wait_return=True)

        with patch("software.core.engine.submission_service.random.uniform", return_value=0.2):
            outcome = await service.finalize_after_submit(_FakeDriver(), stop_signal=stop_signal, gui_instance=None, thread_name="Worker-1")

        assert outcome.status == "aborted"
        assert outcome.failure_reason == FailureReason.USER_STOPPED
        assert outcome.should_stop

    @pytest.mark.asyncio
    async def test_finalize_after_submit_marks_failure_when_completion_never_appears(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(headless_mode=False, survey_provider="wjx")
        state = ExecutionState(config=config)
        stop_policy = make_stop_policy_mock(record_failure_return=True)
        service = SubmissionService(config, state, stop_policy)
        stop_signal = make_mock_event()

        with (
            patch("software.core.engine.submission_service._provider_submission_requires_verification", new=AsyncMock(return_value=False)),
            patch("software.core.engine.submission_service._provider_wait_for_submission_verification", new=AsyncMock(return_value=False)),
            patch.object(service, "_wait_for_completion_page", new=AsyncMock(side_effect=[False])),
            patch("software.core.engine.submission_service.duration_control.is_survey_completion_page", new=AsyncMock(return_value=False)),
            patch("software.core.engine.submission_service.random.uniform", return_value=0.2),
        ):
            outcome = await service.finalize_after_submit(
                _FakeDriver("https://example.com/form"),
                stop_signal=stop_signal,
                gui_instance=None,
                thread_name="Worker-1",
            )

        assert outcome.status == "failure"
        assert outcome.failure_reason == FailureReason.FILL_FAILED
        assert not outcome.completion_detected
        assert outcome.should_stop
        stop_policy.record_failure.assert_called_once()

    @pytest.mark.asyncio
    async def test_finalize_after_submit_uses_conservative_wjx_completion_wait(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(headless_mode=False, survey_provider="wjx")
        state = ExecutionState(config=config)
        service = SubmissionService(config, state, make_stop_policy_mock())
        stop_signal = make_mock_event()

        with (
            patch("software.core.engine.submission_service._provider_submission_requires_verification", new=AsyncMock(return_value=False)),
            patch("software.core.engine.submission_service._provider_wait_for_submission_verification", new=AsyncMock(return_value=False)),
            patch.object(service, "_detect_completion_once", new=AsyncMock(return_value=False)),
            patch.object(service, "_wait_for_completion_page", new=AsyncMock(return_value=True)) as wait_mock,
            patch("software.core.engine.submission_service.random.uniform", return_value=0.2),
        ):
            outcome = await service.finalize_after_submit(
                _FakeDriver("https://example.com/form"),
                stop_signal=stop_signal,
                gui_instance=None,
                thread_name="Worker-1",
            )

        assert outcome.status == "success"
        wait_mock.assert_awaited_once()
        assert wait_mock.await_args.args[2] >= 5.0

    @pytest.mark.asyncio
    async def test_finalize_after_submit_reports_submission_verification(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(survey_provider="qq")
        state = ExecutionState(config=config)
        stop_policy = make_stop_policy_mock(record_failure_return=True)
        service = SubmissionService(config, state, stop_policy)
        stop_signal = make_mock_event()

        runtime_adapter = _RuntimeActionAdapter()
        action_result = RuntimeActionResult.from_actions(
            [RuntimeActionRequest(RuntimeActionKind.SHOW_MESSAGE, "提示", "命中", "warning")],
            should_stop=True,
        )

        with (
            patch("software.core.engine.submission_service._provider_submission_requires_verification", new=AsyncMock(return_value=True)),
            patch("software.core.engine.submission_service._provider_submission_validation_message", new=AsyncMock(return_value="命中腾讯安全验证")),
            patch("software.core.engine.submission_service._provider_handle_submission_verification_detected", new=AsyncMock(return_value=action_result)) as handle_mock,
            patch("software.core.engine.submission_service.random.uniform", return_value=0.2),
        ):
            outcome = await service.finalize_after_submit(_FakeDriver(), stop_signal=stop_signal, gui_instance=runtime_adapter, thread_name="Worker-1")

        assert outcome.status == "failure"
        assert outcome.failure_reason == FailureReason.SUBMISSION_VERIFICATION_REQUIRED
        assert state.get_terminal_stop_snapshot()[0] == "submission_verification"
        assert outcome.should_stop
        handle_mock.assert_awaited_once()
        assert runtime_adapter.results == [action_result]

    @pytest.mark.asyncio
    async def test_check_submission_verification_after_submit_ignores_waiter_exception(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(headless_mode=False, survey_provider="wjx")
        state = ExecutionState(config=config)
        service = SubmissionService(config, state, make_stop_policy_mock())
        stop_signal = make_mock_event()

        with patch("software.core.engine.submission_service._provider_wait_for_submission_verification", new=AsyncMock(side_effect=RuntimeError("boom"))):
            outcome = await service._check_submission_verification_after_submit(
                driver=_FakeDriver(),
                stop_signal=stop_signal,
                gui_instance=None,
                thread_name="Worker-1",
            )

        assert outcome is None

    @pytest.mark.asyncio
    async def test_finalize_after_submit_retries_once_after_provider_recovery(self, make_mock_event, make_stop_policy_mock) -> None:
        config = ExecutionConfig(headless_mode=False, survey_provider="qq")
        state = ExecutionState(config=config)
        stop_policy = make_stop_policy_mock(record_success_return=False)
        service = SubmissionService(config, state, stop_policy)
        stop_signal = make_mock_event()
        driver = _FakeDriver("https://example.com/form")

        with (
            patch("software.core.engine.submission_service._provider_submission_requires_verification", new=AsyncMock(return_value=False)),
            patch.object(service, "_check_submission_verification_after_submit", new=AsyncMock(return_value=None)),
            patch.object(service, "_wait_for_completion_page", new=AsyncMock(side_effect=[False, True])),
            patch.object(service, "_attempt_submission_recovery", new=AsyncMock(return_value=True)) as recovery_mock,
            patch("software.core.engine.submission_service.random.uniform", return_value=0.2),
        ):
            outcome = await service.finalize_after_submit(
                driver,
                stop_signal=stop_signal,
                gui_instance=None,
                thread_name="Worker-1",
            )

        assert outcome.status == "success"
        assert outcome.completion_detected
        recovery_mock.assert_awaited_once_with(driver, stop_signal, None, thread_name="Worker-1")
        stop_policy.record_success.assert_called_once_with(stop_signal, thread_name="Worker-1")

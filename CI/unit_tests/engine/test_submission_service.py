from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from software.core.engine.failure_reason import FailureReason
from software.core.engine.submission_service import SubmissionService
from software.core.task import ExecutionConfig, ExecutionState


class SubmissionServiceTests(unittest.TestCase):
    def test_finalize_after_submit_returns_headless_success_signal(self) -> None:
        config = ExecutionConfig(headless_mode=True, random_proxy_ip_enabled=True, survey_provider="wjx")
        state = ExecutionState(config=config)
        stop_policy = MagicMock()
        stop_policy.record_success.return_value = False
        service = SubmissionService(config, state, stop_policy)
        stop_signal = MagicMock()
        stop_signal.is_set.return_value = False
        driver = object()

        with patch("software.core.engine.submission_service._provider_consume_submission_success_signal", return_value=True), \
             patch("software.core.engine.submission_service.time.sleep") as sleep_mock:
            outcome = service.finalize_after_submit(
                driver,
                stop_signal=stop_signal,
                gui_instance=None,
                thread_name="Worker-1",
            )

        self.assertEqual(outcome.status, "success")
        self.assertTrue(outcome.completion_detected)
        self.assertTrue(outcome.should_rotate_proxy)
        stop_policy.record_success.assert_called_once_with(stop_signal, thread_name="Worker-1")
        sleep_mock.assert_called()

    def test_finalize_after_submit_marks_failure_when_completion_never_appears(self) -> None:
        config = ExecutionConfig(headless_mode=False, survey_provider="wjx")
        state = ExecutionState(config=config)
        stop_policy = MagicMock()
        stop_policy.record_failure.return_value = True
        service = SubmissionService(config, state, stop_policy)
        stop_signal = MagicMock(spec=threading.Event)
        stop_signal.is_set.return_value = False
        stop_signal.wait.return_value = False
        driver = SimpleNamespace(current_url="https://example.com/form")

        with patch("software.core.engine.submission_service._provider_consume_submission_success_signal", return_value=False), \
             patch("software.core.engine.submission_service._provider_submission_requires_verification", return_value=False), \
             patch("software.core.engine.submission_service._provider_wait_for_submission_verification", return_value=False), \
             patch.object(service, "_wait_for_completion_page", side_effect=[False, False]), \
             patch("software.core.engine.submission_service.duration_control.is_survey_completion_page", return_value=False), \
             patch("software.core.engine.submission_service.random.uniform", return_value=0.2):
            outcome = service.finalize_after_submit(
                driver,
                stop_signal=stop_signal,
                gui_instance=None,
                thread_name="Worker-1",
            )

        self.assertEqual(outcome.status, "failure")
        self.assertEqual(outcome.failure_reason, FailureReason.FILL_FAILED)
        self.assertFalse(outcome.completion_detected)
        self.assertTrue(outcome.should_stop)
        stop_policy.record_failure.assert_called_once()

    def test_finalize_after_submit_treats_complete_url_as_success_after_waits(self) -> None:
        config = ExecutionConfig(headless_mode=False, survey_provider="wjx")
        state = ExecutionState(config=config)
        stop_policy = MagicMock()
        stop_policy.record_success.return_value = True
        service = SubmissionService(config, state, stop_policy)
        stop_signal = MagicMock(spec=threading.Event)
        stop_signal.is_set.return_value = False
        stop_signal.wait.return_value = False
        driver = SimpleNamespace(current_url="https://example.com/complete")

        with patch("software.core.engine.submission_service._provider_consume_submission_success_signal", return_value=False), \
             patch("software.core.engine.submission_service._provider_submission_requires_verification", return_value=False), \
             patch("software.core.engine.submission_service._provider_wait_for_submission_verification", return_value=False), \
             patch.object(service, "_wait_for_completion_page", side_effect=[False, False]), \
             patch("software.core.engine.submission_service.random.uniform", return_value=0.2), \
             patch("software.core.engine.submission_service.time.sleep"):
            outcome = service.finalize_after_submit(
                driver,
                stop_signal=stop_signal,
                gui_instance=None,
                thread_name="Worker-1",
            )

        self.assertEqual(outcome.status, "success")
        self.assertTrue(outcome.completion_detected)
        self.assertTrue(outcome.should_stop)
        stop_policy.record_success.assert_called_once_with(stop_signal, thread_name="Worker-1")

    def test_finalize_after_submit_treats_provider_completion_page_as_success_after_waits(self) -> None:
        config = ExecutionConfig(headless_mode=False, survey_provider="wjx")
        state = ExecutionState(config=config)
        stop_policy = MagicMock()
        stop_policy.record_success.return_value = False
        service = SubmissionService(config, state, stop_policy)
        stop_signal = MagicMock(spec=threading.Event)
        stop_signal.is_set.return_value = False
        stop_signal.wait.return_value = False
        driver = SimpleNamespace(current_url="https://example.com/form")

        with patch("software.core.engine.submission_service._provider_consume_submission_success_signal", return_value=False), \
             patch("software.core.engine.submission_service._provider_submission_requires_verification", return_value=False), \
             patch("software.core.engine.submission_service._provider_wait_for_submission_verification", return_value=False), \
             patch.object(service, "_wait_for_completion_page", side_effect=[False, False]), \
             patch("software.core.engine.submission_service.duration_control.is_survey_completion_page", return_value=True), \
             patch("software.core.engine.submission_service.random.uniform", return_value=0.2), \
             patch("software.core.engine.submission_service.time.sleep"):
            outcome = service.finalize_after_submit(
                driver,
                stop_signal=stop_signal,
                gui_instance=None,
                thread_name="Worker-1",
            )

        self.assertEqual(outcome.status, "success")
        self.assertTrue(outcome.completion_detected)
        self.assertFalse(outcome.should_stop)
        stop_policy.record_success.assert_called_once_with(stop_signal, thread_name="Worker-1")

    def test_finalize_after_submit_reports_submission_verification(self) -> None:
        config = ExecutionConfig(survey_provider="qq")
        state = ExecutionState(config=config)
        stop_policy = MagicMock()
        stop_policy.record_failure.return_value = True
        service = SubmissionService(config, state, stop_policy)
        stop_signal = MagicMock(spec=threading.Event)
        stop_signal.is_set.return_value = False
        stop_signal.wait.return_value = False
        driver = object()

        with patch("software.core.engine.submission_service._provider_consume_submission_success_signal", return_value=False), \
             patch("software.core.engine.submission_service._provider_submission_requires_verification", return_value=True), \
             patch("software.core.engine.submission_service._provider_submission_validation_message", return_value="命中腾讯安全验证"), \
             patch("software.core.engine.submission_service._provider_handle_submission_verification_detected") as handle_mock, \
             patch("software.core.engine.submission_service.random.uniform", return_value=0.2):
            outcome = service.finalize_after_submit(
                driver,
                stop_signal=stop_signal,
                gui_instance=object(),
                thread_name="Worker-1",
            )

        self.assertEqual(outcome.status, "failure")
        self.assertEqual(outcome.failure_reason, FailureReason.SUBMISSION_VERIFICATION_REQUIRED)
        self.assertEqual(state.get_terminal_stop_snapshot()[0], "submission_verification")
        self.assertTrue(outcome.should_stop)
        handle_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()

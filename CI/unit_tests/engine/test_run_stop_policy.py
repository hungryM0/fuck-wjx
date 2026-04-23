from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from software.core.engine.failure_reason import FailureReason
from software.core.engine.run_stop_policy import RunStopPolicy
from software.core.task import ExecutionConfig, ExecutionState


class RunStopPolicyTests(unittest.TestCase):
    def test_record_failure_stops_after_reaching_threshold(self) -> None:
        config = ExecutionConfig(fail_threshold=2, stop_on_fail_enabled=True)
        state = ExecutionState(config=config, cur_fail=1)
        state.release_joint_sample = MagicMock(return_value=None)
        state.increment_thread_fail = MagicMock(side_effect=state.increment_thread_fail)
        policy = RunStopPolicy(config, state)
        stop_signal = threading.Event()

        stopped = policy.record_failure(
            stop_signal,
            thread_name="Worker-1",
            failure_reason=FailureReason.FILL_FAILED,
            log_message="boom",
        )

        self.assertTrue(stopped)
        self.assertTrue(stop_signal.is_set())
        self.assertEqual(state.cur_fail, 2)
        self.assertEqual(state.get_terminal_stop_snapshot()[0], "fail_threshold")
        self.assertEqual(state.get_terminal_stop_snapshot()[1], FailureReason.FILL_FAILED.value)
        state.release_joint_sample.assert_called_once_with("Worker-1")
        state.increment_thread_fail.assert_called_once()

    def test_record_success_commits_progress_and_triggers_target_stop(self) -> None:
        config = ExecutionConfig(target_num=1, random_proxy_ip_enabled=True)
        state = ExecutionState(config=config, cur_fail=2)
        state.joint_reserved_sample_by_thread["Worker-1"] = 0
        state.distribution_pending_by_thread["Worker-1"] = [("q:1", 1, 3)]
        gui = SimpleNamespace(handle_random_ip_submission=MagicMock())
        policy = RunStopPolicy(config, state, gui)
        stop_signal = threading.Event()

        with patch("software.core.engine.run_stop_policy._event_bus.emit") as emit_mock:
            should_stop = policy.record_success(stop_signal, thread_name="Worker-1")

        self.assertTrue(should_stop)
        self.assertEqual(state.cur_num, 1)
        self.assertEqual(state.cur_fail, 0)
        self.assertIn(0, state.joint_committed_sample_indexes)
        self.assertEqual(state.distribution_runtime_stats["q:1"]["total"], 1)
        self.assertTrue(stop_signal.is_set())
        self.assertEqual(state.get_terminal_stop_snapshot()[0], "target_reached")
        gui.handle_random_ip_submission.assert_called_once_with(stop_signal)
        emit_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()

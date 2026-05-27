from __future__ import annotations
import threading
from software.core.engine.failure_reason import FailureReason
from software.core.engine.run_stop_policy import RunStopPolicy
from software.core.reverse_fill.schema import ReverseFillSampleRow, ReverseFillSpec
from software.core.task import ExecutionConfig, ExecutionState

class RunStopPolicyTests:

    def _build_reverse_fill_state(self) -> ExecutionState:
        spec = ReverseFillSpec(source_path='demo.xlsx', selected_format='wjx_sequence', detected_format='wjx_sequence', start_row=1, total_samples=1, available_samples=1, target_num=1, samples=[ReverseFillSampleRow(data_row_number=1, worksheet_row_number=2, answers={})])
        state = ExecutionState(config=ExecutionConfig(reverse_fill_spec=spec, target_num=1))
        state.initialize_reverse_fill_runtime()
        return state

    def test_record_failure_stops_after_reaching_threshold(self, make_callable_mock) -> None:
        config = ExecutionConfig(fail_threshold=2, stop_on_fail_enabled=True)
        state = ExecutionState(config=config, cur_fail=1)
        increment_thread_fail = state.increment_thread_fail
        state.release_joint_sample = make_callable_mock(return_value=None)
        state.increment_thread_fail = make_callable_mock(side_effect=increment_thread_fail)
        policy = RunStopPolicy(config, state)
        stop_signal = threading.Event()
        stopped = policy.record_failure(stop_signal, thread_name='Worker-1', failure_reason=FailureReason.FILL_FAILED, log_message='boom')
        assert stopped
        assert stop_signal.is_set()
        assert state.cur_fail == 2
        assert state.get_terminal_stop_snapshot()[0] == 'fail_threshold'
        assert state.get_terminal_stop_snapshot()[1] == FailureReason.FILL_FAILED.value
        state.release_joint_sample.assert_called_once_with('Worker-1')
        state.increment_thread_fail.assert_called_once()

    def test_record_failure_requeues_reverse_fill_row_on_first_failure(self) -> None:
        state = self._build_reverse_fill_state()
        config = state.config
        state.acquire_reverse_fill_sample('Worker-1')
        policy = RunStopPolicy(config, state)
        stop_signal = threading.Event()
        stopped = policy.record_failure(stop_signal, thread_name='Worker-1', failure_reason=FailureReason.FILL_FAILED)
        assert not stopped
        assert not stop_signal.is_set()
        assert list(state.reverse_fill_runtime.queued_row_numbers) == [1]

    def test_record_failure_requeues_reverse_fill_row_without_consuming_attempt(self) -> None:
        state = self._build_reverse_fill_state()
        config = state.config
        state.acquire_reverse_fill_sample('Worker-1')
        policy = RunStopPolicy(config, state)
        stop_signal = threading.Event()
        stopped = policy.record_failure(stop_signal, thread_name='Worker-1', failure_reason=FailureReason.PROXY_UNAVAILABLE, consume_reverse_fill_attempt=False)
        assert not stopped
        assert not stop_signal.is_set()
        assert list(state.reverse_fill_runtime.queued_row_numbers) == [1]
        assert state.reverse_fill_runtime.failure_count_by_row == {}
        assert state.reverse_fill_runtime.discarded_row_numbers == set()

    def test_proxy_unavailable_threshold_scales_with_random_proxy_concurrency(self) -> None:
        config = ExecutionConfig(fail_threshold=5, num_threads=32, random_proxy_ip_enabled=True)
        state = ExecutionState(config=config, cur_fail=4)
        policy = RunStopPolicy(config, state)
        stop_signal = threading.Event()
        stopped = policy.record_failure(stop_signal, thread_name='Slot-1', failure_reason=FailureReason.PROXY_UNAVAILABLE, threshold_override=policy.proxy_unavailable_threshold(), terminal_stop_category='proxy_unavailable_threshold', consume_reverse_fill_attempt=False)
        assert not stopped
        assert not stop_signal.is_set()
        assert state.cur_fail == 4
        assert state.proxy_unavailable_fail_count == 1
        assert state.get_terminal_stop_snapshot()[0] == ''

    def test_failure_threshold_uses_half_concurrency_when_threads_above_ten(self) -> None:
        config = ExecutionConfig(fail_threshold=5, num_threads=32, stop_on_fail_enabled=True)
        state = ExecutionState(config=config, cur_fail=15)
        policy = RunStopPolicy(config, state)
        stop_signal = threading.Event()
        stopped = policy.record_failure(stop_signal, thread_name='Slot-1', failure_reason=FailureReason.FILL_FAILED)
        assert stopped
        assert stop_signal.is_set()
        assert state.cur_fail == 16
        assert state.get_terminal_stop_snapshot()[0] == 'fail_threshold'

    def test_failure_threshold_keeps_config_value_when_threads_not_above_ten(self) -> None:
        config = ExecutionConfig(fail_threshold=5, num_threads=10, stop_on_fail_enabled=True)
        state = ExecutionState(config=config, cur_fail=4)
        policy = RunStopPolicy(config, state)
        stop_signal = threading.Event()
        stopped = policy.record_failure(stop_signal, thread_name='Slot-1', failure_reason=FailureReason.FILL_FAILED)
        assert stopped
        assert stop_signal.is_set()
        assert state.cur_fail == 5
        assert state.get_terminal_stop_snapshot()[0] == 'fail_threshold'

    def test_proxy_unavailable_uses_independent_counter(self) -> None:
        config = ExecutionConfig(fail_threshold=5, num_threads=8, random_proxy_ip_enabled=True)
        state = ExecutionState(config=config, cur_fail=3, proxy_unavailable_fail_count=7)
        policy = RunStopPolicy(config, state)
        stop_signal = threading.Event()
        stopped = policy.record_failure(stop_signal, thread_name='Slot-2', failure_reason=FailureReason.PROXY_UNAVAILABLE, threshold_override=policy.proxy_unavailable_threshold(), terminal_stop_category='proxy_unavailable_threshold', consume_reverse_fill_attempt=False)
        assert stopped
        assert stop_signal.is_set()
        assert state.cur_fail == 3
        assert state.proxy_unavailable_fail_count == 8
        assert state.get_terminal_stop_snapshot()[0] == 'proxy_unavailable_threshold'

    def test_record_success_commits_progress_and_triggers_target_stop(self, make_gui_mock) -> None:
        config = ExecutionConfig(target_num=1, random_proxy_ip_enabled=True)
        state = ExecutionState(config=config, cur_fail=2)
        state.joint_reserved_sample_by_thread['Worker-1'] = 0
        state.distribution_pending_by_thread['Worker-1'] = [('q:1', 1, 3)]
        gui = make_gui_mock('handle_random_ip_submission')
        policy = RunStopPolicy(config, state, gui)
        stop_signal = threading.Event()
        should_stop = policy.record_success(stop_signal, thread_name='Worker-1')
        assert should_stop
        assert state.cur_num == 1
        assert state.cur_fail == 0
        assert state.proxy_unavailable_fail_count == 0
        assert 0 in state.joint_committed_sample_indexes
        assert state.distribution_runtime_stats['q:1']['total'] == 1
        assert stop_signal.is_set()
        assert state.get_terminal_stop_snapshot()[0] == 'target_reached'
        gui.handle_random_ip_submission.assert_called_once_with(stop_signal)

    def test_record_success_commits_reverse_fill_row(self, make_gui_mock) -> None:
        state = self._build_reverse_fill_state()
        config = state.config
        state.acquire_reverse_fill_sample('Worker-1')
        gui = make_gui_mock('handle_random_ip_submission')
        policy = RunStopPolicy(config, state, gui)
        stop_signal = threading.Event()
        should_stop = policy.record_success(stop_signal, thread_name='Worker-1')
        assert should_stop
        assert 1 in state.reverse_fill_runtime.committed_row_numbers

    def test_record_failure_stops_when_reverse_fill_sample_is_exhausted(self) -> None:
        spec = ReverseFillSpec(source_path='demo.xlsx', selected_format='wjx_sequence', detected_format='wjx_sequence', start_row=1, total_samples=2, available_samples=2, target_num=2, samples=[ReverseFillSampleRow(data_row_number=1, worksheet_row_number=2, answers={}), ReverseFillSampleRow(data_row_number=2, worksheet_row_number=3, answers={})])
        state = ExecutionState(config=ExecutionConfig(reverse_fill_spec=spec, target_num=2), cur_num=1)
        state.initialize_reverse_fill_runtime()
        state.acquire_reverse_fill_sample('Worker-9')
        state.commit_reverse_fill_sample('Worker-9')
        state.acquire_reverse_fill_sample('Worker-1')
        policy = RunStopPolicy(state.config, state)
        stop_signal = threading.Event()
        first_stopped = policy.record_failure(stop_signal, thread_name='Worker-1', failure_reason=FailureReason.FILL_FAILED)
        assert not first_stopped
        assert not stop_signal.is_set()
        state.acquire_reverse_fill_sample('Worker-1')
        second_stopped = policy.record_failure(stop_signal, thread_name='Worker-1', failure_reason=FailureReason.FILL_FAILED)
        assert second_stopped
        assert stop_signal.is_set()
        assert 2 in state.reverse_fill_runtime.discarded_row_numbers
        assert state.get_terminal_stop_snapshot()[0] == 'reverse_fill_exhausted'

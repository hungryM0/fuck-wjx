from __future__ import annotations
import asyncio
import threading
import time
from software.core.task import ExecutionState, ProxyLease

class ExecutionStateConcurrencyTests:

    def test_wait_for_runtime_change_returns_false_after_notify(self) -> None:
        state = ExecutionState()
        result: dict[str, bool] = {}

        def _waiter() -> None:
            result['value'] = state.wait_for_runtime_change(timeout=1.0)
        worker = threading.Thread(target=_waiter, name='RuntimeWaiter')
        worker.start()
        time.sleep(0.05)
        state.notify_runtime_change()
        worker.join(timeout=1.0)
        assert not worker.is_alive()
        assert not result['value']

    def test_wait_for_runtime_change_returns_true_when_stop_signal_is_set_during_wait(self) -> None:
        state = ExecutionState()
        stop_signal = threading.Event()
        result: dict[str, bool] = {}

        def _waiter() -> None:
            result['value'] = state.wait_for_runtime_change(stop_signal=stop_signal, timeout=1.0)
        worker = threading.Thread(target=_waiter, name='RuntimeStopWaiter')
        worker.start()
        time.sleep(0.05)
        stop_signal.set()
        state.notify_runtime_change()
        worker.join(timeout=1.0)
        assert not worker.is_alive()
        assert result['value']

    def test_wait_for_runtime_change_async_returns_false_after_notify(self) -> None:
        async def _run() -> bool:
            state = ExecutionState()
            waiter = asyncio.create_task(state.wait_for_runtime_change_async(timeout=1.0))
            await asyncio.sleep(0)
            state.notify_runtime_change()
            return await waiter

        assert asyncio.run(_run()) is False

    def test_wait_for_runtime_change_async_returns_true_when_stop_signal_is_set(self) -> None:
        async def _run() -> bool:
            state = ExecutionState()
            stop_signal = threading.Event()
            waiter = asyncio.create_task(
                state.wait_for_runtime_change_async(stop_signal=stop_signal, timeout=1.0)
            )
            await asyncio.sleep(0)
            stop_signal.set()
            state.notify_runtime_change()
            return await waiter

        assert asyncio.run(_run()) is True

    def test_register_and_unregister_proxy_waiter_stays_consistent_under_concurrency(self) -> None:
        state = ExecutionState()
        barrier = threading.Barrier(8)

        def _worker() -> None:
            barrier.wait()
            for _ in range(50):
                state.register_proxy_waiter()
                time.sleep(0.001)
                state.unregister_proxy_waiter()
        threads = [threading.Thread(target=_worker, name=f'ProxyWaiter-{idx}') for idx in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2.0)
        assert all((not thread.is_alive() for thread in threads))
        assert state.proxy_waiting_threads == 0

    def test_reserve_joint_sample_returns_unique_values_under_concurrency(self) -> None:
        state = ExecutionState()
        barrier = threading.Barrier(5)
        results: dict[str, int | None] = {}
        result_lock = threading.Lock()

        def _worker(name: str) -> None:
            barrier.wait()
            value = state.reserve_joint_sample(3, thread_name=name)
            with result_lock:
                results[name] = value
        threads = [threading.Thread(target=_worker, args=(f'Worker-{idx}',), name=f'Worker-{idx}') for idx in range(1, 6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2.0)
        acquired = [value for value in results.values() if value is not None]
        assert len(acquired) == 3
        assert len(set(acquired)) == 3
        assert sum((value is None for value in results.values())) == 2

    def test_joint_sample_quota_status_distinguishes_allocated_from_exhausted(self) -> None:
        state = ExecutionState()
        assert not state.is_joint_sample_quota_exhausted(2)

        assert state.reserve_joint_sample(2, thread_name='Worker-1') == 0
        assert not state.is_joint_sample_quota_exhausted(2)

        state.commit_joint_sample('Worker-1')
        assert not state.is_joint_sample_quota_exhausted(2)

        assert state.reserve_joint_sample(2, thread_name='Worker-2') == 1
        assert not state.is_joint_sample_quota_exhausted(2)

        state.commit_joint_sample('Worker-2')
        assert state.is_joint_sample_quota_exhausted(2)

    def test_expire_stale_joint_sample_reservations_skips_answering_threads(self) -> None:
        state = ExecutionState()
        released_reverse: list[tuple[str, bool]] = []
        state.release_reverse_fill_sample = lambda thread_name, *, requeue=True: released_reverse.append((thread_name, requeue))

        assert state.reserve_joint_sample(2, thread_name='Worker-1') == 0
        assert state.reserve_joint_sample(2, thread_name='Worker-2') == 1
        assert state.mark_joint_sample_answering('Worker-2')
        state.joint_reserved_sample_started_at_by_thread['Worker-1'] = 1.0
        state.joint_reserved_sample_started_at_by_thread['Worker-2'] = 1.0

        expired = state.expire_stale_joint_sample_reservations(0.001)

        assert expired == 1
        assert state.peek_reserved_joint_sample('Worker-1') is None
        assert state.peek_reserved_joint_sample('Worker-2') == 1
        assert released_reverse == [('Worker-1', True)]

    def test_release_proxy_in_use_notifies_waiting_threads(self) -> None:
        state = ExecutionState()
        state.mark_proxy_in_use('Worker-1', ProxyLease(address='http://1.1.1.1:8000'))
        result: dict[str, bool] = {}

        def _waiter() -> None:
            result['value'] = state.wait_for_runtime_change(timeout=1.0)
        worker = threading.Thread(target=_waiter, name='ProxyReleaseWaiter')
        worker.start()
        time.sleep(0.05)
        released = state.release_proxy_in_use('Worker-1')
        worker.join(timeout=1.0)
        assert released is not None
        assert not worker.is_alive()
        assert not result['value']
        assert state.snapshot_active_proxy_addresses() == set()

    def test_mark_successful_proxy_address_blocks_future_reuse(self) -> None:
        state = ExecutionState()
        changed = state.mark_successful_proxy_address('http://1.1.1.1:8000')
        assert changed
        assert state.is_successful_proxy_address('http://1.1.1.1:8000')
        assert state.snapshot_successful_proxy_addresses() == {'http://1.1.1.1:8000'}

    def test_snapshot_blocked_proxy_addresses_merges_active_and_successful_sets(self) -> None:
        state = ExecutionState()
        state.mark_proxy_in_use('Worker-1', ProxyLease(address='http://1.1.1.1:8000'))
        state.mark_successful_proxy_address('http://2.2.2.2:8000')
        blocked = state.snapshot_blocked_proxy_addresses()
        assert blocked == {'http://1.1.1.1:8000', 'http://2.2.2.2:8000'}

    def test_mark_terminal_stop_preserves_first_value_until_explicit_overwrite(self) -> None:
        state = ExecutionState()
        state.mark_terminal_stop('first', failure_reason='a', message='first-message')
        barrier = threading.Barrier(4)

        def _worker(idx: int) -> None:
            barrier.wait()
            state.mark_terminal_stop(f'other-{idx}', failure_reason=f'b-{idx}', message=f'message-{idx}')
        threads = [threading.Thread(target=_worker, args=(idx,), name=f'Stop-{idx}') for idx in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=1.0)
        assert state.get_terminal_stop_snapshot() == ('first', 'a', 'first-message')
        state.mark_terminal_stop('forced', failure_reason='c', message='forced-message', overwrite=True)
        assert state.get_terminal_stop_snapshot() == ('forced', 'c', 'forced-message')

    def test_snapshot_thread_progress_clamps_step_and_sorts_unknown_threads_last(self) -> None:
        state = ExecutionState()
        state.update_thread_step('Worker-2', 99, 3, status_text='running', running=True)
        state.update_thread_status('Worker-?', 'waiting', running=False)
        state.update_thread_step('Worker-1', 1, 4, status_text='step', running=True)
        rows = state.snapshot_thread_progress()
        assert [row['thread_name'] for row in rows] == ['Worker-1', 'Worker-2', 'Worker-?']
        assert rows[1]['step_current'] == 3
        assert rows[1]['step_total'] == 3
        assert rows[1]['step_percent'] == 100

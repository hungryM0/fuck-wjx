from __future__ import annotations
import asyncio
from collections import deque
import time
from unittest.mock import patch
from software.core.task import ExecutionConfig, ExecutionState, ProxyLease
from software.network import session_policy

class SessionPolicyTests:

    def test_record_bad_proxy_never_pauses_task(self) -> None:
        assert not session_policy._record_bad_proxy_and_maybe_pause(ExecutionState(), object())

    def test_resolve_proxy_request_num_caps_by_waiters_remaining_and_global_limit(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(target_num=200, num_threads=32))
        ctx.cur_num = 10
        ctx.proxy_waiting_threads = 120
        ctx.proxy_in_use_by_thread = {'Worker-1': ProxyLease(address='http://1.1.1.1:8000'), 'Worker-2': ProxyLease(address='http://2.2.2.2:8000')}
        assert session_policy._resolve_proxy_request_num_locked(ctx) == 64
        ctx.config.target_num = 12
        assert session_policy._resolve_proxy_request_num_locked(ctx) == 0

    def test_resolve_proxy_request_num_prefills_available_parallel_slots(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(target_num=64, num_threads=32))
        ctx.cur_num = 0
        ctx.proxy_waiting_threads = 1
        assert session_policy._resolve_proxy_request_num_locked(ctx) == 64

        ctx.proxy_in_use_by_thread = {
            f'Worker-{index}': ProxyLease(address=f'http://1.1.1.{index}:8000')
            for index in range(1, 9)
        }
        assert session_policy._resolve_proxy_request_num_locked(ctx) == 48

        ctx.config.target_num = 20
        assert session_policy._resolve_proxy_request_num_locked(ctx) == 12

    def test_resolve_proxy_prefetch_request_count_fills_double_thread_buffer(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True, target_num=50, num_threads=6))
        ctx.config.proxy_ip_pool = [ProxyLease(address=f'http://1.1.1.{index}:8000') for index in range(1, 4)]
        assert session_policy.resolve_proxy_prefetch_request_count(ctx) == 9

        ctx.cur_num = 48
        assert session_policy.resolve_proxy_prefetch_request_count(ctx) == 0

    def test_purge_unusable_proxy_pool_removes_invalid_duplicate_unpoolable_and_expiring_items(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        ctx.config.proxy_ip_pool = [ProxyLease(address='http://1.1.1.1:8000', poolable=True), ProxyLease(address='http://1.1.1.1:8000', poolable=True), ProxyLease(address='http://2.2.2.2:8000', poolable=False), ProxyLease(address='http://3.3.3.3:8000', poolable=True), '']

        def has_ttl(lease: ProxyLease | None, *, required_ttl_seconds: int) -> bool:
            assert required_ttl_seconds == 30
            return bool(lease and lease.address != 'http://3.3.3.3:8000')
        with patch.object(session_policy, 'get_proxy_required_ttl_seconds', return_value=30), patch.object(session_policy, 'proxy_lease_has_sufficient_ttl', side_effect=has_ttl):
            session_policy._purge_unusable_proxy_pool_locked(ctx)
        assert list(ctx.config.proxy_ip_pool) == [ProxyLease(address='http://1.1.1.1:8000', poolable=True)]
        assert isinstance(ctx.config.proxy_ip_pool, deque)

    def test_pop_available_proxy_lease_skips_expiring_proxy(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        expiring = ProxyLease(address='http://1.1.1.1:8000')
        usable = ProxyLease(address='http://2.2.2.2:8000')
        ctx.config.proxy_ip_pool = [expiring, usable]

        def has_ttl(lease: ProxyLease | None, *, required_ttl_seconds: int) -> bool:
            _ = required_ttl_seconds
            return bool(lease and lease.address == usable.address)
        with patch.object(session_policy, 'get_proxy_required_ttl_seconds', return_value=0), patch.object(session_policy, 'proxy_lease_has_sufficient_ttl', side_effect=has_ttl):
            selected = session_policy._pop_available_proxy_lease_locked(ctx)
        assert selected == usable
        assert list(ctx.config.proxy_ip_pool) == []

    def test_pop_available_proxy_lease_skips_proxy_already_used_by_other_session(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        duplicated = ProxyLease(address='http://1.1.1.1:8000')
        usable = ProxyLease(address='http://2.2.2.2:8000')
        ctx.config.proxy_ip_pool = [duplicated, usable]
        ctx.proxy_in_use_by_thread = {'Worker-9': ProxyLease(address='http://1.1.1.1:8000')}
        with patch.object(session_policy, 'get_proxy_required_ttl_seconds', return_value=0), patch.object(session_policy, 'proxy_lease_has_sufficient_ttl', return_value=True):
            selected = session_policy._pop_available_proxy_lease_locked(ctx)
        assert selected == usable
        assert list(ctx.config.proxy_ip_pool) == []

    def test_pop_available_proxy_lease_skips_proxy_in_cooldown(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        cooled = ProxyLease(address='http://1.1.1.1:8000')
        usable = ProxyLease(address='http://2.2.2.2:8000')
        ctx.config.proxy_ip_pool = [cooled, usable]
        ctx.mark_proxy_in_cooldown(cooled.address, 180.0)
        with patch.object(session_policy, 'get_proxy_required_ttl_seconds', return_value=0), patch.object(session_policy, 'proxy_lease_has_sufficient_ttl', return_value=True):
            selected = session_policy._pop_available_proxy_lease_locked(ctx)
        assert selected == usable
        assert list(ctx.config.proxy_ip_pool) == []

    def test_pop_available_proxy_lease_skips_successfully_used_proxy(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        used = ProxyLease(address='http://1.1.1.1:8000')
        usable = ProxyLease(address='http://2.2.2.2:8000')
        ctx.config.proxy_ip_pool = [used, usable]
        ctx.mark_successful_proxy_address(used.address)
        with patch.object(session_policy, 'get_proxy_required_ttl_seconds', return_value=0), patch.object(session_policy, 'proxy_lease_has_sufficient_ttl', return_value=True):
            selected = session_policy._pop_available_proxy_lease_locked(ctx)
        assert selected == usable
        assert list(ctx.config.proxy_ip_pool) == []

    def test_select_proxy_for_session_returns_none_when_random_proxy_disabled(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=False))
        with patch.object(session_policy, 'fetch_proxy_batch_async') as fetch_proxy_batch:
            assert asyncio.run(session_policy._select_proxy_for_session_async(ctx, 'Worker-1')) is None
        fetch_proxy_batch.assert_not_called()

    def test_select_proxy_for_session_marks_existing_pool_proxy_in_use(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True))
        ctx.config.proxy_ip_pool = [ProxyLease(address='http://1.1.1.1:8000', source='unit')]
        selected = asyncio.run(session_policy._select_proxy_for_session_async(ctx, 'Worker-1'))
        assert selected == 'http://1.1.1.1:8000'
        assert 'Worker-1' in ctx.proxy_in_use_by_thread
        assert ctx.proxy_in_use_by_thread['Worker-1'].address == selected

    def test_select_proxy_for_session_consumes_deque_in_order(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True))
        ctx.config.proxy_ip_pool = deque([
            ProxyLease(address='http://1.1.1.1:8000', source='unit'),
            ProxyLease(address='http://2.2.2.2:8000', source='unit'),
        ])
        selected = asyncio.run(session_policy._select_proxy_for_session_async(ctx, 'Worker-1'))
        assert selected == 'http://1.1.1.1:8000'
        assert [lease.address for lease in ctx.config.proxy_ip_pool] == ['http://2.2.2.2:8000']

    def test_select_proxy_for_session_fetches_one_and_pools_extra_leases(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True, target_num=3))
        ctx.cur_num = 0
        ctx.proxy_waiting_threads = 2
        fetched = [ProxyLease(address='http://1.1.1.1:8000', source='api'), ProxyLease(address='http://2.2.2.2:8000', source='api')]
        async def fake_fetch_proxy_batch_async(**_kwargs):
            return fetched
        with patch.object(session_policy, 'fetch_proxy_batch_async', side_effect=fake_fetch_proxy_batch_async) as fetch_proxy_batch:
            selected = asyncio.run(session_policy._select_proxy_for_session_async(ctx, 'Worker-1'))
        assert selected == 'http://1.1.1.1:8000'
        assert [lease.address for lease in ctx.config.proxy_ip_pool] == ['http://2.2.2.2:8000']
        assert ctx.proxy_waiting_threads == 2
        fetch_proxy_batch.assert_called_once()

    def test_select_proxy_for_session_skips_fetched_proxy_already_used_by_other_session(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True, target_num=2))
        ctx.proxy_in_use_by_thread = {'Worker-2': ProxyLease(address='http://1.1.1.1:8000', source='api')}
        fetched = [ProxyLease(address='http://1.1.1.1:8000', source='api'), ProxyLease(address='http://2.2.2.2:8000', source='api')]
        async def fake_fetch_proxy_batch_async(**_kwargs):
            return fetched
        with patch.object(session_policy, 'fetch_proxy_batch_async', side_effect=fake_fetch_proxy_batch_async), patch.object(session_policy, 'get_proxy_required_ttl_seconds', return_value=0), patch.object(session_policy, 'proxy_lease_has_sufficient_ttl', return_value=True):
            selected = asyncio.run(session_policy._select_proxy_for_session_async(ctx, 'Worker-1'))
        assert selected == 'http://2.2.2.2:8000'
        assert ctx.proxy_in_use_by_thread['Worker-1'].address == 'http://2.2.2.2:8000'

    def test_select_proxy_for_session_skips_fetched_proxy_in_cooldown(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True, target_num=2))
        ctx.mark_proxy_in_cooldown('http://1.1.1.1:8000', 180.0)
        fetched = [ProxyLease(address='http://1.1.1.1:8000', source='api'), ProxyLease(address='http://2.2.2.2:8000', source='api')]
        async def fake_fetch_proxy_batch_async(**_kwargs):
            return fetched
        with patch.object(session_policy, 'fetch_proxy_batch_async', side_effect=fake_fetch_proxy_batch_async), patch.object(session_policy, 'get_proxy_required_ttl_seconds', return_value=0), patch.object(session_policy, 'proxy_lease_has_sufficient_ttl', return_value=True):
            selected = asyncio.run(session_policy._select_proxy_for_session_async(ctx, 'Worker-1'))
        assert selected == 'http://2.2.2.2:8000'
        assert ctx.proxy_in_use_by_thread['Worker-1'].address == 'http://2.2.2.2:8000'

    def test_select_proxy_for_session_skips_fetched_proxy_used_by_previous_success(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True, target_num=2))
        ctx.mark_successful_proxy_address('http://1.1.1.1:8000')
        fetched = [ProxyLease(address='http://1.1.1.1:8000', source='api'), ProxyLease(address='http://2.2.2.2:8000', source='api')]
        async def fake_fetch_proxy_batch_async(**_kwargs):
            return fetched
        with patch.object(session_policy, 'fetch_proxy_batch_async', side_effect=fake_fetch_proxy_batch_async), patch.object(session_policy, 'get_proxy_required_ttl_seconds', return_value=0), patch.object(session_policy, 'proxy_lease_has_sufficient_ttl', return_value=True):
            selected = asyncio.run(session_policy._select_proxy_for_session_async(ctx, 'Worker-1'))
        assert selected == 'http://2.2.2.2:8000'
        assert ctx.proxy_in_use_by_thread['Worker-1'].address == 'http://2.2.2.2:8000'

    def test_select_proxy_for_session_waits_for_new_proxy_when_runtime_requests_blocking_mode(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True, target_num=1))
        results = iter([[], [ProxyLease(address='http://9.9.9.9:8000', source='api')]])
        async def fake_fetch_proxy_batch_async(**_kwargs):
            return next(results)
        async def fake_wait_for_next_proxy_cycle_async(*_args, **_kwargs):
            return False
        with patch.object(session_policy, 'fetch_proxy_batch_async', side_effect=fake_fetch_proxy_batch_async), patch.object(session_policy, '_wait_for_next_proxy_cycle_async', side_effect=fake_wait_for_next_proxy_cycle_async):
            selected = asyncio.run(session_policy._select_proxy_for_session_async(ctx, 'Worker-1', stop_signal=ctx.stop_event, wait=True))
        assert selected == 'http://9.9.9.9:8000'
        assert ctx.proxy_in_use_by_thread['Worker-1'].address == 'http://9.9.9.9:8000'

    def test_async_proxy_fetch_lock_wait_does_not_block_event_loop(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True, target_num=1))

        async def scenario() -> None:
            lock = session_policy._get_proxy_fetch_async_lock(ctx)
            await lock.acquire()

            async def release_later() -> None:
                await asyncio.sleep(0.05)
                lock.release()

            waiter = asyncio.create_task(session_policy._acquire_proxy_fetch_lock_async(ctx, ctx.stop_event))
            releaser = asyncio.create_task(release_later())
            await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.1)
            assert not waiter.done()
            assert await asyncio.wait_for(waiter, timeout=0.2)
            lock.release()
            await releaser

        asyncio.run(scenario())

    def test_discard_unresponsive_proxy_removes_matching_proxy_from_pool(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        ctx.config.proxy_ip_pool = [ProxyLease(address='http://1.1.1.1:8000'), ProxyLease(address='http://2.2.2.2:8000')]
        session_policy._discard_unresponsive_proxy(ctx, ' http://1.1.1.1:8000 ')
        assert [lease.address for lease in ctx.config.proxy_ip_pool] == ['http://2.2.2.2:8000']
        assert isinstance(ctx.config.proxy_ip_pool, deque)

    def test_mark_proxy_temporarily_bad_adds_cooldown_and_discards_from_pool(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        ctx.config.proxy_ip_pool = [ProxyLease(address='http://1.1.1.1:8000')]
        session_policy._mark_proxy_temporarily_bad(ctx, 'http://1.1.1.1:8000', cooldown_seconds=180.0)
        assert ctx.is_proxy_in_cooldown('http://1.1.1.1:8000')
        assert list(ctx.config.proxy_ip_pool) == []

    def test_expired_proxy_cooldown_allows_proxy_back_into_pool(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        lease = ProxyLease(address='http://1.1.1.1:8000')
        ctx.config.proxy_ip_pool = [lease]
        ctx.proxy_cooldown_until_by_address[lease.address] = time.time() - 1.0
        with patch.object(session_policy, 'get_proxy_required_ttl_seconds', return_value=0), patch.object(session_policy, 'proxy_lease_has_sufficient_ttl', return_value=True):
            selected = session_policy._pop_available_proxy_lease_locked(ctx)
        assert selected == lease
        assert not ctx.is_proxy_in_cooldown(lease.address)

    def test_merge_prefetched_proxy_leases_adds_unique_poolable_items(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True))
        ctx.config.proxy_ip_pool = [ProxyLease(address='http://1.1.1.1:8000')]
        fetched = [
            ProxyLease(address='http://1.1.1.1:8000'),
            ProxyLease(address='http://2.2.2.2:8000'),
            ProxyLease(address='http://3.3.3.3:8000', poolable=False),
        ]
        with patch.object(session_policy, 'get_proxy_required_ttl_seconds', return_value=0), patch.object(session_policy, 'proxy_lease_has_sufficient_ttl', return_value=True):
            merged = session_policy.merge_prefetched_proxy_leases(ctx, fetched)
        assert merged == 1
        assert [lease.address for lease in ctx.config.proxy_ip_pool] == ['http://1.1.1.1:8000', 'http://2.2.2.2:8000']

    def test_select_user_agent_returns_none_when_disabled(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_user_agent_enabled=False))
        with patch.object(session_policy, '_select_user_agent_from_ratios') as select_user_agent:
            assert session_policy._select_user_agent_for_session(ctx) == (None, None)
        select_user_agent.assert_not_called()

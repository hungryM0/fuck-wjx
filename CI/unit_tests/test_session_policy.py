from __future__ import annotations

import unittest
from unittest.mock import patch

from software.core.task import ExecutionConfig, ExecutionState, ProxyLease
from software.network import session_policy


class SessionPolicyTests(unittest.TestCase):
    def test_record_bad_proxy_never_pauses_task(self) -> None:
        self.assertFalse(session_policy._record_bad_proxy_and_maybe_pause(ExecutionState(), object()))

    def test_resolve_proxy_request_num_caps_by_waiters_remaining_and_global_limit(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(target_num=200))
        ctx.cur_num = 10
        ctx.proxy_waiting_threads = 120
        ctx.proxy_in_use_by_thread = {
            "Worker-1": ProxyLease(address="http://1.1.1.1:8000"),
            "Worker-2": ProxyLease(address="http://2.2.2.2:8000"),
        }

        self.assertEqual(session_policy._resolve_proxy_request_num_locked(ctx), 80)

        ctx.config.target_num = 12
        self.assertEqual(session_policy._resolve_proxy_request_num_locked(ctx), 0)

    def test_purge_unusable_proxy_pool_removes_invalid_duplicate_unpoolable_and_expiring_items(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        ctx.config.proxy_ip_pool = [
            ProxyLease(address="http://1.1.1.1:8000", poolable=True),
            ProxyLease(address="http://1.1.1.1:8000", poolable=True),
            ProxyLease(address="http://2.2.2.2:8000", poolable=False),
            ProxyLease(address="http://3.3.3.3:8000", poolable=True),
            "",
        ]

        def has_ttl(lease: ProxyLease | None, *, required_ttl_seconds: int) -> bool:
            self.assertEqual(required_ttl_seconds, 30)
            return bool(lease and lease.address != "http://3.3.3.3:8000")

        with (
            patch.object(session_policy, "get_proxy_required_ttl_seconds", return_value=30),
            patch.object(session_policy, "proxy_lease_has_sufficient_ttl", side_effect=has_ttl),
        ):
            session_policy._purge_unusable_proxy_pool_locked(ctx)

        self.assertEqual(ctx.config.proxy_ip_pool, [ProxyLease(address="http://1.1.1.1:8000", poolable=True)])

    def test_pop_available_proxy_lease_skips_expiring_proxy(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        expiring = ProxyLease(address="http://1.1.1.1:8000")
        usable = ProxyLease(address="http://2.2.2.2:8000")
        ctx.config.proxy_ip_pool = [expiring, usable]

        def has_ttl(lease: ProxyLease | None, *, required_ttl_seconds: int) -> bool:
            return bool(lease and lease.address == usable.address)

        with (
            patch.object(session_policy, "get_proxy_required_ttl_seconds", return_value=0),
            patch.object(session_policy, "proxy_lease_has_sufficient_ttl", side_effect=has_ttl),
        ):
            selected = session_policy._pop_available_proxy_lease_locked(ctx)

        self.assertEqual(selected, usable)
        self.assertEqual(ctx.config.proxy_ip_pool, [])

    def test_select_proxy_for_session_returns_none_when_random_proxy_disabled(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=False))

        with patch.object(session_policy, "fetch_proxy_batch") as fetch_proxy_batch:
            self.assertIsNone(session_policy._select_proxy_for_session(ctx, "Worker-1"))

        fetch_proxy_batch.assert_not_called()

    def test_select_proxy_for_session_marks_existing_pool_proxy_in_use(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True))
        ctx.config.proxy_ip_pool = [ProxyLease(address="http://1.1.1.1:8000", source="unit")]

        selected = session_policy._select_proxy_for_session(ctx, "Worker-1")

        self.assertEqual(selected, "http://1.1.1.1:8000")
        self.assertIn("Worker-1", ctx.proxy_in_use_by_thread)
        self.assertEqual(ctx.proxy_in_use_by_thread["Worker-1"].address, selected)

    def test_select_proxy_for_session_fetches_one_and_pools_extra_leases(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_proxy_ip_enabled=True, target_num=3))
        ctx.cur_num = 0
        ctx.proxy_waiting_threads = 2

        fetched = [
            ProxyLease(address="http://1.1.1.1:8000", source="api"),
            ProxyLease(address="http://2.2.2.2:8000", source="api"),
        ]

        with patch.object(session_policy, "fetch_proxy_batch", return_value=fetched) as fetch_proxy_batch:
            selected = session_policy._select_proxy_for_session(ctx, "Worker-1")

        self.assertEqual(selected, "http://1.1.1.1:8000")
        self.assertEqual([lease.address for lease in ctx.config.proxy_ip_pool], ["http://2.2.2.2:8000"])
        self.assertEqual(ctx.proxy_waiting_threads, 2)
        fetch_proxy_batch.assert_called_once()

    def test_discard_unresponsive_proxy_removes_matching_proxy_from_pool(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig())
        ctx.config.proxy_ip_pool = [
            ProxyLease(address="http://1.1.1.1:8000"),
            ProxyLease(address="http://2.2.2.2:8000"),
        ]

        session_policy._discard_unresponsive_proxy(ctx, " http://1.1.1.1:8000 ")

        self.assertEqual([lease.address for lease in ctx.config.proxy_ip_pool], ["http://2.2.2.2:8000"])

    def test_select_user_agent_returns_none_when_disabled(self) -> None:
        ctx = ExecutionState(config=ExecutionConfig(random_user_agent_enabled=False))

        with patch.object(session_policy, "_select_user_agent_from_ratios") as select_user_agent:
            self.assertEqual(session_policy._select_user_agent_for_session(ctx), (None, None))

        select_user_agent.assert_not_called()


if __name__ == "__main__":
    unittest.main()

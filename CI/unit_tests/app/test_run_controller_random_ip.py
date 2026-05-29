from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import Future
from types import SimpleNamespace

import software.ui.controller.run_controller_parts.runtime_random_ip as random_ip_module
from software.network.proxy.session import RandomIPAuthError
from software.ui.controller.run_controller_parts.runtime_random_ip import (
    RunControllerRandomIPMixin,
)


class _FakeAdapter:
    def __init__(self) -> None:
        self.enabled = True
        self.messages: list[tuple[str, str, str]] = []
        self.counters: list[tuple[float, float, bool]] = []
        self.loading: list[tuple[bool, str]] = []
        self.open_quota_calls = 0

    def show_message_dialog(self, title: str, message: str, *, level: str = "info") -> None:
        self.messages.append((title, message, level))

    def update_random_ip_counter(self, used: float, total: float, custom_api: bool) -> None:
        self.counters.append((used, total, custom_api))

    def set_random_ip_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def set_random_ip_loading(self, loading: bool, message: str = "") -> None:
        self.loading.append((bool(loading), str(message)))

    def open_quota_request_form(self) -> bool:
        self.open_quota_calls += 1
        return True


class _FakeController(RunControllerRandomIPMixin):
    def __init__(self) -> None:
        self.adapter = _FakeAdapter()
        self._async_engine_client = SimpleNamespace(submit_ui_task=self._submit_ui_task)
        self._random_ip_server_sync_lock = threading.Lock()
        self._random_ip_server_sync_active = False
        self._random_ip_last_server_sync_at = 0.0
        self._random_ip_background_threads: set[threading.Thread] = set()
        self._random_ip_background_threads_lock = threading.Lock()
        self._parent = None
        self.loading_events: list[tuple[bool, str]] = []
        self.refresh_calls: list[object] = []

    def _submit_ui_task(self, _task_name, coro_factory):
        future: Future[object] = Future()
        try:
            future.set_result(asyncio.run(coro_factory()))
        except Exception as exc:
            future.set_exception(exc)
        return future

    def notify_random_ip_loading(self, loading: bool, message: str = "") -> None:
        self.loading_events.append((bool(loading), str(message)))

    def refresh_random_ip_counter(self, *, adapter=None) -> None:
        self.refresh_calls.append(adapter)
        super().refresh_random_ip_counter(adapter=adapter)

    def parent(self):
        return self._parent

    def wait_random_ip_tasks(self, timeout: float = 1.0) -> None:
        deadline = time.monotonic() + float(timeout)
        while time.monotonic() < deadline:
            if not self.collect_random_ip_background_threads():
                return
            time.sleep(0.01)
        raise AssertionError("随机IP后台任务未按时结束")


class RunControllerRandomIPTests:
    def test_get_counter_snapshot_covers_remote_and_local_fallbacks(self, monkeypatch) -> None:
        controller = _FakeController()

        monkeypatch.setattr(random_ip_module, "is_custom_proxy_api_active", lambda: False)
        monkeypatch.setattr(random_ip_module, "has_authenticated_session", lambda: True)
        monkeypatch.setattr(
            random_ip_module,
            "get_fresh_quota_snapshot",
            lambda: {"used_quota": 2, "total_quota": 8},
        )
        assert controller._get_counter_snapshot() == (2.0, 8.0, False)

        monkeypatch.setattr(
            random_ip_module,
            "get_fresh_quota_snapshot",
            lambda: (_ for _ in ()).throw(RandomIPAuthError("bad", detail="expired")),
        )
        monkeypatch.setattr(
            random_ip_module,
            "get_quota_snapshot",
            lambda: {"used_quota": 1, "total_quota": 5},
        )
        assert controller._get_counter_snapshot() == (1.0, 5.0, False)

        monkeypatch.setattr(random_ip_module, "is_custom_proxy_api_active", lambda: True)
        monkeypatch.setattr(
            random_ip_module,
            "get_random_ip_counter_snapshot_local",
            lambda: (3, 9, False),
        )
        assert controller._get_counter_snapshot() == (3.0, 9.0, True)

    def test_refresh_random_ip_counter_now_handles_auth_error_and_generic_error(self, monkeypatch) -> None:
        controller = _FakeController()
        calls = {"count": 0}

        def _load() -> None:
            calls["count"] += 1

        monkeypatch.setattr(random_ip_module, "load_session_for_startup", _load)

        values = iter([RandomIPAuthError("session_expired"), (4.0, 10.0, False)])

        def _get_snapshot():
            value = next(values)
            if isinstance(value, Exception):
                raise value
            return value

        monkeypatch.setattr(controller, "_get_counter_snapshot", _get_snapshot)
        controller._refresh_random_ip_counter_now(controller.adapter)
        assert calls["count"] == 1
        assert controller.adapter.enabled is False
        assert controller.adapter.messages[0][0] == "随机IP账号状态异常"
        assert controller.adapter.counters[-1] == (4.0, 10.0, False)

        monkeypatch.setattr(
            random_ip_module,
            "format_random_ip_error",
            lambda exc: f"ERR:{exc}",
        )
        fallback_values = iter([(6.0, 11.0, False)])
        monkeypatch.setattr(
            controller,
            "_get_counter_snapshot",
            lambda: next(fallback_values)
            if getattr(controller, "_fallback_once", False)
            else (_ for _ in ()).throw(RuntimeError("boom")),
        )
        controller._fallback_once = True
        controller._refresh_random_ip_counter_now(controller.adapter)
        assert controller.adapter.counters[-1] == (6.0, 11.0, False)

    def test_sync_random_ip_counter_from_server_covers_success_and_failure(self, monkeypatch) -> None:
        controller = _FakeController()

        monkeypatch.setattr(random_ip_module, "is_custom_proxy_api_active", lambda: False)
        monkeypatch.setattr(random_ip_module, "has_authenticated_session", lambda: True)
        monkeypatch.setattr(random_ip_module.time, "monotonic", lambda: 100.0)

        async def fake_sync_quota_snapshot_from_server_async(*, emit_logs=True):
            assert emit_logs is False
            return {"used_quota": 7, "total_quota": 12}

        monkeypatch.setattr(
            random_ip_module,
            "sync_quota_snapshot_from_server_async",
            fake_sync_quota_snapshot_from_server_async,
        )
        monkeypatch.setattr(random_ip_module, "reset_deduped_log_message", lambda _key: None)
        controller.sync_random_ip_counter_from_server(adapter=controller.adapter)
        controller.wait_random_ip_tasks()
        assert controller.adapter.counters[-1] == (7.0, 12.0, False)
        assert controller._random_ip_server_sync_active is False

        logged: list[tuple[str, str]] = []

        async def fake_failed_sync_quota_snapshot_from_server_async(*, emit_logs=True):
            assert emit_logs is True
            raise RuntimeError("net")

        monkeypatch.setattr(
            random_ip_module,
            "sync_quota_snapshot_from_server_async",
            fake_failed_sync_quota_snapshot_from_server_async,
        )
        monkeypatch.setattr(
            random_ip_module,
            "log_deduped_message",
            lambda key, message, **_kwargs: logged.append((key, message)),
        )
        monkeypatch.setattr(
            controller,
            "_refresh_random_ip_counter_now",
            lambda adapter: adapter.counters.append((9.0, 15.0, False)),
        )
        controller.sync_random_ip_counter_from_server(adapter=controller.adapter, silent=False)
        controller.wait_random_ip_tasks()
        assert logged[-1][0] == "random_ip_quota_sync_failure"
        assert controller.adapter.messages[-1][0] == "随机IP同步失败"
        assert controller.adapter.counters[-1] == (9.0, 15.0, False)

    def test_submit_toggle_random_ip_covers_custom_api_success_quota_exhausted_and_failure(
        self, monkeypatch
    ) -> None:
        controller = _FakeController()

        monkeypatch.setattr(random_ip_module, "is_custom_proxy_api_active", lambda: True)
        assert controller.submit_toggle_random_ip(True, adapter=controller.adapter).result() is True
        assert controller.adapter.enabled is True
        assert controller.adapter.counters[-1][2] is True

        monkeypatch.setattr(random_ip_module, "is_custom_proxy_api_active", lambda: False)

        async def fake_ensure_random_ip_ready_async(_adapter):
            return True

        monkeypatch.setattr(controller, "_ensure_random_ip_ready_async", fake_ensure_random_ip_ready_async)
        monkeypatch.setattr(
            random_ip_module,
            "get_random_ip_counter_snapshot_local",
            lambda: (1, 8, False),
        )

        async def fake_sync_quota_snapshot_from_server_async(*, emit_logs=True):
            assert emit_logs is True
            return {"used_quota": 2, "total_quota": 8}

        monkeypatch.setattr(
            random_ip_module,
            "sync_quota_snapshot_from_server_async",
            fake_sync_quota_snapshot_from_server_async,
        )
        monkeypatch.setattr(random_ip_module, "is_quota_exhausted", lambda snapshot: False)
        assert controller.submit_toggle_random_ip(True, adapter=controller.adapter).result() is True
        assert controller.adapter.enabled is True
        assert controller.adapter.counters[-1] == (2.0, 8.0, False)

        monkeypatch.setattr(random_ip_module, "is_quota_exhausted", lambda snapshot: True)
        assert controller.submit_toggle_random_ip(True, adapter=controller.adapter).result() is False
        assert controller.adapter.enabled is False
        assert controller.adapter.messages[-1][0] == "提示"

        async def fake_failed_sync_quota_snapshot_from_server_async(**_kwargs):
            raise RuntimeError("down")

        monkeypatch.setattr(
            random_ip_module,
            "sync_quota_snapshot_from_server_async",
            fake_failed_sync_quota_snapshot_from_server_async,
        )
        assert controller.submit_toggle_random_ip(True, adapter=controller.adapter).result() is False
        assert controller.adapter.messages[-1][0] == "随机IP暂不可用"

        assert controller.submit_toggle_random_ip(False, adapter=controller.adapter).result() is False
        assert controller.adapter.enabled is False

    def test_trial_ready_and_submission_path_are_async_only(self, monkeypatch) -> None:
        controller = _FakeController()

        monkeypatch.setattr(
            random_ip_module,
            "activate_trial_async",
            lambda: asyncio.sleep(0, result=SimpleNamespace(total_quota=5, used_quota=1)),
        )
        ok, fallback = asyncio.run(controller._try_activate_random_ip_trial_async(controller.adapter))
        assert (ok, fallback) == (True, False)
        assert controller.adapter.messages == []

        async def fake_activate_trial_async_already_claimed():
            raise RandomIPAuthError("trial_already_claimed")

        monkeypatch.setattr(
            random_ip_module,
            "activate_trial_async",
            fake_activate_trial_async_already_claimed,
        )
        ok, fallback = asyncio.run(controller._try_activate_random_ip_trial_async(controller.adapter))
        assert (ok, fallback) == (False, True)

        monkeypatch.setattr(random_ip_module, "has_authenticated_session", lambda: False)

        async def fake_try_activate_random_ip_trial_async(_adapter):
            return False, True

        monkeypatch.setattr(
            controller,
            "_try_activate_random_ip_trial_async",
            fake_try_activate_random_ip_trial_async,
        )
        assert asyncio.run(controller._ensure_random_ip_ready_async(controller.adapter)) is True
        assert controller.adapter.open_quota_calls == 1

        monkeypatch.setattr(random_ip_module, "is_custom_proxy_api_active", lambda: False)
        monkeypatch.setattr(random_ip_module, "get_session_snapshot", lambda: {"authenticated": False})
        stop_signal = threading.Event()
        controller.handle_random_ip_submission(stop_signal=stop_signal, adapter=controller.adapter)
        controller.wait_random_ip_tasks()
        assert stop_signal.is_set()
        assert controller.adapter.enabled is False

        controller.adapter.enabled = True
        monkeypatch.setattr(random_ip_module, "get_session_snapshot", lambda: {"authenticated": True})
        controller.handle_random_ip_submission(stop_signal=threading.Event(), adapter=controller.adapter)
        controller.wait_random_ip_tasks()
        assert controller.adapter.counters

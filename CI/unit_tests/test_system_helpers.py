from __future__ import annotations

from software.network.proxy.pool import prefetch
from software.system.power_management import SystemSleepBlocker
from software.system import secure_store
from software.ui.helpers import ai_fill


class _Kernel32:
    def __init__(self, returns: list[int] | None = None) -> None:
        self.returns = list(returns or [1])
        self.calls: list[int] = []

    def SetThreadExecutionState(self, flags: int) -> int:
        self.calls.append(flags)
        return self.returns.pop(0) if self.returns else 1


class SystemHelpersTests:
    def test_sleep_blocker_non_windows_and_windows_success_paths(self, patch_attrs) -> None:
        blocker = SystemSleepBlocker()
        patch_attrs((secure_store.sys, "platform", "linux"))
        patch_attrs((__import__("software.system.power_management", fromlist=["sys"]).sys, "platform", "linux"))

        assert blocker.acquire() is False
        blocker._active = True
        assert blocker.release() is True
        assert blocker.active is False

        import software.system.power_management as power_management

        kernel = _Kernel32([1, 1])
        patch_attrs(
            (power_management.sys, "platform", "win32"),
            (power_management, "_kernel32", lambda: kernel),
        )
        blocker = SystemSleepBlocker()
        assert blocker.acquire() is True
        assert blocker.acquire() is True
        assert blocker.release() is True
        assert kernel.calls == [0x80000001, 0x80000000]

    def test_sleep_blocker_handles_windows_api_failure(self, patch_attrs) -> None:
        import software.system.power_management as power_management

        kernel = _Kernel32([0])
        patch_attrs(
            (power_management.sys, "platform", "win32"),
            (power_management, "_kernel32", lambda: kernel),
        )
        blocker = SystemSleepBlocker()
        assert blocker.acquire() is False

        kernel = _Kernel32([0])
        patch_attrs((power_management, "_kernel32", lambda: kernel))
        blocker._active = True
        assert blocker.release() is False
        assert blocker.active is True

    def test_secure_store_unsupported_and_invalid_key_paths(self, patch_attrs) -> None:
        patch_attrs((secure_store.sys, "platform", "linux"))
        secure_store.set_secret("key", "value")
        secure_store.delete_secret("key")
        assert secure_store.read_secret("key").status == "unsupported"

        patch_attrs((secure_store.sys, "platform", "darwin"), (secure_store, "keyring", object()))
        assert secure_store.read_secret("").status == "invalid_key"
        secure_store.set_secret("", "value")
        secure_store.delete_secret("")

    def test_prefetch_proxy_pool_passes_effective_url_and_minimum_count(self, patch_attrs) -> None:
        calls: list[dict[str, object]] = []

        def fake_fetch(**kwargs):
            calls.append(kwargs)
            return ["lease"]

        import software.network.proxy.api as proxy_api
        async def fake_fetch_async(**kwargs):
            return fake_fetch(**kwargs)

        patch_attrs(
            (prefetch, "get_effective_proxy_api_url", lambda: "https://proxy.example/api"),
            (proxy_api, "fetch_proxy_batch_async", fake_fetch_async),
        )

        assert prefetch.prefetch_proxy_pool(0) == ["lease"]
        assert calls == [
            {
                "expected_count": 1,
                "proxy_url": "https://proxy.example/api",
                "notify_on_area_error": False,
                "stop_signal": None,
            }
        ]

    def test_ensure_ai_ready_warns_when_config_missing(self, patch_attrs) -> None:
        calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        patch_attrs(
            (ai_fill, "get_ai_readiness_error", lambda: "缺少 Key"),
            (ai_fill.InfoBar, "warning", lambda *args, **kwargs: calls.append((args, kwargs))),
        )

        assert ai_fill.ensure_ai_ready(parent="parent") is False
        assert "缺少 Key" in calls[0][0][1]
        assert calls[0][1]["parent"] == "parent"

        patch_attrs((ai_fill, "get_ai_readiness_error", lambda: ""))
        assert ai_fill.ensure_ai_ready(parent="parent") is True

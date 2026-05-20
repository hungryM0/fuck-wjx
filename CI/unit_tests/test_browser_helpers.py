from __future__ import annotations

import asyncio
import errno

import pytest

import software.network.browser.options as browser_options
import software.network.browser.startup as browser_startup


class BrowserOptionsTests:
    def test_build_selector_handles_xpath_and_id(self) -> None:
        assert browser_options._build_selector("xpath", "//div[@id='q1']") == "xpath=//div[@id='q1']"
        assert browser_options._build_selector("id", "div1") == "#div1"
        assert browser_options._build_selector("id", "#div2") == "#div2"
        assert browser_options._build_selector("css", ".question") == ".question"

    def test_build_context_args_extracts_proxy_credentials_and_viewport(self, patch_attrs) -> None:
        patch_attrs(
            (browser_options, "normalize_proxy_address", lambda _value: "http://user:pass@127.0.0.1:8888"),
            (browser_options, "HEADLESS_WINDOW_SIZE", "1280,720"),
            (browser_options, "get_proxy_source", lambda: "pool"),
        )
        context_args = browser_options._build_context_args(headless=True, proxy_address="ignored", user_agent="UA-Test")
        assert context_args == {"proxy": {"server": "http://127.0.0.1:8888", "username": "user", "password": "pass"}, "user_agent": "UA-Test", "viewport": {"width": 1280, "height": 720}}

    def test_build_context_args_uses_custom_proxy_auth_when_url_has_no_credentials(self, patch_attrs) -> None:
        patch_attrs(
            (browser_options, "normalize_proxy_address", lambda _value: "http://127.0.0.1:9999"),
            (browser_options, "get_proxy_source", lambda: browser_options.PROXY_SOURCE_CUSTOM),
            (browser_options, "get_proxy_auth", lambda: "alice:secret"),
        )
        context_args = browser_options._build_context_args(headless=False, proxy_address="http://127.0.0.1:9999", user_agent=None)
        assert context_args == {"proxy": {"server": "http://127.0.0.1:9999", "username": "alice", "password": "secret"}}

    def test_build_launch_args_for_edge_adds_channel_window_position_and_no_proxy(self) -> None:
        launch_args = browser_options._build_launch_args(browser_name="edge", headless=False, window_position=(10, 20), append_no_proxy=True)
        assert launch_args["channel"] == "msedge"
        assert not launch_args["headless"]
        assert "--disable-gpu" in launch_args["args"]
        assert "--disable-extensions" in launch_args["args"]
        assert "--disable-background-networking" in launch_args["args"]
        assert "--window-position=10,20" in launch_args["args"]
        assert "--no-proxy-server" in launch_args["args"]

    def test_build_launch_args_rejects_chrome_fallback(self) -> None:
        with pytest.raises(ValueError, match="Microsoft Edge"):
            browser_options._build_launch_args(
                browser_name="chrome",
                headless=True,
                window_position=None,
                append_no_proxy=False,
            )

    def test_error_detectors_match_proxy_and_disconnect_messages(self) -> None:
        assert browser_options._is_proxy_tunnel_error(RuntimeError("net::ERR_PROXY_CONNECTION_FAILED"))
        assert browser_options._is_browser_disconnected_error(RuntimeError("Target page, context or browser has been closed"))
        assert not browser_options._is_proxy_tunnel_error(RuntimeError("plain error"))
        assert not browser_options._is_browser_disconnected_error(RuntimeError("plain error"))


class BrowserStartupTests:
    def test_is_playwright_startup_environment_error_detects_socket_block(self) -> None:
        exc = PermissionError(errno.EACCES, "socket blocked by firewall")
        assert browser_startup.is_playwright_startup_environment_error(exc)

    def test_is_playwright_startup_environment_error_detects_winsock_breakage(self) -> None:
        exc = OSError("winsock provider failed")
        exc.winerror = 10106
        assert browser_startup.is_playwright_startup_environment_error(exc)

    def test_describe_playwright_startup_error_humanizes_asyncio_subprocess_issue(self) -> None:
        root = NotImplementedError("create_subprocess_exec is unavailable")
        exc = RuntimeError("wrapper")
        exc.__cause__ = root
        message = browser_startup.describe_playwright_startup_error(exc)
        assert "Windows asyncio 子进程能力不可用" in message

    def test_describe_playwright_startup_error_humanizes_broken_asyncio_import(self) -> None:
        exc = NameError("name 'base_events' is not defined")
        message = browser_startup.describe_playwright_startup_error(exc)
        assert "WinError 10106" in message

    def test_classify_playwright_startup_error_uses_shared_environment_kind(self) -> None:
        exc = NameError("name 'base_events' is not defined")
        info = browser_startup.classify_playwright_startup_error(exc)
        assert info.kind == browser_startup.BROWSER_STARTUP_ERROR_ENVIRONMENT
        assert info.is_environment_error

    def test_describe_playwright_startup_error_falls_back_to_exception_type_when_message_empty(self) -> None:
        message = browser_startup.describe_playwright_startup_error(RuntimeError())
        assert message == "RuntimeError"

    @pytest.mark.asyncio
    async def test_start_playwright_async_runtime_retries_known_environment_error_then_succeeds(self, patch_attrs) -> None:
        class _FakeAsyncPlaywright:
            def __init__(self) -> None:
                self.start_calls = 0

            def __call__(self):
                return self

            async def start(self):
                self.start_calls += 1
                if self.start_calls == 1:
                    exc = PermissionError(errno.EACCES, "socket blocked")
                    exc.winerror = 10013
                    raise exc
                return "pw-runtime"

        fake_async = _FakeAsyncPlaywright()
        sleep_calls: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        patch_attrs(
            (browser_startup, "_load_playwright_async", lambda: (fake_async, object())),
            (browser_startup.gc, "collect", lambda: None),
            (browser_startup.asyncio, "sleep", _fake_sleep),
        )

        runtime = await browser_startup._start_playwright_async_runtime()

        assert runtime == "pw-runtime"
        assert fake_async.start_calls == 2
        assert sleep_calls == [0.35]

    @pytest.mark.asyncio
    async def test_start_playwright_async_runtime_does_not_retry_unknown_error(self, patch_attrs) -> None:
        class _FakeAsyncPlaywright:
            def __call__(self):
                return self

            async def start(self):
                raise RuntimeError("boom")

        patch_attrs(
            (browser_startup, "_load_playwright_async", lambda: (_FakeAsyncPlaywright(), object())),
        )

        with pytest.raises(RuntimeError, match="boom"):
            await browser_startup._start_playwright_async_runtime()

    @pytest.mark.asyncio
    async def test_start_playwright_async_runtime_serializes_concurrent_starts(self, patch_attrs) -> None:
        gate = asyncio.Event()
        active_calls = 0
        max_active_calls = 0
        started = 0

        class _FakeAsyncPlaywright:
            def __call__(self):
                return self

            async def start(self):
                nonlocal active_calls, max_active_calls, started
                started += 1
                active_calls += 1
                max_active_calls = max(max_active_calls, active_calls)
                await gate.wait()
                active_calls -= 1
                return f"pw-{started}"

        patch_attrs(
            (browser_startup, "_load_playwright_async", lambda: (_FakeAsyncPlaywright(), object())),
        )

        first = asyncio.create_task(browser_startup._start_playwright_async_runtime())
        await asyncio.sleep(0.01)
        second = asyncio.create_task(browser_startup._start_playwright_async_runtime())
        await asyncio.sleep(0.01)
        assert max_active_calls == 1

        gate.set()
        results = await asyncio.gather(first, second)
        assert results == ["pw-1", "pw-2"]

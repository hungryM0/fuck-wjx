from __future__ import annotations

import errno
import unittest
from contextlib import ExitStack, contextmanager

import software.network.browser.options as browser_options
import software.network.browser.startup as browser_startup
import software.network.browser.transient as browser_transient


@contextmanager
def _patched_attr(target, name: str, value):
    original = getattr(target, name)
    setattr(target, name, value)
    try:
        yield
    finally:
        setattr(target, name, original)


class BrowserOptionsTests(unittest.TestCase):
    def test_build_selector_handles_xpath_and_id(self) -> None:
        self.assertEqual(browser_options._build_selector("xpath", "//div[@id='q1']"), "xpath=//div[@id='q1']")
        self.assertEqual(browser_options._build_selector("id", "div1"), "#div1")
        self.assertEqual(browser_options._build_selector("id", "#div2"), "#div2")
        self.assertEqual(browser_options._build_selector("css", ".question"), ".question")

    def test_build_context_args_extracts_proxy_credentials_and_viewport(self) -> None:
        with ExitStack() as stack:
            stack.enter_context(_patched_attr(browser_options, "normalize_proxy_address", lambda _value: "http://user:pass@127.0.0.1:8888"))
            stack.enter_context(_patched_attr(browser_options, "HEADLESS_WINDOW_SIZE", "1280,720"))
            stack.enter_context(_patched_attr(browser_options, "get_proxy_source", lambda: "pool"))
            context_args = browser_options._build_context_args(
                headless=True,
                proxy_address="ignored",
                user_agent="UA-Test",
            )

        self.assertEqual(
            context_args,
            {
                "proxy": {
                    "server": "http://127.0.0.1:8888",
                    "username": "user",
                    "password": "pass",
                },
                "user_agent": "UA-Test",
                "viewport": {"width": 1280, "height": 720},
            },
        )

    def test_build_context_args_uses_custom_proxy_auth_when_url_has_no_credentials(self) -> None:
        with ExitStack() as stack:
            stack.enter_context(_patched_attr(browser_options, "normalize_proxy_address", lambda _value: "http://127.0.0.1:9999"))
            stack.enter_context(_patched_attr(browser_options, "get_proxy_source", lambda: browser_options.PROXY_SOURCE_CUSTOM))
            stack.enter_context(_patched_attr(browser_options, "get_proxy_auth", lambda: "alice:secret"))
            context_args = browser_options._build_context_args(
                headless=False,
                proxy_address="http://127.0.0.1:9999",
                user_agent=None,
            )

        self.assertEqual(
            context_args,
            {
                "proxy": {
                    "server": "http://127.0.0.1:9999",
                    "username": "alice",
                    "password": "secret",
                }
            },
        )

    def test_build_launch_args_for_edge_adds_channel_window_position_and_no_proxy(self) -> None:
        launch_args = browser_options._build_launch_args(
            browser_name="edge",
            headless=False,
            window_position=(10, 20),
            append_no_proxy=True,
        )

        self.assertEqual(launch_args["channel"], "msedge")
        self.assertFalse(launch_args["headless"])
        self.assertIn("--disable-gpu", launch_args["args"])
        self.assertIn("--disable-extensions", launch_args["args"])
        self.assertIn("--disable-background-networking", launch_args["args"])
        self.assertIn("--window-position=10,20", launch_args["args"])
        self.assertIn("--no-proxy-server", launch_args["args"])

    def test_error_detectors_match_proxy_and_disconnect_messages(self) -> None:
        self.assertTrue(browser_options._is_proxy_tunnel_error(RuntimeError("net::ERR_PROXY_CONNECTION_FAILED")))
        self.assertTrue(browser_options._is_browser_disconnected_error(RuntimeError("Target page, context or browser has been closed")))
        self.assertFalse(browser_options._is_proxy_tunnel_error(RuntimeError("plain error")))
        self.assertFalse(browser_options._is_browser_disconnected_error(RuntimeError("plain error")))


class BrowserStartupTests(unittest.TestCase):
    def test_is_playwright_startup_environment_error_detects_socket_block(self) -> None:
        exc = PermissionError(errno.EACCES, "socket blocked by firewall")
        self.assertTrue(browser_startup.is_playwright_startup_environment_error(exc))

    def test_is_playwright_startup_environment_error_detects_winsock_breakage(self) -> None:
        exc = OSError("winsock provider failed")
        exc.winerror = 10106
        self.assertTrue(browser_startup.is_playwright_startup_environment_error(exc))

    def test_describe_playwright_startup_error_humanizes_asyncio_subprocess_issue(self) -> None:
        root = NotImplementedError("create_subprocess_exec is unavailable")
        exc = RuntimeError("wrapper")
        exc.__cause__ = root

        message = browser_startup.describe_playwright_startup_error(exc)

        self.assertIn("Windows asyncio 子进程能力不可用", message)

    def test_describe_playwright_startup_error_humanizes_broken_asyncio_import(self) -> None:
        exc = NameError("name 'base_events' is not defined")

        message = browser_startup.describe_playwright_startup_error(exc)

        self.assertIn("WinError 10106", message)

    def test_classify_playwright_startup_error_uses_shared_environment_kind(self) -> None:
        exc = NameError("name 'base_events' is not defined")

        info = browser_startup.classify_playwright_startup_error(exc)

        self.assertEqual(info.kind, browser_startup.BROWSER_STARTUP_ERROR_ENVIRONMENT)
        self.assertTrue(info.is_environment_error)

    def test_start_playwright_runtime_retries_known_environment_error_then_succeeds(self) -> None:
        class _FakeSyncPlaywright:
            def __init__(self) -> None:
                self.start_calls = 0

            def __call__(self):
                return self

            def start(self):
                self.start_calls += 1
                if self.start_calls == 1:
                    exc = PermissionError(errno.EACCES, "socket blocked")
                    exc.winerror = 10013
                    raise exc
                return "pw-runtime"

        fake_sync = _FakeSyncPlaywright()
        sleep_calls: list[float] = []

        with ExitStack() as stack:
            stack.enter_context(_patched_attr(browser_startup, "_load_playwright_sync", lambda: (fake_sync, object())))
            stack.enter_context(_patched_attr(browser_startup.gc, "collect", lambda: None))
            stack.enter_context(_patched_attr(browser_startup.time, "sleep", lambda seconds: sleep_calls.append(seconds)))
            runtime = browser_startup._start_playwright_runtime()

        self.assertEqual(runtime, "pw-runtime")
        self.assertEqual(fake_sync.start_calls, 2)
        self.assertEqual(sleep_calls, [0.35])

    def test_start_playwright_runtime_does_not_retry_unknown_error(self) -> None:
        class _FakeSyncPlaywright:
            def __call__(self):
                return self

            def start(self):
                raise RuntimeError("boom")

        with _patched_attr(browser_startup, "_load_playwright_sync", lambda: (_FakeSyncPlaywright(), object())):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                browser_startup._start_playwright_runtime()


class BrowserDriverTests(unittest.TestCase):
    def test_create_transient_driver_uses_normalized_proxy_path_without_name_error(self) -> None:
        fake_page = object()

        class _FakeContext:
            def new_page(self):
                return fake_page

        class _FakeBrowser:
            process = None

            def new_context(self, **_kwargs):
                return _FakeContext()

        class _FakeChromium:
            def launch(self, **_kwargs):
                return _FakeBrowser()

        class _FakePlaywright:
            chromium = _FakeChromium()

        with ExitStack() as stack:
            stack.enter_context(_patched_attr(browser_transient, "normalize_proxy_address", lambda value: value))
            stack.enter_context(_patched_attr(browser_transient, "_start_playwright_runtime", lambda: _FakePlaywright()))
            stack.enter_context(_patched_attr(browser_transient, "_build_launch_args", lambda **_kwargs: {"headless": True, "args": []}))
            stack.enter_context(_patched_attr(browser_transient, "_build_context_args", lambda **_kwargs: {}))
            driver, browser_name = browser_transient._create_transient_driver(
                headless=True,
                prefer_browsers=["edge"],
                proxy_address="http://127.0.0.1:8888",
                user_agent="UA-Test",
                window_position=None,
            )

        self.assertEqual(browser_name, "edge")
        self.assertIs(driver.page, fake_page)


if __name__ == "__main__":
    unittest.main()

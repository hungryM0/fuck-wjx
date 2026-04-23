from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from software.core.engine.execution_loop import ExecutionLoop
from software.core.task import ExecutionConfig, ExecutionState


class _FakeBrowserSession:
    def __init__(self, create_browser_exception: Exception | None = None, driver: object | None = None):
        self.create_browser_exception = create_browser_exception
        self.driver = driver
        self.proxy_address = ""
        self.dispose_called = 0
        self.shutdown_called = 0

    def create_browser(self, *_args, **_kwargs):
        if self.create_browser_exception is not None:
            raise self.create_browser_exception
        return "edge"

    def dispose(self) -> None:
        self.dispose_called += 1
        self.driver = None

    def shutdown(self) -> None:
        self.shutdown_called += 1


class ExecutionLoopTests(unittest.TestCase):
    def test_run_thread_finishes_cleanly_when_url_is_empty(self) -> None:
        config = ExecutionConfig(url="")
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = _FakeBrowserSession(driver=object())

        with patch("software.core.engine.execution_loop.BrowserSessionService", return_value=session):
            loop = ExecutionLoop(config, state)
            loop.run_thread(0, 0, stop_signal)

        self.assertFalse(stop_signal.is_set())
        self.assertEqual(session.shutdown_called, 1)
        self.assertEqual(state.thread_progress["MainThread"].status_text, "已停止")
        self.assertFalse(state.thread_progress["MainThread"].running)

    def test_run_thread_stops_when_browser_environment_is_blocked(self) -> None:
        config = ExecutionConfig(url="https://example.com")
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = _FakeBrowserSession(create_browser_exception=RuntimeError("blocked"))

        with patch("software.core.engine.execution_loop.BrowserSessionService", return_value=session), \
             patch("software.core.engine.execution_loop.describe_playwright_startup_error", return_value="环境阻止启动"), \
             patch("software.core.engine.execution_loop.is_playwright_startup_environment_error", return_value=True):
            loop = ExecutionLoop(config, state)
            loop.run_thread(0, 0, stop_signal)

        self.assertTrue(stop_signal.is_set())
        self.assertEqual(state.get_terminal_stop_snapshot()[0], "browser_environment")
        self.assertEqual(session.shutdown_called, 1)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import threading
import unittest
from contextlib import ExitStack, contextmanager
from types import MethodType, SimpleNamespace

import software.core.engine.execution_loop as execution_loop_module
from software.core.engine.execution_loop import ExecutionLoop, _load_survey_page
from software.core.task import ExecutionConfig, ExecutionState
from software.network.browser import BrowserStartupErrorInfo


@contextmanager
def _patched_attr(target, name: str, value):
    original = getattr(target, name)
    setattr(target, name, value)
    try:
        yield
    finally:
        setattr(target, name, original)


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


class _FakeDriver:
    def __init__(self, failures: int = 0):
        self.failures = failures
        self.calls: list[tuple[str, int, str]] = []

    def get(self, url: str, timeout: int = 20000, wait_until: str = "domcontentloaded") -> None:
        self.calls.append((url, timeout, wait_until))
        if self.failures > 0:
            self.failures -= 1
            raise TimeoutError("goto timeout")


class _FakeStopPolicy:
    def __init__(self, *, stop_on_failure: bool = True, success_should_stop: bool = True):
        self.stop_on_failure = stop_on_failure
        self.success_should_stop = success_should_stop
        self.failure_calls: list[object] = []
        self.success_calls = 0

    def wait_if_paused(self, _stop_signal: threading.Event) -> None:
        return None

    def record_failure(self, stop_signal: threading.Event, **kwargs):
        self.failure_calls.append(kwargs.get("failure_reason"))
        if self.stop_on_failure and not stop_signal.is_set():
            stop_signal.set()
        return self.stop_on_failure

    def record_success(self, _stop_signal: threading.Event, **_kwargs):
        self.success_calls += 1
        return self.success_should_stop


class _FakeSubmissionService:
    def __init__(self, outcome: SimpleNamespace, before_return=None):
        self.outcome = outcome
        self.before_return = before_return
        self.calls = 0

    def finalize_after_submit(self, _driver, *, stop_signal: threading.Event, **_kwargs):
        self.calls += 1
        if callable(self.before_return):
            self.before_return(stop_signal)
        return self.outcome


class ExecutionLoopTests(unittest.TestCase):
    def test_load_survey_page_keeps_default_timeout_for_non_credamo(self) -> None:
        config = ExecutionConfig(url="https://example.com", survey_provider="wjx")
        driver = _FakeDriver()

        _load_survey_page(driver, config)

        self.assertEqual(driver.calls, [("https://example.com", 20000, "domcontentloaded")])

    def test_load_survey_page_retries_credamo_with_commit_after_timeout(self) -> None:
        config = ExecutionConfig(url="https://www.credamo.com/answer.html#/s/demo", survey_provider="credamo")
        driver = _FakeDriver(failures=1)

        _load_survey_page(driver, config)

        self.assertEqual(
            driver.calls,
            [
                ("https://www.credamo.com/answer.html#/s/demo", 45000, "domcontentloaded"),
                ("https://www.credamo.com/answer.html#/s/demo", 45000, "commit"),
            ],
        )

    def test_run_thread_finishes_cleanly_when_url_is_empty(self) -> None:
        config = ExecutionConfig(url="")
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = _FakeBrowserSession(driver=object())

        with _patched_attr(execution_loop_module, "BrowserSessionService", lambda *_args, **_kwargs: session):
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

        with ExitStack() as stack:
            stack.enter_context(_patched_attr(execution_loop_module, "BrowserSessionService", lambda *_args, **_kwargs: session))
            stack.enter_context(
                _patched_attr(
                    execution_loop_module,
                    "classify_playwright_startup_error",
                    lambda _exc: BrowserStartupErrorInfo("browser_environment", "环境阻止启动", True),
                )
            )
            loop = ExecutionLoop(config, state)
            loop.run_thread(0, 0, stop_signal)

        self.assertTrue(stop_signal.is_set())
        self.assertEqual(state.get_terminal_stop_snapshot()[0], "browser_environment")
        self.assertEqual(session.shutdown_called, 1)

    def test_run_thread_disposes_driver_after_page_load_failure(self) -> None:
        config = ExecutionConfig(url="https://example.com")
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = _FakeBrowserSession(driver=object())

        with _patched_attr(execution_loop_module, "BrowserSessionService", lambda *_args, **_kwargs: session):
            loop = ExecutionLoop(config, state)
            loop.stop_policy = _FakeStopPolicy(stop_on_failure=True)
            loop.run_thread(0, 0, stop_signal)

        self.assertTrue(stop_signal.is_set())
        self.assertEqual(session.dispose_called, 1)
        self.assertEqual(session.shutdown_called, 1)

    def test_run_thread_handles_device_quota_limit_and_cleans_up_session(self) -> None:
        config = ExecutionConfig(url="https://example.com", survey_provider="wjx")
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = _FakeBrowserSession(driver=object())

        with ExitStack() as stack:
            stack.enter_context(_patched_attr(execution_loop_module, "BrowserSessionService", lambda *_args, **_kwargs: session))
            stack.enter_context(_patched_attr(execution_loop_module, "_provider_is_device_quota_limit_page", lambda *_args, **_kwargs: True))
            loop = ExecutionLoop(config, state)
            loop.stop_policy = _FakeStopPolicy(stop_on_failure=True)
            loop.run_thread(0, 0, stop_signal)

        self.assertTrue(stop_signal.is_set())
        self.assertEqual(session.dispose_called, 1)
        self.assertEqual(session.shutdown_called, 1)

    def test_run_thread_success_path_calls_submission_service(self) -> None:
        config = ExecutionConfig(url="https://example.com", survey_provider="wjx")
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = _FakeBrowserSession(driver=_FakeDriver())
        outcome = SimpleNamespace(status="success", should_stop=True)

        def _prepare_round_context(self, _stop_signal, *, thread_name: str, session: _FakeBrowserSession) -> bool:
            del thread_name, session
            return True

        with ExitStack() as stack:
            stack.enter_context(_patched_attr(execution_loop_module, "BrowserSessionService", lambda *_args, **_kwargs: session))
            stack.enter_context(_patched_attr(execution_loop_module, "_provider_is_device_quota_limit_page", lambda *_args, **_kwargs: False))
            stack.enter_context(_patched_attr(execution_loop_module, "_provider_fill_survey", lambda *_args, **_kwargs: True))
            loop = ExecutionLoop(config, state)
            loop.stop_policy = _FakeStopPolicy(stop_on_failure=True, success_should_stop=True)
            loop.submission_service = _FakeSubmissionService(outcome)
            loop._prepare_round_context = MethodType(_prepare_round_context, loop)
            loop.run_thread(0, 0, stop_signal)

        self.assertEqual(loop.submission_service.calls, 1)
        self.assertEqual(loop.stop_policy.success_calls, 0)
        self.assertEqual(session.dispose_called, 1)
        self.assertEqual(session.shutdown_called, 1)

    def test_run_thread_submission_failure_disposes_driver(self) -> None:
        config = ExecutionConfig(url="https://example.com", survey_provider="wjx")
        state = ExecutionState(config=config)
        stop_signal = threading.Event()
        session = _FakeBrowserSession(driver=_FakeDriver())
        outcome = SimpleNamespace(status="failure", should_stop=False)

        def _prepare_round_context(self, _stop_signal, *, thread_name: str, session: _FakeBrowserSession) -> bool:
            del thread_name, session
            return True

        with ExitStack() as stack:
            stack.enter_context(_patched_attr(execution_loop_module, "BrowserSessionService", lambda *_args, **_kwargs: session))
            stack.enter_context(_patched_attr(execution_loop_module, "_provider_is_device_quota_limit_page", lambda *_args, **_kwargs: False))
            stack.enter_context(_patched_attr(execution_loop_module, "_provider_fill_survey", lambda *_args, **_kwargs: True))
            loop = ExecutionLoop(config, state)
            loop.stop_policy = _FakeStopPolicy(stop_on_failure=True, success_should_stop=False)
            loop.submission_service = _FakeSubmissionService(outcome, before_return=lambda sig: sig.set())
            loop._prepare_round_context = MethodType(_prepare_round_context, loop)
            loop.run_thread(0, 0, stop_signal)

        self.assertTrue(stop_signal.is_set())
        self.assertEqual(loop.submission_service.calls, 1)
        self.assertEqual(session.dispose_called, 1)
        self.assertEqual(session.shutdown_called, 1)


if __name__ == "__main__":
    unittest.main()

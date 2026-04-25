from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from software.core.engine.browser_session_service import BrowserSessionService


class _FakeSemaphore:
    def __init__(self) -> None:
        self.acquired = 0
        self.released = 0

    def acquire(self) -> None:
        self.acquired += 1

    def release(self) -> None:
        self.released += 1


class _FakeState:
    def __init__(self) -> None:
        self.semaphore = _FakeSemaphore()
        self.released_threads: list[str] = []

    def get_browser_semaphore(self, _count: int) -> _FakeSemaphore:
        return self.semaphore

    def release_proxy_in_use(self, thread_name: str) -> None:
        self.released_threads.append(thread_name)


class _FakeDriver:
    def __init__(self) -> None:
        self.window_sizes: list[tuple[int, int]] = []
        self.cleanup_marked = False

    def set_window_size(self, width: int, height: int) -> None:
        self.window_sizes.append((width, height))

    def mark_cleanup_done(self) -> bool:
        if self.cleanup_marked:
            return False
        self.cleanup_marked = True
        return True

    def quit(self) -> None:
        return None


class BrowserSessionServiceTests(unittest.TestCase):
    def _build_config(self, *, headless_mode: bool) -> SimpleNamespace:
        return SimpleNamespace(
            headless_mode=headless_mode,
            random_proxy_ip_enabled=False,
            num_threads=1,
        )

    def test_create_browser_keeps_headless_viewport(self) -> None:
        state = _FakeState()
        config = self._build_config(headless_mode=True)
        fake_driver = _FakeDriver()
        service = BrowserSessionService(config, state, gui_instance=None, thread_name="Worker-1")

        with patch("software.core.engine.browser_session_service._select_proxy_for_session", return_value=None), \
             patch("software.core.engine.browser_session_service._select_user_agent_for_session", return_value=("", "")), \
             patch("software.core.engine.browser_session_service.create_browser_manager", return_value=object()), \
             patch("software.core.engine.browser_session_service.create_playwright_driver", return_value=(fake_driver, "edge")):
            browser_name = service.create_browser(["edge"], 0, 0)

        self.assertEqual(browser_name, "edge")
        self.assertEqual(fake_driver.window_sizes, [])

    def test_create_browser_resizes_headed_window(self) -> None:
        state = _FakeState()
        config = self._build_config(headless_mode=False)
        fake_driver = _FakeDriver()
        service = BrowserSessionService(config, state, gui_instance=None, thread_name="Worker-1")

        with patch("software.core.engine.browser_session_service._select_proxy_for_session", return_value=None), \
             patch("software.core.engine.browser_session_service._select_user_agent_for_session", return_value=("", "")), \
             patch("software.core.engine.browser_session_service.create_browser_manager", return_value=object()), \
             patch("software.core.engine.browser_session_service.create_playwright_driver", return_value=(fake_driver, "edge")):
            browser_name = service.create_browser(["edge"], 0, 0)

        self.assertEqual(browser_name, "edge")
        self.assertEqual(fake_driver.window_sizes, [(550, 650)])


if __name__ == "__main__":
    unittest.main()

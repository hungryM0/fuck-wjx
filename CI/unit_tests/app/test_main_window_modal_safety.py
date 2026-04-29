from __future__ import annotations

import unittest
from unittest.mock import patch

from software.ui.shell.main_window_parts.dialogs import MainWindowDialogsMixin
from software.ui.shell.main_window_parts.lifecycle import MainWindowLifecycleMixin
from software.ui.shell.main_window_parts.update import MainWindowUpdateMixin


class _FakeEvent:
    def __init__(self) -> None:
        self.ignored = False

    def ignore(self) -> None:
        self.ignored = True


class _FakeDialogsWindow(MainWindowDialogsMixin):
    def __init__(self) -> None:
        self._thread_token = object()

    def thread(self):
        return self._thread_token


class _FakeLifecycleWindow(MainWindowLifecycleMixin):
    def __init__(self) -> None:
        self._close_request_pending = False
        self._close_request_confirmed = False
        self.close_called = 0
        self.confirm_result = True
        self.cleanup_called = 0
        self._skip_save_on_close = False

    def close(self) -> None:
        self.close_called += 1

    def _confirm_close_with_optional_save(self) -> bool:
        return self.confirm_result

    def _cleanup_runtime_resources_on_close(self) -> None:
        self.cleanup_called += 1


class _FakeUpdateWindow(MainWindowUpdateMixin):
    def __init__(self) -> None:
        self.badge_calls = 0
        self.notification_calls = 0

    def _show_outdated_badge(self) -> None:
        self.badge_calls += 1

    def _do_show_update_notification(self) -> None:
        self.notification_calls += 1


class MainWindowModalSafetyTests(unittest.TestCase):
    def test_dispatch_to_ui_uses_receiver_bound_single_shot(self) -> None:
        window = _FakeDialogsWindow()
        callback_calls: list[str] = []

        def callback():
            callback_calls.append("done")
            return 42

        with patch("software.ui.shell.main_window_parts.dialogs.QThread.currentThread", return_value=object()), \
             patch("software.ui.shell.main_window_parts.dialogs.QCoreApplication.instance", return_value=object()), \
             patch("software.ui.shell.main_window_parts.dialogs.QTimer.singleShot", side_effect=lambda _ms, _receiver, func: func()):
            result = window._dispatch_to_ui(callback)

        self.assertEqual(result, 42)
        self.assertEqual(callback_calls, ["done"])

    def test_dispatch_to_ui_async_uses_receiver_bound_single_shot(self) -> None:
        window = _FakeDialogsWindow()
        callback_calls: list[str] = []

        with patch("software.ui.shell.main_window_parts.dialogs.QThread.currentThread", return_value=object()), \
             patch("software.ui.shell.main_window_parts.dialogs.QCoreApplication.instance", return_value=object()), \
             patch("software.ui.shell.main_window_parts.dialogs.QTimer.singleShot", side_effect=lambda _ms, _receiver, func: func()):
            window._dispatch_to_ui_async(lambda: callback_calls.append("done"))

        self.assertEqual(callback_calls, ["done"])

    def test_schedule_deferred_close_confirmation_retries_close_after_prompt(self) -> None:
        window = _FakeLifecycleWindow()

        with patch("software.ui.shell.main_window_parts.lifecycle.QTimer.singleShot", side_effect=lambda _ms, _receiver, func: func()):
            window._schedule_deferred_close_confirmation()

        self.assertFalse(window._close_request_pending)
        self.assertTrue(window._close_request_confirmed)
        self.assertEqual(window.close_called, 1)

    def test_schedule_deferred_close_confirmation_stops_when_user_cancels(self) -> None:
        window = _FakeLifecycleWindow()
        window.confirm_result = False

        with patch("software.ui.shell.main_window_parts.lifecycle.QTimer.singleShot", side_effect=lambda _ms, _receiver, func: func()):
            window._schedule_deferred_close_confirmation()

        self.assertFalse(window._close_request_pending)
        self.assertFalse(window._close_request_confirmed)
        self.assertEqual(window.close_called, 0)

    def test_finalize_confirmed_close_runs_cleanup_once(self) -> None:
        window = _FakeLifecycleWindow()
        window._close_request_confirmed = True

        window._finalize_confirmed_close()

        self.assertFalse(window._close_request_confirmed)
        self.assertEqual(window.cleanup_called, 1)

    def test_update_notification_is_deferred_to_next_tick(self) -> None:
        window = _FakeUpdateWindow()

        with patch("software.ui.shell.main_window_parts.update.QTimer.singleShot", side_effect=lambda _ms, _receiver, func: func()):
            window._show_update_notification()

        self.assertEqual(window.badge_calls, 1)
        self.assertEqual(window.notification_calls, 1)


if __name__ == "__main__":
    unittest.main()

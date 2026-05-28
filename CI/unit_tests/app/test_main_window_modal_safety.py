from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from software.ui.shell.main_window_parts.dialogs import MainWindowDialogsMixin
from software.ui.shell.main_window_parts.lifecycle import MainWindowLifecycleMixin
from software.ui.shell.main_window_parts.update import MainWindowUpdateMixin


class _FakeSignal:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in list(self.callbacks):
            callback(*args)


class _FakeQtApp:
    def processEvents(self) -> None:
        return


class _FakeDialogsWindow(MainWindowDialogsMixin):
    def __init__(self) -> None:
        self._thread_token: Any = object()
        self._async_dialog_refs = []
        self._task_result_tray_icon = None
        self.visible = True
        self.minimized = False
        self.window_obj = None
        self.window_icon = "icon"

    def thread(self):
        return cast(Any, self._thread_token)

    def isVisible(self) -> bool:
        return self.visible

    def isMinimized(self) -> bool:
        return self.minimized

    def window(self):
        return self.window_obj

    def windowIcon(self):
        return cast(Any, self.window_icon)


class _FakeTitleLabel:
    def __init__(self) -> None:
        self.format = None
        self.text = ""
        self.adjusted = 0

    def setTextFormat(self, fmt) -> None:
        self.format = fmt

    def setText(self, text: str) -> None:
        self.text = str(text)

    def adjustSize(self) -> None:
        self.adjusted += 1


class _FakeLifecycleWindow(MainWindowLifecycleMixin):
    def __init__(self) -> None:
        self._close_request_pending = False
        self._close_request_confirmed = False
        self._is_closing = False
        self.close_called = 0
        self.confirm_result = True
        self.cleanup_called = 0
        self._skip_save_on_close = False
        self.persist_calls = 0
        self.saved_cfg = None
        self.saved_via_dialog = True
        self.cleanup_events = []
        self._random_ip_quota_auto_sync_timer = SimpleNamespace(
            stop=lambda: self._record("quota_timer")
        )
        self._boot_splash = SimpleNamespace(cleanup=lambda: self._record("boot_splash"))
        self._contact_dialog = SimpleNamespace(close=lambda: self._record("contact_dialog"))
        self._quota_redeem_dialog = SimpleNamespace(close=lambda: self._record("quota_dialog"))
        self._log_page = SimpleNamespace(
            _refresh_timer=SimpleNamespace(stop=lambda: self._record("log_timer"))
        )
        self._async_dialog_refs = [
            SimpleNamespace(close=lambda: self._record("async1")),
            SimpleNamespace(close=lambda: self._record("async2")),
        ]
        self.controller = SimpleNamespace(
            request_shutdown_for_close=lambda: self._record("shutdown"),
            config=None,
            running=False,
            _starting=False,
            is_initializing=lambda: False,
            stop_run=lambda: self._record("stop_run"),
            refresh_random_ip_counter=lambda: self._record("refresh_counter"),
            load_saved_config=lambda strict=False: SimpleNamespace(
                question_entries=["q1"],
                questions_info=["info1"],
                answer_rules=["rule1"],
                dimension_groups=["dim1"],
            ),
        )
        self.dashboard = SimpleNamespace(
            _is_closing=False,
            _build_config=lambda: {"dashboard": True},
            apply_config=lambda cfg: self._record(("dashboard_apply", cfg)),
            update_random_ip_counter=lambda count, limit, custom_api: self._record(
                ("counter", count, limit, custom_api)
            ),
        )
        self.workbench_state = SimpleNamespace(
            get_entries=lambda: ["entry1"],
            questions_info=["infoA"],
            entries=["entryA"],
            entry_questions_info=["entryInfoA"],
            set_entries=lambda entries, info: self._record(("set_entries", entries, info)),
        )
        self.runtime_page = SimpleNamespace(
            apply_config=lambda cfg: self._record(("runtime_apply", cfg))
        )
        self.strategy_page = SimpleNamespace(
            set_questions_info=lambda info: self._record(("set_questions_info", info)),
            set_entries=lambda entries, info: self._record(("strategy_entries", entries, info)),
            set_rules=lambda rules: self._record(("rules", rules)),
            set_dimension_groups=lambda groups: self._record(("groups", groups)),
        )
        self._base_window_title = "SurveyController"
        self.titleBar = SimpleNamespace(titleLabel=_FakeTitleLabel())

    def _record(self, item) -> None:
        self.cleanup_events.append(item)

    def close(self) -> bool:
        self.close_called += 1
        return True

    def _confirm_close_with_optional_save(self) -> bool:
        return self.confirm_result

    def _cleanup_runtime_resources_on_close(self) -> None:
        self.cleanup_called += 1

    def _persist_last_session_log(self) -> None:
        self.persist_calls += 1

    def _collect_current_config_snapshot(self):
        self.saved_cfg = cast(Any, "snapshot")
        return self.saved_cfg

    def _save_config_via_dialog(self, cfg) -> bool:
        self.saved_cfg = cfg
        return self.saved_via_dialog


class _FakeToast:
    def __init__(self) -> None:
        self.calls = []

    def info(self, *args, **kwargs) -> None:
        self.calls.append(("info", args, kwargs))

    def success(self, *args, **kwargs) -> None:
        self.calls.append(("success", args, kwargs))

    def warning(self, *args, **kwargs) -> None:
        self.calls.append(("warning", args, kwargs))

    def error(self, *args, **kwargs) -> None:
        self.calls.append(("error", args, kwargs))


class _FakeTrayIcon:
    MessageIcon = SimpleNamespace(Information="info")

    def __init__(self, _parent=None) -> None:
        self.icon = None
        self.visible = False
        self.messages = []

    def setIcon(self, icon) -> None:
        self.icon = icon

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)

    def showMessage(self, title: str, message: str, icon, timeout: int) -> None:
        self.messages.append((title, message, icon, timeout))


class _FakeWidgetButton:
    def __init__(self) -> None:
        self.text = ""
        self.hidden = False
        self.clicked = _FakeSignal()

    def setText(self, text: str) -> None:
        self.text = str(text)

    def hide(self) -> None:
        self.hidden = True


class _FakeButtonLayout:
    def __init__(self) -> None:
        self.inserted = []

    def insertWidget(self, index: int, widget) -> None:
        self.inserted.append((int(index), widget))


class _FakeMessageBox:
    next_exec_result: Any = True
    instances = []

    def __init__(self, title: str, message: str, _parent) -> None:
        self.title = title
        self.message = message
        self.yesButton = _FakeWidgetButton()
        self.cancelButton = _FakeWidgetButton()
        self.buttonLayout = _FakeButtonLayout()
        self.destroyed = _FakeSignal()
        self.opened = False
        self.done_calls = []
        _FakeMessageBox.instances.append(self)

    def exec(self):
        return self.next_exec_result

    def open(self) -> None:
        self.opened = True

    def done(self, value: int) -> None:
        self.done_calls.append(int(value))


class _FakePushButton:
    def __init__(self, text: str, _parent=None) -> None:
        self.text = str(text)
        self.clicked = _FakeSignal()


class _FakeUpdateWindow(MainWindowUpdateMixin):
    def __init__(self) -> None:
        self.badge_calls = 0
        self.notification_calls = 0

    def _show_outdated_badge(self) -> None:
        self.badge_calls += 1

    def _do_show_update_notification(self) -> None:
        self.notification_calls += 1


class MainWindowModalSafetyTests:
    def test_dispatch_to_ui_uses_receiver_bound_single_shot(self) -> None:
        window = _FakeDialogsWindow()
        callback_calls: list[str] = []

        def callback():
            callback_calls.append("done")
            return 42

        with (
            patch(
                "software.ui.shell.main_window_parts.dialogs.QThread.currentThread",
                return_value=object(),
            ),
            patch(
                "software.ui.shell.main_window_parts.dialogs.QCoreApplication.instance",
                return_value=_FakeQtApp(),
            ),
            patch(
                "software.ui.shell.main_window_parts.dialogs.QTimer.singleShot",
                side_effect=lambda _ms, _receiver, func: func(),
            ),
        ):
            result = window._dispatch_to_ui(callback)
        assert result == 42
        assert callback_calls == ["done"]

    def test_dispatch_to_ui_async_uses_receiver_bound_single_shot(self) -> None:
        window = _FakeDialogsWindow()
        callback_calls: list[str] = []
        with (
            patch(
                "software.ui.shell.main_window_parts.dialogs.QThread.currentThread",
                return_value=object(),
            ),
            patch(
                "software.ui.shell.main_window_parts.dialogs.QCoreApplication.instance",
                return_value=_FakeQtApp(),
            ),
            patch(
                "software.ui.shell.main_window_parts.dialogs.QTimer.singleShot",
                side_effect=lambda _ms, _receiver, func: func(),
            ),
        ):
            window._dispatch_to_ui_async(lambda: callback_calls.append("done"))
        assert callback_calls == ["done"]

    def test_dispatch_to_ui_timeout_cancels_late_callback_execution(self) -> None:
        window = _FakeDialogsWindow()
        callback_calls: list[str] = []
        scheduled: list = []

        def callback():
            callback_calls.append("done")
            return 42

        with (
            patch.object(window, "_UI_DISPATCH_TIMEOUT_SECONDS", 0.01),
            patch(
                "software.ui.shell.main_window_parts.dialogs.QThread.currentThread",
                return_value=object(),
            ),
            patch(
                "software.ui.shell.main_window_parts.dialogs.QCoreApplication.instance",
                return_value=_FakeQtApp(),
            ),
            patch(
                "software.ui.shell.main_window_parts.dialogs.QTimer.singleShot",
                side_effect=lambda _ms, _receiver, func: scheduled.append(func),
            ),
        ):
            result = window._dispatch_to_ui(callback)
        assert result is None
        assert callback_calls == []
        assert len(scheduled) == 1
        scheduled[0]()
        assert callback_calls == []

    def test_toast_routes_each_level(self) -> None:
        window = _FakeDialogsWindow()
        toast = _FakeToast()
        with patch("software.ui.shell.main_window_parts.dialogs.InfoBar", toast):
            window._toast("ok", level="success", duration=1)
            window._toast("warn", level="warning", duration=2)
            window._toast("bad", level="error", duration=3)
            window._toast("plain", level="info", duration=4)
        assert [call[0] for call in toast.calls] == ["success", "warning", "error", "info"]

    def test_should_show_system_notification_respects_activation_and_setting(self) -> None:
        window = _FakeDialogsWindow()
        settings = SimpleNamespace(value=lambda _key: True)
        with (
            patch(
                "software.ui.shell.main_window_parts.dialogs.app_settings",
                return_value=settings,
            ),
            patch(
                "software.ui.shell.main_window_parts.dialogs.get_bool_from_qsettings",
                return_value=True,
            ),
            patch.object(window, "_is_window_activated", return_value=False),
        ):
            assert window._should_show_task_result_system_notification() is True
        with (
            patch(
                "software.ui.shell.main_window_parts.dialogs.app_settings",
                return_value=settings,
            ),
            patch(
                "software.ui.shell.main_window_parts.dialogs.get_bool_from_qsettings",
                return_value=False,
            ),
        ):
            assert window._should_show_task_result_system_notification() is False

    def test_show_system_notification_creates_and_reuses_tray_icon(self, monkeypatch) -> None:
        import PySide6.QtWidgets as qt_widgets

        window = _FakeDialogsWindow()
        monkeypatch.setattr(qt_widgets, "QSystemTrayIcon", _FakeTrayIcon, raising=False)
        with patch.object(window, "_should_show_task_result_system_notification", return_value=True):
            window.show_task_result_system_notification("标题", "内容")
            tray = window._task_result_tray_icon
            window.show_task_result_system_notification("标题2", "内容2")
        assert isinstance(tray, _FakeTrayIcon)
        assert tray.visible is True
        assert tray.messages == [
            ("标题", "内容", "info", 5000),
            ("标题2", "内容2", "info", 5000),
        ]

    def test_track_async_dialog_and_message_boxes(self) -> None:
        _FakeMessageBox.instances.clear()
        window = _FakeDialogsWindow()
        logs = []
        with (
            patch("software.ui.shell.main_window_parts.dialogs.MessageBox", _FakeMessageBox),
            patch(
                "software.ui.shell.main_window_parts.dialogs.log_action",
                side_effect=lambda *args, **kwargs: logs.append((args, kwargs)),
            ),
            patch.object(window, "_dispatch_to_ui", side_effect=lambda func: func()),
            patch.object(window, "_dispatch_to_ui_async", side_effect=lambda func: func()),
        ):
            _FakeMessageBox.next_exec_result = True
            assert window.show_confirm_dialog("确认", "继续吗") is True
            _FakeMessageBox.next_exec_result = False
            assert window.show_custom_confirm_dialog_ui("危险", "删吗", "删", "不删") is False
            window.show_message_dialog("消息", "已打开")
        assert len(logs) == 4
        message_box = _FakeMessageBox.instances[-1]
        assert message_box.opened is True
        assert window._async_dialog_refs == [message_box]
        message_box.destroyed.emit()
        assert window._async_dialog_refs == []

    def test_schedule_deferred_close_confirmation_retries_close_after_prompt(self) -> None:
        window = _FakeLifecycleWindow()
        with patch(
            "software.ui.shell.main_window_parts.lifecycle.QTimer.singleShot",
            side_effect=lambda _ms, _receiver, func: func(),
        ):
            window._schedule_deferred_close_confirmation()
        assert not window._close_request_pending
        assert window._close_request_confirmed
        assert window.close_called == 1

    def test_schedule_deferred_close_confirmation_stops_when_user_cancels(self) -> None:
        window = _FakeLifecycleWindow()
        window.confirm_result = False
        with patch(
            "software.ui.shell.main_window_parts.lifecycle.QTimer.singleShot",
            side_effect=lambda _ms, _receiver, func: func(),
        ):
            window._schedule_deferred_close_confirmation()
        assert not window._close_request_pending
        assert not window._close_request_confirmed
        assert window.close_called == 0

    def test_finalize_confirmed_close_runs_cleanup_once(self) -> None:
        window = _FakeLifecycleWindow()
        window._close_request_confirmed = True
        window._finalize_confirmed_close()
        assert not window._close_request_confirmed
        assert window.cleanup_called == 1

    def test_cleanup_runtime_resources_on_close_stops_all_known_resources(self) -> None:
        window = _FakeLifecycleWindow()
        MainWindowLifecycleMixin._cleanup_runtime_resources_on_close(window)
        assert window._is_closing is True
        assert window.dashboard._is_closing is True
        assert window.cleanup_events == [
            "quota_timer",
            "shutdown",
            "boot_splash",
            "log_timer",
            "contact_dialog",
            "quota_dialog",
            "async1",
            "async2",
        ]

    def test_persist_and_collect_config_snapshot(self) -> None:
        window = _FakeLifecycleWindow()
        with (
            patch(
                "software.ui.shell.main_window_parts.lifecycle.get_user_local_data_root",
                return_value="D:/data",
            ),
            patch(
                "software.ui.shell.main_window_parts.lifecycle.finalize_session_log_persistence"
            ) as finalize_mock,
        ):
            MainWindowLifecycleMixin._persist_last_session_log(window)
        finalize_mock.assert_called_once_with("D:/data")

        with patch(
            "software.ui.shell.main_window_parts.lifecycle.build_runtime_config_snapshot",
            return_value="cfg",
        ):
            cfg = MainWindowLifecycleMixin._collect_current_config_snapshot(window)
        assert cfg == "cfg"
        assert window.controller.config == "cfg"

    def test_save_config_via_dialog_and_close_confirmation_paths(self) -> None:
        _FakeMessageBox.instances.clear()
        window = _FakeLifecycleWindow()
        with (
            patch(
                "software.ui.shell.main_window_parts.lifecycle.QFileDialog.getSaveFileName",
                return_value=("D:/cfg.json", "json"),
            ),
            patch("software.io.config.store.save_config") as save_mock,
            patch(
                "software.ui.shell.main_window_parts.lifecycle.get_user_config_directory",
                return_value="D:/configs",
            ),
            patch("software.ui.shell.main_window_parts.lifecycle.os.makedirs"),
        ):
            assert MainWindowLifecycleMixin._save_config_via_dialog(window, "cfg") is True
        save_mock.assert_called_once_with("cfg", "D:/cfg.json")

        with (
            patch(
                "software.ui.shell.main_window_parts.lifecycle.QFileDialog.getSaveFileName",
                return_value=("", "json"),
            ),
            patch("software.ui.shell.main_window_parts.lifecycle.MessageBox", _FakeMessageBox),
            patch(
                "software.ui.shell.main_window_parts.lifecycle.get_user_config_directory",
                return_value="D:/configs",
            ),
            patch("software.ui.shell.main_window_parts.lifecycle.os.makedirs"),
        ):
            _FakeMessageBox.next_exec_result = False
            assert MainWindowLifecycleMixin._save_config_via_dialog(window, "cfg") is False
            _FakeMessageBox.next_exec_result = True
            assert MainWindowLifecycleMixin._save_config_via_dialog(window, "cfg") is True

        settings = SimpleNamespace(value=lambda _key: True)
        with (
            patch(
                "software.ui.shell.main_window_parts.lifecycle.app_settings",
                return_value=settings,
            ),
            patch(
                "software.ui.shell.main_window_parts.lifecycle.get_bool_from_qsettings",
                return_value=True,
            ),
            patch("software.ui.shell.main_window_parts.lifecycle.MessageBox", _FakeMessageBox),
            patch("software.ui.shell.main_window_parts.lifecycle.PushButton", _FakePushButton),
        ):
            _FakeMessageBox.next_exec_result = 0
            assert MainWindowLifecycleMixin._confirm_close_with_optional_save(window) is False
            _FakeMessageBox.next_exec_result = 2
            window.controller.running = True
            assert MainWindowLifecycleMixin._confirm_close_with_optional_save(window) is True
            assert "stop_run" in window.cleanup_events
            _FakeMessageBox.next_exec_result = 1
            window.saved_via_dialog = True
            assert MainWindowLifecycleMixin._confirm_close_with_optional_save(window) is True
            assert window.saved_cfg == "snapshot"

    def test_load_saved_config_and_title_refresh(self) -> None:
        window = _FakeLifecycleWindow()
        cfg = window.controller.load_saved_config()
        MainWindowLifecycleMixin._load_saved_config(window)
        assert ("runtime_apply", cfg) in window.cleanup_events
        assert ("dashboard_apply", cfg) in window.cleanup_events
        assert ("set_entries", ["q1"], ["info1"]) in window.cleanup_events
        assert ("rules", ["rule1"]) in window.cleanup_events
        assert ("groups", ["dim1"]) in window.cleanup_events
        assert "refresh_counter" in window.cleanup_events

        with patch(
            "software.ui.shell.main_window_parts.lifecycle.get_session_snapshot",
            return_value={"authenticated": True, "user_id": 7},
        ):
            MainWindowLifecycleMixin._refresh_title_random_ip_user_id(window)
        assert "(7)" in window.titleBar.titleLabel.text
        assert window.titleBar.titleLabel.adjusted == 1

    def test_on_random_ip_counter_update_always_refreshes_title(self) -> None:
        window = _FakeLifecycleWindow()
        refreshed = []
        window._refresh_title_random_ip_user_id = lambda: refreshed.append("ok")
        MainWindowLifecycleMixin._on_random_ip_counter_update(window, 1, 2, False)
        assert ("counter", 1, 2, False) in window.cleanup_events
        assert refreshed == ["ok"]

    def test_update_notification_is_deferred_to_next_tick(self) -> None:
        window = _FakeUpdateWindow()
        with patch(
            "software.ui.shell.main_window_parts.update.QTimer.singleShot",
            side_effect=lambda _ms, _receiver, func: func(),
        ):
            window._show_update_notification()
        assert window.badge_calls == 1
        assert window.notification_calls == 1

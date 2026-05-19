from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

import software.ui.shell.main_window_parts.update as update_module
from software.ui.shell.main_window_parts.update import MainWindowUpdateMixin


class _FakeSignal:
    def __init__(self) -> None:
        self.callbacks: list[Any] = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)

    def disconnect(self, callback) -> None:
        if callback in self.callbacks:
            self.callbacks.remove(callback)

    def emit(self, *args) -> None:
        for callback in list(self.callbacks):
            callback(*args)


class _FakeTimer:
    single_shots: list[tuple[int, Any, Any]] = []

    def __init__(self, *_args, **_kwargs) -> None:
        self.timeout = _FakeSignal()
        self.started_with: list[int] = []
        self.active = False
        self.single_shot = False
        self.interval = None
        self.stopped = 0

    def setSingleShot(self, enabled: bool) -> None:
        self.single_shot = bool(enabled)

    def start(self, delay: int | None = None) -> None:
        self.active = True
        if delay is not None:
            self.started_with.append(int(delay))

    def stop(self) -> None:
        self.active = False
        self.stopped += 1

    def isActive(self) -> bool:
        return self.active

    def setInterval(self, interval: int) -> None:
        self.interval = int(interval)

    @staticmethod
    def singleShot(delay: int, receiver, callback=None) -> None:
        if callback is None:
            callback = receiver
            receiver = None
        _FakeTimer.single_shots.append((int(delay), receiver, callback))
        callback()


class _FakeWidget:
    def __init__(self, parent=None, text: str = "") -> None:
        self._parent = parent
        self._text = text
        self.visible = False
        self.deleted = 0
        self.fixed_height = 0
        self.stylesheet = ""

    def parent(self):
        return self._parent

    def setParent(self, parent) -> None:
        self._parent = parent

    def hide(self) -> None:
        self.visible = False

    def show(self) -> None:
        self.visible = True

    def deleteLater(self) -> None:
        self.deleted += 1

    def setFixedHeight(self, height: int) -> None:
        self.fixed_height = int(height)

    def setStyleSheet(self, stylesheet: str) -> None:
        self.stylesheet = str(stylesheet)

    def height(self) -> int:
        return 16

    def sizeHint(self):
        return SimpleNamespace(height=lambda: 18)


class _FakeLayout:
    def __init__(self, *_args, **_kwargs) -> None:
        self.widgets: list[Any] = []
        self.contents_margins = None
        self.spacing = None
        self.alignment = None

    def setContentsMargins(self, *margins) -> None:
        self.contents_margins = margins

    def setSpacing(self, spacing: int) -> None:
        self.spacing = int(spacing)

    def setAlignment(self, alignment) -> None:
        self.alignment = alignment

    def addWidget(self, widget, *_args) -> None:
        if widget not in self.widgets:
            self.widgets.append(widget)

    def removeWidget(self, widget) -> None:
        if widget in self.widgets:
            self.widgets.remove(widget)

    def insertWidget(self, index: int, widget, *_args) -> None:
        if widget in self.widgets:
            self.widgets.remove(widget)
        self.widgets.insert(index, widget)

    def indexOf(self, widget) -> int:
        try:
            return self.widgets.index(widget)
        except ValueError:
            return -1

    def count(self) -> int:
        return len(self.widgets)


class _FakeLabel(_FakeWidget):
    def setText(self, text: str) -> None:
        self._text = str(text)


class _FakeBadge(_FakeWidget):
    def __init__(self, text: str, *_args, parent=None, **_kwargs) -> None:
        super().__init__(parent=parent, text=text)
        self.text = text

    @classmethod
    def custom(cls, text: str, *_args, parent=None, **_kwargs):
        return cls(text, parent=parent)


class _FakeSpinner(_FakeWidget):
    def __init__(self, *args, start: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.start_requested = start
        self.started = 0
        self.stopped = 0
        self.fixed_size = None
        self.stroke_width = None

    def setFixedSize(self, width: int, height: int) -> None:
        self.fixed_size = (width, height)

    def setStrokeWidth(self, width: int) -> None:
        self.stroke_width = width

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


class _FakeProgressBarWidget(_FakeWidget):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fixed_size = None
        self.range = None
        self.value = 0
        self.text_visible = True

    def setFixedSize(self, width: int, height: int) -> None:
        self.fixed_size = (width, height)

    def setRange(self, minimum: int, maximum: int) -> None:
        self.range = (minimum, maximum)

    def setValue(self, value: int) -> None:
        self.value = int(value)

    def setTextVisible(self, visible: bool) -> None:
        self.text_visible = bool(visible)


class _FakeButton:
    def __init__(self) -> None:
        self.enabled = True
        self.text = ""
        self.clicked = _FakeSignal()
        self.focused = 0

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def setText(self, text: str) -> None:
        self.text = str(text)

    def setFocus(self) -> None:
        self.focused += 1


class _FakeInfoBar:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.closeButton = _FakeButton()
        self.widgets: list[Any] = []
        self.shown = 0
        self.closed = 0

    def addWidget(self, widget) -> None:
        self.widgets.append(widget)

    def show(self) -> None:
        self.shown += 1

    def close(self) -> None:
        self.closed += 1


class _FakeThread:
    def __init__(self, *_args, **_kwargs) -> None:
        self.started = _FakeSignal()
        self.finished = _FakeSignal()
        self.quitted = 0
        self.wait_calls: list[int] = []
        self.started_flag = False
        self.interruption_requested = 0

    def start(self) -> None:
        self.started_flag = True

    def requestInterruption(self) -> None:
        self.interruption_requested += 1

    def quit(self) -> None:
        self.quitted += 1

    def wait(self, timeout: int) -> bool:
        self.wait_calls.append(int(timeout))
        return True

    def deleteLater(self) -> None:
        return


class _FakeWorker:
    def __init__(self) -> None:
        self.finished = _FakeSignal()
        self.thread = None
        self.deleted = 0

    def moveToThread(self, thread) -> None:
        self.thread = thread

    def run(self) -> None:
        return

    def deleteLater(self) -> None:
        self.deleted += 1


class _FakeTitleBar:
    def __init__(self) -> None:
        self.titleLabel = _FakeLabel(text="Title")
        self.hBoxLayout = _FakeLayout()
        self.hBoxLayout.widgets = [self.titleLabel, object()]


class _FakeUpdateWindow(MainWindowUpdateMixin):
    def __init__(self) -> None:
        self.titleBar = _FakeTitleBar()
        self._settings_page = None
        self._update_check_thread = None
        self._update_check_worker = None
        self._startup_update_check_timer = None
        self._startup_update_notification_timer = None
        self._startup_update_check_completed = False
        self._startup_update_check_suspended = False
        self._startup_update_pending_info = None
        self._latest_badge = None
        self._outdated_badge = None
        self._preview_badge = None
        self._unknown_badge = None
        self._update_checking_spinner = None
        self._title_bar_status_container = None
        self._title_bar_status_layout = None
        self.update_info: Any = None
        self._download_infobar = None
        self._download_container = None
        self._download_layout = None
        self._download_progress_bar = None
        self._download_detail_label = None
        self._download_indeterminate_bar = None
        self._download_indeterminate = False
        self._download_cancelled = False
        self.downloadProgress = SimpleNamespace(emit=lambda *args: self.download_events.append(args))
        self.download_events: list[Any] = []
        self.toast_calls: list[tuple[str, str]] = []
        self.confirm_calls: list[tuple[str, str]] = []
        self.message_calls: list[tuple[str, str, str]] = []
        self.closed = 0
        self._skip_save_on_close = False
        self.visible = True
        self.minimized = False
        self.active = True
        self._boot_splash = None

    def _toast(self, text: str, level: str = "info", duration: int = 2000) -> None:
        self.toast_calls.append((text, level))

    def show_confirm_dialog(self, title: str, message: str) -> bool:
        self.confirm_calls.append((title, message))
        return True

    def show_message_dialog(self, title: str, message: str, level: str = "info") -> None:
        self.message_calls.append((title, message, level))

    def close(self) -> None:
        self.closed += 1

    def isVisible(self) -> bool:
        return self.visible

    def isMinimized(self) -> bool:
        return self.minimized

    def isActiveWindow(self) -> bool:
        return self.active


class MainWindowUpdateLargeTests:
    def _patch_widget_deps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(update_module, "QTimer", _FakeTimer)
        monkeypatch.setattr(update_module, "QWidget", _FakeWidget)
        monkeypatch.setattr(update_module, "QHBoxLayout", _FakeLayout)
        monkeypatch.setattr(update_module, "QVBoxLayout", _FakeLayout)
        monkeypatch.setattr(update_module, "InfoBadge", _FakeBadge)
        monkeypatch.setattr(update_module, "IndeterminateProgressRing", _FakeSpinner)
        monkeypatch.setattr(update_module, "IndeterminateProgressBar", _FakeProgressBarWidget)
        monkeypatch.setattr(update_module, "ProgressBar", _FakeProgressBarWidget)
        monkeypatch.setattr(update_module, "CaptionLabel", _FakeLabel)
        monkeypatch.setattr(update_module, "InfoBar", _FakeInfoBar)
        monkeypatch.setattr(
            update_module,
            "set_indeterminate_progress_ring_active",
            lambda ring, active: setattr(ring, "active", bool(active)),
        )

    def test_preview_version_and_startup_timers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_widget_deps(monkeypatch)
        window = _FakeUpdateWindow()

        monkeypatch.setattr(update_module, "__VERSION__", "3.2.0beta1")
        assert window._is_preview_version() is True
        monkeypatch.setattr(update_module, "__VERSION__", "3.2.0")
        assert window._is_preview_version() is False

        monkeypatch.setattr(
            update_module,
            "app_settings",
            lambda: SimpleNamespace(value=lambda _key: True),
        )
        monkeypatch.setattr(update_module, "get_bool_from_qsettings", lambda value, default: bool(value))
        window._check_update_on_startup()
        assert window._startup_update_check_timer is not None
        assert window._startup_update_check_timer.started_with == [800]

        window._startup_update_pending_info = {"version": "3.3.0"}
        window._schedule_startup_update_notification(500)
        assert window._startup_update_notification_timer.started_with == [500]
        window._cancel_startup_update_check()
        assert window._startup_update_check_timer.stopped == 1
        assert window._startup_update_notification_timer.stopped == 1

    def test_suspend_timeout_and_notification_gate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_widget_deps(monkeypatch)
        window = _FakeUpdateWindow()
        starts: list[str] = []
        notices: list[str] = []
        window._start_update_check_worker = lambda: starts.append("start")
        window._show_update_notification = lambda: notices.append("show")

        window._on_startup_update_check_timeout()
        assert starts == ["start"]

        window._startup_update_check_suspended = True
        window._on_startup_update_check_timeout()
        assert window._startup_update_check_timer.started_with[-1] == 3000

        window._startup_update_pending_info = {"version": "3.3.0"}
        window._startup_update_check_suspended = False
        assert window._can_show_startup_update_notification() is True
        window.visible = False
        assert window._can_show_startup_update_notification() is False
        window.visible = True
        window._on_startup_update_notification_timeout()
        assert notices == ["show"]

    def test_update_checked_and_version_badges(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_widget_deps(monkeypatch)
        window = _FakeUpdateWindow()
        calls: list[str] = []
        window._clear_update_checking_placeholder = lambda: calls.append("clear")
        window._show_outdated_badge = lambda: calls.append("outdated")
        window._show_latest_version_badge = lambda: calls.append("latest")
        window._show_preview_badge = lambda: calls.append("preview")
        window._show_unknown_badge = lambda: calls.append("unknown")
        window._check_preview_version = lambda: calls.append("check-preview")

        window._on_update_checked(True, {"version": "3.3.0"})
        assert window._startup_update_pending_info == {"version": "3.3.0"}
        assert "outdated" in calls

        window._on_update_checked(False, {"status": "latest"})
        window._apply_version_status_badge("preview")
        window._apply_version_status_badge("unknown")
        assert calls.count("clear") >= 2
        assert "latest" in calls
        assert "preview" in calls
        assert "unknown" in calls
        assert "check-preview" in calls

    def test_title_bar_status_container_mount_and_clear(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_widget_deps(monkeypatch)
        window = _FakeUpdateWindow()

        container = window._ensure_title_bar_status_container()
        assert container is not None
        assert window._title_bar_status_layout is not None

        badge = cast(Any, _FakeBadge("最新", parent=window.titleBar))
        assert window._mount_title_bar_status_widget(badge) is True
        assert badge.parent() is container
        assert cast(Any, container).visible is True

        window._clear_title_bar_status_widget(badge)
        assert badge.deleted == 1
        assert cast(Any, container).visible is False

    def test_placeholder_and_badges_render_without_real_qt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_widget_deps(monkeypatch)
        window = _FakeUpdateWindow()

        window._show_update_checking_placeholder()
        assert window._update_checking_spinner is not None
        assert window._update_checking_spinner.fixed_size == (16, 16)

        window._clear_update_checking_placeholder()
        assert window._update_checking_spinner is None

        window._show_latest_version_badge()
        assert window._latest_badge is not None
        window._show_unknown_badge()
        assert window._unknown_badge is not None
        window._show_preview_badge()
        assert window._preview_badge is not None
        window._show_outdated_badge()
        assert window._outdated_badge is not None

    def test_start_and_stop_update_worker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_widget_deps(monkeypatch)
        window = _FakeUpdateWindow()
        worker_module = SimpleNamespace(UpdateCheckWorker=_FakeWorker)
        thread_instances: list[_FakeThread] = []
        monkeypatch.setattr(update_module, "QThread", lambda *_args, **_kwargs: thread_instances.append(_FakeThread()) or thread_instances[-1])
        monkeypatch.setitem(__import__("sys").modules, "software.ui.workers.update_worker", worker_module)
        shown: list[str] = []
        cleared: list[str] = []
        window._show_update_checking_placeholder = lambda: shown.append("show")
        window._clear_update_checking_placeholder = lambda: cleared.append("clear")

        window._start_update_check_worker()
        assert shown == ["show"]
        assert isinstance(window._update_check_worker, _FakeWorker)
        assert isinstance(window._update_check_thread, _FakeThread)

        window._stop_update_check_worker()
        assert window._update_check_thread is None
        assert window._update_check_worker is None
        assert thread_instances[0].interruption_requested == 1
        assert thread_instances[0].quitted == 1
        assert thread_instances[0].wait_calls == [2500]

    def test_download_toast_progress_and_cancel_flow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_widget_deps(monkeypatch)
        window = _FakeUpdateWindow()
        actions: list[Any] = []
        monkeypatch.setattr(update_module, "log_action", lambda *args, **kwargs: actions.append((args, kwargs)))

        window._show_download_toast(0, show_spinner=True)
        assert window._download_indeterminate is True
        assert window._download_infobar is not None

        window._update_download_progress(50, 100, speed=2048)
        assert window._download_progress_bar is not None
        assert window._download_progress_bar.value == 50
        assert window._download_detail_label is not None
        assert window._download_detail_label._text == "50 B / 100 B"

        window._update_download_progress(100, 100, speed=0)
        assert ("下载完成", "success") in window.toast_calls

        window._cancel_download()
        assert window._download_cancelled is True
        assert ("已停止本次自动更新", "warning") in window.toast_calls
        assert actions

    def test_formatters_emit_progress_and_download_finished(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_widget_deps(monkeypatch)
        window = _FakeUpdateWindow()

        assert window._format_size(512) == "512 B"
        assert window._format_size(2048).endswith("KB")
        assert window._format_speed(512) == "512 B/s"
        assert window._format_speed(2048).endswith("KB/s")

        window._emit_download_progress(1, 2, 3.0)
        assert window.download_events == [(1, 2, 3.0)]

        updater_module = __import__("software.update.updater", fromlist=["show_update_notification", "UpdateManager"])
        monkeypatch.setattr(updater_module, "show_update_notification", lambda self: self.toast_calls.append(("notify", "info")))
        monkeypatch.setattr(updater_module.UpdateManager, "apply_downloaded_update", lambda payload: payload.update({"applied": True}))
        window.update_info = {"version": "3.3.0"}
        window._do_show_update_notification()
        assert ("notify", "info") in window.toast_calls

        payload = {"version": "3.3.0", "_velopack_update": {}}
        window._on_download_finished(payload)
        assert window.closed == 1

        window._on_download_finished({})
        assert window.message_calls[-1][0] == "更新失败"

        window._download_cancelled = False
        window._on_download_failed("网络炸了")
        assert window.message_calls[-1] == ("更新失败", "网络炸了", "error")

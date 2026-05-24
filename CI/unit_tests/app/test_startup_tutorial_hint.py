from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QPoint, QRect

import software.ui.shell.main_window as main_window_module
from software.ui.shell.main_window import MainWindow
from software.ui.shell.startup_tutorial import STARTUP_TUTORIAL_HINT_SEEN_SETTING_KEY


class _FakeSignal:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in list(self.callbacks):
            callback(*args)


class _FakeTimer:
    instances = []

    def __init__(self, *_args, **_kwargs) -> None:
        self.timeout = _FakeSignal()
        self.single_shot = False
        self.started_with = []
        _FakeTimer.instances.append(self)

    def setSingleShot(self, enabled: bool) -> None:
        self.single_shot = bool(enabled)

    def start(self, delay: int) -> None:
        self.started_with.append(int(delay))


class _FakeSettings:
    def __init__(self, initial: bool = False) -> None:
        self.values = {STARTUP_TUTORIAL_HINT_SEEN_SETTING_KEY: initial}
        self.set_calls = []

    def value(self, key: str):
        return self.values.get(key)

    def setValue(self, key: str, value) -> None:
        self.values[key] = value
        self.set_calls.append((key, value))


class _FakeTutorialView:
    instances = []

    def __init__(self, _parent=None) -> None:
        self.openRequested = _FakeSignal()
        self.dismissed = _FakeSignal()
        _FakeTutorialView.instances.append(self)


class _FakeFlyout:
    instances = []

    def __init__(self, view, parent, isDeleteOnClose: bool = False) -> None:
        self.view = view
        self.parent = parent
        self.is_delete_on_close = bool(isDeleteOnClose)
        self.closed = _FakeSignal()
        self.show_count = 0
        self.exec_calls = []
        self.close_count = 0
        _FakeFlyout.instances.append(self)

    def show(self) -> None:
        self.show_count += 1

    def sizeHint(self):
        return SimpleNamespace(width=lambda: 320, height=lambda: 180)

    def exec(self, pos, animation) -> None:
        self.exec_calls.append((pos, animation))

    def close(self) -> None:
        self.close_count += 1
        self.closed.emit()


class _FakeScreen:
    def __init__(self, rect: QRect) -> None:
        self._rect = rect

    def availableGeometry(self) -> QRect:
        return self._rect


class _FakeTutorialWindow:
    def __init__(self) -> None:
        self._import_check_mode = False
        self._startup_tutorial_hint_timer = None
        self._startup_tutorial_flyout = None
        self._startup_tutorial_view = None
        self._startup_tutorial_hint_showing = False
        self.visible = True
        self.minimized = False
        self.boot_visible = False
        self.width_value = 900
        self.height_value = 640
        self.global_offset = QPoint(100, 50)
        self.screen_obj = _FakeScreen(QRect(0, 0, 1000, 700))

    def isVisible(self) -> bool:
        return self.visible

    def isMinimized(self) -> bool:
        return self.minimized

    def _is_boot_splash_visible(self) -> bool:
        return self.boot_visible

    def width(self) -> int:
        return self.width_value

    def height(self) -> int:
        return self.height_value

    def mapToGlobal(self, point: QPoint) -> QPoint:
        return point + self.global_offset

    def screen(self):
        return self.screen_obj

    def _has_seen_startup_tutorial_hint(self) -> bool:
        return MainWindow._has_seen_startup_tutorial_hint(self)

    def _mark_startup_tutorial_hint_seen(self) -> None:
        MainWindow._mark_startup_tutorial_hint_seen(self)

    def _schedule_startup_tutorial_hint(self, delay_ms: int) -> None:
        MainWindow._schedule_startup_tutorial_hint(self, delay_ms)

    def _can_show_startup_tutorial_hint(self) -> bool:
        return MainWindow._can_show_startup_tutorial_hint(self)

    def _startup_tutorial_hint_global_pos(self, hint_width: int, hint_height: int) -> QPoint:
        return MainWindow._startup_tutorial_hint_global_pos(self, hint_width, hint_height)

    def _clear_startup_tutorial_refs(self) -> None:
        MainWindow._clear_startup_tutorial_refs(self)

    def _on_startup_tutorial_hint_closed(self) -> None:
        MainWindow._on_startup_tutorial_hint_closed(self)

    def _show_startup_tutorial_hint(self) -> None:
        MainWindow._show_startup_tutorial_hint(self)

    def _open_startup_tutorial_from_hint(self) -> None:
        MainWindow._open_startup_tutorial_from_hint(self)

    def _dismiss_startup_tutorial_hint(self) -> None:
        MainWindow._dismiss_startup_tutorial_hint(self)


def _patch_settings(monkeypatch, initial: bool = False) -> _FakeSettings:
    settings = _FakeSettings(initial)
    monkeypatch.setattr(main_window_module, "app_settings", lambda: settings)
    monkeypatch.setattr(
        main_window_module,
        "get_bool_from_qsettings",
        lambda value, default=False: bool(value) if value is not None else bool(default),
    )
    return settings


def test_startup_tutorial_hint_schedules_on_first_startup(monkeypatch) -> None:
    _FakeTimer.instances.clear()
    _patch_settings(monkeypatch, initial=False)
    monkeypatch.setattr(main_window_module, "QTimer", _FakeTimer)
    window = _FakeTutorialWindow()

    MainWindow._schedule_startup_tutorial_hint(window, 1800)

    assert window._startup_tutorial_hint_timer is _FakeTimer.instances[0]
    assert _FakeTimer.instances[0].single_shot is True
    assert _FakeTimer.instances[0].started_with == [1800]


def test_startup_tutorial_hint_skips_when_seen_or_import_check_mode(monkeypatch) -> None:
    _FakeTimer.instances.clear()
    _patch_settings(monkeypatch, initial=True)
    monkeypatch.setattr(main_window_module, "QTimer", _FakeTimer)
    window = _FakeTutorialWindow()

    MainWindow._schedule_startup_tutorial_hint(window, 1800)
    assert window._startup_tutorial_hint_timer is None

    _patch_settings(monkeypatch, initial=False)
    window._import_check_mode = True
    MainWindow._schedule_startup_tutorial_hint(window, 1800)
    assert window._startup_tutorial_hint_timer is None


def test_startup_tutorial_hint_close_marks_seen_and_clears_refs(monkeypatch) -> None:
    settings = _patch_settings(monkeypatch, initial=False)
    window = _FakeTutorialWindow()
    window._startup_tutorial_hint_showing = True
    window._startup_tutorial_flyout = object()
    window._startup_tutorial_view = object()

    MainWindow._on_startup_tutorial_hint_closed(window)

    assert settings.values[STARTUP_TUTORIAL_HINT_SEEN_SETTING_KEY] is True
    assert settings.set_calls == [(STARTUP_TUTORIAL_HINT_SEEN_SETTING_KEY, True)]
    assert window._startup_tutorial_hint_showing is False
    assert window._startup_tutorial_flyout is None
    assert window._startup_tutorial_view is None


def test_startup_tutorial_hint_does_not_duplicate_active_flyout(monkeypatch) -> None:
    _FakeTutorialView.instances.clear()
    _FakeFlyout.instances.clear()
    _patch_settings(monkeypatch, initial=False)
    monkeypatch.setattr(main_window_module, "StartupTutorialFlyoutView", _FakeTutorialView)
    monkeypatch.setattr(main_window_module, "Flyout", _FakeFlyout)
    window = _FakeTutorialWindow()

    MainWindow._show_startup_tutorial_hint(window)
    MainWindow._show_startup_tutorial_hint(window)

    assert len(_FakeTutorialView.instances) == 1
    assert len(_FakeFlyout.instances) == 1
    assert window._startup_tutorial_hint_showing is True


def test_startup_tutorial_hint_position_is_clamped_to_screen(monkeypatch) -> None:
    monkeypatch.setattr(
        main_window_module,
        "QGuiApplication",
        SimpleNamespace(screenAt=lambda _pos: None, primaryScreen=lambda: None),
    )
    window = _FakeTutorialWindow()
    window.width_value = 240
    window.height_value = 160
    window.global_offset = QPoint(920, 640)
    window.screen_obj = _FakeScreen(QRect(0, 0, 1000, 700))

    pos = MainWindow._startup_tutorial_hint_global_pos(window, 320, 180)

    assert pos.x() == 652
    assert pos.y() == 492

from __future__ import annotations

from PySide6.QtCore import QAbstractAnimation
from PySide6.QtWidgets import QWidget
from qfluentwidgets import IndeterminateProgressBar, InfoBarPosition
from shiboken6 import isValid

from software.ui.helpers.message_bar import replace_message_bar, show_message_bar
from software.ui.helpers.qfluent_compat import install_qfluentwidgets_animation_guards
import software.ui.shell.main_window as main_window_module
from software.ui.shell.main_window import create_window


def test_real_infobar_top_message_bar_stays_usable_after_upgrade(qtbot) -> None:
    install_qfluentwidgets_animation_guards()

    host = QWidget()
    host.resize(520, 260)
    host.show()
    qtbot.addWidget(host)

    bar = show_message_bar(
        parent=host,
        title="",
        message="升级冒烟",
        level="info",
        position=InfoBarPosition.TOP,
        duration=-1,
    )
    qtbot.waitUntil(lambda: bar.isVisible(), timeout=1000)
    qtbot.wait(50)

    assert bar.parent() is host
    assert bar.position == InfoBarPosition.TOP
    assert bar.x() >= 0
    assert bar.y() >= 0

    replace_message_bar(bar)
    qtbot.waitUntil(lambda: (not isValid(bar)) or (not bar.isVisible()), timeout=2000)
    host.close()
    qtbot.waitUntil(lambda: not host.isVisible(), timeout=1000)


def test_real_indeterminate_progress_bar_can_pause_resume_after_upgrade(qtbot) -> None:
    install_qfluentwidgets_animation_guards()

    bar = IndeterminateProgressBar(start=True)
    qtbot.addWidget(bar)
    bar.show()

    qtbot.waitUntil(
        lambda: bar.aniGroup.state() == QAbstractAnimation.State.Running,
        timeout=1000,
    )
    bar.setPaused(True)
    qtbot.waitUntil(
        lambda: bar.aniGroup.state() == QAbstractAnimation.State.Paused,
        timeout=1000,
    )

    bar.setPaused(False)
    qtbot.waitUntil(
        lambda: bar.aniGroup.state() == QAbstractAnimation.State.Running,
        timeout=1000,
    )

    bar.stop()
    qtbot.waitUntil(
        lambda: bar.aniGroup.state() == QAbstractAnimation.State.Stopped,
        timeout=1000,
    )

    bar.resume()
    qtbot.waitUntil(
        lambda: bar.aniGroup.state() == QAbstractAnimation.State.Running,
        timeout=1000,
    )


def test_main_window_real_startup_smoke_under_upgraded_qt_stack(monkeypatch, qtbot) -> None:
    install_qfluentwidgets_animation_guards()
    monkeypatch.setenv("WJX_IMPORT_CHECK", "1")

    window = create_window()
    window._schedule_deferred_close_confirmation = lambda: None
    window.controller.request_shutdown_for_close = lambda timeout_seconds=5.0: None

    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.isVisible(), timeout=1000)

    assert window.windowTitle().startswith("SurveyController v")
    assert window.navigationInterface is not None
    assert window.stackedWidget.count() >= 4
    assert window.workbench is not None

    window._close_request_confirmed = True
    window.close()
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=1000)


def test_macos_import_check_uses_lightweight_window(monkeypatch, qtbot) -> None:
    monkeypatch.setenv("WJX_IMPORT_CHECK", "1")
    monkeypatch.setattr(main_window_module.sys, "platform", "darwin")

    window = main_window_module.create_window()

    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.isVisible(), timeout=1000)

    assert window.windowTitle().startswith("SurveyController v")
    assert window.navigationInterface is not None
    assert window.stackedWidget.count() >= 4
    assert window.workbench is not None

    window.close()
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=1000)

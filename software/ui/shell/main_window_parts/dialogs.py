"""MainWindow 对话框与线程安全弹窗方法。"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any, Callable, Dict, cast

from PySide6.QtCore import QObject, QCoreApplication, QThread, QTimer
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QDialog
from qfluentwidgets import InfoBar, InfoBarPosition, MessageBox

from software.app.config import (
    TASK_RESULT_SYSTEM_NOTIFICATION_SETTING_KEY,
    app_settings,
    get_bool_from_qsettings,
)
from software.logging.action_logger import log_action


class MainWindowDialogsMixin:
    """为主窗口提供线程安全的消息提示与确认对话框。"""

    _UI_DISPATCH_TIMEOUT_SECONDS = 5.0

    if TYPE_CHECKING:
        _task_result_tray_icon: Any
        _async_dialog_refs: Any

        def thread(self) -> QThread: ...
        def isVisible(self) -> bool: ...
        def isMinimized(self) -> bool: ...
        def window(self) -> Any: ...
        def windowIcon(self) -> QIcon: ...

    def _qt_timer_context(self) -> QObject:
        """声明该 mixin 只用于 QObject 宿主，统一提供定时器回调上下文。"""
        return cast(QObject, self)

    def _dispatch_to_ui(self, func: Callable[[], Any]) -> Any:
        if cast(QObject, self).thread() == QThread.currentThread():
            return func()
        if QCoreApplication.instance() is None:
            return func()

        done = threading.Event()
        result: Dict[str, Any] = {}
        ticket = object()

        def _wrapper():
            if result.get("cancelled") is ticket:
                done.set()
                return
            try:
                result["value"] = func()
            finally:
                done.set()

        QTimer.singleShot(0, self._qt_timer_context(), _wrapper)

        if not done.wait(timeout=self._UI_DISPATCH_TIMEOUT_SECONDS):
            result["cancelled"] = ticket
            logging.warning("UI 调度超时，放弃执行回调以避免阻塞")
            return None
        return result.get("value")

    def _toast(self, text: str, level: str = "info", duration: int = 2000):
        kind = level.lower()
        if kind == "success":
            InfoBar.success(
                "",
                text,
                parent=self,
                position=InfoBarPosition.TOP,
                duration=duration,
            )
        elif kind == "warning":
            InfoBar.warning(
                "",
                text,
                parent=self,
                position=InfoBarPosition.TOP,
                duration=duration,
            )
        elif kind == "error":
            InfoBar.error(
                "",
                text,
                parent=self,
                position=InfoBarPosition.TOP,
                duration=duration,
            )
        else:
            InfoBar.info(
                "",
                text,
                parent=self,
                position=InfoBarPosition.TOP,
                duration=duration,
            )

    def _dispatch_to_ui_async(self, func: Callable[[], Any]) -> None:
        if cast(QObject, self).thread() == QThread.currentThread():
            func()
            return
        if QCoreApplication.instance() is None:
            func()
            return
        QTimer.singleShot(0, self._qt_timer_context(), func)

    def _is_window_activated(self) -> bool:
        try:
            if not self.isVisible() or self.isMinimized():
                return False
        except Exception:
            return False
        try:
            window = cast(Any, self.window())
            if window is not None and hasattr(window, "isActiveWindow") and window.isActiveWindow():
                return True
        except Exception:
            pass
        try:
            active = QApplication.activeWindow() or QGuiApplication.focusWindow()
            return active is not None
        except Exception:
            return False

    def _should_show_task_result_system_notification(self) -> bool:
        settings = app_settings()
        return (
            get_bool_from_qsettings(
                settings.value(TASK_RESULT_SYSTEM_NOTIFICATION_SETTING_KEY),
                True,
            )
            and not self._is_window_activated()
        )

    def _should_show_task_result_windows_notification(self) -> bool:
        return self._should_show_task_result_system_notification()

    def show_task_result_system_notification(self, title: str, message: str) -> None:
        if not self._should_show_task_result_system_notification():
            return
        try:
            from PySide6.QtWidgets import QSystemTrayIcon
        except Exception:
            return

        tray = getattr(self, "_task_result_tray_icon", None)
        if tray is None:
            tray = QSystemTrayIcon(cast(QObject, self))
            tray.setIcon(self.windowIcon())
            tray.setVisible(True)
            self._task_result_tray_icon = tray
        tray.showMessage(
            str(title or ""),
            str(message or ""),
            QSystemTrayIcon.MessageIcon.Information,
            5000,
        )

    def show_task_result_windows_notification(self, title: str, message: str) -> None:
        self.show_task_result_system_notification(title, message)

    def _track_async_dialog(self, dialog: QDialog) -> None:
        dialogs = getattr(self, "_async_dialog_refs", None)
        if dialogs is None:
            dialogs = []
            self._async_dialog_refs = dialogs
        dialogs.append(dialog)

        def _cleanup(*_args) -> None:
            current = getattr(self, "_async_dialog_refs", None) or []
            try:
                current.remove(dialog)
            except ValueError:
                pass

        dialog.destroyed.connect(_cleanup)

    def show_confirm_dialog(self, title: str, message: str) -> bool:
        """显示确认对话框，返回用户是否确认。"""

        def _show():
            log_action(
                "DIALOG",
                "confirm",
                "message_box",
                "main_window",
                result="shown",
                detail=title,
            )
            box = MessageBox(title, message, self)
            box.yesButton.setText("确定")
            box.cancelButton.setText("取消")
            accepted = bool(box.exec())
            log_action(
                "DIALOG",
                "confirm",
                "message_box",
                "main_window",
                result="confirmed" if accepted else "cancelled",
                detail=title,
            )
            return accepted

        return bool(self._dispatch_to_ui(_show))

    def show_custom_confirm_dialog_ui(
        self,
        title: str,
        message: str,
        yes_text: str,
        cancel_text: str,
    ) -> bool:
        """在 UI 线程显示自定义按钮确认框。"""
        def _show() -> bool:
            log_action(
                "DIALOG",
                "confirm",
                "message_box",
                "main_window",
                result="shown",
                detail=title,
            )
            box = MessageBox(title, message, self)
            box.yesButton.setText(str(yes_text or "确定"))
            box.cancelButton.setText(str(cancel_text or "取消"))
            accepted = bool(box.exec())
            log_action(
                "DIALOG",
                "confirm",
                "message_box",
                "main_window",
                result="confirmed" if accepted else "cancelled",
                detail=title,
            )
            return accepted

        return bool(self._dispatch_to_ui(_show))

    def show_message_dialog(self, title: str, message: str, *, level: str = "info") -> None:
        """显示消息对话框。level 仅用于日志/调用语义，不影响窗口样式。"""
        _ = level

        def _show():
            box = MessageBox(title, message, self)
            box.yesButton.setText("确定")
            box.cancelButton.hide()
            self._track_async_dialog(box)
            box.open()

        self._dispatch_to_ui_async(_show)

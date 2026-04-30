"""MainWindow 对话框与线程安全弹窗方法。"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, cast

from PySide6.QtCore import QObject, QCoreApplication, QThread, QTimer
from PySide6.QtWidgets import QDialog
from qfluentwidgets import InfoBar, InfoBarPosition, MessageBox
from software.logging.action_logger import log_action


class MainWindowDialogsMixin:
    """为主窗口提供线程安全的消息提示与确认对话框。"""

    def _qt_timer_context(self) -> QObject:
        """声明该 mixin 只用于 QObject 宿主，统一提供定时器回调上下文。"""
        return cast(QObject, self)

    def _dispatch_to_ui(self, func: Callable[[], Any]) -> Any:
        if self.thread() == QThread.currentThread():  # type: ignore[attr-defined]
            return func()
        if QCoreApplication.instance() is None:
            return func()

        done = threading.Event()
        result: Dict[str, Any] = {}

        def _wrapper():
            try:
                result["value"] = func()
            finally:
                done.set()

        QTimer.singleShot(0, self._qt_timer_context(), _wrapper)

        if not done.wait(timeout=5):
            logging.warning("UI 调度超时，放弃执行回调以避免阻塞")
            return None
        return result.get("value")

    def _toast(self, text: str, level: str = "info", duration: int = 2000):
        kind = level.lower()
        if kind == "success":
            InfoBar.success("", text, parent=self, position=InfoBarPosition.TOP, duration=duration)
        elif kind == "warning":
            InfoBar.warning("", text, parent=self, position=InfoBarPosition.TOP, duration=duration)
        elif kind == "error":
            InfoBar.error("", text, parent=self, position=InfoBarPosition.TOP, duration=duration)
        else:
            InfoBar.info("", text, parent=self, position=InfoBarPosition.TOP, duration=duration)

    def _dispatch_to_ui_async(self, func: Callable[[], Any]) -> None:
        if self.thread() == QThread.currentThread():  # type: ignore[attr-defined]
            func()
            return
        if QCoreApplication.instance() is None:
            func()
            return
        QTimer.singleShot(0, self._qt_timer_context(), func)

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
            log_action("DIALOG", "confirm", "message_box", "main_window", result="shown", detail=title)
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
        log_action("DIALOG", "confirm", "message_box", "main_window", result="shown", detail=title)
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

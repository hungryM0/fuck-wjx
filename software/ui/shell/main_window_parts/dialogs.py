"""MainWindow 对话框与线程安全弹窗方法。"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict

from PySide6.QtCore import QCoreApplication, QThread, QTimer
from qfluentwidgets import InfoBar, InfoBarPosition, MessageBox
from software.logging.action_logger import log_action


class MainWindowDialogsMixin:
    """为主窗口提供线程安全的消息提示与确认对话框。"""

    def _dispatch_to_ui(self, func):
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

        QTimer.singleShot(0, _wrapper)

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

    def show_message_dialog(self, title: str, message: str, *, level: str = "info") -> None:
        """显示消息对话框。level 仅用于日志/调用语义，不影响窗口样式。"""
        _ = level

        def _show():
            box = MessageBox(title, message, self)
            box.yesButton.setText("确定")
            box.cancelButton.hide()
            box.exec()

        self._dispatch_to_ui(_show)

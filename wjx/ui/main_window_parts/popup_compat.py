"""MainWindow 弹窗与线程调度兼容层。"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict

from PySide6.QtCore import QCoreApplication, QThread, QTimer
from qfluentwidgets import InfoBar, InfoBarPosition, MessageBox


class MainWindowPopupCompatMixin:
    """兼容历史弹窗接口，支持跨线程调用。"""

    def _dispatch_to_ui(self, func):
        if self.thread() == QThread.currentThread():  # type: ignore[attr-defined]
            return func()
        # 若未启动 Qt 事件循环，直接执行以避免死锁
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

    def _log_popup_confirm(self, title: str, message: str, *_args, **_kwargs) -> bool:
        """显示确认对话框，返回用户是否确认（线程安全）。"""

        def _show():
            box = MessageBox(title, message, self)
            box.yesButton.setText("确定")
            box.cancelButton.setText("取消")
            return bool(box.exec())

        return bool(self._dispatch_to_ui(_show))

    def _log_popup_message(self, title: str, message: str, *_args, **_kwargs):
        """显示消息对话框（线程安全）。"""

        def _show():
            box = MessageBox(title, message, self)
            box.yesButton.setText("确定")
            box.cancelButton.hide()
            box.exec()

        self._dispatch_to_ui(_show)

    # 保留别名以兼容现有调用
    def _log_popup_info(self, title: str, message: str, *_args, **_kwargs):
        self._log_popup_message(title, message)

    def _log_popup_error(self, title: str, message: str, *_args, **_kwargs):
        self._log_popup_message(title, message)

    def _log_popup_warning(self, title: str, message: str, *_args, **_kwargs):
        self._log_popup_message(title, message)

"""联系开发者对话框"""

from typing import cast

from PySide6.QtCore import Qt, QTimer
from PySide6.QtCore import QObject
from PySide6.QtGui import QCloseEvent, QShowEvent
from qfluentwidgets import MessageBoxBase

from software.ui.helpers.qfluent_compat import resolve_mask_dialog_parent
from software.ui.widgets.contact_form.widget import ContactForm

_DIALOG_MAX_WIDTH = 760
_DIALOG_MAX_HEIGHT = 620
_DIALOG_MIN_WIDTH = 640
_DIALOG_MIN_HEIGHT = 520
_DIALOG_PARENT_MARGIN = 64


class ContactDialog(MessageBoxBase):
    """联系开发者（Qt 版本）。包装 ContactForm，保留原有对话框入口。"""

    def __init__(
        self,
        parent=None,
        default_type: str = "报错反馈",
        lock_message_type: bool = False,
        status_endpoint: str = "",
        status_formatter=None,
    ):
        resolved_parent = resolve_mask_dialog_parent(parent)
        super().__init__(resolved_parent)
        self._fallback_parent = resolved_parent if resolved_parent is not parent else None
        if self._fallback_parent is not None:
            self.destroyed.connect(self._fallback_parent.deleteLater)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle("联系开发者")
        self.yesButton.hide()
        self.cancelButton.hide()
        self.buttonGroup.hide()
        self.buttonGroup.setFixedHeight(0)
        self._set_center_widget_size(resolved_parent)
        self._status_poll_timer = QTimer(cast(QObject, self))
        self._status_poll_timer.setSingleShot(True)
        self._status_poll_timer.setInterval(700)
        self._status_poll_timer.timeout.connect(self._start_status_polling_if_ready)

        self.viewLayout.setContentsMargins(18, 18, 18, 18)
        self.viewLayout.setSpacing(12)

        self.form = ContactForm(
            self,
            default_type=default_type,
            lock_message_type=lock_message_type,
            status_endpoint=status_endpoint,
            status_formatter=status_formatter,
            config_snapshot_provider=getattr(parent, "_collect_current_config_snapshot", None),
            show_cancel_button=True,
            auto_clear_on_success=False,
            manage_polling=False,
        )
        self.viewLayout.addWidget(self.form)

        self.form.sendSucceeded.connect(self._on_send_succeeded)
        self.form.cancelRequested.connect(self.reject)

    def _set_center_widget_size(self, parent) -> None:
        parent_width = max(0, int(parent.width())) if parent is not None else 0
        parent_height = max(0, int(parent.height())) if parent is not None else 0
        width = min(_DIALOG_MAX_WIDTH, max(_DIALOG_MIN_WIDTH, parent_width - _DIALOG_PARENT_MARGIN))
        height = min(
            _DIALOG_MAX_HEIGHT,
            max(_DIALOG_MIN_HEIGHT, parent_height - _DIALOG_PARENT_MARGIN),
        )
        self.widget.setFixedSize(width, height)

    def showEvent(self, e: QShowEvent) -> None:
        super().showEvent(e)
        self._schedule_status_polling()

    def _schedule_status_polling(self) -> None:
        self._status_poll_timer.stop()
        self._status_poll_timer.start()

    def _start_status_polling_if_ready(self) -> None:
        if not self.isVisible():
            return
        self.form.start_status_polling()

    def _stop_status_polling(self) -> None:
        self._status_poll_timer.stop()
        self.form.stop_status_polling()

    def _on_send_succeeded(self):
        """发送成功后延迟关闭，让InfoBar有时间显示"""
        QTimer.singleShot(2800, self.accept)

    def closeEvent(self, e: QCloseEvent) -> None:
        if self.form.has_pending_async_work():
            self.form.show_pending_async_warning()
            e.ignore()
            return
        self._stop_status_polling()
        super().closeEvent(e)

    def reject(self) -> None:
        if self.form.has_pending_async_work():
            self.form.show_pending_async_warning()
            return
        self._stop_status_polling()
        super().reject()

    def accept(self) -> None:
        if self.form.has_pending_async_work():
            self.form.show_pending_async_warning()
            return
        self._stop_status_polling()
        super().accept()

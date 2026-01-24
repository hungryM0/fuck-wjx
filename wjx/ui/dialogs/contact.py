"""联系开发者对话框"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout

from wjx.ui.widgets.contact_form import ContactForm


class ContactDialog(QDialog):
    """联系开发者（Qt 版本）。包装 ContactForm，保留原有对话框入口。"""

    def __init__(self, parent=None, default_type: str = "报错反馈", status_fetcher=None, status_formatter=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle("联系开发者")
        self.resize(720, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        self.form = ContactForm(
            self,
            default_type=default_type,
            status_fetcher=status_fetcher,
            status_formatter=status_formatter,
            show_cancel_button=True,
            auto_clear_on_success=False,
            manage_polling=False,
        )
        layout.addWidget(self.form)

        # 让对话框控制轮询生命周期，避免关闭时线程残留
        self.form.start_status_polling()
        self.form.sendSucceeded.connect(self.accept)
        self.form.cancelRequested.connect(self.reject)

    def closeEvent(self, event):
        self.form.stop_status_polling()
        super().closeEvent(event)

    def reject(self):
        self.form.stop_status_polling()
        super().reject()

    def accept(self):
        self.form.stop_status_polling()
        super().accept()

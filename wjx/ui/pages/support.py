"""客服与支持页面"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import ScrollArea, SubtitleLabel, BodyLabel, CardWidget

from wjx.ui.widgets.contact_form import ContactForm
from wjx.network.random_ip import get_status, _format_status_payload


class SupportPage(ScrollArea):
    """客服与支持页面，直接内嵌联系开发者表单。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWidget(self)
        self.view.setStyleSheet("background: transparent;")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self._build_ui()

    def showEvent(self, event):
        super().showEvent(event)
        try:
            self.contact_form.start_status_polling()
        except Exception:
            pass

    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # 联系开发者卡片
        contact_card = CardWidget(self.view)
        contact_layout = QVBoxLayout(contact_card)
        contact_layout.setContentsMargins(16, 16, 16, 16)
        contact_layout.setSpacing(12)
        contact_layout.addWidget(SubtitleLabel("联系开发者", self))
        
        self.contact_form = ContactForm(
            self,
            status_fetcher=get_status,
            status_formatter=_format_status_payload,
            show_cancel_button=False,
            auto_clear_on_success=True,
        )
        contact_layout.addWidget(self.contact_form)
        layout.addWidget(contact_card)

        layout.addStretch(1)

        # 不再需要外部按钮/弹窗，表单直接内嵌


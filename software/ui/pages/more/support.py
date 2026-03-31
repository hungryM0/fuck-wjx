"""联系开发者页面"""
from PySide6.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import ScrollArea, SubtitleLabel, CardWidget


from software.ui.widgets.contact_form import ContactForm
from software.app.config import STATUS_ENDPOINT
from software.ui.helpers.proxy_access import format_status_payload


class SupportPage(ScrollArea):
    """客服与支持页面，直接内嵌联系开发者表单。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self._build_ui()

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
            status_endpoint=STATUS_ENDPOINT,
            status_formatter=format_status_payload,
            show_cancel_button=False,
            auto_clear_on_success=True,
        )
        contact_layout.addWidget(self.contact_form)
        layout.addWidget(contact_card)

        layout.addStretch(1)

        # 不再需要外部按钮/弹窗，表单直接内嵌




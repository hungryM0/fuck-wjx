"""捐助页面"""
import sys
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import (
    ScrollArea,
    TitleLabel,
    BodyLabel,
    CaptionLabel,
    ImageLabel,
    CardWidget,
)


def get_resource_path(relative_path: str) -> str:
    """获取资源文件的绝对路径，兼容打包后的环境"""
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        return os.path.join(meipass, relative_path)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))), relative_path)


class DonatePage(ScrollArea):
    """捐助页面，展示付款二维码和感谢文字"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWidget(self)
        self.view.setObjectName('view')
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(36, 20, 36, 20)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        # 标题
        title = TitleLabel("支持作者", self)
        layout.addWidget(title, 0, Qt.AlignmentFlag.AlignHCenter)

        # 说明文字
        desc = BodyLabel("如果这个项目对你有帮助，欢迎请作者喝杯咖啡~", self)
        desc.setStyleSheet("color: #606060;")
        layout.addWidget(desc, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(10)

        # 二维码卡片
        card = CardWidget(self)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 20)
        card_layout.setSpacing(12)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # 二维码图片
        qr_path = get_resource_path("assets/payment.png")
        qr_label = ImageLabel(qr_path, self)
        qr_label.scaledToWidth(280)
        card_layout.addWidget(qr_label, 0, Qt.AlignmentFlag.AlignHCenter)

        # 提示文字
        tip = CaptionLabel("微信扫一扫，随意打赏", self)
        tip.setStyleSheet("color: #888;")
        card_layout.addWidget(tip, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(16)

        # 感谢语
        thanks = BodyLabel("感谢每一位支持者，你们的鼓励是我持续更新的动力！", self)
        thanks.setStyleSheet("color: #606060;")
        layout.addWidget(thanks, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch(1)

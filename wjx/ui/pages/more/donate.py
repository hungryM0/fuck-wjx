"""捐助页面"""
import sys
import os
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QBoxLayout
from qfluentwidgets import (
    ScrollArea,
    TitleLabel,
    BodyLabel,
    CaptionLabel,
    CardWidget,
    StrongBodyLabel,
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
        self._compact = False
        self._qr_items = []
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

        # 二维码卡片（微信/支付宝）
        self.qr_row = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.qr_row.setSpacing(16)
        self.qr_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        wechat_path = get_resource_path("assets/WeDonate.png")
        alipay_path = get_resource_path("assets/AliDonate.jpg")

        self.qr_row.addWidget(
            self._build_qr_card("微信赞赏", wechat_path, "微信扫一扫", brand_color="#07C160")
        )
        self.qr_row.addWidget(
            self._build_qr_card("支付宝", alipay_path, "支付宝扫一扫", brand_color="#1677FF")
        )

        layout.addLayout(self.qr_row)

        layout.addSpacing(16)

        # 感谢语
        thanks = BodyLabel("感谢每一位支持者，你们的鼓励是我持续更新的动力！", self)
        thanks.setStyleSheet("color: #606060;")
        layout.addWidget(thanks, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch(1)

        self._update_layout()

    def _build_qr_card(
        self,
        title: str,
        qr_path: str,
        tip_text: str,
        brand_color: Optional[str] = None,
    ) -> CardWidget:
        card = CardWidget(self)

        # 使用水平布局，左侧放装饰条，右侧放内容
        main_layout = QHBoxLayout(card)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 添加品牌色装饰条（独立的 QWidget）
        if brand_color:
            accent_bar = QWidget(card)
            accent_bar.setFixedWidth(4)
            accent_bar.setStyleSheet(f"background-color: {brand_color};")
            main_layout.addWidget(accent_bar)

        # 内容区域
        content_widget = QWidget(card)
        card_layout = QVBoxLayout(content_widget)
        card_layout.setContentsMargins(24, 20, 24, 20)
        card_layout.setSpacing(10)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        main_layout.addWidget(content_widget)

        title_label = StrongBodyLabel(title, content_widget)
        if brand_color:
            title_label.setStyleSheet(f"color: {brand_color}; font-weight: bold;")
        card_layout.addWidget(title_label, 0, Qt.AlignmentFlag.AlignHCenter)

        qr_label = QLabel(content_widget)
        qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_label.setStyleSheet(
            "border: 1px solid rgba(128,128,128,0.15); border-radius: 8px; padding: 4px;"
        )
        pixmap = QPixmap(qr_path) if os.path.exists(qr_path) else None
        if pixmap and not pixmap.isNull():
            self._qr_items.append((qr_label, pixmap))
        else:
            qr_label.setText(f"二维码未找到\n{os.path.basename(qr_path)}")
        card_layout.addWidget(qr_label, 0, Qt.AlignmentFlag.AlignHCenter)

        tip = CaptionLabel(tip_text, content_widget)
        tip.setStyleSheet("color: #888;")
        card_layout.addWidget(tip, 0, Qt.AlignmentFlag.AlignHCenter)

        return card

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_layout()

    def _update_layout(self):
        compact = self.viewport().width() < 720
        if compact != self._compact:
            self._compact = compact
            self.qr_row.setDirection(
                QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight
            )
        self._apply_qr_pixmaps()

    def _apply_qr_pixmaps(self):
        base_width = 200 if self._compact else 240
        for label, pixmap in self._qr_items:
            if pixmap.isNull():
                continue
            ratio = pixmap.height() / pixmap.width() if pixmap.width() else 1
            height = max(160, int(base_width * ratio))
            label.setFixedSize(base_width, height)
            label.setPixmap(
                pixmap.scaled(
                    label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

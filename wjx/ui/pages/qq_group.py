"""QQ群页面与卡片组件"""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QDialog
from PySide6.QtGui import QPixmap
from qfluentwidgets import ScrollArea, SubtitleLabel, BodyLabel, CardWidget, PushButton

from wjx.utils.load_save import get_assets_directory


class QQGroupCard(CardWidget):
    """展示QQ群二维码的卡片，支持点击放大"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(SubtitleLabel("加入QQ群", self))

        desc = BodyLabel(
            "扫描下方二维码加入QQ交流群，和其他用户一起交流使用心得！\n"
            "群里可以获取最新版本、反馈问题、提出建议~",
            self,
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.qq_group_label = QLabel(self)
        self.qq_group_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qq_group_label.setMinimumSize(360, 480)
        self.qq_group_label.setStyleSheet(
            "border: 1px solid #e0e0e0; border-radius: 8px; padding: 8px;"
        )
        self.qq_group_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.qq_group_label.mousePressEvent = (
            lambda ev: self._on_qq_group_clicked(ev)
        )  # type: ignore[method-assign]
        self._load_qq_group_image()

        click_hint = BodyLabel("点击图片查看原图", self)
        click_hint.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(self.qq_group_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(click_hint, alignment=Qt.AlignmentFlag.AlignHCenter)

    def _on_qq_group_clicked(self, event):
        """点击二维码查看原图"""
        try:
            qq_group_path = os.path.join(get_assets_directory(), "QQ_group.jpg")
            if os.path.exists(qq_group_path):
                self._show_full_image(qq_group_path)
        except Exception:
            pass

    def _show_full_image(self, image_path: str):
        """显示原图弹窗"""
        dialog = QDialog(self.window() or self)
        dialog.setWindowTitle("QQ群二维码")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)

        img_label = QLabel(dialog)
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(image_path)
        if pixmap.width() > 600 or pixmap.height() > 600:
            pixmap = pixmap.scaled(
                600,
                600,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        img_label.setPixmap(pixmap)
        layout.addWidget(img_label)

        close_btn = PushButton("关闭", dialog)
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        dialog.adjustSize()
        dialog.exec()

    def _load_qq_group_image(self):
        """加载QQ群二维码图片"""
        try:
            qq_group_path = os.path.join(get_assets_directory(), "QQ_group.jpg")
            if os.path.exists(qq_group_path):
                pixmap = QPixmap(qq_group_path)
                scaled = pixmap.scaled(
                    360,
                    480,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.qq_group_label.setPixmap(scaled)
            else:
                self.qq_group_label.setText("QQ群二维码图片未找到\n请检查 assets/QQ_group.jpg")
        except Exception as e:
            self.qq_group_label.setText(f"加载图片失败：{e}")


class QQGroupPage(ScrollArea):
    """QQ群页面，单独展示交流群二维码"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWidget(self)
        self.view.setStyleSheet("background: transparent;")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(36, 20, 36, 20)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        layout.addWidget(QQGroupCard(self), 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)

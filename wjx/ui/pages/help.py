"""帮助页面"""
import os
import threading
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QDialog,
)
from PySide6.QtGui import QPixmap
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    BodyLabel,
    CardWidget,
    PushButton,
    PrimaryPushButton,
    IndeterminateProgressRing,
)

from wjx.network.random_ip import get_status, _format_status_payload
from wjx.utils.load_save import get_assets_directory


class HelpPage(ScrollArea):
    """帮助页面，包含联系开发者、QQ群等。"""

    _statusLoaded = Signal(str, str)  # text, color

    def __init__(self, on_contact, parent=None):
        super().__init__(parent)
        self.on_contact = on_contact
        self._status_loaded_once = False
        self.view = QWidget(self)
        self.view.setStyleSheet("background: transparent;")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self._statusLoaded.connect(self._on_status_loaded)
        self._build_ui()
        
        # 定时刷新状态（每5秒），但不立即启动
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(5000)
        self._status_timer.timeout.connect(self._load_status_async)

    def showEvent(self, event):
        """页面显示时触发首次状态查询"""
        super().showEvent(event)
        if not self._status_loaded_once:
            self._status_loaded_once = True
            self._load_status_async()
            self._status_timer.start()

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
        
        desc = BodyLabel(
            "遇到问题、有建议、或者想聊天？直接点击下方按钮联系作者！\n"
            "消息会实时推送到作者手机上，回复很快哦~",
            self
        )
        desc.setWordWrap(True)
        contact_layout.addWidget(desc)

        # 在线状态
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_spinner = IndeterminateProgressRing(self)
        self.status_spinner.setFixedSize(16, 16)
        self.status_spinner.setStrokeWidth(2)
        self.status_label = BodyLabel("作者当前在线状态：查询中...", self)
        self.status_label.setStyleSheet("color:#BA8303;")
        status_row.addWidget(self.status_spinner)
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        contact_layout.addLayout(status_row)

        self.contact_btn = PrimaryPushButton("发送消息给作者", self)
        contact_layout.addWidget(self.contact_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(contact_card)

        # QQ群交流卡片
        community_card = CardWidget(self.view)
        community_layout = QVBoxLayout(community_card)
        community_layout.setContentsMargins(16, 16, 16, 16)
        community_layout.setSpacing(12)
        community_layout.addWidget(SubtitleLabel("加入QQ群", self))
        
        community_desc = BodyLabel(
            "扫描下方二维码加入QQ交流群，和其他用户一起交流使用心得！\n"
            "群里可以获取最新版本、反馈问题、提出建议~",
            self
        )
        community_desc.setWordWrap(True)
        community_layout.addWidget(community_desc)

        # QQ群二维码图片
        self.qq_group_label = QLabel(self)
        self.qq_group_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qq_group_label.setMinimumSize(280, 280)
        self.qq_group_label.setStyleSheet("border: 1px solid #e0e0e0; border-radius: 8px; padding: 8px;")
        self.qq_group_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.qq_group_label.mousePressEvent = lambda ev: self._on_qq_group_clicked(ev)  # type: ignore[method-assign]
        self._load_qq_group_image()
        
        click_hint = BodyLabel("点击图片查看原图", self)
        click_hint.setStyleSheet("color: #888; font-size: 12px;")
        community_layout.addWidget(self.qq_group_label, alignment=Qt.AlignmentFlag.AlignLeft)
        community_layout.addWidget(click_hint, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(community_card)

        layout.addStretch(1)

        # 绑定事件
        self.contact_btn.clicked.connect(lambda: self.on_contact())

    def _on_status_loaded(self, text: str, color: str):
        """信号槽：在主线程更新状态标签"""
        self.status_spinner.hide()
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color:{color};")

    def _load_status_async(self):
        import time
        def _worker():
            text = "作者当前在线状态：未知"
            color = "#666666"
            start = time.time()
            try:
                payload = get_status()
                text, color = _format_status_payload(payload)
            except Exception:
                text = "作者当前在线状态：获取失败"
                color = "#cc0000"
            # 确保加载动画至少显示 800ms
            elapsed = time.time() - start
            if elapsed < 0.8:
                time.sleep(0.8 - elapsed)
            self._statusLoaded.emit(text, color)

        threading.Thread(target=_worker, daemon=True).start()

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
            pixmap = pixmap.scaled(600, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
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
                scaled = pixmap.scaled(280, 280, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.qq_group_label.setPixmap(scaled)
            else:
                self.qq_group_label.setText("QQ群二维码图片未找到\n请检查 assets/QQ_group.jpg")
        except Exception as e:
            self.qq_group_label.setText(f"加载图片失败：{e}")

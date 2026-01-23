"""帮助页面"""
import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    BodyLabel,
    CardWidget,
    PrimaryPushButton,
    IndeterminateProgressRing,
)

from wjx.network.random_ip import get_status, _format_status_payload


class HelpPage(ScrollArea):
    """帮助页面，包含联系开发者信息。"""

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


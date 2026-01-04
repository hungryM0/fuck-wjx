"""
UI 基类模块

抽取 CardUnlockDialog 和 ContactDialog 中的重复代码，
提供统一的状态加载、布局构建等功能。
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Optional, Tuple

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout

from qfluentwidgets import (
    BodyLabel,
    IndeterminateProgressRing,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
)


class BaseDialog(QDialog):
    """
    基础对话框类，提供通用的布局、状态加载和按钮功能。
    """
    
    _statusLoaded = Signal(str, str)
    
    def __init__(
        self,
        parent=None,
        title: str = "",
        width: int = 600,
        height: int = 400,
        status_fetcher: Optional[Callable] = None,
        status_formatter: Optional[Callable] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(width, height)
        
        # 状态加载相关
        self._status_fetcher = status_fetcher
        self._status_formatter = status_formatter
        self._status_timer: Optional[QTimer] = None
        self.status_spinner: Optional[IndeterminateProgressRing] = None
        self.status_label: Optional[BodyLabel] = None
        
        # 主布局
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(18, 18, 18, 18)
        self._main_layout.setSpacing(12)
        
        # 连接信号
        self._statusLoaded.connect(self._on_status_loaded)
        
        # 初始化状态加载
        if status_fetcher:
            self._init_status_timer()
    
    def _init_status_timer(self, refresh_interval: int = 3000) -> None:
        """初始化状态定时器"""
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(refresh_interval)
        self._status_timer.timeout.connect(self._load_status_async)
        self._load_status_async()
        self._status_timer.start()
    
    def _on_status_loaded(self, text: str, color: str) -> None:
        """状态加载完成回调"""
        if self.status_spinner:
            self.status_spinner.hide()
        if self.status_label:
            self.status_label.setText(text)
            self.status_label.setStyleSheet(f"color:{color};")
    
    def _load_status_async(self) -> None:
        """异步加载状态"""
        fetcher = self._status_fetcher
        if not callable(fetcher):
            if self.status_label:
                self.status_label.setText("作者当前在线状态：未知")
            if self.status_spinner:
                self.status_spinner.hide()
            return
        
        def _worker():
            text = "作者当前在线状态：未知"
            color = "#666666"
            try:
                result = fetcher()
                if callable(self._status_formatter):
                    text, color = self._status_formatter(result)
                else:
                    online = bool(result.get("online")) if isinstance(result, dict) else True
                    text = f"作者当前在线状态：{'在线' if online else '离线'}"
                    color = "#228B22" if online else "#cc0000"
            except Exception:
                text = "作者当前在线状态：获取失败"
                color = "#cc0000"
            self._statusLoaded.emit(text, color)
        
        threading.Thread(target=_worker, daemon=True).start()
    
    def _create_status_row(self) -> QHBoxLayout:
        """创建状态显示行"""
        row = QHBoxLayout()
        row.setSpacing(8)
        
        self.status_spinner = IndeterminateProgressRing(self)
        self.status_spinner.setFixedSize(16, 16)
        self.status_spinner.setStrokeWidth(2)
        
        self.status_label = BodyLabel("作者当前在线状态：查询中...", self)
        self.status_label.setStyleSheet("color:#BA8303;")
        
        row.addWidget(self.status_spinner)
        row.addWidget(self.status_label)
        row.addStretch(1)
        
        return row
    
    def add_title(self, text: str) -> SubtitleLabel:
        """添加标题"""
        label = SubtitleLabel(text, self)
        self._main_layout.addWidget(label)
        return label
    
    def add_description(self, text: str) -> BodyLabel:
        """添加描述文本"""
        label = BodyLabel(text, self)
        label.setWordWrap(True)
        self._main_layout.addWidget(label)
        return label
    
    def add_status_row(self) -> QHBoxLayout:
        """添加状态显示行到布局"""
        row = self._create_status_row()
        self._main_layout.addLayout(row)
        return row
    
    def add_button_row(
        self,
        ok_text: str = "确定",
        cancel_text: str = "取消",
        ok_primary: bool = True,
    ) -> Tuple[PushButton, PushButton]:
        """添加按钮行"""
        row = QHBoxLayout()
        row.addStretch(1)
        
        cancel_btn = PushButton(cancel_text, self)
        if ok_primary:
            ok_btn = PrimaryPushButton(ok_text, self)
        else:
            ok_btn = PushButton(ok_text, self)
        
        row.addWidget(cancel_btn)
        row.addWidget(ok_btn)
        self._main_layout.addLayout(row)
        
        cancel_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self.accept)
        
        return ok_btn, cancel_btn
    
    def add_stretch(self) -> None:
        """添加弹性空间"""
        self._main_layout.addStretch(1)
    
    def closeEvent(self, arg__1) -> None:
        """关闭时停止定时器"""
        if self._status_timer:
            self._status_timer.stop()
        super().closeEvent(arg__1)

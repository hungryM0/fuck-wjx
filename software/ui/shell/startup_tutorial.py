"""启动后的教程提示。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    FlyoutViewBase,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
)


TUTORIAL_DOC_URL = "https://surveydoc.hungrym0.top/"
STARTUP_TUTORIAL_HINT_SEEN_SETTING_KEY = "startup_tutorial_hint_seen"


class StartupTutorialFlyoutView(FlyoutViewBase):
    """首次启动教程入口提示。"""

    openRequested = Signal()
    dismissed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(320)
        self.setMaximumWidth(360)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(20, 18, 20, 18)
        self._layout.setSpacing(10)

        title_label = StrongBodyLabel("第一次用？先看教程", self)
        title_label.setWordWrap(True)

        content_label = BodyLabel("教程里有相关设置的详细说明", self)
        content_label.setWordWrap(True)

        hint_label = CaptionLabel("将使用外部浏览器打开教程页面", self)
        hint_label.setWordWrap(True)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 4, 0, 0)
        button_row.setSpacing(8)

        self.dismissButton = PushButton("不再显示", self)
        self.openButton = PrimaryPushButton("打开教程", self, FluentIcon.LIBRARY)
        self.dismissButton.clicked.connect(self.dismissed)
        self.openButton.clicked.connect(self.openRequested)

        button_row.addStretch(1)
        button_row.addWidget(self.dismissButton)
        button_row.addWidget(self.openButton)

        self._layout.addWidget(title_label)
        self._layout.addWidget(content_label)
        self._layout.addWidget(hint_label)
        self._layout.addLayout(button_row)

    def addWidget(self, widget, stretch=0, align=Qt.AlignmentFlag.AlignLeft):
        self._layout.addWidget(widget, stretch, align)

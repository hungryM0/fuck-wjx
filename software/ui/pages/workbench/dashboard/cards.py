"""工作台概览页专用卡片组件。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    FluentIcon,
    IconWidget,
    PushButton,
    SubtitleLabel,
)


class RuntimeSettingsHintCard(CardWidget):
    """首页上的运行参数跳转提示卡。"""

    openRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("runtimeSettingsHintCard")
        self.setMinimumHeight(86)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        self.icon_panel = QWidget(self)
        self.icon_panel.setFixedSize(44, 44)
        self.icon_panel.setStyleSheet(
            "QWidget { background-color: rgba(0, 120, 212, 0.12); border-radius: 14px; }"
        )
        icon_panel_layout = QVBoxLayout(self.icon_panel)
        icon_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.icon_widget = IconWidget(FluentIcon.DEVELOPER_TOOLS, self.icon_panel)
        self.icon_widget.setFixedSize(22, 22)
        icon_panel_layout.addWidget(self.icon_widget, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_panel, 0, Qt.AlignmentFlag.AlignVCenter)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        self.title_label = SubtitleLabel("运行参数", self)
        text_layout.addWidget(self.title_label)
        self.description_label = BodyLabel("更多设置请前往“运行参数”页仔细调整", self)
        self.description_label.setStyleSheet("color: #6b6b6b;")
        self.description_label.setWordWrap(True)
        text_layout.addWidget(self.description_label)
        layout.addLayout(text_layout, 1)

        self.open_button = PushButton("打开", self)
        self.open_button.setMinimumSize(112, 40)
        self.open_button.clicked.connect(self.openRequested.emit)
        layout.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignVCenter)

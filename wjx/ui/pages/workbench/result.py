"""结果页面（预留）"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import BodyLabel, CardWidget, SubtitleLabel


class ResultPage(QWidget):
    """侧边栏结果页：当前仅展示开发中占位内容。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(SubtitleLabel("执行结果查询", self))

        card = CardWidget(self)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(8)

        developing_label = BodyLabel("正在开发中...", card)
        developing_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        developing_label.setStyleSheet("font-size: 16px;")
        card_layout.addWidget(developing_label)

        tip_label = BodyLabel("后续会在这里展示运行结果与信度统计信息", card)
        tip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tip_label.setStyleSheet("font-size: 12px;")
        card_layout.addWidget(tip_label)

        layout.addWidget(card)
        layout.addStretch(1)


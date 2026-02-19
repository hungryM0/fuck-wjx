"""结果页内部复用组件。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, ProgressBar, StrongBodyLabel, TitleLabel, isDarkTheme


class _Divider(QFrame):
    """1px 水平分割线"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)
        self.setStyleSheet("background: rgba(128,128,128,0.15); border: none;")


class _VerticalDivider(QFrame):
    """1px 垂直分割线"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.VLine)
        self.setFixedWidth(1)
        self.setStyleSheet("background: rgba(128,128,128,0.15); border: none;")


class _StatNumberWidget(QWidget):
    """概览区的单个统计数字块"""

    def __init__(self, title: str, value: str = "0", color: Optional[str] = None, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._title_label = CaptionLabel(title, self)
        self._title_label.setStyleSheet("color: rgba(128,128,128,0.9);")

        self._value_label = TitleLabel(value, self)
        if color:
            self._value_label.setStyleSheet(f"font-size: 28px; font-weight: 700; color: {color};")
        else:
            self._value_label.setStyleSheet("font-size: 28px; font-weight: 700;")

        layout.addWidget(self._title_label)
        layout.addWidget(self._value_label)

    def setValue(self, text: str) -> None:
        self._value_label.setText(text)

    def setColor(self, color: str) -> None:
        self._value_label.setStyleSheet(f"font-size: 28px; font-weight: 700; color: {color};")


class _BarRow(QWidget):
    """选项统计的一行：名称 | 进度条 | 次数 / 占比"""

    def __init__(self, name: str, count: int, percentage: float, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)

        name_label = BodyLabel(name, self)
        name_label.setFixedWidth(120)
        name_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(name_label)

        bar = ProgressBar(self)
        bar.setValue(min(100, int(percentage)))
        bar.setFixedHeight(14)
        bar.setMinimumWidth(80)
        h.addWidget(bar, 1)

        stat_text = f"{count} 次  ({percentage:.1f}%)"
        stat_label = CaptionLabel(stat_text, self)
        stat_label.setFixedWidth(120)
        stat_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(stat_label)


class _TextAnswerRow(QWidget):
    """填空题答案行：答案文本 + 次数"""

    def __init__(self, text: str, count: int, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)

        h = QHBoxLayout(self)
        h.setContentsMargins(4, 0, 4, 0)
        h.setSpacing(12)

        display = text[:80] + "…" if len(text) > 80 else text
        text_label = BodyLabel(display, self)
        h.addWidget(text_label, 1)

        count_label = CaptionLabel(f"× {count}", self)
        count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        count_label.setFixedWidth(60)
        h.addWidget(count_label)


class _MatrixCell(QWidget):
    """矩阵题热力格子"""

    def __init__(self, value: int, max_val: int, parent=None):
        super().__init__(parent)
        self._value = value
        self._max_val = max(max_val, 1)
        self.setFixedSize(48, 32)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ratio = self._value / self._max_val if self._max_val > 0 else 0

        if isDarkTheme():
            bg = QColor(0, 120, 212, int(30 + ratio * 180))
            text_color = QColor(255, 255, 255)
        else:
            bg = QColor(0, 120, 212, int(20 + ratio * 180))
            text_color = QColor(0, 0, 0) if ratio < 0.5 else QColor(255, 255, 255)

        painter.setBrush(QBrush(bg))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 4, 4)

        painter.setPen(QPen(text_color))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, str(self._value))
        painter.end()


class _MetricWidget(QWidget):
    """信效度分析卡片中的单个指标展示。"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._title_label = CaptionLabel(title, self)
        self._title_label.setStyleSheet("color: rgba(128,128,128,0.9);")

        self._value_label = StrongBodyLabel("--", self)
        self._value_label.setStyleSheet("font-size: 20px;")

        self._desc_label = CaptionLabel("", self)
        self._desc_label.setStyleSheet("color: rgba(128,128,128,0.7);")
        self._desc_label.setWordWrap(True)

        layout.addWidget(self._title_label)
        layout.addWidget(self._value_label)
        layout.addWidget(self._desc_label)

    def set_value(self, text: str, color: str, description: str) -> None:
        self._value_label.setText(text)
        self._value_label.setStyleSheet(f"font-size: 20px; color: {color};")
        self._desc_label.setText(description)

    def set_unavailable(self, reason: str = "") -> None:
        self._value_label.setText("--")
        self._value_label.setStyleSheet("font-size: 20px; color: rgba(128,128,128,0.5);")
        self._desc_label.setText(reason)

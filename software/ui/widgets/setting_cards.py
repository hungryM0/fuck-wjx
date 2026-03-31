"""通用 SettingCard 组件 - 可跨页面复用的设置卡片"""

from PySide6.QtCore import Qt
from qfluentwidgets import (
    IndicatorPosition,
    SettingCard,
    SwitchButton,
)

from software.ui.widgets.no_wheel import NoWheelSpinBox


class SpinBoxSettingCard(SettingCard):
    """带 SpinBox 的设置卡"""

    def __init__(self, icon, title, content, min_val=1, max_val=99999, default=10, parent=None):
        super().__init__(icon, title, content, parent)
        self.spinBox = NoWheelSpinBox(self)
        self.spinBox.setRange(min_val, max_val)
        self.spinBox.setValue(default)
        self.spinBox.setMinimumWidth(90)
        self.spinBox.setFixedHeight(36)
        self.hBoxLayout.addWidget(self.spinBox, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def value(self):
        return self.spinBox.value()

    def setValue(self, value):
        self.spinBox.setValue(value)

    def setSpinBoxWidth(self, width: int) -> None:
        if width and width > 0:
            self.spinBox.setFixedWidth(int(width))

    def suggestSpinBoxWidthForDigits(self, digits: int) -> int:
        digits = max(1, int(digits))
        metrics = self.spinBox.fontMetrics()
        sample = "8" * digits
        target_width = metrics.horizontalAdvance(sample)
        try:
            current_text = self.spinBox.text()
        except Exception:
            current_text = str(self.spinBox.value())
        current_width = metrics.horizontalAdvance(current_text or "0")
        base_width = self.spinBox.sizeHint().width()
        extra = max(0, target_width - current_width)
        return int(base_width + extra + 8)


class SwitchSettingCard(SettingCard):
    """带开关的设置卡"""

    def __init__(self, icon, title, content, parent=None):
        super().__init__(icon, title, content, parent)
        self.switchButton = SwitchButton(self, IndicatorPosition.RIGHT)
        self.switchButton.setOnText("开")
        self.switchButton.setOffText("关")
        self.hBoxLayout.addWidget(self.switchButton, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def isChecked(self):
        return self.switchButton.isChecked()

    def setChecked(self, checked):
        self.switchButton.setChecked(checked)

    def blockSignals(self, block):
        return self.switchButton.blockSignals(block)


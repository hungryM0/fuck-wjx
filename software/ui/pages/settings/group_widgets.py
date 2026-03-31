"""设置页专用的轻量右侧控件。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import ComboBox, PushButton, SwitchButton


class SwitchGroupWidget(QWidget):
    """设置页开关控件。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.switchButton = SwitchButton(self)
        self.switchButton.setOnText("开")
        self.switchButton.setOffText("关")
        layout.addWidget(self.switchButton, 0, Qt.AlignmentFlag.AlignRight)

    def isChecked(self):
        return self.switchButton.isChecked()

    def setChecked(self, checked):
        self.switchButton.setChecked(checked)

    def blockSignals(self, block):
        return self.switchButton.blockSignals(block)


class ComboBoxGroupWidget(QWidget):
    """设置页下拉选择控件。"""

    def __init__(self, min_width: int = 180, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.comboBox = ComboBox(self)
        self.comboBox.setMinimumWidth(min_width)
        layout.addWidget(self.comboBox, 0, Qt.AlignmentFlag.AlignRight)


class ActionButtonGroupWidget(QWidget):
    """设置页操作按钮控件。"""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.button = PushButton(text, self)
        self.button.setFixedHeight(36)
        layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignRight)

    @property
    def clicked(self):
        return self.button.clicked

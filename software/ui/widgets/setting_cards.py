"""通用 SettingCard 组件 - 可跨页面复用的设置卡片"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    ExpandGroupSettingCard,
    IndicatorPosition,
    SettingCard,
    SwitchButton,
)

from software.ui.widgets.no_wheel import NoWheelSpinBox
from software.ui.widgets.value_slider import ValueSlider


def set_widget_enabled_with_opacity(
    widget: QWidget,
    enabled: bool,
    *,
    disabled_opacity: float = 0.4,
) -> None:
    """统一处理控件禁用态透明度。"""
    widget.setEnabled(bool(enabled))
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    effect.setOpacity(1.0 if enabled else float(disabled_opacity))


class SpinBoxSettingCard(SettingCard):
    """带 SpinBox 的设置卡"""

    def __init__(
        self,
        icon,
        title,
        content,
        min_val=1,
        max_val=99999,
        default=10,
        parent=None,
    ):
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


class SliderSettingCard(SettingCard):
    """带数值滑动条的设置卡。"""

    def __init__(
        self,
        icon,
        title,
        content,
        min_val=1,
        max_val=99999,
        default=10,
        suffix="",
        parent=None,
    ):
        super().__init__(icon, title, content, parent)
        self.slider = ValueSlider(min_val, max_val, default, suffix=suffix, parent=self)
        self.slider.setMinimumWidth(220)
        self.hBoxLayout.addWidget(self.slider, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def value(self):
        return self.slider.value()

    def setValue(self, value):
        self.slider.setValue(value)

    def setRange(self, min_val: int, max_val: int) -> None:
        self.slider.setRange(min_val, max_val)


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

    def blockSignals(self, b):
        return self.switchButton.blockSignals(b)


class ComboSettingCard(SettingCard):
    """带下拉框的设置卡。"""

    def __init__(self, icon, title, content, min_width: int = 180, parent=None):
        super().__init__(icon, title, content, parent)
        self.comboBox = ComboBox(self)
        self.comboBox.setMinimumWidth(max(120, int(min_width or 180)))
        self.hBoxLayout.addWidget(self.comboBox, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)


class ExpandComboSwitchSettingCard(ExpandGroupSettingCard):
    """可展开的开关设置卡，展开后显示一个下拉选择。"""

    def __init__(
        self,
        icon,
        title,
        content,
        combo_label: str,
        *,
        combo_min_width: int = 140,
        combo_suffix: str = "",
        parent=None,
    ):
        super().__init__(icon, title, content, parent)
        self.switchButton = SwitchButton(self, IndicatorPosition.RIGHT)
        self.switchButton.setOnText("开")
        self.switchButton.setOffText("关")
        self.addWidget(self.switchButton)

        self._groupContainer = QWidget(self)
        layout = QVBoxLayout(self._groupContainer)
        layout.setContentsMargins(48, 12, 48, 12)
        layout.setSpacing(12)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(BodyLabel(combo_label, self._groupContainer))
        row.addStretch(1)

        self.comboBox = ComboBox(self._groupContainer)
        self.comboBox.setMinimumWidth(max(120, int(combo_min_width or 140)))
        row.addWidget(self.comboBox)

        self.suffixLabel = BodyLabel(str(combo_suffix or ""), self._groupContainer)
        self.suffixLabel.setVisible(bool(combo_suffix))
        row.addWidget(self.suffixLabel)
        layout.addLayout(row)

        self.addGroupWidget(self._groupContainer)
        self.setExpand(True)
        self.switchButton.checkedChanged.connect(self._sync_group_enabled)
        self._sync_group_enabled(False)

    def isChecked(self) -> bool:
        return self.switchButton.isChecked()

    def setChecked(self, checked: bool) -> None:
        self.switchButton.setChecked(bool(checked))

    def setContentEnabled(self, enabled: bool) -> None:
        self._sync_group_enabled(bool(enabled))

    def _sync_group_enabled(self, enabled: bool) -> None:
        set_widget_enabled_with_opacity(self._groupContainer, bool(enabled))

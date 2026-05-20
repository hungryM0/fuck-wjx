"""带当前数值显示的滑动条。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QWidget
from qfluentwidgets import BodyLabel, Slider


class ValueSlider(QWidget):
    """滑动条 + 当前值标签，提供类似 SpinBox 的常用接口。"""

    valueChanged = Signal(int)

    def __init__(
        self,
        min_val: int,
        max_val: int,
        default: int = 1,
        suffix: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._suffix = str(suffix or "")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.slider = Slider(Qt.Orientation.Horizontal, self)
        self.valueLabel = BodyLabel(self)
        self.valueLabel.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self.slider, 1)
        layout.addWidget(self.valueLabel, 0)

        self.slider.valueChanged.connect(self._on_value_changed)
        self.setRange(min_val, max_val)
        self.setValue(default)

    def _label_text(self, value: int) -> str:
        return f"{int(value)}{self._suffix}"

    def _refresh_label_width(self) -> None:
        minimum = self.slider.minimum()
        maximum = self.slider.maximum()
        sample = max((self._label_text(minimum), self._label_text(maximum)), key=len)
        self.valueLabel.setFixedWidth(self.valueLabel.fontMetrics().horizontalAdvance(sample) + 8)

    def _on_value_changed(self, value: int) -> None:
        self.valueLabel.setText(self._label_text(value))
        self.valueChanged.emit(int(value))

    def setRange(self, min_val: int, max_val: int) -> None:
        min_value = int(min_val)
        max_value = max(min_value, int(max_val))
        self.slider.setRange(min_value, max_value)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(max(1, (max_value - min_value) // 8))
        self._refresh_label_width()
        self.setValue(self.value())

    def setValue(self, value: int) -> None:
        self.slider.setValue(int(value))
        self.valueLabel.setText(self._label_text(self.slider.value()))

    def value(self) -> int:
        return int(self.slider.value())

    def blockSignals(self, block: bool) -> bool:
        return super().blockSignals(block)

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(bool(enabled))
        effect = self.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(effect)
        effect.setOpacity(1.0 if enabled else 0.4)

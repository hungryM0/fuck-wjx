"""运行参数页 - 专属设置卡片组件。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QTime, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    ExpandGroupSettingCard,
    FluentIcon,
    IndicatorPosition,
    LineEdit,
    OptionsConfigItem,
    OptionsSettingCard,
    OptionsValidator,
    SwitchButton,
)
from qfluentwidgets.components.date_time.picker_base import DigitFormatter, PickerColumnFormatter
from qfluentwidgets.components.date_time.time_picker import TimePickerBase

from software.core.psychometrics.psychometric import (
    DEFAULT_TARGET_ALPHA,
    MAX_TARGET_ALPHA,
    MIN_TARGET_ALPHA,
    normalize_target_alpha,
)
from software.ui.helpers.fluent_tooltip import install_tooltip_filter
from software.ui.widgets.setting_cards import set_widget_enabled_with_opacity


class RandomUASettingCard(ExpandGroupSettingCard):
    """随机 UA 设置卡。"""

    def __init__(self, parent=None):
        super().__init__(
            FluentIcon.ROBOT,
            "随机 UA",
            "模拟不同的 User-Agent，例如微信环境或浏览器直链环境",
            parent,
        )

        self.switchButton = SwitchButton(self, IndicatorPosition.RIGHT)
        self.switchButton.setOnText("开")
        self.switchButton.setOffText("关")
        self.addWidget(self.switchButton)

        self._groupContainer = QWidget()
        layout = QVBoxLayout(self._groupContainer)
        layout.setContentsMargins(48, 12, 48, 12)
        layout.setSpacing(16)

        hint_label = BodyLabel(
            "配置不同设备类型的访问占比，三个滑块占比总和必须为 100%",
            self._groupContainer,
        )
        hint_label.setStyleSheet("color: #606060; font-size: 12px;")
        layout.addWidget(hint_label)

        from software.ui.widgets.ratio_slider import RatioSlider

        self.ratioSlider = RatioSlider(
            labels={
                "wechat": "微信访问占比",
                "mobile": "手机访问占比",
                "pc": "链接访问占比",
            },
            parent=self._groupContainer,
        )
        layout.addWidget(self.ratioSlider)

        self.addGroupWidget(self._groupContainer)
        self.setExpand(True)
        self.switchButton.checkedChanged.connect(self.setUAEnabled)
        self.setUAEnabled(False)

    def isChecked(self):
        return self.switchButton.isChecked()

    def setChecked(self, checked):
        self.switchButton.setChecked(checked)

    def setUAEnabled(self, enabled):
        set_widget_enabled_with_opacity(self._groupContainer, bool(enabled))

    def getRatios(self) -> dict:
        """获取当前设备占比配置。"""
        return self.ratioSlider.getValues()

    def setRatios(self, ratios: dict):
        """设置设备占比配置。"""
        self.ratioSlider.setValues(ratios)


class ReliabilitySettingCard(ExpandGroupSettingCard):
    """信效度设置卡。"""

    def __init__(self, parent=None):
        super().__init__(
            FluentIcon.CERTIFICATE,
            "提升问卷信度",
            "仅对量表/评分/矩阵量表/量表型单选生效，不确保信度完全符合预期，请勿用于正式环境。",
            parent,
        )

        self.switchButton = SwitchButton(self, IndicatorPosition.RIGHT)
        self.switchButton.setOnText("开")
        self.switchButton.setOffText("关")
        self.addWidget(self.switchButton)

        self._groupContainer = QWidget(self)
        layout = QVBoxLayout(self._groupContainer)
        layout.setContentsMargins(48, 12, 48, 12)
        layout.setSpacing(12)

        alpha_row = QHBoxLayout()
        alpha_row.setContentsMargins(0, 0, 0, 0)
        alpha_row.setSpacing(8)

        alpha_label = BodyLabel("目标 Cronbach's α 系数", self._groupContainer)
        self.alphaEdit = LineEdit(self._groupContainer)
        placeholder = (
            f"{MIN_TARGET_ALPHA:.2f} - {MAX_TARGET_ALPHA:.2f}（默认 {DEFAULT_TARGET_ALPHA:g}）"
        )
        self.alphaEdit.setPlaceholderText(placeholder)
        self.alphaEdit.setFixedWidth(120)
        self.alphaEdit.setFixedHeight(36)
        self.alphaEdit.setText(f"{DEFAULT_TARGET_ALPHA:g}")

        validator = QDoubleValidator(MIN_TARGET_ALPHA, MAX_TARGET_ALPHA, 2, self.alphaEdit)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.alphaEdit.setValidator(validator)

        alpha_row.addWidget(alpha_label)
        alpha_row.addStretch(1)
        alpha_row.addWidget(self.alphaEdit)

        layout.addLayout(alpha_row)

        self.addGroupWidget(self._groupContainer)
        self.setExpand(True)
        self.switchButton.checkedChanged.connect(self._sync_enabled)
        self._sync_enabled(False)

    def _sync_enabled(self, enabled: bool) -> None:
        """根据开关状态启用/禁用内部控件。"""

        set_widget_enabled_with_opacity(self._groupContainer, bool(enabled))

    def isChecked(self) -> bool:
        return self.switchButton.isChecked()

    def setChecked(self, checked: bool) -> None:
        self.switchButton.setChecked(bool(checked))

    def get_alpha(self) -> float:
        """读取并裁剪目标 Alpha 值，落在允许范围内。"""

        return normalize_target_alpha((self.alphaEdit.text() or "").strip())

    def set_alpha(self, value: float) -> None:
        """设置目标 Alpha，并同步到输入框文本。"""
        num = normalize_target_alpha(value)
        text = f"{num:.2f}".rstrip("0").rstrip(".")
        if not text:
            text = f"{DEFAULT_TARGET_ALPHA:g}"
        if self.alphaEdit.text() != text:
            self.alphaEdit.setText(text)


class DurationMinuteFormatter(PickerColumnFormatter):
    """分钟列显示。"""

    def encode(self, value):
        return f"{int(value)} 分"

    def decode(self, value: str):
        return str(value).replace("分", "").strip() or "0"


class DurationSecondFormatter(DigitFormatter):
    """秒列显示。"""

    def encode(self, value):
        return f"{int(value):02d} 秒"

    def decode(self, value: str):
        return int(str(value).replace("秒", "").strip() or 0)


class DurationTimePicker(TimePickerBase):
    """只显示分钟和秒的时长选择器。"""

    def __init__(self, parent=None, max_seconds: int = 86399):
        super().__init__(parent=parent, showSeconds=True)
        self.max_seconds = max(0, int(max_seconds or 0))
        self._duration_seconds = 0
        minute_max = max(0, self.max_seconds // 60)
        self.addColumn("分钟", range(0, minute_max + 1), 120, formatter=DurationMinuteFormatter())
        self.addColumn("秒", range(0, 60), 120, formatter=DurationSecondFormatter())

    def getDurationSeconds(self) -> int:
        return self._duration_seconds

    def setDurationSeconds(self, seconds: int) -> None:
        normalized = max(0, min(int(seconds or 0), self.max_seconds))
        self._duration_seconds = normalized
        minutes, remainder_seconds = divmod(normalized, 60)
        hours, remainder_minutes = divmod(minutes, 60)
        self._time = QTime(hours, remainder_minutes, remainder_seconds)
        self.setColumnValue(0, minutes)
        self.setColumnValue(1, remainder_seconds)

    def getTime(self):
        return self._time

    def setTime(self, time: QTime):
        if not isinstance(time, QTime) or not time.isValid():
            self.setDurationSeconds(0)
            return
        self.setDurationSeconds(time.hour() * 3600 + time.minute() * 60 + time.second())

    def _onConfirmed(self, value: list):
        super()._onConfirmed(value)
        if len(value) < 2:
            return
        minutes = self.decodeValue(0, value[0])
        seconds = self.decodeValue(1, value[1])
        duration_seconds = int(minutes) * 60 + int(seconds)
        previous = self._duration_seconds
        self.setDurationSeconds(duration_seconds)
        if self._duration_seconds != previous:
            self.timeChanged.emit(self._time)


class TimeRangeSettingCard(OptionsSettingCard):
    """时间范围设置卡。"""

    valueChanged = Signal(int)
    rangeChanged = Signal(tuple)

    def __init__(self, icon, title, content, max_seconds: Optional[int] = 300, parent=None):
        self.max_seconds = None if max_seconds is None else max(0, int(max_seconds))
        self._current_range = (0, 0)
        config_item = OptionsConfigItem(
            "RuntimeTimeRange",
            str(title or "TimeRange"),
            "custom",
            OptionsValidator(["custom"]),
        )
        super().__init__(config_item, icon, title, content, texts=["自定义"], parent=parent)

        self.setExpand(True)
        self.choiceLabel.hide()
        self.choiceLabel.setFixedWidth(0)
        for button in self.buttonGroup.buttons():
            button.hide()
        self.viewLayout.setSpacing(12)
        self.viewLayout.setContentsMargins(48, 12, 48, 16)

        self._input_container = QWidget(self.view)
        input_layout = QVBoxLayout(self._input_container)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(10)

        picker_max_seconds = 86399 if self.max_seconds is None else self.max_seconds
        self.startPicker = DurationTimePicker(
            self._input_container,
            max_seconds=picker_max_seconds,
        )
        self.endPicker = DurationTimePicker(
            self._input_container,
            max_seconds=picker_max_seconds,
        )
        for picker in (self.startPicker, self.endPicker):
            picker.setFixedWidth(240)
            picker.setDurationSeconds(0)

        tooltip_text = (
            "允许范围：0 分 00 秒 - 1439 分 59 秒"
            if self.max_seconds is None
            else f"允许范围：0 分 00 秒 - {self._format_seconds(self.max_seconds)}"
        )
        for picker in (self.startPicker, self.endPicker):
            picker.setToolTip(tooltip_text)
            install_tooltip_filter(picker)
            picker.timeChanged.connect(self._on_time_changed)

        self.inputEdit = self.startPicker
        start_row = QHBoxLayout()
        start_row.setContentsMargins(0, 0, 0, 0)
        start_row.setSpacing(8)
        end_row = QHBoxLayout()
        end_row.setContentsMargins(0, 0, 0, 0)
        end_row.setSpacing(8)

        start_label = BodyLabel("最短时间", self._input_container)
        end_label = BodyLabel("最长时间", self._input_container)
        for label in (start_label, end_label):
            label.setFixedWidth(72)
            label.setStyleSheet("color: #606060;")

        start_row.addWidget(start_label)
        start_row.addStretch(1)
        start_row.addWidget(self.startPicker)
        end_row.addWidget(end_label)
        end_row.addStretch(1)
        end_row.addWidget(self.endPicker)
        input_layout.addLayout(start_row)
        input_layout.addLayout(end_row)

        self.viewLayout.addWidget(self._input_container)
        self._adjustViewSize()

    def _clamp_value(self, value: int) -> int:
        normalized = max(0, int(value))
        if self.max_seconds is None:
            return min(normalized, 86399)
        return min(normalized, self.max_seconds)

    @staticmethod
    def _time_to_seconds(value: QTime) -> int:
        if not isinstance(value, QTime) or not value.isValid():
            return 0
        return max(0, value.hour() * 3600 + value.minute() * 60 + value.second())

    @staticmethod
    def _seconds_to_time(value: int) -> QTime:
        normalized = max(0, min(int(value or 0), 86399))
        hours, remainder = divmod(normalized, 3600)
        minutes, seconds = divmod(remainder, 60)
        return QTime(hours, minutes, seconds)

    @staticmethod
    def _format_seconds(value: int) -> str:
        normalized = max(0, int(value or 0))
        minutes, seconds = divmod(normalized, 60)
        return f"{minutes} 分 {seconds:02d} 秒"

    def _normalize_range(self, start: int, end: int) -> tuple[int, int]:
        low = self._clamp_value(start)
        high = self._clamp_value(end)
        if high < low:
            high = low
        return low, high

    def _on_time_changed(self, _time: QTime):
        start = self.startPicker.getDurationSeconds()
        end = self.endPicker.getDurationSeconds()
        normalized = self._normalize_range(start, end)
        if (start, end) != normalized:
            self.setRange(normalized)
            return
        if normalized != self._current_range:
            self._current_range = normalized
            self.valueChanged.emit(normalized[0])
            self.rangeChanged.emit(normalized)

    def setEnabled(self, arg__1):
        super().setEnabled(arg__1)
        self.startPicker.setEnabled(arg__1)
        self.endPicker.setEnabled(arg__1)

    def getValue(self) -> int:
        """获取当前范围起点秒数。"""
        return self.getRange()[0]

    def getRange(self) -> tuple[int, int]:
        """获取当前秒数范围。"""
        start = self.startPicker.getDurationSeconds()
        end = self.endPicker.getDurationSeconds()
        self._current_range = self._normalize_range(start, end)
        return self._current_range

    def setValue(self, value: int):
        """设置固定秒数。"""
        if isinstance(value, str):
            OptionsSettingCard.setValue(self, value)
            return
        self.setRange((value, value))

    def setRange(self, value_range):
        """设置秒数范围。"""
        if isinstance(value_range, (list, tuple)):
            start = value_range[0] if len(value_range) >= 1 else 0
            end = value_range[1] if len(value_range) >= 2 else start
        else:
            start = end = value_range
        try:
            normalized = self._normalize_range(int(start or 0), int(end or 0))
        except Exception:
            normalized = (0, 0)
        previous = self._current_range
        self._current_range = normalized

        self.startPicker.blockSignals(True)
        self.endPicker.blockSignals(True)
        try:
            self.startPicker.setDurationSeconds(normalized[0])
            self.endPicker.setDurationSeconds(normalized[1])
        finally:
            self.startPicker.blockSignals(False)
            self.endPicker.blockSignals(False)

        if normalized != previous:
            self.valueChanged.emit(normalized[0])
            self.rangeChanged.emit(normalized)

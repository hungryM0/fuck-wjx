"""运行参数页 - 专属设置卡片组件（随机UA、定时模式等）"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    ExpandGroupSettingCard,
    FluentIcon,
    IndicatorPosition,
    LineEdit,
    SettingCard,
    SwitchButton,
    TransparentToolButton,
)

from software.core.psychometrics.psychometric import (
    DEFAULT_TARGET_ALPHA,
    MAX_TARGET_ALPHA,
    MIN_TARGET_ALPHA,
    normalize_target_alpha,
)
from software.ui.helpers.fluent_tooltip import install_tooltip_filter
from software.ui.widgets.setting_cards import set_widget_enabled_with_opacity


class TimedModeSettingCard(SettingCard):
    """定时模式设置卡。"""

    def __init__(self, icon, title, content, parent=None):
        super().__init__(icon, title, content, parent)
        self.helpButton = TransparentToolButton(FluentIcon.INFO, self)
        self.helpButton.setFixedSize(18, 18)
        self.helpButton.setIconSize(QSize(14, 14))
        self.helpButton.setCursor(Qt.CursorShape.PointingHandCursor)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(4)
        self.vBoxLayout.removeWidget(self.titleLabel)
        title_row.addWidget(self.titleLabel)
        title_row.addWidget(self.helpButton)
        title_row.addStretch()
        self.vBoxLayout.insertLayout(0, title_row)

        self.switchButton = SwitchButton(self, IndicatorPosition.RIGHT)
        self.switchButton.setOnText("开")
        self.switchButton.setOffText("关")
        self.hBoxLayout.addWidget(self.switchButton, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def isChecked(self):
        return self.switchButton.isChecked()

    def setChecked(self, checked):
        self.switchButton.setChecked(checked)


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


class TimeRangeSettingCard(SettingCard):
    """时间设置卡。"""

    valueChanged = Signal(int)

    def __init__(self, icon, title, content, max_seconds: Optional[int] = 300, parent=None):
        super().__init__(icon, title, content, parent)

        self.max_seconds = None if max_seconds is None else max(0, int(max_seconds))
        self._current_value = 0

        self._input_container = QWidget(self)
        input_layout = QHBoxLayout(self._input_container)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(8)

        self.inputEdit = LineEdit(self._input_container)
        validator_max = 2147483647 if self.max_seconds is None else self.max_seconds
        self.inputEdit.setValidator(QIntValidator(0, validator_max, self.inputEdit))
        self.inputEdit.setFixedWidth(128)
        self.inputEdit.setFixedHeight(36)
        self.inputEdit.setText("0")
        tooltip_text = (
            "允许范围：大于等于 0 秒"
            if self.max_seconds is None
            else f"允许范围：0-{self.max_seconds} 秒"
        )
        self.inputEdit.setToolTip(tooltip_text)
        install_tooltip_filter(self.inputEdit)
        self.inputEdit.textChanged.connect(self._on_text_changed)
        self.inputEdit.editingFinished.connect(self._normalize_text)

        sec_label = BodyLabel("秒", self._input_container)
        sec_label.setStyleSheet("color: #606060;")

        input_layout.addWidget(self.inputEdit)
        input_layout.addWidget(sec_label)

        self.hBoxLayout.addWidget(self._input_container, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def _clamp_value(self, value: int) -> int:
        normalized = max(0, int(value))
        if self.max_seconds is None:
            return normalized
        return min(normalized, self.max_seconds)

    @staticmethod
    def _parse_digits(text: str, fallback: int) -> int:
        raw = str(text or "").strip()
        return int(raw) if raw.isdigit() else int(fallback)

    def _on_text_changed(self, text: str):
        value = self._clamp_value(self._parse_digits(text, fallback=0))
        if value != self._current_value:
            self._current_value = value
            self.valueChanged.emit(value)

    def _normalize_text(self):
        self.setValue(self.getValue())

    def setEnabled(self, arg__1):
        super().setEnabled(arg__1)
        self.inputEdit.setEnabled(arg__1)

    def getValue(self) -> int:
        """获取当前秒数。"""
        value = self._clamp_value(
            self._parse_digits(self.inputEdit.text(), fallback=self._current_value)
        )
        self._current_value = value
        return value

    def setValue(self, value: int):
        """设置当前秒数。"""
        value = self._clamp_value(value)
        previous = self._current_value
        self._current_value = value
        display = str(value)
        if self.inputEdit.text() != display:
            self.inputEdit.blockSignals(True)
            self.inputEdit.setText(display)
            self.inputEdit.blockSignals(False)
        if value != previous:
            self.valueChanged.emit(value)

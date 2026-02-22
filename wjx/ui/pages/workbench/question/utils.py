"""UI 辅助函数"""
import logging
from PySide6.QtGui import QColor, QIntValidator
from PySide6.QtWidgets import QLabel
from qfluentwidgets import LineEdit

from wjx.ui.widgets.no_wheel import NoWheelSlider

logger = logging.getLogger(__name__)


def _shorten_text(text: str, limit: int = 80) -> str:
    if not text:
        return ""
    text = str(text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _apply_label_color(label: QLabel, light: str, dark: str) -> None:
    """为标签设置浅色/深色主题颜色。"""
    try:
        getattr(label, 'setTextColor')(QColor(light), QColor(dark))
    except AttributeError as e:
        # setTextColor 方法不存在，使用样式表作为备选方案
        logger.debug(f"setTextColor 方法不可用，使用样式表: {e}")
        style = label.styleSheet() or ""
        style = style.strip()
        if style and not style.endswith(";"):
            style = f"{style};"
        label.setStyleSheet(f"{style}color: {light};")


def _bind_slider_input(slider: NoWheelSlider, edit: LineEdit) -> None:
    """绑定滑块与输入框，避免循环触发。"""
    min_value = int(slider.minimum())
    max_value = int(slider.maximum())
    edit.setValidator(QIntValidator(min_value, max_value, edit))

    def sync_edit(value: int) -> None:
        edit.blockSignals(True)
        edit.setText(str(int(value)))
        edit.blockSignals(False)

    def sync_slider_live(text: str) -> None:
        if not text:
            return
        try:
            value = int(text)
        except ValueError:
            logger.debug(f"滑块输入框数值转换失败: '{text}' 不是有效整数")
            return
        if value < min_value or value > max_value:
            return
        slider.blockSignals(True)
        slider.setValue(value)
        slider.blockSignals(False)

    def sync_slider_final() -> None:
        text = edit.text().strip()
        if not text:
            return
        try:
            value = int(text)
        except ValueError:
            logger.debug(f"滑块输入框最终值转换失败: '{text}' 不是有效整数")
            return
        value = max(min_value, min(max_value, value))
        slider.blockSignals(True)
        slider.setValue(value)
        slider.blockSignals(False)
        edit.blockSignals(True)
        edit.setText(str(value))
        edit.blockSignals(False)

    slider.valueChanged.connect(sync_edit)
    edit.textChanged.connect(sync_slider_live)
    edit.editingFinished.connect(sync_slider_final)

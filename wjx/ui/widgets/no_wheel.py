"""禁用鼠标滚轮的组件。"""
from PySide6.QtWidgets import QSlider
from qfluentwidgets import SpinBox


class NoWheelSlider(QSlider):
    """禁用鼠标滚轮的滑块"""
    def wheelEvent(self, event):  # type: ignore[override]
        event.ignore()


class NoWheelSpinBox(SpinBox):
    """禁用鼠标滚轮的数字输入框"""
    def wheelEvent(self, event):  # type: ignore[override]
        event.ignore()

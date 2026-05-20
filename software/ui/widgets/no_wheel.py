"""禁用鼠标滚轮的组件。"""

from PySide6.QtGui import QWheelEvent
from qfluentwidgets import Slider, SpinBox


class NoWheelSlider(Slider):
    """禁用鼠标滚轮的滑块"""

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


class NoWheelSpinBox(SpinBox):
    """禁用鼠标滚轮的数字输入框"""

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()

"""题目向导内部共享 UI 小工具。"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLayout


def color_with_alpha(color: QColor, alpha: int) -> QColor:
    copied = QColor(color)
    copied.setAlpha(max(0, min(255, int(alpha))))
    return copied


def clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            continue
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
            continue
        child_layout = item.layout()
        if child_layout is not None:
            clear_layout(child_layout)

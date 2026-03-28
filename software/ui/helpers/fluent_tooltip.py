"""Fluent tooltip 辅助工具。"""
from __future__ import annotations

from typing import Iterable, Optional

from PySide6.QtWidgets import QWidget
from qfluentwidgets import ToolTipFilter, ToolTipPosition


class FluentToolTipFilter(ToolTipFilter):
    """支持禁用控件显示提示的 Fluent tooltip 过滤器。"""

    def __init__(
        self,
        parent: QWidget,
        showDelay: int = 300,
        position: ToolTipPosition = ToolTipPosition.TOP,
        showOnDisabled: bool = True,
    ):
        super().__init__(parent, showDelay=showDelay, position=position)
        self._show_on_disabled = bool(showOnDisabled)

    def _canShowToolTip(self) -> bool:
        parent = self.parent()
        if not isinstance(parent, QWidget):
            return False
        if not parent.isWidgetType() or not parent.toolTip():
            return False
        return self._show_on_disabled or parent.isEnabled()


def install_tooltip_filter(
    widget: Optional[QWidget],
    *,
    position: ToolTipPosition = ToolTipPosition.TOP,
    show_delay: int = 300,
    show_on_disabled: bool = True,
) -> Optional[FluentToolTipFilter]:
    """给单个控件安装 Fluent tooltip 过滤器。"""
    if widget is None:
        return None

    current = next(
        (child for child in widget.children() if isinstance(child, FluentToolTipFilter)),
        None,
    )
    if current is not None:
        current.position = position
        current.setToolTipDelay(int(show_delay))
        current._show_on_disabled = bool(show_on_disabled)
        return current

    tooltip_filter = FluentToolTipFilter(
        widget,
        showDelay=int(show_delay),
        position=position,
        showOnDisabled=show_on_disabled,
    )
    widget.installEventFilter(tooltip_filter)
    return tooltip_filter


def install_tooltip_filters(
    widgets: Iterable[Optional[QWidget]],
    *,
    position: ToolTipPosition = ToolTipPosition.TOP,
    show_delay: int = 300,
    show_on_disabled: bool = True,
) -> None:
    """批量安装 Fluent tooltip 过滤器。"""
    for widget in widgets:
        install_tooltip_filter(
            widget,
            position=position,
            show_delay=show_delay,
            show_on_disabled=show_on_disabled,
        )


__all__ = [
    "FluentToolTipFilter",
    "install_tooltip_filter",
    "install_tooltip_filters",
]

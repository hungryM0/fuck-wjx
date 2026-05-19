"""统一封装常用 InfoBar 行为。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QTimer
from qfluentwidgets import InfoBar, InfoBarPosition
from qfluentwidgets.components.widgets.info_bar import InfoBarManager


def show_message_bar(
    *,
    parent,
    message: str,
    level: str = "info",
    title: str = "",
    position=InfoBarPosition.TOP,
    duration: int = 2000,
) -> InfoBar:
    """按级别创建统一样式的消息条。"""
    kind = str(level or "info").strip().lower()
    factory = {
        "success": InfoBar.success,
        "warning": InfoBar.warning,
        "error": InfoBar.error,
        "info": InfoBar.info,
    }.get(kind, InfoBar.info)
    bar = factory(
        str(title or ""),
        str(message or ""),
        parent=parent,
        position=position,
        duration=duration,
    )
    reposition_message_bar(bar)
    return bar


def replace_message_bar(current: Optional[InfoBar]) -> None:
    """关闭旧消息条，避免重复堆叠。"""
    if current is None:
        return
    current.close()


def reposition_message_bar(bar: Optional[InfoBar]) -> None:
    """让 QFluentWidgets 原生管理器在布局稳定后重新计算位置。"""
    if bar is None:
        return

    def _reposition() -> None:
        try:
            parent = bar.parent()
            if parent is None or bar.position == InfoBarPosition.NONE:
                return
            bar.adjustSize()
            manager = InfoBarManager.make(bar.position)
            bar.move(manager._pos(bar))
        except Exception:
            return

    QTimer.singleShot(0, _reposition)

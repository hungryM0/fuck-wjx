"""Full-width InfoBar widget."""
from PySide6.QtCore import QTimer
from qfluentwidgets import InfoBar


class FullWidthInfoBar(InfoBar):
    """InfoBar that stretches to its parent's width."""

    def __init__(self, *args, **kwargs):
        self._syncing = False
        super().__init__(*args, **kwargs)

    def _sync_width(self) -> bool:
        parent = self.parentWidget()
        if parent is None:
            return False
        width = parent.contentsRect().width()
        layout = parent.layout()
        if layout is not None:
            layout_width = layout.contentsRect().width()
            if layout_width > 0:
                width = layout_width
        if width <= 0:
            return False
        if self.width() != width:
            self.setFixedWidth(width)
        return True

    def _adjustText(self):
        if self._syncing:
            return
        self._syncing = True
        try:
            self._sync_width()
            super()._adjustText()
            self._sync_width()
        finally:
            self._syncing = False

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._adjustText)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self._syncing:
            self._adjustText()

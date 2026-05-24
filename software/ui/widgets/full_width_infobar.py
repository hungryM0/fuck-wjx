"""Full-width InfoBar widget."""

from PySide6.QtCore import QEvent, QSize, QTimer
from PySide6.QtWidgets import QSizePolicy
from qfluentwidgets import InfoBar


class FullWidthInfoBar(InfoBar):
    """InfoBar that stretches to its parent's width."""

    def __init__(self, *args, **kwargs):
        self._syncing = False
        self._parent_filter_installed = False
        self._sync_timers = []
        super().__init__(*args, **kwargs)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.destroyed.connect(self._clear_sync_timers)

    def sizeHint(self):
        hint = super().sizeHint()
        parent = self.parentWidget()
        if parent is None:
            return hint
        width = parent.contentsRect().width()
        if width <= 0:
            width = parent.width()
        if width > 0:
            return QSize(width, hint.height())
        return hint

    def _adjustText(self):
        if self._syncing:
            return
        self._syncing = True
        try:
            super()._adjustText()
            self.updateGeometry()
        finally:
            self._syncing = False

    def _install_parent_filter(self) -> None:
        parent = self.parentWidget()
        if parent is None or self._parent_filter_installed:
            return
        parent.installEventFilter(self)
        self._parent_filter_installed = True

    def eventFilter(self, obj, e):
        if obj is self.parentWidget() and e.type() in (
            QEvent.Type.Resize,
            QEvent.Type.LayoutRequest,
            QEvent.Type.Show,
        ):
            self._adjustText()
        return super().eventFilter(obj, e)

    def _schedule_deferred_sync(self) -> None:
        for delay in (0, 30, 120):
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._adjustText)
            timer.timeout.connect(lambda timer=timer: self._drop_sync_timer(timer))
            self._sync_timers.append(timer)
            timer.start(delay)

    def _drop_sync_timer(self, timer: QTimer) -> None:
        try:
            self._sync_timers.remove(timer)
        except ValueError:
            pass
        timer.deleteLater()

    def _clear_sync_timers(self) -> None:
        for timer in list(self._sync_timers):
            timer.stop()
            timer.deleteLater()
        self._sync_timers.clear()

    def showEvent(self, e):
        super().showEvent(e)
        self._install_parent_filter()
        self._schedule_deferred_sync()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._syncing:
            self._adjustText()

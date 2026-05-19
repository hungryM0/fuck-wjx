"""题目向导导航控件。"""

from __future__ import annotations

from typing import Any, List, Optional, cast

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QModelIndex, QPersistentModelIndex
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListWidget,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QWidget,
)
from qfluentwidgets import VerticalPipsPager, isDarkTheme, themeColor
from qfluentwidgets.components.widgets.tool_tip import (
    ItemViewToolTipDelegate,
    ItemViewToolTipType,
)

from .ui_helpers import color_with_alpha


class WizardPipsDelegate(QStyledItemDelegate):
    """带 tooltip 的分页点绘制。"""

    def __init__(self, parent: Optional[QAbstractItemView] = None):
        super().__init__(parent)
        self.hoveredRow = -1
        self.pressedRow = -1
        if parent is None:
            raise ValueError("WizardPipsDelegate 需要 QAbstractItemView 作为父对象")
        self._view_parent = parent
        self.tooltipDelegate = ItemViewToolTipDelegate(parent, 200, ItemViewToolTipType.LIST)
        self.tooltipDelegate.setToolTipDuration(1200)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        option_view = cast(Any, option)
        painter.save()
        painter.setRenderHints(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        row = index.row()
        is_hover = row == self.hoveredRow
        is_pressed = row == self.pressedRow
        is_selected = bool(option_view.state & QStyle.StateFlag.State_Selected)
        question_number = row + 1

        center_x = option_view.rect.right() - 9
        center_y = option_view.rect.center().y()
        accent = QColor(themeColor())
        if isDarkTheme():
            idle_color = QColor(255, 255, 255, 150)
            hover_color = QColor(255, 255, 255, 218)
            hover_halo = QColor(255, 255, 255, 56)
            active_halo = color_with_alpha(accent, 92)
            label_color = QColor(255, 255, 255, 235)
            active_label_color = QColor(255, 255, 255, 255)
            label_fill = QColor(255, 255, 255, 42)
            active_label_fill = color_with_alpha(accent, 96)
        else:
            idle_color = QColor(0, 0, 0, 122)
            hover_color = QColor(0, 0, 0, 176)
            hover_halo = QColor(0, 0, 0, 34)
            active_halo = color_with_alpha(accent, 70)
            label_color = QColor(73, 73, 73, 230)
            active_label_color = QColor(22, 22, 22, 255)
            label_fill = QColor(255, 255, 255, 236)
            active_label_fill = color_with_alpha(accent, 72)

        if question_number % 5 == 0:
            badge_rect = QRectF(
                option_view.rect.x() + 1,
                option_view.rect.center().y() - 7,
                14,
                14,
            )
            painter.setBrush(active_label_fill if is_selected else label_fill)
            painter.drawRoundedRect(badge_rect, 5, 5)
            painter.setPen(active_label_color if is_selected else label_color)
            number_font = QFont(painter.font())
            number_font.setPixelSize(10)
            number_font.setBold(True)
            painter.setFont(number_font)
            painter.drawText(
                badge_rect,
                Qt.AlignmentFlag.AlignCenter,
                str(question_number),
            )
            painter.setPen(Qt.PenStyle.NoPen)

        center_point = QPointF(center_x, center_y)
        if is_selected:
            painter.setBrush(active_halo)
            painter.drawEllipse(center_point, 8, 8)
            painter.setBrush(accent)
            painter.drawEllipse(center_point, 4.5, 4.5)
            painter.setBrush(QColor(255, 255, 255, 245))
            painter.drawEllipse(center_point, 1.6, 1.6)
        elif is_pressed or is_hover:
            painter.setBrush(hover_halo)
            painter.drawEllipse(center_point, 6.2, 6.2)
            painter.setBrush(hover_color)
            painter.drawEllipse(center_point, 3.6, 3.6)
        else:
            painter.setBrush(idle_color)
            painter.drawEllipse(center_point, 3.2, 3.2)
        painter.restore()

    def setPressedRow(self, row: int) -> None:
        self.pressedRow = row
        self._view_parent.viewport().update()

    def setHoveredRow(self, row: int) -> None:
        self.hoveredRow = row
        self._view_parent.viewport().update()

    def helpEvent(self, event, view, option, index):
        model_index = cast(QModelIndex, index)
        return self.tooltipDelegate.helpEvent(event, view, option, model_index)


class StableVerticalPipsPager(VerticalPipsPager):
    """稳定版竖向分页器。"""

    _ARROW_STEP = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tooltip_texts: List[str] = []
        self._cell_width = 26
        self._dot_span = 18
        self._cell_gap = 10
        self.delegate = WizardPipsDelegate(self)
        self.setItemDelegate(self.delegate)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("background: transparent; border: none;")
        self.setViewportMargins(0, 14, 0, 14)
        self._apply_grid_metrics()

    def _apply_grid_metrics(self) -> None:
        grid_size = QSize(self._cell_width, self._dot_span + self._cell_gap)
        self.setGridSize(grid_size)
        self.setFixedWidth(self._cell_width)
        for idx in range(self.count()):
            item = self.item(idx)
            if item is not None:
                item.setSizeHint(grid_size)
        self.adjustSize()

    def setSpacing(self, space: int) -> None:
        self._cell_gap = max(0, int(space))
        self._apply_grid_metrics()

    def spacing(self) -> int:
        return self._cell_gap

    def setToolTipTexts(self, texts: List[str]) -> None:
        self._tooltip_texts = [str(text or "").strip() for text in texts]
        for idx in range(self.count()):
            item = self.item(idx)
            if item is None:
                continue
            tip = self._tooltip_texts[idx] if idx < len(self._tooltip_texts) else f"第{idx + 1}题"
            item.setToolTip(tip)

    def setPageNumber(self, n: int):
        super().setPageNumber(n)
        self._apply_grid_metrics()
        if self._tooltip_texts:
            self.setToolTipTexts(self._tooltip_texts)

    def _setPressedItem(self, item) -> None:
        try:
            row = self.row(item)
        except RuntimeError:
            return
        if row < 0:
            return
        self.delegate.setPressedRow(row)
        self.setCurrentIndex(row)

    def _setHoveredItem(self, item) -> None:
        try:
            row = self.row(item)
        except RuntimeError:
            return
        self.delegate.setHoveredRow(row)

    def leaveEvent(self, e):
        self.delegate.setHoveredRow(-1)
        super().leaveEvent(e)

    def setCurrentIndex(self, index: int):
        if not 0 <= index < self.count():
            return
        try:
            item = self.item(index)
        except RuntimeError:
            return
        if item is None:
            return
        self.clearSelection()
        item.setSelected(False)
        self.currentIndexChanged.emit(index)
        QListWidget.setCurrentItem(self, item)
        self._updateScrollButtonVisibility()

    def scrollNext(self) -> None:
        self.setCurrentIndex(min(self.count() - 1, self.currentIndex() + self._ARROW_STEP))

    def scrollPrevious(self) -> None:
        self.setCurrentIndex(max(0, self.currentIndex() - self._ARROW_STEP))


class FloatingPagerShell(QWidget):
    """透明外壳，只负责把分页器摆在左侧。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pager = StableVerticalPipsPager(self)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pager.setCursor(Qt.CursorShape.PointingHandCursor)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        pager_width = self.pager.width()
        pager_height = min(self.height(), self.pager.height())
        self.pager.setGeometry(
            (self.width() - pager_width) // 2,
            max(0, (self.height() - pager_height) // 2),
            pager_width,
            pager_height,
        )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        rect = self.rect().adjusted(5, 4, -5, -4)
        if rect.width() <= 0 or rect.height() <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing)

        if isDarkTheme():
            fill_color = QColor(24, 24, 24, 164)
            border_color = QColor(255, 255, 255, 34)
            rail_color = QColor(255, 255, 255, 42)
        else:
            fill_color = QColor(248, 249, 251, 238)
            border_color = QColor(0, 0, 0, 18)
            rail_color = QColor(0, 0, 0, 28)

        painter.setPen(QPen(border_color, 1))
        painter.setBrush(fill_color)
        painter.drawRoundedRect(QRectF(rect), rect.width() / 2, rect.width() / 2)

        if self.pager.count() > 1:
            line_pen = QPen(rail_color, 1)
            line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(line_pen)
            center_x = rect.center().x()
            painter.drawLine(
                QPointF(center_x, rect.top() + 16),
                QPointF(center_x, rect.bottom() - 16),
            )

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        local_y = event.position().toPoint().y() - self.pager.y()
        index = self._resolve_index_from_y(local_y)
        if index is not None:
            self.pager.setCurrentIndex(index)

    def _resolve_index_from_y(self, local_y: int) -> Optional[int]:
        if self.pager.count() <= 0:
            return None
        nearest_index = 0
        nearest_distance = None
        for idx in range(self.pager.count()):
            item = self.pager.item(idx)
            if item is None:
                continue
            rect = self.pager.visualItemRect(item)
            center_y = rect.center().y()
            distance = abs(local_y - center_y)
            if nearest_distance is None or distance < nearest_distance:
                nearest_distance = distance
                nearest_index = idx
        return nearest_index


__all__ = [
    "FloatingPagerShell",
    "StableVerticalPipsPager",
    "WizardPipsDelegate",
]

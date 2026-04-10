"""题目配置向导导航与滚动同步。"""
from typing import TYPE_CHECKING, Any, List, Optional, cast

from PySide6.QtCore import QObject, QEasingCurve, QEvent, QPointF, QPropertyAnimation, QRectF, QSize, QTimer, Qt, QModelIndex, QPersistentModelIndex
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QStyle, QStyleOptionViewItem, QWidget, QStyledItemDelegate
from qfluentwidgets import CardWidget, VerticalPipsPager, isDarkTheme, themeColor
from qfluentwidgets.components.widgets.pips_pager import PipsScrollButtonDisplayMode
from qfluentwidgets.components.widgets.tool_tip import ItemViewToolTipDelegate, ItemViewToolTipType

from software.ui.helpers.fluent_tooltip import install_tooltip_filters

def _color_with_alpha(color: QColor, alpha: int) -> QColor:
    copied = QColor(color)
    copied.setAlpha(max(0, min(255, int(alpha))))
    return copied

class WizardPipsDelegate(QStyledItemDelegate):
    """带 ItemViewToolTipDelegate 的分页点绘制。"""

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
        painter.save()
        painter.setRenderHints(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        row = index.row()
        is_hover = row == self.hoveredRow
        is_pressed = row == self.pressedRow
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        question_number = row + 1

        center_x = option.rect.right() - 9
        center_y = option.rect.center().y()
        accent = QColor(themeColor())
        if isDarkTheme():
            idle_color = QColor(255, 255, 255, 150)
            hover_color = QColor(255, 255, 255, 218)
            hover_halo = QColor(255, 255, 255, 56)
            active_halo = _color_with_alpha(accent, 92)
            label_color = QColor(255, 255, 255, 235)
            active_label_color = QColor(255, 255, 255, 255)
            label_fill = QColor(255, 255, 255, 42)
            active_label_fill = _color_with_alpha(accent, 96)
        else:
            idle_color = QColor(0, 0, 0, 122)
            hover_color = QColor(0, 0, 0, 176)
            hover_halo = QColor(0, 0, 0, 34)
            active_halo = _color_with_alpha(accent, 70)
            label_color = QColor(73, 73, 73, 230)
            active_label_color = QColor(22, 22, 22, 255)
            label_fill = QColor(255, 255, 255, 236)
            active_label_fill = _color_with_alpha(accent, 72)

        if question_number % 5 == 0:
            badge_rect = QRectF(option.rect.x() + 1, option.rect.center().y() - 7, 14, 14)
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
        return self.tooltipDelegate.helpEvent(event, view, option, index)

class StableVerticalPipsPager(VerticalPipsPager):
    """稳定版竖向分页器：保留 PipsPager 行为，放大命中范围并接 ToolTipFilter 链路。"""

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

    def setSpacing(self, spacing: int) -> None:
        self._cell_gap = max(0, int(spacing))
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
    """透明外壳：只负责把分页器摆在左侧空白带中间。"""

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

class WizardNavigationMixin:
    _QUESTION_INDEX_PROPERTY = "_wizardQuestionIndex"

    if TYPE_CHECKING:
        _question_cards: List[CardWidget]
        _question_shell: Optional[FloatingPagerShell]
        _question_pager: Optional[StableVerticalPipsPager]
        _scroll_area: Any
        _content_layout: Any
        _content_container: Any
        _current_question_idx: int
        _navigation_item_count: int
        _navigation_lane_width: int
        _scroll_animation: Optional[QPropertyAnimation]
        _is_animating_scroll: bool
        _search_edit: Any
        _search_popup: Any

        def _get_entry_info(self, idx: int) -> dict: ...
        def _hide_search_popup(self) -> None: ...
        def _activate_search_popup_item(self, item) -> None: ...
        def _restore_entries(self) -> None: ...

    def _build_navigation_shell(self, parent: QWidget) -> FloatingPagerShell:
        shell = FloatingPagerShell(parent)
        shell.pager.currentIndexChanged.connect(self._on_question_pager_changed)
        shell.raise_()
        return shell
    def _configure_navigation_pager(self, total: int) -> None:
        if self._question_pager is None:
            return
        normalized_total = max(1, int(total))
        visible_number = min(normalized_total, 11)
        if self._navigation_item_count == normalized_total:
            self._question_pager.setVisibleNumber(visible_number)
            self._question_pager.setToolTipTexts(self._build_navigation_tooltips())
            display_mode = (
                PipsScrollButtonDisplayMode.ON_HOVER
                if normalized_total > visible_number
                else PipsScrollButtonDisplayMode.NEVER
            )
            self._question_pager.setPreviousButtonDisplayMode(display_mode)
            self._question_pager.setNextButtonDisplayMode(display_mode)
            return
        self._navigation_item_count = normalized_total
        self._question_pager.blockSignals(True)
        self._question_pager.setPageNumber(normalized_total)
        self._question_pager.setVisibleNumber(visible_number)
        self._question_pager.blockSignals(False)
        self._question_pager.setToolTipTexts(self._build_navigation_tooltips())
        display_mode = (
            PipsScrollButtonDisplayMode.ON_HOVER
            if normalized_total > visible_number
            else PipsScrollButtonDisplayMode.NEVER
        )
        self._question_pager.setPreviousButtonDisplayMode(display_mode)
        self._question_pager.setNextButtonDisplayMode(display_mode)
        self._question_pager.preButton.setToolTip("上一题")
        self._question_pager.nextButton.setToolTip("下一题")
        install_tooltip_filters((self._question_pager.preButton, self._question_pager.nextButton))
    def _build_navigation_tooltips(self) -> List[str]:
        labels: List[str] = []
        for idx in range(len(self._question_cards)):
            qnum = str(self._get_entry_info(idx).get("num") or "").strip()
            labels.append(f"第{qnum or idx + 1}题")
        return labels
    def _update_navigation_pager_geometry(self) -> None:
        if self._question_shell is None or self._scroll_area is None:
            return
        scroll_geo = self._scroll_area.geometry()
        if self._question_pager is not None:
            total = max(1, len(self._question_cards))
            preferred_spacing = 12
            if total >= 10:
                preferred_spacing = 10
            if total >= 18:
                preferred_spacing = 8
            if total >= 28:
                preferred_spacing = 6
            available_height = max(96, scroll_geo.height() - 72)
            max_spacing = 0
            if total > 1:
                visible_total = max(1, min(total, self._question_pager.getVisibleNumber()))
                max_spacing = max(0, (available_height - 12 - visible_total * 18) // (visible_total - 1))
            spacing = min(preferred_spacing, max_spacing)
            self._question_pager.setSpacing(spacing)
            shell_height = min(available_height, max(92, self._question_pager.height() + 16))
        else:
            shell_height = max(92, min(scroll_geo.height() - 72, 144))
        shell_width = 30
        x = max(0, scroll_geo.left() + max(0, (self._navigation_lane_width - shell_width) // 2))
        y = scroll_geo.top() + max(12, (scroll_geo.height() - shell_height) // 2)
        self._question_shell.setGeometry(x, y, shell_width, shell_height)
        self._question_shell.raise_()
    def _on_question_pager_changed(self, question_idx: int) -> None:
        self._navigate_to_question(question_idx, animate=True)
    def _navigate_to_question(self, question_idx: int, animate: bool) -> None:
        total = len(self._question_cards)
        if total <= 0:
            self._current_question_idx = 0
            self._refresh_navigation_state(0)
            self._scroll_to_question(None, animate=False)
            return

        clamped = max(0, min(question_idx, total - 1))
        self._current_question_idx = clamped
        self._refresh_navigation_state(total)
        self._scroll_to_question(clamped, animate=animate)
    def _refresh_navigation_state(self, total: int) -> None:
        if self._question_pager is not None:
            self._question_pager.blockSignals(True)
            current = max(0, min(self._current_question_idx, max(total - 1, 0)))
            if self._question_pager.currentIndex() != current:
                self._question_pager.setCurrentIndex(current)
            self._question_pager.setEnabled(total > 1)
            self._question_pager.blockSignals(False)
    def _scroll_to_question(self, question_idx: Optional[int], animate: bool) -> None:
        if self._scroll_area is None or self._content_layout is None or self._content_container is None:
            return
        scroll_bar = self._scroll_area.verticalScrollBar()
        if question_idx is None or not (0 <= question_idx < len(self._question_cards)):
            scroll_bar.setValue(0)
            return
        card = self._question_cards[question_idx]
        target_value = max(0, min(card.y() - 12, scroll_bar.maximum()))
        if not animate:
            self._stop_scroll_animation()
            scroll_bar.setValue(target_value)
            return
        self._animate_scroll_to(target_value)
    def _animate_scroll_to(self, target_value: int) -> None:
        if self._scroll_area is None:
            return
        scroll_bar = self._scroll_area.verticalScrollBar()
        start_value = scroll_bar.value()
        if abs(target_value - start_value) <= 1:
            scroll_bar.setValue(target_value)
            return

        self._stop_scroll_animation()
        curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
        curve.addCubicBezierSegment(QPointF(0.215, 0.61), QPointF(0.355, 1.0), QPointF(1.0, 1.0))

        self._scroll_animation = QPropertyAnimation(scroll_bar, b"value", cast(QObject, self))
        self._scroll_animation.setStartValue(start_value)
        self._scroll_animation.setEndValue(target_value)
        self._scroll_animation.setDuration(self._resolve_scroll_duration(start_value, target_value))
        self._scroll_animation.setEasingCurve(curve)
        self._is_animating_scroll = True
        self._scroll_animation.finished.connect(self._on_scroll_animation_finished)
        self._scroll_animation.start()
    @staticmethod
    def _resolve_scroll_duration(start_value: int, target_value: int) -> int:
        distance = abs(int(target_value) - int(start_value))
        return max(160, min(420, 160 + int(distance * 0.11)))
    def _stop_scroll_animation(self) -> None:
        if self._scroll_animation is None:
            return
        try:
            self._scroll_animation.stop()
        except Exception:
            pass
        self._scroll_animation.deleteLater()
        self._scroll_animation = None
        self._is_animating_scroll = False
    def _on_scroll_animation_finished(self) -> None:
        self._is_animating_scroll = False
        if self._scroll_animation is not None:
            self._scroll_animation.deleteLater()
            self._scroll_animation = None
        self._sync_current_question_from_scroll()
    def _on_scroll_value_changed(self, _value: int) -> None:
        self._hide_search_popup()
        if self._is_animating_scroll:
            return
        self._sync_current_question_from_scroll()
    def _set_current_question_idx(self, question_idx: int) -> None:
        if not self._question_cards:
            self._current_question_idx = 0
            return
        clamped = max(0, min(int(question_idx), len(self._question_cards) - 1))
        if clamped == self._current_question_idx:
            return
        self._current_question_idx = clamped
        self._refresh_navigation_state(len(self._question_cards))
    def _register_question_card_interaction_targets(self, card: CardWidget, idx: int) -> None:
        widgets = [card, *card.findChildren(QWidget)]
        for widget in widgets:
            try:
                widget.setProperty(self._QUESTION_INDEX_PROPERTY, idx)
                widget.installEventFilter(self)
            except Exception:
                continue
    def eventFilter(self, watched, event):
        if watched is self._search_edit and event is not None and event.type() == QEvent.Type.KeyPress:
            if self._search_popup is not None and self._search_popup.isVisible():
                key = event.key()
                if key == Qt.Key.Key_Down:
                    next_row = min(self._search_popup.count() - 1, max(0, self._search_popup.currentRow() + 1))
                    self._search_popup.setCurrentRow(next_row)
                    return True
                if key == Qt.Key.Key_Up:
                    next_row = max(0, self._search_popup.currentRow() - 1)
                    self._search_popup.setCurrentRow(next_row)
                    return True
                if key == Qt.Key.Key_Escape:
                    self._hide_search_popup()
                    return True
        if watched is self._search_edit and event is not None and event.type() == QEvent.Type.FocusOut:
            QTimer.singleShot(0, self._hide_search_popup)
        if watched is self._search_popup and event is not None and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                current_item = self._search_popup.currentItem() if self._search_popup is not None else None
                if current_item is not None:
                    self._activate_search_popup_item(current_item)
                    return True
            if key == Qt.Key.Key_Escape:
                self._hide_search_popup()
                if self._search_edit is not None:
                    self._search_edit.setFocus()
                return True
        if event is not None and event.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.FocusIn,
            QEvent.Type.Wheel,
        ):
            try:
                idx = watched.property(self._QUESTION_INDEX_PROPERTY)
            except Exception:
                idx = None
            if idx is not None:
                try:
                    self._set_current_question_idx(int(idx))
                except Exception:
                    pass
        return cast(Any, super()).eventFilter(watched, event)
    def _resolve_current_question_idx_from_scroll(self) -> int:
        if self._scroll_area is None or not self._question_cards:
            return 0

        scroll_bar = self._scroll_area.verticalScrollBar()
        viewport_height = max(1, self._scroll_area.viewport().height())
        visible_top = int(scroll_bar.value())
        visible_bottom = visible_top + viewport_height

        best_idx = max(0, min(self._current_question_idx, len(self._question_cards) - 1))
        best_visible_height = -1

        # 以“当前视口内哪张卡片占得最多”为准，而不是盯着某个固定锚点。
        # 这样面对高矮差异很大的题目卡片时，不会因为第二张卡片刚冒头就过早切题。
        for idx, card in enumerate(self._question_cards):
            card_top = int(card.y())
            card_bottom = card_top + int(card.height())
            visible_height = min(card_bottom, visible_bottom) - max(card_top, visible_top)
            if visible_height <= 0:
                continue

            if visible_height > best_visible_height:
                best_visible_height = visible_height
                best_idx = idx
                continue

            if visible_height != best_visible_height:
                continue

            if idx == self._current_question_idx:
                best_idx = idx
                continue

            if best_idx == self._current_question_idx:
                continue

            current_anchor = visible_top + min(96, max(32, viewport_height // 3))
            best_distance = abs(int(self._question_cards[best_idx].y()) - current_anchor)
            candidate_distance = abs(card_top - current_anchor)
            if candidate_distance < best_distance:
                best_idx = idx

        return best_idx
    def _sync_current_question_from_scroll(self) -> None:
        if self._is_animating_scroll or self._scroll_area is None or not self._question_cards:
            return
        scroll_bar = self._scroll_area.verticalScrollBar()
        if scroll_bar.value() <= 2:
            self._set_current_question_idx(0)
            return
        if scroll_bar.value() >= max(0, scroll_bar.maximum() - 2):
            self._set_current_question_idx(len(self._question_cards) - 1)
            return
        current_idx = self._resolve_current_question_idx_from_scroll()
        self._set_current_question_idx(current_idx)
    def resizeEvent(self, event) -> None:
        cast(Any, super()).resizeEvent(event)
        self._hide_search_popup()
        self._update_navigation_pager_geometry()
    def reject(self) -> None:
        self._restore_entries()
        cast(Any, super()).reject()

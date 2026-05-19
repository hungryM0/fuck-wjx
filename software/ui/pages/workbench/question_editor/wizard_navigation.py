"""题目配置向导导航与滚动同步。"""

from typing import TYPE_CHECKING, Any, List, Optional, cast

from PySide6.QtCore import (
    QByteArray,
    QObject,
    QEasingCurve,
    QEvent,
    QPointF,
    QPropertyAnimation,
    QTimer,
    Qt,
)
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    CardWidget,
)
from qfluentwidgets.components.widgets.pips_pager import (
    PipsScrollButtonDisplayMode,
)

from software.providers.contracts import SurveyQuestionMeta
from software.ui.helpers.fluent_tooltip import install_tooltip_filters
from .wizard_navigation_widgets import FloatingPagerShell, StableVerticalPipsPager
from .utils import resolve_display_question_num


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

        def _get_entry_info(self, idx: int) -> SurveyQuestionMeta: ...
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
            qnum = resolve_display_question_num(self._get_entry_info(idx), idx + 1)
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
                max_spacing = max(
                    0,
                    (available_height - 12 - visible_total * 18) // (visible_total - 1),
                )
            spacing = min(preferred_spacing, max_spacing)
            self._question_pager.setSpacing(spacing)
            shell_height = min(available_height, max(92, self._question_pager.height() + 16))
        else:
            shell_height = max(92, min(scroll_geo.height() - 72, 144))
        shell_width = 30
        x = max(
            0,
            scroll_geo.left() + max(0, (self._navigation_lane_width - shell_width) // 2),
        )
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
        if (
            self._scroll_area is None
            or self._content_layout is None
            or self._content_container is None
        ):
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

        self._scroll_animation = QPropertyAnimation(
            scroll_bar, QByteArray(b"value"), cast(QObject, self)
        )
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

    def eventFilter(self, arg__1, arg__2):
        watched, event = arg__1, arg__2
        search_edit = getattr(self, "_search_edit", None)
        search_popup = getattr(self, "_search_popup", None)
        search_popup_any = cast(Any, search_popup)
        is_alive_widget = getattr(self, "_is_alive_widget", None)
        popup_alive = (
            search_popup is not None
            and callable(is_alive_widget)
            and bool(is_alive_widget(search_popup))
        )
        if (
            watched is search_edit
            and event is not None
            and event.type() == QEvent.Type.KeyPress
        ):
            if popup_alive and search_popup_any.isVisible():
                key = event.key()
                if key == Qt.Key.Key_Down:
                    next_row = min(
                        search_popup_any.count() - 1,
                        max(0, search_popup_any.currentRow() + 1),
                    )
                    search_popup_any.setCurrentRow(next_row)
                    return True
                if key == Qt.Key.Key_Up:
                    next_row = max(0, search_popup_any.currentRow() - 1)
                    search_popup_any.setCurrentRow(next_row)
                    return True
                if key == Qt.Key.Key_Escape:
                    self._hide_search_popup()
                    return True
        if (
            watched is search_edit
            and event is not None
            and event.type() == QEvent.Type.FocusOut
        ):
            QTimer.singleShot(0, self._hide_search_popup)
        if (
            watched is search_popup
            and event is not None
            and event.type() == QEvent.Type.KeyPress
        ):
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                current_item = (
                    search_popup.currentItem() if search_popup is not None else None
                )
                if current_item is not None:
                    self._activate_search_popup_item(current_item)
                    return True
            if key == Qt.Key.Key_Escape:
                self._hide_search_popup()
                if search_edit is not None:
                    search_edit.setFocus()
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

        # 以当前视口内哪张卡片占得最多为准。
        # 避免高矮差异大时过早切题。
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

    def resizeEvent(self, arg__1) -> None:
        cast(Any, super()).resizeEvent(arg__1)
        self._hide_search_popup()
        self._update_navigation_pager_geometry()

    def reject(self) -> None:
        self._restore_entries()
        cast(Any, super()).reject()

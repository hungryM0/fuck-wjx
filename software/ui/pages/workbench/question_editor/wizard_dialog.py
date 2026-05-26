"""配置向导弹窗。"""

import copy
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QTimer, Qt, QSize
from PySide6.QtGui import QGuiApplication, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QSizePolicy,
    QSplitter,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    PopUpAniStackedWidget,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SearchLineEdit,
    TreeWidget,
)

from software.core.questions.config import QuestionEntry
from software.providers.contracts import SurveyQuestionMeta

from .utils import (
    _apply_label_color,
    _shorten_text,
    build_entry_info_list,
    resolve_display_question_num,
)
from .constants import _get_entry_type_label
from .wizard_cards import WizardCardsMixin
from .wizard_logic_tree import build_logic_tree_state
from . import wizard_result_builder
from .wizard_search import WizardSearchMixin
from .wizard_sections import WizardSectionsMixin
from .wizard_state import WizardRuntimeState, bind_runtime_state

_VIEW_LOGIC = "logic"
_VIEW_SEQUENTIAL = "sequential"
_TREE_INDEX_ROLE = int(Qt.ItemDataRole.UserRole) + 101
_TREE_RELATION_TARGET_ROLE = _TREE_INDEX_ROLE + 1
_LEFT_PANEL_MIN_WIDTH = 240
_LEFT_PANEL_MAX_WIDTH = 520
_RIGHT_PANEL_MIN_WIDTH = 420
_RIGHT_CONTENT_MIN_WIDTH = 320
_WIDGET_MAX_SIZE = 16777215


class _CurrentPagePopUpStackedWidget(PopUpAniStackedWidget):
    """按当前页计算尺寸，避免长题撑高所有短题。"""

    def hasHeightForWidth(self) -> bool:
        current = self.currentWidget()
        if current is not None:
            return current.hasHeightForWidth()
        return super().hasHeightForWidth()

    def heightForWidth(self, width: int) -> int:
        current = self.currentWidget()
        if current is not None and current.hasHeightForWidth():
            return current.heightForWidth(width)
        return super().heightForWidth(width)

    def sizeHint(self) -> QSize:
        current = self.currentWidget()
        if current is not None:
            return current.sizeHint()
        return super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        current = self.currentWidget()
        if current is not None:
            return current.minimumSizeHint()
        return super().minimumSizeHint()

    def setCurrentIndex(self, *args, **kwargs) -> None:
        super().setCurrentIndex(*args, **kwargs)
        self.updateGeometry()

    def setCurrentWidget(self, *args, **kwargs) -> None:
        super().setCurrentWidget(*args, **kwargs)
        self.updateGeometry()


class QuestionWizardDialog(
    WizardSearchMixin,
    WizardCardsMixin,
    WizardSectionsMixin,
    QDialog,
):
    """配置向导：左侧导航，右侧单题工作区。"""

    _PREFERRED_DIALOG_SIZE = QSize(1180, 840)
    _MIN_DIALOG_SIZE = QSize(900, 620)

    def __init__(
        self,
        entries: List[QuestionEntry],
        info: List[SurveyQuestionMeta | Dict[str, Any]],
        survey_title: Optional[str] = None,
        parent=None,
        reliability_mode_enabled: bool = True,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        window_title = "配置向导"
        if survey_title:
            window_title = f"{window_title} - {_shorten_text(survey_title, 36)}"
        self.setWindowTitle(window_title)
        self.resize(self._PREFERRED_DIALOG_SIZE)

        self.entries = entries
        raw_info = list(info or [])
        self.info = build_entry_info_list(self.entries, raw_info)
        self._logic_tree_state = build_logic_tree_state(self.info)
        self.reliability_mode_enabled = reliability_mode_enabled

        bind_runtime_state(self, WizardRuntimeState())
        self._entry_snapshots: List[QuestionEntry] = [copy.deepcopy(entry) for entry in entries]
        self._question_cards: Dict[int, QWidget] = {}
        self._visible_indices: List[int] = list(range(len(self.entries)))
        self._question_search_cache: Dict[int, str] = {}
        self._search_match_indices: List[int] = []
        self._last_search_keyword = ""
        self._last_search_match_cursor = -1
        self._current_question_idx = self._visible_indices[0] if self._visible_indices else 0
        self._current_view_mode = (
            _VIEW_SEQUENTIAL if self._logic_tree_state.has_unknown_logic else _VIEW_LOGIC
        )
        self._screen_change_bound = False
        self._validation_error_dialog = None

        self._search_edit: Optional[SearchLineEdit] = None
        self._search_status_label: Optional[BodyLabel] = None
        self._search_popup: Optional[Any] = None
        self._tree_widget: Optional[TreeWidget] = None
        self._detail_scroll: Optional[ScrollArea] = None
        self._detail_host: Optional[QWidget] = None
        self._detail_layout: Optional[QVBoxLayout] = None
        self._detail_stack: Optional[PopUpAniStackedWidget] = None
        self._empty_page: Optional[QWidget] = None
        self._content_splitter: Optional[QSplitter] = None
        self._entry_card_widgets: Dict[int, QWidget] = {}
        self._prev_button: Optional[PushButton] = None
        self._next_button: Optional[PushButton] = None
        self._splitter_guarding = False

        self._build_ui()
        self._populate_tree()
        if self._visible_indices:
            self._select_question(self._visible_indices[0])
        else:
            self._show_empty_state()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)

        top_row.addStretch(1)
        search_edit = SearchLineEdit(self)
        search_edit.setPlaceholderText("搜索题号、题干、选项、逻辑摘要")
        search_edit.setFixedWidth(360)
        search_edit.searchSignal.connect(self._handle_search)
        search_edit.textChanged.connect(self._on_search_text_changed)
        search_edit.returnPressed.connect(self._handle_search_return_pressed)
        self._search_edit = search_edit
        self._configure_search_popup(search_edit)
        top_row.addWidget(search_edit)
        top_row.addStretch(1)

        layout.addLayout(top_row)

        status_label = BodyLabel("", self)
        status_label.setStyleSheet("font-size: 12px;")
        _apply_label_color(status_label, "#666666", "#bfbfbf")
        self._search_status_label = status_label
        layout.addWidget(status_label)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        splitter.setStyleSheet(
            "QSplitter::handle { background: transparent; }"
            "QSplitter::handle:hover { background: rgba(128, 128, 128, 0.18); }"
        )
        self._content_splitter = splitter
        layout.addWidget(splitter, 1)

        left_card = CardWidget(self)
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(8)
        tree = TreeWidget(left_card)
        tree.setHeaderHidden(True)
        tree.itemClicked.connect(self._on_tree_item_clicked)
        tree.itemActivated.connect(self._on_tree_item_clicked)
        self._tree_widget = tree
        left_layout.addWidget(tree, 1)
        left_card.setMinimumWidth(_LEFT_PANEL_MIN_WIDTH)
        left_card.setMaximumWidth(_LEFT_PANEL_MAX_WIDTH)
        splitter.addWidget(left_card)

        right_card = CardWidget(self)
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(0)
        detail_scroll = ScrollArea(right_card)
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        detail_scroll.enableTransparentBackground()
        detail_host = QWidget(right_card)
        detail_layout = QVBoxLayout(detail_host)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(0)
        detail_stack = _CurrentPagePopUpStackedWidget(detail_host)
        detail_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        detail_layout.addWidget(detail_stack, 0, Qt.AlignmentFlag.AlignTop)
        detail_scroll.setWidget(detail_host)
        self._detail_scroll = detail_scroll
        self._detail_host = detail_host
        self._detail_layout = detail_layout
        self._detail_stack = detail_stack
        right_layout.addWidget(detail_scroll, 1)
        right_card.setMinimumWidth(_RIGHT_PANEL_MIN_WIDTH)
        splitter.addWidget(right_card)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 820])
        splitter.splitterMoved.connect(self._clamp_splitter_sizes)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch(1)
        prev_btn = PushButton("上一题", self)
        next_btn = PushButton("下一题", self)
        cancel_btn = PushButton("取消", self)
        ok_btn = PrimaryPushButton("保存", self)
        prev_btn.clicked.connect(self._go_prev)
        next_btn.clicked.connect(self._go_next)
        cancel_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self.accept)
        self._prev_button = prev_btn
        self._next_button = next_btn
        btn_row.addWidget(prev_btn)
        btn_row.addWidget(next_btn)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        self._set_search_status("点下拉结果或回车即可跳转")

    def _clamp_splitter_sizes(self, *_args) -> None:
        splitter = self._content_splitter
        if splitter is None or self._splitter_guarding:
            return
        sizes = splitter.sizes()
        if len(sizes) < 2:
            return
        total_width = sum(sizes)
        if total_width <= 0:
            return
        max_left = max(
            _LEFT_PANEL_MIN_WIDTH,
            min(_LEFT_PANEL_MAX_WIDTH, total_width - _RIGHT_PANEL_MIN_WIDTH),
        )
        left_width = max(_LEFT_PANEL_MIN_WIDTH, min(sizes[0], max_left))
        right_width = max(_RIGHT_PANEL_MIN_WIDTH, total_width - left_width)
        if [left_width, right_width] == sizes[:2]:
            return
        self._splitter_guarding = True
        try:
            splitter.setSizes([left_width, right_width])
        finally:
            self._splitter_guarding = False
        QTimer.singleShot(0, self._sync_detail_content_width)

    def _sync_detail_content_width(self) -> None:
        detail_scroll = self._detail_scroll
        detail_host = self._detail_host
        detail_stack = self._detail_stack
        if detail_scroll is None or detail_host is None or detail_stack is None:
            return

        viewport = detail_scroll.viewport()
        viewport_width = viewport.width() if viewport is not None else detail_scroll.width()
        if viewport_width <= 0:
            return
        content_width = max(_RIGHT_CONTENT_MIN_WIDTH, viewport_width)

        detail_host.setMinimumWidth(content_width)
        detail_host.setMaximumWidth(content_width)
        detail_stack.setMinimumWidth(content_width)
        detail_stack.setMaximumWidth(content_width)
        for page in self._question_cards.values():
            page.setMinimumWidth(content_width)
            page.setMaximumWidth(content_width)
        for card in self._entry_card_widgets.values():
            card.setMinimumWidth(content_width)
            card.setMaximumWidth(content_width)
        if self._empty_page is not None:
            self._empty_page.setMinimumWidth(content_width)
            self._empty_page.setMaximumWidth(content_width)
        detail_host.updateGeometry()
        detail_stack.updateGeometry()
        current_page = detail_stack.currentWidget()
        if current_page is not None:
            detail_stack.setMinimumHeight(0)
            detail_stack.setMaximumHeight(_WIDGET_MAX_SIZE)
            current_page.setMinimumHeight(0)
            current_page.setMaximumHeight(_WIDGET_MAX_SIZE)
            current_page.updateGeometry()
            current_page.adjustSize()
            current_height = max(1, current_page.sizeHint().height())
            detail_stack.setMinimumHeight(current_height)
            detail_stack.setMaximumHeight(current_height)
            current_page.setMinimumHeight(current_height)
            current_page.setMaximumHeight(current_height)

    def _reset_detail_scroll_position(self) -> None:
        if self._detail_scroll is None:
            return
        self._detail_scroll.verticalScrollBar().setValue(0)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._clamp_splitter_sizes)
        QTimer.singleShot(0, self._sync_detail_content_width)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._bind_screen_change_signal()
        QTimer.singleShot(0, self._fit_into_available_geometry)
        QTimer.singleShot(0, self._clamp_splitter_sizes)
        QTimer.singleShot(0, self._sync_detail_content_width)

    def _bind_screen_change_signal(self) -> None:
        if self._screen_change_bound:
            return
        window_handle = self.windowHandle()
        if window_handle is None:
            return
        try:
            window_handle.screenChanged.connect(lambda _screen: self._fit_into_available_geometry())
            self._screen_change_bound = True
        except Exception:
            self._screen_change_bound = False

    def _resolve_target_screen(self):
        window_handle = self.windowHandle()
        if window_handle is not None and window_handle.screen() is not None:
            return window_handle.screen()

        parent_widget = self.parentWidget()
        if parent_widget is not None:
            parent_window = parent_widget.window()
            parent_screen = parent_window.screen() if parent_window is not None else None
            if parent_screen is not None:
                return parent_screen

        return self.screen() or QGuiApplication.primaryScreen()

    def _fit_into_available_geometry(self) -> None:
        screen = self._resolve_target_screen()
        if screen is None:
            return

        available = screen.availableGeometry()
        if available.width() <= 0 or available.height() <= 0:
            return

        frame_margin_width = 32
        frame_margin_height = 40
        max_width = max(self._MIN_DIALOG_SIZE.width(), available.width() - frame_margin_width)
        max_height = max(self._MIN_DIALOG_SIZE.height(), available.height() - frame_margin_height)

        target_width = min(self._PREFERRED_DIALOG_SIZE.width(), max_width)
        target_height = min(self._PREFERRED_DIALOG_SIZE.height(), max_height)

        self.setMinimumSize(
            min(self._MIN_DIALOG_SIZE.width(), target_width),
            min(self._MIN_DIALOG_SIZE.height(), target_height),
        )
        self.setMaximumSize(max_width, max_height)

        resized_width = min(max(self.width(), self.minimumWidth()), max_width)
        resized_height = min(max(self.height(), self.minimumHeight()), max_height)
        if resized_width != self.width() or resized_height != self.height():
            self.resize(resized_width, resized_height)

        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        top_left = frame.topLeft()
        top_left.setX(
            max(available.left(), min(top_left.x(), available.right() - frame.width() + 1))
        )
        top_left.setY(
            max(available.top(), min(top_left.y(), available.bottom() - frame.height() + 1))
        )
        self.move(top_left)

    def _visible_indices_for_mode(self) -> List[int]:
        return list(range(len(self.entries)))

    def _build_tree_question_widget(self, idx: int, parent: QWidget) -> QWidget:
        info = self._get_entry_info(idx)
        entry = self.entries[idx]
        qnum = resolve_display_question_num(info, idx + 1) or idx + 1
        title = str(info.title or "").strip() or "未命名题目"

        row = QWidget(parent)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        number_label = BodyLabel(f"{qnum}.", row)
        number_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        row_layout.addWidget(number_label, 0, Qt.AlignmentFlag.AlignLeft)

        type_badge = self._make_badge(_get_entry_type_label(entry), "#0f6cbd", "#63b3ff", row)
        row_layout.addWidget(type_badge, 0, Qt.AlignmentFlag.AlignLeft)

        title_label = BodyLabel(_shorten_text(title, 12), row)
        title_label.setStyleSheet("font-size: 13px;")
        row_layout.addWidget(title_label, 1)
        return row

    def _build_tree_relation_widget(self, relation: Any, parent: QWidget) -> QWidget:
        row = QWidget(parent)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        if str(getattr(relation, "kind", "") or "").strip().lower() == "jump":
            badge = self._make_badge("跳题", "#b45309", "#fbbf24", row)
            row_layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignLeft)

        label = BodyLabel(_shorten_text(str(getattr(relation, "label", "") or ""), 24), row)
        label.setStyleSheet("font-size: 12px;")
        row_layout.addWidget(label, 1)
        return row

    def _populate_tree(self) -> None:
        if self._tree_widget is None:
            return
        self._tree_widget.clear()
        self._visible_indices = self._visible_indices_for_mode()

        page_map = self._logic_tree_state.page_map
        for page_num in sorted(page_map):
            page_indices = [idx for idx in page_map[page_num] if idx in self._visible_indices]
            if not page_indices:
                continue
            page_item = QTreeWidgetItem([f"第 {page_num} 页"])
            page_item.setFlags(page_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self._tree_widget.addTopLevelItem(page_item)

            for idx in page_indices:
                item = QTreeWidgetItem([""])
                item.setSizeHint(0, QSize(0, 34))
                item.setData(0, _TREE_INDEX_ROLE, idx)
                page_item.addChild(item)
                self._tree_widget.setItemWidget(item, 0, self._build_tree_question_widget(idx, self._tree_widget))

                if self._current_view_mode == _VIEW_LOGIC and not self._logic_tree_state.has_unknown_logic:
                    for relation in self._logic_tree_state.relations.get(idx, []):
                        relation_item = QTreeWidgetItem([""])
                        relation_item.setSizeHint(0, QSize(0, 30))
                        relation_item.setData(0, _TREE_INDEX_ROLE, idx)
                        relation_item.setData(
                            0,
                            _TREE_RELATION_TARGET_ROLE,
                            relation.target_index if relation.selectable else None,
                        )
                        item.addChild(relation_item)
                        self._tree_widget.setItemWidget(
                            relation_item,
                            0,
                            self._build_tree_relation_widget(relation, self._tree_widget),
                        )
            page_item.setExpanded(True)

    def _show_empty_state(self) -> None:
        if self._detail_stack is None:
            return
        if self._empty_page is None:
            page = QWidget(self._detail_stack)
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            empty = BodyLabel("当前无题目需要配置", page)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("font-size: 14px; padding: 40px;")
            _apply_label_color(empty, "#888888", "#bfbfbf")
            page_layout.addWidget(empty)
            self._detail_stack.addWidget(page)
            self._empty_page = page
        self._detail_stack.setCurrentWidget(self._empty_page)
        if self._prev_button is not None:
            self._prev_button.setEnabled(False)
        if self._next_button is not None:
            self._next_button.setEnabled(False)

    def _navigate_to_question(self, question_idx: int, animate: bool = False) -> None:
        _ = animate
        self._select_question(question_idx)

    def _select_question(self, idx: int) -> None:
        if idx not in self._visible_indices:
            return
        self._current_question_idx = idx
        self._render_current_question()
        self._sync_tree_selection()
        self._update_nav_buttons()

    def _render_current_question(self) -> None:
        if self._detail_stack is None:
            return
        if not (0 <= self._current_question_idx < len(self.entries)):
            return
        page = self._question_cards.get(self._current_question_idx)
        if page is None:
            page = QWidget(self._detail_stack)
            page.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(0)

            card = self._build_entry_card(
                self._current_question_idx,
                self.entries[self._current_question_idx],
                page,
            )
            self._entry_card_widgets[self._current_question_idx] = card
            page_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignTop)
            page_layout.addStretch(1)
            self._question_cards[self._current_question_idx] = page
            self._detail_stack.addWidget(page)
        self._detail_stack.setCurrentWidget(page)
        self._sync_detail_content_width()
        QTimer.singleShot(0, self._sync_detail_content_width)
        self._reset_detail_scroll_position()
        QTimer.singleShot(0, self._reset_detail_scroll_position)

    def _sync_tree_selection(self) -> None:
        if self._tree_widget is None:
            return
        iterator = self._iter_tree_items()
        for item in iterator:
            item_idx = item.data(0, _TREE_INDEX_ROLE)
            if item_idx == self._current_question_idx:
                self._tree_widget.setCurrentItem(item)
                return

    def _iter_tree_items(self) -> List[QTreeWidgetItem]:
        if self._tree_widget is None:
            return []
        items: List[QTreeWidgetItem] = []
        for i in range(self._tree_widget.topLevelItemCount()):
            top_item = self._tree_widget.topLevelItem(i)
            if top_item is None:
                continue
            items.extend(self._collect_tree_children(top_item))
        return items

    def _collect_tree_children(self, item: QTreeWidgetItem) -> List[QTreeWidgetItem]:
        items = [item]
        for i in range(item.childCount()):
            child = item.child(i)
            if child is not None:
                items.extend(self._collect_tree_children(child))
        return items

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        target_idx = item.data(0, _TREE_RELATION_TARGET_ROLE)
        if isinstance(target_idx, int) and target_idx in self._visible_indices:
            self._select_question(target_idx)
            return
        question_idx = item.data(0, _TREE_INDEX_ROLE)
        if isinstance(question_idx, int):
            self._select_question(question_idx)

    def _update_nav_buttons(self) -> None:
        if self._prev_button is None or self._next_button is None:
            return
        if not self._visible_indices:
            self._prev_button.setEnabled(False)
            self._next_button.setEnabled(False)
            return
        current_pos = self._visible_indices.index(self._current_question_idx)
        self._prev_button.setEnabled(current_pos > 0)
        self._next_button.setEnabled(current_pos < len(self._visible_indices) - 1)

    def _go_prev(self) -> None:
        if self._current_question_idx not in self._visible_indices:
            return
        current_pos = self._visible_indices.index(self._current_question_idx)
        if current_pos > 0:
            self._select_question(self._visible_indices[current_pos - 1])

    def _go_next(self) -> None:
        if self._current_question_idx not in self._visible_indices:
            return
        current_pos = self._visible_indices.index(self._current_question_idx)
        if current_pos < len(self._visible_indices) - 1:
            self._select_question(self._visible_indices[current_pos + 1])

    def _handle_search(self, keyword: str) -> None:
        self._handle_question_search(keyword)

    def reject(self) -> None:
        self._restore_entries()
        super().reject()

    def get_results(self) -> Dict[int, Any]:
        return wizard_result_builder.get_results(self)

    def get_text_results(self) -> Dict[int, List[str]]:
        return wizard_result_builder.get_text_results(self)

    def get_location_results(self) -> Dict[int, List[str]]:
        return wizard_result_builder.get_location_results(self)

    def get_option_fill_results(self) -> Dict[int, List[Optional[str]]]:
        return wizard_result_builder.get_option_fill_results(self)

    def get_text_random_modes(self) -> Dict[int, str]:
        return wizard_result_builder.get_text_random_modes(self)

    def get_text_random_int_ranges(self) -> Dict[int, List[int]]:
        return wizard_result_builder.get_text_random_int_ranges(self)

    def get_multi_text_blank_modes(self) -> Dict[int, List[str]]:
        return wizard_result_builder.get_multi_text_blank_modes(self)

    def get_multi_text_blank_int_ranges(self) -> Dict[int, List[List[int]]]:
        return wizard_result_builder.get_multi_text_blank_int_ranges(self)

    def get_multi_text_blank_ai_flags(self) -> Dict[int, List[bool]]:
        return wizard_result_builder.get_multi_text_blank_ai_flags(self)

    def get_ai_flags(self) -> Dict[int, bool]:
        return wizard_result_builder.get_ai_flags(self)

    def get_attached_select_results(self) -> Dict[int, List[Dict[str, Any]]]:
        return wizard_result_builder.get_attached_select_results(self)

    def get_bias_presets(self) -> Dict[int, Any]:
        return wizard_result_builder.get_bias_presets(self)

    def get_dimensions(self) -> Dict[int, Optional[str]]:
        return wizard_result_builder.get_dimensions(self)

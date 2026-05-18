"""配置向导弹窗。"""

import copy
from typing import Any, Dict, List, Optional, Tuple, cast

from PySide6.QtCore import QTimer, Qt, QSize
from PySide6.QtGui import QGuiApplication, QShowEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QStackedWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    LineEdit,
    Pivot,
    PrimaryPushButton,
    PushButton,
    RadioButton,
    ScrollArea,
    SearchLineEdit,
    SwitchButton,
    TreeWidget,
)

from software.app.config import DEFAULT_FILL_TEXT
from software.core.questions.config import QuestionEntry
from software.core.questions.utils import (
    OPTION_FILL_AI_TOKEN,
    build_random_int_token,
    serialize_random_int_range,
)
from software.providers.contracts import SurveyQuestionMeta
from software.ui.widgets.no_wheel import NoWheelSlider

from .utils import (
    _apply_label_color,
    _shorten_text,
    build_entry_info_list,
    resolve_display_question_num,
)
from .wizard_cards import WizardCardsMixin
from .wizard_logic_tree import build_logic_tree_state
from .wizard_sections import (
    WizardSectionsMixin,
    _TEXT_RANDOM_ID_CARD_TOKEN,
    _TEXT_RANDOM_MOBILE_TOKEN,
    _TEXT_RANDOM_NAME_TOKEN,
    _TEXT_RANDOM_NONE,
)

TextEditsValue = List[LineEdit] | List[List[LineEdit]]

_VIEW_LOGIC = "logic"
_VIEW_SEQUENTIAL = "sequential"
_TREE_INDEX_ROLE = int(Qt.ItemDataRole.UserRole) + 101
_TREE_RELATION_TARGET_ROLE = _TREE_INDEX_ROLE + 1


class QuestionWizardDialog(
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
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
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

        self.slider_map: Dict[int, List[NoWheelSlider]] = {}
        self.matrix_row_slider_map: Dict[int, List[List[NoWheelSlider]]] = {}
        self.text_edit_map: Dict[int, TextEditsValue] = {}
        self.ai_check_map: Dict[int, SwitchButton] = {}
        self.ai_label_map: Dict[int, BodyLabel] = {}
        self.text_container_map: Dict[int, QWidget] = {}
        self.text_add_btn_map: Dict[int, PushButton] = {}
        self.text_random_mode_map: Dict[int, str] = {}
        self.text_random_list_radio_map: Dict[int, RadioButton] = {}
        self.text_random_name_check_map: Dict[int, RadioButton] = {}
        self.text_random_mobile_check_map: Dict[int, RadioButton] = {}
        self.text_random_id_card_check_map: Dict[int, RadioButton] = {}
        self.text_random_integer_check_map: Dict[int, RadioButton] = {}
        self.text_random_int_min_edit_map: Dict[int, LineEdit] = {}
        self.text_random_int_max_edit_map: Dict[int, LineEdit] = {}
        self.text_random_group_map: Dict[int, QButtonGroup] = {}
        self.multi_text_blank_integer_range_edits: Dict[int, List[Tuple[LineEdit, LineEdit]]] = {}
        self.bias_preset_map: Dict[int, Any] = {}
        self.attached_select_slider_map: Dict[int, List[Dict[str, Any]]] = {}
        self.option_fill_edit_map: Dict[int, Dict[int, LineEdit]] = {}
        self.option_fill_state_map: Dict[int, Dict[int, Dict[str, Any]]] = {}
        self._entry_snapshots: List[QuestionEntry] = [copy.deepcopy(entry) for entry in entries]
        self._question_cards: Dict[int, CardWidget] = {}
        self._visible_indices: List[int] = list(range(len(self.entries)))
        self._search_match_indices: List[int] = []
        self._current_question_idx = self._visible_indices[0] if self._visible_indices else 0
        self._current_view_mode = (
            _VIEW_SEQUENTIAL if self._logic_tree_state.has_unknown_logic else _VIEW_LOGIC
        )
        self._screen_change_bound = False
        self._validation_error_dialog = None

        self._search_edit: Optional[SearchLineEdit] = None
        self._search_status_label: Optional[BodyLabel] = None
        self._view_pivot: Optional[Pivot] = None
        self._tree_widget: Optional[TreeWidget] = None
        self._detail_scroll: Optional[ScrollArea] = None
        self._detail_host: Optional[QWidget] = None
        self._detail_layout: Optional[QVBoxLayout] = None
        self._detail_stack: Optional[QStackedWidget] = None
        self._empty_page: Optional[QWidget] = None
        self._prev_button: Optional[PushButton] = None
        self._next_button: Optional[PushButton] = None

        self._build_ui()
        self._populate_tree()
        if self._visible_indices:
            self._select_question(self._visible_indices[0])
        else:
            self._show_empty_state()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)

        search_edit = SearchLineEdit(self)
        search_edit.setPlaceholderText("搜索题号、题干、选项、逻辑摘要")
        search_edit.setFixedWidth(360)
        search_edit.searchSignal.connect(self._handle_search)
        search_edit.textChanged.connect(self._on_search_text_changed)
        search_edit.returnPressed.connect(self._handle_search_return_pressed)
        self._search_edit = search_edit
        top_row.addWidget(search_edit)

        top_row.addStretch(1)

        pivot = Pivot(self)
        pivot.addItem(_VIEW_LOGIC, "逻辑视图")
        pivot.addItem(_VIEW_SEQUENTIAL, "顺序视图")
        if self._logic_tree_state.has_unknown_logic:
            pivot.setVisible(False)
        else:
            pivot.setCurrentItem(self._current_view_mode)
            pivot.currentItemChanged.connect(self._on_view_mode_changed)
        self._view_pivot = pivot
        top_row.addWidget(pivot, 0, Qt.AlignmentFlag.AlignRight)

        layout.addLayout(top_row)

        status_label = BodyLabel("", self)
        status_label.setStyleSheet("font-size: 12px;")
        _apply_label_color(status_label, "#666666", "#bfbfbf")
        self._search_status_label = status_label
        layout.addWidget(status_label)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(16)
        layout.addLayout(content_row, 1)

        left_card = CardWidget(self)
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)
        tree = TreeWidget(left_card)
        tree.setHeaderHidden(True)
        tree.itemClicked.connect(self._on_tree_item_clicked)
        tree.itemActivated.connect(self._on_tree_item_clicked)
        self._tree_widget = tree
        left_layout.addWidget(tree, 1)
        content_row.addWidget(left_card, 0)
        left_card.setFixedWidth(320)

        right_card = CardWidget(self)
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(0)
        detail_scroll = ScrollArea(right_card)
        detail_scroll.setWidgetResizable(True)
        detail_scroll.enableTransparentBackground()
        detail_host = QWidget(right_card)
        detail_layout = QVBoxLayout(detail_host)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(0)
        detail_stack = QStackedWidget(detail_host)
        detail_layout.addWidget(detail_stack, 1)
        detail_scroll.setWidget(detail_host)
        self._detail_scroll = detail_scroll
        self._detail_host = detail_host
        self._detail_layout = detail_layout
        self._detail_stack = detail_stack
        right_layout.addWidget(detail_scroll, 1)
        content_row.addWidget(right_card, 1)

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

        self._set_search_status("输入关键词后回车跳转")

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._bind_screen_change_signal()
        QTimer.singleShot(0, self._fit_into_available_geometry)

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

    def _set_search_status(
        self,
        text: str,
        light: str = "#666666",
        dark: str = "#bfbfbf",
    ) -> None:
        if self._search_status_label is None:
            return
        self._search_status_label.setText(text)
        _apply_label_color(self._search_status_label, light, dark)

    def _visible_indices_for_mode(self) -> List[int]:
        return list(range(len(self.entries)))

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
                info = self._get_entry_info(idx)
                qnum = resolve_display_question_num(info, idx + 1) or idx + 1
                title = str(info.title or "").strip() or "未命名题目"
                item = QTreeWidgetItem([f"第{qnum}题  {_shorten_text(title, 20)}"])
                item.setData(0, _TREE_INDEX_ROLE, idx)
                page_item.addChild(item)

                if self._current_view_mode == _VIEW_LOGIC and not self._logic_tree_state.has_unknown_logic:
                    for relation in self._logic_tree_state.relations.get(idx, []):
                        relation_item = QTreeWidgetItem([relation.label])
                        relation_item.setData(0, _TREE_INDEX_ROLE, idx)
                        relation_item.setData(
                            0,
                            _TREE_RELATION_TARGET_ROLE,
                            relation.target_index if relation.selectable else None,
                        )
                        item.addChild(relation_item)
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
        card = self._question_cards.get(self._current_question_idx)
        if card is None:
            card = self._build_entry_card(
                self._current_question_idx,
                self.entries[self._current_question_idx],
                self._detail_stack,
            )
            self._question_cards[self._current_question_idx] = card
            self._detail_stack.addWidget(card)
        self._detail_stack.setCurrentWidget(card)
        if self._detail_scroll is not None:
            self._detail_scroll.verticalScrollBar().setValue(0)

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

    def _on_view_mode_changed(self, route_key: str) -> None:
        normalized = str(route_key or "").strip()
        if normalized not in {_VIEW_LOGIC, _VIEW_SEQUENTIAL}:
            return
        self._current_view_mode = normalized
        self._populate_tree()
        if self._visible_indices:
            target = self._current_question_idx
            if target not in self._visible_indices:
                target = self._visible_indices[0]
            self._select_question(target)

    def _searchable_text(self, idx: int) -> str:
        return str(self._logic_tree_state.search_text.get(idx) or "")

    @staticmethod
    def _normalize_search_text(text: str) -> str:
        return " ".join(str(text or "").strip().lower().split())

    def _match_indices(self, keyword: str) -> List[int]:
        normalized = self._normalize_search_text(keyword)
        if not normalized:
            return []
        return [
            idx
            for idx in self._visible_indices
            if normalized in self._normalize_search_text(self._searchable_text(idx))
        ]

    def _on_search_text_changed(self, text: str) -> None:
        raw_text = str(text or "").strip()
        if not raw_text:
            self._search_match_indices = []
            self._set_search_status("输入关键词后回车跳转")
            return
        matches = self._match_indices(raw_text)
        self._search_match_indices = matches
        if matches:
            self._set_search_status(f"匹配 {len(matches)} 题，回车定位下一项")
        else:
            self._set_search_status(f"未找到“{raw_text}”", "#c42b1c", "#ff99a4")

    def _handle_search_return_pressed(self) -> None:
        if self._search_edit is None:
            return
        self._handle_search(self._search_edit.text())

    def _handle_search(self, keyword: str) -> None:
        raw_text = str(keyword or "").strip()
        if not raw_text:
            self._search_match_indices = []
            self._set_search_status("输入关键词后回车跳转")
            return
        matches = self._match_indices(raw_text)
        self._search_match_indices = matches
        if not matches:
            self._set_search_status(f"未找到“{raw_text}”", "#c42b1c", "#ff99a4")
            return
        if self._current_question_idx in matches:
            current_pos = matches.index(self._current_question_idx)
            target_idx = matches[(current_pos + 1) % len(matches)]
        else:
            target_idx = matches[0]
        self._select_question(target_idx)
        self._set_search_status(
            f"匹配 {len(matches)} 题，当前定位到{self._format_question_label(target_idx)}"
        )

    def reject(self) -> None:
        self._restore_entries()
        super().reject()

    def get_results(self) -> Dict[int, Any]:
        result: Dict[int, Any] = {}
        for idx, sliders in self.slider_map.items():
            weights = [max(0, s.value()) for s in sliders]
            if weights and not any(weight > 0 for weight in weights):
                raise ValueError(f"{self._format_question_label(idx)}的选项配比不能全为0。")
            result[idx] = weights

        for idx, row_sliders in self.matrix_row_slider_map.items():
            row_weights: List[List[int]] = []
            for row_idx, row in enumerate(row_sliders):
                weights = [max(0, s.value()) for s in row]
                if weights and not any(weight > 0 for weight in weights):
                    question_label = self._format_question_label(idx)
                    raise ValueError(f"{question_label}的第{row_idx + 1}行配比不能全为0。")
                row_weights.append(weights)
            result[idx] = row_weights
        return result

    def get_text_results(self) -> Dict[int, List[str]]:
        from software.core.questions.text_shared import MULTI_TEXT_DELIMITER

        result: Dict[int, List[str]] = {}
        for idx, edits in self.text_edit_map.items():
            if edits and isinstance(edits[0], list):
                texts = []
                matrix_edits = cast(List[List[LineEdit]], edits)
                for row_edits in matrix_edits:
                    row_values = [edit.text().strip() for edit in row_edits]
                    merged = MULTI_TEXT_DELIMITER.join(row_values)
                    if merged:
                        texts.append(merged)
            else:
                flat_edits = cast(List[LineEdit], edits)
                texts = [e.text().strip() for e in flat_edits if e.text().strip()]
            if not texts:
                texts = [DEFAULT_FILL_TEXT]
            result[idx] = texts
        return result

    def get_option_fill_results(self) -> Dict[int, List[Optional[str]]]:
        result: Dict[int, List[Optional[str]]] = {}
        for idx, state_map in self.option_fill_state_map.items():
            if not state_map:
                continue
            info = self._get_entry_info(idx)
            option_count = int(info.get("options") or 0)
            max_index = max(state_map.keys()) if state_map else -1
            normalized_count = max(option_count, max_index + 1, 0)
            values: List[Optional[str]] = [None] * normalized_count
            for option_index, state in state_map.items():
                ai_cb = state.get("ai_cb")
                if ai_cb is not None and ai_cb.isChecked():
                    text: Optional[str] = OPTION_FILL_AI_TOKEN
                else:
                    group = state.get("group")
                    checked_id = group.checkedId() if group is not None else 0
                    if checked_id == 1:
                        text = _TEXT_RANDOM_NAME_TOKEN
                    elif checked_id == 2:
                        text = _TEXT_RANDOM_MOBILE_TOKEN
                    elif checked_id == 3:
                        text = _TEXT_RANDOM_ID_CARD_TOKEN
                    elif checked_id == 4:
                        min_edit = state.get("min_edit")
                        max_edit = state.get("max_edit")
                        text = build_random_int_token(
                            min_edit.text().strip() if min_edit is not None else "",
                            max_edit.text().strip() if max_edit is not None else "",
                        )
                    else:
                        edit = state.get("edit")
                        raw_value = edit.text().strip() if edit is not None else ""
                        text = raw_value or None
                if 0 <= option_index < normalized_count:
                    values[option_index] = text
            result[idx] = values
        return result

    def get_text_random_modes(self) -> Dict[int, str]:
        return dict(self.text_random_mode_map)

    def get_text_random_int_ranges(self) -> Dict[int, List[int]]:
        result: Dict[int, List[int]] = {}
        for idx, min_edit in self.text_random_int_min_edit_map.items():
            max_edit = self.text_random_int_max_edit_map.get(idx)
            raw_range = [
                min_edit.text().strip(),
                max_edit.text().strip() if max_edit else "",
            ]
            result[idx] = serialize_random_int_range(raw_range)
        return result

    def get_multi_text_blank_modes(self) -> Dict[int, List[str]]:
        from .wizard_sections import (
            _TEXT_RANDOM_ID_CARD,
            _TEXT_RANDOM_INTEGER,
            _TEXT_RANDOM_MOBILE,
            _TEXT_RANDOM_NAME,
            _TEXT_RANDOM_NONE,
        )

        result: Dict[int, List[str]] = {}
        if not hasattr(self, "multi_text_blank_radio_groups"):
            return result
        for idx, groups in self.multi_text_blank_radio_groups.items():
            modes: List[str] = []
            for group in groups:
                checked_id = group.checkedId()
                if checked_id == 1:
                    modes.append(_TEXT_RANDOM_NAME)
                elif checked_id == 2:
                    modes.append(_TEXT_RANDOM_MOBILE)
                elif checked_id == 3:
                    modes.append(_TEXT_RANDOM_ID_CARD)
                elif checked_id == 4:
                    modes.append(_TEXT_RANDOM_INTEGER)
                else:
                    modes.append(_TEXT_RANDOM_NONE)
            result[idx] = modes
        return result

    def get_multi_text_blank_int_ranges(self) -> Dict[int, List[List[int]]]:
        result: Dict[int, List[List[int]]] = {}
        for idx, edit_pairs in self.multi_text_blank_integer_range_edits.items():
            ranges: List[List[int]] = []
            for min_edit, max_edit in edit_pairs:
                ranges.append(
                    serialize_random_int_range([min_edit.text().strip(), max_edit.text().strip()])
                )
            result[idx] = ranges
        return result

    def get_multi_text_blank_ai_flags(self) -> Dict[int, List[bool]]:
        result: Dict[int, List[bool]] = {}
        if not hasattr(self, "multi_text_blank_ai_checkboxes"):
            return result
        for idx, checkboxes in self.multi_text_blank_ai_checkboxes.items():
            result[idx] = [cb.isChecked() for cb in checkboxes]
        return result

    def get_ai_flags(self) -> Dict[int, bool]:
        result: Dict[int, bool] = {}
        for idx, cb in self.ai_check_map.items():
            random_mode = self.text_random_mode_map.get(idx, _TEXT_RANDOM_NONE)
            result[idx] = False if random_mode != _TEXT_RANDOM_NONE else cb.isChecked()
        return result

    def get_attached_select_results(self) -> Dict[int, List[Dict[str, Any]]]:
        result: Dict[int, List[Dict[str, Any]]] = {}
        for idx, config_items in self.attached_select_slider_map.items():
            serialized_items: List[Dict[str, Any]] = []
            for item in config_items:
                sliders = item.get("sliders") or []
                weights = [max(0, slider.value()) for slider in sliders]
                if weights and not any(weight > 0 for weight in weights):
                    option_text = str(item.get("option_text") or "").strip()
                    if not option_text:
                        option_text = f"第{int(item.get('option_index', 0)) + 1}项"
                    raise ValueError(
                        f"{self._format_question_label(idx)}里“{option_text}”对应的嵌入式下拉配比不能全为0。"
                    )
                serialized_items.append(
                    {
                        "option_index": int(item.get("option_index", 0)),
                        "option_text": str(item.get("option_text") or "").strip(),
                        "select_options": list(item.get("select_options") or []),
                        "weights": weights,
                    }
                )
            result[idx] = serialized_items
        return result

    def get_bias_presets(self) -> Dict[int, Any]:
        result: Dict[int, Any] = {}
        for idx, seg in self.bias_preset_map.items():
            if isinstance(seg, list):
                result[idx] = [str(s.currentRouteKey() or "custom") for s in seg]
            else:
                result[idx] = str(seg.currentRouteKey() or "custom")
        return result

    def get_dimensions(self) -> Dict[int, Optional[str]]:
        result: Dict[int, Optional[str]] = {}
        for idx, entry in enumerate(self.entries):
            try:
                raw = str(getattr(entry, "dimension", "") or "").strip()
            except Exception:
                raw = ""
            result[idx] = raw or None
        return result

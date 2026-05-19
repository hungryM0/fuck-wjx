"""题目配置向导搜索辅助。"""

import html
from typing import TYPE_CHECKING, Any, List, Tuple, cast

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    Qt,
    QTimer,
)
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListWidgetItem,
    QWidget,
)
from qfluentwidgets import ListWidget, SearchLineEdit, isDarkTheme
from shiboken6 import isValid

from software.providers.contracts import SurveyQuestionMeta

from .constants import _get_entry_type_label
from .wizard_search_popup import (
    QuestionSearchCompleterDelegate,
    SEARCH_RESULT_DETAIL_ROLE,
    SEARCH_RESULT_INDEX_ROLE,
    SEARCH_RESULT_TITLE_ROLE,
    apply_search_popup_style,
)
from .utils import (
    _apply_label_color,
    _shorten_text,
    resolve_display_question_num,
)


class WizardSearchMixin:
    if TYPE_CHECKING:
        entries: List[Any]
        _question_search_cache: dict[int, str]
        _search_match_indices: List[int]
        _last_search_keyword: str
        _last_search_match_cursor: int
        _search_status_label: Any
        _search_popup: Any
        _search_edit: Any
        _logic_tree_state: Any

        def _get_entry_info(self, idx: int) -> SurveyQuestionMeta: ...
        def _navigate_to_question(self, question_idx: int, animate: bool) -> None: ...
        def isVisible(self) -> bool: ...

    @staticmethod
    def _normalize_search_text(text: Any) -> str:
        try:
            raw = str(text or "")
        except Exception:
            return ""
        return "".join(raw.lower().split())

    @staticmethod
    def _build_search_highlight_html(text: str, keyword: str) -> str:
        raw_text = str(text or "")
        raw_keyword = str(keyword or "").strip()
        if not raw_text:
            return ""
        if not raw_keyword:
            return html.escape(raw_text)

        lower_text = raw_text.lower()
        lower_keyword = raw_keyword.lower()
        pieces: List[str] = []
        cursor = 0
        if isDarkTheme():
            highlight_style = (
                "background-color: rgba(99, 179, 255, 0.30); "
                "color: #ffffff; border-radius: 3px; font-weight: 600;"
            )
        else:
            highlight_style = (
                "background-color: rgba(15, 108, 189, 0.16); "
                "color: #0f6cbd; border-radius: 3px; font-weight: 600;"
            )

        while True:
            start = lower_text.find(lower_keyword, cursor)
            if start < 0:
                pieces.append(html.escape(raw_text[cursor:]))
                break
            if start > cursor:
                pieces.append(html.escape(raw_text[cursor:start]))
            matched = raw_text[start : start + len(raw_keyword)]
            escaped = html.escape(matched)
            pieces.append(f'<span style="{highlight_style}">{escaped}</span>')
            cursor = start + len(raw_keyword)
        return "".join(pieces)

    def _iter_searchable_sections(self, idx: int) -> List[Tuple[str, str]]:
        info = self._get_entry_info(idx)
        entry = self.entries[idx] if 0 <= idx < len(self.entries) else None
        sections: List[Tuple[str, str]] = []

        title_text = str(info.get("title") or getattr(entry, "question_title", "") or "").strip()
        if title_text:
            sections.append(("题干", title_text))

        for key, label in (("option_texts", "选项"), ("row_texts", "矩阵行")):
            raw_values = info.get(key)
            if isinstance(raw_values, list):
                for value in raw_values:
                    text = str(value or "").strip()
                    if text:
                        sections.append((label, text))

        raw_attached_configs = (
            getattr(entry, "attached_option_selects", None) if entry is not None else None
        )
        if isinstance(raw_attached_configs, list):
            for item in raw_attached_configs:
                if not isinstance(item, dict):
                    continue
                option_text = str(item.get("option_text") or "").strip()
                if option_text:
                    sections.append(("嵌入式下拉", option_text))
                select_options = item.get("select_options")
                if isinstance(select_options, list):
                    for option in select_options:
                        text = str(option or "").strip()
                        if text:
                            sections.append(("嵌入式下拉", text))
        logic_state = getattr(self, "_logic_tree_state", None)
        for attr, label in (("inbound_summary", "显示逻辑"), ("outbound_summary", "跳转逻辑")):
            values = getattr(logic_state, attr, None)
            if not isinstance(values, dict):
                continue
            text = str(values.get(idx) or "").strip()
            if text:
                sections.append((label, text))
        return sections

    def _build_question_search_text(self, idx: int) -> str:
        cached = self._question_search_cache.get(idx)
        if cached is not None:
            return cached

        info = self._get_entry_info(idx)
        chunks: List[str] = [str(resolve_display_question_num(info, idx + 1) or idx + 1)]
        for _label, text in self._iter_searchable_sections(idx):
            chunks.append(text)

        normalized = self._normalize_search_text(" ".join(chunks))
        self._question_search_cache[idx] = normalized
        return normalized

    def _find_matching_question_indices(self, keyword: str) -> List[int]:
        normalized_keyword = self._normalize_search_text(keyword)
        if not normalized_keyword:
            return []

        return [
            idx
            for idx in range(len(self.entries))
            if normalized_keyword in self._build_question_search_text(idx)
        ]

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

    @staticmethod
    def _is_alive_widget(widget: Any) -> bool:
        if widget is None:
            return False
        try:
            return bool(isValid(widget))
        except Exception:
            return False

    def _configure_search_popup(self, search_edit: SearchLineEdit) -> None:
        popup = ListWidget(cast(QWidget, self))
        popup.setWindowFlag(Qt.WindowType.ToolTip, True)
        popup.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        popup.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        popup.setMouseTracking(True)
        popup.setAlternatingRowColors(False)
        popup.setUniformItemSizes(False)
        popup.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        popup.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        popup.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        popup.setItemDelegate(QuestionSearchCompleterDelegate(popup))
        popup.itemClicked.connect(self._activate_search_popup_item)
        popup.itemActivated.connect(self._activate_search_popup_item)
        apply_search_popup_style(popup)
        self._search_popup = popup
        search_edit.installEventFilter(cast(QObject, self))
        popup.installEventFilter(cast(QObject, self))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        search_edit = getattr(self, "_search_edit", None)
        search_popup = getattr(self, "_search_popup", None)
        popup_alive = search_popup is not None and self._is_alive_widget(search_popup)

        if watched is search_edit and event.type() == QEvent.Type.KeyPress:
            popup = search_popup if popup_alive else None
            if popup is not None and popup.isVisible():
                key = cast(QKeyEvent, event).key()
                if key == Qt.Key.Key_Down:
                    next_row = min(
                        popup.count() - 1,
                        max(0, popup.currentRow() + 1),
                    )
                    popup.setCurrentRow(next_row)
                    return True
                if key == Qt.Key.Key_Up:
                    next_row = max(0, popup.currentRow() - 1)
                    popup.setCurrentRow(next_row)
                    return True
                if key == Qt.Key.Key_Escape:
                    self._hide_search_popup()
                    return True

        if watched is search_edit and event.type() == QEvent.Type.FocusOut:
            QTimer.singleShot(0, self._hide_search_popup)

        if watched is search_popup and event.type() == QEvent.Type.KeyPress:
            key = cast(QKeyEvent, event).key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                current_item = search_popup.currentItem() if search_popup is not None else None
                if current_item is not None:
                    self._activate_search_popup_item(current_item)
                    return True
            if key == Qt.Key.Key_Escape:
                self._hide_search_popup()
                if search_edit is not None:
                    search_edit.setFocus()
                return True

        return cast(Any, super()).eventFilter(watched, event)

    def _build_search_result_item(self, idx: int, keyword: str) -> QListWidgetItem:
        info = self._get_entry_info(idx)
        entry = self.entries[idx] if 0 <= idx < len(self.entries) else None
        qnum = str(resolve_display_question_num(info, idx + 1) or idx + 1)
        type_text = _get_entry_type_label(entry) if entry is not None else "题目"
        title_text = str(info.get("title") or getattr(entry, "question_title", "") or "").strip()
        title_preview = _shorten_text(title_text or f"[{type_text}]", 48)
        title_line = f"第{qnum}题  [{type_text}] {title_preview}"

        normalized_keyword = self._normalize_search_text(keyword)
        detail_line = f"题号：第{qnum}题"
        for label, text in self._iter_searchable_sections(idx):
            if normalized_keyword and normalized_keyword in self._normalize_search_text(text):
                detail_line = f"{label}：{_shorten_text(text, 80)}"
                break

        item = QListWidgetItem(title_line)
        item.setData(SEARCH_RESULT_INDEX_ROLE, idx)
        item.setData(
            SEARCH_RESULT_TITLE_ROLE,
            self._build_search_highlight_html(title_line, keyword),
        )
        item.setData(
            SEARCH_RESULT_DETAIL_ROLE,
            self._build_search_highlight_html(detail_line, keyword),
        )
        return item

    def _hide_search_popup(self) -> None:
        popup = self._search_popup if self._is_alive_widget(self._search_popup) else None
        if popup is None:
            self._search_popup = None
            return
        popup.hide()

    def _refresh_search_popup(self, raw_keyword: str, matches: List[int]) -> None:
        if not self._is_alive_widget(self._search_popup):
            self._search_popup = None
            return
        if not self._is_alive_widget(self._search_edit):
            return

        popup = self._search_popup
        popup.clear()
        raw_keyword = str(raw_keyword or "").strip()
        if not raw_keyword or not matches:
            self._hide_search_popup()
            return

        visible_matches = matches[:30]
        for idx in visible_matches:
            popup.addItem(self._build_search_result_item(idx, raw_keyword))

        if not self.isVisible() or not self._search_edit.isVisible():
            self._hide_search_popup()
            return

        popup.setCurrentRow(-1)
        popup_width = max(520, self._search_edit.width())
        content_height = 0
        for row in range(popup.count()):
            content_height += max(44, popup.sizeHintForRow(row))
        popup_height = min(320, content_height + popup.frameWidth() * 2 + 4)
        popup.resize(popup_width, max(52, popup_height))
        search_pos = self._search_edit.mapToGlobal(QPoint(0, self._search_edit.height() + 4))
        offset_x = max(0, (self._search_edit.width() - popup_width) // 2)
        popup.move(search_pos.x() - offset_x, search_pos.y())
        popup.show()
        popup.raise_()

    def _jump_to_question_from_search(
        self,
        target_idx: int,
        matches: List[int],
        raw_keyword: str,
        match_cursor: int,
    ) -> None:
        self._search_match_indices = matches
        self._last_search_keyword = self._normalize_search_text(raw_keyword)
        self._last_search_match_cursor = match_cursor

        info = self._get_entry_info(target_idx)
        qnum = str(resolve_display_question_num(info, target_idx + 1) or target_idx + 1)
        status_text = (
            f"匹配 {len(matches)} 题，当前定位到第{qnum}题（{match_cursor + 1}/{len(matches)}）"
        )
        self._set_search_status(
            status_text,
            "#0f6cbd",
            "#63b3ff",
        )
        self._navigate_to_question(target_idx, animate=True)

    def _activate_search_popup_item(self, item: QListWidgetItem) -> None:
        if item is None:
            return
        target_idx = item.data(SEARCH_RESULT_INDEX_ROLE)
        try:
            normalized_idx = int(target_idx)
        except Exception:
            return

        raw_keyword = self._search_edit.text().strip() if self._search_edit is not None else ""
        matches = self._find_matching_question_indices(raw_keyword)
        if not matches or normalized_idx not in matches:
            matches = [normalized_idx]
        match_cursor = matches.index(normalized_idx) if normalized_idx in matches else 0

        self._hide_search_popup()
        self._jump_to_question_from_search(normalized_idx, matches, raw_keyword, match_cursor)

    def _handle_search_return_pressed(self) -> None:
        popup = self._search_popup if self._is_alive_widget(self._search_popup) else None
        if popup is not None and popup.isVisible():
            current_item = popup.currentItem()
            if current_item is not None:
                self._activate_search_popup_item(current_item)
                return
        if self._is_alive_widget(self._search_edit):
            self._handle_question_search(self._search_edit.text())
            return

    def _on_search_text_changed(self, text: str) -> None:
        raw_text = str(text or "").strip()
        normalized_text = self._normalize_search_text(raw_text)
        if not normalized_text:
            self._clear_question_search()
            return

        self._search_match_indices = []
        self._last_search_keyword = ""
        self._last_search_match_cursor = -1
        matches = self._find_matching_question_indices(raw_text)
        self._refresh_search_popup(raw_text, matches)
        if matches:
            shown_count = min(len(matches), 30)
            suffix = "，回车可直接跳到当前选中项" if shown_count > 0 else ""
            overflow = f"（下拉仅显示前 {shown_count} 条）" if len(matches) > shown_count else ""
            status_text = f"匹配 {len(matches)} 题{overflow}，点下拉结果跳转{suffix}"
            self._set_search_status(
                status_text,
                "#666666",
                "#bfbfbf",
            )
        else:
            self._set_search_status(f"未找到“{raw_text}”", "#c42b1c", "#ff99a4")

    def _clear_question_search(self) -> None:
        self._search_match_indices = []
        self._last_search_keyword = ""
        self._last_search_match_cursor = -1
        if self._is_alive_widget(self._search_popup):
            self._search_popup.clear()
        else:
            self._search_popup = None
        self._hide_search_popup()
        self._set_search_status("点下拉结果或回车即可跳转", "#666666", "#bfbfbf")

    def _handle_question_search(self, keyword: str) -> None:
        raw_keyword = str(keyword or "").strip()
        normalized_keyword = self._normalize_search_text(raw_keyword)
        if not normalized_keyword:
            self._clear_question_search()
            return

        matches = self._find_matching_question_indices(normalized_keyword)
        self._refresh_search_popup(raw_keyword, matches)
        if not matches:
            self._search_match_indices = []
            self._last_search_keyword = normalized_keyword
            self._last_search_match_cursor = -1
            self._set_search_status(f"未找到“{raw_keyword}”", "#c42b1c", "#ff99a4")
            return

        match_cursor = 0
        is_same_query = (
            normalized_keyword == self._last_search_keyword
            and matches == self._search_match_indices
        )
        if is_same_query and 0 <= self._last_search_match_cursor < len(matches):
            match_cursor = (self._last_search_match_cursor + 1) % len(matches)

        target_idx = matches[match_cursor]
        self._jump_to_question_from_search(target_idx, matches, raw_keyword, match_cursor)

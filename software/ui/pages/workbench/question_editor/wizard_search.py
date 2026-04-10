"""题目配置向导搜索辅助。"""
import html
from typing import TYPE_CHECKING, Any, List, Tuple, cast

from PySide6.QtCore import QObject, QPoint, QRectF, Qt, QModelIndex, QPersistentModelIndex, QSize
from PySide6.QtGui import QColor, QPainter, QTextDocument
from PySide6.QtWidgets import QApplication, QAbstractItemView, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget
from qfluentwidgets import SearchLineEdit, isDarkTheme

from .constants import _get_entry_type_label
from .utils import _apply_label_color, _shorten_text

def _color_with_alpha(color: QColor, alpha: int) -> QColor:
    copied = QColor(color)
    copied.setAlpha(max(0, min(255, int(alpha))))
    return copied
_SEARCH_RESULT_INDEX_ROLE = int(Qt.ItemDataRole.UserRole) + 1

_SEARCH_RESULT_TITLE_ROLE = _SEARCH_RESULT_INDEX_ROLE + 1

_SEARCH_RESULT_DETAIL_ROLE = _SEARCH_RESULT_INDEX_ROLE + 2


class QuestionSearchCompleterDelegate(QStyledItemDelegate):
    """搜索建议下拉项：展示题号/题干，并高亮命中的关键词。"""

    def _build_document(self, index: QModelIndex | QPersistentModelIndex, width: int, selected: bool) -> QTextDocument:
        title_html = str(index.data(_SEARCH_RESULT_TITLE_ROLE) or "")
        detail_html = str(index.data(_SEARCH_RESULT_DETAIL_ROLE) or "")
        if isDarkTheme():
            title_color = "#f5f5f5" if not selected else "#ffffff"
            detail_color = "#cfcfcf" if not selected else "#f2f2f2"
        else:
            title_color = "#1f1f1f" if not selected else "#ffffff"
            detail_color = "#5f5f5f" if not selected else "#edf5ff"

        document = QTextDocument(self)
        document.setDocumentMargin(0)
        document.setTextWidth(max(160, width - 24))
        document.setHtml(
            f"""
            <div style="font-size:13px; font-weight:600; color:{title_color};">{title_html}</div>
            <div style="margin-top:4px; font-size:12px; color:{detail_color};">{detail_html}</div>
            """
        )
        return document

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> None:
        option_copy = QStyleOptionViewItem(option)
        self.initStyleOption(option_copy, index)
        option_copy.text = ""

        style = option.widget.style() if option.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option_copy, painter, option.widget)

        text_rect = option.rect.adjusted(12, 8, -12, -8)
        document = self._build_document(index, text_rect.width(), bool(option.state & QStyle.StateFlag.State_Selected))

        painter.save()
        painter.translate(text_rect.topLeft())
        document.drawContents(painter, QRectF(0, 0, text_rect.width(), text_rect.height()))
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> QSize:
        width = option.rect.width() or 480
        document = self._build_document(index, width, False)
        return QSize(width, max(44, int(document.size().height()) + 16))

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

        def _get_entry_info(self, idx: int) -> dict: ...
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
            highlight_style = "background-color: rgba(99, 179, 255, 0.30); color: #ffffff; border-radius: 3px; font-weight: 600;"
        else:
            highlight_style = "background-color: rgba(15, 108, 189, 0.16); color: #0f6cbd; border-radius: 3px; font-weight: 600;"

        while True:
            start = lower_text.find(lower_keyword, cursor)
            if start < 0:
                pieces.append(html.escape(raw_text[cursor:]))
                break
            if start > cursor:
                pieces.append(html.escape(raw_text[cursor:start]))
            matched = raw_text[start:start + len(raw_keyword)]
            pieces.append(f'<span style="{highlight_style}">{html.escape(matched)}</span>')
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

        raw_attached_configs = getattr(entry, "attached_option_selects", None) if entry is not None else None
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
        return sections
    def _build_question_search_text(self, idx: int) -> str:
        cached = self._question_search_cache.get(idx)
        if cached is not None:
            return cached

        info = self._get_entry_info(idx)
        chunks: List[str] = [str(info.get("num") or idx + 1)]
        for _label, text in self._iter_searchable_sections(idx):
            chunks.append(text)

        normalized = self._normalize_search_text(" ".join(chunks))
        self._question_search_cache[idx] = normalized
        return normalized
    def _find_matching_question_indices(self, keyword: str) -> List[int]:
        normalized_keyword = self._normalize_search_text(keyword)
        if not normalized_keyword:
            return []

        matches: List[int] = []
        for idx in range(len(self.entries)):
            if normalized_keyword in self._build_question_search_text(idx):
                matches.append(idx)
        return matches
    def _set_search_status(self, text: str, light: str = "#666666", dark: str = "#bfbfbf") -> None:
        if self._search_status_label is None:
            return
        self._search_status_label.setText(text)
        _apply_label_color(self._search_status_label, light, dark)
    def _configure_search_popup(self, search_edit: SearchLineEdit) -> None:
        popup = QListWidget(cast(QWidget, self))
        popup.setWindowFlag(Qt.WindowType.ToolTip, True)
        popup.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
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
        self._search_popup = popup
        search_edit.installEventFilter(cast(QObject, self))
        popup.installEventFilter(cast(QObject, self))
    def _build_search_result_item(self, idx: int, keyword: str) -> QListWidgetItem:
        info = self._get_entry_info(idx)
        entry = self.entries[idx] if 0 <= idx < len(self.entries) else None
        qnum = str(info.get("num") or idx + 1)
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
        item.setData(_SEARCH_RESULT_INDEX_ROLE, idx)
        item.setData(_SEARCH_RESULT_TITLE_ROLE, self._build_search_highlight_html(title_line, keyword))
        item.setData(_SEARCH_RESULT_DETAIL_ROLE, self._build_search_highlight_html(detail_line, keyword))
        return item
    def _hide_search_popup(self) -> None:
        if self._search_popup is not None:
            self._search_popup.hide()
    def _refresh_search_popup(self, raw_keyword: str, matches: List[int]) -> None:
        if self._search_popup is None or self._search_edit is None:
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

        popup.setCurrentRow(0)
        popup_width = max(520, self._search_edit.width())
        content_height = 0
        for row in range(popup.count()):
            content_height += max(44, popup.sizeHintForRow(row))
        popup_height = min(320, content_height + popup.frameWidth() * 2 + 4)
        popup.resize(popup_width, max(52, popup_height))
        popup.move(self._search_edit.mapToGlobal(QPoint(0, self._search_edit.height() + 4)))
        popup.show()
        popup.raise_()
    def _jump_to_question_from_search(self, target_idx: int, matches: List[int], raw_keyword: str, match_cursor: int) -> None:
        self._search_match_indices = matches
        self._last_search_keyword = self._normalize_search_text(raw_keyword)
        self._last_search_match_cursor = match_cursor

        info = self._get_entry_info(target_idx)
        qnum = str(info.get("num") or target_idx + 1)
        self._set_search_status(
            f"匹配 {len(matches)} 题，当前定位到第{qnum}题（{match_cursor + 1}/{len(matches)}）",
            "#0f6cbd",
            "#63b3ff",
        )
        self._navigate_to_question(target_idx, animate=True)
    def _activate_search_popup_item(self, item: QListWidgetItem) -> None:
        if item is None:
            return
        target_idx = item.data(_SEARCH_RESULT_INDEX_ROLE)
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
        if self._search_popup is not None and self._search_popup.isVisible():
            current_item = self._search_popup.currentItem()
            if current_item is not None:
                self._activate_search_popup_item(current_item)
                return
        if self._search_edit is not None:
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
            self._set_search_status(f"匹配 {len(matches)} 题{overflow}，点下拉结果或回车跳转{suffix}", "#666666", "#bfbfbf")
        else:
            self._set_search_status(f"未找到“{raw_text}”", "#c42b1c", "#ff99a4")
    def _clear_question_search(self) -> None:
        self._search_match_indices = []
        self._last_search_keyword = ""
        self._last_search_match_cursor = -1
        if self._search_popup is not None:
            self._search_popup.clear()
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
        is_same_query = normalized_keyword == self._last_search_keyword and matches == self._search_match_indices
        if is_same_query and 0 <= self._last_search_match_cursor < len(matches):
            match_cursor = (self._last_search_match_cursor + 1) % len(matches)

        target_idx = matches[match_cursor]
        self._jump_to_question_from_search(target_idx, matches, raw_keyword, match_cursor)

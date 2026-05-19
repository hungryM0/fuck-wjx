"""题目向导搜索弹层与 delegate。"""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QTextDocument
from PySide6.QtWidgets import QApplication, QAbstractItemView, QListView, QStyle, QStyleOptionViewItem
from qfluentwidgets import ListWidget, isDarkTheme
from qfluentwidgets.components.widgets.list_view import ListItemDelegate


SEARCH_RESULT_INDEX_ROLE = int(Qt.ItemDataRole.UserRole) + 1
SEARCH_RESULT_TITLE_ROLE = SEARCH_RESULT_INDEX_ROLE + 1
SEARCH_RESULT_DETAIL_ROLE = SEARCH_RESULT_INDEX_ROLE + 2


class QuestionSearchCompleterDelegate(ListItemDelegate):
    """搜索建议下拉项。"""

    def __init__(self, parent: QAbstractItemView) -> None:
        super().__init__(cast(QListView, cast(Any, parent)))

    def _build_document(
        self,
        index: QModelIndex | QPersistentModelIndex,
        width: int,
        selected: bool,
    ) -> QTextDocument:
        title_html = str(index.data(SEARCH_RESULT_TITLE_ROLE) or "")
        detail_html = str(index.data(SEARCH_RESULT_DETAIL_ROLE) or "")
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
            <div style="font-size:13px; font-weight:600;
                        color:{title_color};">{title_html}</div>
            <div style="margin-top:4px; font-size:12px;
                        color:{detail_color};">{detail_html}</div>
            """
        )
        return document

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        option_view = cast(Any, option)
        option_copy = QStyleOptionViewItem(option)
        self.initStyleOption(option_copy, cast(QModelIndex, cast(Any, index)))
        option_copy_any = cast(Any, option_copy)
        option_copy_any.text = ""

        widget = option_view.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option_copy, painter, widget)

        text_rect = option_view.rect.adjusted(12, 8, -12, -8)
        document = self._build_document(
            index,
            text_rect.width(),
            bool(option_view.state & QStyle.StateFlag.State_Selected),
        )

        painter.save()
        painter.translate(text_rect.topLeft())
        document.drawContents(painter, QRectF(0, 0, text_rect.width(), text_rect.height()))
        painter.restore()

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        option_view = cast(Any, option)
        width = option_view.rect.width() or 480
        document = self._build_document(index, width, False)
        return QSize(width, max(44, int(document.size().height()) + 16))


def apply_search_popup_style(popup: ListWidget) -> None:
    if isDarkTheme():
        background = "#2b2b2b"
        border = "rgba(255, 255, 255, 0.14)"
        hover = "rgba(255, 255, 255, 0.08)"
    else:
        background = "#ffffff"
        border = "rgba(0, 0, 0, 0.14)"
        hover = "rgba(0, 0, 0, 0.05)"

    popup.setObjectName("questionSearchPopup")
    popup.setStyleSheet(
        f"""
        ListWidget#questionSearchPopup {{
            background: {background};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 6px;
        }}
        ListWidget#questionSearchPopup::item {{
            border-radius: 6px;
            padding: 0px;
        }}
        ListWidget#questionSearchPopup::item:hover {{
            background: {hover};
        }}
        ListWidget#questionSearchPopup::item:selected {{
            background: transparent;
        }}
        ListWidget#questionSearchPopup QScrollBar {{
            background: transparent;
        }}
        """
    )
    viewport = popup.viewport()
    if viewport is not None:
        viewport.setStyleSheet(f"background: {background}; border: none;")


__all__ = [
    "QuestionSearchCompleterDelegate",
    "SEARCH_RESULT_DETAIL_ROLE",
    "SEARCH_RESULT_INDEX_ROLE",
    "SEARCH_RESULT_TITLE_ROLE",
    "apply_search_popup_style",
]

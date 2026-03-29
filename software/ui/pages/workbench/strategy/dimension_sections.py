"""维度分组区块组件。"""
from __future__ import annotations

import json
from typing import Dict, List, Sequence

from PySide6.QtCore import QEvent, QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    HorizontalSeparator,
    StrongBodyLabel,
    TableWidget,
    ToolButton,
)

from software.app.config import DIMENSION_UNGROUPED

ENTRY_INDEX_ROLE = 0x0100
ENTRY_DRAG_MIME = "application/x-surveycontroller-dimension-entries"


class DimensionEntryTable(TableWidget):
    """维度题目表格，负责跨区块拖拽。"""

    entriesDropped = Signal(list, object)

    def __init__(self, group_name: str, parent=None):
        super().__init__(parent)
        self.group_name = group_name
        self._build_ui()

    def _build_ui(self) -> None:
        self.setColumnCount(4)
        self.setHorizontalHeaderLabels(["名称", "题号", "题型", "倾向预设"])
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.empty_hint_label = CaptionLabel("将题目拖动到此处以划分维度", self.viewport())
        self.empty_hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.empty_hint_label.setStyleSheet("color: rgba(255, 255, 255, 0.58);")
        self.empty_hint_label.hide()

        header = self.horizontalHeader()
        header.setSectionResizeMode(0, header.ResizeMode.Stretch)
        header.setSectionResizeMode(1, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, header.ResizeMode.ResizeToContents)

    def set_rows(self, rows: Sequence[Dict[str, object]]) -> None:
        self.setRowCount(0)
        for row_index, row in enumerate(rows):
            self.insertRow(row_index)
            self._set_row(row_index, row)
        self._update_height()

    def selected_entry_indices(self) -> List[int]:
        result: List[int] = []
        selection = self.selectionModel()
        if selection is None:
            return result
        for model_index in selection.selectedRows():
            item = self.item(model_index.row(), 0)
            if item is None:
                continue
            value = item.data(ENTRY_INDEX_ROLE)
            if isinstance(value, int) and value >= 0:
                result.append(value)
        return sorted(set(result))

    def startDrag(self, supportedActions) -> None:
        entry_indices = self.selected_entry_indices()
        if not entry_indices:
            return
        mime = QMimeData()
        mime.setData(ENTRY_DRAG_MIME, json.dumps(entry_indices).encode("utf-8"))

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(supportedActions or Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(ENTRY_DRAG_MIME):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(ENTRY_DRAG_MIME):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(ENTRY_DRAG_MIME):
            event.ignore()
            return
        entry_indices = self._decode_entry_indices(event.mimeData())
        if not entry_indices:
            event.ignore()
            return
        self.entriesDropped.emit(entry_indices, self.group_name)
        event.acceptProposedAction()

    def viewportEvent(self, event) -> bool:
        event_type = event.type()
        if event_type in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            mime_data = event.mimeData() if hasattr(event, "mimeData") else None
            if mime_data is None or not mime_data.hasFormat(ENTRY_DRAG_MIME):
                event.ignore()
                return True
            if event_type == QEvent.Type.Drop:
                entry_indices = self._decode_entry_indices(mime_data)
                if not entry_indices:
                    event.ignore()
                    return True
                self.entriesDropped.emit(entry_indices, self.group_name)
            event.acceptProposedAction()
            return True
        return super().viewportEvent(event)

    def _set_row(self, row_index: int, row: Dict[str, object]) -> None:
        from PySide6.QtWidgets import QTableWidgetItem

        title_item = QTableWidgetItem(str(row.get("title") or ""))
        title_item.setData(ENTRY_INDEX_ROLE, int(row.get("entry_index", -1)))
        self.setItem(row_index, 0, title_item)
        self.setItem(row_index, 1, QTableWidgetItem(str(row.get("question_num") or "")))
        self.setItem(row_index, 2, QTableWidgetItem(str(row.get("type_label") or "")))
        self.setItem(row_index, 3, QTableWidgetItem(str(row.get("bias_text") or "")))

    def _update_height(self) -> None:
        frame = self.frameWidth() * 2
        header_height = self.horizontalHeader().height()
        row_height = sum(self.rowHeight(i) for i in range(self.rowCount()))
        min_drop_zone_height = 120
        content_height = max(row_height, min_drop_zone_height)
        self.setFixedHeight(frame + header_height + content_height + 10)
        self._update_empty_hint()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_empty_hint()

    def _layout_empty_hint(self) -> None:
        if not self.empty_hint_label.isVisible():
            return
        self.empty_hint_label.adjustSize()
        viewport_rect = self.viewport().rect()
        x = max(0, (viewport_rect.width() - self.empty_hint_label.width()) // 2)
        y = max(8, (viewport_rect.height() - self.empty_hint_label.height()) // 2)
        self.empty_hint_label.move(x, y)

    def _update_empty_hint(self) -> None:
        is_empty = self.rowCount() == 0
        self.empty_hint_label.setVisible(is_empty)
        if is_empty:
            self._layout_empty_hint()
            self.empty_hint_label.raise_()

    @staticmethod
    def _decode_entry_indices(mime_data: QMimeData) -> List[int]:
        raw = bytes(mime_data.data(ENTRY_DRAG_MIME))
        if not raw:
            return []
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return []
        result: List[int] = []
        for item in data if isinstance(data, list) else []:
            if isinstance(item, int) and item >= 0:
                result.append(item)
        return sorted(set(result))


class DimensionSectionWidget(QWidget):
    """单个维度区块：标题 + 表格。"""

    renameRequested = Signal(str)
    deleteRequested = Signal(str)
    entriesDropped = Signal(list, object)

    def __init__(self, group_name: str, parent=None):
        super().__init__(parent)
        self.group_name = group_name
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.header = QWidget(self)

        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        self.name_label = StrongBodyLabel(self.group_name, self.header)
        self.meta_label = CaptionLabel(
            "系统保留组" if self.group_name == DIMENSION_UNGROUPED else "自定义维度",
            self.header,
        )
        self.rename_button = ToolButton(self.header)
        self.delete_button = ToolButton(self.header)
        self.count_label = BodyLabel("0 题", self.header)
        self.separator = HorizontalSeparator(self)
        self.table = DimensionEntryTable(self.group_name, self)
        self.table.entriesDropped.connect(self.entriesDropped.emit)

        header_layout.addWidget(self.name_label)
        header_layout.addWidget(self.meta_label)
        header_layout.addWidget(self.rename_button, 0, Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(self.delete_button, 0, Qt.AlignmentFlag.AlignVCenter)
        header_layout.addStretch(1)
        header_layout.addWidget(self.count_label)

        self.rename_button.setIcon(FluentIcon.EDIT)
        self.rename_button.setIconSize(QSize(14, 14))
        self.rename_button.setFixedSize(28, 28)
        self.rename_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rename_button.setToolTip("重命名维度")
        self.rename_button.setVisible(self.group_name != DIMENSION_UNGROUPED)
        self.rename_button.clicked.connect(lambda: self.renameRequested.emit(self.group_name))
        self.delete_button.setIcon(FluentIcon.DELETE)
        self.delete_button.setIconSize(QSize(14, 14))
        self.delete_button.setFixedSize(28, 28)
        self.delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_button.setToolTip("删除维度")
        self.delete_button.setVisible(self.group_name != DIMENSION_UNGROUPED)
        self.delete_button.clicked.connect(lambda: self.deleteRequested.emit(self.group_name))

        self.count_label.setObjectName("countLabel")
        self.header.setObjectName("dimensionSectionHeader")
        self.setStyleSheet(
            """
            QWidget#dimensionSectionHeader {
                background: transparent;
            }
            QWidget#dimensionSectionHeader QLabel#countLabel {
                background-color: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
                padding: 2px 10px;
            }
            """
        )

        layout.addWidget(self.header)
        layout.addWidget(self.separator)
        layout.addWidget(self.table)

    def set_rows(self, rows: Sequence[Dict[str, object]]) -> None:
        self.table.set_rows(rows)
        self.count_label.setText(f"{len(rows)} 题")

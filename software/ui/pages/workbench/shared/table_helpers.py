"""Workbench 表格通用小工具。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem


def set_table_text(
    table: QTableWidget,
    row: int,
    column: int,
    text: str,
    *,
    align_center: bool = False,
) -> None:
    item = table.item(row, column)
    if item is None:
        item = QTableWidgetItem(text)
        if align_center:
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        table.setItem(row, column, item)
        return
    if item.text() != text:
        item.setText(text)
    if align_center:
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

"""Adaptive flow layout for card grids.

QFluentWidgets added ``AdaptiveFlowLayout`` in newer versions, but this project
currently pins/uses an older ``qfluentwidgets`` that doesn't ship it.

This implementation is intentionally small and focused:
- Computes the number of columns based on available width and a minimum item width
- Wraps items to next row automatically
- Makes each item in a row share the same width (adaptive grid feel)

No extra UI behaviors, just layout.
"""

from __future__ import annotations

from math import ceil
from typing import cast

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget


class AdaptiveFlowLayout(QLayout):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        minItemWidth: int = 360,
        hSpacing: int = 16,
        vSpacing: int = 16,
    ):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._min_item_width = max(1, int(minItemWidth))
        self._h_spacing = max(0, int(hSpacing))
        self._v_spacing = max(0, int(vSpacing))

    # ---- QLayout required API ----

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 (Qt API)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return cast(QLayoutItem, None)

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), testOnly=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, testOnly=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        margins = self.contentsMargins()
        left = margins.left()
        top = margins.top()
        right = margins.right()
        bottom = margins.bottom()
        width = left + right
        height = top + bottom

        if not self._items:
            return QSize(width, height)

        # Rough minimum: one column.
        max_min_height = 0
        for item in self._items:
            size = item.minimumSize()
            width = max(width, left + right + max(self._min_item_width, size.width()))
            max_min_height = max(max_min_height, size.height())

        height = top + bottom + max_min_height
        return QSize(width, height)

    def invalidate(self) -> None:
        super().invalidate()

    # ---- Internal ----

    def _effective_rect(self, rect: QRect) -> QRect:
        margins = self.contentsMargins()
        left = margins.left()
        top = margins.top()
        right = margins.right()
        bottom = margins.bottom()
        return QRect(
            rect.x() + left,
            rect.y() + top,
            max(0, rect.width() - left - right),
            max(0, rect.height() - top - bottom),
        )

    def _column_count(self, available_width: int) -> int:
        if available_width <= 0:
            return 1

        # cols * min + (cols-1) * spacing <= available
        # => cols <= (available + spacing) / (min + spacing)
        cols = (available_width + self._h_spacing) // (self._min_item_width + self._h_spacing)
        return max(1, int(cols))

    def _do_layout(self, rect: QRect, *, testOnly: bool) -> int:
        if not self._items:
            return 0

        r = self._effective_rect(rect)
        cols = self._column_count(r.width())
        rows = int(ceil(len(self._items) / cols))

        # Compute shared item width per column.
        total_spacing = self._h_spacing * (cols - 1)
        item_width = r.width() if cols == 1 else max(1, (r.width() - total_spacing) // cols)

        # First pass: compute row heights.
        row_heights: list[int] = [0] * rows
        for idx, item in enumerate(self._items):
            row = idx // cols
            hint_h = item.sizeHint().height()
            min_h = item.minimumSize().height()
            row_heights[row] = max(row_heights[row], max(hint_h, min_h))

        # Second pass: set geometries.
        y = r.y()
        for row in range(rows):
            x = r.x()
            row_h = row_heights[row]

            for col in range(cols):
                idx = row * cols + col
                if idx >= len(self._items):
                    break

                item = self._items[idx]
                if not testOnly:
                    item.setGeometry(QRect(x, y, item_width, row_h))

                x += item_width + self._h_spacing

            y += row_h
            if row != rows - 1:
                y += self._v_spacing

        # Return used height including margins.
        margins = self.contentsMargins()
        left = margins.left()
        top = margins.top()
        right = margins.right()
        bottom = margins.bottom()
        used_h = (y - r.y()) + top + bottom
        return used_h

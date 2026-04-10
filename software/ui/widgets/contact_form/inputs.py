"""联系表单输入组件与数值处理。"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Callable, Optional

from PySide6.QtWidgets import QWidget
from qfluentwidgets import Action, FluentIcon, LineEdit, PlainTextEdit, RoundMenu

from software.ui.helpers.contact_api import format_quota_value

from .constants import MAX_REQUEST_QUOTA, REQUEST_QUOTA_STEP


class PasteOnlyLineEdit(LineEdit):
    """只显示 Fluent 风格“复制 / 粘贴 / 全选”菜单的 LineEdit。"""



    def __init__(self, parent=None, on_paste: Optional[Callable[[QWidget], bool]] = None):
        super().__init__(parent)
        self._on_paste = on_paste

    def contextMenuEvent(self, e):
        menu = RoundMenu(parent=self)
        copy_action = Action(FluentIcon.COPY, "复制", parent=menu)
        copy_action.setEnabled(self.hasSelectedText())
        copy_action.triggered.connect(self.copy)
        paste_action = Action(FluentIcon.PASTE, "粘贴", parent=menu)

        def _do_paste():
            if self._on_paste and self._on_paste(self):
                return
            self.paste()

        menu.addAction(copy_action)
        paste_action.triggered.connect(_do_paste)
        menu.addAction(paste_action)
        menu.exec(e.globalPos())
        e.accept()

class PasteOnlyPlainTextEdit(PlainTextEdit):
    """只显示 Fluent 风格“复制 / 粘贴 / 全选”菜单的 PlainTextEdit，兼容外部粘贴处理。"""

    def __init__(self, parent=None, on_paste: Optional[Callable[[QWidget], bool]] = None):
        super().__init__(parent)
        self._on_paste = on_paste

    def contextMenuEvent(self, e):
        menu = RoundMenu(parent=self)
        copy_action = Action(FluentIcon.COPY, "复制", parent=menu)
        copy_action.setEnabled(self.textCursor().hasSelection())
        copy_action.triggered.connect(self.copy)
        paste_action = Action(FluentIcon.PASTE, "粘贴", parent=menu)

        def _do_paste():
            if self._on_paste and self._on_paste(self):
                return
            self.paste()

        menu.addAction(copy_action)
        paste_action.triggered.connect(_do_paste)
        menu.addAction(paste_action)
        menu.exec(e.globalPos())
        e.accept()

class ContactFormInputMixin:
    if TYPE_CHECKING:
        quantity_edit: Any
        amount_edit: Any
        _last_valid_quantity_text: str

    def _parse_quantity_value(self, text: Optional[str] = None) -> Optional[Decimal]:
        raw_text = (self.quantity_edit.text() if text is None else text) or ""
        raw_text = raw_text.strip()
        if not raw_text:
            return None
        try:
            value = Decimal(raw_text)
        except (InvalidOperation, ValueError):
            return None
        if value < 0:
            return None
        scaled = value / REQUEST_QUOTA_STEP
        if scaled != scaled.to_integral_value():
            return None
        return value
    def _normalize_quantity_text(self, text: str) -> str:
        quantity = self._parse_quantity_value(text)
        if quantity is None:
            return (text or "").strip()
        return format_quota_value(quantity)
    def _normalize_quantity_if_needed(self) -> None:
        raw_text = (self.quantity_edit.text() or "").strip()
        if not raw_text:
            return
        quantity = self._parse_quantity_value(raw_text)
        if quantity is None:
            return
        normalized_text = self._normalize_quantity_text(raw_text)
        if quantity > Decimal(str(MAX_REQUEST_QUOTA)):
            normalized_text = self._last_valid_quantity_text
        if normalized_text == raw_text:
            return
        self.quantity_edit.blockSignals(True)
        try:
            self.quantity_edit.setText(normalized_text)
        finally:
            self.quantity_edit.blockSignals(False)
    def _normalize_amount_text(self, text: str) -> str:
        raw_text = (text or "").strip()
        if not raw_text:
            return ""
        try:
            normalized = Decimal(raw_text)
        except (InvalidOperation, ValueError):
            return raw_text
        return format(normalized.normalize(), "f").rstrip("0").rstrip(".") or "0"
    def _parse_amount_value(self, text: Optional[str] = None) -> Optional[Decimal]:
        raw_text = (self.amount_edit.currentText() if text is None else text) or ""
        raw_text = raw_text.strip()
        if not raw_text:
            return None
        try:
            value = Decimal(raw_text)
        except (InvalidOperation, ValueError):
            return None
        if value <= 0:
            return None
        return value

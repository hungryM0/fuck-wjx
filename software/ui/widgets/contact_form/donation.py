"""联系表单捐赠与额度规则。"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional, cast

from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon, InfoBar, InfoBarPosition

from software.logging.log_utils import log_suppressed_exception

from .constants import DONATION_AMOUNT_OPTIONS, DONATION_AMOUNT_RULES, MAX_REQUEST_QUOTA, REQUEST_MESSAGE_TYPE


class ContactFormDonationMixin:
    if TYPE_CHECKING:
        type_combo: Any
        amount_edit: Any
        quantity_edit: Any
        amount_rule_hint: QWidget
        donated_cb: Any
        status_spinner: Any
        status_icon: Any
        online_label: Any
        _random_ip_user_id: int
        _last_valid_quantity_text: str

        def _selected_payment_method(self) -> str: ...
        def _parse_quantity_value(self, text: Optional[str] = None) -> Optional[Decimal]: ...
        def _normalize_quantity_text(self, text: str) -> str: ...
        def _normalize_quantity_if_needed(self) -> None: ...
        def _parse_amount_value(self, text: Optional[str] = None) -> Optional[Decimal]: ...
        def _update_send_button_state(self) -> None: ...
        def window(self) -> QWidget: ...

    def _get_donation_check_block_reason(self) -> str:
        current_type = self.type_combo.currentText() or ""
        if current_type != REQUEST_MESSAGE_TYPE:
            return ""
        if not self._selected_payment_method():
            return "请先选择你刚刚使用的支付方式（微信或支付宝）。"
        amount_text = (self.amount_edit.currentText() or "").strip()
        if not amount_text:
            return "请先填写支付金额后，再勾选“我已完成支付，且确认随机ip可用”。"
        if self._random_ip_user_id > 0:
            return ""
        return "你还没有成功使用过随机IP，暂时不能勾选。请先启用并实际跑通一次随机IP，确认能正常用，再来申请。"
    def _sync_donation_check_state(self) -> None:
        """当勾选条件失效时，自动撤销“已支付”勾选。"""
        if not hasattr(self, "donated_cb"):
            return
        if self._get_donation_check_block_reason() and self.donated_cb.isChecked():
            previous_block_state = self.donated_cb.blockSignals(True)
            try:
                self.donated_cb.setChecked(False)
            finally:
                self.donated_cb.blockSignals(previous_block_state)
    def _open_donate_page(self) -> None:
        widget: Optional[QWidget] = cast(QWidget, self)
        while widget is not None:
            if hasattr(widget, "_get_donate_page") and hasattr(widget, "_switch_to_more_page"):
                try:
                    host = cast(Any, widget)
                    donate_page = host._get_donate_page()
                    host._switch_to_more_page(donate_page)
                    top_level = self.window()
                    if top_level is not None and top_level is not widget:
                        top_level.close()
                    return
                except Exception as exc:
                    log_suppressed_exception("_open_donate_page", exc, level=logging.WARNING)
                    break
            widget = widget.parentWidget()
        InfoBar.warning(
            "",
                    "暂时打不开支付页，请从“更多 -> 捐助”进入",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=2500,
        )
    def _on_amount_changed(self, text: str):
        """金额输入变化时同步金额规则提示。"""
        _ = text
        self._sync_amount_rule_warning()
        self._sync_donation_check_state()
        self._update_send_button_state()
    def _normalize_amount_if_needed(self) -> None:
        """将 0 自动纠正为 0.01，避免提交无效金额。"""
        text = (self.amount_edit.currentText() or "").strip()
        if not text:
            return
        try:
            value = float(text)
        except ValueError:
            return
        if value == 0.0 and text != "0.01":
            self.amount_edit.setText("0.01")
    def _on_amount_editing_finished(self):
        self._normalize_amount_if_needed()
        self._sync_amount_rule_warning()
    def _on_quantity_changed(self, text: str):
        """申请额度变化时刷新支付金额选项。"""
        normalized_text = (text or "").strip()
        if not normalized_text:
            self._last_valid_quantity_text = ""
        else:
            quantity = self._parse_quantity_value(normalized_text)
            if quantity is not None and quantity <= Decimal(str(MAX_REQUEST_QUOTA)):
                self._last_valid_quantity_text = self._normalize_quantity_text(normalized_text)
            elif quantity is not None and quantity > Decimal(str(MAX_REQUEST_QUOTA)):
                self.quantity_edit.blockSignals(True)
                try:
                    self.quantity_edit.setText(self._last_valid_quantity_text)
                finally:
                    self.quantity_edit.blockSignals(False)
                return
        self._refresh_amount_options()
        self._sync_amount_rule_warning()
    def _on_quantity_editing_finished(self):
        self._normalize_quantity_if_needed()
        self._refresh_amount_options()
        self._sync_amount_rule_warning()
    def _on_urgency_changed(self):
        """紧急程度改变时预留钩子。"""
        return
    def _on_status_loaded(self, text: str, color: str):
        """信号槽：在主线程更新状态标签"""
        try:
            self.status_spinner.hide()
            self.status_icon.show()
            if color.lower() == "#228b22":
                self.status_icon.setIcon(FluentIcon.ACCEPT)
            elif color.lower() == "#cc0000":
                self.status_icon.setIcon(FluentIcon.REMOVE_FROM)
            else:
                self.status_icon.setIcon(FluentIcon.INFO)
            self.online_label.setText(text)
            self.online_label.setStyleSheet(f"color:{color};")
        except RuntimeError as exc:
            log_suppressed_exception("_on_status_loaded: self.status_spinner.hide()", exc, level=logging.WARNING)
    def _get_minimum_allowed_amount(self, quantity: Decimal) -> Optional[Decimal]:
        for min_quantity, min_amount in DONATION_AMOUNT_RULES:
            if quantity >= min_quantity:
                return min_amount
        return self._parse_amount_value(DONATION_AMOUNT_OPTIONS[0])
    def _get_allowed_amount_options(self, quantity: Decimal) -> list[str]:
        minimum_allowed_amount = self._get_minimum_allowed_amount(quantity)
        if minimum_allowed_amount is None:
            return DONATION_AMOUNT_OPTIONS[:]
        return [
            amount
            for amount in DONATION_AMOUNT_OPTIONS
            if (self._parse_amount_value(amount) or Decimal("0")) >= minimum_allowed_amount
        ]
    def _is_amount_allowed(self, amount_text: str, quantity_text: Optional[str] = None) -> bool:
        amount_value = self._parse_amount_value(amount_text)
        if amount_value is None:
            return True

        quantity = self._parse_quantity_value(quantity_text) or Decimal("0")
        minimum_allowed_amount = self._get_minimum_allowed_amount(quantity)
        if minimum_allowed_amount is None:
            return True
        return amount_value >= minimum_allowed_amount
    def _refresh_amount_options(self) -> None:
        current_text = (self.amount_edit.currentText() or "").strip()
        allowed_amounts = self._get_allowed_amount_options(self._parse_quantity_value() or Decimal("0"))

        previous_block_state = self.amount_edit.blockSignals(True)
        try:
            self.amount_edit.clear()
            for amount in allowed_amounts:
                self.amount_edit.addItem(amount)
            if not current_text:
                self.amount_edit._currentIndex = -1
                self.amount_edit.setText("")
            else:
                current_index = self.amount_edit.findText(current_text)
                if current_index >= 0:
                    self.amount_edit.setCurrentIndex(current_index)
                else:
                    self.amount_edit._currentIndex = -1
                    self.amount_edit.setText(current_text)
        finally:
            self.amount_edit.blockSignals(previous_block_state)
    def _show_amount_rule_infobar(self) -> None:
        self.amount_rule_hint.show()
    def _close_amount_rule_infobar(self) -> None:
        self.amount_rule_hint.hide()
    def _sync_amount_rule_warning(self) -> None:
        current_type = self.type_combo.currentText() or ""
        amount_text = (self.amount_edit.currentText() or "").strip()
        if current_type != REQUEST_MESSAGE_TYPE or not amount_text:
            self._close_amount_rule_infobar()
            return
        if self._is_amount_allowed(amount_text):
            self._close_amount_rule_infobar()
            return
        self._show_amount_rule_infobar()

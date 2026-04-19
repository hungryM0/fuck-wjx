"""联系表单提交流程。"""
from __future__ import annotations

import logging
import os
import re
import threading
import tempfile
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional, cast

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget
from qfluentwidgets import InfoBar, InfoBarPosition, MessageBox

from software.app.config import CONTACT_API_URL
from software.app.runtime_paths import get_runtime_directory
from software.app.version import __VERSION__
from software.io.config import RuntimeConfig, save_config
from software.logging.log_utils import LOG_BUFFER_HANDLER, log_suppressed_exception, save_log_records_to_file
from software.ui.helpers.contact_api import format_quota_value, post as http_post

from .constants import DONATION_AMOUNT_BLOCK_MESSAGE, MAX_REQUEST_QUOTA, REQUEST_MESSAGE_TYPE


def build_contact_message(
    *,
    version_str: str,
    message_type: str,
    email: str,
    donated: bool,
    random_ip_user_id: int,
    message: str,
    request_payment_method: str,
    request_amount_text: str,
    request_quota_text: str,
    request_urgency_text: str,
) -> str:
    lines = [f"来源：SurveyController v{version_str}", f"类型：{message_type}"]
    if email:
        lines.append(f"联系邮箱： {email}")
    if message_type == REQUEST_MESSAGE_TYPE:
        lines.append(f"已支付：{'是' if donated else '否'}")
    if random_ip_user_id > 0:
        lines.append(f"随机IP用户ID：{random_ip_user_id}")
    if message_type == REQUEST_MESSAGE_TYPE:
        lines.extend(
            [
                f"支付方式：{request_payment_method}",
                f"支付金额：￥{request_amount_text}",
                f"申请额度：{request_quota_text}",
                f"紧急程度：{request_urgency_text or '中'}",
                "",
                f"补充说明：{message or '未填写'}",
            ]
        )
    else:
        lines.extend(["", f"消息：{message}"])
    return "\n".join(lines)


def build_contact_request_fields(
    *,
    message: str,
    timestamp: str,
    random_ip_user_id: int,
    files_payload: list[tuple[str, tuple[str, bytes, str]]],
) -> list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]]:
    fields: list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]] = [
        ("message", (None, message)),
        ("timestamp", (None, timestamp)),
    ]
    if random_ip_user_id > 0:
        fields.append(("userId", (None, str(random_ip_user_id))))
    fields.extend(files_payload)
    return fields


class ContactFormSubmissionMixin:
    if TYPE_CHECKING:
        email_edit: Any
        type_combo: Any
        amount_edit: Any
        quantity_edit: Any
        verify_code_edit: Any
        urgency_combo: Any
        donated_cb: Any
        auto_attach_config_checkbox: Any
        auto_attach_log_checkbox: Any
        message_edit: Any
        send_btn: Any
        send_spinner: Any
        _attachments: Any
        _config_snapshot_provider: Any
        _pending_temp_attachment_paths: list[str]
        _random_ip_user_id: int
        _current_has_email: bool
        _current_message_type: str
        _verify_code_requested: bool
        _verify_code_requested_email: str
        _auto_clear_on_success: bool
        _sendFinished: Any
        sendSucceeded: Any
        quotaRequestSucceeded: Any

        def _normalize_amount_if_needed(self) -> None: ...
        def _normalize_quantity_if_needed(self) -> None: ...
        def _selected_payment_method(self) -> str: ...
        def _normalize_quantity_text(self, text: str) -> str: ...
        def _update_send_button_state(self) -> None: ...
        def _parse_quantity_value(self, text: Optional[str] = None) -> Optional[Decimal]: ...
        def _is_amount_allowed(self, amount_text: str, quantity_text: Optional[str] = None) -> bool: ...
        def _show_amount_rule_infobar(self) -> None: ...
        def _close_amount_rule_infobar(self) -> None: ...
        def _render_attachments_ui(self) -> None: ...
        def _clear_payment_method_selection(self) -> None: ...
        def refresh_random_ip_user_id_hint(self) -> None: ...
        def _is_bug_report_type(self, message_type: Optional[str]) -> bool: ...
        def _reset_bug_report_auto_attach_defaults(self) -> None: ...
        def window(self) -> QWidget: ...

    def _cleanup_pending_temp_files(self) -> None:
        for path in list(getattr(self, "_pending_temp_attachment_paths", [])):
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception as exc:
                log_suppressed_exception(f"_cleanup_pending_temp_files: {path}", exc, level=logging.WARNING)
        self._pending_temp_attachment_paths = []

    @staticmethod
    def _read_file_bytes(path: str) -> bytes:
        with open(path, "rb") as file:
            return file.read()

    def _export_bug_report_config_snapshot(self) -> tuple[str, tuple[str, bytes, str]]:
        provider = getattr(self, "_config_snapshot_provider", None)
        if not callable(provider):
            host = self._find_controller_host()
            provider = getattr(host, "_collect_current_config_snapshot", None) if host is not None else None
        if not callable(provider):
            raise ValueError("当前窗口没有可导出的运行时配置")
        config_snapshot = cast(RuntimeConfig, provider())
        if config_snapshot is None:
            raise ValueError("当前运行时配置为空，无法导出")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"bug_report_config_{timestamp}.json"
        path = os.path.join(tempfile.gettempdir(), file_name)
        save_config(config_snapshot, path)
        self._pending_temp_attachment_paths.append(path)
        return "配置快照", (file_name, self._read_file_bytes(path), "application/json")

    def _export_bug_report_log_snapshot(self) -> tuple[str, tuple[str, bytes, str]]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"bug_report_log_{timestamp}.txt"
        path = os.path.join(tempfile.gettempdir(), file_name)
        save_log_records_to_file(LOG_BUFFER_HANDLER.get_records(), get_runtime_directory(), path)
        self._pending_temp_attachment_paths.append(path)
        return "日志快照", (file_name, self._read_file_bytes(path), "text/plain")

    @staticmethod
    def _fatal_crash_log_payload() -> Optional[tuple[str, tuple[str, bytes, str]]]:
        path = os.path.join(get_runtime_directory(), "logs", "fatal_crash.log")
        if not os.path.exists(path):
            return None
        if os.path.getsize(path) <= 0:
            return None
        with open(path, "rb") as file:
            data = file.read()
        return "fatal_crash.log", ("fatal_crash.log", data, "text/plain")

    @staticmethod
    def _renumber_files_payload(
        items: list[tuple[str, tuple[str, bytes, str]]],
    ) -> list[tuple[str, tuple[str, bytes, str]]]:
        payload: list[tuple[str, tuple[str, bytes, str]]] = []
        for index, (_, file_tuple) in enumerate(items, start=1):
            payload.append((f"file{index}", file_tuple))
        return payload

    def _build_bug_report_auto_files_payload(
        self,
    ) -> tuple[list[tuple[str, tuple[str, bytes, str]]], list[str]]:
        auto_files: list[tuple[str, tuple[str, bytes, str]]] = []
        summary_lines = [
            f"当前运行配置快照：{'已附带' if self.auto_attach_config_checkbox.isChecked() else '未附带'}",
            f"当前日志快照：{'已附带' if self.auto_attach_log_checkbox.isChecked() else '未附带'}",
        ]

        if self.auto_attach_config_checkbox.isChecked():
            auto_files.append(self._export_bug_report_config_snapshot())

        if self.auto_attach_log_checkbox.isChecked():
            auto_files.append(self._export_bug_report_log_snapshot())
            fatal_payload = self._fatal_crash_log_payload()
            if fatal_payload is not None:
                auto_files.append(fatal_payload)
                summary_lines.append("fatal_crash.log：已附带")
            else:
                summary_lines.append("fatal_crash.log：未发现")
        else:
            summary_lines.append("fatal_crash.log：未附带")

        return auto_files, summary_lines

    def _validate_email(self, email: str) -> bool:
        if not email:
            return True
        pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        return re.match(pattern, email) is not None
    def _on_send_clicked(self):
        self._cleanup_pending_temp_files()
        email = (self.email_edit.text() or "").strip()
        self._current_has_email = bool(email)

        QTimer.singleShot(10, lambda: self._clear_email_selection())
        QTimer.singleShot(10, lambda: self._focus_send_button())

        mtype = self.type_combo.currentText() or "报错反馈"

        request_amount_text = ""
        request_quota_text = ""
        request_urgency_text = ""
        request_payment_method = ""
        if mtype == REQUEST_MESSAGE_TYPE:
            self._normalize_amount_if_needed()
            self._normalize_quantity_if_needed()
            amount_text = (self.amount_edit.currentText() or "").strip()
            quantity_text = (self.quantity_edit.text() or "").strip()
            verify_code = (self.verify_code_edit.text() or "").strip()
            request_payment_method = self._selected_payment_method()
            request_amount_text = amount_text
            request_quota_text = self._normalize_quantity_text(quantity_text)
            request_urgency_text = (self.urgency_combo.currentText() or "").strip()
            if not request_payment_method:
                InfoBar.warning("", "请选择你刚刚使用的支付方式", parent=self, position=InfoBarPosition.TOP, duration=2000)
                self._update_send_button_state()
                return
            if not amount_text:
                InfoBar.warning("", "请输入支付金额", parent=self, position=InfoBarPosition.TOP, duration=2000)
                return
            if not self.donated_cb.isChecked():
                InfoBar.warning("", "请先勾选“我已完成支付”后再发送申请", parent=self, position=InfoBarPosition.TOP, duration=2000)
                self._update_send_button_state()
                return
            if not quantity_text:
                InfoBar.warning("", "请输入申请额度", parent=self, position=InfoBarPosition.TOP, duration=2000)
                return
            quantity_value = self._parse_quantity_value(quantity_text)
            if quantity_value is None:
                InfoBar.warning("", "申请额度必须 >= 0，且只能填 0.5 的倍数", parent=self, position=InfoBarPosition.TOP, duration=2200)
                return
            if quantity_value > Decimal(str(MAX_REQUEST_QUOTA)):
                InfoBar.warning(
                    "",
                    f"申请额度不能超过 {format_quota_value(MAX_REQUEST_QUOTA)}",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                )
                return
            if amount_text and not self._is_amount_allowed(amount_text, quantity_text):
                self._show_amount_rule_infobar()
                InfoBar.warning("", DONATION_AMOUNT_BLOCK_MESSAGE, parent=self, position=InfoBarPosition.TOP, duration=2200)
                return
            if not self._verify_code_requested:
                InfoBar.warning("", "请先点击发送验证码", parent=self, position=InfoBarPosition.TOP, duration=2000)
                return
            if email != self._verify_code_requested_email:
                InfoBar.warning("", "邮箱已变更，请重新发送验证码", parent=self, position=InfoBarPosition.TOP, duration=2200)
                return
            if verify_code != "114514":
                InfoBar.warning("", "验证码错误，请重试", parent=self, position=InfoBarPosition.TOP, duration=2200)
                return

        message = (self.message_edit.toPlainText() or "").strip()
        if not message and mtype != REQUEST_MESSAGE_TYPE:
            warn_text = "请输入消息内容"
            InfoBar.warning("", warn_text, parent=self, position=InfoBarPosition.TOP, duration=2000)
            return

        if mtype == REQUEST_MESSAGE_TYPE and not email:
            InfoBar.warning("", "额度申请必须填写邮箱地址", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return

        if email and not self._validate_email(email):
            InfoBar.warning("", "邮箱格式不正确", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return

        self.refresh_random_ip_user_id_hint()
        if mtype == REQUEST_MESSAGE_TYPE and self._random_ip_user_id <= 0:
            InfoBar.warning(
                "",
                "暂时还不能申请额度。请先小测试一两份，确认能正常提交成功后，再来申请额度。",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3500,
            )
            return

        if mtype == REQUEST_MESSAGE_TYPE:
            confirm_email_box = MessageBox(
                "确认邮箱地址",
                f"当前输入的邮箱地址是：{email}\n\n请确认邮箱地址正确无误。开发者会在2小时内发放额度并通过邮件通知",
                self.window() or self,
            )
            confirm_email_box.yesButton.setText("确认发送")
            confirm_email_box.cancelButton.setText("返回检查")
            if not confirm_email_box.exec():
                return

        if mtype != REQUEST_MESSAGE_TYPE and not email:
            confirm_box = MessageBox(
                "未填写邮箱",
                "当前未输入邮箱地址，开发者可能无法联系你回复处理进度。是否继续发送？",
                self.window() or self,
            )
            confirm_box.yesButton.setText("继续发送")
            confirm_box.cancelButton.setText("返回填写")
            if not confirm_box.exec():
                return

        version_str = __VERSION__
        full_message = build_contact_message(
            version_str=version_str,
            message_type=mtype,
            email=email,
            donated=self.donated_cb.isChecked(),
            random_ip_user_id=self._random_ip_user_id,
            message=message,
            request_payment_method=request_payment_method,
            request_amount_text=request_amount_text,
            request_quota_text=request_quota_text,
            request_urgency_text=request_urgency_text,
        )

        api_url = CONTACT_API_URL
        if not api_url:
            InfoBar.error("", "联系API未配置", parent=self, position=InfoBarPosition.TOP, duration=3000)
            return
        manual_files_payload = [] if mtype == REQUEST_MESSAGE_TYPE else self._attachments.files_payload()
        auto_files_payload: list[tuple[str, tuple[str, bytes, str]]] = []
        if self._is_bug_report_type(mtype):
            try:
                auto_files_payload, _ = self._build_bug_report_auto_files_payload()
            except Exception as exc:
                self._cleanup_pending_temp_files()
                InfoBar.error("", f"自动导出附件失败：{exc}", parent=self, position=InfoBarPosition.TOP, duration=3500)
                return
        payload = {"message": full_message, "timestamp": datetime.now().isoformat()}
        files_payload = self._renumber_files_payload(manual_files_payload + auto_files_payload)

        self.send_btn.setFocus()

        self.send_btn.setEnabled(False)
        self.send_btn.setText("发送中...")
        self.send_spinner.show()
        self._update_send_button_state()

        self._current_message_type = mtype

        def _send():
            try:
                multipart_fields = build_contact_request_fields(
                    message=payload["message"],
                    timestamp=payload["timestamp"],
                    random_ip_user_id=self._random_ip_user_id,
                    files_payload=files_payload,
                )
                timeout = 20 if files_payload else 10
                resp = http_post(api_url, files=multipart_fields, timeout=timeout)
                if resp.status_code == 200:
                    self._sendFinished.emit(True, "")
                else:
                    self._sendFinished.emit(False, f"发送失败：{resp.status_code}")
            except Exception as exc:
                self._sendFinished.emit(False, f"发送失败：{exc}")
            finally:
                self._cleanup_pending_temp_files()

        threading.Thread(target=_send, daemon=True).start()
    def _clear_email_selection(self):
        """清除邮箱选择（由QTimer调用）"""
        try:
            self.email_edit.setSelection(0, 0)
        except (RuntimeError, AttributeError) as exc:
            log_suppressed_exception("_clear_email_selection: self.email_edit.setSelection(0, 0)", exc, level=logging.WARNING)
    def _focus_send_button(self):
        """聚焦发送按钮（由QTimer调用）"""
        try:
            self.send_btn.setFocus()
        except (RuntimeError, AttributeError) as exc:
            log_suppressed_exception("_focus_send_button: self.send_btn.setFocus()", exc, level=logging.WARNING)
    def _on_send_finished(self, success: bool, error_msg: str):
        """发送完成回调（在主线程执行）"""
        self.send_spinner.hide()
        self.send_btn.setText("发送")
        self._update_send_button_state()
        self._cleanup_pending_temp_files()

        if success:
            current_type = getattr(self, "_current_message_type", "")
            if current_type == REQUEST_MESSAGE_TYPE:
                msg = "申请已提交，请等待人工处理"
            else:
                msg = "消息已发送"
            if getattr(self, "_current_has_email", False):
                msg += "，开发者会优先通过邮箱联系你"
            InfoBar.success("", msg, parent=self, position=InfoBarPosition.TOP, duration=2500)
            if current_type == REQUEST_MESSAGE_TYPE:
                self.quotaRequestSucceeded.emit()
            if self._auto_clear_on_success:
                self._close_amount_rule_infobar()
                self.amount_edit.setText("")
                self.quantity_edit.clear()
                self.verify_code_edit.clear()
                self._clear_payment_method_selection()
                self._verify_code_requested = False
                self._verify_code_requested_email = ""
                urgency_default_index = self.urgency_combo.findText("中")
                if urgency_default_index >= 0:
                    self.urgency_combo.setCurrentIndex(urgency_default_index)
                self.message_edit.clear()
                self._attachments.clear()
                self._render_attachments_ui()
                self._reset_bug_report_auto_attach_defaults()
            self.sendSucceeded.emit()
        else:
            InfoBar.error("", error_msg, parent=self, position=InfoBarPosition.TOP, duration=3000)
    def _find_controller_host(self) -> Optional[QWidget]:
        widget: Optional[QWidget] = cast(QWidget, self)
        while widget is not None:
            if hasattr(widget, "controller"):
                return widget
            widget = widget.parentWidget()
        win = self.window()
        if isinstance(win, QWidget) and hasattr(win, "controller"):
            return win
        return None

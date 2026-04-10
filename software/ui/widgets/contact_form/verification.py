"""联系表单验证码流程。"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import QObject, QTimer
from qfluentwidgets import InfoBar, InfoBarPosition

from software.app.config import EMAIL_VERIFY_ENDPOINT
from software.ui.helpers.contact_api import post as http_post


class ContactFormVerificationMixin:
    if TYPE_CHECKING:
        send_verify_btn: Any
        verify_send_spinner: Any
        email_edit: Any
        _verify_code_sending: bool
        _verify_code_requested: bool
        _verify_code_requested_email: str
        _cooldown_timer: Any
        _cooldown_remaining: int
        _verifyCodeFinished: Any

        def _validate_email(self, email: str) -> bool: ...

    def _set_verify_code_sending(self, sending: bool):
        self._verify_code_sending = sending
        self.send_verify_btn.setEnabled(not sending)
        self.send_verify_btn.setText("发送中..." if sending else "发送验证码")
        self.verify_send_spinner.setVisible(sending)
    def _start_cooldown(self):
        """发送成功后启动30秒冷却，期间按钮不可点击并显示倒计时。"""
        self._cooldown_remaining = 30
        self.send_verify_btn.setEnabled(False)
        self.send_verify_btn.setText(f"重新发送({self._cooldown_remaining}s)")
        self._cooldown_timer = QTimer(cast(QObject, self))
        self._cooldown_timer.setInterval(1000)
        self._cooldown_timer.timeout.connect(self._on_cooldown_tick)
        self._cooldown_timer.start()
    def _on_cooldown_tick(self):
        self._cooldown_remaining -= 1
        if self._cooldown_remaining <= 0:
            if self._cooldown_timer is not None:
                self._cooldown_timer.stop()
            self._cooldown_timer = None
            self.send_verify_btn.setEnabled(True)
            self.send_verify_btn.setText("发送验证码")
        else:
            self.send_verify_btn.setText(f"重新发送({self._cooldown_remaining}s)")
    def _stop_cooldown(self):
        """停止冷却计时器并重置按钮状态。"""
        if self._cooldown_timer is not None:
            self._cooldown_timer.stop()
            self._cooldown_timer = None
        self._cooldown_remaining = 0
        self.send_verify_btn.setEnabled(True)
        self.send_verify_btn.setText("发送验证码")
    def _on_send_verify_clicked(self):
        if self._verify_code_sending:
            return

        email = (self.email_edit.text() or "").strip()
        if not email:
            InfoBar.warning("", "请先填写邮箱地址", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return
        if not self._validate_email(email):
            InfoBar.warning("", "邮箱格式不正确，请先检查", parent=self, position=InfoBarPosition.TOP, duration=2000)
            return

        if not EMAIL_VERIFY_ENDPOINT:
            InfoBar.error("", "验证码接口未配置", parent=self, position=InfoBarPosition.TOP, duration=2500)
            return

        self._verify_code_requested = False
        self._verify_code_requested_email = ""
        self._set_verify_code_sending(True)

        def _send_verify():
            try:
                resp = http_post(
                    EMAIL_VERIFY_ENDPOINT,
                    headers={"Content-Type": "application/json"},
                    json={"email": email},
                    timeout=10,
                )
                data = None
                try:
                    data = resp.json()
                except Exception:
                    data = None

                if resp.status_code == 200 and isinstance(data, dict) and bool(data.get("ok")):
                    self._verifyCodeFinished.emit(True, "", email)
                    return

                if isinstance(data, dict):
                    error_msg = str(data.get("error") or f"发送失败：{resp.status_code}")
                else:
                    error_msg = f"发送失败：{resp.status_code}"
                self._verifyCodeFinished.emit(False, error_msg, email)
            except Exception as exc:
                self._verifyCodeFinished.emit(False, f"发送失败：{exc}", email)

        threading.Thread(target=_send_verify, daemon=True).start()
    def _on_verify_code_finished(self, success: bool, error_msg: str, email: str):
        self._set_verify_code_sending(False)

        if success:
            self._verify_code_requested = True
            self._verify_code_requested_email = email
            InfoBar.success("", "验证码已发送，请查收并输入验证码", parent=self, position=InfoBarPosition.TOP, duration=2200)
            self._start_cooldown()
            return

        self._verify_code_requested = False
        self._verify_code_requested_email = ""
        normalized = (error_msg or "").strip().lower()
        if normalized == "invalid request":
            ui_msg = "邮箱参数无效，请检查邮箱后重试"
        elif normalized == "send mail failed":
            ui_msg = "邮件发送失败，请稍后重试"
        else:
            ui_msg = error_msg or "验证码发送失败，请稍后重试"
        InfoBar.error("", ui_msg, parent=self, position=InfoBarPosition.TOP, duration=2500)

"""ContactForm 验证码流程与冷却。"""

from __future__ import annotations

import threading
from typing import Any, Callable, Protocol, cast

from PySide6.QtCore import QObject, QTimer
from qfluentwidgets import InfoBarPosition


class _InfoBarLike(Protocol):
    def warning(self, *args, **kwargs) -> Any: ...
    def error(self, *args, **kwargs) -> Any: ...
    def success(self, *args, **kwargs) -> Any: ...


class _ResponseLike(Protocol):
    status_code: int

    def json(self) -> Any: ...


def _widget_module():
    from . import widget as widget_module

    return widget_module


def _info_bar(form: Any) -> _InfoBarLike:
    getter = getattr(form, "_info_bar", None)
    if callable(getter):
        return cast(_InfoBarLike, getter())
    return cast(_InfoBarLike, _widget_module().InfoBar)


def _email_verify_endpoint(form: Any) -> str:
    getter = getattr(form, "_email_verify_endpoint", None)
    if callable(getter):
        return cast(str, getter())
    return cast(str, _widget_module().EMAIL_VERIFY_ENDPOINT)


def _contact_http_post(form: Any) -> Callable[..., _ResponseLike]:
    getter = getattr(form, "_contact_http_post", None)
    if callable(getter):
        return cast(Callable[..., _ResponseLike], getter)
    return cast(Callable[..., _ResponseLike], _widget_module().http_post)


def set_verify_code_sending(form: Any, sending: bool) -> None:
    form._verify_code_sending = sending
    form.send_verify_btn.setEnabled(not sending)
    form.send_verify_btn.setText("发送中..." if sending else "发送验证码")
    form._set_verify_loading(sending)


def start_cooldown(form: Any) -> None:
    form._cooldown_remaining = 30
    form.send_verify_btn.setEnabled(False)
    form.send_verify_btn.setText(f"重新发送({form._cooldown_remaining}s)")
    form._cooldown_timer = QTimer(cast(QObject, form))
    form._cooldown_timer.setInterval(1000)
    form._cooldown_timer.timeout.connect(form._on_cooldown_tick)
    form._cooldown_timer.start()


def on_cooldown_tick(form: Any) -> None:
    form._cooldown_remaining -= 1
    if form._cooldown_remaining <= 0:
        if form._cooldown_timer is not None:
            form._cooldown_timer.stop()
        form._cooldown_timer = None
        form.send_verify_btn.setEnabled(True)
        form.send_verify_btn.setText("发送验证码")
        return
    form.send_verify_btn.setText(f"重新发送({form._cooldown_remaining}s)")


def stop_cooldown(form: Any) -> None:
    if form._cooldown_timer is not None:
        form._cooldown_timer.stop()
        form._cooldown_timer = None
    form._cooldown_remaining = 0
    form.send_verify_btn.setEnabled(True)
    form.send_verify_btn.setText("发送验证码")


def on_send_verify_clicked(form: Any) -> None:
    if form._verify_code_sending:
        return

    email = (form.email_edit.text() or "").strip()
    if not email:
        _info_bar(form).warning("", "请先填写邮箱地址", parent=form, position=InfoBarPosition.TOP, duration=2000)
        return
    if not form._validate_email(email):
        _info_bar(form).warning("", "邮箱格式不正确，请先检查", parent=form, position=InfoBarPosition.TOP, duration=2000)
        return
    if not _email_verify_endpoint(form):
        _info_bar(form).error("", "验证码接口未配置", parent=form, position=InfoBarPosition.TOP, duration=2500)
        return

    form._verify_code_requested = False
    form._verify_code_requested_email = ""
    set_verify_code_sending(form, True)

    def _send_verify() -> None:
        try:
            resp = _contact_http_post(form)(
                _email_verify_endpoint(form),
                headers={"Content-Type": "application/json"},
                json={"email": email},
                timeout=10,
            )
            try:
                data = resp.json()
            except Exception:
                data = None

            if resp.status_code == 200 and isinstance(data, dict) and bool(data.get("ok")):
                form._verifyCodeFinished.emit(True, "", email)
                return

            if isinstance(data, dict):
                error_msg = str(data.get("error") or f"发送失败：{resp.status_code}")
            else:
                error_msg = f"发送失败：{resp.status_code}"
            form._verifyCodeFinished.emit(False, error_msg, email)
        except Exception as exc:
            form._verifyCodeFinished.emit(False, f"发送失败：{exc}", email)

    threading.Thread(target=_send_verify, daemon=True).start()


def on_verify_code_finished(form: Any, success: bool, error_msg: str, email: str) -> None:
    set_verify_code_sending(form, False)

    if success:
        form._verify_code_requested = True
        form._verify_code_requested_email = email
        _info_bar(form).success("", "验证码已发送，请查收并输入验证码", parent=form, position=InfoBarPosition.TOP, duration=2200)
        start_cooldown(form)
        return

    form._verify_code_requested = False
    form._verify_code_requested_email = ""
    normalized = (error_msg or "").strip().lower()
    if normalized == "invalid request":
        ui_msg = "邮箱参数无效，请检查邮箱后重试"
    elif normalized == "send mail failed":
        ui_msg = "邮件发送失败，请稍后重试"
    else:
        ui_msg = error_msg or "验证码发送失败，请稍后重试"
    _info_bar(form).error("", ui_msg, parent=form, position=InfoBarPosition.TOP, duration=2500)

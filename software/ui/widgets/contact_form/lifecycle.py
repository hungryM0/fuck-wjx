"""ContactForm 生命周期与常用状态操作。"""

from __future__ import annotations

import logging
from typing import Any, Protocol, cast

from PySide6.QtWidgets import QWidget
from qfluentwidgets import InfoBarPosition
from software.logging.log_utils import log_suppressed_exception


class _InfoBarLike(Protocol):
    def warning(self, *args, **kwargs) -> Any: ...


def _widget_module():
    from . import widget as widget_module

    return widget_module


def _info_bar(form: Any) -> _InfoBarLike:
    getter = getattr(form, "_info_bar", None)
    if callable(getter):
        return cast(_InfoBarLike, getter())
    return cast(_InfoBarLike, _widget_module().InfoBar)


def _set_progress_ring_active(form: Any, widget: Any, loading: bool) -> None:
    setter = getattr(form, "_set_progress_ring_active", None)
    if callable(setter):
        setter(widget, loading)
        return
    _widget_module().set_indeterminate_progress_ring_active(widget, loading)


def _get_session_snapshot(form: Any) -> dict[str, Any]:
    getter = getattr(form, "_get_session_snapshot", None)
    if callable(getter):
        return cast(dict[str, Any], getter())
    return cast(dict[str, Any], _widget_module().get_session_snapshot())


def has_pending_async_work(form: Any) -> bool:
    return bool(getattr(form, "_send_in_progress", False) or getattr(form, "_verify_code_sending", False))


def show_pending_async_warning(form: Any) -> None:
    if getattr(form, "_send_in_progress", False):
        message = "正在发送反馈，请等待完成后再关闭"
    elif getattr(form, "_verify_code_sending", False):
        message = "正在发送验证码，请等待完成后再关闭"
    else:
        return
    _info_bar(form).warning(
        "",
        message,
        parent=form,
        position=InfoBarPosition.TOP,
        duration=2500,
    )


def set_status_loading(form: Any, loading: bool) -> None:
    _set_progress_ring_active(form, form.status_spinner, loading)


def set_send_loading(form: Any, loading: bool) -> None:
    _set_progress_ring_active(form, form.send_spinner, loading)


def set_verify_loading(form: Any, loading: bool) -> None:
    _set_progress_ring_active(form, form.verify_send_spinner, loading)


def stop_activity_indicators(form: Any) -> None:
    set_status_loading(form, False)
    set_send_loading(form, False)
    set_verify_loading(form, False)


def refresh_random_ip_user_id_hint(form: Any) -> None:
    """刷新消息框下方的随机IP账号提示。"""
    try:
        snapshot = _get_session_snapshot(form)
    except Exception as exc:
        log_suppressed_exception("refresh_random_ip_user_id_hint", exc, level=logging.WARNING)
        snapshot = {}
    user_id = int(snapshot.get("user_id") or 0)
    form._random_ip_user_id = user_id
    if user_id > 0:
        form.random_ip_user_id_label.setText(f"随机IP用户ID：{user_id}")
        form.random_ip_user_id_label.show()
    else:
        form.random_ip_user_id_label.hide()
    form._sync_donation_check_state()
    form._update_send_button_state()


def start_status_polling(form: Any) -> None:
    if getattr(form, "_polling_started", False):
        return
    form._polling_started = True
    set_status_loading(form, True)
    form.status_icon.hide()
    form.online_label.setText("作者当前在线状态：查询中...")
    form.online_label.setStyleSheet("color:#BA8303;")
    form._start_status_polling()


def stop_status_polling(form: Any) -> None:
    if not getattr(form, "_polling_started", False):
        return
    form._polling_started = False
    form._stop_status_polling()
    set_status_loading(form, False)


def close_all_infobars(form: Any) -> None:
    """关闭所有子 InfoBar 组件，避免线程泄漏。"""
    try:
        for child in form.findChildren(_info_bar(form)):
            try:
                child.close()
                child.deleteLater()
            except Exception:
                pass
    except Exception as exc:
        log_suppressed_exception("_close_all_infobars", exc, level=logging.WARNING)
    finally:
        form.amount_rule_hint.hide()


def find_controller_host(form: Any) -> QWidget | None:
    widget = cast(QWidget | None, form)
    while widget is not None:
        if hasattr(widget, "controller"):
            return widget
        widget = widget.parentWidget()
    win = form.window()
    if isinstance(win, QWidget) and hasattr(win, "controller"):
        return win
    return None

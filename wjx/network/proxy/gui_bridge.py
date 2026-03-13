"""GUI 交互桥接 - 弹窗、线程派发、开关控制。"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

from PySide6.QtCore import QEventLoop, QTimer

from wjx.network.proxy.auth import (
    RandomIPAuthError,
    activate_trial,
    format_random_ip_error,
    get_fresh_quota_snapshot,
    get_quota_snapshot,
    get_session_snapshot,
    has_authenticated_session,
    load_session_for_startup,
)
from wjx.network.proxy.quota import get_random_ip_counter_snapshot_local
from wjx.utils.logging.log_utils import (
    log_popup_confirm,
    log_popup_error,
    log_popup_info,
    log_popup_warning,
    log_suppressed_exception,
)

_COUNTER_REFRESH_TTL_SECONDS = 2.0
_counter_refresh_lock = threading.Lock()
_counter_refresh_cache: Optional[tuple[int, int, float]] = None


def _apply_counter_snapshot_to_gui(gui: Any, *, used: int, total: int, custom_api: bool = False) -> None:
    def _apply() -> None:
        handler = getattr(gui, "update_random_ip_counter", None)
        if not callable(handler):
            return
        safe_used = max(0, int(used or 0))
        safe_total = max(0, int(total or 0))
        handler(safe_used, safe_total, bool(custom_api))
        if not custom_api and safe_total > 0 and safe_used >= safe_total:
            _set_random_ip_enabled(gui, False)

    _schedule_on_gui_thread(gui, _apply)


def _set_random_ip_loading(gui: Any, loading: bool, message: str = "") -> None:
    if gui is None:
        return
    handler = getattr(gui, "set_random_ip_loading", None)
    if not callable(handler):
        return
    try:
        handler(bool(loading), str(message or ""))
    except Exception:
        logging.debug("更新随机IP加载提示失败", exc_info=True)


def _run_with_loading_dialog(
    gui: Any,
    *,
    title: str,
    message: str,
    worker: Callable[[], Any],
) -> Any:
    if gui is None or threading.current_thread() is not threading.main_thread():
        return worker()

    result: dict[str, Any] = {}
    done = threading.Event()

    def _background() -> None:
        try:
            result["value"] = worker()
        except Exception as exc:
            result["error"] = exc
        finally:
            done.set()

    _set_random_ip_loading(gui, True, message)
    threading.Thread(target=_background, daemon=True, name="RandomIPLoadingWorker").start()

    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(50)

    def _poll_done() -> None:
        if done.is_set():
            timer.stop()
            loop.quit()

    timer.timeout.connect(_poll_done)
    timer.start()
    try:
        loop.exec()
    finally:
        _set_random_ip_loading(gui, False, "")

    if "error" in result:
        raise result["error"]
    return result.get("value")


def _invoke_popup(gui: Any, kind: str, title: str, message: str) -> Any:
    gui_handler = getattr(gui, f"_log_popup_{kind}", None) if gui is not None else None
    if callable(gui_handler):
        try:
            return gui_handler(title, message)
        except Exception:
            logging.debug("GUI popup handler failed; falling back to global handler", exc_info=True)
    popup_map = {"info": log_popup_info, "warning": log_popup_warning, "error": log_popup_error, "confirm": log_popup_confirm}
    handler = popup_map.get(kind)
    return handler(title, message) if handler else None


def _set_random_ip_enabled(gui: Any, enabled: bool) -> None:
    if gui is None:
        return
    var = getattr(gui, "random_ip_enabled_var", None)
    if var and hasattr(var, "set"):
        try:
            var.set(bool(enabled))
        except Exception:
            logging.debug("无法更新随机IP开关状态", exc_info=True)


def _schedule_on_gui_thread(gui: Any, callback: Callable[[], None]) -> None:
    if gui is None:
        callback()
        return
    for attr in ("_post_to_ui_thread_async", "_post_to_ui_thread"):
        dispatcher = getattr(gui, attr, None)
        if callable(dispatcher):
            try:
                if attr == "_post_to_ui_thread_async":
                    dispatcher(callback)
                else:
                    threading.Thread(target=dispatcher, args=(callback,), daemon=True).start()
                return
            except Exception:
                logging.debug("派发到 GUI 线程失败", exc_info=True)
    try:
        callback()
    except Exception:
        logging.debug("执行回调失败", exc_info=True)


def confirm_random_ip_usage(gui: Any) -> bool:
    if gui is not None:
        setattr(gui, "_random_ip_disclaimer_ack", True)
    return True


def _build_counter_snapshot() -> tuple[int, int]:
    global _counter_refresh_cache
    from wjx.network.proxy.source import is_custom_proxy_api_active

    if not is_custom_proxy_api_active() and has_authenticated_session():
        now = time.monotonic()
        cached = _counter_refresh_cache
        if cached and (now - cached[2]) < _COUNTER_REFRESH_TTL_SECONDS:
            return cached[0], cached[1]
        with _counter_refresh_lock:
            now = time.monotonic()
            cached = _counter_refresh_cache
            if cached and (now - cached[2]) < _COUNTER_REFRESH_TTL_SECONDS:
                return cached[0], cached[1]
            try:
                snapshot = get_fresh_quota_snapshot()
                used = int(snapshot["used_quota"])
                total = int(snapshot["total_quota"])
                _counter_refresh_cache = (used, total, time.monotonic())
                return used, total
            except RandomIPAuthError as exc:
                log_suppressed_exception("_build_counter_snapshot: get_fresh_quota_snapshot", exc, level=logging.DEBUG)
                if exc.detail.startswith("refresh_token_persist_failed"):
                    raise
                snapshot = get_quota_snapshot()
                return int(snapshot["used_quota"]), int(snapshot["total_quota"])
            except Exception as exc:
                log_suppressed_exception("_build_counter_snapshot: get_fresh_quota_snapshot", exc, level=logging.DEBUG)
                snapshot = get_quota_snapshot()
                return int(snapshot["used_quota"]), int(snapshot["total_quota"])
    count, limit, _custom_api = get_random_ip_counter_snapshot_local()
    return int(count), int(limit)


def _open_quota_request_dialog(gui: Any, default_type: str = "额度申请") -> bool:
    handler = getattr(gui, "_open_contact_dialog", None) if gui is not None else None
    if callable(handler):
        try:
            return bool(handler(default_type))
        except Exception as exc:
            log_suppressed_exception("_open_quota_request_dialog passthrough", exc)
    adapter_handler = getattr(gui, "open_quota_request_dialog", None) if gui is not None else None
    if callable(adapter_handler):
        try:
            return bool(adapter_handler())
        except Exception as exc:
            log_suppressed_exception("_open_quota_request_dialog adapter open_quota_request_dialog", exc)
    _invoke_popup(gui, "warning", "需要申请额度", "请在“联系开发者”中提交随机IP额度申请。")
    return False


def on_random_ip_toggle(gui: Any) -> None:
    from wjx.network.proxy.source import is_custom_proxy_api_active

    if gui is None:
        return
    var = getattr(gui, "random_ip_enabled_var", None)
    enabled = bool(var.get() if var and hasattr(var, "get") else False)
    if not enabled:
        return
    if is_custom_proxy_api_active():
        if confirm_random_ip_usage(gui):
            return
        _set_random_ip_enabled(gui, False)
        return
    if not has_authenticated_session():
        activated = show_random_ip_activation_dialog(gui)
        if not activated:
            _set_random_ip_enabled(gui, False)
            return
    try:
        snapshot = _run_with_loading_dialog(
            gui,
            title="随机IP校验中",
            message="正在校验额度...",
            worker=get_fresh_quota_snapshot,
        )
    except Exception as exc:
        message = format_random_ip_error(exc)
        _invoke_popup(gui, "warning", "随机IP暂不可用", message)
        _set_random_ip_enabled(gui, False)
        try:
            refresh_ip_counter_display(gui)
        except Exception as refresh_exc:
            log_suppressed_exception("on_random_ip_toggle refresh counter", refresh_exc)
        return
    remaining = int(snapshot["remaining_quota"])
    if remaining <= 0:
        _invoke_popup(gui, "warning", "提示", "随机IP额度不足，请先补充额度后再启用。")
        _set_random_ip_enabled(gui, False)
        return
    if confirm_random_ip_usage(gui):
        return
    _set_random_ip_enabled(gui, False)


def _try_activate_trial(gui: Any = None) -> tuple[bool, bool]:
    global _counter_refresh_cache
    try:
        session = _run_with_loading_dialog(
            gui,
            title="领取试用中",
            message="正在领取试用...",
            worker=activate_trial,
        )
    except RandomIPAuthError as exc:
        message = format_random_ip_error(exc)
        if exc.detail in {"trial_already_claimed", "trial_already_used", "device_trial_already_claimed"}:
            _invoke_popup(gui, "warning", "试用已领取", message)
            return False, True
        _invoke_popup(gui, "error", "领取试用失败", message)
        return False, False
    except Exception as exc:
        _invoke_popup(gui, "error", "领取试用失败", f"领取试用失败：{exc}")
        return False, False

    quota_left = max(0, int(session.remaining_quota or 0))
    total_quota = max(int(session.total_quota or 0), quota_left)
    used_quota = max(0, total_quota - quota_left)
    _counter_refresh_cache = (used_quota, total_quota, time.monotonic())
    _apply_counter_snapshot_to_gui(gui, used=used_quota, total=total_quota, custom_api=False)
    _invoke_popup(gui, "info", "试用已领取", f"已领取免费试用，随机IP剩余额度：{quota_left}。")
    return True, False


def show_random_ip_activation_dialog(gui: Any = None) -> bool:
    if has_authenticated_session():
        return True

    activated, should_fallback_to_card = _try_activate_trial(gui)
    if activated:
        return True
    if not should_fallback_to_card:
        return False

    return show_quota_request_dialog(gui, require_confirm=False)


def show_quota_request_dialog(gui: Any = None, *, require_confirm: bool = True) -> bool:
    if require_confirm:
        prompt = (
            "默认随机IP现已改为账号额度模式。\n\n"
            "若免费试用已用完，请提交额度申请；开发者会根据你的随机IP用户ID人工补充额度。"
        )
        if not _invoke_popup(gui, "confirm", "申请随机IP额度", prompt):
            return False
    return _open_quota_request_dialog(gui, "额度申请")


def refresh_ip_counter_display(gui: Any) -> None:
    from wjx.network.proxy.source import is_custom_proxy_api_active

    load_session_for_startup()
    if gui is None:
        return

    def _compute_and_update():
        custom_api = is_custom_proxy_api_active()
        try:
            count, limit = _build_counter_snapshot()
        except RandomIPAuthError as exc:
            message = format_random_ip_error(exc)
            logging.error("随机IP会话刷新后保存失败：%s", message)
            _set_random_ip_enabled(gui, False)
            _invoke_popup(gui, "error", "随机IP登录状态保存失败", message)
            count, limit, _ = get_random_ip_counter_snapshot_local()
        except Exception as exc:
            message = format_random_ip_error(exc)
            logging.warning("刷新随机IP计数失败：%s", message)
            count, limit, _ = get_random_ip_counter_snapshot_local()
        _apply_counter_snapshot_to_gui(gui, used=count, total=limit, custom_api=custom_api)

    if threading.current_thread() is threading.main_thread():
        threading.Thread(target=_compute_and_update, daemon=True, name="IPCounterRefresh").start()
    else:
        _compute_and_update()


def handle_random_ip_submission(gui: Any, stop_signal: Optional[threading.Event]) -> None:
    from wjx.network.proxy.source import is_custom_proxy_api_active

    if gui is None or is_custom_proxy_api_active():
        return
    try:
        snapshot = get_session_snapshot()
        if not bool(snapshot.get("authenticated")):
            if stop_signal:
                stop_signal.set()
            _set_random_ip_enabled(gui, False)
            return
        refresh_ip_counter_display(gui)
    except Exception as exc:
        message = format_random_ip_error(exc)
        logging.warning("刷新随机IP状态失败：%s", message)

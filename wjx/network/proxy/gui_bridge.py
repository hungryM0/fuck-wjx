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
    format_quota_value,
    get_fresh_quota_snapshot,
    get_quota_snapshot,
    get_session_snapshot,
    has_authenticated_session,
    has_incomplete_session,
    is_quota_exhausted,
    load_session_for_startup,
    recover_incomplete_session,
    sync_quota_snapshot_from_server,
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
_counter_refresh_cache: Optional[tuple[float, float, float]] = None
_INCOMPLETE_SESSION_RETRY_LATER_DETAILS = {
    "site_daily_limit_exceeded",
    "upstream_rejected",
    "upstream_surplus_exhausted",
}


def _apply_counter_snapshot_to_gui(gui: Any, *, used: float, total: float, custom_api: bool = False) -> None:
    def _apply() -> None:
        safe_used = max(0.0, float(used or 0.0))
        safe_total = max(0.0, float(total or 0.0))
        gui.update_random_ip_counter(safe_used, safe_total, bool(custom_api))
        if not custom_api and safe_total > 0 and safe_used >= safe_total:
            _set_random_ip_enabled(gui, False)

    _schedule_on_gui_thread(gui, _apply)


def _set_random_ip_loading(gui: Any, loading: bool, message: str = "") -> None:
    if gui is None:
        return
    try:
        gui.set_random_ip_loading(bool(loading), str(message or ""))
    except Exception:
        logging.info("更新随机IP加载提示失败", exc_info=True)


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
    if gui is not None:
        try:
            if kind == "confirm":
                return gui.show_confirm_dialog(title, message)
            gui.show_message_dialog(title, message, level=kind)
            return None
        except Exception:
            logging.info("GUI popup handler failed; falling back to global handler", exc_info=True)
    popup_map = {"info": log_popup_info, "warning": log_popup_warning, "error": log_popup_error, "confirm": log_popup_confirm}
    handler = popup_map.get(kind)
    return handler(title, message) if handler else None


def _set_random_ip_enabled(gui: Any, enabled: bool) -> None:
    if gui is None:
        return
    try:
        gui.set_random_ip_enabled(bool(enabled))
    except Exception:
        logging.info("无法更新随机IP开关状态", exc_info=True)


def _schedule_on_gui_thread(gui: Any, callback: Callable[[], None]) -> None:
    if gui is None:
        callback()
        return
    try:
        gui.dispatch_to_ui_async(callback)
    except Exception:
        logging.info("派发到 GUI 线程失败", exc_info=True)


def _should_retry_incomplete_session_later(exc: BaseException) -> bool:
    if not isinstance(exc, RandomIPAuthError):
        return True
    detail = str(exc.detail or "").strip()
    if not detail:
        return True
    if detail.startswith(("network_error:", "http_", "invalid_response")):
        return True
    if detail.endswith("rate_limited"):
        return True
    return detail in _INCOMPLETE_SESSION_RETRY_LATER_DETAILS


def confirm_random_ip_usage(gui: Any) -> bool:
    return True


def _build_counter_snapshot() -> tuple[float, float]:
    global _counter_refresh_cache
    from wjx.network.proxy.source import is_custom_proxy_source

    if not is_custom_proxy_source() and (has_authenticated_session() or has_incomplete_session()):
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
                used = float(snapshot["used_quota"])
                total = float(snapshot["total_quota"])
                _counter_refresh_cache = (used, total, time.monotonic())
                return used, total
            except RandomIPAuthError as exc:
                logging.warning("随机IP额度校验失败，改用本地快照：detail=%s", exc.detail)
                if exc.detail.startswith("session_persist_failed"):
                    raise
                snapshot = get_quota_snapshot()
                return float(snapshot["used_quota"]), float(snapshot["total_quota"])
            except Exception as exc:
                logging.warning("随机IP额度校验异常，改用本地快照：error=%s", exc)
                snapshot = get_quota_snapshot()
                return float(snapshot["used_quota"]), float(snapshot["total_quota"])
    count, limit, _custom_api = get_random_ip_counter_snapshot_local()
    return float(count), float(limit)


def on_random_ip_toggle(gui: Any) -> None:
    global _counter_refresh_cache
    from wjx.network.proxy.source import is_custom_proxy_source

    if gui is None:
        return
    enabled = bool(gui.is_random_ip_enabled())
    if not enabled:
        return
    if is_custom_proxy_source():
        if confirm_random_ip_usage(gui):
            return
        _set_random_ip_enabled(gui, False)
        return
    if not has_authenticated_session():
        activated = show_random_ip_activation_dialog(gui)
        if not activated:
            _set_random_ip_enabled(gui, False)
            return
    local_used, local_total, local_custom_api = get_random_ip_counter_snapshot_local()
    _apply_counter_snapshot_to_gui(gui, used=local_used, total=local_total, custom_api=local_custom_api)
    try:
        snapshot = _run_with_loading_dialog(
            gui,
            title="随机IP校验中",
            message="正在同步服务端额度...",
            worker=sync_quota_snapshot_from_server,
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
    used_quota = float(snapshot.get("used_quota") or 0.0)
    total_quota = float(snapshot.get("total_quota") or 0.0)
    _counter_refresh_cache = (used_quota, total_quota, time.monotonic())
    _apply_counter_snapshot_to_gui(gui, used=used_quota, total=total_quota, custom_api=False)
    if is_quota_exhausted({"authenticated": True, **snapshot}):
        _invoke_popup(gui, "warning", "提示", "随机IP已用额度已达到上限，请先补充额度后再启用。")
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

    total_quota = max(float(session.total_quota or 0.0), 0.0)
    used_quota = max(0.0, float(session.used_quota or 0.0))
    _counter_refresh_cache = (used_quota, total_quota, time.monotonic())
    _apply_counter_snapshot_to_gui(gui, used=used_quota, total=total_quota, custom_api=False)
    if total_quota > 0:
        _invoke_popup(
            gui,
            "info",
            "试用已领取",
            f"已领取免费试用，当前随机IP已用/总额度：{format_quota_value(used_quota)}/{format_quota_value(total_quota)}。",
        )
    else:
        _invoke_popup(gui, "info", "试用已领取", "已领取免费试用，随机IP账号已绑定到当前设备。")
    return True, False


def show_random_ip_activation_dialog(gui: Any = None) -> bool:
    if has_authenticated_session():
        return True
    if has_incomplete_session():
        try:
            _run_with_loading_dialog(
                gui,
                title="校验登录状态中",
                message="正在检查本机随机IP账号信息...",
                worker=recover_incomplete_session,
            )
            return True
        except Exception as exc:
            message = format_random_ip_error(exc)
            detail = exc.detail if isinstance(exc, RandomIPAuthError) else str(exc)
            logging.warning("随机IP半残会话恢复失败：detail=%s", detail)
            _invoke_popup(gui, "warning", "随机IP账号状态异常", message)
            if _should_retry_incomplete_session_later(exc):
                return False

    activated, should_fallback_to_card = _try_activate_trial(gui)
    if activated:
        return True
    if not should_fallback_to_card:
        return False

    return _invoke_quota_request_form(gui)


def _invoke_quota_request_form(gui: Any) -> bool:
    if gui is None:
        return False
    try:
        return bool(gui.open_quota_request_form())
    except Exception as exc:
        log_suppressed_exception("_invoke_quota_request_form", exc)
        _invoke_popup(gui, "warning", "需要申请额度", "请在“联系开发者”中提交随机IP额度申请。")
        return False


def refresh_ip_counter_display(gui: Any) -> None:
    from wjx.network.proxy.source import is_custom_proxy_source

    load_session_for_startup()
    if gui is None:
        return

    def _compute_and_update():
        custom_api = is_custom_proxy_source()
        try:
            count, limit = _build_counter_snapshot()
        except RandomIPAuthError as exc:
            message = format_random_ip_error(exc)
            logging.error("随机IP账号状态校验失败：%s", message)
            _set_random_ip_enabled(gui, False)
            _invoke_popup(gui, "error", "随机IP账号状态异常", message)
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
    from wjx.network.proxy.source import is_custom_proxy_source

    if gui is None or is_custom_proxy_source():
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


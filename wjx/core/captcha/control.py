import logging
import threading
from typing import Any, Optional

import wjx.core.state as state
from wjx.network.random_ip import on_random_ip_toggle
from wjx.utils.logging.log_utils import log_popup_confirm, log_popup_warning


def _show_aliyun_captcha_popup(message: str) -> None:
    """在首次检测到阿里云智能验证时弹窗提醒用户。"""
    with state._aliyun_captcha_stop_lock:
        if state._aliyun_captcha_popup_shown:
            return
        state._aliyun_captcha_popup_shown = True
    try:
        log_popup_warning("智能验证提示", message)
    except Exception:
        logging.warning("弹窗提示阿里云智能验证失败", exc_info=True)


def _trigger_aliyun_captcha_stop(
    gui_instance: Optional[Any],
    stop_signal: Optional[threading.Event],
) -> None:
    """检测到阿里云智能验证时触发全局暂停，并提示用户启用随机 IP。"""
    with state._aliyun_captcha_stop_lock:
        if state._aliyun_captcha_stop_triggered:
            return
        state._aliyun_captcha_stop_triggered = True

    try:
        state._resume_after_aliyun_captcha_stop = True
        state._resume_snapshot = {
            "url": state.url,
            "target": state.target_num,
            "cur_num": state.cur_num,
            "cur_fail": state.cur_fail,
        }
    except Exception:
        state._resume_after_aliyun_captcha_stop = True
        state._resume_snapshot = {}

    logging.warning("检测到阿里云智能验证，已触发全局暂停。")

    message = (
        "检测到阿里云智能验证，为避免继续失败提交已暂停所有任务。\n\n"
        "建议开启/保持随机 IP，并在处理完验证后点击主页的“继续”按钮恢复执行。\n"
    )

    def _notify():
        try:
            if gui_instance and hasattr(gui_instance, "pause_run"):
                gui_instance.pause_run("触发智能验证")
        except Exception:
            logging.debug("阿里云智能验证触发暂停失败", exc_info=True)
        try:
            if threading.current_thread() is not threading.main_thread():
                return
            if gui_instance and hasattr(gui_instance, "_log_popup_confirm"):
                confirmed = bool(gui_instance._log_popup_confirm("智能验证提示", message, icon="warning"))
            else:
                confirmed = bool(log_popup_confirm("智能验证提示", message, icon="warning"))

            if confirmed and gui_instance:
                try:
                    var = getattr(gui_instance, "random_ip_enabled_var", None)
                    if var is not None and hasattr(var, "set"):
                        var.set(True)
                    on_random_ip_toggle(gui_instance)
                except Exception:
                    logging.warning("自动启用随机IP失败", exc_info=True)
        except Exception:
            logging.warning("弹窗提示用户启用随机IP失败")

    dispatcher = getattr(gui_instance, "_post_to_ui_thread", None) if gui_instance else None
    if callable(dispatcher):
        try:
            dispatcher(_notify)
            return
        except Exception:
            logging.debug("派发阿里云停止事件到主线程失败", exc_info=True)
    root = getattr(gui_instance, "root", None) if gui_instance else None
    if root is not None and threading.current_thread() is threading.main_thread():
        try:
            root.after(0, _notify)
            return
        except Exception:
            logging.debug("root.after 派发阿里云停止事件失败", exc_info=True)
    _notify()


def _handle_aliyun_captcha_detected(gui_instance: Optional[Any], stop_signal: Optional[threading.Event]) -> None:
    """
    统一处理阿里云智能验证命中后的策略：
    - 默认（pause_on_aliyun_captcha=True）：全局暂停执行并提示用户启用随机 IP；
    - 关闭该开关：不全局暂停，仅记录告警（可能会导致后续持续失败）。
    """
    if state.pause_on_aliyun_captcha:
        _trigger_aliyun_captcha_stop(gui_instance, stop_signal)
        return
    logging.warning("检测到阿里云智能验证，但已关闭“触发智能验证自动暂停”，将继续尝试后续提交。")

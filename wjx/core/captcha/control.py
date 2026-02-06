import logging
import threading
from typing import Any, Optional

import wjx.core.state as state
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

    logging.warning("检测到阿里云智能验证，已触发全局暂停。")

    # 关键兜底：先立即停止所有工作线程，再做 UI 提示。
    # 避免 UI 线程忙/派发超时时没有真正停下。
    if stop_signal and not stop_signal.is_set():
        stop_signal.set()
        logging.warning("智能验证命中：已设置 stop_signal，任务将立即停止")
    try:
        if gui_instance and hasattr(gui_instance, "pause_run"):
            gui_instance.pause_run("触发智能验证")
            logging.warning("智能验证命中：已调用 pause_run")
    except Exception:
        logging.debug("阿里云智能验证触发暂停失败", exc_info=True)

    def _notify():
        try:
            if threading.current_thread() is not threading.main_thread():
                return
            
            # 先检查当前随机IP状态和配额情况
            from wjx.utils.system.registry_manager import RegistryManager
            from wjx.network.random_ip import get_random_ip_limit
            
            var = getattr(gui_instance, "random_ip_enabled_var", None) if gui_instance else None
            is_enabled = bool(var.get() if var and hasattr(var, "get") else False)
            
            # 如果已经启用随机IP，只需提示暂停
            if is_enabled:
                message = (
                    "检测到阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                    "随机 IP 已启用，建议处理完验证后重新启动任务。\n"
                )
                if gui_instance and hasattr(gui_instance, "_log_popup_warning"):
                    gui_instance._log_popup_warning("智能验证提示", message, icon="warning")
                else:
                    log_popup_warning("智能验证提示", message)
                return
            
            # 检查配额情况
            is_unlimited = RegistryManager.is_quota_unlimited()
            count = RegistryManager.read_submit_count()
            limit = max(1, get_random_ip_limit())
            quota_exceeded = (not is_unlimited) and (count >= limit)
            
            # 根据配额情况构建不同的提示消息
            if quota_exceeded:
                message = (
                    "检测到阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                    f"建议启用随机 IP，但当前配额已用完（{count}/{limit}）。\n"
                    "请先验证卡密解锁额度后再启用随机 IP。\n\n"
                    "是否现在前往验证卡密？"
                )
                if gui_instance and hasattr(gui_instance, "_log_popup_confirm"):
                    go_verify = bool(gui_instance._log_popup_confirm("智能验证提示", message, icon="warning"))
                else:
                    go_verify = bool(log_popup_confirm("智能验证提示", message, icon="warning"))
                
                if go_verify and gui_instance:
                    # 尝试显示卡密验证对话框
                    try:
                        # 寻找主窗口上的账号页面切换方法
                        if hasattr(gui_instance, "switch_to_account_page"):
                            gui_instance.switch_to_account_page()
                        elif hasattr(gui_instance, "stack") and hasattr(gui_instance.stack, "setCurrentIndex"):
                            # 尝试切换到账号页面（通常索引为1）
                            gui_instance.stack.setCurrentIndex(1)
                        logging.info("已引导用户前往账号页面验证卡密")
                    except Exception:
                        logging.warning("切换到账号页面失败", exc_info=True)
                return
            
            # 配额充足，询问是否启用随机IP（包含免责声明）
            message = (
                "检测到阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                "建议启用随机 IP 并在处理完验证后重新启动任务。\n\n"
                "启用前请确认：\n"
                "1) 代理来源于网络，确认启用视为已知悉风险并自愿承担后果\n"
                "2) 禁止用于污染他人问卷数据，否则可能被封禁或承担法律责任\n"
                "3) 随机IP维护成本高昂，如需大量使用需要付费\n\n"
                "是否启用随机 IP 提交？"
            )
            
            if gui_instance and hasattr(gui_instance, "_log_popup_confirm"):
                confirmed = bool(gui_instance._log_popup_confirm("智能验证提示", message, icon="warning"))
            else:
                confirmed = bool(log_popup_confirm("智能验证提示", message, icon="warning"))

            if confirmed and gui_instance:
                try:
                    # 设置免责声明已确认标记，避免on_random_ip_toggle再次弹窗
                    setattr(gui_instance, "_random_ip_disclaimer_ack", True)
                    
                    # 启用随机IP
                    if var is not None and hasattr(var, "set"):
                        var.set(True)
                    
                    # 刷新显示
                    from wjx.network.random_ip import refresh_ip_counter_display
                    refresh_ip_counter_display(gui_instance)
                    
                    logging.info("智能验证触发：用户已确认启用随机IP")
                except Exception:
                    logging.warning("自动启用随机IP失败", exc_info=True)
        except Exception:
            logging.warning("弹窗提示用户启用随机IP失败", exc_info=True)

    dispatcher = getattr(gui_instance, "_post_to_ui_thread_async", None) if gui_instance else None
    if not callable(dispatcher):
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

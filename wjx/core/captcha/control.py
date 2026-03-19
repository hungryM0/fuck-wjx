"""验证码流程控制 - 检测与处理阿里云智能验证"""
import logging
import threading
from typing import Any, Optional

from wjx.core.task_context import TaskContext
from wjx.utils.event_bus import bus as _event_bus, EVENT_CAPTCHA_DETECTED
from wjx.utils.logging.log_utils import log_popup_confirm, log_popup_warning


def _show_aliyun_captcha_popup(ctx: TaskContext, message: str) -> None:
    """在首次检测到阿里云智能验证时弹窗提醒用户。"""
    with ctx._aliyun_captcha_stop_lock:
        if ctx._aliyun_captcha_popup_shown:
            return
        ctx._aliyun_captcha_popup_shown = True
    try:
        log_popup_warning("智能验证提示", message)
    except Exception:
        logging.warning("弹窗提示阿里云智能验证失败", exc_info=True)


def _trigger_aliyun_captcha_stop(
    ctx: TaskContext,
    gui_instance: Optional[Any],
    stop_signal: Optional[threading.Event],
) -> None:
    """检测到阿里云智能验证时触发全局暂停，并提示用户启用随机 IP。"""
    with ctx._aliyun_captcha_stop_lock:
        if ctx._aliyun_captcha_stop_triggered:
            return
        ctx._aliyun_captcha_stop_triggered = True

    logging.warning("检测到阿里云智能验证，已触发全局暂停。")

    # 通过 EventBus 广播验证码事件
    _event_bus.emit(EVENT_CAPTCHA_DETECTED, ctx=ctx)

    # 关键兜底：先立即停止所有工作线程，再做 UI 提示。
    # 避免 UI 线程忙/派发超时时没有真正停下。
    if stop_signal and not stop_signal.is_set():
        stop_signal.set()
        logging.warning("智能验证命中：已设置 stop_signal，任务将立即停止")
    try:
        if gui_instance:
            gui_instance.pause_run("触发智能验证")
            logging.warning("智能验证命中：已调用 pause_run")
    except Exception:
        logging.info("阿里云智能验证触发暂停失败", exc_info=True)

    def _notify():
        try:
            if threading.current_thread() is not threading.main_thread():
                return
            
            # 先检查当前随机IP状态和配额情况
            from wjx.network.proxy import get_random_ip_counter_snapshot_local
            from wjx.network.proxy.auth import has_authenticated_session, is_quota_exhausted

            is_enabled = bool(gui_instance.is_random_ip_enabled()) if gui_instance else False
            
            # 如果已经启用随机IP，只需提示暂停
            if is_enabled:
                message = (
                    "检测到阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                    "随机 IP 已启用，建议处理完验证后重新启动任务。\n"
                )
                if gui_instance:
                    gui_instance.show_message_dialog("智能验证提示", message, level="warning")
                else:
                    log_popup_warning("智能验证提示", message)
                return

            used, total, custom_api = get_random_ip_counter_snapshot_local()
            if custom_api:
                message = (
                    "检测到阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                    "你当前使用的是自定义代理接口，请处理完验证后重新启动任务。"
                )
                if gui_instance:
                    gui_instance.show_message_dialog("智能验证提示", message, level="warning")
                else:
                    log_popup_warning("智能验证提示", message)
                return

            if not has_authenticated_session():
                message = (
                    "检测到阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                    "默认随机IP现已需要先领取免费试用或提交额度申请。\n"
                    "请先完成试用激活或额度申请，或切换自定义代理接口后再试。"
                )
                if gui_instance:
                    gui_instance.show_message_dialog("智能验证提示", message, level="warning")
                else:
                    log_popup_warning("智能验证提示", message)
                return

            quota_exceeded = is_quota_exhausted(
                {"authenticated": True, "used_quota": float(used or 0.0), "total_quota": float(total or 0.0)}
            )

            # 根据配额情况构建不同的提示消息
            if quota_exceeded:
                message = (
                    "检测到阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                    "建议启用随机 IP，但当前随机IP已用额度已达到上限。\n"
                    "请先补充额度后再启用随机 IP。"
                )
                if gui_instance:
                    gui_instance.show_message_dialog("智能验证提示", message, level="warning")
                else:
                    log_popup_warning("智能验证提示", message)
                return
            
            # 配额充足，询问是否启用随机IP（包含免责声明）
            message = (
                "检测到触发阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                "建议启用随机 IP 后重新启动任务。\n"
                "是否立即启用随机 IP 功能？"
            )
            
            if gui_instance:
                confirmed = bool(gui_instance.show_confirm_dialog("智能验证提示", message))
            else:
                confirmed = bool(log_popup_confirm("智能验证提示", message))

            if confirmed and gui_instance:
                try:
                    # 启用随机IP
                    gui_instance.set_random_ip_enabled(True)

                    # 刷新显示
                    from wjx.network.proxy import refresh_ip_counter_display
                    refresh_ip_counter_display(gui_instance)
                    
                    logging.info("智能验证触发：用户已确认启用随机IP")
                except Exception:
                    logging.warning("自动启用随机IP失败", exc_info=True)
        except Exception:
            logging.warning("弹窗提示用户启用随机IP失败", exc_info=True)

    if gui_instance:
        try:
            gui_instance.dispatch_to_ui_async(_notify)
            return
        except Exception:
            logging.info("派发阿里云停止事件到主线程失败", exc_info=True)
    _notify()


def _handle_aliyun_captcha_detected(
    ctx: TaskContext,
    gui_instance: Optional[Any],
    stop_signal: Optional[threading.Event],
) -> None:
    """
    统一处理阿里云智能验证命中后的策略：
    - 随机IP开启（random_proxy_ip_enabled=True）：仅记录日志，不全局暂停、不弹窗；
    - 默认（pause_on_aliyun_captcha=True）：全局暂停执行并提示用户启用随机 IP；
    - 关闭该开关：不全局暂停，仅记录告警（可能会导致后续持续失败）。
    """
    if bool(getattr(ctx, "random_proxy_ip_enabled", False)):
        logging.warning("随机IP模式命中阿里云智能验证：按配置仅记录日志，不暂停、不弹窗。")
        return
    if not bool(getattr(ctx, "pause_on_aliyun_captcha", True)):
        logging.warning("检测到阿里云智能验证：pause_on_aliyun_captcha=False，仅记录告警。")
        return

    _trigger_aliyun_captcha_stop(ctx, gui_instance, stop_signal)



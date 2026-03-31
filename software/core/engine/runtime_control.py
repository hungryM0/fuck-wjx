"""运行时流程控制 - 暂停、停止、重试等状态管理"""
import logging
import threading
import time
from typing import Any, Optional

from software.core.task import EVENT_TARGET_REACHED, TaskContext, bus as _event_bus
from software.logging.log_utils import log_suppressed_exception

FAILURE_REASON_DEVICE_QUOTA_LIMIT = "device_quota_limit"


def _is_headless_mode(ctx: Optional[TaskContext]) -> bool:
    """当前任务是否启用无头模式。"""
    return bool(ctx is not None and getattr(ctx, "headless_mode", False))


def _timed_mode_active(ctx: TaskContext) -> bool:
    return bool(ctx.timed_mode_enabled)


def _handle_submission_failure(
    ctx: TaskContext,
    stop_signal: Optional[threading.Event],
    thread_name: Optional[str] = None,
    *,
    failure_reason: str = "",
    status_text: str = "失败重试",
    log_message: str = "",
) -> bool:
    """
    递增连续失败计数；当开启失败止损时超过阈值会触发停止。
    返回 True 表示已触发强制停止。
    """
    normalized_reason = str(failure_reason or "").strip().lower()
    with ctx.lock:
        ctx.cur_fail += 1
        if normalized_reason == FAILURE_REASON_DEVICE_QUOTA_LIMIT:
            ctx.device_quota_fail_count = max(0, int(ctx.device_quota_fail_count or 0)) + 1
        message = str(log_message or "").strip()
        if message:
            logging.warning("%s", message)
        if ctx.stop_on_fail_enabled:
            logging.warning(
                "已连续失败%s次，连续失败达到%s次将强制停止",
                ctx.cur_fail,
                int(ctx.fail_threshold),
            )
        else:
            logging.warning("已连续失败%s次（失败止损已关闭）", ctx.cur_fail)
    if thread_name:
        try:
            ctx.increment_thread_fail(thread_name, status_text=status_text)
        except Exception:
            logging.info("更新线程失败计数失败", exc_info=True)
    if ctx.stop_on_fail_enabled and ctx.cur_fail >= ctx.fail_threshold:
        logging.critical("连续失败次数过多，强制停止，请检查配置是否正确")
        if stop_signal:
            stop_signal.set()
        return True
    return False


def _wait_if_paused(gui_instance: Optional[Any], stop_signal: Optional[threading.Event]) -> None:
    try:
        if gui_instance:
            gui_instance.wait_if_paused(stop_signal)
    except Exception as exc:
        log_suppressed_exception("runtime_control._wait_if_paused", exc)


def _trigger_target_reached_stop(
    ctx: TaskContext,
    stop_signal: Optional[threading.Event],
    gui_instance: Optional[Any] = None,
) -> None:
    """达到目标份数时触发全局立即停止。"""
    with ctx._target_reached_stop_lock:
        if ctx._target_reached_stop_triggered:
            if stop_signal:
                stop_signal.set()
            return
        ctx._target_reached_stop_triggered = True

    if stop_signal:
        stop_signal.set()

    # 通过 EventBus 通知上层
    _event_bus.emit(EVENT_TARGET_REACHED, ctx=ctx)


def _sleep_with_stop(stop_signal: Optional[threading.Event], seconds: float) -> bool:
    """带停止信号的睡眠，返回 True 表示被中断。"""
    if seconds <= 0:
        return False
    if stop_signal:
        interrupted = stop_signal.wait(seconds)
        return bool(interrupted and stop_signal.is_set())
    time.sleep(seconds)
    return False




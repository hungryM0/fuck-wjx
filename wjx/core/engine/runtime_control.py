"""运行时流程控制 - 暂停、停止、重试等状态管理"""
import logging
import threading
import time
from typing import Any, Optional

import wjx.core.state as state
from wjx.utils.logging.log_utils import log_suppressed_exception


def _is_fast_mode() -> bool:
    # 极速模式：时长控制/随机IP关闭且时间间隔为0时自动启用
    return (
        not state.duration_control_enabled
        and not state.random_proxy_ip_enabled
        and state.submit_interval_range_seconds == (0, 0)
        and state.answer_duration_range_seconds == (0, 0)
    )


def _timed_mode_active() -> bool:
    return bool(state.timed_mode_enabled)


def _handle_submission_failure(stop_signal: Optional[threading.Event]) -> bool:
    """
    递增失败计数；当开启失败止损时超过阈值会触发停止。
    返回 True 表示已触发强制停止。
    """
    with state.lock:
        state.cur_fail += 1
        if state.stop_on_fail_enabled:
            print(f"已失败{state.cur_fail}次, 失败次数达到{int(state.fail_threshold)}次将强制停止")
        else:
            print(f"已失败{state.cur_fail}次（失败止损已关闭）")
    if state.stop_on_fail_enabled and state.cur_fail >= state.fail_threshold:
        logging.critical("失败次数过多，强制停止，请检查配置是否正确")
        if stop_signal:
            stop_signal.set()
        return True
    return False


def _wait_if_paused(gui_instance: Optional[Any], stop_signal: Optional[threading.Event]) -> None:
    try:
        if gui_instance and hasattr(gui_instance, "wait_if_paused"):
            gui_instance.wait_if_paused(stop_signal)
    except Exception as exc:
        log_suppressed_exception("runtime_control._wait_if_paused", exc)


def _trigger_target_reached_stop(
    gui_instance: Optional[Any],
    stop_signal: Optional[threading.Event],
) -> None:
    """达到目标份数时触发全局立即停止。"""
    with state._target_reached_stop_lock:
        if state._target_reached_stop_triggered:
            if stop_signal:
                stop_signal.set()
            return
        state._target_reached_stop_triggered = True

    if stop_signal:
        stop_signal.set()

    def _notify():
        try:
            if gui_instance and hasattr(gui_instance, "force_stop_immediately"):
                gui_instance.force_stop_immediately(reason="任务完成")
        except Exception:
            logging.debug("达到目标份数时触发强制停止失败", exc_info=True)

    dispatcher = getattr(gui_instance, "_post_to_ui_thread_async", None) if gui_instance else None
    if callable(dispatcher):
        try:
            dispatcher(_notify)
            return
        except Exception:
            logging.debug("派发任务完成事件到主线程失败", exc_info=True)
    dispatcher = getattr(gui_instance, "_post_to_ui_thread", None) if gui_instance else None
    if callable(dispatcher):
        try:
            dispatcher(_notify)
            return
        except Exception:
            logging.debug("派发任务完成事件到主线程失败", exc_info=True)
    root = getattr(gui_instance, "root", None) if gui_instance else None
    if root is not None and threading.current_thread() is threading.main_thread():
        try:
            root.after(0, _notify)
            return
        except Exception as exc:
            log_suppressed_exception("runtime_control._trigger_target_reached_stop root.after", exc)
    _notify()


def _sleep_with_stop(stop_signal: Optional[threading.Event], seconds: float) -> bool:
    """带停止信号的睡眠，返回 True 表示被中断。"""
    if seconds <= 0:
        return False
    if stop_signal:
        interrupted = stop_signal.wait(seconds)
        return bool(interrupted and stop_signal.is_set())
    time.sleep(seconds)
    return False

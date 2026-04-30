"""运行时流程控制 - 暂停、停止、重试等状态管理"""
import threading
import time
from typing import Any, Optional

from software.core.task import ExecutionState
from software.logging.log_utils import log_suppressed_exception

def _is_headless_mode(ctx: Optional[ExecutionState]) -> bool:
    """当前任务是否启用无头模式。"""
    if ctx is None:
        return False
    config = getattr(ctx, "config", None)
    if config is not None and hasattr(config, "headless_mode"):
        return bool(getattr(config, "headless_mode", False))
    return bool(getattr(ctx, "headless_mode", False))


def _wait_if_paused(gui_instance: Optional[Any], stop_signal: Optional[threading.Event]) -> None:
    try:
        if gui_instance:
            gui_instance.wait_if_paused(stop_signal)
    except Exception as exc:
        log_suppressed_exception("runtime_control._wait_if_paused", exc)


def _sleep_with_stop(stop_signal: Optional[threading.Event], seconds: float) -> bool:
    """带停止信号的睡眠，返回 True 表示被中断。"""
    if seconds <= 0:
        return False
    if stop_signal:
        interrupted = stop_signal.wait(seconds)
        return bool(interrupted and stop_signal.is_set())
    time.sleep(seconds)
    return False




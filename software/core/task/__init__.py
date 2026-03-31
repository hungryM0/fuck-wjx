"""任务模型与事件。"""

from software.core.task.event_bus import (
    EVENT_CAPTCHA_DETECTED,
    EVENT_IP_COUNTER_UPDATED,
    EVENT_SUBMIT_FAILURE,
    EVENT_SUBMIT_SUCCESS,
    EVENT_TARGET_REACHED,
    EVENT_TASK_PAUSED,
    EVENT_TASK_RESUMED,
    EVENT_TASK_STARTED,
    EVENT_TASK_STOPPED,
    EventBus,
    bus,
)
from software.core.task.task_context import ProxyLease, TaskContext, ThreadProgressState

__all__ = [
    "EventBus",
    "bus",
    "EVENT_TASK_STARTED",
    "EVENT_TASK_STOPPED",
    "EVENT_TASK_PAUSED",
    "EVENT_TASK_RESUMED",
    "EVENT_TARGET_REACHED",
    "EVENT_CAPTCHA_DETECTED",
    "EVENT_SUBMIT_SUCCESS",
    "EVENT_SUBMIT_FAILURE",
    "EVENT_IP_COUNTER_UPDATED",
    "ProxyLease",
    "TaskContext",
    "ThreadProgressState",
]


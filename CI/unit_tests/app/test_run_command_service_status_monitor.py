from __future__ import annotations

import threading
import time
from typing import Any

from software.core.task import ExecutionState
from software.ui.controller.run_command_service import RunCommandService


def test_status_snapshot_monitor_publishes_thread_progress_changes() -> None:
    service = object.__new__(RunCommandService)
    state = ExecutionState()
    service._execution_state = state
    snapshots: list[list[dict[str, Any]]] = []

    def dispatch(callback):
        callback()

    def emit_status_snapshot() -> None:
        snapshots.append(state.snapshot_thread_progress())

    service._dispatch_to_ui_async = dispatch
    service.emit_status_snapshot = emit_status_snapshot
    stop_signal = threading.Event()

    monitor = threading.Thread(
        target=service._status_snapshot_monitor_loop,
        args=(state, stop_signal),
        daemon=True,
    )
    monitor.start()

    state.update_thread_step("Slot-1", 1, 3, status_text="填写问卷", running=True)
    state.increment_thread_success("Slot-1", status_text="提交成功")

    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        if snapshots and snapshots[-1] and snapshots[-1][0]["success_count"] == 1:
            break
        time.sleep(0.02)

    stop_signal.set()
    state.notify_runtime_change()
    monitor.join(timeout=1.0)

    assert snapshots
    latest = snapshots[-1][0]
    assert latest["thread_name"] == "Slot-1"
    assert latest["success_count"] == 1
    assert latest["status_text"] == "提交成功"

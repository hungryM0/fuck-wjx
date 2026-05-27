"""Runtime helpers for reverse fill."""

from __future__ import annotations

from collections import deque
from typing import Any, Optional

from software.core.reverse_fill.schema import ReverseFillAnswer, ReverseFillRuntimeState, ReverseFillSpec


def create_reverse_fill_runtime_state(spec: Optional[ReverseFillSpec]) -> Optional[ReverseFillRuntimeState]:
    if spec is None:
        return None
    runtime = ReverseFillRuntimeState(spec=spec)
    for sample in list(spec.samples or []):
        runtime.samples_by_row_number[int(sample.data_row_number)] = sample
        runtime.queued_row_numbers.append(int(sample.data_row_number))
    if not isinstance(runtime.queued_row_numbers, deque):
        runtime.queued_row_numbers = deque(runtime.queued_row_numbers)
    return runtime


def resolve_current_reverse_fill_answer(
    task_ctx: Any,
    question_num: int,
    *,
    thread_name: str = "",
) -> Optional[ReverseFillAnswer]:
    if task_ctx is None:
        return None
    getter = getattr(task_ctx, "get_reverse_fill_answer", None)
    if not callable(getter):
        return None
    try:
        if thread_name:
            answer = getter(int(question_num), thread_name)
        else:
            answer = getter(int(question_num))
    except Exception:
        return None
    return answer if isinstance(answer, ReverseFillAnswer) else None

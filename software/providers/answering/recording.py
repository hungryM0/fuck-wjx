"""Shared answer recording helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .actions import AnswerAction


def record_answer_action(
    ctx: Any,
    action: AnswerAction,
    *,
    record_answer_fn: Callable[..., Any],
    record_pending_distribution_choice_fn: Callable[..., Any],
    default_fill_text: str,
) -> None:
    current = int(action.question_num or 0)
    if current <= 0:
        return
    record_type = str(action.record_type or action.kind or "").strip()
    for option_index, option_count, row_index in action.pending_distribution_choices:
        record_pending_distribution_choice_fn(
            ctx,
            current,
            int(option_index),
            int(option_count),
            row_index=row_index,
        )
    if record_type == "matrix":
        for row_index, selected_index in enumerate(action.matrix_indices):
            record_answer_fn(current, "matrix", selected_indices=[int(selected_index)], row_index=row_index)
        return
    if record_type == "text":
        text_values = [str(item or "").strip() or default_fill_text for item in action.text_values]
        if not text_values:
            text_values = [default_fill_text]
        record_answer_fn(
            current,
            "text",
            text_answer=" | ".join(text_values) if len(text_values) > 1 else text_values[0],
        )
        return
    if record_type == "slider":
        record_answer_fn(
            current,
            "slider",
            text_answer=str(action.slider_value if action.slider_value is not None else ""),
        )
        return
    record_answer_fn(
        current,
        record_type,
        selected_indices=[int(item) for item in action.selected_indices],
        selected_texts=[str(item or "") for item in action.selected_texts],
    )

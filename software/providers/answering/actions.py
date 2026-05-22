"""Shared answer action models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class AnswerAction:
    question_num: int = 0
    kind: str = ""
    question_id: str = ""
    root_index: int = -1
    input_type: str = ""
    selected_indices: tuple[int, ...] = ()
    matrix_indices: tuple[int, ...] = ()
    text_values: tuple[str, ...] = ()
    slider_value: Optional[float] = None
    option_fill_texts: tuple[tuple[int, str], ...] = ()
    selected_texts: tuple[str, ...] = ()
    record_type: str = ""
    pending_distribution_choices: tuple[tuple[int, int, Optional[int]], ...] = ()


@dataclass(frozen=True)
class BatchFillResult:
    applied: tuple[int, ...] = ()
    failed: tuple[int, ...] = ()
    skipped: tuple[int, ...] = ()


def action_payload(action: AnswerAction) -> dict[str, Any]:
    return {
        "questionNum": int(action.question_num),
        "questionId": str(action.question_id or ""),
        "rootIndex": int(action.root_index),
        "kind": str(action.kind or ""),
        "inputType": str(action.input_type or ""),
        "selectedIndices": [int(item) for item in action.selected_indices],
        "matrixIndices": [int(item) for item in action.matrix_indices],
        "textValues": [str(item or "") for item in action.text_values],
        "sliderValue": action.slider_value,
        "optionFillTexts": [
            {"optionIndex": int(option_index), "value": str(value or "")}
            for option_index, value in action.option_fill_texts
            if str(value or "").strip()
        ],
    }

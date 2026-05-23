"""Credamo answer action builders."""

from __future__ import annotations

from typing import Any, Optional

from software.app.config import DEFAULT_FILL_TEXT
from software.core.questions.runtime_async import resolve_runtime_text_values_from_config
from software.core.questions.utils import (
    normalize_droplist_probs,
    weighted_index,
)
from software.providers.answering import AnswerAction


from .answering_matrix import _normalize_positive_indices

def build_answer_action(
    *,
    root_index: int,
    question_num: int,
    entry_type: str,
    config_index: int,
    config: Any,
    question_meta: Any = None,
    psycho_plan: Any = None,
) -> Optional[AnswerAction]:
    kind = str(entry_type or "").strip()
    if kind == "single":
        raw_option_count = int(getattr(question_meta, "options", 0) or 0)
        if raw_option_count <= 0:
            return None
        option_count = max(1, raw_option_count)
        selected_index = _resolve_plan_choice(psycho_plan, question_num, option_count)
        if selected_index is None:
            weights = config.single_prob[config_index] if config_index < len(config.single_prob) else -1
            selected_index = weighted_index(normalize_droplist_probs(weights, option_count))
        return AnswerAction(root_index=int(root_index), question_num=int(question_num), kind="single", selected_indices=(selected_index,))
    if kind == "multiple":
        raw_option_count = int(getattr(question_meta, "options", 0) or 0)
        if raw_option_count <= 0:
            return None
        option_count = max(1, raw_option_count)
        weights = config.multiple_prob[config_index] if config_index < len(config.multiple_prob) else []
        selected = _normalize_positive_indices(weights, option_count)
        if not selected:
            return None
        return AnswerAction(root_index=int(root_index), question_num=int(question_num), kind="multiple", selected_indices=tuple(selected))
    if kind in {"scale", "score"}:
        raw_option_count = int(getattr(question_meta, "options", 0) or 0)
        if raw_option_count <= 0:
            return None
        option_count = max(2, raw_option_count)
        selected_index = _resolve_plan_choice(psycho_plan, question_num, option_count)
        if selected_index is None:
            weights = config.scale_prob[config_index] if config_index < len(config.scale_prob) else -1
            selected_index = weighted_index(normalize_droplist_probs(weights, option_count))
        return AnswerAction(root_index=int(root_index), question_num=int(question_num), kind="scale", selected_indices=(selected_index,))
    if kind == "matrix":
        row_count = max(1, int(getattr(question_meta, "rows", 1) or 1))
        raw_option_count = int(getattr(question_meta, "options", 0) or 0)
        if raw_option_count <= 0:
            return None
        option_count = max(2, raw_option_count)
        selected: list[int] = []
        for row_offset in range(row_count):
            matrix_index = config_index + row_offset
            plan_choice = _resolve_plan_choice(psycho_plan, question_num, option_count, row_index=row_offset)
            if plan_choice is not None:
                selected.append(plan_choice)
                continue
            weights = config.matrix_prob[matrix_index] if matrix_index < len(config.matrix_prob) else -1
            selected.append(weighted_index(normalize_droplist_probs(weights, option_count)))
        return AnswerAction(root_index=int(root_index), question_num=int(question_num), kind="matrix", matrix_indices=tuple(selected))
    if kind in {"text", "multi_text"}:
        text_config = config.texts[config_index] if config_index < len(config.texts) else [DEFAULT_FILL_TEXT]
        texts_prob = list(getattr(config, "texts_prob", []) or [])
        text_probabilities = texts_prob[config_index] if config_index < len(texts_prob) else [1.0]
        multi_text_blank_modes = list(getattr(config, "multi_text_blank_modes", []) or [])
        multi_text_blank_ranges = list(getattr(config, "multi_text_blank_int_ranges", []) or [])
        blank_count = max(1, int(getattr(question_meta, "text_inputs", 1) or 1))
        text_values = resolve_runtime_text_values_from_config(
            text_config,
            text_probabilities,
            blank_count=blank_count,
            entry_type=kind,
            blank_modes=multi_text_blank_modes[config_index] if config_index < len(multi_text_blank_modes) else [],
            blank_int_ranges=multi_text_blank_ranges[config_index] if config_index < len(multi_text_blank_ranges) else [],
        )
        return AnswerAction(
            root_index=int(root_index),
            question_num=int(question_num),
            kind="text" if kind == "text" else "multi_text",
            text_values=tuple(text_values),
        )
    return None


def _resolve_plan_choice(
    psycho_plan: Any,
    question_num: int,
    option_count: int,
    *,
    row_index: int | None = None,
) -> Optional[int]:
    if psycho_plan is None or not hasattr(psycho_plan, "get_choice"):
        return None
    try:
        choice = psycho_plan.get_choice(int(question_num), row_index)
    except Exception:
        return None
    try:
        selected = int(choice)
    except Exception:
        return None
    if 0 <= selected < int(option_count or 0):
        return selected
    return None


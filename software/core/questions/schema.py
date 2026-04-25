"""题目配置数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Union

from software.logging.log_utils import log_suppressed_exception

_TEXT_RANDOM_NAME_TOKEN = "__RANDOM_NAME__"
_TEXT_RANDOM_MOBILE_TOKEN = "__RANDOM_MOBILE__"
_TEXT_RANDOM_ID_CARD_TOKEN = "__RANDOM_ID_CARD__"
_TEXT_RANDOM_NONE = "none"
_TEXT_RANDOM_NAME = "name"
_TEXT_RANDOM_MOBILE = "mobile"
_TEXT_RANDOM_ID_CARD = "id_card"
_TEXT_RANDOM_INTEGER = "integer"
GLOBAL_RELIABILITY_DIMENSION = "__global_reliability__"

__all__ = [
    "GLOBAL_RELIABILITY_DIMENSION",
    "QuestionEntry",
    "_TEXT_RANDOM_ID_CARD",
    "_TEXT_RANDOM_ID_CARD_TOKEN",
    "_TEXT_RANDOM_INTEGER",
    "_TEXT_RANDOM_MOBILE",
    "_TEXT_RANDOM_MOBILE_TOKEN",
    "_TEXT_RANDOM_NAME",
    "_TEXT_RANDOM_NAME_TOKEN",
    "_TEXT_RANDOM_NONE",
    "_infer_option_count",
]


def _infer_option_count(entry: "QuestionEntry") -> int:
    """当配置中缺少选项数量时，尽可能从已保存的权重/文本推导。"""

    def _nested_length(raw: Any) -> Optional[int]:
        if not isinstance(raw, list):
            return None
        lengths: List[int] = []
        for item in raw:
            if isinstance(item, (list, tuple)):
                lengths.append(len(item))
        return max(lengths) if lengths else None

    if getattr(entry, "question_type", "") == "matrix":
        nested_len = _nested_length(getattr(entry, "custom_weights", None))
        if nested_len:
            return nested_len
        nested_len = _nested_length(getattr(entry, "probabilities", None))
        if nested_len:
            return nested_len

    try:
        if entry.option_count and entry.option_count > 0:
            return int(entry.option_count)
    except Exception as exc:
        log_suppressed_exception("questions.schema._infer_option_count option_count", exc)
    try:
        if entry.custom_weights and len(entry.custom_weights) > 0:
            return len(entry.custom_weights)
    except Exception as exc:
        log_suppressed_exception("questions.schema._infer_option_count custom_weights", exc)
    try:
        if isinstance(entry.probabilities, (list, tuple)) and len(entry.probabilities) > 0:
            return len(entry.probabilities)
    except Exception as exc:
        log_suppressed_exception("questions.schema._infer_option_count probabilities", exc)
    try:
        if entry.texts and len(entry.texts) > 0:
            return len(entry.texts)
    except Exception as exc:
        log_suppressed_exception("questions.schema._infer_option_count texts", exc)
    if getattr(entry, "question_type", "") in ("scale", "score"):
        return 5
    return 0


@dataclass
class QuestionEntry:
    question_type: str
    probabilities: Union[List[float], List[List[float]], int, None]
    texts: Optional[List[str]] = None
    rows: int = 1
    option_count: int = 0
    distribution_mode: str = "random"
    custom_weights: Union[List[float], List[List[float]], None] = None
    question_num: Optional[int] = None
    question_title: Optional[str] = None
    survey_provider: str = "wjx"
    provider_question_id: Optional[str] = None
    provider_page_id: Optional[str] = None
    ai_enabled: bool = False
    multi_text_blank_modes: List[str] = field(default_factory=list)
    multi_text_blank_ai_flags: List[bool] = field(default_factory=list)
    multi_text_blank_int_ranges: List[List[int]] = field(default_factory=list)
    text_random_mode: str = _TEXT_RANDOM_NONE
    text_random_int_range: List[int] = field(default_factory=list)
    option_fill_texts: Optional[List[Optional[str]]] = None
    fillable_option_indices: Optional[List[int]] = None
    attached_option_selects: List[dict] = field(default_factory=list)
    is_location: bool = False
    dimension: Optional[str] = None
    psycho_bias: str = "custom"

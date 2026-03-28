"""题目策略页通用辅助函数。"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional

from software.app.config import DIMENSION_UNGROUPED
from software.core.questions.config import QuestionEntry

DIMENSION_SUPPORTED_TYPES = {"scale", "score", "matrix"}
_BIAS_TEXT_MAP = {
    "left": "低分倾向",
    "center": "居中",
    "right": "高分倾向",
    "custom": "自定义",
}


def normalize_dimension_name(value: Any) -> Optional[str]:
    try:
        text = str(value or "").strip()
    except Exception:
        text = ""
    if not text or text == DIMENSION_UNGROUPED:
        return None
    return text


def entry_dimension_label(entry: QuestionEntry) -> str:
    return normalize_dimension_name(getattr(entry, "dimension", None)) or DIMENSION_UNGROUPED


def question_supports_dimension_grouping(entry: QuestionEntry) -> bool:
    return str(getattr(entry, "question_type", "") or "").strip().lower() in DIMENSION_SUPPORTED_TYPES


def sanitize_dimension_groups(
    groups: Iterable[Any],
    entries: Optional[Iterable[QuestionEntry]] = None,
) -> List[str]:
    result: List[str] = []
    seen = set()

    def _append(value: Any) -> None:
        normalized = normalize_dimension_name(value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        result.append(normalized)

    for item in groups or []:
        _append(item)
    for entry in entries or []:
        _append(getattr(entry, "dimension", None))
    return result


def summarize_bias(entry: QuestionEntry) -> str:
    raw_bias = getattr(entry, "psycho_bias", "custom")
    if isinstance(raw_bias, list):
        normalized = [str(item or "custom").strip().lower() for item in raw_bias if str(item or "").strip()]
        if not normalized:
            return _BIAS_TEXT_MAP["custom"]
        unique = []
        seen = set()
        for item in normalized:
            if item in seen:
                continue
            seen.add(item)
            unique.append(_BIAS_TEXT_MAP.get(item, item))
        if len(unique) == 1:
            return unique[0]
        return "按行预设"
    bias = str(raw_bias or "custom").strip().lower()
    return _BIAS_TEXT_MAP.get(bias, bias or _BIAS_TEXT_MAP["custom"])

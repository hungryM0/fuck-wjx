"""量表型选项识别工具。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class OrdinalOptionMapping:
    score_by_choice_index: List[int]

    @property
    def option_count(self) -> int:
        return len(self.score_by_choice_index)


_NUMERIC_RE = re.compile(r"^\s*(\d+)(?:\s*(?:分|点|级|星))?\s*$")
_CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

_ORDINAL_GROUPS = [
    ["非常不满意", "不满意", "一般", "满意", "非常满意"],
    ["很不满意", "不满意", "一般", "满意", "很满意"],
    ["非常不同意", "不同意", "一般", "同意", "非常同意"],
    ["很不同意", "不同意", "一般", "同意", "很同意"],
    ["很差", "较差", "一般", "较好", "很好"],
    ["非常差", "差", "一般", "好", "非常好"],
    ["从不", "偶尔", "有时", "经常", "总是"],
    ["完全没有", "较少", "一般", "较多", "非常多"],
]


def _normalize_option_text(value: object) -> str:
    text = str(value or "").strip()
    return re.sub(r"\s+", "", text)


def _parse_numeric_options(texts: List[str]) -> Optional[List[int]]:
    values: List[int] = []
    for text in texts:
        match = _NUMERIC_RE.match(text)
        if not match:
            return None
        values.append(int(match.group(1)))
    if len(values) < 2:
        return None
    if values == list(range(values[0], values[0] + len(values))):
        return [value - min(values) for value in values]
    if values == list(range(values[0], values[0] - len(values), -1)):
        max_value = max(values)
        return [max_value - value for value in values]
    return None


def _parse_chinese_numeric_options(texts: List[str]) -> Optional[List[int]]:
    values: List[int] = []
    for text in texts:
        value = text.removesuffix("分").removesuffix("点").removesuffix("级").removesuffix("星")
        if value not in _CHINESE_NUMBERS:
            return None
        values.append(_CHINESE_NUMBERS[value])
    if len(values) < 2:
        return None
    if values == list(range(values[0], values[0] + len(values))):
        return [value - min(values) for value in values]
    if values == list(range(values[0], values[0] - len(values), -1)):
        max_value = max(values)
        return [max_value - value for value in values]
    return None


def _match_text_group(texts: List[str]) -> Optional[List[int]]:
    if len(texts) < 2:
        return None
    for group in _ORDINAL_GROUPS:
        normalized_group = [_normalize_option_text(item) for item in group]
        if texts == normalized_group[: len(texts)]:
            return list(range(len(texts)))
        if texts == list(reversed(normalized_group[-len(texts) :])):
            return list(reversed(range(len(texts))))
        if len(texts) == len(normalized_group) and texts == list(reversed(normalized_group)):
            return list(reversed(range(len(texts))))
    return None


def infer_ordinal_option_mapping(option_texts: Iterable[object]) -> Optional[OrdinalOptionMapping]:
    texts = [_normalize_option_text(item) for item in list(option_texts or [])]
    texts = [text for text in texts if text]
    if len(texts) < 2:
        return None

    score_by_choice_index = (
        _parse_numeric_options(texts)
        or _parse_chinese_numeric_options(texts)
        or _match_text_group(texts)
    )
    if score_by_choice_index is None:
        return None
    if len(score_by_choice_index) != len(texts):
        return None
    if sorted(score_by_choice_index) != list(range(len(texts))):
        return None
    return OrdinalOptionMapping(score_by_choice_index=score_by_choice_index)


__all__ = ["OrdinalOptionMapping", "infer_ordinal_option_mapping"]

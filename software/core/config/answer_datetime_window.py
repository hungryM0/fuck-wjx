"""作答日期时间窗的字符串规整与转换。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

ANSWER_DATETIME_WINDOW_FORMAT = "%Y-%m-%d %H:%M:%S"
EMPTY_ANSWER_DATETIME_WINDOW = ("", "")


def parse_answer_datetime_string(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, ANSWER_DATETIME_WINDOW_FORMAT)
    except Exception:
        return None


def format_answer_datetime_string(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime(ANSWER_DATETIME_WINDOW_FORMAT)


def normalize_answer_datetime_window(value: Any) -> tuple[str, str]:
    if not isinstance(value, (list, tuple)):
        return EMPTY_ANSWER_DATETIME_WINDOW
    start_raw = value[0] if len(value) >= 1 else ""
    end_raw = value[1] if len(value) >= 2 else ""
    start = format_answer_datetime_string(parse_answer_datetime_string(start_raw))
    end = format_answer_datetime_string(parse_answer_datetime_string(end_raw))
    return start, end


def answer_datetime_window_to_epoch_ms(value: Any) -> tuple[int, int]:
    start_text, end_text = normalize_answer_datetime_window(value)
    start = parse_answer_datetime_string(start_text)
    end = parse_answer_datetime_string(end_text)
    if start is None or end is None:
        return 0, 0
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def has_configured_answer_datetime_window(value: Any) -> bool:
    start_text, end_text = normalize_answer_datetime_window(value)
    return bool(start_text and end_text)


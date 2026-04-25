"""Provider 标准契约与解析结果归一化。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from software.providers.common import SURVEY_PROVIDER_WJX, normalize_survey_provider

__all__ = [
    "SurveyDefinition",
    "build_survey_definition",
    "normalize_survey_questions",
]


@dataclass(frozen=True)
class SurveyDefinition:
    provider: str
    title: str
    questions: List[Dict[str, Any]]


def _as_int(value: Any, default: int, *, minimum: int | None = None) -> int:
    try:
        number = int(value)
    except Exception:
        number = default
    if minimum is not None:
        number = max(minimum, number)
    return number


def _normalize_text_list(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    return [str(item or "").strip() for item in raw]


def _normalize_question(question: Dict[str, Any], provider: str, index: int) -> Dict[str, Any]:
    normalized = dict(question or {})
    page_number = _as_int(normalized.get("page"), 1, minimum=1)
    question_number = _as_int(normalized.get("num"), index, minimum=1)
    option_count = _as_int(normalized.get("options"), len(_normalize_text_list(normalized.get("option_texts"))), minimum=0)
    row_count = _as_int(normalized.get("rows"), len(_normalize_text_list(normalized.get("row_texts"))) or 1, minimum=1)

    normalized_provider = normalize_survey_provider(normalized.get("provider"), default=provider)
    option_texts = _normalize_text_list(normalized.get("option_texts"))
    row_texts = _normalize_text_list(normalized.get("row_texts"))
    text_input_labels = _normalize_text_list(normalized.get("text_input_labels"))
    forced_texts = _normalize_text_list(normalized.get("forced_texts"))
    fillable_options_raw = normalized.get("fillable_options")
    if isinstance(fillable_options_raw, list):
        fillable_options: List[int] = []
        for raw in fillable_options_raw:
            try:
                fillable_options.append(int(raw))
            except Exception:
                continue
    else:
        fillable_options = []
    attached_option_selects = normalized.get("attached_option_selects")
    if not isinstance(attached_option_selects, list):
        attached_option_selects = []

    unsupported = bool(normalized.get("unsupported"))
    unsupported_reason = str(normalized.get("unsupported_reason") or "").strip()
    if unsupported and not unsupported_reason:
        unsupported_reason = "当前平台暂不支持该题型"

    normalized.update({
        "num": question_number,
        "title": str(normalized.get("title") or "").strip(),
        "description": str(normalized.get("description") or "").strip(),
        "type_code": str(normalized.get("type_code") or "0").strip() or "0",
        "options": option_count,
        "rows": row_count,
        "row_texts": row_texts,
        "page": page_number,
        "option_texts": option_texts,
        "forced_option_index": normalized.get("forced_option_index"),
        "forced_option_text": str(normalized.get("forced_option_text") or "").strip(),
        "forced_texts": forced_texts,
        "fillable_options": fillable_options,
        "attached_option_selects": attached_option_selects,
        "has_attached_option_select": bool(normalized.get("has_attached_option_select") or attached_option_selects),
        "is_location": bool(normalized.get("is_location")),
        "is_rating": bool(normalized.get("is_rating")),
        "is_description": bool(normalized.get("is_description")),
        "rating_max": _as_int(normalized.get("rating_max"), option_count if bool(normalized.get("is_rating")) else 0, minimum=0),
        "text_inputs": _as_int(normalized.get("text_inputs"), 0, minimum=0),
        "text_input_labels": text_input_labels,
        "is_multi_text": bool(normalized.get("is_multi_text")),
        "is_text_like": bool(normalized.get("is_text_like")),
        "is_slider_matrix": bool(normalized.get("is_slider_matrix")),
        "has_jump": bool(normalized.get("has_jump")),
        "jump_rules": normalized.get("jump_rules") if isinstance(normalized.get("jump_rules"), list) else [],
        "has_display_condition": bool(normalized.get("has_display_condition")),
        "display_conditions": normalized.get("display_conditions") if isinstance(normalized.get("display_conditions"), list) else [],
        "slider_min": normalized.get("slider_min"),
        "slider_max": normalized.get("slider_max"),
        "slider_step": normalized.get("slider_step"),
        "multi_min_limit": normalized.get("multi_min_limit"),
        "multi_max_limit": normalized.get("multi_max_limit"),
        "provider": normalized_provider,
        "provider_question_id": str(normalized.get("provider_question_id") or question_number).strip(),
        "provider_page_id": str(normalized.get("provider_page_id") or page_number).strip(),
        "provider_type": str(normalized.get("provider_type") or normalized.get("type_code") or "").strip(),
        "unsupported": unsupported,
        "unsupported_reason": unsupported_reason,
        "required": bool(normalized.get("required")),
    })
    return normalized


def normalize_survey_questions(provider: str, questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized_provider = normalize_survey_provider(provider, default=SURVEY_PROVIDER_WJX)
    normalized: List[Dict[str, Any]] = []
    for index, question in enumerate(questions or [], start=1):
        if not isinstance(question, dict):
            continue
        normalized.append(_normalize_question(question, normalized_provider, index))
    return normalized


def build_survey_definition(provider: str, title: str, questions: List[Dict[str, Any]]) -> SurveyDefinition:
    normalized_provider = normalize_survey_provider(provider, default=SURVEY_PROVIDER_WJX)
    return SurveyDefinition(
        provider=normalized_provider,
        title=str(title or "").strip(),
        questions=normalize_survey_questions(normalized_provider, questions),
    )

"""Provider 标准契约与解析结果归一化。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

from software.providers.common import SURVEY_PROVIDER_WJX, normalize_survey_provider

__all__ = [
    "SurveyDefinition",
    "SurveyQuestionMeta",
    "build_survey_definition",
    "clone_survey_question_metas",
    "ensure_survey_question_meta",
    "ensure_survey_question_metas",
    "normalize_survey_questions",
    "serialize_survey_question_metas",
    "survey_question_meta_to_dict",
]


@dataclass
class SurveyQuestionMeta:
    num: int
    title: str
    description: str = ""
    type_code: str = "0"
    options: int = 0
    rows: int = 1
    row_texts: List[str] = field(default_factory=list)
    page: int = 1
    option_texts: List[str] = field(default_factory=list)
    forced_option_index: Optional[int] = None
    forced_option_text: str = ""
    forced_texts: List[str] = field(default_factory=list)
    fillable_options: List[int] = field(default_factory=list)
    attached_option_selects: List[Dict[str, Any]] = field(default_factory=list)
    has_attached_option_select: bool = False
    is_location: bool = False
    is_rating: bool = False
    is_description: bool = False
    rating_max: int = 0
    text_inputs: int = 0
    text_input_labels: List[str] = field(default_factory=list)
    is_multi_text: bool = False
    is_text_like: bool = False
    is_slider_matrix: bool = False
    has_jump: bool = False
    jump_rules: List[Dict[str, Any]] = field(default_factory=list)
    has_display_condition: bool = False
    display_conditions: List[Dict[str, Any]] = field(default_factory=list)
    has_dependent_display_logic: bool = False
    controls_display_targets: List[Dict[str, Any]] = field(default_factory=list)
    slider_min: Any = None
    slider_max: Any = None
    slider_step: Any = None
    multi_min_limit: Any = None
    multi_max_limit: Any = None
    provider: str = SURVEY_PROVIDER_WJX
    provider_question_id: str = ""
    provider_page_id: str = ""
    provider_type: str = ""
    provider_page_raw: Any = None
    unsupported: bool = False
    unsupported_reason: str = ""
    required: bool = False

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, str(key or ""), default)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, str(key or ""))

    def keys(self):
        return self.to_dict().keys()

    def items(self):
        return self.to_dict().items()

    def values(self):
        return self.to_dict().values()

    def __iter__(self):
        return iter(self.to_dict().items())

    def __len__(self) -> int:
        return len(self.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        return survey_question_meta_to_dict(self)


@dataclass(frozen=True)
class SurveyDefinition:
    provider: str
    title: str
    questions: List[SurveyQuestionMeta]


SurveyQuestionInput = SurveyQuestionMeta | Mapping[str, Any]


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


def _normalize_dict_list(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    items: List[Dict[str, Any]] = []
    for item in raw:
        normalized = _survey_question_input_to_dict(item)
        if normalized is not None:
            items.append(normalized)
    return items


def _survey_question_input_to_dict(question: Any) -> Optional[Dict[str, Any]]:
    if isinstance(question, SurveyQuestionMeta):
        return survey_question_meta_to_dict(question)
    if isinstance(question, Mapping):
        return dict(question)
    return None


def survey_question_meta_to_dict(question: SurveyQuestionMeta) -> Dict[str, Any]:
    return {
        "num": int(question.num),
        "title": str(question.title or "").strip(),
        "description": str(question.description or "").strip(),
        "type_code": str(question.type_code or "0").strip() or "0",
        "options": int(question.options or 0),
        "rows": int(question.rows or 1),
        "row_texts": list(question.row_texts or []),
        "page": int(question.page or 1),
        "option_texts": list(question.option_texts or []),
        "forced_option_index": question.forced_option_index,
        "forced_option_text": str(question.forced_option_text or "").strip(),
        "forced_texts": list(question.forced_texts or []),
        "fillable_options": list(question.fillable_options or []),
        "attached_option_selects": _normalize_dict_list(question.attached_option_selects),
        "has_attached_option_select": bool(question.has_attached_option_select),
        "is_location": bool(question.is_location),
        "is_rating": bool(question.is_rating),
        "is_description": bool(question.is_description),
        "rating_max": int(question.rating_max or 0),
        "text_inputs": int(question.text_inputs or 0),
        "text_input_labels": list(question.text_input_labels or []),
        "is_multi_text": bool(question.is_multi_text),
        "is_text_like": bool(question.is_text_like),
        "is_slider_matrix": bool(question.is_slider_matrix),
        "has_jump": bool(question.has_jump),
        "jump_rules": _normalize_dict_list(question.jump_rules),
        "has_display_condition": bool(question.has_display_condition),
        "display_conditions": _normalize_dict_list(question.display_conditions),
        "has_dependent_display_logic": bool(question.has_dependent_display_logic),
        "controls_display_targets": _normalize_dict_list(question.controls_display_targets),
        "slider_min": question.slider_min,
        "slider_max": question.slider_max,
        "slider_step": question.slider_step,
        "multi_min_limit": question.multi_min_limit,
        "multi_max_limit": question.multi_max_limit,
        "provider": normalize_survey_provider(question.provider, default=SURVEY_PROVIDER_WJX),
        "provider_question_id": str(question.provider_question_id or "").strip(),
        "provider_page_id": str(question.provider_page_id or "").strip(),
        "provider_type": str(question.provider_type or "").strip(),
        "provider_page_raw": question.provider_page_raw,
        "unsupported": bool(question.unsupported),
        "unsupported_reason": str(question.unsupported_reason or "").strip(),
        "required": bool(question.required),
    }


def _normalize_question(question: SurveyQuestionInput, provider: str, index: int) -> SurveyQuestionMeta:
    normalized = dict(_survey_question_input_to_dict(question) or {})
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

    forced_option_index = normalized.get("forced_option_index")
    try:
        if forced_option_index is not None:
            forced_option_index = int(forced_option_index)
    except Exception:
        forced_option_index = None

    return SurveyQuestionMeta(
        num=question_number,
        title=str(normalized.get("title") or "").strip(),
        description=str(normalized.get("description") or "").strip(),
        type_code=str(normalized.get("type_code") or "0").strip() or "0",
        options=option_count,
        rows=row_count,
        row_texts=row_texts,
        page=page_number,
        option_texts=option_texts,
        forced_option_index=forced_option_index,
        forced_option_text=str(normalized.get("forced_option_text") or "").strip(),
        forced_texts=forced_texts,
        fillable_options=fillable_options,
        attached_option_selects=_normalize_dict_list(attached_option_selects),
        has_attached_option_select=bool(normalized.get("has_attached_option_select") or attached_option_selects),
        is_location=bool(normalized.get("is_location")),
        is_rating=bool(normalized.get("is_rating")),
        is_description=bool(normalized.get("is_description")),
        rating_max=_as_int(normalized.get("rating_max"), option_count if bool(normalized.get("is_rating")) else 0, minimum=0),
        text_inputs=_as_int(normalized.get("text_inputs"), 0, minimum=0),
        text_input_labels=text_input_labels,
        is_multi_text=bool(normalized.get("is_multi_text")),
        is_text_like=bool(normalized.get("is_text_like")),
        is_slider_matrix=bool(normalized.get("is_slider_matrix")),
        has_jump=bool(normalized.get("has_jump")),
        jump_rules=_normalize_dict_list(normalized.get("jump_rules")),
        has_display_condition=bool(normalized.get("has_display_condition")),
        display_conditions=_normalize_dict_list(normalized.get("display_conditions")),
        has_dependent_display_logic=bool(normalized.get("has_dependent_display_logic")),
        controls_display_targets=_normalize_dict_list(normalized.get("controls_display_targets")),
        slider_min=normalized.get("slider_min"),
        slider_max=normalized.get("slider_max"),
        slider_step=normalized.get("slider_step"),
        multi_min_limit=normalized.get("multi_min_limit"),
        multi_max_limit=normalized.get("multi_max_limit"),
        provider=normalized_provider,
        provider_question_id=str(normalized.get("provider_question_id") or question_number).strip(),
        provider_page_id=str(normalized.get("provider_page_id") or page_number).strip(),
        provider_type=str(normalized.get("provider_type") or normalized.get("type_code") or "").strip(),
        provider_page_raw=normalized.get("provider_page_raw"),
        unsupported=unsupported,
        unsupported_reason=unsupported_reason,
        required=bool(normalized.get("required")),
    )


def ensure_survey_question_meta(question: SurveyQuestionInput, *, default_provider: str = SURVEY_PROVIDER_WJX, index: int = 1) -> SurveyQuestionMeta:
    return _normalize_question(question, normalize_survey_provider(default_provider, default=SURVEY_PROVIDER_WJX), index)


def ensure_survey_question_metas(
    questions: Iterable[SurveyQuestionInput],
    *,
    default_provider: str = SURVEY_PROVIDER_WJX,
) -> List[SurveyQuestionMeta]:
    normalized_provider = normalize_survey_provider(default_provider, default=SURVEY_PROVIDER_WJX)
    normalized: List[SurveyQuestionMeta] = []
    for index, question in enumerate(questions or [], start=1):
        if not isinstance(question, (SurveyQuestionMeta, Mapping)):
            continue
        normalized.append(_normalize_question(question, normalized_provider, index))
    return normalized


def serialize_survey_question_metas(questions: Iterable[SurveyQuestionInput]) -> List[Dict[str, Any]]:
    serialized: List[Dict[str, Any]] = []
    for question in questions or []:
        normalized = _survey_question_input_to_dict(question)
        if normalized is not None:
            serialized.append(normalized)
    return serialized


def clone_survey_question_metas(
    questions: Iterable[SurveyQuestionInput],
    *,
    default_provider: str = SURVEY_PROVIDER_WJX,
) -> List[SurveyQuestionMeta]:
    serialized = serialize_survey_question_metas(questions)
    return ensure_survey_question_metas(serialized, default_provider=default_provider)


def normalize_survey_questions(provider: str, questions: Iterable[SurveyQuestionInput]) -> List[SurveyQuestionMeta]:
    normalized_provider = normalize_survey_provider(provider, default=SURVEY_PROVIDER_WJX)
    return ensure_survey_question_metas(questions, default_provider=normalized_provider)


def build_survey_definition(provider: str, title: str, questions: Iterable[SurveyQuestionInput]) -> SurveyDefinition:
    normalized_provider = normalize_survey_provider(provider, default=SURVEY_PROVIDER_WJX)
    return SurveyDefinition(
        provider=normalized_provider,
        title=str(title or "").strip(),
        questions=normalize_survey_questions(normalized_provider, questions),
    )

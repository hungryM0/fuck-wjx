"""Credamo 见数问卷纯 HTTP 解析。"""

from __future__ import annotations

import ast
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

from software.app.config import DEFAULT_USER_AGENT
from software.providers.common import SURVEY_PROVIDER_CREDAMO
from software.providers.contracts import LOGIC_PARSE_STATUS_NONE

from .http_runtime import (
    _CredamoHttpSession,
    _as_mapping_list,
    _fetch_detail,
    _iter_raw_questions,
    _noauth_short_url,
    _origin_from_url,
    _raw_option_count,
    _raw_provider_type,
    _raw_question_num,
    _raw_question_type,
    _raw_row_count,
    _request_headers,
    _short_url_from_url,
)

_QUESTION_NUMBER_RE = re.compile(r"^\s*(?:Q|题目?)\s*(\d+)\b", re.IGNORECASE)
_TYPE_ONLY_TITLE_RE = re.compile(r"^\s*\[[^\]]+\]\s*$")
_LEADING_TYPE_TAG_RE = re.compile(r"^(?:(?:\[[^\]]+\]|【[^】]+】)\s*)+")
_FORCE_SELECT_COMMAND_RE = re.compile(r"请(?:务必|一定|必须|直接)?\s*选(?:择)?")
_FORCE_SELECT_INDEX_RE = re.compile(r"^第?\s*(\d{1,3})\s*(?:个|项|选项|分|星)?$")
_FORCE_SELECT_SENTENCE_SPLIT_RE = re.compile(r"[。；;！？!\n\r]")
_FORCE_SELECT_CLEAN_RE = re.compile(r"[\s`'\"“”‘’【】\[\]\(\)（）<>《》,，、。；;:：!?！？]")
_FORCE_SELECT_LABEL_TARGET_RE = re.compile(r"^([A-Za-z])(?:项|选项|答案)?$")
_FORCE_SELECT_OPTION_LABEL_RE = re.compile(
    r"^(?:第\s*)?[\(（【\[]?\s*([A-Za-z])\s*[\)）】\]]?(?=$|[\.．、:：\-\s]|[\u4e00-\u9fff])"
)
_ARITHMETIC_EXPR_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?(?:\s*[+\-*/×xX÷]\s*\d+(?:\.\d+)?)+)(?!\d)")
_OPTION_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_FORCE_TEXT_RE = re.compile(r"请(?:务必|一定|必须|直接)?\s*(?:输入|填写|填入|写入)\s*[：:\s]*[\"“'‘]?([^\"”'’\s，,。；;！!？?）)]+)")
_MULTI_SELECT_LIMIT_RE = re.compile(
    r"(?:[\[【（(]\s*)?"
    r"(?P<kind>至多|最多|不超过|至多可|最多可|至少|最少|不少于)"
    r"\s*(?:可)?(?:选择|选)?\s*"
    r"(?P<count>\d{1,3}|[零〇一二两三四五六七八九十百]{1,4})\s*(?:个)?(?:选项|项)?"
    r"(?:\s*[\]】）)])?"
)
_MULTI_SELECT_RANGE_RE = re.compile(
    r"(?:[\[【（(]\s*)?"
    r"(?:请)?(?:选择|选)\s*"
    r"(?P<min>\d{1,3}|[零〇一二两三四五六七八九十百]{1,4})\s*"
    r"(?:-|~|～|至|到)\s*"
    r"(?P<max>\d{1,3}|[零〇一二两三四五六七八九十百]{1,4})\s*"
    r"(?:个)?(?:选项|项)"
    r"(?:\s*[\]】）)])?"
)


class CredamoParseError(RuntimeError):
    """Credamo 接口结构无法解析时抛出的业务异常。"""


def _normalize_text(value: Any) -> str:
    try:
        text = str(value or "").strip()
    except Exception:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_force_select_text(value: Any) -> str:
    text = _normalize_text(value)
    return _FORCE_SELECT_CLEAN_RE.sub("", text).lower() if text else ""


def _extract_force_select_option_label(option_text: Any) -> Optional[str]:
    match = _FORCE_SELECT_OPTION_LABEL_RE.match(_normalize_text(option_text))
    if not match:
        return None
    label = str(match.group(1) or "").strip().upper()
    return label or None


def _extract_force_select_option(
    title_text: str,
    option_texts: List[str],
    extra_fragments: Optional[List[Any]] = None,
) -> Tuple[Optional[int], Optional[str]]:
    if not option_texts:
        return None, None
    normalized_options: List[Tuple[int, str, str]] = []
    for idx, option_text in enumerate(option_texts):
        raw_text = _normalize_text(option_text)
        normalized = _normalize_force_select_text(raw_text)
        if normalized:
            normalized_options.append((idx, raw_text, normalized))
    if not normalized_options:
        return None, None

    fragments: List[str] = []
    seen: set[str] = set()
    for candidate in [title_text, *(extra_fragments or [])]:
        fragment = _normalize_text(candidate)
        if fragment and fragment not in seen:
            seen.add(fragment)
            fragments.append(fragment)

    for fragment in fragments:
        for command_match in _FORCE_SELECT_COMMAND_RE.finditer(fragment):
            sentence = _FORCE_SELECT_SENTENCE_SPLIT_RE.split(fragment[command_match.end():], maxsplit=1)[0]
            sentence = sentence.strip(" ：:，,、")
            compact_sentence = _normalize_force_select_text(sentence)
            if not compact_sentence:
                continue

            best_index: Optional[int] = None
            best_text: Optional[str] = None
            best_length = -1
            for option_idx, raw_text, normalized_text in normalized_options:
                if normalized_text.isdigit():
                    continue
                if normalized_text in compact_sentence and len(normalized_text) > best_length:
                    best_index = option_idx
                    best_text = raw_text
                    best_length = len(normalized_text)
            if best_index is not None:
                return best_index, best_text

            label_match = _FORCE_SELECT_LABEL_TARGET_RE.fullmatch(compact_sentence)
            if label_match:
                target_label = str(label_match.group(1) or "").strip().upper()
                for option_idx, raw_text, _ in normalized_options:
                    if _extract_force_select_option_label(raw_text) == target_label:
                        return option_idx, raw_text

            index_match = _FORCE_SELECT_INDEX_RE.fullmatch(sentence)
            if index_match:
                try:
                    target_idx = int(index_match.group(1)) - 1
                except Exception:
                    target_idx = -1
                if 0 <= target_idx < len(option_texts):
                    return target_idx, _normalize_text(option_texts[target_idx]) or None
    return None, None


def _safe_eval_arithmetic_expression(expression: str) -> Optional[float]:
    text = str(expression or "").strip().replace("×", "*").replace("x", "*").replace("X", "*").replace("÷", "/")
    if not text or not re.fullmatch(r"[\d\s+\-*/.]+", text):
        return None
    try:
        node = ast.parse(text, mode="eval")
    except Exception:
        return None

    def eval_node(current: ast.AST) -> Optional[float]:
        if isinstance(current, ast.Expression):
            return eval_node(current.body)
        if isinstance(current, ast.Constant) and isinstance(current.value, (int, float)):
            return float(current.value)
        if isinstance(current, ast.UnaryOp) and isinstance(current.op, (ast.UAdd, ast.USub)):
            value = eval_node(current.operand)
            if value is None:
                return None
            return value if isinstance(current.op, ast.UAdd) else -value
        if isinstance(current, ast.BinOp) and isinstance(current.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left = eval_node(current.left)
            right = eval_node(current.right)
            if left is None or right is None:
                return None
            if isinstance(current.op, ast.Add):
                return left + right
            if isinstance(current.op, ast.Sub):
                return left - right
            if isinstance(current.op, ast.Mult):
                return left * right
            return None if abs(right) < 1e-12 else left / right
        return None

    return eval_node(node)


def _parse_count_token(raw: Any) -> Optional[int]:
    text = _normalize_text(raw)
    if not text:
        return None
    if text.isdigit():
        return int(text)
    digit_map = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    total = 0
    current = 0
    for ch in text:
        if ch in digit_map:
            current = digit_map[ch]
        elif ch == "十":
            total += (current or 1) * 10
            current = 0
        elif ch == "百":
            total += (current or 1) * 100
            current = 0
        else:
            return None
    result = total + current
    return result if result > 0 else None


def _extract_numeric_option_value(option_text: Any) -> Optional[float]:
    match = _OPTION_NUMBER_RE.search(_normalize_text(option_text))
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None


def _extract_arithmetic_option(
    title_text: str,
    option_texts: List[str],
    extra_fragments: Optional[List[Any]] = None,
) -> Tuple[Optional[int], Optional[str]]:
    if not option_texts:
        return None, None
    for candidate in [title_text, *(extra_fragments or [])]:
        fragment = _normalize_text(candidate)
        if not fragment:
            continue
        for match in _ARITHMETIC_EXPR_RE.finditer(fragment):
            result = _safe_eval_arithmetic_expression(match.group(1))
            if result is None:
                continue
            for option_idx, option_text in enumerate(option_texts):
                option_value = _extract_numeric_option_value(option_text)
                if option_value is not None and abs(option_value - result) < 1e-9:
                    return option_idx, _normalize_text(option_text) or None
    return None, None


def _extract_forced_texts(title_text: str, extra_fragments: Optional[List[Any]] = None) -> List[str]:
    forced: List[str] = []
    seen: set[str] = set()
    for candidate in [title_text, *(extra_fragments or [])]:
        fragment = _normalize_text(candidate)
        if not fragment:
            continue
        for match in _FORCE_TEXT_RE.finditer(fragment):
            text = _normalize_text(match.group(1))
            if text and text not in seen:
                seen.add(text)
                forced.append(text)
    return forced


def _extract_multi_select_limits(
    title_text: str,
    *,
    option_count: int = 0,
    extra_fragments: Optional[List[Any]] = None,
) -> Tuple[Optional[int], Optional[int]]:
    min_limit: Optional[int] = None
    max_limit: Optional[int] = None
    upper_bound = max(0, int(option_count or 0))
    seen: set[str] = set()
    fragments = []
    for candidate in [title_text, *(extra_fragments or [])]:
        fragment = _normalize_text(candidate)
        if fragment and fragment not in seen:
            seen.add(fragment)
            fragments.append(fragment)
    for fragment in fragments:
        for match in _MULTI_SELECT_LIMIT_RE.finditer(fragment):
            count = _parse_count_token(match.group("count"))
            if count is None:
                continue
            count = max(1, count)
            if upper_bound > 0:
                count = min(count, upper_bound)
            kind = str(match.group("kind") or "")
            if kind in {"至少", "最少", "不少于"}:
                min_limit = count if min_limit is None else max(min_limit, count)
            elif kind in {"至多", "最多", "不超过", "至多可", "最多可"}:
                max_limit = count if max_limit is None else min(max_limit, count)
        for match in _MULTI_SELECT_RANGE_RE.finditer(fragment):
            parsed_min = _parse_count_token(match.group("min"))
            parsed_max = _parse_count_token(match.group("max"))
            if parsed_min is None or parsed_max is None:
                continue
            range_min = max(1, parsed_min)
            range_max = max(range_min, parsed_max)
            if upper_bound > 0:
                range_min = min(range_min, upper_bound)
                range_max = min(range_max, upper_bound)
            min_limit = range_min if min_limit is None else max(min_limit, range_min)
            max_limit = range_max if max_limit is None else min(max_limit, range_max)
    if min_limit is not None and max_limit is not None and min_limit > max_limit:
        min_limit = max_limit
    return min_limit, max_limit


def _normalize_question_number(raw: Any, fallback_num: int) -> int:
    match = re.search(r"\d+", str(raw or ""))
    return max(1, int(match.group(0))) if match else max(1, int(fallback_num or 1))


def _infer_type_code(question: Dict[str, Any]) -> str:
    question_kind = str(question.get("question_kind") or "").strip().lower()
    input_types = {str(item or "").strip().lower() for item in question.get("input_types") or []}
    option_count = int(question.get("options") or 0)
    text_input_count = int(question.get("text_inputs") or 0)
    if question_kind == "multiple" or "checkbox" in input_types:
        return "4"
    if question_kind == "dropdown":
        return "7"
    if question_kind == "matrix":
        return "6"
    if question_kind == "scale":
        return "5"
    if question_kind == "order":
        return "11"
    if question_kind == "single" or "radio" in input_types:
        return "3"
    if question_kind in {"text", "multi_text"} or text_input_count > 0:
        return "1"
    if option_count >= 2:
        return "3"
    return "1"


def _is_generic_matrix_option_text(text: Any) -> bool:
    return bool(re.fullmatch(r"选项\s*\d+", _normalize_text(text), re.IGNORECASE))


def _resolve_matrix_option_texts(raw: Dict[str, Any], option_texts: List[str]) -> List[str]:
    question_kind = str(raw.get("question_kind") or "").strip().lower()
    provider_type = str(raw.get("provider_type") or "").strip().lower()
    if question_kind != "matrix" and provider_type != "matrix":
        return option_texts
    matrix_column_texts = [_normalize_text(text) for text in raw.get("matrix_column_texts") or []]
    matrix_column_texts = [text for text in matrix_column_texts if text]
    if matrix_column_texts:
        return matrix_column_texts
    if option_texts and not all(_is_generic_matrix_option_text(text) for text in option_texts):
        return option_texts
    return option_texts


def _normalize_question(raw: Dict[str, Any], fallback_num: int) -> Dict[str, Any]:
    raw_title = _normalize_text(raw.get("title_full_text") or raw.get("title"))
    question_num = _normalize_question_number(raw.get("question_num"), fallback_num)
    title = raw_title
    match = _QUESTION_NUMBER_RE.match(raw_title)
    if match:
        question_num = _normalize_question_number(match.group(1), fallback_num)
        stripped_title = _normalize_text(_LEADING_TYPE_TAG_RE.sub("", raw_title[match.end():]))
        title = stripped_title if stripped_title and not _TYPE_ONLY_TITLE_RE.fullmatch(stripped_title) else raw_title or f"Q{question_num}"
    elif not title:
        title = f"Q{question_num}"

    option_texts = [_normalize_text(text) for text in raw.get("option_texts") or []]
    option_texts = _resolve_matrix_option_texts(raw, [text for text in option_texts if text])
    text_inputs = max(0, int(raw.get("text_inputs") or 0))
    question_kind = str(raw.get("question_kind") or "").strip().lower()
    row_texts = [_normalize_text(text) for text in raw.get("row_texts") or []]
    row_texts = [text for text in row_texts if text]
    type_code = _infer_type_code({**raw, "options": len(option_texts), "text_inputs": text_inputs})
    is_description = not (
        option_texts
        or text_inputs > 0
        or question_kind in {"single", "multiple", "dropdown", "scale", "order", "matrix", "text", "multi_text"}
    )
    if is_description:
        type_code = "0"

    extra_fragments = [raw.get("title_text"), raw.get("tip_text")]
    forced_option_index, forced_option_text = _extract_force_select_option(raw_title or title, option_texts, extra_fragments=extra_fragments)
    if forced_option_index is None:
        forced_option_index, forced_option_text = _extract_arithmetic_option(raw_title or title, option_texts, extra_fragments=extra_fragments)
    forced_texts = _extract_forced_texts(raw_title or title, extra_fragments=extra_fragments)
    multi_min_limit: Optional[int] = None
    multi_max_limit: Optional[int] = None
    if type_code == "4":
        multi_min_limit, multi_max_limit = _extract_multi_select_limits(raw_title or title, option_count=len(option_texts), extra_fragments=extra_fragments)

    normalized: Dict[str, Any] = {
        "num": question_num,
        "title": title or raw_title or f"Q{question_num}",
        "description": "",
        "type_code": type_code,
        "options": len(option_texts),
        "rows": max(1, len(row_texts)),
        "row_texts": row_texts,
        "page": max(1, int(raw.get("page") or 1)),
        "option_texts": option_texts,
        "provider": SURVEY_PROVIDER_CREDAMO,
        "provider_question_id": str(raw.get("question_id") or question_num),
        "provider_page_id": str(raw.get("page") or 1),
        "provider_type": str(raw.get("provider_type") or question_kind or type_code).strip(),
        "has_jump": False,
        "jump_rules": [],
        "has_display_condition": False,
        "display_conditions": [],
        "has_dependent_display_logic": False,
        "controls_display_targets": [],
        "logic_parse_status": LOGIC_PARSE_STATUS_NONE,
        "question_media": list(raw.get("question_media") or []),
        "required": bool(raw.get("required")),
        "text_inputs": text_inputs,
        "text_input_labels": [],
        "is_description": is_description,
        "is_text_like": question_kind in {"text", "multi_text"} or (text_inputs > 0 and not option_texts),
        "is_multi_text": question_kind == "multi_text" or text_inputs > 1,
        "is_rating": False,
        "rating_max": max(len(option_texts), 1) if type_code == "5" else 0,
        "forced_option_index": forced_option_index,
        "forced_option_text": forced_option_text,
        "forced_texts": forced_texts,
        "multi_min_limit": multi_min_limit,
        "multi_max_limit": multi_max_limit,
    }
    return normalized


def _is_answerable_question(question: Dict[str, Any]) -> bool:
    option_count = int(question.get("options") or 0)
    text_inputs = int(question.get("text_inputs") or 0)
    type_code = str(question.get("type_code") or "").strip()
    return option_count > 0 or text_inputs > 0 or type_code in {"3", "4", "5", "6", "7", "11"}


def _page_has_answerable_questions(questions: List[Dict[str, Any]]) -> bool:
    return any(_is_answerable_question(question) for question in questions)


def _first_text(raw: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        text = _normalize_text(raw.get(key))
        if text:
            return text
    return ""


def _item_texts(items: list[Mapping[str, Any]], *keys: str) -> list[str]:
    result: list[str] = []
    for item in items:
        text = _first_text(item, *keys)
        if text:
            result.append(text)
    return result


def _raw_to_normalized_input(raw_question: Mapping[str, Any], *, fallback_num: int) -> Dict[str, Any]:
    provider_type = _raw_provider_type(raw_question)
    question_num = _raw_question_num(raw_question, fallback_num)
    qst_no = _first_text(raw_question, "qstNo", "questionNo", "qstNum", "sortNo") or f"Q{question_num}"
    title_text = _first_text(
        raw_question,
        "qstTitle",
        "qstName",
        "questionTitle",
        "questionName",
        "title",
        "name",
        "content",
        "display",
    )
    full_title = _normalize_text(f"{qst_no} {title_text}") if title_text and not title_text.startswith(qst_no) else title_text or qst_no
    choices = _as_mapping_list(raw_question.get("choices"))
    answers = _as_mapping_list(raw_question.get("answers"))
    question_type = _raw_question_type(raw_question)
    option_texts = _item_texts(answers if question_type == 4 else choices, "display", "answerContent", "choiceContent", "choiceTitle", "answerTitle", "content", "text", "title", "name")
    row_texts = _item_texts(choices if question_type == 4 else [], "display", "choiceContent", "choiceTitle", "content", "text", "title", "name")
    if not option_texts:
        option_texts = [f"选项 {index + 1}" for index in range(_raw_option_count(raw_question))]
    if question_type == 4 and not row_texts:
        row_texts = [f"第 {index + 1} 行" for index in range(_raw_row_count(raw_question))]
    text_inputs = 1 if question_type == 1 else 0
    question_id = _first_text(raw_question, "questionId", "qstId", "id") or str(question_num)
    return {
        "question_num": qst_no,
        "title": full_title,
        "title_full_text": full_title,
        "title_text": title_text,
        "tip_text": _first_text(raw_question, "tip", "tips", "remark", "description"),
        "question_kind": provider_type,
        "provider_type": provider_type,
        "option_texts": option_texts,
        "matrix_column_texts": option_texts if question_type == 4 else [],
        "row_texts": row_texts,
        "text_inputs": text_inputs,
        "page": raw_question.get("page") or raw_question.get("pageNo") or 1,
        "question_id": question_id,
        "required": bool(raw_question.get("required") or raw_question.get("mustAnswer")),
    }


def _survey_title(detail_data: Mapping[str, Any]) -> str:
    title = _first_text(detail_data, "surveyTitle", "title", "name", "projectName")
    if title:
        return title
    survey = detail_data.get("survey")
    if isinstance(survey, Mapping):
        title = _first_text(survey, "surveyTitle", "title", "name")
        if title:
            return title
    return "Credamo 见数问卷"


async def parse_credamo_survey(url: str) -> Tuple[List[Dict[str, Any]], str]:
    origin = _origin_from_url(url)
    short_url = _noauth_short_url(_short_url_from_url(url))
    headers = _request_headers(origin=origin, short_url=short_url, user_agent=DEFAULT_USER_AGENT)
    async with _CredamoHttpSession() as session:
        detail_data = await _fetch_detail(session, origin=origin, short_url=short_url, headers=headers)

    questions: List[Dict[str, Any]] = []
    for index, raw_question in enumerate(_iter_raw_questions(detail_data), start=1):
        normalized = _normalize_question(_raw_to_normalized_input(raw_question, fallback_num=index), fallback_num=index)
        if _is_answerable_question(normalized):
            questions.append(normalized)
    if not questions:
        raise CredamoParseError("见数详情接口未返回可解析题目，请确认链接为免登录问卷且已开放")
    return questions, _survey_title(detail_data)


__all__ = [
    "CredamoParseError",
    "parse_credamo_survey",
]

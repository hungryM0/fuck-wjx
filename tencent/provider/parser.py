"""腾讯问卷解析与标准化。"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import software.network.http as http_client
from software.app.config import DEFAULT_HTTP_HEADERS, _HTML_SPACE_RE
from software.providers.common import SURVEY_PROVIDER_QQ
from software.providers.contracts import LOGIC_PARSE_STATUS_UNKNOWN

QQ_SUPPORTED_PROVIDER_TYPES = {
    "radio",
    "checkbox",
    "select",
    "text",
    "textarea",
    "nps",
    "star",
    "matrix_radio",
    "matrix_star",
}
QQ_DESCRIPTION_PROVIDER_TYPES = {
    "description",
}
QQ_PROVIDER_TYPE_TO_INTERNAL = {
    "radio": "3",
    "checkbox": "4",
    "select": "7",
    "text": "1",
    "textarea": "1",
    "nps": "5",
    "star": "5",
    "matrix_radio": "6",
    "matrix_star": "6",
}
_QQ_TITLE_SUFFIX_RE = re.compile(r"(?:[-|｜]\s*)?腾讯问卷.*$", re.IGNORECASE)
_QQ_URL_RE = re.compile(r"/s\d+/(\d+)/([A-Za-z0-9_-]+)/?$", re.IGNORECASE)
_QQ_QUESTION_ID_TOKEN_RE = re.compile(r"\bq-[A-Za-z0-9_-]+\b", re.IGNORECASE)
_QQ_PAGE_ID_TOKEN_RE = re.compile(r"\bp-[A-Za-z0-9_-]+\b", re.IGNORECASE)
_QQ_HTTP_LOCALES = ("zhs", "zht", "zh", "en")
_QQ_LOGIN_PATH_RE = re.compile(r"^/r/login\.html(?:/)?$", re.IGNORECASE)
_QQ_FILLBLANK_TOKEN_RE = re.compile(r"\{fillblank-[^{}]+\}", re.IGNORECASE)
_QQ_FILLBLANK_SUFFIX_RE = re.compile(r"\s*[_＿]*\s*\{fillblank-[^{}]+\}", re.IGNORECASE)
_QQ_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\(([^)\s]+)\)(?:\{[^}]*\})?", re.IGNORECASE)
_QQ_LOGIC_END_TOKENS = (
    "submit",
    "finish",
    "complete",
    "end",
    "结束",
    "提交",
    "完成",
)
_QQ_LOGIN_REQUIRED_MESSAGE = "作答该问卷需要登录，请自行在后台开放访问权限"
_QQ_LOGIN_REQUIRED_TOKENS = (
    "open.weixin.qq.com/connect/confirm",
    "wj.qq.com/r/login.html",
    "/r/login.html",
    "need login",
    "login required",
    "require login",
    "未登录",
    "需登录",
    "需要登录",
)

acquire_parse_browser_session = None


def _extract_markdown_image_urls(text: Any) -> List[str]:
    raw_text = str(text or "").strip()
    if not raw_text:
        return []
    return [str(match.group(1) or "").strip() for match in _QQ_MARKDOWN_IMAGE_RE.finditer(raw_text) if str(match.group(1) or "").strip()]


def _strip_markdown_images(text: Any) -> str:
    raw_text = str(text or "")
    if not raw_text:
        return ""
    return _QQ_MARKDOWN_IMAGE_RE.sub(" ", raw_text)
def _normalize_media_url(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    markdown_urls = _extract_markdown_image_urls(text)
    if markdown_urls:
        text = markdown_urls[0]
    if text.startswith("//"):
        return f"https:{text}"
    return text


def _collect_image_urls(value: Any, *, depth: int = 0) -> List[str]:
    if depth > 5 or value is None:
        return []
    if isinstance(value, dict):
        collected: List[str] = []
        for key, item in value.items():
            key_text = str(key or "").strip().lower()
            if key_text in {"img", "image", "image_url", "img_url", "pic", "pic_url", "url", "src"}:
                normalized = _normalize_media_url(item)
                if normalized:
                    collected.append(normalized)
            collected.extend(_collect_image_urls(item, depth=depth + 1))
        return collected
    if isinstance(value, (list, tuple, set)):
        collected: List[str] = []
        for item in value:
            collected.extend(_collect_image_urls(item, depth=depth + 1))
        return collected
    normalized = _normalize_media_url(value)
    if not normalized:
        return []
    lowered = normalized.lower()
    if any(token in lowered for token in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
        return [normalized]
    return []


def _build_question_media_from_payload(question: Dict[str, Any], provider_type: str) -> List[Dict[str, Any]]:
    media: List[Dict[str, Any]] = []
    seen: set[tuple[str, int | None, str]] = set()

    def add(scope: str, index: int | None, label: str, raw_urls: List[str]) -> None:
        for raw_url in raw_urls:
            normalized_url = _normalize_media_url(raw_url)
            if not normalized_url:
                continue
            key = (scope, index, normalized_url)
            if key in seen:
                continue
            seen.add(key)
            media.append(
                {
                    "kind": "image",
                    "scope": scope,
                    "index": index,
                    "source_url": normalized_url,
                    "label": str(label or "").strip(),
                }
            )

    add("title", None, "题干图", _collect_image_urls(question.get("title")) + _collect_image_urls(question.get("description")))

    raw_options = question.get("options")
    if isinstance(raw_options, list):
        option_texts = _build_option_texts(question, provider_type)
        for option_index, option in enumerate(raw_options):
            option_label = option_texts[option_index] if option_index < len(option_texts) else f"选项 {option_index + 1}"
            add("option", option_index, option_label or f"选项 {option_index + 1}", _collect_image_urls(option))

    raw_rows = question.get("sub_titles")
    if isinstance(raw_rows, list):
        row_texts = _build_row_texts(question)
        for row_index, row in enumerate(raw_rows):
            row_label = row_texts[row_index] if row_index < len(row_texts) else f"第 {row_index + 1} 行"
            add("row", row_index, row_label or f"第 {row_index + 1} 行", _collect_image_urls(row))
    return media


def _normalize_html_text(value: Any) -> str:
    if not value:
        return ""
    cleaned = _strip_markdown_images(value)
    return _HTML_SPACE_RE.sub(" ", cleaned).strip()


def _is_qq_login_required_url(url: Any) -> bool:
    text = str(url or "").strip()
    if not text:
        return False
    try:
        parsed = urlparse(text if "://" in text else f"https://{text}")
    except Exception:
        return False
    host = (parsed.netloc or "").split(":", 1)[0].lower()
    path = str(parsed.path or "").strip()
    if host == "open.weixin.qq.com" and path.startswith("/connect/confirm"):
        return True
    if host == "wj.qq.com" and _QQ_LOGIN_PATH_RE.match(path):
        return True
    return False


def _is_qq_login_required_error(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_qq_login_required_error(key) or _is_qq_login_required_error(item):
                return True
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_is_qq_login_required_error(item) for item in value)
    text = str(value or "").strip().lower()
    if not text:
        return False
    return any(token in text for token in _QQ_LOGIN_REQUIRED_TOKENS)


def _is_qq_login_required_response(response: Any) -> bool:
    if response is None:
        return False
    response_url = str(getattr(response, "url", "") or "").strip()
    if _is_qq_login_required_url(response_url):
        return True
    history = getattr(response, "history", None) or []
    for item in history:
        if _is_qq_login_required_url(getattr(item, "url", "")):
            return True
    headers = getattr(response, "headers", None)
    if headers:
        try:
            location = headers.get("location")
        except Exception:
            location = None
        if _is_qq_login_required_url(location):
            return True
    return _is_qq_login_required_error(getattr(response, "text", ""))


def _raise_qq_login_required() -> None:
    raise RuntimeError(_QQ_LOGIN_REQUIRED_MESSAGE)


def _extract_qq_identifiers(url: str) -> Tuple[str, str]:
    text = str(url or "").strip()
    match = _QQ_URL_RE.search(text)
    if not match:
        raise RuntimeError("腾讯问卷链接格式无效，请确认链接完整且公开可访问")
    return str(match.group(1) or "").strip(), str(match.group(2) or "").strip()


def _normalize_qq_title(raw_title: Any) -> str:
    title = _normalize_html_text(str(raw_title or ""))
    if not title:
        return ""
    title = _QQ_TITLE_SUFFIX_RE.sub("", title).strip(" -_|")
    return title or _normalize_html_text(str(raw_title or ""))


def _build_qq_survey_page_url(survey_id: str, hash_value: str) -> str:
    return f"https://wj.qq.com/s2/{survey_id}/{hash_value}/"


def _build_qq_api_headers(page_url: str) -> Dict[str, str]:
    return {
        **DEFAULT_HTTP_HEADERS,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://wj.qq.com",
        "Referer": page_url,
    }


async def _request_qq_api(
    survey_id: str,
    endpoint: str,
    *,
    hash_value: str,
    headers: Dict[str, str],
    extra_params: Optional[Dict[str, Any]] = None,
    proxies: Any = None,
) -> Dict[str, Any]:
    url = f"https://wj.qq.com/api/v2/respondent/surveys/{survey_id}/{endpoint}"
    params: Dict[str, Any] = {
        "_": str(int(time.time() * 1000)),
        "hash": hash_value,
    }
    if extra_params:
        params.update(extra_params)
    response = await http_client.aget(
        url,
        params=params,
        headers=headers,
        timeout=15,
        proxies={} if proxies is None else proxies,
    )
    if _is_qq_login_required_response(response):
        _raise_qq_login_required()
    response.raise_for_status()
    try:
        payload = response.json()
    except Exception as exc:
        if _is_qq_login_required_response(response):
            _raise_qq_login_required()
        raise RuntimeError(f"腾讯问卷接口返回了无法解析的响应：{endpoint}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"腾讯问卷接口返回了非对象响应：{endpoint}")
    if _is_qq_login_required_error(payload):
        _raise_qq_login_required()
    return payload


def _ensure_qq_api_ok(payload: Dict[str, Any], endpoint: str) -> Dict[str, Any]:
    if _is_qq_login_required_error(payload):
        _raise_qq_login_required()
    code = str(payload.get("code") or "").upper()
    if code not in {"OK", "0"}:
        raise RuntimeError(f"腾讯问卷接口返回异常（{endpoint}）：{payload.get('code') or 'unknown'}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"腾讯问卷接口缺少 data 对象：{endpoint}")
    return data


def _raise_if_qq_login_required(value: Any) -> None:
    if _is_qq_login_required_error(value):
        _raise_qq_login_required()


def _build_qq_parse_result(
    questions: List[Dict[str, Any]],
    *,
    raw_title: Any,
    empty_error_message: str,
) -> Tuple[List[Dict[str, Any]], str]:
    title = _normalize_qq_title(raw_title or "")
    info = _standardize_qq_questions(questions)
    if not info:
        raise RuntimeError(empty_error_message)
    return info, title


async def _fetch_qq_locale_payload(
    survey_id: str,
    hash_value: str,
    headers: Dict[str, str],
    locale: str,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    meta_payload = await _request_qq_api(
        survey_id,
        "meta",
        hash_value=hash_value,
        headers=headers,
        extra_params={"locale": locale},
    )
    meta_data = _ensure_qq_api_ok(meta_payload, f"meta?locale={locale}")

    questions_payload = await _request_qq_api(
        survey_id,
        "questions",
        hash_value=hash_value,
        headers=headers,
        extra_params={"locale": locale},
    )
    questions_data = _ensure_qq_api_ok(questions_payload, f"questions?locale={locale}")
    questions = questions_data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise RuntimeError(f"腾讯问卷题目接口未返回可解析的题目数据（locale={locale}）")
    return meta_data, questions


async def _fetch_qq_survey_via_http(survey_id: str, hash_value: str) -> Tuple[List[Dict[str, Any]], str]:
    page_url = _build_qq_survey_page_url(survey_id, hash_value)
    headers = _build_qq_api_headers(page_url)

    session_payload = await _request_qq_api(
        survey_id,
        "session",
        hash_value=hash_value,
        headers=headers,
    )
    _ensure_qq_api_ok(session_payload, "session")

    last_error: Optional[Exception] = None
    for locale in _QQ_HTTP_LOCALES:
        try:
            meta_data, questions = await _fetch_qq_locale_payload(survey_id, hash_value, headers, locale)
            return _build_qq_parse_result(
                questions,
                raw_title=meta_data.get("title") or "",
                empty_error_message=f"腾讯问卷解析结果为空（locale={locale}）",
            )
        except Exception as exc:
            _raise_if_qq_login_required(exc)
            last_error = exc

    if last_error is not None:
        raise RuntimeError(f"腾讯问卷 HTTP 解析失败：{last_error}") from last_error
    raise RuntimeError("腾讯问卷 HTTP 解析失败：未获得可用 locale")


def _build_option_texts(question: Dict[str, Any], provider_type: str) -> List[str]:
    if provider_type in {"nps", "star"}:
        start = int(question.get("star_begin_num") or 0)
        count = max(0, int(question.get("star_num") or 0))
        return [str(start + idx) for idx in range(count)]
    if provider_type == "matrix_star":
        count = max(0, int(question.get("star_num") or 0))
        return [str(idx + 1) for idx in range(count)]
    raw_options = question.get("options")
    if not isinstance(raw_options, list):
        return []
    option_texts: List[str] = []
    for item in raw_options:
        text = _normalize_qq_option_text((item or {}).get("text") or "")
        option_texts.append(text)
    return option_texts


def _normalize_qq_option_text(value: Any) -> str:
    text = _normalize_html_text(str(value or ""))
    if not text:
        return ""
    text = _QQ_FILLBLANK_SUFFIX_RE.sub("", text).strip()
    text = _QQ_FILLBLANK_TOKEN_RE.sub("", text).strip()
    return _normalize_html_text(text)


def _option_payload_contains_fillblank(value: Any, *, depth: int = 0) -> bool:
    if depth > 4 or value is None:
        return False
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key or "").strip().lower()
            if key_text and "fillblank" in key_text:
                return True
            if _option_payload_contains_fillblank(item, depth=depth + 1):
                return True
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_option_payload_contains_fillblank(item, depth=depth + 1) for item in value)
    return bool(_QQ_FILLBLANK_TOKEN_RE.search(str(value or "")))


def _build_fillable_option_indices(question: Dict[str, Any], provider_type: str) -> List[int]:
    if provider_type not in {"radio", "checkbox", "select"}:
        return []
    raw_options = question.get("options")
    if not isinstance(raw_options, list):
        return []
    fillable: List[int] = []
    for idx, item in enumerate(raw_options):
        if _option_payload_contains_fillblank(item):
            fillable.append(idx)
    return fillable


def _build_row_texts(question: Dict[str, Any]) -> List[str]:
    raw_sub_titles = question.get("sub_titles")
    if not isinstance(raw_sub_titles, list):
        return []
    row_texts: List[str] = []
    for item in raw_sub_titles:
        text = _normalize_html_text(str((item or {}).get("text") or ""))
        if text:
            row_texts.append(text)
    return row_texts


def _resolve_option_count(question: Dict[str, Any], provider_type: str, option_texts: List[str]) -> int:
    if provider_type in QQ_DESCRIPTION_PROVIDER_TYPES:
        return 0
    if provider_type in {"nps", "star"}:
        return max(len(option_texts), int(question.get("star_num") or 0))
    if provider_type == "matrix_star":
        return max(len(option_texts), int(question.get("star_num") or 0))
    if option_texts:
        return len(option_texts)
    raw_options = question.get("options")
    if isinstance(raw_options, list):
        return len(raw_options)
    return 0


def _build_page_number_map(questions: List[Dict[str, Any]]) -> Dict[Tuple[str, str], int]:
    page_map: Dict[Tuple[str, str], int] = {}
    next_page = 1
    for question in questions:
        page_id = str(question.get("page_id") or "").strip()
        page_raw = str(question.get("page") or "").strip()
        key = (page_id, page_raw)
        if key in page_map:
            continue
        page_map[key] = next_page
        next_page += 1
    return page_map


def _merge_question_media_lists(*groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen: set[tuple[str, int | None, str]] = set()
    for group in groups:
        for item in list(group or []):
            if not isinstance(item, dict):
                continue
            key = (
                str(item.get("scope") or ""),
                item.get("index"),
                str(item.get("source_url") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def _merge_same_page_descriptions_into_questions(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pending: List[Dict[str, Any]] = []
    for item in items:
        if bool(item.get("is_description")):
            pending.append(item)
            continue

        if pending:
            current_page = int(item.get("page") or 1)
            mergeable = [desc for desc in pending if int(desc.get("page") or 1) == current_page]
            if mergeable:
                title_parts = [
                    str(desc.get("title") or "").strip()
                    for desc in mergeable
                    if str(desc.get("title") or "").strip()
                ]
                title_parts.append(str(item.get("title") or "").strip())
                item["title"] = " ".join(part for part in title_parts if part).strip()

                description_parts = [
                    str(desc.get("description") or "").strip()
                    for desc in mergeable
                    if str(desc.get("description") or "").strip()
                ]
                current_description = str(item.get("description") or "").strip()
                if current_description:
                    description_parts.append(current_description)
                item["description"] = "\n".join(part for part in description_parts if part).strip()

                merged_media: List[Dict[str, Any]] = []
                for desc in mergeable:
                    merged_media.extend(list(desc.get("question_media") or []))
                item["question_media"] = _merge_question_media_lists(
                    merged_media,
                    list(item.get("question_media") or []),
                )
        pending = []

    return items


def _inherit_description_browser_media(items: List[Dict[str, Any]]) -> None:
    pending: List[Dict[str, Any]] = []
    for item in items:
        if bool(item.get("is_description")):
            pending.append(item)
            continue
        if pending:
            current_page = int(item.get("page") or 1)
            mergeable = [desc for desc in pending if int(desc.get("page") or 1) == current_page]
            if mergeable:
                inherited_media: List[Dict[str, Any]] = []
                for desc in mergeable:
                    inherited_media.extend(list(desc.get("question_media") or []))
                item["question_media"] = _merge_question_media_lists(
                    inherited_media,
                    list(item.get("question_media") or []),
                )
        pending = []


def _assign_visible_display_numbers(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    visible_counter = 1
    for item in items:
        if bool(item.get("is_description")):
            item["display_num"] = None
            continue
        item["display_num"] = visible_counter
        visible_counter += 1
    return items


def _collect_token_refs(value: Any, pattern: re.Pattern[str], *, depth: int = 0) -> List[str]:
    if depth > 5 or value is None:
        return []
    if isinstance(value, dict):
        collected: List[str] = []
        for key, item in value.items():
            collected.extend(_collect_token_refs(key, pattern, depth=depth + 1))
            collected.extend(_collect_token_refs(item, pattern, depth=depth + 1))
        return collected
    if isinstance(value, (list, tuple, set)):
        collected: List[str] = []
        for item in value:
            collected.extend(_collect_token_refs(item, pattern, depth=depth + 1))
        return collected
    text = str(value or "").strip()
    if not text:
        return []
    return [str(match.group(0) or "").strip() for match in pattern.finditer(text)]


def _unique_text_list(values: List[str]) -> List[str]:
    normalized: List[str] = []
    seen = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _extract_qq_question_refs(value: Any) -> List[str]:
    return _unique_text_list(_collect_token_refs(value, _QQ_QUESTION_ID_TOKEN_RE))


def _extract_qq_page_refs(value: Any) -> List[str]:
    return _unique_text_list(_collect_token_refs(value, _QQ_PAGE_ID_TOKEN_RE))


def _normalize_option_index_list(raw_values: Any) -> List[int]:
    if not isinstance(raw_values, list):
        return []
    normalized: List[int] = []
    seen = set()
    for raw in raw_values:
        try:
            option_index = int(raw)
        except Exception:
            continue
        if option_index < 0 or option_index in seen:
            continue
        seen.add(option_index)
        normalized.append(option_index)
    return normalized


def _dedupe_dict_list(items: List[Dict[str, Any]], *, key_fields: tuple[str, ...]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        marker_parts: List[Any] = []
        for field_name in key_fields:
            value = item.get(field_name)
            if isinstance(value, list):
                marker_parts.append(tuple(value))
            else:
                marker_parts.append(value)
        marker = tuple(marker_parts)
        if marker in seen:
            continue
        seen.add(marker)
        normalized.append(item)
    return normalized


def _resolve_qq_jump_target_num(
    raw_target: Any,
    *,
    question_num_by_provider_id: Dict[str, int],
    first_question_num_by_page_id: Dict[str, int],
    max_question_num: int,
) -> Optional[int]:
    if raw_target in (None, "", [], {}, False):
        return None

    try:
        numeric_value = int(raw_target)
    except Exception:
        numeric_value = 0
    if numeric_value > 0:
        return numeric_value

    for question_id in _extract_qq_question_refs(raw_target):
        target_num = question_num_by_provider_id.get(question_id)
        if target_num:
            return target_num

    for page_id in _extract_qq_page_refs(raw_target):
        target_num = first_question_num_by_page_id.get(page_id)
        if target_num:
            return target_num

    lowered = str(raw_target or "").strip().lower()
    if lowered and any(token in lowered for token in _QQ_LOGIC_END_TOKENS):
        return max_question_num + 1
    return None


def _attach_qq_logic_metadata(
    raw_questions: List[Dict[str, Any]],
    normalized_questions: List[Dict[str, Any]],
) -> None:
    if not raw_questions or not normalized_questions:
        return

    normalized_by_provider_id: Dict[str, Dict[str, Any]] = {}
    question_num_by_provider_id: Dict[str, int] = {}
    first_question_num_by_page_id: Dict[str, int] = {}
    max_question_num = 0

    for item in normalized_questions:
        provider_question_id = str(item.get("provider_question_id") or "").strip()
        provider_page_id = str(item.get("provider_page_id") or "").strip()
        try:
            question_num = int(item.get("num") or 0)
        except Exception:
            question_num = 0
        if not provider_question_id or question_num <= 0:
            continue
        normalized_by_provider_id[provider_question_id] = item
        question_num_by_provider_id[provider_question_id] = question_num
        max_question_num = max(max_question_num, question_num)
        if provider_page_id and provider_page_id not in first_question_num_by_page_id:
            first_question_num_by_page_id[provider_page_id] = question_num

    source_targets: Dict[str, List[Dict[str, Any]]] = {}
    inbound_conditions: Dict[str, List[Dict[str, Any]]] = {}

    for raw_question in raw_questions:
        provider_question_id = str(raw_question.get("id") or "").strip()
        normalized_question = normalized_by_provider_id.get(provider_question_id)
        if normalized_question is None:
            continue

        raw_options = raw_question.get("options")
        options = raw_options if isinstance(raw_options, list) else []
        jump_rules: List[Dict[str, Any]] = []
        has_jump = False
        has_source_display_logic = False
        exact_logic_parsed = False

        question_jump_target = _resolve_qq_jump_target_num(
            raw_question.get("goto"),
            question_num_by_provider_id=question_num_by_provider_id,
            first_question_num_by_page_id=first_question_num_by_page_id,
            max_question_num=max_question_num,
        )
        if question_jump_target is not None:
            jump_rules.append(
                {
                    "option_index": -1,
                    "jumpto": question_jump_target,
                    "option_text": None,
                }
            )
            has_jump = True
            exact_logic_parsed = True
        elif raw_question.get("goto") not in (None, "", [], {}, False):
            has_jump = True

        for option_index, option in enumerate(options):
            if not isinstance(option, dict):
                continue

            option_jump_target = _resolve_qq_jump_target_num(
                option.get("goto"),
                question_num_by_provider_id=question_num_by_provider_id,
                first_question_num_by_page_id=first_question_num_by_page_id,
                max_question_num=max_question_num,
            )
            if option_jump_target is not None:
                jump_rules.append(
                    {
                        "option_index": option_index,
                        "jumpto": option_jump_target,
                        "option_text": _normalize_qq_option_text(option.get("text") or ""),
                    }
                )
                has_jump = True
                exact_logic_parsed = True
            elif option.get("goto") not in (None, "", [], {}, False):
                has_jump = True

            display_payload = option.get("display")
            if display_payload in (None, "", [], {}, False):
                continue
            has_source_display_logic = True
            target_question_ids = _extract_qq_question_refs(display_payload)
            if not target_question_ids:
                continue
            exact_logic_parsed = True
            for target_question_id in target_question_ids:
                target_question_num = question_num_by_provider_id.get(target_question_id)
                if not target_question_num:
                    continue
                source_targets.setdefault(provider_question_id, []).append(
                    {
                        "target_question_num": target_question_num,
                        "condition_option_indices": [option_index],
                        "condition_mode": "selected",
                    }
                )
                inbound_conditions.setdefault(target_question_id, []).append(
                    {
                        "condition_question_num": int(normalized_question.get("num") or 0),
                        "condition_mode": "selected",
                        "condition_option_indices": [option_index],
                    }
                )

        refer_question_ids = _extract_qq_question_refs(raw_question.get("refer"))
        if refer_question_ids and provider_question_id not in inbound_conditions:
            fallback_conditions: List[Dict[str, Any]] = []
            for refer_question_id in refer_question_ids:
                source_question_num = question_num_by_provider_id.get(refer_question_id)
                if not source_question_num:
                    continue
                fallback_conditions.append(
                    {
                        "condition_question_num": source_question_num,
                        "condition_mode": "selected",
                        "condition_option_indices": [],
                    }
                )
                source_targets.setdefault(refer_question_id, []).append(
                    {
                        "target_question_num": int(normalized_question.get("num") or 0),
                        "condition_option_indices": [],
                        "condition_mode": "selected",
                    }
                )
            if fallback_conditions:
                inbound_conditions[provider_question_id] = fallback_conditions

        normalized_question["jump_rules"] = _dedupe_dict_list(
            jump_rules,
            key_fields=("option_index", "jumpto"),
        )
        normalized_question["has_jump"] = bool(has_jump or normalized_question["jump_rules"])
        controls_display_targets = _dedupe_dict_list(
            [
                {
                    "target_question_num": int(item.get("target_question_num") or 0),
                    "condition_option_indices": _normalize_option_index_list(item.get("condition_option_indices")),
                    "condition_mode": str(item.get("condition_mode") or "selected").strip() or "selected",
                }
                for item in list(source_targets.get(provider_question_id) or [])
            ],
            key_fields=("target_question_num", "condition_option_indices", "condition_mode"),
        )
        if controls_display_targets or has_source_display_logic:
            normalized_question["has_dependent_display_logic"] = True
        if controls_display_targets:
            normalized_question["controls_display_targets"] = controls_display_targets

        raw_hidden = raw_question.get("hidden")
        if raw_hidden not in (None, "", [], {}, False) or refer_question_ids or provider_question_id in inbound_conditions:
            normalized_question["has_display_condition"] = True
        display_conditions = _dedupe_dict_list(
            [
                {
                    "condition_question_num": int(item.get("condition_question_num") or 0),
                    "condition_mode": str(item.get("condition_mode") or "selected").strip() or "selected",
                    "condition_option_indices": _normalize_option_index_list(item.get("condition_option_indices")),
                }
                for item in list(inbound_conditions.get(provider_question_id) or [])
                if int(item.get("condition_question_num") or 0) > 0
            ],
            key_fields=("condition_question_num", "condition_option_indices", "condition_mode"),
        )
        if display_conditions:
            normalized_question["display_conditions"] = display_conditions
            if any(_normalize_option_index_list(item.get("condition_option_indices")) for item in display_conditions):
                exact_logic_parsed = True

        has_any_logic = bool(
            normalized_question.get("has_jump")
            or normalized_question.get("has_display_condition")
            or normalized_question.get("has_dependent_display_logic")
        )
        if has_any_logic and exact_logic_parsed:
            normalized_question["logic_parse_status"] = "complete"
        elif has_any_logic:
            normalized_question["logic_parse_status"] = LOGIC_PARSE_STATUS_UNKNOWN


def _standardize_qq_questions(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    page_map = _build_page_number_map(questions)
    normalized: List[Dict[str, Any]] = []
    for idx, question in enumerate(questions, start=1):
        provider_type = str(question.get("type") or "").strip()
        title = _normalize_html_text(str(question.get("title") or ""))
        description = _normalize_html_text(str(question.get("description") or ""))
        page_id = str(question.get("page_id") or "").strip()
        page_raw = question.get("page")
        page = page_map.get((page_id, str(page_raw or "").strip()), 1)
        row_texts = _build_row_texts(question)
        option_texts = _build_option_texts(question, provider_type)
        fillable_options = _build_fillable_option_indices(question, provider_type)
        option_count = _resolve_option_count(question, provider_type, option_texts)
        is_description = provider_type in QQ_DESCRIPTION_PROVIDER_TYPES
        type_code = QQ_PROVIDER_TYPE_TO_INTERNAL.get(provider_type, "0") if not is_description else "0"
        supported = provider_type in QQ_SUPPORTED_PROVIDER_TYPES or is_description
        unsupported_reason = "" if supported else f"暂不支持腾讯题型：{provider_type or 'unknown'}"
        is_text_like = provider_type in {"text", "textarea"} and not is_description
        is_rating = provider_type in {"nps", "star"} and not is_description
        multi_min_limit = question.get("min_length") if provider_type == "checkbox" else None
        multi_max_limit = question.get("max_length") if provider_type == "checkbox" else None
        normalized.append({
            "num": idx,
            "title": title,
            "display_num": None,
            "description": description,
            "type_code": type_code,
            "options": option_count,
            "rows": len(row_texts) if row_texts else 1,
            "row_texts": row_texts,
            "page": page,
            "option_texts": option_texts,
            "forced_option_index": None,
            "forced_option_text": "",
            "fillable_options": fillable_options,
            "attached_option_selects": [],
            "has_attached_option_select": False,
            "is_location": False,
            "is_rating": is_rating,
            "is_description": is_description,
            "rating_max": option_count if is_rating else 0,
            "text_inputs": 1 if is_text_like else 0,
            "text_input_labels": [],
            "is_multi_text": False,
            "is_text_like": is_text_like,
            "has_jump": False,
            "jump_rules": [],
            "has_display_condition": False,
            "display_conditions": [],
            "has_dependent_display_logic": False,
            "controls_display_targets": [],
            "logic_parse_status": LOGIC_PARSE_STATUS_UNKNOWN,
            "question_media": _build_question_media_from_payload(question, provider_type),
            "slider_min": None,
            "slider_max": None,
            "slider_step": None,
            "multi_min_limit": multi_min_limit,
            "multi_max_limit": multi_max_limit,
            "provider": SURVEY_PROVIDER_QQ,
            "provider_question_id": str(question.get("id") or "").strip(),
            "provider_page_id": page_id,
            "provider_type": provider_type,
            "provider_page_raw": page_raw,
            "unsupported": not supported,
            "unsupported_reason": unsupported_reason,
            "required": bool(question.get("required", False)),
        })
    _attach_qq_logic_metadata(questions, normalized)
    return _assign_visible_display_numbers(_merge_same_page_descriptions_into_questions(normalized))


async def parse_qq_survey(url: str) -> Tuple[List[Dict[str, Any]], str]:
    if _is_qq_login_required_url(url):
        _raise_qq_login_required()
    survey_id, hash_value = _extract_qq_identifiers(url)

    try:
        return await _fetch_qq_survey_via_http(survey_id, hash_value)
    except Exception as exc:
        _raise_if_qq_login_required(exc)
        logging.exception("腾讯问卷 HTTP 解析失败，url=%r", url)
        raise RuntimeError(f"腾讯问卷 HTTP 解析失败：{exc}") from exc


__all__ = [
    "QQ_SUPPORTED_PROVIDER_TYPES",
    "QQ_PROVIDER_TYPE_TO_INTERNAL",
    "parse_qq_survey",
]



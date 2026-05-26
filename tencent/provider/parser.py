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
from software.network.browser.parse_pool import acquire_parse_browser_session

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
_QQ_HTTP_LOCALES = ("zhs", "zht", "zh", "en")
_QQ_LOGIN_PATH_RE = re.compile(r"^/r/login\.html(?:/)?$", re.IGNORECASE)
_QQ_FILLBLANK_TOKEN_RE = re.compile(r"\{fillblank-[^{}]+\}", re.IGNORECASE)
_QQ_FILLBLANK_SUFFIX_RE = re.compile(r"\s*[_＿]*\s*\{fillblank-[^{}]+\}", re.IGNORECASE)
_QQ_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\(([^)\s]+)\)(?:\{[^}]*\})?", re.IGNORECASE)
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
        proxies={},
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
    browser_media: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    title = _normalize_qq_title(raw_title or "")
    info = _standardize_qq_questions(questions)
    if browser_media:
        _merge_browser_media(info, browser_media)
        _inherit_description_browser_media(info)
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
    return _assign_visible_display_numbers(_merge_same_page_descriptions_into_questions(normalized))


async def _extract_qq_media_via_browser(page: Any) -> Dict[str, List[Dict[str, Any]]]:
    script = r"""
() => {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const normalizeUrl = (value) => {
    const text = clean(value);
    if (!text) return '';
    if (text.startsWith('//')) return `https:${text}`;
    return text;
  };
  const uniquePush = (items, media) => {
    if (!media || !media.source_url) return;
    const key = `${media.scope}|${String(media.index)}|${media.source_url}`;
    if (items.__seen.has(key)) return;
    items.__seen.add(key);
    items.list.push(media);
  };
  const result = {};
  const roots = Array.from(document.querySelectorAll('main [data-question-id], .question-list [data-question-id], .question-item, .question'));
  roots.forEach((root, index) => {
    const questionId = clean(root.getAttribute('data-question-id') || root.getAttribute('data-id') || root.id || String(index + 1));
    const holder = { list: [], __seen: new Set() };
    const optionNodes = Array.from(root.querySelectorAll('.choice-item, .option-item, li'));
    optionNodes.forEach((item, optionIndex) => {
      const label = clean(item.innerText || item.textContent || '') || `选项 ${optionIndex + 1}`;
      Array.from(item.querySelectorAll('img')).forEach((img) => {
        uniquePush(holder, {
          kind: 'image',
          scope: 'option',
          index: optionIndex,
          source_url: normalizeUrl(img.getAttribute('src') || img.getAttribute('data-src')),
          label,
        });
      });
    });
    const rowNodes = Array.from(root.querySelectorAll('tbody tr, .matrix-row'));
    rowNodes.forEach((row, rowIndex) => {
      const labelNode = row.querySelector('th, td, .label, .row-title');
      const label = clean((labelNode && (labelNode.innerText || labelNode.textContent)) || '') || `第 ${rowIndex + 1} 行`;
      Array.from(row.querySelectorAll('img')).forEach((img) => {
        uniquePush(holder, {
          kind: 'image',
          scope: 'row',
          index: rowIndex,
          source_url: normalizeUrl(img.getAttribute('src') || img.getAttribute('data-src')),
          label,
        });
      });
    });
    Array.from(root.querySelectorAll('img')).forEach((img) => {
      if (img.closest('.choice-item, .option-item, li, tbody tr, .matrix-row')) {
        return;
      }
      uniquePush(holder, {
        kind: 'image',
        scope: 'title',
        index: null,
        source_url: normalizeUrl(img.getAttribute('src') || img.getAttribute('data-src')),
        label: '题干图',
      });
    });
    result[questionId] = holder.list;
  });
  return result;
}
"""
    payload = await page.evaluate(script) or {}
    if not isinstance(payload, dict):
        return {}
    normalized: Dict[str, List[Dict[str, Any]]] = {}
    for key, value in payload.items():
        question_id = str(key or "").strip()
        if not question_id or not isinstance(value, list):
            continue
        normalized[question_id] = [item for item in value if isinstance(item, dict)]
    return normalized


async def _get_qq_browser_current_url(driver: Any, page: Any) -> str:
    try:
        return str(getattr(page, "url", "") or await driver.current_url() or "")
    except Exception:
        return ""


async def _ensure_qq_browser_ready(driver: Any, page: Any) -> None:
    current_url = await _get_qq_browser_current_url(driver, page)
    if _is_qq_login_required_url(current_url):
        _raise_qq_login_required()
    try:
        await page.wait_for_selector("main, .question-list, .page-control", state="visible", timeout=12000)
        return
    except Exception:
        try:
            await page.wait_for_load_state("networkidle", timeout=1500)
        except Exception:
            pass
    current_url = await _get_qq_browser_current_url(driver, page)
    if _is_qq_login_required_url(current_url):
        _raise_qq_login_required()


async def _fetch_qq_browser_payload(page: Any, survey_id: str, hash_value: str) -> Dict[str, Any]:
    payload = await page.evaluate(
        """async ({ surveyId, hashValue }) => {
            const sessionUrl = `https://wj.qq.com/api/v2/respondent/surveys/${surveyId}/session?_=${Date.now()}&hash=${encodeURIComponent(hashValue)}`;
            await fetch(sessionUrl, {
                credentials: 'include',
                headers: {
                    'Accept': 'application/json, text/plain, */*'
                }
            });

            const metaUrl = `https://wj.qq.com/api/v2/respondent/surveys/${surveyId}/meta?_=${Date.now()}&hash=${encodeURIComponent(hashValue)}&locale=zhs`;
            const metaResponse = await fetch(metaUrl, {
                credentials: 'include',
                headers: {
                    'Accept': 'application/json, text/plain, */*'
                }
            });
            const metaJson = await metaResponse.json();

            const requestUrl = `https://wj.qq.com/api/v2/respondent/surveys/${surveyId}/questions?_=${Date.now()}&hash=${encodeURIComponent(hashValue)}&locale=zhs`;
            const response = await fetch(requestUrl, { credentials: 'include' });
            const json = await response.json();
            return {
                status: response.status,
                ok: response.ok,
                payload: json,
                metaStatus: metaResponse.status,
                metaPayload: metaJson,
                title: document.title || '',
                pageUrl: location.href || ''
            };
        }""",
        {"surveyId": survey_id, "hashValue": hash_value},
    ) or {}
    if not isinstance(payload, dict):
        raise RuntimeError("腾讯问卷浏览器回退返回了无效响应")
    return payload


def _extract_qq_browser_questions(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    if _is_qq_login_required_url(payload.get("pageUrl")):
        _raise_qq_login_required()
    _raise_if_qq_login_required(payload)
    if not bool(payload.get("ok")):
        raise RuntimeError(f"腾讯问卷题目接口请求失败（HTTP {payload.get('status') or 'unknown'}）")
    meta_payload = payload.get("metaPayload") or {}
    meta_data = _ensure_qq_api_ok(meta_payload, "meta?locale=zhs")
    outer_payload = payload.get("payload") or {}
    questions_data = _ensure_qq_api_ok(outer_payload, "questions?locale=zhs")
    questions = questions_data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise RuntimeError("腾讯问卷题目接口未返回可解析的题目数据")
    return meta_data, questions


async def _fetch_qq_survey_via_browser(url: str, survey_id: str, hash_value: str) -> Tuple[List[Dict[str, Any]], str]:
    async with acquire_parse_browser_session() as driver:
        await driver.get(url)
        page = await driver.page()
        if page is None:
            raise RuntimeError("当前浏览器驱动不支持腾讯问卷解析")
        await _ensure_qq_browser_ready(driver, page)

        payload = await _fetch_qq_browser_payload(page, survey_id, hash_value)
        meta_data, questions = _extract_qq_browser_questions(payload)

        try:
            browser_media = await _extract_qq_media_via_browser(page)
        except Exception:
            browser_media = {}

        return _build_qq_parse_result(
            questions,
            raw_title=meta_data.get("title") or payload.get("title") or await driver.title() or "",
            empty_error_message="腾讯问卷解析结果为空，请确认链接有效且公开可访问",
            browser_media=browser_media,
        )


def _merge_browser_media(
    info: List[Dict[str, Any]],
    browser_media: Dict[str, List[Dict[str, Any]]],
) -> None:
    if not browser_media:
        return
    for item in info:
        question_id = str(item.get("provider_question_id") or "").strip()
        if not question_id:
            continue
        existing = list(item.get("question_media") or [])
        seen = {
            (
                str(media.get("scope") or ""),
                media.get("index"),
                str(media.get("source_url") or ""),
            )
            for media in existing
            if isinstance(media, dict)
        }
        for media in browser_media.get(question_id, []):
            key = (
                str(media.get("scope") or ""),
                media.get("index"),
                str(media.get("source_url") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            existing.append(media)
        item["question_media"] = existing


async def parse_qq_survey(url: str) -> Tuple[List[Dict[str, Any]], str]:
    if _is_qq_login_required_url(url):
        _raise_qq_login_required()
    survey_id, hash_value = _extract_qq_identifiers(url)

    try:
        return await _fetch_qq_survey_via_http(survey_id, hash_value)
    except Exception as exc:
        _raise_if_qq_login_required(exc)
        logging.exception("腾讯问卷 HTTP 解析失败，准备回退 Playwright，url=%r", url)

    try:
        return await _fetch_qq_survey_via_browser(url, survey_id, hash_value)
    except Exception:
        logging.exception("解析腾讯问卷失败，url=%r", url)
        raise


__all__ = [
    "QQ_SUPPORTED_PROVIDER_TYPES",
    "QQ_PROVIDER_TYPE_TO_INTERNAL",
    "parse_qq_survey",
]



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
from software.network.browser import create_playwright_driver

QQ_SUPPORTED_PROVIDER_TYPES = {
    "radio",
    "checkbox",
    "select",
    "text",
    "textarea",
    "nps",
    "matrix_radio",
    "matrix_star",
}
QQ_PROVIDER_TYPE_TO_INTERNAL = {
    "radio": "3",
    "checkbox": "4",
    "select": "7",
    "text": "1",
    "textarea": "1",
    "nps": "5",
    "matrix_radio": "6",
    "matrix_star": "6",
}
_QQ_TITLE_SUFFIX_RE = re.compile(r"(?:[-|｜]\s*)?腾讯问卷.*$", re.IGNORECASE)
_QQ_URL_RE = re.compile(r"/s\d+/(\d+)/([A-Za-z0-9_-]+)/?$", re.IGNORECASE)
_QQ_HTTP_LOCALES = ("zhs", "zht", "zh", "en")
_QQ_LOGIN_PATH_RE = re.compile(r"^/r/login\.html(?:/)?$", re.IGNORECASE)
_QQ_FILLBLANK_TOKEN_RE = re.compile(r"\{fillblank-[^{}]+\}", re.IGNORECASE)
_QQ_FILLBLANK_SUFFIX_RE = re.compile(r"\s*[_＿]*\s*\{fillblank-[^{}]+\}", re.IGNORECASE)
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


def _normalize_html_text(value: Any) -> str:
    if not value:
        return ""
    return _HTML_SPACE_RE.sub(" ", str(value)).strip()


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


def _request_qq_api(
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
    response = http_client.get(
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


def _fetch_qq_survey_via_http(survey_id: str, hash_value: str) -> Tuple[List[Dict[str, Any]], str]:
    page_url = _build_qq_survey_page_url(survey_id, hash_value)
    headers = _build_qq_api_headers(page_url)

    session_payload = _request_qq_api(
        survey_id,
        "session",
        hash_value=hash_value,
        headers=headers,
    )
    _ensure_qq_api_ok(session_payload, "session")

    last_error: Optional[Exception] = None
    for locale in _QQ_HTTP_LOCALES:
        try:
            meta_payload = _request_qq_api(
                survey_id,
                "meta",
                hash_value=hash_value,
                headers=headers,
                extra_params={"locale": locale},
            )
            meta_data = _ensure_qq_api_ok(meta_payload, f"meta?locale={locale}")

            questions_payload = _request_qq_api(
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

            title = _normalize_qq_title(meta_data.get("title") or "")
            info = _standardize_qq_questions(questions)
            if not info:
                raise RuntimeError(f"腾讯问卷解析结果为空（locale={locale}）")
            return info, title
        except Exception as exc:
            if _is_qq_login_required_error(exc):
                _raise_qq_login_required()
            last_error = exc

    if last_error is not None:
        raise RuntimeError(f"腾讯问卷 HTTP 解析失败：{last_error}") from last_error
    raise RuntimeError("腾讯问卷 HTTP 解析失败：未获得可用 locale")


def _build_option_texts(question: Dict[str, Any], provider_type: str) -> List[str]:
    if provider_type == "nps":
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
    if provider_type == "nps":
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
        type_code = QQ_PROVIDER_TYPE_TO_INTERNAL.get(provider_type, "0")
        supported = provider_type in QQ_SUPPORTED_PROVIDER_TYPES
        unsupported_reason = "" if supported else f"暂不支持腾讯题型：{provider_type or 'unknown'}"
        is_text_like = provider_type in {"text", "textarea"}
        is_rating = provider_type == "nps"
        multi_min_limit = question.get("min_length") if provider_type == "checkbox" else None
        multi_max_limit = question.get("max_length") if provider_type == "checkbox" else None
        normalized.append({
            "num": idx,
            "title": title,
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
            "is_description": False,
            "rating_max": option_count if is_rating else 0,
            "text_inputs": 1 if is_text_like else 0,
            "text_input_labels": [],
            "is_multi_text": False,
            "is_text_like": is_text_like,
            "has_jump": False,
            "jump_rules": [],
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
    return normalized


def parse_qq_survey(url: str) -> Tuple[List[Dict[str, Any]], str]:
    if _is_qq_login_required_url(url):
        _raise_qq_login_required()
    survey_id, hash_value = _extract_qq_identifiers(url)

    try:
        return _fetch_qq_survey_via_http(survey_id, hash_value)
    except Exception as exc:
        if _is_qq_login_required_error(exc):
            _raise_qq_login_required()
        logging.exception("腾讯问卷 HTTP 解析失败，准备回退 Playwright，url=%r", url)

    driver = None
    try:
        driver, _ = create_playwright_driver(
            headless=True,
            user_agent=None,
            persistent_browser=False,
            transient_launch=True,
        )
        driver.get(url)
        page = getattr(driver, "page", None)
        if page is None:
            raise RuntimeError("当前浏览器驱动不支持腾讯问卷解析")
        current_url = ""
        try:
            current_url = str(getattr(page, "url", "") or getattr(driver, "current_url", "") or "")
        except Exception:
            current_url = ""
        if _is_qq_login_required_url(current_url):
            _raise_qq_login_required()
        try:
            page.wait_for_selector("main, .question-list, .page-control", state="visible", timeout=12000)
        except Exception:
            time.sleep(2.0)
            try:
                current_url = str(getattr(page, "url", "") or getattr(driver, "current_url", "") or "")
            except Exception:
                current_url = ""
            if _is_qq_login_required_url(current_url):
                _raise_qq_login_required()
        payload = page.evaluate(
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
        if _is_qq_login_required_url(payload.get("pageUrl")) or _is_qq_login_required_error(payload):
            _raise_qq_login_required()
        if not bool(payload.get("ok")):
            raise RuntimeError(f"腾讯问卷题目接口请求失败（HTTP {payload.get('status') or 'unknown'}）")
        meta_payload = payload.get("metaPayload") or {}
        meta_data = _ensure_qq_api_ok(meta_payload, "meta?locale=zhs")
        outer_payload = payload.get("payload") or {}
        questions_data = _ensure_qq_api_ok(outer_payload, "questions?locale=zhs")
        questions_payload = questions_data.get("questions")
        if not isinstance(questions_payload, list) or not questions_payload:
            raise RuntimeError("腾讯问卷题目接口未返回可解析的题目数据")
        title = _normalize_qq_title(meta_data.get("title") or payload.get("title") or driver.title or "")
        info = _standardize_qq_questions(questions_payload)
        if not info:
            raise RuntimeError("腾讯问卷解析结果为空，请确认链接有效且公开可访问")
        return info, title
    except Exception:
        logging.exception("解析腾讯问卷失败，url=%r", url)
        raise
    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            logging.info("关闭腾讯问卷解析浏览器失败", exc_info=True)


__all__ = [
    "QQ_SUPPORTED_PROVIDER_TYPES",
    "QQ_PROVIDER_TYPE_TO_INTERNAL",
    "parse_qq_survey",
]



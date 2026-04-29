# -*- coding: utf-8 -*-
"""AI 协议解析、响应提取与重试请求。"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Iterable
from urllib.parse import urlsplit, urlunsplit

import software.network.http as http_client

_CHAT_COMPLETIONS_SUFFIX = "/chat/completions"
_RESPONSES_SUFFIX = "/responses"
_LEGACY_COMPLETIONS_SUFFIX = "/completions"
_AI_REQUEST_TIMEOUT_SECONDS = 25
_AI_MAX_RETRY_ATTEMPTS = 2
_AI_RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})
_AI_RETRY_BACKOFF_SECONDS = 1.0

logger = logging.getLogger(__name__)

__all__ = [
    "_AI_REQUEST_TIMEOUT_SECONDS",
    "_CHAT_COMPLETIONS_SUFFIX",
    "_RESPONSES_SUFFIX",
    "_execute_ai_request_with_retry",
    "_extract_chat_completion_text",
    "_extract_json_dict",
    "_extract_responses_text",
    "_is_ai_timeout_exception",
    "_is_endpoint_mismatch_error",
    "_normalize_endpoint_url",
    "_resolve_custom_endpoint",
    "call_chat_completions",
    "call_responses_api",
]


def _normalize_endpoint_url(raw_url: str) -> str:
    return str(raw_url or "").strip().rstrip("/")


def _path_endswith(path: str, suffix: str) -> bool:
    normalized_path = (path or "").rstrip("/").lower()
    return normalized_path.endswith(suffix)


def _replace_path_suffix(parts, suffix: str) -> str:
    normalized_path = (parts.path or "").rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, normalized_path + suffix, parts.query, parts.fragment))


def _resolve_custom_endpoint(base_url: str, api_protocol: str) -> tuple[str, str, bool]:
    normalized_base_url = _normalize_endpoint_url(base_url)
    if not normalized_base_url:
        raise RuntimeError("自定义模式需要配置 Base URL")

    parts = urlsplit(normalized_base_url)
    path = parts.path or ""

    if _path_endswith(path, _CHAT_COMPLETIONS_SUFFIX):
        return "chat_completions", normalized_base_url, True
    if _path_endswith(path, _RESPONSES_SUFFIX):
        return "responses", normalized_base_url, True
    if _path_endswith(path, _LEGACY_COMPLETIONS_SUFFIX):
        raise RuntimeError("暂不支持旧版 /completions 协议，请改用 /chat/completions 或 /responses")

    if str(api_protocol or "auto").strip().lower() == "responses":
        return "responses", _replace_path_suffix(parts, _RESPONSES_SUFFIX), False
    return "chat_completions", _replace_path_suffix(parts, _CHAT_COMPLETIONS_SUFFIX), False


def _is_endpoint_mismatch_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    mismatch_markers = (
        "404",
        "405",
        "410",
        "not found",
        "no route",
        "no handler",
        "unsupported path",
        "invalid url",
        "method not allowed",
    )
    return any(marker in message for marker in mismatch_markers)


def _extract_text_parts(content: Any) -> Iterable[str]:
    if isinstance(content, str):
        text = content.strip()
        if text:
            yield text
        return

    if not isinstance(content, list):
        return

    for item in content:
        if isinstance(item, str):
            text = item.strip()
            if text:
                yield text
            continue
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        text = str(item.get("text") or item.get("content") or "").strip()
        if item_type in {"text", "output_text", "input_text"} and text:
            yield text


def _extract_chat_completion_text(data: Dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("API 返回中缺少 choices")

    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = message.get("content")
    parts = list(_extract_text_parts(content))
    if parts:
        return "\n".join(parts).strip()
    raise RuntimeError("API 返回内容为空")


def _extract_responses_text(data: Dict[str, Any]) -> str:
    top_level_text = str(data.get("output_text") or "").strip()
    if top_level_text:
        return top_level_text

    output = data.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            parts = list(_extract_text_parts(item.get("content")))
            if parts:
                return "\n".join(parts).strip()

    raise RuntimeError("Responses API 返回内容为空")


def _extract_json_dict(response: Any) -> Dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _should_retry_ai_request(exc: Exception) -> bool:
    if isinstance(exc, (http_client.Timeout, http_client.ConnectTimeout, http_client.ReadTimeout, http_client.ConnectionError)):
        return True
    if isinstance(exc, http_client.RequestException) and not isinstance(exc, http_client.HTTPError):
        return True
    if isinstance(exc, http_client.HTTPError):
        response = getattr(exc, "response", None)
        status_code = int(getattr(response, "status_code", 0) or 0)
        return status_code in _AI_RETRYABLE_STATUS_CODES
    return False


def _is_ai_timeout_exception(exc: Exception) -> bool:
    return isinstance(exc, (http_client.Timeout, http_client.ConnectTimeout, http_client.ReadTimeout))


def _execute_ai_request_with_retry(request_name: str, request_func):
    last_error: Exception | None = None
    for attempt in range(1, _AI_MAX_RETRY_ATTEMPTS + 1):
        try:
            return request_func()
        except Exception as exc:
            last_error = exc
            should_retry = attempt < _AI_MAX_RETRY_ATTEMPTS and _should_retry_ai_request(exc)
            if not should_retry:
                raise
            logger.warning(
                "AI 请求临时失败，准备重试 | request=%s | attempt=%s/%s | error=%s",
                request_name,
                attempt,
                _AI_MAX_RETRY_ATTEMPTS,
                exc,
            )
            time.sleep(_AI_RETRY_BACKOFF_SECONDS)
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"AI 请求执行失败：{request_name}")


def call_chat_completions(
    url: str,
    api_key: str,
    model: str,
    question: str,
    system_prompt: str,
    timeout: int = _AI_REQUEST_TIMEOUT_SECONDS,
) -> str:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请简短回答这个问卷问题：{question}"},
        ],
        "max_tokens": 200,
        "temperature": 0.7,
    }
    try:
        resp = _execute_ai_request_with_retry(
            "chat_completions",
            lambda: http_client.post(url, headers=headers, json=payload, timeout=timeout, proxies={}).raise_for_status(),
        )
        data = resp.json()
        return _extract_chat_completion_text(data)
    except Exception as exc:
        raise RuntimeError(f"API 调用失败: {exc}") from exc


def call_responses_api(
    url: str,
    api_key: str,
    model: str,
    question: str,
    system_prompt: str,
    timeout: int = _AI_REQUEST_TIMEOUT_SECONDS,
) -> str:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "instructions": system_prompt,
        "input": f"请简短回答这个问卷问题：{question}",
        "max_output_tokens": 200,
        "temperature": 0.7,
    }
    try:
        resp = _execute_ai_request_with_retry(
            "responses",
            lambda: http_client.post(url, headers=headers, json=payload, timeout=timeout, proxies={}).raise_for_status(),
        )
        data = resp.json()
        return _extract_responses_text(data)
    except Exception as exc:
        raise RuntimeError(f"API 调用失败: {exc}") from exc

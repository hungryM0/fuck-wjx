# -*- coding: utf-8 -*-
"""免费 AI 服务请求与响应解析。"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import software.network.http as http_client
from software.app.config import AI_FREE_ENDPOINT, DEFAULT_HTTP_HEADERS
from software.integrations.ai.protocols import (
    _AI_REQUEST_TIMEOUT_SECONDS,
    _extract_json_dict,
    _execute_ai_request_with_retry,
    _is_ai_timeout_exception,
)
from software.network.proxy.session import (
    RandomIPAuthError,
    activate_trial,
    format_random_ip_error,
    get_device_id,
    get_session_snapshot,
)

logger = logging.getLogger(__name__)


class FreeAITimeoutError(RuntimeError):
    """免费 AI 在完成内部重试后仍然超时。"""


_FREE_AI_ERROR_MESSAGES = {
    "device_id_required": "免费 AI 调用失败：缺少设备标识（X-Device-ID）",
    "invalid_request_body": "免费 AI 调用失败：请求参数格式错误",
    "user_id_required": "免费 AI 调用失败：缺少 user_id",
    "invalid_user_id": "免费 AI 调用失败：user_id 无效",
    "invalid_question_type": "免费 AI 调用失败：question_type 无效",
    "blank_count_required": "免费 AI 调用失败：多项填空缺少 blank_count",
    "invalid_blank_count": "免费 AI 调用失败：blank_count 无效",
    "question_content_required": "免费 AI 调用失败：题干不能为空",
    "user_expired": "免费 AI 调用失败：账号已过期",
    "user_banned": "免费 AI 调用失败：账号已被封禁",
    "device_owned_by_other_user": "免费 AI 调用失败：当前设备已绑定其他账号",
    "device_banned": "免费 AI 调用失败：当前设备已被封禁",
    "user_ai_banned": "免费 AI 调用失败：当前账号已被禁止使用免费 AI",
    "ai_not_configured": "免费 AI 调用失败：服务端未配置 AI",
    "ai_upstream_failed": "免费 AI 调用失败：上游模型服务异常",
    "ai_empty_response": "免费 AI 调用失败：上游返回空答案",
    "ai_usage_missing": "免费 AI 调用失败：服务端使用记录异常",
    "ai_invalid_answers_format": "免费 AI 调用失败：服务端返回的 answers 格式无效",
    "ai_answers_count_mismatch": "免费 AI 调用失败：服务端返回的答案数量与空位数量不匹配",
}

_FREE_AI_LOG_TEXT_LIMIT = 240
_AI_RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})

__all__ = [
    "FreeAITimeoutError",
    "call_free_ai_api",
]


def _mask_user_id(user_id: Any) -> str:
    text = str(user_id or "").strip()
    if not text:
        return "unknown"
    if len(text) <= 2:
        return text
    return f"{text[:2]}***"


def _mask_device_id(device_id: Any) -> str:
    text = str(device_id or "").strip()
    if not text:
        return "unknown"
    if len(text) <= 8:
        return f"{text[:2]}***"
    return f"{text[:6]}***"


def _shorten_text(value: Any, limit: int = _FREE_AI_LOG_TEXT_LIMIT) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _serialize_log_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return repr(value)
    return str(value or "")


def _extract_response_body_preview(response: Any) -> str:
    data = _extract_json_dict(response)
    if data:
        return _shorten_text(_serialize_log_value(data))
    try:
        return _shorten_text(getattr(response, "text", ""))
    except Exception:
        return ""


def _log_free_ai_request_start(
    *,
    user_id: int,
    device_id: str,
    question_type: str,
    blank_count: Optional[int],
    question: str,
    system_prompt: str = "",
) -> None:
    logger.info(
        "免费 AI 请求开始 | endpoint=%s | question_type=%s | blank_count=%s | user_id=%s | device=%s | system_prompt_len=%s | question_preview=%s",
        AI_FREE_ENDPOINT,
        question_type,
        blank_count if blank_count is not None else "-",
        _mask_user_id(user_id),
        _mask_device_id(device_id),
        len(str(system_prompt or "").strip()),
        _shorten_text(question, 80),
    )


def _log_free_ai_request_failure(
    *,
    user_id: int,
    device_id: str,
    question_type: str,
    blank_count: Optional[int],
    status_code: int,
    detail: str,
    response: Any,
) -> None:
    logger.error(
        "免费 AI 请求失败 | endpoint=%s | question_type=%s | blank_count=%s | user_id=%s | device=%s | status=%s | detail=%s | body=%s",
        AI_FREE_ENDPOINT,
        question_type,
        blank_count if blank_count is not None else "-",
        _mask_user_id(user_id),
        _mask_device_id(device_id),
        status_code or "-",
        detail or "-",
        _extract_response_body_preview(response) or "-",
    )


def _log_free_ai_format_error(
    *,
    user_id: int,
    device_id: str,
    question_type: str,
    blank_count: Optional[int],
    payload: Dict[str, Any],
    error: Exception,
) -> None:
    logger.error(
        "免费 AI 返回格式异常 | question_type=%s | blank_count=%s | user_id=%s | device=%s | error=%s | payload=%s",
        question_type,
        blank_count if blank_count is not None else "-",
        _mask_user_id(user_id),
        _mask_device_id(device_id),
        error,
        _shorten_text(_serialize_log_value(payload)),
    )


def _format_free_ai_error(detail: str, status_code: int) -> str:
    if detail in _FREE_AI_ERROR_MESSAGES:
        return _FREE_AI_ERROR_MESSAGES[detail]
    if detail:
        return f"免费 AI 调用失败：{detail}"
    if status_code > 0:
        return f"免费 AI 调用失败：服务端异常（HTTP {status_code}）"
    return "免费 AI 调用失败：未知错误"


def _extract_free_error_detail(response: Any) -> str:
    data = _extract_json_dict(response)
    detail = data.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    if isinstance(detail, dict):
        return _shorten_text(_serialize_log_value(detail))
    if isinstance(detail, list):
        return _shorten_text(_serialize_log_value(detail))
    error = data.get("error")
    if isinstance(error, str) and error.strip():
        return error.strip()
    message = data.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return ""


def _ensure_free_ai_identity() -> tuple[int, str]:
    snapshot = get_session_snapshot()
    user_id = int(snapshot.get("user_id") or 0)
    device_id = str(snapshot.get("device_id") or "").strip()
    if not device_id:
        device_id = str(get_device_id() or "").strip()

    if user_id > 0 and device_id:
        logger.info(
            "免费 AI 身份就绪 | user_id=%s | device=%s | source=session",
            _mask_user_id(user_id),
            _mask_device_id(device_id),
        )
        return user_id, device_id

    logger.info(
        "免费 AI 身份缺失，尝试自动领取试用 | user_id=%s | device=%s",
        _mask_user_id(user_id),
        _mask_device_id(device_id),
    )
    try:
        activate_trial()
    except RandomIPAuthError as exc:
        raise RuntimeError(f"免费 AI 身份初始化失败：{format_random_ip_error(exc)}") from exc
    except Exception as exc:
        raise RuntimeError(f"免费 AI 身份初始化失败：{exc}") from exc

    snapshot = get_session_snapshot()
    user_id = int(snapshot.get("user_id") or 0)
    device_id = str(snapshot.get("device_id") or "").strip()
    if not device_id:
        device_id = str(get_device_id() or "").strip()
    if user_id <= 0 or not device_id:
        raise RuntimeError("免费 AI 身份初始化失败：未获取到有效 user_id/device_id")
    logger.info(
        "免费 AI 身份领取成功 | user_id=%s | device=%s",
        _mask_user_id(user_id),
        _mask_device_id(device_id),
    )
    return user_id, device_id


def _extract_free_answers(data: Dict[str, Any], question_type: str, blank_count: Optional[int]) -> List[str]:
    raw_answers = data.get("answers")
    if not isinstance(raw_answers, list) or not raw_answers:
        raise RuntimeError("免费 AI 返回格式异常：缺少 answers 数组")

    answers: List[str] = []
    for item in raw_answers:
        if not isinstance(item, str):
            raise RuntimeError("免费 AI 返回格式异常：answers 内含非字符串项")
        text = item.strip()
        if not text:
            raise RuntimeError("免费 AI 返回格式异常：answers 内含空字符串")
        answers.append(text)

    if question_type == "fill_blank":
        if len(answers) != 1:
            raise RuntimeError(f"免费 AI 返回格式异常：fill_blank 期望 1 个答案，实际 {len(answers)} 个")
        return answers

    expected = int(blank_count or 0)
    if expected <= 0:
        raise RuntimeError("免费 AI 返回格式异常：multi_fill_blank 缺少有效 blank_count")
    if len(answers) != expected:
        raise RuntimeError(f"免费 AI 返回格式异常：multi_fill_blank 期望 {expected} 个答案，实际 {len(answers)} 个")
    return answers


def call_free_ai_api(
    question: str,
    question_type: str,
    blank_count: Optional[int],
    system_prompt: str = "",
    timeout: int = _AI_REQUEST_TIMEOUT_SECONDS,
) -> List[str]:
    user_id, device_id = _ensure_free_ai_identity()
    _log_free_ai_request_start(
        user_id=user_id,
        device_id=device_id,
        question_type=question_type,
        blank_count=blank_count,
        question=question,
        system_prompt=system_prompt,
    )
    headers = {
        "Content-Type": "application/json",
        "X-Device-ID": device_id,
        **DEFAULT_HTTP_HEADERS,
    }
    payload: Dict[str, Any] = {
        "user_id": int(user_id),
        "question_type": question_type,
        "question_content": question,
    }
    normalized_system_prompt = str(system_prompt or "").strip()
    if normalized_system_prompt:
        payload["system_prompt"] = normalized_system_prompt
    if question_type == "multi_fill_blank":
        payload["blank_count"] = int(blank_count or 0)

    def _send_request():
        response = http_client.post(AI_FREE_ENDPOINT, headers=headers, json=payload, timeout=timeout, proxies={})
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code in _AI_RETRYABLE_STATUS_CODES:
            response.raise_for_status()
        return response

    try:
        response = _execute_ai_request_with_retry("free_ai", _send_request)
    except Exception as exc:
        if _is_ai_timeout_exception(exc):
            raise FreeAITimeoutError(
                "免费 AI 调用超时，已重试 2 次仍失败"
            ) from exc
        raise
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code != 200:
        detail = _extract_free_error_detail(response)
        _log_free_ai_request_failure(
            user_id=user_id,
            device_id=device_id,
            question_type=question_type,
            blank_count=blank_count,
            status_code=status_code,
            detail=detail,
            response=response,
        )
        raise RuntimeError(_format_free_ai_error(detail, status_code))
    data = _extract_json_dict(response)
    try:
        answers = _extract_free_answers(data, question_type, blank_count)
    except Exception as exc:
        _log_free_ai_format_error(
            user_id=user_id,
            device_id=device_id,
            question_type=question_type,
            blank_count=blank_count,
            payload=data,
            error=exc,
        )
        raise
    logger.info(
        "免费 AI 请求成功 | question_type=%s | blank_count=%s | user_id=%s | device=%s | answers_count=%s",
        question_type,
        blank_count if blank_count is not None else "-",
        _mask_user_id(user_id),
        _mask_device_id(device_id),
        len(answers),
    )
    return answers

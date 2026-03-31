# -*- coding: utf-8 -*-
"""AI 服务模块 - 支持多种 AI API 调用。"""
import json
import logging
from typing import Optional, Dict, Any, Iterable, List, Union
from urllib.parse import urlsplit, urlunsplit

import software.network.http as http_client
from software.network.proxy.session import (
    RandomIPAuthError,
    activate_trial,
    format_random_ip_error,
    get_device_id,
    get_session_snapshot,
)
from software.app.config import AI_FREE_ENDPOINT, DEFAULT_HTTP_HEADERS


logger = logging.getLogger(__name__)

# AI 服务提供商配置
# 注意: recommended_models 仅作为 UI 快捷选择建议,用户可以自由输入任意模型名
AI_PROVIDERS = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "recommended_models": ["deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-chat",
    },
    "qwen": {
        "label": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "recommended_models": ["qwen-max", "qwen-plus", "qwen-turbo", "qwen-long", "qwen-flash"],
        "default_model": "qwen-turbo",
    },
    "siliconflow": {
        "label": "硅基流动",
        "base_url": "https://api.siliconflow.cn/v1",
        "recommended_models": ["deepseek-ai/DeepSeek-V3.2", "Qwen/Qwen3-VL-8B-Instruct", "PaddlePaddle/PaddleOCR-VL-1.5"],
        "default_model": "deepseek-ai/DeepSeek-V3.2",
    },
    "volces": {
        "label": "火山引擎",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "recommended_models": ["doubao-seed-1-8-251228", "glm-4-7-251222", "doubao-seed-1-6-251015", "doubao-seed-1-6-lite-251015", "doubao-seed-1-6-flash-250828", "doubao-seed-1-6-250615"],
        "default_model": "doubao-seed-1-8-251228",
    },
    "custom": {
        "label": "自定义 (OpenAI 兼容)",
        "base_url": "",
        "recommended_models": [],
        "default_model": "",
    },
}

CUSTOM_API_PROTOCOLS = {
    "auto": {
        "label": "自动识别（推荐）",
        "description": "自动识别完整端点；只填 /v1 时自动尝试兼容协议",
    },
    "chat_completions": {
        "label": "Chat Completions",
        "description": "兼容 /chat/completions 协议",
    },
    "responses": {
        "label": "Responses",
        "description": "兼容 /responses 协议",
    },
}

AI_MODE_PROVIDER = "provider"
AI_MODE_FREE = "free"

FREE_QUESTION_TYPE_FILL = "fill_blank"
FREE_QUESTION_TYPE_MULTI = "multi_fill_blank"

_SYSTEM_PROMPT_BASE = (
    "你现在不是AI助手，而是一名有实际使用经验但不专业的普通用户。\n"
    "请按照“填写问卷/填空题”的方式作答，而不是进行解释或对话。\n\n"
    "回答规则：\n"
    "1. 只给出答案本身，不要解释原因，不要分析，不要教学\n"
    "2. 以个人体验和模糊印象为主，可以不确定、可以用“大概、感觉、差不多”等表达\n"
    "3. 回答尽量简短，避免长句\n"
    "4. 不要使用专业术语或严谨表述\n"
    "5. 如果不确定，可以直接说“不太清楚/没太注意”\n\n"
    "请注意：\n"
    "- 不要像AI助手一样分点说明\n"
    "- 不要补充背景知识\n"
    "- 不要解释题目\n"
    "- 不要自称“作为AI”\n\n"
    "如果你的回答开始变得专业、详细或像在解释，请立即改回普通用户的随意回答风格。"
)

DEFAULT_SYSTEM_PROMPT_FREE = _SYSTEM_PROMPT_BASE
DEFAULT_SYSTEM_PROMPT_PROVIDER = (
    _SYSTEM_PROMPT_BASE
    + "\n\n多项填空补充规则：\n"
      "6. 当题目有多个空位时，按空位顺序输出一个字符串，并使用 || 分隔每个答案（示例：答案1||答案2||答案3）"
)
def get_default_system_prompt(ai_mode: Any = AI_MODE_PROVIDER) -> str:
    """根据模式返回默认系统提示词。"""
    mode = str(ai_mode or AI_MODE_FREE).strip().lower()
    if mode == AI_MODE_FREE:
        return DEFAULT_SYSTEM_PROMPT_FREE
    return DEFAULT_SYSTEM_PROMPT_PROVIDER

_DEFAULT_AI_SETTINGS: Dict[str, Any] = {
    "ai_mode": AI_MODE_FREE,
    "provider": "deepseek",
    "api_key": "",
    "base_url": "",
    "api_protocol": "auto",
    "model": "",
    "system_prompt": DEFAULT_SYSTEM_PROMPT_FREE,
}
_RUNTIME_AI_SETTINGS: Optional[Dict[str, Any]] = None

_CHAT_COMPLETIONS_SUFFIX = "/chat/completions"
_RESPONSES_SUFFIX = "/responses"
_LEGACY_COMPLETIONS_SUFFIX = "/completions"

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


def _ensure_runtime_settings() -> Dict[str, Any]:
    global _RUNTIME_AI_SETTINGS
    if _RUNTIME_AI_SETTINGS is None:
        _RUNTIME_AI_SETTINGS = dict(_DEFAULT_AI_SETTINGS)
    return _RUNTIME_AI_SETTINGS


def get_ai_settings() -> Dict[str, Any]:
    """获取 AI 配置。"""
    settings = dict(_ensure_runtime_settings())
    settings["ai_mode"] = _normalize_ai_mode(settings.get("ai_mode"))
    provider = str(settings.get("provider") or "deepseek").strip()
    settings["provider"] = provider if provider in AI_PROVIDERS else "deepseek"
    settings["api_protocol"] = _normalize_custom_api_protocol(settings.get("api_protocol"))
    prompt = str(settings.get("system_prompt") or "").strip()
    settings["system_prompt"] = prompt or get_default_system_prompt(settings["ai_mode"])
    return settings


def save_ai_settings(
    ai_mode: Optional[str] = None,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    api_protocol: Optional[str] = None,
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
):
    """保存 AI 配置。"""
    settings = _ensure_runtime_settings()
    if ai_mode is not None:
        settings["ai_mode"] = _normalize_ai_mode(ai_mode)
    if provider is not None:
        settings["provider"] = str(provider)
    if api_key is not None:
        settings["api_key"] = str(api_key)
    if base_url is not None:
        settings["base_url"] = str(base_url)
    if api_protocol is not None:
        settings["api_protocol"] = _normalize_custom_api_protocol(api_protocol)
    if model is not None:
        settings["model"] = str(model)
    if system_prompt is not None:
        settings["system_prompt"] = str(system_prompt)


def get_ai_readiness_error(config: Optional[Dict[str, Any]] = None) -> str:
    """返回 AI 配置不可用的原因；空字符串表示已就绪。"""
    settings = get_ai_settings() if config is None else dict(config)
    ai_mode = _normalize_ai_mode(settings.get("ai_mode"))
    if ai_mode == AI_MODE_FREE:
        return ""

    provider = str(settings.get("provider") or "deepseek").strip() or "deepseek"
    provider_config = AI_PROVIDERS.get(provider)
    if provider_config is None:
        return "服务提供商无效"

    missing_fields: List[str] = []
    if not str(settings.get("api_key") or "").strip():
        missing_fields.append("API Key")

    if provider == "custom":
        if not str(settings.get("base_url") or "").strip():
            missing_fields.append("Base URL")
        if not str(settings.get("model") or "").strip():
            missing_fields.append("模型 ID")
    else:
        resolved_model = str(settings.get("model") or provider_config.get("default_model") or "").strip()
        if not resolved_model:
            missing_fields.append("模型 ID")

    if missing_fields:
        return f"缺少 {'、'.join(missing_fields)}"
    return ""


def is_ai_ready(config: Optional[Dict[str, Any]] = None) -> bool:
    """判断 AI 配置是否已满足调用条件。"""
    return not get_ai_readiness_error(config)


def _normalize_ai_mode(value: Any) -> str:
    mode = str(value or AI_MODE_FREE).strip().lower()
    if mode == AI_MODE_FREE:
        return AI_MODE_FREE
    return AI_MODE_PROVIDER


def _normalize_custom_api_protocol(value: Any) -> str:
    protocol = str(value or "auto").strip().lower()
    if protocol in CUSTOM_API_PROTOCOLS:
        return protocol
    return "auto"


def _normalize_free_question_type(value: Any) -> str:
    question_type = str(value or FREE_QUESTION_TYPE_FILL).strip().lower()
    if question_type == FREE_QUESTION_TYPE_MULTI:
        return FREE_QUESTION_TYPE_MULTI
    return FREE_QUESTION_TYPE_FILL


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

    normalized_protocol = _normalize_custom_api_protocol(api_protocol)
    if normalized_protocol == "responses":
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

    if question_type == FREE_QUESTION_TYPE_FILL:
        if len(answers) != 1:
            raise RuntimeError(f"免费 AI 返回格式异常：fill_blank 期望 1 个答案，实际 {len(answers)} 个")
        return answers

    expected = int(blank_count or 0)
    if expected <= 0:
        raise RuntimeError("免费 AI 返回格式异常：multi_fill_blank 缺少有效 blank_count")
    if len(answers) != expected:
        raise RuntimeError(f"免费 AI 返回格式异常：multi_fill_blank 期望 {expected} 个答案，实际 {len(answers)} 个")
    return answers


def _call_free_ai_api(
    question: str,
    question_type: str,
    blank_count: Optional[int],
    system_prompt: str = "",
    timeout: int = 30,
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
    if question_type == FREE_QUESTION_TYPE_MULTI:
        payload["blank_count"] = int(blank_count or 0)

    # AI 填空请求强制直连本机网络，不读取系统代理环境变量。
    response = http_client.post(AI_FREE_ENDPOINT, headers=headers, json=payload, timeout=timeout, proxies={})
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


def _call_chat_completions(
    url: str,
    api_key: str,
    model: str,
    question: str,
    system_prompt: str,
    timeout: int = 30,
) -> str:
    """调用 Chat Completions 兼容接口。"""
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
        resp = http_client.post(url, headers=headers, json=payload, timeout=timeout, proxies={})
        resp.raise_for_status()
        data = resp.json()
        return _extract_chat_completion_text(data)
    except Exception as exc:
        raise RuntimeError(f"API 调用失败: {exc}") from exc


def _call_responses_api(
    url: str,
    api_key: str,
    model: str,
    question: str,
    system_prompt: str,
    timeout: int = 30,
) -> str:
    """调用 Responses 兼容接口。"""
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
        resp = http_client.post(url, headers=headers, json=payload, timeout=timeout, proxies={})
        resp.raise_for_status()
        data = resp.json()
        return _extract_responses_text(data)
    except Exception as exc:
        raise RuntimeError(f"API 调用失败: {exc}") from exc


def generate_answer(
    question_title: str,
    *,
    question_type: str = FREE_QUESTION_TYPE_FILL,
    blank_count: Optional[int] = None,
) -> Union[str, List[str]]:
    """根据问题标题生成答案。"""
    config = get_ai_settings()
    readiness_error = get_ai_readiness_error(config)
    if readiness_error:
        raise RuntimeError(f"AI 配置不完整：{readiness_error}")

    resolved_question_type = _normalize_free_question_type(question_type)
    resolved_blank_count = int(blank_count or 0) if blank_count is not None else None
    ai_mode = _normalize_ai_mode(config.get("ai_mode"))
    system_prompt = str(config.get("system_prompt") or "").strip() or get_default_system_prompt(ai_mode)

    if ai_mode == AI_MODE_FREE:
        answers = _call_free_ai_api(
            question=question_title,
            question_type=resolved_question_type,
            blank_count=resolved_blank_count,
            system_prompt=system_prompt,
        )
        if resolved_question_type == FREE_QUESTION_TYPE_FILL:
            return answers[0]
        return answers

    if not config["api_key"]:
        raise RuntimeError("请先配置 API Key")

    provider = str(config.get("provider") or "deepseek")
    api_key = str(config.get("api_key") or "")

    # 确定 base_url 和 model
    if provider == "custom":
        base_url = str(config.get("base_url") or "")
        api_protocol = _normalize_custom_api_protocol(config.get("api_protocol"))
        model = str(config.get("model") or "")
        if not base_url:
            raise RuntimeError("自定义模式需要配置 Base URL")
        if not model:
            raise RuntimeError("自定义模式需要配置模型名称")
        resolved_protocol, request_url, has_explicit_endpoint = _resolve_custom_endpoint(base_url, api_protocol)
        if resolved_protocol == "responses":
            return _call_responses_api(request_url, api_key, model, question_title, system_prompt)
        try:
            return _call_chat_completions(request_url, api_key, model, question_title, system_prompt)
        except Exception as exc:
            if has_explicit_endpoint or api_protocol != "auto" or not _is_endpoint_mismatch_error(exc):
                raise
            fallback_url = f"{_normalize_endpoint_url(base_url)}{_RESPONSES_SUFFIX}"
            return _call_responses_api(fallback_url, api_key, model, question_title, system_prompt)
    provider_config = AI_PROVIDERS.get(provider)
    if not provider_config:
        raise RuntimeError(f"不支持的 AI 服务提供商: {provider}")
    base_url = provider_config["base_url"]
    model = str(config.get("model") or provider_config["default_model"])
    if provider == "siliconflow" and not model:
        raise RuntimeError("硅基流动需要先配置模型名称")

    request_url = f"{_normalize_endpoint_url(base_url)}{_CHAT_COMPLETIONS_SUFFIX}"
    return _call_chat_completions(request_url, api_key, model, question_title, system_prompt)


def test_connection() -> str:
    """测试 AI 连接。"""
    try:
        ai_mode = _normalize_ai_mode(get_ai_settings().get("ai_mode"))
        logger.info("AI 连接测试开始 | mode=%s", ai_mode)
        result = generate_answer(
            "这是一个测试问题，请回复'连接成功'",
            question_type=FREE_QUESTION_TYPE_FILL,
            blank_count=1,
        )
        if isinstance(result, list):
            preview = " | ".join(result[:3])
        else:
            preview = str(result)
        logger.info("AI 连接测试成功 | mode=%s | preview=%s", ai_mode, _shorten_text(preview, 80))
        return f"连接成功！AI 回复: {preview[:50]}..."
    except Exception as exc:
        logger.error("AI 连接测试失败: %s", exc)
        return f"连接失败: {exc}"



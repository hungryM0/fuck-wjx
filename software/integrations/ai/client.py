# -*- coding: utf-8 -*-
"""AI 服务门面 - 对外保持稳定入口。"""

from __future__ import annotations

import logging
from typing import List, Optional, Union

from software.integrations.ai.free_api import FreeAITimeoutError, call_free_ai_api
from software.integrations.ai.protocols import (
    _CHAT_COMPLETIONS_SUFFIX,
    _RESPONSES_SUFFIX,
    _is_endpoint_mismatch_error,
    _normalize_endpoint_url,
    _resolve_custom_endpoint,
    call_chat_completions,
    call_responses_api,
)
from software.integrations.ai.settings import (
    AI_MODE_FREE,
    AI_MODE_PROVIDER,
    AI_PROVIDERS,
    CUSTOM_API_PROTOCOLS,
    DEFAULT_SYSTEM_PROMPT_FREE,
    DEFAULT_SYSTEM_PROMPT_PROVIDER,
    FREE_QUESTION_TYPE_FILL,
    FREE_QUESTION_TYPE_MULTI,
    _normalize_ai_mode,
    _normalize_custom_api_protocol,
    _normalize_free_question_type,
    get_ai_readiness_error,
    get_ai_settings,
    get_default_system_prompt,
    save_ai_settings,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AI_MODE_FREE",
    "AI_MODE_PROVIDER",
    "AI_PROVIDERS",
    "CUSTOM_API_PROTOCOLS",
    "DEFAULT_SYSTEM_PROMPT_FREE",
    "DEFAULT_SYSTEM_PROMPT_PROVIDER",
    "FREE_QUESTION_TYPE_FILL",
    "FREE_QUESTION_TYPE_MULTI",
    "FreeAITimeoutError",
    "generate_answer",
    "get_ai_readiness_error",
    "get_ai_settings",
    "get_default_system_prompt",
    "save_ai_settings",
    "test_connection",
]


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
        answers = call_free_ai_api(
            question=question_title,
            question_type=resolved_question_type,
            blank_count=resolved_blank_count,
            system_prompt=system_prompt,
        )
        if resolved_question_type == FREE_QUESTION_TYPE_FILL:
            return answers[0]
        return answers

    api_key = str(config.get("api_key") or "")
    if not api_key:
        raise RuntimeError("请先配置 API Key")

    provider = str(config.get("provider") or "deepseek")
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
            return call_responses_api(request_url, api_key, model, question_title, system_prompt)
        try:
            return call_chat_completions(request_url, api_key, model, question_title, system_prompt)
        except Exception as exc:
            if has_explicit_endpoint or api_protocol != "auto" or not _is_endpoint_mismatch_error(exc):
                raise
            fallback_url = f"{_normalize_endpoint_url(base_url)}{_RESPONSES_SUFFIX}"
            return call_responses_api(fallback_url, api_key, model, question_title, system_prompt)

    provider_config = AI_PROVIDERS.get(provider)
    if not provider_config:
        raise RuntimeError(f"不支持的 AI 服务提供商: {provider}")
    base_url = provider_config["base_url"]
    model = str(config.get("model") or provider_config["default_model"])
    if provider == "siliconflow" and not model:
        raise RuntimeError("硅基流动需要先配置模型名称")

    request_url = f"{_normalize_endpoint_url(base_url)}{_CHAT_COMPLETIONS_SUFFIX}"
    return call_chat_completions(request_url, api_key, model, question_title, system_prompt)


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
        logger.info("AI 连接测试成功 | mode=%s | preview=%s", ai_mode, preview[:80])
        return f"连接成功！AI 回复: {preview[:50]}..."
    except Exception as exc:
        logger.error("AI 连接测试失败: %s", exc)
        return f"连接失败: {exc}"

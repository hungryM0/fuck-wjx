# -*- coding: utf-8 -*-
"""AI 设置、默认值与基础归一化。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

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
    "4. 不要使用专业术语或严谨表述\n\n"
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

__all__ = [
    "AI_MODE_FREE",
    "AI_MODE_PROVIDER",
    "AI_PROVIDERS",
    "CUSTOM_API_PROTOCOLS",
    "DEFAULT_SYSTEM_PROMPT_FREE",
    "DEFAULT_SYSTEM_PROMPT_PROVIDER",
    "FREE_QUESTION_TYPE_FILL",
    "FREE_QUESTION_TYPE_MULTI",
    "_normalize_ai_mode",
    "_normalize_custom_api_protocol",
    "_normalize_free_question_type",
    "get_ai_readiness_error",
    "get_ai_settings",
    "get_default_system_prompt",
    "save_ai_settings",
]


def get_default_system_prompt(ai_mode: Any = AI_MODE_PROVIDER) -> str:
    """根据模式返回默认系统提示词。"""
    mode = str(ai_mode or AI_MODE_FREE).strip().lower()
    if mode == AI_MODE_FREE:
        return DEFAULT_SYSTEM_PROMPT_FREE
    return DEFAULT_SYSTEM_PROMPT_PROVIDER


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

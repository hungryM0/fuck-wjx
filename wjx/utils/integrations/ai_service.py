# -*- coding: utf-8 -*-
"""AI 服务模块 - 支持多种 AI API 调用"""
import json
import requests
from typing import Optional, Dict, Any

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
    "openai": {
        "label": "ChatGPT",
        "base_url": "https://api.openai.com/v1",
        "recommended_models": ["gpt-5.2-2025-12-11", "gpt-5-2025-08-07", "gpt-5-mini-2025-08-07", "gpt-5-nano-2025-08-07", "gpt-4.1-2025-04-14", "chatgpt-4o-latest"],
        "default_model": "gpt-5-mini-2025-08-07",
    },
    "gemini": {
        "label": "Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "recommended_models": ["gemini-3-pro-preview", "gemini-3-flash-preview", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"],
        "default_model": "gemini-3-flash-preview",
    },
    "custom": {
        "label": "自定义 (OpenAI 兼容)",
        "base_url": "",
        "recommended_models": [],
        "default_model": "",
    },
}

DEFAULT_SYSTEM_PROMPT = "你是一名有相关使用经验但并非专业人士的普通用户。填写问卷时更多是凭印象和实际体验作答。回答可以简短，也可以有些模糊，不需要追求严谨。"

_DEFAULT_AI_SETTINGS: Dict[str, Any] = {
    "enabled": False,
    "provider": "deepseek",
    "api_key": "",
    "base_url": "",
    "model": "",
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
}
_RUNTIME_AI_SETTINGS: Optional[Dict[str, Any]] = None


def _ensure_runtime_settings() -> Dict[str, Any]:
    global _RUNTIME_AI_SETTINGS
    if _RUNTIME_AI_SETTINGS is None:
        _RUNTIME_AI_SETTINGS = dict(_DEFAULT_AI_SETTINGS)
    return _RUNTIME_AI_SETTINGS


def get_ai_settings() -> Dict[str, Any]:
    """获取 AI 配置"""
    return dict(_ensure_runtime_settings())


def save_ai_settings(
    enabled: Optional[bool] = None,
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
):
    """保存 AI 配置"""
    settings = _ensure_runtime_settings()
    if enabled is not None:
        settings["enabled"] = bool(enabled)
    if provider is not None:
        settings["provider"] = str(provider)
    if api_key is not None:
        settings["api_key"] = str(api_key)
    if base_url is not None:
        settings["base_url"] = str(base_url)
    if model is not None:
        settings["model"] = str(model)
    if system_prompt is not None:
        settings["system_prompt"] = str(system_prompt)


def _call_openai_compatible(
    base_url: str,
    api_key: str,
    model: str,
    question: str,
    system_prompt: str,
    timeout: int = 30,
) -> str:
    """调用 OpenAI 兼容接口"""
    url = f"{base_url.rstrip('/')}/chat/completions"
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
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content")
        if not content:
            raise RuntimeError("API 返回内容为空")
        return str(content).strip()
    except Exception as e:
        raise RuntimeError(f"API 调用失败: {e}")


def _call_gemini(
    api_key: str,
    model: str,
    question: str,
    system_prompt: str,
    timeout: int = 30,
) -> str:
    """调用 Google Gemini API"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"{system_prompt}\n\n请简短回答这个问卷问题：{question}"}
                ]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": 200,
            "temperature": 0.7,
        },
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text")
        )
        if not text:
            raise RuntimeError("Gemini API 返回内容为空")
        return str(text).strip()
    except Exception as e:
        raise RuntimeError(f"Gemini API 调用失败: {e}")


def generate_answer(question_title: str) -> str:
    """根据问题标题生成答案"""
    config = get_ai_settings()
    if not config["enabled"]:
        raise RuntimeError("AI 功能未启用")
    if not config["api_key"]:
        raise RuntimeError("请先配置 API Key")

    provider = config["provider"]
    api_key = config["api_key"]
    system_prompt = config["system_prompt"] or DEFAULT_SYSTEM_PROMPT

    # 确定 base_url 和 model
    if provider == "custom":
        base_url = config["base_url"]
        model = config["model"]
        if not base_url:
            raise RuntimeError("自定义模式需要配置 Base URL")
        if not model:
            raise RuntimeError("自定义模式需要配置模型名称")
    elif provider == "gemini":
        model = config["model"] or AI_PROVIDERS["gemini"]["default_model"]
        return _call_gemini(api_key, model, question_title, system_prompt)
    else:
        provider_config = AI_PROVIDERS.get(provider, AI_PROVIDERS["openai"])
        base_url = provider_config["base_url"]
        model = config["model"] or provider_config["default_model"]
        if provider == "siliconflow" and not model:
            raise RuntimeError("硅基流动需要先配置模型名称")

    return _call_openai_compatible(base_url, api_key, model, question_title, system_prompt)


def test_connection() -> str:
    """测试 AI 连接"""
    try:
        result = generate_answer("这是一个测试问题，请回复'连接成功'")
        return f"连接成功！AI 回复: {result[:50]}..."
    except Exception as e:
        return f"连接失败: {e}"

"""AI 外部服务适配。"""

from software.integrations.ai.client import (
    AI_PROVIDERS,
    DEFAULT_SYSTEM_PROMPT_FREE,
    DEFAULT_SYSTEM_PROMPT_PROVIDER,
    generate_answer,
    get_ai_readiness_error,
    get_ai_settings,
    get_default_system_prompt,
    save_ai_settings,
    test_connection,
)

__all__ = [
    "AI_PROVIDERS",
    "DEFAULT_SYSTEM_PROMPT_FREE",
    "DEFAULT_SYSTEM_PROMPT_PROVIDER",
    "generate_answer",
    "get_ai_readiness_error",
    "get_ai_settings",
    "get_default_system_prompt",
    "save_ai_settings",
    "test_connection",
]


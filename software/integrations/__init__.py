"""外部服务对接。"""

from software.integrations.ai import (
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
    "get_default_system_prompt",
    "get_ai_settings",
    "save_ai_settings",
    "test_connection",
]


"""外部服务对接"""
from wjx.utils.integrations.ai_service import (
    AI_PROVIDERS,
    DEFAULT_SYSTEM_PROMPT_FREE,
    DEFAULT_SYSTEM_PROMPT_PROVIDER,
    get_ai_settings,
    get_default_system_prompt,
    save_ai_settings,
    generate_answer,
    test_connection,
)

__all__ = [
    "AI_PROVIDERS",
    "DEFAULT_SYSTEM_PROMPT_FREE",
    "DEFAULT_SYSTEM_PROMPT_PROVIDER",
    "get_default_system_prompt",
    "get_ai_settings",
    "save_ai_settings",
    "generate_answer",
    "test_connection",
]

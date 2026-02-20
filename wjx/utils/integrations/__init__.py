"""外部服务对接"""
from wjx.utils.integrations.ai_service import (
    AI_PROVIDERS,
    get_ai_settings,
    save_ai_settings,
    DEFAULT_SYSTEM_PROMPT,
    generate_answer,
    test_connection,
)

__all__ = [
    "AI_PROVIDERS",
    "get_ai_settings",
    "save_ai_settings",
    "DEFAULT_SYSTEM_PROMPT",
    "generate_answer",
    "test_connection",
]

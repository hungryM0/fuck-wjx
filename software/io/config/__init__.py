"""配置 IO。"""

from software.core.config.codec import (
    CURRENT_CONFIG_SCHEMA_VERSION,
    _ensure_supported_config_payload,
    _select_user_agent_from_ratios,
    deserialize_question_entry,
    deserialize_runtime_config,
    normalize_runtime_config_payload,
    serialize_question_entry,
    serialize_runtime_config,
)
from software.core.config.schema import RuntimeConfig
from software.io.config.store import (
    _sanitize_filename,
    build_default_config_filename,
    load_config,
    save_config,
)

__all__ = [
    "RuntimeConfig",
    "CURRENT_CONFIG_SCHEMA_VERSION",
    "_ensure_supported_config_payload",
    "_sanitize_filename",
    "_select_user_agent_from_ratios",
    "build_default_config_filename",
    "deserialize_question_entry",
    "deserialize_runtime_config",
    "load_config",
    "normalize_runtime_config_payload",
    "save_config",
    "serialize_question_entry",
    "serialize_runtime_config",
]


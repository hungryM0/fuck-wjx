"""运行时配置序列化与校验逻辑。"""
from __future__ import annotations

import logging
import random
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

from software.core.config.schema import RuntimeConfig
from software.core.questions.consistency import normalize_rule_dict, sanitize_answer_rules
from software.core.questions.utils import serialize_random_int_range
from software.network.proxy import normalize_random_ip_enabled_value
from software.providers.common import (
    SURVEY_PROVIDER_WJX,
    detect_survey_provider,
    ensure_questions_provider_fields,
    normalize_survey_provider,
)
from software.logging.log_utils import log_suppressed_exception
from software.app.config import BROWSER_PREFERENCE, USER_AGENT_PRESETS

CURRENT_CONFIG_SCHEMA_VERSION = 4
_SUPPORTED_LEGACY_CONFIG_SCHEMA_VERSIONS = {3}
_LEGACY_CONFIG_KEYS = ("random_proxy_api", "ai_enabled")
_TEXT_RANDOM_MODES = {"none", "name", "mobile", "id_card", "integer"}

__all__ = [
    "CURRENT_CONFIG_SCHEMA_VERSION",
    "_select_user_agent_from_ratios",
    "serialize_question_entry",
    "deserialize_question_entry",
    "normalize_runtime_config_payload",
    "serialize_runtime_config",
    "deserialize_runtime_config",
    "_ensure_supported_config_payload",
]


def _filter_valid_user_agent_keys(selected_keys: List[str]) -> List[str]:
    return [key for key in (selected_keys or []) if key in USER_AGENT_PRESETS]


def _select_user_agent_from_ratios(ratios: Dict[str, int]) -> Tuple[Optional[str], Optional[str]]:
    """根据设备类型占比选择 User-Agent。"""
    device_to_ua_keys = {
        "wechat": ["wechat_android"],
        "mobile": ["mobile_android"],
        "pc": ["pc_web"],
    }
    weighted_devices: List[str] = []
    for device_type, weight in ratios.items():
        if weight > 0:
            weighted_devices.extend([device_type] * weight)
    if not weighted_devices:
        return None, None

    device_type = random.choice(weighted_devices)
    ua_keys = device_to_ua_keys.get(device_type, [])
    if not ua_keys:
        return None, None

    key = random.choice(ua_keys)
    preset = USER_AGENT_PRESETS.get(key) or {}
    return preset.get("ua"), preset.get("label")


def _prob_config_is_unset(value: Any) -> bool:
    if value is None:
        return True
    if value == -1:
        return True
    if isinstance(value, (list, tuple)):
        if not value:
            return True
        for item in value:
            try:
                if float(item) > 0:
                    return False
            except Exception:
                continue
        return True
    return False


def _custom_weights_has_positive(weights: Any) -> bool:
    if not isinstance(weights, list) or not weights:
        return False
    stack: List[Any] = list(weights)
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            stack.extend(item)
            continue
        try:
            if float(item) > 0:
                return True
        except Exception:
            continue
    return False


def _normalize_psycho_bias(data: Dict[str, Any]) -> str:
    bias = str(data.get("psycho_bias") or "custom")
    if bias in ("left", "center", "right"):
        return bias
    return "custom"


def _normalize_multi_text_blank_modes(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    normalized: List[str] = []
    for item in raw:
        mode = str(item or "none").strip().lower()
        normalized.append(mode if mode in _TEXT_RANDOM_MODES else "none")
    return normalized


def _normalize_multi_text_blank_ai_flags(raw: Any) -> List[bool]:
    if not isinstance(raw, list):
        return []
    return [bool(item) for item in raw]


def _normalize_random_int_range(raw: Any) -> List[int]:
    if raw in (None, "", []):
        return []
    return serialize_random_int_range(raw)


def _normalize_multi_text_blank_int_ranges(raw: Any) -> List[List[int]]:
    if not isinstance(raw, list):
        return []
    return [_normalize_random_int_range(item) for item in raw]


def _normalize_dimension_value(raw: Any) -> Optional[str]:
    try:
        text = str(raw or "").strip()
    except Exception:
        text = ""
    if not text or text == "未分组":
        return None
    return text


def _normalize_dimension_groups(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    groups: List[str] = []
    seen = set()
    for item in raw:
        normalized = _normalize_dimension_value(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        groups.append(normalized)
    return groups


def _migrate_config_payload_v3_to_v4(payload: Dict[str, Any]) -> Dict[str, Any]:
    migrated = dict(payload)
    migrated["dimension_groups"] = _normalize_dimension_groups(migrated.get("dimension_groups"))
    migrated["config_schema_version"] = CURRENT_CONFIG_SCHEMA_VERSION
    return migrated


def serialize_question_entry(entry) -> Dict[str, Any]:
    probabilities = entry.probabilities
    if (
        getattr(entry, "distribution_mode", None) == "custom"
        and _prob_config_is_unset(probabilities)
        and _custom_weights_has_positive(entry.custom_weights)
    ):
        probabilities = entry.custom_weights
    return {
        "question_type": entry.question_type,
        "probabilities": probabilities,
        "texts": entry.texts,
        "rows": entry.rows,
        "option_count": entry.option_count,
        "distribution_mode": entry.distribution_mode,
        "custom_weights": entry.custom_weights,
        "question_num": entry.question_num,
        "question_title": getattr(entry, "question_title", None),
        "survey_provider": normalize_survey_provider(getattr(entry, "survey_provider", None)),
        "provider_question_id": str(getattr(entry, "provider_question_id", None) or ""),
        "provider_page_id": str(getattr(entry, "provider_page_id", None) or ""),
        "ai_enabled": bool(getattr(entry, "ai_enabled", False)),
        "multi_text_blank_modes": _normalize_multi_text_blank_modes(getattr(entry, "multi_text_blank_modes", [])),
        "multi_text_blank_ai_flags": _normalize_multi_text_blank_ai_flags(getattr(entry, "multi_text_blank_ai_flags", [])),
        "multi_text_blank_int_ranges": _normalize_multi_text_blank_int_ranges(getattr(entry, "multi_text_blank_int_ranges", [])),
        "text_random_mode": str(getattr(entry, "text_random_mode", "none") or "none"),
        "text_random_int_range": _normalize_random_int_range(getattr(entry, "text_random_int_range", [])),
        "option_fill_texts": entry.option_fill_texts,
        "fillable_option_indices": entry.fillable_option_indices,
        "attached_option_selects": list(getattr(entry, "attached_option_selects", []) or []),
        "is_location": getattr(entry, "is_location", False),
        "dimension": _normalize_dimension_value(getattr(entry, "dimension", None)),
        "psycho_bias": str(getattr(entry, "psycho_bias", "custom") or "custom"),
    }


def deserialize_question_entry(data: Dict[str, Any]):
    from software.core.questions.config import QuestionEntry

    mode_raw = data.get("distribution_mode") or "random"
    probabilities = data.get("probabilities")
    custom_weights = data.get("custom_weights")
    if mode_raw == "custom" and _prob_config_is_unset(probabilities) and _custom_weights_has_positive(custom_weights):
        probabilities = custom_weights
    if mode_raw == "custom" and (custom_weights is None or custom_weights == []) and isinstance(probabilities, list):
        custom_weights = list(probabilities)
    return QuestionEntry(
        question_type=data.get("question_type") or "text",
        probabilities=probabilities,
        texts=data.get("texts"),
        rows=int(data.get("rows") or 1),
        option_count=int(data.get("option_count") or 0),
        distribution_mode=mode_raw,
        custom_weights=custom_weights,
        question_num=data.get("question_num"),
        question_title=data.get("question_title"),
        survey_provider=normalize_survey_provider(
            data.get("survey_provider"),
            default=SURVEY_PROVIDER_WJX,
        ),
        provider_question_id=str(data.get("provider_question_id") or "").strip() or None,
        provider_page_id=str(data.get("provider_page_id") or "").strip() or None,
        ai_enabled=bool(data.get("ai_enabled", False)),
        multi_text_blank_modes=_normalize_multi_text_blank_modes(data.get("multi_text_blank_modes")),
        multi_text_blank_ai_flags=_normalize_multi_text_blank_ai_flags(data.get("multi_text_blank_ai_flags")),
        multi_text_blank_int_ranges=_normalize_multi_text_blank_int_ranges(data.get("multi_text_blank_int_ranges")),
        text_random_mode=str(data.get("text_random_mode") or "none"),
        text_random_int_range=_normalize_random_int_range(data.get("text_random_int_range")),
        option_fill_texts=data.get("option_fill_texts"),
        fillable_option_indices=data.get("fillable_option_indices"),
        attached_option_selects=list(data.get("attached_option_selects") or []),
        is_location=bool(data.get("is_location")),
        dimension=_normalize_dimension_value(data.get("dimension")),
        psycho_bias=_normalize_psycho_bias(data),
    )


def normalize_runtime_config_payload(raw: Dict[str, Any]) -> RuntimeConfig:
    """将磁盘载荷规整为 RuntimeConfig。"""

    def _as_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _as_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _as_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"1", "true", "yes", "on"}:
                return True
            if text in {"0", "false", "no", "off", ""}:
                return False
            return default
        return bool(value)

    def _tuple_pair(value: Any) -> Tuple[int, int]:
        try:
            if isinstance(value, (list, tuple)) and len(value) >= 2:
                return int(value[0]), int(value[1])
        except Exception as exc:
            log_suppressed_exception("_tuple_pair failure", exc, level=logging.WARNING)
        return 0, 0

    def _browser_pref_list(value: Any) -> List[str]:
        allowed = set(BROWSER_PREFERENCE) | {"edge", "chrome"}
        prefs: List[str] = []
        raw_list: List[Any] = []
        if isinstance(value, str):
            raw_list = [value]
        elif isinstance(value, (list, tuple)):
            raw_list = list(value)
        if not raw_list:
            return prefs
        for item in raw_list:
            name = str(item or "").strip().lower()
            if not name or name not in allowed:
                continue
            if name not in prefs:
                prefs.append(name)
        return prefs

    config = RuntimeConfig()
    config.url = str(raw.get("url") or "")
    config.survey_title = str(raw.get("survey_title") or "")
    config.survey_provider = normalize_survey_provider(
        raw.get("survey_provider"),
        default=detect_survey_provider(config.url),
    )
    config.target = _as_int(raw.get("target"), 1)
    config.threads = _as_int(raw.get("threads"), 1)
    config.browser_preference = _browser_pref_list(raw.get("browser_preference"))
    config.submit_interval = _tuple_pair(raw.get("submit_interval"))
    config.answer_duration = _tuple_pair(raw.get("answer_duration"))
    config.timed_mode_enabled = bool(raw.get("timed_mode_enabled", False))
    config.timed_mode_interval = _as_float(raw.get("timed_mode_interval") or 3.0, 3.0)
    config.random_ip_enabled = normalize_random_ip_enabled_value(_as_bool(raw.get("random_ip_enabled"), False))
    custom_proxy_api = str(raw.get("custom_proxy_api") or "").strip()
    proxy_source = str(raw.get("proxy_source") or "default").strip().lower()
    if proxy_source not in ("default", "benefit", "custom"):
        proxy_source = "custom" if custom_proxy_api else "default"
    config.proxy_source = proxy_source
    config.custom_proxy_api = custom_proxy_api
    raw_area_code = raw.get("proxy_area_code")
    config.proxy_area_code = None if raw_area_code is None else str(raw_area_code)
    config.random_ua_enabled = bool(raw.get("random_ua_enabled", False))
    config.random_ua_keys = _filter_valid_user_agent_keys(raw.get("random_ua_keys") or [])

    raw_ratios = raw.get("random_ua_ratios")
    if isinstance(raw_ratios, dict):
        total = sum(_as_int(v, 0) for v in raw_ratios.values())
        if total == 100:
            config.random_ua_ratios = {
                "wechat": _as_int(raw_ratios.get("wechat"), 33),
                "mobile": _as_int(raw_ratios.get("mobile"), 33),
                "pc": _as_int(raw_ratios.get("pc"), 34),
            }
        else:
            config.random_ua_ratios = {"wechat": 33, "mobile": 33, "pc": 34}
    else:
        config.random_ua_ratios = {"wechat": 33, "mobile": 33, "pc": 34}

    config.fail_stop_enabled = bool(raw.get("fail_stop_enabled", True))
    config.pause_on_aliyun_captcha = bool(raw.get("pause_on_aliyun_captcha", True))
    config.reliability_mode_enabled = bool(raw.get("reliability_mode_enabled", True))
    config.psycho_target_alpha = _as_float(raw.get("psycho_target_alpha") or 0.9, 0.9)
    config.psycho_target_alpha = max(0.70, min(0.95, config.psycho_target_alpha))
    config.headless_mode = _as_bool(raw.get("headless_mode", True), True)
    config.answer_rules = []
    config.dimension_groups = _normalize_dimension_groups(raw.get("dimension_groups"))
    raw_rules = raw.get("answer_rules")
    if isinstance(raw_rules, list):
        for item in raw_rules:
            normalized_rule = normalize_rule_dict(item)
            if normalized_rule:
                config.answer_rules.append(normalized_rule)

    ai_keys = {
        "ai_mode",
        "ai_provider",
        "ai_api_key",
        "ai_base_url",
        "ai_api_protocol",
        "ai_model",
        "ai_system_prompt",
    }
    has_ai_keys = any(key in raw for key in ai_keys)
    config._ai_config_present = has_ai_keys
    if has_ai_keys:
        config.ai_mode = str(raw.get("ai_mode") or "free").strip().lower()
        if config.ai_mode not in {"free", "provider"}:
            config.ai_mode = "free"
        config.ai_provider = str(raw.get("ai_provider") or "deepseek")
        config.ai_api_key = str(raw.get("ai_api_key") or "")
        config.ai_base_url = str(raw.get("ai_base_url") or "")
        config.ai_api_protocol = str(raw.get("ai_api_protocol") or "auto")
        config.ai_model = str(raw.get("ai_model") or "")
        config.ai_system_prompt = str(raw.get("ai_system_prompt") or "")

    entries_data = raw.get("question_entries") or []
    config.question_entries = []
    for item in entries_data:
        try:
            entry = deserialize_question_entry(item)
            if (
                config.survey_provider != SURVEY_PROVIDER_WJX
                and getattr(entry, "provider_question_id", None)
                and normalize_survey_provider(getattr(entry, "survey_provider", None)) == SURVEY_PROVIDER_WJX
            ):
                entry.survey_provider = config.survey_provider
            config.question_entries.append(entry)
        except Exception as exc:
            logging.info("跳过损坏的题目配置: %s", exc)

    questions_info_data = raw.get("questions_info") or []
    if isinstance(questions_info_data, list):
        config.questions_info = ensure_questions_provider_fields(
            questions_info_data,
            default_provider=config.survey_provider,
        )
    else:
        config.questions_info = []
    config.answer_rules, _ = sanitize_answer_rules(config.answer_rules, config.questions_info or [])
    return config


def _coerce_schema_version(raw_value: Any) -> int:
    try:
        version = int(raw_value)
    except Exception:
        return 0
    return version if version > 0 else 0


def _ensure_supported_config_payload(payload: Dict[str, Any], *, config_path: str) -> Dict[str, Any]:
    legacy_keys = [key for key in _LEGACY_CONFIG_KEYS if key in payload]
    if legacy_keys:
        legacy_text = "、".join(legacy_keys)
        raise ValueError(
            f"配置文件使用了已移除的旧字段（{legacy_text}），请在旧版本客户端中重新保存后再导入：{config_path}"
        )
    schema_version = _coerce_schema_version(payload.get("config_schema_version"))
    if schema_version == CURRENT_CONFIG_SCHEMA_VERSION:
        current = dict(payload)
        current["config_schema_version"] = schema_version
        return current
    if schema_version in _SUPPORTED_LEGACY_CONFIG_SCHEMA_VERSIONS:
        logging.info(
            "检测到旧版配置 schema v%s，已按当前 schema v%s 兼容加载: %s",
            schema_version,
            CURRENT_CONFIG_SCHEMA_VERSION,
            config_path,
        )
        if schema_version == 3:
            return _migrate_config_payload_v3_to_v4(payload)
    raise ValueError(
        f"配置文件版本不受支持（当前仅支持 schema v{CURRENT_CONFIG_SCHEMA_VERSION}，实际为 v{schema_version}）：{config_path}"
    )


def serialize_runtime_config(config: RuntimeConfig) -> Dict[str, Any]:
    payload: Dict[str, Any] = asdict(config)
    payload["question_entries"] = [
        serialize_question_entry(entry) for entry in list(config.question_entries or [])
    ]
    payload["config_schema_version"] = CURRENT_CONFIG_SCHEMA_VERSION
    return payload


def deserialize_runtime_config(payload: Dict[str, Any]) -> RuntimeConfig:
    return normalize_runtime_config_payload(payload)



from __future__ import annotations

import json
import logging
import os
import random
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from wjx.utils.config import DEFAULT_RANDOM_UA_KEYS, USER_AGENT_PRESETS
from wjx.network.random_ip import normalize_random_ip_enabled_value

if TYPE_CHECKING:
    from wjx.engine import QuestionEntry


def get_runtime_directory() -> str:
    """获取运行时目录（项目根目录）"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # __file__ = wjx/utils/load_save.py -> 需要向上三层到项目根目录
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

__all__ = [
    "_sanitize_filename",
    "_select_user_agent_from_keys",
    "RuntimeConfig",
    "serialize_question_entry",
    "deserialize_question_entry",
    "load_config",
    "save_config",
    "ConfigPersistenceMixin",
]


def _sanitize_filename(value: Optional[str], max_length: int = 80) -> str:
    """Remove characters that are invalid for file names."""
    normalized = "".join(ch for ch in (value or "") if ch.isprintable())
    normalized = normalized.strip().replace(" ", "_")
    sanitized = "".join(ch for ch in normalized if ch not in '\\/:*?"<>|')
    if not sanitized:
        return "wjx_config"
    return sanitized[:max_length]


def _filter_valid_user_agent_keys(selected_keys: List[str]) -> List[str]:
    return [key for key in (selected_keys or []) if key in USER_AGENT_PRESETS]


def _select_user_agent_from_keys(selected_keys: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """Randomly pick a UA preset by key and return (ua, label)."""
    pool = _filter_valid_user_agent_keys(selected_keys)
    if not pool:
        return None, None
    key = random.choice(pool)
    preset = USER_AGENT_PRESETS.get(key) or {}
    return preset.get("ua"), preset.get("label")


def _ensure_configs_dir() -> str:
    """Ensure the configs directory exists and return its path."""
    base = get_runtime_directory()
    target = os.path.join(base, "configs")
    os.makedirs(target, exist_ok=True)
    return target


def _default_config_path() -> str:
    return os.path.join(get_runtime_directory(), "config.json")


@dataclass
class RuntimeConfig:
    url: str = ""
    target: int = 1
    threads: int = 1
    submit_interval: Tuple[int, int] = (0, 0)  # (min_seconds, max_seconds)
    answer_duration: Tuple[int, int] = (0, 0)
    timed_mode_enabled: bool = False
    timed_mode_interval: float = 3.0
    random_ip_enabled: bool = False
    random_proxy_api: Optional[str] = None
    proxy_source: str = "default"  # 代理源选择: "default" 或 "pikachu"
    random_ua_enabled: bool = False
    random_ua_keys: List[str] = field(default_factory=lambda: list(DEFAULT_RANDOM_UA_KEYS))
    fail_stop_enabled: bool = True
    question_entries: List[QuestionEntry] = field(default_factory=list)
    layout_hint: Optional[int] = None  # e.g. splitter position


def serialize_question_entry(entry: QuestionEntry) -> Dict[str, Any]:
    """Convert a QuestionEntry to a JSON-serializable dict."""
    return {
        "question_type": entry.question_type,
        "probabilities": entry.probabilities,
        "texts": entry.texts,
        "rows": entry.rows,
        "option_count": entry.option_count,
        "distribution_mode": entry.distribution_mode,
        "custom_weights": entry.custom_weights,
        "question_num": entry.question_num,
        "option_fill_texts": entry.option_fill_texts,
        "fillable_option_indices": entry.fillable_option_indices,
        "is_location": getattr(entry, "is_location", False),
    }


def deserialize_question_entry(data: Dict[str, Any]) -> "QuestionEntry":
    """Create a QuestionEntry from a persisted dict."""
    from wjx.engine import QuestionEntry
    mode_raw = data.get("distribution_mode") or "random"
    if mode_raw == "equal":
        mode_raw = "random"
    return QuestionEntry(
        question_type=data.get("question_type") or "text",
        probabilities=data.get("probabilities"),
        texts=data.get("texts"),
        rows=int(data.get("rows") or 1),
        option_count=int(data.get("option_count") or 0),
        distribution_mode=mode_raw,
        custom_weights=data.get("custom_weights"),
        question_num=data.get("question_num"),
        option_fill_texts=data.get("option_fill_texts"),
        fillable_option_indices=data.get("fillable_option_indices"),
        is_location=bool(data.get("is_location")),
    )


def _sanitize_runtime_config_payload(raw: Dict[str, Any]) -> RuntimeConfig:
    """Guard against malformed persisted data."""
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

    def _tuple_pair(value: Any) -> Tuple[int, int]:
        try:
            if isinstance(value, (list, tuple)) and len(value) >= 2:
                return int(value[0]), int(value[1])
        except Exception:
            pass
        return 0, 0

    def _legacy_interval_pair(value: Any) -> Optional[Tuple[int, int]]:
        """Support legacy payload: {'minutes','seconds','max_minutes','max_seconds'}."""
        if not isinstance(value, dict):
            return None
        min_seconds = _as_int(value.get("minutes")) * 60 + _as_int(value.get("seconds"))
        max_seconds = _as_int(value.get("max_minutes")) * 60 + _as_int(value.get("max_seconds"))
        if min_seconds < 0:
            min_seconds = 0
        if max_seconds < min_seconds:
            max_seconds = min_seconds
        return min_seconds, max_seconds

    config = RuntimeConfig()
    config.url = str(raw.get("url") or "")
    config.target = _as_int(raw.get("target") or raw.get("target_num") or 1, 1)
    config.threads = _as_int(raw.get("threads") or raw.get("num_threads") or 1, 1)

    submit_interval = raw.get("submit_interval")
    config.submit_interval = _tuple_pair(submit_interval)
    if config.submit_interval == (0, 0):
        legacy = _legacy_interval_pair(submit_interval)
        if legacy:
            config.submit_interval = legacy

    answer_duration = raw.get("answer_duration")
    config.answer_duration = _tuple_pair(answer_duration)
    if config.answer_duration == (0, 0):
        legacy_range = raw.get("answer_duration_range")
        if isinstance(legacy_range, dict):
            config.answer_duration = (
                max(0, _as_int(legacy_range.get("min_seconds"))),
                max(0, _as_int(legacy_range.get("max_seconds"))),
            )

    config.timed_mode_enabled = bool(raw.get("timed_mode_enabled") or (raw.get("timed_mode") or {}).get("enabled"))
    try:
        config.timed_mode_interval = _as_float(raw.get("timed_mode_interval") or 3.0, 3.0)
    except Exception:
        config.timed_mode_interval = 3.0

    # random ip/proxy: new key random_ip_enabled, legacy key random_proxy_enabled
    config.random_ip_enabled = normalize_random_ip_enabled_value(
        bool(raw.get("random_ip_enabled") if "random_ip_enabled" in raw else raw.get("random_proxy_enabled"))
    )
    config.random_proxy_api = raw.get("random_proxy_api") or raw.get("random_proxy_api_url") or None
    config.proxy_source = str(raw.get("proxy_source") or "default")

    # random UA: legacy payload stored under random_user_agent
    legacy_ua = raw.get("random_user_agent") if isinstance(raw.get("random_user_agent"), dict) else {}
    config.random_ua_enabled = bool(raw.get("random_ua_enabled") if "random_ua_enabled" in raw else legacy_ua.get("enabled"))
    selected_ua_keys = raw.get("random_ua_keys") if "random_ua_keys" in raw else legacy_ua.get("selected")
    config.random_ua_keys = _filter_valid_user_agent_keys(selected_ua_keys or [])
    config.fail_stop_enabled = bool(raw.get("fail_stop_enabled", True))
    config.layout_hint = raw.get("layout_hint", raw.get("paned_position"))

    # question entries: new key question_entries; legacy key questions
    entries_data = raw.get("question_entries") or raw.get("questions") or []
    config.question_entries = []
    for item in entries_data:
        try:
            config.question_entries.append(deserialize_question_entry(item))
        except Exception as exc:
            logging.debug(f"跳过损坏的题目配置: {exc}")
    return config


def load_config(path: Optional[str] = None) -> RuntimeConfig:
    """Load persisted runtime configuration."""
    config_path = os.fspath(path or _default_config_path())
    if not os.path.exists(config_path):
        return RuntimeConfig()
    try:
        with open(config_path, "r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except Exception as exc:
        logging.warning(f"读取配置失败: {exc}")
        return RuntimeConfig()
    return _sanitize_runtime_config_payload(payload if isinstance(payload, dict) else {})


def save_config(config: RuntimeConfig, path: Optional[str] = None) -> str:
    """Persist runtime configuration to disk and return the saved path."""
    config_path = os.fspath(path or _default_config_path())
    payload: Dict[str, Any] = asdict(config)
    payload["question_entries"] = [serialize_question_entry(entry) for entry in config.question_entries]
    with open(config_path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    return config_path


class ConfigPersistenceMixin:
    """
    Compatibility stub retained for legacy imports.
    New UI should call load_config/save_config directly.
    """

    def load_runtime_config(self, path: Optional[str] = None) -> RuntimeConfig:
        return load_config(path)

    def save_runtime_config(self, config: RuntimeConfig, path: Optional[str] = None) -> str:
        return save_config(config, path)

    def build_default_config_name(self, survey_title: Optional[str] = None) -> str:
        title = _sanitize_filename(survey_title or "")
        if title:
            return f"{title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        return f"wjx_config_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def get_configs_directory(self) -> str:
        return _ensure_configs_dir()

"""配置文件加载与保存 - 读写 JSON 配置"""
from __future__ import annotations
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception


import json
import os
import random
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from wjx.utils.app.config import DEFAULT_RANDOM_UA_KEYS, USER_AGENT_PRESETS, BROWSER_PREFERENCE
from wjx.network.random_ip import normalize_random_ip_enabled_value

if TYPE_CHECKING:
    from wjx.core.questions.config import QuestionEntry


def get_runtime_directory() -> str:
    """获取运行时目录（项目根目录）"""


    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        # 如果 exe 在 lib 目录中，返回上一级目录
        if os.path.basename(exe_dir) == "lib":
            return os.path.dirname(exe_dir)
        return exe_dir
    # __file__ = wjx/utils/io/load_save.py -> 需要向上四层到项目根目录
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def get_assets_directory() -> str:
    """获取 assets 资源目录"""
    if getattr(sys, "frozen", False):
        # exe 所在目录就是 lib 目录，assets 也在 lib 目录中
        exe_dir = os.path.dirname(sys.executable)
        assets_path = os.path.join(exe_dir, "assets")
        if os.path.isdir(assets_path):
            return assets_path
        
        # 兼容旧的 _internal 结构
        internal_assets = os.path.join(exe_dir, "_internal", "assets")
        if os.path.isdir(internal_assets):
            return internal_assets
            
        # 兼容 sys._MEIPASS（单文件模式）
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return os.path.join(meipass, "assets")
    return os.path.join(get_runtime_directory(), "assets")

__all__ = [
    "_sanitize_filename",
    "_select_user_agent_from_keys",
    "RuntimeConfig",
    "serialize_question_entry",
    "deserialize_question_entry",
    "load_config",
    "save_config",
    "ConfigPersistenceMixin",
    "get_runtime_directory",
    "get_assets_directory",
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
    browser_preference: List[str] = field(default_factory=list)
    submit_interval: Tuple[int, int] = (0, 0)  # (min_seconds, max_seconds)
    answer_duration: Tuple[int, int] = (0, 0)
    timed_mode_enabled: bool = False
    timed_mode_interval: float = 3.0
    random_ip_enabled: bool = False
    random_proxy_api: Optional[str] = None
    proxy_source: str = "default"  # 代理源选择: "default", "pikachu" 或 "custom"
    custom_proxy_api: str = ""  # 自定义代理API地址
    proxy_area_code: Optional[str] = None
    random_ua_enabled: bool = False
    random_ua_keys: List[str] = field(default_factory=lambda: list(DEFAULT_RANDOM_UA_KEYS))
    fail_stop_enabled: bool = True
    pause_on_aliyun_captcha: bool = True
    debug_mode: bool = False
    ai_enabled: bool = False
    ai_provider: str = "deepseek"
    ai_api_key: str = ""
    ai_base_url: str = ""
    ai_model: str = ""
    ai_system_prompt: str = ""
    question_entries: List[QuestionEntry] = field(default_factory=list)
    questions_info: Optional[List[Dict[str, Any]]] = field(default_factory=list)
    _ai_config_present: bool = field(default=False, init=False, repr=False)


def serialize_question_entry(entry: QuestionEntry) -> Dict[str, Any]:
    """Convert a QuestionEntry to a JSON-serializable dict."""
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
        "ai_enabled": bool(getattr(entry, "ai_enabled", False)),
        "option_fill_texts": entry.option_fill_texts,
        "fillable_option_indices": entry.fillable_option_indices,
        "is_location": getattr(entry, "is_location", False),
    }


def deserialize_question_entry(data: Dict[str, Any]) -> "QuestionEntry":
    """Create a QuestionEntry from a persisted dict."""
    from wjx.core.questions.config import QuestionEntry
    mode_raw = data.get("distribution_mode") or "random"
    if mode_raw == "equal":
        mode_raw = "random"

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

    probabilities = data.get("probabilities")
    custom_weights = data.get("custom_weights")
    if mode_raw == "custom" and _prob_config_is_unset(probabilities) and _custom_weights_has_positive(custom_weights):
        probabilities = custom_weights
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
        ai_enabled=bool(data.get("ai_enabled", False)),
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
        except Exception as exc:
            log_suppressed_exception("_tuple_pair: if isinstance(value, (list, tuple)) and len(value) >= 2: return int(value[0])...", exc, level=logging.WARNING)
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

    def _browser_pref_list(value: Any) -> List[str]:
        allowed = set(BROWSER_PREFERENCE) | {"edge", "chrome", "chromium"}
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
    config.target = _as_int(raw.get("target") or raw.get("target_num") or 1, 1)
    config.threads = _as_int(raw.get("threads") or raw.get("num_threads") or 1, 1)
    config.browser_preference = _browser_pref_list(raw.get("browser_preference") or raw.get("preferred_browser"))

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
    config.custom_proxy_api = str(raw.get("custom_proxy_api") or "")
    raw_area_code = raw.get("proxy_area_code")
    config.proxy_area_code = None if raw_area_code is None else str(raw_area_code)

    # random UA: legacy payload stored under random_user_agent
    legacy_ua_raw = raw.get("random_user_agent")
    legacy_ua: Dict[str, Any] = legacy_ua_raw if isinstance(legacy_ua_raw, dict) else {}
    config.random_ua_enabled = bool(raw.get("random_ua_enabled") if "random_ua_enabled" in raw else legacy_ua.get("enabled"))
    selected_ua_keys = raw.get("random_ua_keys") if "random_ua_keys" in raw else legacy_ua.get("selected")
    config.random_ua_keys = _filter_valid_user_agent_keys(selected_ua_keys or [])
    config.fail_stop_enabled = bool(raw.get("fail_stop_enabled", True))
    config.pause_on_aliyun_captcha = bool(raw.get("pause_on_aliyun_captcha", True))
    config.debug_mode = bool(raw.get("debug_mode", False))

    ai_keys = {
        "ai_enabled",
        "ai_provider",
        "ai_api_key",
        "ai_base_url",
        "ai_model",
        "ai_system_prompt",
    }
    has_ai_keys = any(key in raw for key in ai_keys)
    config._ai_config_present = has_ai_keys
    if has_ai_keys:
        config.ai_enabled = bool(raw.get("ai_enabled", False))
        config.ai_provider = str(raw.get("ai_provider") or "deepseek")
        config.ai_api_key = str(raw.get("ai_api_key") or "")
        config.ai_base_url = str(raw.get("ai_base_url") or "")
        config.ai_model = str(raw.get("ai_model") or "")
        config.ai_system_prompt = str(raw.get("ai_system_prompt") or "")

    # question entries: new key question_entries; legacy key questions
    entries_data = raw.get("question_entries") or raw.get("questions") or []
    config.question_entries = []
    for item in entries_data:
        try:
            config.question_entries.append(deserialize_question_entry(item))
        except Exception as exc:
            logging.debug(f"跳过损坏的题目配置: {exc}")

    # questions_info: 问卷解析信息（包含多选题限制等）
    questions_info_data = raw.get("questions_info") or []
    if isinstance(questions_info_data, list):
        config.questions_info = questions_info_data
    else:
        config.questions_info = []

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

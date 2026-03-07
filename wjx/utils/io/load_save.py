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
from wjx.core.questions.consistency import normalize_rule_dict
from wjx.network.proxy import normalize_random_ip_enabled_value

if TYPE_CHECKING:
    from wjx.core.questions.config import QuestionEntry

_CURRENT_CONFIG_SCHEMA_VERSION = 2
_TEXT_RANDOM_MODES = {"none", "name", "mobile"}


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
    "_select_user_agent_from_ratios",
    "build_default_config_filename",
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


def _select_user_agent_from_ratios(ratios: Dict[str, int]) -> Tuple[Optional[str], Optional[str]]:
    """根据设备类型占比选择 User-Agent"""
    # 映射设备类型到UA预设键
    device_to_ua_keys = {
        "wechat": ["wechat_android"],
        "mobile": ["mobile_android"],
        "pc": ["pc_web"],
    }

    # 先按占比选择设备类型
    weighted_devices = []
    for device_type, weight in ratios.items():
        if weight > 0:
            weighted_devices.extend([device_type] * weight)

    if not weighted_devices:
        return None, None

    # 随机选择设备类型
    device_type = random.choice(weighted_devices)

    # 从该设备类型的UA键中随机选一个
    ua_keys = device_to_ua_keys.get(device_type, [])
    if not ua_keys:
        return None, None

    key = random.choice(ua_keys)
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


def build_default_config_filename(survey_title: Optional[str] = None) -> str:
    """生成默认配置文件名（不包含时间戳）"""
    title = _sanitize_filename(survey_title or "")
    if title:
        return f"{title}.json"
    return "wjx_config.json"


@dataclass
class RuntimeConfig:
    url: str = ""
    survey_title: str = ""
    target: int = 1
    threads: int = 1
    browser_preference: List[str] = field(default_factory=list)
    submit_interval: Tuple[int, int] = (0, 0)  # (min_seconds, max_seconds)
    answer_duration: Tuple[int, int] = (0, 0)
    timed_mode_enabled: bool = False
    timed_mode_interval: float = 3.0
    random_ip_enabled: bool = False
    proxy_source: str = "default"  # 代理源选择: "default" 或 "custom"
    custom_proxy_api: str = ""  # 自定义代理API地址
    proxy_area_code: Optional[str] = None
    random_ua_enabled: bool = False
    random_ua_keys: List[str] = field(default_factory=lambda: list(DEFAULT_RANDOM_UA_KEYS))
    random_ua_ratios: Dict[str, int] = field(default_factory=lambda: {"wechat": 33, "mobile": 33, "pc": 34})  # 设备类型占比
    fail_stop_enabled: bool = True
    pause_on_aliyun_captcha: bool = True
    reliability_mode_enabled: bool = True  # 信效度生成总开关
    reliability_mode_type: str = "simple"  # 兼容旧配置字段：simple/psychometric
    psycho_target_alpha: float = 0.85  # 心理测量计划目标 Cronbach's Alpha（0.70-0.95）
    headless_mode: bool = True
    debug_mode: bool = False
    ai_enabled: bool = False
    ai_provider: str = "deepseek"
    ai_api_key: str = ""
    ai_base_url: str = ""
    ai_model: str = ""
    ai_system_prompt: str = ""
    answer_rules: List[Dict[str, Any]] = field(default_factory=list)
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
        "multi_text_blank_modes": _normalize_multi_text_blank_modes(getattr(entry, "multi_text_blank_modes", [])),
        "multi_text_blank_ai_flags": _normalize_multi_text_blank_ai_flags(getattr(entry, "multi_text_blank_ai_flags", [])),
        "text_random_mode": str(getattr(entry, "text_random_mode", "none") or "none"),
        "option_fill_texts": entry.option_fill_texts,
        "fillable_option_indices": entry.fillable_option_indices,
        "is_location": getattr(entry, "is_location", False),
        "is_reverse": bool(getattr(entry, "is_reverse", False)),
        "row_reverse_flags": list(getattr(entry, "row_reverse_flags", []) or []),
        "psycho_bias": str(getattr(entry, "psycho_bias", "custom") or "custom"),
    }


def _normalize_psycho_bias(data: Dict[str, Any]) -> str:
    """规范化 psycho_bias，仅接受 left/center/right。"""
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


def deserialize_question_entry(data: Dict[str, Any]) -> "QuestionEntry":
    """Create a QuestionEntry from a persisted dict."""
    from wjx.core.questions.config import QuestionEntry
    mode_raw = data.get("distribution_mode") or "random"

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
        ai_enabled=bool(data.get("ai_enabled", False)),
        multi_text_blank_modes=_normalize_multi_text_blank_modes(data.get("multi_text_blank_modes")),
        multi_text_blank_ai_flags=_normalize_multi_text_blank_ai_flags(data.get("multi_text_blank_ai_flags")),
        text_random_mode=str(data.get("text_random_mode") or "none"),
        option_fill_texts=data.get("option_fill_texts"),
        fillable_option_indices=data.get("fillable_option_indices"),
        is_location=bool(data.get("is_location")),
        is_reverse=bool(data.get("is_reverse", False)),
        row_reverse_flags=[bool(v) for v in (data.get("row_reverse_flags") or [])],
        psycho_bias=_normalize_psycho_bias(data),
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
            log_suppressed_exception("_tuple_pair: if isinstance(value, (list, tuple)) and len(value) >= 2: return int(value[0])...", exc, level=logging.WARNING)
        return 0, 0

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
    config.survey_title = str(raw.get("survey_title") or "")
    config.target = _as_int(raw.get("target"), 1)
    config.threads = _as_int(raw.get("threads"), 1)
    config.browser_preference = _browser_pref_list(raw.get("browser_preference"))

    submit_interval = raw.get("submit_interval")
    config.submit_interval = _tuple_pair(submit_interval)

    answer_duration = raw.get("answer_duration")
    config.answer_duration = _tuple_pair(answer_duration)

    config.timed_mode_enabled = bool(raw.get("timed_mode_enabled", False))
    try:
        config.timed_mode_interval = _as_float(raw.get("timed_mode_interval") or 3.0, 3.0)
    except Exception:
        config.timed_mode_interval = 3.0

    config.random_ip_enabled = normalize_random_ip_enabled_value(_as_bool(raw.get("random_ip_enabled"), False))
    legacy_proxy_api = str(raw.get("random_proxy_api") or "").strip()
    custom_proxy_api = str(raw.get("custom_proxy_api") or "").strip()
    if (not custom_proxy_api) and legacy_proxy_api:
        custom_proxy_api = legacy_proxy_api
    proxy_source = str(raw.get("proxy_source") or "default")
    if proxy_source not in ("default", "custom"):
        proxy_source = "custom" if custom_proxy_api else "default"
    config.proxy_source = proxy_source
    config.custom_proxy_api = custom_proxy_api
    raw_area_code = raw.get("proxy_area_code")
    config.proxy_area_code = None if raw_area_code is None else str(raw_area_code)

    config.random_ua_enabled = bool(raw.get("random_ua_enabled", False))
    selected_ua_keys = raw.get("random_ua_keys")
    config.random_ua_keys = _filter_valid_user_agent_keys(selected_ua_keys or [])

    # random UA ratios: 设备类型占比配置
    raw_ratios = raw.get("random_ua_ratios")
    if isinstance(raw_ratios, dict):
        # 验证占比总和是否为100
        total = sum(_as_int(v, 0) for v in raw_ratios.values())
        if total == 100:
            config.random_ua_ratios = {
                "wechat": _as_int(raw_ratios.get("wechat"), 33),
                "mobile": _as_int(raw_ratios.get("mobile"), 33),
                "pc": _as_int(raw_ratios.get("pc"), 34),
            }
        else:
            # 占比不合法，使用默认值
            config.random_ua_ratios = {"wechat": 33, "mobile": 33, "pc": 34}
    else:
        config.random_ua_ratios = {"wechat": 33, "mobile": 33, "pc": 34}

    config.fail_stop_enabled = bool(raw.get("fail_stop_enabled", True))
    config.pause_on_aliyun_captcha = bool(raw.get("pause_on_aliyun_captcha", True))
    config.reliability_mode_enabled = bool(raw.get("reliability_mode_enabled", True))
    config.reliability_mode_type = str(raw.get("reliability_mode_type") or "simple")
    if config.reliability_mode_type not in ("simple", "psychometric"):
        config.reliability_mode_type = "simple"
    config.psycho_target_alpha = _as_float(raw.get("psycho_target_alpha") or 0.85, 0.85)
    config.psycho_target_alpha = max(0.70, min(0.95, config.psycho_target_alpha))
    config.headless_mode = _as_bool(raw.get("headless_mode", True), True)
    config.debug_mode = bool(raw.get("debug_mode", False))
    config.answer_rules = []
    raw_rules = raw.get("answer_rules")
    if isinstance(raw_rules, list):
        for item in raw_rules:
            normalized_rule = normalize_rule_dict(item)
            if normalized_rule:
                config.answer_rules.append(normalized_rule)

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

    entries_data = raw.get("question_entries") or []
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


def _strip_json_comments(raw_text: str) -> str:
    """移除 JSON 文本中的 // 与 /* */ 注释（保留字符串内容）。"""
    text = str(raw_text or "").lstrip("\ufeff")
    if not text:
        return ""

    out: List[str] = []
    in_string = False
    escaped = False
    in_line_comment = False
    in_block_comment = False
    quote = '"'
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                out.append(ch)
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            quote = ch
            out.append(ch)
            i += 1
            continue

        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue

        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def _coerce_schema_version(raw_value: Any) -> int:
    try:
        version = int(raw_value)
    except Exception:
        return 1
    return version if version > 0 else 1


def _migrate_v1_to_v2(payload: Dict[str, Any]) -> Dict[str, Any]:
    migrated: Dict[str, Any] = dict(payload)

    # 代理字段迁移：random_proxy_api -> proxy_source/custom_proxy_api
    legacy_proxy_api = str(migrated.get("random_proxy_api") or "").strip()
    custom_proxy_api = str(migrated.get("custom_proxy_api") or "").strip()
    if (not custom_proxy_api) and legacy_proxy_api:
        custom_proxy_api = legacy_proxy_api
    proxy_source = str(migrated.get("proxy_source") or "").strip().lower()
    if proxy_source not in ("default", "custom"):
        proxy_source = "custom" if custom_proxy_api else "default"
    migrated["proxy_source"] = proxy_source
    migrated["custom_proxy_api"] = custom_proxy_api
    migrated.pop("random_proxy_api", None)

    # 多项填空细粒度配置迁移：缺失时写入空列表，后续由业务按空列表兜底
    entries = migrated.get("question_entries")
    if isinstance(entries, list):
        updated_entries: List[Any] = []
        for raw_entry in entries:
            if not isinstance(raw_entry, dict):
                updated_entries.append(raw_entry)
                continue
            entry = dict(raw_entry)
            entry["multi_text_blank_modes"] = _normalize_multi_text_blank_modes(entry.get("multi_text_blank_modes"))
            entry["multi_text_blank_ai_flags"] = _normalize_multi_text_blank_ai_flags(entry.get("multi_text_blank_ai_flags"))
            updated_entries.append(entry)
        migrated["question_entries"] = updated_entries

    migrated["config_schema_version"] = 2
    return migrated


def _upgrade_config_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    current: Dict[str, Any] = dict(payload)
    schema_version = _coerce_schema_version(current.get("config_schema_version"))

    if schema_version < 2:
        current = _migrate_v1_to_v2(current)
        schema_version = 2

    current["config_schema_version"] = schema_version
    return current


def load_config(path: Optional[str] = None, *, strict: bool = False) -> RuntimeConfig:
    """Load persisted runtime configuration.

    strict=True 时，遇到坏配置会抛出 ValueError，供 UI 明确提示用户。
    strict=False 时，读取失败回退默认配置，避免启动中断。
    """
    config_path = os.fspath(path or _default_config_path())
    if not os.path.exists(config_path):
        return RuntimeConfig()
    try:
        with open(config_path, "r", encoding="utf-8") as fp:
            raw_text = fp.read()
        clean_text = _strip_json_comments(raw_text)
        if not clean_text.strip():
            default_path = os.path.abspath(_default_config_path())
            current_path = os.path.abspath(config_path)
            if not strict and current_path == default_path:
                try:
                    with open(config_path, "w", encoding="utf-8") as fp:
                        fp.write("{}\n")
                except Exception as repair_exc:
                    logging.debug(f"自动修复空配置失败: {config_path} -> {repair_exc}")
            raise ValueError("配置文件为空")
        payload = json.loads(clean_text)
    except Exception as exc:
        error_message = f"读取配置失败: {config_path} -> {exc}"
        if strict:
            logging.error(error_message)
            raise ValueError(error_message) from exc
        logging.warning(error_message)
        return RuntimeConfig()
    if not isinstance(payload, dict):
        error_message = f"读取配置失败: {config_path} -> JSON 顶层必须是对象"
        if strict:
            raise ValueError(error_message)
        logging.warning(error_message)
        return RuntimeConfig()
    try:
        payload = _upgrade_config_payload(payload)
    except Exception as exc:
        error_message = f"迁移配置失败: {config_path} -> {exc}"
        if strict:
            raise ValueError(error_message) from exc
        logging.warning(error_message)
        return RuntimeConfig()
    return _sanitize_runtime_config_payload(payload)


def save_config(config: RuntimeConfig, path: Optional[str] = None) -> str:
    """Persist runtime configuration to disk and return the saved path."""
    config_path = os.fspath(path or _default_config_path())
    payload: Dict[str, Any] = asdict(config)
    payload["question_entries"] = [serialize_question_entry(entry) for entry in config.question_entries]
    payload["config_schema_version"] = _CURRENT_CONFIG_SCHEMA_VERSION
    payload.pop("random_proxy_api", None)
    with open(config_path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    return config_path


class ConfigPersistenceMixin:
    """
    兼容层：保留旧调用入口，内部转发到 load_config/save_config。
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


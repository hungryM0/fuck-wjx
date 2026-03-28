# -*- coding: utf-8 -*-


import logging

"""
应用配置常量

集中管理应用的各种配置参数，方便统一修改和维护
"""

import os
import re
import sys
from pathlib import Path
from typing import Dict, Optional

from software.app.settings_store import (
    app_settings as _app_settings,
    get_bool_from_qsettings as _get_bool_from_qsettings,
)

app_settings = _app_settings
get_bool_from_qsettings = _get_bool_from_qsettings

NAVIGATION_TEXT_VISIBLE_SETTING_KEY = "navigation_selected_text_visible"

_ENV_FILE_NAME = ".env"
def _read_windows_env_var(key: str) -> str:
    if sys.platform != "win32":
        return ""
    try:
        import winreg  # type: ignore
    except Exception:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as reg_key:
            value, _ = winreg.QueryValueEx(reg_key, key)
    except FileNotFoundError:
        return ""
    except Exception:
        return ""
    if value is None:
        return ""
    try:
        return str(value).strip()
    except Exception:
        return ""


def _find_env_file() -> Optional[Path]:
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass))
        try:
            candidates.append(Path(sys.executable).resolve().parent)
        except Exception as exc:
            logging.warning(f"_find_env_file: {exc}")
    try:
        candidates.append(Path(__file__).resolve().parent)
    except Exception as exc:
        logging.warning(f"_find_env_file: {exc}")
    candidates.append(Path.cwd())

    seen = set()
    for directory in candidates:
        try:
            resolved = directory.resolve()
        except Exception:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        candidate = resolved / _ENV_FILE_NAME
        if candidate.is_file():
            return candidate
    return None


def _parse_env_file(path: Path) -> Dict[str, str]:
    env_map: Dict[str, str] = {}
    try:
        with path.open("r", encoding="utf-8") as fp:
            for raw_line in fp:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                if key:
                    env_map[key] = value
    except Exception as exc:
        logging.warning(f"_parse_env_file: {exc}")
    return env_map


# 延迟初始化环境变量，避免模块导入时的阻塞
_ENV_FILE_PATH: Optional[Path] = None
_ENV_VARS: Dict[str, str] = {}
_ENV_INITIALIZED = False


def _ensure_env_initialized():
    """确保环境变量已初始化（延迟加载）"""
    global _ENV_FILE_PATH, _ENV_VARS, _ENV_INITIALIZED
    if not _ENV_INITIALIZED:
        _ENV_FILE_PATH = _find_env_file()
        _ENV_VARS = _parse_env_file(_ENV_FILE_PATH) if _ENV_FILE_PATH else {}
        _ENV_INITIALIZED = True


def _resolve_env_value(key: str, default: str) -> str:
    # 延迟初始化环境变量
    _ensure_env_initialized()

    env_value = os.environ.get(key)
    if env_value:
        return env_value
    file_value = _ENV_VARS.get(key)
    if file_value:
        return file_value
    registry_value = _read_windows_env_var(key)
    if registry_value:
        return registry_value
    return default


def get_proxy_auth() -> str:
    """获取代理认证信息（仅保留环境变量兼容）。"""
    return os.environ.get("WJX_PROXY_AUTH", "")
_DEFAULT_CONTACT_API = "https://bot.hungrym0.top"
_DEFAULT_AUTH_TRIAL = "https://api-wjx.hungrym0.top/api/auth/trial"
_DEFAULT_AUTH_BONUS_CLAIM = "https://api-wjx.hungrym0.top/api/bonus"
_DEFAULT_IP_EXTRACT_ENDPOINT = "https://api-wjx.hungrym0.top/api/ip/extract"
_DEFAULT_AI_FREE_ENDPOINT = "https://api-wjx.hungrym0.top/api/ai/free"
_DEFAULT_STATUS_ENDPOINT = "https://api-wjx.hungrym0.top/api/status"
_DEFAULT_EMAIL_VERIFY_ENDPOINT = "https://api-wjx.hungrym0.top/api/email"

# ==================== 浏览器配置 ====================
# 浏览器选择优先级（默认优先 Edge，不存在则回落到 Chrome）
BROWSER_PREFERENCE = ["edge", "chrome"]
# 无头模式窗口尺寸 (宽x高)
HEADLESS_WINDOW_SIZE = "1920,1080"

# ==================== 用户代理配置 ====================
USER_AGENT_PRESETS = {
    "pc_web": {
        "label": "电脑网页端",
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    },
    "mobile_android": {
        "label": "安卓手机浏览器",
        "ua": "Mozilla/5.0 (Linux; Android 16; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
    },
    "wechat_android": {
        "label": "安卓微信端",
        "ua": "Mozilla/5.0 (Linux; Android 16; Pixel 8 Build/BP22.250124.009; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/121.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.43.2460(0x28002B3B) Process/appbrand0 WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64",
    },
}

# 默认随机 UA 选择范围
DEFAULT_RANDOM_UA_KEYS = ["pc_web"]
# 默认用户代理
DEFAULT_USER_AGENT = USER_AGENT_PRESETS["pc_web"]["ua"]

# 默认 HTTP 请求头
DEFAULT_HTTP_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "close",
}

# ==================== 日志配置 ====================
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_BUFFER_CAPACITY = 2000
LOG_DIR_NAME = "logs"
LOG_REFRESH_INTERVAL_MS = 100

# ==================== 资源路径配置 ====================
APP_ICON_RELATIVE_PATH = "icon.ico"

# ==================== 提交行为配置 ====================
# 提交前初始延迟（秒）
SUBMIT_INITIAL_DELAY = 0.35
# 点击提交后的稳定延迟（秒）
SUBMIT_CLICK_SETTLE_DELAY = 0.25
# 无头模式专属：提交流程前置等待（秒）
HEADLESS_SUBMIT_INITIAL_DELAY = 0.15
# 无头模式专属：点击提交后的稳定等待（秒）
HEADLESS_SUBMIT_CLICK_SETTLE_DELAY = 0.10
# 无头模式专属：翻页前后的缓冲等待（秒）
HEADLESS_PAGE_BUFFER_DELAY = 0.20
# 无头模式专属：点击下一页后的等待（秒）
HEADLESS_PAGE_CLICK_DELAY = 0.20
# 提交后等待 URL 变化的最大时间（秒）
POST_SUBMIT_URL_MAX_WAIT = 0.8
# 提交后 URL 变化检测轮询间隔（秒）
POST_SUBMIT_URL_POLL_INTERVAL = 0.05
# 判定提交成功后，关闭浏览器实例前的缓冲等待（秒）
# 目的：避免过早关闭页面导致提交请求尚未发送/尚未完成就被中断。
POST_SUBMIT_CLOSE_GRACE_SECONDS = 0.8
# 无头模式专属：提交成功后关闭浏览器前的缓冲等待（秒）
HEADLESS_POST_SUBMIT_CLOSE_GRACE_SECONDS = 0.25
# 停止操作的强制等待时间（秒）- 浏览器cleanup延迟启动时间
# 降低此值可减少窗口关闭到重新打开的间隔
STOP_FORCE_WAIT_SECONDS = 0.3

# ==================== 代理配置 ====================
PROXY_MAX_PROXIES = 80
PROXY_HEALTH_CHECK_URL = "https://www.wjx.cn"
PROXY_HEALTH_CHECK_TIMEOUT = 15
PROXY_STATUS_TIMEOUT_SECONDS = 5
PROXY_TTL_GRACE_SECONDS = 20
PROXY_MINUTE_OPTIONS = (1, 3, 5, 10, 15, 30)
PROXY_QUOTA_COST_MAP = {
    1: 1,
    3: 2,
    5: 3,
    10: 5,
    15: 8,
    30: 20,
}
# 代理源常量
PROXY_SOURCE_DEFAULT = "default"
PROXY_SOURCE_BENEFIT = "benefit"
PROXY_SOURCE_CUSTOM = "custom"
# 默认代理池类型
PROXY_POOL_ORDINARY = "ordinary"
PROXY_POOL_QUALITY = "quality"
# ==================== API 端点配置 ====================
CONTACT_API_URL = _resolve_env_value("CONTACT_API_URL", _DEFAULT_CONTACT_API)
AUTH_TRIAL_ENDPOINT = _resolve_env_value("AUTH_TRIAL_ENDPOINT", _DEFAULT_AUTH_TRIAL)
AUTH_BONUS_CLAIM_ENDPOINT = _resolve_env_value("AUTH_BONUS_CLAIM_ENDPOINT", _DEFAULT_AUTH_BONUS_CLAIM)
IP_EXTRACT_ENDPOINT = _resolve_env_value("IP_EXTRACT_ENDPOINT", _DEFAULT_IP_EXTRACT_ENDPOINT)
AI_FREE_ENDPOINT = _resolve_env_value("AI_FREE_ENDPOINT", _DEFAULT_AI_FREE_ENDPOINT)
STATUS_ENDPOINT = _resolve_env_value("STATUS_ENDPOINT", _DEFAULT_STATUS_ENDPOINT)
EMAIL_VERIFY_ENDPOINT = _resolve_env_value("EMAIL_VERIFY_ENDPOINT", _DEFAULT_EMAIL_VERIFY_ENDPOINT)


# ==================== 时长控制配置 ====================
# 时长控制持续时间抖动系数
# 时长控制最小延迟（秒）

# ==================== 问卷题型配置 ====================
QUESTION_TYPE_LABELS = {
    "radio": "单选题",
    "checkbox": "多选题",
    "textarea": "简答题",
    "input": "填空题",
    "dropdown": "下拉题",
    "slider": "滑块题",
    "order": "排序题",
    "score": "评价题",
    "single": "单选题",
    "multiple": "多选题",
    "matrix": "矩阵题",
    "scale": "量表题",
    "text": "填空题",
    "multi_text": "多项填空题",
}
LOCATION_QUESTION_LABEL = "位置题"
DEFAULT_FILL_TEXT = "无"  # 填空选项留空时的默认文本

# ==================== 维度配置 ====================
# 预设的常用维度列表（用户也可以自定义新维度）
PRESET_DIMENSIONS = [
    "满意度",
    "信任感",
    "使用意愿",
    "感知价值",
    "服务质量",
    "产品质量",
]
DIMENSION_UNGROUPED = "未分组"  # 未指定维度的题目归为此组

# ==================== 正则表达式配置 ====================
_HTML_SPACE_RE = re.compile(r"\s+")
_LNGLAT_PATTERN = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s*$")
_INVALID_FILENAME_CHARS_RE = re.compile(r'[\\/:*?"<>|]+')

# ==================== 多选题限制检测配置 ====================
_MULTI_LIMIT_ATTRIBUTE_NAMES = (
    "max",
    "maxvalue",
    "maxValue",
    "maxcount",
    "maxCount",
    "maxchoice",
    "maxChoice",
    "maxselect",
    "maxSelect",
    "selectmax",
    "selectMax",
    "maxsel",
    "maxSel",
    "maxnum",
    "maxNum",
    "maxlimit",
    "maxLimit",
    "data-max",
    "data-maxvalue",
    "data-maxcount",
    "data-maxchoice",
    "data-maxselect",
    "data-selectmax",
)

_MULTI_LIMIT_VALUE_KEYS = (
    "max",
    "maxvalue",
    "maxcount",
    "maxchoice",
    "maxselect",
    "selectmax",
)

_MULTI_LIMIT_VALUE_KEYSET = {name.lower() for name in _MULTI_LIMIT_VALUE_KEYS}

_MULTI_MIN_LIMIT_ATTRIBUTE_NAMES = (
    "min",
    "minvalue",
    "minValue",
    "mincount",
    "minCount",
    "minchoice",
    "minChoice",
    "minselect",
    "minSelect",
    "selectmin",
    "selectMin",
    "minsel",
    "minSel",
    "minnum",
    "minNum",
    "minlimit",
    "minLimit",
    "data-min",
    "data-minvalue",
    "data-mincount",
    "data-minchoice",
    "data-minselect",
    "data-selectmin",
)

_MULTI_MIN_LIMIT_VALUE_KEYS = (
    "min",
    "minvalue",
    "mincount",
    "minchoice",
    "minselect",
    "selectmin",
    "minlimit",
)

_MULTI_MIN_LIMIT_VALUE_KEYSET = {name.lower() for name in _MULTI_MIN_LIMIT_VALUE_KEYS}

_SELECTION_KEYWORDS_CN = ("选", "選", "选择", "多选", "复选")
_SELECTION_KEYWORDS_EN = ("option", "options", "choice", "choices", "select", "choose")

_CHINESE_MULTI_LIMIT_PATTERNS = (
    re.compile(r"[最多至]多\s*[选選]\s*(\d+)\s*[个項项]?"),
    re.compile(r"[选選]\s*(\d+)\s*[个項项]"),
)

_CHINESE_MULTI_RANGE_PATTERNS = (
    re.compile(r"(?:请[选選择擇]?[^0-9]{0,4})?(\d+)\s*(?:-|－|—|–|~|～|至|到)\s*(\d+)\s*[个項项条]"),
    re.compile(r"至少\s*(\d+)\s*[个項项条]?(?:[^0-9]{0,6})(?:最多|至多|不超过|不超過)\s*(\d+)\s*[个項项条]?"),
    re.compile(r"(?:请[选選择擇]?[^0-9]{0,6})?(\d+)\s*(?:-|－|—|–|~|～|至|到)\s*(\d+)\b"),
)

_CHINESE_MULTI_MIN_PATTERNS = (
    re.compile(r"(?:至少|最少|不少于)\s*(\d+)\s*[个項项条]"),
)

_ENGLISH_MULTI_LIMIT_PATTERNS = (
    re.compile(r"select\s+(?:up\s+to\s+)?(\d+)", re.IGNORECASE),
    re.compile(r"choose\s+(?:up\s+to\s+)?(\d+)", re.IGNORECASE),
    re.compile(r"pick\s+(?:up\s+to\s+)?(\d+)", re.IGNORECASE),
)

_ENGLISH_MULTI_RANGE_PATTERNS = (
    re.compile(r"(?:select|choose|pick)\s*(\d+)\s*(?:-|–|—|~|～|to)\s*(\d+)", re.IGNORECASE),
    re.compile(r"(?:select|choose)\s+between\s+(\d+)\s+and\s+(\d+)", re.IGNORECASE),
)

_ENGLISH_MULTI_MIN_PATTERNS = (
    re.compile(r"(?:at\s+least|min(?:imum)?\s*)\s*(\d+)", re.IGNORECASE),
)

# ==================== 下载源配置 ====================
DOWNLOAD_SOURCES = {
    "official": {
        "label": "官方服务器",
        "api_prefix": "",  # API 不修改
        "download_prefix": "",  # 不使用前缀拼接
        "direct_download_url": "https://dl.hungrym0.top/SurveyController_latest_setup.exe",
    },
    "github": {
        "label": "GitHub 原始地址",
        "api_prefix": "",  # 不修改 API 地址
        "download_prefix": "",  # 不修改下载地址
    },
    "ghfast": {
        "label": "ghfast.top 镜像 (推荐)",
        "api_prefix": "",
        "download_prefix": "https://ghfast.top/",
    },
    "ghproxy": {
        "label": "ghproxy.net 镜像",
        "api_prefix": "",  # API 不走镜像
        "download_prefix": "https://ghproxy.net/",
    },
}
DEFAULT_DOWNLOAD_SOURCE = "official"

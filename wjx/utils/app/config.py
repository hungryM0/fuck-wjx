# -*- coding: utf-8 -*-
"""
应用配置常量

集中管理应用的各种配置参数，方便统一修改和维护
"""

import base64
import os
import re
import sys
from pathlib import Path
from typing import Dict, Optional

_ENV_FILE_NAME = ".env"


def _find_env_file() -> Optional[Path]:
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass))
        try:
            candidates.append(Path(sys.executable).resolve().parent)
        except Exception:
            pass
    try:
        candidates.append(Path(__file__).resolve().parent)
    except Exception:
        pass
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
    except Exception:
        pass
    return env_map


_ENV_FILE_PATH = _find_env_file()
_ENV_VARS = _parse_env_file(_ENV_FILE_PATH) if _ENV_FILE_PATH else {}


def _resolve_env_value(key: str, default: str) -> str:
    return os.environ.get(key) or _ENV_VARS.get(key) or default

def _r(s: str) -> str:
    try:
        return base64.b64decode(s).decode("utf-8")
    except Exception:
        return ""

_CFG = {
    "a": "aHR0cHM6Ly9zZXJ2aWNlLmlwemFuLmNvbS9jb3JlLWV4dHJhY3Q/bnVtPTEmbm89MjAyNjAxMTI1NzIzNzY0OTA4NzQmbWludXRlPTEmZm9ybWF0PWpzb24mcmVwZWF0PTEmcHJvdG9jb2w9MSZwb29sPW9yZGluYXJ5Jm1vZGU9YXV0aCZzZWNyZXQ9cGY3MDZ2azc3a2tubG8=",
    "b": "aHR0cHM6Ly9ib3QuaHVuZ3J5bTAudG9w",
    "c": "aHR0cHM6Ly9hcGktd2p4Lmh1bmdyeW0wLnRvcC9hcGkvY2FyZC92ZXJpZnk=",
    "d": "aHR0cHM6Ly93anguaHVuZ3J5bTAudG9wL3N0YXR1cw==",
    "e": "aHR0cHM6Ly9yYXcuZ2l0aHVidXNlcmNvbnRlbnQuY29tL0NoYXJsZXNQaWthY2h1L2ZyZWVwcm94eS9tYXN0ZXIvcHJveGllcy5qc29u",
}

# ==================== UI 界面配置 ====================
# 左右面板最小宽度
PANED_MIN_LEFT_WIDTH = 360
PANED_MIN_RIGHT_WIDTH = 280

# ==================== 浏览器配置 ====================
# 浏览器选择优先级（默认优先 Edge，不存在则回落到 Chrome/内置 Chromium）
BROWSER_PREFERENCE = ["edge", "chrome", "chromium"]
# 无头模式窗口尺寸 (宽x高)
HEADLESS_WINDOW_SIZE = "1920,1080"

# ==================== 用户代理配置 ====================
USER_AGENT_PRESETS = {
    "pc_web": {
        "label": "电脑网页端",
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    },
    "wechat_android": {
        "label": "安卓微信端",
        "ua": "Mozilla/5.0 (Linux; Android 13; Pixel 6 Build/TQ3A.230901.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/108.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.43.2460(0x28002B3B) Process/appbrand0 WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64",
    },
    "wechat_ios": {
        "label": "苹果微信端",
        "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.43(0x18002b2f) NetType/WIFI Language/zh_CN",
    },
    "wechat_windows": {
        "label": "Windows微信WebView",
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36 MicroMessenger/3.9.8.25 NetType/WIFI WindowsWechat/WMPF WindowsWechat(0x63090819) XWEB/9129 Flue",
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
LOG_REFRESH_INTERVAL_MS = 1000

# ==================== 资源路径配置 ====================
APP_ICON_RELATIVE_PATH = "icon.ico"
QQ_GROUP_QR_RELATIVE_PATH = os.path.join("assets", "QQ_group.jpg")

# ==================== 提交行为配置 ====================
# 提交前初始延迟（秒）
SUBMIT_INITIAL_DELAY = 0.35
# 点击提交后的稳定延迟（秒）
SUBMIT_CLICK_SETTLE_DELAY = 0.25
# 提交后等待 URL 变化的最大时间（秒）
POST_SUBMIT_URL_MAX_WAIT = 0.5
# 提交后 URL 变化检测轮询间隔（秒）
POST_SUBMIT_URL_POLL_INTERVAL = 0.1
# 提交后若按选项跳转到“下一份问卷”，最多自动跟随的问卷数量
# 说明：部分问卷会在最后一题按选项分流到新的问卷链接；此处限制用于防止异常循环跳转。
POST_SUBMIT_FOLLOWUP_MAX_HOPS = 5
# 判定提交成功后，关闭浏览器实例前的缓冲等待（秒）
# 目的：避免过早关闭页面导致提交请求尚未发送/尚未完成就被中断。
POST_SUBMIT_CLOSE_GRACE_SECONDS = 1.2
# 停止操作的强制等待时间（秒）
STOP_FORCE_WAIT_SECONDS = 1.5

# ==================== 代理配置 ====================
PROXY_LIST_FILENAME = "ips.txt"
PROXY_MAX_PROXIES = 80
PROXY_HEALTH_CHECK_URL = "https://www.wjx.cn"
PROXY_HEALTH_CHECK_TIMEOUT = 15
PROXY_HEALTH_CHECK_MAX_DURATION = 45
_RANDOM_IP_API_ENV_KEY = "RANDOM_IP_API_URL"
PROXY_REMOTE_URL = _resolve_env_value(_RANDOM_IP_API_ENV_KEY, _r(_CFG["a"]))

# ==================== API 端点配置 ====================
CONTACT_API_URL = _resolve_env_value("CONTACT_API_URL", _r(_CFG["b"]))
CARD_VALIDATION_ENDPOINT = _resolve_env_value("CARD_VALIDATION_ENDPOINT", _r(_CFG["c"]))
STATUS_ENDPOINT = _resolve_env_value("STATUS_ENDPOINT", _r(_CFG["d"]))
PIKACHU_PROXY_API = _resolve_env_value("PIKACHU_PROXY_API", _r(_CFG["e"]))
CARD_TOKEN_SECRET = _resolve_env_value("CARD_TOKEN_SECRET", "")


# ==================== 时长控制配置 ====================
# 时长控制持续时间抖动系数
DURATION_CONTROL_JITTER = 0.2
# 时长控制最小延迟（秒）
DURATION_CONTROL_MIN_DELAY_SECONDS = 0.15

# ==================== 问卷题型配置 ====================
QUESTION_TYPE_LABELS = {
    "radio": "单选题",
    "checkbox": "多选题",
    "textarea": "简答题",
    "input": "填空题",
    "dropdown": "下拉题",
    "slider": "滑块题",
    "order": "排序题",
    "score": "评分题",
    "single": "单选题",
    "multiple": "多选题",
    "matrix": "矩阵题",
    "scale": "量表题",
    "text": "填空题",
    "multi_text": "多项填空题",
}
LOCATION_QUESTION_LABEL = "位置题"
DEFAULT_FILL_TEXT = "无"  # 填空选项留空时的默认文本

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

# ==================== GitHub 镜像源配置 ====================
GITHUB_MIRROR_SOURCES = {
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
DEFAULT_GITHUB_MIRROR = "github"

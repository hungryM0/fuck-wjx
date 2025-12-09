# -*- coding: utf-8 -*-
"""
应用配置常量

集中管理应用的各种配置参数，方便统一修改和维护
"""

import os
import re

# ==================== UI 界面配置 ====================
# 左右面板最小宽度
PANED_MIN_LEFT_WIDTH = 360
PANED_MIN_RIGHT_WIDTH = 280

# ==================== 浏览器配置 ====================
# 浏览器选择优先级
BROWSER_PREFERENCE = ["edge", "chrome"]
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
    "wechat_ipad": {
        "label": "iPad微信端",
        "ua": "Mozilla/5.0 (iPad; CPU OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.43(0x18002b2f) NetType/WIFI Language/zh_CN",
    },
    "ipad_web": {
        "label": "iPad网页端",
        "ua": "Mozilla/5.0 (iPad; CPU OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
    },
    "wechat_android_tablet": {
        "label": "安卓平板微信端",
        "ua": "Mozilla/5.0 (Linux; Android 13; SM-X906C Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/108.0.0.0 Safari/537.36 MicroMessenger/8.0.43.2460(0x28002B3B) Process/appbrand0 WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64",
    },
    "android_tablet_web": {
        "label": "安卓平板网页端",
        "ua": "Mozilla/5.0 (Linux; Android 13; SM-X906C) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    },
    "wechat_mac": {
        "label": "Mac微信WebView",
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36 MicroMessenger/8.0.43 NetType/WIFI WindowsWechat Language/zh_CN",
    },
    "wechat_windows": {
        "label": "Windows微信WebView",
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36 MicroMessenger/3.9.8.25 NetType/WIFI WindowsWechat/WMPF WindowsWechat(0x63090819) XWEB/9129 Flue",
    },
    "mac_web": {
        "label": "Mac网页端",
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    },
}

# 默认随机 UA 选择范围
DEFAULT_RANDOM_UA_KEYS = list(USER_AGENT_PRESETS.keys())
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

# ==================== 资源路径配置 ====================
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
# 停止操作的强制等待时间（秒）
STOP_FORCE_WAIT_SECONDS = 1.5

# ==================== 代理配置 ====================
PROXY_LIST_FILENAME = "ips.txt"
PROXY_MAX_PROXIES = 80
PROXY_HEALTH_CHECK_URL = "https://bilibili.com/"
PROXY_HEALTH_CHECK_TIMEOUT = 5
PROXY_HEALTH_CHECK_MAX_DURATION = 45
PROXY_REMOTE_URL = "https://service.ipzan.com/core-extract?num=1&no=20251209063007602516&minute=1&format=json&protocol=1&pool=quality&mode=auth&secret=reuoen35jvep3go"

# ==================== 地理位置配置 ====================
_GAODE_GEOCODE_ENDPOINT = "https://restapi.amap.com/v3/geocode/geo"
_GAODE_GEOCODE_KEY = "775438cfaa326e71ed2f51d0f6429f79"
_LOCATION_GEOCODE_TIMEOUT = 8

# ==================== 完整模拟配置 ====================
# 完整模拟持续时间抖动系数
FULL_SIM_DURATION_JITTER = 0.2
# 完整模拟最小延迟（秒）
FULL_SIM_MIN_DELAY_SECONDS = 0.15

# ==================== 问卷题型配置 ====================
QUESTION_TYPE_LABELS = {
    "radio": "单选题",
    "checkbox": "多选题",
    "textarea": "简答题",
    "input": "填空题",
    "dropdown": "下拉题",
    "slider": "量表题",
    "order": "排序题",
    "score": "评分题",
    "single": "单选题",
    "multiple": "多选题",
    "matrix": "矩阵题",
    "scale": "量表题",
    "text": "填空题",
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

_SELECTION_KEYWORDS_CN = ("选", "選", "选择", "多选", "复选")
_SELECTION_KEYWORDS_EN = ("option", "options", "choice", "choices", "select", "choose")

_CHINESE_MULTI_LIMIT_PATTERNS = (
    re.compile(r"[最多至]多\s*[选選]\s*(\d+)\s*[个項项]?"),
    re.compile(r"[选選]\s*(\d+)\s*[个項项]"),
)

_ENGLISH_MULTI_LIMIT_PATTERNS = (
    re.compile(r"select\s+(?:up\s+to\s+)?(\d+)", re.IGNORECASE),
    re.compile(r"choose\s+(?:up\s+to\s+)?(\d+)", re.IGNORECASE),
    re.compile(r"pick\s+(?:up\s+to\s+)?(\d+)", re.IGNORECASE),
)

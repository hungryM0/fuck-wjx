import logging
import math
import random
import re
import threading
import time
import traceback
import json
import os
import subprocess
import sys
import tempfile
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from threading import Thread
from typing import List, Optional, Union, Dict, Any, Tuple, Callable, Set, Deque
from urllib.parse import urlparse
import webbrowser

import numpy
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
try:
    from selenium.webdriver.edge.options import Options as EdgeOptions
except ImportError:
    EdgeOptions = None
from PIL import Image, ImageTk
from pyzbar.pyzbar import decode as pyzbar_decode

try:
    import requests
except ImportError:
    requests = None

try:
    from packaging import version
except ImportError:
    version = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

# 版本号
__VERSION__ = "0.5.1"

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_BUFFER_CAPACITY = 2000
LOG_DIR_NAME = "logs"
QQ_GROUP_QR_RELATIVE_PATH = os.path.join("assets", "QQ_group.jpg")
PANED_MIN_LEFT_WIDTH = 360
PANED_MIN_RIGHT_WIDTH = 280
DEFAULT_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "close",
}
_HTML_SPACE_RE = re.compile(r"\s+")
BROWSER_PREFERENCE = ("edge", "chrome")
HEADLESS_WINDOW_SIZE = "1920,1080"
SUBMIT_INITIAL_DELAY = 0.35
SUBMIT_CLICK_SETTLE_DELAY = 0.25
POST_SUBMIT_URL_MAX_WAIT = 0.5
POST_SUBMIT_URL_POLL_INTERVAL = 0.1

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
    "maxnum",
    "maxlimit",
)
_MULTI_LIMIT_VALUE_KEYSET = {name.lower() for name in _MULTI_LIMIT_VALUE_KEYS}
_SELECTION_KEYWORDS_CN = ("选", "選", "选择", "多选", "复选")
_SELECTION_KEYWORDS_EN = ("option", "options", "choice", "choices", "select", "choose")
_CHINESE_MULTI_LIMIT_PATTERNS = (
    re.compile(r"最多(?:只能|可|可以)?(?:选|选择)?[^\d]{0,3}(\d+)", re.IGNORECASE),
    re.compile(r"(?:至多|不超过|不超過|限选)[^\d]{0,3}(\d+)", re.IGNORECASE),
    re.compile(r"(?:选|选择)[^\d]{0,3}(\d+)[^\d]{0,3}(?:项以内|项以下|项之内)?", re.IGNORECASE),
)
_ENGLISH_MULTI_LIMIT_PATTERNS = (
    re.compile(r"(?:select|choose)\s+(?:up to|no more than|at most|a maximum of)\s*(\d+)", re.IGNORECASE),
    re.compile(r"(?:up to|no more than|at most|maximum of)\s*(\d+)\s*(?:options?|choices?|items)", re.IGNORECASE),
    re.compile(r"(?:maximum|max)\s*(?:of\s*)?(\d+)\s*(?:options?|choices?)", re.IGNORECASE),
)
_DETECTED_MULTI_LIMITS: Dict[Tuple[str, int], Optional[int]] = {}
_REPORTED_MULTI_LIMITS: Set[Tuple[str, int]] = set()


class AliyunCaptchaBypassError(RuntimeError):
    """在阿里云智能验证无法自动通过时抛出。"""


class LoadingSplash:
    def __init__(self, master: Optional[tk.Tk], title: str = "正在加载", message: str = "程序正在启动，请稍候...", width: int = 360, height: int = 140):
        self.master = master or tk.Tk()
        self.width = width
        self.height = height
        self.window = tk.Toplevel(self.master)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg="#f8fafb")
        self.message_var = tk.StringVar(value=message)
        self.progress_value = 0

        self.window.title(title)
        frame = ttk.Frame(self.window, padding=15, relief="solid", borderwidth=1)
        frame.pack(expand=True, fill=tk.BOTH)

        ttk.Label(frame, text=title, font=("Segoe UI", 11, "bold")).pack(anchor="center")
        ttk.Label(frame, textvariable=self.message_var, wraplength=width - 30, justify="center").pack(pady=(8, 12))
        
        # 创建进度条容器
        progress_frame = ttk.Frame(frame)
        progress_frame.pack(fill=tk.X)
        
        self.progress = ttk.Progressbar(progress_frame, mode="determinate", length=width - 60, maximum=100)
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.progress_label = ttk.Label(progress_frame, text="0%", width=4, anchor="center")
        self.progress_label.pack(side=tk.LEFT, padx=(5, 0))

    def show(self):
        self._center()
        self.window.deiconify()
        self.window.update()

    def update_progress(self, percent: int, message: Optional[str] = None):
        """更新进度条和消息"""
        self.progress_value = min(100, max(0, percent))
        self.progress['value'] = self.progress_value
        self.progress_label.config(text=f"{self.progress_value}%")
        if message is not None:
            self.message_var.set(message)
        self.window.update_idletasks()

    def update_message(self, message: str):
        self.message_var.set(message)
        self.window.update_idletasks()

    def close(self):
        if self.window.winfo_exists():
            self.window.destroy()

    def _center(self):
        self.window.update_idletasks()
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        x = (screen_width - self.width) // 2
        y = (screen_height - self.height) // 2
        self.window.geometry(f"{self.width}x{self.height}+{x}+{y}")
PANED_MIN_LEFT_WIDTH = 360
PANED_MIN_RIGHT_WIDTH = 280

ORIGINAL_STDOUT = sys.stdout
ORIGINAL_STDERR = sys.stderr
ORIGINAL_EXCEPTHOOK = sys.excepthook


class StreamToLogger:
    def __init__(self, logger: logging.Logger, level: int, stream=None):
        self.logger = logger
        self.level = level
        self.stream = stream
        self._buffer = ""

    def write(self, message: str):
        if message is None:
            return
        text = str(message)
        self._buffer += text.replace("\r", "")
        if "\n" in self._buffer:
            parts = self._buffer.split("\n")
            self._buffer = parts.pop()
            for line in parts:
                self.logger.log(self.level, line)
        if self.stream:
            try:
                self.stream.write(message)
            except Exception:
                pass

    def flush(self):
        if self._buffer:
            self.logger.log(self.level, self._buffer)
            self._buffer = ""
        if self.stream:
            try:
                self.stream.flush()
            except Exception:
                pass


def _get_runtime_directory() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _find_chrome_binary() -> Optional[str]:
    """查找 Chrome 或 Chromium 的可执行文件路径"""
    # 常见的 Chrome/Chromium 安装路径
    possible_paths = [
        # Windows 常见路径
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        # Chromium
        r"C:\Program Files\Chromium\Application\chrome.exe",
        r"C:\Program Files (x86)\Chromium\Application\chrome.exe",
        # 便携版可能在程序同目录
        os.path.join(_get_runtime_directory(), "chrome.exe"),
        os.path.join(_get_runtime_directory(), "chromium", "chrome.exe"),
        os.path.join(_get_runtime_directory(), "chrome", "chrome.exe"),
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            logging.info(f"找到 Chrome 浏览器: {path}")
            return path
    
    # 如果都找不到，返回 None，让 Selenium Manager 自动处理
    logging.debug("未找到本地 Chrome 浏览器，将使用 Selenium Manager 自动检测")
    return None

def _find_edge_binary() -> Optional[str]:
    """尝试定位 Microsoft Edge 可执行文件"""
    possible_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expanduser(r"~\AppData\Local\Microsoft\Edge\Application\msedge.exe"),
        os.path.join(_get_runtime_directory(), "msedge.exe"),
        os.path.join(_get_runtime_directory(), "edge", "msedge.exe"),
    ]
    for path in possible_paths:
        if os.path.exists(path):
            logging.info(f"找到了 Edge 浏览器: {path}")
            return path
    logging.debug("未找到 Edge 浏览器，可交由 Selenium Manager 自动处理")
    return None





def handle_aliyun_captcha(
    driver: WebDriver, timeout: int = 3, stop_signal: Optional[threading.Event] = None
) -> bool:
    """检测并尝试自动通过阿里云智能验证弹窗。"""
    popup_locator = (By.ID, "aliyunCaptcha-window-popup")
    mask_locator = (By.ID, "aliyunCaptcha-mask")
    clickable_locators = [
        (By.ID, "aliyunCaptcha-checkbox-body"),
        (By.ID, "aliyunCaptcha-checkbox-left"),
        (By.ID, "aliyunCaptcha-checkbox-text"),
        (By.CSS_SELECTOR, "#aliyunCaptcha-checkbox-text-box"),
    ]
    wait = WebDriverWait(driver, timeout, poll_frequency=0.2)
    short_wait = WebDriverWait(driver, 1.5, poll_frequency=0.2)

    def _popup_visible() -> bool:
        try:
            popup = driver.find_element(*popup_locator)
            return popup.is_displayed()
        except NoSuchElementException:
            return False
        except Exception:
            return False

    def _mask_visible() -> bool:
        try:
            mask = driver.find_element(*mask_locator)
            return mask.is_displayed()
        except NoSuchElementException:
            return False
        except Exception:
            return False

    def _wait_for_popup() -> bool:
        end_time = time.time() + timeout
        while time.time() < end_time:
            if stop_signal and stop_signal.is_set():
                return False
            if _popup_visible():
                return True
            time.sleep(0.15)
        return _popup_visible()

    if not _wait_for_popup():
        return False
    if stop_signal and stop_signal.is_set():
        return False

    logging.info("检测到阿里云智能验证弹窗，尝试自动点击“开始智能验证”。")

    def _click_candidate(element) -> bool:
        clicked = False
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        except Exception:
            pass
        try:
            ActionChains(driver).move_to_element(element).pause(0.05).click(element).perform()
            clicked = True
        except Exception:
            pass
        if not clicked:
            try:
                element.click()
                clicked = True
            except Exception:
                pass
        if not clicked:
            try:
                driver.execute_script("arguments[0].click();", element)
                clicked = True
            except Exception:
                pass
        return clicked

    max_attempts = 4
    for attempt in range(max_attempts):
        if stop_signal and stop_signal.is_set():
            return False
        target_element = None
        for locator in clickable_locators:
            try:
                target_element = wait.until(EC.visibility_of_element_located(locator))
                if target_element and target_element.is_enabled():
                    break
            except TimeoutException:
                continue
        if not target_element:
            if not _popup_visible():
                logging.info("阿里云智能验证弹窗已关闭，继续执行。")
                return True
            logging.warning("未能定位到可点击的阿里云验证控件。")
            raise AliyunCaptchaBypassError("未能定位可点击的阿里云智能验证控件。")

        if _click_candidate(target_element):
            try:
                short_wait.until(lambda _: not _popup_visible() or not _mask_visible())
            except TimeoutException:
                pass
            if not _popup_visible():
                logging.info("阿里云智能验证弹窗已关闭，继续执行。")
                return True
        time.sleep(0.3)

    if not _popup_visible():
        logging.info("阿里云智能验证弹窗已关闭，继续执行。")
        return True
    logging.warning("多次尝试点击阿里云智能验证失败，可能需要人工干预。")
    raise AliyunCaptchaBypassError("自动处理阿里云智能验证失败。")

def _apply_common_browser_options(options, headless: bool = False) -> None:
    try:
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
    except Exception:
        pass
    if hasattr(options, "add_argument"):
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        if headless:
            options.add_argument("--headless=new")
            options.add_argument(f"--window-size={HEADLESS_WINDOW_SIZE}")
            options.add_argument("--disable-software-rasterizer")

def _disable_driver_http_retry(driver: WebDriver) -> None:
    """
    Selenium 4.10+ 默认会对 WebDriver 的 HTTP 请求做指数退避重试。
    如果驱动意外挂掉，重试将导致“幽灵”进程堆积，所以下面尝试清零重试次数。
    """
    try:
        executor = getattr(driver, 'command_executor', None)
        if executor is None:
            return
        http_client = getattr(executor, '_conn', None)
        if http_client is None:
            return
        session = getattr(http_client, 'session', None)
        if session is None:
            return
        adapters = getattr(session, 'adapters', None)
        if not adapters:
            return
        for adapter in adapters.values():
            retries = getattr(adapter, 'max_retries', None)
            if retries is None:
                continue
            try:
                retries.total = 0
                retries.connect = 0
                retries.read = 0
                retries.redirect = 0
                retries.status = 0
                retries.respect_retry_after_header = False
            except Exception:
                try:
                    adapter.max_retries = 0  # type: ignore[assignment]
                except Exception:
                    pass
    except Exception as exc:
        logging.debug('Failed to disable driver HTTP retry: %s', exc)

def setup_browser_options(browser: str, headless: bool = False):
    browser_key = (browser or "").lower()
    if browser_key not in ("chrome", "edge"):
        raise ValueError(f"不支持的浏览器类型: {browser}")
    if browser_key == "edge":
        if EdgeOptions is None:
            raise RuntimeError("当前环境未提供 EdgeOptions，请确认 selenium 版本 >= 4.6")
        options = EdgeOptions()
        binary = _find_edge_binary()
    else:
        options = webdriver.ChromeOptions()
        binary = _find_chrome_binary()
    if binary:
        try:
            options.binary_location = binary
        except Exception:
            pass
    _apply_common_browser_options(options, headless=headless)
    return options


def create_selenium_driver(headless: bool = False, prefer_browsers: Optional[List[str]] = None) -> Tuple[WebDriver, str]:
    candidates = prefer_browsers or list(BROWSER_PREFERENCE)
    if not candidates:
        candidates = list(BROWSER_PREFERENCE)
    last_exc: Optional[Exception] = None
    for browser in candidates:
        try:
            options = setup_browser_options(browser, headless=headless)
        except Exception as exc:
            logging.debug(f"构建 {browser} 选项失败: {exc}")
            last_exc = exc
            continue
        try:
            if browser == "edge":
                driver = webdriver.Edge(options=options)  # type: ignore[arg-type]
            else:
                driver = webdriver.Chrome(options=options)  # type: ignore[arg-type]
            _disable_driver_http_retry(driver)
            logging.info(f"使用 {browser.capitalize()} WebDriver")
            return driver, browser
        except Exception as exc:
            logging.warning(f"启动 {browser.capitalize()} WebDriver 失败: {exc}")
            last_exc = exc
    raise RuntimeError(f"无法启动任何浏览器驱动: {last_exc}")





@dataclass
class LogBufferEntry:
    text: str
    category: str


class LogBufferHandler(logging.Handler):
    def __init__(self, capacity: int = LOG_BUFFER_CAPACITY):
        super().__init__()
        self.capacity = capacity
        self.records: List[LogBufferEntry] = []
        self.setFormatter(logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))

    def emit(self, record: logging.LogRecord):
        try:
            original_level = record.levelname
            message = self.format(record)
            category = self._determine_category(record, message)
            display_text = self._apply_category_label(message, original_level, category)
            self.records.append(LogBufferEntry(text=display_text, category=category))
            if self.capacity and len(self.records) > self.capacity:
                self.records.pop(0)
        except Exception:
            self.handleError(record)

    def get_records(self) -> List[LogBufferEntry]:
        return list(self.records)

    @staticmethod
    def _determine_category(record: logging.LogRecord, message: str) -> str:
        custom_category = getattr(record, "log_category", None)
        if isinstance(custom_category, str):
            normalized = custom_category.strip().upper()
            if normalized in {"INFO", "OK", "WARNING", "ERROR"}:
                return normalized

        level = record.levelname.upper()
        if level in {"ERROR", "CRITICAL"}:
            return "ERROR"
        if level == "WARNING":
            return "WARNING"
        if level in {"OK", "SUCCESS"}:
            return "OK"

        normalized_message = message.upper()
        ok_markers = ("[OK]", "[SUCCESS]", "✅", "✔")
        ok_keywords = (
            "成功",
            "已完成",
            "解析完成",
            "填写完成",
            "填写成功",
            "提交成功",
            "保存成功",
            "恢复成功",
            "加载上次配置",
            "已加载上次配置",
            "加载完成",
        )
        negative_keywords = ("未成功", "未完成", "失败", "错误", "异常")
        if any(marker in message for marker in ok_markers):
            return "OK"
        if normalized_message.startswith("OK"):
            return "OK"
        if any(keyword in message for keyword in ok_keywords):
            if not any(neg in message for neg in negative_keywords):
                return "OK"

        return "INFO"

    @staticmethod
    def _apply_category_label(message: str, original_level: str, category: str) -> str:
        if not message or not original_level:
            return message
        original_label = f"[{original_level.upper()}]"
        if category.upper() == original_level.upper():
            return message
        replacement_label = f"[{category.upper()}]"
        if original_label in message:
            return message.replace(original_label, replacement_label, 1)
        return message


LOG_BUFFER_HANDLER = LogBufferHandler()
# 立即把缓冲处理器注册到根日志记录器，保证启动前的日志也能被收集
_root_logger = logging.getLogger()
if not any(isinstance(h, LogBufferHandler) for h in _root_logger.handlers):
    _root_logger.addHandler(LOG_BUFFER_HANDLER)
_root_logger.setLevel(logging.INFO)


url = ""

single_prob: List[Union[List[float], int]] = []
droplist_prob: List[Union[List[float], int]] = []
multiple_prob: List[List[float]] = []
matrix_prob: List[Union[List[float], int]] = []
scale_prob: List[Union[List[float], int]] = []
texts: List[List[str]] = []
texts_prob: List[List[float]] = []
single_option_fill_texts: List[Optional[List[Optional[str]]]] = []
droplist_option_fill_texts: List[Optional[List[Optional[str]]]] = []
multiple_option_fill_texts: List[Optional[List[Optional[str]]]] = []

target_num = 1
fail_threshold = 1
num_threads = 1
cur_num = 0
cur_fail = 0
submit_interval_range_seconds: Tuple[int, int] = (0, 0)
answer_duration_range_seconds: Tuple[int, int] = (0, 0)
lock = threading.Lock()
stop_event = threading.Event()
full_simulation_enabled = False
full_simulation_estimated_seconds = 0
full_simulation_total_duration_seconds = 0
full_simulation_schedule: Deque[float] = deque()
full_simulation_end_timestamp = 0.0
FULL_SIM_DURATION_JITTER = 0.2
FULL_SIM_MIN_DELAY_SECONDS = 0.15

# GitHub 更新配置
GITHUB_OWNER = "hungryM0"
GITHUB_REPO = "fuck-wjx"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
ISSUE_FEEDBACK_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/issues/new"

# 可选：设置 GitHub Token 以避免 API 速率限制
# 优先从环境变量读取，如果没有则尝试从配置文件读取
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
if not GITHUB_TOKEN:
    # 尝试从同目录下的 .github_token 文件读取
    token_file = os.path.join(_get_runtime_directory(), ".github_token")
    if os.path.exists(token_file):
        try:
            with open(token_file, 'r', encoding='utf-8') as f:
                GITHUB_TOKEN = f.read().strip()
        except:
            pass


class UpdateManager:
    """GitHub 自动更新管理器"""
    
    @staticmethod
    def check_updates() -> Optional[Dict[str, Any]]:
        """
        检查 GitHub 上是否有新版本
        
        返回:
            如果有新版本，返回更新信息字典，包括:
            - has_update: 是否有更新
            - version: 新版本号
            - download_url: 下载地址
            - release_notes: 发布说明
            - file_name: 文件名
            
            如果无新版本或检查失败，返回 None
        """
        if not requests or not version:
            logging.warning("更新功能依赖 requests 和 packaging 模块")
            return None
        
        try:
            response = requests.get(GITHUB_API_URL, timeout=5)
            response.raise_for_status()
            latest_release = response.json()
            
            latest_version = latest_release['tag_name'].lstrip('v')
            current_version = __VERSION__
            
            # 比较版本号
            try:
                if version.parse(latest_version) <= version.parse(current_version):
                    return None
            except:
                logging.warning(f"版本比较失败: {latest_version} vs {current_version}")
                return None
            
            # 查找 .exe 文件资源（Release中的最新exe文件）
            download_url = None
            file_name = None
            for asset in latest_release.get('assets', []):
                if asset['name'].endswith('.exe'):
                    download_url = asset['browser_download_url']
                    file_name = asset['name']
                    break
            
            if not download_url:
                logging.warning("Release 中没有找到 .exe 文件")
                return None
            
            return {
                'has_update': True,
                'version': latest_version,
                'download_url': download_url,
                'release_notes': latest_release.get('body', ''),
                'file_name': file_name,
                'current_version': current_version
            }
            
        except requests.exceptions.Timeout:
            logging.warning("检查更新超时")
            return None
        except requests.exceptions.RequestException as e:
            logging.warning(f"检查更新失败: {e}")
            return None
        except Exception as e:
            logging.error(f"检查更新时发生错误: {e}")
            return None
    
    @staticmethod
    def download_update(download_url: str, file_name: str, progress_callback=None) -> Optional[str]:
        """
        下载更新文件
        
        参数:
            download_url: 下载链接
            file_name: 文件名（保留原始Release文件名）
            progress_callback: 进度回调函数 (downloaded, total)
            
        返回:
            下载的文件路径，失败返回 None
        """
        if not requests:
            logging.error("下载更新需要 requests 模块")
            return None
        
        try:
            logging.info(f"正在下载更新文件: {download_url}")
            response = requests.get(download_url, timeout=30, stream=True)
            response.raise_for_status()
            
            # 获取文件大小
            total_size = int(response.headers.get('content-length', 0))
            
            # 确定下载目录：统一使用运行时目录，保证与当前可执行文件同级
            current_dir = _get_runtime_directory()
            
            target_file = os.path.join(current_dir, file_name)
            temp_file = target_file + '.tmp'
            downloaded_size = 0
            
            logging.info(f"下载目标目录: {current_dir}")
            
            with open(temp_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded_size, total_size)
                        if total_size > 0:
                            progress = (downloaded_size / total_size) * 100
                            logging.debug(f"下载进度: {progress:.1f}%")
            
            # 移动临时文件到目标位置
            if os.path.exists(target_file):
                os.remove(target_file)
            os.rename(temp_file, target_file)

            logging.info(f"文件已成功下载到: {target_file}")

            UpdateManager.cleanup_old_executables(target_file)

            return target_file
            
        except Exception as e:
            logging.error(f"下载文件失败: {e}")
            # 清理临时文件
            try:
                current_dir = _get_runtime_directory()
                target_file = os.path.join(current_dir, file_name)
                temp_file = target_file + '.tmp'
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except:
                pass
            return None
    
    @staticmethod
    def restart_application():
        """重启应用程序"""
        try:
            python_exe = sys.executable
            script_path = os.path.abspath(__file__)
            subprocess.Popen([python_exe, script_path])
            sys.exit(0)
        except Exception as e:
            logging.error(f"重启应用失败: {e}")

    @staticmethod
    def cleanup_old_executables(exclude_path: str):
        """删除目录下旧版本的exe文件（保留exclude_path本体）"""
        if not exclude_path:
            return
        directory = os.path.dirname(os.path.abspath(exclude_path))
        if not os.path.isdir(directory):
            return

        try:
            exclude_norm = os.path.normcase(os.path.abspath(exclude_path))
            for file in os.listdir(directory):
                if not file.lower().endswith('.exe'):
                    continue
                file_path = os.path.join(directory, file)
                if os.path.normcase(os.path.abspath(file_path)) == exclude_norm:
                    continue
                lower_name = file.lower()
                if 'fuck-wjx' not in lower_name and 'wjx' not in lower_name:
                    continue
                try:
                    os.remove(file_path)
                    logging.info(f"已删除旧版本: {file_path}")
                except Exception as exc:
                    logging.warning(f"无法删除旧版本 {file_path}: {exc}")
        except Exception as exc:
            logging.warning(f"清理旧版本时出错: {exc}")

    @staticmethod
    def schedule_running_executable_deletion(exclude_path: str):
        """调度在当前进程退出后删除正在运行的 exe 文件"""
        if not getattr(sys, "frozen", False):
            return
        current_executable = os.path.abspath(sys.executable)
        if not current_executable.lower().endswith('.exe'):
            return
        exclude_norm = os.path.normcase(os.path.abspath(exclude_path)) if exclude_path else ""
        if exclude_norm and os.path.normcase(current_executable) == exclude_norm:
            return

        safe_executable = current_executable.replace('%', '%%')
        script_content = (
            "@echo off\r\n"
            f"set \"target={safe_executable}\"\r\n"
            ":wait_loop\r\n"
            "if exist \"%target%\" (\r\n"
            "    del /f /q \"%target%\" >nul 2>&1\r\n"
            "    if exist \"%target%\" (\r\n"
            "        ping 127.0.0.1 -n 3 >nul\r\n"
            "        goto wait_loop\r\n"
            "    )\r\n"
            ")\r\n"
            "del /f /q \"%~f0\" >nul 2>&1\r\n"
        )

        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".bat") as script_file:
                script_file.write(script_content)
                script_path = script_file.name
            subprocess.Popen([
                "cmd.exe",
                "/c",
                script_path,
            ], creationflags=subprocess.CREATE_NO_WINDOW)
            logging.info(f"已调度删除旧版本执行文件: {current_executable}")
        except Exception as exc:
            logging.warning(f"调度删除旧版本失败: {exc}")


def setup_logging():
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    root_logger.setLevel(logging.INFO)
    if not any(isinstance(handler, LogBufferHandler) for handler in root_logger.handlers):
        root_logger.addHandler(LOG_BUFFER_HANDLER)
    
    if not getattr(setup_logging, "_streams_hooked", False):
        stdout_logger = StreamToLogger(root_logger, logging.INFO, stream=ORIGINAL_STDOUT)
        stderr_logger = StreamToLogger(root_logger, logging.ERROR, stream=ORIGINAL_STDERR)
        sys.stdout = stdout_logger
        sys.stderr = stderr_logger

        def _handle_unhandled_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                if ORIGINAL_EXCEPTHOOK:
                    ORIGINAL_EXCEPTHOOK(exc_type, exc_value, exc_traceback)
                return
            root_logger.error("未处理的异常", exc_info=(exc_type, exc_value, exc_traceback))
            if ORIGINAL_EXCEPTHOOK:
                ORIGINAL_EXCEPTHOOK(exc_type, exc_value, exc_traceback)

        sys.excepthook = _handle_unhandled_exception
        setattr(setup_logging, "_streams_hooked", True)


def normalize_probabilities(values: List[float]) -> List[float]:
    if not values:
        raise ValueError("概率列表不能为空")
    total = sum(values)
    if total <= 0:
        raise ValueError("概率列表的和必须大于0")
    return [value / total for value in values]


@dataclass
class QuestionEntry:
    question_type: str
    probabilities: Union[List[float], int, None]
    texts: Optional[List[str]] = None
    rows: int = 1
    option_count: int = 0
    distribution_mode: str = "random"  # random, equal, custom
    custom_weights: Optional[List[float]] = None
    question_num: Optional[str] = None
    option_fill_texts: Optional[List[Optional[str]]] = None
    fillable_option_indices: Optional[List[int]] = None

    def summary(self) -> str:
        def _mode_text(mode: Optional[str]) -> str:
            return {
                "random": "完全随机",
                "equal": "平均分配",
                "custom": "自定义配比",
            }.get(mode or "", "平均分配")

        if self.question_type == "text":
            samples = " | ".join(filter(None, self.texts or []))
            preview = samples if samples else "未设置示例内容"
            if len(preview) > 60:
                preview = preview[:57] + "..."
            return f"填空题: {preview}"

        if self.question_type == "matrix":
            mode_text = _mode_text(self.distribution_mode)
            rows = max(1, self.rows)
            columns = max(1, self.option_count)
            return f"{rows} 行 × {columns} 列 - {mode_text}"

        if self.question_type == "multiple" and self.probabilities == -1:
            return f"{self.option_count} 个选项 - 随机多选"

        if self.probabilities == -1:
            return f"{self.option_count} 个选项 - 完全随机"

        mode_text = _mode_text(self.distribution_mode)
        fillable_hint = ""
        if self.option_fill_texts and any(text for text in self.option_fill_texts if text):
            fillable_hint = " | 含填空项"

        if self.question_type == "multiple" and self.custom_weights:
            weights_str = ",".join(f"{int(round(max(w, 0)))}%" for w in self.custom_weights)
            return f"{self.option_count} 个选项 - 权重 {weights_str}{fillable_hint}"

        if self.distribution_mode == "custom" and self.custom_weights:
            def _format_ratio(value: float) -> str:
                rounded = round(value, 1)
                if abs(rounded - int(rounded)) < 1e-6:
                    return str(int(rounded))
                return f"{rounded}".rstrip("0").rstrip(".")

            weights_str = ":".join(_format_ratio(max(w, 0.1)) for w in self.custom_weights)
            return f"{self.option_count} 个选项 - 配比 {weights_str}{fillable_hint}"

        return f"{self.option_count} 个选项 - {mode_text}{fillable_hint}"


QUESTION_TYPE_LABELS = {
    "single": "单选题",
    "multiple": "多选题",
    "dropdown": "下拉题",
    "matrix": "矩阵题",
    "scale": "量表题",
    "text": "填空题",
}

DEFAULT_FILL_TEXT = "无"  # 填空选项留空时的默认文本

def _normalize_option_fill_texts(option_texts: Optional[List[Optional[str]]], option_count: int) -> Optional[List[Optional[str]]]:
    if not option_texts:
        return None
    normalized_count = option_count if option_count > 0 else len(option_texts)
    normalized: List[Optional[str]] = []
    for idx in range(normalized_count):
        raw = option_texts[idx] if idx < len(option_texts) else None
        if raw is None:
            normalized.append(None)
            continue
        try:
            text_value = str(raw).strip()
        except Exception:
            text_value = ""
        normalized.append(text_value or None)
    if not any(value for value in normalized):
        return None
    return normalized


def _get_fill_text_from_config(fill_entries: Optional[List[Optional[str]]], option_index: int) -> Optional[str]:
    if not fill_entries or option_index < 0 or option_index >= len(fill_entries):
        return None
    value = fill_entries[option_index]
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _fill_option_additional_text(driver: WebDriver, question_number: int, option_index_zero_based: int, fill_value: Optional[str]) -> None:
    if not fill_value:
        return
    text = str(fill_value).strip()
    if not text:
        return
    try:
        question_div = driver.find_element(By.CSS_SELECTOR, f"#div{question_number}")
    except Exception:
        return
    candidate_inputs = []
    try:
        option_elements = question_div.find_elements(By.CSS_SELECTOR, 'div.ui-controlgroup > div')
    except Exception:
        option_elements = []
    if option_elements and 0 <= option_index_zero_based < len(option_elements):
        option_element = option_elements[option_index_zero_based]
        try:
            candidate_inputs.extend(option_element.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='search'], textarea"))
        except Exception:
            pass
        try:
            candidate_inputs.extend(option_element.find_elements(By.CSS_SELECTOR, ".ui-other input, .ui-other textarea"))
        except Exception:
            pass
    if not candidate_inputs:
        try:
            candidate_inputs = question_div.find_elements(By.CSS_SELECTOR, ".ui-other input, .ui-other textarea")
        except Exception:
            candidate_inputs = []
    if not candidate_inputs:
        try:
            candidate_inputs = question_div.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='search'], textarea")
        except Exception:
            candidate_inputs = []
    for input_element in candidate_inputs:
        try:
            if not input_element.is_displayed():
                continue
        except Exception:
            continue
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", input_element)
        except Exception:
            pass
        try:
            input_element.clear()
        except Exception:
            pass
        try:
            input_element.send_keys(text)
            time.sleep(0.05)
            return
        except Exception:
            continue

def configure_probabilities(entries: List[QuestionEntry]):
    global single_prob, droplist_prob, multiple_prob, matrix_prob, scale_prob, texts, texts_prob
    global single_option_fill_texts, droplist_option_fill_texts, multiple_option_fill_texts
    single_prob = []
    droplist_prob = []
    multiple_prob = []
    matrix_prob = []
    scale_prob = []
    texts = []
    texts_prob = []
    single_option_fill_texts = []
    droplist_option_fill_texts = []
    multiple_option_fill_texts = []

    for entry in entries:
        probs = entry.probabilities
        if entry.question_type == "single":
            single_prob.append(normalize_probabilities(probs) if isinstance(probs, list) else -1)
            single_option_fill_texts.append(_normalize_option_fill_texts(entry.option_fill_texts, entry.option_count))
        elif entry.question_type == "dropdown":
            droplist_prob.append(normalize_probabilities(probs) if isinstance(probs, list) else -1)
            droplist_option_fill_texts.append(_normalize_option_fill_texts(entry.option_fill_texts, entry.option_count))
        elif entry.question_type == "multiple":
            if not isinstance(probs, list):
                raise ValueError("多选题必须提供概率列表，数值范围0-100")
            multiple_prob.append([float(value) for value in probs])
            multiple_option_fill_texts.append(_normalize_option_fill_texts(entry.option_fill_texts, entry.option_count))
        elif entry.question_type == "matrix":
            rows = max(1, entry.rows)
            if isinstance(probs, list):
                normalized = normalize_probabilities(probs)
                for _ in range(rows):
                    matrix_prob.append(list(normalized))
            else:
                for _ in range(rows):
                    matrix_prob.append(-1)
        elif entry.question_type == "scale":
            scale_prob.append(normalize_probabilities(probs) if isinstance(probs, list) else -1)
        elif entry.question_type == "text":
            values = entry.texts or []
            if not values:
                raise ValueError("填空题至少需要一个候选答案")
            if isinstance(probs, list):
                if len(probs) != len(values):
                    raise ValueError("填空题概率数量需与答案数量一致")
                normalized = normalize_probabilities(probs)
            else:
                normalized = normalize_probabilities([1.0] * len(values))
            texts.append(values)
            texts_prob.append(normalized)


def decode_qrcode(image_source: Union[str, Image.Image]) -> Optional[str]:
    """
    解码二维码图片,提取其中的链接
    
    参数:
        image_source: 图片文件路径(str)或PIL Image对象
    
    返回:
        str: 解码出的链接,如果解码失败返回None
    
    示例:
        >>> url = decode_qrcode("qrcode.png")
        >>> url = decode_qrcode(Image.open("qrcode.png"))
    """
    try:
        # 如果是文件路径,打开图片
        if isinstance(image_source, str):
            if not os.path.exists(image_source):
                raise FileNotFoundError(f"图片文件不存在: {image_source}")
            image = Image.open(image_source)
        else:
            image = image_source
        
        # 解码二维码
        decoded_objects = pyzbar_decode(image)
        
        if not decoded_objects:
            return None
        
        # 获取第一个二维码的数据
        qr_data = decoded_objects[0].data.decode('utf-8')
        
        # 验证是否为有效URL
        if qr_data.startswith(('http://', 'https://', 'www.')):
            return qr_data
        
        return qr_data
        
    except Exception as e:
        logging.error(f"二维码解码失败: {str(e)}")
        return None


def _normalize_html_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return _HTML_SPACE_RE.sub(" ", value).strip()


_INVALID_FILENAME_CHARS_RE = re.compile(r'[\\/:*?"<>|]+')


def _sanitize_filename(value: str, max_length: int = 80) -> str:
    """将字符串转换为适合作为文件名的形式。"""
    text = value.strip()
    if not text:
        return ""
    text = _INVALID_FILENAME_CHARS_RE.sub("_", text)
    text = text.strip(" ._")
    if max_length and len(text) > max_length:
        text = text[:max_length].rstrip(" ._")
    return text


def _extract_survey_title_from_html(html: str) -> Optional[str]:
    """尝试从问卷 HTML 文本中提取标题。"""
    if not BeautifulSoup:
        return None
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return None

    selectors = [
        "#divTitle h1",
        "#divTitle",
        ".surveytitle",
        ".survey-title",
        ".surveyTitle",
        ".wjdcTitle",
        ".htitle",
        ".topic_tit",
        "#htitle",
        "#lbTitle",
    ]
    candidates: List[str] = []
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            text = _normalize_html_text(element.get_text(" ", strip=True))
            if text:
                candidates.append(text)

    if not candidates:
        for tag_name in ("h1", "h2"):
            header = soup.find(tag_name)
            if header:
                text = _normalize_html_text(header.get_text(" ", strip=True))
                if text:
                    candidates.append(text)
                if candidates:
                    break

    title_tag = soup.find("title")
    if title_tag:
        text = _normalize_html_text(title_tag.get_text(" ", strip=True))
        if text:
            candidates.append(text)

    for raw in candidates:
        cleaned = raw
        cleaned = re.sub(r"(?:[-|]\s*)?(?:问卷星.*)$", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip(" -_|")
        if cleaned:
            return cleaned
    return None


def _extract_question_number_from_div(question_div) -> Optional[int]:
    topic_attr = question_div.get("topic")
    if topic_attr and topic_attr.isdigit():
        return int(topic_attr)
    id_attr = question_div.get("id") or ""
    match = re.search(r"div(\d+)", id_attr)
    if match:
        return int(match.group(1))
    return None


def _cleanup_question_title(raw_title: str) -> str:
    title = _normalize_html_text(raw_title)
    if not title:
        return ""
    title = re.sub(r"^\*?\s*\d+\.\s*", "", title)
    title = title.replace("【单选题】", "").replace("【多选题】", "")
    return title.strip()


def _element_contains_text_input(element) -> bool:
    if element is None:
        return False
    try:
        candidates = element.find_all(['input', 'textarea'])
    except Exception:
        return False
    for candidate in candidates:
        try:
            tag_name = (candidate.name or '').lower()
        except Exception:
            tag_name = ''
        input_type = (candidate.get('type') or '').lower()
        if tag_name == 'textarea':
            return True
        if input_type in ('', 'text', 'search', 'tel', 'number'):
            return True
    return False


def _question_div_has_shared_text_input(question_div) -> bool:
    if question_div is None:
        return False
    try:
        shared_inputs = question_div.select('.ui-other input, .ui-other textarea')
    except Exception:
        shared_inputs = []
    if shared_inputs:
        return True
    try:
        keyword_inputs = question_div.select("input[id*='other'], input[name*='other'], textarea[id*='other'], textarea[name*='other']")
        if keyword_inputs:
            return True
    except Exception:
        pass
    text_blob = _normalize_html_text(question_div.get_text(' ', strip=True))
    option_fill_keywords = ["请注明", "其他", "其他内容", "填空", "填写"]
    if any(keyword in text_blob for keyword in option_fill_keywords):
        return True
    return False


def _collect_choice_option_texts(question_div) -> Tuple[List[str], List[int]]:
    texts: List[str] = []
    fillable_indices: List[int] = []
    seen = set()
    option_elements: List[Any] = []
    selectors = ['.ui-controlgroup > div', 'ul > li']
    for selector in selectors:
        try:
            option_elements = question_div.select(selector)
        except Exception:
            option_elements = []
        if option_elements:
            break
    if option_elements:
        for element in option_elements:
            label_element = None
            try:
                label_element = element.select_one('.label')
            except Exception:
                label_element = None
            if not label_element:
                label_element = element
            text = _normalize_html_text(label_element.get_text(' ', strip=True))
            if not text or text in seen:
                continue
            option_index = len(texts)
            texts.append(text)
            seen.add(text)
            if _element_contains_text_input(element):
                fillable_indices.append(option_index)
    if not texts:
        fallback_selectors = ['.label', 'li span', 'li']
        for selector in fallback_selectors:
            try:
                elements = question_div.select(selector)
            except Exception:
                elements = []
            for element in elements:
                text = _normalize_html_text(element.get_text(' ', strip=True))
                if not text or text in seen:
                    continue
                texts.append(text)
                seen.add(text)
            if texts:
                break
    if not fillable_indices and texts and _question_div_has_shared_text_input(question_div):
        fillable_indices.append(len(texts) - 1)
    fillable_indices = sorted(set(fillable_indices))
    return texts, fillable_indices


def _selenium_element_contains_text_input(element) -> bool:
    if element is None:
        return False
    try:
        inputs = element.find_elements(By.CSS_SELECTOR, "input, textarea")
    except Exception:
        return False
    for candidate in inputs:
        try:
            tag_name = (candidate.tag_name or "").lower()
        except Exception:
            tag_name = ""
        input_type = ""
        try:
            input_type = (candidate.get_attribute("type") or "").lower()
        except Exception:
            input_type = ""
        if tag_name == "textarea":
            return True
        if tag_name == "input" and input_type in ("", "text", "search", "tel", "number"):
            return True
    return False


def _selenium_question_has_shared_text_input(question_div) -> bool:
    if question_div is None:
        return False
    try:
        shared = question_div.find_elements(By.CSS_SELECTOR, ".ui-other input, .ui-other textarea")
        if shared:
            return True
    except Exception:
        pass
    try:
        keyword_elements = question_div.find_elements(By.CSS_SELECTOR, "input[id*='other'], textarea[id*='other']")
        if keyword_elements:
            return True
    except Exception:
        pass
    try:
        text_blob = (question_div.text or "").strip()
    except Exception:
        text_blob = ""
    if not text_blob:
        return False
    option_fill_keywords = ["请注明", "其他", "填空", "填写", "specify", "other"]
    return any(keyword in text_blob for keyword in option_fill_keywords)


def _collect_select_option_texts(question_div, soup, question_number: int) -> List[str]:
    select = question_div.find("select")
    if not select and soup:
        select = soup.find("select", id=f"q{question_number}")
    if not select:
        return []
    options: List[str] = []
    option_elements = select.find_all("option")
    for idx, option in enumerate(option_elements):
        value = (option.get("value") or "").strip()
        text = _normalize_html_text(option.get_text(" ", strip=True))
        if idx == 0 and (value == "" or value == "0"):
            continue
        if not text:
            continue
        options.append(text)
    return options


def _collect_matrix_option_texts(soup, question_number: int) -> Tuple[int, List[str]]:
    option_texts: List[str] = []
    matrix_rows = 0
    table = soup.find(id=f"divRefTab{question_number}") if soup else None
    if table:
        for row in table.find_all("tr"):
            row_index = str(row.get("rowindex") or "").strip()
            if row_index and str(row_index).isdigit():
                matrix_rows += 1
    header_row = soup.find(id=f"drv{question_number}_1") if soup else None
    if header_row:
        cells = header_row.find_all("td")
        if len(cells) > 1:
            option_texts = [_normalize_html_text(td.get_text(" ", strip=True)) for td in cells[1:]]
            option_texts = [text for text in option_texts if text]
    if not option_texts and table:
        header_cells = table.find_all("th")
        if len(header_cells) > 1:
            option_texts = [_normalize_html_text(th.get_text(" ", strip=True)) for th in header_cells[1:]]
            option_texts = [text for text in option_texts if text]
    return matrix_rows, option_texts


def _extract_question_title(question_div, fallback_number: int) -> str:
    title_element = question_div.find(class_="topichtml")
    if title_element:
        title_text = _cleanup_question_title(title_element.get_text(" ", strip=True))
        if title_text:
            return title_text
    label_element = question_div.find(class_="field-label")
    if label_element:
        title_text = _cleanup_question_title(label_element.get_text(" ", strip=True))
        if title_text:
            return title_text
    return f"第{fallback_number}题"


def _extract_question_metadata_from_html(soup, question_div, question_number: int, type_code: str):
    option_texts: List[str] = []
    option_count = 0
    matrix_rows = 0
    fillable_indices: List[int] = []
    if type_code in {"3", "4", "5", "11"}:
        option_texts, fillable_indices = _collect_choice_option_texts(question_div)
        option_count = len(option_texts)
    elif type_code == "7":
        option_texts = _collect_select_option_texts(question_div, soup, question_number)
        option_count = len(option_texts)
        if option_count > 0 and _question_div_has_shared_text_input(question_div):
            fillable_indices = [option_count - 1]
    elif type_code == "6":
        matrix_rows, option_texts = _collect_matrix_option_texts(soup, question_number)
        option_count = len(option_texts)
    return option_texts, option_count, matrix_rows, fillable_indices


def parse_survey_questions_from_html(html: str) -> List[Dict[str, Any]]:
    if not BeautifulSoup:
        raise RuntimeError("BeautifulSoup is required for HTML parsing")
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find("div", id="divQuestion")
    if not container:
        return []
    fieldsets = container.find_all("fieldset")
    if not fieldsets:
        fieldsets = [container]
    questions_info: List[Dict[str, Any]] = []
    for page_index, fieldset in enumerate(fieldsets, 1):
        question_divs = fieldset.find_all("div", attrs={"topic": True}, recursive=False)
        if not question_divs:
            question_divs = fieldset.find_all("div", attrs={"topic": True})
        for question_div in question_divs:
            question_number = _extract_question_number_from_div(question_div)
            if question_number is None:
                continue
            type_code = str(question_div.get("type") or "").strip() or "0"
            title_text = _extract_question_title(question_div, question_number)
            option_texts, option_count, matrix_rows, fillable_indices = _extract_question_metadata_from_html(
                soup, question_div, question_number, type_code
            )
            questions_info.append({
                "num": question_number,
                "title": title_text,
                "type_code": type_code,
                "options": option_count,
                "rows": matrix_rows,
                "page": page_index,
                "option_texts": option_texts,
                "fillable_options": fillable_indices,
            })
    return questions_info


def _extract_text_from_element(element) -> str:
    try:
        text = element.text or ""
    except Exception:
        text = ""
    text = text.strip()
    if text:
        return text
    try:
        text = (element.get_attribute("textContent") or "").strip()
    except Exception:
        text = ""
    return text


def _safe_positive_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        int_value = int(value)
        return int_value if int_value > 0 else None
    try:
        text = str(value).strip()
    except Exception:
        return None
    if not text:
        return None
    if text.isdigit():
        int_value = int(text)
        return int_value if int_value > 0 else None
    match = re.search(r"(\d+)", text)
    if match:
        int_value = int(match.group(1))
        return int_value if int_value > 0 else None
    return None


def _extract_limit_from_json_obj(obj: Any) -> Optional[int]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            normalized_key = str(key).lower()
            if normalized_key in _MULTI_LIMIT_VALUE_KEYSET:
                limit = _safe_positive_int(value)
                if limit:
                    return limit
            nested = _extract_limit_from_json_obj(value)
            if nested:
                return nested
    elif isinstance(obj, list):
        for item in obj:
            nested = _extract_limit_from_json_obj(item)
            if nested:
                return nested
    return None


def _extract_limit_from_possible_json(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    normalized = text.strip()
    if not normalized:
        return None
    candidates = [normalized]
    if normalized.startswith("{") and "'" in normalized and '"' not in normalized:
        candidates.append(normalized.replace("'", '"'))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        limit = _extract_limit_from_json_obj(parsed)
        if limit:
            return limit
    for key in _MULTI_LIMIT_VALUE_KEYSET:
        pattern = re.compile(rf"{re.escape(key)}\s*[:=]\s*(\d+)", re.IGNORECASE)
        match = pattern.search(normalized)
        if match:
            limit = _safe_positive_int(match.group(1))
            if limit:
                return limit
    return None


def _extract_limit_from_attributes(element) -> Optional[int]:
    for attr in _MULTI_LIMIT_ATTRIBUTE_NAMES:
        try:
            raw_value = element.get_attribute(attr)
        except Exception:
            continue
        limit = _safe_positive_int(raw_value)
        if limit:
            return limit
    return None


def _extract_multi_limit_from_text(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    normalized = text.strip()
    if not normalized:
        return None
    normalized_lower = normalized.lower()
    contains_cn_keyword = any(keyword in normalized for keyword in _SELECTION_KEYWORDS_CN)
    contains_en_keyword = any(keyword in normalized_lower for keyword in _SELECTION_KEYWORDS_EN)
    if contains_cn_keyword:
        for pattern in _CHINESE_MULTI_LIMIT_PATTERNS:
            match = pattern.search(normalized)
            if match:
                limit = _safe_positive_int(match.group(1))
                if limit:
                    return limit
    if contains_en_keyword:
        for pattern in _ENGLISH_MULTI_LIMIT_PATTERNS:
            match = pattern.search(normalized)
            if match:
                limit = _safe_positive_int(match.group(1))
                if limit:
                    return limit
    return None


def _get_driver_session_key(driver: WebDriver) -> str:
    session_id = getattr(driver, "session_id", None)
    if session_id:
        return str(session_id)
    return f"id-{id(driver)}"


def detect_multiple_choice_limit(driver: WebDriver, question_number: int) -> Optional[int]:
    cache_key = (_get_driver_session_key(driver), question_number)
    if cache_key in _DETECTED_MULTI_LIMITS:
        return _DETECTED_MULTI_LIMITS[cache_key]
    limit: Optional[int] = None
    try:
        container = driver.find_element(By.CSS_SELECTOR, f"#div{question_number}")
    except NoSuchElementException:
        container = None
    if container is not None:
        limit = _extract_limit_from_attributes(container)
        if limit is None:
            for attr_name in ("data", "data-setting", "data-validate"):
                limit = _extract_limit_from_possible_json(container.get_attribute(attr_name))
                if limit:
                    break
        if limit is None:
            fragments: List[str] = []
            for selector in (".qtypetip", ".topichtml", ".field-label"):
                try:
                    fragments.append(container.find_element(By.CSS_SELECTOR, selector).text)
                except Exception:
                    continue
            fragments.append(container.text)
            for fragment in fragments:
                limit = _extract_multi_limit_from_text(fragment)
                if limit:
                    break
        if limit is None:
            html = container.get_attribute("outerHTML")
            limit = _extract_limit_from_possible_json(html)
            if limit is None:
                limit = _extract_multi_limit_from_text(html)
    _DETECTED_MULTI_LIMITS[cache_key] = limit
    return limit


def _log_multi_limit_once(driver: WebDriver, question_number: int, limit: Optional[int]) -> None:
    if not limit:
        return
    cache_key = (_get_driver_session_key(driver), question_number)
    if cache_key in _REPORTED_MULTI_LIMITS:
        return
    print(f"第{question_number}题检测到最多可选 {limit} 项，自动限制选择数量。")
    _REPORTED_MULTI_LIMITS.add(cache_key)


def try_click_start_answer_button(driver: WebDriver, timeout: float = 1.0) -> bool:
    """
    快速检测开屏“开始作答”按钮，若存在立即点击；否则立即继续，无需额外等待。
    """
    poll_interval = 0.2
    total_window = max(0.0, timeout)
    max_checks = max(1, int(math.ceil(total_window / max(poll_interval, 0.05)))) if total_window else 1
    locator_candidates = [
        (By.CSS_SELECTOR, "div.slideChunkWord"),
        (By.XPATH, "//div[contains(@class,'slideChunkWord') and contains(normalize-space(),'开始作答')]"),
        (By.XPATH, "//*[contains(text(),'开始作答')]"),
    ]
    already_reported = False
    for attempt in range(max_checks):
        for by, value in locator_candidates:
            try:
                elements = driver.find_elements(by, value)
            except Exception:
                continue
            for element in elements:
                try:
                    displayed = element.is_displayed()
                except Exception:
                    continue
                if not displayed:
                    continue
                text = _extract_text_from_element(element)
                if "开始作答" not in text:
                    continue
                if not already_reported:
                    print("检测到“开始作答”按钮，尝试自动点击...")
                    already_reported = True
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", element)
                except Exception:
                    pass
                clicked = False
                try:
                    element.click()
                    clicked = True
                except Exception:
                    try:
                        driver.execute_script("arguments[0].click();", element)
                        clicked = True
                    except Exception:
                        try:
                            ActionChains(driver).move_to_element(element).click().perform()
                            clicked = True
                        except Exception:
                            clicked = False
                if clicked:
                    time.sleep(0.3)
                    return True
        if attempt < max_checks - 1:
            time.sleep(poll_interval)
    return False


def dismiss_resume_dialog_if_present(driver: WebDriver, timeout: float = 1.0) -> bool:
    """
    快速检查“继续上次作答”弹窗，如有立即点击“取消”；否则不额外等待。
    """
    poll_interval = 0.2
    total_window = max(0.0, timeout)
    max_checks = max(1, int(math.ceil(total_window / max(poll_interval, 0.05)))) if total_window else 1
    locator_candidates = [
        (By.CSS_SELECTOR, "a.layui-layer-btn1"),
        (By.XPATH, "//a[contains(@class,'layui-layer-btn1') and contains(normalize-space(),'取消')]"),
        (By.XPATH, "//div[contains(@class,'layui-layer-btn')]//a[contains(text(),'取消')]"),
    ]
    clicked_once = False
    for attempt in range(max_checks):
        for by, value in locator_candidates:
            try:
                buttons = driver.find_elements(by, value)
            except Exception:
                continue
            for button in buttons:
                try:
                    displayed = button.is_displayed()
                except Exception:
                    continue
                if not displayed:
                    continue
                text = _extract_text_from_element(button)
                if text and "取消" not in text:
                    continue
                if not clicked_once:
                    print("检测到“继续上次作答”弹窗，自动点击取消以开始新作答...")
                    clicked_once = True
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", button)
                except Exception:
                    pass
                try:
                    button.click()
                    return True
                except Exception:
                    try:
                        driver.execute_script("arguments[0].click();", button)
                        return True
                    except Exception:
                        try:
                            ActionChains(driver).move_to_element(button).click().perform()
                            return True
                        except Exception:
                            continue
        if attempt < max_checks - 1:
            time.sleep(poll_interval)
    return False


def detect(driver: WebDriver) -> List[int]:
    dismiss_resume_dialog_if_present(driver)
    try_click_start_answer_button(driver)
    question_counts_per_page: List[int] = []
    total_pages = len(driver.find_elements(By.XPATH, '//*[@id="divQuestion"]/fieldset'))
    for page_index in range(1, total_pages + 1):
        page_questions = driver.find_elements(By.XPATH, f'//*[@id="fieldset{page_index}"]/div')
        valid_question_count = 0
        for question_element in page_questions:
            topic_attr = question_element.get_attribute("topic")
            if topic_attr and topic_attr.isdigit():
                valid_question_count += 1
        question_counts_per_page.append(valid_question_count)
    return question_counts_per_page


def vacant(driver: WebDriver, current, index):
    answer_candidates = texts[index] if index < len(texts) else [""]
    selection_probabilities = texts_prob[index] if index < len(texts_prob) else [1.0]
    if not answer_candidates:
        answer_candidates = [""]
    if len(selection_probabilities) != len(answer_candidates):
        selection_probabilities = normalize_probabilities([1.0] * len(answer_candidates))
    selected_index = numpy.random.choice(a=numpy.arange(0, len(selection_probabilities)), p=selection_probabilities)
    driver.find_element(By.CSS_SELECTOR, f"#q{current}").send_keys(answer_candidates[selected_index])


def single(driver: WebDriver, current, index):
    options_xpath = f'//*[@id="div{current}"]/div[2]/div'
    option_elements = driver.find_elements(By.XPATH, options_xpath)
    probabilities = single_prob[index] if index < len(single_prob) else -1
    if probabilities == -1:
        selected_option = random.randint(1, len(option_elements))
    else:
        assert len(probabilities) == len(option_elements), f"第{current}题参数长度：{len(probabilities)},选项长度{len(option_elements)},不一致！"
        selected_option = numpy.random.choice(a=numpy.arange(1, len(option_elements) + 1), p=probabilities)
    driver.find_element(
        By.CSS_SELECTOR, f"#div{current} > div.ui-controlgroup > div:nth-child({selected_option})"
    ).click()
    fill_entries = single_option_fill_texts[index] if index < len(single_option_fill_texts) else None
    fill_value = _get_fill_text_from_config(fill_entries, selected_option - 1)
    _fill_option_additional_text(driver, current, selected_option - 1, fill_value)


# 下拉框处理函数
def droplist(driver: WebDriver, current, index):
    # 先点击“请选择”
    driver.find_element(By.CSS_SELECTOR, f"#select2-q{current}-container").click()
    time.sleep(0.5)
    # 选项数量
    options = driver.find_elements(
        By.XPATH, f"//*[@id='select2-q{current}-results']/li"
    )
    if len(options) <= 1:
        return
    p = droplist_prob[index] if index < len(droplist_prob) else -1
    if p == -1:
        p = normalize_probabilities([1.0] * (len(options) - 1))
    r = numpy.random.choice(a=numpy.arange(1, len(options)), p=p)
    driver.find_element(
        By.XPATH, f"//*[@id='select2-q{current}-results']/li[{r + 1}]"
    ).click()
    fill_entries = droplist_option_fill_texts[index] if index < len(droplist_option_fill_texts) else None
    fill_value = _get_fill_text_from_config(fill_entries, r - 1)
    _fill_option_additional_text(driver, current, r - 1, fill_value)


def multiple(driver: WebDriver, current, index):
    options_xpath = f'//*[@id="div{current}"]/div[2]/div'
    option_elements = driver.find_elements(By.XPATH, options_xpath)
    if not option_elements:
        return
    max_select_limit = detect_multiple_choice_limit(driver, current)
    if max_select_limit is not None:
        effective_limit = max(1, min(max_select_limit, len(option_elements)))
        _log_multi_limit_once(driver, current, max_select_limit)
    else:
        effective_limit = len(option_elements)
    selection_probabilities = multiple_prob[index] if index < len(multiple_prob) else [50.0] * len(option_elements)
    fill_entries = multiple_option_fill_texts[index] if index < len(multiple_option_fill_texts) else None

    if selection_probabilities == -1 or (isinstance(selection_probabilities, list) and len(selection_probabilities) == 1 and selection_probabilities[0] == -1):
        num_to_select = random.randint(1, max(1, effective_limit))
        selected_indices = random.sample(range(len(option_elements)), num_to_select)
        for option_idx in selected_indices:
            selector = f"#div{current} > div.ui-controlgroup > div:nth-child({option_idx + 1})"
            driver.find_element(By.CSS_SELECTOR, selector).click()
            fill_value = _get_fill_text_from_config(fill_entries, option_idx)
            _fill_option_additional_text(driver, current, option_idx, fill_value)
        return
    
    assert len(option_elements) == len(selection_probabilities), f"第{current}题概率值和选项值不一致"
    selection_mask: List[int] = []
    while sum(selection_mask) == 0:
        selection_mask = [
            numpy.random.choice(a=numpy.arange(0, 2), p=[1 - (prob / 100), prob / 100])
            for prob in selection_probabilities
        ]
    selected_indices = [idx for idx, selected in enumerate(selection_mask) if selected == 1]
    if max_select_limit is not None and len(selected_indices) > effective_limit:
        random.shuffle(selected_indices)
        selected_indices = selected_indices[:effective_limit]
    if not selected_indices:
        selected_indices = [random.randrange(len(option_elements))]
    for option_idx in selected_indices:
        selector = f"#div{current} > div.ui-controlgroup > div:nth-child({option_idx + 1})"
        driver.find_element(By.CSS_SELECTOR, selector).click()
        fill_value = _get_fill_text_from_config(fill_entries, option_idx)
        _fill_option_additional_text(driver, current, option_idx, fill_value)


def matrix(driver: WebDriver, current, index):
    rows_xpath = f'//*[@id="divRefTab{current}"]/tbody/tr'
    row_elements = driver.find_elements(By.XPATH, rows_xpath)
    matrix_row_count = sum(1 for row in row_elements if row.get_attribute("rowindex") is not None)
    
    columns_xpath = f'//*[@id="drv{current}_1"]/td'
    column_elements = driver.find_elements(By.XPATH, columns_xpath)
    if len(column_elements) <= 1:
        return index
    
    for row_index in range(1, matrix_row_count + 1):
        probabilities = matrix_prob[index] if index < len(matrix_prob) else -1
        index += 1
        if probabilities == -1:
            selected_column = random.randint(2, len(column_elements))
        else:
            selected_column = numpy.random.choice(a=numpy.arange(2, len(column_elements) + 1), p=probabilities)
        driver.find_element(
            By.CSS_SELECTOR, f"#drv{current}_{row_index} > td:nth-child({selected_column})"
        ).click()
    return index


def reorder(driver: WebDriver, current):
    items_xpath = f'//*[@id="div{current}"]/ul/li'
    order_items = driver.find_elements(By.XPATH, items_xpath)
    for position in range(1, len(order_items) + 1):
        selected_item = random.randint(position, len(order_items))
        driver.find_element(
            By.CSS_SELECTOR, f"#div{current} > ul > li:nth-child({selected_item})"
        ).click()
        time.sleep(0.4)


def scale(driver: WebDriver, current, index):
    scale_items_xpath = f'//*[@id="div{current}"]/div[2]/div/ul/li'
    scale_options = driver.find_elements(By.XPATH, scale_items_xpath)
    probabilities = scale_prob[index] if index < len(scale_prob) else -1
    if not scale_options:
        return
    if probabilities == -1:
        selected_index = random.randrange(len(scale_options))
    else:
        selected_index = numpy.random.choice(a=numpy.arange(0, len(scale_options)), p=probabilities)
    scale_options[selected_index].click()


def _set_slider_input_value(driver: WebDriver, current: int, value: int):
    try:
        slider_input = driver.find_element(By.CSS_SELECTOR, f"#q{current}")
    except NoSuchElementException:
        return
    script = (
        "const input = arguments[0];"
        "const target = String(arguments[1]);"
        "input.value = target;"
        "['input','change'].forEach(evt => input.dispatchEvent(new Event(evt, { bubbles: true })));"
    )
    try:
        driver.execute_script(script, slider_input, value)
    except Exception:
        pass


def _click_slider_track(driver: WebDriver, container, ratio: float) -> bool:
    xpath_candidates = [
        ".//div[contains(@class,'wjx-slider') or contains(@class,'slider-track') or contains(@class,'range-slider') or contains(@class,'ui-slider') or contains(@class,'scale-slider') or contains(@class,'slider-container')]",
        ".//div[@role='slider']",
    ]
    for xpath in xpath_candidates:
        tracks = container.find_elements(By.XPATH, xpath)
        for track in tracks:
            width = track.size.get("width") or 0
            height = track.size.get("height") or 0
            if width <= 0 or height <= 0:
                continue
            offset_x = int(width * ratio)
            offset_x = max(5, min(offset_x, width - 5))
            offset_y = max(1, height // 2)
            try:
                ActionChains(driver).move_to_element_with_offset(track, offset_x, offset_y).click().perform()
                return True
            except Exception:
                continue
    return False


def slider_question(driver: WebDriver, current: int, score: int):
    ratio = max(0.0, min(score / 100.0, 1.0))
    try:
        container = driver.find_element(By.CSS_SELECTOR, f"#div{current}")
    except NoSuchElementException:
        container = None
    if container:
        _click_slider_track(driver, container, ratio)
    _set_slider_input_value(driver, current, score)


def _full_simulation_active() -> bool:
    return bool(full_simulation_enabled and full_simulation_estimated_seconds > 0)


def _reset_full_simulation_runtime_state() -> None:
    global full_simulation_schedule, full_simulation_end_timestamp
    try:
        full_simulation_schedule.clear()
    except Exception:
        full_simulation_schedule = deque()
    full_simulation_end_timestamp = 0.0


def _prepare_full_simulation_schedule(run_count: int, total_duration_seconds: int) -> Deque[float]:
    global full_simulation_end_timestamp
    schedule: Deque[float] = deque()
    if run_count <= 0:
        full_simulation_end_timestamp = 0.0
        return schedule
    now = time.time()
    total_span = max(0, total_duration_seconds)
    if total_span <= 0:
        for idx in range(run_count):
            schedule.append(now + idx * 5)
        full_simulation_end_timestamp = now + run_count * 5
        return schedule
    base_interval = total_span / max(1, run_count)
    jitter_window = base_interval * 0.6
    offsets: List[float] = []
    for index in range(run_count):
        ideal = index * base_interval
        jitter = random.uniform(-jitter_window, jitter_window) if jitter_window > 0 else 0.0
        offset = max(0.0, min(total_span * 0.98, ideal + jitter))
        offsets.append(offset)
    offsets.sort()
    for offset in offsets:
        schedule.append(now + offset)
    full_simulation_end_timestamp = now + total_span
    return schedule


def _wait_for_next_full_simulation_slot(stop_signal: threading.Event) -> bool:
    with lock:
        if not full_simulation_schedule:
            return False
        next_slot = full_simulation_schedule.popleft()
    while True:
        if stop_signal.is_set():
            return False
        delay = next_slot - time.time()
        if delay <= 0:
            break
        wait_time = min(delay, 1.0)
        if wait_time <= 0:
            break
        if stop_signal.wait(wait_time):
            return False
    return True


def _calculate_full_simulation_run_target() -> float:
    base = max(5.0, float(full_simulation_estimated_seconds))
    jitter = max(0.05, min(0.5, FULL_SIM_DURATION_JITTER))
    lower = max(2.0, base * (1 - jitter))
    upper = max(lower + 0.5, base * (1 + jitter))
    return random.uniform(lower, upper)


def _build_per_question_delay_plan(question_count: int, target_seconds: float) -> List[float]:
    if question_count <= 0 or target_seconds <= 0:
        return []
    avg_delay = target_seconds / max(1, question_count)
    min_delay = max(FULL_SIM_MIN_DELAY_SECONDS, avg_delay * 0.6)
    max_possible_min = target_seconds / max(1, question_count)
    if min_delay > max_possible_min:
        min_delay = max(FULL_SIM_MIN_DELAY_SECONDS * 0.2, max_possible_min)
    min_delay = max(0.02, min_delay)
    baseline_total = min_delay * question_count
    remaining = max(0.0, target_seconds - baseline_total)
    if remaining <= 0:
        return [target_seconds / max(1, question_count)] * question_count
    weights = [random.uniform(0.3, 1.2) for _ in range(question_count)]
    total_weight = sum(weights) or 1.0
    extras = [remaining * (w / total_weight) for w in weights]
    return [min_delay + extra for extra in extras]


def _simulate_answer_duration_delay(stop_signal: Optional[threading.Event] = None) -> bool:
    """根据配置在提交前等待一段时间，返回 True 表示等待过程中被中断。"""
    if _full_simulation_active():
        return False
    global answer_duration_range_seconds
    min_delay, max_delay = answer_duration_range_seconds
    min_delay = max(0, min_delay)
    max_delay = max(min_delay, max(0, max_delay))
    if max_delay <= 0:
        return False
    wait_seconds = random.uniform(min_delay, max_delay)
    if wait_seconds <= 0:
        return False
    logging.info(
        "[Action Log] Simulating answer duration: waiting %.1f seconds before submit",
        wait_seconds,
    )
    if stop_signal:
        interrupted = stop_signal.wait(wait_seconds)
        return bool(interrupted and stop_signal.is_set())
    time.sleep(wait_seconds)
    return False


def brush(driver: WebDriver, stop_signal: Optional[threading.Event] = None) -> bool:
    """批量填写一份问卷；返回 True 代表完整提交，False 代表过程中被用户打断。"""
    questions_per_page = detect(driver)
    total_question_count = sum(questions_per_page)
    single_question_index = 0
    vacant_question_index = 0
    droplist_question_index = 0
    multiple_question_index = 0
    matrix_question_index = 0
    scale_question_index = 0
    current_question_number = 0
    active_stop = stop_signal or stop_event
    question_delay_plan: Optional[List[float]] = None
    if _full_simulation_active() and total_question_count > 0:
        target_seconds = _calculate_full_simulation_run_target()
        question_delay_plan = _build_per_question_delay_plan(total_question_count, target_seconds)
        planned_total = sum(question_delay_plan)
        logging.info(
            "[Action Log] ȫ��ģ�⣺���μƻ���ʱԼ %.1f �룬�� %d ��",
            planned_total,
            total_question_count,
        )

    def _abort_requested() -> bool:
        return bool(active_stop and active_stop.is_set())

    if _abort_requested():
        return False

    total_pages = len(questions_per_page)
    for page_index, questions_count in enumerate(questions_per_page):
        for _ in range(1, questions_count + 1):
            if _abort_requested():
                return False
            current_question_number += 1
            question_type = driver.find_element(
                By.CSS_SELECTOR, f"#div{current_question_number}"
            ).get_attribute("type")

            if question_type in ("1", "2"):
                vacant(driver, current_question_number, vacant_question_index)
                vacant_question_index += 1
            elif question_type == "3":
                single(driver, current_question_number, single_question_index)
                single_question_index += 1
            elif question_type == "4":
                multiple(driver, current_question_number, multiple_question_index)
                multiple_question_index += 1
            elif question_type == "5":
                scale(driver, current_question_number, scale_question_index)
                scale_question_index += 1
            elif question_type == "6":
                matrix_question_index = matrix(driver, current_question_number, matrix_question_index)
            elif question_type == "7":
                droplist(driver, current_question_number, droplist_question_index)
                droplist_question_index += 1
            elif question_type == "8":
                slider_score = random.randint(1, 100)
                slider_question(driver, current_question_number, slider_score)
            elif question_type == "11":
                reorder(driver, current_question_number)
            else:
                print(f"第{current_question_number}题为不支持类型")
        if (
            question_delay_plan
            and current_question_number < total_question_count
        ):
            plan_index = min(current_question_number - 1, len(question_delay_plan) - 1)
            if plan_index >= 0:
                delay_seconds = question_delay_plan[plan_index]
                if delay_seconds > 0.01:
                    if active_stop:
                        if active_stop.wait(delay_seconds):
                            return False
                    else:
                        time.sleep(delay_seconds)
        if _abort_requested():
            return False
        time.sleep(0.5)
        is_last_page = (page_index == total_pages - 1)
        if is_last_page:
            if _simulate_answer_duration_delay(active_stop):
                return False
            if _abort_requested():
                return False
        try:
            driver.find_element(By.CSS_SELECTOR, "#divNext").click()
            time.sleep(0.5)
        except:
            driver.find_element(By.XPATH, '//*[@id="ctlNext"]').click()
    if _abort_requested():
        return False
    submit(driver, stop_signal=active_stop)
    return True
def submit(driver: WebDriver, stop_signal: Optional[threading.Event] = None):
    def _click_submit_buttons():
        try:
            driver.find_element(By.XPATH, '//*[@id="layui-layer1"]/div[3]/a').click()
            if SUBMIT_CLICK_SETTLE_DELAY > 0:
                time.sleep(SUBMIT_CLICK_SETTLE_DELAY)
        except:
            pass
        try:
            driver.find_element(By.XPATH, '//*[@id="SM_BTN_1"]').click()
            if SUBMIT_CLICK_SETTLE_DELAY > 0:
                time.sleep(SUBMIT_CLICK_SETTLE_DELAY)
        except:
            pass

    if SUBMIT_INITIAL_DELAY > 0:
        time.sleep(SUBMIT_INITIAL_DELAY)
    _click_submit_buttons()
    if stop_signal and stop_signal.is_set():
        return
    try:
        captcha_bypassed = handle_aliyun_captcha(driver, timeout=3, stop_signal=stop_signal)
    except AliyunCaptchaBypassError as exc:
        logging.error("阿里云智能验证无法绕过，本次提交将被标记为失败: %s", exc)
        raise
    if captcha_bypassed:
        if stop_signal and stop_signal.is_set():
            return
        if SUBMIT_CLICK_SETTLE_DELAY > 0:
            time.sleep(SUBMIT_CLICK_SETTLE_DELAY)
        _click_submit_buttons()
    try:
        slider_text_element = driver.find_element(By.XPATH, '//*[@id="nc_1__scale_text"]/span')
        slider_handle = driver.find_element(By.XPATH, '//*[@id="nc_1_n1z"]')
        if str(slider_text_element.text).startswith("请按住滑块"):
            slider_width = slider_text_element.size.get("width") or 0
            ActionChains(driver).drag_and_drop_by_offset(
                slider_handle, int(slider_width), 0
            ).perform()
    except:
        pass


def run(window_x_pos, window_y_pos, stop_signal: threading.Event, gui_instance=None):
    global cur_num, cur_fail
    preferred_browsers = list(BROWSER_PREFERENCE)
    while True:
        if stop_signal.is_set():
            break
        # 使用锁并响应停止/完成等动态地触发提交
        with lock:
            if stop_signal.is_set() or (target_num > 0 and cur_num >= target_num):
                break
        if _full_simulation_active():
            if not _wait_for_next_full_simulation_slot(stop_signal):
                break
            logging.info("[Action Log] ȫ��ģ��ʱ����������༭����������...")
        if stop_signal.is_set():
            break
        driver = None
        try:
            if stop_signal.is_set():
                break
            driver, active_browser = create_selenium_driver(headless=False, prefer_browsers=list(preferred_browsers) if preferred_browsers else None)
            preferred_browsers = [active_browser] + [b for b in BROWSER_PREFERENCE if b != active_browser]
            if gui_instance and hasattr(gui_instance, 'active_drivers'):
                gui_instance.active_drivers.append(driver)
            driver.set_window_size(550, 650)
            driver.set_window_position(x=window_x_pos, y=window_y_pos)
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'},
            )
            if stop_signal.is_set():
                break
            driver.get(url)
            if stop_signal.is_set():
                break
            initial_url = driver.current_url
            if stop_signal.is_set():
                break
            finished = brush(driver, stop_signal=stop_signal)
            if stop_signal.is_set() or not finished:
                break
            wait_deadline = time.time() + POST_SUBMIT_URL_MAX_WAIT
            while time.time() < wait_deadline:
                if stop_signal.is_set():
                    break
                if driver.current_url != initial_url:
                    break
                time.sleep(POST_SUBMIT_URL_POLL_INTERVAL)
            final_url = driver.current_url
            if stop_signal.is_set():
                break
            if initial_url != final_url:
                with lock:
                    if target_num <= 0 or cur_num < target_num:
                        cur_num += 1
                        print(
                            f"已填写{cur_num}份 - 失败{cur_fail}次 - {time.strftime('%H:%M:%S', time.localtime(time.time()))} "
                        )
                        if target_num > 0 and cur_num >= target_num:
                            stop_signal.set()
                    else:
                        stop_signal.set()
                        break
        except Exception:
            traceback.print_exc()
            with lock:
                cur_fail += 1
                print(f"已失败{cur_fail}次, 失败次数达到{int(fail_threshold)}次将强制停止")
            if cur_fail >= fail_threshold:
                logging.critical("失败次数过多，强制停止，请检查配置是否正确")
                stop_signal.set()
                break
        finally:
            if driver:
                try:
                    if gui_instance and hasattr(gui_instance, 'active_drivers') and driver in gui_instance.active_drivers:
                        gui_instance.active_drivers.remove(driver)
                    driver.quit()
                except Exception:
                    pass
        if stop_signal.is_set():
            break
        if not _full_simulation_active():
            min_wait, max_wait = submit_interval_range_seconds
            if max_wait > 0:
                wait_seconds = min_wait if max_wait == min_wait else random.uniform(min_wait, max_wait)
                if stop_signal.wait(wait_seconds):
                    break





TYPE_OPTIONS = [
    ("single", "单选题"),
    ("multiple", "多选题"),
    ("dropdown", "下拉题"),
    ("matrix", "矩阵题"),
    ("scale", "量表题"),
    ("text", "填空题"),
]

LABEL_TO_TYPE = {label: value for value, label in TYPE_OPTIONS}


class SurveyGUI:

    def _save_logs_to_file(self):
        records = LOG_BUFFER_HANDLER.get_records()
        parent_window: tk.Misc = self.root
        log_window = getattr(self, "_log_window", None)
        if log_window and getattr(log_window, "winfo_exists", lambda: False)():
            parent_window = log_window
        if not records:
            self._log_popup_info("保存日志文件", "当前尚无日志可保存。", parent=parent_window)
            return

        logs_dir = os.path.join(_get_runtime_directory(), LOG_DIR_NAME)
        os.makedirs(logs_dir, exist_ok=True)
        file_name = datetime.now().strftime("log_%Y%m%d_%H%M%S.txt")
        file_path = os.path.join(logs_dir, file_name)

        try:
            text_records = [entry.text for entry in records]
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(text_records))
            logging.info(f"已保存日志文件: {file_path}")
            self._log_popup_info("保存日志文件", f"日志已保存到:\n{file_path}", parent=parent_window)
        except Exception as exc:
            logging.error(f"保存日志文件失败: {exc}")
            self._log_popup_error("保存日志文件失败", f"无法保存日志: {exc}", parent=parent_window)

    def _refresh_log_viewer(self):
        text_widget = getattr(self, "_log_text_widget", None)
        if not text_widget:
            return
        records = LOG_BUFFER_HANDLER.get_records()
        total_records = len(records)
        prev_count = getattr(self, "_log_rendered_count", 0)
        prev_first = getattr(self, "_log_first_rendered_record", None)
        current_first = records[0].text if records else None

        def _append_entries(entries, has_existing_content):
            needs_newline = has_existing_content
            for entry in entries:
                if needs_newline:
                    text_widget.insert(tk.END, "\n")
                text_widget.insert(tk.END, entry.text, entry.category)
                needs_newline = True

        try:
            _, view_bottom = text_widget.yview()
        except tk.TclError:
            view_bottom = 1.0
        auto_follow = view_bottom >= 0.999

        need_full_reload = False
        if prev_count > total_records:
            need_full_reload = True
        elif prev_count and total_records and prev_count == total_records and prev_first != current_first:
            need_full_reload = True

        if need_full_reload:
            text_widget.delete("1.0", tk.END)
            prev_count = 0

        if total_records == 0:
            if prev_count:
                text_widget.delete("1.0", tk.END)
            self._log_rendered_count = 0
            self._log_first_rendered_record = None
            return

        if prev_count == total_records:
            return

        if prev_count == 0:
            text_widget.delete("1.0", tk.END)
            _append_entries(records, False)
        else:
            new_records = records[prev_count:]
            if not new_records:
                return
            _append_entries(new_records, prev_count > 0)

        if auto_follow:
            text_widget.yview_moveto(1.0)
            text_widget.xview_moveto(0.0)

        self._log_rendered_count = total_records
        self._log_first_rendered_record = current_first

    def _on_log_text_keypress(self, event):
        """阻止日志窗口被键盘输入修改"""
        control_pressed = bool(event.state & 0x4)
        navigation_keys = {
            "Left", "Right", "Up", "Down", "Home", "End", "Next", "Prior", "Insert"
        }
        if control_pressed:
            key = event.keysym.lower()
            if key in ("c", "a"):
                return None
            if event.keysym in navigation_keys:
                return None
            return "break"
        if event.keysym in navigation_keys:
            return None
        if event.keysym in ("BackSpace", "Delete"):
            return "break"
        if event.char:
            return "break"
        return None

    def _log_popup_info(self, title: str, message: str, **kwargs):
        logging.info(f"[Popup Info] {title} | {message}")
        return messagebox.showinfo(title, message, **kwargs)

    def _log_popup_error(self, title: str, message: str, **kwargs):
        logging.error(f"[Popup Error] {title} | {message}")
        return messagebox.showerror(title, message, **kwargs)

    def _log_popup_confirm(self, title: str, message: str, **kwargs) -> bool:
        logging.info(f"[Popup Confirm] {title} | {message}")
        return messagebox.askyesno(title, message, **kwargs)

    def _is_supported_wjx_url(self, url: str) -> bool:
        if not url:
            return False
        candidate = url.strip()
        parsed = None
        try:
            parsed = urlparse(candidate)
            if not parsed.scheme or not parsed.netloc:
                parsed = urlparse(f"https://{candidate}")
        except Exception:
            return False
        host = (parsed.netloc or "").lower()
        supported_domains = ("wjx.cn", "wjx.top")
        return bool(host) and any(
            host == domain or host.endswith(f".{domain}") for domain in supported_domains
        )

    def _validate_wjx_url(self, url: str) -> bool:
        if not self._is_supported_wjx_url(url):
            self._log_popup_error("链接错误", "当前仅支持 wjx.cn / wjx.top 的问卷链接，请检查后重试。")
            return False
        return True

    def _open_issue_feedback(self):
        message = (
            "将打开浏览器访问 GitHub Issue 页面以反馈问题：\n"
            f"{ISSUE_FEEDBACK_URL}\n\n"
            "提醒：该网站可能在国内访问较慢或需要额外网络配置。\n"
            "是否继续？"
        )
        if not self._log_popup_confirm("问题反馈", message):
            return
        try:
            opened = webbrowser.open(ISSUE_FEEDBACK_URL, new=2, autoraise=True)
            if not opened:
                raise RuntimeError("浏览器未响应")
        except Exception as exc:
            logging.error(f"打开问题反馈链接失败: {exc}")
            self._log_popup_error("打开失败", f"请复制并手动访问：\n{ISSUE_FEEDBACK_URL}\n\n错误: {exc}")


    def _open_qq_group_dialog(self):
        if self._qq_group_window and self._qq_group_window.winfo_exists():
            try:
                self._qq_group_window.deiconify()
                self._qq_group_window.lift()
                self._qq_group_window.focus_force()
            except Exception:
                pass
            return

        qr_image_path = os.path.join(_get_runtime_directory(), QQ_GROUP_QR_RELATIVE_PATH)
        if not os.path.exists(qr_image_path):
            logging.error(f"未找到 QQ 群二维码图片: {qr_image_path}")
            self._log_popup_error("资源缺失", f"没有找到 QQ 群二维码图片：\n{qr_image_path}")
            return

        try:
            with Image.open(qr_image_path) as qr_image:
                display_image = qr_image.copy()
        except Exception as exc:
            logging.error(f"加载 QQ 群二维码失败: {exc}")
            self._log_popup_error("加载失败", f"二维码图片加载失败：\n{exc}")
            return

        max_qr_size = 420
        # 兼容新旧版本的 Pillow
        try:
            from PIL.Image import Resampling
            resample_method = Resampling.LANCZOS
        except (ImportError, AttributeError):
            resample_method = 1  # LANCZOS 的值
        try:
            if display_image.width > max_qr_size or display_image.height > max_qr_size:
                display_image.thumbnail((max_qr_size, max_qr_size), resample=resample_method)  # type: ignore
        except Exception as exc:
            logging.debug(f"调整 QQ 群二维码尺寸失败: {exc}")

        self._qq_group_photo = ImageTk.PhotoImage(display_image)
        self._qq_group_image_path = qr_image_path
        try:
            display_image.close()
        except Exception:
            pass

        window = tk.Toplevel(self.root)
        window.title("加入QQ群")
        window.resizable(False, False)
        window.transient(self.root)
        window.protocol("WM_DELETE_WINDOW", self._close_qq_group_window)

        container = ttk.Frame(window, padding=20)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text="扫描加入官方QQ群\n解决使用过程中的问题，或提出功能建议\n(点击二维码打开原图)").pack(pady=(0, 12))
        qr_label = ttk.Label(container, image=self._qq_group_photo, cursor="hand2")
        qr_label.pack()
        qr_label.bind("<Button-1>", self._show_qq_group_full_image)

        self._qq_group_window = window
        self._center_child_window(window)

    def _close_qq_group_window(self):
        if not self._qq_group_window:
            return
        try:
            if self._qq_group_window.winfo_exists():
                self._qq_group_window.destroy()
        except Exception:
            pass
        finally:
            self._qq_group_window = None
            self._qq_group_photo = None
            self._qq_group_image_path = None

    def _show_qq_group_full_image(self, event=None):
        if not self._qq_group_image_path:
            return
        image_path = self._qq_group_image_path
        try:
            if sys.platform.startswith("win"):
                os.startfile(image_path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", image_path], close_fds=True)
            else:
                subprocess.Popen(["xdg-open", image_path], close_fds=True)
        except Exception as exc:
            logging.error(f"打开 QQ 群二维码原图失败: {exc}")
            self._log_popup_error("打开失败", f"无法打开原图：\n{image_path}\n\n错误: {exc}")

    def _on_root_focus(self, event=None):
        pass

    def _clear_logs_display(self):
        """清空日志显示"""
        # 清空日志缓冲区
        LOG_BUFFER_HANDLER.records.clear()
        # 清空 UI 显示
        if self._log_text_widget:
            self._log_text_widget.delete("1.0", tk.END)
        self._log_rendered_count = 0
        self._log_first_rendered_record = None

    def _schedule_log_refresh(self):
        """定期刷新日志显示"""
        if self._log_refresh_job:
            self.root.after_cancel(self._log_refresh_job)
        
        if self._log_text_widget:
            self._refresh_log_viewer()
        
        # 继续定期刷新
        self._log_refresh_job = self.root.after(500, self._schedule_log_refresh)

    def __init__(self, root: Optional[tk.Tk] = None, loading_splash: Optional[LoadingSplash] = None):
        self._shared_root = root is not None
        self.root = root if root is not None else tk.Tk()
        self._loading_splash = loading_splash
        self._configs_dir = self._get_configs_directory()
        # 在窗口标题中显示当前版本号
        try:
            ver = __VERSION__
        except NameError:
            ver = "0.0.0"
        self.root.title(f"问卷星速填 v{ver}")
        self.root.bind("<FocusIn>", self._on_root_focus)
        self.question_entries: List[QuestionEntry] = []
        self.runner_thread: Optional[Thread] = None
        self.worker_threads: List[Thread] = []
        self.active_drivers: List[WebDriver] = []  # 跟踪活跃的浏览器实例
        self.running = False
        self.status_job = None
        self.update_info = None  # 存储更新信息
        self.progress_value = 0  # 进度值 (0-100)
        self.total_submissions = 0  # 总提交数
        self.current_submissions = 0  # 当前提交数
        self._log_window: Optional[tk.Toplevel] = None
        self._settings_window: Optional[tk.Toplevel] = None
        self._log_text_widget: Optional[tk.Text] = None
        self._log_refresh_job: Optional[str] = None
        self._log_rendered_count = 0
        self._log_first_rendered_record: Optional[str] = None
        self._paned_position_restored = False
        self._default_paned_position_applied = False
        self._paned_configure_binding: Optional[str] = None
        self._qq_group_window: Optional[tk.Toplevel] = None
        self._qq_group_photo: Optional[ImageTk.PhotoImage] = None
        self._qq_group_image_path: Optional[str] = None
        self._config_changed = False  # 跟踪配置是否有改动
        self._initial_config: Dict[str, Any] = {}  # 存储初始配置以便比较
        self._wizard_history: List[int] = []
        self._wizard_commit_log: List[Dict[str, Any]] = []
        self._last_parsed_url: Optional[str] = None
        self._last_questions_info: Optional[List[Dict[str, Any]]] = None
        self._last_survey_title: Optional[str] = None
        self._main_parameter_widgets: List[tk.Widget] = []
        self._settings_window_widgets: List[tk.Widget] = []
        self._full_simulation_window: Optional[tk.Toplevel] = None
        self._full_sim_status_label: Optional[ttk.Label] = None
        self.url_var = tk.StringVar()
        self.target_var = tk.StringVar(value="")
        self.thread_var = tk.StringVar(value="2")
        self.interval_minutes_var = tk.StringVar(value="0")
        self.interval_seconds_var = tk.StringVar(value="0")
        self.interval_max_minutes_var = tk.StringVar(value="0")
        self.interval_max_seconds_var = tk.StringVar(value="0")
        self.answer_duration_min_var = tk.StringVar(value="0")
        self.answer_duration_max_var = tk.StringVar(value="0")
        self.full_simulation_enabled_var = tk.BooleanVar(value=False)
        self.full_sim_target_var = tk.StringVar(value="")
        self.full_sim_estimated_minutes_var = tk.StringVar(value="3")
        self.full_sim_estimated_seconds_var = tk.StringVar(value="0")
        self.full_sim_total_minutes_var = tk.StringVar(value="30")
        self.full_sim_total_seconds_var = tk.StringVar(value="0")
        self._full_simulation_control_widgets: List[tk.Widget] = []
        self.preview_button: Optional[ttk.Button] = None
        self._build_ui()
        if self._loading_splash:
            self._loading_splash.update_progress(90, "主界面加载完成，即将显示...")
        if self._shared_root:
            self.root.deiconify()
        self._center_window()  # 窗口居中显示
        self._check_updates_on_startup()  # 启动时检查更新
        self._schedule_log_refresh()  # 启动日志刷新

    def _build_ui(self):
        self.root.geometry("950x750")
        self.root.resizable(True, True)

        # 创建菜单栏
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="文件", menu=file_menu)
        file_menu.add_command(label="载入配置", command=self._load_config_from_dialog)
        file_menu.add_command(label="保存配置", command=self._save_config_as_dialog)

        menubar.add_command(label="设置", command=self._open_settings_window)

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="帮助", menu=help_menu)
        help_menu.add_command(label="检查更新", command=self.check_for_updates)
        help_menu.add_command(label="问题反馈", command=self._open_issue_feedback)
        help_menu.add_command(label="加入QQ群", command=self._open_qq_group_dialog)
        help_menu.add_separator()
        help_menu.add_command(label="关于", command=self.show_about)

        # 创建主容器，使用 PanedWindow 分左右两部分
        self.main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._paned_configure_binding = self.main_paned.bind("<Configure>", self._on_main_paned_configure)
        
        # 左侧：配置区域（可滚动）
        config_container = ttk.Frame(self.main_paned)
        self.main_paned.add(config_container, weight=3)
        
        # 创建 Canvas 和 Scrollbar 用于整页滚动
        main_canvas = tk.Canvas(config_container, highlightthickness=0, bg="#f0f0f0")
        main_scrollbar = ttk.Scrollbar(config_container, orient="vertical", command=main_canvas.yview)
        
        # 创建可滚动的内容框架
        self.scrollable_content = ttk.Frame(main_canvas)
        
        # 创建窗口
        canvas_frame = main_canvas.create_window((0, 0), window=self.scrollable_content, anchor="nw")
        
        # 配置 scrollregion - 立即设置，避免空白
        def _update_scrollregion():
            self.scrollable_content.update_idletasks()
            main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        
        self.scrollable_content.bind("<Configure>", lambda e: _update_scrollregion())
        
        # 当 Canvas 大小改变时，调整内容宽度
        def _on_canvas_configure(event):
            if event.width > 1:
                main_canvas.itemconfig(canvas_frame, width=event.width)
        
        main_canvas.bind("<Configure>", _on_canvas_configure)
        main_canvas.configure(yscrollcommand=main_scrollbar.set)
        
        # 布局 Canvas 和 Scrollbar
        main_canvas.pack(side="left", fill="both", expand=True)
        main_scrollbar.pack(side="right", fill="y")
        
        # 绑定鼠标滚轮事件（仅在鼠标在主窗口时）
        def _on_mousewheel(event):
            # 阻止向上滚动超出顶部
            if event.delta > 0 and main_canvas.yview()[0] <= 0:
                return
            main_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        def _bind_mousewheel(event):
            main_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_mousewheel(event):
            main_canvas.unbind_all("<MouseWheel>")

        # 仅在配置区域获得焦点时启用滚轮
        main_canvas.bind("<Enter>", _bind_mousewheel)
        main_canvas.bind("<Leave>", _unbind_mousewheel)
        
        # 保存引用以便后续使用
        self.main_canvas = main_canvas
        self.main_scrollbar = main_scrollbar

        # 右侧：日志区域
        log_container = ttk.LabelFrame(self.main_paned, text="📋 运行日志", padding=5)
        self.main_paned.add(log_container, weight=2)
        
        # 创建日志显示区域（带水平和垂直滚动条）
        # 使用 Frame 包装 Text 和滚动条
        log_frame = ttk.Frame(log_container)
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建垂直滚动条
        v_scrollbar = ttk.Scrollbar(log_frame, orient="vertical")
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 创建水平滚动条
        h_scrollbar = ttk.Scrollbar(log_frame, orient="horizontal")
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # 创建 Text Widget
        self._log_text_widget = tk.Text(
            log_frame,
            wrap=tk.NONE,
            state="normal",
            yscrollcommand=v_scrollbar.set,
            xscrollcommand=h_scrollbar.set
        )
        default_log_color = self._log_text_widget.cget("fg") or "#000000"
        self._log_text_widget.tag_configure("INFO", foreground=default_log_color)
        self._log_text_widget.tag_configure("OK", foreground="#2e7d32")
        self._log_text_widget.tag_configure("WARNING", foreground="#f5a623")
        self._log_text_widget.tag_configure("ERROR", foreground="#d32f2f")
        self._log_text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._log_text_widget.bind("<Key>", self._on_log_text_keypress)
        for sequence in ("<<Paste>>", "<<Cut>>", "<<Clear>>"):
            self._log_text_widget.bind(sequence, lambda e: "break")
        
        # 配置滚动条
        v_scrollbar.config(command=self._log_text_widget.yview)
        h_scrollbar.config(command=self._log_text_widget.xview)
        
        # 日志按钮区域
        log_button_frame = ttk.Frame(log_container)
        log_button_frame.pack(fill=tk.X, padx=0, pady=(5, 0))
        
        ttk.Button(log_button_frame, text="保存日志文件", command=self._save_logs_to_file).pack(side=tk.RIGHT, padx=2)
        ttk.Button(log_button_frame, text="清空日志", command=self._clear_logs_display).pack(side=tk.RIGHT, padx=2)

        # 问卷链接输入区域
        step1_frame = ttk.LabelFrame(self.scrollable_content, text="🔗 问卷链接", padding=10)
        step1_frame.pack(fill=tk.X, padx=10, pady=5)

        link_frame = ttk.Frame(step1_frame)
        link_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(link_frame, text="问卷链接：").pack(side=tk.LEFT, padx=(0, 5))
        self.url_var.trace("w", lambda *args: self._mark_config_changed())
        url_entry = ttk.Entry(link_frame, textvariable=self.url_var, width=50)
        url_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        qr_frame = ttk.Frame(step1_frame)
        qr_frame.pack(fill=tk.X, pady=(0, 5))
        qr_upload_button = ttk.Button(
            qr_frame,
            text="📂上传问卷二维码图片",
            command=self.upload_qrcode,
            width=24,
            style="Accent.TButton"
        )
        qr_upload_button.pack(side=tk.LEFT, padx=5, pady=5, ipady=2)

        # 配置题目区域
        step2_frame = ttk.LabelFrame(self.scrollable_content, text="⚙️ 配置题目", padding=10)
        step2_frame.pack(fill=tk.X, padx=10, pady=5)

        auto_config_frame = ttk.Frame(step2_frame)
        auto_config_frame.pack(fill=tk.X, pady=(0, 5))

        button_row = ttk.Frame(auto_config_frame)
        button_row.pack(fill=tk.X)
        self.preview_button = ttk.Button(
            button_row,
            text="⚡ 自动配置问卷",
            command=self.preview_survey,
            style="Accent.TButton"
        )
        self.preview_button.pack(side=tk.LEFT, padx=5)

        auto_hint_frame = ttk.Frame(step2_frame)
        auto_hint_frame.pack(fill=tk.X, pady=(0, 10))
        auto_hint_box = tk.Frame(auto_hint_frame, bg="#edf7ec", bd=1, relief="solid")
        auto_hint_box.pack(fill=tk.X, expand=True, padx=4, pady=2)
        self._auto_hint_label = ttk.Label(
            auto_hint_box,
            text="  💡通过配置向导可快速预设答案并保持原始题型结构",
            foreground="#1b5e20",
            font=("Segoe UI", 9),
            wraplength=520,
            justify="left"
        )
        self._auto_hint_label.pack(anchor="w", padx=8, pady=6)
        auto_hint_frame.bind("<Configure>", lambda e: self._auto_hint_label.configure(wraplength=max(180, e.width - 30)))

        # 执行设置区域（放在配置题目下方）
        step3_frame = ttk.LabelFrame(self.scrollable_content, text="⚙️ 执行设置", padding=10)
        step3_frame.pack(fill=tk.X, padx=10, pady=5)

        settings_grid = ttk.Frame(step3_frame)
        settings_grid.pack(fill=tk.X)
        settings_grid.columnconfigure(1, weight=1)
        
        ttk.Label(settings_grid, text="目标份数：").grid(row=0, column=0, sticky="w", padx=5)
        self.target_var.trace("w", lambda *args: self._mark_config_changed())
        target_entry = ttk.Entry(settings_grid, textvariable=self.target_var, width=10)
        target_entry.grid(row=0, column=1, sticky="w", padx=5)
        self._main_parameter_widgets.append(target_entry)

        ttk.Label(
            settings_grid,
            text="线程数（浏览器并发数量）：",
            wraplength=220,
            justify="left"
        ).grid(row=1, column=0, sticky="w", padx=5, pady=(8, 0))
        self.thread_var.trace("w", lambda *args: self._mark_config_changed())
        self.interval_minutes_var.trace("w", lambda *args: self._mark_config_changed())
        self.interval_seconds_var.trace("w", lambda *args: self._mark_config_changed())
        self.interval_max_minutes_var.trace("w", lambda *args: self._mark_config_changed())
        self.interval_max_seconds_var.trace("w", lambda *args: self._mark_config_changed())
        self.answer_duration_min_var.trace("w", lambda *args: self._mark_config_changed())
        self.answer_duration_max_var.trace("w", lambda *args: self._mark_config_changed())
        self.full_sim_target_var.trace("w", lambda *args: self._mark_config_changed())
        self.full_sim_target_var.trace_add("write", lambda *args: self._sync_full_sim_target_to_main())
        self.full_sim_estimated_minutes_var.trace("w", lambda *args: self._mark_config_changed())
        self.full_sim_estimated_seconds_var.trace("w", lambda *args: self._mark_config_changed())
        self.full_sim_total_minutes_var.trace("w", lambda *args: self._mark_config_changed())
        self.full_sim_total_seconds_var.trace("w", lambda *args: self._mark_config_changed())
        self.full_simulation_enabled_var.trace_add("write", lambda *args: self._on_full_simulation_toggle())

        def adjust_thread_count(delta: int) -> None:
            try:
                current = int(self.thread_var.get())
            except ValueError:
                current = 1
            new_value = max(1, current + delta)
            self.thread_var.set(str(new_value))
            self._mark_config_changed()

        thread_control_frame = ttk.Frame(settings_grid)
        thread_control_frame.grid(row=1, column=1, sticky="w", padx=5, pady=(8, 0))
        thread_dec_button = ttk.Button(
            thread_control_frame,
            text="−",
            width=2,
            command=lambda: adjust_thread_count(-1)
        )
        thread_dec_button.grid(row=0, column=0, padx=(0, 2))
        thread_entry = ttk.Entry(thread_control_frame, textvariable=self.thread_var, width=5)
        thread_entry.grid(row=0, column=1, padx=2)
        thread_inc_button = ttk.Button(
            thread_control_frame,
            text="＋",
            width=2,
            command=lambda: adjust_thread_count(1)
        )
        thread_inc_button.grid(row=0, column=2, padx=(2, 0))
        self._main_parameter_widgets.extend([thread_dec_button, thread_entry, thread_inc_button])

        
        # 高级选项：手动配置（始终显示）
        self.manual_config_frame = ttk.LabelFrame(self.scrollable_content, text="🔧 高级选项", padding=10)
        self.manual_config_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 按钮区域（放在这个 LabelFrame 中）
        btn_frame = ttk.Frame(self.manual_config_frame)
        btn_frame.pack(fill=tk.X, pady=5)
        
        # 全选复选框
        self.select_all_var = tk.BooleanVar(value=False)
        self.select_all_check = ttk.Checkbutton(
            btn_frame, 
            text="全选",
            variable=self.select_all_var,
            command=self.toggle_select_all
        )
        self.select_all_check.grid(row=0, column=0, padx=5)
        
        ttk.Button(btn_frame, text="手动添加配置", command=self.add_question_dialog).grid(
            row=0, column=1, padx=5
        )
        ttk.Button(btn_frame, text="编辑选中", command=self.edit_question).grid(
            row=0, column=2, padx=5
        )
        ttk.Button(btn_frame, text="删除选中", command=self.remove_question).grid(
            row=0, column=3, padx=5
        )
        
        # 提示信息（放在按钮下，避免被树状控件遮挡）
        info_frame = ttk.Frame(self.manual_config_frame)
        info_frame.pack(fill=tk.X, padx=5, pady=(0, 6))
        manual_hint_box = tk.Frame(info_frame, bg="#eef2fb", bd=1, relief="solid")
        manual_hint_box.pack(fill=tk.X, expand=True, padx=4, pady=2)
        self._manual_hint_label = ttk.Label(
            manual_hint_box, 
            text="  💡提示：排序题/滑块题会自动随机填写",
            foreground="#0f3d7a",
            font=("Segoe UI", 9),
            wraplength=520,
            justify="left"
        )
        self._manual_hint_label.pack(anchor="w", padx=8, pady=6)
        info_frame.bind("<Configure>", lambda e: self._manual_hint_label.configure(wraplength=max(180, e.width - 30)))

        # 分隔符
        ttk.Separator(self.manual_config_frame, orient='horizontal').pack(fill=tk.X, pady=(0, 5))

        # 题目列表区域（放在最后）
        question_list_frame = ttk.LabelFrame(self.scrollable_content, text="📝 已配置的题目", padding=10)
        question_list_frame.pack(fill=tk.X, padx=10, pady=5)
        self.question_list_frame = question_list_frame
        
        tree_frame = ttk.Frame(question_list_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建带滚动条的Canvas（限制高度）
        canvas = tk.Canvas(tree_frame, highlightthickness=0, height=200)
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self.questions_canvas = canvas
        self.questions_frame = scrollable_frame
        self.question_items = []

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # 执行按钮区域（固定在窗口底部，不参与滚动）
        action_frame = ttk.Frame(self.root, padding=10)
        action_frame.pack(fill=tk.X, side=tk.BOTTOM)

        # 进度条区域（在上面）
        progress_frame = ttk.Frame(action_frame)
        progress_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(progress_frame, text="执行进度:", font=("TkDefaultFont", 9)).pack(side=tk.LEFT, padx=(0, 5))
        
        self.progress_bar = ttk.Progressbar(
            progress_frame, 
            mode='determinate', 
            maximum=100,
            length=300
        )
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        self.progress_label = ttk.Label(progress_frame, text="0%", width=5, font=("TkDefaultFont", 9))
        self.progress_label.pack(side=tk.LEFT, padx=5)
        
        # 按钮行（在下面）
        button_frame = ttk.Frame(action_frame)
        button_frame.pack(fill=tk.X)
        
        self.start_button = ttk.Button(
            button_frame, 
            text="开始执行", 
            command=self.start_run,
            style="Accent.TButton"
        )
        self.start_button.pack(side=tk.LEFT, padx=5)
        self.stop_button = ttk.Button(button_frame, text="🚫 停止", command=self.stop_run, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)

        self.status_var = tk.StringVar(value="等待配置...")
        status_label = ttk.Label(button_frame, textvariable=self.status_var)
        status_label.pack(side=tk.LEFT, padx=10)
        
        self._load_config()
        self._update_full_simulation_controls_state()
        self._update_parameter_widgets_state()
        self.root.after(200, self._ensure_default_paned_position)

    def _notify_loading(self, message: str):
        if self._loading_splash:
            self._loading_splash.update_message(message)

    def _on_main_paned_configure(self, event):
        width = getattr(event, "width", 0) or self.main_paned.winfo_width()
        if width <= 0:
            return
        if not self._paned_position_restored and not self._default_paned_position_applied:
            desired = max(PANED_MIN_LEFT_WIDTH, width // 2)
            try:
                self.main_paned.sashpos(0, desired)
                self._default_paned_position_applied = True
            except tk.TclError:
                self.root.after(150, self._ensure_default_paned_position)
        self._enforce_paned_minimums()

    def _ensure_default_paned_position(self):
        if self._paned_position_restored or self._default_paned_position_applied:
            return
        pane_width = self.main_paned.winfo_width() or self.root.winfo_width()
        if pane_width <= 0:
            self.root.after(100, self._ensure_default_paned_position)
            return
        desired = max(320, pane_width // 2)
        try:
            self.main_paned.sashpos(0, desired)
            self._default_paned_position_applied = True
        except Exception:
            self.root.after(150, self._ensure_default_paned_position)
        self._enforce_paned_minimums()

    def _enforce_paned_minimums(self):
        try:
            width = self.main_paned.winfo_width()
            if width <= 0:
                return
            sash_pos = self.main_paned.sashpos(0)
        except Exception:
            return
        min_left = PANED_MIN_LEFT_WIDTH
        min_right = PANED_MIN_RIGHT_WIDTH
        max_allowed = max(min_left, width - min_right)
        max_allowed = min(max_allowed, width - 1)
        max_allowed = max(0, max_allowed)
        min_target = min(min_left, max(0, width - 1))
        desired = min(max_allowed, max(min_target, sash_pos))
        if desired != sash_pos:
            try:
                self.main_paned.sashpos(0, desired)
            except Exception:
                pass

    def _update_full_simulation_controls_state(self):
        state = tk.NORMAL if self.full_simulation_enabled_var.get() else tk.DISABLED
        cleaned: List[tk.Widget] = []
        for widget in getattr(self, "_full_simulation_control_widgets", []):
            if widget is None:
                continue
            try:
                if widget.winfo_exists():
                    widget.configure(state=state)
                    cleaned.append(widget)
            except Exception:
                try:
                    if widget.winfo_exists():
                        widget["state"] = state
                        cleaned.append(widget)
                except Exception:
                    continue
        self._full_simulation_control_widgets = cleaned

    def _update_parameter_widgets_state(self):
        state = tk.DISABLED if self.full_simulation_enabled_var.get() else tk.NORMAL
        targets = [w for w in getattr(self, '_main_parameter_widgets', []) if w is not None]
        targets += [w for w in getattr(self, '_settings_window_widgets', []) if w is not None]
        for widget in targets:
            try:
                if widget.winfo_exists():
                    widget.configure(state=state)
            except Exception:
                try:
                    if widget.winfo_exists():
                        widget["state"] = state
                except Exception:
                    continue

    def _refresh_full_simulation_status_label(self):
        label = getattr(self, '_full_sim_status_label', None)
        if not label or not label.winfo_exists():
            return
        enabled = bool(self.full_simulation_enabled_var.get())
        status_text = "已开启" if enabled else "未开启"
        color = "#2e7d32" if enabled else "#616161"
        label.config(text=f"当前状态：{status_text}", foreground=color)

    def _sync_full_sim_target_to_main(self):
        if not self.full_simulation_enabled_var.get():
            return
        target_value = self.full_sim_target_var.get().strip()
        if target_value:
            self.target_var.set(target_value)

    def _on_full_simulation_toggle(self, *args):
        if self.full_simulation_enabled_var.get() and not self.full_sim_target_var.get().strip():
            current_target = self.target_var.get().strip()
            if current_target:
                self.full_sim_target_var.set(current_target)
        self._sync_full_sim_target_to_main()
        self._update_full_simulation_controls_state()
        self._update_parameter_widgets_state()
        self._refresh_full_simulation_status_label()
        self._mark_config_changed()

    def _restore_saved_paned_position(self, target_position: int, attempts: int = 5, delay_ms: int = 120) -> None:
        """
        多次尝试恢复保存的分隔线位置，避免布局未稳定时被默认值覆盖。
        """

        def _attempt(remaining: int):
            if remaining <= 0:
                return
            try:
                width = self.main_paned.winfo_width()
                if width <= 0:
                    raise RuntimeError("paned window width is zero")
                max_allowed = max(PANED_MIN_LEFT_WIDTH, width - PANED_MIN_RIGHT_WIDTH)
                max_allowed = min(max_allowed, width - 1)
                max_allowed = max(0, max_allowed)
                adjusted = min(max_allowed, max(PANED_MIN_LEFT_WIDTH, target_position))
                self.main_paned.sashpos(0, adjusted)
                self._paned_position_restored = True
            except Exception:
                pass
            finally:
                if remaining - 1 > 0:
                    self.root.after(delay_ms, lambda: _attempt(remaining - 1))

        self.root.after(0, lambda: _attempt(max(1, attempts)))


    def _open_settings_window(self):
        existing = getattr(self, "_settings_window", None)
        if existing:
            try:
                if existing.winfo_exists():
                    existing.lift()
                    existing.focus_force()
                    self._center_child_window(existing)
                    return
                else:
                    self._settings_window = None
            except tk.TclError:
                self._settings_window = None

        window = tk.Toplevel(self.root)
        window.title("设置")
        window.resizable(False, False)
        window.transient(self.root)
        self._settings_window = window
        self._settings_window_widgets = []
        self._full_sim_status_label = None

        def _on_close():
            if self._settings_window is window:
                self._settings_window = None
                self._settings_window_widgets = []
                self._full_sim_status_label = None
            try:
                window.destroy()
            except Exception:
                pass

        window.protocol("WM_DELETE_WINDOW", _on_close)

        content = ttk.Frame(window, padding=20)
        content.pack(fill=tk.BOTH, expand=True)

        header_frame = ttk.Frame(content)
        header_frame.pack(fill=tk.X, pady=(0, 12))
        ttk.Button(
            header_frame,
            text="全真模拟设置",
            command=self._open_full_simulation_window,
            style="Accent.TButton"
        ).pack(side=tk.LEFT)
        status_label = ttk.Label(header_frame, text="当前状态：未开启", foreground="#616161")
        status_label.pack(side=tk.LEFT, padx=(12, 0))
        self._full_sim_status_label = status_label
        self._refresh_full_simulation_status_label()

        interval_frame = ttk.LabelFrame(content, text="提交间隔", padding=15)
        interval_frame.pack(fill=tk.X)
        ttk.Label(
            interval_frame,
            text="设置每次自动提交后的等待范围，可模拟更加自然的提交节奏；设置为 0 表示不延迟。",
            wraplength=320,
            justify="left",
        ).pack(anchor="w")

        input_frame = ttk.Frame(interval_frame)
        input_frame.pack(anchor="w", pady=(12, 0))
        ttk.Label(input_frame, text="最短等待").grid(row=0, column=0, sticky="w")
        interval_min_entry = ttk.Entry(input_frame, textvariable=self.interval_minutes_var, width=6)
        interval_min_entry.grid(row=0, column=1, padx=(6, 0))
        self._settings_window_widgets.append(interval_min_entry)
        ttk.Label(input_frame, text="分").grid(row=0, column=2, padx=(4, 6))
        interval_sec_entry = ttk.Entry(input_frame, textvariable=self.interval_seconds_var, width=6)
        interval_sec_entry.grid(row=0, column=3)
        self._settings_window_widgets.append(interval_sec_entry)
        ttk.Label(input_frame, text="秒").grid(row=0, column=4, padx=(4, 10))

        ttk.Label(input_frame, text="最长等待").grid(row=1, column=0, sticky="w", pady=(10, 0))
        interval_max_min_entry = ttk.Entry(input_frame, textvariable=self.interval_max_minutes_var, width=6)
        interval_max_min_entry.grid(row=1, column=1, padx=(6, 0), pady=(10, 0))
        self._settings_window_widgets.append(interval_max_min_entry)
        ttk.Label(input_frame, text="分").grid(row=1, column=2, padx=(4, 6), pady=(10, 0))
        interval_max_sec_entry = ttk.Entry(input_frame, textvariable=self.interval_max_seconds_var, width=6)
        interval_max_sec_entry.grid(row=1, column=3, pady=(10, 0))
        self._settings_window_widgets.append(interval_max_sec_entry)
        ttk.Label(input_frame, text="秒").grid(row=1, column=4, padx=(4, 10), pady=(10, 0))

        ttk.Label(input_frame, text="最长等待会被自动取不小于最短等待的数值。").grid(row=2, column=0, columnspan=5, sticky="w", pady=(12, 0))

        answer_frame = ttk.LabelFrame(content, text="作答时长", padding=15)
        answer_frame.pack(fill=tk.X, pady=(15, 0))
        ttk.Label(
            answer_frame,
            text="每份问卷在提交前会停留一段时间以模拟真人作答，具体秒数会在设定范围内随机选择。",
            wraplength=320,
            justify="left",
        ).pack(anchor="w")

        answer_range_frame = ttk.Frame(answer_frame)
        answer_range_frame.pack(anchor="w", pady=(12, 0))
        ttk.Label(answer_range_frame, text="最短停留").grid(row=0, column=0, sticky="w")
        answer_min_entry = ttk.Entry(answer_range_frame, textvariable=self.answer_duration_min_var, width=8)
        answer_min_entry.grid(row=0, column=1, padx=(4, 6))
        self._settings_window_widgets.append(answer_min_entry)
        ttk.Label(answer_range_frame, text="秒").grid(row=0, column=2, sticky="w")
        ttk.Label(answer_range_frame, text="最长停留").grid(row=1, column=0, sticky="w", pady=(8, 0))
        answer_max_entry = ttk.Entry(answer_range_frame, textvariable=self.answer_duration_max_var, width=8)
        answer_max_entry.grid(row=1, column=1, padx=(4, 6), pady=(8, 0))
        self._settings_window_widgets.append(answer_max_entry)
        ttk.Label(answer_range_frame, text="秒").grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Label(answer_range_frame, text="（设为 0 表示不等待）").grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))

        button_frame = ttk.Frame(content)
        button_frame.pack(fill=tk.X, pady=(18, 0))
        ttk.Button(button_frame, text="关闭", command=_on_close, width=10).pack(anchor="e")

        self._update_parameter_widgets_state()
        window.update_idletasks()
        self._center_child_window(window)
        window.lift()
        window.focus_force()


    def _open_full_simulation_window(self):
        existing = getattr(self, "_full_simulation_window", None)
        if existing:
            try:
                if existing.winfo_exists():
                    existing.lift()
                    existing.focus_force()
                    self._center_child_window(existing)
                    return
                else:
                    self._full_simulation_window = None
            except tk.TclError:
                self._full_simulation_window = None

        window = tk.Toplevel(self.root)
        window.title("全真模拟设置")
        window.resizable(False, False)
        window.transient(self.root)
        self._full_simulation_window = window

        def _on_close():
            if self._full_simulation_window is window:
                self._full_simulation_window = None
                self._full_simulation_control_widgets = []
            try:
                window.destroy()
            except Exception:
                pass

        window.protocol("WM_DELETE_WINDOW", _on_close)

        container = ttk.Frame(window, padding=20)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            container,
            text="在特定时段内按照真实考试节奏自动填答与提交。",
            wraplength=360,
            justify="left"
        ).pack(anchor="w")

        ttk.Checkbutton(
            container,
            text="启用全真模拟（任务会被节奏管控，仅允许单线程执行）",
            variable=self.full_simulation_enabled_var
        ).pack(anchor="w", pady=(8, 6))

        if not self.full_sim_target_var.get().strip():
            current_target = self.target_var.get().strip()
            if current_target:
                self.full_sim_target_var.set(current_target)

        target_frame = ttk.Frame(container)
        target_frame.pack(fill=tk.X, pady=(4, 6))
        ttk.Label(target_frame, text="目标份数：").grid(row=0, column=0, sticky="w")
        target_entry = ttk.Entry(target_frame, textvariable=self.full_sim_target_var, width=10)
        target_entry.grid(row=0, column=1, padx=(6, 0))
        ttk.Label(target_frame, text="（覆盖主面板的目标设置）", foreground="#616161").grid(row=0, column=2, padx=(8, 0), sticky="w")

        timing_frame = ttk.LabelFrame(container, text="时间参数", padding=12)
        timing_frame.pack(fill=tk.X, pady=(4, 0))

        ttk.Label(timing_frame, text="预计单次作答").grid(row=0, column=0, sticky="w")
        est_min_entry = ttk.Entry(timing_frame, textvariable=self.full_sim_estimated_minutes_var, width=6)
        est_min_entry.grid(row=0, column=1, padx=(8, 4))
        ttk.Label(timing_frame, text="分").grid(row=0, column=2, padx=(0, 8))
        est_sec_entry = ttk.Entry(timing_frame, textvariable=self.full_sim_estimated_seconds_var, width=6)
        est_sec_entry.grid(row=0, column=3, padx=(0, 4))
        ttk.Label(timing_frame, text="秒").grid(row=0, column=4, padx=(0, 12))

        ttk.Label(timing_frame, text="模拟总时长").grid(row=1, column=0, sticky="w", pady=(10, 0))
        total_min_entry = ttk.Entry(timing_frame, textvariable=self.full_sim_total_minutes_var, width=6)
        total_min_entry.grid(row=1, column=1, padx=(8, 4), pady=(10, 0))
        ttk.Label(timing_frame, text="分").grid(row=1, column=2, padx=(0, 8), pady=(10, 0))
        total_sec_entry = ttk.Entry(timing_frame, textvariable=self.full_sim_total_seconds_var, width=6)
        total_sec_entry.grid(row=1, column=3, padx=(0, 4), pady=(10, 0))
        ttk.Label(timing_frame, text="秒").grid(row=1, column=4, padx=(0, 12), pady=(10, 0))

        ttk.Label(
            container,
            text="启动后所有执行参数全部锁定，仅使用本窗口中的设置。",
            foreground="#d84315",
            wraplength=360,
            justify="left"
        ).pack(anchor="w", pady=(10, 0))

        action_frame = ttk.Frame(container)
        action_frame.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(action_frame, text="完成", command=_on_close, width=10).pack(side=tk.RIGHT)

        self._full_simulation_control_widgets = [
            target_entry,
            est_min_entry,
            est_sec_entry,
            total_min_entry,
            total_sec_entry,
        ]
        self._update_full_simulation_controls_state()
        self._refresh_full_simulation_status_label()
        self._update_parameter_widgets_state()

        window.update_idletasks()
        self._center_child_window(window)
        window.lift()
        window.focus_force()

    def add_question_dialog(self):
        """弹出对话框来添加新的题目配置"""
        dialog = tk.Toplevel(self.root)
        dialog.title("添加题目配置")
        dialog.geometry("650x550")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 创建可滚动的内容区域
        main_canvas = tk.Canvas(dialog, highlightthickness=0)
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=main_canvas.yview)
        main_frame = ttk.Frame(main_canvas, padding=15)
        
        main_frame.bind(
            "<Configure>",
            lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        )
        
        main_canvas.create_window((0, 0), window=main_frame, anchor="nw")
        main_canvas.configure(yscrollcommand=scrollbar.set)
        
        main_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 绑定鼠标滚轮到对话框
        def _on_mousewheel(event):
            # 检查鼠标是否在canvas上方，如果是则处理滚轮事件
            if main_canvas.winfo_containing(event.x_root, event.y_root) == main_canvas:
                main_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        dialog.bind("<MouseWheel>", _on_mousewheel)
        
        def _cleanup():
            dialog.unbind("<MouseWheel>")
            dialog.destroy()
        
        dialog.protocol("WM_DELETE_WINDOW", _cleanup)
        
        # ===== 题型选择 =====
        ttk.Label(main_frame, text="题型：", font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, sticky="w", pady=8, padx=(0, 10))
        question_type_var = tk.StringVar(value=TYPE_OPTIONS[0][1])
        question_type_combo = ttk.Combobox(
            main_frame,
            textvariable=question_type_var,
            state="readonly",
            values=[item[1] for item in TYPE_OPTIONS],
            width=30,
        )
        question_type_combo.grid(row=0, column=1, sticky="w", pady=8)
        
        # 创建一个容器用于动态内容
        dynamic_frame = ttk.Frame(main_frame)
        dynamic_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=10)
        main_frame.rowconfigure(1, weight=1)
        
        # 保存状态变量
        state: Dict[str, Any] = {
            'option_count_var': None,
            'matrix_rows_var': None,
            'distribution_var': None,
            'weights_var': None,
            'multiple_random_var': None,
            'answer_vars': None,
            'weight_frame': None,
            'current_sliders': None,
        }
        
        def refresh_dynamic_content(*args):
            """根据选择的题型刷新动态内容"""
            # 清空动态框
            for child in dynamic_frame.winfo_children():
                child.destroy()
            
            q_type = LABEL_TO_TYPE.get(question_type_var.get(), "single")
            
            if q_type == "text":
                # ===== 填空题 =====
                ttk.Label(dynamic_frame, text="填空答案列表：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=5, fill=tk.X)
                
                answer_frame = ttk.Frame(dynamic_frame)
                answer_frame.pack(fill=tk.BOTH, expand=True, pady=5)
                
                state['answer_vars'] = []  # type: ignore
                
                def add_answer_field(initial_value=""):
                    row_frame = ttk.Frame(answer_frame)
                    row_frame.pack(fill=tk.X, pady=3, padx=5)
                    
                    ttk.Label(row_frame, text=f"答案{len(state['answer_vars'])+1}:", width=8).pack(side=tk.LEFT)  # type: ignore
                    
                    var = tk.StringVar(value=initial_value)
                    entry_widget = ttk.Entry(row_frame, textvariable=var, width=35)
                    entry_widget.pack(side=tk.LEFT, padx=5)
                    
                    def remove_field():
                        row_frame.destroy()
                        state['answer_vars'].remove(var)  # type: ignore
                        update_labels()
                    
                    if len(state['answer_vars']) > 0:  # type: ignore
                        ttk.Button(row_frame, text="✖", width=3, command=remove_field).pack(side=tk.LEFT)
                    
                    state['answer_vars'].append(var)  # type: ignore
                    return var
                
                def update_labels():
                    for i, child in enumerate(answer_frame.winfo_children()):
                        if child.winfo_children():
                            label = child.winfo_children()[0]
                            if isinstance(label, ttk.Label):
                                label.config(text=f"答案{i+1}:")
                
                add_answer_field("默认答案")
                
                add_btn_frame = ttk.Frame(dynamic_frame)
                add_btn_frame.pack(fill=tk.X, pady=(5, 0))
                ttk.Button(add_btn_frame, text="➕ 添加答案", command=lambda: add_answer_field()).pack(anchor="w")
                
            elif q_type == "multiple":
                # ===== 多选题 =====
                option_control_frame = ttk.Frame(dynamic_frame)
                option_control_frame.pack(fill=tk.X, pady=5)
                
                ttk.Label(option_control_frame, text="选项个数：", font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, padx=(0, 5))
                
                state['option_count_var'] = tk.StringVar(value="4")
                
                def update_option_count(delta):
                    try:
                        current = int(state['option_count_var'].get())
                        new_count = max(1, current + delta)
                        state['option_count_var'].set(str(new_count))
                        refresh_sliders()
                    except ValueError:
                        pass
                
                ttk.Button(option_control_frame, text="➖", width=3, command=lambda: update_option_count(-1)).pack(side=tk.LEFT, padx=2)
                ttk.Entry(option_control_frame, textvariable=state['option_count_var'], width=5).pack(side=tk.LEFT, padx=2)
                ttk.Button(option_control_frame, text="➕", width=3, command=lambda: update_option_count(1)).pack(side=tk.LEFT, padx=2)
                
                # 多选方式
                ttk.Label(dynamic_frame, text="多选方式：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(10, 5), fill=tk.X)
                
                state['multiple_random_var'] = tk.BooleanVar(value=False)  # type: ignore
                ttk.Checkbutton(
                    dynamic_frame, 
                    text="完全随机选择若干项",
                    variable=state['multiple_random_var']  # type: ignore
                ).pack(anchor="w", pady=3, fill=tk.X)
                
                # 概率设置
                ttk.Label(dynamic_frame, text="选项选中概率（0-100%）：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(10, 5), fill=tk.X)
                
                sliders_frame = ttk.Frame(dynamic_frame)
                sliders_frame.pack(fill=tk.BOTH, expand=True, pady=5)
                
                state['current_sliders'] = []  # type: ignore
                
                def refresh_sliders():
                    for child in sliders_frame.winfo_children():
                        child.destroy()
                    state['current_sliders'] = []  # type: ignore
                    
                    try:
                        option_count = int(state['option_count_var'].get())  # type: ignore
                    except:
                        option_count = 4
                    
                    for i in range(option_count):
                        row_frame = ttk.Frame(sliders_frame)
                        row_frame.pack(fill=tk.X, pady=3, padx=(10, 10))
                        row_frame.columnconfigure(1, weight=1)
                        
                        var = tk.DoubleVar(value=50.0)
                        
                        label_text = ttk.Label(row_frame, text=f"选项 {i+1}:", width=8, anchor="w")
                        label_text.grid(row=0, column=0, sticky="w")
                        
                        slider = ttk.Scale(row_frame, from_=0, to=100, variable=var, orient=tk.HORIZONTAL)
                        slider.grid(row=0, column=1, sticky="ew", padx=5)
                        
                        percent_label = ttk.Label(row_frame, text="50%", width=6, anchor="e")
                        percent_label.grid(row=0, column=2, sticky="e")
                        
                        var.trace_add("write", lambda *args, l=percent_label, v=var: l.config(text=f"{int(v.get())}%"))
                        state['current_sliders'].append(var)  # type: ignore
                
                refresh_sliders()
                state['option_count_var'].trace_add("write", lambda *args: refresh_sliders())  # type: ignore
                
            elif q_type == "matrix":
                # ===== 矩阵题 =====
                option_control_frame = ttk.Frame(dynamic_frame)
                option_control_frame.pack(fill=tk.X, pady=5)
                
                ttk.Label(option_control_frame, text="选项个数（列）：", font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, padx=(0, 5))
                
                state['option_count_var'] = tk.StringVar(value="4")  # type: ignore
                
                def update_option_count(delta):
                    try:
                        current = int(state['option_count_var'].get())  # type: ignore
                        new_count = max(1, current + delta)
                        state['option_count_var'].set(str(new_count))  # type: ignore
                        refresh_matrix_sliders()
                    except ValueError:
                        pass
                
                ttk.Button(option_control_frame, text="➖", width=3, command=lambda: update_option_count(-1)).pack(side=tk.LEFT, padx=2)
                ttk.Entry(option_control_frame, textvariable=state['option_count_var'], width=5).pack(side=tk.LEFT, padx=2)  # type: ignore
                ttk.Button(option_control_frame, text="➕", width=3, command=lambda: update_option_count(1)).pack(side=tk.LEFT, padx=2)
                
                # 矩阵行数
                matrix_row_frame = ttk.Frame(dynamic_frame)
                matrix_row_frame.pack(fill=tk.X, pady=5)
                
                ttk.Label(matrix_row_frame, text="矩阵行数：", font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, padx=(0, 5))
                
                state['matrix_rows_var'] = tk.StringVar(value="3")  # type: ignore
                
                def update_matrix_rows(delta):
                    try:
                        current = int(state['matrix_rows_var'].get())  # type: ignore
                        new_count = max(1, current + delta)
                        state['matrix_rows_var'].set(str(new_count))  # type: ignore
                    except ValueError:
                        pass
                
                ttk.Button(matrix_row_frame, text="➖", width=3, command=lambda: update_matrix_rows(-1)).pack(side=tk.LEFT, padx=2)
                ttk.Entry(matrix_row_frame, textvariable=state['matrix_rows_var'], width=5).pack(side=tk.LEFT, padx=2)  # type: ignore
                ttk.Button(matrix_row_frame, text="➕", width=3, command=lambda: update_matrix_rows(1)).pack(side=tk.LEFT, padx=2)
                
                # 分布方式
                ttk.Label(dynamic_frame, text="选择分布方式：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(10, 5), fill=tk.X)
                
                state['distribution_var'] = tk.StringVar(value="random")  # type: ignore
                
                ttk.Radiobutton(dynamic_frame, text="完全随机（每次随机选择）", 
                              variable=state['distribution_var'], value="random",  # type: ignore
                              command=lambda: (state['weight_frame'].pack_forget() if state['weight_frame'] else None)).pack(anchor="w", pady=3, fill=tk.X)  # type: ignore
                ttk.Radiobutton(dynamic_frame, text="自定义权重（使用滑块设置）", 
                              variable=state['distribution_var'], value="custom",  # type: ignore
                              command=lambda: (state['weight_frame'].pack(fill=tk.BOTH, expand=True, pady=5) if state['weight_frame'] else None)).pack(anchor="w", pady=3, fill=tk.X)  # type: ignore
                
                # 权重滑块容器
                state['weight_frame'] = ttk.Frame(dynamic_frame)  # type: ignore
                
                ttk.Label(state['weight_frame'], text="选项权重（用:或,分隔，如 3:2:1）：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(5, 3), fill=tk.X)  # type: ignore
                
                state['weights_var'] = tk.StringVar(value="1:1:1:1")  # type: ignore
                ttk.Entry(state['weight_frame'], textvariable=state['weights_var'], width=40).pack(fill=tk.X, pady=3)  # type: ignore
                
                state['current_sliders'] = []  # type: ignore
                
                def refresh_matrix_sliders():
                    pass  # 矩阵题不需要动态刷新滑块
                
                state['option_count_var'].trace_add("write", lambda *args: refresh_matrix_sliders())  # type: ignore
                
            else:
                # ===== 单选、量表、下拉题 =====
                option_control_frame = ttk.Frame(dynamic_frame)
                option_control_frame.pack(fill=tk.X, pady=5)
                
                ttk.Label(option_control_frame, text="选项个数：", font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, padx=(0, 5))
                
                state['option_count_var'] = tk.StringVar(value="4")  # type: ignore
                
                def update_option_count(delta):
                    try:
                        current = int(state['option_count_var'].get())  # type: ignore
                        new_count = max(1, current + delta)
                        state['option_count_var'].set(str(new_count))  # type: ignore
                        refresh_sliders()
                    except ValueError:
                        pass
                
                ttk.Button(option_control_frame, text="➖", width=3, command=lambda: update_option_count(-1)).pack(side=tk.LEFT, padx=2)
                ttk.Entry(option_control_frame, textvariable=state['option_count_var'], width=5).pack(side=tk.LEFT, padx=2)  # type: ignore
                ttk.Button(option_control_frame, text="➕", width=3, command=lambda: update_option_count(1)).pack(side=tk.LEFT, padx=2)
                
                # 分布方式
                ttk.Label(dynamic_frame, text="选择分布方式：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(10, 5), fill=tk.X)
                
                state['distribution_var'] = tk.StringVar(value="random")  # type: ignore
                
                ttk.Radiobutton(dynamic_frame, text="完全随机（每次随机选择）", 
                              variable=state['distribution_var'], value="random",  # type: ignore
                              command=lambda: (state['weight_frame'].pack_forget() if state['weight_frame'] else None)).pack(anchor="w", pady=3, fill=tk.X)  # type: ignore
                ttk.Radiobutton(dynamic_frame, text="自定义权重（使用滑块设置）", 
                              variable=state['distribution_var'], value="custom",  # type: ignore
                              command=lambda: (state['weight_frame'].pack(fill=tk.BOTH, expand=True, pady=5) if state['weight_frame'] else None)).pack(anchor="w", pady=3, fill=tk.X)  # type: ignore
                
                # 权重滑块容器
                state['weight_frame'] = ttk.Frame(dynamic_frame)  # type: ignore
                
                ttk.Label(state['weight_frame'], text="选项权重（0-10）：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(5, 3), fill=tk.X)  # type: ignore
                
                sliders_frame = ttk.Frame(state['weight_frame'])  # type: ignore
                sliders_frame.pack(fill=tk.BOTH, expand=True, pady=5)
                
                state['current_sliders'] = []  # type: ignore
                
                def refresh_sliders():
                    for child in sliders_frame.winfo_children():
                        child.destroy()
                    state['current_sliders'] = []  # type: ignore
                    
                    try:
                        option_count = int(state['option_count_var'].get())  # type: ignore
                    except:
                        option_count = 4
                    
                    for i in range(option_count):
                        row_frame = ttk.Frame(sliders_frame)
                        row_frame.pack(fill=tk.X, pady=3, padx=(10, 10))
                        row_frame.columnconfigure(1, weight=1)
                        
                        var = tk.DoubleVar(value=1.0)
                        
                        label_text = ttk.Label(row_frame, text=f"选项 {i+1}:", width=8, anchor="w")
                        label_text.grid(row=0, column=0, sticky="w")
                        
                        slider = ttk.Scale(row_frame, from_=0, to=10, variable=var, orient=tk.HORIZONTAL)
                        slider.grid(row=0, column=1, sticky="ew", padx=5)
                        
                        weight_label = ttk.Label(row_frame, text="1.0", width=6, anchor="e")
                        weight_label.grid(row=0, column=2, sticky="e")
                        
                        def update_label(v=var, l=weight_label):
                            l.config(text=f"{v.get():.1f}")
                        
                        var.trace_add("write", lambda *args, v=var, l=weight_label: update_label(v, l))
                        state['current_sliders'].append(var)  # type: ignore
                
                refresh_sliders()
                state['option_count_var'].trace_add("write", lambda *args: refresh_sliders())  # type: ignore
        
        # 初始化动态内容
        question_type_combo.bind("<<ComboboxSelected>>", refresh_dynamic_content)
        refresh_dynamic_content()
        
        # ===== 按钮区域 =====
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=15, pady=(0, 15), side=tk.BOTTOM)
        
        def save_question():
            try:
                q_type = LABEL_TO_TYPE.get(question_type_var.get(), "single")
                option_count = 0
                distribution_mode = "equal"
                custom_weights = None
                probabilities = None
                texts_values = None
                rows = 1
                
                if q_type == "text":
                    raw = "||".join([var.get().strip() for var in state['answer_vars']]) if state['answer_vars'] else ""
                    if not raw:
                        self._log_popup_error("错误", "请填写至少一个答案")
                        return
                    parts = re.split(r"[|\n,]", raw)
                    texts_values = [item.strip() for item in parts if item.strip()]
                    if not texts_values:
                        self._log_popup_error("错误", "请填写至少一个答案")
                        return
                    option_count = len(texts_values)
                    probabilities = normalize_probabilities([1.0] * option_count)
                elif q_type == "multiple":
                    option_count = int(state['option_count_var'].get())  # type: ignore
                    if option_count <= 0:
                        raise ValueError("选项个数必须为正整数")
                    if state['multiple_random_var'].get():  # type: ignore
                        probabilities = -1
                        distribution_mode = "random"
                    else:
                        if state['current_sliders']:  # type: ignore
                            custom_weights = [var.get() for var in state['current_sliders']]  # type: ignore
                        else:
                            custom_weights = [50.0] * option_count
                        probabilities = custom_weights
                        distribution_mode = "custom"
                elif q_type == "matrix":
                    option_count = int(state['option_count_var'].get())  # type: ignore
                    rows = int(state['matrix_rows_var'].get())  # type: ignore
                    if option_count <= 0 or rows <= 0:
                        raise ValueError("选项数和行数必须为正整数")
                    distribution_mode = state['distribution_var'].get()  # type: ignore
                    if distribution_mode == "random":
                        probabilities = -1
                    elif distribution_mode == "equal":
                        probabilities = normalize_probabilities([1.0] * option_count)
                    else:
                        raw = state['weights_var'].get().strip()  # type: ignore
                        if not raw:
                            custom_weights = [1.0] * option_count
                        else:
                            parts = raw.replace("：", ":").replace("，", ",").replace(" ", "").split(":" if ":" in raw else ",")
                            custom_weights = [float(item.strip()) for item in parts if item.strip()]
                            if len(custom_weights) != option_count:
                                raise ValueError(f"权重数量({len(custom_weights)})与选项数({option_count})不匹配")
                        probabilities = normalize_probabilities(custom_weights)
                else:
                    option_count = int(state['option_count_var'].get())  # type: ignore
                    if option_count <= 0:
                        raise ValueError("选项个数必须为正整数")
                    distribution_mode = state['distribution_var'].get()  # type: ignore
                    if distribution_mode == "random":
                        probabilities = -1
                    elif distribution_mode == "equal":
                        probabilities = normalize_probabilities([1.0] * option_count)
                    else:
                        if state['current_sliders']:  # type: ignore
                            custom_weights = [var.get() for var in state['current_sliders']]  # type: ignore
                        else:
                            custom_weights = [1.0] * option_count
                        probabilities = normalize_probabilities(custom_weights)
                
                entry = QuestionEntry(
                    question_type=q_type,
                    probabilities=probabilities,
                    texts=texts_values,
                    rows=rows,
                    option_count=option_count,
                    distribution_mode=distribution_mode,
                    custom_weights=custom_weights,
                    option_fill_texts=None,
                    fillable_option_indices=None,
                )
                logging.info(f"[Action Log] Adding question type={q_type} options={option_count} mode={distribution_mode}")
                self.question_entries.append(entry)
                self._refresh_tree()
                _cleanup()
                logging.info(f"[Action Log] Question added successfully (total={len(self.question_entries)})")
            except ValueError as exc:
                self._log_popup_error("参数错误", str(exc))
        
        ttk.Button(button_frame, text="保存", command=save_question).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="取消", command=_cleanup).pack(side=tk.RIGHT, padx=5)


    def _get_selected_indices(self):
        return sorted([item['index'] for item in self.question_items if item['var'].get()])

    def toggle_select_all(self):
        """全选/取消全选所有题目"""
        select_all = self.select_all_var.get()
        for item in self.question_items:
            item['var'].set(select_all)

    def remove_question(self):
        selected_indices = self._get_selected_indices()
        if not selected_indices:
            logging.info("[Action Log] Remove question requested without selection")
            self._log_popup_info("提示", "请先勾选要删除的题目")
            return
        
        # 添加确认弹窗
        count = len(selected_indices)
        logging.info(f"[Action Log] Remove question requested for {count} items")
        confirm_msg = f"确定要删除选中的 {count} 道题目吗？\n\n此操作无法撤销！"
        if not self._log_popup_confirm("确认删除", confirm_msg, icon='warning'):
            logging.info("[Action Log] Remove question canceled by user")
            return
        
        for index in sorted(selected_indices, reverse=True):
            if 0 <= index < len(self.question_entries):
                self.question_entries.pop(index)
        logging.info(f"[Action Log] Removed {count} question(s)")
        
        self._refresh_tree()

    def edit_question(self):
        selected_indices = self._get_selected_indices()
        if not selected_indices:
            logging.info("[Action Log] Edit question requested without selection")
            self._log_popup_info("提示", "请先勾选要编辑的题目")
            return
        if len(selected_indices) > 1:
            logging.info("[Action Log] Edit question requested with multiple selections")
            self._log_popup_info("提示", "一次只能编辑一道题目")
            return
        index = selected_indices[0]
        if 0 <= index < len(self.question_entries):
            logging.info(f"[Action Log] Opening edit dialog for question #{index+1}")
            entry = self.question_entries[index]
            self._show_edit_dialog(entry, index)

    def _refresh_tree(self):
        # 清除所有旧项目
        for item in self.question_items:
            item['frame'].destroy()
        self.question_items.clear()
        
        # 为每个问题创建一行
        for idx, entry in enumerate(self.question_entries):
            # 创建一行的Frame
            row_frame = ttk.Frame(self.questions_frame)
            row_frame.pack(fill=tk.X, pady=2, padx=5)
            
            # 复选框（使用ttk样式）
            var = tk.BooleanVar(value=False)
            var.trace_add("write", lambda *args: self._update_select_all_state())
            cb = ttk.Checkbutton(row_frame, variable=var)
            cb.pack(side=tk.LEFT, padx=(0, 10))
            
            # 题型标签
            type_label = ttk.Label(row_frame, text=QUESTION_TYPE_LABELS.get(entry.question_type, entry.question_type), 
                                  width=12, anchor="w")
            type_label.pack(side=tk.LEFT, padx=(0, 10))
            
            # 配置信息标签
            detail_label = ttk.Label(row_frame, text=entry.summary(), anchor="w")
            detail_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            # 保存引用
            self.question_items.append({
                'frame': row_frame,
                'checkbox': cb,
                'var': var,
                'index': idx
            })
        
        # 标记配置有改动
        self._mark_config_changed()
        
        # 更新全选复选框状态
        self._update_select_all_state()

        self._safe_preview_button_config(text=self._get_preview_button_label())

    def _update_select_all_state(self):
        """根据单个复选框状态更新全选复选框"""
        if not self.question_items:
            self.select_all_var.set(False)
            return
        
        all_selected = all(item['var'].get() for item in self.question_items)
        self.select_all_var.set(all_selected)

    def _show_edit_dialog(self, entry, index):
        edit_win = tk.Toplevel(self.root)
        edit_win.title(f"编辑第 {index + 1} 题")
        edit_win.geometry("550x550")
        edit_win.transient(self.root)
        edit_win.grab_set()

        scroll_container = ttk.Frame(edit_win)
        scroll_container.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(scroll_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        frame = ttk.Frame(canvas, padding=20)
        canvas_window = canvas.create_window((0, 0), window=frame, anchor="nw")

        def _on_frame_configure(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event=None):
            if event and event.width > 1:
                canvas.itemconfigure(canvas_window, width=event.width)

        frame.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        def _close_edit_window():
            canvas.unbind_all("<MouseWheel>")
            try:
                edit_win.grab_release()
            except Exception:
                pass
            edit_win.destroy()

        edit_win.protocol("WM_DELETE_WINDOW", _close_edit_window)

        question_identifier = entry.question_num or f"第 {index + 1} 题"
        overview_card = tk.Frame(frame, bg="#f6f8ff", highlightbackground="#cfd8ff", highlightthickness=1, bd=0)
        overview_card.pack(fill=tk.X, pady=(0, 15))
        overview_inner = tk.Frame(overview_card, bg="#f6f8ff")
        overview_inner.pack(fill=tk.X, padx=14, pady=10)

        tk.Label(
            overview_inner,
            text=f"正在编辑：{question_identifier}",
            font=("TkDefaultFont", 11, "bold"),
            fg="#1a237e",
            bg="#f6f8ff"
        ).pack(anchor="w", fill=tk.X)

        summary_line = entry.summary()
        tk.Label(
            overview_inner,
            text=summary_line,
            fg="#455a64",
            bg="#f6f8ff",
            wraplength=420,
            justify="left"
        ).pack(anchor="w", pady=(4, 2), fill=tk.X)

        readable_type = QUESTION_TYPE_LABELS.get(entry.question_type, entry.question_type)
        mode_map = {
            "random": "完全随机",
            "equal": "平均分配",
            "custom": "自定义配比",
        }
        mode_label = mode_map.get(entry.distribution_mode, "平均分配")
        tk.Label(
            overview_inner,
            text=f"题型：{readable_type} | 当前策略：{mode_label}",
            fg="#546e7a",
            bg="#f6f8ff"
        ).pack(anchor="w", fill=tk.X)

        chip_frame = tk.Frame(overview_inner, bg="#f6f8ff")
        chip_frame.pack(anchor="w", pady=(6, 0))
        ttk.Label(
            chip_frame,
            text=f"选项数：{entry.option_count}",
        ).pack(side=tk.LEFT, padx=(0, 6))
        fillable_count = len(entry.fillable_option_indices or [])
        filled_values = len([text for text in (entry.option_fill_texts or []) if text])
        if fillable_count:
            tk.Label(
                chip_frame,
                text=f"含 {fillable_count} 个附加填空",
                bg="#e3f2fd",
                fg="#0d47a1",
                font=("TkDefaultFont", 9),
                padx=8,
                pady=2
            ).pack(side=tk.LEFT, padx=(0, 6))
        if filled_values:
            tk.Label(
                chip_frame,
                text=f"{filled_values} 个附加内容已设置",
                bg="#ede7f6",
                fg="#4527a0",
                font=("TkDefaultFont", 9),
                padx=8,
                pady=2
            ).pack(side=tk.LEFT)

        helper_text = self._get_edit_dialog_hint(entry)
        if helper_text:
            helper_box = tk.Frame(frame, bg="#fff8e1", highlightbackground="#ffe082", highlightthickness=1)
            helper_box.pack(fill=tk.X, pady=(0, 12))
            tk.Label(
                helper_box,
                text=helper_text,
                bg="#fff8e1",
                fg="#864a00",
                wraplength=460,
                justify="left",
                padx=12,
                pady=8
            ).pack(fill=tk.X)

        fillable_indices = set(entry.fillable_option_indices or [])
        existing_fill_values = entry.option_fill_texts or []

        def _should_show_inline_fill(option_index: int) -> bool:
            if fillable_indices and option_index in fillable_indices:
                return True
            if option_index < len(existing_fill_values) and existing_fill_values[option_index]:
                return True
            return False

        def _attach_inline_fill_input(row_frame: ttk.Frame, option_index: int, inline_vars: List[Optional[tk.StringVar]]):
            if not inline_vars or option_index < 0 or option_index >= len(inline_vars):
                return
            if not _should_show_inline_fill(option_index):
                return
            inline_row = ttk.Frame(row_frame)
            inline_row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(2, 4))
            ttk.Label(inline_row, text="附加填空：").pack(side=tk.LEFT)
            initial_text = ""
            if option_index < len(existing_fill_values) and existing_fill_values[option_index]:
                initial_text = existing_fill_values[option_index] or ""
            var = tk.StringVar(value=initial_text)
            entry_widget = ttk.Entry(inline_row, textvariable=var, width=32)
            entry_widget.pack(side=tk.LEFT, padx=(6, 6), fill=tk.X, expand=True)
            ttk.Label(inline_row, text="留空将自动填“无”", foreground="gray").pack(side=tk.LEFT)
            inline_vars[option_index] = var

        def _collect_inline_fill_values(inline_vars: List[Optional[tk.StringVar]], option_total: int) -> Optional[List[Optional[str]]]:
            if not inline_vars:
                return None
            existing = list(existing_fill_values)
            if len(existing) < option_total:
                existing.extend([None] * (option_total - len(existing)))
            collected: List[Optional[str]] = []
            has_value = False
            for idx in range(option_total):
                var = inline_vars[idx] if idx < len(inline_vars) else None
                if var is None:
                    value = existing[idx] if idx < len(existing) else None
                    if value:
                        has_value = True
                    collected.append(value)
                    continue
                value = var.get().strip()
                if value:
                    collected.append(value)
                    has_value = True
                elif (fillable_indices and idx in fillable_indices) or (idx < len(existing) and existing[idx]):
                    collected.append(DEFAULT_FILL_TEXT)
                    has_value = True
                else:
                    collected.append(None)
            return collected if has_value else None

        ttk.Label(frame, text=f"题型: {QUESTION_TYPE_LABELS.get(entry.question_type, entry.question_type)}",
                 font=("TkDefaultFont", 10, "bold")).pack(pady=(0, 20))
        
        if entry.question_type == "text":
            ttk.Label(frame, text="填空答案列表：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=5, fill=tk.X)
            
            answers_frame = ttk.Frame(frame)
            answers_frame.pack(fill=tk.BOTH, expand=True, pady=10)
            
            canvas = tk.Canvas(answers_frame, height=200)
            scrollbar = ttk.Scrollbar(answers_frame, orient="vertical", command=canvas.yview)
            scrollable_frame = ttk.Frame(canvas)
            
            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )
            
            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
            
            answer_vars = []
            
            def add_answer_field(initial_value=""):
                row_frame = ttk.Frame(scrollable_frame)
                row_frame.pack(fill=tk.X, pady=5, padx=5)
                
                ttk.Label(row_frame, text=f"答案{len(answer_vars)+1}:", width=8).pack(side=tk.LEFT)
                
                var = tk.StringVar(value=initial_value)
                entry_widget = ttk.Entry(row_frame, textvariable=var, width=40)
                entry_widget.pack(side=tk.LEFT, padx=5)
                
                def remove_field():
                    row_frame.destroy()
                    answer_vars.remove(var)
                    update_labels()
                
                if len(answer_vars) > 0:
                    ttk.Button(row_frame, text="✖", width=3, command=remove_field).pack(side=tk.LEFT)
                
                answer_vars.append(var)
                return var
            
            def update_labels():
                for i, child in enumerate(scrollable_frame.winfo_children()):
                    label = child.winfo_children()[0]
                    if isinstance(label, ttk.Label):
                        label.config(text=f"答案{i+1}:")
            
            for answer in (entry.texts if entry.texts else ["默认答案"]):
                add_answer_field(answer)
            
            canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            
            add_btn_frame = ttk.Frame(frame)
            add_btn_frame.pack(fill=tk.X, pady=(5, 0))
            ttk.Button(add_btn_frame, text="➕ 添加答案", command=lambda: add_answer_field()).pack(anchor="w", fill=tk.X)
            
            def save_text():
                values = [var.get().strip() for var in answer_vars if var.get().strip()]
                if not values:
                    self._log_popup_error("错误", "请填写至少一个答案")
                    return
                entry.texts = values
                entry.probabilities = normalize_probabilities([1.0] * len(values))
                entry.option_count = len(values)
                self._refresh_tree()
                _close_edit_window()
                logging.info(f"[Action Log] Saved text answers for question #{index+1}")
            
            save_btn = ttk.Button(frame, text="保存", command=save_text)
            save_btn.pack(pady=20, ipadx=20, ipady=5)
            
        elif entry.question_type == "multiple":
            ttk.Label(frame, text=f"多选题（{entry.option_count}个选项）").pack(anchor="w", pady=5, fill=tk.X)
            ttk.Label(frame, text="设置每个选项的选中概率（0-100%）：",
                     foreground="gray").pack(anchor="w", pady=5, fill=tk.X)

            sliders = []
            slider_frame = ttk.Frame(frame)
            slider_frame.pack(fill=tk.BOTH, expand=True, pady=10)

            canvas = tk.Canvas(slider_frame, height=250, highlightthickness=0)
            scrollbar = ttk.Scrollbar(slider_frame, orient="vertical", command=canvas.yview)
            scrollable_frame = ttk.Frame(canvas)

            canvas_win = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

            def _on_scroll_config(event):
                canvas.configure(scrollregion=canvas.bbox("all"))
            scrollable_frame.bind("<Configure>", _on_scroll_config)

            def _on_canvas_config(event):
                canvas.itemconfigure(canvas_win, width=event.width)
            canvas.bind("<Configure>", _on_canvas_config)

            canvas.configure(yscrollcommand=scrollbar.set)

            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            current_probs = entry.custom_weights if entry.custom_weights else [50.0] * entry.option_count
            # 获取选项文本（如果有的话）
            option_texts = entry.texts if entry.texts else []
            inline_fill_vars: List[Optional[tk.StringVar]] = [None] * entry.option_count

            for i in range(entry.option_count):
                row_frame = ttk.Frame(scrollable_frame)
                row_frame.pack(fill=tk.X, pady=4, padx=(10, 20))
                row_frame.columnconfigure(1, weight=1)

                # 显示选项文本（如果有的话）- 使用两行布局
                option_text = option_texts[i] if i < len(option_texts) and option_texts[i] else ""
                text_label = ttk.Label(row_frame, text=f"选项 {i+1}: {option_text}" if option_text else f"选项 {i+1}", 
                                       anchor="w", wraplength=450)
                text_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 2))
                
                # 第二行：滑块和百分比
                var = tk.DoubleVar(value=current_probs[i] if i < len(current_probs) else 50.0)
                slider = ttk.Scale(row_frame, from_=0, to=100, variable=var, orient=tk.HORIZONTAL)
                slider.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(20, 5))

                label = ttk.Label(row_frame, text=f"{int(var.get())}%", width=6, anchor="e")
                label.grid(row=1, column=2, sticky="e")

                var.trace_add("write", lambda *args, l=label, v=var: l.config(text=f"{int(v.get())}%"))
                sliders.append(var)
                _attach_inline_fill_input(row_frame, i, inline_fill_vars)

            def save_multiple():
                probs = [var.get() for var in sliders]
                entry.custom_weights = probs
                entry.probabilities = probs
                entry.distribution_mode = "custom"
                entry.option_fill_texts = _collect_inline_fill_values(inline_fill_vars, entry.option_count)
                self._refresh_tree()
                _close_edit_window()
                logging.info(f"[Action Log] Saved custom weights for question #{index+1}")
            
            save_btn = ttk.Button(frame, text="保存", command=save_multiple)
            save_btn.pack(pady=10, ipadx=20, ipady=5)
            
        else:
            ttk.Label(frame, text=f"选项数: {entry.option_count}").pack(anchor="w", pady=5, fill=tk.X)
            if entry.question_type == "matrix":
                ttk.Label(frame, text=f"矩阵行数: {entry.rows}").pack(anchor="w", pady=5, fill=tk.X)

            ttk.Label(frame, text="选择分布方式：").pack(anchor="w", pady=10, fill=tk.X)

            dist_var = tk.StringVar(value=entry.distribution_mode if entry.distribution_mode in ["random", "custom"] else "random")

            weight_frame = ttk.Frame(frame)
            slider_vars: List[tk.DoubleVar] = []
            option_texts = entry.texts if entry.texts else []
            initial_weights = entry.custom_weights if entry.custom_weights else [1.0] * entry.option_count
            slider_hint = "拖动滑块设置每个选项的权重（0-10）：" if entry.question_type != "matrix" else "拖动滑块设置每列被选中的优先级（0-10）："
            ttk.Label(weight_frame, text=slider_hint, foreground="gray").pack(anchor="w", pady=(5, 8), fill=tk.X)

            sliders_container = ttk.Frame(weight_frame)
            sliders_container.pack(fill=tk.BOTH, expand=True)
            inline_fill_vars: List[Optional[tk.StringVar]] = [None] * entry.option_count if entry.question_type in ("single", "dropdown") else []

            for i in range(entry.option_count):
                row_frame = ttk.Frame(sliders_container)
                row_frame.pack(fill=tk.X, pady=4, padx=(10, 20))
                row_frame.columnconfigure(1, weight=1)

                option_text = option_texts[i] if i < len(option_texts) and option_texts[i] else ""
                text_value = f"选项 {i+1}: {option_text}" if option_text else f"选项 {i+1}"
                ttk.Label(row_frame, text=text_value, anchor="w", wraplength=420).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 2))

                initial_value = float(initial_weights[i]) if i < len(initial_weights) else 1.0
                var = tk.DoubleVar(value=initial_value)
                slider = ttk.Scale(row_frame, from_=0, to=10, variable=var, orient=tk.HORIZONTAL)
                slider.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(20, 5))

                value_label = ttk.Label(row_frame, text=f"{initial_value:.1f}", width=6, anchor="e")
                value_label.grid(row=1, column=2, sticky="e")

                def _update_value_label(v=var, lbl=value_label):
                    lbl.config(text=f"{v.get():.1f}")

                var.trace_add("write", lambda *args, v=var, lbl=value_label: _update_value_label(v, lbl))
                slider_vars.append(var)
                _attach_inline_fill_input(row_frame, i, inline_fill_vars)

            ttk.Radiobutton(frame, text="完全随机", variable=dist_var, value="random").pack(anchor="w", fill=tk.X)
            ttk.Radiobutton(frame, text="自定义权重（使用滑块设置）", variable=dist_var, value="custom").pack(anchor="w", fill=tk.X)

            def save_other():
                mode = dist_var.get()
                if mode == "random":
                    entry.probabilities = -1
                    entry.custom_weights = None
                elif mode == "equal":
                    weights = [1.0] * entry.option_count
                    entry.custom_weights = weights
                    entry.probabilities = normalize_probabilities(weights)
                else:
                    weights = [var.get() for var in slider_vars]
                    if not weights or all(w <= 0 for w in weights):
                        self._log_popup_error("错误", "至少需要一个选项的权重大于 0")
                        return
                    entry.custom_weights = weights
                    entry.probabilities = normalize_probabilities(weights)

                entry.distribution_mode = mode
                entry.option_fill_texts = _collect_inline_fill_values(inline_fill_vars, entry.option_count)
                self._refresh_tree()
                _close_edit_window()
                logging.info(f"[Action Log] Saved distribution settings ({mode}) for question #{index+1}")
            save_btn = ttk.Button(frame, text="保存", command=save_other)
            save_btn.pack(pady=20, ipadx=20, ipady=5)

            def _toggle_weight_frame(*_):
                if dist_var.get() == "custom":
                    weight_frame.pack(fill=tk.BOTH, expand=True, pady=10, before=save_btn)
                else:
                    weight_frame.pack_forget()

            dist_var.trace_add("write", _toggle_weight_frame)
            _toggle_weight_frame()


    def _get_edit_dialog_hint(self, entry: QuestionEntry) -> str:
        """根据题型返回更口语化的编辑提示。"""
        hints = {
            "text": "可输入多个候选答案，执行时会在这些答案中轮换填写；建议保留能覆盖不同语气的内容。",
            "multiple": "右侧滑块控制每个选项的命中率，百分比越高越常被勾选；可结合下方“选项填写”设置附加文本。",
            "single": "可在“完全随机”和“自定义权重”之间切换，想突出热门选项时直接把滑块调高即可。",
            "dropdown": "与单选题相同，若问卷含“其他”选项，可在底部“附加填空”区写入默认内容。",
            "scale": "量表题通常代表分值，若希望答案集中在某个区间，请在自定义配比里提升对应滑块。",
            "matrix": "矩阵题的滑块作用于每一列，值越大越倾向被选，适合模拟“偏好列”的情况。",
        }
        return hints.get(entry.question_type, "根据右侧控件调整答案或权重，保存后可在列表中随时再次修改。")


    def upload_qrcode(self):
        """上传二维码图片并解析链接"""
        file_path = filedialog.askopenfilename(
            title="选择问卷二维码图片",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.webp *.bmp *.gif")
            ]
        )
        
        if not file_path:
            return
        logging.info(f"[Action Log] QR code image selected: {file_path}")
        
        try:
            # 解码二维码
            url = decode_qrcode(file_path)
            
            if url:
                self.url_var.set(url)
                self._log_popup_info("成功", f"二维码解析成功！\n链接: {url}")
            else:
                self._log_popup_error("错误", "未能从图片中识别出二维码，请确认图片包含有效的二维码。")
        except Exception as e:
            logging.error(f"二维码解析失败: {str(e)}")
            self._log_popup_error("错误", f"二维码解析失败: {str(e)}")

    def preview_survey(self):
        url_value = self.url_var.get().strip()
        if not url_value:
            self._log_popup_error("错误", "请先填写问卷链接")
            return
        if not self._validate_wjx_url(url_value):
            return
        logging.info(f"[Action Log] Preview survey requested for URL: {url_value}")
        if self.question_entries:
            choice = self._show_preview_choice_dialog(len(self.question_entries))
            if choice is None:
                return
            if choice == "preview":
                self._start_preview_only(url_value, preserve_existing=True)
                return
            self._start_auto_config(url_value, preserve_existing=True)
            return
        self._start_auto_config(url_value, preserve_existing=False)

    def _show_preview_choice_dialog(self, configured_count: int) -> Optional[str]:
        dialog = tk.Toplevel(self.root)
        dialog.title("请选择操作")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        message = (
            f"当前已配置 {configured_count} 道题目。\n"
            f"请选择要执行的操作：\n\n"
            f"继续自动配置：解析问卷并根据必要题目追加/覆盖。\n"
            f"仅预览：仅查看问卷结构或快速演示填写。"
        )
        ttk.Label(frame, text=message, justify="left", wraplength=360).pack(pady=(0, 12))

        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X)

        result = tk.StringVar(value="")

        def choose(value: str):
            result.set(value)
            dialog.destroy()

        ttk.Button(button_frame, text="仅预览", command=lambda: choose("preview")).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="继续自动配置", command=lambda: choose("auto")).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=lambda: choose("")).pack(side=tk.RIGHT, padx=5)

        def on_close():
            result.set("")
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", on_close)
        dialog.update_idletasks()
        win_w = dialog.winfo_width()
        win_h = dialog.winfo_height()
        screen_w = dialog.winfo_screenwidth()
        screen_h = dialog.winfo_screenheight()
        x = max(0, (screen_w - win_w) // 2)
        y = max(0, (screen_h - win_h) // 2)
        dialog.geometry(f"+{x}+{y}")

        self.root.wait_window(dialog)
        value = result.get()
        return value if value else None

    def _start_preview_only(self, url_value: str, preserve_existing: bool):
        if self.question_entries and self._last_parsed_url == url_value and self._last_questions_info:
            self._safe_preview_button_config(state=tk.DISABLED, text="正在预览...")
            Thread(target=self._launch_preview_browser_session, args=(url_value,), daemon=True).start()
            return
        if self._last_parsed_url == url_value and self._last_questions_info:
            self._show_preview_window(deepcopy(self._last_questions_info), preserve_existing=preserve_existing)
            return
        self._start_survey_parsing(
            url_value,
            lambda info: self._show_preview_window(info, preserve_existing=preserve_existing),
        )

    def _start_auto_config(self, url_value: str, preserve_existing: bool):
        if self._last_parsed_url == url_value and self._last_questions_info:
            self._show_preview_window(deepcopy(self._last_questions_info), preserve_existing=preserve_existing)
            return
        self._start_survey_parsing(
            url_value,
            lambda info: self._show_preview_window(info, preserve_existing=preserve_existing),
        )

    def _start_survey_parsing(self, url_value: str, result_handler: Callable[[List[Dict[str, Any]]], None]):
        self._last_survey_title = None
        self._safe_preview_button_config(state=tk.DISABLED, text="加载中...")
        progress_win = tk.Toplevel(self.root)
        progress_win.title("正在加载问卷")
        progress_win.geometry("400x200")
        progress_win.resizable(False, False)
        progress_win.transient(self.root)
        progress_win.grab_set()

        progress_win.update_idletasks()
        win_width = progress_win.winfo_width()
        win_height = progress_win.winfo_height()
        screen_width = progress_win.winfo_screenwidth()
        screen_height = progress_win.winfo_screenheight()

        try:
            import ctypes
            from ctypes.wintypes import RECT

            work_area = RECT()
            ctypes.windll.user32.SystemParametersInfoA(48, 0, ctypes.byref(work_area), 0)
            work_width = work_area.right - work_area.left
            work_height = work_area.bottom - work_area.top
            work_x = work_area.left
            work_y = work_area.top
            x = work_x + (work_width - win_width) // 2
            y = work_y + (work_height - win_height) // 2
        except Exception:
            x = (screen_width - win_width) // 2
            y = (screen_height - win_height) // 2

        x = max(0, x)
        y = max(0, y)
        progress_win.geometry(f"+{x}+{y}")

        frame = ttk.Frame(progress_win, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="正在加载问卷...", font=("", 11, "bold")).pack(pady=(0, 15))
        status_label = ttk.Label(frame, text="初始化浏览器...", foreground="gray")
        status_label.pack(pady=(0, 10))

        progress_bar = ttk.Progressbar(frame, mode="determinate", maximum=100, length=300)
        progress_bar.pack(fill=tk.X, pady=5)

        percentage_label = ttk.Label(frame, text="0%", font=("", 10, "bold"))
        percentage_label.pack(pady=(5, 0))

        progress_win.update()

        preview_thread = Thread(
            target=self._parse_and_show_survey,
            args=(url_value, progress_win, status_label, progress_bar, percentage_label, result_handler),
            daemon=True,
        )
        preview_thread.start()

    def _parse_and_show_survey(self, survey_url, progress_win=None, status_label=None, progress_bar=None, percentage_label=None, result_handler: Optional[Callable[[List[Dict[str, Any]]], None]] = None):
        driver = None
        try:
            # 更新进度函数
            def update_progress(percent, status_text):
                if progress_bar is not None:
                    self.root.after(0, lambda p=percent, pb=progress_bar: pb.config(value=p) if pb else None)
                if percentage_label is not None:
                    self.root.after(0, lambda p=percent, pl=percentage_label: pl.config(text=f"{int(p)}%") if pl else None)
                if status_label is not None:
                    self.root.after(0, lambda s=status_text, sl=status_label: sl.config(text=s) if sl else None)
            
            # 更新状态
            update_progress(5, "开始准备解析...")
            
            questions_info = self._try_parse_survey_via_http(survey_url, update_progress)
            if questions_info is not None:
                print(f"已成功通过 HTTP 解析，共 {len(questions_info)} 题")
                update_progress(100, "解析完成，正在显示结果...")
                time.sleep(0.5)
                if progress_win:
                    self.root.after(0, lambda: progress_win.destroy())
                self._cache_parsed_survey(questions_info, survey_url)
                handler = result_handler or (lambda data: self._show_preview_window(data))
                info_copy = deepcopy(questions_info)
                self.root.after(0, lambda data=info_copy: handler(data))
                self.root.after(0, lambda: self._safe_preview_button_config(state=tk.NORMAL, text=self._get_preview_button_label()))
                return
            
            update_progress(30, "HTTP 解析失败，准备启动浏览器...")
            
            print(f"正在加载问卷: {survey_url}")
            driver, browser_name = create_selenium_driver(headless=True)
            logging.info(f"Fallback 到 {browser_name.capitalize()} WebDriver 解析问卷")
            
            update_progress(45, "正在打开问卷页面...")
            
            driver.get(survey_url)
            time.sleep(3)
            
            page_source = ""
            try:
                page_source = driver.page_source
            except Exception:
                page_source = ""
            extracted_title = _extract_survey_title_from_html(page_source) if page_source else None
            if extracted_title:
                self._last_survey_title = extracted_title
            else:
                try:
                    driver_title = driver.title
                except Exception:
                    driver_title = ""
                cleaned = _normalize_html_text(driver_title)
                cleaned = re.sub(r"(?:[-|]\s*)?(?:问卷星.*)$", "", cleaned, flags=re.IGNORECASE).strip(" -_|")
                if cleaned:
                    self._last_survey_title = cleaned
            
            update_progress(60, "正在解析题目结构...")
            
            print("开始解析题目...")
            questions_info = []
            questions_per_page = detect(driver)
            total_questions = sum(questions_per_page)
            print(f"检测到 {len(questions_per_page)} 页，总题数: {total_questions}")
            current_question_num = 0
            
            for page_idx, questions_count in enumerate(questions_per_page, 1):
                print(f"正在解析第{page_idx}页，共{questions_count}题")
                
                for _ in range(questions_count):
                    current_question_num += 1
                    
                    # 计算进度百分比（30%~95%）
                    progress_percent = 30 + (current_question_num / max(total_questions, 1)) * 65
                    update_progress(progress_percent, f"正在解析第 {page_idx}/{len(questions_per_page)} 页 (已解析 {current_question_num}/{total_questions} 题)...")
                    
                    try:
                        question_div = driver.find_element(By.CSS_SELECTOR, f"#div{current_question_num}")
                        question_type = question_div.get_attribute("type")
                        
                        title_text = ""
                        try:
                            title_element = question_div.find_element(By.CSS_SELECTOR, ".topichtml")
                            title_text = title_element.text.strip()
                        except:
                            try:
                                title_element = question_div.find_element(By.CSS_SELECTOR, ".field-label")
                                full_text = title_element.text.strip()
                                lines = [line.strip() for line in full_text.split('\n') if line.strip()]
                                for line in lines:
                                    if not line.startswith('*') and not line.endswith('.'):
                                        title_text = line
                                        break
                            except:
                                pass
                        
                        if not title_text:
                            title_text = f"第{current_question_num}题"
                        
                        type_name = self._get_question_type_name(question_type)
                        option_count = 0
                        matrix_rows = 0
                        option_texts = []  # 存储选项文本
                        
                        if question_type in ("3", "4", "5", "7"):
                            if question_type == "7":
                                try:
                                    options = driver.find_elements(By.XPATH, f"//*[@id='q{current_question_num}']/option")
                                    option_count = max(0, len(options) - 1)
                                    # 提取下拉题选项文本
                                    option_texts = [opt.text.strip() for opt in options[1:]] if len(options) > 1 else []
                                except:
                                    option_count = 0
                                    option_texts = []
                            else:
                                try:
                                    options = driver.find_elements(By.XPATH, f'//*[@id="div{current_question_num}"]/div[2]/div')
                                    option_count = len(options)
                                    # 提取单选/多选/量表题选项文本
                                    option_texts = [opt.text.strip() for opt in options]
                                except:
                                    try:
                                        options = driver.find_elements(By.XPATH, f'//*[@id="div{current_question_num}"]//div[@class="ui-radio"]')
                                        option_count = len(options)
                                        option_texts = [opt.text.strip() for opt in options]
                                    except:
                                        option_count = 0
                                        option_texts = []
                        elif question_type == "6":
                            try:
                                rows = driver.find_elements(By.XPATH, f'//*[@id="divRefTab{current_question_num}"]/tbody/tr')
                                matrix_rows = sum(1 for row in rows if row.get_attribute("rowindex") is not None)
                                columns = driver.find_elements(By.XPATH, f'//*[@id="drv{current_question_num}_1"]/td')
                                option_count = max(0, len(columns) - 1)
                                option_texts = [col.text.strip() for col in columns[1:]] if len(columns) > 1 else []
                            except Exception:
                                matrix_rows = 0
                                option_count = 0
                                option_texts = []

                        option_fillable_indices: List[int] = []
                        if question_type in ("3", "4", "5"):
                            try:
                                option_elements = driver.find_elements(By.XPATH, f'//*[@id="div{current_question_num}"]/div[2]/div')
                            except Exception:
                                option_elements = []
                            if not option_elements:
                                try:
                                    option_elements = driver.find_elements(By.XPATH, f'//*[@id="div{current_question_num}"]//div[@class="ui-radio"]')
                                except Exception:
                                    option_elements = []
                            for idx, opt_element in enumerate(option_elements):
                                if _selenium_element_contains_text_input(opt_element):
                                    option_fillable_indices.append(idx)
                            if not option_fillable_indices and option_count > 0 and _selenium_question_has_shared_text_input(question_div):
                                option_fillable_indices.append(option_count - 1)
                        elif question_type == "7":
                            try:
                                inputs = question_div.find_elements(By.CSS_SELECTOR, ".ui-other input, .ui-other textarea")
                            except Exception:
                                inputs = []
                            if inputs and option_count > 0:
                                option_fillable_indices.append(option_count - 1)

                        questions_info.append({
                            "num": current_question_num,
                            "title": title_text,
                            "type": type_name,
                            "type_code": question_type,
                            "options": option_count,
                            "rows": matrix_rows,
                            "page": page_idx,
                            "option_texts": option_texts,
                            "fillable_options": option_fillable_indices
                        })
                        print(f"  ✓ 第{current_question_num}题: {type_name} - {title_text[:30]}")
                    except Exception as e:
                        print(f"  ✗ 第{current_question_num}题解析失败: {e}")
                        traceback.print_exc()
                        questions_info.append({
                            "num": current_question_num,
                            "title": "[解析失败]",
                            "type": "未知",
                            "type_code": "0",
                            "options": 0,
                            "rows": 0,
                            "page": page_idx,
                            "option_texts": []
                        })
                
                if page_idx < len(questions_per_page):
                    try:
                        next_button = driver.find_element(By.CSS_SELECTOR, "#divNext")
                        next_button.click()
                        time.sleep(1.5)
                        print(f"已翻页到第{page_idx + 1}页")
                    except Exception as e:
                        print(f"翻页失败: {e}")
            
            print(f"解析完成，共{len(questions_info)}题")
            update_progress(100, "解析完成，正在显示结果...")
            time.sleep(0.5)
            if progress_win:
                self.root.after(0, lambda: progress_win.destroy())
            self._cache_parsed_survey(questions_info, survey_url)
            handler = result_handler or (lambda data: self._show_preview_window(data))
            info_copy = deepcopy(questions_info)
            self.root.after(0, lambda data=info_copy: handler(data))
            self.root.after(0, lambda: self._safe_preview_button_config(state=tk.NORMAL, text=self._get_preview_button_label()))
            
        except Exception as e:
            error_str = str(e)
            error_lower = error_str.lower()
            if "chrome" in error_lower or "edge" in error_lower:
                if "binary" in error_lower or "not found" in error_lower or "browser" in error_lower:
                    error_msg = (
                        "未找到可用浏览器 (Edge/Chrome)\n\n"
                        "请确认系统已安装 Microsoft Edge 或 Google Chrome"
                    )
                elif "webdriver" in error_lower or "driver" in error_lower:
                    error_msg = (
                        f"浏览器驱动初始化失败: {error_str}\n\n"
                        "建议:\n"
                        "1. Edge/Chrome 是否已安装并可独立启动\n"
                        "2. Selenium 版本需 >= 4.6 以启用 Selenium Manager\n"
                        "3. 检查安全软件是否拦截 WebDriver"
                    )
                else:
                    error_msg = f"浏览器启动失败: {error_str}\n\n请检查 Edge/Chrome 是否能够手动打开问卷"
            else:
                error_msg = (
                    f"解析问卷失败: {error_str}\n\n"
                    "请检查:\n"
                    "1. 问卷链接是否正确\n"
                    "2. 网络连接是否正常\n"
                    "3. 问卷是否需要额外登录"
                )
            print(f"错误: {error_msg}")
            clean_error_msg = error_msg.replace("\n", " ")
            logging.error(f"[Action Log] Preview parsing failed: {clean_error_msg}")
            traceback.print_exc()
            if progress_win:
                self.root.after(0, lambda: progress_win.destroy())
            self.root.after(0, lambda: self._log_popup_error("错误", error_msg))
            self.root.after(0, lambda: self._safe_preview_button_config(state=tk.NORMAL, text=self._get_preview_button_label()))
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass

    def _try_parse_survey_via_http(self, survey_url: str, progress_callback=None) -> Optional[List[Dict[str, Any]]]:
        if not requests or not BeautifulSoup:
            logging.debug("HTTP 解析依赖缺失，跳过无浏览器解析")
            return None
        try:
            if progress_callback:
                progress_callback(10, "正在获取问卷页面...")
            headers = dict(DEFAULT_HTTP_HEADERS)
            headers["Referer"] = survey_url
            response = requests.get(survey_url, headers=headers, timeout=15)
            response.raise_for_status()
            html = response.text
            self._last_survey_title = _extract_survey_title_from_html(html)
            if progress_callback:
                progress_callback(25, "正在解析题目结构...")
            questions_info = parse_survey_questions_from_html(html)
            if not questions_info:
                logging.info("HTTP 解析未能找到任何题目，将回退到浏览器模式")
                return None
            for question in questions_info:
                question["type"] = self._get_question_type_name(question.get("type_code"))
            return questions_info
        except Exception as exc:
            logging.debug(f"HTTP 解析问卷失败: {exc}")
            return None

    def _cache_parsed_survey(self, questions_info: List[Dict[str, Any]], url: str):
        """缓存解析结果以便预览和配置向导复用"""
        self._last_parsed_url = url
        self._last_questions_info = deepcopy(questions_info)

    def _launch_preview_browser_session(self, url: str):
        driver = None
        try:
            configure_probabilities(self.question_entries)
        except ValueError as exc:
            error_text = str(exc)
            self.root.after(0, lambda msg=error_text: self._log_popup_error("预览失败", msg))
            self.root.after(
                0,
                lambda: self._safe_preview_button_config(state=tk.NORMAL, text=self._get_preview_button_label()),
            )
            return

        try:
            driver, browser_name = create_selenium_driver(headless=False)
            driver.maximize_window()
            driver.get(url)

            logging.info(f"[Action Log] Launching preview session for {url}")
            if self._last_questions_info:
                self._fill_preview_answers(driver, self._last_questions_info)
            self.root.after(0, lambda: self._log_popup_info(
                "预览完成",
                "浏览器已自动填写一份，请在窗口中确认是否满意，提交/关闭请手动操作。"
            ))

        except Exception as exc:
            error_msg = f"预览演示失败: {exc}"
            logging.error(error_msg)
            traceback.print_exc()
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            self.root.after(0, lambda: self._log_popup_error("预览失败", error_msg))
        finally:
            self.root.after(0, lambda: self._safe_preview_button_config(state=tk.NORMAL, text=self._get_preview_button_label()))

    def _fill_preview_answers(self, driver: WebDriver, questions_info: List[Dict[str, Any]]) -> None:
        vacancy_idx = single_idx = droplist_idx = multiple_idx = matrix_idx = scale_idx = 0
        for q in questions_info:
            q_type = q.get("type_code")
            current = q.get("num")
            if not current or not q_type:
                continue
            try:
                if q_type in ("1", "2"):
                    vacant(driver, current, vacancy_idx)
                    vacancy_idx += 1
                elif q_type == "3":
                    single(driver, current, single_idx)
                    single_idx += 1
                elif q_type == "4":
                    multiple(driver, current, multiple_idx)
                    multiple_idx += 1
                elif q_type == "5":
                    scale(driver, current, scale_idx)
                    scale_idx += 1
                elif q_type == "6":
                    matrix_idx = matrix(driver, current, matrix_idx)
                elif q_type == "7":
                    droplist(driver, current, droplist_idx)
                    droplist_idx += 1
            except Exception as exc:
                logging.debug(f"预览题目 {current} ({q_type}) 填写失败: {exc}")

    def _safe_preview_button_config(self, **kwargs) -> None:
        if self.preview_button:
            self.preview_button.config(**kwargs)

    def _get_preview_button_label(self) -> str:
        return "预览 / 继续配置" if self.question_entries else "⚡ 自动配置问卷"

    def _get_question_type_name(self, type_code):
        type_map = {
            "1": "填空题(单行)",
            "2": "填空题(多行)",
            "3": "单选题",
            "4": "多选题",
            "5": "量表题",
            "6": "矩阵题",
            "7": "下拉题",
            "8": "滑块题",
            "11": "排序题"
        }
        return type_map.get(type_code, f"未知类型({type_code})")

    def _show_preview_window(self, questions_info, preserve_existing: bool = False):
        preview_win = tk.Toplevel(self.root)
        preview_win.title("问卷预览")
        preview_win.geometry("900x600")
        
        frame = ttk.Frame(preview_win, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text=f"问卷共 {len(questions_info)} 题", font=("TkDefaultFont", 11, "bold")).pack(pady=(0, 10))
        
        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        columns = ("num", "title", "type", "details", "page")
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=20)
        tree.heading("num", text="题号")
        tree.heading("title", text="题目标题")
        tree.heading("type", text="题型")
        tree.heading("details", text="详情")
        tree.heading("page", text="页码")
        
        tree.column("num", width=50, anchor="center")
        tree.column("title", width=400, anchor="w")
        tree.column("type", width=120, anchor="center")
        tree.column("details", width=180, anchor="center")
        tree.column("page", width=60, anchor="center")
        
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        for q in questions_info:
            details = ""
            if q["type_code"] == "6":
                details = f"{q['rows']}行 × {q['options']}列"
            elif q["type_code"] in ("3", "4", "5", "7"):
                details = f"{q['options']}个选项"
            elif q["type_code"] in ("1", "2"):
                details = "文本输入"
            elif q["type_code"] == "8":
                details = "滑块(1-100)"
            elif q["type_code"] == "11":
                details = "拖拽排序"
            
            tree.insert("", "end", values=(
                q["num"],
                q["title"][:80] + "..." if len(q["title"]) > 80 else q["title"],
                q["type"],
                details,
                f"第{q['page']}页"
            ))
        
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=(10, 0))
        
        wizard_btn = ttk.Button(
            btn_frame,
            text="开始配置题目",
            command=lambda: self._start_config_wizard(questions_info, preview_win, preserve_existing=preserve_existing),
        )
        wizard_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(btn_frame, text="关闭", command=preview_win.destroy).pack(side=tk.LEFT, padx=5)

    def _normalize_question_identifier(self, value: Optional[Union[str, int]]) -> Optional[str]:
        if value is None:
            return None
        try:
            normalized = str(value).strip()
            return normalized or None
        except Exception:
            return None

    def _find_entry_index_by_question(self, question_id: Optional[str]) -> Optional[int]:
        if not question_id:
            return None
        for idx, entry in enumerate(self.question_entries):
            if entry.question_num == question_id:
                return idx
        return None

    def _handle_auto_config_entry(self, entry: QuestionEntry, question_meta: Optional[Dict[str, Any]] = None):
        question_id = None
        question_title = ""
        if question_meta:
            question_id = self._normalize_question_identifier(question_meta.get("num"))
            question_title = question_meta.get("title", "")
        entry.question_num = question_id
        conflict_index = self._find_entry_index_by_question(question_id)
        if conflict_index is not None:
            question_label = f"第 {question_id} 题" if question_id else "该题目"
            title_suffix = f"「{question_title[:40]}{'...' if len(question_title) > 40 else ''}」" if question_title else ""
            message = (
                f"{question_label}{title_suffix} 已存在配置。\n\n"
                f"选择“是”：覆盖已有配置并使用最新设置。\n"
                f"选择“否”：跳过本题保留原配置。"
            )
            overwrite = self._log_popup_confirm("检测到重复配置", message, icon="question")
            if overwrite:
                previous_entry = deepcopy(self.question_entries[conflict_index])
                self.question_entries[conflict_index] = entry
                self._wizard_commit_log.append(
                    {"action": "replace", "index": conflict_index, "previous": previous_entry}
                )
                logging.info(f"[Action Log] Wizard overwrote configuration for question {question_id or '?'}")
            else:
                self._wizard_commit_log.append({"action": "skip"})
                logging.info(f"[Action Log] Wizard skipped configuring question {question_id or '?'}")
            return
        self.question_entries.append(entry)
        self._wizard_commit_log.append({"action": "append", "index": len(self.question_entries) - 1})
        logging.info(f"[Action Log] Wizard stored configuration (total={len(self.question_entries)})")

    def _revert_last_wizard_action(self):
        if not self._wizard_commit_log:
            return
        action = self._wizard_commit_log.pop()
        action_type = action.get("action")
        if action_type == "append":
            idx = action.get("index")
            if idx is not None and 0 <= idx < len(self.question_entries):
                self.question_entries.pop(idx)
        elif action_type == "replace":
            idx = action.get("index")
            previous_entry = action.get("previous")
            if (
                idx is not None
                and previous_entry is not None
                and 0 <= idx < len(self.question_entries)
                and isinstance(previous_entry, QuestionEntry)
            ):
                self.question_entries[idx] = previous_entry
        elif action_type == "skip":
            pass

    def _start_config_wizard(self, questions_info, preview_win, preserve_existing: bool = False):
        preview_win.destroy()
        if not preserve_existing:
            self.question_entries.clear()
        self._wizard_history = []
        self._wizard_commit_log = []
        self._show_wizard_for_question(questions_info, 0)

    def _get_wizard_hint_text(self, type_code: str) -> str:
        """为不同题型提供面向用户的操作提示文本。"""
        hints = {
            "1": "填空题建议准备 2~5 个真实可用的答案，点击“添加答案”即可增加内容，后续执行会在这些答案中随机选择。",
            "2": "多行填空通常用于意见反馈，可输入若干句式或话术，系统会自动随机抽取并填写。",
            "3": "单选题可直接选择完全随机，也可以切换到自定义权重，将高频选项的滑块调高即可。",
            "4": "多选题常需要控制命中率，拖动每个选项的百分比滑块即可直观设置被勾选的概率。",
            "5": "量表题本质类似单选题，若某些分值更常见，可使用自定义权重突出这些分值。",
            "6": "矩阵题按“行 × 列”处理，每列的权重决定更倾向选择哪一列，可先整体确定策略再微调滑块。",
            "7": "下拉题与单选题一致：先选择随机/自定义，再视需要为特定选项设置额外填空内容。",
        }
        default = "确认题干后，根据下方输入区域逐步设置答案或权重，完成后点击“下一题”即可保存。"
        return hints.get(type_code, default)

    def _show_wizard_for_question(self, questions_info, current_index):
        if current_index >= len(questions_info):
            self._refresh_tree()
            logging.info(f"[Action Log] Wizard finished with {len(self.question_entries)} configured questions")
            self._log_popup_info("完成",
                              f"配置完成！\n\n"
                              f"已配置 {len(self.question_entries)} 道题目。\n"
                              f"可在下方题目列表中查看和编辑。")
            self._wizard_history.clear()
            self._wizard_commit_log.clear()
            return
        
        q = questions_info[current_index]
        type_code = q["type_code"]
        detected_fillable_indices = q.get('fillable_options') or []

        if type_code in ("8", "11"):
            self._show_wizard_for_question(questions_info, current_index + 1)
            return

        self._wizard_history.append(current_index)
        
        wizard_win = tk.Toplevel(self.root)
        wizard_win.title(f"配置向导 - 第 {current_index + 1}/{len(questions_info)} 题")
        wizard_win.geometry("800x600")
        wizard_win.minsize(700, 500)  # 设置最小尺寸，防止窗口过小
        wizard_win.transient(self.root)
        wizard_win.grab_set()

        # 创建可滚动的内容区域
        canvas = tk.Canvas(wizard_win, highlightthickness=0)
        scrollbar = ttk.Scrollbar(wizard_win, orient="vertical", command=canvas.yview)
        frame = ttk.Frame(canvas, padding=15)
        
        # 让 frame 的宽度跟随 Canvas 的宽度
        canvas_window = canvas.create_window((0, 0), window=frame, anchor="nw")
        
        def on_frame_configure(event=None):
            # 更新滚动区域
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        def on_canvas_configure(event=None):
            # 让 frame 宽度适应 canvas 宽度
            canvas_width = canvas.winfo_width()
            if canvas_width > 1:  # 避免初始化时宽度为1
                canvas.itemconfig(canvas_window, width=canvas_width)
        
        frame.bind("<Configure>", on_frame_configure)
        canvas.bind("<Configure>", on_canvas_configure)
        
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 绑定鼠标滚轮到 Canvas
        def _on_wizard_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        canvas.bind_all("<MouseWheel>", _on_wizard_mousewheel)
        
        def _cleanup_mousewheel():
            canvas.unbind_all("<MouseWheel>")
            wizard_win.destroy()
        
        wizard_win.protocol("WM_DELETE_WINDOW", _cleanup_mousewheel)
        
        progress_text = f"进度：已完成 {current_index + 1} / {len(questions_info)}"
        ttk.Label(frame, text=progress_text, foreground="gray").pack(anchor="w", fill=tk.X)

        readable_title = q.get("title") or "（该题暂无标题）"

        # 顶部信息卡片，集中展示题目关键属性
        header_card = tk.Frame(frame, bg="#f5f8ff", highlightbackground="#cddcfe", highlightthickness=1, bd=0)
        header_card.pack(fill=tk.X, pady=(10, 12))
        header_inner = tk.Frame(header_card, bg="#f5f8ff")
        header_inner.pack(fill=tk.X, padx=14, pady=10)

        tk.Label(
            header_inner,
            text=f"第 {q['num']} 题",
            font=("TkDefaultFont", 12, "bold"),
            fg="#1a237e",
            bg="#f5f8ff"
        ).pack(anchor="w", fill=tk.X)

        # 使用 wraplength 确保题目标题完整显示并自动换行
        title_label = tk.Label(
            header_inner,
            text=readable_title,
            font=("TkDefaultFont", 10),
            wraplength=680,
            justify="left",
            bg="#f5f8ff"
        )
        title_label.pack(pady=(4, 6), anchor="w", fill=tk.X)

        def update_title_wraplength(event=None):
            available = header_inner.winfo_width() or frame.winfo_width()
            wrap = max(240, available - 40)
            title_label.configure(wraplength=wrap)

        header_inner.bind("<Configure>", update_title_wraplength, add="+")

        meta_tokens = [f"题型：{q['type']}"]
        option_count = q.get("options")
        if option_count:
            unit = "选项" if type_code != "6" else "列"
            meta_tokens.append(f"{option_count} 个{unit}")
        if type_code == "6" and q.get("rows"):
            meta_tokens.append(f"{q['rows']} 行")
        if q.get("page"):
            meta_tokens.append(f"所属页面：第{q['page']}页")
        meta_text = " · ".join(meta_tokens)
        tk.Label(
            header_inner,
            text=meta_text,
            fg="#455a64",
            bg="#f5f8ff",
            justify="left"
        ).pack(anchor="w", fill=tk.X)

        if detected_fillable_indices:
            chip_frame = tk.Frame(header_inner, bg="#f5f8ff")
            chip_frame.pack(anchor="w", pady=(6, 0))
            tk.Label(
                chip_frame,
                text=f"已发现 {len(detected_fillable_indices)} 个选项含附加填空",
                bg="#e3f2fd",
                fg="#0d47a1",
                font=("TkDefaultFont", 9),
                padx=10,
                pady=2
            ).pack(side=tk.LEFT)

        helper_text = self._get_wizard_hint_text(type_code)
        if helper_text:
            helper_box = tk.Frame(frame, bg="#fff8e1", highlightbackground="#ffe082", highlightthickness=1)
            helper_box.pack(fill=tk.X, pady=(0, 12))
            tk.Label(
                helper_box,
                text=helper_text,
                bg="#fff8e1",
                fg="#775800",
                justify="left",
                wraplength=710,
                padx=12,
                pady=8
            ).pack(fill=tk.X)
            if detected_fillable_indices:
                tk.Label(
                    helper_box,
                    text="贴士：保留为空时系统会写入“无”，便于顺利提交。",
                    bg="#fff8e1",
                    fg="#946200",
                    justify="left",
                    padx=12
                ).pack(fill=tk.X, pady=(0, 6))

        option_texts_in_question = q.get('option_texts', [])

        def _build_fillable_inputs() -> Tuple[List[Optional[tk.StringVar]], Callable[[ttk.Frame, int], None]]:
            option_total = q.get('options') or 0
            valid_indices = {idx for idx in detected_fillable_indices if isinstance(idx, int) and 0 <= idx < option_total}
            if option_total <= 0 or not valid_indices:
                return [], lambda *_: None

            fill_vars: List[Optional[tk.StringVar]] = [None] * option_total

            def attach_inline(parent_frame: ttk.Frame, opt_index: int):
                if opt_index not in valid_indices or opt_index < 0 or opt_index >= option_total:
                    return
                inline_row = ttk.Frame(parent_frame)
                inline_row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(2, 4))
                ttk.Label(inline_row, text="附加填空：").pack(side=tk.LEFT)
                var = tk.StringVar(value='')
                ttk.Entry(inline_row, textvariable=var, width=32).pack(side=tk.LEFT, padx=(6, 6), fill=tk.X, expand=True)
                ttk.Label(inline_row, text='留空将自动填“无”', foreground='gray').pack(side=tk.LEFT)
                fill_vars[opt_index] = var

            return fill_vars, attach_inline

        def _collect_fill_values(fill_vars: List[Optional[tk.StringVar]]) -> Optional[List[Optional[str]]]:
            if not fill_vars:
                return None
            collected: List[Optional[str]] = []
            has_value = False
            for var in fill_vars:
                if var is None:
                    collected.append(None)
                    continue
                value = var.get().strip()
                if value:
                    has_value = True
                    collected.append(value)
                else:
                    has_value = True
                    collected.append(DEFAULT_FILL_TEXT)

            return collected if has_value else None

        config_frame = ttk.Frame(frame)
        config_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        def skip_question():
            self._wizard_commit_log.append({"action": "skip"})
            wizard_win.destroy()
            self._show_wizard_for_question(questions_info, current_index + 1)
        
        if type_code in ("1", "2"):
            ttk.Label(config_frame, text="填空答案列表：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=5, fill=tk.X)
            
            answer_vars = []
            answers_inner_frame = ttk.Frame(config_frame)
            answers_inner_frame.pack(fill=tk.BOTH, expand=True, pady=10)
            
            def add_answer_field(initial_value=""):
                row_frame = ttk.Frame(answers_inner_frame)
                row_frame.pack(fill=tk.X, pady=3, padx=5)
                
                ttk.Label(row_frame, text=f"答案{len(answer_vars)+1}:", width=8).pack(side=tk.LEFT)
                
                var = tk.StringVar(value=initial_value)
                entry_widget = ttk.Entry(row_frame, textvariable=var, width=35)
                entry_widget.pack(side=tk.LEFT, padx=5)
                
                def remove_field():
                    row_frame.destroy()
                    answer_vars.remove(var)
                    update_labels()
                
                if len(answer_vars) > 0:
                    ttk.Button(row_frame, text="✖", width=3, command=remove_field).pack(side=tk.LEFT)
                
                answer_vars.append(var)
                return var
            
            def update_labels():
                for i, child in enumerate(answers_inner_frame.winfo_children()):
                    if child.winfo_children():
                        label = child.winfo_children()[0]
                        if isinstance(label, ttk.Label):
                            label.config(text=f"答案{i+1}:")
            
            add_answer_field("")
            
            add_btn_frame = ttk.Frame(config_frame)
            add_btn_frame.pack(fill=tk.X, pady=(5, 0))
            ttk.Button(add_btn_frame, text="➕ 添加答案", command=lambda: add_answer_field()).pack(anchor="w")
            
            def save_and_next():
                values = [var.get().strip() for var in answer_vars if var.get().strip()]
                if not values:
                    self._log_popup_error("错误", "请填写至少一个答案")
                    return
                entry = QuestionEntry(
                    question_type="text",
                    probabilities=normalize_probabilities([1.0] * len(values)),
                    texts=values,
                    rows=1,
                    option_count=len(values),
                    distribution_mode="equal",
                    custom_weights=None
                )
                self._handle_auto_config_entry(entry, q)
                wizard_win.destroy()
                self._show_wizard_for_question(questions_info, current_index + 1)
        
        elif type_code == "4":
            ttk.Label(config_frame, text=f"多选题（共 {q['options']} 个选项）").pack(anchor="w", pady=5, fill=tk.X)
            ttk.Label(config_frame, text="拖动滑块设置每个选项的选中概率：",
                     foreground="gray").pack(anchor="w", pady=5, fill=tk.X)

            sliders_frame = ttk.Frame(config_frame)
            sliders_frame.pack(fill=tk.BOTH, expand=True, pady=10)

            sliders = []
            fill_text_vars, attach_inline_fill = _build_fillable_inputs()
            for i in range(q['options']):
                row_frame = ttk.Frame(sliders_frame)
                row_frame.pack(fill=tk.X, pady=4, padx=(10, 20))
                row_frame.columnconfigure(1, weight=1)

                option_text = ""
                if i < len(q.get('option_texts', [])) and q['option_texts'][i]:
                    option_text = q['option_texts'][i]

                text_label = ttk.Label(row_frame, text=f"选项 {i+1}: {option_text}" if option_text else f"选项 {i+1}",
                                       anchor="w", wraplength=500)
                text_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 2))

                var = tk.DoubleVar(value=50.0)
                slider = ttk.Scale(row_frame, from_=0, to=100, variable=var, orient=tk.HORIZONTAL)
                slider.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(20, 5))

                label = ttk.Label(row_frame, text="50%", width=6, anchor="e")
                label.grid(row=1, column=2, sticky="e")

                var.trace_add("write", lambda *args, l=label, v=var: l.config(text=f"{int(v.get())}%"))
                sliders.append(var)

                attach_inline_fill(row_frame, i)

            def save_and_next():
                probs = [var.get() for var in sliders]
                option_texts_list = q.get('option_texts', [])
                fill_values = _collect_fill_values(fill_text_vars)
                entry = QuestionEntry(
                    question_type="multiple",
                    probabilities=probs,
                    texts=option_texts_list if option_texts_list else None,
                    rows=1,
                    option_count=q['options'],
                    distribution_mode="custom",
                    custom_weights=probs,
                    option_fill_texts=fill_values,
                    fillable_option_indices=detected_fillable_indices if detected_fillable_indices else None
                )
                self._handle_auto_config_entry(entry, q)
                wizard_win.destroy()
                self._show_wizard_for_question(questions_info, current_index + 1)
        
        else:
            option_text = f"共 {q['options']} 个选项"
            if type_code == "6":
                option_text = f"{q['rows']} 行 × {q['options']} 列"
            ttk.Label(config_frame, text=option_text).pack(anchor="w", pady=10, fill=tk.X)

            if type_code == "6" and q.get('option_texts'):
                ttk.Label(config_frame, text="列标题：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(5, 0), fill=tk.X)
                options_info_text = " | ".join([f"{i+1}: {text[:20]}{'...' if len(text) > 20 else ''}" for i, text in enumerate(q['option_texts'])])
                ttk.Label(config_frame, text=options_info_text, foreground="gray", wraplength=700).pack(anchor="w", pady=(0, 10), fill=tk.X)
            elif q.get('option_texts'):
                ttk.Label(config_frame, text="选项列表：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(5, 0), fill=tk.X)
                options_list_frame = ttk.Frame(config_frame)
                options_list_frame.pack(anchor="w", fill=tk.X, pady=(0, 10), padx=(20, 0))

                max_options_display = min(5, len(q['option_texts']))
                for i in range(max_options_display):
                    option_lbl = ttk.Label(options_list_frame, text=f"  • {q['option_texts'][i]}",
                                          foreground="gray", wraplength=650)
                    option_lbl.pack(anchor="w", fill=tk.X)

                if len(q['option_texts']) > 5:
                    ttk.Label(options_list_frame, text=f"  ... 共 {len(q['option_texts'])} 个选项", foreground="gray").pack(anchor="w", fill=tk.X)

            ttk.Label(config_frame, text="选择分布方式：").pack(anchor="w", pady=10, fill=tk.X)

            dist_var = tk.StringVar(value="random")

            weight_frame = ttk.Frame(config_frame)

            ttk.Radiobutton(config_frame, text="完全随机（每次随机选择）",
                          variable=dist_var, value="random",
                          command=lambda: weight_frame.pack_forget()).pack(anchor="w", pady=5, fill=tk.X)
            ttk.Radiobutton(config_frame, text="自定义权重（使用滑块设置）",
                          variable=dist_var, value="custom",
                          command=lambda: weight_frame.pack(fill=tk.BOTH, expand=True, pady=10)).pack(anchor="w", pady=5, fill=tk.X)

            ttk.Label(weight_frame, text="拖动滑块设置每个选项的权重比例：",
                     foreground="gray").pack(anchor="w", pady=(10, 5), fill=tk.X)

            sliders_weight_frame = ttk.Frame(weight_frame)
            sliders_weight_frame.pack(fill=tk.BOTH, expand=True)

            slider_vars = []
            fill_text_vars: List[Optional[tk.StringVar]] = []
            attach_inline_fill: Callable[[ttk.Frame, int], None] = lambda *_: None
            if type_code in ("3", "7"):
                fill_text_vars, attach_inline_fill = _build_fillable_inputs()
            for i in range(q['options']):
                slider_frame = ttk.Frame(sliders_weight_frame)
                slider_frame.pack(fill=tk.X, pady=4, padx=(10, 20))
                slider_frame.columnconfigure(1, weight=1)

                option_text = ""
                if i < len(q.get('option_texts', [])) and q['option_texts'][i]:
                    option_text = q['option_texts'][i]

                text_label = ttk.Label(slider_frame, text=f"选项 {i+1}: {option_text}" if option_text else f"选项 {i+1}",
                                       anchor="w", wraplength=500)
                text_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 2))

                var = tk.DoubleVar(value=1.0)
                slider = ttk.Scale(slider_frame, from_=0, to=10, variable=var, orient=tk.HORIZONTAL)
                slider.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(20, 5))

                value_label = ttk.Label(slider_frame, text="1.0", width=6, anchor="e")
                value_label.grid(row=1, column=2, sticky="e")

                def update_label(v=var, l=value_label):
                    l.config(text=f"{v.get():.1f}")

                var.trace_add("write", lambda *args, v=var, l=value_label: update_label(v, l))
                slider_vars.append(var)

                attach_inline_fill(slider_frame, i)

            def save_and_next():
                mode = dist_var.get()
                q_type_map = {"3": "single", "5": "scale", "6": "matrix", "7": "dropdown"}
                q_type = q_type_map.get(type_code, "single")

                if mode == "random":
                    probs = -1
                    weights = None
                elif mode == "equal":
                    weights = [1.0] * q['options']
                    probs = normalize_probabilities(weights)
                else:
                    weights = [var.get() for var in slider_vars]
                    if all(w == 0 for w in weights):
                        self._log_popup_error("错误", "至少要有一个选项的权重大于0")
                        return
                    probs = normalize_probabilities(weights)
                fill_values = _collect_fill_values(fill_text_vars)

                entry = QuestionEntry(
                    question_type=q_type,
                    probabilities=probs,
                    texts=None,
                    rows=q['rows'] if type_code == "6" else 1,
                    option_count=q['options'],
                    distribution_mode=mode,
                    custom_weights=weights,
                    option_fill_texts=fill_values,
                    fillable_option_indices=detected_fillable_indices if detected_fillable_indices else None
                )
                self._handle_auto_config_entry(entry, q)
                wizard_win.destroy()
                self._show_wizard_for_question(questions_info, current_index + 1)
        
        # 按钮区域（固定在窗口底部）- 使用分隔线和更好的布局
        separator = ttk.Separator(wizard_win, orient='horizontal')
        separator.pack(side=tk.BOTTOM, fill=tk.X, before=canvas)
        
        btn_frame = ttk.Frame(wizard_win, padding=(15, 10, 15, 15))
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, before=separator)
        
        # 左侧按钮组
        left_btn_frame = ttk.Frame(btn_frame)
        left_btn_frame.pack(side=tk.LEFT, fill=tk.X)
        
        if current_index > 0:
            prev_btn = ttk.Button(left_btn_frame, text="← 上一题", width=10,
                      command=lambda: self._go_back_in_wizard(wizard_win, questions_info, current_index))
            prev_btn.pack(side=tk.LEFT, padx=(0, 8), pady=2)
        
        skip_btn = ttk.Button(left_btn_frame, text="跳过", width=8, command=skip_question)
        skip_btn.pack(side=tk.LEFT, padx=8, pady=2)
        
        next_btn = ttk.Button(left_btn_frame, text="下一题 →", width=10, command=save_and_next)
        next_btn.pack(side=tk.LEFT, padx=8, pady=2)
        
        # 右侧取消按钮
        cancel_btn = ttk.Button(btn_frame, text="取消向导", width=10, command=_cleanup_mousewheel)
        cancel_btn.pack(side=tk.RIGHT, padx=(8, 0), pady=2)

    def _go_back_in_wizard(self, current_win, questions_info, current_index):
        if self._wizard_history and self._wizard_history[-1] == current_index:
            self._wizard_history.pop()
        prev_index = 0
        if self._wizard_history:
            prev_index = self._wizard_history.pop()
        self._revert_last_wizard_action()
        current_win.destroy()
        self._show_wizard_for_question(questions_info, prev_index)

    def start_run(self):
        url_value = self.url_var.get().strip()
        if not url_value:
            self._log_popup_error("参数错误", "请填写问卷链接")
            return
        if not self._validate_wjx_url(url_value):
            return
        target_value = self.target_var.get().strip()
        full_sim_enabled = bool(self.full_simulation_enabled_var.get())
        if full_sim_enabled:
            target_value = self.full_sim_target_var.get().strip()
            if not target_value:
                self._log_popup_error("参数错误", "请在全真模拟设置中填写目标份数")
                return
            self.target_var.set(target_value)
        if not target_value:
            self._log_popup_error("参数错误", "目标份数不能为空")
            return
        try:
            target = int(target_value)
            threads_count = int(self.thread_var.get().strip() or "0")
            if target <= 0 or threads_count <= 0:
                raise ValueError
        except ValueError:
            self._log_popup_error("参数错误", "目标份数和线程数必须为正整数")
            return
        minute_text = self.interval_minutes_var.get().strip()
        second_text = self.interval_seconds_var.get().strip()
        max_minute_text = self.interval_max_minutes_var.get().strip()
        max_second_text = self.interval_max_seconds_var.get().strip()
        answer_min_text = self.answer_duration_min_var.get().strip()
        answer_max_text = self.answer_duration_max_var.get().strip()
        full_sim_est_min_text = self.full_sim_estimated_minutes_var.get().strip()
        full_sim_est_sec_text = self.full_sim_estimated_seconds_var.get().strip()
        full_sim_total_min_text = self.full_sim_total_minutes_var.get().strip()
        full_sim_total_sec_text = self.full_sim_total_seconds_var.get().strip()
        try:
            interval_minutes = int(minute_text) if minute_text else 0
            interval_seconds = int(second_text) if second_text else 0
            interval_max_minutes = int(max_minute_text) if max_minute_text else 0
            interval_max_seconds = int(max_second_text) if max_second_text else 0
        except ValueError:
            self._log_popup_error("参数错误", "提交间隔请输入整数分钟和秒")
            return
        try:
            answer_min_seconds = int(answer_min_text) if answer_min_text else 0
            answer_max_seconds = int(answer_max_text) if answer_max_text else 0
        except ValueError:
            self._log_popup_error("参数错误", "作答时长请输入整数秒")
            return
        full_sim_est_seconds = 0
        full_sim_total_seconds = 0
        if full_sim_enabled:
            try:
                est_minutes = int(full_sim_est_min_text) if full_sim_est_min_text else 0
                est_seconds = int(full_sim_est_sec_text) if full_sim_est_sec_text else 0
                total_minutes = int(full_sim_total_min_text) if full_sim_total_min_text else 0
                total_seconds = int(full_sim_total_sec_text) if full_sim_total_sec_text else 0
            except ValueError:
                self._log_popup_error("参数错误", "全真模拟时间请输入整数")
                return
            if est_minutes < 0 or est_seconds < 0 or total_minutes < 0 or total_seconds < 0:
                self._log_popup_error("参数错误", "全真模拟时间不允许为负数")
                return
            if est_seconds >= 60 or total_seconds >= 60:
                self._log_popup_error("参数错误", "全真模拟时间中的秒数应在 0-59 之间")
                return
            full_sim_est_seconds = est_minutes * 60 + est_seconds
            full_sim_total_seconds = total_minutes * 60 + total_seconds
            if full_sim_est_seconds <= 0:
                self._log_popup_error("参数错误", "请填写预计单次作答时长")
                return
            if full_sim_total_seconds <= 0:
                self._log_popup_error("参数错误", "请填写模拟总时长")
                return
            if threads_count != 1:
                threads_count = 1
                self.thread_var.set("1")
                logging.info("全真模拟模式强制使用单线程执行")
        max_fields_empty = (not max_minute_text) and (not max_second_text)
        if interval_minutes < 0 or interval_seconds < 0 or interval_max_minutes < 0 or interval_max_seconds < 0:
            self._log_popup_error("参数错误", "提交间隔必须为非负数")
            return
        if interval_seconds >= 60 or interval_max_seconds >= 60:
            self._log_popup_error("参数错误", "秒数范围应为 0-59")
            return
        if answer_min_seconds < 0 or answer_max_seconds < 0:
            self._log_popup_error("参数错误", "作答时长必须为非负秒数")
            return
        if answer_max_seconds < answer_min_seconds:
            self._log_popup_error("参数错误", "最长作答时长需大于或等于最短作答时长")
            return
        if full_sim_enabled and full_sim_total_seconds < full_sim_est_seconds * max(1, target):
            logging.warning("全真模拟总时长可能偏短，作答间隔会自动压缩以完成既定份数")
        interval_total_seconds = interval_minutes * 60 + interval_seconds
        max_interval_total_seconds = (
            interval_total_seconds
            if max_fields_empty
            else interval_max_minutes * 60 + interval_max_seconds
        )
        if max_interval_total_seconds < interval_total_seconds:
            max_interval_total_seconds = interval_total_seconds
            self.interval_max_minutes_var.set(str(interval_minutes))
            self.interval_max_seconds_var.set(str(interval_seconds))
        if not self.question_entries:
            msg = (
                "当前尚未配置任何题目。\n\n"
                "是否先预览问卷页面以确认题目？\n"
                "选择“是”：立即打开预览窗口，不会开始执行。\n"
                "选择“否”：直接开始执行（默认随机填写/跳过未配置题目）。"
            )
            if self._log_popup_confirm("提示", msg):
                self.preview_survey()
                return
        try:
            configure_probabilities(self.question_entries)
        except ValueError as exc:
            self._log_popup_error("配置错误", str(exc))
            return

        logging.info(
            f"[Action Log] Starting run url={url_value} target={target} threads={threads_count}"
        )

        global url, target_num, num_threads, fail_threshold, cur_num, cur_fail, stop_event, submit_interval_range_seconds, answer_duration_range_seconds, full_simulation_enabled, full_simulation_estimated_seconds, full_simulation_total_duration_seconds, full_simulation_schedule
        url = url_value
        target_num = target
        num_threads = threads_count
        submit_interval_range_seconds = (interval_total_seconds, max_interval_total_seconds)
        answer_duration_range_seconds = (answer_min_seconds, answer_max_seconds)
        full_simulation_enabled = full_sim_enabled
        if full_sim_enabled:
            full_simulation_estimated_seconds = full_sim_est_seconds
            full_simulation_total_duration_seconds = full_sim_total_seconds
            schedule = _prepare_full_simulation_schedule(target, full_sim_total_seconds)
            if not schedule:
                self._log_popup_error("参数错误", "模拟时间设置无效")
                return
            full_simulation_schedule = schedule
        else:
            full_simulation_estimated_seconds = 0
            full_simulation_total_duration_seconds = 0
            _reset_full_simulation_runtime_state()
        fail_threshold = max(1, math.ceil(target_num / 4) + 1)
        cur_num = 0
        cur_fail = 0
        stop_event = threading.Event()
        
        # 重置进度条
        self.progress_value = 0
        self.total_submissions = target
        self.current_submissions = 0
        self.progress_bar['value'] = 0
        self.progress_label.config(text="0%")

        self.running = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.status_var.set("正在启动浏览器...")

        self.runner_thread = Thread(target=self._launch_threads, daemon=True)
        self.runner_thread.start()
        self._schedule_status_update()

    def _launch_threads(self):
        print(f"正在启动 {num_threads} 个浏览器窗口...")
        threads: List[Thread] = []
        for browser_index in range(num_threads):
            window_x = 50 + browser_index * 60
            window_y = 50
            thread = Thread(target=run, args=(window_x, window_y, stop_event, self), daemon=True)
            threads.append(thread)
        for thread in threads:
            thread.start()
            time.sleep(0.1)
        print("浏览器启动中，请稍候...")
        for thread in threads:
            thread.join()
        self.worker_threads = threads
        self.root.after(0, self._on_run_finished)

    def _schedule_status_update(self):
        status = f"已提交 {cur_num}/{target_num} 份 | 失败 {cur_fail} 次"
        self.status_var.set(status)
        
        # 更新进度条
        if target_num > 0:
            progress = int((cur_num / target_num) * 100)
            self.progress_bar['value'] = progress
            self.progress_label.config(text=f"{progress}%")
        
        if self.running:
            self.status_job = self.root.after(500, self._schedule_status_update)

    def _on_run_finished(self):
        self.running = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED, text="停止")
        if self.status_job:
            self.root.after_cancel(self.status_job)
            self.status_job = None
        if cur_num >= target_num:
            msg = "任务完成"
        elif stop_event.is_set():
            msg = "已停止"
        else:
            msg = "已结束"
        self.status_var.set(f"{msg} | 已提交 {cur_num}/{target_num} 份 | 失败 {cur_fail} 次")
        
        # 最终更新进度条
        if cur_num >= target_num:
            self.progress_bar['value'] = 100
            self.progress_label.config(text="100%")
        else:
            if target_num > 0:
                progress = int((cur_num / target_num) * 100)
                self.progress_bar['value'] = progress
                self.progress_label.config(text=f"{progress}%")

    def stop_run(self):
        if not self.running:
            return
        stop_event.set()
        self.running = False
        self.stop_button.config(state=tk.DISABLED, text="停止中...")
        self.status_var.set("已发送停止请求，正在等待当前任务结束...")
        if self.status_job:
            try:
                self.root.after_cancel(self.status_job)
            except Exception:
                pass
            self.status_job = None

        for driver in self.active_drivers:
            try:
                driver.quit()
            except:
                pass
        self.active_drivers.clear()
        logging.info("收到停止请求，等待当前提交线程完成")
        print("已暂停新的问卷提交，等待现有流程退出")

    def on_close(self):
        # 停止日志刷新
        if self._log_refresh_job:
            try:
                self.root.after_cancel(self._log_refresh_job)
            except Exception:
                pass
        
        self.stop_run()
        
        # 只有在配置有实质性改动时才提示保存
        if not self._has_config_changed():
            # 配置未改动，直接关闭
            if self._log_refresh_job:
                try:
                    self.root.after_cancel(self._log_refresh_job)
                except Exception:
                    pass
            self.root.destroy()
            return
        
        # 检查是否有问卷链接或题目配置
        has_url = bool(self.url_var.get().strip())
        has_questions = bool(self.question_entries)
        
        if has_url or has_questions:
            # 生成保存提示信息
            if has_questions:
                msg = f"是否保存配置以便下次使用？\n\n已配置 {len(self.question_entries)} 道题目"
            else:
                msg = "是否保存问卷链接以便下次使用？"
            
            # 创建自定义对话框，包含保存、不保存、取消三个按钮
            dialog = tk.Toplevel(self.root)
            dialog.title("保存配置")
            dialog.geometry("300x150")
            dialog.resizable(False, False)
            dialog.transient(self.root)
            dialog.grab_set()
            
            # 居中显示对话框
            dialog.update_idletasks()
            dialog_width = dialog.winfo_width()
            dialog_height = dialog.winfo_height()
            screen_width = dialog.winfo_screenwidth()
            screen_height = dialog.winfo_screenheight()
            
            try:
                import ctypes
                from ctypes.wintypes import RECT
                work_area = RECT()
                ctypes.windll.user32.SystemParametersInfoA(48, 0, ctypes.byref(work_area), 0)
                work_width = work_area.right - work_area.left
                work_height = work_area.bottom - work_area.top
                work_x = work_area.left
                work_y = work_area.top
                x = work_x + (work_width - dialog_width) // 2
                y = work_y + (work_height - dialog_height) // 2
            except:
                x = (screen_width - dialog_width) // 2
                y = (screen_height - dialog_height) // 2
            
            x = max(0, x)
            y = max(0, y)
            dialog.geometry(f"+{x}+{y}")
            
            # 消息标签
            ttk.Label(dialog, text=msg, wraplength=280, justify=tk.CENTER).pack(pady=20)
            
            # 按钮容器
            button_frame = ttk.Frame(dialog)
            button_frame.pack(pady=(0, 10))
            
            # 结果变量
            result = tk.IntVar(value=None)
            
            def save_config():
                saved = self._save_config_as_dialog(show_popup=False)
                if not saved:
                    return
                logging.info("[Action Log] Saved configuration via dialog before exit")
                result.set(1)
                dialog.destroy()
                if self._log_refresh_job:
                    try:
                        self.root.after_cancel(self._log_refresh_job)
                    except Exception:
                        pass
                self.root.destroy()
            
            def discard_config():
                # 不保存时，保持现有的config文件不删除，下次打开时会读取之前保存的config
                logging.info("[Action Log] Discarded new changes, keeping previous configuration")
                result.set(0)
                dialog.destroy()
                if self._log_refresh_job:
                    try:
                        self.root.after_cancel(self._log_refresh_job)
                    except Exception:
                        pass
                self.root.destroy()
            
            def cancel_close():
                logging.info("[Action Log] Cancelled exit")
                result.set(-1)
                dialog.destroy()
            
            ttk.Button(button_frame, text="保存", command=save_config, width=10).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame, text="不保存", command=discard_config, width=10).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame, text="取消", command=cancel_close, width=10).pack(side=tk.LEFT, padx=5)
            
            # 焦点设置到取消按钮作为默认
            dialog.focus_set()
            
            return
        
        if self._log_refresh_job:
            try:
                self.root.after_cancel(self._log_refresh_job)
            except Exception:
                pass
        self.root.destroy()

    def _center_child_window(self, window: tk.Toplevel):
        """使指定窗口居中显示。"""
        try:
            window.update_idletasks()
            width = window.winfo_width()
            height = window.winfo_height()
            screen_width = window.winfo_screenwidth()
            screen_height = window.winfo_screenheight()
            x = max(0, (screen_width - width) // 2)
            y = max(0, (screen_height - height) // 2)
            window.geometry(f"+{int(x)}+{int(y)}")
        except Exception:
            pass

    def _center_window(self):
        """将窗口放在屏幕上方中央"""
        self.root.update_idletasks()
        
        # 获取窗口大小
        window_width = self.root.winfo_width()
        window_height = self.root.winfo_height()
        
        # 获取屏幕大小（包括任务栏）
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        # 在 Windows 上获取工作区（不包括任务栏）
        try:
            import ctypes
            from ctypes.wintypes import RECT
            
            # 获取工作区坐标
            work_area = RECT()
            ctypes.windll.user32.SystemParametersInfoA(48, 0, ctypes.byref(work_area), 0)
            
            work_width = work_area.right - work_area.left
            work_height = work_area.bottom - work_area.top
            work_x = work_area.left
            work_y = work_area.top
            
            # 使用工作区计算位置 - 水平居中，垂直放在上方
            x = work_x + (work_width - window_width) // 2
            y = max(work_y + 20, work_y + (work_height - window_height) // 5)
        except:
            # 如果获取工作区失败，回退到简单计算
            x = (screen_width - window_width) // 2
            y = max(20, (screen_height - window_height) // 5)
        
        # 确保坐标不为负数
        x = max(0, x)
        y = max(0, y)
        
        # 设置窗口位置
        self.root.geometry(f"+{x}+{y}")

    def _get_config_path(self) -> str:
        return os.path.join(_get_runtime_directory(), "config.json")

    def _get_configs_directory(self) -> str:
        """返回多配置保存目录，并在需要时创建。"""
        configs_dir = os.path.join(_get_runtime_directory(), "configs")
        os.makedirs(configs_dir, exist_ok=True)
        return configs_dir

    def _get_default_config_initial_name(self) -> str:
        """根据问卷标题生成默认的配置文件名。"""
        if self._last_survey_title:
            sanitized = _sanitize_filename(self._last_survey_title)
            if sanitized:
                return sanitized
        return f"wjx_config_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def _build_current_config_data(self) -> Dict[str, Any]:
        """收集当前界面上的配置数据。"""
        paned_sash_pos = None
        try:
            paned_sash_pos = self.main_paned.sashpos(0)
        except Exception:
            pass

        return {
            "url": self.url_var.get(),
            "target_num": self.target_var.get(),
            "num_threads": self.thread_var.get(),
            "submit_interval": self._serialize_submit_interval(),
            "answer_duration_range": self._serialize_answer_duration_config(),
            "full_simulation": self._serialize_full_simulation_config(),
            "paned_position": paned_sash_pos,
            "questions": [
                {
                    "question_type": entry.question_type,
                    "probabilities": entry.probabilities
                    if not isinstance(entry.probabilities, int)
                    else entry.probabilities,
                    "texts": entry.texts,
                    "rows": entry.rows,
                    "option_count": entry.option_count,
                    "distribution_mode": entry.distribution_mode,
                    "custom_weights": entry.custom_weights,
                    "question_num": entry.question_num,
                    "option_fill_texts": entry.option_fill_texts,
                    "fillable_option_indices": entry.fillable_option_indices,
                }
                for entry in self.question_entries
            ],
        }

    def _serialize_submit_interval(self) -> Dict[str, int]:
        def _normalize(value: Any, *, cap_seconds: bool = False) -> int:
            try:
                text = str(value).strip()
            except Exception:
                text = ""
            if not text:
                parsed = 0
            else:
                try:
                    parsed = int(text)
                except ValueError:
                    parsed = 0
            parsed = max(0, parsed)
            if cap_seconds:
                parsed = min(59, parsed)
            return parsed

        minutes_text = self.interval_minutes_var.get()
        seconds_text = self.interval_seconds_var.get()
        max_minutes_text = self.interval_max_minutes_var.get()
        max_seconds_text = self.interval_max_seconds_var.get()

        minutes = _normalize(minutes_text)
        seconds = _normalize(seconds_text, cap_seconds=True)
        max_minutes = _normalize(max_minutes_text, cap_seconds=False)
        max_seconds = _normalize(max_seconds_text, cap_seconds=True)

        min_total = minutes * 60 + seconds
        max_total = max_minutes * 60 + max_seconds
        if (not str(max_minutes_text).strip() and not str(max_seconds_text).strip()) or max_total < min_total:
            max_minutes, max_seconds = minutes, seconds

        return {
            "minutes": minutes,
            "seconds": seconds,
            "max_minutes": max_minutes,
            "max_seconds": max_seconds,
        }

    def _serialize_answer_duration_config(self) -> Dict[str, int]:
        def _normalize(value: Any) -> int:
            try:
                text = str(value).strip()
            except Exception:
                text = ""
            if not text:
                parsed = 0
            else:
                try:
                    parsed = int(text)
                except ValueError:
                    parsed = 0
            return max(0, parsed)

        min_seconds = _normalize(self.answer_duration_min_var.get())
        max_seconds = _normalize(self.answer_duration_max_var.get())
        if max_seconds < min_seconds:
            max_seconds = min_seconds
        return {"min_seconds": min_seconds, "max_seconds": max_seconds}

    def _serialize_full_simulation_config(self) -> Dict[str, Any]:
        def _normalize(value: Any, *, cap_seconds: bool = False) -> int:
            try:
                text = str(value).strip()
            except Exception:
                text = ""
            if not text:
                parsed = 0
            else:
                try:
                    parsed = int(text)
                except ValueError:
                    parsed = 0
            parsed = max(0, parsed)
            if cap_seconds:
                parsed = min(59, parsed)
            return parsed

        return {
            "enabled": bool(self.full_simulation_enabled_var.get()),
            "target": _normalize(self.full_sim_target_var.get()),
            "estimated_minutes": _normalize(self.full_sim_estimated_minutes_var.get()),
            "estimated_seconds": _normalize(self.full_sim_estimated_seconds_var.get(), cap_seconds=True),
            "total_minutes": _normalize(self.full_sim_total_minutes_var.get()),
            "total_seconds": _normalize(self.full_sim_total_seconds_var.get(), cap_seconds=True),
        }

    def _apply_submit_interval_config(self, interval_config: Optional[Dict[str, Any]]):
        if not isinstance(interval_config, dict):
            interval_config = {}

        def _format_value(raw_value: Any, *, cap_seconds: bool = False) -> str:
            try:
                text = str(raw_value).strip()
            except Exception:
                text = ""
            if not text:
                parsed = 0
            else:
                try:
                    parsed = int(text)
                except ValueError:
                    parsed = 0
            parsed = max(0, parsed)
            if cap_seconds:
                parsed = min(59, parsed)
            return str(parsed)

        minutes_value = interval_config.get("minutes")
        seconds_value = interval_config.get("seconds")
        max_minutes_value = interval_config.get("max_minutes")
        max_seconds_value = interval_config.get("max_seconds")

        if max_minutes_value is None and max_seconds_value is None:
            max_minutes_value = minutes_value
            max_seconds_value = seconds_value

        self.interval_minutes_var.set(_format_value(minutes_value))
        self.interval_seconds_var.set(_format_value(seconds_value, cap_seconds=True))
        self.interval_max_minutes_var.set(_format_value(max_minutes_value if max_minutes_value is not None else minutes_value))
        self.interval_max_seconds_var.set(
            _format_value(
                max_seconds_value if max_seconds_value is not None else seconds_value,
                cap_seconds=True,
            )
        )

    def _apply_answer_duration_config(self, config: Optional[Dict[str, Any]]):
        if not isinstance(config, dict):
            config = {}

        def _format_value(raw_value: Any) -> str:
            try:
                text = str(raw_value).strip()
            except Exception:
                text = ""
            if not text:
                parsed = 0
            else:
                try:
                    parsed = int(text)
                except ValueError:
                    parsed = 0
            return str(max(0, parsed))

        self.answer_duration_min_var.set(_format_value(config.get("min_seconds")))
        self.answer_duration_max_var.set(_format_value(config.get("max_seconds")))

    def _apply_full_simulation_config(self, config: Optional[Dict[str, Any]]):
        if not isinstance(config, dict):
            config = {}

        def _format(raw_value: Any, *, cap_seconds: bool = False) -> str:
            try:
                text = str(raw_value).strip()
            except Exception:
                text = ""
            if not text:
                parsed = 0
            else:
                try:
                    parsed = int(text)
                except ValueError:
                    parsed = 0
            parsed = max(0, parsed)
            if cap_seconds:
                parsed = min(59, parsed)
            return str(parsed)

        self.full_simulation_enabled_var.set(bool(config.get("enabled")))
        self.full_sim_target_var.set(_format(config.get("target")))
        self.full_sim_estimated_minutes_var.set(_format(config.get("estimated_minutes")))
        self.full_sim_estimated_seconds_var.set(_format(config.get("estimated_seconds"), cap_seconds=True))
        self.full_sim_total_minutes_var.set(_format(config.get("total_minutes")))
        self.full_sim_total_seconds_var.set(_format(config.get("total_seconds"), cap_seconds=True))

    def _write_config_file(self, file_path: str, config_data: Optional[Dict[str, Any]] = None):
        """将配置写入指定文件。"""
        config_to_save = config_data if config_data is not None else self._build_current_config_data()
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(config_to_save, f, ensure_ascii=False, indent=2)

    def _save_config(self):
        try:
            self._write_config_file(self._get_config_path())
        except Exception as e:
            print(f"保存配置失败: {e}")

    def _apply_config_data(self, config: Dict[str, Any]):
        """将配置数据应用到界面。"""
        if not isinstance(config, dict):
            raise ValueError("配置文件格式不正确")

        self.url_var.set(config.get("url", ""))
        self.target_var.set(config.get("target_num", ""))
        self.thread_var.set(config.get("num_threads", ""))
        self._apply_submit_interval_config(config.get("submit_interval"))
        self._apply_answer_duration_config(config.get("answer_duration_range"))
        self._apply_full_simulation_config(config.get("full_simulation"))

        paned_position = config.get("paned_position")
        if paned_position is not None:
            try:
                desired_position = int(paned_position)
            except (TypeError, ValueError):
                desired_position = None
            if desired_position is not None:
                self._restore_saved_paned_position(desired_position)

        questions_data = config.get("questions") or []
        self.question_entries.clear()
        def _load_option_fill_texts_from_config(raw_value: Any) -> Optional[List[Optional[str]]]:
            if not isinstance(raw_value, list):
                return None
            normalized: List[Optional[str]] = []
            has_value = False
            for item in raw_value:
                if item is None:
                    normalized.append(None)
                    continue
                try:
                    text_value = str(item).strip()
                except Exception:
                    text_value = ""
                if text_value:
                    has_value = True
                    normalized.append(text_value)
                else:
                    normalized.append(None)
            return normalized if has_value else None

        def _load_fillable_indices_from_config(raw_value: Any) -> Optional[List[int]]:
            if not isinstance(raw_value, list):
                return None
            parsed: List[int] = []
            for item in raw_value:
                try:
                    index_value = int(item)
                except (TypeError, ValueError):
                    continue
                if index_value >= 0:
                    parsed.append(index_value)
            return parsed if parsed else None
        if isinstance(questions_data, list):
            for q_data in questions_data:
                entry = QuestionEntry(
                    question_type=q_data.get("question_type", "single"),
                    probabilities=q_data.get("probabilities", -1),
                    texts=q_data.get("texts"),
                    rows=q_data.get("rows", 1),
                    option_count=q_data.get("option_count", 0),
                    distribution_mode=q_data.get("distribution_mode", "random"),
                    custom_weights=q_data.get("custom_weights"),
                    question_num=q_data.get("question_num"),
                    option_fill_texts=_load_option_fill_texts_from_config(q_data.get("option_fill_texts")),
                    fillable_option_indices=_load_fillable_indices_from_config(q_data.get("fillable_option_indices")),
                )
                if entry.fillable_option_indices is None and entry.option_fill_texts:
                    derived = [idx for idx, value in enumerate(entry.option_fill_texts) if value]
                    entry.fillable_option_indices = derived if derived else None
                self.question_entries.append(entry)
        self._refresh_tree()

        self._save_initial_config()
        self._config_changed = False
        self._update_full_simulation_controls_state()
        self._update_parameter_widgets_state()

    def _load_config_from_file(self, file_path: str, *, silent: bool = False):
        """从指定路径加载配置。"""
        with open(file_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        self._apply_config_data(config)
        if not silent:
            print(f"已加载配置：{os.path.basename(file_path)}")

    def _load_config(self):
        config_path = self._get_config_path()
        if not os.path.exists(config_path):
            return

        should_load_last = True
        try:
            should_load_last = self._log_popup_confirm(
                "加载上次配置",
                "检测到上一次保存的配置。\n是否要继续加载该配置？"
            )
        except Exception as e:
            print(f"询问是否加载上次配置时出错，将默认加载：{e}")

        if not should_load_last:
            print("用户选择在启动时不加载上一次保存的配置")
            return

        try:
            self._load_config_from_file(config_path, silent=True)
            print(f"已加载上次配置：{len(self.question_entries)} 道题目")
        except Exception as e:
            print(f"加载配置失败: {e}")

    def _save_config_as_dialog(self, *, show_popup: bool = True) -> bool:
        """通过对话框保存配置到用户自定义文件。"""
        configs_dir = self._get_configs_directory()
        default_name = self._get_default_config_initial_name()
        file_path = filedialog.asksaveasfilename(
            parent=self.root,
            title="保存配置",
            defaultextension=".json",
            initialfile=f"{default_name}.json",
            initialdir=configs_dir,
            filetypes=(("JSON 配置文件", "*.json"), ("所有文件", "*.*")),
        )
        if not file_path:
            return False
        try:
            self._write_config_file(file_path)
            if show_popup:
                self._log_popup_info("保存配置", f"配置已保存到:\n{file_path}")
            return True
        except Exception as exc:
            logging.error(f"保存配置失败: {exc}")
            self._log_popup_error("保存配置失败", f"无法保存配置:\n{exc}")
            return False

    def _load_config_from_dialog(self):
        """通过对话框加载用户选择的配置文件。"""
        configs_dir = self._get_configs_directory()
        file_path = filedialog.askopenfilename(
            parent=self.root,
            title="加载配置",
            initialdir=configs_dir,
            filetypes=(("JSON 配置文件", "*.json"), ("所有文件", "*.*")),
        )
        if not file_path:
            return
        try:
            self._load_config_from_file(file_path)
            self._log_popup_info("加载配置", f"已加载配置:\n{file_path}")
        except Exception as exc:
            logging.error(f"加载配置失败: {exc}")
            self._log_popup_error("加载配置失败", f"无法加载配置:\n{exc}")

    def _save_initial_config(self):
        """保存初始配置状态以便检测后续变化"""
        self._initial_config = {
            "url": self.url_var.get(),
            "target_num": self.target_var.get(),
            "num_threads": self.thread_var.get(),
            "submit_interval": self._serialize_submit_interval(),
            "full_simulation": self._serialize_full_simulation_config(),
            "questions": [
                {
                    "question_type": entry.question_type,
                    "probabilities": entry.probabilities if not isinstance(entry.probabilities, int) else entry.probabilities,
                    "texts": entry.texts,
                    "rows": entry.rows,
                    "option_count": entry.option_count,
                    "distribution_mode": entry.distribution_mode,
                    "custom_weights": entry.custom_weights,
                    "question_num": entry.question_num,
                    "option_fill_texts": entry.option_fill_texts,
                    "fillable_option_indices": entry.fillable_option_indices,
                }
                for entry in self.question_entries
            ],
        }

    def _mark_config_changed(self):
        """标记配置已改动"""
        self._config_changed = True

    def _has_config_changed(self) -> bool:
        """检查配置是否有实质性改动"""
        current_config = {
            "url": self.url_var.get(),
            "target_num": self.target_var.get(),
            "num_threads": self.thread_var.get(),
            "submit_interval": self._serialize_submit_interval(),
            "full_simulation": self._serialize_full_simulation_config(),
            "questions": [
                {
                    "question_type": entry.question_type,
                    "probabilities": entry.probabilities if not isinstance(entry.probabilities, int) else entry.probabilities,
                    "texts": entry.texts,
                    "rows": entry.rows,
                    "option_count": entry.option_count,
                    "distribution_mode": entry.distribution_mode,
                    "custom_weights": entry.custom_weights,
                    "question_num": entry.question_num,
                    "option_fill_texts": entry.option_fill_texts,
                    "fillable_option_indices": entry.fillable_option_indices,
                }
                for entry in self.question_entries
            ],
        }
        return current_config != self._initial_config

    def _check_updates_on_startup(self):
        """在启动时后台检查更新"""
        def check():
            try:
                update_info = UpdateManager.check_updates()
                if update_info:
                    self.update_info = update_info
                    self.root.after(0, self._show_update_notification)
            except Exception as e:
                logging.debug(f"启动时检查更新失败: {e}")
        
        thread = Thread(target=check, daemon=True)
        thread.start()

    def _show_update_notification(self):
        """显示更新通知"""
        if not self.update_info:
            return
        
        info = self.update_info
        release_notes = info.get('release_notes', '')
        # 限制发布说明长度，避免弹窗过大
        release_notes_preview = release_notes[:300] if release_notes else "暂无更新说明"
        if len(release_notes) > 300:
            release_notes_preview += "\n..."
        
        msg = (
            f"检测到新版本 v{info['version']}\n"
            f"当前版本 v{info['current_version']}\n\n"
            f"发布说明:\n{release_notes_preview}\n\n"
            f"是否要立即下载更新？"
        )
        
        if self._log_popup_confirm("检查到更新", msg):
            logging.info("[Action Log] User accepted update notification")
            self._perform_update()
        else:
            logging.info("[Action Log] User declined update notification")

    def check_for_updates(self):
        """手动检查更新"""
        self.root.config(cursor="wait")
        self.root.update()
        
        try:
            update_info = UpdateManager.check_updates()
            if update_info:
                self.update_info = update_info
                msg = (
                    f"检测到新版本！\n\n"
                    f"当前版本: v{update_info['current_version']}\n"
                    f"新版本: v{update_info['version']}\n\n"
                    f"发布说明:\n{update_info['release_notes'][:200]}\n\n"
                    f"立即更新？"
                )
                if self._log_popup_confirm("检查到更新", msg):
                    logging.info("[Action Log] User triggered manual update")
                    self._perform_update()
                else:
                    logging.info("[Action Log] User postponed manual update")
            else:
                self._log_popup_info("检查更新", f"当前已是最新版本 v{__VERSION__}")
        except Exception as e:
            self._log_popup_error("检查更新失败", f"错误: {str(e)}")
        finally:
            self.root.config(cursor="")

    def _perform_update(self):
        """执行更新"""
        if not self.update_info:
            return
        
        update_info = self.update_info
        
        # 显示更新进度窗口
        progress_win = tk.Toplevel(self.root)
        progress_win.title("正在更新")
        progress_win.geometry("500x200")
        progress_win.resizable(False, False)
        progress_win.transient(self.root)
        progress_win.grab_set()
        
        # 居中显示进度窗口
        progress_win.update_idletasks()
        win_width = progress_win.winfo_width()
        win_height = progress_win.winfo_height()
        screen_width = progress_win.winfo_screenwidth()
        screen_height = progress_win.winfo_screenheight()
        
        try:
            import ctypes
            from ctypes.wintypes import RECT
            work_area = RECT()
            ctypes.windll.user32.SystemParametersInfoA(48, 0, ctypes.byref(work_area), 0)
            work_width = work_area.right - work_area.left
            work_height = work_area.bottom - work_area.top
            work_x = work_area.left
            work_y = work_area.top
            x = work_x + (work_width - win_width) // 2
            y = work_y + (work_height - win_height) // 2
        except:
            x = (screen_width - win_width) // 2
            y = (screen_height - win_height) // 2
        
        x = max(0, x)
        y = max(0, y)
        progress_win.geometry(f"+{x}+{y}")
        
        frame = ttk.Frame(progress_win, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        title_label = ttk.Label(frame, text="正在下载新版本...", font=('', 10, 'bold'))
        title_label.pack(pady=(0, 10))
        
        # 文件名标签
        file_label = ttk.Label(frame, text=f"文件: {update_info['file_name']}", foreground="gray")
        file_label.pack(pady=(0, 5))
        
        # 进度条（确定模式）
        progress = ttk.Progressbar(frame, mode='determinate', maximum=100)
        progress.pack(fill=tk.X, pady=10)
        
        # 进度文字
        progress_label = ttk.Label(frame, text="0%", foreground="gray")
        progress_label.pack(pady=(0, 5))
        
        # 状态标签
        status_label = ttk.Label(frame, text="准备下载...", foreground="gray", wraplength=450)
        status_label.pack(pady=10)
        
        progress_win.update()
        
        def update_progress(downloaded, total):
            """更新进度条"""
            if total > 0:
                percent = (downloaded / total) * 100
                progress['value'] = percent
                # 格式化文件大小
                downloaded_mb = downloaded / (1024 * 1024)
                total_mb = total / (1024 * 1024)
                progress_label.config(text=f"{percent:.1f}% ({downloaded_mb:.1f}MB / {total_mb:.1f}MB)")
                progress_win.update()
        
        def do_update():
            try:
                status_label.config(text="正在更新...")
                progress_win.update()
                
                downloaded_file = UpdateManager.download_update(
                    update_info['download_url'],
                    update_info['file_name'],
                    progress_callback=update_progress
                )
                
                if downloaded_file:
                    status_label.config(text="新版本下载成功！合并文件中...")
                    progress_label.config(text="100%")
                    progress['value'] = 100
                    progress_win.update()
                    time.sleep(2)
                    progress_win.destroy()
                    
                    # 询问是否立即运行新版本
                    should_launch = self._log_popup_confirm("更新完成", 
                        f"新版本已下载到:\n{downloaded_file}\n\n是否立即运行新版本？")
                    UpdateManager.schedule_running_executable_deletion(downloaded_file)
                    if should_launch:
                        try:
                            subprocess.Popen([downloaded_file])
                            self.on_close()
                        except Exception as e:
                            logging.error("[Action Log] Failed to launch downloaded update")
                            self._log_popup_error("启动失败", f"无法启动新版本: {e}")
                    else:
                        logging.info("[Action Log] Deferred launching downloaded update")
                else:
                    status_label.config(text="下载失败", foreground="red")
                    progress_win.update()
                    time.sleep(2)
                    progress_win.destroy()
                    self._log_popup_error("更新失败", "下载文件失败，请稍后重试")
            except Exception as e:
                logging.error(f"更新过程中出错: {e}")
                status_label.config(text=f"错误: {str(e)}", foreground="red")
                progress_win.update()
                time.sleep(2)
                progress_win.destroy()
                self._log_popup_error("更新失败", f"更新过程出错: {str(e)}")
        
        thread = Thread(target=do_update, daemon=True)
        thread.start()

    def show_about(self):
        """显示关于对话框"""
        about_text = (
            f"fuck-wjx（问卷星速填）\n\n"
            f"当前版本 v{__VERSION__}\n\n"
            f"GitHub项目地址: https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}\n"
            f"有问题可在 GitHub 提交 issue 或发送电子邮件至 help@hungrym0.top\n\n"
            f"官方网站: https://www.hungrym0.top/fuck-wjx\n"
            f"©2025 HUNGRY_M0 版权所有  MIT Lisence"
        )
        logging.info("[Action Log] Displaying About dialog")
        self._log_popup_info("关于", about_text)

    def run(self):
        self.root.mainloop()


def main():
    setup_logging()
    base_root = tk.Tk()
    base_root.withdraw()
    splash = LoadingSplash(base_root, title="加载中", message="正在准备问卷星速填...")
    splash.show()
    
    splash.update_progress(20, "正在初始化环境...")
    splash.update_progress(40, "正在加载界面...")
    
    gui = None
    try:
        gui = SurveyGUI(root=base_root, loading_splash=splash)
        splash.update_progress(80, "主界面加载完成...")
    finally:
        splash.close()
    if gui:
        gui.run()


if __name__ == "__main__":
    main()

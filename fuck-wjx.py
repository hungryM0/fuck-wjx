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
from pathlib import Path
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Thread
from typing import List, Optional, Union, Dict, Any, Tuple, Callable, Set, Deque
from urllib.parse import urlparse
import webbrowser

import numpy
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
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

# 导入版本号及相关常量
from version import __VERSION__, GITHUB_OWNER, GITHUB_REPO, GITHUB_API_URL, ISSUE_FEEDBACK_URL
# 导入注册表管理器
from registry_manager import RegistryManager
# 导入配置常量
from config import (
    USER_AGENT_PRESETS,
    DEFAULT_RANDOM_UA_KEYS,
    DEFAULT_USER_AGENT,
    DEFAULT_HTTP_HEADERS,
    LOG_FORMAT,
    LOG_BUFFER_CAPACITY,
    LOG_DIR_NAME,
    QQ_GROUP_QR_RELATIVE_PATH,
    PANED_MIN_LEFT_WIDTH,
    PANED_MIN_RIGHT_WIDTH,
    BROWSER_PREFERENCE,
    HEADLESS_WINDOW_SIZE,
    SUBMIT_INITIAL_DELAY,
    SUBMIT_CLICK_SETTLE_DELAY,
    POST_SUBMIT_URL_MAX_WAIT,
    POST_SUBMIT_URL_POLL_INTERVAL,
    PROXY_LIST_FILENAME,
    PROXY_MAX_PROXIES,
    PROXY_REMOTE_URL,
    PROXY_HEALTH_CHECK_URL,
    PROXY_HEALTH_CHECK_TIMEOUT,
    PROXY_HEALTH_CHECK_MAX_DURATION,
    STOP_FORCE_WAIT_SECONDS,
    _GAODE_GEOCODE_ENDPOINT,
    _GAODE_GEOCODE_KEY,
    _LOCATION_GEOCODE_TIMEOUT,
    FULL_SIM_DURATION_JITTER,
    FULL_SIM_MIN_DELAY_SECONDS,
    QUESTION_TYPE_LABELS,
    LOCATION_QUESTION_LABEL,
    DEFAULT_FILL_TEXT,
    _HTML_SPACE_RE,
    _LNGLAT_PATTERN,
    _INVALID_FILENAME_CHARS_RE,
    _MULTI_LIMIT_ATTRIBUTE_NAMES,
    _MULTI_LIMIT_VALUE_KEYS,
    _MULTI_LIMIT_VALUE_KEYSET,
    _SELECTION_KEYWORDS_CN,
    _SELECTION_KEYWORDS_EN,
    _CHINESE_MULTI_LIMIT_PATTERNS,
    _ENGLISH_MULTI_LIMIT_PATTERNS,
)

# Playwright + Selenium 兼容封装
class NoSuchElementException(Exception):
    pass


class TimeoutException(Exception):
    pass


class By:
    CSS_SELECTOR = "css"
    XPATH = "xpath"
    ID = "id"


def _build_selector(by: str, value: str) -> str:
    if by == By.XPATH:
        return f"xpath={value}"
    if by == By.ID:
        if value.startswith("#") or value.startswith("xpath=") or value.startswith("css="):
            return value
        return f"#{value}"
    return value


class PlaywrightElement:
    def __init__(self, handle, page: Page):
        self._handle = handle
        self._page = page

    @property
    def text(self) -> str:
        try:
            return self._handle.inner_text()
        except Exception:
            return ""

    def get_attribute(self, name: str):
        try:
            return self._handle.get_attribute(name)
        except Exception:
            return None

    def is_displayed(self) -> bool:
        try:
            return self._handle.bounding_box() is not None
        except Exception:
            return False

    @property
    def size(self) -> Dict[str, float]:
        try:
            box = self._handle.bounding_box()
        except Exception:
            box = None
        if not box:
            return {"width": 0, "height": 0}
        return {"width": box.get("width") or 0, "height": box.get("height") or 0}

    @property
    def tag_name(self) -> str:
        try:
            value = self._handle.evaluate("el => el.tagName.toLowerCase()")
            return value or ""
        except Exception:
            return ""

    def click(self):
        try:
            self._handle.click()
        except Exception:
            try:
                self._handle.scroll_into_view_if_needed()
                self._handle.click()
            except Exception:
                pass

    def clear(self):
        try:
            self._handle.fill("")
            return
        except Exception:
            pass
        try:
            self._handle.evaluate(
                "el => { el.value = ''; el.dispatchEvent(new Event('input', {bubbles:true})); "
                "el.dispatchEvent(new Event('change', {bubbles:true})); }"
            )
        except Exception:
            pass

    def send_keys(self, value: str):
        text = "" if value is None else str(value)
        try:
            self._handle.fill(text)
            return
        except Exception:
            pass
        try:
            self._handle.type(text)
        except Exception:
            pass

    def find_element(self, by: str, value: str):
        selector = _build_selector(by, value)
        handle = self._handle.query_selector(selector)
        if handle is None:
            raise NoSuchElementException(f"Element not found: {by} {value}")
        return PlaywrightElement(handle, self._page)

    def find_elements(self, by: str, value: str):
        selector = _build_selector(by, value)
        handles = self._handle.query_selector_all(selector)
        return [PlaywrightElement(h, self._page) for h in handles]


class PlaywrightDriver:
    def __init__(self, playwright, browser: Browser, context: BrowserContext, page: Page, browser_name: str):
        self._playwright = playwright
        self._browser = browser
        self._context = context
        self._page = page
        self.browser_name = browser_name
        self.session_id = f"pw-{int(time.time() * 1000)}-{random.randint(1000, 9999)}"
        try:
            proc = getattr(browser, "process", None)
            self.browser_pid = int(proc.pid) if proc and getattr(proc, "pid", None) else None
        except Exception:
            self.browser_pid = None
        self.browser_pids: Set[int] = set()

    def find_element(self, by: str, value: str):
        handle = self._page.query_selector(_build_selector(by, value))
        if handle is None:
            raise NoSuchElementException(f"Element not found: {by} {value}")
        return PlaywrightElement(handle, self._page)

    def find_elements(self, by: str, value: str):
        handles = self._page.query_selector_all(_build_selector(by, value))
        return [PlaywrightElement(h, self._page) for h in handles]

    def execute_script(self, script: str, *args):
        processed_args = [arg._handle if isinstance(arg, PlaywrightElement) else arg for arg in args]
        try:
            return self._page.evaluate(f"function(){{{script}}}", *processed_args)
        except Exception as exc:
            logging.debug("execute_script failed: %s", exc)
            return None

    def get(self, url: str):
        self._page.goto(url, wait_until="domcontentloaded")

    @property
    def current_url(self) -> str:
        return self._page.url

    @property
    def page(self) -> Page:
        return self._page

    @property
    def page_source(self) -> str:
        try:
            return self._page.content()
        except Exception:
            return ""

    @property
    def title(self) -> str:
        try:
            return self._page.title()
        except Exception:
            return ""

    def set_window_size(self, width: int, height: int):
        try:
            self._page.set_viewport_size({"width": width, "height": height})
        except Exception:
            pass

    def set_window_position(self, x: int, y: int):
        try:
            self._page.evaluate(f"window.moveTo({x}, {y});")
        except Exception:
            pass

    def maximize_window(self):
        try:
            self._page.set_viewport_size({"width": 1280, "height": 900})
        except Exception:
            pass

    def refresh(self):
        """刷新当前页面"""
        try:
            self._page.reload(wait_until="domcontentloaded")
        except Exception:
            pass

    def execute_cdp_cmd(self, *_args, **_kwargs):
        return None

    def quit(self):
        try:
            self._page.close()
        except Exception:
            pass
        try:
            self._context.close()
        except Exception:
            pass
        try:
            self._browser.close()
        except Exception:
            pass
        try:
            self._playwright.stop()
        except Exception:
            pass


# 兼容原先类型标注
BrowserDriver = PlaywrightDriver

# 以下字典/集合需要运行时初始化
_LOCATION_GEOCODE_CACHE: Dict[str, str] = {}
_LOCATION_GEOCODE_FAILURES: Set[str] = set()
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


def _get_resource_path(relative_path: str) -> str:
    """
    获取资源文件的完整路径。
    在 PyInstaller 打包时，资源会被提取到 sys._MEIPASS 目录。
    在开发时，资源位于项目根目录。
    """
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后，资源在 _MEIPASS 目录中
        base_path = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        # 开发环境，资源在项目根目录
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    return os.path.join(base_path, relative_path)


def _parse_proxy_line(line: str) -> Optional[str]:
    if not line:
        return None
    cleaned = line.strip()
    if not cleaned or cleaned.startswith("#"):
        return None
    if "://" in cleaned:
        return cleaned
    if ":" in cleaned and cleaned.count(":") == 1:
        host, port = cleaned.split(":", 1)
    else:
        parts = re.split(r"[\s,]+", cleaned)
        if len(parts) < 2:
            return None
        host, port = parts[0], parts[1]
    host = host.strip()
    port = port.strip()
    if not host or not port:
        return None
    try:
        int(port)
    except ValueError:
        return None
    return f"{host}:{port}"


def _load_proxy_ip_pool() -> List[str]:
    if requests is None:
        raise RuntimeError("requests 模块不可用，无法从远程获取代理列表")
    proxy_url = PROXY_REMOTE_URL
    try:
        response = requests.get(proxy_url, headers=DEFAULT_HTTP_HEADERS, timeout=12)
        response.raise_for_status()
    except Exception as exc:
        raise OSError(f"获取远程代理列表失败：{exc}") from exc

    try:
        payload = response.json()
    except Exception as exc:
        raise ValueError(f"远程代理接口返回格式错误（期望 JSON）：{exc}") from exc

    proxy_items: List[Dict[str, Any]] = []
    if isinstance(payload, dict):
        error_code = payload.get("code")
        status_code = payload.get("status")
        if isinstance(error_code, str) and error_code.isdigit():
            error_code = int(error_code)
        if isinstance(status_code, str) and status_code.isdigit():
            status_code = int(status_code)
        if not isinstance(error_code, int):
            raise ValueError("远程代理接口缺少 code 字段或格式不正确")
        if error_code != 0:
            message = payload.get("message") or payload.get("msg") or "未知错误"
            status_hint = f"，status={status_code}" if status_code is not None else ""
            raise ValueError(f"远程代理接口返回错误：{message}（code={error_code}{status_hint}）")
        data_section = payload.get("data")
        if isinstance(data_section, dict):
            proxy_items = data_section.get("list") or []
        if not proxy_items:
            proxy_items = payload.get("list") or payload.get("proxies") or []
    if not isinstance(proxy_items, list):
        proxy_items = []

    proxies: List[str] = []
    seen: Set[str] = set()
    for item in proxy_items:
        if not isinstance(item, dict):
            continue
        host = str(item.get("ip") or item.get("host") or "").strip()
        port = str(item.get("port") or "").strip()
        if not host or not port:
            continue
        try:
            int(port)
        except ValueError:
            continue
        expired = item.get("expired")
        if isinstance(expired, str) and expired.isdigit():
            try:
                expired = int(expired)
            except Exception:
                expired = None
        if isinstance(expired, (int, float)):
            now_ms = int(time.time() * 1000)
            if expired <= now_ms:
                continue
        username = str(item.get("account") or item.get("username") or "").strip()
        password = str(item.get("password") or item.get("pwd") or "").strip()
        auth_prefix = f"{username}:{password}@" if username and password else ""
        candidate = f"http://{auth_prefix}{host}:{port}"
        scheme = candidate.split("://", 1)[0].lower()
        if scheme not in ("http", "https"):
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        proxies.append(candidate)
    if not proxies:
        raise ValueError(f"代理列表为空，请检查远程地址：{proxy_url}")
    random.shuffle(proxies)
    if len(proxies) > PROXY_MAX_PROXIES:
        proxies = proxies[:PROXY_MAX_PROXIES]
    return proxies


def _fetch_new_proxy_batch(expected_count: int = 1) -> List[str]:
    try:
        expected = int(expected_count)
    except Exception:
        expected = 1
    expected = max(1, expected)
    proxies: List[str] = []
    # 多尝试几次，尽量拿到足够数量的 IP
    attempts = max(2, expected)
    for _ in range(attempts):
        batch = _load_proxy_ip_pool()
        for proxy in batch:
            if proxy not in proxies:
                proxies.append(proxy)
                if len(proxies) >= expected:
                    break
        if len(proxies) >= expected:
            break
    return proxies


def _proxy_is_responsive(proxy_address: str, timeout: float = PROXY_HEALTH_CHECK_TIMEOUT, stop_signal: Optional[threading.Event] = None) -> bool:
    """验证代理是否能在限定时间内连通，可用返回 True。"""
    if stop_signal and stop_signal.is_set():
        return False
    if not proxy_address:
        return True
    if requests is None:
        logging.debug("requests 模块不可用，跳过代理超时验证")
        return True
    normalized = proxy_address.strip()
    if not normalized:
        return False
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    proxies = {"http": normalized, "https": normalized}
    # 减少超时时间到 2 秒，以便更快地响应停止信号
    effective_timeout = min(timeout, 2.0)
    start_ts = time.monotonic()
    try:
        response = requests.get(
            PROXY_HEALTH_CHECK_URL,
            headers=DEFAULT_HTTP_HEADERS,
            proxies=proxies,
            timeout=effective_timeout,
        )
        elapsed = time.monotonic() - start_ts
    except requests.exceptions.Timeout:
        logging.warning(f"代理 {proxy_address} 超过 {effective_timeout} 秒无响应，跳过本次提交")
        return False
    except requests.exceptions.RequestException as exc:
        logging.warning(f"代理 {proxy_address} 验证失败：{exc}")
        return False
    except Exception as exc:
        logging.warning(f"代理 {proxy_address} 验证出现异常：{exc}")
        return False
    if response.status_code >= 400:
        logging.warning(f"代理 {proxy_address} 验证返回状态码 {response.status_code}，跳过本次提交")
        return False
    logging.debug(f"代理 {proxy_address} 验证通过，耗时 {elapsed:.2f} 秒")
    return True


def _geocode_location_name(place_name: str) -> Optional[str]:
    """
    根据地名查询经纬度，返回格式为 '经度,纬度'。
    """
    normalized = str(place_name or "").strip()
    if not normalized:
        return None
    cache_key = normalized.lower()
    if cache_key in _LOCATION_GEOCODE_CACHE:
        return _LOCATION_GEOCODE_CACHE[cache_key]
    if cache_key in _LOCATION_GEOCODE_FAILURES:
        return None
    if requests is None:
        logging.debug("requests 模块不可用，无法执行地理编码")
        _LOCATION_GEOCODE_FAILURES.add(cache_key)
        return None
    (
        env_key,
        env_key_alt,
    ) = (os.environ.get("GAODE_WEB_KEY"), os.environ.get("GAODE_GEOCODE_KEY"))
    api_key = env_key or env_key_alt or _GAODE_GEOCODE_KEY
    if not api_key:
        logging.warning("未配置高德 Web 服务 key，无法执行地理编码")
        _LOCATION_GEOCODE_FAILURES.add(cache_key)
        return None
    try:
        headers = dict(DEFAULT_HTTP_HEADERS)
        headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (compatible; WJXAuto; +https://www.hungrym0.top/)",
        )
        params = {
            "address": normalized,
            "key": api_key,
        }
        response = requests.get(
            _GAODE_GEOCODE_ENDPOINT,
            params=params,
            headers=headers,
            timeout=_LOCATION_GEOCODE_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logging.warning(f"地理编码失败（{normalized}）：{exc}")
        _LOCATION_GEOCODE_FAILURES.add(cache_key)
        return None
    if not isinstance(data, dict) or data.get("status") != "1":
        logging.warning(f"地理编码返回异常数据：{normalized} -> {data}")
        _LOCATION_GEOCODE_FAILURES.add(cache_key)
        return None
    geocodes = data.get("geocodes") or []
    if not geocodes:
        logging.warning(f"地理编码没有返回任何结果：{normalized}")
        _LOCATION_GEOCODE_FAILURES.add(cache_key)
        return None
    location = ""
    try:
        location = str(geocodes[0].get("location") or "").strip()
    except Exception:
        location = ""
    if not _LNGLAT_PATTERN.match(location):
        logging.warning(f"地理编码结果缺失经纬度：{normalized}")
        _LOCATION_GEOCODE_FAILURES.add(cache_key)
        return None
    lnglat_value = location
    _LOCATION_GEOCODE_CACHE[cache_key] = lnglat_value
    logging.info(f"地理编码成功：{normalized} -> {lnglat_value}")
    return lnglat_value


def _normalize_proxy_address(proxy_address: Optional[str]) -> Optional[str]:
    if not proxy_address:
        return None
    normalized = proxy_address.strip()
    if not normalized:
        return None
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    return normalized


def _filter_valid_user_agent_keys(selected_keys: List[str]) -> List[str]:
    """过滤并保留合法的 UA key"""
    return [key for key in (selected_keys or []) if key in USER_AGENT_PRESETS]


def _select_user_agent_from_keys(selected_keys: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """从给定 key 列表中随机挑选 UA，返回 (ua, label)"""
    pool = _filter_valid_user_agent_keys(selected_keys)
    if not pool:
        return None, None
    key = random.choice(pool)
    preset = USER_AGENT_PRESETS.get(key) or {}
    return preset.get("ua"), preset.get("label")


def _kill_playwright_browser_processes():
    """
    强制终止由 Playwright 启动的浏览器进程。
    通过检查命令行参数来识别 Playwright 启动的进程，避免误杀用户手动打开的浏览器。
    """
    try:
        import psutil
    except ImportError:
        logging.warning("psutil 未安装，无法快速清理浏览器进程")
        return
    
    killed_count = 0
    
    # Playwright 启动的浏览器进程通常包含这些特征命令行参数
    playwright_indicators = [
        '--enable-automation',
        '--test-type',
        '--remote-debugging-port',
        '--user-data-dir=',  # Playwright 会创建临时用户数据目录
        'playwright',
    ]
    
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                proc_info = proc.info
                proc_name = proc_info.get('name', '').lower()
                
                # 只检查浏览器进程
                if proc_name not in ['msedge.exe', 'chrome.exe', 'chromium.exe']:
                    continue
                
                cmdline = proc_info.get('cmdline')
                if not cmdline:
                    continue
                
                # 将命令行参数转为字符串便于检查
                cmdline_str = ' '.join(cmdline).lower()
                
                # 检查是否包含 Playwright 特征
                is_playwright_process = False
                for indicator in playwright_indicators:
                    if indicator.lower() in cmdline_str:
                        is_playwright_process = True
                        break
                
                # 如果确认是 Playwright 进程，则终止
                if is_playwright_process:
                    try:
                        proc.kill()
                        killed_count += 1
                        logging.info(f"已终止 Playwright 浏览器进程: PID={proc_info['pid']}, Name={proc_name}")
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                        
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
                
    except Exception as e:
        logging.warning(f"清理浏览器进程时出错: {e}")
    
    if killed_count > 0:
        logging.info(f"共终止 {killed_count} 个 Playwright 浏览器进程")


def _list_browser_pids() -> Set[int]:
    """
    列出现有 Edge/Chrome/Chromium 进程 PID，便于精确清理。
    """
    try:
        import psutil
    except ImportError:
        return set()
    names = {"msedge.exe", "chrome.exe", "chromium.exe"}
    pids: Set[int] = set()
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            proc_name = (proc.info.get("name") or "").lower()
            if proc_name in names:
                pids.add(int(proc.info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue
    return pids


def _kill_processes_by_pid(pids: Set[int]) -> int:
    """
    按 PID 精确终止一批进程，返回成功杀掉的数量。
    用于只清理当前会话启动的浏览器，避免全盘扫描导致卡顿。
    """
    try:
        import psutil
    except ImportError:
        logging.warning("psutil 未安装，无法按 PID 精确清理浏览器进程")
        return 0

    killed = 0
    for pid in list(set(pids or []))[:6]:
        if not pid or pid <= 0:
            continue
        try:
            proc = psutil.Process(pid)
            proc.kill()
            killed += 1
            logging.info(f"已终止浏览器进程 PID={pid}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        except Exception as exc:
            logging.debug(f"按 PID 清理浏览器失败 pid={pid}: {exc}", exc_info=True)
    if killed > 0:
        logging.info(f"按 PID 共终止 {killed} 个浏览器进程")
    return killed


def create_playwright_driver(headless: bool = False, prefer_browsers: Optional[List[str]] = None, proxy_address: Optional[str] = None, user_agent: Optional[str] = None, window_position: Optional[Tuple[int, int]] = None) -> Tuple[BrowserDriver, str]:
    candidates = prefer_browsers or list(BROWSER_PREFERENCE)
    if not candidates:
        candidates = list(BROWSER_PREFERENCE)
    if "chromium" not in candidates:
        candidates.append("chromium")
    normalized_proxy = _normalize_proxy_address(proxy_address)
    last_exc: Optional[Exception] = None
    for browser in candidates:
        pre_launch_pids = _list_browser_pids()
        try:
            pw = sync_playwright().start()
        except Exception as exc:
            last_exc = exc
            continue
        try:
            launch_args: Dict[str, Any] = {"headless": headless}
            if browser == "edge":
                launch_args["channel"] = "msedge"
            elif browser == "chrome":
                launch_args["channel"] = "chrome"
            if window_position and not headless:
                x, y = window_position
                launch_args["args"] = [f"--window-position={x},{y}"]
            browser_instance = pw.chromium.launch(**launch_args)
            context_args: Dict[str, Any] = {}
            proxy_for_logging = normalized_proxy
            if normalized_proxy:
                proxy_settings: Dict[str, Any] = {"server": normalized_proxy}
                try:
                    parsed = urlparse(normalized_proxy)
                    if parsed.scheme and parsed.hostname:
                        server = f"{parsed.scheme}://{parsed.hostname}"
                        if parsed.port:
                            server += f":{parsed.port}"
                        proxy_settings["server"] = server
                        proxy_for_logging = server
                    if parsed.username:
                        proxy_settings["username"] = parsed.username
                    if parsed.password:
                        proxy_settings["password"] = parsed.password
                except Exception:
                    proxy_for_logging = normalized_proxy
                context_args["proxy"] = proxy_settings
            if user_agent:
                context_args["user_agent"] = user_agent
            if headless and HEADLESS_WINDOW_SIZE:
                try:
                    width, height = [int(x) for x in HEADLESS_WINDOW_SIZE.split(",")]
                    context_args["viewport"] = {"width": width, "height": height}
                except Exception:
                    pass
            context = browser_instance.new_context(**context_args)
            page = context.new_page()
            driver = PlaywrightDriver(pw, browser_instance, context, page, browser)
            # 捕获主进程 PID，尽量只杀主进程，减小停止时的系统抖动
            collected_pids: Set[int] = set()
            main_pid = getattr(driver, "browser_pid", None)
            if main_pid:
                collected_pids.add(int(main_pid))
            else:
                # 如果未能拿到主 PID，再退而求其次记录新增的少量浏览器进程
                try:
                    time.sleep(0.05)
                    after = _list_browser_pids()
                    diff = list(after - pre_launch_pids)[:3]
                    collected_pids.update(diff)
                    if not collected_pids:
                        logging.warning("[Action Log] 未捕获浏览器主 PID，回退到差集依然为空")
                except Exception:
                    pass
            driver.browser_pids = collected_pids
            logging.debug(f"[Action Log] 捕获浏览器 PID: {sorted(collected_pids) if collected_pids else '无'}")
            logging.info(f"使用 {browser} Playwright 浏览器")
            if normalized_proxy:
                logging.info(f"当前浏览器将使用代理：{proxy_for_logging}")
            return driver, browser
        except Exception as exc:
            last_exc = exc
            logging.warning(f"启动 {browser} 浏览器失败: {exc}")
            try:
                pw.stop()
            except Exception:
                pass
    raise RuntimeError(f"无法启动任何浏览器: {last_exc}")


def handle_aliyun_captcha(
    driver: BrowserDriver, timeout: int = 3, stop_signal: Optional[threading.Event] = None
) -> bool:
    """检测到阿里云智能验证后尝试点击确认按钮，若成功返回 True，未出现返回 False。"""
    popup_locator = (By.ID, "aliyunCaptcha-window-popup")
    checkbox_locator = (By.ID, "aliyunCaptcha-checkbox-icon")
    checkbox_left_locator = (By.ID, "aliyunCaptcha-checkbox-left")
    checkbox_text_locator = (By.ID, "aliyunCaptcha-checkbox-text")
    page = getattr(driver, "page", None)

    def _probe_with_js(script: str) -> bool:
        """确保 JS 片段以 return 返回布尔值，避免 evaluate 丢失返回。"""
        js = script.strip()
        if not js.lstrip().startswith("return"):
            js = "return (" + js + ")"
        try:
            return bool(driver.execute_script(js))
        except Exception:
            return False

    def _ack_security_dialog() -> None:
        """点击可能出现的“安全认证/确定”按钮以触发阿里云弹窗。"""
        script = r"""
            (() => {
                const candidates = ['button', 'a', '.layui-layer-btn0', '.sm-dialog .btn', '.dialog-footer button'];
                const docList = [document, ...Array.from(document.querySelectorAll('iframe')).map(f => {
                    try { return f.contentDocument || f.contentWindow?.document; } catch (e) { return null; }
                }).filter(Boolean)];
                const matchText = (txt) => /^(确\s*定|确\s*认|继续|我知道了|开始验证)$/i.test((txt || '').trim());
                for (const doc of docList) {
                    for (const sel of candidates) {
                        const nodes = doc.querySelectorAll(sel);
                        for (const node of nodes) {
                            const text = (node.innerText || node.textContent || '').trim();
                            if (matchText(text)) { try { node.click(); return true; } catch (e) {} }
                        }
                    }
                }
                return false;
            })();
        """
        _probe_with_js(script)

    def _challenge_visible() -> bool:
        script = r"""
            (() => {
                const ids = [
                    'aliyunCaptcha-window-popup',
                    'aliyunCaptcha-checkbox',
                    'aliyunCaptcha-checkbox-icon',
                    'aliyunCaptcha-checkbox-left',
                    'aliyunCaptcha-checkbox-text',
                    'aliyunCaptcha-loading'
                ];
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const checkDoc = (doc) => {
                    for (const id of ids) {
                        const el = doc.getElementById(id);
                        if (visible(el)) return true;
                    }
                    return false;
                };
                if (checkDoc(document)) return true;
                const frames = Array.from(document.querySelectorAll('iframe'));
                for (const frame of frames) {
                    try {
                        const doc = frame.contentDocument || frame.contentWindow?.document;
                        if (doc && checkDoc(doc)) return true;
                    } catch (e) {}
                }
                return false;
            })();
        """
        return _probe_with_js(script)

    def _wait_for_challenge() -> bool:
        end_time = time.time() + max(timeout, 3)
        while time.time() < end_time:
            if stop_signal and stop_signal.is_set():
                return False
            _ack_security_dialog()
            if _challenge_visible():
                return True
            time.sleep(0.15)
        return _challenge_visible()

    # 先用简单的元素存在性检测作为补充
    def _element_exists() -> bool:
        for locator in (checkbox_locator, checkbox_left_locator, checkbox_text_locator, popup_locator):
            try:
                el = driver.find_element(*locator)
                if el and el.is_displayed():
                    return True
            except Exception:
                continue
        return False

    challenge_detected = _wait_for_challenge() or _element_exists()
    if not challenge_detected:
        logging.debug("未检测到阿里云智能验证弹窗")
        return False
    if stop_signal and stop_signal.is_set():
        return False

    logging.info("检测到阿里云智能验证，尝试通过点击按钮绕过。")
    checkbox = None
    try:
        checkbox = driver.find_element(*checkbox_locator)
    except NoSuchElementException:
        logging.debug("常规方式未找到阿里云验证按钮，尝试使用 JS 兜底。")
    except Exception as exc:
        logging.debug("获取阿里云验证按钮失败，尝试使用 JS 兜底: %s", exc)

    # 兜底尝试获取父级或文字区域点击
    if checkbox is None:
        for locator in (checkbox_left_locator, checkbox_text_locator):
            try:
                checkbox = driver.find_element(*locator)
                break
            except Exception:
                continue

    def _click_checkbox_via_js() -> bool:
        script = r"""
            (() => {
                const ids = [
                    'aliyunCaptcha-checkbox',
                    'aliyunCaptcha-checkbox-icon',
                    'aliyunCaptcha-checkbox-left',
                    'aliyunCaptcha-checkbox-text'
                ];
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const clickDoc = (doc) => {
                    for (const id of ids) {
                        const el = doc.getElementById(id);
                        if (visible(el)) { try { el.click(); return true; } catch (e) {} }
                    }
                    // 也尝试点击任何包含"智能验证"或"开始验证"文字的元素
                    const allClickable = doc.querySelectorAll('span, div, button, a');
                    for (const el of allClickable) {
                        const txt = (el.innerText || el.textContent || '').trim();
                        if (txt.includes('智能验证') || txt.includes('开始验证') || txt === '点击开始智能验证') {
                            if (visible(el)) { try { el.click(); return true; } catch (e) {} }
                        }
                    }
                    return false;
                };
                if (clickDoc(document)) return true;
                const frames = Array.from(document.querySelectorAll('iframe'));
                for (const frame of frames) {
                    try {
                        const doc = frame.contentDocument || frame.contentWindow?.document;
                        if (doc && clickDoc(doc)) return true;
                    } catch (e) {}
                }
                return false;
            })();
        """
        return _probe_with_js(script)

    def _human_like_click(target) -> bool:
        """模拟人类微停顿和微偏移点击，降低“机器点击”特征。"""
        if not target:
            return False
        local_page = page
        for attempt in range(2):
            if stop_signal and stop_signal.is_set():
                return False
            time.sleep(random.uniform(0.35, 0.9))
            try:
                if local_page:
                    try:
                        box = target._handle.bounding_box()  # type: ignore[attr-defined]
                    except Exception:
                        box = None
                    if box:
                        cx = box.get("x", 0) + (box.get("width", 0) * random.uniform(0.35, 0.65))
                        cy = box.get("y", 0) + (box.get("height", 0) * random.uniform(0.35, 0.65))
                        local_page.mouse.move(cx, cy, steps=5)
                        local_page.mouse.click(cx, cy, delay=random.randint(70, 160))
                    else:
                        target.click()
                else:
                    target.click()
            except Exception as exc:
                logging.debug("第 %d 次点击阿里云按钮失败: %s", attempt + 1, exc)
            else:
                if not _challenge_visible():
                    return True
        return False

    clicked = _human_like_click(checkbox) or _click_checkbox_via_js()
    if not clicked or _challenge_visible():
        logging.warning("点击阿里云验证按钮后弹窗仍存在，视为无法绕过。")
        raise AliyunCaptchaBypassError("点击阿里云智能验证按钮后弹窗未关闭。")

    # 检测是否出现"验证失败，请刷新重试"
    time.sleep(0.5)  # 等待验证结果
    
    def _check_captcha_failed() -> bool:
        """检测是否出现验证失败提示"""
        script = r"""
            (() => {
                const texts = ['验证失败', '请刷新重试', '请刷新'];
                const allElements = document.querySelectorAll('*');
                for (const el of allElements) {
                    const txt = (el.innerText || el.textContent || '').trim();
                    for (const t of texts) {
                        if (txt.includes(t)) return true;
                    }
                }
                return false;
            })();
        """
        return _probe_with_js(script)
    
    if _check_captcha_failed():
        logging.warning("检测到阿里云验证失败，需要刷新重试")
        raise AliyunCaptchaBypassError("阿里云验证失败，需要刷新重试")

    logging.info("阿里云点击验证已处理，准备继续提交。")
    return True





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

# 最大线程数限制（确保用户电脑流畅）
MAX_THREADS = 12

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
random_proxy_ip_enabled = False
proxy_ip_pool: List[str] = []
random_user_agent_enabled = False
user_agent_pool_keys: List[str] = []
last_submit_had_captcha = False

# 极速模式：全真模拟/随机IP关闭且时间间隔为0时自动启用
def _is_fast_mode() -> bool:
    return (
        not full_simulation_enabled
        and not random_proxy_ip_enabled
        and submit_interval_range_seconds == (0, 0)
        and answer_duration_range_seconds == (0, 0)
    )

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
    is_location: bool = False

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
            label = "位置题" if self.is_location else "填空题"
            return f"{label}: {preview}"

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


def _get_entry_type_label(entry: QuestionEntry) -> str:
    if getattr(entry, "is_location", False):
        return LOCATION_QUESTION_LABEL
    return QUESTION_TYPE_LABELS.get(entry.question_type, entry.question_type)


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


def _fill_option_additional_text(driver: BrowserDriver, question_number: int, option_index_zero_based: int, fill_value: Optional[str]) -> None:
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
            _smooth_scroll_to_element(driver, input_element, 'center')
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


def _driver_element_contains_text_input(element) -> bool:
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


def _driver_question_has_shared_text_input(question_div) -> bool:
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


def _verify_text_indicates_location(value: Optional[str]) -> bool:
    if not value:
        return False
    text = str(value).strip()
    if not text:
        return False
    return ("地图" in text) or ("map" in text.lower())


def _driver_question_is_location(question_div) -> bool:
    if question_div is None:
        return False
    try:
        local_elements = question_div.find_elements(By.CSS_SELECTOR, ".get_Local")
        if local_elements:
            return True
    except Exception:
        pass
    try:
        inputs = question_div.find_elements(By.CSS_SELECTOR, "input[verify], .get_Local input, input")
    except Exception:
        inputs = []
    for input_element in inputs:
        try:
            verify_value = input_element.get_attribute("verify")
        except Exception:
            verify_value = None
        if _verify_text_indicates_location(verify_value):
            return True
    return False


def _soup_question_is_location(question_div) -> bool:
    if question_div is None:
        return False
    try:
        if question_div.find(class_="get_Local"):
            return True
    except Exception:
        pass
    try:
        inputs = question_div.find_all("input")
    except Exception:
        inputs = []
    for input_element in inputs:
        verify_value = input_element.get("verify")
        if _verify_text_indicates_location(verify_value):
            return True
    return False


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
            is_location = type_code in {"1", "2"} and _soup_question_is_location(question_div)
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
                "is_location": is_location,
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


def _get_driver_session_key(driver: BrowserDriver) -> str:
    session_id = getattr(driver, "session_id", None)
    if session_id:
        return str(session_id)
    return f"id-{id(driver)}"


def detect_multiple_choice_limit(driver: BrowserDriver, question_number: int) -> Optional[int]:
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


def _log_multi_limit_once(driver: BrowserDriver, question_number: int, limit: Optional[int]) -> None:
    if not limit:
        return
    cache_key = (_get_driver_session_key(driver), question_number)
    if cache_key in _REPORTED_MULTI_LIMITS:
        return
    print(f"第{question_number}题检测到最多可选 {limit} 项，自动限制选择数量。")
    _REPORTED_MULTI_LIMITS.add(cache_key)


def try_click_start_answer_button(
    driver: BrowserDriver, timeout: float = 1.0, stop_signal: Optional[threading.Event] = None
) -> bool:
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
        if stop_signal and stop_signal.is_set():
            return False
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
                if stop_signal and stop_signal.is_set():
                    return False
                if not displayed:
                    continue
                text = _extract_text_from_element(element)
                if "开始作答" not in text:
                    continue
                if not already_reported:
                    print("检测到“开始作答”按钮，尝试自动点击...")
                    already_reported = True
                try:
                    _smooth_scroll_to_element(driver, element, 'center')
                except Exception:
                    pass
                for click_method in (
                    lambda: element.click(),
                    lambda: driver.execute_script("arguments[0].click();", element),
                ):
                    try:
                        click_method()
                        if stop_signal:
                            if stop_signal.wait(0.3):
                                return False
                        else:
                            time.sleep(0.3)
                        return True
                    except Exception:
                        continue
        if attempt < max_checks - 1:
            if stop_signal and stop_signal.wait(poll_interval):
                return False
            if not stop_signal:
                time.sleep(poll_interval)
    return False


def dismiss_resume_dialog_if_present(
    driver: BrowserDriver, timeout: float = 1.0, stop_signal: Optional[threading.Event] = None
) -> bool:
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
        if stop_signal and stop_signal.is_set():
            return False
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
                if stop_signal and stop_signal.is_set():
                    return False
                if not displayed:
                    continue
                text = _extract_text_from_element(button)
                if text and "取消" not in text:
                    continue
                if not clicked_once:
                    print("检测到“继续上次作答”弹窗，自动点击取消以开始新作答...")
                    clicked_once = True
                try:
                    _smooth_scroll_to_element(driver, button, 'center')
                except Exception:
                    pass
                for click_method in (
                    lambda: button.click(),
                    lambda: driver.execute_script("arguments[0].click();", button),
                ):
                    try:
                        click_method()
                        return True
                    except Exception:
                        continue
        if attempt < max_checks - 1:
            if stop_signal:
                if stop_signal.wait(poll_interval):
                    return False
            else:
                time.sleep(poll_interval)
    return False


def detect(driver: BrowserDriver, stop_signal: Optional[threading.Event] = None) -> List[int]:
    dismiss_resume_dialog_if_present(driver, stop_signal=stop_signal)
    try_click_start_answer_button(driver, stop_signal=stop_signal)
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


def _fill_text_question_input(driver: BrowserDriver, element, value: Optional[Any]) -> None:
    """
    Safely填充单/多行文本题，包括带地图组件的题目。
    支持“答案|经度,纬度”格式设置地图坐标。
    """
    raw_text = "" if value is None else str(value)
    lnglat_value: Optional[str] = None
    if "|" in raw_text:
        candidate_text, candidate_lnglat = raw_text.rsplit("|", 1)
        if _LNGLAT_PATTERN.match(candidate_lnglat):
            raw_text = candidate_text
            lnglat_value = candidate_lnglat.strip()
    try:
        read_only_attr = element.get_attribute("readonly") or ""
    except Exception:
        read_only_attr = ""
    try:
        verify_value = element.get_attribute("verify") or ""
    except Exception:
        verify_value = ""
    is_readonly = bool(read_only_attr)
    verify_value_lower = verify_value.lower()
    is_location_field = ("地图" in verify_value) or ("map" in verify_value_lower)
    if is_location_field and not lnglat_value and raw_text:
        geocoded_value = _geocode_location_name(raw_text)
        if geocoded_value:
            lnglat_value = geocoded_value

    if not is_readonly and not is_location_field:
        try:
            element.clear()
        except Exception:
            pass
        element.send_keys(raw_text)
        if lnglat_value:
            driver.execute_script(
                "arguments[0].setAttribute('lnglat', arguments[1]); arguments[0].lnglat = arguments[1];",
                element,
                lnglat_value,
            )
        return

    driver.execute_script(
        """
        const input = arguments[0];
        const value = arguments[1];
        const lnglat = arguments[2];
        if (!input) {
            return;
        }
        try {
            input.value = value;
        } catch (err) {}
        if (lnglat) {
            try {
                input.setAttribute('lnglat', lnglat);
                input.lnglat = lnglat;
            } catch (err) {}
        }
        const eventOptions = { bubbles: true };
        try {
            input.dispatchEvent(new Event('input', eventOptions));
        } catch (err) {}
        try {
            input.dispatchEvent(new Event('change', eventOptions));
        } catch (err) {}
        const localBox = input.closest('.get_Local');
        if (localBox) {
            const display = localBox.querySelector('.res_local');
            if (display) {
                display.textContent = value || '';
                display.style.display = value ? '' : 'none';
            }
            const button = localBox.querySelector('.getLocalBtn');
            if (button && button.classList && value) {
                button.classList.add('selected');
            }
        }
        """,
        element,
        raw_text,
        lnglat_value,
    )


def vacant(driver: BrowserDriver, current, index):
    answer_candidates = texts[index] if index < len(texts) else [""]
    selection_probabilities = texts_prob[index] if index < len(texts_prob) else [1.0]
    if not answer_candidates:
        answer_candidates = [""]
    if len(selection_probabilities) != len(answer_candidates):
        selection_probabilities = normalize_probabilities([1.0] * len(answer_candidates))
    selected_index = numpy.random.choice(a=numpy.arange(0, len(selection_probabilities)), p=selection_probabilities)
    input_element = driver.find_element(By.CSS_SELECTOR, f"#q{current}")
    _fill_text_question_input(driver, input_element, answer_candidates[selected_index])


def single(driver: BrowserDriver, current, index):
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


def _normalize_droplist_probs(prob_config: Union[List[float], int, None], option_count: int) -> List[float]:
    if option_count <= 0:
        return []
    if isinstance(prob_config, list) and len(prob_config) == option_count:
        try:
            return normalize_probabilities(list(prob_config))
        except Exception:
            pass
    if prob_config == -1 or prob_config is None:
        try:
            return normalize_probabilities([1.0] * option_count)
        except Exception:
            return [1.0 / option_count] * option_count
    try:
        base = list(prob_config) if isinstance(prob_config, list) else [1.0] * option_count
        if len(base) != option_count:
            base = [1.0] * option_count
        return normalize_probabilities(base)
    except Exception:
        return [1.0 / option_count] * option_count


def _extract_select_options(driver: BrowserDriver, question_number: int):
    try:
        select_element = driver.find_element(By.CSS_SELECTOR, f"#q{question_number}")
    except Exception:
        return None, []
    try:
        option_elements = select_element.find_elements(By.CSS_SELECTOR, "option")
    except Exception:
        option_elements = []
    valid_options: List[Tuple[str, str]] = []
    for idx, opt in enumerate(option_elements):
        try:
            value = (opt.get_attribute("value") or "").strip()
        except Exception:
            value = ""
        try:
            text = (opt.text or "").strip()
        except Exception:
            text = ""
        if idx == 0 and ((value == "") or (value == "0") or ("请选择" in text)):
            continue
        if not text and not value:
            continue
        valid_options.append((value, text or value))
    return select_element, valid_options


def _select_dropdown_option_via_js(
    driver: BrowserDriver, select_element, option_value: str, display_text: str
) -> bool:
    try:
        applied = driver.execute_script(
            """
const select = arguments[0];
const optionValue = arguments[1];
const displayText = arguments[2];
if (!select) { return false; }
const opts = Array.from(select.options || []);
const target = opts.find(o => (o.value || '') == optionValue);
if (!target) { return false; }
target.selected = true;
select.value = target.value;
try { select.setAttribute('value', target.value); } catch (e) {}
['input','change'].forEach(name => {
    try { select.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
});
const span = document.getElementById(`select2-${select.id}-container`);
if (span) {
    span.textContent = displayText || target.textContent || target.innerText || '';
    span.title = span.textContent;
}
return true;
            """,
            select_element,
            option_value or "",
            display_text or "",
        )
    except Exception:
        applied = False
    return bool(applied)


def _fill_droplist_via_click(
    driver: BrowserDriver,
    current: int,
    prob_config: Union[List[float], int, None],
    fill_entries: Optional[List[Optional[str]]],
) -> None:
    container_selectors = [
        f"#select2-q{current}-container",
        f"#div{current} .select2-selection__rendered",
        f"#div{current} .select2-selection--single",
        f"#div{current} .ui-select",
    ]
    clicked = False
    for selector in container_selectors:
        try:
            element = driver.find_element(By.CSS_SELECTOR, selector)
            element.click()
            clicked = True
            break
        except Exception:
            continue
    if not clicked:
        return
    time.sleep(0.1)
    options: List[Any] = []
    for _ in range(5):
        options = driver.find_elements(By.XPATH, f"//*[@id='select2-q{current}-results']/li")
        if not options:
            options = driver.find_elements(By.CSS_SELECTOR, ".select2-results__options li")
        visible_options: List[Any] = []
        for opt in options:
            try:
                if hasattr(opt, "is_displayed") and not opt.is_displayed():
                    continue
            except Exception:
                continue
            visible_options.append(opt)
        options = visible_options
        if options:
            break
        time.sleep(0.15)
    if not options:
        return
    filtered_options: List[Tuple[int, Any, str]] = []
    for idx, opt in enumerate(options):
        try:
            text = (opt.text or "").strip()
        except Exception:
            text = ""
        if idx == 0 and (text == "" or "请选择" in text):
            continue
        filtered_options.append((idx, opt, text))
    option_count = len(filtered_options)
    if option_count <= 0:
        return
    probabilities = _normalize_droplist_probs(prob_config, option_count)
    selected_idx = numpy.random.choice(a=numpy.arange(0, len(probabilities)), p=probabilities)
    _, selected_option, _ = filtered_options[selected_idx]
    try:
        selected_option.click()
    except Exception:
        return
    fill_value = _get_fill_text_from_config(fill_entries, selected_idx)
    _fill_option_additional_text(driver, current, selected_idx, fill_value)


# 下拉框处理函数
def droplist(driver: BrowserDriver, current, index):
    prob_config = droplist_prob[index] if index < len(droplist_prob) else -1
    fill_entries = droplist_option_fill_texts[index] if index < len(droplist_option_fill_texts) else None
    select_element, select_options = _extract_select_options(driver, current)
    if select_options:
        probabilities = _normalize_droplist_probs(prob_config, len(select_options))
        selected_idx = numpy.random.choice(a=numpy.arange(0, len(probabilities)), p=probabilities)
        selected_value, selected_text = select_options[selected_idx]
        if _select_dropdown_option_via_js(driver, select_element, selected_value, selected_text):
            fill_value = _get_fill_text_from_config(fill_entries, selected_idx)
            _fill_option_additional_text(driver, current, selected_idx, fill_value)
            return
    _fill_droplist_via_click(driver, current, prob_config, fill_entries)


def multiple(driver: BrowserDriver, current, index):
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


def matrix(driver: BrowserDriver, current, index):
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


def reorder(driver: BrowserDriver, current):
    items_xpath = f'//*[@id="div{current}"]/ul/li'
    order_items = driver.find_elements(By.XPATH, items_xpath)
    for position in range(1, len(order_items) + 1):
        selected_item = random.randint(position, len(order_items))
        driver.find_element(
            By.CSS_SELECTOR, f"#div{current} > ul > li:nth-child({selected_item})"
        ).click()
        time.sleep(0.4)


def scale(driver: BrowserDriver, current, index):
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


def _set_slider_input_value(driver: BrowserDriver, current: int, value: int):
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


def _click_slider_track(driver: BrowserDriver, container, ratio: float) -> bool:
    xpath_candidates = [
        ".//div[contains(@class,'wjx-slider') or contains(@class,'slider-track') or contains(@class,'range-slider') or contains(@class,'ui-slider') or contains(@class,'scale-slider') or contains(@class,'slider-container')]",
        ".//div[@role='slider']",
    ]
    page = getattr(driver, "page", None)
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
            handle = getattr(track, "_handle", None)
            if page and handle:
                try:
                    box = handle.bounding_box()
                except Exception:
                    box = None
                if box:
                    target_x = box["x"] + offset_x
                    target_y = box["y"] + offset_y
                    try:
                        page.mouse.click(target_x, target_y)
                        return True
                    except Exception:
                        continue
    return False


def slider_question(driver: BrowserDriver, current: int, score: int):
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


FULL_SIM_MIN_QUESTION_SECONDS = 3.0


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


def _calculate_full_simulation_run_target(question_count: int) -> float:
    per_question_cfg = 0.0
    if full_simulation_estimated_seconds > 0 and question_count > 0:
        per_question_cfg = float(full_simulation_estimated_seconds) / max(1, question_count)
    per_question_target = max(FULL_SIM_MIN_QUESTION_SECONDS, per_question_cfg)
    base = max(5.0, per_question_target * max(1, question_count))
    jitter = max(0.05, min(0.5, FULL_SIM_DURATION_JITTER))
    upper = max(base + per_question_target * 0.5, base * (1 + jitter))
    return random.uniform(base, upper)


def _build_per_question_delay_plan(question_count: int, target_seconds: float) -> List[float]:
    if question_count <= 0 or target_seconds <= 0:
        return []
    avg_delay = target_seconds / max(1, question_count)
    min_delay = max(FULL_SIM_MIN_DELAY_SECONDS, avg_delay * 0.8, FULL_SIM_MIN_QUESTION_SECONDS)
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


def _smooth_scroll_to_element(driver: BrowserDriver, element, block: str = 'center') -> None:
    """
    平滑滚动到指定元素位置，模拟人类滚动行为。
    仅在启用全真模拟时使用平滑滚动，否则使用瞬间滚动。
    """
    if not _full_simulation_active():
        # 未启用全真模拟时使用瞬间滚动
        try:
            driver.execute_script(f"arguments[0].scrollIntoView({{block:'{block}', behavior:'auto'}});", element)
        except Exception:
            pass
        return
    
    # 启用全真模拟时使用平滑滚动
    try:
        # 获取元素位置和当前滚动位置
        element_y = driver.execute_script("return arguments[0].getBoundingClientRect().top + window.pageYOffset;", element)
        current_scroll = driver.execute_script("return window.pageYOffset;")
        viewport_height = driver.execute_script("return window.innerHeight;")
        
        # 确保值不为None
        if element_y is None or current_scroll is None or viewport_height is None:
            driver.execute_script(f"arguments[0].scrollIntoView({{block:'{block}'}});", element)
            return
        
        # 计算目标滚动位置（居中）
        if block == 'center':
            target_scroll = element_y - viewport_height / 2
        elif block == 'start':
            target_scroll = element_y - 100
        else:  # 'end' or other
            target_scroll = element_y - viewport_height + 100
        
        distance = target_scroll - current_scroll
        
        # 如果距离很小，直接跳转
        if abs(distance) < 30:
            driver.execute_script(f"arguments[0].scrollIntoView({{block:'{block}', behavior:'auto'}});", element)
            return
        
        # 分步平滑滚动 - 快速但仍有平滑感
        steps = max(10, min(25, int(abs(distance) / 80)))  # 减少步数
        
        # 更短的延迟
        base_delay = random.uniform(0.015, 0.025)
        
        for i in range(steps):
            # 使用缓动函数让滚动更自然（先快后慢）
            progress = (i + 1) / steps
            # 使用更温和的缓动曲线
            ease_progress = progress - (1 - progress) * progress * 0.5
            current_step_scroll = current_scroll + distance * ease_progress
            
            driver.execute_script("window.scrollTo(0, arguments[0]);", current_step_scroll)
            time.sleep(base_delay)
        
        # 最后确保精确到达目标位置
        time.sleep(0.02)  # 极短停顿
        driver.execute_script(f"arguments[0].scrollIntoView({{block:'{block}', behavior:'auto'}});", element)
        
    except Exception:
        # 出错时回退到普通滚动
        try:
            driver.execute_script(f"arguments[0].scrollIntoView({{block:'{block}'}});", element)
        except Exception:
            pass


def _human_scroll_after_question(driver: BrowserDriver) -> None:
    distance = random.uniform(120, 260)
    page = getattr(driver, "page", None)
    if page:
        try:
            page.mouse.wheel(0, distance)
            return
        except Exception:
            pass
    try:
        driver.execute_script("window.scrollBy(0, arguments[0]);", distance)
    except Exception:
        pass


def _click_next_page_button(driver: BrowserDriver) -> bool:
    """尝试点击“下一页”按钮，兼容多种问卷模板。"""
    # 先尝试解除可能的隐藏/禁用状态
    try:
        driver.execute_script(
            """
            const candidates = [
                '#divNext', '#ctlNext', '#btnNext', '#next',
                '.next', '.next-btn', '.next-button', '.btn-next',
                'a.button.mainBgColor'
            ];
            for (const sel of candidates) {
                document.querySelectorAll(sel).forEach(el => {
                    el.style.display = 'block';
                    el.style.visibility = 'visible';
                    el.removeAttribute('disabled');
                    el.classList.remove('hide');
                });
            }
            """
        )
    except Exception:
        pass
    locator_candidates = [
        (By.CSS_SELECTOR, "#divNext"),
        (By.XPATH, '//*[@id="ctlNext"]'),
        (By.CSS_SELECTOR, "a.button.mainBgColor[onclick*='show_next_page']"),
        (By.XPATH, "//a[contains(@class,'button') and contains(@class,'mainBgColor') and contains(@onclick,'show_next_page')]"),
        (By.XPATH, "//a[contains(@class,'button') and contains(@class,'mainBgColor') and contains(normalize-space(text()),'下一页')]"),
        (By.CSS_SELECTOR, "a.button.mainBgColor"),
        (By.XPATH, "//a[contains(normalize-space(.),'下一页')]"),
        (By.XPATH, "//button[contains(normalize-space(.),'下一页')]"),
        (By.CSS_SELECTOR, "#btnNext"),
        (By.CSS_SELECTOR, "[id*='next']"),
        (By.CSS_SELECTOR, "[class*='next']"),
        (By.XPATH, "//a[contains(@onclick,'next_page') or contains(@onclick,'nextPage')]"),
    ]
    for by, value in locator_candidates:
        try:
            elements = driver.find_elements(by, value)
        except Exception:
            continue
        for element in elements:
            try:
                if not element.is_displayed():
                    continue
            except Exception:
                continue
            text = _extract_text_from_element(element)
            if text and all(keyword not in text for keyword in ("下一页", "下一步", "下一题", "下一")):
                continue
            try:
                _smooth_scroll_to_element(driver, element, 'center')
            except Exception:
                pass
            for click_method in (
                lambda: element.click(),
                lambda: driver.execute_script("arguments[0].click();", element),
            ):
                try:
                    click_method()
                    return True
                except Exception:
                    continue
    # 最后尝试 JS 执行：直接找常见选择器、触发点击或调用内置翻页函数
    try:
        executed = driver.execute_script(
            """
            const selectors = [
                '#divNext',
                '#ctlNext',
                '#btnNext',
                '#next',
                'a.button.mainBgColor',
                'a[href=\"javascript:;\"][onclick*=\"show_next_page\"]',
                'a[href=\"javascript:;\" i]',
                'a[role=\"button\"]',
                '.next',
                '.next-btn',
                '.next-button',
                '.btn-next',
                'button'
            ];
            const textMatch = el => {
                const t = (el.innerText || el.textContent || '').trim();
                return /下一页|下一步|下一题/.test(t);
            };
            for (const sel of selectors) {
                const elList = Array.from(document.querySelectorAll(sel));
                for (const el of elList) {
                    if (!textMatch(el)) continue;
                    try { el.scrollIntoView({block:'center'}); } catch(_) {}
                    try { el.click(); return true; } catch(_) {}
                    try {
                        el.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, composed:true}));
                        return true;
                    } catch(_) {}
                }
            }
            if (typeof show_next_page === 'function') { show_next_page(); return true; }
            if (typeof next_page === 'function') { next_page(); return true; }
            if (typeof nextPage === 'function') { nextPage(); return true; }
            return false;
            """
        )
        if executed:
            return True
    except Exception:
        pass
    return False


def _click_submit_button(driver: BrowserDriver) -> bool:
    """尝试点击“提交”按钮，兼容多种问卷模板。"""
    locator_candidates = [
        (By.CSS_SELECTOR, "#submit_button"),
        (By.CSS_SELECTOR, "#divSubmit"),
        (By.CSS_SELECTOR, "#ctlNext"),
        (By.CSS_SELECTOR, "#SM_BTN_1"),
        (By.XPATH, "//a[contains(@onclick,'submit') or contains(@onclick,'Submit')]"),
        (By.XPATH, "//button[contains(@onclick,'submit') or contains(@onclick,'Submit')]"),
        (By.XPATH, "//a[contains(normalize-space(.),'提交')]"),
        (By.XPATH, "//button[contains(normalize-space(.),'提交')]"),
        (By.XPATH, "//a[contains(normalize-space(.),'完成')]"),
        (By.XPATH, "//button[contains(normalize-space(.),'完成')]"),
        (By.XPATH, "//a[contains(normalize-space(.),'交卷')]"),
        (By.XPATH, "//button[contains(normalize-space(.),'交卷')]"),
    ]
    for by, value in locator_candidates:
        try:
            elements = driver.find_elements(by, value)
        except Exception:
            continue
        for element in elements:
            try:
                if not element.is_displayed():
                    continue
            except Exception:
                continue
            text = _extract_text_from_element(element)
            if text and all(k not in text for k in ("提交", "完成", "交卷", "确认", "确定")):
                # 如果文本里没这些关键字，尝试依赖 onclick 的元素照样点击
                if not element.get_attribute("onclick"):
                    continue
            try:
                _smooth_scroll_to_element(driver, element, 'center')
            except Exception:
                pass
            for click_method in (
                lambda: element.click(),
                lambda: driver.execute_script("arguments[0].click();", element),
            ):
                try:
                    click_method()
                    return True
                except Exception:
                    continue
    # JS 兜底：通过选择器和文本匹配点击，或调用全局提交函数
    try:
        executed = driver.execute_script(
            """
            const selectors = [
                '#submit_button',
                '#divSubmit',
                '#ctlNext',
                '#SM_BTN_1',
                'a.button.mainBgColor',
                'a.button',
                'button[type=\"submit\"]',
                'button',
                'a[href=\"javascript:;\" i]'
            ];
            const matchText = el => {
                const t = (el.innerText || el.textContent || '').trim();
                return /(提交|完成|交卷|确认提交)/.test(t);
            };
            for (const sel of selectors) {
                const elList = Array.from(document.querySelectorAll(sel));
                for (const el of elList) {
                    if (!matchText(el)) continue;
                    try { el.scrollIntoView({block:'center'}); } catch(_) {}
                    try { el.click(); return true; } catch(_) {}
                    try {
                        el.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, composed:true}));
                        return true;
                    } catch(_) {}
                }
            }
            const fnNames = ['submit_survey','submitSurvey','wjxwpr_submit','doSubmit','submit','Submit','save','Save'];
            for (const name of fnNames) {
                if (typeof window[name] === 'function') {
                    try { window[name](); return true; } catch(_) {}
                }
            }
            return false;
            """
        )
        if executed:
            return True
    except Exception:
        pass
    return False


def _sleep_with_stop(stop_signal: Optional[threading.Event], seconds: float) -> bool:
    """带停止信号的睡眠，返回 True 表示被中断。"""
    if seconds <= 0:
        return False
    if stop_signal:
        interrupted = stop_signal.wait(seconds)
        return bool(interrupted and stop_signal.is_set())
    time.sleep(seconds)
    return False


def brush(driver: BrowserDriver, stop_signal: Optional[threading.Event] = None) -> bool:
    """批量填写一份问卷；返回 True 代表完整提交，False 代表过程中被用户打断。"""
    questions_per_page = detect(driver, stop_signal=stop_signal)
    total_question_count = sum(questions_per_page)
    fast_mode = _is_fast_mode()
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
        target_seconds = _calculate_full_simulation_run_target(total_question_count)
        question_delay_plan = _build_per_question_delay_plan(total_question_count, target_seconds)
        planned_total = sum(question_delay_plan)
        logging.info(
            "[Action Log] 全真模拟：本次计划总耗时约 %.1f 秒，共 %d 题",
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
            if _full_simulation_active():
                if _sleep_with_stop(active_stop, random.uniform(0.8, 1.5)):
                    return False
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
        if _full_simulation_active():
            _human_scroll_after_question(driver)
        if (
            question_delay_plan
            and current_question_number < total_question_count
        ):
            plan_index = min(current_question_number - 1, len(question_delay_plan) - 1)
            delay_seconds = question_delay_plan[plan_index] if plan_index >= 0 else 0.0
            if delay_seconds > 0.01:
                if active_stop:
                    if active_stop.wait(delay_seconds):
                        return False
                else:
                    time.sleep(delay_seconds)
        if _abort_requested():
            return False
        buffer_delay = 0.0 if fast_mode else 0.5
        if buffer_delay > 0:
            if active_stop:
                if active_stop.wait(buffer_delay):
                    return False
            else:
                time.sleep(buffer_delay)
        is_last_page = (page_index == total_pages - 1)
        if is_last_page:
            if _simulate_answer_duration_delay(active_stop):
                return False
            if _abort_requested():
                return False
        clicked = _click_next_page_button(driver)
        if not clicked:
            raise NoSuchElementException("Next page button not found")
        click_delay = 0.0 if fast_mode else 0.5
        if click_delay > 0:
            if active_stop:
                if active_stop.wait(click_delay):
                    return False
            else:
                time.sleep(click_delay)
    if _abort_requested():
        return False
    submit(driver, stop_signal=active_stop)
    return True
def submit(driver: BrowserDriver, stop_signal: Optional[threading.Event] = None):
    fast_mode = _is_fast_mode()
    settle_delay = 0 if fast_mode else SUBMIT_CLICK_SETTLE_DELAY
    pre_submit_delay = 0 if fast_mode else SUBMIT_INITIAL_DELAY

    global last_submit_had_captcha
    last_submit_had_captcha = False

    def _click_submit_buttons():
        clicked = False
        try:
            driver.find_element(By.XPATH, '//*[@id="layui-layer1"]/div[3]/a').click()
            clicked = True
            if settle_delay > 0:
                time.sleep(settle_delay)
        except Exception:
            pass
        try:
            driver.find_element(By.XPATH, '//*[@id="SM_BTN_1"]').click()
            clicked = True
            if settle_delay > 0:
                time.sleep(settle_delay)
        except Exception:
            pass
        if not clicked:
            clicked = _click_submit_button(driver)
        return clicked

    def _click_security_confirm_dialog():
        """点击"需要安全校验，请重新提交！"弹窗的确认按钮。"""
        script = r"""
            (() => {
                // 查找 layui 弹窗中的确认按钮
                const selectors = [
                    '.layui-layer-btn0',
                    '.layui-layer-btn a',
                    '.layui-layer-dialog .layui-layer-btn0',
                    '.layui-layer .layui-layer-btn a',
                    '.layui-layer-btn .layui-layer-btn0',
                    'a.layui-layer-btn0',
                    '.layui-layer-page .layui-layer-btn a',
                    '.layui-layer-dialog .layui-layer-btn a'
                ];
                const matchText = (txt) => /^(确\s*定|确\s*认|OK|好的?)$/i.test((txt || '').trim());
                
                // 方法1: 使用选择器查找
                for (const sel of selectors) {
                    const nodes = document.querySelectorAll(sel);
                    for (const node of nodes) {
                        if (!node.offsetParent) continue; // 跳过不可见元素
                        const text = (node.innerText || node.textContent || '').trim();
                        if (matchText(text)) {
                            try { node.click(); return true; } catch (e) {}
                        }
                    }
                }
                
                // 方法2: 查找所有可见的 a 标签和 button 标签
                const allButtons = [...document.querySelectorAll('a, button')];
                for (const btn of allButtons) {
                    if (!btn.offsetParent) continue; // 跳过不可见元素
                    const text = (btn.innerText || btn.textContent || '').trim();
                    if (matchText(text)) {
                        try { btn.click(); return true; } catch (e) {}
                    }
                }
                
                return false;
            })();
        """
        try:
            result = driver.execute_script(script)
            if result:
                logging.debug("已点击安全校验确认弹窗")
                time.sleep(0.3)
            return result
        except Exception:
            return False

    def _handle_captcha_failure_refresh():
        """处理验证失败后的刷新流程：刷新页面 -> 点击'是'继续作答 -> 点击提交 -> 重新进行智能验证"""
        logging.info("验证失败，正在刷新页面...")
        driver.refresh()
        if _sleep_with_stop(stop_signal, 1.5):
            return  # 等待页面刷新完成
        
        # 点击"是"继续上次作答
        script_click_continue = r"""
            (() => {
                const selectors = [
                    '.layui-layer-btn0',
                    '.layui-layer-btn a',
                    '.layui-layer-dialog .layui-layer-btn0',
                    '.layui-layer .layui-layer-btn a',
                    'button',
                    'a.layui-layer-btn0'
                ];
                const matchText = (txt) => /^(是|确\s*定|确\s*认|继续|OK)$/i.test((txt || '').trim());
                for (const sel of selectors) {
                    const nodes = document.querySelectorAll(sel);
                    for (const node of nodes) {
                        const text = (node.innerText || node.textContent || '').trim();
                        if (matchText(text)) {
                            try { node.click(); return true; } catch (e) {}
                        }
                    }
                }
                return false;
            })();
        """
        # 等待并点击"是"按钮
        for _ in range(10):  # 最多尝试 10 次，共 2 秒
            if stop_signal and stop_signal.is_set():
                return
            try:
                result = driver.execute_script(script_click_continue)
                if result:
                    logging.info("已点击'是'继续上次作答")
                    if _sleep_with_stop(stop_signal, 0.5):
                        return
                    break
            except Exception:
                pass
            if _sleep_with_stop(stop_signal, 0.2):
                return
        
        if _sleep_with_stop(stop_signal, 0.5):
            return
        # 点击提交按钮，会触发新的智能验证
        _click_submit_buttons()
        # 点击安全校验确认弹窗（如果有）
        for _ in range(5):
            if stop_signal and stop_signal.is_set():
                return
            if _click_security_confirm_dialog():
                break
            if _sleep_with_stop(stop_signal, 0.3):
                return
        _click_security_confirm_dialog()

    if pre_submit_delay > 0 and _sleep_with_stop(stop_signal, pre_submit_delay):
        return
    _click_submit_buttons()
    # 检查并处理"需要安全校验"的确认弹窗，多次尝试
    for _ in range(5):  # 尝试5次，共约1.5秒
        if stop_signal and stop_signal.is_set():
            return
        if _click_security_confirm_dialog():
            break  # 成功点击就退出
        if _sleep_with_stop(stop_signal, 0.3):
            return
    if stop_signal and stop_signal.is_set():
        return
    
    # 最多重试 3 次验证
    max_captcha_retries = 3
    for retry_count in range(max_captcha_retries):
        if stop_signal and stop_signal.is_set():
            return
        try:
            captcha_bypassed = handle_aliyun_captcha(driver, timeout=3, stop_signal=stop_signal)
            if captcha_bypassed:
                break  # 验证成功，跳出循环
        except AliyunCaptchaBypassError as exc:
            if "验证失败" in str(exc) or "刷新重试" in str(exc):
                if retry_count < max_captcha_retries - 1:
                    logging.warning(f"阿里云验证失败，正在进行第 {retry_count + 2} 次尝试...")
                    _handle_captcha_failure_refresh()
                    continue
                else:
                    logging.error("阿里云验证多次失败，本次提交将被标记为失败")
                    raise
            else:
                logging.error("阿里云智能验证无法绕过，本次提交将被标记为失败: %s", exc)
                raise
    else:
        # 没有验证弹窗出现，正常继续
        captcha_bypassed = False

    if captcha_bypassed:
        last_submit_had_captcha = True
        if stop_signal and stop_signal.is_set():
            return
        if settle_delay > 0:
            if _sleep_with_stop(stop_signal, settle_delay):
                return
        _click_submit_buttons()
        # 阿里云验证通过后，等待提交完成（URL 变化或超时）
        if full_simulation_enabled:
            captcha_submit_timeout = 2.2  # 全真模拟略放宽，避免二次验证
            captcha_poll_interval = 0.07
        else:
            captcha_submit_timeout = 3.0
            captcha_poll_interval = 0.1
        initial_url = driver.current_url
        wait_deadline = time.time() + captcha_submit_timeout
        logging.debug("阿里云验证后等待提交完成，初始 URL: %s", initial_url)
        while time.time() < wait_deadline:
            if stop_signal and stop_signal.is_set():
                return
            try:
                current_url = driver.current_url
                if current_url != initial_url:
                    logging.info("阿里云验证后提交成功，URL 已变化")
                    break
            except Exception:
                pass
            time.sleep(captcha_poll_interval)
        else:
            logging.debug("阿里云验证后等待超时，URL 未变化")
    try:
        slider_text_element = driver.find_element(By.XPATH, '//*[@id="nc_1__scale_text"]/span')
        slider_handle = driver.find_element(By.XPATH, '//*[@id="nc_1_n1z"]')
        if str(slider_text_element.text).startswith("请按住滑块"):
            slider_width = slider_text_element.size.get("width") or 0
            handle = getattr(slider_handle, "_handle", None)
            page = getattr(driver, "page", None)
            if handle and page:
                try:
                    box = handle.bounding_box()
                except Exception:
                    box = None
                if box:
                    start_x = box["x"] + (box.get("width") or 0) / 2
                    start_y = box["y"] + (box.get("height") or 0) / 2
                    delta_x = slider_width if slider_width > 0 else 100
                    try:
                        page.mouse.move(start_x, start_y)
                        page.mouse.down()
                        page.mouse.move(start_x + delta_x, start_y, steps=15)
                        page.mouse.up()
                    except Exception:
                        pass
    except:
        pass


def _select_proxy_for_session() -> Optional[str]:
    if not random_proxy_ip_enabled:
        return None
    candidate: Optional[str] = None
    with lock:
        if proxy_ip_pool:
            candidate = proxy_ip_pool.pop(0)
    if candidate:
        return candidate
    try:
        fetched = _fetch_new_proxy_batch(expected_count=1)
    except Exception as exc:
        logging.warning(f"获取随机代理失败：{exc}")
        return None
    if not fetched:
        return None
    # 将多余的缓存起来，避免并发重复调用
    extra = fetched[1:]
    if extra:
        with lock:
            for proxy in extra:
                if proxy not in proxy_ip_pool:
                    proxy_ip_pool.append(proxy)
    return fetched[0]


def _select_user_agent_for_session() -> Tuple[Optional[str], Optional[str]]:
    if not random_user_agent_enabled:
        return None, None
    return _select_user_agent_from_keys(user_agent_pool_keys)


def _discard_unresponsive_proxy(proxy_address: str) -> None:
    if not proxy_address:
        return
    with lock:
        try:
            proxy_ip_pool.remove(proxy_address)
            logging.debug(f"已移除无响应代理：{proxy_address}")
        except ValueError:
            pass


def run(window_x_pos, window_y_pos, stop_signal: threading.Event, gui_instance=None):
    global cur_num, cur_fail
    fast_mode = _is_fast_mode()
    preferred_browsers = list(BROWSER_PREFERENCE)
    driver: Optional[BrowserDriver] = None

    def _register_driver(instance: BrowserDriver) -> None:
        if gui_instance and hasattr(gui_instance, 'active_drivers'):
            gui_instance.active_drivers.append(instance)
            try:
                pids = set()
                pid_single = getattr(instance, "browser_pid", None)
                if pid_single:
                    pids.add(int(pid_single))
                pid_set = getattr(instance, "browser_pids", None)
                if pid_set:
                    pids.update(int(p) for p in pid_set)
                gui_instance._launched_browser_pids.update(pids)
            except Exception:
                pass

    def _unregister_driver(instance: BrowserDriver) -> None:
        if gui_instance and hasattr(gui_instance, 'active_drivers'):
            try:
                gui_instance.active_drivers.remove(instance)
            except ValueError:
                pass
            try:
                pids = set()
                pid_single = getattr(instance, "browser_pid", None)
                if pid_single:
                    pids.add(int(pid_single))
                pid_set = getattr(instance, "browser_pids", None)
                if pid_set:
                    pids.update(int(p) for p in pid_set)
                for pid in pids:
                    gui_instance._launched_browser_pids.discard(int(pid))
            except Exception:
                pass

    def _dispose_driver() -> None:
        nonlocal driver
        if not driver:
            return
        _unregister_driver(driver)
        try:
            driver.quit()
        except Exception:
            pass
        driver = None

    while True:
        if stop_signal.is_set():
            break
        with lock:
            if stop_signal.is_set() or (target_num > 0 and cur_num >= target_num):
                break
        if _full_simulation_active():
            if not _wait_for_next_full_simulation_slot(stop_signal):
                break
            logging.info("[Action Log] 全真模拟时段管控中，等待编辑区释放...")
        if stop_signal.is_set():
            break
        if driver is None:
            proxy_address = _select_proxy_for_session()
            if proxy_address and not _proxy_is_responsive(proxy_address, stop_signal=stop_signal):
                _discard_unresponsive_proxy(proxy_address)
                if stop_signal.is_set():
                    break
                continue
            ua_value, ua_label = _select_user_agent_for_session()
            if ua_label:
                logging.info(f"使用随机 UA：{ua_label}")
            try:
                driver, active_browser = create_playwright_driver(
                    headless=False,
                    prefer_browsers=list(preferred_browsers) if preferred_browsers else None,
                    proxy_address=proxy_address,
                    user_agent=ua_value,
                    window_position=(window_x_pos, window_y_pos),
                )
            except Exception as exc:
                if stop_signal.is_set():
                    break
                logging.warning(f"启动浏览器失败：{exc}")
                if stop_signal.wait(1.0):
                    break
                continue
            preferred_browsers = [active_browser] + [b for b in BROWSER_PREFERENCE if b != active_browser]
            _register_driver(driver)
            driver.set_window_size(550, 650)

        driver_had_error = False
        try:
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
            need_watch_submit = bool(last_submit_had_captcha)
            if full_simulation_enabled:
                # 稍微放慢提交完成检测，降低触发阿里云验证概率
                max_wait = 0.12 if not need_watch_submit else (0.25 if fast_mode else min(0.4, POST_SUBMIT_URL_MAX_WAIT))
                poll_interval = 0.05 if fast_mode else POST_SUBMIT_URL_POLL_INTERVAL
            else:
                max_wait = 0.1 if not need_watch_submit else (0.2 if fast_mode else POST_SUBMIT_URL_MAX_WAIT)
                poll_interval = 0.05 if fast_mode else POST_SUBMIT_URL_POLL_INTERVAL
            wait_deadline = time.time() + max_wait
            while time.time() < wait_deadline:
                if stop_signal.is_set():
                    break
                if driver.current_url != initial_url:
                    break
                time.sleep(poll_interval)
            final_url = driver.current_url
            if stop_signal.is_set():
                break
            if initial_url != final_url:
                with lock:
                    if target_num <= 0 or cur_num < target_num:
                        cur_num += 1
                        logging.info(
                            f"[OK] 已填写{cur_num}份 - 失败{cur_fail}次 - {time.strftime('%H:%M:%S', time.localtime(time.time()))}"
                        )
                        
                        # 检查是否启用了随机IP提交，如果是，更新计数
                        if proxy_ip_pool and random_proxy_ip_enabled:
                            # 检查是否已启用无限额度
                            if not RegistryManager.is_quota_unlimited():
                                ip_count = RegistryManager.increment_submit_count()
                                logging.info(f"随机IP提交计数: {ip_count}/20")
                                
                                # 当达到20份时，触发卡密验证
                                if ip_count >= 20:
                                    logging.warning("随机IP提交已达20份，需要卡密验证才能继续")
                                    # 在主线程中显示卡密验证窗口
                                    if gui_instance:
                                        def show_dialog():
                                            gui_instance._show_card_validation_dialog()
                                        gui_instance.root.after(0, show_dialog)
                            else:
                                logging.info("已启用无限额度，无需验证")
                        
                        if target_num > 0 and cur_num >= target_num:
                            stop_signal.set()
                    else:
                        stop_signal.set()
                        break
                # 成功提交后关闭浏览器，全真模拟直接换新实例，避免停留完成页
                if full_simulation_enabled or random_user_agent_enabled or proxy_ip_pool:
                    if full_simulation_enabled:
                        # 快速检测是否到达完成页，无需长时间等待广告
                        detected = False
                        try:
                            # 检测完成页面的特定元素
                            divdsc = driver.find_element("id", "divdsc")
                            if divdsc and divdsc.is_displayed():
                                text = divdsc.text or ""
                                if "答卷已经提交" in text or "感谢您的参与" in text:
                                    detected = True
                        except Exception:
                            pass
                        
                        if not detected:
                            # 备用检测：检查页面文本
                            try:
                                page_text = driver.execute_script("return document.body.innerText || '';") or ""
                                if "答卷已经提交" in page_text or "感谢您的参与" in page_text:
                                    detected = True
                            except Exception:
                                pass
                        
                        if detected:
                            # 确认已到达完成页，等待2秒后关闭
                            time.sleep(2.0)
                        else:
                            # 未检测到完成标识，使用原有等待时间
                            time.sleep(0.3)
                    _dispose_driver()
        except Exception:
            driver_had_error = True
            if stop_signal.is_set():
                break
            traceback.print_exc()
            with lock:
                cur_fail += 1
                print(f"已失败{cur_fail}次, 失败次数达到{int(fail_threshold)}次将强制停止")
            if cur_fail >= fail_threshold:
                logging.critical("失败次数过多，强制停止，请检查配置是否正确")
                stop_signal.set()
                break
        finally:
            if driver_had_error:
                _dispose_driver()

        if stop_signal.is_set():
            break
        if not _full_simulation_active():
            min_wait, max_wait = submit_interval_range_seconds
            if max_wait > 0:
                wait_seconds = min_wait if max_wait == min_wait else random.uniform(min_wait, max_wait)
                if stop_signal.wait(wait_seconds):
                    break

    _dispose_driver()





TYPE_OPTIONS = [
    ("single", "单选题"),
    ("multiple", "多选题"),
    ("dropdown", "下拉题"),
    ("matrix", "矩阵题"),
    ("scale", "量表题"),
    ("text", "填空题"),
    ("location", "位置题"),
]

LABEL_TO_TYPE = {label: value for value, label in TYPE_OPTIONS}

LOG_LIGHT_THEME = {
    "background": "#ffffff",
    "foreground": "#1e1e1e",
    "insert": "#1e1e1e",
    "select_bg": "#cfe8ff",
    "select_fg": "#1e1e1e",
    "highlight_bg": "#d9d9d9",
    "highlight_color": "#a6a6a6",
    "info_color": "#1e1e1e",
}

LOG_DARK_THEME = {
    "background": "#292929",
    "foreground": "#ffffff",
    "insert": "#ffffff",
    "select_bg": "#333333",
    "select_fg": "#ffffff",
    "highlight_bg": "#1e1e1e",
    "highlight_color": "#3c3c3c",
    "info_color": "#f0f0f0",
}


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

    def _dump_threads_to_file(self, tag: str = "stop") -> Optional[str]:
        """
        导出当前所有线程的堆栈，便于排查停止后卡顿。
        返回写入的文件路径。
        """
        try:
            import sys
            import traceback
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            logs_dir = os.path.join(_get_runtime_directory(), LOG_DIR_NAME)
            os.makedirs(logs_dir, exist_ok=True)
            file_path = os.path.join(logs_dir, f"thread_dump_{tag}_{ts}.txt")
            frames = sys._current_frames()
            lines = []
            for tid, frame in frames.items():
                thr = next((t for t in threading.enumerate() if t.ident == tid), None)
                name = thr.name if thr else "Unknown"
                lines.append(f"### Thread {name} (id={tid}) ###")
                lines.extend(traceback.format_stack(frame))
                lines.append("")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            logging.info(f"[Debug] 线程堆栈已导出：{file_path}")
            return file_path
        except Exception as exc:
            logging.debug(f"导出线程堆栈失败: {exc}", exc_info=True)
            return None

    def _exit_app(self):
        """结束应用，优先销毁 Tk，再强制退出以避免残留卡顿。"""
        try:
            self._closing = True
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        try:
            os._exit(0)
        except Exception:
            pass

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

        qr_image_path = _get_resource_path(QQ_GROUP_QR_RELATIVE_PATH)
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

    def _open_contact_dialog(self):
        """打开联系对话框，允许用户发送消息"""
        window = tk.Toplevel(self.root)
        window.title("联系开发者")
        window.resizable(True, True)
        window.transient(self.root)

        container = ttk.Frame(window, padding=15)
        container.pack(fill=tk.BOTH, expand=True)

        # 邮箱标签和输入框
        email_label = ttk.Label(container, text="您的邮箱（选填，如果希望收到回复的话）：", font=("Microsoft YaHei", 10))
        email_label.pack(anchor=tk.W, pady=(0, 5))
        email_var = tk.StringVar()
        email_entry = ttk.Entry(container, textvariable=email_var, font=("Microsoft YaHei", 10))
        email_entry.pack(fill=tk.X, pady=(0, 10))

        # 消息类型下拉框
        ttk.Label(container, text="消息类型（可选）：", font=("Microsoft YaHei", 10)).pack(anchor=tk.W, pady=(0, 5))
        message_type_var = tk.StringVar(value="报错反馈")
        message_type_combo = ttk.Combobox(
            container, 
            textvariable=message_type_var, 
            values=["报错反馈", "卡密获取", "新功能建议", "纯聊天"],
            state="readonly",
            font=("Microsoft YaHei", 10)
        )
        message_type_combo.pack(fill=tk.X, pady=(0, 10))

        # 消息类型变化回调
        def on_message_type_changed(*args):
            """当消息类型改变时更新邮箱标签和消息框"""
            current_type = message_type_var.get()
            if current_type == "卡密获取":
                email_label.config(text="您的邮箱（必填）：")
                # 检查文本框是否已有前缀
                current_text = text_widget.get("1.0", tk.END).strip()
                if not current_text.startswith("交易订单号后六位："):
                    text_widget.delete("1.0", tk.END)
                    text_widget.insert("1.0", "交易订单号后六位：")
            else:
                email_label.config(text="您的邮箱（选填，如果希望收到回复的话）：")
                # 移除前缀
                current_text = text_widget.get("1.0", tk.END).strip()
                if current_text.startswith("交易订单号后六位："):
                    text_widget.delete("1.0", tk.END)
                    text_widget.insert("1.0", current_text[11:])  # 移除前缀
        
        message_type_var.trace("w", on_message_type_changed)

        ttk.Label(container, text="请输入您的消息：", font=("Microsoft YaHei", 10)).pack(anchor=tk.W, pady=(0, 5))

        # 创建文本框
        text_frame = ttk.Frame(container)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        text_widget = tk.Text(text_frame, wrap=tk.WORD, yscrollcommand=scrollbar.set, font=("Microsoft YaHei", 10), height=8)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=text_widget.yview)

        # 按钮框架
        button_frame = ttk.Frame(container)
        button_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(8, 0))

        def send_message():
            """发送消息到API"""
            message_content = text_widget.get("1.0", tk.END).strip()
            email = email_var.get().strip()
            message_type = message_type_var.get()
            
            if not message_content:
                messagebox.showwarning("提示", "请输入消息内容", parent=window)
                return
            
            # 如果是卡密获取类型，邮箱必填；其他类型选填
            if message_type == "卡密获取":
                if not email:
                    messagebox.showwarning("提示", "卡密获取类型需要填写邮箱地址", parent=window)
                    return
            
            # 验证邮箱格式（如果填写了邮箱）
            if email:
                email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                if not re.match(email_pattern, email):
                    messagebox.showwarning("提示", "邮箱格式不正确，请输入有效的邮箱地址", parent=window)
                    return

            if not requests:
                messagebox.showerror("错误", "requests 模块未安装，无法发送消息", parent=window)
                return
            # 组合邮箱、来源和消息内容
            try:
                version = __VERSION__
            except NameError:
                version = "unknown"
            
            full_message = f"来源：fuck-wjx v{version}\n"
            full_message += f"类型：{message_type}\n"
            if email:
                full_message += f"联系邮箱：{email}\n"
            full_message += f"消息：{message_content}"

            # 禁用发送按钮，防止重复点击
            send_btn.config(state=tk.DISABLED)
            status_label.config(text="正在发送...")

            def send_request():
                try:
                    if requests is None:
                        def update_ui_no_requests():
                            status_label.config(text="")
                            send_btn.config(state=tk.NORMAL)
                            messagebox.showerror("错误", "requests 模块未安装", parent=window)
                        window.after(0, update_ui_no_requests)
                        return
                    
                    api_url = "https://bot.hungrym0.top"
                    payload = {
                        "message": full_message,
                        "timestamp": datetime.now().isoformat()
                    }
                    
                    response = requests.post(
                        api_url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=10
                    )
                    
                    def update_ui_success():
                        status_label.config(text="")
                        send_btn.config(state=tk.NORMAL)
                        if response.status_code == 200:
                            # 根据消息类型显示不同的成功提示
                            if message_type == "卡密获取":
                                success_message = "发送成功！请留意邮件信息！如未及时发送请在帮助-加入QQ群进群反馈！"
                            else:
                                success_message = "消息已成功发送！"
                            messagebox.showinfo("成功", success_message, parent=window)
                            window.destroy()
                        else:
                            messagebox.showerror("错误", f"发送失败，服务器返回: {response.status_code}", parent=window)
                    
                    window.after(0, update_ui_success)
                    
                except Exception as exc:
                    def update_ui_error():
                        status_label.config(text="")
                        send_btn.config(state=tk.NORMAL)
                        logging.error(f"发送联系消息失败: {exc}")
                        messagebox.showerror("错误", f"发送失败：\n{str(exc)}", parent=window)
                    
                    window.after(0, update_ui_error)

            # 在后台线程发送请求
            thread = threading.Thread(target=send_request, daemon=True)
            thread.start()

        send_btn = ttk.Button(button_frame, text="发送", command=send_message)
        send_btn.pack(side=tk.RIGHT, padx=(0, 8))

        ttk.Button(button_frame, text="取消", command=window.destroy).pack(side=tk.RIGHT, padx=(0, 8))

        status_label = ttk.Label(button_frame, text="", foreground="blue")
        status_label.pack(side=tk.LEFT, padx=(12, 0))

        self._apply_window_scaling(window, base_width=520, base_height=440, min_height=380)
        self._center_child_window(window)
        text_widget.focus_set()

    def _on_root_focus(self, event=None):
        pass

    def _open_donation_dialog(self):
        """打开捐助窗口，显示payment.png"""
        window = tk.Toplevel(self.root)
        window.title("捐助")
        window.resizable(False, False)
        window.transient(self.root)
        window.protocol("WM_DELETE_WINDOW", lambda: window.destroy())

        # 加载payment.png图片
        payment_image_path = _get_resource_path(os.path.join("assets", "payment.png"))
        
        if not os.path.exists(payment_image_path):
            logging.error(f"未找到支付二维码图片: {payment_image_path}")
            messagebox.showerror("资源缺失", f"没有找到支付二维码图片：\n{payment_image_path}")
            window.destroy()
            return

        try:
            with Image.open(payment_image_path) as payment_image:
                display_image = payment_image.copy()
        except Exception as exc:
            logging.error(f"加载支付二维码失败: {exc}")
            messagebox.showerror("加载失败", f"支付二维码图片加载失败：\n{exc}")
            window.destroy()
            return

        max_image_size = 420
        # 兼容新旧版本的 Pillow
        try:
            from PIL.Image import Resampling
            resample_method = Resampling.LANCZOS
        except (ImportError, AttributeError):
            resample_method = 1  # LANCZOS 的值
        try:
            if display_image.width > max_image_size or display_image.height > max_image_size:
                display_image.thumbnail((max_image_size, max_image_size), resample=resample_method)  # type: ignore
        except Exception as exc:
            logging.debug(f"调整支付二维码尺寸失败: {exc}")

        self._payment_photo = ImageTk.PhotoImage(display_image)
        self._payment_image_path = payment_image_path
        try:
            display_image.close()
        except Exception:
            pass

        container = ttk.Frame(window, padding=20)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text="如果你认为这个程序对你有帮助\n可否考虑通过以下方式支持一下求求了呜呜呜\n(点击二维码打开原图)", 
                 justify=tk.CENTER, font=("Microsoft YaHei", 10)).pack(pady=(0, 12))
        
        payment_label = ttk.Label(container, image=self._payment_photo, cursor="hand2")
        payment_label.pack()
        payment_label.bind("<Button-1>", self._show_payment_full_image)

        self._center_child_window(window)

    def _show_payment_full_image(self, event=None):
        """打开支付二维码原图"""
        if not self._payment_image_path:
            return
        image_path = self._payment_image_path
        try:
            if sys.platform.startswith("win"):
                os.startfile(image_path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", image_path], close_fds=True)
            else:
                subprocess.Popen(["xdg-open", image_path], close_fds=True)
        except Exception as exc:
            logging.error(f"打开支付二维码原图失败: {exc}")
            messagebox.showerror("打开失败", f"无法打开原图：\n{image_path}\n\n错误: {exc}")

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

    def _schedule_ip_counter_refresh(self):
        """定期刷新随机IP计数显示"""
        try:
            self._refresh_ip_counter_display()
        except Exception as e:
            logging.debug(f"刷新IP计数显示出错: {e}")
        
        # 继续定期刷新（每2秒刷新一次）
        if not getattr(self, "_closing", False):
            self.root.after(2000, self._schedule_ip_counter_refresh)

    def _on_toggle_log_dark_mode(self):
        """切换日志区域的深色背景"""
        self._apply_log_theme(self.log_dark_mode_var.get())

    def _apply_log_theme(self, use_dark: Optional[bool] = None):
        """根据复选框状态应用日志主题"""
        if not self._log_text_widget:
            return
        if use_dark is None:
            use_dark = bool(self.log_dark_mode_var.get())
        theme = LOG_DARK_THEME if use_dark else LOG_LIGHT_THEME
        self._log_text_widget.configure(
            bg=theme["background"],
            fg=theme["foreground"],
            insertbackground=theme["insert"],
            selectbackground=theme["select_bg"],
            selectforeground=theme["select_fg"],
            highlightbackground=theme["highlight_bg"],
            highlightcolor=theme["highlight_color"],
        )
        self._log_text_widget.tag_configure("INFO", foreground=theme["info_color"])

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
        self.active_drivers: List[BrowserDriver] = []  # 跟踪活跃的浏览器实例
        self._launched_browser_pids: Set[int] = set()  # 跟踪本次会话启动的浏览器 PID
        self._stop_cleanup_thread_running = False  # 避免重复触发停止清理
        # 是否在点击停止后自动退出；可用环境变量 AUTO_EXIT_ON_STOP 控制，默认关闭
        _auto_exit_env = str(os.getenv("AUTO_EXIT_ON_STOP", "")).strip().lower()
        self._auto_exit_on_stop = _auto_exit_env in ("1", "true", "yes", "on")
        self.stop_requested_by_user: bool = False
        self.stop_request_ts: Optional[float] = None
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

        self._closing = False
        self._qq_group_photo: Optional[ImageTk.PhotoImage] = None
        self._qq_group_image_path: Optional[str] = None
        self._payment_photo: Optional[ImageTk.PhotoImage] = None
        self._payment_image_path: Optional[str] = None
        self._config_changed = False  # 跟踪配置是否有改动
        self._initial_config: Dict[str, Any] = {}  # 存储初始配置以便比较
        self._wizard_history: List[int] = []
        self._wizard_commit_log: List[Dict[str, Any]] = []
        self._last_parsed_url: Optional[str] = None
        self._last_questions_info: Optional[List[Dict[str, Any]]] = None
        self._suspend_full_sim_autofill = False
        self._last_survey_title: Optional[str] = None
        self._threads_value_before_full_sim: Optional[str] = None
        self._main_parameter_widgets: List[tk.Widget] = []
        self._settings_window_widgets: List[tk.Widget] = []
        self._random_ua_option_widgets: List[tk.Widget] = []
        self._full_simulation_window: Optional[tk.Toplevel] = None
        self._full_sim_status_label: Optional[ttk.Label] = None

        self._archived_notice_shown = False
        self._random_ip_disclaimer_ack = False
        self._suspend_random_ip_notice = False
        self.url_var = tk.StringVar()
        self.target_var = tk.StringVar(value="")
        self.thread_var = tk.StringVar(value="2")
        
        # 为线程数输入框添加验证，限制最大值为12
        def _validate_thread_input(*args):
            try:
                val = self.thread_var.get().strip()
                if val and val.isdigit():
                    num = int(val)
                    if num > MAX_THREADS:
                        self.thread_var.set(str(MAX_THREADS))
            except:
                pass
        self.thread_var.trace_add("write", _validate_thread_input)
        
        self.interval_minutes_var = tk.StringVar(value="0")
        self.interval_seconds_var = tk.StringVar(value="0")
        self.interval_max_minutes_var = tk.StringVar(value="0")
        self.interval_max_seconds_var = tk.StringVar(value="0")
        self.answer_duration_min_var = tk.StringVar(value="0")
        self.answer_duration_max_var = tk.StringVar(value="0")
        self.random_ua_enabled_var = tk.BooleanVar(value=False)
        self.random_ua_pc_web_var = tk.BooleanVar(value=False)
        self.random_ua_android_wechat_var = tk.BooleanVar(value=True)
        self.random_ua_ios_wechat_var = tk.BooleanVar(value=True)
        self.random_ua_ipad_wechat_var = tk.BooleanVar(value=False)
        self.random_ua_ipad_web_var = tk.BooleanVar(value=False)
        self.random_ua_android_tablet_wechat_var = tk.BooleanVar(value=False)
        self.random_ua_android_tablet_web_var = tk.BooleanVar(value=False)
        self.random_ua_mac_wechat_var = tk.BooleanVar(value=False)
        self.random_ua_windows_wechat_var = tk.BooleanVar(value=False)
        self.random_ua_mac_web_var = tk.BooleanVar(value=False)
        self.random_ip_enabled_var = tk.BooleanVar(value=False)
        self.full_simulation_enabled_var = tk.BooleanVar(value=False)
        self.full_sim_target_var = tk.StringVar(value="")
        self.full_sim_estimated_minutes_var = tk.StringVar(value="3")
        self.full_sim_estimated_seconds_var = tk.StringVar(value="0")
        self.full_sim_total_minutes_var = tk.StringVar(value="30")
        self.full_sim_total_seconds_var = tk.StringVar(value="0")
        self.log_dark_mode_var = tk.BooleanVar(value=False)
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
        self._schedule_ip_counter_refresh()  # 启动IP计数刷新

    def _build_ui(self):
        self.root.geometry("950x750")
        self.root.resizable(True, True)

        # 创建菜单栏
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        self._apply_win11_round_corners(menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        self._apply_win11_round_corners(file_menu)
        menubar.add_cascade(label="文件", menu=file_menu)
        file_menu.add_command(label="载入配置", command=self._load_config_from_dialog)
        file_menu.add_command(label="保存配置", command=self._save_config_as_dialog)

        menubar.add_command(label="设置", command=self._open_settings_window)

        help_menu = tk.Menu(menubar, tearoff=0)
        self._apply_win11_round_corners(help_menu)
        menubar.add_cascade(label="帮助", menu=help_menu)
        help_menu.add_command(label="检查更新", command=self.check_for_updates)
        help_menu.add_command(label="问题反馈", command=self._open_issue_feedback)
        help_menu.add_command(label="加入QQ群", command=self._open_qq_group_dialog)
        help_menu.add_separator()
        help_menu.add_command(label="关于", command=self.show_about)

        menubar.add_command(label="联系", command=self._open_contact_dialog)
        menubar.add_command(label="捐助", command=self._open_donation_dialog)

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
        current_log_theme = LOG_DARK_THEME if self.log_dark_mode_var.get() else LOG_LIGHT_THEME
        self._log_text_widget = tk.Text(
            log_frame,
            wrap=tk.NONE,
            state="normal",
            yscrollcommand=v_scrollbar.set,
            xscrollcommand=h_scrollbar.set,
            bg=current_log_theme["background"],
            fg=current_log_theme["foreground"],
            insertbackground=current_log_theme["insert"],
            selectbackground=current_log_theme["select_bg"],
            selectforeground=current_log_theme["select_fg"],
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=2,
            highlightbackground=current_log_theme["highlight_bg"],
            highlightcolor=current_log_theme["highlight_color"],
            font=("SimHei", 10)
        )
        default_log_color = current_log_theme["info_color"]
        self._log_text_widget.tag_configure("INFO", foreground=default_log_color)
        self._log_text_widget.tag_configure("OK", foreground="#1f9525")
        self._log_text_widget.tag_configure("WARNING", foreground="#f5ba23")
        self._log_text_widget.tag_configure("ERROR", foreground="#ff2929")
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

        ttk.Checkbutton(
            log_button_frame,
            text="启用深色背景",
            variable=self.log_dark_mode_var,
            command=self._on_toggle_log_dark_mode
        ).pack(side=tk.LEFT, padx=2)
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

        # 执行设置区域（放在配置题目下方）
        step3_frame = ttk.LabelFrame(self.scrollable_content, text="💣 执行设置", padding=10)
        step3_frame.pack(fill=tk.X, padx=10, pady=5)

        settings_grid = ttk.Frame(step3_frame)
        settings_grid.pack(fill=tk.X)
        settings_grid.columnconfigure(1, weight=1)
        
        ttk.Label(settings_grid, text="目标份数：").grid(row=0, column=0, sticky="w", padx=5)
        self.target_var.trace_add("write", lambda *args: self._on_main_target_changed())
        target_entry = ttk.Entry(settings_grid, textvariable=self.target_var, width=10)
        target_entry.grid(row=0, column=1, sticky="w", padx=5)
        self._main_parameter_widgets.append(target_entry)

        ttk.Label(
            settings_grid,
            text="线程数（提交速度）：",
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
        self.random_ua_enabled_var.trace_add("write", lambda *args: self._on_random_ua_toggle())
        for _ua_var in (
            self.random_ua_pc_web_var,
            self.random_ua_android_wechat_var,
            self.random_ua_ios_wechat_var,
            self.random_ua_ipad_wechat_var,
            self.random_ua_ipad_web_var,
            self.random_ua_android_tablet_wechat_var,
            self.random_ua_android_tablet_web_var,
            self.random_ua_mac_wechat_var,
            self.random_ua_windows_wechat_var,
            self.random_ua_mac_web_var,
        ):
            _ua_var.trace_add("write", lambda *args: self._mark_config_changed())
        self.random_ip_enabled_var.trace_add("write", lambda *args: self._mark_config_changed())
        self.full_sim_target_var.trace_add("write", lambda *args: self._on_full_sim_target_changed())
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
            # 限制线程数在1-12之间
            new_value = max(1, min(current + delta, MAX_THREADS))
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

        proxy_control_frame = ttk.Frame(step3_frame)
        proxy_control_frame.pack(fill=tk.X, padx=4, pady=(6, 4))
        random_ip_toggle = ttk.Checkbutton(
            proxy_control_frame,
            text="启用随机 IP 提交（若触发智能验证可尝试开启此选项）",
            variable=self.random_ip_enabled_var,
            command=self._on_random_ip_toggle,
        )
        random_ip_toggle.pack(side=tk.LEFT, padx=(0, 10))
        self._random_ip_toggle_widget = random_ip_toggle
        self._main_parameter_widgets.append(random_ip_toggle)

        # 随机IP计数显示和管理
        ip_counter_frame = ttk.Frame(step3_frame)
        ip_counter_frame.pack(fill=tk.X, padx=4, pady=(0, 4))
        ttk.Label(ip_counter_frame, text="随机IP计数：").pack(side=tk.LEFT, padx=5)
        self._ip_counter_label = ttk.Label(ip_counter_frame, text="0/20", font=("Segoe UI", 10, "bold"), foreground="blue")
        self._ip_counter_label.pack(side=tk.LEFT, padx=5)
        ttk.Button(ip_counter_frame, text="重置", command=self._reset_ip_counter).pack(side=tk.LEFT, padx=2)
        self._refresh_ip_counter_display()

        
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

    def _apply_win11_round_corners(self, *menus: tk.Misc) -> None:
        """在 Windows 11 上为菜单窗口启用圆角。"""
        if not sys.platform.startswith("win"):
            return

        try:
            import ctypes
            from ctypes import wintypes
        except Exception:
            return

        dwm_api = getattr(ctypes, "windll", None)
        if not dwm_api:
            return
        dwm_api = getattr(dwm_api, "dwmapi", None)
        if not dwm_api:
            return

        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2

        for menu in menus:
            if not menu:
                continue
            try:
                hwnd_value = int(menu.winfo_id())
            except Exception:
                continue
            if hwnd_value <= 0:
                continue
            preference = wintypes.DWORD(DWMWCP_ROUND)
            try:
                dwm_api.DwmSetWindowAttribute(
                    wintypes.HWND(hwnd_value),
                    ctypes.c_uint(DWMWA_WINDOW_CORNER_PREFERENCE),
                    ctypes.byref(preference),
                    ctypes.sizeof(preference),
                )
            except Exception:
                continue

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
        locking = bool(self.full_simulation_enabled_var.get())
        if locking and not self.random_ua_enabled_var.get():
            self.random_ua_enabled_var.set(True)
        state = tk.DISABLED if locking else tk.NORMAL
        targets = [w for w in getattr(self, '_main_parameter_widgets', []) if w is not None]
        targets += [w for w in getattr(self, '_settings_window_widgets', []) if w is not None]
        allowed_when_locked = []
        if locking:
            allowed_when_locked.extend(
                [getattr(self, "_random_ip_toggle_widget", None)]
            )
            allowed_when_locked.extend(getattr(self, "_random_ua_option_widgets", []))
            allowed_when_locked = [w for w in allowed_when_locked if w is not None]
        for widget in targets:
            desired_state = state
            if locking and widget in allowed_when_locked:
                desired_state = tk.NORMAL
            try:
                if widget.winfo_exists():
                    widget.configure(state=desired_state)
            except Exception:
                try:
                    if widget.winfo_exists():
                        widget["state"] = desired_state
                except Exception:
                    continue
        self._apply_random_ua_widgets_state()

    def _apply_random_ua_widgets_state(self):
        option_widgets = getattr(self, "_random_ua_option_widgets", [])
        state = tk.NORMAL if self.random_ua_enabled_var.get() else tk.DISABLED
        cleaned: List[tk.Widget] = []
        for widget in option_widgets:
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
        self._random_ua_option_widgets = cleaned

    def _on_random_ua_toggle(self):
        self._apply_random_ua_widgets_state()
        self._mark_config_changed()

    def _confirm_random_ip_usage(self) -> bool:
        notice = (
            "启用随机IP提交前请确认：\n\n"
            "1) 代理来源于网络，具有被攻击的安全风险，确认启用视为已知悉风险并自愿承担一切后果；\n"
            "2) 禁止用于污染他人数据，否则可能被封禁或承担法律责任。\n"
            "3) 随机IP维护成本高昂，如需大量使用需要付费。\n\n"
            "是否确认已知悉并继续启用随机IP提交？"
        )
        if self._log_popup_confirm("随机IP使用声明", notice, icon="warning"):
            self._random_ip_disclaimer_ack = True
            return True
        return False

    def _on_random_ip_toggle(self):
        if getattr(self, "_suspend_random_ip_notice", False):
            return
        if not self.random_ip_enabled_var.get():
            return
        if self._confirm_random_ip_usage():
            return
        self._suspend_random_ip_notice = True
        try:
            self.random_ip_enabled_var.set(False)
        finally:
            self._suspend_random_ip_notice = False

    def _show_card_validation_dialog(self):
        """显示卡密验证对话框"""
        dialog = tk.Toplevel(self.root)
        dialog.title("随机IP额度限制")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.protocol("WM_DELETE_WINDOW", lambda: dialog.destroy())
        dialog.grab_set()

        container = ttk.Frame(dialog, padding=15)
        container.pack(fill=tk.BOTH, expand=True)

        # 标题和说明
        ttk.Label(container, text="解锁无限随机IP提交额度", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, pady=(0, 10))
        
        info_text = (
            "作者只是一个大一小登，但是由于ip池及开发成本较高，用户量大，问卷份数要求多，\n"
            "加上学业压力，导致长期如此无偿经营困难……\n\n"
            "1.在菜单栏-捐助中赞助任意金额（看着给，多少都行）\n"
            "2.在上方菜单栏-联系中找到开发者，并留下联系邮箱、交易订单号\n"
            "3.开发者验证后会发送卡密到你的邮箱，输入卡密后即可解锁无限随机IP提交额度\n"
            "4.你也可以通过自己的口才白嫖卡密（误）\n\n"
            "感谢您的支持与理解！🙏"
        )
        ttk.Label(container, text=info_text, justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 15))

        # 卡密输入框
        ttk.Label(container, text="请输入卡密：", font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(0, 5))
        card_var = tk.StringVar()
        card_entry = ttk.Entry(container, textvariable=card_var, width=30, show="*")
        card_entry.pack(fill=tk.X, pady=(0, 15))
        card_entry.focus()

        # 按钮框
        button_frame = ttk.Frame(container)
        button_frame.pack(fill=tk.X, pady=(10, 0))

        result_var = tk.BooleanVar(value=False)

        def on_validate():
            card_input = card_var.get().strip()
            if not card_input:
                messagebox.showwarning("提示", "请输入卡密", parent=dialog)
                return
            
            # 目前采用简单的本地验证
            if self._validate_card(card_input):
                messagebox.showinfo("成功", "卡密验证成功！已启用无限额度，随机IP可无限使用。", parent=dialog)
                RegistryManager.reset_submit_count()
                RegistryManager.write_card_validate_result(True)
                RegistryManager.set_quota_unlimited(True)  # 启用无限额度
                logging.info("卡密验证成功，已启用无限额度")
                self._refresh_ip_counter_display()  # 刷新计数显示
                result_var.set(True)
                dialog.destroy()
            else:
                messagebox.showerror("失败", "卡密无效，请检查后重试。", parent=dialog)

        ttk.Button(button_frame, text="验证", command=on_validate).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="取消", command=dialog.destroy).pack(side=tk.RIGHT, padx=(5, 0))

        self._apply_window_scaling(dialog, base_width=380, base_height=250, min_height=200)
        self._center_child_window(dialog)

        dialog.wait_window()
        return result_var.get()

    def _validate_card(self, card_code: str) -> bool:
        """
        验证卡密
        从 https://hungrym0.top/password.txt 获取正确的卡密进行验证
        """
        if not card_code:
            logging.warning("卡密为空")
            return False
        
        try:
            # 从远程服务器获取正确的卡密
            card_code_stripped = card_code.strip()
            
            # 尝试从远程获取卡密
            if requests is None:
                logging.warning("requests 模块未安装，无法验证卡密")
                return False
            
            try:
                response = requests.get(
                    "https://hungrym0.top/password.txt",
                    timeout=10,
                    headers=DEFAULT_HTTP_HEADERS
                )
                
                if response.status_code != 200:
                    logging.warning(f"无法获取卡密列表，服务器返回: {response.status_code}")
                    return False
                
                # 获取所有有效的卡密（支持多行，每行一个）
                valid_cards = set()
                for line in response.text.strip().split('\n'):
                    line = line.strip()
                    if line:  # 跳过空行
                        valid_cards.add(line)
                
                # 检查输入的卡密是否在有效卡密列表中
                if card_code_stripped in valid_cards:
                    # 只记录卡密前4位和后4位，隐藏中间部分
                    display = f"{card_code_stripped[:4]}***{card_code_stripped[-4:]}" if len(card_code_stripped) > 8 else "***"
                    logging.info(f"卡密 {display} 验证通过")
                    return True
                else:
                    logging.warning(f"卡密验证失败：输入的卡密不在有效列表中")
                    return False
                    
            except requests.exceptions.Timeout:
                logging.error("获取卡密列表超时（10秒）")
                return False
            except requests.exceptions.ConnectionError as e:
                logging.error(f"无法连接到卡密服务器: {e}")
                return False
            except Exception as e:
                logging.error(f"获取卡密列表出错: {e}")
                return False
                
        except Exception as e:
            logging.error(f"卡密验证出现异常: {e}")
            return False

    def _refresh_ip_counter_display(self):
        """刷新随机IP计数显示"""
        try:
            label = getattr(self, "_ip_counter_label", None)
            if label and label.winfo_exists():
                # 检查是否启用了无限额度
                if RegistryManager.is_quota_unlimited():
                    label.config(text="∞ (无限额度)", foreground="green")
                else:
                    count = RegistryManager.read_submit_count()
                    percentage = min(100, int((count / 20) * 100)) if count < 20 else 100
                    if count >= 20:
                        label.config(text=f"{count}/20 (已达上限)", foreground="red")
                    else:
                        label.config(text=f"{count}/20 ({percentage}%)", foreground="blue")
        except Exception as e:
            logging.debug(f"刷新IP计数显示出错: {e}")

    def _reset_ip_counter(self):
        """重置随机IP提交计数或禁用无限额度"""
        # 检查当前状态
        if RegistryManager.is_quota_unlimited():
            # 已启用无限额度，提供禁用选项
            result = messagebox.askyesno("确认", "当前已启用无限额度。\n是否要禁用无限额度并恢复计数限制？")
            if result:
                RegistryManager.set_quota_unlimited(False)
                RegistryManager.reset_submit_count()
                logging.info("已禁用无限额度，恢复计数限制")
                self._refresh_ip_counter_display()
                messagebox.showinfo("成功", "已禁用无限额度，恢复为20份限制。")
        else:
            # 未启用无限额度，提供卡密验证
            result = messagebox.askyesno("确认", "确定要启用无限额度吗？\n(需要卡密验证)")
            if result:
                self._show_card_validation_dialog()
                # 验证成功后计数已重置并启用无限额度

    def _refresh_full_simulation_status_label(self):
        label = getattr(self, '_full_sim_status_label', None)
        if not label or not label.winfo_exists():
            return
        enabled = bool(self.full_simulation_enabled_var.get())
        status_text = "已开启" if enabled else "未开启"
        color = "#2e7d32" if enabled else "#E4A207"
        label.config(text=f"当前状态：{status_text}", foreground=color)

    def _update_full_sim_time_section_visibility(self):
        frame = getattr(self, "_full_sim_timing_frame", None)
        if not frame or not frame.winfo_exists():
            return
        has_target = bool(str(self.full_sim_target_var.get()).strip())
        try:
            managed = frame.winfo_manager()
        except Exception:
            managed = ""
        if has_target:
            if not managed:
                frame.pack(fill=tk.X, pady=(4, 0))
        else:
            if managed:
                frame.pack_forget()

    def _sync_full_sim_target_to_main(self):
        if not self.full_simulation_enabled_var.get():
            return
        target_value = self.full_sim_target_var.get().strip()
        if target_value:
            self.target_var.set(target_value)

    def _get_full_simulation_question_count(self) -> int:
        count = len(self.question_entries)
        if count <= 0 and self._last_questions_info:
            try:
                count = len(self._last_questions_info)
            except Exception:
                count = 0
        return max(0, count)

    @staticmethod
    def _parse_positive_int(value: Any) -> int:
        try:
            parsed = int(str(value).strip())
        except Exception:
            return 0
        return parsed if parsed > 0 else 0

    def _set_full_sim_duration(self, minutes_var: tk.StringVar, seconds_var: tk.StringVar, total_seconds: int) -> bool:
        try:
            total = max(0, int(total_seconds))
        except Exception:
            total = 0
        minutes = total // 60
        seconds = total % 60
        try:
            current_minutes = int(str(minutes_var.get()).strip() or "0")
        except Exception:
            current_minutes = 0
        try:
            current_seconds = int(str(seconds_var.get()).strip() or "0")
        except Exception:
            current_seconds = 0
        if current_minutes * 60 + current_seconds == total:
            return False
        minutes_var.set(str(minutes))
        seconds_var.set(str(seconds))
        return True

    def _auto_update_full_simulation_times(self):
        if getattr(self, "_suspend_full_sim_autofill", False):
            return
        question_count = self._get_full_simulation_question_count()
        if question_count <= 0:
            return
        per_question_seconds = 3
        estimated_seconds = question_count * per_question_seconds
        self._set_full_sim_duration(self.full_sim_estimated_minutes_var, self.full_sim_estimated_seconds_var, estimated_seconds)
        target_value = self._parse_positive_int(self.full_sim_target_var.get()) or self._parse_positive_int(self.target_var.get())
        if target_value > 0:
            total_seconds = estimated_seconds * target_value
            self._set_full_sim_duration(self.full_sim_total_minutes_var, self.full_sim_total_seconds_var, total_seconds)
        self._update_full_sim_time_section_visibility()

    def _on_full_sim_target_changed(self, *_):
        self._mark_config_changed()
        self._sync_full_sim_target_to_main()
        self._auto_update_full_simulation_times()

    def _on_main_target_changed(self, *_):
        self._mark_config_changed()
        self._auto_update_full_simulation_times()

    def _on_full_simulation_toggle(self, *args):
        if self.full_simulation_enabled_var.get() and not self.full_sim_target_var.get().strip():
            current_target = self.target_var.get().strip()
            if current_target:
                self.full_sim_target_var.set(current_target)
        if self.full_simulation_enabled_var.get():
            if self._threads_value_before_full_sim is None:
                self._threads_value_before_full_sim = self.thread_var.get().strip() or "1"
            if self.thread_var.get().strip() != "1":
                self.thread_var.set("1")
        else:
            if self._threads_value_before_full_sim is not None:
                self.thread_var.set(self._threads_value_before_full_sim or "1")
            self._threads_value_before_full_sim = None
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
        self._random_ua_option_widgets = []
        self._random_ua_toggle_widget = None
        self._full_sim_status_label = None

        def _on_close():
            if self._settings_window is window:
                self._settings_window = None
                self._settings_window_widgets = []
                self._random_ua_option_widgets = []
                self._random_ua_toggle_widget = None
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
        status_label = ttk.Label(header_frame, text="当前状态：未开启", foreground="#FF8C00")
        status_label.pack(side=tk.LEFT, padx=(12, 0))
        self._full_sim_status_label = status_label
        self._refresh_full_simulation_status_label()

        proxy_frame = ttk.LabelFrame(content, text="高级设置", padding=15)
        proxy_frame.pack(fill=tk.X, pady=(15, 0))
        ua_toggle_row = ttk.Frame(proxy_frame)
        ua_toggle_row.pack(fill=tk.X, pady=(0, 6))
        ua_toggle = ttk.Checkbutton(
            ua_toggle_row,
            text="启用随机 UA",
            variable=self.random_ua_enabled_var,
            command=self._on_random_ua_toggle,
        )
        ua_toggle.pack(anchor="w")
        self._random_ua_toggle_widget = ua_toggle
        self._settings_window_widgets.append(ua_toggle)

        ua_options_frame = ttk.Frame(proxy_frame)
        ua_options_frame.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(ua_options_frame, text="随机范围：").grid(row=0, column=0, sticky="nw", padx=(0, 8))
        ua_options_inner = ttk.Frame(ua_options_frame)
        ua_options_inner.grid(row=0, column=1, sticky="w")
        ua_option_widgets: List[tk.Widget] = []
        ua_options_list = [
            ("Windows网页端", self.random_ua_pc_web_var),
            ("安卓微信端", self.random_ua_android_wechat_var),
            ("苹果微信端", self.random_ua_ios_wechat_var),
            ("iPad微信端", self.random_ua_ipad_wechat_var),
            ("iPad网页端", self.random_ua_ipad_web_var),
            ("安卓平板微信端", self.random_ua_android_tablet_wechat_var),
            ("安卓平板网页端", self.random_ua_android_tablet_web_var),
            ("Mac微信WebView", self.random_ua_mac_wechat_var),
            ("Windows微信WebView", self.random_ua_windows_wechat_var),
            ("Mac网页端", self.random_ua_mac_web_var),
        ]
        for idx, (text_value, var) in enumerate(ua_options_list):
            row = idx // 3
            col = idx % 3
            cb = ttk.Checkbutton(ua_options_inner, text=text_value, variable=var)
            cb.grid(row=row, column=col, padx=(0, 10), pady=2, sticky="w")
            ua_option_widgets.append(cb)
        self._random_ua_option_widgets.extend(ua_option_widgets)
        self._settings_window_widgets.extend(ua_option_widgets)

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
        self._full_sim_timing_frame = timing_frame

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
        self._update_full_sim_time_section_visibility()
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
            'is_location': False,
        }
        
        def refresh_dynamic_content(*args):
            """根据选择的题型刷新动态内容"""
            # 清空动态框
            for child in dynamic_frame.winfo_children():
                child.destroy()
            
            q_type = LABEL_TO_TYPE.get(question_type_var.get(), "single")
            location_mode = q_type == "location"
            if location_mode:
                q_type = "text"
            state['is_location'] = location_mode

            if q_type == "text":
                # ===== 填空/位置题 =====
                header_text = "位置候选列表：" if location_mode else "填空答案列表："
                ttk.Label(dynamic_frame, text=header_text, font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=5, fill=tk.X)
                
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
                
                default_value = "" if location_mode else "默认答案"
                add_answer_field(default_value)
                
                add_btn_frame = ttk.Frame(dynamic_frame)
                add_btn_frame.pack(fill=tk.X, pady=(5, 0))
                ttk.Button(add_btn_frame, text="➕ 添加答案", command=lambda: add_answer_field()).pack(anchor="w")
                if location_mode:
                    ttk.Label(
                        dynamic_frame,
                        text="支持“地名”或“地名|经度,纬度”格式，未提供经纬度时系统会尝试自动解析。",
                        foreground="gray",
                        wraplength=540,
                    ).pack(anchor="w", pady=(6, 0), fill=tk.X)
                
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
                raw_q_type = LABEL_TO_TYPE.get(question_type_var.get(), "single")
                is_location_question = bool(state.get('is_location')) if raw_q_type in ("text", "location") else False
                if raw_q_type == "location":
                    is_location_question = True
                q_type = "text" if raw_q_type == "location" else raw_q_type
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
                    is_location=is_location_question,
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
            type_label = ttk.Label(row_frame, text=_get_entry_type_label(entry), 
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
        self._auto_update_full_simulation_times()

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

        # 底部固定按钮，避免滚动内容较多时保存按钮溢出窗口
        action_bar = ttk.Frame(edit_win, padding=(16, 12))
        action_bar.pack(side=tk.BOTTOM, fill=tk.X)

        save_button = ttk.Button(action_bar, text="保存", width=12, command=lambda: None)
        save_button.pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Button(action_bar, text="取消", width=10, command=_close_edit_window).pack(side=tk.RIGHT, padx=(0, 6))

        def _set_save_command(handler: Callable[[], None]):
            save_button.configure(command=handler)

        scroll_container.pack(fill=tk.BOTH, expand=True)

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

        readable_type = _get_entry_type_label(entry)
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

        ttk.Label(frame, text=f"题型: {_get_entry_type_label(entry)}",
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
            
            _set_save_command(save_text)
            
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
            
            _set_save_command(save_multiple)
            
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
            _set_save_command(save_other)

            def _toggle_weight_frame(*_):
                if dist_var.get() == "custom":
                    if not weight_frame.winfo_manager():
                        weight_frame.pack(fill=tk.BOTH, expand=True, pady=10)
                else:
                    weight_frame.pack_forget()

            dist_var.trace_add("write", _toggle_weight_frame)
            _toggle_weight_frame()


    def _get_edit_dialog_hint(self, entry: QuestionEntry) -> str:
        """根据题型返回更口语化的编辑提示。"""
        if entry.is_location:
            return "可直接列出多个地名，格式为“地名”或“地名|经度,纬度”；未提供经纬度时，系统会自动尝试解析。"
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
                self._start_preview_only(url_value, preserve_existing=True, show_preview_window=False)
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

    def _start_preview_only(self, url_value: str, preserve_existing: bool, *, show_preview_window: bool = True):
        def _launch_after_parse(info):
            if show_preview_window:
                self._show_preview_window(deepcopy(info), preserve_existing=preserve_existing)
            else:
                logging.info(f"[Action Log] Preview-only mode: parsed {len(info)} questions, launching browser preview")
            self._safe_preview_button_config(state=tk.DISABLED, text="正在预览...")
            Thread(target=self._launch_preview_browser_session, args=(url_value,), daemon=True).start()

        if self._last_parsed_url == url_value and self._last_questions_info:
            _launch_after_parse(self._last_questions_info)
            return
        self._start_survey_parsing(
            url_value,
            lambda info: _launch_after_parse(info),
            restore_button_state=False,
        )

    def _start_auto_config(self, url_value: str, preserve_existing: bool):
        if self._last_parsed_url == url_value and self._last_questions_info:
            self._show_preview_window(deepcopy(self._last_questions_info), preserve_existing=preserve_existing)
            return
        self._start_survey_parsing(
            url_value,
            lambda info: self._show_preview_window(info, preserve_existing=preserve_existing),
        )

    def _start_survey_parsing(self, url_value: str, result_handler: Callable[[List[Dict[str, Any]]], None], restore_button_state: bool = True):
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
            args=(url_value, progress_win, status_label, progress_bar, percentage_label, result_handler, restore_button_state),
            daemon=True,
        )
        preview_thread.start()

    def _parse_and_show_survey(
        self,
        survey_url,
        progress_win=None,
        status_label=None,
        progress_bar=None,
        percentage_label=None,
        result_handler: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
        restore_button_state: bool = True,
    ):
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
                if restore_button_state:
                    self.root.after(0, lambda: self._safe_preview_button_config(state=tk.NORMAL, text=self._get_preview_button_label()))
                return
            
            update_progress(30, "HTTP 解析失败，准备启动浏览器...")
            
            print(f"正在加载问卷: {survey_url}")
            ua_value, ua_label = self._pick_random_user_agent()
            driver, browser_name = create_playwright_driver(headless=True, user_agent=ua_value)
            if ua_label:
                logging.info(f"[Action Log] 解析使用随机 UA：{ua_label}")
            logging.info(f"Fallback 到 {browser_name.capitalize()} BrowserDriver 解析问卷")
            
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
                        
                        is_location_question = question_type in ("1", "2") and _driver_question_is_location(question_div)
                        type_name = self._get_question_type_name(question_type, is_location=is_location_question)
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
                                if _driver_element_contains_text_input(opt_element):
                                    option_fillable_indices.append(idx)
                            if not option_fillable_indices and option_count > 0 and _driver_question_has_shared_text_input(question_div):
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
                            "fillable_options": option_fillable_indices,
                            "is_location": is_location_question,
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
                            "option_texts": [],
                            "is_location": False,
                        })
                
                if page_idx < len(questions_per_page):
                    try:
                        clicked = _click_next_page_button(driver)
                        if clicked:
                            time.sleep(1.5)
                            print(f"已翻页到第{page_idx + 1}页")
                        else:
                            print("翻页失败: 未找到“下一页”按钮")
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
            if restore_button_state:
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
                elif "BrowserDriver" in error_lower or "driver" in error_lower:
                    error_msg = (
                        f"浏览器驱动初始化失败: {error_str}\n\n"
                        "建议:\n"
                        "1. Edge/Chrome 是否已安装并可独立启动\n"
                        "2. 运行一次 `playwright install chromium` 确保内置浏览器可用\n"
                        "3. 检查安全软件是否拦截浏览器自动化进程"
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
            ua_value, _ = self._pick_random_user_agent()
            if ua_value:
                headers["User-Agent"] = ua_value
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
                is_location = bool(question.get("is_location"))
                question["type"] = self._get_question_type_name(question.get("type_code"), is_location=is_location)
            return questions_info
        except Exception as exc:
            logging.debug(f"HTTP 解析问卷失败: {exc}")
            return None

    def _cache_parsed_survey(self, questions_info: List[Dict[str, Any]], url: str):
        """缓存解析结果以便预览和配置向导复用"""
        self._last_parsed_url = url
        self._last_questions_info = deepcopy(questions_info)
        self._auto_update_full_simulation_times()

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
            ua_value, ua_label = self._pick_random_user_agent()
            driver, browser_name = create_playwright_driver(headless=False, user_agent=ua_value)
            if ua_label:
                logging.info(f"[Action Log] 预览使用随机 UA：{ua_label}")
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

    def _fill_preview_answers(self, driver: BrowserDriver, questions_info: List[Dict[str, Any]]) -> None:
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

    def _get_question_type_name(self, type_code, *, is_location: bool = False):
        if is_location:
            return LOCATION_QUESTION_LABEL
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

    def _get_wizard_hint_text(self, type_code: str, *, is_location: bool = False) -> str:
        """为不同题型提供面向用户的操作提示文本。"""
        if is_location:
            return "建议准备多个真实地名，可选用“地名|经度,纬度”格式显式指定坐标；若只填地名，系统会自动尝试地理编码。"
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
        is_location_question = bool(q.get("is_location"))
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
        
        def _release_wizard_grab(event=None):
            try:
                wizard_win.grab_release()
            except tk.TclError:
                pass

        def _restore_wizard_grab(event=None):
            try:
                if wizard_win.state() == "normal":
                    wizard_win.grab_set()
                    wizard_win.lift()
            except tk.TclError:
                pass

        wizard_win.bind("<Unmap>", _release_wizard_grab, add="+")
        wizard_win.bind("<Map>", _restore_wizard_grab, add="+")

        def _cleanup_wizard():
            _release_wizard_grab()
            try:
                canvas.unbind_all("<MouseWheel>")
            except tk.TclError:
                pass
            try:
                wizard_win.destroy()
            except tk.TclError:
                pass
        
        wizard_win.protocol("WM_DELETE_WINDOW", _cleanup_wizard)
        
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

        helper_text = self._get_wizard_hint_text(type_code, is_location=is_location_question)
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
            _cleanup_wizard()
            self._show_wizard_for_question(questions_info, current_index + 1)
        
        if type_code in ("1", "2"):
            answer_header = "位置候选列表：" if is_location_question else "填空答案列表："
            ttk.Label(config_frame, text=answer_header, font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=5, fill=tk.X)
            
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
            if is_location_question:
                ttk.Label(
                    config_frame,
                    text="可填写“地名”或“地名|经度,纬度”，未提供经纬度时系统会尝试自动解析。",
                    foreground="gray"
                ).pack(anchor="w", pady=(4, 0), fill=tk.X)
            
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
                    custom_weights=None,
                    is_location=bool(q.get("is_location")),
                )
                self._handle_auto_config_entry(entry, q)
                _cleanup_wizard()
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
                _cleanup_wizard()
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
                _cleanup_wizard()
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
                      command=lambda: self._go_back_in_wizard(wizard_win, questions_info, current_index, _cleanup_wizard))
            prev_btn.pack(side=tk.LEFT, padx=(0, 8), pady=2)
        
        skip_btn = ttk.Button(left_btn_frame, text="跳过", width=8, command=skip_question)
        skip_btn.pack(side=tk.LEFT, padx=8, pady=2)
        
        next_btn = ttk.Button(left_btn_frame, text="下一题 →", width=10, command=save_and_next)
        next_btn.pack(side=tk.LEFT, padx=8, pady=2)
        
        # 右侧取消按钮
        cancel_btn = ttk.Button(btn_frame, text="取消向导", width=10, command=_cleanup_wizard)
        cancel_btn.pack(side=tk.RIGHT, padx=(8, 0), pady=2)

    def _go_back_in_wizard(self, current_win, questions_info, current_index, destroy_cb=None):
        if self._wizard_history and self._wizard_history[-1] == current_index:
            self._wizard_history.pop()
        prev_index = 0
        if self._wizard_history:
            prev_index = self._wizard_history.pop()
        self._revert_last_wizard_action()
        if destroy_cb:
            destroy_cb()
        else:
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
        random_proxy_flag = bool(self.random_ip_enabled_var.get())
        random_ua_flag = bool(self.random_ua_enabled_var.get())
        random_ua_keys_list = self._get_selected_random_ua_keys() if random_ua_flag else []
        if random_ua_flag and not random_ua_keys_list:
            self._log_popup_error("参数错误", "启用随机 UA 时至少选择一个终端类型")
            return
        if random_proxy_flag and not self._random_ip_disclaimer_ack:
            if not self._confirm_random_ip_usage():
                self._suspend_random_ip_notice = True
                try:
                    self.random_ip_enabled_var.set(False)
                finally:
                    self._suspend_random_ip_notice = False
                self._log_popup_info("已取消随机IP提交", "未同意免责声明，已禁用随机IP提交。")
                return
        ctx = {
            "url_value": url_value,
            "target": target,
            "threads_count": threads_count,
            "interval_total_seconds": interval_total_seconds,
            "max_interval_total_seconds": max_interval_total_seconds,
            "answer_min_seconds": answer_min_seconds,
            "answer_max_seconds": answer_max_seconds,
            "full_sim_enabled": full_sim_enabled,
            "full_sim_est_seconds": full_sim_est_seconds,
            "full_sim_total_seconds": full_sim_total_seconds,
            "random_proxy_flag": random_proxy_flag,
            "random_ua_flag": random_ua_flag,
            "random_ua_keys_list": random_ua_keys_list,
        }
        if random_proxy_flag:
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.DISABLED)
            self.status_var.set("正在获取代理...")
            Thread(target=self._load_proxies_and_start, args=(ctx,), daemon=True).start()
            return
        self._finish_start_run(ctx, proxy_pool=[])

    def _load_proxies_and_start(self, ctx: Dict[str, Any]):
        if getattr(self, "_closing", False):
            return
        try:
            try:
                need_count = int(ctx.get("threads_count") or 1)
            except Exception:
                need_count = 1
            need_count = max(1, need_count)
            proxy_pool = _fetch_new_proxy_batch(expected_count=need_count)
        except (OSError, ValueError, RuntimeError) as exc:
            self.root.after(0, lambda: self._on_proxy_load_failed(str(exc)))
            return
        if getattr(self, "_closing", False):
            return
        self.root.after(0, lambda: self._finish_start_run(ctx, proxy_pool))

    def _on_proxy_load_failed(self, message: str):
        if getattr(self, "_closing", False):
            return
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED, text="🚫 停止")
        self.status_var.set("准备就绪")
        self._log_popup_error("代理IP错误", message)

    def _finish_start_run(self, ctx: Dict[str, Any], proxy_pool: List[str]):
        if getattr(self, "_closing", False):
            return
        # 启动前重置已记录的浏览器 PID，避免上一轮遗留
        self._launched_browser_pids.clear()
        if not self._log_refresh_job:
            self._schedule_log_refresh()
        random_proxy_flag = bool(ctx.get("random_proxy_flag"))
        random_ua_flag = bool(ctx.get("random_ua_flag"))
        random_ua_keys_list = ctx.get("random_ua_keys_list", [])
        if random_proxy_flag:
            logging.info(f"[Action Log] 启用随机代理 IP（每个浏览器独立分配），已预取 {len(proxy_pool)} 条（{PROXY_REMOTE_URL}）")
        try:
            configure_probabilities(self.question_entries)
        except ValueError as exc:
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED, text="🚫 停止")
            self.status_var.set("准备就绪")
            self._log_popup_error("配置错误", str(exc))
            return

        self.stop_requested_by_user = False
        self.stop_request_ts = None

        url_value = ctx["url_value"]
        target = ctx["target"]
        threads_count = ctx["threads_count"]
        interval_total_seconds = ctx["interval_total_seconds"]
        max_interval_total_seconds = ctx["max_interval_total_seconds"]
        answer_min_seconds = ctx["answer_min_seconds"]
        answer_max_seconds = ctx["answer_max_seconds"]
        full_sim_enabled = ctx["full_sim_enabled"]
        full_sim_est_seconds = ctx["full_sim_est_seconds"]
        full_sim_total_seconds = ctx["full_sim_total_seconds"]

        logging.info(
            f"[Action Log] Starting run url={url_value} target={target} threads={threads_count}"
        )

        global url, target_num, num_threads, fail_threshold, cur_num, cur_fail, stop_event, submit_interval_range_seconds, answer_duration_range_seconds, full_simulation_enabled, full_simulation_estimated_seconds, full_simulation_total_duration_seconds, full_simulation_schedule, random_proxy_ip_enabled, proxy_ip_pool, random_user_agent_enabled, user_agent_pool_keys
        url = url_value
        target_num = target
        # 强制限制线程数不超过12，确保用户电脑流畅
        num_threads = min(threads_count, MAX_THREADS)
        submit_interval_range_seconds = (interval_total_seconds, max_interval_total_seconds)
        answer_duration_range_seconds = (answer_min_seconds, answer_max_seconds)
        full_simulation_enabled = full_sim_enabled
        random_proxy_ip_enabled = random_proxy_flag
        proxy_ip_pool = proxy_pool if random_proxy_flag else []
        random_user_agent_enabled = random_ua_flag
        user_agent_pool_keys = random_ua_keys_list
        if full_sim_enabled:
            full_simulation_estimated_seconds = full_sim_est_seconds
            full_simulation_total_duration_seconds = full_sim_total_seconds
            schedule = _prepare_full_simulation_schedule(target, full_sim_total_seconds)
            if not schedule:
                self.start_button.config(state=tk.NORMAL)
                self.stop_button.config(state=tk.DISABLED, text="🚫 停止")
                self.status_var.set("准备就绪")
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
        self.stop_button.config(state=tk.NORMAL, text="🚫 停止")
        self.status_var.set("正在启动浏览器...")

        self.runner_thread = Thread(target=self._launch_threads, daemon=True)
        self.runner_thread.start()
        self._schedule_status_update()

    def _launch_threads(self):
        print(f"正在启动 {num_threads} 个浏览器窗口...")
        launch_gap = 0.0 if _is_fast_mode() else 0.1
        threads: List[Thread] = []
        for browser_index in range(num_threads):
            if stop_event.is_set():
                break
            window_x = 50 + browser_index * 60
            window_y = 50 + browser_index * 60
            thread = Thread(target=run, args=(window_x, window_y, stop_event, self), daemon=True)
            threads.append(thread)
        self.worker_threads = threads
        for thread in threads:
            if stop_event.is_set():
                break
            thread.start()
            if launch_gap > 0:
                time.sleep(launch_gap)
        print("浏览器启动中，请稍候...")
        self._wait_for_worker_threads(threads)
        self.root.after(0, self._on_run_finished)

    def _wait_for_worker_threads(self, threads: List[Thread]):
        grace_deadline: Optional[float] = None
        while True:
            alive_threads = [t for t in threads if t.is_alive()]
            self.worker_threads = alive_threads
            if not alive_threads:
                return
            if self.stop_requested_by_user:
                if grace_deadline is None:
                    grace_deadline = time.time() + STOP_FORCE_WAIT_SECONDS
                elif time.time() >= grace_deadline:
                    logging.warning("停止等待提交线程退出超时，剩余线程将在后台自行收尾")
                    return
            for t in alive_threads:
                t.join(timeout=0.2)

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
        self.worker_threads = []
        
        # 最终更新进度条
        if cur_num >= target_num:
            self.progress_bar['value'] = 100
            self.progress_label.config(text="100%")
        else:
            if target_num > 0:
                progress = int((cur_num / target_num) * 100)
                self.progress_bar['value'] = progress
                self.progress_label.config(text=f"{progress}%")

    def _start_stop_cleanup_with_grace(
        self,
        drivers_snapshot: List[BrowserDriver],
        worker_threads_snapshot: List[Thread],
        browser_pids_snapshot: Set[int],
    ):
        """手动停止时先给线程一次“达标式”软退出机会，减少卡顿，再视情况强制清理。"""

        def _runner():
            # 先模仿达到目标份数时的收尾，等待线程自行退出
            soft_wait_seconds = max(3.0, STOP_FORCE_WAIT_SECONDS * 2)
            deadline = time.time() + soft_wait_seconds
            try:
                while time.time() < deadline:
                    alive_threads = [t for t in worker_threads_snapshot if t.is_alive()]
                    if not alive_threads:
                        if not browser_pids_snapshot:
                            logging.info("[Stop] 线程已自然退出，无需强制清理")
                            self._stop_cleanup_thread_running = False
                            return
                        break
                    time.sleep(0.12)
            except Exception:
                logging.debug("停止预等待阶段异常，继续执行强制清理", exc_info=True)

            # 若仍有线程或可能残留的浏览器进程，再进入原有的强制清理流程
            self._async_stop_cleanup(
                drivers_snapshot,
                worker_threads_snapshot,
                browser_pids_snapshot,
                wait_for_threads=False,
            )

        Thread(target=_runner, daemon=True).start()

    def _async_stop_cleanup(
        self,
        drivers_snapshot: List[BrowserDriver],
        worker_threads_snapshot: List[Thread],
        browser_pids_snapshot: Set[int],
        *,
        wait_for_threads: bool = True,
    ):
        """在后台线程中执行分阶段停止，先温和关闭，再必要时强杀，避免主线程卡顿。"""
        deadline = time.time() + (STOP_FORCE_WAIT_SECONDS if wait_for_threads else 0)
        logging.info(f"[Stop] 后台清理启动: drivers={len(drivers_snapshot)} threads={len(worker_threads_snapshot)} pids={len(browser_pids_snapshot)}")
        try:
            for driver in drivers_snapshot:
                try:
                    driver.quit()
                except Exception:
                    logging.debug("停止时关闭浏览器实例失败", exc_info=True)
            # 先等待线程退出，再按需清理进程，避免过早强杀导致抖动
            if wait_for_threads:
                while time.time() < deadline:
                    alive = [t for t in worker_threads_snapshot if t.is_alive()]
                    if not alive:
                        break
                    time.sleep(0.1)
            alive_threads = [t for t in worker_threads_snapshot if t.is_alive()]
            killed = 0
            if alive_threads or browser_pids_snapshot:
                killed = _kill_processes_by_pid(browser_pids_snapshot)
            # 如果线程还活着或按 PID 没杀掉进程，兜底再扫一次 Playwright 进程
            if alive_threads or (browser_pids_snapshot and killed == 0):
                try:
                    _kill_playwright_browser_processes()
                except Exception as e:
                    logging.warning(f"强制清理浏览器进程时出错: {e}")
        finally:
            self._stop_cleanup_thread_running = False
            logging.info("[Stop] 后台清理结束")

    def stop_run(self):
        if not self.running:
            return
        self.stop_requested_by_user = True
        self.stop_request_ts = time.time()
        stop_event.set()
        self.running = False
        self.stop_button.config(state=tk.DISABLED, text="停止中...")
        self.status_var.set("已发送停止请求，正在清理浏览器进程...")
        if self.status_job:
            try:
                self.root.after_cancel(self.status_job)
            except Exception:
                pass
            self.status_job = None
        # 停止日志刷新，避免停止阶段 UI 额外负担
        if self._log_refresh_job:
            try:
                self.root.after_cancel(self._log_refresh_job)
            except Exception:
                pass
            self._log_refresh_job = None

        # 在后台线程里关闭浏览器并清理 Playwright 进程，避免阻塞主线程
        drivers_snapshot = list(self.active_drivers)
        worker_threads_snapshot = list(self.worker_threads)
        browser_pids_snapshot = set(self._launched_browser_pids)
        self.active_drivers.clear()
        self._launched_browser_pids.clear()
        if not self._stop_cleanup_thread_running:
            self._stop_cleanup_thread_running = True
            self._start_stop_cleanup_with_grace(drivers_snapshot, worker_threads_snapshot, browser_pids_snapshot)
        if self._auto_exit_on_stop:
            # 清理线程启动后快速退出，规避 Tk 主线程后续卡顿
            self.root.after(150, self._exit_app)
        
        logging.info("收到停止请求，等待当前提交线程完成")
        print("已暂停新的问卷提交，等待现有流程退出")

    def on_close(self):
        self._closing = True
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
            self._exit_app()
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

    def _get_display_scale(self) -> float:
        """获取显示缩放比例。"""
        try:
            # 尝试通过 tkinter 获取 DPI 缩放比例
            dpi = self.root.winfo_fpixels('1i')
            return dpi / 96.0  # 96 DPI 是标准值
        except Exception:
            return 1.0  # 出错时返回默认值

    def _apply_window_scaling(
        self,
        window: Union[tk.Tk, tk.Toplevel],
        *,
        base_width: Optional[int] = None,
        base_height: Optional[int] = None,
        min_width: Optional[int] = None,
        min_height: Optional[int] = None,
    ) -> None:
        """根据 DPI 缩放窗口尺寸并限制最大值，避免控件溢出。"""
        try:
            window.update_idletasks()
            scale = getattr(self, "_ui_scale", self._get_display_scale())
            req_w = window.winfo_reqwidth()
            req_h = window.winfo_reqheight()
            target_w = req_w
            target_h = req_h
            if base_width:
                target_w = max(target_w, int(base_width * scale))
            if base_height:
                target_h = max(target_h, int(base_height * scale))
            if min_width:
                target_w = max(target_w, int(min_width * scale))
            if min_height:
                target_h = max(target_h, int(min_height * scale))

            screen_w = window.winfo_screenwidth()
            screen_h = window.winfo_screenheight()
            max_w = max(320, int(screen_w * 0.95))
            max_h = max(240, int(screen_h * 0.95))
            target_w = min(target_w, max_w)
            target_h = min(target_h, max_h)

            window.geometry(f"{target_w}x{target_h}")
            try:
                window.minsize(min(target_w, max_w), min(target_h, max_h))
            except Exception:
                pass
        except Exception:
            pass

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
            "random_user_agent": self._serialize_random_ua_config(),
            "random_proxy_enabled": bool(self.random_ip_enabled_var.get()),
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
                    "is_location": bool(entry.is_location),
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

    def _get_random_ua_option_vars(self) -> List[Tuple[str, tk.BooleanVar]]:
        return [
            ("pc_web", self.random_ua_pc_web_var),
            ("wechat_android", self.random_ua_android_wechat_var),
            ("wechat_ios", self.random_ua_ios_wechat_var),
            ("wechat_ipad", self.random_ua_ipad_wechat_var),
            ("ipad_web", self.random_ua_ipad_web_var),
            ("wechat_android_tablet", self.random_ua_android_tablet_wechat_var),
            ("android_tablet_web", self.random_ua_android_tablet_web_var),
            ("wechat_mac", self.random_ua_mac_wechat_var),
            ("wechat_windows", self.random_ua_windows_wechat_var),
            ("mac_web", self.random_ua_mac_web_var),
        ]

    def _get_selected_random_ua_keys(self) -> List[str]:
        return [key for key, var in self._get_random_ua_option_vars() if var.get()]

    def _serialize_random_ua_config(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.random_ua_enabled_var.get()),
            "selected": _filter_valid_user_agent_keys(self._get_selected_random_ua_keys()),
        }

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

    def _apply_random_ua_config(self, config: Optional[Dict[str, Any]]):
        enabled = False
        selected_keys = list(DEFAULT_RANDOM_UA_KEYS)
        if isinstance(config, dict):
            enabled = bool(config.get("enabled"))
            selected_keys = _filter_valid_user_agent_keys(
                config.get("selected") or config.get("options") or list(DEFAULT_RANDOM_UA_KEYS)
            )
            if not selected_keys:
                selected_keys = list(DEFAULT_RANDOM_UA_KEYS)
        self.random_ua_enabled_var.set(enabled)
        for key, var in self._get_random_ua_option_vars():
            var.set(key in selected_keys)
        self._apply_random_ua_widgets_state()

    def _pick_random_user_agent(self) -> Tuple[Optional[str], Optional[str]]:
        if not self.random_ua_enabled_var.get():
            return None, None
        return _select_user_agent_from_keys(self._get_selected_random_ua_keys())

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

    def _apply_config_data(self, config: Dict[str, Any], *, restore_paned_position: bool = True):
        """将配置数据应用到界面。"""
        if not isinstance(config, dict):
            raise ValueError("配置文件格式不正确")

        self._suspend_full_sim_autofill = True
        try:
            self.url_var.set(config.get("url", ""))
            self.target_var.set(config.get("target_num", ""))
            self.thread_var.set(config.get("num_threads", ""))
            self._apply_random_ua_config(config.get("random_user_agent"))
            self.random_ip_enabled_var.set(bool(config.get("random_proxy_enabled")))
            self._apply_submit_interval_config(config.get("submit_interval"))
            self._apply_answer_duration_config(config.get("answer_duration_range"))
            self._apply_full_simulation_config(config.get("full_simulation"))

            if restore_paned_position:
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
                        is_location=bool(q_data.get("is_location")),
                    )
                    if entry.fillable_option_indices is None and entry.option_fill_texts:
                        derived = [idx for idx, value in enumerate(entry.option_fill_texts) if value]
                        entry.fillable_option_indices = derived if derived else None
                    self.question_entries.append(entry)
            self._refresh_tree()
        finally:
            self._suspend_full_sim_autofill = False

        self._save_initial_config()
        self._config_changed = False
        self._update_full_simulation_controls_state()
        self._update_parameter_widgets_state()

        def _duration_total_seconds(min_var: tk.StringVar, sec_var: tk.StringVar) -> int:
            try:
                minutes = int(str(min_var.get()).strip() or "0")
            except Exception:
                minutes = 0
            try:
                seconds = int(str(sec_var.get()).strip() or "0")
            except Exception:
                seconds = 0
            return max(0, minutes) * 60 + max(0, seconds)

        if (
            _duration_total_seconds(self.full_sim_estimated_minutes_var, self.full_sim_estimated_seconds_var) == 0
            or _duration_total_seconds(self.full_sim_total_minutes_var, self.full_sim_total_seconds_var) == 0
        ):
            self._auto_update_full_simulation_times()
        else:
            self._update_full_sim_time_section_visibility()

    def _load_config_from_file(self, file_path: str, *, silent: bool = False, restore_paned_position: bool = True):
        """从指定路径加载配置。"""
        with open(file_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        self._apply_config_data(config, restore_paned_position=restore_paned_position)
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
            self._load_config_from_file(config_path, silent=True, restore_paned_position=True)
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
            self._load_config_from_file(file_path, restore_paned_position=False)
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
            "answer_duration_range": self._serialize_answer_duration_config(),
            "full_simulation": self._serialize_full_simulation_config(),
            "random_user_agent": self._serialize_random_ua_config(),
            "random_proxy_enabled": bool(self.random_ip_enabled_var.get()),
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
                    "is_location": bool(entry.is_location),
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
            "answer_duration_range": self._serialize_answer_duration_config(),
            "full_simulation": self._serialize_full_simulation_config(),
            "random_user_agent": self._serialize_random_ua_config(),
            "random_proxy_enabled": bool(self.random_ip_enabled_var.get()),
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
                    "is_location": bool(entry.is_location),
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
            f"有问题可在 GitHub 提交 issue 或发送电子邮件至 hungrym0@qq.com\n\n"
            f"官方网站: https://www.hungrym0.top/fuck-wjx.html\n"
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





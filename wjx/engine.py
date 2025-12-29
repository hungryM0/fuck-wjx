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
import importlib.util
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from threading import Thread
from typing import List, Optional, Union, Dict, Any, Tuple, Callable, Set, Deque, Literal
from urllib.parse import urlparse
import webbrowser

from wjx.random_ip import (
    _fetch_new_proxy_batch,
    _proxy_is_responsive,
    _normalize_proxy_address,
    on_random_ip_toggle,
    ensure_random_ip_ready,
    refresh_ip_counter_display,
    reset_ip_counter,
    handle_random_ip_submission,
    reset_quota_limit_dialog_flag,
    get_effective_proxy_api_url,
    get_custom_proxy_api_config_path,
    load_custom_proxy_api_config,
    save_custom_proxy_api_config,
    reset_custom_proxy_api_config,
)

from wjx.log_utils import (
    LOG_BUFFER_HANDLER,
    setup_logging,
    LOG_LIGHT_THEME,
    LOG_DARK_THEME,
    save_log_records_to_file,
    dump_threads_to_file,
    log_popup_info,
    log_popup_error,
    log_popup_warning,
    log_popup_confirm,
)

from wjx.updater import (
    check_updates_on_startup,
    show_update_notification,
    check_for_updates as _check_for_updates_impl,
    perform_update as _perform_update_impl,
)

import wjx.full_simulation_mode as full_simulation_mode
from wjx.full_simulation_mode import FULL_SIM_STATE as _FULL_SIM_STATE
import wjx.full_simulation_ui as full_simulation_ui
import wjx.timed_mode as timed_mode

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError
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
from wjx.version import __VERSION__, GITHUB_OWNER, GITHUB_REPO, ISSUE_FEEDBACK_URL
# 导入注册表管理器
# 导入配置常量
from wjx.config import (
    DEFAULT_HTTP_HEADERS,
    QQ_GROUP_QR_RELATIVE_PATH,
    PANED_MIN_LEFT_WIDTH,
    PANED_MIN_RIGHT_WIDTH,
    BROWSER_PREFERENCE,
    HEADLESS_WINDOW_SIZE,
    SUBMIT_INITIAL_DELAY,
    SUBMIT_CLICK_SETTLE_DELAY,
    POST_SUBMIT_URL_MAX_WAIT,
    POST_SUBMIT_URL_POLL_INTERVAL,
    POST_SUBMIT_FOLLOWUP_MAX_HOPS,
    POST_SUBMIT_CLOSE_GRACE_SECONDS,
    PROXY_REMOTE_URL,
    STOP_FORCE_WAIT_SECONDS,
    _GAODE_GEOCODE_ENDPOINT,
    _GAODE_GEOCODE_KEY,
    _LOCATION_GEOCODE_TIMEOUT,
    QUESTION_TYPE_LABELS,
    LOCATION_QUESTION_LABEL,
    DEFAULT_FILL_TEXT,
    _HTML_SPACE_RE,
    _LNGLAT_PATTERN,
    _MULTI_LIMIT_ATTRIBUTE_NAMES,
    _MULTI_LIMIT_VALUE_KEYSET,
    _MULTI_MIN_LIMIT_ATTRIBUTE_NAMES,
    _MULTI_MIN_LIMIT_VALUE_KEYSET,
    _SELECTION_KEYWORDS_CN,
    _SELECTION_KEYWORDS_EN,
    _CHINESE_MULTI_LIMIT_PATTERNS,
    _CHINESE_MULTI_RANGE_PATTERNS,
    _CHINESE_MULTI_MIN_PATTERNS,
    _ENGLISH_MULTI_LIMIT_PATTERNS,
    _ENGLISH_MULTI_RANGE_PATTERNS,
    _ENGLISH_MULTI_MIN_PATTERNS,
)

from wjx.browser_driver import (
    By,
    BrowserDriver,
    NoSuchElementException,
    PlaywrightDriver,
    PlaywrightElement,
    TimeoutException,
    create_playwright_driver as _browser_create_playwright_driver,
    kill_playwright_browser_processes as _kill_playwright_browser_processes,
    kill_processes_by_pid as _kill_processes_by_pid,
    list_browser_pids as _list_browser_pids,
)

# 以下字典/集合需要运行时初始化
_LOCATION_GEOCODE_CACHE: Dict[str, str] = {}
_LOCATION_GEOCODE_FAILURES: Set[str] = set()
_DETECTED_MULTI_LIMITS: Dict[Tuple[str, int], Optional[int]] = {}
_DETECTED_MULTI_LIMIT_RANGES: Dict[Tuple[str, int], Tuple[Optional[int], Optional[int]]] = {}
_REPORTED_MULTI_LIMITS: Set[Tuple[str, int]] = set()


def _weighted_index(probabilities: List[float]) -> int:
    if not probabilities:
        raise ValueError("probabilities cannot be empty")
    weights: List[float] = []
    total = 0.0
    for value in probabilities:
        try:
            weight = float(value)
        except Exception:
            weight = 0.0
        if math.isnan(weight) or math.isinf(weight) or weight < 0.0:
            weight = 0.0
        weights.append(weight)
        total += weight

    if total <= 0.0:
        return random.randrange(len(weights))

    pivot = random.random() * total
    running = 0.0
    for index, weight in enumerate(weights):
        running += weight
        if pivot <= running:
            return index
    return len(weights) - 1


def _generate_random_chinese_name_value() -> str:
    surname_pool = [
        "张", "王", "李", "赵", "陈", "杨", "刘", "黄", "周", "吴", "徐", "孙", "马", "朱", "胡", "林",
        "郭", "何", "高", "罗", "郑", "梁", "谢", "宋", "唐", "韩", "曹", "许", "邓", "冯",
    ]
    given_pool = "嘉伟俊涛明强磊洋超刚凯鹏华建鑫宇泽浩瑞博杰涛宁安晨泽轩磊晨豪轩皓轩梓轩浩宇子豪思远家豪文博宇航志强明浩志伟文涛文轩梓豪志鹏伟豪君豪承泽"
    surname = random.choice(surname_pool)
    given_len = 1 if random.random() < 0.65 else 2
    given = "".join(random.choice(given_pool) for _ in range(given_len))
    return f"{surname}{given}"


def _generate_random_mobile_value() -> str:
    prefixes = (
        "130", "131", "132", "133", "134", "135", "136", "137", "138", "139",
        "147", "150", "151", "152", "153", "155", "156", "157", "158", "159",
        "166", "171", "172", "173", "175", "176", "177", "178", "180", "181",
        "182", "183", "184", "185", "186", "187", "188", "189", "198", "199",
    )
    tail = "".join(str(random.randint(0, 9)) for _ in range(8))
    return random.choice(prefixes) + tail


def _generate_random_generic_text_value() -> str:
    samples = [
        "已填写", "同上", "无", "OK", "收到", "确认", "正常", "通过", "测试数据", "自动填写",
    ]
    base = random.choice(samples)
    suffix = str(random.randint(10, 999))
    return f"{base}{suffix}"


def _resolve_dynamic_text_token_value(token: Any) -> str:
    if token is None:
        return DEFAULT_FILL_TEXT
    text = str(token).strip()
    if text == "__RANDOM_NAME__":
        return _generate_random_chinese_name_value()
    if text == "__RANDOM_MOBILE__":
        return _generate_random_mobile_value()
    if text == "__RANDOM_TEXT__":
        return _generate_random_generic_text_value()
    return text or DEFAULT_FILL_TEXT


class AliyunCaptchaBypassError(RuntimeError):
    """检测到阿里云智能验证（需要人工交互）时抛出，用于触发全局停止。"""


class EmptySurveySubmissionError(RuntimeError):
    """检测到问卷未添加题目导致无法提交时抛出，用于关闭当前实例并继续下一份。"""



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
    
    # 仅匹配命令行中明确包含 playwright 痕迹的进程，避免误杀用户浏览器。
    # 说明：仅用 --user-data-dir 等通用参数会导致把用户正常浏览器也当成 Playwright 进程。
    playwright_indicators = [
        "playwright",
        "ms-playwright",
        "playwright_chromium",
        "playwright_firefox",
        "playwright_webkit",
    ]
    
    try:
        browser_names = {"msedge.exe", "chrome.exe", "chromium.exe"}
        indicators = [x.lower() for x in playwright_indicators if x]
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                proc_info = proc.info or {}
                proc_name = (proc_info.get("name") or "").lower()
                if proc_name not in browser_names:
                    continue
                try:
                    cmdline = proc.cmdline()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
                if not cmdline:
                    continue
                cmdline_str = " ".join(cmdline).lower()
                if not any(ind in cmdline_str for ind in indicators):
                    continue
                try:
                    proc.kill()
                    killed_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
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
    unique_pids = [int(p) for p in sorted(set(pids or [])) if int(p) > 0]
    if not unique_pids:
        return 0

    # 注意：这里返回的是“尝试终止”的数量；Windows 的 taskkill 不容易在静默模式下精确统计成功数。
    attempted = 0

    def _chunk(seq: List[int], size: int) -> List[List[int]]:
        return [seq[i : i + size] for i in range(0, len(seq), size)]

    # Windows 下优先用 taskkill，一次性杀多个 PID，避免每个 PID 都启动一个 taskkill 导致卡顿/GIL 抖动
    if sys.platform.startswith("win"):
        chunk_size = 24  # 兼顾命令行长度与调用次数
        for batch in _chunk(unique_pids, chunk_size):
            if not batch:
                continue
            args = ["taskkill", "/T", "/F"]
            for pid in batch:
                args.extend(["/PID", str(pid)])
            try:
                subprocess.run(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=6,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                attempted += len(batch)
            except Exception as exc:
                logging.debug(f"taskkill 批量清理失败: {exc}", exc_info=True)
        if attempted:
            logging.info(f"按 PID 已请求终止 {attempted} 个浏览器进程")
        return attempted

    # 非 Windows / taskkill 不可用：退化为 psutil 逐个 kill
    killed = 0
    try:
        import psutil  # type: ignore
    except Exception:
        return 0
    for pid in unique_pids:
        try:
            psutil.Process(pid).kill()
            killed += 1
        except Exception as exc:
            logging.debug(f"按 PID 清理浏览器失败 pid={pid}: {exc}", exc_info=True)
    if killed:
        logging.info(f"按 PID 共终止 {killed} 个浏览器进程")
    return killed


def create_playwright_driver(
    headless: bool = False,
    prefer_browsers: Optional[List[str]] = None,
    proxy_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    window_position: Optional[Tuple[int, int]] = None,
) -> Tuple[BrowserDriver, str]:
    """Delegate to browser_driver implementation (Playwright-only)."""
    return _browser_create_playwright_driver(
        headless=headless,
        prefer_browsers=prefer_browsers,
        proxy_address=proxy_address,
        user_agent=user_agent,
        window_position=window_position,
    )


def handle_aliyun_captcha(
    driver: BrowserDriver,
    timeout: int = 3,
    stop_signal: Optional[threading.Event] = None,
    raise_on_detect: bool = True,
) -> bool:
    """检测是否出现阿里云智能验证。

    之前这里会尝试点击“智能验证/开始验证”等按钮做绕过；现在按需求改为：
    - 未出现：返回 False
    - 出现：默认抛出 AliyunCaptchaBypassError，让上层触发全局停止
    """
    popup_locator = (By.ID, "aliyunCaptcha-window-popup")
    checkbox_locator = (By.ID, "aliyunCaptcha-checkbox-icon")
    checkbox_left_locator = (By.ID, "aliyunCaptcha-checkbox-left")
    checkbox_text_locator = (By.ID, "aliyunCaptcha-checkbox-text")

    def _probe_with_js(script: str) -> bool:
        """确保 JS 片段以 return 返回布尔值，避免 evaluate 丢失返回。"""
        js = script.strip()
        if not js.lstrip().startswith("return"):
            js = "return (" + js + ")"
        try:
            return bool(driver.execute_script(js))
        except Exception:
            return False

    def _verification_button_text_visible() -> bool:
        """检测页面/iframe 中是否出现可见的“智能验证/开始验证”按钮或文案。"""
        script = r"""
            (() => {
                const texts = ['智能验证', '开始验证', '点击开始智能验证'];
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const checkDoc = (doc) => {
                    const nodes = doc.querySelectorAll('button, a, span, div');
                    for (const el of nodes) {
                        if (!visible(el)) continue;
                        const txt = (el.innerText || el.textContent || '').trim();
                        if (!txt) continue;
                        for (const t of texts) {
                            if (txt.includes(t)) return true;
                        }
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
            if _challenge_visible() or _verification_button_text_visible():
                return True
            time.sleep(0.15)
        return _challenge_visible() or _verification_button_text_visible()

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

    logging.warning("检测到阿里云智能验证（按钮/弹窗）。")
    if raise_on_detect:
        raise AliyunCaptchaBypassError("检测到阿里云智能验证，按配置直接放弃")
    return True


url = ""

single_prob: List[Union[List[float], int, float, None]] = []
droplist_prob: List[Union[List[float], int, float, None]] = []
multiple_prob: List[List[float]] = []
matrix_prob: List[Union[List[float], int, float, None]] = []
scale_prob: List[Union[List[float], int, float, None]] = []
texts: List[List[str]] = []
texts_prob: List[List[float]] = []
# 多项填空题：同一题含多个输入框，内部使用 "||" 分隔每个填空项
MULTI_TEXT_DELIMITER = "||"
# 与 texts/texts_prob 对齐，记录每道填空题的具体类型（text / multi_text）
text_entry_types: List[str] = []
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
stop_on_fail_enabled = True
submit_interval_range_seconds: Tuple[int, int] = (0, 0)
answer_duration_range_seconds: Tuple[int, int] = (0, 0)
lock = threading.Lock()
stop_event = threading.Event()
full_simulation_enabled = False
full_simulation_estimated_seconds = 0
full_simulation_total_duration_seconds = 0
timed_mode_enabled = False
timed_mode_refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
random_proxy_ip_enabled = False
proxy_ip_pool: List[str] = []
random_user_agent_enabled = False
user_agent_pool_keys: List[str] = []
last_submit_had_captcha = False
_aliyun_captcha_stop_triggered = False
_aliyun_captcha_stop_lock = threading.Lock()
_target_reached_stop_triggered = False
_target_reached_stop_lock = threading.Lock()
_resume_after_aliyun_captcha_stop = False
_resume_snapshot: Dict[str, Any] = {}

# 极速模式：全真模拟/随机IP关闭且时间间隔为0时自动启用
def _is_fast_mode() -> bool:
    return (
        not full_simulation_enabled
        and not random_proxy_ip_enabled
        and submit_interval_range_seconds == (0, 0)
        and answer_duration_range_seconds == (0, 0)
    )


def _timed_mode_active() -> bool:
    return bool(timed_mode_enabled)


def _handle_submission_failure(stop_signal: Optional[threading.Event]) -> bool:
    """
    递增失败计数；当开启失败止损时超过阈值会触发停止。
    返回 True 表示已触发强制停止。
    """
    global cur_fail
    with lock:
        cur_fail += 1
        if stop_on_fail_enabled:
            print(f"已失败{cur_fail}次, 失败次数达到{int(fail_threshold)}次将强制停止")
        else:
            print(f"已失败{cur_fail}次（失败止损已关闭）")
    if stop_on_fail_enabled and cur_fail >= fail_threshold:
        logging.critical("失败次数过多，强制停止，请检查配置是否正确")
        if stop_signal:
            stop_signal.set()
        return True
    return False


def _trigger_aliyun_captcha_stop(
    gui_instance: Optional[Any],
    stop_signal: Optional[threading.Event],
) -> None:
    """检测到阿里云智能验证时触发全局停止，并提示用户启用随机 IP。"""
    global _aliyun_captcha_stop_triggered
    global _resume_after_aliyun_captcha_stop, _resume_snapshot
    with _aliyun_captcha_stop_lock:
        if _aliyun_captcha_stop_triggered:
            if stop_signal:
                stop_signal.set()
            return
        _aliyun_captcha_stop_triggered = True

    if stop_signal:
        stop_signal.set()

    try:
        _resume_after_aliyun_captcha_stop = True
        _resume_snapshot = {
            "url": url,
            "target": target_num,
            "cur_num": cur_num,
            "cur_fail": cur_fail,
        }
    except Exception:
        _resume_after_aliyun_captcha_stop = True
        _resume_snapshot = {}

    logging.warning("检测到阿里云智能验证，已触发全局停止。")

    message = (
        "检测到阿里云智能验证，为避免失败提交已停止所有任务。\n\n"
        "是否启用随机 IP 提交以绕过智能验证？\n"
    )

    def _notify():
        try:
            if gui_instance and hasattr(gui_instance, "force_stop_immediately"):
                gui_instance.force_stop_immediately(reason="触发智能验证")
            elif gui_instance and hasattr(gui_instance, "stop_run"):
                gui_instance.stop_run()
        except Exception:
            logging.debug("阿里云智能验证触发停止失败", exc_info=True)
        try:
            if threading.current_thread() is not threading.main_thread():
                return
            if gui_instance and hasattr(gui_instance, "_log_popup_confirm"):
                confirmed = bool(gui_instance._log_popup_confirm("智能验证提示", message, icon="warning"))
            else:
                confirmed = bool(log_popup_confirm("智能验证提示", message, icon="warning"))

            if confirmed and gui_instance:
                try:
                    var = getattr(gui_instance, "random_ip_enabled_var", None)
                    if var is not None and hasattr(var, "set"):
                        var.set(True)
                    on_random_ip_toggle(gui_instance)
                except Exception:
                    logging.warning("自动启用随机IP失败", exc_info=True)
        except Exception:
            logging.warning("弹窗提示用户启用随机IP失败")

    dispatcher = getattr(gui_instance, "_post_to_ui_thread", None) if gui_instance else None
    if callable(dispatcher):
        try:
            dispatcher(_notify)
            return
        except Exception:
            logging.debug("派发阿里云停止事件到主线程失败", exc_info=True)
    root = getattr(gui_instance, "root", None) if gui_instance else None
    if root is not None and threading.current_thread() is threading.main_thread():
        try:
            root.after(0, _notify)
            return
        except Exception:
            logging.debug("root.after 派发阿里云停止事件失败", exc_info=True)
    _notify()


def _trigger_target_reached_stop(
    gui_instance: Optional[Any],
    stop_signal: Optional[threading.Event],
) -> None:
    """达到目标份数时触发全局立即停止。"""
    global _target_reached_stop_triggered
    with _target_reached_stop_lock:
        if _target_reached_stop_triggered:
            if stop_signal:
                stop_signal.set()
            return
        _target_reached_stop_triggered = True

    if stop_signal:
        stop_signal.set()

    def _notify():
        try:
            if gui_instance and hasattr(gui_instance, "force_stop_immediately"):
                gui_instance.force_stop_immediately(reason="任务完成")
        except Exception:
            logging.debug("达到目标份数时触发强制停止失败", exc_info=True)

    dispatcher = getattr(gui_instance, "_post_to_ui_thread", None) if gui_instance else None
    if callable(dispatcher):
        try:
            dispatcher(_notify)
            return
        except Exception:
            logging.debug("派发任务完成事件到主线程失败", exc_info=True)
    root = getattr(gui_instance, "root", None) if gui_instance else None
    if root is not None and threading.current_thread() is threading.main_thread():
        try:
            root.after(0, _notify)
            return
        except Exception:
            pass
    _notify()


def _sync_full_sim_state_from_globals() -> None:
    """确保全真模拟全局变量与模块状态保持一致（主要在 GUI/运行线程之间传递配置时使用）。"""
    _FULL_SIM_STATE.enabled = bool(full_simulation_enabled)
    _FULL_SIM_STATE.estimated_seconds = int(full_simulation_estimated_seconds or 0)
    _FULL_SIM_STATE.total_duration_seconds = int(full_simulation_total_duration_seconds or 0)

def normalize_probabilities(values: List[float]) -> List[float]:
    if not values:
        raise ValueError("概率列表不能为空")
    total = sum(values)
    if total <= 0:
        raise ValueError("概率列表的和必须大于0")
    return [value / total for value in values]


def _normalize_single_like_prob_config(prob_config: Union[List[float], int, float, None], option_count: int) -> Union[List[float], int]:
    """
    将单选/下拉/量表的权重长度对齐到选项数。
    - -1 保持随机
    - 其余情况按 _normalize_droplist_probs 逻辑扩展/截断并归一化
    """
    if prob_config == -1 or prob_config is None:
        return -1
    return _normalize_droplist_probs(prob_config, option_count)


def _infer_option_count(entry: "QuestionEntry") -> int:
    """
    当配置中缺少选项数量时，尽可能从已保存的权重/文本推导。
    优先顺序：已有数量 > 自定义权重 > 概率列表长度 > 文本数量 >（量表题兜底为5）。
    """
    def _nested_length(raw: Any) -> Optional[int]:
        """用于矩阵题：当传入的是按行拆分的权重列表时，返回其中最长的一行长度。"""
        if not isinstance(raw, list):
            return None
        lengths: List[int] = []
        for item in raw:
            if isinstance(item, (list, tuple)):
                lengths.append(len(item))
        return max(lengths) if lengths else None

    # 矩阵题优先检查按行拆分的权重，避免把“行数”误当成列数
    if getattr(entry, "question_type", "") == "matrix":
        nested_len = _nested_length(getattr(entry, "custom_weights", None))
        if nested_len:
            return nested_len
        nested_len = _nested_length(getattr(entry, "probabilities", None))
        if nested_len:
            return nested_len

    try:
        if entry.option_count and entry.option_count > 0:
            return int(entry.option_count)
    except Exception:
        pass
    try:
        if entry.custom_weights and len(entry.custom_weights) > 0:
            return len(entry.custom_weights)
    except Exception:
        pass
    try:
        if isinstance(entry.probabilities, (list, tuple)) and len(entry.probabilities) > 0:
            return len(entry.probabilities)
    except Exception:
        pass
    try:
        if entry.texts and len(entry.texts) > 0:
            return len(entry.texts)
    except Exception:
        pass
    if getattr(entry, "question_type", "") == "scale":
        return 5
    return 0


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

        if self.question_type in ("text", "multi_text"):
            raw_samples = self.texts or []
            if self.question_type == "multi_text":
                formatted_samples: List[str] = []
                for sample in raw_samples:
                    try:
                        text_value = str(sample).strip()
                    except Exception:
                        text_value = ""
                    if not text_value:
                        continue
                    if MULTI_TEXT_DELIMITER in text_value:
                        parts = [part.strip() for part in text_value.split(MULTI_TEXT_DELIMITER)]
                        parts = [part for part in parts if part]
                        formatted_samples.append(" / ".join(parts) if parts else text_value)
                    else:
                        formatted_samples.append(text_value)
                samples = " | ".join(formatted_samples)
            else:
                samples = " | ".join(filter(None, raw_samples))
            preview = samples if samples else "未设置示例内容"
            if len(preview) > 60:
                preview = preview[:57] + "..."
            if self.is_location:
                label = "位置题"
            else:
                label = "多项填空题" if self.question_type == "multi_text" else "填空题"
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

            def _safe_weight(raw_value: Any) -> float:
                try:
                    return max(float(raw_value), 0.0)
                except Exception:
                    return 0.0

            weights_str = ":".join(_format_ratio(_safe_weight(w)) for w in self.custom_weights)
            return f"{self.option_count} 个选项 - 配比 {weights_str}{fillable_hint}"

        return f"{self.option_count} 个选项 - {mode_text}{fillable_hint}"


from wjx.load_save import ConfigPersistenceMixin, _select_user_agent_from_keys


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
    global single_prob, droplist_prob, multiple_prob, matrix_prob, scale_prob, texts, texts_prob, text_entry_types
    global single_option_fill_texts, droplist_option_fill_texts, multiple_option_fill_texts
    single_prob = []
    droplist_prob = []
    multiple_prob = []
    matrix_prob = []
    scale_prob = []
    texts = []
    texts_prob = []
    text_entry_types = []
    single_option_fill_texts = []
    droplist_option_fill_texts = []
    multiple_option_fill_texts = []

    for entry in entries:
        # 若配置里未写明选项数，尽量从权重/概率推断，并回写以便后续编辑显示正确数量
        inferred_count = _infer_option_count(entry)
        if inferred_count and inferred_count != entry.option_count:
            entry.option_count = inferred_count
        probs = entry.probabilities
        if entry.question_type == "single":
            single_prob.append(_normalize_single_like_prob_config(probs, entry.option_count))
            single_option_fill_texts.append(_normalize_option_fill_texts(entry.option_fill_texts, entry.option_count))
        elif entry.question_type == "dropdown":
            droplist_prob.append(_normalize_single_like_prob_config(probs, entry.option_count))
            droplist_option_fill_texts.append(_normalize_option_fill_texts(entry.option_fill_texts, entry.option_count))
        elif entry.question_type == "multiple":
            if not isinstance(probs, list):
                raise ValueError("多选题必须提供概率列表，数值范围0-100")
            multiple_prob.append([float(value) for value in probs])
            multiple_option_fill_texts.append(_normalize_option_fill_texts(entry.option_fill_texts, entry.option_count))
        elif entry.question_type == "matrix":
            rows = max(1, entry.rows)
            option_count = max(1, _infer_option_count(entry))

            def _normalize_row(raw_row: Any) -> Optional[List[float]]:
                if not isinstance(raw_row, (list, tuple)):
                    return None
                cleaned: List[float] = []
                for value in raw_row:
                    try:
                        cleaned.append(max(0.0, float(value)))
                    except Exception:
                        continue
                if not cleaned:
                    return None
                if len(cleaned) < option_count:
                    cleaned = cleaned + [1.0] * (option_count - len(cleaned))
                elif len(cleaned) > option_count:
                    cleaned = cleaned[:option_count]
                try:
                    return normalize_probabilities(cleaned)
                except Exception:
                    return None

            # 支持按行配置的权重（list[list]），否则退化为对所有行复用同一组
            row_weights_source: Optional[List[Any]] = None
            if isinstance(probs, list) and any(isinstance(item, (list, tuple)) for item in probs):
                row_weights_source = probs
            elif isinstance(entry.custom_weights, list) and any(isinstance(item, (list, tuple)) for item in entry.custom_weights):  # type: ignore[attr-defined]
                row_weights_source = entry.custom_weights  # type: ignore[attr-defined]

            if row_weights_source is not None:
                last_row: Optional[Any] = None
                for idx in range(rows):
                    raw_row = row_weights_source[idx] if idx < len(row_weights_source) else last_row
                    normalized_row = _normalize_row(raw_row)
                    if normalized_row is None:
                        normalized_row = [1.0 / option_count] * option_count
                    matrix_prob.append(normalized_row)
                    last_row = raw_row if raw_row is not None else last_row
            elif isinstance(probs, list):
                normalized = _normalize_row(probs)
                if normalized is None:
                    normalized = [1.0 / option_count] * option_count
                for _ in range(rows):
                    matrix_prob.append(list(normalized))
            else:
                for _ in range(rows):
                    matrix_prob.append(-1)
        elif entry.question_type == "scale":
            scale_prob.append(_normalize_single_like_prob_config(probs, entry.option_count))
        elif entry.question_type in ("text", "multi_text"):
            raw_values = entry.texts or []
            normalized_values: List[str] = []
            for item in raw_values:
                try:
                    text_value = str(item).strip()
                except Exception:
                    text_value = ""
                if text_value:
                    normalized_values.append(text_value)
            if not normalized_values:
                raise ValueError("填空题至少需要一个候选答案")
            if isinstance(probs, list) and len(probs) == len(normalized_values):
                normalized = normalize_probabilities([float(value) for value in probs])
            else:
                normalized = normalize_probabilities([1.0] * len(normalized_values))
            texts.append(normalized_values)
            texts_prob.append(normalized)
            text_entry_types.append(entry.question_type)


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


def _count_prefixed_text_inputs_driver(driver: BrowserDriver, question_number: int, question_div=None) -> int:
    """Count inputs like q{num}_1 used by gap-fill/multi-text questions."""
    if not question_number:
        return 0
    prefix = f"q{question_number}_"
    selector = (
        f"input[id^='{prefix}'], textarea[id^='{prefix}'], "
        f"input[name^='{prefix}'], textarea[name^='{prefix}']"
    )
    try:
        if question_div is not None:
            elements = question_div.find_elements(By.CSS_SELECTOR, selector)
        else:
            elements = driver.find_elements(By.CSS_SELECTOR, f"#div{question_number} {selector}")
    except Exception:
        return 0
    return len(elements)


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


def _driver_question_looks_like_reorder(question_div) -> bool:
    """兜底判断：当 type 属性异常/缺失时，尝试通过 DOM 特征识别排序题。"""
    if question_div is None:
        return False
    try:
        if question_div.find_elements(By.CSS_SELECTOR, ".sortnum, .sortnum-sel"):
            return True
    except Exception:
        pass
    try:
        # 仅作为兜底：需要同时满足“存在列表项”与“具备排序/拖拽特征”，避免误判普通题型
        has_list_items = bool(question_div.find_elements(By.CSS_SELECTOR, "ul li, ol li"))
        has_sort_signature = bool(
            question_div.find_elements(By.CSS_SELECTOR, ".ui-sortable, .ui-sortable-handle, [class*='sort']")
        )
        return has_list_items and has_sort_signature
    except Exception:
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


def _extract_jump_rules_from_html(question_div, question_number: int, option_texts: List[str]) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    从静态 HTML 中提取跳题逻辑。
    返回 (是否声明有跳题, 跳转规则列表)，其中规则形如：
    {"option_index": 1, "jumpto": 4, "option_text": "选项2"}。
    """
    has_jump_attr = str(question_div.get("hasjump") or "").strip() == "1"
    jump_rules: List[Dict[str, Any]] = []
    option_idx = 0
    inputs = question_div.find_all("input")
    for input_el in inputs:
        input_type = (input_el.get("type") or "").lower()
        if input_type not in ("radio", "checkbox"):
            continue
        jumpto_raw = input_el.get("jumpto") or input_el.get("data-jumpto")
        if not jumpto_raw:
            option_idx += 1
            continue
        text_value = str(jumpto_raw).strip()
        jumpto_num: Optional[int] = None
        if text_value.isdigit():
            jumpto_num = int(text_value)
        else:
            match = re.search(r"(\d+)", text_value)
            if match:
                try:
                    jumpto_num = int(match.group(1))
                except Exception:
                    jumpto_num = None
        if jumpto_num:
            jump_rules.append({
                "option_index": option_idx,
                "jumpto": jumpto_num,
                "option_text": option_texts[option_idx] if option_idx < len(option_texts) else None,
            })
        option_idx += 1
    return has_jump_attr or bool(jump_rules), jump_rules


_TEXT_INPUT_ALLOWED_TYPES = {"", "text", "search", "tel", "number"}
_KNOWN_NON_TEXT_QUESTION_TYPES = {"3", "4", "5", "6", "7", "8", "11"}


def _count_text_inputs_in_soup(question_div) -> int:
    try:
        candidates = question_div.find_all(["input", "textarea", "span", "div"])
    except Exception:
        return 0
    count = 0
    for cand in candidates:
        try:
            tag_name = (cand.name or "").lower()
        except Exception:
            tag_name = ""
        input_type = ""
        try:
            input_type = (cand.get("type") or "").lower()
        except Exception:
            input_type = ""
        style_text = ""
        try:
            style_text = (cand.get("style") or "").lower()
        except Exception:
            style_text = ""
        try:
            class_attr = cand.get("class") or []
            if isinstance(class_attr, str):
                class_text = class_attr.lower()
            else:
                class_text = " ".join(class_attr).lower()
        except Exception:
            class_text = ""
        is_textcont = "textcont" in class_text or "textedit" in class_text

        # 跳过隐藏元素（type hidden 或 display:none）
        if input_type == "hidden" or "display:none" in style_text or "visibility:hidden" in style_text:
            continue

        # 若 input 紧跟着 textEdit 的 contenteditable，避免重复计数，交给 span/div 处理
        if tag_name == "input":
            try:
                sibling = cand.find_next_sibling()
                sibling_classes = sibling.get("class") if sibling else None
                if sibling_classes and any("textedit" in cls.lower() for cls in sibling_classes):
                    continue
            except Exception:
                pass
        if tag_name == "textarea" or (tag_name == "input" and input_type in _TEXT_INPUT_ALLOWED_TYPES):
            count += 1
            continue
        try:
            contenteditable = (cand.get("contenteditable") or "").lower() == "true"
        except Exception:
            contenteditable = False
        if (contenteditable or is_textcont) and tag_name in {"span", "div"}:
            count += 1
    return count


def _count_visible_text_inputs_driver(question_div) -> int:
    try:
        candidates = question_div.find_elements(
            By.CSS_SELECTOR,
            "input, textarea, span[contenteditable='true'], div[contenteditable='true'], .textCont, .textcont"
        )
    except Exception:
        candidates = []
    count = 0
    for cand in candidates:
        try:
            tag_name = (cand.tag_name or "").lower()
        except Exception:
            tag_name = ""
        input_type = ""
        try:
            input_type = (cand.get_attribute("type") or "").lower()
        except Exception:
            input_type = ""
        try:
            style_text = (cand.get_attribute("style") or "").lower()
        except Exception:
            style_text = ""
        try:
            class_attr = (cand.get_attribute("class") or "").lower()
        except Exception:
            class_attr = ""
        is_textcont = "textcont" in class_attr or "textedit" in class_attr

        # 跳过隐藏元素（type hidden 或 display:none / visibility:hidden）
        if input_type == "hidden" or "display:none" in style_text or "visibility:hidden" in style_text:
            continue
        # 若 input 后紧跟 textEdit 的 contenteditable，避免重复计数
        if tag_name == "input":
            try:
                sibling = cand.find_element(By.XPATH, "following-sibling::*[1]")
                sibling_tag = (sibling.tag_name or "").lower()
                sibling_class = (sibling.get_attribute("class") or "").lower()
                if sibling_tag in {"label", "div", "span"} and "textedit" in sibling_class:
                    continue
            except Exception:
                pass

        if tag_name == "textarea" or (tag_name == "input" and input_type in _TEXT_INPUT_ALLOWED_TYPES):
            try:
                if cand.is_displayed():
                    count += 1
            except Exception:
                count += 1
            continue
        try:
            contenteditable = (cand.get_attribute("contenteditable") or "").lower() == "true"
        except Exception:
            contenteditable = False
        if (contenteditable or is_textcont) and tag_name in {"span", "div"}:
            try:
                if cand.is_displayed():
                    count += 1
            except Exception:
                count += 1
    return count


def _count_choice_inputs_driver(question_div) -> Tuple[int, int]:
    try:
        inputs = question_div.find_elements(By.CSS_SELECTOR, "input[type='checkbox'], input[type='radio']")
    except Exception:
        inputs = []
    checkbox_count = 0
    radio_count = 0
    for ipt in inputs:
        try:
            input_type = (ipt.get_attribute("type") or "").lower()
        except Exception:
            input_type = ""
        try:
            style_text = (ipt.get_attribute("style") or "").lower()
        except Exception:
            style_text = ""
        if input_type == "hidden" or "display:none" in style_text or "visibility:hidden" in style_text:
            continue
        try:
            if not ipt.is_displayed():
                continue
        except Exception:
            pass
        if input_type == "checkbox":
            checkbox_count += 1
        elif input_type == "radio":
            radio_count += 1
    return checkbox_count, radio_count


def _normalize_question_type_code(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value).strip()
    except Exception:
        return ""


def _should_treat_question_as_text_like(type_code: Any, option_count: int, text_input_count: int) -> bool:
    normalized = _normalize_question_type_code(type_code)
    if normalized in ("1", "2"):
        return text_input_count > 0
    if normalized in _KNOWN_NON_TEXT_QUESTION_TYPES:
        return False
    return (option_count or 0) == 0 and text_input_count > 0


def _should_mark_as_multi_text(type_code: Any, option_count: int, text_input_count: int, is_location: bool) -> bool:
    if is_location or text_input_count < 2:
        return False
    normalized = _normalize_question_type_code(type_code)
    if normalized in ("1", "2"):
        return True
    if normalized in _KNOWN_NON_TEXT_QUESTION_TYPES:
        return False
    if (option_count or 0) == 0:
        return True
    return (option_count or 0) <= 1 and text_input_count >= 2


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
            has_jump, jump_rules = _extract_jump_rules_from_html(question_div, question_number, option_texts)
            text_input_count = _count_text_inputs_in_soup(question_div)
            is_text_like_question = _should_treat_question_as_text_like(type_code, option_count, text_input_count)
            is_multi_text = _should_mark_as_multi_text(type_code, option_count, text_input_count, is_location)
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
                "text_inputs": text_input_count,
                "is_multi_text": is_multi_text,
                "is_text_like": is_text_like_question,
                "has_jump": has_jump,
                "jump_rules": jump_rules,
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


def _extract_range_from_json_obj(obj: Any) -> Tuple[Optional[int], Optional[int]]:
    min_limit: Optional[int] = None
    max_limit: Optional[int] = None
    if isinstance(obj, dict):
        for key, value in obj.items():
            normalized_key = str(key).lower()
            if normalized_key in _MULTI_MIN_LIMIT_VALUE_KEYSET:
                candidate = _safe_positive_int(value)
                if candidate:
                    min_limit = min_limit or candidate
            if normalized_key in _MULTI_LIMIT_VALUE_KEYSET:
                candidate = _safe_positive_int(value)
                if candidate:
                    max_limit = max_limit or candidate
            nested_min, nested_max = _extract_range_from_json_obj(value)
            if min_limit is None and nested_min is not None:
                min_limit = nested_min
            if max_limit is None and nested_max is not None:
                max_limit = nested_max
            if min_limit is not None and max_limit is not None:
                break
    elif isinstance(obj, list):
        for item in obj:
            nested_min, nested_max = _extract_range_from_json_obj(item)
            if min_limit is None and nested_min is not None:
                min_limit = nested_min
            if max_limit is None and nested_max is not None:
                max_limit = nested_max
            if min_limit is not None and max_limit is not None:
                break
    return min_limit, max_limit


def _extract_range_from_possible_json(text: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    min_limit: Optional[int] = None
    max_limit: Optional[int] = None
    if not text:
        return min_limit, max_limit
    normalized = text.strip()
    if not normalized:
        return min_limit, max_limit
    candidates = [normalized]
    if normalized.startswith("{") and "'" in normalized and '"' not in normalized:
        candidates.append(normalized.replace("'", '"'))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        cand_min, cand_max = _extract_range_from_json_obj(parsed)
        if min_limit is None and cand_min is not None:
            min_limit = cand_min
        if max_limit is None and cand_max is not None:
            max_limit = cand_max
        if min_limit is not None and max_limit is not None:
            return min_limit, max_limit
    for key in _MULTI_MIN_LIMIT_VALUE_KEYSET:
        pattern = re.compile(rf"{re.escape(key)}\s*[:=]\s*(\d+)", re.IGNORECASE)
        match = pattern.search(normalized)
        if match:
            candidate = _safe_positive_int(match.group(1))
            if candidate:
                min_limit = min_limit or candidate
                if max_limit is not None:
                    return min_limit, max_limit
    for key in _MULTI_LIMIT_VALUE_KEYSET:
        pattern = re.compile(rf"{re.escape(key)}\s*[:=]\s*(\d+)", re.IGNORECASE)
        match = pattern.search(normalized)
        if match:
            candidate = _safe_positive_int(match.group(1))
            if candidate:
                max_limit = max_limit or candidate
                if min_limit is not None:
                    return min_limit, max_limit
    return min_limit, max_limit


def _extract_min_max_from_attributes(element) -> Tuple[Optional[int], Optional[int]]:
    min_limit = None
    max_limit = None
    for attr in _MULTI_MIN_LIMIT_ATTRIBUTE_NAMES:
        try:
            raw_value = element.get_attribute(attr)
        except Exception:
            continue
        candidate = _safe_positive_int(raw_value)
        if candidate:
            min_limit = candidate
            break
    for attr in _MULTI_LIMIT_ATTRIBUTE_NAMES:
        try:
            raw_value = element.get_attribute(attr)
        except Exception:
            continue
        candidate = _safe_positive_int(raw_value)
        if candidate:
            max_limit = candidate
            break
    return min_limit, max_limit


def _extract_multi_limit_range_from_text(text: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    if not text:
        return None, None
    normalized = text.strip()
    if not normalized:
        return None, None
    normalized_lower = normalized.lower()
    min_limit: Optional[int] = None
    max_limit: Optional[int] = None
    contains_cn_keyword = any(keyword in normalized for keyword in _SELECTION_KEYWORDS_CN)
    contains_en_keyword = any(keyword in normalized_lower for keyword in _SELECTION_KEYWORDS_EN)
    if contains_cn_keyword:
        for pattern in _CHINESE_MULTI_RANGE_PATTERNS:
            match = pattern.search(normalized)
            if match:
                first = _safe_positive_int(match.group(1))
                second = _safe_positive_int(match.group(2))
                if first and second:
                    min_limit = min(first, second)
                    max_limit = max(first, second)
                    break
    if min_limit is None and max_limit is None and contains_en_keyword:
        for pattern in _ENGLISH_MULTI_RANGE_PATTERNS:
            match = pattern.search(normalized)
            if match:
                first = _safe_positive_int(match.group(1))
                second = _safe_positive_int(match.group(2))
                if first and second:
                    min_limit = min(first, second)
                    max_limit = max(first, second)
                    break
    if min_limit is None and contains_cn_keyword:
        for pattern in _CHINESE_MULTI_MIN_PATTERNS:
            match = pattern.search(normalized)
            if match:
                candidate = _safe_positive_int(match.group(1))
                if candidate:
                    min_limit = candidate
                    break
    if max_limit is None and contains_cn_keyword:
        for pattern in _CHINESE_MULTI_LIMIT_PATTERNS:
            match = pattern.search(normalized)
            if match:
                candidate = _safe_positive_int(match.group(1))
                if candidate:
                    max_limit = candidate
                    break
    if min_limit is None and contains_en_keyword:
        for pattern in _ENGLISH_MULTI_MIN_PATTERNS:
            match = pattern.search(normalized_lower)
            if match:
                candidate = _safe_positive_int(match.group(1))
                if candidate:
                    min_limit = candidate
                    break
    if max_limit is None and contains_en_keyword:
        for pattern in _ENGLISH_MULTI_LIMIT_PATTERNS:
            match = pattern.search(normalized_lower)
            if match:
                candidate = _safe_positive_int(match.group(1))
                if candidate:
                    max_limit = candidate
                    break
    if min_limit is not None and max_limit is not None and min_limit > max_limit:
        min_limit, max_limit = max_limit, min_limit
    return min_limit, max_limit


def _get_driver_session_key(driver: BrowserDriver) -> str:
    session_id = getattr(driver, "session_id", None)
    if session_id:
        return str(session_id)
    return f"id-{id(driver)}"


def detect_multiple_choice_limit_range(driver: BrowserDriver, question_number: int) -> Tuple[Optional[int], Optional[int]]:
    cache_key = (_get_driver_session_key(driver), question_number)
    if cache_key in _DETECTED_MULTI_LIMIT_RANGES:
        return _DETECTED_MULTI_LIMIT_RANGES[cache_key]
    min_limit: Optional[int] = None
    max_limit: Optional[int] = None
    try:
        container = driver.find_element(By.CSS_SELECTOR, f"#div{question_number}")
    except NoSuchElementException:
        container = None
    if container is not None:
        attr_min, attr_max = _extract_min_max_from_attributes(container)
        if attr_min is not None:
            min_limit = attr_min
        if attr_max is not None:
            max_limit = attr_max
        if min_limit is None or max_limit is None:
            for attr_name in ("data", "data-setting", "data-validate"):
                cand_min, cand_max = _extract_range_from_possible_json(container.get_attribute(attr_name))
                if min_limit is None and cand_min is not None:
                    min_limit = cand_min
                if max_limit is None and cand_max is not None:
                    max_limit = cand_max
                if min_limit is not None and max_limit is not None:
                    break
        if min_limit is None or max_limit is None:
            fragments: List[str] = []
            for selector in (".qtypetip", ".topichtml", ".field-label"):
                try:
                    fragments.append(container.find_element(By.CSS_SELECTOR, selector).text)
                except Exception:
                    continue
            fragments.append(container.text)
            for fragment in fragments:
                cand_min, cand_max = _extract_multi_limit_range_from_text(fragment)
                if min_limit is None and cand_min is not None:
                    min_limit = cand_min
                if max_limit is None and cand_max is not None:
                    max_limit = cand_max
                if min_limit is not None and max_limit is not None:
                    break
        if min_limit is None or max_limit is None:
            html = container.get_attribute("outerHTML")
            cand_min, cand_max = _extract_range_from_possible_json(html)
            if min_limit is None and cand_min is not None:
                min_limit = cand_min
            if max_limit is None and cand_max is not None:
                max_limit = cand_max
            if min_limit is None or max_limit is None:
                cand_min, cand_max = _extract_multi_limit_range_from_text(html)
                if min_limit is None and cand_min is not None:
                    min_limit = cand_min
                if max_limit is None and cand_max is not None:
                    max_limit = cand_max
    if min_limit is not None and max_limit is not None and min_limit > max_limit:
        min_limit, max_limit = max_limit, min_limit
    _DETECTED_MULTI_LIMIT_RANGES[cache_key] = (min_limit, max_limit)
    _DETECTED_MULTI_LIMITS[cache_key] = max_limit
    return min_limit, max_limit


def detect_multiple_choice_limit(driver: BrowserDriver, question_number: int) -> Optional[int]:
    _, max_limit = detect_multiple_choice_limit_range(driver, question_number)
    return max_limit


def _log_multi_limit_once(
    driver: BrowserDriver, question_number: int, min_limit: Optional[int], max_limit: Optional[int]
) -> None:
    if min_limit is None and max_limit is None:
        return
    cache_key = (_get_driver_session_key(driver), question_number)
    if cache_key in _REPORTED_MULTI_LIMITS:
        return
    # 仅标记已处理的题目，不再输出限制日志以保持日志简洁
    _REPORTED_MULTI_LIMITS.add(cache_key)


def _extract_reorder_required_from_text(text: Optional[str], total_options: Optional[int] = None) -> Optional[int]:
    if not text:
        return None
    normalized = text.strip()
    if not normalized:
        return None
    if total_options:
        all_keywords = ("全选", "全部选择", "请选择全部", "全部选项", "所有选项", "全部排序", "全都排序")
        if any(keyword in normalized for keyword in all_keywords):
            return total_options
        range_patterns = (
            re.compile(r"数字?\s*(\d+)\s*[-~—－到]\s*(\d+)\s*填"),
            re.compile(r"(\d+)\s*[-~—－到]\s*(\d+)\s*填入括号"),
        )
        for pattern in range_patterns:
            match = pattern.search(normalized)
            if match:
                first = _safe_positive_int(match.group(1))
                second = _safe_positive_int(match.group(2))
                if first and second and max(first, second) == total_options:
                    return total_options
    patterns = (
        re.compile(r"(?:选|选择|勾选|挑选)[^0-9]{0,4}(\d+)\s*[项个条]"),
        re.compile(r"至少\s*(\d+)\s*[项个条]"),
    )
    for pattern in patterns:
        match = pattern.search(normalized)
        if match:
            return _safe_positive_int(match.group(1))
    return None


def detect_reorder_required_count(
    driver: BrowserDriver, question_number: int, total_options: Optional[int] = None
) -> Optional[int]:
    """检测多选排序题需要勾选的数量，优先使用通用限制解析，失败后额外从题干文本抽取。"""
    limit = detect_multiple_choice_limit(driver, question_number)
    detected_required: Optional[int] = None
    try:
        container = driver.find_element(By.CSS_SELECTOR, f"#div{question_number}")
    except NoSuchElementException:
        container = None
    if container is None:
        return None
    fragments: List[str] = []
    for selector in (".qtypetip", ".topichtml", ".field-label"):
        try:
            fragments.append(container.find_element(By.CSS_SELECTOR, selector).text)
        except Exception:
            continue
    try:
        fragments.append(container.text)
    except Exception:
        pass
    for fragment in fragments:
        required = _extract_reorder_required_from_text(fragment, total_options)
        if required:
            print(f"第{question_number}题检测到需要选择 {required} 项并排序。")
            detected_required = required
            break
    if detected_required is not None:
        return detected_required
    return limit


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


def _fill_contenteditable_element(driver: BrowserDriver, element, value: str) -> None:
    """在可编辑的 span/div 上模拟“点击-输入-派发事件”的行为，并同步隐藏输入框。"""
    text_value = value if value else DEFAULT_FILL_TEXT
    # 尝试让元素获取焦点并清空历史内容
    try:
        driver.execute_script(
            """
            const el = arguments[0];
            if (!el) { return; }
            try { el.focus(); } catch (err) {}
            if (window.getSelection && document.createRange) {
                const sel = window.getSelection();
                const range = document.createRange();
                try {
                    range.selectNodeContents(el);
                    sel.removeAllRanges();
                    sel.addRange(range);
                } catch (err) {}
            }
            if (document.execCommand) {
                try { document.execCommand('delete'); } catch (err) {}
            }
            try { el.innerText = ''; } catch (err) { el.textContent = ''; }
            """,
            element,
        )
    except Exception:
        pass

    typed_successfully = False
    try:
        element.send_keys(text_value)
        typed_successfully = True
    except Exception:
        typed_successfully = False

    driver.execute_script(
        """
        const el = arguments[0];
        const value = arguments[1];
        const typed = !!arguments[2];
        if (!el) {
            return;
        }
        if (!typed) {
            try { el.innerText = value; } catch (err) { el.textContent = value; }
        }
        const eventOptions = { bubbles: true };
        ['input','change','blur','keyup','keydown','keypress'].forEach(name => {
            try { el.dispatchEvent(new Event(name, eventOptions)); } catch (err) {}
        });
        const container = el.closest ? el.closest('.textEdit') : null;
        let hiddenInput = null;
        if (container) {
            hiddenInput = container.querySelector('input[type="text"], input[type="hidden"]');
            if (!hiddenInput) {
                hiddenInput = container.previousElementSibling;
            }
        }
        if (hiddenInput && hiddenInput.tagName && (hiddenInput.type === 'text' || hiddenInput.type === 'hidden')) {
            try {
                hiddenInput.value = value;
                hiddenInput.setAttribute('value', value);
            } catch (err) {}
            ['input','change','blur','keyup','keydown','keypress'].forEach(name => {
                try { hiddenInput.dispatchEvent(new Event(name, eventOptions)); } catch (err) {}
            });
        }
        """,
        element,
        text_value,
        typed_successfully,
    )


def vacant(driver: BrowserDriver, current, index):
    def _infer_text_entry(driver_obj: BrowserDriver, q_num: int) -> Tuple[str, List[str]]:
        try:
            q_div = driver_obj.find_element(By.CSS_SELECTOR, f"#div{q_num}")
        except Exception:
            q_div = None
        text_input_count = _count_visible_text_inputs_driver(q_div) if q_div is not None else 0
        prefixed_text_count = _count_prefixed_text_inputs_driver(driver_obj, q_num, q_div)
        is_location_question = _driver_question_is_location(q_div) if q_div is not None else False
        has_multi_text_signature = prefixed_text_count > 0
        is_multi = _should_mark_as_multi_text("1", 0, text_input_count, is_location_question)
        if not is_multi and has_multi_text_signature and not is_location_question:
            is_multi = True
        if is_multi:
            blanks_hint = prefixed_text_count if prefixed_text_count > 0 else text_input_count
            blanks = max(1, blanks_hint or 1)
            if not has_multi_text_signature:
                blanks = max(2, blanks)
            default_answer = MULTI_TEXT_DELIMITER.join([DEFAULT_FILL_TEXT] * blanks)
            return "multi_text", [default_answer]
        return "text", [DEFAULT_FILL_TEXT]

    if index < len(texts):
        answer_candidates = texts[index]
        selection_probabilities = texts_prob[index] if index < len(texts_prob) else [1.0]
        entry_kind = text_entry_types[index] if index < len(text_entry_types) else "text"
    else:
        entry_kind, answer_candidates = _infer_text_entry(driver, current)
        selection_probabilities = normalize_probabilities([1.0] * len(answer_candidates)) if answer_candidates else [1.0]

    if not answer_candidates:
        answer_candidates = [DEFAULT_FILL_TEXT]
    if len(selection_probabilities) != len(answer_candidates):
        selection_probabilities = normalize_probabilities([1.0] * len(answer_candidates))
    resolved_candidates = []
    for candidate in answer_candidates:
        try:
            text_value = _resolve_dynamic_text_token_value(candidate)
        except Exception:
            text_value = DEFAULT_FILL_TEXT
        resolved_candidates.append(text_value if text_value else DEFAULT_FILL_TEXT)

    if len(selection_probabilities) != len(resolved_candidates):
        selection_probabilities = normalize_probabilities([1.0] * len(resolved_candidates))

    selected_index = _weighted_index(selection_probabilities)
    selected_answer = resolved_candidates[selected_index] if resolved_candidates else DEFAULT_FILL_TEXT

    if entry_kind != "multi_text":
        prefixed_text_count = _count_prefixed_text_inputs_driver(driver, current)
        if prefixed_text_count > 0:
            entry_kind = "multi_text"

    if entry_kind == "multi_text":
        raw_text = "" if selected_answer is None else str(selected_answer)
        if MULTI_TEXT_DELIMITER in raw_text:
            parts = raw_text.split(MULTI_TEXT_DELIMITER)
        elif "|" in raw_text:
            parts = raw_text.split("|")
        else:
            parts = [raw_text]
        values = [part.strip() for part in parts]

        # 若答案为空，使用默认填充值避免必填题校验不通过
        if not values or all(not v for v in values):
            values = [DEFAULT_FILL_TEXT]

        # 先区分「可见可编辑」与「隐藏/不可见」的输入，避免把答案映射到隐藏框导致填充失败
        primary_inputs: List[Any] = []   # 优先填写：contenteditable 节点、可见输入框
        secondary_inputs: List[Any] = [] # 兜底填写：隐藏或不可见的输入框
        seen_nodes: Set[int] = set()
        question_div = None
        try:
            question_div = driver.find_element(By.CSS_SELECTOR, f"#div{current}")
            candidates = question_div.find_elements(By.CSS_SELECTOR, "input, textarea")
        except Exception:
            candidates = []

        def _mark_and_append(target_list: List[Any], node: Any):
            obj_id = id(node)
            if obj_id in seen_nodes:
                return
            seen_nodes.add(obj_id)
            target_list.append(node)

        def _collect_text_inputs(cands: List[Any]):
            for candidate in cands:
                try:
                    tag_name = (candidate.tag_name or "").lower()
                except Exception:
                    tag_name = ""
                try:
                    input_type = (candidate.get_attribute("type") or "").lower()
                except Exception:
                    input_type = ""
                try:
                    contenteditable_attr = (candidate.get_attribute("contenteditable") or "").lower()
                except Exception:
                    contenteditable_attr = ""
                try:
                    class_attr = (candidate.get_attribute("class") or "").lower()
                except Exception:
                    class_attr = ""
                is_contenteditable = (contenteditable_attr == "true") or ("textcont" in class_attr and tag_name in {"span", "div"})

                # 兼容内容可编辑的 span/div（如问卷星 gapfill 的 textCont），不再依赖显示检测
                if is_contenteditable and tag_name in {"span", "div"}:
                    _mark_and_append(primary_inputs, candidate)
                    continue

                # 优先收集可见的常规输入框，若可见性检测返回 False 也尝试保留一次
                if tag_name == "textarea" or (tag_name == "input" and input_type in ("", "text", "search", "tel", "number")):
                    try:
                        displayed = candidate.is_displayed()
                    except Exception:
                        displayed = True
                    # hidden 类型直接归类为兜底节点，避免占用答案顺序
                    if input_type == "hidden":
                        _mark_and_append(secondary_inputs, candidate)
                        continue
                    if displayed:
                        _mark_and_append(primary_inputs, candidate)
                        continue
                    _mark_and_append(secondary_inputs, candidate)

        _collect_text_inputs(candidates)

        # 兜底查找 contenteditable 的文本节点，并保持 DOM 顺序
        if question_div:
            try:
                editable_nodes = question_div.find_elements(By.CSS_SELECTOR, "span[contenteditable='true'], div[contenteditable='true'], .textCont")
            except Exception:
                editable_nodes = []
            _collect_text_inputs(editable_nodes)

        # 兜底：部分多项填空的输入框不会出现在通用查询结果里，尝试按 id 前缀再找一遍
        if question_div and (len(primary_inputs) + len(secondary_inputs)) < 2:
            try:
                fallback_candidates = question_div.find_elements(By.CSS_SELECTOR, f"input[id^='q{current}_'], textarea[id^='q{current}_']")
            except Exception:
                fallback_candidates = []
            _collect_text_inputs(fallback_candidates)

        if not primary_inputs and not secondary_inputs:
            try:
                primary_inputs = [driver.find_element(By.CSS_SELECTOR, f"#q{current}")]
            except Exception:
                primary_inputs = []

        input_elements = primary_inputs + secondary_inputs if primary_inputs else secondary_inputs
        visible_count = len(primary_inputs) if primary_inputs else len(input_elements)

        # 若答案数量少于可见输入框数量，扩展默认值；隐藏输入框不再占用答案配额
        fill_values = [v if v else DEFAULT_FILL_TEXT for v in values] or [DEFAULT_FILL_TEXT]
        while len(fill_values) < visible_count:
            fill_values.append(DEFAULT_FILL_TEXT)

        def _resolve_value_for_index(idx: int) -> str:
            if idx < visible_count:
                return fill_values[idx] if idx < len(fill_values) else DEFAULT_FILL_TEXT
            rel = idx - visible_count
            if rel < len(fill_values):
                return fill_values[rel]
            return fill_values[-1] if fill_values else DEFAULT_FILL_TEXT

        for idx_input, element in enumerate(input_elements):
            value = _resolve_value_for_index(idx_input)
            if not value:
                value = DEFAULT_FILL_TEXT
            try:
                tag_name = (element.tag_name or "").lower()
            except Exception:
                tag_name = ""
            if tag_name in {"span", "div"}:
                try:
                    _smooth_scroll_to_element(driver, element, 'center')
                except Exception:
                    pass
                try:
                    element.click()
                except Exception:
                    pass
                _fill_contenteditable_element(driver, element, value)
            else:
                _fill_text_question_input(driver, element, value)

        # 再兜底：直接按顺序写入隐藏输入框 q{current}_n，避免验证遗漏
        try:
            sync_values = fill_values if fill_values else [DEFAULT_FILL_TEXT]
            sync_count = max(len(sync_values), len(input_elements), visible_count)
            for idx_value in range(sync_count):
                val = sync_values[idx_value] if idx_value < len(sync_values) else (sync_values[-1] if sync_values else DEFAULT_FILL_TEXT)
                driver.execute_script(
                    """
                    const id = arguments[0];
                    const value = arguments[1];
                    const el = document.getElementById(id);
                    if (!el) return;
                    try { el.value = value; } catch (e) {}
                    try { el.setAttribute('value', value); } catch (e) {}
                    ['input','change','blur','keyup','keydown','keypress'].forEach(name => {
                        try { el.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
                    });
                    """,
                    f"q{current}_{idx_value + 1}",
                    val or DEFAULT_FILL_TEXT,
                )
        except Exception:
            pass

        # 触发题目容器上的输入相关事件，避免多项填空未触发脚本校验
        try:
            driver.execute_script(
                """
                return (function() {
                    const qid = arguments[0];
                    const container = document.getElementById(qid);
                    if (!container) return false;
                    const inputs = container.querySelectorAll('input, textarea, [contenteditable=\"true\"], .textCont, .textcont');
                    const events = ['input','change','blur','keyup','keydown'];
                    inputs.forEach(el => {
                        events.forEach(name => {
                            try { el.dispatchEvent(new Event(name, { bubbles: true })); } catch (_) {}
                        });
                    });
                    return true;
                })();
                """,
                f"div{current}"
                )
        except Exception:
            pass
        return

    filled = False
    question_div = None
    try:
        input_element = driver.find_element(By.CSS_SELECTOR, f"#q{current}")
        _fill_text_question_input(driver, input_element, selected_answer)
        filled = True
    except Exception:
        try:
            question_div = driver.find_element(By.CSS_SELECTOR, f"#div{current}")
            candidates = question_div.find_elements(By.CSS_SELECTOR, "input, textarea")
        except Exception:
            candidates = []
        for candidate in candidates:
            try:
                tag_name = (candidate.tag_name or "").lower()
            except Exception:
                tag_name = ""
            input_type = ""
            try:
                input_type = (candidate.get_attribute("type") or "").lower()
            except Exception:
                input_type = ""
            try:
                style_attr = (candidate.get_attribute("style") or "").lower()
            except Exception:
                style_attr = ""
            try:
                displayed = candidate.is_displayed()
            except Exception:
                displayed = True
            if (
                input_type == "hidden"
                or "display:none" in style_attr
                or "visibility:hidden" in style_attr
                or not displayed
            ):
                continue
            if tag_name == "textarea" or (tag_name == "input" and input_type in ("", "text", "search", "tel", "number")):
                _fill_text_question_input(driver, candidate, selected_answer)
                filled = True
                break

    if not filled and question_div is None:
        try:
            question_div = driver.find_element(By.CSS_SELECTOR, f"#div{current}")
        except Exception:
            question_div = None

    if not filled and question_div is not None:
        try:
            editable_nodes = question_div.find_elements(
                By.CSS_SELECTOR,
                "span[contenteditable='true'], div[contenteditable='true'], .textCont, .textcont"
            )
        except Exception:
            editable_nodes = []
        for editable in editable_nodes:
            try:
                if not editable.is_displayed():
                    continue
            except Exception:
                pass
            try:
                _smooth_scroll_to_element(driver, editable, 'center')
            except Exception:
                pass
            try:
                editable.click()
            except Exception:
                pass
            try:
                fill_value = DEFAULT_FILL_TEXT if selected_answer is None else str(selected_answer)
                _fill_contenteditable_element(driver, editable, fill_value)
                filled = True
                break
            except Exception:
                continue


def single(driver: BrowserDriver, current, index):
    # 兼容不同模板下的单选题 DOM 结构，按优先级收集可点击的选项节点
    option_elements: List[Any] = []
    probe_xpaths = [
        f'//*[@id="div{current}"]/div[2]/div',
        f'//*[@id="div{current}"]//div[contains(@class,"ui-radio")]',
        f'//*[@id="div{current}"]//div[contains(@class,"jqradio")]',
        f'//*[@id="div{current}"]//li[contains(@class,"option") or contains(@class,"radio")]/label',
        f'//*[@id="div{current}"]//label[contains(@class,"radio") or contains(@class,"option")]',
    ]
    seen: Set[Any] = set()
    for xpath in probe_xpaths:
        try:
            found = driver.find_elements(By.XPATH, xpath)
        except Exception:
            found = []
        for elem in found:
            try:
                if not elem.is_displayed():
                    continue
            except Exception:
                pass
            if elem not in seen:
                seen.add(elem)
                option_elements.append(elem)
    if not option_elements:
        try:
            radios = driver.find_elements(By.XPATH, f'//*[@id="div{current}"]//input[@type="radio"]')
        except Exception:
            radios = []
        for radio in radios:
            try:
                if not radio.is_displayed():
                    continue
            except Exception:
                pass
            if radio not in seen:
                seen.add(radio)
                option_elements.append(radio)
    if not option_elements:
        logging.warning(f"第{current}题未找到任何单选选项，已跳过该题。")
        return
    prob_config = single_prob[index] if index < len(single_prob) else -1
    config_len = None
    try:
        if hasattr(prob_config, "__len__") and not isinstance(prob_config, (int, float)):
            config_len = len(prob_config)
    except Exception:
        config_len = None
    probabilities = _normalize_droplist_probs(prob_config, len(option_elements))
    if config_len is not None and config_len != len(option_elements):
        logging.debug(
            "单选题概率配置与选项数不一致（题号%s，概率数%s，选项数%s），已按设定权重自动扩展/截断并重新归一化。",
            current,
            config_len,
            len(option_elements),
        )
    target_index = _weighted_index(probabilities)
    selected_option = target_index + 1
    target_elem = option_elements[target_index] if target_index < len(option_elements) else None
    clicked = False
    if target_elem:
        try:
            target_elem.click()
            clicked = True
        except Exception as exc:
            logging.debug("单选题直接点击失败（题号%s，索引%s）：%s", current, selected_option, exc)
            try:
                inner_radio = target_elem.find_element(By.XPATH, ".//input[@type='radio']")
                inner_radio.click()
                clicked = True
            except Exception:
                pass
    if not clicked:
        try:
            driver.find_element(
                By.CSS_SELECTOR, f"#div{current} > div.ui-controlgroup > div:nth-child({selected_option})"
            ).click()
            clicked = True
        except Exception as exc:
            logging.warning("单选题默认选择器点击失败（题号%s，索引%s）：%s", current, selected_option, exc)
            return
    fill_entries = single_option_fill_texts[index] if index < len(single_option_fill_texts) else None
    fill_value = _get_fill_text_from_config(fill_entries, selected_option - 1)
    _fill_option_additional_text(driver, current, selected_option - 1, fill_value)


def _normalize_droplist_probs(prob_config: Union[List[float], int, float, None], option_count: int) -> List[float]:
    if option_count <= 0:
        return []
    if prob_config == -1 or prob_config is None:
        try:
            return normalize_probabilities([1.0] * option_count)
        except Exception:
            return [1.0 / option_count] * option_count
    try:
        # 尽量保留用户配置的配比，即便选项数量有变化也不直接退回平均分配
        if isinstance(prob_config, (list, tuple)):
            base = list(prob_config)
        else:
            try:
                base = list(prob_config)  # type: ignore
            except Exception:
                base = []
        sanitized = [max(0.0, float(v)) if v is not None else 0.0 for v in base]
        if len(sanitized) < option_count:
            sanitized.extend([0.0] * (option_count - len(sanitized)))
        elif len(sanitized) > option_count:
            sanitized = sanitized[:option_count]
        total = sum(sanitized)
        if total > 0:
            return [value / total for value in sanitized]
        return [1.0 / option_count] * option_count
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
    selected_idx = _weighted_index(probabilities)
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
        selected_idx = _weighted_index(probabilities)
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
    min_select_limit, max_select_limit = detect_multiple_choice_limit_range(driver, current)
    max_allowed = max_select_limit if max_select_limit is not None else len(option_elements)
    max_allowed = max(1, min(max_allowed, len(option_elements)))
    min_required = min_select_limit if min_select_limit is not None else 1
    min_required = max(1, min(min_required, len(option_elements)))
    if min_required > max_allowed:
        min_required = max_allowed
    _log_multi_limit_once(driver, current, min_select_limit, max_select_limit)
    selection_probabilities = multiple_prob[index] if index < len(multiple_prob) else [50.0] * len(option_elements)
    fill_entries = multiple_option_fill_texts[index] if index < len(multiple_option_fill_texts) else None

    if selection_probabilities == -1 or (isinstance(selection_probabilities, list) and len(selection_probabilities) == 1 and selection_probabilities[0] == -1):
        num_to_select = random.randint(min_required, max_allowed)
        selected_indices = random.sample(range(len(option_elements)), num_to_select)
        for option_idx in selected_indices:
            selector = f"#div{current} > div.ui-controlgroup > div:nth-child({option_idx + 1})"
            driver.find_element(By.CSS_SELECTOR, selector).click()
            fill_value = _get_fill_text_from_config(fill_entries, option_idx)
            _fill_option_additional_text(driver, current, option_idx, fill_value)
        return

    if len(option_elements) != len(selection_probabilities):
        logging.warning("第%d题多选概率数量(%d)与选项数量(%d)不一致，自动矫正", current, len(selection_probabilities), len(option_elements))
        if len(selection_probabilities) > len(option_elements):
            selection_probabilities = selection_probabilities[: len(option_elements)]
        else:
            try:
                base_prob = max(1.0, max(float(p) for p in selection_probabilities if p is not None))
            except Exception:
                base_prob = 100.0
            padding = [base_prob] * (len(option_elements) - len(selection_probabilities))
            selection_probabilities = list(selection_probabilities) + padding
    sanitized_probabilities: List[float] = []
    for raw_prob in selection_probabilities:
        try:
            prob_value = float(raw_prob)
        except Exception:
            prob_value = 0.0
        if math.isnan(prob_value) or math.isinf(prob_value):
            prob_value = 0.0
        prob_value = max(0.0, min(100.0, prob_value))
        sanitized_probabilities.append(prob_value)
    if not any(value > 0 for value in sanitized_probabilities):
        sanitized_probabilities = [100.0] * len(option_elements)
    selection_probabilities = sanitized_probabilities

    selection_mask: List[int] = []
    attempts = 0
    max_attempts = 32
    while sum(selection_mask) == 0 and attempts < max_attempts:
        selection_mask = [1 if random.random() < (prob / 100.0) else 0 for prob in selection_probabilities]
        attempts += 1
    if sum(selection_mask) == 0:
        selection_mask = [0] * len(option_elements)
        selection_mask[random.randrange(len(option_elements))] = 1
    selected_indices = [idx for idx, selected in enumerate(selection_mask) if selected == 1]
    if max_select_limit is not None and len(selected_indices) > max_allowed:
        random.shuffle(selected_indices)
        selected_indices = selected_indices[:max_allowed]
    if len(selected_indices) < min_required:
        remaining = [i for i in range(len(option_elements)) if i not in selected_indices]
        random.shuffle(remaining)
        needed = min_required - len(selected_indices)
        selected_indices.extend(remaining[:needed])
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
    candidate_columns = list(range(2, len(column_elements) + 1))
    
    for row_index in range(1, matrix_row_count + 1):
        raw_probabilities = matrix_prob[index] if index < len(matrix_prob) else -1
        index += 1
        probabilities = raw_probabilities

        if isinstance(probabilities, list):
            try:
                probs = [float(value) for value in probabilities]
            except Exception:
                probs = []
            if len(probs) != len(candidate_columns):
                logging.warning(
                    "矩阵题第%d行的概率数量(%d)与列数(%d)不符，已自动调整为平均分布",
                    row_index,
                    len(probs),
                    len(candidate_columns),
                )
                probs = [1.0] * len(candidate_columns)
            try:
                normalized_probs = normalize_probabilities(probs)
            except Exception:
                normalized_probs = [1.0 / len(candidate_columns)] * len(candidate_columns)
            selected_column = candidate_columns[_weighted_index(normalized_probs)]
        else:
            selected_column = random.choice(candidate_columns)
        driver.find_element(
            By.CSS_SELECTOR, f"#drv{current}_{row_index} > td:nth-child({selected_column})"
        ).click()
    return index


def reorder(driver: BrowserDriver, current):
    try:
        container = driver.find_element(By.CSS_SELECTOR, f"#div{current}")
    except Exception:
        container = None
    # 排序题 DOM 在不同模板下差异较大：ul 可能不是 div 的直接子节点，甚至会使用 ol。
    # 旧逻辑使用 "/ul/li" 会导致找不到选项，从而整题被“跳过”。
    items_xpath_candidates = [
        # 优先：li 内存在 name 以 q{题号} 开头的输入框（隐藏/勾选框等），更不易误匹配题干里的列表
        f"//*[@id='div{current}']//li[.//input[starts-with(@name,'q{current}')]]",
        # 兜底：常见 ul/ol 结构（允许嵌套）
        f"//*[@id='div{current}']//ul/li",
        f"//*[@id='div{current}']//ol/li",
    ]
    items_xpath = items_xpath_candidates[-1]
    order_items: List[Any] = []
    for candidate_xpath in items_xpath_candidates:
        try:
            order_items = driver.find_elements(By.XPATH, candidate_xpath)
        except Exception:
            order_items = []
        if order_items:
            items_xpath = candidate_xpath
            break
    if not order_items:
        return
    if container:
        try:
            _smooth_scroll_to_element(driver, container, block="center")
        except Exception:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", container)
            except Exception:
                pass
    rank_mode = False
    if container:
        try:
            rank_mode = bool(container.find_elements(By.CSS_SELECTOR, ".sortnum, .sortnum-sel"))
        except Exception:
            rank_mode = False
    def _is_item_selected(item) -> bool:
        try:
            inputs = item.find_elements(By.CSS_SELECTOR, "input[type='checkbox'], input[type='radio']")
        except Exception:
            inputs = []
        for ipt in inputs:
            try:
                if ipt.is_selected():
                    return True
            except Exception:
                continue
        try:
            cls = (item.get_attribute("class") or "").lower()
            # 部分排序题点击后会给 li 添加 check 类或数字类名
            if any(token in cls for token in ("selected", "checked", "jqchecked", "active", "on", "check", "cur", "sel")):
                return True
            data_checked = (item.get_attribute("data-checked") or "").lower()
            aria_checked = (item.get_attribute("aria-checked") or "").lower()
            if data_checked in ("true", "checked") or aria_checked == "true":
                return True
        except Exception:
            pass
        try:
            badges = item.find_elements(
                By.CSS_SELECTOR, ".ui-icon-number, .order-number, .order-index, .num, .sortnum, .sortnum-sel"
            )
            for badge in badges:
                try:
                    text = _extract_text_from_element(badge).strip()
                except Exception:
                    text = ""
                if text:
                    return True
        except Exception:
            pass
        return False

    def _count_selected() -> int:
        try:
            if container:
                count = len(
                    container.find_elements(
                        By.CSS_SELECTOR,
                        "input[type='checkbox']:checked, input[type='radio']:checked, li.jqchecked, li.selected, li.on, li.checked, li.check, .option.on, .option.selected",
                    )
                )
                if count > 0:
                    return count
                # 对于排序题，数字标识可能在 span.sortnum 中
                badges = container.find_elements(By.CSS_SELECTOR, ".sortnum, .sortnum-sel")
                badge_count = 0
                for badge in badges:
                    try:
                        text = _extract_text_from_element(badge).strip()
                    except Exception:
                        text = ""
                    if text:
                        badge_count += 1
                if badge_count:
                    return badge_count
            # 一些排序题会把“已选”写入 data-checked 或 aria-checked
            candidates = container.find_elements(By.CSS_SELECTOR, "li[aria-checked='true'], li[data-checked='true']")
            if candidates:
                return len(candidates)
            hidden_inputs = container.find_elements(By.CSS_SELECTOR, "input[type='hidden'][name^='q'][value]")
            forced_inputs = [h for h in hidden_inputs if (h.get_attribute("data-forced") or "") == "1"]
            if forced_inputs:
                return len(forced_inputs)
            selected_hidden = 0
            for hidden in hidden_inputs:
                try:
                    checked_attr = (hidden.get_attribute("checked") or "").lower()
                    data_checked = (hidden.get_attribute("data-checked") or "").lower()
                    aria_checked = (hidden.get_attribute("aria-checked") or "").lower()
                except Exception:
                    checked_attr = data_checked = aria_checked = ""
                if checked_attr in ("true", "checked") or data_checked in ("true", "checked") or aria_checked == "true":
                    selected_hidden += 1
            if selected_hidden:
                return selected_hidden
        except Exception:
            pass
        count = 0
        for item in order_items:
            if _is_item_selected(item):
                count += 1
        return count

    def _click_item(option_idx: int, item) -> bool:
        selector = (
            f"#div{current} ul > li:nth-child({option_idx + 1}), "
            f"#div{current} ol > li:nth-child({option_idx + 1})"
        )

        def _after_rank_click(changed: bool) -> None:
            if changed and rank_mode:
                time.sleep(0.28)

        def _playwright_click_selector(css_selector: str) -> bool:
            page = getattr(driver, "page", None)
            if not page:
                return False
            try:
                page.click(css_selector, timeout=1200)
                return True
            except Exception:
                return False

        def _native_click(target) -> None:
            # Playwright 的 element.click() 会触发更完整的鼠标事件链；
            # 部分模板（点击顺序排序）不会响应 JS 触发的 el.click()/dispatchEvent。
            try:
                if target is not None and hasattr(target, "click"):
                    target.click()
            except Exception:
                pass

        def _safe_dom_click(target) -> None:
            driver.execute_script(
                r"""
                const el = arguments[0];
                if (!el) return;
                const rect = el.getBoundingClientRect ? el.getBoundingClientRect() : null;
                const vh = window.innerHeight || document.documentElement.clientHeight || 0;
                const inView = !!(rect && rect.width > 0 && rect.height > 0 && rect.top >= 0 && rect.bottom <= vh);
                const y = window.scrollY || document.documentElement.scrollTop || 0;
                try { if (!inView) el.scrollIntoView({block:'nearest', inline:'nearest'}); } catch(e) {}
                try { el.focus({preventScroll:true}); } catch(e) {}
                try { el.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true, composed:true})); } catch(e) {}
                try { el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, cancelable:true, composed:true})); } catch(e) {}
                try { el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, cancelable:true, composed:true})); } catch(e) {}
                try { el.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, composed:true})); } catch(e) {}
                try { el.click(); } catch(e) {}
                try { if (inView) window.scrollTo(0, y); } catch(e) {}
                """,
                target,
            )

        def _mouse_click_center(target) -> bool:
            page = getattr(driver, "page", None)
            if not page:
                return False
            try:
                payload = driver.execute_script(
                    r"""
                    const el = arguments[0];
                    if (!el || !el.getBoundingClientRect) return null;
                    const rect = el.getBoundingClientRect();
                    if (!rect || rect.width <= 0 || rect.height <= 0) return null;
                    const vh = window.innerHeight || document.documentElement.clientHeight || 0;
                    if (rect.bottom < 0 || rect.top > vh) {
                        try { el.scrollIntoView({block:'nearest', inline:'nearest'}); } catch(e) {}
                    }
                    const r2 = el.getBoundingClientRect();
                    return {x: r2.left + r2.width / 2, y: r2.top + r2.height / 2, w: r2.width, h: r2.height};
                    """,
                    target,
                )
            except Exception:
                payload = None
            if not isinstance(payload, dict):
                return False
            try:
                x = float(payload.get("x", 0))
                y = float(payload.get("y", 0))
            except Exception:
                return False
            if x <= 0 or y <= 0:
                return False
            try:
                page.mouse.click(x, y)
                return True
            except Exception:
                return False

        def _click_targets(base_item) -> List[Any]:
            targets: List[Any] = []
            if base_item:
                targets.append(base_item)
                for css in (
                    "input[type='checkbox']",
                    "input[type='radio']",
                    "input[type='hidden']",
                    "label",
                    "a",
                    ".option",
                    ".item",
                    ".ui-state-default",
                    ".ui-sortable-handle",
                    "span",
                    "div",
                ):
                    try:
                        found = base_item.find_elements(By.CSS_SELECTOR, css)
                    except Exception:
                        found = []
                    for el in found[:3]:
                        targets.append(el)
            return targets

        def _get_item_fresh() -> Any:
            try:
                items_now = driver.find_elements(By.XPATH, items_xpath)
            except Exception:
                items_now = []
            if 0 <= option_idx < len(items_now):
                return items_now[option_idx]
            try:
                return driver.find_element(By.CSS_SELECTOR, selector)
            except Exception:
                return item

        if _is_item_selected(item):
            return True

        count_before = _count_selected()
        # 点击顺序排序题：优先使用 Playwright 原生 click，确保触发 jQuery Mobile 的 vclick/tap 绑定
        if rank_mode:
            clicked = False
            for css in (
                f"#div{current} ul > li:nth-child({option_idx + 1})",
                f"#div{current} ol > li:nth-child({option_idx + 1})",
            ):
                if _playwright_click_selector(css):
                    clicked = True
                    break
            if clicked:
                deadline = time.time() + 0.55
                while time.time() < deadline:
                    try:
                        if _count_selected() > count_before:
                            _after_rank_click(True)
                            return True
                    except Exception:
                        pass
                    try:
                        fresh_check = _get_item_fresh()
                        if fresh_check and _is_item_selected(fresh_check):
                            _after_rank_click(True)
                            return True
                    except Exception:
                        pass
                    time.sleep(0.05)
        for _ in range(6):
            base_item = _get_item_fresh()
            if base_item and _is_item_selected(base_item):
                return True

            for target in _click_targets(base_item):
                try:
                    _native_click(target)
                except Exception:
                    pass

                # 选择状态有时会延迟更新，轮询一小段时间比“狂点”更稳定
                deadline = time.time() + 0.45
                while time.time() < deadline:
                    try:
                        if _count_selected() > count_before:
                            _after_rank_click(True)
                            return True
                    except Exception:
                        pass
                    try:
                        fresh_check = _get_item_fresh()
                        if fresh_check and _is_item_selected(fresh_check):
                            _after_rank_click(True)
                            return True
                    except Exception:
                        pass
                    time.sleep(0.05)

                # 未生效时再用 JS 事件触发一次（对少数覆盖层/事件绑定更友好）
                try:
                    _safe_dom_click(target)
                except Exception:
                    pass
                deadline = time.time() + 0.45
                while time.time() < deadline:
                    try:
                        if _count_selected() > count_before:
                            _after_rank_click(True)
                            return True
                    except Exception:
                        pass
                    try:
                        fresh_check = _get_item_fresh()
                        if fresh_check and _is_item_selected(fresh_check):
                            _after_rank_click(True)
                            return True
                    except Exception:
                        pass
                    time.sleep(0.05)

                # 最后再尝试一次鼠标坐标点击（对某些覆盖层/事件绑定更友好）
                try:
                    if _mouse_click_center(target):
                        deadline = time.time() + 0.45
                        while time.time() < deadline:
                            try:
                                if _count_selected() > count_before:
                                    _after_rank_click(True)
                                    return True
                            except Exception:
                                pass
                            time.sleep(0.05)
                except Exception:
                    pass

            time.sleep(0.06)

        try:
            return _is_item_selected(_get_item_fresh())
        except Exception:
            return False

    def _ensure_reorder_complete(target_count: int) -> None:
        target_count = max(1, min(target_count, total_options))
        for _ in range(3):
            current_count = _count_selected()
            if current_count >= target_count:
                return
            missing_indices = [i for i, it in enumerate(order_items) if not _is_item_selected(it)]
            if not missing_indices:
                break
            random.shuffle(missing_indices)
            for option_idx in missing_indices:
                item = order_items[option_idx]
                if _click_item(option_idx, item):
                    current_count += 1
                    if current_count >= target_count:
                        return
            time.sleep(0.12)

    def _wait_until_reorder_done(target_count: int, max_wait: Optional[float] = None) -> None:
        target_count = max(1, min(target_count, total_options))
        wait_window = max_wait
        if wait_window is None:
            wait_window = 2.8 if rank_mode else 1.5
        deadline = time.time() + wait_window
        while time.time() < deadline:
            current_count = _count_selected()
            if current_count >= target_count:
                return
            _ensure_reorder_complete(target_count)
            time.sleep(0.08)

    total_options = len(order_items)
    required_count = detect_reorder_required_count(driver, current, total_options)
    min_select_limit, max_select_limit = detect_multiple_choice_limit_range(driver, current)
    # 排序题 DOM 中常包含大量数字（例如 hidden input 的 value/serial），会干扰通用“至多/至少”解析；
    # 若题干未出现“至少/最多/选择”等关键词，则默认视为无限制，按“填满”处理。
    if rank_mode and container:
        fragments: List[str] = []
        for selector in (".qtypetip", ".topichtml", ".field-label"):
            try:
                fragments.append(container.find_element(By.CSS_SELECTOR, selector).text)
            except Exception:
                continue
        cand_min, cand_max = _extract_multi_limit_range_from_text("\n".join(fragments))
        if cand_min is None and cand_max is None:
            min_select_limit = None
            max_select_limit = None
        else:
            min_select_limit = cand_min
            max_select_limit = cand_max
    force_select_all = required_count is not None and required_count == total_options
    if force_select_all and max_select_limit is not None and required_count is not None and max_select_limit < required_count:
        max_select_limit = required_count
    if min_select_limit is not None or max_select_limit is not None:
        _log_multi_limit_once(driver, current, min_select_limit, max_select_limit)
    if force_select_all:
        candidate_indices = list(range(len(order_items)))
        random.shuffle(candidate_indices)
        for option_idx in candidate_indices:
            item = order_items[option_idx]
            if _is_item_selected(item):
                continue
            _click_item(option_idx, item)
        # 如果仍有未选中的项，补点两轮，确保随机但全选
        for _ in range(2):
            selected_now = _count_selected()
            if selected_now >= total_options:
                break
            missing_indices = [i for i, it in enumerate(order_items) if not _is_item_selected(it)]
            random.shuffle(missing_indices)
            for option_idx in missing_indices:
                item = order_items[option_idx]
                _click_item(option_idx, item)
        _wait_until_reorder_done(total_options)
        return
    # 优先使用题目要求数量，其次用最大限制，最后兜底为全部选项
    if required_count is None:
        effective_limit = max_select_limit if max_select_limit is not None else len(order_items)
    else:
        effective_limit = required_count
        if max_select_limit is not None:
            effective_limit = min(effective_limit, max_select_limit)
    if min_select_limit is not None:
        effective_limit = max(effective_limit, min_select_limit)
    effective_limit = max(1, min(effective_limit, len(order_items)))

    candidate_indices = list(range(len(order_items)))
    random.shuffle(candidate_indices)
    selected_indices = candidate_indices[:effective_limit]

    for option_idx in selected_indices:
        item = order_items[option_idx]
        if _is_item_selected(item):
            continue
        _click_item(option_idx, item)

    selected_count = _count_selected()
    if selected_count < effective_limit:
        for option_idx, item in enumerate(order_items):
            if selected_count >= effective_limit:
                break
            if _is_item_selected(item):
                continue
            if _click_item(option_idx, item):
                selected_count += 1
    selected_count = _count_selected()
    if selected_count < effective_limit and container:
        try:
            # 兜底：直接写入排序序号并标记为已选（仅最后兜底，优先依赖真实点击）
            order = list(range(len(order_items)))
            random.shuffle(order)
            driver.execute_script(
                r"""
                const container = arguments[0];
                const order = arguments[1];
                const limit = arguments[2];
                if (!container || !Array.isArray(order)) return;
                const items = Array.from(container.querySelectorAll('ul > li, ol > li'));
                const maxCount = Math.max(1, Math.min(Number(limit || items.length) || items.length, items.length));
                const chosen = order.slice(0, maxCount);
                const chosenSet = new Set(chosen);

                chosen.forEach((idx, pos) => {
                    const li = items[idx];
                    if (!li) return;
                    const rank = pos + 1;
                    li.classList.add('selected', 'jqchecked', 'on', 'check');
                    li.setAttribute('aria-checked', 'true');
                    li.setAttribute('data-checked', 'true');
                    const badge = li.querySelector('.sortnum, .sortnum-sel, .order-number, .order-index');
                    if (badge) {
                        badge.textContent = String(rank);
                        badge.style.display = '';
                    }
                    const hidden = li.querySelector("input.custom[type='hidden'][name^='q'], input[type='hidden'][name^='q']");
                    if (hidden) {
                        hidden.value = String(rank);
                        hidden.setAttribute('data-forced', '1');
                        hidden.setAttribute('data-checked', 'true');
                        hidden.setAttribute('aria-checked', 'true');
                    }
                    const box = li.querySelector("input[type='checkbox'], input[type='radio']");
                    if (box) {
                        box.checked = true;
                        box.value = String(rank);
                        box.setAttribute('checked', 'checked');
                        box.setAttribute('data-checked', 'true');
                        box.setAttribute('aria-checked', 'true');
                        try { box.dispatchEvent(new Event('change', {bubbles:true})); } catch (err) {}
                    }
                });

                items.forEach((li, idx) => {
                    if (chosenSet.has(idx)) return;
                    li.classList.remove('selected', 'jqchecked', 'on', 'check');
                    li.removeAttribute('aria-checked');
                    li.removeAttribute('data-checked');
                    const badge = li.querySelector('.sortnum, .sortnum-sel, .order-number, .order-index');
                    if (badge) badge.textContent = '';
                    const hidden = li.querySelector("input.custom[type='hidden'][name^='q'], input[type='hidden'][name^='q']");
                    if (hidden) {
                        hidden.value = '';
                        hidden.removeAttribute('data-forced');
                        hidden.removeAttribute('data-checked');
                        hidden.removeAttribute('aria-checked');
                    }
                    const box = li.querySelector("input[type='checkbox'], input[type='radio']");
                    if (box) {
                        box.checked = false;
                        box.removeAttribute('checked');
                        box.removeAttribute('data-checked');
                        box.removeAttribute('aria-checked');
                    }
                });
                """,
                container,
                order,
                effective_limit,
            )
        except Exception:
            pass
    _wait_until_reorder_done(effective_limit)


def scale(driver: BrowserDriver, current, index):
    scale_items_xpath = f'//*[@id="div{current}"]/div[2]/div/ul/li'
    scale_options = driver.find_elements(By.XPATH, scale_items_xpath)
    probabilities = scale_prob[index] if index < len(scale_prob) else -1
    if not scale_options:
        return
    if probabilities == -1:
        selected_index = random.randrange(len(scale_options))
    else:
        selected_index = _weighted_index(probabilities)
    scale_options[selected_index].click()


def _set_slider_input_value(driver: BrowserDriver, current: int, value: Union[int, float]):
    try:
        slider_input = driver.find_element(By.CSS_SELECTOR, f"#q{current}")
    except NoSuchElementException:
        return
    script = (
        "const input = arguments[0];"
        "const target = String(arguments[1]);"
        "input.value = target;"
        "try { input.setAttribute('value', target); } catch (err) {}"
        "['input','change'].forEach(evt => input.dispatchEvent(new Event(evt, { bubbles: true })));"
    )
    try:
        driver.execute_script(script, slider_input, value)
    except Exception:
        pass


def _click_slider_track(driver: BrowserDriver, container, ratio: float) -> bool:
    xpath_candidates = [
        ".//div[contains(@class,'wjx-slider') or contains(@class,'slider-track') or contains(@class,'range-slider') or contains(@class,'rangeslider') or contains(@class,'ui-slider') or contains(@class,'scale-slider') or contains(@class,'slider-container')]",
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


def slider_question(driver: BrowserDriver, current: int, score: Optional[float] = None):
    try:
        question_div = driver.find_element(By.CSS_SELECTOR, f"#div{current}")
    except NoSuchElementException:
        question_div = None
    if question_div:
        try:
            _smooth_scroll_to_element(driver, question_div, block="center")
        except Exception:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", question_div)
            except Exception:
                pass

    slider_input = None
    min_value = 0.0
    max_value = 100.0
    step_value = 1.0

    def _parse_number(raw, default):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    try:
        slider_input = driver.find_element(By.CSS_SELECTOR, f"#q{current}")
    except NoSuchElementException:
        slider_input = None

    if slider_input:
        min_value = _parse_number(slider_input.get_attribute("min"), min_value)
        max_value = _parse_number(slider_input.get_attribute("max"), max_value)
        step_value = abs(_parse_number(slider_input.get_attribute("step"), step_value))
        if step_value == 0:
            step_value = 1.0
        if max_value <= min_value:
            max_value = min_value + 100.0

    target_value = _parse_number(score, None)
    if target_value is None:
        target_value = random.uniform(min_value, max_value)
    if target_value < min_value or target_value > max_value:
        if max_value > min_value:
            target_value = random.uniform(min_value, max_value)
        else:
            target_value = min_value
    if step_value > 0 and max_value > min_value:
        step_count = round((target_value - min_value) / step_value)
        target_value = min_value + step_count * step_value
        target_value = max(min_value, min(target_value, max_value))
    if abs(target_value - round(target_value)) < 1e-6:
        target_value = int(round(target_value))

    ratio = 0.0 if max_value == min_value else (target_value - min_value) / (max_value - min_value)
    ratio = max(0.0, min(ratio, 1.0))
    container = question_div
    if container:
        try:
            _click_slider_track(driver, container, ratio)
        except Exception:
            pass
        try:
            driver.execute_script(
                r"""
                const container = arguments[0];
                const ratio = arguments[1];
                if (!container) return;
                const track = container.querySelector(
                    '.rangeslider, .range-slider, .slider-track, .wjx-slider, .ui-slider, .scale-slider, .slider-container'
                );
                if (!track) return;
                const width = track.clientWidth || track.offsetWidth || 0;
                if (!width) return;
                const pos = Math.max(0, Math.min(width, ratio * width));
                const handle = track.querySelector('.rangeslider__handle, .slider-handle, .ui-slider-handle, .handle');
                const fill = track.querySelector('.rangeslider__fill, .slider-selection, .ui-slider-range, .fill');
                if (fill) {
                    fill.style.width = pos + 'px';
                    if (!fill.style.left) { fill.style.left = '0px'; }
                }
                if (handle) {
                    handle.style.left = pos + 'px';
                }
                try { track.setAttribute('data-answered', '1'); } catch (err) {}
                """,
                container,
                ratio,
            )
        except Exception:
            pass
    _set_slider_input_value(driver, current, target_value)


def _full_simulation_active() -> bool:
    _sync_full_sim_state_from_globals()
    return bool(_FULL_SIM_STATE.active())


def _reset_full_simulation_runtime_state() -> None:
    _FULL_SIM_STATE.reset_runtime()


def _prepare_full_simulation_schedule(run_count: int, total_duration_seconds: int) -> Deque[float]:
    schedule = _FULL_SIM_STATE.prepare_schedule(run_count, total_duration_seconds)
    return schedule


def _wait_for_next_full_simulation_slot(stop_signal: threading.Event) -> bool:
    return _FULL_SIM_STATE.wait_for_next_slot(stop_signal)


def _calculate_full_simulation_run_target(question_count: int) -> float:
    return _FULL_SIM_STATE.calculate_run_target(question_count)


def _build_per_question_delay_plan(question_count: int, target_seconds: float) -> List[float]:
    return _FULL_SIM_STATE.build_per_question_delay_plan(question_count, target_seconds)


def _simulate_answer_duration_delay(stop_signal: Optional[threading.Event] = None) -> bool:
    # 委托到模块实现，传入当前配置范围以避免模块依赖全局变量
    return full_simulation_mode.simulate_answer_duration_delay(stop_signal, answer_duration_range_seconds)


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


def _click_submit_button(driver: BrowserDriver, max_wait: float = 10.0) -> bool:
    """点击“提交”按钮（简单版）。

    设计目标：只做“找按钮 -> click”这一件事，不做 JS 强行触发/移除遮罩/调用全局函数等兜底。

    Args:
        driver: 浏览器驱动
        max_wait: 最大等待时间（秒），用于轮询等待按钮出现
    """

    submit_keywords = ("提交", "完成", "交卷", "确认提交", "确认")

    locator_candidates = [
        (By.CSS_SELECTOR, "#submit_button"),
        (By.CSS_SELECTOR, "#divSubmit"),
        (By.CSS_SELECTOR, "#ctlNext"),
        (By.CSS_SELECTOR, "#SM_BTN_1"),
        (By.CSS_SELECTOR, "#SubmitBtnGroup .submitbtn"),
        (By.CSS_SELECTOR, "button[type='submit']"),
        (By.XPATH, "//a[normalize-space(.)='提交' or normalize-space(.)='完成' or normalize-space(.)='交卷' or normalize-space(.)='确认提交' or normalize-space(.)='确认']"),
        (By.XPATH, "//button[normalize-space(.)='提交' or normalize-space(.)='完成' or normalize-space(.)='交卷' or normalize-space(.)='确认提交' or normalize-space(.)='确认']"),
    ]

    def _text_looks_like_submit(element) -> bool:
        text = (_extract_text_from_element(element) or "").strip()
        if not text:
            text = (element.get_attribute("value") or "").strip()
        if not text:
            return False
        return any(k in text for k in submit_keywords)

    deadline = time.time() + max(0.0, float(max_wait or 0.0))
    while True:
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

                if by == By.CSS_SELECTOR and value in ("button[type='submit']",):
                    if not _text_looks_like_submit(element):
                        continue

                try:
                    element.click()
                    logging.debug("成功点击提交按钮：%s=%s", by, value)
                    return True
                except Exception:
                    continue

        if time.time() >= deadline:
            break
        time.sleep(0.2)

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
            question_selector = f"#div{current_question_number}"
            try:
                question_div = driver.find_element(By.CSS_SELECTOR, question_selector)
            except Exception:
                question_div = None
            if question_div is None:
                continue
            question_visible = False
            for attempt in range(5):
                try:
                    if question_div.is_displayed():
                        question_visible = True
                        break
                except Exception:
                    break
                if attempt < 4:
                    time.sleep(0.1)
            if not question_visible:
                logging.debug("跳过第%d题（未显示）", current_question_number)
                continue
            question_type = question_div.get_attribute("type")
            is_reorder_question = (question_type == "11") or _driver_question_looks_like_reorder(question_div)

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
            elif is_reorder_question:
                reorder(driver, current_question_number)
            else:
                # 兜底：尝试把未知类型当成填空题/多项填空题处理，避免直接跳过
                handled = False
                if question_div is not None:
                    checkbox_count, radio_count = _count_choice_inputs_driver(question_div)
                    if checkbox_count or radio_count:
                        if checkbox_count >= radio_count:
                            multiple(driver, current_question_number, multiple_question_index)
                            multiple_question_index += 1
                        else:
                            single(driver, current_question_number, single_question_index)
                            single_question_index += 1
                        handled = True

                if not handled:
                    option_count = 0
                    if question_div is not None:
                        try:
                            option_elements = question_div.find_elements(By.CSS_SELECTOR, ".ui-controlgroup > div")
                            option_count = len(option_elements)
                        except Exception:
                            option_count = 0
                    text_input_count = _count_visible_text_inputs_driver(question_div) if question_div is not None else 0
                    is_location_question = _driver_question_is_location(question_div) if question_div is not None else False
                    is_multi_text_question = _should_mark_as_multi_text(
                        question_type, option_count, text_input_count, is_location_question
                    )
                    is_text_like_question = _should_treat_question_as_text_like(
                        question_type, option_count, text_input_count
                    )

                    if is_text_like_question:
                        vacant(driver, current_question_number, vacant_question_index)
                        vacant_question_index += 1
                        print(
                            f"第{current_question_number}题识别为"
                            f"{'多项填空' if is_multi_text_question else '填空'}，已按填空题处理"
                        )
                    else:
                        print(f"第{current_question_number}题为不支持类型(type={question_type})")
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
            # 最后一页直接跳出循环，由后续的 submit() 处理提交
            break
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
    """点击提交按钮并结束。

    仅保留最基础的行为：可选等待 -> 点击提交 -> 可选稳定等待。
    不再做弹窗确认/验证码检测/JS 强行触发等兜底逻辑。
    """
    fast_mode = _is_fast_mode()
    settle_delay = 0 if fast_mode else SUBMIT_CLICK_SETTLE_DELAY
    pre_submit_delay = 0 if fast_mode else SUBMIT_INITIAL_DELAY

    global last_submit_had_captcha
    last_submit_had_captcha = False

    if pre_submit_delay > 0 and _sleep_with_stop(stop_signal, pre_submit_delay):
        return
    if stop_signal and stop_signal.is_set():
        return

    clicked = _click_submit_button(driver, max_wait=10.0)
    if not clicked:
        raise NoSuchElementException("Submit button not found")

    if settle_delay > 0:
        time.sleep(settle_delay)

    # 有些模板点击“提交”后会弹出确认层，需要再点一次“确定/确认提交”
    try:
        confirm_candidates = [
            (By.XPATH, '//*[@id="layui-layer1"]/div[3]/a'),
            (By.CSS_SELECTOR, "#layui-layer1 .layui-layer-btn a"),
            (By.CSS_SELECTOR, ".layui-layer .layui-layer-btn a.layui-layer-btn0"),
        ]
        for by, value in confirm_candidates:
            try:
                el = driver.find_element(by, value)
            except Exception:
                el = None
            if not el:
                continue
            try:
                if not el.is_displayed():
                    continue
            except Exception:
                continue
            try:
                el.click()
                if settle_delay > 0:
                    time.sleep(settle_delay)
                break
            except Exception:
                continue
    except Exception:
        pass


def _normalize_url_for_compare(value: str) -> str:
    """用于比较的 URL 归一化：去掉 fragment，去掉首尾空白。"""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except Exception:
        return text
    try:
        if parsed.fragment:
            parsed = parsed._replace(fragment="")
        return parsed.geturl()
    except Exception:
        return text


def _is_wjx_domain(url_value: str) -> bool:
    try:
        parsed = urlparse(str(url_value))
    except Exception:
        return False
    host = (parsed.netloc or "").split(":", 1)[0].lower()
    return bool(host == "wjx.cn" or host.endswith(".wjx.cn"))


def _looks_like_wjx_survey_url(url_value: str) -> bool:
    """粗略判断是否像问卷星问卷链接（用于“提交后分流到下一问卷”的识别）。"""
    if not url_value:
        return False
    text = str(url_value).strip()
    if not text:
        return False
    if not _is_wjx_domain(text):
        return False
    try:
        parsed = urlparse(text)
    except Exception:
        return False
    path = (parsed.path or "").lower()
    if "complete" in path:
        return False
    if not path.endswith(".aspx"):
        return False
    # 常见路径：/vm/xxxxx.aspx、/jq/xxxxx.aspx、/vj/xxxxx.aspx
    if any(segment in path for segment in ("/vm/", "/jq/", "/vj/")):
        return True
    return True


def _page_looks_like_wjx_questionnaire(driver: BrowserDriver) -> bool:
    """用 DOM 特征判断当前页是否为可作答的问卷页。"""
    script = r"""
        return (() => {
            const bodyText = (document.body?.innerText || '').replace(/\s+/g, '');
            const completeMarkers = ['答卷已经提交', '感谢您的参与', '感谢参与'];
            if (completeMarkers.some(m => bodyText.includes(m))) return false;

            // 开屏“开始作答”页（还未展示题目）
            if (bodyText.includes('开始作答') || bodyText.includes('开始答题') || bodyText.includes('开始填写')) {
                const startLike = Array.from(document.querySelectorAll('div, a, button, span')).some(el => {
                    const t = (el.innerText || el.textContent || '').replace(/\s+/g, '');
                    return t === '开始作答' || t === '开始答题' || t === '开始填写';
                });
                if (startLike) return true;
            }

            const questionLike = document.querySelector(
                '#div1, #divQuestion, [id^="divquestion"], .div_question, .question, .wjx_question, [topic]'
            );

            const actionLike = document.querySelector(
                '#submit_button, #divSubmit, #ctlNext, #divNext, #btnNext, #next, ' +
                '.next, .next-btn, .next-button, .btn-next, button[type="submit"], a.button.mainBgColor'
            );

            return !!(questionLike && actionLike);
        })();
    """
    try:
        return bool(driver.execute_script(script))
    except Exception:
        return False


def _wait_for_post_submit_outcome(
    driver: BrowserDriver,
    initial_url: str,
    max_wait: float,
    poll_interval: float,
    stop_signal: Optional[threading.Event] = None,
) -> Tuple[Literal["complete", "followup", "unknown"], str]:
    """
    等待提交后的结果：
    - complete：进入完成页
    - followup：按选项分流跳转到下一份问卷
    - unknown：未识别
    """
    deadline = time.time() + max(0.0, float(max_wait or 0.0))
    initial_norm = _normalize_url_for_compare(initial_url)
    while time.time() < deadline:
        if stop_signal and stop_signal.is_set():
            break
        try:
            current_url = driver.current_url
        except Exception:
            current_url = ""
        current_lower = str(current_url).lower()
        if "complete" in current_lower:
            return "complete", str(current_url)
        try:
            if full_simulation_mode.is_survey_completion_page(driver):
                return "complete", str(current_url)
        except Exception:
            pass

        current_norm = _normalize_url_for_compare(str(current_url))
        if current_norm and current_norm != initial_norm:
            if _looks_like_wjx_survey_url(current_norm) and _page_looks_like_wjx_questionnaire(driver):
                return "followup", str(current_url)

        time.sleep(max(0.02, float(poll_interval or 0.1)))

    try:
        final_url = str(driver.current_url)
    except Exception:
        final_url = ""
    return "unknown", final_url


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
    timed_mode_active = _timed_mode_active()
    try:
        timed_refresh_interval = float(timed_mode_refresh_interval or timed_mode.DEFAULT_REFRESH_INTERVAL)
    except Exception:
        timed_refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
    if timed_refresh_interval <= 0:
        timed_refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
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

    def _is_device_quota_limit_page(instance: BrowserDriver) -> bool:
        """
        检测“设备已达到最大填写次数”提示页。
        """
        script = r"""
            return (() => {
                const text = (document.body?.innerText || '').replace(/\s+/g, '');
                if (!text) return false;

                const limitMarkers = [
                    '设备已达到最大填写次数',
                    '已达到最大填写次数',
                    '达到最大填写次数',
                    '填写次数已达上限',
                    '超过最大填写次数',
                ];
                const hasLimit = limitMarkers.some(marker => text.includes(marker));
                if (!hasLimit) return false;

                const hasThanks = text.includes('感谢参与') || text.includes('感谢参与!');
                const hasApology = text.includes('很抱歉') || text.includes('提示');
                if (!(hasThanks || hasApology)) return false;

                const questionLike = document.querySelector(
                    '#divQuestion, [id^="divquestion"], .div_question, .question, .wjx_question, [topic]'
                );
                if (questionLike) return false;

                const startHints = ['开始作答', '开始答题', '开始填写', '继续作答', '继续填写'];
                if (startHints.some(hint => text.includes(hint))) return false;

                const submitSelectors = [
                    '#submit_button',
                    '#divSubmit',
                    '#ctlNext',
                    '#SM_BTN_1',
                    '.submitDiv a',
                    '.btn-submit',
                    'button[type="submit"]',
                    'a.mainBgColor',
                ];
                if (submitSelectors.some(sel => document.querySelector(sel))) return false;

                return true;
            })();
        """
        try:
            return bool(instance.execute_script(script))
        except Exception:
            return False

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
            if not url:
                logging.error("无法启动：问卷链接为空")
                driver_had_error = True
                break
            if timed_mode_active:
                logging.info("[Action Log] 定时模式：开始刷新等待问卷开放")
                ready = timed_mode.wait_until_open(
                    driver,
                    url,
                    stop_signal,
                    refresh_interval=timed_refresh_interval,
                    logger=logging.info,
                )
                if not ready:
                    if not stop_signal.is_set():
                        stop_signal.set()
                    break
            else:
                driver.get(url)
                if stop_signal.is_set():
                    break
            if _is_device_quota_limit_page(driver):
                logging.warning("检测到“设备已达到最大填写次数”提示页，直接放弃当前浏览器实例并标记为成功。")
                with lock:
                    if target_num <= 0 or cur_num < target_num:
                        cur_num += 1
                        logging.info(
                            f"[OK/Quota] 已填写{cur_num}份 - 失败{cur_fail}次 - {time.strftime('%H:%M:%S', time.localtime(time.time()))}"
                        )
                        if random_proxy_ip_enabled:
                            handle_random_ip_submission(gui_instance, stop_signal)
                        if target_num > 0 and cur_num >= target_num:
                            stop_signal.set()
                            _trigger_target_reached_stop(gui_instance, stop_signal)
                    else:
                        stop_signal.set()
                        break
                _dispose_driver()
                continue
            followup_hops = 0
            visited_urls: Set[str] = set()
            try:
                visited_urls.add(_normalize_url_for_compare(driver.current_url))
            except Exception:
                visited_urls.add(_normalize_url_for_compare(url))

            while True:
                initial_url = driver.current_url
                if stop_signal.is_set():
                    break
                finished = brush(driver, stop_signal=stop_signal)
                if stop_signal.is_set() or not finished:
                    break

                need_watch_submit = bool(last_submit_had_captcha)
                max_wait, poll_interval = full_simulation_mode.get_post_submit_wait_params(need_watch_submit, fast_mode)
                outcome, outcome_url = _wait_for_post_submit_outcome(
                    driver,
                    str(initial_url),
                    max_wait=max_wait,
                    poll_interval=poll_interval,
                    stop_signal=stop_signal,
                )

                if outcome == "unknown" and not stop_signal.is_set():
                    extra_wait_seconds = max(1.0, float(POST_SUBMIT_URL_MAX_WAIT or 0.0) * 3.0)
                    extra_poll = max(0.05, float(POST_SUBMIT_URL_POLL_INTERVAL or 0.1))
                    outcome, outcome_url = _wait_for_post_submit_outcome(
                        driver,
                        str(initial_url),
                        max_wait=extra_wait_seconds,
                        poll_interval=extra_poll,
                        stop_signal=stop_signal,
                    )

                if outcome == "unknown" and not stop_signal.is_set():
                    aliyun_detected = False
                    try:
                        aliyun_detected = handle_aliyun_captcha(
                            driver,
                            timeout=3,
                            stop_signal=stop_signal,
                            raise_on_detect=False,
                        )
                    except Exception:
                        aliyun_detected = False
                    if aliyun_detected:
                        driver_had_error = True
                        _trigger_aliyun_captcha_stop(gui_instance, stop_signal)
                        break

                if outcome == "complete":
                    with lock:
                        if target_num <= 0 or cur_num < target_num:
                            cur_num += 1
                            logging.info(
                                f"[OK] 已填写{cur_num}份 - 失败{cur_fail}次 - {time.strftime('%H:%M:%S', time.localtime(time.time()))}"
                            )
                            if random_proxy_ip_enabled:
                                handle_random_ip_submission(gui_instance, stop_signal)
                            if target_num > 0 and cur_num >= target_num:
                                stop_signal.set()
                                _trigger_target_reached_stop(gui_instance, stop_signal)
                        else:
                            stop_signal.set()
                            break
                    grace_seconds = float(POST_SUBMIT_CLOSE_GRACE_SECONDS or 0.0)
                    if grace_seconds > 0 and not stop_signal.is_set():
                        time.sleep(grace_seconds)
                    _dispose_driver()
                    break

                if outcome == "followup":
                    followup_hops += 1
                    if POST_SUBMIT_FOLLOWUP_MAX_HOPS and followup_hops > int(POST_SUBMIT_FOLLOWUP_MAX_HOPS):
                        logging.warning(
                            "提交后检测到连续跳转问卷次数过多（>%s），视为失败：%s",
                            POST_SUBMIT_FOLLOWUP_MAX_HOPS,
                            outcome_url,
                        )
                        driver_had_error = True
                        if _handle_submission_failure(stop_signal):
                            break
                        break
                    next_norm = _normalize_url_for_compare(outcome_url)
                    if next_norm and next_norm in visited_urls:
                        logging.warning("提交后跳转问卷出现循环，视为失败：%s", outcome_url)
                        driver_had_error = True
                        if _handle_submission_failure(stop_signal):
                            break
                        break
                    if next_norm:
                        visited_urls.add(next_norm)
                    logging.info("[Action Log] 检测到分流：提交后跳转到下一份问卷：%s", outcome_url)
                    continue

                driver_had_error = True
                if _handle_submission_failure(stop_signal):
                    break
                break
        except AliyunCaptchaBypassError:
            driver_had_error = True
            _trigger_aliyun_captcha_stop(gui_instance, stop_signal)
            break
        except TimeoutException as exc:
            if stop_signal.is_set():
                break
            logging.debug("提交未完成（未检测到完成页）：%s", exc)

            # 未检测到完成页时再等一会：
            # 1) 继续等待完成页跳转/文案出现
            # 2) 若仍未完成，检查是否出现阿里云智能验证；若出现则按既有流程触发全局停止
            completion_detected = False
            extra_wait_seconds = max(1.0, float(POST_SUBMIT_URL_MAX_WAIT or 0.0) * 3.0)
            extra_poll = max(0.05, float(POST_SUBMIT_URL_POLL_INTERVAL or 0.1))
            extra_deadline = time.time() + extra_wait_seconds
            while time.time() < extra_deadline:
                if stop_signal.is_set():
                    break
                try:
                    current_url = driver.current_url
                except Exception:
                    current_url = ""
                if "complete" in str(current_url).lower():
                    completion_detected = True
                    break
                try:
                    if full_simulation_mode.is_survey_completion_page(driver):
                        completion_detected = True
                        break
                except Exception:
                    pass
                time.sleep(extra_poll)

            if not completion_detected and not stop_signal.is_set():
                aliyun_detected = False
                try:
                    aliyun_detected = handle_aliyun_captcha(
                        driver,
                        timeout=3,
                        stop_signal=stop_signal,
                        raise_on_detect=False,
                    )
                except Exception:
                    aliyun_detected = False
                if aliyun_detected:
                    driver_had_error = True
                    _trigger_aliyun_captcha_stop(gui_instance, stop_signal)
                    break

            if not completion_detected and not stop_signal.is_set():
                try:
                    current_url = driver.current_url
                except Exception:
                    current_url = ""
                if "complete" in str(current_url).lower():
                    completion_detected = True
                else:
                    try:
                        completion_detected = bool(full_simulation_mode.is_survey_completion_page(driver))
                    except Exception:
                        completion_detected = False

            if completion_detected:
                driver_had_error = False
                with lock:
                    if target_num <= 0 or cur_num < target_num:
                        cur_num += 1
                        logging.info(
                            f"[OK] 已填写{cur_num}份 - 失败{cur_fail}次 - {time.strftime('%H:%M:%S', time.localtime(time.time()))}"
                        )
                        if random_proxy_ip_enabled:
                            handle_random_ip_submission(gui_instance, stop_signal)
                        if target_num > 0 and cur_num >= target_num:
                            stop_signal.set()
                            _trigger_target_reached_stop(gui_instance, stop_signal)
                    else:
                        stop_signal.set()
                grace_seconds = float(POST_SUBMIT_CLOSE_GRACE_SECONDS or 0.0)
                if grace_seconds > 0 and not stop_signal.is_set():
                    time.sleep(grace_seconds)
                _dispose_driver()
                continue

            driver_had_error = True
            if _handle_submission_failure(stop_signal):
                break
        except EmptySurveySubmissionError:
            driver_had_error = True
            if stop_signal.is_set():
                break
            if _handle_submission_failure(stop_signal):
                break
        except Exception:
            driver_had_error = True
            if stop_signal.is_set():
                break
            traceback.print_exc()
            if _handle_submission_failure(stop_signal):
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
    ("multi_text", "多项填空题"),
    ("location", "位置题"),
]

LABEL_TO_TYPE = {label: value for value, label in TYPE_OPTIONS}


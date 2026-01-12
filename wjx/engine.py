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

from wjx.network.random_ip import (
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

from wjx.utils.log_utils import (
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

from wjx.utils.updater import (
    check_updates_on_startup,
    show_update_notification,
    check_for_updates as _check_for_updates_impl,
    perform_update as _perform_update_impl,
)

import wjx.modes.timed_mode as timed_mode
import wjx.modes.duration_control as duration_control
from wjx.modes.duration_control import DURATION_CONTROL_STATE as _DURATION_CONTROL_STATE

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError
from PIL import Image
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
from wjx.utils.version import __VERSION__, GITHUB_OWNER, GITHUB_REPO, ISSUE_FEEDBACK_URL
# 导入配置常量
from wjx.utils.config import (
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
    QUESTION_TYPE_LABELS,
    LOCATION_QUESTION_LABEL,
    DEFAULT_FILL_TEXT,
    _HTML_SPACE_RE,
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

from wjx.network.browser_driver import (
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

# 导入拆分后的模块
from wjx.core.captcha_handler import (
    AliyunCaptchaBypassError,
    EmptySurveySubmissionError,
    handle_aliyun_captcha,
    reset_captcha_popup_state,
)
from wjx.core.survey_parser import (
    parse_survey_questions_from_html,
    extract_survey_title_from_html as _extract_survey_title_from_html,
    _normalize_html_text,
    _should_treat_question_as_text_like,
    _should_mark_as_multi_text,
    _count_text_inputs_in_soup,
    _normalize_question_type_code,
)
# 题型处理函数
from wjx.core.question_utils import (
    weighted_index as _weighted_index,
    normalize_probabilities,
    normalize_droplist_probs as _normalize_droplist_probs,
    normalize_single_like_prob_config as _normalize_single_like_prob_config,
    normalize_option_fill_texts as _normalize_option_fill_texts,
    smooth_scroll_to_element as _smooth_scroll_to_element,
    fill_option_additional_text as _fill_option_additional_text,
    get_fill_text_from_config as _get_fill_text_from_config,
    resolve_dynamic_text_token as _resolve_dynamic_text_token_value,
    extract_text_from_element as _extract_text_from_element,
    generate_random_chinese_name as _generate_random_chinese_name_value,
    generate_random_mobile as _generate_random_mobile_value,
    generate_random_generic_text as _generate_random_generic_text_value,
)
from wjx.core.question_text import (
    vacant as _vacant_impl,
    MULTI_TEXT_DELIMITER,
    fill_text_question_input as _fill_text_question_input,
    fill_contenteditable_element as _fill_contenteditable_element,
    count_prefixed_text_inputs as _count_prefixed_text_inputs_driver,
    count_visible_text_inputs as _count_visible_text_inputs_driver,
    driver_question_is_location as _driver_question_is_location,
    should_mark_as_multi_text as _should_mark_as_multi_text_impl,
    should_treat_as_text_like as _should_treat_question_as_text_like_impl,
)
from wjx.core.question_single import single as _single_impl
from wjx.core.question_multiple import (
    multiple as _multiple_impl,
    detect_multiple_choice_limit,
    detect_multiple_choice_limit_range,
    _log_multi_limit_once,
)
from wjx.core.question_dropdown import droplist as _droplist_impl
from wjx.core.question_matrix import matrix as _matrix_impl
from wjx.core.question_scale import scale as _scale_impl
from wjx.core.question_slider import slider_question as _slider_question_impl, _resolve_slider_score
from wjx.core.question_reorder import reorder as _reorder_impl, detect_reorder_required_count






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
        # 开发环境，资源在项目根目录（wjx 目录的上一级）
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    return os.path.join(base_path, relative_path)




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


url = ""

single_prob: List[Union[List[float], int, float, None]] = []
droplist_prob: List[Union[List[float], int, float, None]] = []
multiple_prob: List[List[float]] = []
matrix_prob: List[Union[List[float], int, float, None]] = []
scale_prob: List[Union[List[float], int, float, None]] = []
slider_targets: List[float] = []
texts: List[List[str]] = []
texts_prob: List[List[float]] = []
# 与 texts/texts_prob 对齐，记录每道填空题的具体类型（text / multi_text）
text_entry_types: List[str] = []
single_option_fill_texts: List[Optional[List[Optional[str]]]] = []
droplist_option_fill_texts: List[Optional[List[Optional[str]]]] = []
multiple_option_fill_texts: List[Optional[List[Optional[str]]]] = []

# 最大线程数限制（确保用户电脑流畅）
MAX_THREADS = 12

# 浏览器实例并发限制（防止内存爆炸）
MAX_BROWSER_INSTANCES = 4
_browser_semaphore: Optional[threading.Semaphore] = None
_browser_semaphore_lock = threading.Lock()


def _get_browser_semaphore(max_instances: int = MAX_BROWSER_INSTANCES) -> threading.Semaphore:
    """获取或创建浏览器实例信号量，限制同时运行的浏览器数量"""
    global _browser_semaphore
    with _browser_semaphore_lock:
        if _browser_semaphore is None:
            _browser_semaphore = threading.Semaphore(max_instances)
        return _browser_semaphore


def _reset_browser_semaphore(max_instances: int = MAX_BROWSER_INSTANCES) -> None:
    """重置信号量（任务开始时调用）"""
    global _browser_semaphore
    with _browser_semaphore_lock:
        _browser_semaphore = threading.Semaphore(max_instances)

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
duration_control_enabled = False
duration_control_estimated_seconds = 0
duration_control_total_duration_seconds = 0
timed_mode_enabled = False
timed_mode_refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
random_proxy_ip_enabled = False
proxy_ip_pool: List[str] = []
random_user_agent_enabled = False
user_agent_pool_keys: List[str] = []
last_submit_had_captcha = False
_aliyun_captcha_stop_triggered = False
_aliyun_captcha_stop_lock = threading.Lock()
_aliyun_captcha_popup_shown = False
_target_reached_stop_triggered = False
_target_reached_stop_lock = threading.Lock()
_resume_after_aliyun_captcha_stop = False
_resume_snapshot: Dict[str, Any] = {}

def _show_aliyun_captcha_popup(message: str) -> None:
    """在首次检测到阿里云智能验证时弹窗提醒用户。"""
    global _aliyun_captcha_popup_shown
    with _aliyun_captcha_stop_lock:
        if _aliyun_captcha_popup_shown:
            return
        _aliyun_captcha_popup_shown = True
    try:
        log_popup_warning("智能验证提示", message)
    except Exception:
        logging.warning("弹窗提示阿里云智能验证失败", exc_info=True)

# 极速模式：时长控制/随机IP关闭且时间间隔为0时自动启用
def _is_fast_mode() -> bool:
    return (
        not duration_control_enabled
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
    """确保时长控制全局变量与模块状态保持一致（主要在 GUI/运行线程之间传递配置时使用）。"""
    _DURATION_CONTROL_STATE.enabled = bool(duration_control_enabled)
    _DURATION_CONTROL_STATE.estimated_seconds = int(duration_control_estimated_seconds or 0)
    _DURATION_CONTROL_STATE.total_duration_seconds = int(duration_control_total_duration_seconds or 0)

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
    distribution_mode: str = "random"  # random, custom
    custom_weights: Optional[List[float]] = None
    question_num: Optional[str] = None
    option_fill_texts: Optional[List[Optional[str]]] = None
    fillable_option_indices: Optional[List[int]] = None
    is_location: bool = False

    def summary(self) -> str:
        def _mode_text(mode: Optional[str]) -> str:
            return {
                "random": "完全随机",
                "custom": "自定义配比",
            }.get(mode or "", "完全随机")

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


from wjx.utils.load_save import ConfigPersistenceMixin, _select_user_agent_from_keys


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
    global single_prob, droplist_prob, multiple_prob, matrix_prob, scale_prob, slider_targets, texts, texts_prob, text_entry_types
    global single_option_fill_texts, droplist_option_fill_texts, multiple_option_fill_texts
    single_prob = []
    droplist_prob = []
    multiple_prob = []
    matrix_prob = []
    scale_prob = []
    slider_targets = []
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
        elif entry.question_type == "slider":
            target_value: Optional[float] = None
            if isinstance(entry.custom_weights, (list, tuple)) and entry.custom_weights:
                try:
                    target_value = float(entry.custom_weights[0])
                except Exception:
                    target_value = None
            if target_value is None:
                if isinstance(probs, (int, float)):
                    target_value = float(probs)
                elif isinstance(probs, list) and probs:
                    try:
                        target_value = float(probs[0])
                    except Exception:
                        target_value = None
            if target_value is None:
                target_value = 50.0
            slider_targets.append(target_value)
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
    elif type_code == "8":
        option_count = 1
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


def _extract_slider_range(question_div, question_number: int) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    尝试解析滑块题的最小值、最大值和步长，未找到时返回 (None, None, None)。
    """
    try:
        slider_input = question_div.find("input", id=f"q{question_number}")
        if not slider_input:
            slider_input = question_div.find("input", attrs={"type": "range"})
    except Exception:
        slider_input = None

    def _parse(raw: Any) -> Optional[float]:
        try:
            return float(raw)
        except Exception:
            return None

    if slider_input:
        return (
            _parse(slider_input.get("min")),
            _parse(slider_input.get("max")),
            _parse(slider_input.get("step")),
        )
    return None, None, None


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
    # 未知类型：若没有选项或仅1个伪选项，但存在输入框，则视作填空题
    return (option_count or 0) <= 1 and text_input_count > 0


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
            slider_min, slider_max, slider_step = (None, None, None)
            if type_code == "8":
                slider_min, slider_max, slider_step = _extract_slider_range(question_div, question_number)
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
                "slider_min": slider_min,
                "slider_max": slider_max,
                "slider_step": slider_step,
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


def _normalize_droplist_probs(prob_config: Union[List[float], int, float, None], option_count: int) -> List[float]:
    if option_count <= 0:
        return []
    if prob_config == -1 or prob_config is None:
        try:
            return normalize_probabilities([1.0] * option_count)
        except Exception:
            return [1.0 / option_count] * option_count
    try:
        # 尽量保留用户配置的配比，即便选项数量有变化也不强制重置
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


def _full_simulation_active() -> bool:
    _sync_full_sim_state_from_globals()
    return bool(_DURATION_CONTROL_STATE.active())


def _reset_full_simulation_runtime_state() -> None:
    _DURATION_CONTROL_STATE.reset_runtime()


def _prepare_full_simulation_schedule(run_count: int, total_duration_seconds: int) -> Deque[float]:
    schedule = _DURATION_CONTROL_STATE.prepare_schedule(run_count, total_duration_seconds)
    return schedule


def _wait_for_next_full_simulation_slot(stop_signal: threading.Event) -> bool:
    return _DURATION_CONTROL_STATE.wait_for_next_slot(stop_signal)


def _calculate_full_simulation_run_target(question_count: int) -> float:
    return _DURATION_CONTROL_STATE.calculate_run_target(question_count)


def _build_per_question_delay_plan(question_count: int, target_seconds: float) -> List[float]:
    return _DURATION_CONTROL_STATE.build_per_question_delay_plan(question_count, target_seconds)


def _simulate_answer_duration_delay(stop_signal: Optional[threading.Event] = None) -> bool:
    # 委托到模块实现，传入当前配置范围以避免模块依赖全局变量
    return duration_control.simulate_answer_duration_delay(stop_signal, answer_duration_range_seconds)


def _smooth_scroll_to_element(driver: BrowserDriver, element, block: str = 'center') -> None:
    """
    平滑滚动到指定元素位置，模拟人类滚动行为。
    仅在启用时长控制时使用平滑滚动，否则使用瞬间滚动。
    """
    if not _full_simulation_active():
        # 未启用时长控制时使用瞬间滚动
        try:
            driver.execute_script(f"arguments[0].scrollIntoView({{block:'{block}', behavior:'auto'}});", element)
        except Exception:
            pass
        return
    
    # 启用时长控制时使用平滑滚动
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
    slider_question_index = 0
    current_question_number = 0
    active_stop = stop_signal or stop_event
    question_delay_plan: Optional[List[float]] = None
    if _full_simulation_active() and total_question_count > 0:
        target_seconds = _calculate_full_simulation_run_target(total_question_count)
        question_delay_plan = _build_per_question_delay_plan(total_question_count, target_seconds)
        planned_total = sum(question_delay_plan)
        logging.info(
            "[Action Log] 时长控制：本次计划总耗时约 %.1f 秒，共 %d 题",
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
                # 检测是否为位置题
                is_location_question = _driver_question_is_location(question_div) if question_div is not None else False
                if is_location_question:
                    print(f"第{current_question_number}题为位置题，暂不支持，已跳过")
                else:
                    _vacant_impl(driver, current_question_number, vacant_question_index, texts, texts_prob, text_entry_types)
                    vacant_question_index += 1
            elif question_type == "3":
                _single_impl(driver, current_question_number, single_question_index, single_prob, single_option_fill_texts)
                single_question_index += 1
            elif question_type == "4":
                _multiple_impl(driver, current_question_number, multiple_question_index, multiple_prob, multiple_option_fill_texts)
                multiple_question_index += 1
            elif question_type == "5":
                _scale_impl(driver, current_question_number, scale_question_index, scale_prob)
                scale_question_index += 1
            elif question_type == "6":
                matrix_question_index = _matrix_impl(driver, current_question_number, matrix_question_index, matrix_prob)
            elif question_type == "7":
                _droplist_impl(driver, current_question_number, droplist_question_index, droplist_prob, droplist_option_fill_texts)
                droplist_question_index += 1
            elif question_type == "8":
                slider_score = _resolve_slider_score(slider_question_index, slider_targets)
                _slider_question_impl(driver, current_question_number, slider_score)
                slider_question_index += 1
            elif is_reorder_question:
                _reorder_impl(driver, current_question_number)
            else:
                # 兜底：尝试把未知类型当成填空题/多项填空题处理，避免直接跳过
                handled = False
                if question_div is not None:
                    checkbox_count, radio_count = _count_choice_inputs_driver(question_div)
                    if checkbox_count or radio_count:
                        if checkbox_count >= radio_count:
                            _multiple_impl(driver, current_question_number, multiple_question_index, multiple_prob, multiple_option_fill_texts)
                            multiple_question_index += 1
                        else:
                            _single_impl(driver, current_question_number, single_question_index, single_prob, single_option_fill_texts)
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
                        _vacant_impl(driver, current_question_number, vacant_question_index, texts, texts_prob, text_entry_types)
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
            if duration_control.is_survey_completion_page(driver):
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
    
    # 最后再检查一次 URL 是否包含 complete
    if "complete" in final_url.lower():
        return "complete", final_url
    
    # 也检查一下页面内容
    try:
        if duration_control.is_survey_completion_page(driver):
            return "complete", final_url
    except Exception:
        pass
    
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


def _is_device_quota_limit_page(driver: BrowserDriver) -> bool:
    """检测"设备已达到最大填写次数"提示页。"""
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
        return bool(driver.execute_script(script))
    except Exception:
        return False


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
    
    # 获取浏览器实例信号量，限制同时运行的浏览器数量
    browser_sem = _get_browser_semaphore(min(num_threads, MAX_BROWSER_INSTANCES))
    sem_acquired = False
    
    logging.info(f"目标份数: {target_num}, 当前进度: {cur_num}/{target_num}")
    if timed_mode_active:
        logging.info("定时模式已启用")
    if random_proxy_ip_enabled:
        logging.info("随机IP已启用")
    if random_user_agent_enabled:
        logging.info("随机UA已启用")

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
        nonlocal driver, sem_acquired
        if not driver:
            return
        # 收集浏览器进程 PID 用于强制清理
        pids_to_kill = set(getattr(driver, 'browser_pids', set()))
        _unregister_driver(driver)
        try:
            driver.quit()
        except Exception:
            pass
        driver = None
        # 强制清理残留进程
        if pids_to_kill:
            try:
                _kill_processes_by_pid(pids_to_kill)
            except Exception:
                pass
        # 释放信号量
        if sem_acquired:
            try:
                browser_sem.release()
                sem_acquired = False
                logging.debug("已释放浏览器信号量")
            except Exception:
                pass

    while True:
        if stop_signal.is_set():
            break
        with lock:
            if stop_signal.is_set() or (target_num > 0 and cur_num >= target_num):
                break
        
        if _full_simulation_active():
            if not _wait_for_next_full_simulation_slot(stop_signal):
                break
            logging.info("[Action Log] 时长控制时段管控中，等待编辑区释放...")
        if stop_signal.is_set():
            break
        
        if driver is None:
            # 获取信号量，限制同时运行的浏览器实例数量
            if not sem_acquired:
                browser_sem.acquire()
                sem_acquired = True
                logging.debug("已获取浏览器信号量")
            
            proxy_address = _select_proxy_for_session()
            if proxy_address:
                if not _proxy_is_responsive(proxy_address):
                    logging.warning(f"代理无响应：{proxy_address}")
                    _discard_unresponsive_proxy(proxy_address)
                    if stop_signal.is_set():
                        break
                    continue
            
            ua_value, ua_label = _select_user_agent_for_session()
            
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
                logging.error(f"启动浏览器失败：{exc}")
                traceback.print_exc()
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

                # 简化判断逻辑：点击提交成功后，短暂等待让页面加载
                post_submit_wait = random.uniform(0.2, 0.6)
                if stop_signal.wait(post_submit_wait):
                    break

                # 检查是否触发阿里云验证
                aliyun_detected = False
                if not stop_signal.is_set():
                    try:
                        aliyun_detected = handle_aliyun_captcha(
                            driver,
                            timeout=2,
                            stop_signal=stop_signal,
                            raise_on_detect=False,
                        )
                    except Exception:
                        aliyun_detected = False

                if aliyun_detected:
                    driver_had_error = True
                    _trigger_aliyun_captcha_stop(gui_instance, stop_signal)
                    break

                # 没有触发验证，直接标记为成功
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
                    if duration_control.is_survey_completion_page(driver):
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
                        completion_detected = bool(duration_control.is_survey_completion_page(driver))
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
    ("slider", "滑块题"),
    ("text", "填空题"),
    ("multi_text", "多项填空题"),
    ("location", "位置题"),
]

LABEL_TO_TYPE = {label: value for value, label in TYPE_OPTIONS}

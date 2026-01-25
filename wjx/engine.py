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
from datetime import datetime
from threading import Thread
from typing import List, Optional, Union, Dict, Any, Tuple, Callable, Set, Deque, Literal
from urllib.parse import urlparse
import webbrowser

import wjx.core.state as state
from wjx.core.captcha.control import _handle_aliyun_captcha_detected
from wjx.core.questions.config import QuestionEntry, configure_probabilities
from wjx.network.random_ip import _mask_proxy_for_log, _proxy_is_responsive, handle_random_ip_submission
from wjx.network.session_policy import (
    _discard_unresponsive_proxy,
    _record_bad_proxy_and_maybe_pause,
    _reset_bad_proxy_streak,
    _select_proxy_for_session,
    _select_user_agent_for_session,
)
from wjx.utils.io.qrcode_utils import decode_qrcode
from wjx.utils.app.runtime_paths import _get_resource_path, _get_runtime_directory

from wjx.utils.update.updater import (
    check_updates_on_startup,
    show_update_notification,
    check_for_updates as _check_for_updates_impl,
    perform_update as _perform_update_impl,
)

import wjx.modes.timed_mode as timed_mode
import wjx.modes.duration_control as duration_control
from wjx.modes.duration_control import DURATION_CONTROL_STATE as _DURATION_CONTROL_STATE

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

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
from wjx.utils.app.version import __VERSION__, GITHUB_OWNER, GITHUB_REPO, ISSUE_FEEDBACK_URL
# 导入配置常量
from wjx.utils.app.config import (
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
    ProxyConnectionError,
    TimeoutException,
    create_playwright_driver as _browser_create_playwright_driver,
    list_browser_pids as _list_browser_pids,
    graceful_terminate_process_tree,
)

# 导入拆分后的模块
from wjx.core.captcha.handler import (
    AliyunCaptchaBypassError,
    EmptySurveySubmissionError,
    handle_aliyun_captcha,
    reset_captcha_popup_state,
)
from wjx.core.survey.parser import (
    parse_survey_questions_from_html,
    extract_survey_title_from_html as _extract_survey_title_from_html,
    _normalize_html_text,
    _should_treat_question_as_text_like,
    _should_mark_as_multi_text,
    _count_text_inputs_in_soup,
    _normalize_question_type_code,
    _extract_question_number_from_div,
    _cleanup_question_title,
    _element_contains_text_input,
    _question_div_has_shared_text_input,
    _collect_choice_option_texts,
    _soup_question_is_location,
    _collect_select_option_texts,
    _collect_matrix_option_texts,
    _extract_question_title,
    _extract_question_metadata_from_html,
    _extract_jump_rules_from_html,
    _extract_slider_range,
)
# 题型处理函数
from wjx.core.questions.utils import (
    weighted_index as _weighted_index,
    normalize_probabilities,
    normalize_droplist_probs as _normalize_droplist_probs,
    normalize_single_like_prob_config as _normalize_single_like_prob_config,
    normalize_option_fill_texts as _normalize_option_fill_texts,
    resolve_prob_config as _resolve_prob_config,
    smooth_scroll_to_element as _smooth_scroll_to_element,
    fill_option_additional_text as _fill_option_additional_text,
    get_fill_text_from_config as _get_fill_text_from_config,
    resolve_dynamic_text_token as _resolve_dynamic_text_token_value,
    extract_text_from_element as _extract_text_from_element,
    generate_random_chinese_name as _generate_random_chinese_name_value,
    generate_random_mobile as _generate_random_mobile_value,
    generate_random_generic_text as _generate_random_generic_text_value,
)
from wjx.core.questions.types.text import (
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
from wjx.core.ai.runtime import AIRuntimeError
from wjx.core.questions.types.single import single as _single_impl
from wjx.core.questions.types.multiple import (
    multiple as _multiple_impl,
    detect_multiple_choice_limit,
    detect_multiple_choice_limit_range,
    _log_multi_limit_once,
    _safe_positive_int,
    _extract_range_from_json_obj,
    _extract_range_from_possible_json,
    _extract_min_max_from_attributes,
    _extract_multi_limit_range_from_text,
    _get_driver_session_key,
)
from wjx.core.questions.types.dropdown import droplist as _droplist_impl
from wjx.core.questions.types.matrix import matrix as _matrix_impl
from wjx.core.questions.types.scale import scale as _scale_impl
from wjx.core.questions.types.slider import slider_question as _slider_question_impl, _resolve_slider_score
from wjx.core.questions.types.reorder import reorder as _reorder_impl, detect_reorder_required_count






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


def _is_fast_mode() -> bool:
    # 极速模式：时长控制/随机IP关闭且时间间隔为0时自动启用
    return (
        not state.duration_control_enabled
        and not state.random_proxy_ip_enabled
        and state.submit_interval_range_seconds == (0, 0)
        and state.answer_duration_range_seconds == (0, 0)
    )


def _timed_mode_active() -> bool:
    return bool(state.timed_mode_enabled)


def _handle_submission_failure(stop_signal: Optional[threading.Event]) -> bool:
    """
    递增失败计数；当开启失败止损时超过阈值会触发停止。
    返回 True 表示已触发强制停止。
    """
    with state.lock:
        state.cur_fail += 1
        if state.stop_on_fail_enabled:
            print(f"已失败{state.cur_fail}次, 失败次数达到{int(state.fail_threshold)}次将强制停止")
        else:
            print(f"已失败{state.cur_fail}次（失败止损已关闭）")
    if state.stop_on_fail_enabled and state.cur_fail >= state.fail_threshold:
        logging.critical("失败次数过多，强制停止，请检查配置是否正确")
        if stop_signal:
            stop_signal.set()
        return True
    return False


def _wait_if_paused(gui_instance: Optional[Any], stop_signal: Optional[threading.Event]) -> None:
    try:
        if gui_instance and hasattr(gui_instance, "wait_if_paused"):
            gui_instance.wait_if_paused(stop_signal)
    except Exception:
        pass


def _trigger_target_reached_stop(
    gui_instance: Optional[Any],
    stop_signal: Optional[threading.Event],
) -> None:
    """达到目标份数时触发全局立即停止。"""
    with state._target_reached_stop_lock:
        if state._target_reached_stop_triggered:
            if stop_signal:
                stop_signal.set()
            return
        state._target_reached_stop_triggered = True

    if stop_signal:
        stop_signal.set()

    def _notify():
        try:
            if gui_instance and hasattr(gui_instance, "force_stop_immediately"):
                gui_instance.force_stop_immediately(reason="任务完成")
        except Exception:
            logging.debug("达到目标份数时触发强制停止失败", exc_info=True)

    dispatcher = getattr(gui_instance, "_post_to_ui_thread_async", None) if gui_instance else None
    if callable(dispatcher):
        try:
            dispatcher(_notify)
            return
        except Exception:
            logging.debug("派发任务完成事件到主线程失败", exc_info=True)
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
    _DURATION_CONTROL_STATE.enabled = bool(state.duration_control_enabled)
    _DURATION_CONTROL_STATE.estimated_seconds = int(state.duration_control_estimated_seconds or 0)
    _DURATION_CONTROL_STATE.total_duration_seconds = int(state.duration_control_total_duration_seconds or 0)


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




_TEXT_INPUT_ALLOWED_TYPES = {"", "text", "search", "tel", "number"}
_KNOWN_NON_TEXT_QUESTION_TYPES = {"3", "4", "5", "6", "7", "8", "11"}


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
    return duration_control.simulate_answer_duration_delay(stop_signal, state.answer_duration_range_seconds)


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
    active_stop = stop_signal or state.stop_event
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
                    _vacant_impl(
                        driver,
                        current_question_number,
                        vacant_question_index,
                        state.texts,
                        state.texts_prob,
                        state.text_entry_types,
                        state.text_ai_flags,
                        state.text_titles,
                    )
                    vacant_question_index += 1
            elif question_type == "3":
                _single_impl(driver, current_question_number, single_question_index, state.single_prob, state.single_option_fill_texts)
                single_question_index += 1
            elif question_type == "4":
                _multiple_impl(driver, current_question_number, multiple_question_index, state.multiple_prob, state.multiple_option_fill_texts)
                multiple_question_index += 1
            elif question_type == "5":
                _scale_impl(driver, current_question_number, scale_question_index, state.scale_prob)
                scale_question_index += 1
            elif question_type == "6":
                matrix_question_index = _matrix_impl(driver, current_question_number, matrix_question_index, state.matrix_prob)
            elif question_type == "7":
                _droplist_impl(driver, current_question_number, droplist_question_index, state.droplist_prob, state.droplist_option_fill_texts)
                droplist_question_index += 1
            elif question_type == "8":
                slider_score = _resolve_slider_score(slider_question_index, state.slider_targets)
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
                            _multiple_impl(driver, current_question_number, multiple_question_index, state.multiple_prob, state.multiple_option_fill_texts)
                            multiple_question_index += 1
                        else:
                            _single_impl(driver, current_question_number, single_question_index, state.single_prob, state.single_option_fill_texts)
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
                        _vacant_impl(
                            driver,
                            current_question_number,
                            vacant_question_index,
                            state.texts,
                            state.texts_prob,
                            state.text_entry_types,
                            state.text_ai_flags,
                            state.text_titles,
                        )
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

    state.last_submit_had_captcha = False

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

    fast_mode = _is_fast_mode()
    timed_mode_active = _timed_mode_active()
    try:
        timed_refresh_interval = float(state.timed_mode_refresh_interval or timed_mode.DEFAULT_REFRESH_INTERVAL)
    except Exception:
        timed_refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
    if timed_refresh_interval <= 0:
        timed_refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
    base_browser_preference = list(getattr(state, "browser_preference", []) or BROWSER_PREFERENCE)
    preferred_browsers = list(base_browser_preference)
    driver: Optional[BrowserDriver] = None
    proxy_address: Optional[str] = None  # 初始化代理地址变量，避免异常处理中未绑定错误
    
    # 获取浏览器实例信号量，限制同时运行的浏览器数量
    browser_sem = state._get_browser_semaphore(min(state.num_threads, state.MAX_BROWSER_INSTANCES))
    sem_acquired = False
    
    logging.info(f"目标份数: {state.target_num}, 当前进度: {state.cur_num}/{state.target_num}")
    if timed_mode_active:
        logging.info("定时模式已启用")
    if state.random_proxy_ip_enabled:
        logging.info("随机IP已启用")
    if state.random_user_agent_enabled:
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
        if driver:
            # 收集浏览器进程 PID 用于强制清理
            pids_to_kill = set(getattr(driver, "browser_pids", set()))
            _unregister_driver(driver)
            try:
                driver.quit()
            except Exception:
                pass
            driver = None
            # 等待已知 PID 自行退出，避免 taskkill
            if pids_to_kill:
                try:
                    graceful_terminate_process_tree(pids_to_kill, wait_seconds=3.0)
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
        _wait_if_paused(gui_instance, stop_signal)
        if stop_signal.is_set():
            break
        with state.lock:
            if stop_signal.is_set() or (state.target_num > 0 and state.cur_num >= state.target_num):
                break
        
        if _full_simulation_active():
            if not _wait_for_next_full_simulation_slot(stop_signal):
                break
            logging.info("[Action Log] 时长控制时段管控中，等待编辑区释放...")
        if stop_signal.is_set():
            break
        _wait_if_paused(gui_instance, stop_signal)
        
        if driver is None:
            proxy_address = _select_proxy_for_session()
            if state.random_proxy_ip_enabled and not proxy_address:
                if _record_bad_proxy_and_maybe_pause(gui_instance):
                    continue
            if proxy_address:
                if not _proxy_is_responsive(proxy_address):
                    logging.warning(f"代理无响应：{_mask_proxy_for_log(proxy_address)}")
                    _discard_unresponsive_proxy(proxy_address)
                    if stop_signal.is_set():
                        break
                    # 避免代理源异常时进入高频死循环（频繁请求代理/健康检查会拖慢整机）
                    if state.random_proxy_ip_enabled:
                        if _record_bad_proxy_and_maybe_pause(gui_instance):
                            continue
                    stop_signal.wait(0.8)
                    continue
                else:
                    _reset_bad_proxy_streak()
            
            ua_value, ua_label = _select_user_agent_for_session()
            
            # 获取信号量，限制同时运行的浏览器实例数量
            if not sem_acquired:
                browser_sem.acquire()
                sem_acquired = True
                logging.debug("已获取浏览器信号量")
            
            try:
                driver, active_browser = create_playwright_driver(
                    headless=False,
                    prefer_browsers=list(preferred_browsers) if preferred_browsers else None,
                    proxy_address=proxy_address,
                    user_agent=ua_value,
                    window_position=(window_x_pos, window_y_pos),
                )
            except Exception as exc:
                # 创建浏览器失败时释放信号量
                if sem_acquired:
                    browser_sem.release()
                    sem_acquired = False
                    logging.debug("创建浏览器失败，已释放信号量")
                if stop_signal.is_set():
                    break
                logging.error(f"启动浏览器失败：{exc}")
                traceback.print_exc()
                if stop_signal.wait(1.0):
                    break
                continue
            
            preferred_browsers = [active_browser] + [b for b in base_browser_preference if b != active_browser]
            _register_driver(driver)
            driver.set_window_size(550, 650)

        driver_had_error = False
        try:
            if stop_signal.is_set():
                break
            if not state.url:
                logging.error("无法启动：问卷链接为空")
                driver_had_error = True
                break
            _wait_if_paused(gui_instance, stop_signal)
            if timed_mode_active:
                logging.info("[Action Log] 定时模式：开始刷新等待问卷开放")
                ready = timed_mode.wait_until_open(
                    driver,
                    state.url,
                    stop_signal,
                    refresh_interval=timed_refresh_interval,
                    logger=logging.info,
                )
                if not ready:
                    if not stop_signal.is_set():
                        stop_signal.set()
                    break
            else:
                driver.get(state.url)
                if stop_signal.is_set():
                    break
            if _is_device_quota_limit_page(driver):
                logging.warning("检测到“设备已达到最大填写次数”提示页，直接放弃当前浏览器实例并标记为成功。")
                should_handle_random_ip = False
                should_stop_after_quota = False
                trigger_target_stop = False
                force_stop = False
                with state.lock:
                    if state.target_num <= 0 or state.cur_num < state.target_num:
                        state.cur_num += 1
                        logging.info(
                            f"[OK/Quota] 已填写{state.cur_num}份 - 失败{state.cur_fail}次 - {time.strftime('%H:%M:%S', time.localtime(time.time()))}"
                        )
                        should_handle_random_ip = state.random_proxy_ip_enabled
                        if state.target_num > 0 and state.cur_num >= state.target_num:
                            trigger_target_stop = True
                            force_stop = True
                            should_stop_after_quota = True
                    else:
                        force_stop = True
                        should_stop_after_quota = True
                if force_stop:
                    stop_signal.set()
                if trigger_target_stop:
                    _trigger_target_reached_stop(gui_instance, stop_signal)
                _dispose_driver()
                if should_handle_random_ip:
                    handle_random_ip_submission(gui_instance, stop_signal)
                if should_stop_after_quota:
                    break
                continue
            followup_hops = 0
            visited_urls: Set[str] = set()
            try:
                visited_urls.add(_normalize_url_for_compare(driver.current_url))
            except Exception:
                visited_urls.add(_normalize_url_for_compare(state.url))

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
                    _handle_aliyun_captcha_detected(gui_instance, stop_signal)
                    break

                # 没有触发验证，直接标记为成功
                should_handle_random_ip = False
                trigger_target_stop = False
                should_break = False
                with state.lock:
                    if state.target_num <= 0 or state.cur_num < state.target_num:
                        state.cur_num += 1
                        logging.info(
                            f"[OK] 已填写{state.cur_num}份 - 失败{state.cur_fail}次 - {time.strftime('%H:%M:%S', time.localtime(time.time()))}"
                        )
                        should_handle_random_ip = state.random_proxy_ip_enabled
                        if state.target_num > 0 and state.cur_num >= state.target_num:
                            trigger_target_stop = True
                    else:
                        should_break = True
                if should_break:
                    stop_signal.set()
                    break
                if trigger_target_stop:
                    stop_signal.set()
                    _trigger_target_reached_stop(gui_instance, stop_signal)
                grace_seconds = float(POST_SUBMIT_CLOSE_GRACE_SECONDS or 0.0)
                if grace_seconds > 0 and not stop_signal.is_set():
                    time.sleep(grace_seconds)
                _dispose_driver()
                if should_handle_random_ip:
                    handle_random_ip_submission(gui_instance, stop_signal)
                break
        except AliyunCaptchaBypassError:
            driver_had_error = True
            _handle_aliyun_captcha_detected(gui_instance, stop_signal)
            break
        except AIRuntimeError as exc:
            driver_had_error = True
            logging.error("AI 填空失败，已停止任务：%s", exc, exc_info=True)
            if stop_signal and not stop_signal.is_set():
                stop_signal.set()
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
                    _handle_aliyun_captcha_detected(gui_instance, stop_signal)
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
                should_handle_random_ip = False
                trigger_target_stop = False
                with state.lock:
                    if state.target_num <= 0 or state.cur_num < state.target_num:
                        state.cur_num += 1
                        logging.info(
                            f"[OK] 已填写{state.cur_num}份 - 失败{state.cur_fail}次 - {time.strftime('%H:%M:%S', time.localtime(time.time()))}"
                        )
                        should_handle_random_ip = state.random_proxy_ip_enabled
                        if state.target_num > 0 and state.cur_num >= state.target_num:
                            trigger_target_stop = True
                    else:
                        stop_signal.set()
                if trigger_target_stop:
                    stop_signal.set()
                    _trigger_target_reached_stop(gui_instance, stop_signal)
                grace_seconds = float(POST_SUBMIT_CLOSE_GRACE_SECONDS or 0.0)
                if grace_seconds > 0 and not stop_signal.is_set():
                    time.sleep(grace_seconds)
                _dispose_driver()
                if should_handle_random_ip:
                    handle_random_ip_submission(gui_instance, stop_signal)
                continue

            driver_had_error = True
            if _handle_submission_failure(stop_signal):
                break
        except ProxyConnectionError as exc:
            driver_had_error = True
            if stop_signal.is_set():
                break
            logging.warning(f"代理隧道连接失败：{exc}")
            if proxy_address:
                _discard_unresponsive_proxy(proxy_address)
            if state.random_proxy_ip_enabled and proxy_address:
                if _record_bad_proxy_and_maybe_pause(gui_instance):
                    break
                stop_signal.wait(0.8)
                continue
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
            min_wait, max_wait = state.submit_interval_range_seconds
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

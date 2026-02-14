"""页面导航 - 翻页、跳转与滚动控制"""
import math
import random
import threading
import time
from typing import Optional

from wjx.core.questions.utils import (
    extract_text_from_element as _extract_text_from_element,
    smooth_scroll_to_element as _smooth_scroll_to_element,
)
from wjx.network.browser import By, BrowserDriver
from wjx.utils.logging.log_utils import log_suppressed_exception


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
                except Exception as exc:
                    log_suppressed_exception("navigation.try_click_start_answer_button scroll", exc)
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
                except Exception as exc:
                    log_suppressed_exception("navigation.dismiss_resume_dialog_if_present scroll", exc)
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


def _human_scroll_after_question(driver: BrowserDriver) -> None:
    distance = random.uniform(120, 260)
    page = getattr(driver, "page", None)
    if page:
        try:
            page.mouse.wheel(0, distance)
            return
        except Exception as exc:
            log_suppressed_exception("navigation._human_scroll_after_question mouse wheel", exc)
    try:
        driver.execute_script("window.scrollBy(0, arguments[0]);", distance)
    except Exception as exc:
        log_suppressed_exception("navigation._human_scroll_after_question script", exc)


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
    except Exception as exc:
        log_suppressed_exception("navigation._click_next_page_button unhide", exc)
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
            except Exception as exc:
                log_suppressed_exception("navigation._click_next_page_button scroll", exc)
            try:
                element.click()
                return True
            except Exception as exc:
                log_suppressed_exception("navigation._click_next_page_button click", exc)
            try:
                driver.execute_script("arguments[0].click();", element)
                return True
            except Exception as exc:
                log_suppressed_exception("navigation._click_next_page_button js click", exc)
    try:
        executed = driver.execute_script(
            """
            if (typeof show_next_page === 'function') { show_next_page(); return true; }
            if (typeof next_page === 'function') { next_page(); return true; }
            if (typeof nextPage === 'function') { nextPage(); return true; }
            return false;
            """
        )
        if executed:
            return True
    except Exception as exc:
        log_suppressed_exception("navigation._click_next_page_button js fallback", exc)
    return False


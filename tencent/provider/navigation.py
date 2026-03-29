"""腾讯问卷导航辅助。"""

from __future__ import annotations

import math
import threading
import time
from typing import Optional

from software.core.questions.utils import (
    extract_text_from_element as _extract_text_from_element,
    smooth_scroll_to_element as _smooth_scroll_to_element,
)
from software.logging.log_utils import log_suppressed_exception
from software.network.browser import By, BrowserDriver


def dismiss_resume_dialog_if_present(
    driver: BrowserDriver, timeout: float = 1.0, stop_signal: Optional[threading.Event] = None
) -> bool:
    """兼容处理可能出现的续答弹窗；未命中时直接继续。"""
    poll_interval = 0.2
    total_window = max(0.0, timeout)
    max_checks = max(1, int(math.ceil(total_window / max(poll_interval, 0.05)))) if total_window else 1
    locator_candidates = [
        (By.CSS_SELECTOR, "a.layui-layer-btn1"),
        (By.XPATH, "//a[contains(@class,'layui-layer-btn1') and contains(normalize-space(),'取消')]"),
        (By.XPATH, "//div[contains(@class,'layui-layer-btn')]//a[contains(text(),'取消')]"),
        (By.XPATH, "//button[contains(normalize-space(.),'重新填写')]"),
        (By.XPATH, "//button[contains(normalize-space(.),'重新作答')]"),
        (By.XPATH, "//button[contains(normalize-space(.),'重新开始')]"),
        (By.XPATH, "//button[contains(normalize-space(.),'取消')]"),
    ]
    dialog_hint_script = r"""
        return (() => {
            const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };
            const bodyText = (document.body?.innerText || '').replace(/\s+/g, '');
            const markers = ['继续上次作答', '继续上次填写', '继续填写', '重新填写', '重新作答'];
            if (!markers.some((marker) => bodyText.includes(marker))) return false;
            const buttons = Array.from(document.querySelectorAll('button, a')).filter(visible);
            return buttons.some((node) => {
                const text = (node.innerText || node.textContent || '').replace(/\s+/g, '');
                return ['取消', '重新填写', '重新作答', '重新开始'].some((label) => text.includes(label));
            });
        })();
    """
    for attempt in range(max_checks):
        if stop_signal and stop_signal.is_set():
            return False
        try:
            dialog_visible = bool(driver.execute_script(dialog_hint_script))
        except Exception:
            dialog_visible = False
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
                normalized_text = text.replace(" ", "") if text else ""
                if normalized_text:
                    labels = ("取消", "重新填写", "重新作答", "重新开始")
                    if not any(label in normalized_text for label in labels):
                        continue
                if not normalized_text and not dialog_visible:
                    continue
                try:
                    _smooth_scroll_to_element(driver, button, "center")
                except Exception as exc:
                    log_suppressed_exception("tencent.navigation.dismiss_resume_dialog_if_present scroll", exc)
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


def _click_next_page_button(driver: BrowserDriver) -> bool:
    """尝试点击“下一页”按钮。"""
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
        log_suppressed_exception("tencent.navigation._click_next_page_button unhide", exc)
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
                _smooth_scroll_to_element(driver, element, "center")
            except Exception as exc:
                log_suppressed_exception("tencent.navigation._click_next_page_button scroll", exc)
            try:
                element.click()
                return True
            except Exception as exc:
                log_suppressed_exception("tencent.navigation._click_next_page_button click", exc)
            try:
                driver.execute_script("arguments[0].click();", element)
                return True
            except Exception as exc:
                log_suppressed_exception("tencent.navigation._click_next_page_button js click", exc)
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
        log_suppressed_exception("tencent.navigation._click_next_page_button js fallback", exc)
    return False


__all__ = [
    "_click_next_page_button",
    "dismiss_resume_dialog_if_present",
]

"""腾讯问卷提交流程。"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from software.app.config import (
    HEADLESS_SUBMIT_CLICK_SETTLE_DELAY,
    HEADLESS_SUBMIT_INITIAL_DELAY,
    SUBMIT_CLICK_SETTLE_DELAY,
    SUBMIT_INITIAL_DELAY,
)
from software.core.engine.runtime_control import _is_headless_mode, _sleep_with_stop
from software.core.questions.utils import extract_text_from_element as _extract_text_from_element
from software.core.task import TaskContext
from software.network.browser import By, BrowserDriver, NoSuchElementException


def _click_submit_button(driver: BrowserDriver, max_wait: float = 10.0) -> bool:
    submit_keywords = ("提交", "完成", "交卷", "确认提交", "确认")
    locator_candidates = [
        (By.CSS_SELECTOR, "#ctlNext"),
        (By.CSS_SELECTOR, "#submit_button"),
        (By.CSS_SELECTOR, "#SubmitBtnGroup .submitbtn"),
        (By.CSS_SELECTOR, ".submitbtn.mainBgColor"),
        (By.CSS_SELECTOR, "#SM_BTN_1"),
        (By.CSS_SELECTOR, "#divSubmit"),
        (By.CSS_SELECTOR, ".btn-submit"),
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
        return any(keyword in text for keyword in submit_keywords)

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
                if by == By.CSS_SELECTOR and value == "button[type='submit']" and not _text_looks_like_submit(element):
                    continue
                for click_method in (
                    lambda: element.click(),
                    lambda: driver.execute_script("arguments[0].click();", element),
                ):
                    try:
                        click_method()
                        logging.info("腾讯问卷提交按钮已点击：%s=%s", by, value)
                        return True
                    except Exception:
                        continue
        if time.time() >= deadline:
            break
        time.sleep(0.2)

    try:
        force_triggered = bool(
            driver.execute_script(
                r"""
                return (() => {
                    const clickVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        if (!style) return false;
                        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                        const rect = el.getBoundingClientRect();
                        if (rect.width <= 0 || rect.height <= 0) return false;
                        el.click();
                        return true;
                    };

                    const submitLike = Array.from(document.querySelectorAll('div,a,button,input,span')).find((el) => {
                        const text = (el.innerText || el.textContent || el.value || '').replace(/\s+/g, '');
                        return text === '提交' || text === '完成' || text === '交卷' || text === '确认提交';
                    });
                    if (clickVisible(submitLike)) return true;

                    if (typeof submit_button_click === 'function') {
                        submit_button_click();
                        return true;
                    }
                    return false;
                })();
                """
            )
        )
        if force_triggered:
            logging.info("腾讯问卷提交按钮常规选择器未命中，已触发 JS 兜底")
            return True
    except Exception:
        pass
    return False


def _click_submit_confirm_button(driver: BrowserDriver, settle_delay: float = 0.0) -> None:
    confirm_candidates = [
        (By.XPATH, '//*[@id="layui-layer1"]/div[3]/a'),
        (By.CSS_SELECTOR, "#layui-layer1 .layui-layer-btn a"),
        (By.CSS_SELECTOR, ".layui-layer .layui-layer-btn a.layui-layer-btn0"),
    ]
    for by, value in confirm_candidates:
        try:
            element = driver.find_element(by, value)
        except Exception:
            element = None
        if not element:
            continue
        try:
            if not element.is_displayed():
                continue
        except Exception:
            continue
        try:
            element.click()
            if settle_delay > 0:
                time.sleep(settle_delay)
            return
        except Exception:
            continue


def submit(
    driver: BrowserDriver,
    ctx: Optional[TaskContext] = None,
    stop_signal: Optional[threading.Event] = None,
) -> None:
    headless_mode = _is_headless_mode(ctx)
    settle_delay = float(HEADLESS_SUBMIT_CLICK_SETTLE_DELAY if headless_mode else SUBMIT_CLICK_SETTLE_DELAY)
    pre_submit_delay = float(HEADLESS_SUBMIT_INITIAL_DELAY if headless_mode else SUBMIT_INITIAL_DELAY)

    if pre_submit_delay > 0 and _sleep_with_stop(stop_signal, pre_submit_delay):
        return
    if stop_signal and stop_signal.is_set():
        return

    clicked = _click_submit_button(driver, max_wait=10.0)
    if not clicked:
        raise NoSuchElementException("Submit button not found")
    if settle_delay > 0:
        time.sleep(settle_delay)
    _click_submit_confirm_button(driver, settle_delay=settle_delay)


def consume_submission_success_signal(driver: BrowserDriver) -> bool:
    del driver
    return False


def is_device_quota_limit_page(driver: BrowserDriver) -> bool:
    del driver
    return False


__all__ = [
    "_click_submit_button",
    "consume_submission_success_signal",
    "is_device_quota_limit_page",
    "submit",
]

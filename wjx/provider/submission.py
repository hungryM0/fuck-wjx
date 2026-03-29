"""问卷星提交流程能力（provider 入口）。"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from wjx.provider._submission_core import (
    EmptySurveySubmissionError,
    _click_submit_button,
    _is_wjx_domain,
    _looks_like_wjx_survey_url,
    _normalize_url_for_compare,
    _page_looks_like_wjx_questionnaire,
    consume_headless_httpx_submit_success,
    _is_device_quota_limit_page,
    submit,
)
from software.core.task import EVENT_CAPTCHA_DETECTED, TaskContext, bus as _event_bus
from software.logging.log_utils import log_popup_confirm, log_popup_warning
from software.network.browser import By, BrowserDriver

_ALIYUN_CAPTCHA_MESSAGE = "检测到问卷星阿里云智能验证，当前版本暂不支持自动处理，请更换或启用随机 IP 后重试。"
_ALIYUN_CAPTCHA_DOM_IDS = (
    "aliyunCaptcha-window-popup",
    "aliyunCaptcha-title",
    "aliyunCaptcha-checkbox",
    "aliyunCaptcha-checkbox-wrapper",
    "aliyunCaptcha-checkbox-body",
    "aliyunCaptcha-checkbox-icon",
    "aliyunCaptcha-checkbox-left",
    "aliyunCaptcha-checkbox-text",
    "aliyunCaptcha-loading",
    "aliyunCaptcha-certifyId",
)
_ALIYUN_CAPTCHA_LOCATORS = (
    (By.ID, "aliyunCaptcha-window-popup"),
    (By.ID, "aliyunCaptcha-checkbox-icon"),
    (By.ID, "aliyunCaptcha-checkbox-left"),
    (By.ID, "aliyunCaptcha-checkbox-text"),
)


class AliyunCaptchaBypassError(RuntimeError):
    """检测到问卷星阿里云智能验证（需要人工交互）时抛出。"""


def submission_validation_message(driver: Optional[BrowserDriver] = None) -> str:
    """返回问卷星提交流程的风控提示文案。"""
    return _ALIYUN_CAPTCHA_MESSAGE


def _aliyun_captcha_visible_with_js(driver: BrowserDriver) -> bool:
    script = r"""
        return (() => {
            const ids = [
                'aliyunCaptcha-window-popup',
                'aliyunCaptcha-title',
                'aliyunCaptcha-checkbox',
                'aliyunCaptcha-checkbox-wrapper',
                'aliyunCaptcha-checkbox-body',
                'aliyunCaptcha-checkbox-icon',
                'aliyunCaptcha-checkbox-left',
                'aliyunCaptcha-checkbox-text',
                'aliyunCaptcha-loading',
                'aliyunCaptcha-certifyId',
            ];

            const visible = (el, win) => {
                if (!el || !win) return false;
                const style = win.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };

            const checkDoc = (doc) => {
                if (!doc) return false;
                const win = doc.defaultView;
                if (!win) return false;
                for (const id of ids) {
                    const el = doc.getElementById(id);
                    if (visible(el, win)) return true;
                }
                return false;
            };

            if (checkDoc(document)) return true;
            const frames = Array.from(document.querySelectorAll('iframe'));
            for (const frame of frames) {
                try {
                    const doc = frame.contentDocument || frame.contentWindow?.document;
                    if (checkDoc(doc)) return true;
                } catch (e) {}
            }
            return false;
        })();
    """
    try:
        return bool(driver.execute_script(script))
    except Exception:
        return False


def _aliyun_captcha_element_exists(driver: BrowserDriver) -> bool:
    for locator in _ALIYUN_CAPTCHA_LOCATORS:
        try:
            element = driver.find_element(*locator)
            if element and element.is_displayed():
                return True
        except Exception:
            continue
    return False


def submission_requires_verification(driver: BrowserDriver) -> bool:
    """检测提交后是否出现问卷星阿里云智能验证 DOM。"""
    return _aliyun_captcha_visible_with_js(driver) or _aliyun_captcha_element_exists(driver)


def wait_for_submission_verification(
    driver: BrowserDriver,
    timeout: int = 3,
    stop_signal: Optional[threading.Event] = None,
    raise_on_detect: bool = False,
    notify_on_detect: bool = False,
) -> bool:
    """在短时间内轮询问卷星提交流程是否触发阿里云智能验证。"""
    del notify_on_detect  # 统一由命中后的 provider 处理流程负责提示，避免线程弹窗和主线程弹窗重复轰炸。

    end_time = time.time() + max(timeout, 3)
    while time.time() < end_time:
        if stop_signal and stop_signal.is_set():
            return False
        if submission_requires_verification(driver):
            if raise_on_detect:
                raise AliyunCaptchaBypassError(_ALIYUN_CAPTCHA_MESSAGE)
            return True
        time.sleep(0.15)

    if submission_requires_verification(driver):
        if raise_on_detect:
            raise AliyunCaptchaBypassError(_ALIYUN_CAPTCHA_MESSAGE)
        return True
    return False


def _trigger_aliyun_captcha_stop(
    ctx: TaskContext,
    gui_instance: Optional[Any],
    stop_signal: Optional[threading.Event],
) -> None:
    """命中问卷星阿里云智能验证后触发全局暂停，并提示用户启用随机 IP。"""
    with ctx._aliyun_captcha_stop_lock:
        if ctx._aliyun_captcha_stop_triggered:
            return
        ctx._aliyun_captcha_stop_triggered = True

    logging.warning("检测到问卷星阿里云智能验证，已触发全局暂停。")
    _event_bus.emit(EVENT_CAPTCHA_DETECTED, ctx=ctx)

    if stop_signal and not stop_signal.is_set():
        stop_signal.set()
        logging.warning("智能验证命中：已设置 stop_signal，任务将立即停止")

    try:
        if gui_instance:
            gui_instance.pause_run("触发智能验证")
            logging.warning("智能验证命中：已调用 pause_run")
    except Exception:
        logging.info("阿里云智能验证触发暂停失败", exc_info=True)

    def _notify() -> None:
        try:
            if threading.current_thread() is not threading.main_thread():
                return

            from software.network.proxy.policy import get_random_ip_counter_snapshot_local
            from software.network.proxy.session import has_authenticated_session, is_quota_exhausted

            is_enabled = bool(gui_instance.is_random_ip_enabled()) if gui_instance else False

            if is_enabled:
                message = (
                    "检测到问卷星阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                    "随机 IP 已启用，建议处理完验证后重新启动任务。"
                )
                if gui_instance:
                    gui_instance.show_message_dialog("智能验证提示", message, level="warning")
                else:
                    log_popup_warning("智能验证提示", message)
                return

            used, total, custom_api = get_random_ip_counter_snapshot_local()
            if custom_api:
                message = (
                    "检测到问卷星阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                    "你当前使用的是自定义代理接口，请处理完验证后重新启动任务。"
                )
                if gui_instance:
                    gui_instance.show_message_dialog("智能验证提示", message, level="warning")
                else:
                    log_popup_warning("智能验证提示", message)
                return

            if not has_authenticated_session():
                message = (
                    "检测到问卷星阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                    "默认随机 IP 现已需要先领取免费试用或提交额度申请。\n"
                    "请先完成试用激活或额度申请，或切换自定义代理接口后再试。"
                )
                if gui_instance:
                    gui_instance.show_message_dialog("智能验证提示", message, level="warning")
                else:
                    log_popup_warning("智能验证提示", message)
                return

            quota_exceeded = is_quota_exhausted(
                {
                    "authenticated": True,
                    "used_quota": float(used or 0.0),
                    "total_quota": float(total or 0.0),
                }
            )
            if quota_exceeded:
                message = (
                    "检测到问卷星阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                    "建议启用随机 IP，但当前随机 IP 已用额度达到上限。\n"
                    "请先补充额度后再启用随机 IP。"
                )
                if gui_instance:
                    gui_instance.show_message_dialog("智能验证提示", message, level="warning")
                else:
                    log_popup_warning("智能验证提示", message)
                return

            message = (
                "检测到问卷星阿里云智能验证，为避免继续失败提交已停止所有任务。\n\n"
                "建议启用随机 IP 后重新启动任务。\n"
                "是否立即启用随机 IP 功能？"
            )
            if gui_instance:
                confirmed = bool(gui_instance.show_confirm_dialog("智能验证提示", message))
            else:
                confirmed = bool(log_popup_confirm("智能验证提示", message))

            if confirmed and gui_instance:
                try:
                    gui_instance.set_random_ip_enabled(True)
                    refresh_counter = getattr(gui_instance, "refresh_random_ip_counter", None)
                    if callable(refresh_counter):
                        refresh_counter()
                    logging.info("智能验证触发：用户已确认启用随机IP")
                except Exception:
                    logging.warning("自动启用随机IP失败", exc_info=True)
        except Exception:
            logging.warning("弹窗提示用户启用随机IP失败", exc_info=True)

    if gui_instance:
        try:
            gui_instance.dispatch_to_ui_async(_notify)
            return
        except Exception:
            logging.info("派发阿里云停止事件到主线程失败", exc_info=True)
    _notify()


def handle_submission_verification_detected(
    ctx: TaskContext,
    gui_instance: Optional[Any],
    stop_signal: Optional[threading.Event],
) -> None:
    """统一处理问卷星提交后命中阿里云智能验证后的策略。"""
    if bool(getattr(ctx, "random_proxy_ip_enabled", False)):
        logging.warning("随机IP模式命中问卷星阿里云智能验证：按配置仅记录日志，不暂停、不弹窗。")
        return

    if not bool(getattr(ctx, "pause_on_aliyun_captcha", True)):
        logging.warning("检测到问卷星阿里云智能验证：pause_on_aliyun_captcha=False，仅记录告警。")
        return

    _trigger_aliyun_captcha_stop(ctx, gui_instance, stop_signal)


def consume_submission_success_signal(driver: BrowserDriver) -> bool:
    return consume_headless_httpx_submit_success(driver)


def is_device_quota_limit_page(driver: BrowserDriver) -> bool:
    return _is_device_quota_limit_page(driver)


__all__ = [
    "AliyunCaptchaBypassError",
    "_ALIYUN_CAPTCHA_DOM_IDS",
    "_click_submit_button",
    "_is_wjx_domain",
    "_looks_like_wjx_survey_url",
    "_normalize_url_for_compare",
    "_page_looks_like_wjx_questionnaire",
    "consume_submission_success_signal",
    "EmptySurveySubmissionError",
    "handle_submission_verification_detected",
    "is_device_quota_limit_page",
    "submission_requires_verification",
    "submission_validation_message",
    "submit",
    "wait_for_submission_verification",
]



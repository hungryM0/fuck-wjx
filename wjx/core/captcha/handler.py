"""验证码处理模块 - 阿里云智能验证检测"""
import logging
import threading
import time
from typing import Optional

from wjx.network.browser import By, BrowserDriver
from wjx.utils.logging.log_utils import log_popup_warning


class AliyunCaptchaBypassError(RuntimeError):
    """检测到阿里云智能验证（需要人工交互）时抛出，用于触发全局停止。"""


class EmptySurveySubmissionError(RuntimeError):
    """检测到问卷未添加题目导致无法提交时抛出，用于关闭当前实例并继续下一份。"""


# 阿里云验证码弹窗状态
_aliyun_captcha_popup_shown = False
_aliyun_captcha_popup_lock = threading.Lock()


def _show_aliyun_captcha_popup(message: str) -> None:
    """在首次检测到阿里云智能验证时弹窗提醒用户。"""
    global _aliyun_captcha_popup_shown
    with _aliyun_captcha_popup_lock:
        if _aliyun_captcha_popup_shown:
            return
        _aliyun_captcha_popup_shown = True
    try:
        log_popup_warning("智能验证提示", message)
    except Exception:
        logging.warning("弹窗提示阿里云智能验证失败", exc_info=True)


def reset_captcha_popup_state() -> None:
    """重置验证码弹窗状态"""
    global _aliyun_captcha_popup_shown
    with _aliyun_captcha_popup_lock:
        _aliyun_captcha_popup_shown = False


def handle_aliyun_captcha(
    driver: BrowserDriver,
    timeout: int = 3,
    stop_signal: Optional[threading.Event] = None,
    raise_on_detect: bool = True,
) -> bool:
    """检测是否出现阿里云智能验证。

    之前这里会尝试点击"智能验证/开始验证"等按钮做绕过；现在按需求改为：
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
            # 先去掉尾部分号，避免 return (...;) 产生 SyntaxError: Unexpected token ';'
            js = "return (" + js.rstrip(";") + ")"
        try:
            return bool(driver.execute_script(js))
        except Exception:
            return False

    def _verification_button_text_visible() -> bool:
        """检测页面/iframe 中是否出现可见的高置信验证文案。"""
        script = r"""
            (() => {
                const textPatterns = [
                    /请完成安全验证/,
                    /点击开始智能验证/,
                    /需要安全校验/,
                    /请重新提交/,
                    /人机验证/,
                    /滑动验证/,
                    /安全验证失败/
                ];
                const visible = (el, win) => {
                    if (!el || !win) return false;
                    const style = win.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const checkDoc = (doc) => {
                    const win = doc.defaultView;
                    if (!win) return false;
                    const nodes = doc.querySelectorAll('button, a, span, div, p');
                    for (const el of nodes) {
                        if (!visible(el, win)) continue;
                        const txt = (el.innerText || el.textContent || '').trim();
                        if (!txt) continue;
                        for (const p of textPatterns) {
                            if (p.test(txt)) return true;
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
                    'aliyunCaptcha-title',
                    'aliyunCaptcha-checkbox',
                    'aliyunCaptcha-checkbox-wrapper',
                    'aliyunCaptcha-checkbox-body',
                    'aliyunCaptcha-checkbox-icon',
                    'aliyunCaptcha-checkbox-left',
                    'aliyunCaptcha-checkbox-text',
                    'aliyunCaptcha-loading',
                    'aliyunCaptcha-certifyId'
                ];
                const visible = (el, win) => {
                    if (!el || !win) return false;
                    const style = win.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };
                const checkDoc = (doc) => {
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
                        if (doc && checkDoc(doc)) return true;
                    } catch (e) {}
                }
                return false;
            })();
        """
        return _probe_with_js(script)

    def _wait_for_challenge() -> bool:
        end_time = time.time() + max(timeout, 3)
        weak_text_hits = 0
        while time.time() < end_time:
            if stop_signal and stop_signal.is_set():
                return False
            if _challenge_visible() or _element_exists():
                return True
            if _verification_button_text_visible():
                weak_text_hits += 1
                if weak_text_hits >= 2:
                    return True
            else:
                weak_text_hits = 0
            time.sleep(0.15)
        if _challenge_visible() or _element_exists():
            return True
        return bool(weak_text_hits >= 2 and _verification_button_text_visible())

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

    challenge_detected = _wait_for_challenge()
    if not challenge_detected:
        logging.debug("未检测到阿里云智能验证弹窗")
        return False
    if stop_signal and stop_signal.is_set():
        return False

    logging.warning("检测到阿里云智能验证（按钮/弹窗）。")
    _show_aliyun_captcha_popup("检测到阿里云智能验证，已暂停本次提交。如需继续，请更换/随机 IP 后重试。")
    if raise_on_detect:
        raise AliyunCaptchaBypassError("检测到阿里云智能验证，按配置直接放弃")
    return True


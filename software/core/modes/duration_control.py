"""答题时长控制 - 模拟真实答题时间分布"""
import logging
import random
import threading
import time
from typing import Any, Optional, Tuple

from software.network.proxy.policy.source import _map_answer_seconds_to_proxy_minute
from software.logging.log_utils import log_suppressed_exception

_COMPLETION_MARKERS = (
    "答卷已经提交",
    "感谢您的参与",
    "问卷提交成功",
    "提交成功",
    "已完成本次问卷",
    "已完成本次答卷",
    "感谢您的宝贵时间",
    "问卷已结束",
)





def simulate_answer_duration_delay(
    stop_signal: Optional[threading.Event] = None,
    answer_duration_range_seconds: Tuple[int, int] = (0, 0),
) -> bool:
    """在提交前模拟答题时长等待；返回 True 表示等待中被中断。"""

    # 保留原始配置值，用于推导随机 IP 分钟档
    raw_min, raw_max = answer_duration_range_seconds

    # 先规范化到非负、且 max >= min
    min_delay = max(0, int(raw_min))
    max_delay = max(min_delay, int(raw_max))
    if max_delay <= 0:
        return False

    # 如果界面只给了一个时间（min == max），在内部静默扩一段区间用于抖动
    if min_delay == max_delay:
        base = max_delay  # UI 里看到的那个目标秒数
        # 抖动幅度：±20%，但至少 ±5 秒，避免区间太窄看起来太机械
        jitter = max(5, int(base * 0.2))
        min_delay = max(0, base - jitter)
        max_delay = base + jitter

    # 用原始配置的最大秒数推导随机 IP 的分钟档位（1/3/5/10/15/30 分），作为硬上限参考
    proxy_ref_seconds = max(0, int(max(raw_min, raw_max)))
    try:
        ip_minute = _map_answer_seconds_to_proxy_minute(proxy_ref_seconds)
    except Exception:
        ip_minute = 0

    safe_upper = max_delay
    if ip_minute > 0:
        ip_limit_seconds = int(ip_minute) * 60
        # 留 1 秒安全边界，避免等到刚好用满随机 IP 时长
        safe_upper = min(max_delay, max(min_delay, ip_limit_seconds - 1))

    # 使用正态分布使时间更集中在中心值附近
    center = (min_delay + safe_upper) / 2.0
    # 标准差设为范围的 1/6，这样约 95% 的值会落在 [min_delay, safe_upper] 之间
    std_dev = (safe_upper - min_delay) / 6.0 if safe_upper > min_delay else 0.0

    # 生成正态分布的随机值，并限制在 [min_delay, safe_upper] 范围内
    if std_dev > 0:
        wait_seconds = random.gauss(center, std_dev)
    else:
        # 区间退化时，就不抖动，直接用下限
        wait_seconds = float(min_delay)

    wait_seconds = max(min_delay, min(safe_upper, wait_seconds))

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


def is_survey_completion_page(driver: Any, provider: Optional[str] = None) -> bool:
    """尝试检测当前页面是否为问卷提交完成页。"""
    try:
        current_url = str(getattr(driver, "current_url", "") or "")
        if "complete" in current_url.lower():
            return True
    except Exception as exc:
        log_suppressed_exception("is_survey_completion_page: current_url", exc, level=logging.WARNING)

    try:
        from software.providers.registry import is_completion_page as _provider_is_completion_page

        if _provider_is_completion_page(driver, provider=provider):
            return True
    except Exception as exc:
        log_suppressed_exception("is_survey_completion_page: provider_is_completion_page", exc, level=logging.WARNING)

    detected = False
    try:
        divdsc = None
        try:
            divdsc = driver.find_element("id", "divdsc")
        except Exception:
            divdsc = None
        if divdsc and getattr(divdsc, "is_displayed", lambda: True)():
            text = getattr(divdsc, "text", "") or ""
            if any(marker in text for marker in _COMPLETION_MARKERS):
                detected = True
    except Exception as exc:
        log_suppressed_exception("is_survey_completion_page: divdsc = None", exc, level=logging.WARNING)
    if not detected:
        try:
            page_text = driver.execute_script("return document.body.innerText || '';") or ""
            has_marker = any(marker in page_text for marker in _COMPLETION_MARKERS)
            if has_marker:
                action_visible = bool(
                    driver.execute_script(
                        r"""
                        return (() => {
                            const selectors = [
                                '#submit_button',
                                '#divSubmit',
                                '#ctlNext',
                                '#divNext',
                                '#btnNext',
                                '#SM_BTN_1',
                                '#SubmitBtnGroup .submitbtn',
                                '.btn-next',
                                '.btn-submit',
                                '.page-control button',
                                'button[type="submit"]',
                                'a.button.mainBgColor'
                            ];
                            const visible = (el) => {
                                if (!el) return false;
                                const style = window.getComputedStyle(el);
                                if (!style) return false;
                                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                                const rect = el.getBoundingClientRect();
                                return rect.width > 0 && rect.height > 0;
                            };
                            for (const sel of selectors) {
                                const nodes = document.querySelectorAll(sel);
                                for (const node of nodes) {
                                    if (visible(node)) return true;
                                }
                            }
                            return false;
                        })();
                        """
                    )
                )
                detected = not action_visible
        except Exception as exc:
            log_suppressed_exception("is_survey_completion_page: page_text = driver.execute_script(\"return document.body.innerText || '';\") or \"\"", exc, level=logging.WARNING)
    return bool(detected)




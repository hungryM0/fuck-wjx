from __future__ import annotations

import logging
import time
import re
from dataclasses import dataclass
from typing import Callable, Optional

from wjx.browser_driver import BrowserDriver

DEFAULT_REFRESH_INTERVAL = 0.5
_MIN_REFRESH_INTERVAL = 0.2
_MAX_REFRESH_INTERVAL = 10.0
_LOG_INTERVAL_SECONDS = 10.0

_NOT_STARTED_KEYWORDS = (
    "未开始",
    "尚未开始",
    "未到开始时间",
    "还未开始",
    "未开放",
    "开放时间",
    "开始时间",
    "将于",
    "距离开始",
    "倒计时",
    "start in",
    "countdown",
)
_ENDED_KEYWORDS = (
    "已结束",
    "结束填写",
    "停止填写",
    "暂停填写",
    "已关闭",
    "已暂停",
    "本次答题已结束",
)


@dataclass
class TimedModeState:
    enabled: bool = False
    refresh_interval: float = DEFAULT_REFRESH_INTERVAL


def _extract_body_text(driver: BrowserDriver) -> str:
    try:
        return driver.execute_script("return (document.body && document.body.innerText) || '';") or ""
    except Exception:
        return ""


def _normalize_interval(value: float) -> float:
    try:
        interval = float(value)
    except Exception:
        interval = DEFAULT_REFRESH_INTERVAL
    if interval <= 0:
        interval = DEFAULT_REFRESH_INTERVAL
    return max(_MIN_REFRESH_INTERVAL, min(interval, _MAX_REFRESH_INTERVAL))


def _parse_countdown_seconds(normalized_text: str) -> Optional[float]:
    """
    从“距离开始还有X天Y时Z分W秒”文案中提取剩余秒数。
    返回 None 表示未检测到倒计时。
    """
    if not normalized_text:
        return None
    match = re.search(r"距离开始还有(?:(\d+)天)?(?:(\d+)时)?(?:(\d+)分)?(?:(\d+)秒)?", normalized_text)
    if not match:
        return None
    days = int(match.group(1) or 0)
    hours = int(match.group(2) or 0)
    minutes = int(match.group(3) or 0)
    seconds = int(match.group(4) or 0)
    total = days * 86400 + hours * 3600 + minutes * 60 + seconds
    return float(total)


def _page_status(driver: BrowserDriver) -> tuple[bool, bool, bool, str]:
    """
    返回 (ready, not_started, ended, normalized_text)
    - ready: 页面已有题目/提交按钮可填写
    - not_started: 检测到未开始/未开放提示
    - ended: 检测到结束/暂停提示
    """
    ready = False
    try:
        ready = bool(
            driver.execute_script(
                """
                return (() => {
                    const hasQuestionBlock = !!document.querySelector('#divQuestion fieldset, #divQuestion [topic]');
                    const hasInputs = !!document.querySelector('#divQuestion input, #divQuestion textarea, #divQuestion select');
                    const hasSubmit = !!document.querySelector('#submit_button, #divSubmit, #ctlNext, #SM_BTN_1, .submitDiv a');
                    const hasStartBtn = !!document.querySelector(
                        '#starttime, #ctlNext, #startbnt, #btstart, #SM_BTN_1, .startbtn, .btn-start, button[id*=\"start\" i], a[id*=\"start\" i]'
                    );
                    return hasQuestionBlock || hasInputs || hasSubmit || hasStartBtn;
                })();
                """
            )
        )
    except Exception:
        ready = False

    text = _extract_body_text(driver)
    normalized = "".join(text.split())
    lowered = normalized.lower()
    not_started = any(keyword in normalized for keyword in _NOT_STARTED_KEYWORDS)
    ended = any(keyword in normalized for keyword in _ENDED_KEYWORDS)

    if not not_started:
        patterns = (
            r"将于\d{4}[-/年]\d{1,2}[-/月]\d{1,2}.*开放",
            r"将于\d{1,2}[:点]\d{1,2}开放",
            r"距离开始还有",
        )
        for pat in patterns:
            if re.search(pat, normalized):
                not_started = True
                break

    # 某些提示仅有英文，简单兜底
    if "notstart" in lowered or "not start" in lowered:
        not_started = True
    if "finished" in lowered or "closed" in lowered:
        ended = True

    if not_started or ended:
        ready = False

    return ready, not_started, ended, normalized


def wait_until_open(
    driver: BrowserDriver,
    url: str,
    stop_signal: Optional[object] = None,
    *,
    refresh_interval: float = DEFAULT_REFRESH_INTERVAL,
    logger: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    在同一浏览器实例中持续刷新，直到问卷开放或停止信号触发。

    返回 True 表示检测到问卷已开放；False 表示收到停止信号或页面提示已关闭。
    """
    interval = _normalize_interval(refresh_interval)
    first_load = True
    last_reason = ""
    last_log_ts = 0.0

    def _log(message: str) -> None:
        if logger:
            try:
                logger(message)
            except Exception:
                logging.debug("Timed mode logger failed", exc_info=True)

    while True:
        if stop_signal is not None and getattr(stop_signal, "is_set", lambda: False)():
            return False

        try:
            if first_load:
                driver.get(url)
                first_load = False
            else:
                driver.refresh()
        except Exception as exc:  # pragma: no cover - 容错
            _log(f"[Timed Mode] 刷新失败，将继续重试：{exc}")

        ready, not_started, ended, normalized_text = _page_status(driver)
        countdown_seconds = _parse_countdown_seconds(normalized_text)
        if countdown_seconds is not None:
            # 倒计时阶段加速刷新，越接近开放刷新越快
            if countdown_seconds <= 1.0:
                interval = _MIN_REFRESH_INTERVAL
            elif countdown_seconds <= 5.0:
                interval = max(_MIN_REFRESH_INTERVAL, min(interval, 0.3))

        if ready:
            _log("[Timed Mode] 检测到问卷已开放，开始填写...")
            return True

        if ended:
            _log("[Timed Mode] 页面提示问卷已结束/关闭，停止等待。")
            return False

        reason = ""
        if not_started:
            reason = "检测到“未开始/未开放”提示，继续快速刷新等待..."
        elif normalized_text:
            reason = "尚未开放，继续刷新等待..."
        now = time.time()
        if countdown_seconds is not None and countdown_seconds <= 1.0:
            reason = f"检测到倒计时 <= {countdown_seconds:.1f}s，正快速刷新..."

        if reason and (reason != last_reason or now - last_log_ts >= _LOG_INTERVAL_SECONDS):
            _log(f"[Timed Mode] {reason}")
            last_reason = reason
            last_log_ts = now

        # 倒计时刚结束，直接再刷一次，不做额外等待
        if countdown_seconds is not None and countdown_seconds <= 0.0:
            continue

        if stop_signal is not None and getattr(stop_signal, "wait", lambda *_: False)(interval):
            return False


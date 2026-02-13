"""答题时长控制 - 模拟真实答题时间分布"""
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, List, Optional, Tuple
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception


from wjx.utils.app.config import DURATION_CONTROL_JITTER, DURATION_CONTROL_MIN_DELAY_SECONDS

DURATION_CONTROL_MIN_QUESTION_SECONDS = 3.0


@dataclass
class DurationControlState:
    enabled: bool = False
    estimated_seconds: int = 0
    total_duration_seconds: int = 0
    schedule: Deque[float] = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def active(self) -> bool:
        return bool(self.enabled and self.estimated_seconds > 0)

    def reset_runtime(self) -> None:
        with self._lock:
            try:
                self.schedule.clear()
            except Exception:
                self.schedule = deque()

    def prepare_schedule(self, run_count: int, total_duration_seconds: int) -> Deque[float]:
        schedule: Deque[float] = deque()
        if run_count <= 0:
            with self._lock:
                self.schedule = schedule
            return schedule

        now = time.time()
        total_span = max(0, int(total_duration_seconds))

        if total_span <= 0:
            for idx in range(run_count):
                schedule.append(now + idx * 5)
            with self._lock:
                self.schedule = schedule
            return schedule

        base_interval = total_span / max(1, run_count)
        jitter_window = base_interval * 0.6
        offsets: List[float] = []
        for index in range(run_count):
            ideal = index * base_interval
            jitter = random.uniform(-jitter_window, jitter_window) if jitter_window > 0 else 0.0
            offset = max(0.0, min(total_span * 0.98, ideal + jitter))
            offsets.append(offset)
        offsets.sort()
        for offset in offsets:
            schedule.append(now + offset)

        with self._lock:
            self.schedule = schedule
        return schedule

    def wait_for_next_slot(self, stop_signal: threading.Event) -> bool:
        with self._lock:
            if not self.schedule:
                return False
            next_slot = self.schedule.popleft()

        while True:
            if stop_signal.is_set():
                return False
            delay = next_slot - time.time()
            if delay <= 0:
                break
            wait_time = min(delay, 1.0)
            if wait_time <= 0:
                break
            if stop_signal.wait(wait_time):
                return False
        return True

    def calculate_run_target(self, question_count: int) -> float:
        per_question_cfg = 0.0
        if self.estimated_seconds > 0 and question_count > 0:
            per_question_cfg = float(self.estimated_seconds) / max(1, question_count)
        per_question_target = max(DURATION_CONTROL_MIN_QUESTION_SECONDS, per_question_cfg)
        base = max(5.0, per_question_target * max(1, question_count))
        jitter = max(0.05, min(0.5, float(DURATION_CONTROL_JITTER)))
        upper = max(base + per_question_target * 0.5, base * (1 + jitter))
        return random.uniform(base, upper)

    def build_per_question_delay_plan(self, question_count: int, target_seconds: float) -> List[float]:
        if question_count <= 0 or target_seconds <= 0:
            return []
        avg_delay = target_seconds / max(1, question_count)
        min_delay = max(DURATION_CONTROL_MIN_DELAY_SECONDS, avg_delay * 0.8, DURATION_CONTROL_MIN_QUESTION_SECONDS)
        max_possible_min = target_seconds / max(1, question_count)
        if min_delay > max_possible_min:
            min_delay = max(DURATION_CONTROL_MIN_DELAY_SECONDS * 0.2, max_possible_min)
        min_delay = max(0.02, min_delay)
        baseline_total = min_delay * question_count
        remaining = max(0.0, target_seconds - baseline_total)
        if remaining <= 0:
            return [target_seconds / max(1, question_count)] * question_count
        weights = [random.uniform(0.3, 1.2) for _ in range(question_count)]
        total_weight = sum(weights) or 1.0
        extras = [remaining * (w / total_weight) for w in weights]
        return [min_delay + extra for extra in extras]


DURATION_CONTROL_STATE = DurationControlState()


def simulate_answer_duration_delay(
    stop_signal: Optional[threading.Event] = None,
    answer_duration_range_seconds: Tuple[int, int] = (0, 0),
) -> bool:
    """在提交前模拟答题时长等待；返回 True 表示等待中被中断。"""


    min_delay, max_delay = answer_duration_range_seconds
    min_delay = max(0, min_delay)
    max_delay = max(min_delay, max(0, max_delay))
    if max_delay <= 0:
        return False
    
    # 使用正态分布使时间更集中在中心值附近
    center = (min_delay + max_delay) / 2.0
    # 标准差设为范围的1/6，这样约95%的值会落在min和max之间
    std_dev = (max_delay - min_delay) / 6.0
    
    # 生成正态分布的随机值，并限制在min和max范围内
    wait_seconds = random.gauss(center, std_dev)
    wait_seconds = max(min_delay, min(max_delay, wait_seconds))
    
    if wait_seconds <= 0:
        return False
    logging.debug("[Action Log] Simulating answer duration: waiting %.1f seconds before submit", wait_seconds)
    if stop_signal:
        interrupted = stop_signal.wait(wait_seconds)
        return bool(interrupted and stop_signal.is_set())
    time.sleep(wait_seconds)
    return False


def is_survey_completion_page(driver: Any) -> bool:
    """尝试检测当前页面是否为问卷提交完成页。"""
    detected = False
    try:
        divdsc = None
        try:
            divdsc = driver.find_element("id", "divdsc")
        except Exception:
            divdsc = None
        if divdsc and getattr(divdsc, "is_displayed", lambda: True)():
            text = getattr(divdsc, "text", "") or ""
            if "答卷已经提交" in text or "感谢您的参与" in text:
                detected = True
    except Exception as exc:
        log_suppressed_exception("is_survey_completion_page: divdsc = None", exc, level=logging.WARNING)
    if not detected:
        try:
            page_text = driver.execute_script("return document.body.innerText || '';") or ""
            if "答卷已经提交" in page_text or "感谢您的参与" in page_text:
                detected = True
        except Exception as exc:
            log_suppressed_exception("is_survey_completion_page: page_text = driver.execute_script(\"return document.body.innerText || '';\") or \"\"", exc, level=logging.WARNING)
    return bool(detected)

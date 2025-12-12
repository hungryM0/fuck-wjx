import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List

from config import FULL_SIM_DURATION_JITTER, FULL_SIM_MIN_DELAY_SECONDS


FULL_SIM_MIN_QUESTION_SECONDS = 3.0


@dataclass
class FullSimulationState:
    enabled: bool = False
    estimated_seconds: int = 0
    total_duration_seconds: int = 0
    schedule: Deque[float] = field(default_factory=deque)
    end_timestamp: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def active(self) -> bool:
        return bool(self.enabled and self.estimated_seconds > 0)

    def reset_runtime(self) -> None:
        with self._lock:
            try:
                self.schedule.clear()
            except Exception:
                self.schedule = deque()
            self.end_timestamp = 0.0

    def disable(self) -> None:
        with self._lock:
            self.enabled = False
            self.estimated_seconds = 0
            self.total_duration_seconds = 0
        self.reset_runtime()

    def prepare_schedule(self, run_count: int, total_duration_seconds: int) -> Deque[float]:
        schedule: Deque[float] = deque()
        if run_count <= 0:
            with self._lock:
                self.schedule = schedule
                self.end_timestamp = 0.0
            return schedule

        now = time.time()
        total_span = max(0, int(total_duration_seconds))

        if total_span <= 0:
            for idx in range(run_count):
                schedule.append(now + idx * 5)
            end_ts = now + run_count * 5
            with self._lock:
                self.schedule = schedule
                self.end_timestamp = end_ts
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

        end_ts = now + total_span
        with self._lock:
            self.schedule = schedule
            self.end_timestamp = end_ts
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
        per_question_target = max(FULL_SIM_MIN_QUESTION_SECONDS, per_question_cfg)
        base = max(5.0, per_question_target * max(1, question_count))
        jitter = max(0.05, min(0.5, float(FULL_SIM_DURATION_JITTER)))
        upper = max(base + per_question_target * 0.5, base * (1 + jitter))
        return random.uniform(base, upper)

    def build_per_question_delay_plan(self, question_count: int, target_seconds: float) -> List[float]:
        if question_count <= 0 or target_seconds <= 0:
            return []
        avg_delay = target_seconds / max(1, question_count)
        min_delay = max(FULL_SIM_MIN_DELAY_SECONDS, avg_delay * 0.8, FULL_SIM_MIN_QUESTION_SECONDS)
        max_possible_min = target_seconds / max(1, question_count)
        if min_delay > max_possible_min:
            min_delay = max(FULL_SIM_MIN_DELAY_SECONDS * 0.2, max_possible_min)
        min_delay = max(0.02, min_delay)
        baseline_total = min_delay * question_count
        remaining = max(0.0, target_seconds - baseline_total)
        if remaining <= 0:
            return [target_seconds / max(1, question_count)] * question_count
        weights = [random.uniform(0.3, 1.2) for _ in range(question_count)]
        total_weight = sum(weights) or 1.0
        extras = [remaining * (w / total_weight) for w in weights]
        return [min_delay + extra for extra in extras]


FULL_SIM_STATE = FullSimulationState()

"""任务上下文 - 单次提交任务的完整配置与运行时状态。

替代散落在 state.py 中的模块级全局变量，每次 start_run() 时
由 RunController 构造一个新实例，并作为参数透传给引擎和辅助模块，
彻底消除全局状态带来的线程安全盲区与单例限制。
"""
from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from software.core.questions.reliability_mode import DEFAULT_RELIABILITY_PRIORITY_MODE

# ---------------------------------------------------------------------------
# 答题内容配置（由 configure_probabilities 写入）
# ---------------------------------------------------------------------------

@dataclass
class ThreadProgressState:
    """单个工作线程的运行状态快照。"""

    thread_name: str
    thread_index: int = 0
    success_count: int = 0
    fail_count: int = 0
    step_current: int = 0
    step_total: int = 0
    status_text: str = "等待中"
    running: bool = False
    last_update_ts: float = 0.0


@dataclass
class ProxyLease:
    """代理租约对象，保存地址与过期时间信息。"""

    address: str = ""
    expire_at: str = ""
    expire_ts: float = 0.0
    poolable: bool = True
    source: str = ""


@dataclass
class TaskContext:
    """一次刷问卷任务的完整上下文。

    分为两大部分：
    - 静态配置：任务开始前由 RunController._prepare_engine_state 一次性写入。
    - 运行时状态：引擎运行期间动态更新（cur_num / cur_fail 等），
                  通过 lock 保护并发访问。
    """

    # ── 问卷基本信息 ──────────────────────────────────────────────────────
    url: str = ""
    survey_title: str = ""
    survey_provider: str = "wjx"

    # ── 答题内容概率配置（由 configure_probabilities 写入） ───────────────
    single_prob: List[Union[List[float], int, float, None]] = field(default_factory=list)
    droplist_prob: List[Union[List[float], int, float, None]] = field(default_factory=list)
    multiple_prob: List[List[float]] = field(default_factory=list)
    matrix_prob: List[Union[List[float], int, float, None]] = field(default_factory=list)
    scale_prob: List[Union[List[float], int, float, None]] = field(default_factory=list)
    slider_targets: List[float] = field(default_factory=list)
    texts: List[List[str]] = field(default_factory=list)
    texts_prob: List[List[float]] = field(default_factory=list)
    text_entry_types: List[str] = field(default_factory=list)
    text_ai_flags: List[bool] = field(default_factory=list)
    text_titles: List[str] = field(default_factory=list)
    multi_text_blank_modes: List[List[str]] = field(default_factory=list)
    multi_text_blank_ai_flags: List[List[bool]] = field(default_factory=list)
    multi_text_blank_int_ranges: List[List[List[int]]] = field(default_factory=list)
    single_option_fill_texts: List[Optional[List[Optional[str]]]] = field(default_factory=list)
    single_attached_option_selects: List[List[Dict[str, Any]]] = field(default_factory=list)
    droplist_option_fill_texts: List[Optional[List[Optional[str]]]] = field(default_factory=list)
    multiple_option_fill_texts: List[Optional[List[Optional[str]]]] = field(default_factory=list)
    answer_rules: List[Dict[str, Any]] = field(default_factory=list)

    # 题号 → (配置题型, 在对应类型概率列表中的起始索引)
    question_config_index_map: Dict[int, Tuple[str, int]] = field(default_factory=dict)

    # 题号 → 运行时信度维度（None 表示不参与；整卷未分组时可回退到全局维度）
    question_dimension_map: Dict[int, Optional[str]] = field(default_factory=dict)

    # 题号 → 是否为严格自定义比例题（手动配比绝对优先）
    question_strict_ratio_map: Dict[int, bool] = field(default_factory=dict)

    # 题号 → 倾向预设（scale/score 为 str；matrix 为 List[str]，每行一个）
    question_psycho_bias_map: Dict[int, Any] = field(default_factory=dict)

    # 题目元数据（从 HTML 解析得到）：题号 → 题目信息字典
    questions_metadata: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    # 心理测量计划目标 Alpha（0.70-0.95）
    psycho_target_alpha: float = 0.9
    reliability_priority_mode: str = DEFAULT_RELIABILITY_PRIORITY_MODE

    # ── 并发 / 浏览器配置 ─────────────────────────────────────────────────
    headless_mode: bool = False
    browser_preference: List[str] = field(default_factory=list)
    num_threads: int = 1
    target_num: int = 1
    fail_threshold: int = 5
    stop_on_fail_enabled: bool = True

    # ── 时间 / 节奏配置 ───────────────────────────────────────────────────
    submit_interval_range_seconds: Tuple[int, int] = (0, 0)
    answer_duration_range_seconds: Tuple[int, int] = (0, 0)

    # ── 定时模式 ──────────────────────────────────────────────────────────
    timed_mode_enabled: bool = False
    timed_mode_refresh_interval: float = 0.5  # DEFAULT_REFRESH_INTERVAL

    # ── 代理 / UA 配置 ────────────────────────────────────────────────────
    random_proxy_ip_enabled: bool = False
    proxy_ip_pool: List[ProxyLease] = field(default_factory=list)
    random_user_agent_enabled: bool = False
    user_agent_ratios: Dict[str, int] = field(
        default_factory=lambda: {"wechat": 33, "mobile": 33, "pc": 34}
    )
    pause_on_aliyun_captcha: bool = True
    proxy_waiting_threads: int = 0
    proxy_in_use_by_thread: Dict[str, ProxyLease] = field(default_factory=dict)

    # ── 运行时计数（引擎动态更新，需加锁！） ─────────────────────────────
    cur_num: int = 0
    cur_fail: int = 0  # 全线程共享的连续失败计数，成功提交后归零
    device_quota_fail_count: int = 0
    thread_progress: Dict[str, ThreadProgressState] = field(default_factory=dict)
    distribution_runtime_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    distribution_pending_by_thread: Dict[str, List[Tuple[str, int, int]]] = field(default_factory=dict)

    # ── 停止控制 ──────────────────────────────────────────────────────────
    stop_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)

    # ── 验证码相关标志 ────────────────────────────────────────────────────
    _aliyun_captcha_stop_triggered: bool = False
    _aliyun_captcha_stop_lock: threading.Lock = field(default_factory=threading.Lock)
    _aliyun_captcha_popup_shown: bool = False
    _target_reached_stop_triggered: bool = False
    _target_reached_stop_lock: threading.Lock = field(default_factory=threading.Lock)

    _proxy_fetch_lock: threading.Lock = field(default_factory=threading.Lock)

    # ── 浏览器信号量（私有，通过 get_browser_semaphore 访问） ────────────
    _browser_semaphore: Optional[threading.Semaphore] = field(default=None, repr=False)
    _browser_semaphore_lock: threading.Lock = field(default_factory=threading.Lock)
    _browser_semaphore_max_instances: int = 0

    def get_browser_semaphore(self, max_instances: int) -> threading.Semaphore:
        """获取或创建浏览器实例信号量，限制同时运行的浏览器数量。"""
        normalized = max(1, int(max_instances or 1))
        with self._browser_semaphore_lock:
            if (
                self._browser_semaphore is None
                or self._browser_semaphore_max_instances != normalized
            ):
                self._browser_semaphore = threading.Semaphore(normalized)
                self._browser_semaphore_max_instances = normalized
            return self._browser_semaphore

    @staticmethod
    def _resolve_thread_index(thread_name: str) -> int:
        text = str(thread_name or "").strip()
        if not text:
            return 0
        if text.startswith("Worker-"):
            suffix = text.split("-", 1)[1].strip()
            try:
                value = int(suffix)
                return value if value > 0 else 0
            except Exception:
                return 0
        tail = []
        for ch in reversed(text):
            if ch.isdigit():
                tail.append(ch)
            else:
                break
        if not tail:
            return 0
        try:
            return int("".join(reversed(tail)))
        except Exception:
            return 0

    @staticmethod
    def _format_thread_display_name(thread_name: str, thread_index: int) -> str:
        if thread_index > 0:
            return f"线程 {thread_index}"
        text = str(thread_name or "").strip()
        if text.startswith("Worker-?"):
            return "线程 ?"
        return text or "线程 ?"

    def _get_or_create_thread_state_locked(self, thread_name: str) -> ThreadProgressState:
        key = str(thread_name or "").strip() or "Worker-?"
        state = self.thread_progress.get(key)
        if state is not None:
            return state
        state = ThreadProgressState(
            thread_name=key,
            thread_index=self._resolve_thread_index(key),
            last_update_ts=time.time(),
        )
        self.thread_progress[key] = state
        return state

    def ensure_worker_threads(self, expected_count: int) -> None:
        """预创建 Worker-1..N 的进度行，便于 UI 提前渲染。"""
        count = max(1, int(expected_count or 1))
        now = time.time()
        with self.lock:
            for idx in range(1, count + 1):
                name = f"Worker-{idx}"
                state = self.thread_progress.get(name)
                if state is None:
                    self.thread_progress[name] = ThreadProgressState(
                        thread_name=name,
                        thread_index=idx,
                        last_update_ts=now,
                    )
                else:
                    state.thread_index = idx
                    state.last_update_ts = now

    def register_proxy_waiter(self) -> None:
        with self.lock:
            self.proxy_waiting_threads = max(0, int(self.proxy_waiting_threads or 0)) + 1

    def unregister_proxy_waiter(self) -> None:
        with self.lock:
            self.proxy_waiting_threads = max(0, int(self.proxy_waiting_threads or 0) - 1)

    def get_proxy_waiter_count(self) -> int:
        with self.lock:
            return max(0, int(self.proxy_waiting_threads or 0))

    def mark_proxy_in_use(self, thread_name: str, lease: ProxyLease) -> None:
        key = str(thread_name or "").strip()
        if not key or not isinstance(lease, ProxyLease):
            return
        with self.lock:
            self.proxy_in_use_by_thread[key] = lease

    def release_proxy_in_use(self, thread_name: str) -> Optional[ProxyLease]:
        key = str(thread_name or "").strip()
        if not key:
            return None
        with self.lock:
            return self.proxy_in_use_by_thread.pop(key, None)

    def get_proxy_in_use_count(self) -> int:
        with self.lock:
            return len(self.proxy_in_use_by_thread)

    def update_thread_status(
        self,
        thread_name: str,
        status_text: str,
        *,
        running: Optional[bool] = None,
    ) -> None:
        now = time.time()
        with self.lock:
            state = self._get_or_create_thread_state_locked(thread_name)
            state.status_text = str(status_text or "")
            if running is not None:
                state.running = bool(running)
            state.last_update_ts = now

    def update_thread_step(
        self,
        thread_name: str,
        step_current: int,
        step_total: int,
        *,
        status_text: Optional[str] = None,
        running: Optional[bool] = None,
    ) -> None:
        now = time.time()
        current = max(0, int(step_current or 0))
        total = max(0, int(step_total or 0))
        if total > 0:
            current = min(current, total)
        with self.lock:
            state = self._get_or_create_thread_state_locked(thread_name)
            state.step_current = current
            state.step_total = total
            if status_text is not None:
                state.status_text = str(status_text or "")
            if running is not None:
                state.running = bool(running)
            state.last_update_ts = now

    def increment_thread_success(self, thread_name: str, *, status_text: str = "提交成功") -> None:
        now = time.time()
        with self.lock:
            state = self._get_or_create_thread_state_locked(thread_name)
            state.success_count += 1
            if state.step_total > 0:
                state.step_current = state.step_total
            state.status_text = str(status_text or "提交成功")
            state.running = True
            state.last_update_ts = now

    def increment_thread_fail(self, thread_name: str, *, status_text: str = "失败重试") -> None:
        now = time.time()
        with self.lock:
            state = self._get_or_create_thread_state_locked(thread_name)
            state.fail_count += 1
            state.status_text = str(status_text or "失败重试")
            state.running = True
            state.last_update_ts = now

    def mark_thread_finished(self, thread_name: str, *, status_text: str = "已停止") -> None:
        now = time.time()
        with self.lock:
            state = self._get_or_create_thread_state_locked(thread_name)
            state.running = False
            state.status_text = str(status_text or "已停止")
            state.last_update_ts = now

    @staticmethod
    def _normalize_distribution_counts(raw_counts: Any, option_count: int) -> List[int]:
        count = max(0, int(option_count or 0))
        normalized = [0] * count
        if not isinstance(raw_counts, list):
            return normalized
        for idx in range(min(len(raw_counts), count)):
            try:
                normalized[idx] = max(0, int(raw_counts[idx] or 0))
            except Exception:
                normalized[idx] = 0
        return normalized

    def snapshot_distribution_stats(self, stat_key: str, option_count: int) -> Tuple[int, List[int]]:
        with self.lock:
            bucket = self.distribution_runtime_stats.get(str(stat_key or "")) or {}
            total = max(0, int(bucket.get("total") or 0)) if isinstance(bucket, dict) else 0
            counts = self._normalize_distribution_counts(
                bucket.get("counts") if isinstance(bucket, dict) else None,
                option_count,
            )
        return total, counts

    def reset_pending_distribution(self, thread_name: Optional[str] = None) -> None:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        with self.lock:
            self.distribution_pending_by_thread[key] = []

    def append_pending_distribution_choice(
        self,
        stat_key: str,
        option_index: int,
        option_count: int,
        thread_name: Optional[str] = None,
    ) -> None:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        normalized_option_count = max(0, int(option_count or 0))
        normalized_option_index = int(option_index or 0)
        if normalized_option_count <= 0:
            return
        if normalized_option_index < 0 or normalized_option_index >= normalized_option_count:
            return
        item = (str(stat_key or ""), normalized_option_index, normalized_option_count)
        with self.lock:
            pending = self.distribution_pending_by_thread.setdefault(key, [])
            pending.append(item)

    def commit_pending_distribution(self, thread_name: Optional[str] = None) -> int:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        committed = 0
        with self.lock:
            pending = list(self.distribution_pending_by_thread.get(key) or [])
            self.distribution_pending_by_thread[key] = []
            for stat_key, option_index, option_count in pending:
                if option_count <= 0 or option_index < 0 or option_index >= option_count:
                    continue
                bucket = self.distribution_runtime_stats.get(stat_key) or {}
                total = max(0, int(bucket.get("total") or 0)) if isinstance(bucket, dict) else 0
                counts = self._normalize_distribution_counts(
                    bucket.get("counts") if isinstance(bucket, dict) else None,
                    option_count,
                )
                counts[option_index] += 1
                self.distribution_runtime_stats[stat_key] = {
                    "total": total + 1,
                    "counts": counts,
                }
                committed += 1
        return committed

    def snapshot_thread_progress(self) -> List[Dict[str, Any]]:
        """返回线程进度快照（用于 UI 刷新，已排序）。"""
        with self.lock:
            rows = []
            for state in self.thread_progress.values():
                total = max(0, int(state.step_total or 0))
                current = max(0, int(state.step_current or 0))
                if total > 0:
                    current = min(current, total)
                    step_percent = int(min(100, (current / float(total)) * 100))
                else:
                    step_percent = 0
                rows.append(
                    {
                        "thread_name": state.thread_name,
                        "thread_display_name": self._format_thread_display_name(
                            state.thread_name,
                            int(state.thread_index or 0),
                        ),
                        "thread_index": int(state.thread_index or 0),
                        "success_count": int(state.success_count or 0),
                        "fail_count": int(state.fail_count or 0),
                        "step_current": current,
                        "step_total": total,
                        "step_percent": step_percent,
                        "status_text": str(state.status_text or ""),
                        "running": bool(state.running),
                        "last_update_ts": float(state.last_update_ts or 0.0),
                    }
                )
        rows.sort(
            key=lambda item: (
                item["thread_index"] <= 0,
                item["thread_index"] if item["thread_index"] > 0 else 10**9,
                item["thread_name"],
            )
        )
        return rows

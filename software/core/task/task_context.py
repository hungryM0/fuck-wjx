"""任务模型 - 静态执行配置与运行态状态。"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol, Tuple, Union

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
class ExecutionConfig:
    """一次任务在启动前固定下来的静态执行配置。"""

    url: str = ""
    survey_title: str = ""
    survey_provider: str = "wjx"

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

    question_config_index_map: Dict[int, Tuple[str, int]] = field(default_factory=dict)
    question_dimension_map: Dict[int, Optional[str]] = field(default_factory=dict)
    question_strict_ratio_map: Dict[int, bool] = field(default_factory=dict)
    question_psycho_bias_map: Dict[int, Any] = field(default_factory=dict)
    questions_metadata: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    joint_psychometric_answer_plan: Optional[Any] = None

    psycho_target_alpha: float = 0.9

    headless_mode: bool = False
    browser_preference: List[str] = field(default_factory=list)
    num_threads: int = 1
    target_num: int = 1
    fail_threshold: int = 5
    stop_on_fail_enabled: bool = True

    submit_interval_range_seconds: Tuple[int, int] = (0, 0)
    answer_duration_range_seconds: Tuple[int, int] = (0, 0)

    timed_mode_enabled: bool = False
    timed_mode_refresh_interval: float = 0.5

    random_proxy_ip_enabled: bool = False
    proxy_ip_pool: List[ProxyLease] = field(default_factory=list)
    random_user_agent_enabled: bool = False
    user_agent_ratios: Dict[str, int] = field(
        default_factory=lambda: {"wechat": 33, "mobile": 33, "pc": 34}
    )
    pause_on_aliyun_captcha: bool = True


@dataclass
class ExecutionState:
    """一次任务运行中的动态状态。"""

    config: ExecutionConfig = field(default_factory=ExecutionConfig)

    cur_num: int = 0
    cur_fail: int = 0
    device_quota_fail_count: int = 0
    thread_progress: Dict[str, ThreadProgressState] = field(default_factory=dict)
    distribution_runtime_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    distribution_pending_by_thread: Dict[str, List[Tuple[str, int, int]]] = field(default_factory=dict)
    joint_reserved_sample_by_thread: Dict[str, int] = field(default_factory=dict)
    joint_committed_sample_indexes: set[int] = field(default_factory=set)

    proxy_waiting_threads: int = 0
    proxy_in_use_by_thread: Dict[str, ProxyLease] = field(default_factory=dict)

    stop_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)

    _aliyun_captcha_stop_triggered: bool = False
    _aliyun_captcha_stop_lock: threading.Lock = field(default_factory=threading.Lock)
    _aliyun_captcha_popup_shown: bool = False
    _target_reached_stop_triggered: bool = False
    _target_reached_stop_lock: threading.Lock = field(default_factory=threading.Lock)

    _proxy_fetch_lock: threading.Lock = field(default_factory=threading.Lock)
    _browser_semaphore: Optional[threading.Semaphore] = field(default=None, repr=False)
    _browser_semaphore_lock: threading.Lock = field(default_factory=threading.Lock)
    _browser_semaphore_max_instances: int = 0

    def __getattr__(self, name: str) -> Any:
        """只读透传静态配置，避免旧的内部消费者到处改一轮。"""
        config = object.__getattribute__(self, "config")
        if hasattr(config, name):
            return getattr(config, name)
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        """旧路径写入配置字段时，继续落到 ExecutionConfig，避免在运行态对象上制造同名脏属性。"""
        if name in _EXECUTION_STATE_FIELD_NAMES:
            object.__setattr__(self, name, value)
            return
        config = self.__dict__.get("config")
        if name in _EXECUTION_CONFIG_FIELD_NAMES and isinstance(config, ExecutionConfig):
            setattr(config, name, value)
            return
        object.__setattr__(self, name, value)

    def get_browser_semaphore(self, max_instances: int) -> threading.Semaphore:
        normalized = max(1, int(max_instances or 1))
        with self._browser_semaphore_lock:
            if self._browser_semaphore is None or self._browser_semaphore_max_instances != normalized:
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
            thread_state = self._get_or_create_thread_state_locked(thread_name)
            thread_state.step_current = current
            thread_state.step_total = total
            if status_text is not None:
                thread_state.status_text = str(status_text or "")
            if running is not None:
                thread_state.running = bool(running)
            thread_state.last_update_ts = now

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

    def peek_reserved_joint_sample(self, thread_name: Optional[str] = None) -> Optional[int]:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        with self.lock:
            reserved = self.joint_reserved_sample_by_thread.get(key)
            return int(reserved) if reserved is not None else None

    def reserve_joint_sample(self, sample_count: int, thread_name: Optional[str] = None) -> Optional[int]:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        total = max(0, int(sample_count or 0))
        if total <= 0:
            return None
        with self.lock:
            existing = self.joint_reserved_sample_by_thread.get(key)
            if existing is not None:
                return int(existing)
            reserved_values = set(self.joint_reserved_sample_by_thread.values())
            for sample_index in range(total):
                if sample_index in reserved_values or sample_index in self.joint_committed_sample_indexes:
                    continue
                self.joint_reserved_sample_by_thread[key] = sample_index
                return sample_index
        return None

    def release_joint_sample(self, thread_name: Optional[str] = None) -> Optional[int]:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        with self.lock:
            reserved = self.joint_reserved_sample_by_thread.pop(key, None)
            return int(reserved) if reserved is not None else None

    def commit_joint_sample(self, thread_name: Optional[str] = None) -> Optional[int]:
        key = str(thread_name or threading.current_thread().name or "Worker-?").strip() or "Worker-?"
        with self.lock:
            reserved = self.joint_reserved_sample_by_thread.pop(key, None)
            if reserved is None:
                return None
            self.joint_committed_sample_indexes.add(int(reserved))
            return int(reserved)

    def snapshot_thread_progress(self) -> List[Dict[str, Any]]:
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


_EXECUTION_CONFIG_FIELD_NAMES = frozenset(ExecutionConfig.__dataclass_fields__.keys())
_EXECUTION_STATE_FIELD_NAMES = frozenset(ExecutionState.__dataclass_fields__.keys())


if TYPE_CHECKING:
    class TaskContext(Protocol):
        """旧类型名的静态过渡协议，兼容仍按旧心智混用配置态与运行态的调用方。"""

        config: ExecutionConfig

        url: str
        survey_title: str
        survey_provider: str
        single_prob: List[Union[List[float], int, float, None]]
        droplist_prob: List[Union[List[float], int, float, None]]
        multiple_prob: List[List[float]]
        matrix_prob: List[Union[List[float], int, float, None]]
        scale_prob: List[Union[List[float], int, float, None]]
        slider_targets: List[float]
        texts: List[List[str]]
        texts_prob: List[List[float]]
        text_entry_types: List[str]
        text_ai_flags: List[bool]
        text_titles: List[str]
        multi_text_blank_modes: List[List[str]]
        multi_text_blank_ai_flags: List[List[bool]]
        multi_text_blank_int_ranges: List[List[List[int]]]
        single_option_fill_texts: List[Optional[List[Optional[str]]]]
        single_attached_option_selects: List[List[Dict[str, Any]]]
        droplist_option_fill_texts: List[Optional[List[Optional[str]]]]
        multiple_option_fill_texts: List[Optional[List[Optional[str]]]]
        answer_rules: List[Dict[str, Any]]
        question_config_index_map: Dict[int, Tuple[str, int]]
        question_dimension_map: Dict[int, Optional[str]]
        question_strict_ratio_map: Dict[int, bool]
        question_psycho_bias_map: Dict[int, Any]
        questions_metadata: Dict[int, Dict[str, Any]]
        joint_psychometric_answer_plan: Optional[Any]
        psycho_target_alpha: float
        headless_mode: bool
        browser_preference: List[str]
        num_threads: int
        target_num: int
        fail_threshold: int
        stop_on_fail_enabled: bool
        submit_interval_range_seconds: Tuple[int, int]
        answer_duration_range_seconds: Tuple[int, int]
        timed_mode_enabled: bool
        timed_mode_refresh_interval: float
        random_proxy_ip_enabled: bool
        proxy_ip_pool: List[ProxyLease]
        random_user_agent_enabled: bool
        user_agent_ratios: Dict[str, int]
        pause_on_aliyun_captcha: bool

        cur_num: int
        cur_fail: int
        device_quota_fail_count: int
        thread_progress: Dict[str, ThreadProgressState]
        distribution_runtime_stats: Dict[str, Dict[str, Any]]
        distribution_pending_by_thread: Dict[str, List[Tuple[str, int, int]]]
        joint_reserved_sample_by_thread: Dict[str, int]
        joint_committed_sample_indexes: set[int]
        proxy_waiting_threads: int
        proxy_in_use_by_thread: Dict[str, ProxyLease]
        stop_event: threading.Event
        lock: threading.Lock
        _aliyun_captcha_stop_triggered: bool
        _aliyun_captcha_stop_lock: threading.Lock
        _aliyun_captcha_popup_shown: bool
        _target_reached_stop_triggered: bool
        _target_reached_stop_lock: threading.Lock
        _proxy_fetch_lock: threading.Lock

        def get_browser_semaphore(self, max_instances: int) -> threading.Semaphore: ...
        def ensure_worker_threads(self, expected_count: int) -> None: ...
        def register_proxy_waiter(self) -> None: ...
        def unregister_proxy_waiter(self) -> None: ...
        def get_proxy_waiter_count(self) -> int: ...
        def mark_proxy_in_use(self, thread_name: str, lease: ProxyLease) -> None: ...
        def release_proxy_in_use(self, thread_name: str) -> Optional[ProxyLease]: ...
        def get_proxy_in_use_count(self) -> int: ...
        def update_thread_status(self, thread_name: str, status_text: str, *, running: Optional[bool] = None) -> None: ...
        def update_thread_step(
            self,
            thread_name: str,
            step_current: int,
            step_total: int,
            *,
            status_text: Optional[str] = None,
            running: Optional[bool] = None,
        ) -> None: ...
        def increment_thread_success(self, thread_name: str, *, status_text: str = "提交成功") -> None: ...
        def increment_thread_fail(self, thread_name: str, *, status_text: str = "失败重试") -> None: ...
        def mark_thread_finished(self, thread_name: str, *, status_text: str = "已停止") -> None: ...
        def snapshot_distribution_stats(self, stat_key: str, option_count: int) -> Tuple[int, List[int]]: ...
        def reset_pending_distribution(self, thread_name: Optional[str] = None) -> None: ...
        def append_pending_distribution_choice(
            self,
            stat_key: str,
            option_index: int,
            option_count: int,
            thread_name: Optional[str] = None,
        ) -> None: ...
        def commit_pending_distribution(self, thread_name: Optional[str] = None) -> int: ...
        def peek_reserved_joint_sample(self, thread_name: Optional[str] = None) -> Optional[int]: ...
        def reserve_joint_sample(self, sample_count: int, thread_name: Optional[str] = None) -> Optional[int]: ...
        def release_joint_sample(self, thread_name: Optional[str] = None) -> Optional[int]: ...
        def commit_joint_sample(self, thread_name: Optional[str] = None) -> Optional[int]: ...
        def snapshot_thread_progress(self) -> List[Dict[str, Any]]: ...
else:
    # 运行时继续导出 ExecutionState，保证旧 import 不崩；静态检查期则使用上面的协议补足过渡字段。
    TaskContext = ExecutionState

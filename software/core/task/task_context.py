"""任务模型 - 静态执行配置与运行态状态。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from software.core.reverse_fill import ReverseFillRuntimeState, ReverseFillSpec
from software.core.task.distribution_state import DistributionRuntimeMixin
from software.core.task.progress_state import ThreadProgressMixin, ThreadProgressState
from software.core.task.proxy_state import ProxyLease, ProxyRuntimeMixin
from software.core.task.reverse_fill_state import ReverseFillRuntimeMixin
from software.providers.contracts import SurveyQuestionMeta


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
    location_parts: Dict[int, List[str]] = field(default_factory=dict)
    multi_text_blank_modes: List[List[str]] = field(default_factory=list)
    multi_text_blank_ai_flags: List[List[bool]] = field(default_factory=list)
    multi_text_blank_int_ranges: List[List[List[int]]] = field(default_factory=list)
    single_option_fill_texts: List[Optional[List[Optional[str]]]] = field(default_factory=list)
    single_attached_option_selects: List[List[Dict[str, Any]]] = field(default_factory=list)
    droplist_option_fill_texts: List[Optional[List[Optional[str]]]] = field(default_factory=list)
    multiple_option_fill_texts: List[Optional[List[Optional[str]]]] = field(default_factory=list)
    answer_rules: List[Dict[str, Any]] = field(default_factory=list)
    reverse_fill_spec: Optional[ReverseFillSpec] = None

    question_config_index_map: Dict[int, Tuple[str, int]] = field(default_factory=dict)
    provider_question_config_index_map: Dict[str, Tuple[str, int]] = field(default_factory=dict)
    question_dimension_map: Dict[int, Optional[str]] = field(default_factory=dict)
    question_strict_ratio_map: Dict[int, bool] = field(default_factory=dict)
    question_psycho_bias_map: Dict[int, Any] = field(default_factory=dict)
    questions_metadata: Dict[int, SurveyQuestionMeta] = field(default_factory=dict)
    provider_question_metadata_map: Dict[str, SurveyQuestionMeta] = field(default_factory=dict)
    joint_psychometric_answer_plan: Optional[Any] = None

    psycho_target_alpha: float = 0.85

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
class ExecutionState(
    ThreadProgressMixin,
    ProxyRuntimeMixin,
    DistributionRuntimeMixin,
    ReverseFillRuntimeMixin,
):
    """一次任务运行中的动态状态。"""

    config: ExecutionConfig = field(default_factory=ExecutionConfig)

    cur_num: int = 0
    cur_fail: int = 0
    proxy_unavailable_fail_count: int = 0
    device_quota_fail_count: int = 0
    terminal_stop_category: str = ""
    terminal_failure_reason: str = ""
    terminal_stop_message: str = ""
    thread_progress: Dict[str, ThreadProgressState] = field(default_factory=dict)
    distribution_runtime_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    distribution_pending_by_thread: Dict[str, List[Tuple[str, int, int]]] = field(default_factory=dict)
    joint_reserved_sample_by_thread: Dict[str, int] = field(default_factory=dict)
    joint_reserved_sample_started_at_by_thread: Dict[str, float] = field(default_factory=dict)
    joint_committed_sample_indexes: set[int] = field(default_factory=set)
    joint_answering_threads: set[str] = field(default_factory=set)

    proxy_waiting_threads: int = 0
    proxy_in_use_by_thread: Dict[str, ProxyLease] = field(default_factory=dict)
    successful_proxy_addresses: set[str] = field(default_factory=set)
    proxy_cooldown_until_by_address: Dict[str, float] = field(default_factory=dict)
    reverse_fill_runtime: Optional[ReverseFillRuntimeState] = None

    stop_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)

    _aliyun_captcha_stop_triggered: bool = False
    _aliyun_captcha_stop_lock: threading.Lock = field(default_factory=threading.Lock)
    _aliyun_captcha_popup_shown: bool = False
    _target_reached_stop_triggered: bool = False
    _target_reached_stop_lock: threading.Lock = field(default_factory=threading.Lock)
    _terminal_stop_lock: threading.Lock = field(default_factory=threading.Lock)
    _runtime_condition: threading.Condition = field(default_factory=threading.Condition, repr=False)

    _proxy_fetch_lock: threading.Lock = field(default_factory=threading.Lock)
    _browser_semaphore: Optional[threading.Semaphore] = field(default=None, repr=False)
    _browser_semaphore_lock: threading.Lock = field(default_factory=threading.Lock)
    _browser_semaphore_max_instances: int = 0

    def __setattr__(self, name: str, value: Any) -> None:
        """阻止把静态配置字段误写到运行态对象本身。"""
        if name in _EXECUTION_STATE_FIELD_NAMES:
            object.__setattr__(self, name, value)
            return
        if name in _EXECUTION_CONFIG_FIELD_NAMES:
            raise AttributeError(f"ExecutionState 不允许直接设置配置字段 '{name}'，请改用 state.config.{name}")
        object.__setattr__(self, name, value)

    def mark_terminal_stop(
        self,
        category: str,
        *,
        failure_reason: str = "",
        message: str = "",
        overwrite: bool = False,
    ) -> None:
        normalized_category = str(category or "").strip()
        if not normalized_category:
            return
        normalized_failure_reason = str(failure_reason or "").strip()
        normalized_message = str(message or "").strip()
        with self._terminal_stop_lock:
            if self.terminal_stop_category and not overwrite:
                return
            self.terminal_stop_category = normalized_category
            self.terminal_failure_reason = normalized_failure_reason
            self.terminal_stop_message = normalized_message
        self.notify_runtime_change()

    def get_terminal_stop_snapshot(self) -> Tuple[str, str, str]:
        with self._terminal_stop_lock:
            return (
                str(self.terminal_stop_category or ""),
                str(self.terminal_failure_reason or ""),
                str(self.terminal_stop_message or ""),
            )


_EXECUTION_CONFIG_FIELD_NAMES = frozenset(ExecutionConfig.__dataclass_fields__.keys())
_EXECUTION_STATE_FIELD_NAMES = frozenset(ExecutionState.__dataclass_fields__.keys())

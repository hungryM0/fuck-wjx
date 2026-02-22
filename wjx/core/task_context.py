"""任务上下文 - 单次提交任务的完整配置与运行时状态。

替代散落在 state.py 中的模块级全局变量，每次 start_run() 时
由 RunController 构造一个新实例，并作为参数透传给引擎和辅助模块，
彻底消除全局状态带来的线程安全盲区与单例限制。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union


# ---------------------------------------------------------------------------
# 答题内容配置（由 configure_probabilities 写入）
# ---------------------------------------------------------------------------

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
    single_option_fill_texts: List[Optional[List[Optional[str]]]] = field(default_factory=list)
    droplist_option_fill_texts: List[Optional[List[Optional[str]]]] = field(default_factory=list)
    multiple_option_fill_texts: List[Optional[List[Optional[str]]]] = field(default_factory=list)

    # 题号 → (配置题型, 在对应类型概率列表中的起始索引)
    question_config_index_map: Dict[int, Tuple[str, int]] = field(default_factory=dict)

    # 题号 → 维度名称（None 表示未分组，走纯随机）
    question_dimension_map: Dict[int, Optional[str]] = field(default_factory=dict)

    # 题号 → 是否为反向题（scale/score 为 bool；matrix 为 List[bool]，每行一个）
    question_reverse_map: Dict[int, Any] = field(default_factory=dict)

    # 题目元数据（从 HTML 解析得到）：题号 → 题目信息字典
    questions_metadata: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    # ── 并发 / 浏览器配置 ─────────────────────────────────────────────────
    browser_preference: List[str] = field(default_factory=list)
    num_threads: int = 1
    target_num: int = 1
    fail_threshold: int = 1
    stop_on_fail_enabled: bool = True

    # ── 时间 / 节奏配置 ───────────────────────────────────────────────────
    submit_interval_range_seconds: Tuple[int, int] = (0, 0)
    answer_duration_range_seconds: Tuple[int, int] = (0, 0)
    duration_control_enabled: bool = False
    duration_control_estimated_seconds: int = 0
    duration_control_total_duration_seconds: int = 0

    # ── 定时模式 ──────────────────────────────────────────────────────────
    timed_mode_enabled: bool = False
    timed_mode_refresh_interval: float = 0.5  # DEFAULT_REFRESH_INTERVAL

    # ── 代理 / UA 配置 ────────────────────────────────────────────────────
    random_proxy_ip_enabled: bool = False
    proxy_ip_pool: List[str] = field(default_factory=list)
    random_user_agent_enabled: bool = False
    user_agent_pool_keys: List[str] = field(default_factory=list)
    user_agent_ratios: Dict[str, int] = field(
        default_factory=lambda: {"wechat": 33, "mobile": 33, "pc": 34}
    )
    pause_on_aliyun_captcha: bool = True

    # ── 运行时计数（引擎动态更新，需加锁！） ─────────────────────────────
    cur_num: int = 0
    cur_fail: int = 0

    # ── 停止控制 ──────────────────────────────────────────────────────────
    stop_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)

    # ── 验证码相关标志 ────────────────────────────────────────────────────
    _aliyun_captcha_stop_triggered: bool = False
    _aliyun_captcha_stop_lock: threading.Lock = field(default_factory=threading.Lock)
    _aliyun_captcha_popup_shown: bool = False
    _target_reached_stop_triggered: bool = False
    _target_reached_stop_lock: threading.Lock = field(default_factory=threading.Lock)

    # ── 代理连续失败计数 ──────────────────────────────────────────────────
    _consecutive_bad_proxy_count: int = 0
    MAX_CONSECUTIVE_BAD_PROXIES: int = 5
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

    def is_fast_mode(self) -> bool:
        """极速模式：时长控制/随机IP关闭且时间间隔为0时自动启用。"""
        return (
            not self.duration_control_enabled
            and not self.random_proxy_ip_enabled
            and self.submit_interval_range_seconds == (0, 0)
            and self.answer_duration_range_seconds == (0, 0)
        )

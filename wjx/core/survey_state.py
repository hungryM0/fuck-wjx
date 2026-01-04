"""
问卷填写状态管理模块

将原本散落在 engine.py 中的全局变量封装为类，
支持线程安全访问和状态重置。
"""
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union


@dataclass
class SurveyState:
    """
    问卷填写运行时状态，封装原 engine.py 中的全局变量。
    
    使用方式：
        state = SurveyState()
        state.reset()  # 重置所有状态
        with state.lock:
            state.cur_num += 1
    """
    # 问卷链接
    url: str = ""
    
    # 各题型概率配置
    single_prob: List[Union[List[float], int, float, None]] = field(default_factory=list)
    droplist_prob: List[Union[List[float], int, float, None]] = field(default_factory=list)
    multiple_prob: List[List[float]] = field(default_factory=list)
    matrix_prob: List[Union[List[float], int, float, None]] = field(default_factory=list)
    scale_prob: List[Union[List[float], int, float, None]] = field(default_factory=list)
    slider_targets: List[float] = field(default_factory=list)
    
    # 填空题配置
    texts: List[List[str]] = field(default_factory=list)
    texts_prob: List[List[float]] = field(default_factory=list)
    text_entry_types: List[str] = field(default_factory=list)
    
    # 选项附加填空文本
    single_option_fill_texts: List[Optional[List[Optional[str]]]] = field(default_factory=list)
    droplist_option_fill_texts: List[Optional[List[Optional[str]]]] = field(default_factory=list)
    multiple_option_fill_texts: List[Optional[List[Optional[str]]]] = field(default_factory=list)
    
    # 运行参数
    target_num: int = 1
    fail_threshold: int = 1
    num_threads: int = 1
    cur_num: int = 0
    cur_fail: int = 0
    stop_on_fail_enabled: bool = True
    
    # 时间控制
    submit_interval_range_seconds: Tuple[int, int] = (0, 0)
    answer_duration_range_seconds: Tuple[int, int] = (0, 0)
    
    # 模式开关
    duration_control_enabled: bool = False
    duration_control_estimated_seconds: int = 0
    duration_control_total_duration_seconds: int = 0
    timed_mode_enabled: bool = False
    timed_mode_refresh_interval: float = 5.0
    
    # 代理/UA
    random_proxy_ip_enabled: bool = False
    proxy_ip_pool: List[str] = field(default_factory=list)
    random_user_agent_enabled: bool = False
    user_agent_pool_keys: List[str] = field(default_factory=list)
    
    # 验证码相关
    last_submit_had_captcha: bool = False
    _aliyun_captcha_stop_triggered: bool = False
    _aliyun_captcha_popup_shown: bool = False
    _target_reached_stop_triggered: bool = False
    _resume_after_aliyun_captcha_stop: bool = False
    _resume_snapshot: Dict[str, Any] = field(default_factory=dict)
    
    # 线程同步
    lock: threading.Lock = field(default_factory=threading.Lock)
    stop_event: threading.Event = field(default_factory=threading.Event)
    _aliyun_captcha_stop_lock: threading.Lock = field(default_factory=threading.Lock)
    _target_reached_stop_lock: threading.Lock = field(default_factory=threading.Lock)
    
    # 常量
    MAX_THREADS: int = 12
    MULTI_TEXT_DELIMITER: str = "||"
    
    def reset_counters(self) -> None:
        """重置计数器（开始新任务时调用）"""
        with self.lock:
            self.cur_num = 0
            self.cur_fail = 0
    
    def reset_probabilities(self) -> None:
        """重置概率配置"""
        self.single_prob = []
        self.droplist_prob = []
        self.multiple_prob = []
        self.matrix_prob = []
        self.scale_prob = []
        self.slider_targets = []
        self.texts = []
        self.texts_prob = []
        self.text_entry_types = []
        self.single_option_fill_texts = []
        self.droplist_option_fill_texts = []
        self.multiple_option_fill_texts = []
    
    def reset_captcha_flags(self) -> None:
        """重置验证码相关标志"""
        with self._aliyun_captcha_stop_lock:
            self._aliyun_captcha_stop_triggered = False
            self._aliyun_captcha_popup_shown = False
        with self._target_reached_stop_lock:
            self._target_reached_stop_triggered = False
        self._resume_after_aliyun_captcha_stop = False
        self._resume_snapshot = {}
    
    def reset_all(self) -> None:
        """完全重置所有状态"""
        self.url = ""
        self.reset_probabilities()
        self.reset_counters()
        self.reset_captcha_flags()
        self.stop_event.clear()
        self.proxy_ip_pool = []
        self.last_submit_had_captcha = False
    
    def is_fast_mode(self) -> bool:
        """判断是否为极速模式"""
        return (
            not self.duration_control_enabled
            and not self.random_proxy_ip_enabled
            and self.submit_interval_range_seconds == (0, 0)
            and self.answer_duration_range_seconds == (0, 0)
        )
    
    def is_timed_mode_active(self) -> bool:
        """判断定时模式是否激活"""
        return bool(self.timed_mode_enabled)
    
    def increment_success(self) -> int:
        """递增成功计数，返回新值"""
        with self.lock:
            self.cur_num += 1
            return self.cur_num
    
    def increment_failure(self) -> Tuple[int, bool]:
        """
        递增失败计数。
        返回 (新失败数, 是否应该停止)
        """
        with self.lock:
            self.cur_fail += 1
            should_stop = (
                self.stop_on_fail_enabled 
                and self.cur_fail >= self.fail_threshold
            )
            return self.cur_fail, should_stop
    
    def should_continue(self) -> bool:
        """判断是否应该继续执行"""
        if self.stop_event.is_set():
            return False
        with self.lock:
            if self.target_num > 0 and self.cur_num >= self.target_num:
                return False
        return True
    
    def get_progress(self) -> Tuple[int, int, int]:
        """获取进度 (当前完成数, 目标数, 失败数)"""
        with self.lock:
            return self.cur_num, self.target_num, self.cur_fail


# 全局单例（向后兼容）
_global_state: Optional[SurveyState] = None
_global_state_lock = threading.Lock()


def get_global_state() -> SurveyState:
    """获取全局状态单例"""
    global _global_state
    if _global_state is None:
        with _global_state_lock:
            if _global_state is None:
                _global_state = SurveyState()
    return _global_state


def reset_global_state() -> SurveyState:
    """重置并返回全局状态"""
    state = get_global_state()
    state.reset_all()
    return state

"""
问卷填写引擎的状态管理模块
将原本分散的全局变量封装成类，便于管理和测试
"""
import threading
from typing import List, Optional, Union, Dict, Any, Tuple


class SurveyRunnerState:
    """问卷填写引擎的运行时状态"""
    
    def __init__(self):
        # 问卷链接
        self.url: str = ""
        
        # 各题型的概率配置
        self.single_prob: List[Union[List[float], int, float, None]] = []
        self.droplist_prob: List[Union[List[float], int, float, None]] = []
        self.multiple_prob: List[List[float]] = []
        self.matrix_prob: List[Union[List[float], int, float, None]] = []
        self.scale_prob: List[Union[List[float], int, float, None]] = []
        self.slider_targets: List[float] = []
        
        # 填空题配置
        self.texts: List[List[str]] = []
        self.texts_prob: List[List[float]] = []
        self.text_entry_types: List[str] = []
        
        # 选项填空配置
        self.single_option_fill_texts: List[Optional[List[Optional[str]]]] = []
        self.droplist_option_fill_texts: List[Optional[List[Optional[str]]]] = []
        self.multiple_option_fill_texts: List[Optional[List[Optional[str]]]] = []
        
        # 运行参数
        self.target_num: int = 1
        self.fail_threshold: int = 1
        self.num_threads: int = 1
        self.stop_on_fail_enabled: bool = True
        
        # 时间控制
        self.submit_interval_range_seconds: Tuple[int, int] = (0, 0)
        self.answer_duration_range_seconds: Tuple[int, int] = (0, 0)
        
        # 运行状态
        self.cur_num: int = 0
        self.cur_fail: int = 0
        self.lock: threading.Lock = threading.Lock()
        self.stop_event: threading.Event = threading.Event()
        
        # 时长控制
        self.duration_control_enabled: bool = False
        self.duration_control_estimated_seconds: int = 0
        self.duration_control_total_duration_seconds: int = 0
        
        # 定时模式
        self.timed_mode_enabled: bool = False
        self.timed_mode_refresh_interval: float = 5.0
        
        # 随机IP
        self.random_proxy_ip_enabled: bool = False
        self.proxy_ip_pool: List[str] = []
        
        # 随机UA
        self.random_user_agent_enabled: bool = False
        self.user_agent_pool_keys: List[str] = []
        
        # 验证码状态
        self.last_submit_had_captcha: bool = False
        self._aliyun_captcha_stop_triggered: bool = False
        self._aliyun_captcha_stop_lock: threading.Lock = threading.Lock()
        self._aliyun_captcha_popup_shown: bool = False
        
        # 目标达成状态
        self._target_reached_stop_triggered: bool = False
        self._target_reached_stop_lock: threading.Lock = threading.Lock()
        
        # 恢复快照
        self._resume_after_aliyun_captcha_stop: bool = False
        self._resume_snapshot: Dict[str, Any] = {}
    
    def reset_runtime_state(self):
        """重置运行时状态（保留配置）"""
        self.cur_num = 0
        self.cur_fail = 0
        self.stop_event.clear()
        self.last_submit_had_captcha = False
        self._aliyun_captcha_stop_triggered = False
        self._aliyun_captcha_popup_shown = False
        self._target_reached_stop_triggered = False
        self._resume_after_aliyun_captcha_stop = False
        self._resume_snapshot = {}


# 全局单例实例（向后兼容）
_global_state = SurveyRunnerState()

import threading
from typing import Any, Dict, List, Optional, Tuple, Union

import wjx.modes.timed_mode as timed_mode

url = ""

single_prob: List[Union[List[float], int, float, None]] = []
droplist_prob: List[Union[List[float], int, float, None]] = []
multiple_prob: List[List[float]] = []
matrix_prob: List[Union[List[float], int, float, None]] = []
scale_prob: List[Union[List[float], int, float, None]] = []
slider_targets: List[float] = []
texts: List[List[str]] = []
texts_prob: List[List[float]] = []
text_entry_types: List[str] = []
text_ai_flags: List[bool] = []
text_titles: List[str] = []
single_option_fill_texts: List[Optional[List[Optional[str]]]] = []
droplist_option_fill_texts: List[Optional[List[Optional[str]]]] = []
multiple_option_fill_texts: List[Optional[List[Optional[str]]]] = []

# 最大线程数限制（确保用户电脑流畅）
MAX_THREADS = 12

# 浏览器实例并发限制（防止内存爆炸）
MAX_BROWSER_INSTANCES = 4
_browser_semaphore: Optional[threading.Semaphore] = None
_browser_semaphore_lock = threading.Lock()
browser_preference: List[str] = []


def _get_browser_semaphore(max_instances: int = MAX_BROWSER_INSTANCES) -> threading.Semaphore:
    """获取或创建浏览器实例信号量，限制同时运行的浏览器数量"""
    global _browser_semaphore
    with _browser_semaphore_lock:
        if _browser_semaphore is None:
            _browser_semaphore = threading.Semaphore(max_instances)
        return _browser_semaphore


def _reset_browser_semaphore(max_instances: int = MAX_BROWSER_INSTANCES) -> None:
    """重置信号量（任务开始时调用）"""
    global _browser_semaphore
    with _browser_semaphore_lock:
        _browser_semaphore = threading.Semaphore(max_instances)


target_num = 1
fail_threshold = 1
num_threads = 1
cur_num = 0
cur_fail = 0
stop_on_fail_enabled = True
submit_interval_range_seconds: Tuple[int, int] = (0, 0)
answer_duration_range_seconds: Tuple[int, int] = (0, 0)
lock = threading.Lock()
stop_event = threading.Event()
duration_control_enabled = False
duration_control_estimated_seconds = 0
duration_control_total_duration_seconds = 0
timed_mode_enabled = False
timed_mode_refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
random_proxy_ip_enabled = False
proxy_ip_pool: List[str] = []
random_user_agent_enabled = False
user_agent_pool_keys: List[str] = []
last_submit_had_captcha = False
_aliyun_captcha_stop_triggered = False
_aliyun_captcha_stop_lock = threading.Lock()
_aliyun_captcha_popup_shown = False
_target_reached_stop_triggered = False
_target_reached_stop_lock = threading.Lock()
_resume_after_aliyun_captcha_stop = False
_resume_snapshot: Dict[str, Any] = {}
pause_on_aliyun_captcha = True
_consecutive_bad_proxy_count = 0
MAX_CONSECUTIVE_BAD_PROXIES = 5
_proxy_fetch_lock = threading.Lock()

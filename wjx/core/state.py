"""全局运行状态与控制变量

.. deprecated::
    此模块已弃用。新代码应通过 ``TaskContext`` 实例获取/修改运行时状态。
    现有引用将在后续版本中逐步清除。
"""
import threading
from typing import Any, Dict, List, Optional, Tuple, Union

import wjx.modes.timed_mode as timed_mode

url = ""
survey_title = ""

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

# 题号 → (配置题型, 在对应类型概率列表中的起始索引)
# 用于在问卷存在条件跳转（隐藏题目）时，仍能正确查找每道题的概率配置
question_config_index_map: Dict[int, Tuple[str, int]] = {}

# 题号 → 维度名称（None 表示未分组）
question_dimension_map: Dict[int, Optional[str]] = {}

# 题号 → 是否为反向题（scale/score 为 bool；matrix 为 List[bool]）
question_reverse_map: Dict[int, Any] = {}

# 题目元数据（从 HTML 解析得到，用于统计展示时补充选项文本等信息）
# 题号 → 题目信息字典（包含 option_texts, row_texts 等）
questions_metadata: Dict[int, Dict[str, Any]] = {}

_browser_semaphore: Optional[threading.Semaphore] = None
_browser_semaphore_lock = threading.Lock()
_browser_semaphore_max_instances = 0
browser_preference: List[str] = []


def _get_browser_semaphore(max_instances: int) -> threading.Semaphore:
    """获取或创建浏览器实例信号量，限制同时运行的浏览器数量"""
    global _browser_semaphore, _browser_semaphore_max_instances
    normalized = max(1, int(max_instances or 1))
    with _browser_semaphore_lock:
        # 并发配置变更后（例如 1 -> 3），需要重建信号量，
        # 否则会沿用旧容量导致实际并发一直卡在初始值。
        if (
            _browser_semaphore is None
            or _browser_semaphore_max_instances != normalized
        ):
            _browser_semaphore = threading.Semaphore(normalized)
            _browser_semaphore_max_instances = normalized
        return _browser_semaphore


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
user_agent_ratios: Dict[str, int] = {"wechat": 33, "mobile": 33, "pc": 34}  # 设备类型占比
_aliyun_captcha_stop_triggered = False
_aliyun_captcha_stop_lock = threading.Lock()
_aliyun_captcha_popup_shown = False
_target_reached_stop_triggered = False
_target_reached_stop_lock = threading.Lock()
pause_on_aliyun_captcha = True
_consecutive_bad_proxy_count = 0
MAX_CONSECUTIVE_BAD_PROXIES = 5
_proxy_fetch_lock = threading.Lock()

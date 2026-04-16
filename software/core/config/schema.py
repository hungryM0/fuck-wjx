"""运行时配置数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from software.providers.common import SURVEY_PROVIDER_WJX
from software.app.config import DEFAULT_RANDOM_UA_KEYS

if TYPE_CHECKING:
    from software.core.questions.config import QuestionEntry


@dataclass
class RuntimeConfig:
    """运行时配置对象。"""

    url: str = ""
    survey_title: str = ""
    survey_provider: str = SURVEY_PROVIDER_WJX
    target: int = 1
    threads: int = 1
    browser_preference: List[str] = field(default_factory=list)
    submit_interval: Tuple[int, int] = (0, 0)
    answer_duration: Tuple[int, int] = (0, 0)
    timed_mode_enabled: bool = False
    timed_mode_interval: float = 3.0
    random_ip_enabled: bool = False
    proxy_source: str = "default"
    custom_proxy_api: str = ""
    proxy_area_code: Optional[str] = None
    random_ua_enabled: bool = False
    random_ua_keys: List[str] = field(default_factory=lambda: list(DEFAULT_RANDOM_UA_KEYS))
    random_ua_ratios: Dict[str, int] = field(default_factory=lambda: {"wechat": 33, "mobile": 33, "pc": 34})
    fail_stop_enabled: bool = True
    pause_on_aliyun_captcha: bool = True
    reliability_mode_enabled: bool = True
    psycho_target_alpha: float = 0.9
    headless_mode: bool = True
    ai_mode: str = "free"
    ai_provider: str = "deepseek"
    ai_api_key: str = ""
    ai_base_url: str = ""
    ai_api_protocol: str = "auto"
    ai_model: str = ""
    ai_system_prompt: str = ""
    answer_rules: List[Dict[str, Any]] = field(default_factory=list)
    dimension_groups: List[str] = field(default_factory=list)
    question_entries: List[QuestionEntry] = field(default_factory=list)
    questions_info: Optional[List[Dict[str, Any]]] = field(default_factory=list)
    _ai_config_present: bool = field(default=False, init=False, repr=False)


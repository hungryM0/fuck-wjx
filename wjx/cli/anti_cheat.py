"""
CLI 反作弊检查模块

提供问卷星反作弊机制的检测和规避策略。
"""

import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class AntiCheatConfig:
    enabled: bool = True
    check_interval: int = 3
    max_retries: int = 3
    bypass_captcha: bool = True
    simulate_human_delay: bool = True
    randomize_answer_order: bool = True
    fill_text_realistic: bool = True
    min_answer_time: int = 5
    max_answer_time: int = 30


@dataclass
class CaptchaInfo:
    captcha_type: str
    image_url: Optional[str] = None
    position: Optional[Tuple[int, int]] = None
    options: List[str] = field(default_factory=list)


class AntiCheatDetector:
    _instance: Optional["AntiCheatDetector"] = None

    def __new__(cls, *args, **kwargs) -> "AntiCheatDetector":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._config = AntiCheatConfig()
        self._detected_anti_cheat: List[str] = []
        self._captcha_callbacks: Dict[str, Callable] = {}
        self._initialized = True

    def set_config(self, config: AntiCheatConfig) -> None:
        self._config = config
        logger.info(f"反作弊配置已更新: enabled={config.enabled}")

    def get_config(self) -> AntiCheatConfig:
        return self._config

    def register_captcha_handler(self, captcha_type: str, handler: Callable[[CaptchaInfo], Any]) -> None:
        self._captcha_callbacks[captcha_type] = handler
        logger.info(f"已注册验证码处理器: {captcha_type}")

    def check_for_anti_cheat(self, page_html: str, url: str) -> List[str]:
        detected = []
        patterns = {
            "滑块验证": r"slider.*?captcha|验证.*?滑动",
            "点选验证": r"click.*?captcha|验证.*?点击|点击.*?验证",
            "文字识别": r"captcha.*?text|文字.*?验证",
            "行为验证": r"behavior.*?captcha|行为.*?验证",
            "设备检测": r"device.*?fingerprint|fingerprint",
            "浏览器检测": r"browser.*?detect|headless|automation",
        }

        for name, pattern in patterns.items():
            if re.search(pattern, page_html, re.IGNORECASE):
                detected.append(name)
                if name not in self._detected_anti_cheat:
                    self._detected_anti_cheat.append(name)
                    logger.warning(f"检测到反作弊机制: {name}")

        return detected

    def should_simulate_human_delay(self, action_type: str) -> bool:
        if not self._config.simulate_human_delay:
            return False

        delays = {
            "page_load": (2, 5),
            "click": (0.1, 0.3),
            "input": (0.05, 0.15),
            "scroll": (0.2, 0.5),
            "answer": (self._config.min_answer_time, self._config.max_answer_time),
        }

        delay_range = delays.get(action_type, (1, 3))
        time.sleep(random.uniform(*delay_range))
        return True

    def generate_realistic_delay(self, base_time: float) -> float:
        variation = base_time * random.uniform(0.5, 1.5)
        return max(0.1, variation)

    def get_captcha_type_from_page(self, page_html: str) -> Optional[CaptchaInfo]:
        captcha_patterns = [
            (r"slider.*?captcha", "slider"),
            (r"geetest.*?slider", "geetest_slider"),
            (r"verify.*?click", "click"),
            (r"nocaptcha.*?click", "click"),
            (r"aliyun.*?captcha", "aliyun"),
            (r"tencent.*?captcha", "tencent"),
        ]

        for pattern, captcha_type in captcha_patterns:
            if re.search(pattern, page_html, re.IGNORECASE):
                return CaptchaInfo(captcha_type=captcha_type)

        return None

    def handle_captcha(self, captcha_info: CaptchaInfo) -> bool:
        handler = self._captcha_callbacks.get(captcha_info.captcha_type)
        if handler:
            try:
                result = handler(captcha_info)
                logger.info(f"验证码处理成功: {captcha_info.captcha_type}")
                return result
            except Exception as e:
                logger.error(f"验证码处理失败: {e}")
                return False

        if not self._config.bypass_captcha:
            logger.warning(f"未处理验证码: {captcha_info.captcha_type}")
            return False

        logger.info(f"跳过验证码: {captcha_info.captcha_type}")
        return True

    def randomize_options(self, options: List[str]) -> List[str]:
        if not self._config.randomize_answer_order:
            return options
        randomized = options.copy()
        random.shuffle(randomized)
        return randomized

    def generate_realistic_text(self, field_type: str, min_length: int = 5, max_length: int = 50) -> str:
        templates = {
            "name": ["张三", "李四", "王五", "赵六", "钱七"],
            "phone": ["138", "139", "150", "151", "152"],
            "email": ["@qq.com", "@163.com", "@gmail.com"],
            "general": [
                "这个问卷很有意思",
                "感谢提供这次机会",
                "希望能够得到您的认可",
                "回答问题让我学到很多",
                "继续保持加油",
            ],
        }

        text_type = field_type.lower()
        if "name" in text_type:
            return random.choice(templates["name"])
        elif "phone" in text_type or "tel" in text_type:
            number = random.choice(templates["phone"]) + "".join([str(random.randint(0, 9)) for _ in range(8)])
            return number
        elif "email" in text_type:
            username = "".join([random.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(random.randint(5, 10))])
            return username + random.choice(templates["email"])
        else:
            text = random.choice(templates["general"])
            if len(text) < min_length:
                text = text * 2
            if len(text) > max_length:
                text = text[:max_length]
            return text

    def calculate_answer_score(self, question_type: str, answer_time: float) -> float:
        base_score = 1.0

        if answer_time < self._config.min_answer_time:
            base_score *= 0.5
        elif answer_time > self._config.max_answer_time * 2:
            base_score *= 0.8

        if question_type == "single" and answer_time < 2:
            base_score *= 0.3
        elif question_type == "multiple" and answer_time < 3:
            base_score *= 0.4
        elif question_type == "text" and answer_time < 5:
            base_score *= 0.5

        return base_score

    def get_reliability_score(self) -> float:
        if not self._detected_anti_cheat:
            return 1.0

        penalty = len(self._detected_anti_cheat) * 0.15
        return max(0.0, 1.0 - penalty)


_anti_cheat_instance: Optional[AntiCheatDetector] = None


def get_anti_cheat() -> AntiCheatDetector:
    global _anti_cheat_instance
    if _anti_cheat_instance is None:
        _anti_cheat_instance = AntiCheatDetector()
    return _anti_cheat_instance
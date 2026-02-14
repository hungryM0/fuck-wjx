"""题型处理共享辅助函数"""
import math
import random
import time
from typing import Any, List, Optional, Tuple, Union
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception


from wjx.network.browser import By, BrowserDriver
from wjx.utils.app.config import DEFAULT_FILL_TEXT


def weighted_index(probabilities: List[float]) -> int:
    """根据权重列表随机选择索引"""

    if not probabilities:
        raise ValueError("probabilities cannot be empty")
    weights: List[float] = []
    total = 0.0
    for value in probabilities:
        try:
            weight = float(value)
        except Exception:
            weight = 0.0
        if math.isnan(weight) or math.isinf(weight) or weight < 0.0:
            weight = 0.0
        weights.append(weight)
        total += weight

    if total <= 0.0:
        return random.randrange(len(weights))

    pivot = random.random() * total
    running = 0.0
    for index, weight in enumerate(weights):
        running += weight
        if pivot <= running:
            return index
    return len(weights) - 1


def normalize_probabilities(values: List[float]) -> List[float]:
    """归一化概率列表"""
    if not values:
        raise ValueError("概率列表不能为空")
    total = sum(values)
    if total <= 0:
        raise ValueError("概率列表的和必须大于0")
    return [value / total for value in values]


def generate_random_chinese_name() -> str:
    """生成随机中文姓名，如果存在画像则根据性别选择名字风格"""
    surname_pool = [
        "张", "王", "李", "赵", "陈", "杨", "刘", "黄", "周", "吴", "徐", "孙", "马", "朱", "胡", "林",
        "郭", "何", "高", "罗", "郑", "梁", "谢", "宋", "唐", "韩", "曹", "许", "邓", "冯",
    ]
    # 偏男性化的名字用字
    male_given_pool = "伟俊涛强磊刚凯鹏鑫宇浩瑞博杰宁豪轩皓浩宇子豪思远家豪文博宇航志强明浩志伟文涛梓豪志鹏伟豪君豪承泽"
    # 偏女性化的名字用字
    female_given_pool = "婷雅静怡欣萱琳玲芳颖慧敏雪晶莉倩蕾佳媛茜悦岚蓉瑶诗梦菲琪韵彤璐"
    # 中性用字
    neutral_given_pool = "嘉明华建安晨泽文超洋"

    # 尝试从画像获取性别
    gender = None
    try:
        from wjx.core.persona.generator import get_current_persona
        persona = get_current_persona()
        if persona is not None:
            gender = persona.gender
    except Exception as exc:
        log_suppressed_exception("generate_random_chinese_name: from wjx.core.persona.generator import get_current_persona", exc, level=logging.ERROR)

    surname = random.choice(surname_pool)
    given_len = 1 if random.random() < 0.65 else 2

    if gender == "男":
        pool = male_given_pool + neutral_given_pool
    elif gender == "女":
        pool = female_given_pool + neutral_given_pool
    else:
        pool = male_given_pool + female_given_pool + neutral_given_pool

    given = "".join(random.choice(pool) for _ in range(given_len))
    return f"{surname}{given}"


def generate_random_mobile() -> str:
    """生成随机手机号"""
    prefixes = (
        "130", "131", "132", "133", "134", "135", "136", "137", "138", "139",
        "147", "150", "151", "152", "153", "155", "156", "157", "158", "159",
        "166", "171", "172", "173", "175", "176", "177", "178", "180", "181",
        "182", "183", "184", "185", "186", "187", "188", "189", "198", "199",
    )
    tail = "".join(str(random.randint(0, 9)) for _ in range(8))
    return random.choice(prefixes) + tail


def generate_random_generic_text() -> str:
    """生成随机通用文本"""
    samples = [
        "已填写", "同上", "无", "OK", "收到", "确认", "正常", "通过", "测试数据", "自动填写",
    ]
    base = random.choice(samples)
    suffix = str(random.randint(10, 999))
    return f"{base}{suffix}"


def resolve_dynamic_text_token(token: Any) -> str:
    """解析动态文本令牌"""
    if token is None:
        return DEFAULT_FILL_TEXT
    text = str(token).strip()
    if text == "__RANDOM_NAME__":
        return generate_random_chinese_name()
    if text == "__RANDOM_MOBILE__":
        return generate_random_mobile()
    if text == "__RANDOM_TEXT__":
        return generate_random_generic_text()
    return text or DEFAULT_FILL_TEXT


def extract_text_from_element(element) -> str:
    """从元素提取文本内容"""
    try:
        text = element.text or ""
    except Exception:
        text = ""
    text = text.strip()
    if text:
        return text
    try:
        text = (element.get_attribute("textContent") or "").strip()
    except Exception:
        text = ""
    return text


def get_fill_text_from_config(fill_entries: Optional[List[Optional[str]]], option_index: int) -> Optional[str]:
    """从配置获取填充文本"""
    if not fill_entries or option_index < 0 or option_index >= len(fill_entries):
        return None
    value = fill_entries[option_index]
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def fill_option_additional_text(driver: BrowserDriver, question_number: int, option_index_zero_based: int, fill_value: Optional[str]) -> None:
    """填充选项附加文本输入框"""
    if not fill_value:
        return
    text = str(fill_value).strip()
    if not text:
        return
    try:
        question_div = driver.find_element(By.CSS_SELECTOR, f"#div{question_number}")
    except Exception:
        return
    candidate_inputs = []
    try:
        option_elements = question_div.find_elements(By.CSS_SELECTOR, 'div.ui-controlgroup > div')
    except Exception:
        option_elements = []
    if option_elements and 0 <= option_index_zero_based < len(option_elements):
        option_element = option_elements[option_index_zero_based]
        try:
            candidate_inputs.extend(option_element.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='search'], textarea"))
        except Exception as exc:
            log_suppressed_exception("questions.utils.fill_option_additional_text inputs", exc, level=logging.ERROR)
        try:
            candidate_inputs.extend(option_element.find_elements(By.CSS_SELECTOR, ".ui-other input, .ui-other textarea"))
        except Exception as exc:
            log_suppressed_exception("questions.utils.fill_option_additional_text other inputs", exc, level=logging.ERROR)
    if not candidate_inputs:
        try:
            candidate_inputs = question_div.find_elements(By.CSS_SELECTOR, ".ui-other input, .ui-other textarea")
        except Exception:
            candidate_inputs = []
    if not candidate_inputs:
        try:
            candidate_inputs = question_div.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='search'], textarea")
        except Exception:
            candidate_inputs = []
    for input_element in candidate_inputs:
        try:
            if not input_element.is_displayed():
                continue
        except Exception:
            continue
        try:
            smooth_scroll_to_element(driver, input_element, 'center')
        except Exception as exc:
            log_suppressed_exception("questions.utils.fill_option_additional_text scroll", exc, level=logging.ERROR)
        try:
            input_element.clear()
        except Exception as exc:
            log_suppressed_exception("questions.utils.fill_option_additional_text clear", exc, level=logging.ERROR)
        try:
            input_element.send_keys(text)
            time.sleep(0.05)
            return
        except Exception:
            continue


def smooth_scroll_to_element(driver: BrowserDriver, element, block: str = 'center', full_simulation_active: bool = False) -> None:
    """
    平滑滚动到指定元素位置，模拟人类滚动行为。
    仅在启用时长控制时使用平滑滚动，否则使用瞬间滚动。
    """
    if not full_simulation_active:
        try:
            driver.execute_script(f"arguments[0].scrollIntoView({{block:'{block}', behavior:'auto'}});", element)
        except Exception as exc:
            log_suppressed_exception("questions.utils.smooth_scroll_to_element quick scroll", exc, level=logging.ERROR)
        return
    
    try:
        element_y = driver.execute_script("return arguments[0].getBoundingClientRect().top + window.pageYOffset;", element)
        current_scroll = driver.execute_script("return window.pageYOffset;")
        viewport_height = driver.execute_script("return window.innerHeight;")
        
        if element_y is None or current_scroll is None or viewport_height is None:
            driver.execute_script(f"arguments[0].scrollIntoView({{block:'{block}'}});", element)
            return
        
        if block == 'center':
            target_scroll = element_y - viewport_height / 2
        elif block == 'start':
            target_scroll = element_y - 100
        else:
            target_scroll = element_y - viewport_height + 100
        
        distance = target_scroll - current_scroll
        
        if abs(distance) < 30:
            driver.execute_script(f"arguments[0].scrollIntoView({{block:'{block}', behavior:'auto'}});", element)
            return
        
        steps = max(10, min(25, int(abs(distance) / 80)))
        base_delay = random.uniform(0.015, 0.025)
        
        for i in range(steps):
            progress = (i + 1) / steps
            ease_progress = progress - (1 - progress) * progress * 0.5
            current_step_scroll = current_scroll + distance * ease_progress
            driver.execute_script("window.scrollTo(0, arguments[0]);", current_step_scroll)
            time.sleep(base_delay)
        
        time.sleep(0.02)
        driver.execute_script(f"arguments[0].scrollIntoView({{block:'{block}', behavior:'auto'}});", element)
        
    except Exception:
        try:
            driver.execute_script(f"arguments[0].scrollIntoView({{block:'{block}'}});", element)
        except Exception as exc:
            log_suppressed_exception("questions.utils.smooth_scroll_to_element fallback", exc, level=logging.ERROR)


def normalize_single_like_prob_config(prob_config: Union[List[float], int, float, None], option_count: int) -> Union[List[float], int]:
    """将单选/下拉/量表的权重长度对齐到选项数"""
    if prob_config == -1 or prob_config is None:
        return -1
    return normalize_droplist_probs(prob_config, option_count)


def normalize_droplist_probs(prob_config: Union[List[float], int, float, None], option_count: int) -> List[float]:
    """归一化下拉题概率配置"""
    if option_count <= 0:
        return []
    if prob_config == -1 or prob_config is None:
        try:
            return normalize_probabilities([1.0] * option_count)
        except Exception:
            return [1.0 / option_count] * option_count
    try:
        if isinstance(prob_config, (list, tuple)):
            base = list(prob_config)
        elif isinstance(prob_config, (int, float)):
            base = [float(prob_config)]
        else:
            base = []
        sanitized = [max(0.0, float(v)) if v is not None else 0.0 for v in base]
        if len(sanitized) < option_count:
            sanitized.extend([0.0] * (option_count - len(sanitized)))
        elif len(sanitized) > option_count:
            sanitized = sanitized[:option_count]
        total = sum(sanitized)
        if total > 0:
            return [value / total for value in sanitized]
        return [1.0 / option_count] * option_count
    except Exception:
        return [1.0 / option_count] * option_count


def normalize_option_fill_texts(option_texts: Optional[List[Optional[str]]], option_count: int) -> Optional[List[Optional[str]]]:
    """归一化选项填充文本配置"""
    if not option_texts:
        return None
    normalized_count = option_count if option_count > 0 else len(option_texts)
    normalized: List[Optional[str]] = []
    for idx in range(normalized_count):
        raw = option_texts[idx] if idx < len(option_texts) else None
        if raw is None:
            normalized.append(None)
            continue
        try:
            text_value = str(raw).strip()
        except Exception:
            text_value = ""
        normalized.append(text_value or None)
    if not any(value for value in normalized):
        return None
    return normalized


def _prob_config_is_unset(value: Any) -> bool:
    if value is None:
        return True
    if value == -1:
        return True
    if isinstance(value, (list, tuple)):
        if not value:
            return True
        for item in value:
            try:
                if float(item) > 0:
                    return False
            except Exception:
                continue
        return True
    return False


def _custom_weights_has_positive(weights: Any) -> bool:
    if not isinstance(weights, list) or not weights:
        return False
    stack: List[Any] = list(weights)
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            stack.extend(item)
            continue
        try:
            if float(item) > 0:
                return True
        except Exception:
            continue
    return False


def resolve_prob_config(prob_config: Any, custom_weights: Any, prefer_custom: bool = False) -> Any:
    """
    运行时兜底：当 UI/旧配置导致 `probabilities` 为空/`-1`/全<=0 时，优先使用 `custom_weights`。

    目的：权重为 0 的选项不应被选中（除非所有权重都为 0，此时只能回退随机）。
    """
    if prefer_custom and _prob_config_is_unset(prob_config) and _custom_weights_has_positive(custom_weights):
        return custom_weights
    return prob_config


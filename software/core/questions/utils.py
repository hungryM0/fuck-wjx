"""题型处理共享辅助函数"""
import json
import math
import os
import random
import time
from datetime import date, timedelta
from functools import lru_cache
from typing import Any, List, Optional, Tuple, Union
import logging
from software.logging.log_utils import log_suppressed_exception


from software.network.browser import By, BrowserDriver
from software.app.config import DEFAULT_FILL_TEXT
from software.app.runtime_paths import get_resource_path

_KNOWN_NON_TEXT_QUESTION_TYPES = {"3", "4", "5", "6", "7", "8", "11"}
RANDOM_INT_TOKEN_PREFIX = "__RANDOM_INT__:"
_RANDOM_ID_CARD_TOKEN = "__RANDOM_ID_CARD__"
OPTION_FILL_AI_TOKEN = "__AI_FILL__"
_ID_CARD_CHECKSUM_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CARD_CHECKSUM_CHARS = "10X98765432"


def _normalize_question_type_code(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value).strip()
    except Exception:
        return ""


def _should_treat_question_as_text_like(type_code: Any, option_count: int, text_input_count: int) -> bool:
    normalized = _normalize_question_type_code(type_code)
    if normalized in ("1", "2", "9"):
        return text_input_count > 0
    if normalized in _KNOWN_NON_TEXT_QUESTION_TYPES:
        return False
    return (option_count or 0) <= 1 and text_input_count > 0


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
    last_positive_index = 0
    for index, weight in enumerate(weights):
        if weight <= 0.0:
            continue
        running += weight
        last_positive_index = index
        # 只允许命中正权重区间，避免 pivot == 0 时误落到前导 0 权重选项。
        if pivot < running:
            return index
    return last_positive_index


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
        from software.core.persona.generator import get_current_persona
        persona = get_current_persona()
        if persona is not None:
            gender = persona.gender
    except Exception as exc:
        log_suppressed_exception("generate_random_chinese_name: from software.core.persona.generator import get_current_persona", exc, level=logging.ERROR)

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


@lru_cache(maxsize=1)
def _load_id_card_area_codes() -> Tuple[str, ...]:
    """加载可用于随机身份证的 6 位行政区划代码。"""
    asset_path = get_resource_path(os.path.join("software", "assets", "area_codes_2022.json"))
    fallback_codes = ("110100", "310100", "440100", "330100", "510100")
    try:
        with open(asset_path, "r", encoding="utf-8") as fp:
            area_data = json.load(fp)
    except Exception as exc:
        log_suppressed_exception("questions.utils._load_id_card_area_codes open", exc, level=logging.ERROR)
        return fallback_codes

    codes: List[str] = []
    seen = set()
    provinces = area_data.get("provinces", []) if isinstance(area_data, dict) else []
    for province in provinces:
        if not isinstance(province, dict):
            continue
        for city in province.get("cities", []) or []:
            if not isinstance(city, dict):
                continue
            code = str(city.get("code") or "").strip()
            if len(code) == 6 and code.isdigit() and code not in seen:
                seen.add(code)
                codes.append(code)
    return tuple(codes or fallback_codes)


def _resolve_current_persona() -> Any:
    try:
        from software.core.persona.generator import get_current_persona
        return get_current_persona()
    except Exception as exc:
        log_suppressed_exception("questions.utils._resolve_current_persona import", exc, level=logging.ERROR)
        return None


def _choose_random_birth_date_for_id_card() -> date:
    """根据当前画像生成更像真人填写习惯的出生日期。"""
    today = date.today()
    persona = _resolve_current_persona()
    age_range_map = {
        "18-25": (18, 25),
        "26-35": (26, 35),
        "36-45": (36, 45),
        "46-60": (46, 60),
    }
    min_age, max_age = age_range_map.get(getattr(persona, "age_group", ""), (18, 60))
    age = random.randint(min_age, max_age)
    birth_year = today.year - age
    start = date(birth_year, 1, 1)
    end = date(birth_year, 12, 31)
    return start + timedelta(days=random.randint(0, (end - start).days))


def _choose_id_card_sequence_tail() -> str:
    """生成身份证顺序码，尽量与当前画像性别保持一致。"""
    persona = _resolve_current_persona()
    gender = str(getattr(persona, "gender", "") or "").strip()
    seq_prefix = random.randint(0, 99)
    if gender == "男":
        gender_digit = random.choice((1, 3, 5, 7, 9))
    elif gender == "女":
        gender_digit = random.choice((0, 2, 4, 6, 8))
    else:
        gender_digit = random.randint(0, 9)
    return f"{seq_prefix:02d}{gender_digit}"


def _calculate_id_card_checksum(first_seventeen_digits: str) -> str:
    total = sum(int(num) * weight for num, weight in zip(first_seventeen_digits, _ID_CARD_CHECKSUM_WEIGHTS))
    return _ID_CARD_CHECKSUM_CHARS[total % 11]


def generate_random_id_card() -> str:
    """生成随机身份证号，仅保证格式和校验位算法合法，不对应真实身份。"""
    area_code = random.choice(_load_id_card_area_codes())
    birth_date = _choose_random_birth_date_for_id_card()
    sequence_tail = _choose_id_card_sequence_tail()
    first_seventeen_digits = f"{area_code}{birth_date:%Y%m%d}{sequence_tail}"
    return f"{first_seventeen_digits}{_calculate_id_card_checksum(first_seventeen_digits)}"


def generate_random_generic_text() -> str:
    """生成随机通用文本"""
    samples = [
        "已填写", "同上", "无", "OK", "收到", "确认", "正常", "通过", "测试数据", "自动填写",
    ]
    base = random.choice(samples)
    suffix = str(random.randint(10, 999))
    return f"{base}{suffix}"


def try_parse_random_int_range(raw: Any) -> Optional[Tuple[int, int]]:
    """尝试解析随机整数范围，失败时返回 None。"""

    def _coerce_int(value: Any) -> Optional[int]:
        try:
            text = str(value).strip()
        except Exception:
            return None
        if not text:
            return None
        try:
            return int(text)
        except Exception:
            return None

    if isinstance(raw, dict):
        min_value = _coerce_int(raw.get("min"))
        max_value = _coerce_int(raw.get("max"))
    elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
        min_value = _coerce_int(raw[0])
        max_value = _coerce_int(raw[1])
    else:
        return None

    if min_value is None or max_value is None:
        return None
    if min_value > max_value:
        min_value, max_value = max_value, min_value
    return min_value, max_value


def normalize_random_int_range(raw: Any) -> Tuple[int, int]:
    """将整数范围规整为有序的 (min, max)。"""
    parsed = try_parse_random_int_range(raw)
    if parsed is None:
        raise ValueError("随机整数范围无效")
    return parsed


def serialize_random_int_range(raw: Any) -> List[int]:
    """将整数范围序列化为 [min, max] 结构。"""
    parsed = try_parse_random_int_range(raw)
    if parsed is None:
        return []
    min_value, max_value = parsed
    return [min_value, max_value]


def describe_random_int_range(raw: Any) -> str:
    """输出统一的整数范围描述文本。"""
    parsed = try_parse_random_int_range(raw)
    if parsed is None:
        return "未设置"
    min_value, max_value = parsed
    return f"{min_value}-{max_value}"


def build_random_int_token(min_value: Any, max_value: Any) -> str:
    """构造随机整数动态令牌。"""
    normalized_min, normalized_max = normalize_random_int_range([min_value, max_value])
    return f"{RANDOM_INT_TOKEN_PREFIX}{normalized_min}:{normalized_max}"


def parse_random_int_token(token: Any) -> Optional[Tuple[int, int]]:
    """从动态令牌中提取随机整数范围。"""
    if token is None:
        return None
    text = str(token).strip()
    if not text.startswith(RANDOM_INT_TOKEN_PREFIX):
        return None
    payload = text[len(RANDOM_INT_TOKEN_PREFIX):]
    parts = payload.split(":", 1)
    if len(parts) != 2:
        return None
    return try_parse_random_int_range(parts)


def generate_random_integer_text(min_value: Any, max_value: Any) -> str:
    """生成指定闭区间内的随机整数文本。"""
    normalized_min, normalized_max = normalize_random_int_range([min_value, max_value])
    return str(random.randint(normalized_min, normalized_max))


def resolve_dynamic_text_token(token: Any) -> str:
    """解析动态文本令牌"""
    if token is None:
        return DEFAULT_FILL_TEXT
    text = str(token).strip()
    random_int_range = parse_random_int_token(text)
    if random_int_range is not None:
        return generate_random_integer_text(random_int_range[0], random_int_range[1])
    if text == "__RANDOM_NAME__":
        return generate_random_chinese_name()
    if text == "__RANDOM_MOBILE__":
        return generate_random_mobile()
    if text == _RANDOM_ID_CARD_TOKEN:
        return generate_random_id_card()
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


def resolve_option_fill_text_from_config(
    fill_entries: Optional[List[Optional[str]]],
    option_index: int,
    *,
    driver: Optional[BrowserDriver] = None,
    question_number: int = 0,
    option_text: Optional[str] = None,
) -> Optional[str]:
    """解析选项附加输入框配置，支持固定文本、随机值和 AI。"""
    raw_value = get_fill_text_from_config(fill_entries, option_index)
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    if text != OPTION_FILL_AI_TOKEN:
        return resolve_dynamic_text_token(text)

    from software.core.ai.runtime import AIRuntimeError, generate_ai_answer, resolve_question_title_for_ai

    if driver is None or question_number <= 0:
        raise AIRuntimeError("AI 选项附加填空缺少运行时上下文")

    question_title = resolve_question_title_for_ai(driver, question_number)
    option_hint = str(option_text or "").strip()
    ai_prompt = (
        f"{question_title}\n\n"
        "当前需要填写的是某个选择题选项后面的补充输入框。"
    )
    if option_hint:
        ai_prompt += f"\n已选择的选项是：{option_hint}"
    ai_prompt += "\n请只输出最终要填写的内容，不要解释。"

    try:
        answer = generate_ai_answer(ai_prompt, question_type="fill_blank")
    except AIRuntimeError as exc:
        raise AIRuntimeError(f"第{question_number}题附加填空 AI 生成失败：{exc}") from exc
    return str(answer).strip()


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




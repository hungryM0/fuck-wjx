"""
答题一致性校验 - 防止明显矛盾的前后作答
现在是硬编码匹配词，后续肯定会砍掉换成更系统的语义理解模块
这里先做个简单版本验证思路。

"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from wjx.network.browser import By, BrowserDriver

# 语义关键词（可按需扩展）
_AWARENESS_KEYWORDS = (
    "听说",
    "听过",
    "了解",
    "认识",
    "知道",
    "见过",
    "印象",
)
_PURCHASE_KEYWORDS = (
    "购买",
    "买过",
    "使用",
    "用过",
    "体验",
    "尝试",
    "消费",
)

_AWARENESS_NEGATIVE = (
    "没听过",
    "未听过",
    "没有听过",
    "不了解",
    "不认识",
    "没听说",
    "未听说",
    "从未听过",
    "没见过",
    "无印象",
    "没印象",
)
_AWARENESS_POSITIVE = (
    "听过",
    "听说过",
    "了解",
    "认识",
    "知道",
    "见过",
    "有印象",
)

_PURCHASE_NEGATIVE = (
    "从未购买",
    "未购买",
    "没买过",
    "没有购买",
    "不购买",
    "从未使用",
    "未使用",
    "没用过",
    "没有使用",
    "不使用",
    "未体验",
    "没有体验",
    "从未体验",
    "未尝试",
    "从未尝试",
)
_PURCHASE_POSITIVE = (
    "购买过",
    "买过",
    "使用过",
    "用过",
    "体验过",
    "尝试过",
    "经常",
    "偶尔",
    "已购买",
    "已经购买",
    "正在使用",
)

_YES_WORDS = ("是", "有", "有过", "有购买", "有使用", "已购买", "听过", "了解")
_NO_WORDS = ("否", "没有", "无", "未", "从未", "不", "没")

_QUOTE_PATTERNS = (
    r"[“\"《『「](.{2,20}?)[”\"》』」]",
)
_ENTITY_PATTERNS = (
    r"([\u4e00-\u9fffA-Za-z0-9·]{2,20})\s*品牌",
    r"品牌\s*([\u4e00-\u9fffA-Za-z0-9·]{2,20})",
    r"([\u4e00-\u9fffA-Za-z0-9·]{2,20})\s*产品",
    r"产品\s*([\u4e00-\u9fffA-Za-z0-9·]{2,20})",
)
_ENTITY_STOP_WORDS = {
    "品牌",
    "产品",
    "该品牌",
    "此品牌",
    "本品牌",
    "这个品牌",
    "该产品",
    "此产品",
    "本产品",
}

_MULTI_ENTITY_HINTS = ("以下", "下列", "哪些", "多选")
_MULTI_ENTITY_TOKENS = ("品牌", "产品")


@dataclass
class QuestionSemantic:
    question_text: str
    intent: Optional[str]
    entity: Optional[str]
    positive_indices: List[int]
    negative_indices: List[int]


@dataclass
class EntityState:
    awareness: Optional[bool] = None
    purchase: Optional[bool] = None


_thread_local = threading.local()

_AGE_QUESTION_KEYWORDS = ("年龄", "岁", "出生", "年龄段")
_IDENTITY_QUESTION_KEYWORDS = ("身份", "学历", "职业", "在读", "学生", "工作", "岗位")
_CURRENT_STUDY_QUESTION_KEYWORDS = ("目前就读", "当前就读", "在读", "年级", "读到")

# 学历关键词与最低合理年龄（用于过滤明显不可能的组合）
_EDUCATION_AGE_RULES: Sequence[Tuple[int, Sequence[str]]] = (
    (
        20,
        (
            "研究生",
            "硕士",
            "硕士生",
            "博士",
            "博士生",
            "mba",
            "emba",
        ),
    ),
    (
        17,
        (
            "本科",
            "本科生",
            "本科在读",
            "在读本科",
            "大学本科",
            "学士",
        ),
    ),
    (
        16,
        (
            "大专",
            "专科",
            "高职",
        ),
    ),
)

# 当前就读阶段关键词与最大合理年龄（仅用于“在读/年级”类题）
_CURRENT_STUDY_MAX_AGE_RULES: Sequence[Tuple[int, Sequence[str]]] = (
    (
        15,
        (
            "小学",
            "小学生",
            "一年级",
            "二年级",
            "三年级",
            "四年级",
            "五年级",
            "六年级",
        ),
    ),
    (
        19,
        (
            "初中",
            "初一",
            "初二",
            "初三",
        ),
    ),
    (
        23,
        (
            "高中",
            "高一",
            "高二",
            "高三",
            "中专",
            "职高",
            "技校",
        ),
    ),
    (
        30,
        (
            "大专",
            "专科",
            "高职",
            "本科",
            "本科生",
            "大一",
            "大二",
            "大三",
            "大四",
        ),
    ),
)


@dataclass
class DemographicState:
    age_min: Optional[int] = None
    age_max: Optional[int] = None


def reset_consistency_context() -> None:
    """每份问卷开始时调用，清空一致性状态。"""
    _thread_local.entity_states = {}
    _thread_local.demo_state = DemographicState()


def _get_entity_states() -> Dict[str, EntityState]:
    states = getattr(_thread_local, "entity_states", None)
    if states is None:
        states = {}
        _thread_local.entity_states = states
    return states


def _get_demo_state() -> DemographicState:
    state_obj = getattr(_thread_local, "demo_state", None)
    if state_obj is None:
        state_obj = DemographicState()
        _thread_local.demo_state = state_obj
    return state_obj


def _normalize_text(text: Optional[str]) -> str:
    try:
        return str(text or "").strip()
    except Exception:
        return ""


def _contains_any(text: str, keywords: Sequence[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _looks_like_multi_entity_question(text: str) -> bool:
    if not text:
        return False
    return _contains_any(text, _MULTI_ENTITY_HINTS) and _contains_any(text, _MULTI_ENTITY_TOKENS)


def _extract_entity(text: str) -> Optional[str]:
    if not text or _looks_like_multi_entity_question(text):
        return None
    for pattern in _QUOTE_PATTERNS:
        match = re.search(pattern, text)
        if match:
            candidate = _normalize_text(match.group(1))
            if candidate and candidate not in _ENTITY_STOP_WORDS:
                return candidate
    for pattern in _ENTITY_PATTERNS:
        match = re.search(pattern, text)
        if match:
            candidate = _normalize_text(match.group(1))
            if candidate and candidate not in _ENTITY_STOP_WORDS:
                return candidate
    return None


def _detect_intent(question_text: str, option_texts: Sequence[str]) -> Optional[str]:
    text = _normalize_text(question_text)
    if text:
        has_awareness = _contains_any(text, _AWARENESS_KEYWORDS)
        has_purchase = _contains_any(text, _PURCHASE_KEYWORDS)
        if has_purchase and not has_awareness:
            return "purchase"
        if has_awareness and not has_purchase:
            return "awareness"
        if has_purchase and has_awareness:
            return "purchase"
    for option in option_texts:
        opt = _normalize_text(option)
        if not opt:
            continue
        if _contains_any(opt, _AWARENESS_KEYWORDS):
            return "awareness"
        if _contains_any(opt, _PURCHASE_KEYWORDS):
            return "purchase"
    return None


def _classify_option(intent: Optional[str], option_text: str) -> Optional[str]:
    text = _normalize_text(option_text)
    if not text or not intent:
        return None

    if text in _YES_WORDS:
        return "positive"
    if text in _NO_WORDS:
        return "negative"

    if intent == "awareness":
        if _contains_any(text, _AWARENESS_NEGATIVE):
            return "negative"
        if _contains_any(text, _AWARENESS_POSITIVE):
            return "positive"
        if _contains_any(text, _NO_WORDS):
            return "negative"
        if _contains_any(text, _YES_WORDS):
            return "positive"
    elif intent == "purchase":
        if _contains_any(text, _PURCHASE_NEGATIVE):
            return "negative"
        if _contains_any(text, _PURCHASE_POSITIVE):
            return "positive"
        if _contains_any(text, _NO_WORDS):
            return "negative"
        if _contains_any(text, _YES_WORDS):
            return "positive"
    return None


def resolve_question_text(driver: BrowserDriver, question_number: int) -> str:
    """尽量提取题目标题文本（失败则回退到题目容器文本）。"""
    try:
        container = driver.find_element(By.CSS_SELECTOR, f"#div{question_number}")
    except Exception:
        return ""
    selectors = (
        ".div_title",
        ".qtitle",
        ".field-label",
        ".topichtml",
        ".div_topic",
        ".question-title",
        ".qtext",
        ".div_title_question",
    )
    for selector in selectors:
        try:
            element = container.find_element(By.CSS_SELECTOR, selector)
        except Exception:
            continue
        try:
            text = _normalize_text(element.text)
        except Exception:
            text = ""
        if text:
            return text
    try:
        return _normalize_text(container.text)
    except Exception:
        return ""


def resolve_question_context(
    driver: BrowserDriver,
    question_number: int,
    option_texts: Sequence[str],
) -> Tuple[str, List[str], str]:
    question_text = resolve_question_text(driver, question_number)
    meta: dict = {}
    meta_title = _normalize_text(meta.get("title")) if isinstance(meta, dict) else ""
    meta_options: List[str] = []
    if isinstance(meta, dict):
        raw_options = meta.get("option_texts") or []
        if isinstance(raw_options, list):
            meta_options = [_normalize_text(item) for item in raw_options if _normalize_text(item)]

    cleaned_options = [_normalize_text(text) for text in option_texts]
    if not any(cleaned_options) and meta_options:
        cleaned_options = list(meta_options)

    if not question_text and meta_title:
        question_text = meta_title

    return question_text, cleaned_options, meta_title


def build_question_semantic(
    driver: BrowserDriver,
    question_number: int,
    option_texts: Sequence[str],
) -> QuestionSemantic:
    question_text, cleaned_options, meta_title = resolve_question_context(
        driver, question_number, option_texts
    )

    intent = _detect_intent(question_text, cleaned_options)
    entity = _extract_entity(question_text)
    if not entity and meta_title:
        entity = _extract_entity(meta_title)

    positive_indices: List[int] = []
    negative_indices: List[int] = []
    for idx, text in enumerate(cleaned_options):
        flag = _classify_option(intent, text)
        if flag == "positive":
            positive_indices.append(idx)
        elif flag == "negative":
            negative_indices.append(idx)
    return QuestionSemantic(
        question_text=question_text,
        intent=intent,
        entity=entity,
        positive_indices=positive_indices,
        negative_indices=negative_indices,
    )


def _get_required_polarity(semantic: QuestionSemantic) -> Optional[str]:
    if not semantic.intent or not semantic.entity:
        return None
    states = _get_entity_states()
    state = states.get(semantic.entity)
    if state is None:
        return None
    if semantic.intent == "purchase" and state.awareness is False:
        return "negative"
    if semantic.intent == "awareness" and state.purchase is True:
        return "positive"
    return None


def apply_single_like_consistency(
    probabilities: Sequence[float],
    semantic: QuestionSemantic,
) -> List[float]:
    """对单选/下拉题的权重做一致性约束（不强制触发时返回原权重）。"""
    required = _get_required_polarity(semantic)
    if not required:
        return list(probabilities)
    allowed = semantic.negative_indices if required == "negative" else semantic.positive_indices
    if not allowed:
        return list(probabilities)
    adjusted: List[float] = []
    allowed_sum = 0.0
    for idx, weight in enumerate(probabilities):
        if idx in allowed:
            adjusted.append(float(weight))
            allowed_sum += float(weight)
        else:
            adjusted.append(0.0)
    if allowed_sum <= 0:
        adjusted = [1.0 if idx in allowed else 0.0 for idx in range(len(adjusted))]
    logging.debug(
        "一致性校验：题目[%s] 触发 %s 约束，允许索引=%s",
        semantic.entity or semantic.question_text[:12],
        required,
        allowed,
    )
    return adjusted


def apply_multiple_consistency(
    probabilities: Sequence[float],
    semantic: QuestionSemantic,
) -> List[float]:
    """对多选题的概率做一致性约束（不强制触发时返回原概率）。"""
    required = _get_required_polarity(semantic)
    if not required:
        return list(probabilities)
    allowed = semantic.negative_indices if required == "negative" else semantic.positive_indices
    if not allowed:
        return list(probabilities)
    adjusted: List[float] = []
    allowed_sum = 0.0
    for idx, prob in enumerate(probabilities):
        if idx in allowed:
            val = max(0.0, float(prob))
            adjusted.append(val)
            allowed_sum += val
        else:
            adjusted.append(0.0)
    if allowed_sum <= 0:
        adjusted = [100.0 if idx in allowed else 0.0 for idx in range(len(adjusted))]
    logging.debug(
        "一致性校验：题目[%s] 触发 %s 约束，多选允许索引=%s",
        semantic.entity or semantic.question_text[:12],
        required,
        allowed,
    )
    return adjusted


def pick_allowed_indices_for_random_multi(
    option_count: int,
    semantic: QuestionSemantic,
    min_required: int,
) -> Optional[List[int]]:
    """随机多选分支：在一致性约束下返回可选索引池（不满足条件返回 None）。"""
    required = _get_required_polarity(semantic)
    if not required:
        return None
    allowed = semantic.negative_indices if required == "negative" else semantic.positive_indices
    if not allowed:
        return None
    if len(allowed) < min_required:
        return None
    return [idx for idx in allowed if 0 <= idx < option_count]


def record_consistency_answer(
    semantic: QuestionSemantic,
    selected_indices: Sequence[int],
) -> None:
    """记录语义状态（仅在识别到实体与意图时更新）。"""
    if not semantic.intent or not semantic.entity:
        return
    states = _get_entity_states()
    state = states.get(semantic.entity)
    if state is None:
        state = EntityState()
        states[semantic.entity] = state
    selected_set = set(selected_indices or [])
    if semantic.intent == "awareness":
        if any(idx in selected_set for idx in semantic.positive_indices):
            state.awareness = True
        elif any(idx in selected_set for idx in semantic.negative_indices):
            state.awareness = False
    elif semantic.intent == "purchase":
        if any(idx in selected_set for idx in semantic.positive_indices):
            state.purchase = True
        elif any(idx in selected_set for idx in semantic.negative_indices):
            state.purchase = False


def _parse_age_range(text: str) -> Tuple[Optional[int], Optional[int]]:
    if not text:
        return None, None
    cleaned = text.replace("－", "-").replace("—", "-").replace("–", "-").replace("~", "-")
    range_match = re.search(r"(\d+)\s*[-到]\s*(\d+)\s*岁?", cleaned)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        return min(start, end), max(start, end)
    above_match = re.search(r"(\d+)\s*岁?\s*(以上|及以上)", cleaned)
    if above_match:
        return int(above_match.group(1)), None
    below_match = re.search(r"(\d+)\s*岁?\s*(以下|及以下)", cleaned)
    if below_match:
        return None, int(below_match.group(1))
    single_match = re.search(r"(\d+)\s*岁", cleaned)
    if single_match:
        value = int(single_match.group(1))
        return value, value
    return None, None


def _is_age_question(question_text: str, option_texts: Sequence[str]) -> bool:
    if _contains_any(question_text, _AGE_QUESTION_KEYWORDS):
        return True
    return any("岁" in (text or "") for text in option_texts)


def _is_identity_question(question_text: str) -> bool:
    return _contains_any(question_text, _IDENTITY_QUESTION_KEYWORDS)


def _is_current_study_question(question_text: str) -> bool:
    return _contains_any(question_text, _CURRENT_STUDY_QUESTION_KEYWORDS)


def _detect_education_min_age(option_text: str) -> Optional[int]:
    normalized = _normalize_text(option_text).lower()
    if not normalized:
        return None
    for min_age, keywords in _EDUCATION_AGE_RULES:
        if any(keyword in normalized for keyword in keywords):
            return min_age
    return None


def _detect_current_study_max_age(option_text: str) -> Optional[int]:
    normalized = _normalize_text(option_text).lower()
    if not normalized:
        return None
    for max_age, keywords in _CURRENT_STUDY_MAX_AGE_RULES:
        if any(keyword in normalized for keyword in keywords):
            return max_age
    return None


def apply_demographic_consistency(
    probabilities: Sequence[float],
    driver: BrowserDriver,
    question_number: int,
    option_texts: Sequence[str],
) -> List[float]:
    question_text, cleaned_options, _ = resolve_question_context(driver, question_number, option_texts)
    if not _is_identity_question(question_text):
        return list(probabilities)
    demo_state = _get_demo_state()
    if demo_state.age_min is None and demo_state.age_max is None:
        return list(probabilities)

    is_current_study = _is_current_study_question(question_text)
    disallowed = set()
    for idx, text in enumerate(cleaned_options):
        required_min_age = _detect_education_min_age(text)
        if required_min_age is None:
            pass
        else:
            # 仅在年龄上限明确且低于学历最低合理年龄时拦截，避免误伤边界情况
            if demo_state.age_max is not None and demo_state.age_max < required_min_age:
                disallowed.add(idx)

        # “目前就读/年级”题额外校验：年龄下限高于就读阶段上限则拦截
        if is_current_study:
            allowed_max_age = _detect_current_study_max_age(text)
            if allowed_max_age is not None and demo_state.age_min is not None and demo_state.age_min > allowed_max_age:
                disallowed.add(idx)

    if not disallowed:
        return list(probabilities)
    adjusted = [0.0 if idx in disallowed else float(prob) for idx, prob in enumerate(probabilities)]
    if sum(adjusted) <= 0:
        adjusted = [1.0 if idx not in disallowed else 0.0 for idx in range(len(adjusted))]
    logging.debug(
        "一致性校验：年龄与学历冲突，题号=%s，年龄区间=[%s,%s]，禁用索引=%s",
        question_number,
        demo_state.age_min,
        demo_state.age_max,
        sorted(disallowed),
    )
    return adjusted


def record_demographic_answer(
    driver: BrowserDriver,
    question_number: int,
    option_texts: Sequence[str],
    selected_indices: Sequence[int],
) -> None:
    question_text, cleaned_options, _ = resolve_question_context(driver, question_number, option_texts)
    if not _is_age_question(question_text, cleaned_options):
        return
    if not selected_indices:
        return
    idx = selected_indices[0]
    if idx < 0 or idx >= len(cleaned_options):
        return
    selected_text = cleaned_options[idx]
    age_min, age_max = _parse_age_range(selected_text)
    if age_min is None and age_max is None:
        return
    demo_state = _get_demo_state()
    demo_state.age_min = age_min
    demo_state.age_max = age_max

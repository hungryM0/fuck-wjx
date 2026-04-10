"""问卷星多选题限制识别。"""
import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from software.app.config import (
    _CHINESE_MULTI_EXACT_PATTERNS,
    _CHINESE_MULTI_LIMIT_PATTERNS,
    _CHINESE_MULTI_MIN_PATTERNS,
    _CHINESE_MULTI_RANGE_PATTERNS,
    _ENGLISH_MULTI_EXACT_PATTERNS,
    _ENGLISH_MULTI_LIMIT_PATTERNS,
    _ENGLISH_MULTI_MIN_PATTERNS,
    _ENGLISH_MULTI_RANGE_PATTERNS,
    _MULTI_LIMIT_ATTRIBUTE_NAMES,
    _MULTI_LIMIT_VALUE_KEYSET,
    _MULTI_MIN_LIMIT_ATTRIBUTE_NAMES,
    _MULTI_MIN_LIMIT_VALUE_KEYSET,
    _SELECTION_KEYWORDS_CN,
    _SELECTION_KEYWORDS_EN,
)
from software.network.browser import By, BrowserDriver, NoSuchElementException
from .multiple_dom import _WARNED_OPTION_LOCATOR
from .multiple_rules import _WARNED_PROB_MISMATCH

_DETECTED_MULTI_LIMITS: Dict[Tuple[str, int], Optional[int]] = {}

_DETECTED_MULTI_LIMIT_RANGES: Dict[Tuple[str, int], Tuple[Optional[int], Optional[int]]] = {}

_REPORTED_MULTI_LIMITS: Set[Tuple[str, int]] = set()


def clear_multiple_choice_cache() -> None:
    """清理多选题缓存（在任务结束时调用）"""
    global _DETECTED_MULTI_LIMITS, _DETECTED_MULTI_LIMIT_RANGES, _REPORTED_MULTI_LIMITS, _WARNED_PROB_MISMATCH, _WARNED_OPTION_LOCATOR
    _DETECTED_MULTI_LIMITS.clear()
    _DETECTED_MULTI_LIMIT_RANGES.clear()
    _REPORTED_MULTI_LIMITS.clear()
    _WARNED_PROB_MISMATCH.clear()
    _WARNED_OPTION_LOCATOR.clear()

def _safe_positive_int(value: Any) -> Optional[int]:
    """安全转换为正整数"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        int_value = int(value)
        return int_value if int_value > 0 else None
    try:
        text = str(value).strip()
    except Exception:
        return None
    if not text:
        return None
    if text.isdigit():
        int_value = int(text)
        return int_value if int_value > 0 else None
    match = re.search(r"(\d+)", text)
    if match:
        int_value = int(match.group(1))
        return int_value if int_value > 0 else None
    return None

def _extract_range_from_json_obj(obj: Any) -> Tuple[Optional[int], Optional[int]]:
    """从JSON对象提取范围"""
    min_limit: Optional[int] = None
    max_limit: Optional[int] = None
    if isinstance(obj, dict):
        for key, value in obj.items():
            normalized_key = str(key).lower()
            if normalized_key in _MULTI_MIN_LIMIT_VALUE_KEYSET:
                candidate = _safe_positive_int(value)
                if candidate:
                    min_limit = min_limit or candidate
            if normalized_key in _MULTI_LIMIT_VALUE_KEYSET:
                candidate = _safe_positive_int(value)
                if candidate:
                    max_limit = max_limit or candidate
            nested_min, nested_max = _extract_range_from_json_obj(value)
            if min_limit is None and nested_min is not None:
                min_limit = nested_min
            if max_limit is None and nested_max is not None:
                max_limit = nested_max
            if min_limit is not None and max_limit is not None:
                break
    elif isinstance(obj, list):
        for item in obj:
            nested_min, nested_max = _extract_range_from_json_obj(item)
            if min_limit is None and nested_min is not None:
                min_limit = nested_min
            if max_limit is None and nested_max is not None:
                max_limit = nested_max
            if min_limit is not None and max_limit is not None:
                break
    return min_limit, max_limit

def _extract_range_from_possible_json(text: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    """从可能的JSON文本提取范围"""
    min_limit: Optional[int] = None
    max_limit: Optional[int] = None
    if not text:
        return min_limit, max_limit
    normalized = text.strip()
    if not normalized:
        return min_limit, max_limit
    candidates = [normalized]
    if normalized.startswith("{") and "'" in normalized and '"' not in normalized:
        candidates.append(normalized.replace("'", '"'))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        cand_min, cand_max = _extract_range_from_json_obj(parsed)
        if min_limit is None and cand_min is not None:
            min_limit = cand_min
        if max_limit is None and cand_max is not None:
            max_limit = cand_max
        if min_limit is not None and max_limit is not None:
            return min_limit, max_limit
    for key in _MULTI_MIN_LIMIT_VALUE_KEYSET:
        pattern = re.compile(rf"{re.escape(key)}\s*[:=]\s*(\d+)", re.IGNORECASE)
        match = pattern.search(normalized)
        if match:
            candidate = _safe_positive_int(match.group(1))
            if candidate:
                min_limit = min_limit or candidate
                if max_limit is not None:
                    return min_limit, max_limit
    for key in _MULTI_LIMIT_VALUE_KEYSET:
        pattern = re.compile(rf"{re.escape(key)}\s*[:=]\s*(\d+)", re.IGNORECASE)
        match = pattern.search(normalized)
        if match:
            candidate = _safe_positive_int(match.group(1))
            if candidate:
                max_limit = max_limit or candidate
                if min_limit is not None:
                    return min_limit, max_limit
    return min_limit, max_limit

def _extract_min_max_from_attributes(element) -> Tuple[Optional[int], Optional[int]]:
    """从元素属性提取最小最大值"""
    min_limit = None
    max_limit = None
    for attr in _MULTI_MIN_LIMIT_ATTRIBUTE_NAMES:
        try:
            raw_value = element.get_attribute(attr)
        except Exception:
            continue
        candidate = _safe_positive_int(raw_value)
        if candidate:
            min_limit = candidate
            break
    for attr in _MULTI_LIMIT_ATTRIBUTE_NAMES:
        try:
            raw_value = element.get_attribute(attr)
        except Exception:
            continue
        candidate = _safe_positive_int(raw_value)
        if candidate:
            max_limit = candidate
            break
    return min_limit, max_limit

def _extract_multi_limit_range_from_text(text: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    """从文本提取多选限制范围"""
    if not text:
        return None, None
    normalized = text.strip()
    if not normalized:
        return None, None
    normalized_lower = normalized.lower()
    min_limit: Optional[int] = None
    max_limit: Optional[int] = None
    contains_cn_keyword = any(keyword in normalized for keyword in _SELECTION_KEYWORDS_CN)
    contains_en_keyword = any(keyword in normalized_lower for keyword in _SELECTION_KEYWORDS_EN)
    contains_cn_min_hint = any(keyword in normalized for keyword in ("至少", "最少", "不少于"))
    contains_cn_max_hint = any(keyword in normalized for keyword in ("最多", "至多", "不超过", "不超過", "限选", "限選"))
    contains_en_min_hint = any(keyword in normalized_lower for keyword in ("at least", "minimum"))
    contains_en_max_hint = any(keyword in normalized_lower for keyword in ("up to", "at most", "no more than"))
    if contains_cn_keyword:
        for pattern in _CHINESE_MULTI_RANGE_PATTERNS:
            match = pattern.search(normalized)
            if match:
                first = _safe_positive_int(match.group(1))
                second = _safe_positive_int(match.group(2))
                if first and second:
                    min_limit = min(first, second)
                    max_limit = max(first, second)
                    break
    if min_limit is None and max_limit is None and contains_cn_keyword and not contains_cn_min_hint and not contains_cn_max_hint:
        for pattern in _CHINESE_MULTI_EXACT_PATTERNS:
            match = pattern.search(normalized)
            if match:
                candidate = _safe_positive_int(match.group(1))
                if candidate:
                    min_limit = candidate
                    max_limit = candidate
                    break
    if min_limit is None and max_limit is None and contains_en_keyword:
        for pattern in _ENGLISH_MULTI_RANGE_PATTERNS:
            match = pattern.search(normalized)
            if match:
                first = _safe_positive_int(match.group(1))
                second = _safe_positive_int(match.group(2))
                if first and second:
                    min_limit = min(first, second)
                    max_limit = max(first, second)
                    break
    if min_limit is None and max_limit is None and contains_en_keyword and not contains_en_min_hint and not contains_en_max_hint:
        for pattern in _ENGLISH_MULTI_EXACT_PATTERNS:
            match = pattern.search(normalized_lower)
            if match:
                candidate = _safe_positive_int(match.group(1))
                if candidate:
                    min_limit = candidate
                    max_limit = candidate
                    break
    if min_limit is None and contains_cn_keyword:
        for pattern in _CHINESE_MULTI_MIN_PATTERNS:
            match = pattern.search(normalized)
            if match:
                candidate = _safe_positive_int(match.group(1))
                if candidate:
                    min_limit = candidate
                    break
    if max_limit is None and contains_cn_keyword:
        for pattern in _CHINESE_MULTI_LIMIT_PATTERNS:
            match = pattern.search(normalized)
            if match:
                candidate = _safe_positive_int(match.group(1))
                if candidate:
                    max_limit = candidate
                    break
    if min_limit is None and contains_en_keyword:
        for pattern in _ENGLISH_MULTI_MIN_PATTERNS:
            match = pattern.search(normalized_lower)
            if match:
                candidate = _safe_positive_int(match.group(1))
                if candidate:
                    min_limit = candidate
                    break
    if max_limit is None and contains_en_keyword:
        for pattern in _ENGLISH_MULTI_LIMIT_PATTERNS:
            match = pattern.search(normalized_lower)
            if match:
                candidate = _safe_positive_int(match.group(1))
                if candidate:
                    max_limit = candidate
                    break
    if min_limit is not None and max_limit is not None and min_limit > max_limit:
        min_limit, max_limit = max_limit, min_limit
    return min_limit, max_limit

def _collect_multi_limit_text_fragments_from_container(driver: BrowserDriver, container: Any) -> List[str]:
    """收集题干/提示中的限制文本，排除选项内容避免误把数字选项当成限制。"""
    if container is None:
        return []

    fragments: List[str] = []
    for selector in (
        ".qtypetip",
        ".topichtml",
        ".field-label",
        ".field-desc",
        ".question-desc",
        ".question-tip",
        ".qtip",
        ".qnotice",
        ".question-hint",
    ):
        try:
            elements = container.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            elements = []
        for element in elements:
            try:
                text = str(element.text or "").strip()
            except Exception:
                text = ""
            if text:
                fragments.append(text)

    try:
        cleaned_text = driver.execute_script(
            """
            const root = arguments[0];
            if (!root) return '';
            const clone = root.cloneNode(true);
            clone.querySelectorAll(
                '.ui-controlgroup, ul, ol, table, textarea, select, .slider, .rangeslider, .range-slider, .errorMessage'
            ).forEach((node) => node.remove());
            return (clone.innerText || clone.textContent || '').trim();
            """,
            container,
        )
    except Exception:
        cleaned_text = ""
    if cleaned_text:
        fragments.append(str(cleaned_text).strip())

    deduped: List[str] = []
    seen = set()
    for fragment in fragments:
        normalized = " ".join(str(fragment).split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped

def _get_driver_session_key(driver: BrowserDriver) -> str:
    """获取驱动会话键"""
    session_id = getattr(driver, "session_id", None)
    if session_id:
        return str(session_id)
    return f"id-{id(driver)}"

def detect_multiple_choice_limit_range(driver: BrowserDriver, question_number: int) -> Tuple[Optional[int], Optional[int]]:
    """检测多选题的选择数量限制范围"""
    cache_key = (_get_driver_session_key(driver), question_number)
    if cache_key in _DETECTED_MULTI_LIMIT_RANGES:
        return _DETECTED_MULTI_LIMIT_RANGES[cache_key]
    min_limit: Optional[int] = None
    max_limit: Optional[int] = None
    try:
        container = driver.find_element(By.CSS_SELECTOR, f"#div{question_number}")
    except NoSuchElementException:
        container = None
    if container is not None:
        attr_min, attr_max = _extract_min_max_from_attributes(container)
        if attr_min is not None:
            min_limit = attr_min
        if attr_max is not None:
            max_limit = attr_max
        if min_limit is None or max_limit is None:
            for attr_name in ("data", "data-setting", "data-validate"):
                cand_min, cand_max = _extract_range_from_possible_json(container.get_attribute(attr_name))
                if min_limit is None and cand_min is not None:
                    min_limit = cand_min
                if max_limit is None and cand_max is not None:
                    max_limit = cand_max
                if min_limit is not None and max_limit is not None:
                    break
        if min_limit is None or max_limit is None:
            for fragment in _collect_multi_limit_text_fragments_from_container(driver, container):
                cand_min, cand_max = _extract_multi_limit_range_from_text(fragment)
                if min_limit is None and cand_min is not None:
                    min_limit = cand_min
                if max_limit is None and cand_max is not None:
                    max_limit = cand_max
                if min_limit is not None and max_limit is not None:
                    break
        if min_limit is None or max_limit is None:
            html = container.get_attribute("outerHTML")
            cand_min, cand_max = _extract_range_from_possible_json(html)
            if min_limit is None and cand_min is not None:
                min_limit = cand_min
            if max_limit is None and cand_max is not None:
                max_limit = cand_max
            if min_limit is None or max_limit is None:
                cand_min, cand_max = _extract_multi_limit_range_from_text(html)
                if min_limit is None and cand_min is not None:
                    min_limit = cand_min
                if max_limit is None and cand_max is not None:
                    max_limit = cand_max
    if min_limit is not None and max_limit is not None and min_limit > max_limit:
        min_limit, max_limit = max_limit, min_limit
    _DETECTED_MULTI_LIMIT_RANGES[cache_key] = (min_limit, max_limit)
    _DETECTED_MULTI_LIMITS[cache_key] = max_limit
    return min_limit, max_limit

def detect_multiple_choice_limit(driver: BrowserDriver, question_number: int) -> Optional[int]:
    """检测多选题的最大选择数量限制"""
    _, max_limit = detect_multiple_choice_limit_range(driver, question_number)
    return max_limit

def _log_multi_limit_once(driver: BrowserDriver, question_number: int, min_limit: Optional[int], max_limit: Optional[int]) -> None:
    """仅记录一次多选限制日志"""
    if min_limit is None and max_limit is None:
        return
    cache_key = (_get_driver_session_key(driver), question_number)
    if cache_key in _REPORTED_MULTI_LIMITS:
        return
    _REPORTED_MULTI_LIMITS.add(cache_key)

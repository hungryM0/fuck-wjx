"""问卷星 HTML 解析：规则与元数据。"""
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from .html_parser_choice import (
    _collect_choice_option_texts,
    _collect_select_option_texts,
    _question_div_has_shared_text_input,
)
from .html_parser_common import _cleanup_question_title, _normalize_html_text
from .html_parser_matrix import _collect_matrix_option_texts, _collect_slider_matrix_metadata, _question_div_looks_like_slider_matrix


def _extract_question_title(question_div, fallback_number: int) -> str:
    title_element = question_div.find(class_="topichtml")
    if title_element:
        title_text = _cleanup_question_title(title_element.get_text(" ", strip=True))
        if title_text:
            return title_text
    label_element = question_div.find(class_="field-label")
    if label_element:
        title_text = _cleanup_question_title(label_element.get_text(" ", strip=True))
        if title_text:
            return title_text
    return f"第{fallback_number}题"

def _collect_multi_limit_text_fragments(question_div) -> List[str]:
    """收集可能包含多选限制说明的文本，排除选项正文避免数字误判。"""
    if question_div is None:
        return []

    fragments: List[str] = []
    selectors = (
        ".qtypetip",
        ".topichtml",
        ".field-label",
        ".field-desc",
        ".question-desc",
        ".question-tip",
        ".qtip",
        ".qnotice",
        ".question-hint",
    )
    for selector in selectors:
        try:
            elements = question_div.select(selector)
        except Exception:
            elements = []
        for element in elements:
            try:
                text = _normalize_html_text(element.get_text(" ", strip=True))
            except Exception:
                text = ""
            if text:
                fragments.append(text)

    if BeautifulSoup is not None:
        try:
            cloned_soup = BeautifulSoup(str(question_div), "html.parser")
            for selector in (
                ".ui-controlgroup",
                "ul",
                "ol",
                "table",
                "textarea",
                "select",
                ".slider",
                ".rangeslider",
                ".range-slider",
                ".errorMessage",
            ):
                for element in cloned_soup.select(selector):
                    element.decompose()
            cleaned_text = _normalize_html_text(cloned_soup.get_text(" ", strip=True))
            if cleaned_text:
                fragments.append(cleaned_text)
        except Exception:
            pass

    deduped: List[str] = []
    seen = set()
    for fragment in fragments:
        if not fragment or fragment in seen:
            continue
        seen.add(fragment)
        deduped.append(fragment)
    return deduped

def _extract_multiple_choice_limits(question_div, question_number: int) -> Tuple[Optional[int], Optional[int]]:
    """从多选题 HTML 中提取选择数量限制（最少/最多）"""
    if question_div is None:
        return None, None

    # 尝试从 multiple.py 中复用限制检测逻辑
    try:
        from wjx.provider.questions.multiple import (
            _extract_multi_limit_range_from_text,
        )
        from wjx.provider.questions.multiple_limits import (
            _extract_min_max_from_attributes,
            _extract_range_from_possible_json,
        )

        min_limit: Optional[int] = None
        max_limit: Optional[int] = None

        # 1. 从属性提取
        attr_min, attr_max = _extract_min_max_from_attributes(question_div)
        if attr_min is not None:
            min_limit = attr_min
        if attr_max is not None:
            max_limit = attr_max

        # 2. 从 JSON 属性提取
        if min_limit is None or max_limit is None:
            for attr_name in ("data", "data-setting", "data-validate"):
                try:
                    attr_value = question_div.get(attr_name)
                except Exception:
                    attr_value = None
                cand_min, cand_max = _extract_range_from_possible_json(attr_value)
                if min_limit is None and cand_min is not None:
                    min_limit = cand_min
                if max_limit is None and cand_max is not None:
                    max_limit = cand_max
                if min_limit is not None and max_limit is not None:
                    break

        # 3. 从文本提取
        if min_limit is None or max_limit is None:
            for fragment in _collect_multi_limit_text_fragments(question_div):
                cand_min, cand_max = _extract_multi_limit_range_from_text(fragment)
                if min_limit is None and cand_min is not None:
                    min_limit = cand_min
                if max_limit is None and cand_max is not None:
                    max_limit = cand_max
                if min_limit is not None and max_limit is not None:
                    break

        if min_limit is not None and max_limit is not None and min_limit > max_limit:
            min_limit, max_limit = max_limit, min_limit

        return min_limit, max_limit
    except Exception:
        return None, None

def _extract_question_metadata_from_html(soup, question_div, question_number: int, type_code: str):
    option_texts: List[str] = []
    option_count = 0
    matrix_rows = 0
    row_texts: List[str] = []
    fillable_indices: List[int] = []
    multi_min_limit: Optional[int] = None
    multi_max_limit: Optional[int] = None

    if type_code in {"3", "4", "5", "11"}:
        option_texts, fillable_indices = _collect_choice_option_texts(question_div)
        option_count = len(option_texts)
        # 如果是多选题（type_code == "4"），提取选择数量限制
        if type_code == "4":
            multi_min_limit, multi_max_limit = _extract_multiple_choice_limits(question_div, question_number)
    elif type_code == "7":
        option_texts = _collect_select_option_texts(question_div, soup, question_number)
        option_count = len(option_texts)
        if option_count > 0 and _question_div_has_shared_text_input(question_div):
            fillable_indices = [option_count - 1]
    elif type_code == "6":
        matrix_rows, option_texts, row_texts = _collect_matrix_option_texts(soup, question_div, question_number)
        option_count = len(option_texts)
    elif _question_div_looks_like_slider_matrix(question_div):
        matrix_rows, option_texts, row_texts = _collect_slider_matrix_metadata(question_div)
        option_count = len(option_texts)
    elif type_code == "8":
        option_count = 1
    return option_texts, option_count, matrix_rows, row_texts, fillable_indices, multi_min_limit, multi_max_limit

def _extract_jump_rules_from_html(question_div, question_number: int, option_texts: List[str]) -> Tuple[bool, List[Dict[str, Any]]]:
    """从静态 HTML 中提取跳题逻辑。"""
    has_jump_attr = str(question_div.get("hasjump") or "").strip() == "1"
    jump_rules: List[Dict[str, Any]] = []
    option_idx = 0
    inputs = question_div.find_all("input")
    for input_el in inputs:
        input_type = (input_el.get("type") or "").lower()
        if input_type not in ("radio", "checkbox"):
            continue
        jumpto_raw = input_el.get("jumpto") or input_el.get("data-jumpto")
        if not jumpto_raw:
            option_idx += 1
            continue
        text_value = str(jumpto_raw).strip()
        jumpto_num: Optional[int] = None
        if text_value.isdigit():
            jumpto_num = int(text_value)
        else:
            match = re.search(r"(\d+)", text_value)
            if match:
                try:
                    jumpto_num = int(match.group(1))
                except Exception:
                    jumpto_num = None
        if jumpto_num:
            jump_rules.append({
                "option_index": option_idx,
                "jumpto": jumpto_num,
                "option_text": option_texts[option_idx] if option_idx < len(option_texts) else None,
            })
        option_idx += 1
    return has_jump_attr or bool(jump_rules), jump_rules

def _extract_display_conditions_from_html(question_div, question_number: int) -> Tuple[bool, List[Dict[str, Any]]]:
    """从静态 HTML 中提取按答案显示/隐藏题目的条件逻辑。"""
    relation_raw = str(question_div.get("relation") or "").strip()
    if not relation_raw:
        return False, []

    conditions: List[Dict[str, Any]] = []
    seen: set[Tuple[int, Tuple[int, ...]]] = set()
    for chunk in re.split(r"\s*[|]\s*", relation_raw):
        text = str(chunk or "").strip()
        if not text or "," not in text:
            continue
        source_text, option_text = text.split(",", 1)
        source_match = re.search(r"\d+", source_text)
        if not source_match:
            continue
        try:
            source_question_num = int(source_match.group(0))
        except Exception:
            continue
        option_indices: List[int] = []
        seen_indices = set()
        for match in re.finditer(r"\d+", option_text):
            try:
                option_num = int(match.group(0))
            except Exception:
                continue
            if option_num <= 0:
                continue
            option_index = option_num - 1
            if option_index in seen_indices:
                continue
            seen_indices.add(option_index)
            option_indices.append(option_index)
        if source_question_num <= 0 or not option_indices:
            continue
        dedupe_key = (source_question_num, tuple(option_indices))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        conditions.append({
            "condition_question_num": source_question_num,
            "condition_mode": "selected",
            "condition_option_indices": option_indices,
            "raw_relation": text,
        })
    return bool(conditions), conditions

def _attach_display_condition_metadata(questions_info: List[Dict[str, Any]]) -> None:
    """为题目列表补充“受条件控制显示”和“控制后续显示”两类元数据。"""
    by_num: Dict[int, Dict[str, Any]] = {}
    for info in questions_info:
        try:
            question_num = int(info.get("num") or 0)
        except Exception:
            question_num = 0
        if question_num > 0 and question_num not in by_num:
            by_num[question_num] = info

    for info in questions_info:
        display_conditions = info.get("display_conditions") or []
        if not isinstance(display_conditions, list) or not display_conditions:
            continue
        try:
            target_question_num = int(info.get("num") or 0)
        except Exception:
            target_question_num = 0
        for condition in display_conditions:
            if not isinstance(condition, dict):
                continue
            try:
                source_question_num = int(condition.get("condition_question_num") or 0)
            except Exception:
                source_question_num = 0
            option_indices = condition.get("condition_option_indices") or []
            if source_question_num <= 0 or not isinstance(option_indices, list):
                continue
            source_info = by_num.get(source_question_num)
            if not source_info:
                continue
            targets = source_info.setdefault("controls_display_targets", [])
            if not isinstance(targets, list):
                targets = []
                source_info["controls_display_targets"] = targets
            normalized_indices: List[int] = []
            seen_indices = set()
            for raw_index in option_indices:
                try:
                    index = int(raw_index)
                except Exception:
                    continue
                if index < 0 or index in seen_indices:
                    continue
                seen_indices.add(index)
                normalized_indices.append(index)
            if not normalized_indices:
                continue
            duplicate = False
            for existing in targets:
                if not isinstance(existing, dict):
                    continue
                try:
                    existing_target = int(existing.get("target_question_num") or 0)
                except Exception:
                    existing_target = 0
                existing_indices = existing.get("condition_option_indices") or []
                if existing_target == target_question_num and list(existing_indices) == normalized_indices:
                    duplicate = True
                    break
            if duplicate:
                continue
            targets.append({
                "target_question_num": target_question_num,
                "condition_option_indices": normalized_indices,
                "condition_mode": str(condition.get("condition_mode") or "selected").strip() or "selected",
            })

    for info in questions_info:
        targets = info.get("controls_display_targets")
        if isinstance(targets, list) and targets:
            targets.sort(key=lambda item: (
                int(item.get("target_question_num") or 0) if isinstance(item, dict) else 0,
                tuple(item.get("condition_option_indices") or []) if isinstance(item, dict) else (),
            ))
            info["has_dependent_display_logic"] = True
        else:
            info["controls_display_targets"] = []
            info["has_dependent_display_logic"] = False

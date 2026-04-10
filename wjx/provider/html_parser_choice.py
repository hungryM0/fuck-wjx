"""问卷星 HTML 解析：选择题与文本输入辅助。"""
import re
import logging
from typing import Any, Dict, List, Optional, Tuple

from software.logging.log_utils import log_suppressed_exception
from .html_parser_common import _normalize_html_text

_FORCE_SELECT_COMMAND_RE = re.compile(r"请(?:务必|一定|必须|直接)?\s*选(?:择)?")

_FORCE_SELECT_INDEX_RE = re.compile(r"^第?\s*(\d{1,3})\s*(?:个|项|选项|分|星)?$")

_FORCE_SELECT_SENTENCE_SPLIT_RE = re.compile(r"[。；;！？!\n\r]")

_FORCE_SELECT_CLEAN_RE = re.compile(r"[\s`'\"“”‘’【】\[\]\(\)（）<>《》,，、。；;:：!?！？]")

_FORCE_SELECT_LABEL_TARGET_RE = re.compile(r"^([A-Za-z])(?:项|选项|答案)?$")

_FORCE_SELECT_OPTION_LABEL_RE = re.compile(
    r"^(?:第\s*)?[\(（【\[]?\s*([A-Za-z])\s*[\)）】\]]?(?=$|[\.．、:：\-\s]|[\u4e00-\u9fff])"
)

_TEXT_INPUT_ALLOWED_TYPES = {"", "text", "search", "tel", "number"}

_KNOWN_NON_TEXT_QUESTION_TYPES = {"3", "4", "5", "6", "7", "8", "11"}


def _normalize_force_select_text(value: Any) -> str:
    text = _normalize_html_text(str(value or ""))
    if not text:
        return ""
    return _FORCE_SELECT_CLEAN_RE.sub("", text).lower()

def _extract_force_select_option_label(option_text: Any) -> Optional[str]:
    text = _normalize_html_text(str(option_text or ""))
    if not text:
        return None
    match = _FORCE_SELECT_OPTION_LABEL_RE.match(text)
    if not match:
        return None
    label = str(match.group(1) or "").strip().upper()
    return label or None

def _collect_force_select_fragments(question_div, title_text: str) -> List[str]:
    fragments: List[str] = []
    if title_text:
        cleaned_title = _normalize_html_text(title_text)
        if cleaned_title:
            fragments.append(cleaned_title)
    if question_div is None:
        return fragments
    for selector in (".qtypetip", ".topichtml", ".field-label"):
        try:
            element = question_div.select_one(selector)
        except Exception:
            element = None
        if not element:
            continue
        try:
            text = _normalize_html_text(element.get_text(" ", strip=True))
        except Exception:
            text = ""
        if text:
            fragments.append(text)
    unique_fragments: List[str] = []
    seen: set = set()
    for fragment in fragments:
        key = _normalize_html_text(fragment)
        if not key or key in seen:
            continue
        seen.add(key)
        unique_fragments.append(key)
    return unique_fragments

def _extract_force_select_option(
    question_div,
    title_text: str,
    option_texts: List[str],
) -> Tuple[Optional[int], Optional[str]]:
    """识别“请选XX”类指令，返回强制选择的选项索引。"""
    if not option_texts:
        return None, None

    normalized_options: List[Tuple[int, str, str]] = []
    for idx, option_text in enumerate(option_texts):
        normalized = _normalize_force_select_text(option_text)
        if not normalized:
            continue
        normalized_options.append((idx, str(option_text or "").strip(), normalized))
    if not normalized_options:
        return None, None

    fragments = _collect_force_select_fragments(question_div, title_text)
    for fragment in fragments:
        for command_match in _FORCE_SELECT_COMMAND_RE.finditer(fragment):
            tail_text = fragment[command_match.end():]
            if not tail_text:
                continue
            sentence = _FORCE_SELECT_SENTENCE_SPLIT_RE.split(tail_text, maxsplit=1)[0]
            sentence = sentence.strip(" ：:，,、")
            if not sentence:
                continue
            compact_sentence = _normalize_force_select_text(sentence)
            if not compact_sentence:
                continue

            best_index: Optional[int] = None
            best_text: Optional[str] = None
            best_length = -1
            for option_idx, raw_text, normalized_text in normalized_options:
                # 跳过纯数字文本，避免“第1题”之类误判；数字题走索引匹配兜底。
                if normalized_text.isdigit():
                    continue
                if normalized_text in compact_sentence:
                    text_len = len(normalized_text)
                    if text_len > best_length:
                        best_length = text_len
                        best_index = option_idx
                        best_text = raw_text
            if best_index is not None:
                return best_index, best_text

            label_match = _FORCE_SELECT_LABEL_TARGET_RE.fullmatch(compact_sentence)
            if label_match:
                target_label = str(label_match.group(1) or "").strip().upper()
                if target_label:
                    for option_idx, raw_text, _ in normalized_options:
                        option_label = _extract_force_select_option_label(raw_text)
                        if option_label == target_label:
                            return option_idx, raw_text

            index_match = _FORCE_SELECT_INDEX_RE.fullmatch(sentence)
            if index_match:
                try:
                    target_idx = int(index_match.group(1)) - 1
                except Exception:
                    target_idx = -1
                if 0 <= target_idx < len(option_texts):
                    selected = str(option_texts[target_idx] or "").strip()
                    return target_idx, selected or None
    return None, None

def _is_text_input_element(element) -> bool:
    if element is None:
        return False
    try:
        tag_name = (element.name or '').lower()
    except Exception:
        tag_name = ''
    try:
        input_type = (element.get('type') or '').lower()
    except Exception:
        input_type = ''
    if tag_name == 'textarea':
        return True
    return tag_name == 'input' and input_type in ('', 'text', 'search', 'tel', 'number')

def _element_contains_text_input(element) -> bool:
    if element is None:
        return False
    if _is_text_input_element(element):
        return True
    try:
        candidates = element.find_all(['input', 'textarea'])
    except Exception:
        return False
    for candidate in candidates:
        if _is_text_input_element(candidate):
            return True
    return False

def _question_div_has_shared_text_input(question_div) -> bool:
    if question_div is None:
        return False
    try:
        shared_inputs = question_div.select('.ui-other input, .ui-other textarea')
    except Exception:
        shared_inputs = []
    if any(_element_contains_text_input(element) for element in shared_inputs):
        return True
    try:
        keyword_inputs = question_div.select(
            "input[id*='other'], input[name*='other'], textarea[id*='other'], textarea[name*='other']"
        )
        if any(_element_contains_text_input(element) for element in keyword_inputs):
            return True
    except Exception as exc:
        log_suppressed_exception("survey.parser._question_div_has_shared_text_input keyword", exc, level=logging.ERROR)
    return False

def _extract_option_text_from_attrs(target) -> str:
    if target is None:
        return ""

    def _get_attr_text(node, keys) -> str:
        for key in keys:
            try:
                raw = node.get(key)
            except Exception:
                raw = None
            if raw is None:
                continue
            text_value = _normalize_html_text(str(raw))
            if text_value:
                return text_value
        return ""

    primary_keys = ("title", "data-title", "data-text", "data-label", "aria-label", "alt", "htitle")
    text_value = _get_attr_text(target, primary_keys)
    if text_value:
        return text_value

    try:
        candidates = target.find_all(["a", "span", "label"], limit=4)
    except Exception:
        candidates = []
    for child in candidates:
        text_value = _get_attr_text(child, primary_keys)
        if text_value:
            return text_value

    fallback_keys = ("val", "value", "data-value", "data-val")
    text_value = _get_attr_text(target, fallback_keys)
    if text_value:
        return text_value
    for child in candidates:
        text_value = _get_attr_text(child, fallback_keys)
        if text_value:
            return text_value
    return ""

def _text_looks_meaningful(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"[A-Za-z0-9\u4e00-\u9fff]", text))

def _extract_rating_option_texts(question_div) -> List[str]:
    """优先从评价题的星级锚点提取文本（避免 iconfont 文本）"""
    if question_div is None:
        return []
    selectors = (
        ".scale-rating ul li a",
        ".scale-rating a[val]",
        "ul[tp='d'] li a",
        "ul[class*='modlen'] li a",
    )
    anchors: List[Any] = []
    for selector in selectors:
        try:
            anchors = question_div.select(selector)
        except Exception:
            anchors = []
        if anchors:
            break
    if not anchors:
        return []
    texts: List[str] = []
    seen = set()
    for idx, anchor in enumerate(anchors):
        text = _extract_option_text_from_attrs(anchor)
        if not _text_looks_meaningful(text):
            try:
                text = _normalize_html_text(anchor.get_text(" ", strip=True))
            except Exception:
                text = ""
        if not _text_looks_meaningful(text):
            try:
                text = _normalize_html_text(anchor.get("title") or "")
            except Exception:
                text = ""
        if not _text_looks_meaningful(text):
            try:
                text = _normalize_html_text(anchor.get("val") or "")
            except Exception:
                text = ""
        if not _text_looks_meaningful(text):
            text = str(idx + 1)
        if text in seen:
            continue
        seen.add(text)
        texts.append(text)
    return texts

def _collect_choice_option_texts(question_div) -> Tuple[List[str], List[int]]:
    texts: List[str] = []
    fillable_indices: List[int] = []
    option_elements: List[Any] = []
    selectors = ['.ui-controlgroup > div', 'ul > li']
    for selector in selectors:
        try:
            option_elements = question_div.select(selector)
        except Exception:
            option_elements = []
        if option_elements:
            break
    if option_elements:
        for element in option_elements:
            label_element = None
            try:
                label_element = element.select_one('.label')
            except Exception:
                label_element = None
            if not label_element:
                label_element = element
            text = _normalize_html_text(label_element.get_text(' ', strip=True))
            if not text:
                text = _extract_option_text_from_attrs(element)
            if not text:
                continue
            option_index = len(texts)
            texts.append(text)
            if _element_contains_text_input(element):
                fillable_indices.append(option_index)
    if not texts:
        seen = set()
        fallback_selectors = ['.label', 'li span', 'li']
        for selector in fallback_selectors:
            try:
                elements = question_div.select(selector)
            except Exception:
                elements = []
            for element in elements:
                text = _normalize_html_text(element.get_text(' ', strip=True))
                if not text:
                    text = _extract_option_text_from_attrs(element)
                if not text or text in seen:
                    continue
                texts.append(text)
                seen.add(text)
            if texts:
                break
    if not fillable_indices and texts and _question_div_has_shared_text_input(question_div):
        fillable_indices.append(len(texts) - 1)
    fillable_indices = sorted(set(fillable_indices))
    return texts, fillable_indices

def _extract_select_option_texts_from_element(select_element) -> List[str]:
    if select_element is None:
        return []
    options: List[str] = []
    try:
        option_elements = select_element.find_all("option")
    except Exception:
        option_elements = []
    for idx, option in enumerate(option_elements):
        value = _normalize_html_text(option.get("value") or "")
        text = _normalize_html_text(option.get_text(" ", strip=True))
        if idx == 0 and ((value == "") or (value == "0") or ("请选择" in text)):
            continue
        if not text:
            continue
        options.append(text)
    return options

def _extract_custom_select_option_texts(element) -> List[str]:
    if element is None:
        return []
    raw_values: List[str] = []
    attr_keys = ("cusom", "custom", "data-custom", "data-cusom")
    for key in attr_keys:
        try:
            raw = element.get(key)
        except Exception:
            raw = None
        if raw is not None:
            raw_values.append(str(raw))
    options: List[str] = []
    for raw in raw_values:
        for part in re.split(r"[,，\n\r|/]+", raw):
            text = _normalize_html_text(part)
            if not text or text == "请选择":
                continue
            options.append(text)
    deduped: List[str] = []
    seen = set()
    for option in options:
        if option in seen:
            continue
        seen.add(option)
        deduped.append(option)
    return deduped

def _extract_choice_attached_selects(question_div) -> List[Dict[str, Any]]:
    if question_div is None:
        return []
    option_elements: List[Any] = []
    for selector in ('.ui-controlgroup > div', 'ul > li'):
        try:
            option_elements = question_div.select(selector)
        except Exception:
            option_elements = []
        if option_elements:
            break
    attached_selects: List[Dict[str, Any]] = []
    for option_index, element in enumerate(option_elements):
        option_text = ""
        try:
            label_element = element.select_one(".label")
        except Exception:
            label_element = None
        if label_element is not None:
            try:
                option_text = _normalize_html_text(label_element.get_text(" ", strip=True))
            except Exception:
                option_text = ""
        if not option_text:
            option_text = _extract_option_text_from_attrs(element)
        try:
            select_element = element.find("select")
        except Exception:
            select_element = None
        select_options = _extract_select_option_texts_from_element(select_element)
        if not select_options:
            input_candidates = []
            try:
                input_candidates = element.find_all("input")
            except Exception:
                input_candidates = []
            for input_element in input_candidates:
                select_options = _extract_custom_select_option_texts(input_element)
                if select_options:
                    break
        if not select_options:
            continue
        attached_selects.append({
            "option_index": option_index,
            "option_text": option_text,
            "select_options": select_options,
            "select_option_count": len(select_options),
        })
    return attached_selects

def _verify_text_indicates_location(value: Optional[str]) -> bool:
    if not value:
        return False
    text = str(value).strip()
    if not text:
        return False
    return ("地图" in text) or ("map" in text.lower())

def _soup_question_is_location(question_div) -> bool:
    if question_div is None:
        return False
    try:
        if question_div.find(class_="get_Local"):
            return True
    except Exception as exc:
        log_suppressed_exception("survey.parser._soup_question_is_location get_Local", exc, level=logging.ERROR)
    try:
        inputs = question_div.find_all("input")
    except Exception:
        inputs = []
    for input_element in inputs:
        verify_value = input_element.get("verify")
        if _verify_text_indicates_location(verify_value):
            return True
    return False

def _collect_select_option_texts(question_div, soup, question_number: int) -> List[str]:
    select = question_div.find("select")
    if not select and soup:
        select = soup.find("select", id=f"q{question_number}")
    if not select:
        return []
    options: List[str] = []
    option_elements = select.find_all("option")
    for idx, option in enumerate(option_elements):
        value = (option.get("value") or "").strip()
        text = _normalize_html_text(option.get_text(" ", strip=True))
        if idx == 0 and (value == "" or value == "0"):
            continue
        if not text:
            continue
        options.append(text)
    return options

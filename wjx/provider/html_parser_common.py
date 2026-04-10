"""问卷星 HTML 解析公共辅助。"""
import logging
import re
from typing import Any, List, Optional

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from software.app.config import _HTML_SPACE_RE
from software.core.questions.utils import _normalize_question_type_code
from software.logging.log_utils import log_suppressed_exception

_TEXT_INPUT_ALLOWED_TYPES = {"text", "tel", "email", "number", "search", "url", "password"}
_KNOWN_NON_TEXT_QUESTION_TYPES = {"3", "4", "5", "6", "7", "8", "11", "12", "13", "15", "16", "17"}


def _normalize_html_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return _HTML_SPACE_RE.sub(" ", value).strip()

def extract_survey_title_from_html(html: str) -> Optional[str]:
    """尝试从问卷 HTML 文本中提取标题。"""


    if not BeautifulSoup:
        return None
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return None

    selectors = [
        "#divTitle h1",
        "#divTitle",
        ".surveytitle",
        ".survey-title",
        ".surveyTitle",
        ".wjdcTitle",
        ".htitle",
        ".topic_tit",
        "#htitle",
        "#lbTitle",
    ]
    candidates: List[str] = []
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            text = _normalize_html_text(element.get_text(" ", strip=True))
            if text:
                candidates.append(text)

    if not candidates:
        for tag_name in ("h1", "h2"):
            header = soup.find(tag_name)
            if header:
                text = _normalize_html_text(header.get_text(" ", strip=True))
                if text:
                    candidates.append(text)
                if candidates:
                    break

    title_tag = soup.find("title")
    if title_tag:
        text = _normalize_html_text(title_tag.get_text(" ", strip=True))
        if text:
            candidates.append(text)

    for raw in candidates:
        cleaned = raw
        cleaned = re.sub(r"(?:[-|]\s*)?(?:问卷星.*)$", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip(" -_|")
        if cleaned:
            return cleaned
    return None

def _extract_question_number_from_div(question_div) -> Optional[int]:
    topic_attr = question_div.get("topic")
    if topic_attr and topic_attr.isdigit():
        return int(topic_attr)
    id_attr = question_div.get("id") or ""
    match = re.search(r"div(\d+)", id_attr)
    if match:
        return int(match.group(1))
    return None

def _cleanup_question_title(raw_title: str) -> str:
    title = _normalize_html_text(raw_title)
    if not title:
        return ""
    title = re.sub(r"^\*?\s*\d+\.\s*", "", title)
    title = title.replace("【单选题】", "").replace("【多选题】", "")
    return title.strip()

def _extract_display_question_number(raw_title: Any) -> Optional[int]:
    text = _normalize_html_text(str(raw_title or ""))
    if not text:
        return None
    match = re.match(r"^\*?\s*(\d+)\.\s*", text)
    if not match:
        return None
    try:
        number = int(match.group(1))
    except Exception:
        return None
    return number if number > 0 else None

def _extract_display_heading_text(question_div) -> str:
    if question_div is None:
        return ""
    for class_name in ("topichtml", "field-label", "qtypetip"):
        try:
            title_element = question_div.find(class_=class_name)
        except Exception:
            title_element = None
        if not title_element:
            continue
        try:
            text = title_element.get_text(" ", strip=True)
        except Exception:
            text = ""
        text = _normalize_html_text(text)
        if text:
            return text
    try:
        blockquote = question_div.find("blockquote")
    except Exception:
        blockquote = None
    if blockquote is not None:
        try:
            text = blockquote.get_text(" ", strip=True)
        except Exception:
            text = ""
        text = _normalize_html_text(text)
        if text:
            return text
    try:
        text = question_div.get_text(" ", strip=True)
    except Exception:
        text = ""
    return _normalize_html_text(text)

def _count_text_inputs_in_soup(question_div) -> int:
    try:
        candidates = question_div.find_all(["input", "textarea", "span", "div"])
    except Exception:
        return 0
    count = 0
    for cand in candidates:
        try:
            tag_name = (cand.name or "").lower()
        except Exception:
            tag_name = ""
        input_type = ""
        try:
            input_type = (cand.get("type") or "").lower()
        except Exception:
            input_type = ""
        style_text = ""
        try:
            style_text = (cand.get("style") or "").lower()
        except Exception:
            style_text = ""
        try:
            class_attr = cand.get("class") or []
            if isinstance(class_attr, str):
                class_text = class_attr.lower()
            else:
                class_text = " ".join(class_attr).lower()
        except Exception:
            class_text = ""
        is_textcont = "textcont" in class_text or "textedit" in class_text

        if input_type == "hidden" or "display:none" in style_text or "visibility:hidden" in style_text:
            continue

        if tag_name == "input":
            try:
                sibling = cand.find_next_sibling()
                sibling_classes = sibling.get("class") if sibling else None
                if sibling_classes and any("textedit" in cls.lower() for cls in sibling_classes):
                    continue
            except Exception as exc:
                log_suppressed_exception("survey.parser._count_text_inputs sibling", exc, level=logging.ERROR)
        if tag_name == "textarea" or (tag_name == "input" and input_type in _TEXT_INPUT_ALLOWED_TYPES):
            count += 1
            continue
        try:
            contenteditable = (cand.get("contenteditable") or "").lower() == "true"
        except Exception:
            contenteditable = False
        if (contenteditable or is_textcont) and tag_name in {"span", "div"}:
            count += 1
    return count

def _extract_text_input_labels(question_div) -> List[str]:
    """提取多项填空题每个输入框的标签信息"""
    labels = []
    try:
        candidates = question_div.find_all(["input", "textarea", "span", "div"])
    except Exception:
        return labels

    for cand in candidates:
        try:
            tag_name = (cand.name or "").lower()
            input_type = (cand.get("type") or "").lower()
            style_text = (cand.get("style") or "").lower()
            class_attr = cand.get("class") or []
            class_text = " ".join(class_attr).lower() if isinstance(class_attr, list) else str(class_attr).lower()
            is_textcont = "textcont" in class_text or "textedit" in class_text

            if input_type == "hidden" or "display:none" in style_text or "visibility:hidden" in style_text:
                continue

            if tag_name == "input":
                sibling = cand.find_next_sibling()
                if sibling and sibling.get("class") and any("textedit" in cls.lower() for cls in sibling.get("class")):
                    continue

            is_text_input = False
            if tag_name == "textarea" or (tag_name == "input" and input_type in _TEXT_INPUT_ALLOWED_TYPES):
                is_text_input = True
            elif (cand.get("contenteditable") == "true" or is_textcont) and tag_name in {"span", "div"}:
                is_text_input = True

            if is_text_input:
                label = cand.get("placeholder") or cand.get("aria-label") or cand.get("data-label") or ""
                if not label:
                    prev = cand.find_previous_sibling(string=True)
                    if prev:
                        label = prev.strip().rstrip("：:").strip()
                labels.append(label if label else f"填空{len(labels) + 1}")
        except Exception:
            continue

    return labels

def _soup_question_looks_like_description(question_div, type_code: str) -> bool:
    """检测是否为说明页/阅读材料（有 topic 和 type 属性但无可交互控件）。

    问卷星有时会给纯阅读材料/说明文字也打上 topic 和 type 属性，
    导致解析器误将其识别为正常题目。此函数通过检测交互控件的缺失来识别这类情况。
    """
    if question_div is None:
        return False
    # 只对选择类题型做检测（type 3/4 是最常见的误识别情况）
    if type_code not in {"3", "4"}:
        return False
    try:
        # 检查是否有 radio/checkbox input（单选/多选题必备）
        choice_inputs = question_div.find_all(
            "input", attrs={"type": lambda v: v and v.lower() in ("radio", "checkbox")}
        )
        if choice_inputs:
            return False
        # 检查是否有标准选项容器
        has_control_group = bool(question_div.select_one(".ui-controlgroup"))
        if has_control_group:
            return False
        # 检查是否有 jqradio/jqcheck 样式的选项（另一种模板）
        has_jq_controls = bool(question_div.select_one(".jqradio, .jqcheck"))
        if has_jq_controls:
            return False
    except Exception:
        return False
    # 没有任何选择控件 → 说明页
    return True

def _soup_question_looks_like_reorder(question_div) -> bool:
    """兜底判断：通过 DOM 特征识别排序题（静态 HTML）。"""
    if question_div is None:
        return False
    try:
        if question_div.select_one(".sortnum, .sortnum-sel, .order-number, .order-index"):
            return True
    except Exception as exc:
        log_suppressed_exception("survey.parser._soup_question_looks_like_reorder quick", exc, level=logging.ERROR)
    try:
        has_list_items = bool(question_div.select("ul li, ol li"))
        if not has_list_items:
            return False
        has_sort_signature = bool(
            question_div.select(".ui-sortable, .ui-sortable-handle, [class*='sort']")
        )
        return has_sort_signature
    except Exception:
        return False

def _soup_question_looks_like_numeric_scale(question_div) -> bool:
    """检测是否更像数字量表/NPS（大量数字刻度+两端文字提示）。"""
    if question_div is None:
        return False
    try:
        anchors = question_div.select("ul[tp='d'] li a, .scale-rating ul li a, .scale-rating a[val]")
    except Exception:
        anchors = []
    texts: List[str] = []
    for anchor in anchors:
        text = _normalize_html_text(anchor.get_text(" ", strip=True))
        if not text:
            try:
                text = _normalize_html_text(anchor.get("title") or anchor.get("val") or anchor.get("value") or "")
            except Exception:
                text = ""
        if text:
            texts.append(text)
    if not texts:
        return False
    numeric_count = sum(1 for t in texts if re.fullmatch(r"\d{1,2}", t))
    has_scale_title = False
    try:
        has_scale_title = bool(question_div.select_one(".scaleTitle, .scaleTitle_frist, .scaleTitle_last, .scaleTitleFirst, .scaleTitleLast"))
    except Exception:
        has_scale_title = False
    total = len(texts)
    return total >= 5 and numeric_count >= max(3, int(total * 0.7)) and (total >= 9 or has_scale_title)

def _soup_question_looks_like_rating(question_div) -> bool:
    """识别评价题（星级评价）"""
    if question_div is None:
        return False
    # NPS/数字刻度题虽然也有 rate-off/rate-on 样式，但应判为量表而非评价题
    if _soup_question_looks_like_numeric_scale(question_div):
        return False
    has_rate_icon = False
    try:
        has_rate_icon = bool(question_div.select_one("a.rate-off, a.rate-on, .rate-off, .rate-on"))
    except Exception:
        has_rate_icon = False
    has_tag_wrap = False
    try:
        has_tag_wrap = bool(question_div.find(class_="evaluateTagWrap"))
    except Exception:
        has_tag_wrap = False
    has_iconfont = False
    try:
        has_iconfont = bool(question_div.select_one(".scale-rating .iconfontNew, .iconfontNew"))
    except Exception:
        has_iconfont = False

    # 评价题需要“星级/评价”特征，避免普通量表误判
    if has_tag_wrap:
        return True
    if has_rate_icon or has_iconfont:
        return True
    return False

def _extract_rating_option_count(question_div) -> int:
    """尝试解析评价题的星级数量。"""
    if question_div is None:
        return 0
    try:
        rating_list = question_div.find("ul", class_=re.compile(r"modlen(\d+)"))
    except Exception:
        rating_list = None
    if rating_list:
        try:
            class_attr = rating_list.get("class") or []
            for cls in class_attr:
                match = re.search(r"modlen(\d+)", str(cls))
                if match:
                    return int(match.group(1))
        except Exception as exc:
            log_suppressed_exception("survey.parser._extract_rating_option_count modlen", exc, level=logging.ERROR)
    try:
        options = question_div.select(".scale-rating ul li")
        if options:
            return len(options)
    except Exception as exc:
        log_suppressed_exception("survey.parser._extract_rating_option_count scale-rating", exc, level=logging.ERROR)
    try:
        options = question_div.select("a.rate-off, a.rate-on")
        if options:
            return len(options)
    except Exception as exc:
        log_suppressed_exception("survey.parser._extract_rating_option_count rate-off", exc, level=logging.ERROR)
    return 0

def _should_mark_as_multi_text(
    type_code: Any,
    option_count: int,
    text_input_count: int,
    is_location: bool,
    has_gapfill: bool = False,
    has_slider_matrix: bool = False,
) -> bool:
    if is_location:
        return False
    if has_slider_matrix:
        return False
    normalized = _normalize_question_type_code(type_code)
    if normalized == "9" and has_gapfill:
        return True
    if text_input_count < 2:
        return False
    if normalized in ("1", "2", "9"):
        return True
    if normalized in _KNOWN_NON_TEXT_QUESTION_TYPES:
        return False
    if (option_count or 0) == 0:
        return True
    return (option_count or 0) <= 1 and text_input_count >= 2

"""问卷星 HTML 解析模块 - 从 HTML 解析问卷结构。"""
from typing import Any, Dict, List, Optional

from software.providers.contracts import (
    LOGIC_PARSE_STATUS_COMPLETE,
    LOGIC_PARSE_STATUS_NONE,
)

from software.core.questions.utils import _should_treat_question_as_text_like

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from .html_parser_choice import (
    _extract_choice_attached_selects,
    _extract_force_select_option,
    _extract_rating_option_texts,
    _soup_question_is_location,
    _text_looks_meaningful,
)
from .html_parser_common import (
    _count_text_inputs_in_soup,
    _extract_display_heading_text,
    _extract_display_question_number,
    _extract_question_number_from_div,
    _extract_rating_option_count,
    _extract_text_input_labels,
    _normalize_html_text,
    _soup_question_is_required,
    _should_mark_as_multi_text,
    _soup_question_looks_like_description,
    _soup_question_looks_like_rating,
    _soup_question_looks_like_reorder,
    extract_survey_title_from_html,
)
from .html_parser_matrix import _extract_slider_range, _question_div_looks_like_slider_matrix
from .html_parser_rules import (
    _attach_display_condition_metadata,
    _extract_display_conditions_from_html,
    _extract_jump_rules_from_html,
    _extract_question_metadata_from_html,
    _extract_question_title,
)

__all__ = ["_normalize_html_text", "extract_survey_title_from_html", "parse_survey_questions_from_html"]


def _normalize_media_source_url(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if text.startswith("//"):
        return f"https:{text}"
    return text


def _append_media_item(
    media: List[Dict[str, Any]],
    *,
    scope: str,
    index: Optional[int],
    source_url: Any,
    label: str,
) -> None:
    normalized_url = _normalize_media_source_url(source_url)
    if not normalized_url:
        return
    item = {
        "kind": "image",
        "scope": scope,
        "index": index,
        "source_url": normalized_url,
        "label": str(label or "").strip(),
    }
    if item not in media:
        media.append(item)


def _collect_question_media(question_div, row_texts: List[str], option_texts: List[str]) -> List[Dict[str, Any]]:
    if question_div is None:
        return []
    media: List[Dict[str, Any]] = []

    title_nodes: List[Any] = []
    for selector in (".topichtml", ".field-label"):
        try:
            title_nodes.extend(list(question_div.select(selector) or []))
        except Exception:
            continue
    for node in title_nodes:
        try:
            images = node.select("img")
        except Exception:
            images = []
        for image in images:
            _append_media_item(
                media,
                scope="title",
                index=None,
                source_url=image.get("src") or image.get("data-src") or image.get("data-original"),
                label="题干图",
            )

    option_nodes: List[Any] = []
    for selector in (".ui-controlgroup > div", "ul > li"):
        try:
            option_nodes = list(question_div.select(selector) or [])
        except Exception:
            option_nodes = []
        if option_nodes:
            break
    for option_index, node in enumerate(option_nodes):
        option_label = (
            str(option_texts[option_index] or "").strip()
            if option_index < len(option_texts)
            else f"选项 {option_index + 1}"
        )
        try:
            images = node.select("img")
        except Exception:
            images = []
        for image in images:
            _append_media_item(
                media,
                scope="option",
                index=option_index,
                source_url=image.get("src") or image.get("data-src") or image.get("data-original"),
                label=option_label or f"选项 {option_index + 1}",
            )

    row_nodes: List[Any] = []
    for selector in ("tr[rowindex]", "tr.rowtitletr", "tr[id^='drv']"):
        try:
            row_nodes = list(question_div.select(selector) or [])
        except Exception:
            row_nodes = []
        if row_nodes:
            break
    for row_index, node in enumerate(row_nodes):
        row_label = (
            str(row_texts[row_index] or "").strip()
            if row_index < len(row_texts)
            else f"第 {row_index + 1} 行"
        )
        try:
            images = node.select("img")
        except Exception:
            images = []
        for image in images:
            _append_media_item(
                media,
                scope="row",
                index=row_index,
                source_url=image.get("src") or image.get("data-src") or image.get("data-original"),
                label=row_label or f"第 {row_index + 1} 行",
            )
    return media


def _question_div_is_initially_hidden(question_div) -> bool:
    if question_div is None:
        return False
    style_text = str(question_div.get("style") or "").lower()
    hidden_attr = str(question_div.get("hidden") or "").strip().lower()
    class_text = " ".join(question_div.get("class") or []).lower() if question_div.get("class") else ""
    return (
        "display:none" in style_text
        or "display: none" in style_text
        or "visibility:hidden" in style_text
        or "visibility: hidden" in style_text
        or hidden_attr in {"hidden", "true", "1"}
        or "display-none" in class_text
    )


def _question_div_or_ancestors_are_hidden(question_div) -> bool:
    current = question_div
    while current is not None:
        if _question_div_is_initially_hidden(current):
            return True
        current = getattr(current, "parent", None)
    return False


def _question_div_has_question_ancestor(question_div, fieldset) -> bool:
    current = getattr(question_div, "parent", None)
    while current is not None and current is not fieldset:
        try:
            if current.name == "div" and current.get("topic") is not None:
                return True
        except Exception:
            return False
        current = getattr(current, "parent", None)
    return False


def parse_survey_questions_from_html(html: str) -> List[Dict[str, Any]]:
    """从 HTML 解析问卷题目列表"""
    if not BeautifulSoup:
        raise RuntimeError("BeautifulSoup is required for HTML parsing")
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find("div", id="divQuestion")
    if not container:
        return []
    fieldsets = container.find_all("fieldset")
    if not fieldsets:
        fieldsets = [container]
    questions_info: List[Dict[str, Any]] = []
    for page_index, fieldset in enumerate(fieldsets, 1):
        question_divs = [
            item
            for item in fieldset.find_all("div", attrs={"topic": True})
            if not _question_div_has_question_ancestor(item, fieldset)
        ]
        current_display_num: Optional[int] = None
        visible_question_counter = 0
        for question_div in question_divs:
            raw_heading_text = _extract_display_heading_text(question_div)
            question_number = _extract_question_number_from_div(question_div)
            if question_number is None:
                heading_num = _extract_display_question_number(raw_heading_text)
                if heading_num is not None:
                    current_display_num = heading_num
                continue
            type_code = str(question_div.get("type") or "").strip() or "0"
            if type_code != "11" and _soup_question_looks_like_reorder(question_div):
                type_code = "11"
            is_description = _soup_question_looks_like_description(question_div, type_code)
            is_required = _soup_question_is_required(question_div)
            is_rating = False
            rating_max = 0
            if type_code == "5":
                is_rating = _soup_question_looks_like_rating(question_div)
                if is_rating:
                    rating_max = _extract_rating_option_count(question_div)
            is_location = type_code in {"1", "2"} and _soup_question_is_location(question_div)
            display_num = _extract_display_question_number(raw_heading_text)
            if display_num is None:
                display_num = current_display_num
            elif display_num > 0:
                current_display_num = display_num
            if not _question_div_or_ancestors_are_hidden(question_div):
                visible_question_counter += 1
                if display_num is None or display_num != visible_question_counter:
                    display_num = visible_question_counter
                    current_display_num = display_num
            title_text = _extract_question_title(question_div, question_number)
            (
                option_texts,
                option_count,
                matrix_rows,
                row_texts,
                fillable_indices,
                multi_min_limit,
                multi_max_limit,
            ) = _extract_question_metadata_from_html(soup, question_div, question_number, type_code)
            if is_rating:
                rating_texts = _extract_rating_option_texts(question_div)
                if rating_texts:
                    option_texts = rating_texts
                option_count = max(option_count, rating_max, len(option_texts))
                if option_count > 0:
                    has_meaningful = any(_text_looks_meaningful(text) for text in option_texts)
                    if not option_texts or not has_meaningful:
                        option_texts = [str(i + 1) for i in range(option_count)]
            # 量表题（type_code="5"）如果不是评价题，需要提取数字刻度选项文本
            elif type_code == "5":
                scale_texts = _extract_rating_option_texts(question_div)
                if scale_texts:
                    option_texts = scale_texts
                    option_count = len(scale_texts)
            attached_option_selects: List[Dict[str, Any]] = []
            if type_code in {"3", "4"}:
                attached_option_selects = _extract_choice_attached_selects(question_div)
            has_jump, jump_rules = _extract_jump_rules_from_html(question_div, question_number, option_texts)
            has_display_condition, display_conditions = _extract_display_conditions_from_html(question_div, question_number)
            is_slider_matrix = _question_div_looks_like_slider_matrix(question_div)
            slider_min, slider_max, slider_step = (None, None, None)
            if type_code == "8":
                slider_min, slider_max, slider_step = _extract_slider_range(question_div, question_number)
            elif is_slider_matrix:
                slider_min, slider_max, slider_step = _extract_slider_range(question_div, question_number)
            text_input_count = _count_text_inputs_in_soup(question_div)
            text_input_labels = _extract_text_input_labels(question_div) if text_input_count > 1 else []
            has_gapfill = str(question_div.get("gapfill") or "").strip() == "1"
            is_text_like_question = _should_treat_question_as_text_like(
                type_code,
                option_count,
                text_input_count,
                has_slider_matrix=is_slider_matrix,
            )
            is_multi_text = _should_mark_as_multi_text(
                type_code,
                option_count,
                text_input_count,
                is_location,
                has_gapfill,
                has_slider_matrix=is_slider_matrix,
            )
            forced_option_index: Optional[int] = None
            forced_option_text: Optional[str] = None
            if type_code in {"3", "5", "7"}:
                forced_option_index, forced_option_text = _extract_force_select_option(
                    question_div,
                    title_text,
                    option_texts,
                )
            questions_info.append({
                "num": question_number,
                "display_num": display_num,
                "title": title_text,
                "type_code": type_code,
                "options": option_count,
                "rows": matrix_rows,
                "row_texts": row_texts,
                "page": page_index,
                "option_texts": option_texts,
                "forced_option_index": forced_option_index,
                "forced_option_text": forced_option_text,
                "fillable_options": fillable_indices,
                "attached_option_selects": attached_option_selects,
                "has_attached_option_select": bool(attached_option_selects),
                "is_location": is_location,
                "is_rating": is_rating,
                "is_description": is_description,
                "rating_max": rating_max,
                "text_inputs": text_input_count,
                "text_input_labels": text_input_labels,
                "is_multi_text": is_multi_text,
                "is_text_like": is_text_like_question,
                "is_slider_matrix": is_slider_matrix,
                "has_jump": has_jump,
                "jump_rules": jump_rules,
                "has_display_condition": has_display_condition,
                "display_conditions": display_conditions,
                "logic_parse_status": LOGIC_PARSE_STATUS_NONE,
                "question_media": _collect_question_media(question_div, row_texts, option_texts),
                "slider_min": slider_min,
                "slider_max": slider_max,
                "slider_step": slider_step,
                "multi_min_limit": multi_min_limit,
                "multi_max_limit": multi_max_limit,
                "required": is_required,
            })
    _attach_display_condition_metadata(questions_info)
    for question in questions_info:
        has_logic = (
            bool(question.get("has_jump"))
            or bool(question.get("has_display_condition"))
            or bool(question.get("has_dependent_display_logic"))
        )
        question["logic_parse_status"] = (
            LOGIC_PARSE_STATUS_COMPLETE if has_logic else LOGIC_PARSE_STATUS_NONE
        )
    return questions_info

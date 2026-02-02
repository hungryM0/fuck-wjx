"""问卷解析模块 - 从 HTML 解析问卷结构"""
import json
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from wjx.utils.app.config import _HTML_SPACE_RE


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


def _element_contains_text_input(element) -> bool:
    if element is None:
        return False
    try:
        candidates = element.find_all(['input', 'textarea'])
    except Exception:
        return False
    for candidate in candidates:
        try:
            tag_name = (candidate.name or '').lower()
        except Exception:
            tag_name = ''
        input_type = (candidate.get('type') or '').lower()
        if tag_name == 'textarea':
            return True
        if input_type in ('', 'text', 'search', 'tel', 'number'):
            return True
    return False


def _question_div_has_shared_text_input(question_div) -> bool:
    if question_div is None:
        return False
    try:
        shared_inputs = question_div.select('.ui-other input, .ui-other textarea')
    except Exception:
        shared_inputs = []
    if shared_inputs:
        return True
    try:
        keyword_inputs = question_div.select("input[id*='other'], input[name*='other'], textarea[id*='other'], textarea[name*='other']")
        if keyword_inputs:
            return True
    except Exception:
        pass
    text_blob = _normalize_html_text(question_div.get_text(' ', strip=True))
    option_fill_keywords = ["请注明", "其他", "其他内容", "填空", "填写"]
    if any(keyword in text_blob for keyword in option_fill_keywords):
        return True
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
    """优先从评分题的星级锚点提取文本（避免 iconfont 文本）"""
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
    seen = set()
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
            if not text or text in seen:
                continue
            option_index = len(texts)
            texts.append(text)
            seen.add(text)
            if _element_contains_text_input(element):
                fillable_indices.append(option_index)
    if not texts:
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
    except Exception:
        pass
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


def _collect_matrix_option_texts(soup, question_div, question_number: int) -> Tuple[int, List[str], List[str]]:
    option_texts: List[str] = []
    matrix_rows = 0
    row_texts: List[str] = []
    row_text_map: Dict[int, str] = {}
    def _extract_attr_text(node) -> str:
        if node is None:
            return ""
        keys = (
            "title",
            "data-title",
            "data-text",
            "data-label",
            "aria-label",
            "alt",
            "htitle",
            "data-original-title",
        )
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

    def _extract_row_label(row, cells) -> str:
        label_text = ""
        if cells:
            label_text = _normalize_html_text(cells[0].get_text(" ", strip=True))
            if not label_text:
                label_text = _extract_attr_text(cells[0])
        if not label_text:
            label_text = _extract_attr_text(row)
        if not label_text:
            try:
                for selector in (
                    ".label",
                    ".row-title",
                    ".rowtitle",
                    ".row",
                    ".item-title",
                    ".itemTitle",
                    ".itemTitleSpan",
                    ".stitle",
                ):
                    node = row.select_one(selector)
                    if node:
                        label_text = _normalize_html_text(node.get_text(" ", strip=True))
                        if label_text:
                            break
            except Exception:
                pass
        if not label_text:
            try:
                for child in row.find_all(["label", "span", "div", "p"], limit=10):
                    label_text = _extract_attr_text(child)
                    if label_text:
                        break
                    label_text = _normalize_html_text(child.get_text(" ", strip=True))
                    if label_text:
                        break
            except Exception:
                pass
        return label_text
    table = None
    if question_div is not None:
        try:
            table = question_div.find(id=f"divRefTab{question_number}")
        except Exception:
            table = None
    if table is None and soup:
        table = soup.find(id=f"divRefTab{question_number}")
    if table:
        for row in table.find_all("tr"):
            row_index = str(row.get("rowindex") or "").strip()
            if row_index and str(row_index).isdigit():
                matrix_rows += 1
                try:
                    cells = row.find_all(["td", "th"])
                except Exception:
                    cells = []
                if cells:
                    label_text = _extract_row_label(row, cells)
                    if label_text:
                        try:
                            row_text_map[int(row_index)] = label_text
                        except Exception:
                            pass
    if matrix_rows > 0:
        row_texts = [row_text_map.get(idx, "") for idx in range(1, matrix_rows + 1)]
    elif table:
        # 兼容没有 rowindex 的矩阵题：用表格行作为兜底
        data_rows = []
        header_id = f"drv{question_number}_1"
        for row in table.find_all("tr"):
            row_id = str(row.get("id") or "")
            if row_id == header_id:
                continue
            try:
                cells = row.find_all(["td", "th"])
            except Exception:
                cells = []
            if len(cells) <= 1:
                continue
            first_text = _extract_row_label(row, cells)
            other_texts = [_normalize_html_text(cell.get_text(" ", strip=True)) for cell in cells[1:]]
            # 如果首列为空、后面有标题文字，多半是表头行
            if not first_text and any(other_texts):
                continue
            data_rows.append((first_text, cells))
        matrix_rows = len(data_rows)
        row_texts = [label for label, _ in data_rows]
        if not option_texts and data_rows:
            max_cols = 0
            for _, cells in data_rows:
                try:
                    max_cols = max(max_cols, max(0, len(cells) - 1))
                except Exception:
                    continue
            if max_cols > 0:
                option_texts = [str(i + 1) for i in range(max_cols)]
    if matrix_rows == 0 and question_div is not None:
        # 再兜底：从输入控件名推断行列数
        try:
            inputs = question_div.find_all("input")
        except Exception:
            inputs = []
        row_indices: List[int] = []
        col_indices: List[int] = []
        name_pattern = re.compile(rf"q{question_number}[_-](\d+)(?:[_-](\d+))?")
        for item in inputs:
            raw_name = str(item.get("name") or item.get("id") or "")
            if not raw_name:
                continue
            match = name_pattern.search(raw_name)
            if not match:
                continue
            try:
                row_idx = int(match.group(1))
                row_indices.append(row_idx)
            except Exception:
                pass
            if match.group(2):
                try:
                    col_idx = int(match.group(2))
                    col_indices.append(col_idx)
                except Exception:
                    pass
        if row_indices:
            matrix_rows = max(row_indices)
            row_texts = [""] * matrix_rows
        if not option_texts and col_indices:
            max_cols = max(col_indices)
            if max_cols > 0:
                option_texts = [str(i + 1) for i in range(max_cols)]
    if question_div is not None and (not row_texts or any(not text for text in row_texts)):
        try:
            candidates = []
            for selector in (".itemTitleSpan", ".itemTitle", ".item-title", ".row-title"):
                nodes = question_div.select(selector)
                if nodes:
                    candidates = [_normalize_html_text(node.get_text(" ", strip=True)) for node in nodes]
                    candidates = [text for text in candidates if text]
                    if candidates:
                        break
            if candidates:
                if matrix_rows <= 0:
                    matrix_rows = len(candidates)
                    row_texts = list(candidates)
                else:
                    merged: List[str] = list(row_texts)
                    for idx in range(min(len(candidates), len(merged))):
                        if not merged[idx]:
                            merged[idx] = candidates[idx]
                    row_texts = merged
        except Exception:
            pass
    header_row = soup.find(id=f"drv{question_number}_1") if soup else None
    if header_row:
        cells = header_row.find_all("td")
        if len(cells) > 1:
            option_texts = [_normalize_html_text(td.get_text(" ", strip=True)) for td in cells[1:]]
            option_texts = [text for text in option_texts if text]
    if not option_texts and table:
        header_cells = table.find_all("th")
        if len(header_cells) > 1:
            option_texts = [_normalize_html_text(th.get_text(" ", strip=True)) for th in header_cells[1:]]
            option_texts = [text for text in option_texts if text]
    return matrix_rows, option_texts, row_texts


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


def _extract_question_metadata_from_html(soup, question_div, question_number: int, type_code: str):
    option_texts: List[str] = []
    option_count = 0
    matrix_rows = 0
    row_texts: List[str] = []
    fillable_indices: List[int] = []
    if type_code in {"3", "4", "5", "11"}:
        option_texts, fillable_indices = _collect_choice_option_texts(question_div)
        option_count = len(option_texts)
    elif type_code == "7":
        option_texts = _collect_select_option_texts(question_div, soup, question_number)
        option_count = len(option_texts)
        if option_count > 0 and _question_div_has_shared_text_input(question_div):
            fillable_indices = [option_count - 1]
    elif type_code == "6":
        matrix_rows, option_texts, row_texts = _collect_matrix_option_texts(soup, question_div, question_number)
        option_count = len(option_texts)
    elif type_code == "8":
        option_count = 1
    return option_texts, option_count, matrix_rows, row_texts, fillable_indices


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


def _extract_slider_range(question_div, question_number: int) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """尝试解析滑块题的最小值、最大值和步长。"""
    try:
        slider_input = question_div.find("input", id=f"q{question_number}")
        if not slider_input:
            slider_input = question_div.find("input", attrs={"type": "range"})
    except Exception:
        slider_input = None

    def _parse(raw: Any) -> Optional[float]:
        try:
            return float(raw)
        except Exception:
            return None

    if slider_input:
        return (
            _parse(slider_input.get("min")),
            _parse(slider_input.get("max")),
            _parse(slider_input.get("step")),
        )
    return None, None, None


_TEXT_INPUT_ALLOWED_TYPES = {"", "text", "search", "tel", "number"}
_KNOWN_NON_TEXT_QUESTION_TYPES = {"3", "4", "5", "6", "7", "8", "11"}


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
            except Exception:
                pass
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


def _soup_question_looks_like_reorder(question_div) -> bool:
    """兜底判断：通过 DOM 特征识别排序题（静态 HTML）。"""
    if question_div is None:
        return False
    try:
        if question_div.select_one(".sortnum, .sortnum-sel, .order-number, .order-index"):
            return True
    except Exception:
        pass
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


def _soup_question_looks_like_rating(question_div) -> bool:
    """识别评分题（星级评价）"""
    if question_div is None:
        return False
    has_scale_rating = False
    try:
        has_scale_rating = bool(question_div.find(class_="scale-rating"))
    except Exception:
        has_scale_rating = False
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
    if has_scale_rating:
        try:
            has_iconfont = bool(question_div.select_one(".scale-rating .iconfontNew"))
        except Exception:
            has_iconfont = False
    try:
        has_pj = str(question_div.get("pj") or "").strip() == "1"
    except Exception:
        has_pj = False

    # 评分题需要更强特征：仅有量表结构时不判为评分题
    if has_tag_wrap:
        return True
    if has_pj and (has_scale_rating or has_rate_icon or has_iconfont):
        return True
    return False


def _extract_rating_option_count(question_div) -> int:
    """尝试解析评分题的星级数量。"""
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
        except Exception:
            pass
    try:
        options = question_div.select(".scale-rating ul li")
        if options:
            return len(options)
    except Exception:
        pass
    try:
        options = question_div.select("a.rate-off, a.rate-on")
        if options:
            return len(options)
    except Exception:
        pass
    return 0


def _normalize_question_type_code(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value).strip()
    except Exception:
        return ""


def _should_treat_question_as_text_like(type_code: Any, option_count: int, text_input_count: int) -> bool:
    normalized = _normalize_question_type_code(type_code)
    if normalized in ("1", "2"):
        return text_input_count > 0
    if normalized in _KNOWN_NON_TEXT_QUESTION_TYPES:
        return False
    return (option_count or 0) <= 1 and text_input_count > 0


def _should_mark_as_multi_text(type_code: Any, option_count: int, text_input_count: int, is_location: bool) -> bool:
    if is_location or text_input_count < 2:
        return False
    normalized = _normalize_question_type_code(type_code)
    if normalized in ("1", "2"):
        return True
    if normalized in _KNOWN_NON_TEXT_QUESTION_TYPES:
        return False
    if (option_count or 0) == 0:
        return True
    return (option_count or 0) <= 1 and text_input_count >= 2


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
        question_divs = fieldset.find_all("div", attrs={"topic": True}, recursive=False)
        if not question_divs:
            question_divs = fieldset.find_all("div", attrs={"topic": True})
        for question_div in question_divs:
            question_number = _extract_question_number_from_div(question_div)
            if question_number is None:
                continue
            type_code = str(question_div.get("type") or "").strip() or "0"
            if type_code != "11" and _soup_question_looks_like_reorder(question_div):
                type_code = "11"
            is_rating = False
            rating_max = 0
            if type_code == "5":
                is_rating = _soup_question_looks_like_rating(question_div)
                if is_rating:
                    rating_max = _extract_rating_option_count(question_div)
            is_location = type_code in {"1", "2"} and _soup_question_is_location(question_div)
            title_text = _extract_question_title(question_div, question_number)
            option_texts, option_count, matrix_rows, row_texts, fillable_indices = _extract_question_metadata_from_html(
                soup, question_div, question_number, type_code
            )
            if is_rating:
                rating_texts = _extract_rating_option_texts(question_div)
                if rating_texts:
                    option_texts = rating_texts
                option_count = max(option_count, rating_max, len(option_texts))
                if option_count > 0:
                    has_meaningful = any(_text_looks_meaningful(text) for text in option_texts)
                    if not option_texts or not has_meaningful:
                        option_texts = [str(i + 1) for i in range(option_count)]
            has_jump, jump_rules = _extract_jump_rules_from_html(question_div, question_number, option_texts)
            slider_min, slider_max, slider_step = (None, None, None)
            if type_code == "8":
                slider_min, slider_max, slider_step = _extract_slider_range(question_div, question_number)
            text_input_count = _count_text_inputs_in_soup(question_div)
            is_text_like_question = _should_treat_question_as_text_like(type_code, option_count, text_input_count)
            is_multi_text = _should_mark_as_multi_text(type_code, option_count, text_input_count, is_location)
            questions_info.append({
                "num": question_number,
                "title": title_text,
                "type_code": type_code,
                "options": option_count,
                "rows": matrix_rows,
                "row_texts": row_texts,
                "page": page_index,
                "option_texts": option_texts,
                "fillable_options": fillable_indices,
                "is_location": is_location,
                "is_rating": is_rating,
                "rating_max": rating_max,
                "text_inputs": text_input_count,
                "is_multi_text": is_multi_text,
                "is_text_like": is_text_like_question,
                "has_jump": has_jump,
                "jump_rules": jump_rules,
                "slider_min": slider_min,
                "slider_max": slider_max,
                "slider_step": slider_step,
            })
    return questions_info

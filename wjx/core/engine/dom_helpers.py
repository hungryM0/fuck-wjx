import re
from typing import List, Optional, Tuple

from wjx.network.browser_driver import By, BrowserDriver


_TEXT_INPUT_ALLOWED_TYPES = {"", "text", "search", "tel", "number"}
_KNOWN_NON_TEXT_QUESTION_TYPES = {"3", "4", "5", "6", "7", "8", "11"}


def _driver_element_contains_text_input(element) -> bool:
    if element is None:
        return False
    try:
        inputs = element.find_elements(By.CSS_SELECTOR, "input, textarea")
    except Exception:
        return False
    for candidate in inputs:
        try:
            tag_name = (candidate.tag_name or "").lower()
        except Exception:
            tag_name = ""
        input_type = ""
        try:
            input_type = (candidate.get_attribute("type") or "").lower()
        except Exception:
            input_type = ""
        if tag_name == "textarea":
            return True
        if tag_name == "input" and input_type in ("", "text", "search", "tel", "number"):
            return True
    return False


def _driver_question_has_shared_text_input(question_div) -> bool:
    if question_div is None:
        return False
    try:
        shared = question_div.find_elements(By.CSS_SELECTOR, ".ui-other input, .ui-other textarea")
        if shared:
            return True
    except Exception:
        pass
    try:
        keyword_elements = question_div.find_elements(By.CSS_SELECTOR, "input[id*='other'], textarea[id*='other']")
        if keyword_elements:
            return True
    except Exception:
        pass
    try:
        text_blob = (question_div.text or "").strip()
    except Exception:
        text_blob = ""
    if not text_blob:
        return False
    option_fill_keywords = ["请注明", "其他", "填空", "填写", "specify", "other"]
    return any(keyword in text_blob for keyword in option_fill_keywords)


def _verify_text_indicates_location(value: Optional[str]) -> bool:
    if not value:
        return False
    text = str(value).strip()
    if not text:
        return False
    return ("地图" in text) or ("map" in text.lower())


def _driver_question_looks_like_reorder(question_div) -> bool:
    """兜底判断：当 type 属性异常/缺失时，尝试通过 DOM 特征识别排序题。"""
    if question_div is None:
        return False
    try:
        if question_div.find_elements(By.CSS_SELECTOR, ".sortnum, .sortnum-sel"):
            return True
    except Exception:
        pass
    try:
        # 仅作为兜底：需要同时满足“存在列表项”与“具备排序/拖拽特征”，避免误判普通题型
        has_list_items = bool(question_div.find_elements(By.CSS_SELECTOR, "ul li, ol li"))
        has_sort_signature = bool(
            question_div.find_elements(By.CSS_SELECTOR, ".ui-sortable, .ui-sortable-handle, [class*='sort']")
        )
        return has_list_items and has_sort_signature
    except Exception:
        return False


def _driver_question_looks_like_numeric_scale(question_div) -> bool:
    """检测数字刻度/NPS 量表，避免被误判为星级评价。"""
    if question_div is None:
        return False
    try:
        anchors = question_div.find_elements(By.CSS_SELECTOR, "ul[tp='d'] li a, .scale-rating ul li a, .scale-rating a[val]")
    except Exception:
        anchors = []
    texts: List[str] = []
    for anchor in anchors:
        try:
            text = (anchor.text or "").strip()
        except Exception:
            text = ""
        if not text:
            for attr in ("title", "aria-label", "val", "value"):
                try:
                    raw = anchor.get_attribute(attr) or ""
                except Exception:
                    raw = ""
                if raw:
                    text = str(raw).strip()
                    if text:
                        break
        if text:
            texts.append(text)
    if not texts:
        return False
    numeric_count = sum(1 for t in texts if re.fullmatch(r"\d{1,2}", t))
    try:
        has_scale_title = bool(question_div.find_elements(By.CSS_SELECTOR, ".scaleTitle, .scaleTitle_frist, .scaleTitle_last, .scaleTitleFirst, .scaleTitleLast"))
    except Exception:
        has_scale_title = False
    total = len(texts)
    return total >= 5 and numeric_count >= max(3, int(total * 0.7)) and (total >= 9 or has_scale_title)


def _driver_question_looks_like_rating(question_div) -> bool:
    """兜底判断：通过 DOM 特征识别评价题（星级评价）。"""
    if question_div is None:
        return False
    if _driver_question_looks_like_numeric_scale(question_div):
        return False
    has_rate_icon = False
    try:
        has_rate_icon = bool(question_div.find_elements(By.CSS_SELECTOR, "a.rate-off, a.rate-on, .rate-off, .rate-on"))
    except Exception:
        has_rate_icon = False
    has_tag_wrap = False
    try:
        has_tag_wrap = bool(question_div.find_elements(By.CSS_SELECTOR, ".evaluateTagWrap"))
    except Exception:
        has_tag_wrap = False
    has_iconfont = False
    try:
        has_iconfont = bool(question_div.find_elements(By.CSS_SELECTOR, ".scale-rating .iconfontNew, .iconfontNew"))
    except Exception:
        has_iconfont = False

    if has_tag_wrap:
        return True
    if has_rate_icon or has_iconfont:
        return True
    return False



def _count_choice_inputs_driver(question_div) -> Tuple[int, int]:
    try:
        inputs = question_div.find_elements(By.CSS_SELECTOR, "input[type='checkbox'], input[type='radio']")
    except Exception:
        inputs = []
    checkbox_count = 0
    radio_count = 0
    for ipt in inputs:
        try:
            input_type = (ipt.get_attribute("type") or "").lower()
        except Exception:
            input_type = ""
        try:
            style_text = (ipt.get_attribute("style") or "").lower()
        except Exception:
            style_text = ""
        if input_type == "hidden" or "display:none" in style_text or "visibility:hidden" in style_text:
            continue
        try:
            if not ipt.is_displayed():
                continue
        except Exception:
            pass
        if input_type == "checkbox":
            checkbox_count += 1
        elif input_type == "radio":
            radio_count += 1
    return checkbox_count, radio_count



def _extract_select_options(driver: BrowserDriver, question_number: int):
    try:
        select_element = driver.find_element(By.CSS_SELECTOR, f"#q{question_number}")
    except Exception:
        return None, []
    try:
        option_elements = select_element.find_elements(By.CSS_SELECTOR, "option")
    except Exception:
        option_elements = []
    valid_options: List[Tuple[str, str]] = []
    for idx, opt in enumerate(option_elements):
        try:
            value = (opt.get_attribute("value") or "").strip()
        except Exception:
            value = ""
        try:
            text = (opt.text or "").strip()
        except Exception:
            text = ""
        if idx == 0 and ((value == "") or (value == "0") or ("请选择" in text)):
            continue
        if not text and not value:
            continue
        valid_options.append((value, text or value))
    return select_element, valid_options


def _select_dropdown_option_via_js(
    driver: BrowserDriver, select_element, option_value: str, display_text: str
) -> bool:
    try:
        applied = driver.execute_script(
            """
const select = arguments[0];
const optionValue = arguments[1];
const displayText = arguments[2];
if (!select) { return false; }
const opts = Array.from(select.options || []);
const target = opts.find(o => (o.value || '') == optionValue);
if (!target) { return false; }
target.selected = true;
select.value = target.value;
try { select.setAttribute('value', target.value); } catch (e) {}
['input','change'].forEach(name => {
    try { select.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
});
const span = document.getElementById(`select2-${select.id}-container`);
if (span) {
    span.textContent = displayText || target.textContent || target.innerText || '';
    span.title = span.textContent;
}
return true;
            """,
            select_element,
            option_value or "",
            display_text or "",
        )
    except Exception:
        applied = False
    return bool(applied)

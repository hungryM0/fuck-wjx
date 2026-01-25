"""填空题/多项填空题处理"""
import time
from typing import Any, List, Optional, Set

from wjx.network.browser_driver import By, BrowserDriver
from wjx.utils.app.config import DEFAULT_FILL_TEXT
from wjx.core.questions.utils import (
    weighted_index,
    normalize_probabilities,
    resolve_dynamic_text_token,
    smooth_scroll_to_element,
)
from wjx.core.ai.runtime import AIRuntimeError, generate_ai_answer, resolve_question_title_for_ai

# 多项填空题分隔符
MULTI_TEXT_DELIMITER = "||"


def fill_text_question_input(driver: BrowserDriver, element, value: Optional[Any]) -> None:
    """填充单/多行文本题"""
    raw_text = "" if value is None else str(value)
    try:
        read_only_attr = element.get_attribute("readonly") or ""
    except Exception:
        read_only_attr = ""
    is_readonly = bool(read_only_attr)

    if not is_readonly:
        try:
            element.clear()
        except Exception:
            pass
        element.send_keys(raw_text)
        return

    driver.execute_script(
        """
        const input = arguments[0];
        const value = arguments[1];
        if (!input) {
            return;
        }
        try {
            input.value = value;
        } catch (err) {}
        const eventOptions = { bubbles: true };
        try {
            input.dispatchEvent(new Event('input', eventOptions));
        } catch (err) {}
        try {
            input.dispatchEvent(new Event('change', eventOptions));
        } catch (err) {}
        """,
        element,
        raw_text,
    )


def fill_contenteditable_element(driver: BrowserDriver, element, value: str) -> None:
    """在可编辑的 span/div 上模拟"点击-输入-派发事件"的行为，并同步隐藏输入框"""
    text_value = value if value else DEFAULT_FILL_TEXT
    try:
        driver.execute_script(
            """
            const el = arguments[0];
            if (!el) { return; }
            try { el.focus(); } catch (err) {}
            if (window.getSelection && document.createRange) {
                const sel = window.getSelection();
                const range = document.createRange();
                try {
                    range.selectNodeContents(el);
                    sel.removeAllRanges();
                    sel.addRange(range);
                } catch (err) {}
            }
            if (document.execCommand) {
                try { document.execCommand('delete'); } catch (err) {}
            }
            try { el.innerText = ''; } catch (err) { el.textContent = ''; }
            """,
            element,
        )
    except Exception:
        pass

    typed_successfully = False
    try:
        element.send_keys(text_value)
        typed_successfully = True
    except Exception:
        typed_successfully = False

    driver.execute_script(
        """
        const el = arguments[0];
        const value = arguments[1];
        const typed = !!arguments[2];
        if (!el) {
            return;
        }
        if (!typed) {
            try { el.innerText = value; } catch (err) { el.textContent = value; }
        }
        const eventOptions = { bubbles: true };
        ['input','change','blur','keyup','keydown','keypress'].forEach(name => {
            try { el.dispatchEvent(new Event(name, eventOptions)); } catch (err) {}
        });
        const container = el.closest ? el.closest('.textEdit') : null;
        let hiddenInput = null;
        if (container) {
            hiddenInput = container.querySelector('input[type="text"], input[type="hidden"]');
            if (!hiddenInput) {
                hiddenInput = container.previousElementSibling;
            }
        }
        if (hiddenInput && hiddenInput.tagName && (hiddenInput.type === 'text' || hiddenInput.type === 'hidden')) {
            try {
                hiddenInput.value = value;
                hiddenInput.setAttribute('value', value);
            } catch (err) {}
            ['input','change','blur','keyup','keydown','keypress'].forEach(name => {
                try { hiddenInput.dispatchEvent(new Event(name, eventOptions)); } catch (err) {}
            });
        }
        """,
        element,
        text_value,
        typed_successfully,
    )


def count_prefixed_text_inputs(driver: BrowserDriver, question_number: int, question_div=None) -> int:
    """Count inputs like q{num}_1 used by gap-fill/multi-text questions."""
    if not question_number:
        return 0
    prefix = f"q{question_number}_"
    selector = (
        f"input[id^='{prefix}'], textarea[id^='{prefix}'], "
        f"input[name^='{prefix}'], textarea[name^='{prefix}']"
    )
    try:
        if question_div is not None:
            elements = question_div.find_elements(By.CSS_SELECTOR, selector)
        else:
            elements = driver.find_elements(By.CSS_SELECTOR, f"#div{question_number} {selector}")
    except Exception:
        return 0
    return len(elements)


def count_visible_text_inputs(question_div) -> int:
    """统计可见的文本输入框数量"""
    _TEXT_INPUT_ALLOWED_TYPES = {"", "text", "search", "tel", "number"}
    try:
        candidates = question_div.find_elements(
            By.CSS_SELECTOR,
            "input, textarea, span[contenteditable='true'], div[contenteditable='true'], .textCont, .textcont"
        )
    except Exception:
        candidates = []
    count = 0
    for cand in candidates:
        try:
            tag_name = (cand.tag_name or "").lower()
        except Exception:
            tag_name = ""
        input_type = ""
        try:
            input_type = (cand.get_attribute("type") or "").lower()
        except Exception:
            input_type = ""
        try:
            style_text = (cand.get_attribute("style") or "").lower()
        except Exception:
            style_text = ""
        try:
            class_attr = (cand.get_attribute("class") or "").lower()
        except Exception:
            class_attr = ""
        is_textcont = "textcont" in class_attr or "textedit" in class_attr

        if input_type == "hidden" or "display:none" in style_text or "visibility:hidden" in style_text:
            continue
        if tag_name == "input":
            try:
                sibling = cand.find_element(By.XPATH, "following-sibling::*[1]")
                sibling_tag = (sibling.tag_name or "").lower()
                sibling_class = (sibling.get_attribute("class") or "").lower()
                if sibling_tag in {"label", "div", "span"} and "textedit" in sibling_class:
                    continue
            except Exception:
                pass

        if tag_name == "textarea" or (tag_name == "input" and input_type in _TEXT_INPUT_ALLOWED_TYPES):
            try:
                if cand.is_displayed():
                    count += 1
            except Exception:
                count += 1
            continue
        try:
            contenteditable = (cand.get_attribute("contenteditable") or "").lower() == "true"
        except Exception:
            contenteditable = False
        if (contenteditable or is_textcont) and tag_name in {"span", "div"}:
            try:
                if cand.is_displayed():
                    count += 1
            except Exception:
                count += 1
    return count


def infer_text_entry_type(driver: BrowserDriver, question_number: int) -> tuple:
    """推断填空题类型和默认答案"""
    try:
        q_div = driver.find_element(By.CSS_SELECTOR, f"#div{question_number}")
    except Exception:
        q_div = None
    text_input_count = count_visible_text_inputs(q_div) if q_div is not None else 0
    prefixed_text_count = count_prefixed_text_inputs(driver, question_number, q_div)
    
    # 检测是否为位置题
    is_location_question = driver_question_is_location(q_div) if q_div is not None else False
    has_multi_text_signature = prefixed_text_count > 0
    is_multi = should_mark_as_multi_text("1", 0, text_input_count, is_location_question)
    if not is_multi and has_multi_text_signature and not is_location_question:
        is_multi = True
    if is_multi:
        blanks_hint = prefixed_text_count if prefixed_text_count > 0 else text_input_count
        blanks = max(1, blanks_hint or 1)
        if not has_multi_text_signature:
            blanks = max(2, blanks)
        default_answer = MULTI_TEXT_DELIMITER.join([DEFAULT_FILL_TEXT] * blanks)
        return "multi_text", [default_answer]
    return "text", [DEFAULT_FILL_TEXT]


def driver_question_is_location(question_div) -> bool:
    """检测是否为位置题"""
    if question_div is None:
        return False
    try:
        local_elements = question_div.find_elements(By.CSS_SELECTOR, ".get_Local")
        if local_elements:
            return True
    except Exception:
        pass
    try:
        inputs = question_div.find_elements(By.CSS_SELECTOR, "input[verify], .get_Local input, input")
    except Exception:
        inputs = []
    for input_element in inputs:
        try:
            verify_value = input_element.get_attribute("verify")
        except Exception:
            verify_value = None
        if verify_value and (("地图" in str(verify_value)) or ("map" in str(verify_value).lower())):
            return True
    return False


def should_mark_as_multi_text(type_code: Any, option_count: int, text_input_count: int, is_location: bool) -> bool:
    """判断是否应标记为多项填空题"""
    _KNOWN_NON_TEXT_QUESTION_TYPES = {"3", "4", "5", "6", "7", "8", "11"}
    if is_location or text_input_count < 2:
        return False
    normalized = str(type_code).strip() if type_code is not None else ""
    if normalized in ("1", "2"):
        return True
    if normalized in _KNOWN_NON_TEXT_QUESTION_TYPES:
        return False
    if (option_count or 0) == 0:
        return True
    return (option_count or 0) <= 1 and text_input_count >= 2


def should_treat_as_text_like(type_code: Any, option_count: int, text_input_count: int) -> bool:
    """判断是否应视为填空类题型"""
    _KNOWN_NON_TEXT_QUESTION_TYPES = {"3", "4", "5", "6", "7", "8", "11"}
    normalized = str(type_code).strip() if type_code is not None else ""
    if normalized in ("1", "2"):
        return text_input_count > 0
    if normalized in _KNOWN_NON_TEXT_QUESTION_TYPES:
        return False
    return (option_count or 0) <= 1 and text_input_count > 0


def vacant(
    driver: BrowserDriver,
    current: int,
    index: int,
    texts_config: List[List[str]],
    texts_prob_config: List[List[float]],
    text_entry_types_config: List[str],
    text_ai_flags: Optional[List[bool]] = None,
    text_titles: Optional[List[str]] = None,
) -> None:
    """填空题处理主函数"""
    if index < len(texts_config):
        answer_candidates = texts_config[index]
        selection_probabilities = texts_prob_config[index] if index < len(texts_prob_config) else [1.0]
        entry_kind = text_entry_types_config[index] if index < len(text_entry_types_config) else "text"
    else:
        entry_kind, answer_candidates = infer_text_entry_type(driver, current)
        selection_probabilities = normalize_probabilities([1.0] * len(answer_candidates)) if answer_candidates else [1.0]

    if not answer_candidates:
        answer_candidates = [DEFAULT_FILL_TEXT]
    if len(selection_probabilities) != len(answer_candidates):
        selection_probabilities = normalize_probabilities([1.0] * len(answer_candidates))
    resolved_candidates = []
    for candidate in answer_candidates:
        try:
            text_value = resolve_dynamic_text_token(candidate)
        except Exception:
            text_value = DEFAULT_FILL_TEXT
        resolved_candidates.append(text_value if text_value else DEFAULT_FILL_TEXT)

    if len(selection_probabilities) != len(resolved_candidates):
        selection_probabilities = normalize_probabilities([1.0] * len(resolved_candidates))

    if entry_kind != "multi_text":
        prefixed_text_count = count_prefixed_text_inputs(driver, current)
        if prefixed_text_count > 0:
            entry_kind = "multi_text"

    ai_enabled = False
    if text_ai_flags and index < len(text_ai_flags):
        ai_enabled = bool(text_ai_flags[index])
    fallback_title = ""
    if text_titles and index < len(text_titles):
        fallback_title = str(text_titles[index] or "")

    if entry_kind == "text" and ai_enabled:
        try:
            title = resolve_question_title_for_ai(driver, current, fallback_title)
            selected_answer = generate_ai_answer(title)
        except AIRuntimeError as exc:
            raise AIRuntimeError(f"第{current}题 AI 生成失败：{exc}") from exc
        _handle_single_text(driver, current, selected_answer)
        return

    selected_index = weighted_index(selection_probabilities)
    selected_answer = resolved_candidates[selected_index] if resolved_candidates else DEFAULT_FILL_TEXT

    if entry_kind == "multi_text":
        _handle_multi_text(driver, current, selected_answer)
        return

    _handle_single_text(driver, current, selected_answer)


def _handle_multi_text(driver: BrowserDriver, current: int, selected_answer: str) -> None:
    """处理多项填空题"""
    raw_text = "" if selected_answer is None else str(selected_answer)
    if MULTI_TEXT_DELIMITER in raw_text:
        parts = raw_text.split(MULTI_TEXT_DELIMITER)
    elif "|" in raw_text:
        parts = raw_text.split("|")
    else:
        parts = [raw_text]
    values = [part.strip() for part in parts]

    if not values or all(not v for v in values):
        values = [DEFAULT_FILL_TEXT]

    primary_inputs: List[Any] = []
    secondary_inputs: List[Any] = []
    seen_nodes: Set[int] = set()
    question_div = None
    try:
        question_div = driver.find_element(By.CSS_SELECTOR, f"#div{current}")
        candidates = question_div.find_elements(By.CSS_SELECTOR, "input, textarea")
    except Exception:
        candidates = []

    def _mark_and_append(target_list: List[Any], node: Any):
        obj_id = id(node)
        if obj_id in seen_nodes:
            return
        seen_nodes.add(obj_id)
        target_list.append(node)

    _TEXT_INPUT_ALLOWED_TYPES = {"", "text", "search", "tel", "number"}

    def _collect_text_inputs(cands: List[Any]):
        for candidate in cands:
            try:
                tag_name = (candidate.tag_name or "").lower()
            except Exception:
                tag_name = ""
            try:
                input_type = (candidate.get_attribute("type") or "").lower()
            except Exception:
                input_type = ""
            try:
                contenteditable_attr = (candidate.get_attribute("contenteditable") or "").lower()
            except Exception:
                contenteditable_attr = ""
            try:
                class_attr = (candidate.get_attribute("class") or "").lower()
            except Exception:
                class_attr = ""
            is_contenteditable = (contenteditable_attr == "true") or ("textcont" in class_attr and tag_name in {"span", "div"})

            if is_contenteditable and tag_name in {"span", "div"}:
                _mark_and_append(primary_inputs, candidate)
                continue

            if tag_name == "textarea" or (tag_name == "input" and input_type in _TEXT_INPUT_ALLOWED_TYPES):
                try:
                    displayed = candidate.is_displayed()
                except Exception:
                    displayed = True
                if input_type == "hidden":
                    _mark_and_append(secondary_inputs, candidate)
                    continue
                if displayed:
                    _mark_and_append(primary_inputs, candidate)
                    continue
                _mark_and_append(secondary_inputs, candidate)

    _collect_text_inputs(candidates)

    if question_div:
        try:
            editable_nodes = question_div.find_elements(By.CSS_SELECTOR, "span[contenteditable='true'], div[contenteditable='true'], .textCont")
        except Exception:
            editable_nodes = []
        _collect_text_inputs(editable_nodes)

    if question_div and (len(primary_inputs) + len(secondary_inputs)) < 2:
        try:
            fallback_candidates = question_div.find_elements(By.CSS_SELECTOR, f"input[id^='q{current}_'], textarea[id^='q{current}_']")
        except Exception:
            fallback_candidates = []
        _collect_text_inputs(fallback_candidates)

    if not primary_inputs and not secondary_inputs:
        try:
            primary_inputs = [driver.find_element(By.CSS_SELECTOR, f"#q{current}")]
        except Exception:
            primary_inputs = []

    input_elements = primary_inputs + secondary_inputs if primary_inputs else secondary_inputs
    visible_count = len(primary_inputs) if primary_inputs else len(input_elements)

    fill_values = [v if v else DEFAULT_FILL_TEXT for v in values] or [DEFAULT_FILL_TEXT]
    while len(fill_values) < visible_count:
        fill_values.append(DEFAULT_FILL_TEXT)

    def _resolve_value_for_index(idx: int) -> str:
        if idx < visible_count:
            return fill_values[idx] if idx < len(fill_values) else DEFAULT_FILL_TEXT
        rel = idx - visible_count
        if rel < len(fill_values):
            return fill_values[rel]
        return fill_values[-1] if fill_values else DEFAULT_FILL_TEXT

    for idx_input, element in enumerate(input_elements):
        value = _resolve_value_for_index(idx_input)
        if not value:
            value = DEFAULT_FILL_TEXT
        try:
            tag_name = (element.tag_name or "").lower()
        except Exception:
            tag_name = ""
        if tag_name in {"span", "div"}:
            try:
                smooth_scroll_to_element(driver, element, 'center')
            except Exception:
                pass
            try:
                element.click()
            except Exception:
                pass
            fill_contenteditable_element(driver, element, value)
        else:
            fill_text_question_input(driver, element, value)

    try:
        sync_values = fill_values if fill_values else [DEFAULT_FILL_TEXT]
        sync_count = max(len(sync_values), len(input_elements), visible_count)
        for idx_value in range(sync_count):
            val = sync_values[idx_value] if idx_value < len(sync_values) else (sync_values[-1] if sync_values else DEFAULT_FILL_TEXT)
            driver.execute_script(
                """
                const id = arguments[0];
                const value = arguments[1];
                const el = document.getElementById(id);
                if (!el) return;
                try { el.value = value; } catch (e) {}
                try { el.setAttribute('value', value); } catch (e) {}
                ['input','change','blur','keyup','keydown','keypress'].forEach(name => {
                    try { el.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
                });
                """,
                f"q{current}_{idx_value + 1}",
                val or DEFAULT_FILL_TEXT,
            )
    except Exception:
        pass

    try:
        driver.execute_script(
            """
            return (function() {
                const qid = arguments[0];
                const container = document.getElementById(qid);
                if (!container) return false;
                const inputs = container.querySelectorAll('input, textarea, [contenteditable=\"true\"], .textCont, .textcont');
                const events = ['input','change','blur','keyup','keydown'];
                inputs.forEach(el => {
                    events.forEach(name => {
                        try { el.dispatchEvent(new Event(name, { bubbles: true })); } catch (_) {}
                    });
                });
                return true;
            })();
            """,
            f"div{current}"
        )
    except Exception:
        pass


def _handle_single_text(driver: BrowserDriver, current: int, selected_answer: str) -> None:
    """处理单项填空题"""
    filled = False
    question_div = None
    try:
        input_element = driver.find_element(By.CSS_SELECTOR, f"#q{current}")
        fill_text_question_input(driver, input_element, selected_answer)
        filled = True
    except Exception:
        try:
            question_div = driver.find_element(By.CSS_SELECTOR, f"#div{current}")
            candidates = question_div.find_elements(By.CSS_SELECTOR, "input, textarea")
        except Exception:
            candidates = []
        _TEXT_INPUT_ALLOWED_TYPES = {"", "text", "search", "tel", "number"}
        for candidate in candidates:
            try:
                tag_name = (candidate.tag_name or "").lower()
            except Exception:
                tag_name = ""
            input_type = ""
            try:
                input_type = (candidate.get_attribute("type") or "").lower()
            except Exception:
                input_type = ""
            try:
                style_attr = (candidate.get_attribute("style") or "").lower()
            except Exception:
                style_attr = ""
            try:
                displayed = candidate.is_displayed()
            except Exception:
                displayed = True
            if (
                input_type == "hidden"
                or "display:none" in style_attr
                or "visibility:hidden" in style_attr
                or not displayed
            ):
                continue
            if tag_name == "textarea" or (tag_name == "input" and input_type in _TEXT_INPUT_ALLOWED_TYPES):
                fill_text_question_input(driver, candidate, selected_answer)
                filled = True
                break

    if not filled and question_div is None:
        try:
            question_div = driver.find_element(By.CSS_SELECTOR, f"#div{current}")
        except Exception:
            question_div = None

    if not filled and question_div is not None:
        try:
            editable_nodes = question_div.find_elements(
                By.CSS_SELECTOR,
                "span[contenteditable='true'], div[contenteditable='true'], .textCont, .textcont"
            )
        except Exception:
            editable_nodes = []
        for editable in editable_nodes:
            try:
                if not editable.is_displayed():
                    continue
            except Exception:
                pass
            try:
                smooth_scroll_to_element(driver, editable, 'center')
            except Exception:
                pass
            try:
                editable.click()
            except Exception:
                pass
            try:
                fill_value = DEFAULT_FILL_TEXT if selected_answer is None else str(selected_answer)
                fill_contenteditable_element(driver, editable, fill_value)
                filled = True
                break
            except Exception:
                continue

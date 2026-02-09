"""下拉题处理"""
import time
from typing import Any, List, Optional, Tuple, Union

from wjx.network.browser_driver import By, BrowserDriver
from wjx.core.persona.context import apply_persona_boost, record_answer
from wjx.core.questions.utils import (
    weighted_index,
    normalize_droplist_probs,
    get_fill_text_from_config,
    fill_option_additional_text,
)
from wjx.core.stats.collector import stats_collector


def _extract_select_options(driver: BrowserDriver, question_number: int) -> Tuple[Any, List[Tuple[str, str]]]:
    """提取下拉框选项"""
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


def _select_dropdown_option_via_js(driver: BrowserDriver, select_element, option_value: str, display_text: str) -> bool:
    """通过JS选择下拉选项"""
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


def _fill_droplist_via_click(driver: BrowserDriver, current: int, prob_config: Union[List[float], int, None], fill_entries: Optional[List[Optional[str]]]) -> None:
    """通过点击方式填充下拉框"""
    container_selectors = [
        f"#select2-q{current}-container",
        f"#div{current} .select2-selection__rendered",
        f"#div{current} .select2-selection--single",
        f"#div{current} .ui-select",
    ]
    clicked = False
    for selector in container_selectors:
        try:
            element = driver.find_element(By.CSS_SELECTOR, selector)
            element.click()
            clicked = True
            break
        except Exception:
            continue
    if not clicked:
        return
    time.sleep(0.1)
    options: List[Any] = []
    for _ in range(5):
        options = driver.find_elements(By.XPATH, f"//*[@id='select2-q{current}-results']/li")
        if not options:
            options = driver.find_elements(By.CSS_SELECTOR, ".select2-results__options li")
        visible_options: List[Any] = []
        for opt in options:
            try:
                if hasattr(opt, "is_displayed") and not opt.is_displayed():
                    continue
            except Exception:
                continue
            visible_options.append(opt)
        options = visible_options
        if options:
            break
        time.sleep(0.15)
    if not options:
        return
    filtered_options: List[Tuple[int, Any, str]] = []
    for idx, opt in enumerate(options):
        try:
            text = (opt.text or "").strip()
        except Exception:
            text = ""
        if idx == 0 and (text == "" or "请选择" in text):
            continue
        filtered_options.append((idx, opt, text))
    option_count = len(filtered_options)
    if option_count <= 0:
        return
    probabilities = normalize_droplist_probs(prob_config, option_count)
    # 画像约束：对匹配画像的选项加权
    click_option_texts = [text for _, _, text in filtered_options]
    probabilities = apply_persona_boost(click_option_texts, probabilities)
    selected_idx = weighted_index(probabilities)
    _, selected_option, selected_text = filtered_options[selected_idx]
    try:
        selected_option.click()
    except Exception:
        return
    # 记录统计数据
    stats_collector.record_dropdown_choice(current, selected_idx)
    # 记录作答上下文
    record_answer(current, "dropdown", selected_indices=[selected_idx], selected_texts=[selected_text])
    fill_value = get_fill_text_from_config(fill_entries, selected_idx)
    fill_option_additional_text(driver, current, selected_idx, fill_value)


def droplist(driver: BrowserDriver, current: int, index: int, droplist_prob_config: List, droplist_option_fill_texts_config: List) -> None:
    """下拉题处理主函数"""
    prob_config = droplist_prob_config[index] if index < len(droplist_prob_config) else -1
    fill_entries = droplist_option_fill_texts_config[index] if index < len(droplist_option_fill_texts_config) else None
    select_element, select_options = _extract_select_options(driver, current)
    if select_options:
        probabilities = normalize_droplist_probs(prob_config, len(select_options))
        # 画像约束：对匹配画像的选项加权
        option_texts = [text for _, text in select_options]
        probabilities = apply_persona_boost(option_texts, probabilities)
        selected_idx = weighted_index(probabilities)
        selected_value, selected_text = select_options[selected_idx]
        if _select_dropdown_option_via_js(driver, select_element, selected_value, selected_text):
            # 记录统计数据
            stats_collector.record_dropdown_choice(current, selected_idx)
            # 记录作答上下文
            record_answer(current, "dropdown", selected_indices=[selected_idx], selected_texts=[selected_text])
            fill_value = get_fill_text_from_config(fill_entries, selected_idx)
            fill_option_additional_text(driver, current, selected_idx, fill_value)
            return
    _fill_droplist_via_click(driver, current, prob_config, fill_entries)

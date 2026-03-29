"""单选题处理"""
from typing import Any, List, Optional, Set, Tuple
import logging
from software.logging.log_utils import log_suppressed_exception


from software.network.browser import By, BrowserDriver
from software.core.persona.context import apply_persona_boost, record_answer
from software.core.questions.distribution import (
    record_pending_distribution_choice,
    resolve_distribution_probabilities,
)
from software.core.questions.consistency import (
    apply_single_like_consistency,
)
from software.core.questions.strict_ratio import is_strict_ratio_question
from software.core.questions.strict_ratio import enforce_reference_rank_order
from software.core.questions.utils import (
    weighted_index,
    normalize_droplist_probs,
    resolve_option_fill_text_from_config,
    fill_option_additional_text,
    extract_text_from_element,
    smooth_scroll_to_element,
)
from software.app.config import DEFAULT_FILL_TEXT


def _looks_like_single_option(element: Any) -> bool:
    """判断节点是否像一个真实的单选选项容器。"""
    try:
        class_name = (element.get_attribute("class") or "").lower()
    except Exception:
        class_name = ""
    if "ui-radio" in class_name:
        return True
    try:
        input_type = (element.get_attribute("type") or "").lower()
    except Exception:
        input_type = ""
    if input_type == "radio":
        return True
    try:
        if element.find_elements(By.CSS_SELECTOR, "input[type='radio'], .jqradio, a.jqradio, .jqradiowrapper"):
            return True
    except Exception:
        pass
    return False


def _is_single_option_selected(driver: BrowserDriver, target_elem: Any) -> bool:
    """校验指定选项是否已经被选中。"""
    try:
        selected = driver.execute_script(
            """
            const el = arguments[0];
            if (!el) return false;
            const isRadio = (typeof el.matches === 'function') && el.matches("input[type='radio']");
            const radio = isRadio ? el : (el.querySelector ? el.querySelector("input[type='radio']") : null);
            if (radio) return !!radio.checked;
            if (el.classList && (el.classList.contains('checked') || el.classList.contains('on'))) return true;
            const marked = el.querySelector
                ? el.querySelector(".jqradio.checked, .jqradio.jqchecked, .ui-radio.checked, .ui-radio.on")
                : null;
            return !!marked;
            """,
            target_elem,
        )
        return bool(selected)
    except Exception as exc:
        log_suppressed_exception("single: _is_single_option_selected", exc, level=logging.ERROR)
        return False


def _extract_single_option_text(element: Any) -> str:
    if element is None:
        return ""
    try:
        label_candidates = element.find_elements(By.CSS_SELECTOR, ".label, label")
    except Exception:
        label_candidates = []
    for candidate in label_candidates:
        text = extract_text_from_element(candidate).strip()
        if text:
            return text
    return extract_text_from_element(element).strip()


def _single_option_has_free_text_input(target_elem: Any) -> bool:
    """判断单选项是否带有真正的“其他请填空”输入框，而不是嵌入式下拉。"""
    if target_elem is None:
        return False
    try:
        if target_elem.find_elements(By.CSS_SELECTOR, "select"):
            return False
    except Exception:
        pass
    try:
        candidates = target_elem.find_elements(
            By.CSS_SELECTOR,
            "input.OtherRadioText, input[type='text'], input[type='search'], input[type='tel'], input[type='number'], textarea",
        )
    except Exception as exc:
        log_suppressed_exception("single: detect free text input", exc, level=logging.ERROR)
        return False
    for candidate in candidates:
        try:
            input_type = (candidate.get_attribute("type") or "").lower()
        except Exception:
            input_type = ""
        if input_type == "hidden":
            continue
        try:
            class_name = (candidate.get_attribute("class") or "").lower()
        except Exception:
            class_name = ""
        if "cusomselect" in class_name or "customselect" in class_name:
            continue
        return True
    return False


def _click_single_option(driver: BrowserDriver, current: int, selected_option: int, target_elem: Any) -> bool:
    """稳健点击单选项：点击后必须验收是否真正选中。"""
    click_candidates: List[Any] = []
    if target_elem is not None:
        click_candidates.append(target_elem)
        try:
            click_candidates.extend(
                target_elem.find_elements(
                    By.CSS_SELECTOR, ".label, label, .jqradio, a.jqradio, .jqradiowrapper, input[type='radio']"
                )
            )
        except Exception as exc:
            log_suppressed_exception("single: collect click candidates", exc, level=logging.ERROR)

    seen: Set[Any] = set()
    for candidate in click_candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            smooth_scroll_to_element(driver, candidate, "center")
        except Exception as exc:
            log_suppressed_exception("single: smooth_scroll_to_element click candidate", exc, level=logging.ERROR)
        try:
            candidate.click()
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", candidate)
            except Exception as exc:
                log_suppressed_exception("single: click candidate fallback", exc, level=logging.ERROR)
        if _is_single_option_selected(driver, target_elem):
            return True

    try:
        # 兜底：基于标准问卷星结构按序号点击
        fallback = driver.find_element(
            By.CSS_SELECTOR, f"#div{current} > div.ui-controlgroup > div:nth-child({selected_option})"
        )
        try:
            smooth_scroll_to_element(driver, fallback, "center")
        except Exception as exc:
            log_suppressed_exception("single: smooth_scroll_to_element fallback", exc, level=logging.ERROR)
        fallback.click()
        if _is_single_option_selected(driver, target_elem):
            return True
    except Exception as exc:
        log_suppressed_exception("single: css nth-child fallback", exc, level=logging.ERROR)

    try:
        # 最后兜底：直接把目标 radio 设为 checked 并触发事件
        forced = driver.execute_script(
            """
            const rootId = arguments[0];
            const optionPos = Number(arguments[1]) - 1;
            const root = document.getElementById(rootId);
            if (!root || Number.isNaN(optionPos) || optionPos < 0) return false;
            const group = root.querySelector("div.ui-controlgroup");
            if (!group) return false;
            const items = Array.from(group.children || []);
            const item = items[optionPos];
            if (!item) return false;
            const radio = item.querySelector("input[type='radio']");
            if (!radio) return false;
            try { radio.click(); } catch (e) {}
            if (!radio.checked) {
                radio.checked = true;
                try { radio.dispatchEvent(new Event('input', { bubbles: true })); } catch (e) {}
                try { radio.dispatchEvent(new Event('change', { bubbles: true })); } catch (e) {}
                try { radio.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); } catch (e) {}
            }
            return !!radio.checked;
            """,
            f"div{current}",
            selected_option,
        )
        if bool(forced) and _is_single_option_selected(driver, target_elem):
            return True
    except Exception as exc:
        log_suppressed_exception("single: force-check fallback", exc, level=logging.ERROR)

    return False


def _extract_attached_select_options(target_elem: Any) -> Tuple[Optional[Any], List[Tuple[str, str]]]:
    if target_elem is None:
        return None, []
    try:
        select_elements = target_elem.find_elements(By.CSS_SELECTOR, "select")
    except Exception as exc:
        log_suppressed_exception("single: find attached selects", exc, level=logging.ERROR)
        return None, []
    for select_element in select_elements:
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
        if valid_options:
            return select_element, valid_options
    return None, []


def _select_attached_option_via_js(driver: BrowserDriver, select_element: Any, option_value: str, display_text: str) -> bool:
    try:
        applied = driver.execute_script(
            """
const select = arguments[0];
const optionValue = arguments[1];
const displayText = arguments[2];
if (!select) return false;
const options = Array.from(select.options || []);
const target = options.find(opt => String(opt.value || '') === String(optionValue || ''));
if (!target) return false;
target.selected = true;
select.value = target.value;
try { select.setAttribute('value', target.value); } catch (e) {}
['input', 'change'].forEach(name => {
    try { select.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
});
const container = select.parentElement || select.closest('.ui-select') || select.closest('.ui-text');
const rendered = container
    ? container.querySelector('.select2-selection__rendered, [role="textbox"], .select2-selection__placeholder')
    : null;
const resolvedText = displayText || target.textContent || target.innerText || '';
if (rendered) {
    rendered.textContent = resolvedText;
    try { rendered.setAttribute('title', resolvedText); } catch (e) {}
}
const hiddenInput = container
    ? container.querySelector('input.OtherRadioText, input.cusomSelect, input[type="text"], input[type="search"]')
    : null;
if (hiddenInput) {
    hiddenInput.value = resolvedText;
    try { hiddenInput.setAttribute('value', resolvedText); } catch (e) {}
    ['input', 'change'].forEach(name => {
        try { hiddenInput.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {}
    });
}
return String(select.value || '') === String(target.value || '');
            """,
            select_element,
            option_value or "",
            display_text or "",
        )
    except Exception as exc:
        log_suppressed_exception("single: select attached option via js", exc, level=logging.ERROR)
        applied = False
    return bool(applied)


def _handle_attached_select(
    driver: BrowserDriver,
    current: int,
    selected_option_index_zero_based: int,
    target_elem: Any,
    fill_value: Optional[str],
    attached_selects_config: Optional[List[dict]],
) -> Optional[str]:
    select_element, select_options = _extract_attached_select_options(target_elem)
    if not select_element or not select_options:
        return None
    config_item = None
    for item in attached_selects_config or []:
        if not isinstance(item, dict):
            continue
        try:
            option_index = int(item.get("option_index"))
        except Exception:
            continue
        if option_index == selected_option_index_zero_based:
            config_item = item
            break
    matched_idx: Optional[int] = None
    normalized_fill = str(fill_value or "").strip()
    if normalized_fill:
        lowered_fill = normalized_fill.casefold()
        for idx, (value, text) in enumerate(select_options):
            if lowered_fill in {str(value or "").strip().casefold(), str(text or "").strip().casefold()}:
                matched_idx = idx
                break
    if matched_idx is None:
        configured_weights = config_item.get("weights") if isinstance(config_item, dict) else None
        if isinstance(configured_weights, list) and configured_weights:
            option_text_map = {str(text or "").strip(): idx for idx, (_, text) in enumerate(select_options)}
            normalized_weights = [0.0] * len(select_options)
            config_options = config_item.get("select_options") if isinstance(config_item, dict) else None
            if isinstance(config_options, list) and config_options:
                for cfg_idx, cfg_text in enumerate(config_options):
                    target_idx = option_text_map.get(str(cfg_text or "").strip())
                    if target_idx is None:
                        continue
                    raw_weight = configured_weights[cfg_idx] if cfg_idx < len(configured_weights) else 0.0
                    try:
                        normalized_weights[target_idx] = max(0.0, float(raw_weight))
                    except Exception:
                        normalized_weights[target_idx] = 0.0
            else:
                for idx in range(len(select_options)):
                    raw_weight = configured_weights[idx] if idx < len(configured_weights) else 0.0
                    try:
                        normalized_weights[idx] = max(0.0, float(raw_weight))
                    except Exception:
                        normalized_weights[idx] = 0.0
            if any(weight > 0 for weight in normalized_weights):
                matched_idx = weighted_index(normalized_weights)
        if matched_idx is None:
            matched_idx = weighted_index([1.0] * len(select_options))
    option_value, option_text = select_options[matched_idx]
    if _select_attached_option_via_js(driver, select_element, option_value, option_text):
        logging.info(
            "单选题第%s题第%s项命中嵌入式下拉，已自动选择：%s",
            current,
            selected_option_index_zero_based + 1,
            option_text or option_value or "未知选项",
        )
        return option_text or option_value or None
    logging.warning(
        "单选题第%s题第%s项的嵌入式下拉选择失败，页面可能仍会判定未作答。",
        current,
        selected_option_index_zero_based + 1,
    )
    return None


def single(
    driver: BrowserDriver,
    current: int,
    index: int,
    single_prob_config: List,
    single_option_fill_texts_config: List,
    single_attached_selects_config: Optional[List[List[dict]]] = None,
    task_ctx: Optional[Any] = None,
) -> None:
    """单选题处理主函数"""
    # 兼容不同模板下的单选题 DOM 结构，按优先级收集“真实选项”节点
    option_elements: List[Any] = []
    probe_selectors = [
        (By.CSS_SELECTOR, f"#div{current} > div.ui-controlgroup > div"),
        (By.CSS_SELECTOR, f"#div{current} .ui-controlgroup > div.ui-radio"),
        (By.CSS_SELECTOR, f"#div{current} .ui-controlgroup > div"),
        (By.XPATH, f'//*[@id="div{current}"]//div[contains(@class,"ui-radio")]'),
        (By.XPATH, f'//*[@id="div{current}"]//li[.//input[@type="radio"] or .//a[contains(@class,"jqradio")]]'),
        (By.XPATH, f'//*[@id="div{current}"]//label[.//input[@type="radio"]]'),
    ]
    seen: Set[Any] = set()
    for by, selector in probe_selectors:
        try:
            found = driver.find_elements(by, selector)
        except Exception:
            found = []
        for elem in found:
            try:
                if not elem.is_displayed():
                    continue
            except Exception as exc:
                log_suppressed_exception("single: if not elem.is_displayed(): continue", exc, level=logging.ERROR)
                continue
            if not _looks_like_single_option(elem):
                continue
            if elem not in seen:
                seen.add(elem)
                option_elements.append(elem)
    if not option_elements:
        try:
            radios = driver.find_elements(By.XPATH, f'//*[@id="div{current}"]//input[@type="radio"]')
        except Exception:
            radios = []
        for radio in radios:
            try:
                if not radio.is_displayed():
                    continue
            except Exception as exc:
                log_suppressed_exception("single: if not radio.is_displayed(): continue", exc, level=logging.ERROR)
            if radio not in seen:
                seen.add(radio)
                option_elements.append(radio)
    if not option_elements:
        logging.warning(f"第{current}题未找到任何单选选项，已跳过该题。")
        return
    
    prob_config = single_prob_config[index] if index < len(single_prob_config) else -1
    config_len = None
    try:
        if hasattr(prob_config, "__len__") and not isinstance(prob_config, (int, float)):
            config_len = len(prob_config)
    except Exception:
        config_len = None
    probabilities = normalize_droplist_probs(prob_config, len(option_elements))
    if config_len is not None and config_len > len(option_elements):
        # 仅在截断（丢弃多余配置）时提示，补零扩展属正常行为无需提示
        logging.info(
            "单选题概率配置数(%s)多于实际选项数(%s)（题号%s），多余部分已截断并重新归一化。",
            config_len,
            len(option_elements),
            current,
        )
    # 画像约束：提取选项文本，对匹配画像的选项加权
    option_texts = []
    for elem in option_elements:
        option_texts.append(_extract_single_option_text(elem))
    strict_ratio = is_strict_ratio_question(task_ctx, current)
    if not strict_ratio:
        probabilities = apply_persona_boost(option_texts, probabilities)
    probabilities = apply_single_like_consistency(probabilities, current)
    if strict_ratio:
        strict_reference = list(probabilities)
        probabilities = resolve_distribution_probabilities(
            probabilities,
            len(option_elements),
            task_ctx,
            current,
        )
        probabilities = enforce_reference_rank_order(probabilities, strict_reference)
    target_index = weighted_index(probabilities)
    selected_option = target_index + 1
    target_elem = option_elements[target_index] if target_index < len(option_elements) else None
    if not target_elem:
        logging.warning("单选题目标选项不存在（题号%s，索引%s），已跳过。", current, selected_option)
        return
    clicked = _click_single_option(driver, current, selected_option, target_elem)
    if not clicked:
        logging.warning("单选题点击未生效（题号%s，索引%s），已跳过。", current, selected_option)
        return
    if strict_ratio:
        record_pending_distribution_choice(task_ctx, current, target_index, len(option_elements))

    has_free_text_input = _single_option_has_free_text_input(target_elem)
    fill_entries = single_option_fill_texts_config[index] if index < len(single_option_fill_texts_config) else None
    fill_value = resolve_option_fill_text_from_config(
        fill_entries,
        selected_option - 1,
        driver=driver,
        question_number=current,
        option_text=option_texts[target_index] if target_index < len(option_texts) else "",
    )
    if not fill_value and has_free_text_input:
        fill_value = DEFAULT_FILL_TEXT
        logging.info(
            "单选题第%s题第%s项检测到附加填空但未配置文本，已自动使用默认值“%s”。",
            current,
            selected_option,
            DEFAULT_FILL_TEXT,
        )
    attached_selects_config = (
        single_attached_selects_config[index]
        if single_attached_selects_config and index < len(single_attached_selects_config)
        else None
    )
    attached_select_text = _handle_attached_select(
        driver,
        current,
        selected_option - 1,
        target_elem,
        fill_value,
        attached_selects_config,
    )

    # 记录统计数据

    # 记录作答上下文（供后续题目参考）
    selected_text = option_texts[target_index] if target_index < len(option_texts) else ""
    if attached_select_text:
        selected_text = f"{selected_text} / {attached_select_text}" if selected_text else attached_select_text
    elif fill_value and has_free_text_input:
        selected_text = f"{selected_text} / {fill_value}" if selected_text else fill_value
    record_answer(current, "single", selected_indices=[target_index], selected_texts=[selected_text])

    fill_option_additional_text(driver, current, selected_option - 1, fill_value)




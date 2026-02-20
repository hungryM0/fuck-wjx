"""单选题处理"""
from typing import Any, List, Optional, Set, Union
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception


from wjx.network.browser import By, BrowserDriver
from wjx.core.persona.context import apply_persona_boost, record_answer
from wjx.core.questions.consistency import (
    apply_demographic_consistency,
    apply_single_like_consistency,
    build_question_semantic,
    record_demographic_answer,
    record_consistency_answer,
)
from wjx.core.questions.utils import (
    weighted_index,
    normalize_droplist_probs,
    get_fill_text_from_config,
    fill_option_additional_text,
    extract_text_from_element,
    smooth_scroll_to_element,
)


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


def single(driver: BrowserDriver, current: int, index: int, single_prob_config: List, single_option_fill_texts_config: List) -> None:
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
        logging.debug(
            "单选题概率配置数(%s)多于实际选项数(%s)（题号%s），多余部分已截断并重新归一化。",
            config_len,
            len(option_elements),
            current,
        )
    # 画像约束：提取选项文本，对匹配画像的选项加权
    option_texts = []
    for elem in option_elements:
        option_texts.append(extract_text_from_element(elem))
    probabilities = apply_persona_boost(option_texts, probabilities)
    semantic = build_question_semantic(driver, current, option_texts)
    probabilities = apply_single_like_consistency(probabilities, semantic)
    probabilities = apply_demographic_consistency(probabilities, driver, current, option_texts)
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

    # 记录统计数据

    # 记录作答上下文（供后续题目参考）
    selected_text = option_texts[target_index] if target_index < len(option_texts) else ""
    record_answer(current, "single", selected_indices=[target_index], selected_texts=[selected_text])
    record_consistency_answer(semantic, [target_index])
    record_demographic_answer(driver, current, option_texts, [target_index])

    fill_entries = single_option_fill_texts_config[index] if index < len(single_option_fill_texts_config) else None
    fill_value = get_fill_text_from_config(fill_entries, selected_option - 1)
    fill_option_additional_text(driver, current, selected_option - 1, fill_value)


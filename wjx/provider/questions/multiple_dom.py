"""问卷星多选题 DOM 交互。"""
import logging
from typing import Any, List, Set, Tuple

from software.network.browser import By, BrowserDriver

_WARNED_OPTION_LOCATOR: Set[int] = set()

def _warn_option_locator_once(question_number: int, message: str, *args: Any) -> None:
    """选项定位异常只告警一次，避免日志刷屏。"""
    if question_number in _WARNED_OPTION_LOCATOR:
        return
    _WARNED_OPTION_LOCATOR.add(question_number)
    logging.warning(message, *args)

def _looks_like_multiple_option(element: Any) -> bool:
    """判断元素是否像多选题真实选项。"""
    try:
        class_name = (element.get_attribute("class") or "").lower()
    except Exception:
        class_name = ""
    if any(token in class_name for token in ("ui-checkbox", "jqcheck", "check", "option")):
        return True
    try:
        element_type = (element.get_attribute("type") or "").lower()
    except Exception:
        element_type = ""
    if element_type == "checkbox":
        return True
    try:
        if element.find_elements(By.CSS_SELECTOR, "input[type='checkbox'], .jqcheck, .ui-checkbox"):
            return True
    except Exception:
        return False
    return False

def _collect_multiple_option_elements(driver: BrowserDriver, question_number: int) -> Tuple[List[Any], str]:
    """收集多选题选项元素，兼容不同 DOM 模板。"""
    try:
        container = driver.find_element(By.CSS_SELECTOR, f"#div{question_number}")
    except Exception:
        return [], "container-missing"

    selector_chain = [
        ("css:#div .ui-controlgroup > div", ".ui-controlgroup > div"),
        ("css:#div .ui-controlgroup li", ".ui-controlgroup li"),
        ("css:#div ul > li", "ul > li"),
        ("css:#div ol > li", "ol > li"),
        ("css:#div .option", ".option"),
        ("css:#div .ui-checkbox", ".ui-checkbox"),
        ("css:#div .jqcheck", ".jqcheck"),
    ]
    seen: Set[str] = set()

    for source, selector in selector_chain:
        try:
            found = container.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            found = []
        options: List[Any] = []
        for elem in found:
            try:
                if not elem.is_displayed():
                    continue
            except Exception:
                continue
            if not _looks_like_multiple_option(elem):
                continue
            elem_key = str(getattr(elem, "id", None) or id(elem))
            if elem_key in seen:
                continue
            seen.add(elem_key)
            options.append(elem)
        if options:
            return options, source

    # 兜底：直接用 checkbox input（某些模板没有可点击容器）
    try:
        checkbox_inputs = container.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
    except Exception:
        checkbox_inputs = []
    options = []
    for elem in checkbox_inputs:
        try:
            if not elem.is_displayed():
                continue
        except Exception:
            continue
        elem_key = str(getattr(elem, "id", None) or id(elem))
        if elem_key in seen:
            continue
        seen.add(elem_key)
        options.append(elem)
    if options:
        return options, "css:#div input[type=checkbox]"
    return [], "no-option-found"

def _is_multiple_option_selected(driver: BrowserDriver, option_element: Any) -> bool:
    """检查多选选项是否已选中。"""
    try:
        selected = driver.execute_script(
            """
            const el = arguments[0];
            if (!el) return false;
            const isCheckbox = (typeof el.matches === 'function') && el.matches("input[type='checkbox']");
            const checkbox = isCheckbox ? el : (el.querySelector ? el.querySelector("input[type='checkbox']") : null);
            if (checkbox) return !!checkbox.checked;
            if (el.classList && (el.classList.contains('checked') || el.classList.contains('on') || el.classList.contains('jqchecked'))) {
                return true;
            }
            const marked = el.querySelector
                ? el.querySelector(".jqcheck.checked, .jqcheck.jqchecked, .ui-checkbox.checked, .ui-checkbox.on")
                : null;
            return !!marked;
            """,
            option_element,
        )
        return bool(selected)
    except Exception:
        return False

def _click_multiple_option(driver: BrowserDriver, option_element: Any) -> bool:
    """稳健点击多选项，点击后必须验收选中状态。"""
    if option_element is None:
        return False
    if _is_multiple_option_selected(driver, option_element):
        return True

    click_candidates: List[Any] = [option_element]
    try:
        click_candidates.extend(
            option_element.find_elements(
                By.CSS_SELECTOR,
                ".label, label, .jqcheck, .ui-checkbox, input[type='checkbox'], a, span, div",
            )
        )
    except Exception:
        pass

    seen: Set[str] = set()
    for candidate in click_candidates:
        cand_key = str(getattr(candidate, "id", None) or id(candidate))
        if cand_key in seen:
            continue
        seen.add(cand_key)
        try:
            candidate.click()
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", candidate)
            except Exception:
                continue
        if _is_multiple_option_selected(driver, option_element):
            return True

    try:
        forced = driver.execute_script(
            """
            const el = arguments[0];
            if (!el) return false;
            const isCheckbox = (typeof el.matches === 'function') && el.matches("input[type='checkbox']");
            const checkbox = isCheckbox ? el : (el.querySelector ? el.querySelector("input[type='checkbox']") : null);
            if (checkbox) {
                try { checkbox.click(); } catch (e) {}
                if (!checkbox.checked) {
                    checkbox.checked = true;
                    try { checkbox.dispatchEvent(new Event('input', { bubbles: true })); } catch (e) {}
                    try { checkbox.dispatchEvent(new Event('change', { bubbles: true })); } catch (e) {}
                    try { checkbox.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); } catch (e) {}
                }
                return !!checkbox.checked;
            }
            try { el.click(); } catch (e) {}
            return true;
            """,
            option_element,
        )
        if bool(forced) and _is_multiple_option_selected(driver, option_element):
            return True
    except Exception:
        return False
    return False

"""滑块题处理"""
import random
from typing import List, Optional, Union
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception


from wjx.network.browser_driver import By, BrowserDriver, NoSuchElementException
from wjx.core.questions.utils import smooth_scroll_to_element
from wjx.core.stats.collector import stats_collector


def _set_slider_input_value(driver: BrowserDriver, current: int, value: Union[int, float]) -> None:
    """设置滑块输入值"""


    try:
        slider_input = driver.find_element(By.CSS_SELECTOR, f"#q{current}")
    except NoSuchElementException:
        return
    script = (
        "const input = arguments[0];"
        "const target = String(arguments[1]);"
        "input.value = target;"
        "try { input.setAttribute('value', target); } catch (err) {}"
        "['input','change'].forEach(evt => input.dispatchEvent(new Event(evt, { bubbles: true })));"
    )
    try:
        driver.execute_script(script, slider_input, value)
    except Exception as exc:
        log_suppressed_exception("_set_slider_input_value: driver.execute_script(script, slider_input, value)", exc, level=logging.ERROR)


def _click_slider_track(driver: BrowserDriver, container, ratio: float) -> bool:
    """点击滑块轨道"""
    xpath_candidates = [
        ".//div[contains(@class,'wjx-slider') or contains(@class,'slider-track') or contains(@class,'range-slider') or contains(@class,'rangeslider') or contains(@class,'ui-slider') or contains(@class,'scale-slider') or contains(@class,'slider-container')]",
        ".//div[@role='slider']",
    ]
    page = getattr(driver, "page", None)
    for xpath in xpath_candidates:
        tracks = container.find_elements(By.XPATH, xpath)
        for track in tracks:
            width = track.size.get("width") or 0
            height = track.size.get("height") or 0
            if width <= 0 or height <= 0:
                continue
            offset_x = int(width * ratio)
            offset_x = max(5, min(offset_x, width - 5))
            offset_y = max(1, height // 2)
            handle = getattr(track, "_handle", None)
            if page and handle:
                try:
                    box = handle.bounding_box()
                except Exception:
                    box = None
                if box:
                    target_x = box["x"] + offset_x
                    target_y = box["y"] + offset_y
                    try:
                        page.mouse.click(target_x, target_y)
                        return True
                    except Exception:
                        continue
    return False


def _resolve_slider_score(index: int, slider_targets_config: List[float]) -> float:
    """解析滑块目标分数"""
    base: Optional[float] = None
    if 0 <= index < len(slider_targets_config):
        try:
            base = float(slider_targets_config[index])
        except Exception:
            base = None
    if base is None:
        base = random.uniform(1.0, 100.0)
    jitter = max(3.0, abs(base) * 0.05)
    return random.uniform(base - jitter, base + jitter)


def slider(driver: BrowserDriver, current: int, score: Optional[float] = None) -> None:
    """滑块题处理主函数"""
    try:
        question_div = driver.find_element(By.CSS_SELECTOR, f"#div{current}")
    except NoSuchElementException:
        question_div = None
    if question_div:
        smooth_scroll_to_element(driver, question_div, "center")

    slider_input = None
    min_value = 0.0
    max_value = 100.0
    step_value = 1.0

    def _parse_number(raw, default):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    try:
        slider_input = driver.find_element(By.CSS_SELECTOR, f"#q{current}")
    except NoSuchElementException:
        slider_input = None

    if slider_input:
        min_value = _parse_number(slider_input.get_attribute("min"), min_value)
        max_value = _parse_number(slider_input.get_attribute("max"), max_value)
        step_value = abs(_parse_number(slider_input.get_attribute("step"), step_value))
        if step_value == 0:
            step_value = 1.0
        if max_value <= min_value:
            max_value = min_value + 100.0

    target_value = _parse_number(score, None)
    if target_value is None:
        target_value = random.uniform(min_value, max_value)
    if target_value < min_value or target_value > max_value:
        if max_value > min_value:
            target_value = random.uniform(min_value, max_value)
        else:
            target_value = min_value
    if step_value > 0 and max_value > min_value:
        step_count = round((target_value - min_value) / step_value)
        target_value = min_value + step_count * step_value
        target_value = max(min_value, min(target_value, max_value))
    if abs(target_value - round(target_value)) < 1e-6:
        target_value = int(round(target_value))

    ratio = 0.0 if max_value == min_value else (target_value - min_value) / (max_value - min_value)
    ratio = max(0.0, min(ratio, 1.0))
    container = question_div
    if container:
        try:
            _click_slider_track(driver, container, ratio)
        except Exception as exc:
            log_suppressed_exception("slider: _click_slider_track(driver, container, ratio)", exc, level=logging.ERROR)
        try:
            driver.execute_script(
                r"""
                const container = arguments[0];
                const ratio = arguments[1];
                if (!container) return;
                const track = container.querySelector(
                    '.rangeslider, .range-slider, .slider-track, .wjx-slider, .ui-slider, .scale-slider, .slider-container'
                );
                if (!track) return;
                const width = track.clientWidth || track.offsetWidth || 0;
                if (!width) return;
                const pos = Math.max(0, Math.min(width, ratio * width));
                const handle = track.querySelector('.rangeslider__handle, .slider-handle, .ui-slider-handle, .handle');
                const fill = track.querySelector('.rangeslider__fill, .slider-selection, .ui-slider-range, .fill');
                if (fill) {
                    fill.style.width = pos + 'px';
                    if (!fill.style.left) { fill.style.left = '0px'; }
                }
                if (handle) {
                    handle.style.left = pos + 'px';
                }
                try { track.setAttribute('data-answered', '1'); } catch (err) {}
                """,
                container,
                ratio,
            )
        except Exception as exc:
            log_suppressed_exception("slider: driver.execute_script( r\"\"\" const container = arguments[0]; const ratio = arg...", exc, level=logging.ERROR)
    _set_slider_input_value(driver, current, target_value)
    # 记录统计数据（将目标值映射为索引，按step计算）
    if step_value > 0 and max_value > min_value:
        step_index = int(round((target_value - min_value) / step_value))
        stats_collector.record_slider_choice(current, step_index)

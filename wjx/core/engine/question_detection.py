"""题目检测与分类 - 识别页面上的题型"""
import logging
import threading
import time
from typing import List, Optional, Tuple

from wjx.core.engine.navigation import dismiss_resume_dialog_if_present, try_click_start_answer_button
from wjx.network.browser import By, BrowserDriver


def _count_questions_by_fieldset(driver: BrowserDriver) -> List[int]:
    question_counts_per_page: List[int] = []
    total_pages = len(driver.find_elements(By.XPATH, '//*[@id="divQuestion"]/fieldset'))
    for page_index in range(1, total_pages + 1):
        page_questions = driver.find_elements(By.XPATH, f'//*[@id="fieldset{page_index}"]/div')
        valid_question_count = 0
        for question_element in page_questions:
            topic_attr = question_element.get_attribute("topic")
            if topic_attr and topic_attr.isdigit():
                valid_question_count += 1
        question_counts_per_page.append(valid_question_count)
    return question_counts_per_page


def _count_questions_by_script(driver: BrowserDriver) -> Tuple[List[int], int, int]:
    script = r"""
        return (() => {
            const container = document.querySelector('#divQuestion') || document;
            const fieldsets = Array.from(container.querySelectorAll('fieldset[id^="fieldset"]'));

            const countInRoot = (root) => {
                const ids = new Set();
                const topicEls = Array.from(root.querySelectorAll('[topic]'));
                topicEls.forEach(el => {
                    const t = (el.getAttribute('topic') || '').trim();
                    if (/^\d+$/.test(t)) ids.add(`t${t}`);
                });
                const idEls = Array.from(root.querySelectorAll('div[id^="div"]'));
                idEls.forEach(el => {
                    const id = (el.getAttribute('id') || '').trim();
                    const m = id.match(/^div(\d+)$/);
                    if (m) ids.add(`d${m[1]}`);
                });
                if (!ids.size) {
                    const clsEls = Array.from(root.querySelectorAll('.div_question, .question, .wjx_question'));
                    clsEls.forEach((_, idx) => ids.add(`c${idx}`));
                }
                return ids.size;
            };

            if (fieldsets.length) {
                const counts = fieldsets.map(fs => countInRoot(fs));
                const total = counts.reduce((a, b) => a + b, 0);
                return { pages: counts, total, inputs: container.querySelectorAll('input, textarea, select').length };
            }

            const total = countInRoot(container);
            const inputs = container.querySelectorAll('input, textarea, select').length;
            return { pages: total ? [total] : [], total, inputs };
        })();
    """
    try:
        payload = driver.execute_script(script) or {}
    except Exception:
        return [], 0, 0
    pages = payload.get("pages") or []
    try:
        pages = [int(x) for x in pages if int(x) >= 0]
    except Exception:
        pages = []
    total = 0
    for item in pages:
        try:
            total += int(item)
        except Exception:
            continue
    try:
        inputs = int(payload.get("inputs") or 0)
    except Exception:
        inputs = 0
    return pages, total, inputs


def detect(driver: BrowserDriver, stop_signal: Optional[threading.Event] = None) -> List[int]:
    dismiss_resume_dialog_if_present(driver, stop_signal=stop_signal)
    try_click_start_answer_button(driver, stop_signal=stop_signal)
    question_counts_per_page = _count_questions_by_fieldset(driver)
    if sum(question_counts_per_page) > 0:
        return question_counts_per_page

    # 题目结构较新或被动态渲染时，尝试用更宽松的 DOM 规则再探测一次
    fallback_pages, fallback_total, inputs = _count_questions_by_script(driver)
    if fallback_total > 0:
        logging.info("题目检测回退：使用宽松规则识别到 %d 题", fallback_total)
        return fallback_pages

    # 可能还在加载中，稍等一次再尝试
    if stop_signal and stop_signal.is_set():
        return question_counts_per_page
    if stop_signal:
        stop_signal.wait(0.4)
    else:
        time.sleep(0.4)
    fallback_pages, fallback_total, inputs = _count_questions_by_script(driver)
    if fallback_total > 0:
        logging.info("题目检测回退（延迟后）：识别到 %d 题", fallback_total)
        return fallback_pages

    # 如果页面里有输入控件但没识别到题目，至少保底 1 题，避免直接提交
    if inputs > 0:
        logging.warning("题目检测失败但检测到输入控件，保底按 1 题处理")
        return [1]

    return question_counts_per_page


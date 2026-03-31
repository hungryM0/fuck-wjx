"""AI 运行时辅助函数 - 调用 AI 模型生成答案"""
import re
from typing import Optional, Union, List
import logging
from software.logging.log_utils import log_suppressed_exception


from software.network.browser import By, BrowserDriver
from software.integrations.ai import generate_answer
from software.app.config import _HTML_SPACE_RE


class AIRuntimeError(RuntimeError):
    """AI 填空运行时错误（需要终止任务）。"""




def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return _HTML_SPACE_RE.sub(" ", str(value)).strip()


def _cleanup_question_title(raw_title: str) -> str:
    title = _normalize_text(raw_title)
    if not title:
        return ""
    title = re.sub(r"^\*?\s*\d+[\.、]?\s*", "", title)
    title = title.replace("【单选题】", "").replace("【多选题】", "")
    return title.strip()


def extract_question_title_from_dom(driver: BrowserDriver, question_number: int) -> str:
    selectors = [
        f"#div{question_number} .topichtml",
        f"#div{question_number} .field-label",
        f"#div{question_number} .title",
        f"#div{question_number} .topic",
    ]
    for selector in selectors:
        try:
            element = driver.find_element(By.CSS_SELECTOR, selector)
        except Exception:
            element = None
        if not element:
            continue
        try:
            text = element.text
        except Exception:
            text = ""
        cleaned = _cleanup_question_title(text)
        if cleaned:
            return cleaned
    return ""


def resolve_question_title_for_ai(
    driver: BrowserDriver,
    question_number: int,
    fallback_title: Optional[str] = None,
) -> str:
    title = _cleanup_question_title(fallback_title or "")
    if not title:
        title = extract_question_title_from_dom(driver, question_number)
    if not title:
        raise AIRuntimeError(f"无法获取第{question_number}题题干，无法调用 AI")
    return title


def generate_ai_answer(
    question_title: str,
    *,
    question_type: str = "fill_blank",
    blank_count: Optional[int] = None,
) -> Union[str, List[str]]:
    cleaned = _cleanup_question_title(question_title)
    if not cleaned:
        raise AIRuntimeError("题干为空，无法调用 AI")

    # 注入画像和上下文信息，让 AI 答案与前面的作答保持一致
    try:
        from software.core.persona.context import build_ai_context_prompt
        context_prompt = build_ai_context_prompt()
        if context_prompt:
            cleaned = f"{context_prompt}\n\n请回答以下问卷问题：{cleaned}"
    except Exception as exc:
        log_suppressed_exception("generate_ai_answer: from software.core.persona.context import build_ai_context_prompt", exc, level=logging.WARNING)

    try:
        answer = generate_answer(
            cleaned,
            question_type=question_type,
            blank_count=blank_count,
        )
    except Exception as exc:
        raise AIRuntimeError(f"AI 调用失败：{exc}") from exc
    if question_type == "multi_fill_blank":
        if not isinstance(answer, list):
            if not answer or not str(answer).strip():
                raise AIRuntimeError("AI 未返回有效答案")
            return str(answer).strip()
        cleaned_answers: List[str] = []
        for item in answer:
            text = str(item or "").strip()
            if not text:
                raise AIRuntimeError("AI 返回的多项填空答案包含空值")
            cleaned_answers.append(text)
        if not cleaned_answers:
            raise AIRuntimeError("AI 未返回有效答案")
        return cleaned_answers
    if not answer or not str(answer).strip():
        raise AIRuntimeError("AI 未返回有效答案")
    return str(answer).strip()




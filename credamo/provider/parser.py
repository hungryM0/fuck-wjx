"""Credamo 见数问卷解析实现。"""

from __future__ import annotations

import ast
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from software.app.config import DEFAULT_FILL_TEXT
from software.core.engine.driver_factory import create_playwright_driver
from software.providers.common import SURVEY_PROVIDER_CREDAMO

_QUESTION_NUMBER_RE = re.compile(r"^\s*(?:Q|题目?)\s*(\d+)\b", re.IGNORECASE)
_TYPE_ONLY_TITLE_RE = re.compile(r"^\s*\[[^\]]+\]\s*$")
_LEADING_TYPE_TAG_RE = re.compile(r"^(?:(?:\[[^\]]+\]|【[^】]+】)\s*)+")
_FORCE_SELECT_COMMAND_RE = re.compile(r"请(?:务必|一定|必须|直接)?\s*选(?:择)?")
_FORCE_SELECT_INDEX_RE = re.compile(r"^第?\s*(\d{1,3})\s*(?:个|项|选项|分|星)?$")
_FORCE_SELECT_SENTENCE_SPLIT_RE = re.compile(r"[。；;！？!\n\r]")
_FORCE_SELECT_CLEAN_RE = re.compile(r"[\s`'\"“”‘’【】\[\]\(\)（）<>《》,，、。；;:：!?！？]")
_FORCE_SELECT_LABEL_TARGET_RE = re.compile(r"^([A-Za-z])(?:项|选项|答案)?$")
_FORCE_SELECT_OPTION_LABEL_RE = re.compile(
    r"^(?:第\s*)?[\(（【\[]?\s*([A-Za-z])\s*[\)）】\]]?(?=$|[\.．、:：\-\s]|[\u4e00-\u9fff])"
)
_ARITHMETIC_EXPR_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?(?:\s*[+\-*/×xX÷]\s*\d+(?:\.\d+)?)+)(?!\d)")
_OPTION_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_FORCE_TEXT_RE = re.compile(r"请(?:务必|一定|必须|直接)?\s*(?:输入|填写|填入|写入)\s*[：:\s]*[\"“'‘]?([^\"”'’\s，,。；;！!？?）)]+)")
_MULTI_SELECT_LIMIT_RE = re.compile(
    r"(?:[\[【（(]\s*)?"
    r"(?P<kind>至多|最多|不超过|至多可|最多可|至少|最少|不少于)"
    r"\s*(?:可)?(?:选择|选)?\s*"
    r"(?P<count>\d{1,3})\s*(?:个)?(?:选项|项)?"
    r"(?:\s*[\]】）)])?"
)
_MAX_PARSE_PAGES = 20
_MAX_DYNAMIC_REVEAL_ROUNDS = 20
_PARSE_POLL_SECONDS = 0.2
_PARSE_PAGE_WAIT_SECONDS = 8.0
_DYNAMIC_REVEAL_WAIT_SECONDS = 2.0
_NEXT_BUTTON_MARKERS = ("下一页", "next", "继续")
_SUBMIT_BUTTON_MARKERS = ("提交", "完成", "交卷", "submit", "finish", "done")


class CredamoParseError(RuntimeError):
    """Credamo 页面结构无法解析时抛出的业务异常。"""


def _normalize_text(value: Any) -> str:
    try:
        text = str(value or "").strip()
    except Exception:
        return ""
    return re.sub(r"\s+", " ", text)


def _normalize_force_select_text(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    return _FORCE_SELECT_CLEAN_RE.sub("", text).lower()


def _extract_force_select_option_label(option_text: Any) -> Optional[str]:
    text = _normalize_text(option_text)
    if not text:
        return None
    match = _FORCE_SELECT_OPTION_LABEL_RE.match(text)
    if not match:
        return None
    label = str(match.group(1) or "").strip().upper()
    return label or None


def _extract_force_select_option(
    title_text: str,
    option_texts: List[str],
    extra_fragments: Optional[List[Any]] = None,
) -> Tuple[Optional[int], Optional[str]]:
    """识别 Credamo 题干中的“请选 XX”指令。"""
    if not option_texts:
        return None, None

    normalized_options: List[Tuple[int, str, str]] = []
    for idx, option_text in enumerate(option_texts):
        raw_text = _normalize_text(option_text)
        normalized = _normalize_force_select_text(raw_text)
        if not normalized:
            continue
        normalized_options.append((idx, raw_text, normalized))
    if not normalized_options:
        return None, None

    fragments: List[str] = []
    for candidate in [title_text, *(extra_fragments or [])]:
        text = _normalize_text(candidate)
        if text:
            fragments.append(text)
    unique_fragments: List[str] = []
    seen: set[str] = set()
    for fragment in fragments:
        normalized_fragment = _normalize_text(fragment)
        if not normalized_fragment or normalized_fragment in seen:
            continue
        seen.add(normalized_fragment)
        unique_fragments.append(normalized_fragment)

    for fragment in unique_fragments:
        for command_match in _FORCE_SELECT_COMMAND_RE.finditer(fragment):
            tail_text = fragment[command_match.end():]
            if not tail_text:
                continue
            sentence = _FORCE_SELECT_SENTENCE_SPLIT_RE.split(tail_text, maxsplit=1)[0]
            sentence = sentence.strip(" ：:，,、")
            if not sentence:
                continue
            compact_sentence = _normalize_force_select_text(sentence)
            if not compact_sentence:
                continue

            best_index: Optional[int] = None
            best_text: Optional[str] = None
            best_length = -1
            for option_idx, raw_text, normalized_text in normalized_options:
                if normalized_text.isdigit():
                    continue
                if normalized_text in compact_sentence:
                    text_len = len(normalized_text)
                    if text_len > best_length:
                        best_length = text_len
                        best_index = option_idx
                        best_text = raw_text
            if best_index is not None:
                return best_index, best_text

            label_match = _FORCE_SELECT_LABEL_TARGET_RE.fullmatch(compact_sentence)
            if label_match:
                target_label = str(label_match.group(1) or "").strip().upper()
                if target_label:
                    for option_idx, raw_text, _ in normalized_options:
                        if _extract_force_select_option_label(raw_text) == target_label:
                            return option_idx, raw_text

            index_match = _FORCE_SELECT_INDEX_RE.fullmatch(sentence)
            if index_match:
                try:
                    target_idx = int(index_match.group(1)) - 1
                except Exception:
                    target_idx = -1
                if 0 <= target_idx < len(option_texts):
                    return target_idx, _normalize_text(option_texts[target_idx]) or None
    return None, None


def _safe_eval_arithmetic_expression(expression: str) -> Optional[float]:
    text = str(expression or "").strip()
    if not text:
        return None
    text = text.replace("×", "*").replace("x", "*").replace("X", "*").replace("÷", "/")
    if not re.fullmatch(r"[\d\s+\-*/.]+", text):
        return None
    try:
        node = ast.parse(text, mode="eval")
    except Exception:
        return None

    def eval_node(current: ast.AST) -> Optional[float]:
        if isinstance(current, ast.Expression):
            return eval_node(current.body)
        if isinstance(current, ast.Constant) and isinstance(current.value, (int, float)):
            return float(current.value)
        if isinstance(current, ast.UnaryOp) and isinstance(current.op, (ast.UAdd, ast.USub)):
            value = eval_node(current.operand)
            if value is None:
                return None
            return value if isinstance(current.op, ast.UAdd) else -value
        if isinstance(current, ast.BinOp) and isinstance(current.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left = eval_node(current.left)
            right = eval_node(current.right)
            if left is None or right is None:
                return None
            if isinstance(current.op, ast.Add):
                return left + right
            if isinstance(current.op, ast.Sub):
                return left - right
            if isinstance(current.op, ast.Mult):
                return left * right
            if abs(right) < 1e-12:
                return None
            return left / right
        return None

    return eval_node(node)


def _extract_numeric_option_value(option_text: Any) -> Optional[float]:
    text = _normalize_text(option_text)
    if not text:
        return None
    match = _OPTION_NUMBER_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None


def _extract_arithmetic_option(
    title_text: str,
    option_texts: List[str],
    extra_fragments: Optional[List[Any]] = None,
) -> Tuple[Optional[int], Optional[str]]:
    """识别“100+100 等于多少”这类简单算术陷阱题。"""
    if not option_texts:
        return None, None
    fragments: List[str] = []
    for candidate in [title_text, *(extra_fragments or [])]:
        text = _normalize_text(candidate)
        if text:
            fragments.append(text)
    for fragment in fragments:
        for match in _ARITHMETIC_EXPR_RE.finditer(fragment):
            result = _safe_eval_arithmetic_expression(match.group(1))
            if result is None:
                continue
            for option_idx, option_text in enumerate(option_texts):
                option_value = _extract_numeric_option_value(option_text)
                if option_value is not None and abs(option_value - result) < 1e-9:
                    return option_idx, _normalize_text(option_text) or None
    return None, None


def _extract_forced_texts(title_text: str, extra_fragments: Optional[List[Any]] = None) -> List[str]:
    """识别“请输入：你好”这类填空陷阱题的固定答案。"""
    forced: List[str] = []
    seen: set[str] = set()
    for candidate in [title_text, *(extra_fragments or [])]:
        fragment = _normalize_text(candidate)
        if not fragment:
            continue
        for match in _FORCE_TEXT_RE.finditer(fragment):
            text = _normalize_text(match.group(1))
            if text and text not in seen:
                seen.add(text)
                forced.append(text)
    return forced


def _extract_multi_select_limits(
    title_text: str,
    *,
    option_count: int = 0,
    extra_fragments: Optional[List[Any]] = None,
) -> Tuple[Optional[int], Optional[int]]:
    """识别 Credamo 题干中的“至少/至多选 N 项”多选限制。"""
    min_limit: Optional[int] = None
    max_limit: Optional[int] = None
    fragments: List[str] = []
    seen: set[str] = set()
    for candidate in [title_text, *(extra_fragments or [])]:
        fragment = _normalize_text(candidate)
        if not fragment or fragment in seen:
            continue
        seen.add(fragment)
        fragments.append(fragment)

    upper_bound = max(0, int(option_count or 0))
    for fragment in fragments:
        for match in _MULTI_SELECT_LIMIT_RE.finditer(fragment):
            try:
                count = max(1, int(match.group("count") or 0))
            except Exception:
                continue
            if upper_bound > 0:
                count = min(count, upper_bound)
            kind = str(match.group("kind") or "")
            if kind in {"至少", "最少", "不少于"}:
                min_limit = count if min_limit is None else max(min_limit, count)
            elif kind in {"至多", "最多", "不超过", "至多可", "最多可"}:
                max_limit = count if max_limit is None else min(max_limit, count)

    if min_limit is not None and max_limit is not None and min_limit > max_limit:
        min_limit = max_limit
    return min_limit, max_limit


def _normalize_question_number(raw: Any, fallback_num: int) -> int:
    try:
        match = re.search(r"\d+", str(raw or ""))
        if match:
            return max(1, int(match.group(0)))
    except Exception:
        pass
    return max(1, int(fallback_num or 1))


def _infer_type_code(question: Dict[str, Any]) -> str:
    question_kind = str(question.get("question_kind") or "").strip().lower()
    input_types = {str(item or "").strip().lower() for item in question.get("input_types") or []}
    option_count = int(question.get("options") or 0)
    text_input_count = int(question.get("text_inputs") or 0)

    if question_kind == "multiple" or "checkbox" in input_types:
        return "4"
    if question_kind == "dropdown":
        return "7"
    if question_kind == "scale":
        return "5"
    if question_kind == "order":
        return "11"
    if question_kind == "single" or "radio" in input_types:
        return "3"
    if question_kind in {"text", "multi_text"} or text_input_count > 0:
        return "1"
    if option_count >= 2:
        return "3"
    return "1"


def _normalize_question(raw: Dict[str, Any], fallback_num: int) -> Dict[str, Any]:
    raw_title = _normalize_text(raw.get("title_full_text") or raw.get("title"))
    question_num = _normalize_question_number(raw.get("question_num"), fallback_num)
    title = raw_title
    match = _QUESTION_NUMBER_RE.match(raw_title)
    if match:
        question_num = _normalize_question_number(match.group(1), fallback_num)
        stripped_title = _normalize_text(raw_title[match.end():])
        stripped_title = _normalize_text(_LEADING_TYPE_TAG_RE.sub("", stripped_title))
        if stripped_title and not _TYPE_ONLY_TITLE_RE.fullmatch(stripped_title):
            title = stripped_title
        else:
            title = raw_title or f"Q{question_num}"
    elif not title:
        title = f"Q{question_num}"

    option_texts = [_normalize_text(text) for text in raw.get("option_texts") or []]
    option_texts = [text for text in option_texts if text]
    text_inputs = max(0, int(raw.get("text_inputs") or 0))
    question_kind = str(raw.get("question_kind") or "").strip().lower()
    type_code = _infer_type_code({**raw, "options": len(option_texts), "text_inputs": text_inputs})
    forced_option_index, forced_option_text = _extract_force_select_option(
        raw_title or title,
        option_texts,
        extra_fragments=[
            raw.get("title_text"),
            raw.get("tip_text"),
        ],
    )
    if forced_option_index is None:
        forced_option_index, forced_option_text = _extract_arithmetic_option(
            raw_title or title,
            option_texts,
            extra_fragments=[
                raw.get("title_text"),
                raw.get("tip_text"),
            ],
        )
    forced_texts = _extract_forced_texts(
        raw_title or title,
        extra_fragments=[
            raw.get("title_text"),
            raw.get("tip_text"),
        ],
    )
    multi_min_limit: Optional[int] = None
    multi_max_limit: Optional[int] = None
    if type_code == "4":
        multi_min_limit, multi_max_limit = _extract_multi_select_limits(
            raw_title or title,
            option_count=len(option_texts),
            extra_fragments=[
                raw.get("title_text"),
                raw.get("tip_text"),
            ],
        )

    normalized: Dict[str, Any] = {
        "num": question_num,
        "title": title or raw_title or f"Q{question_num}",
        "description": "",
        "type_code": type_code,
        "options": len(option_texts),
        "rows": 1,
        "row_texts": [],
        "page": max(1, int(raw.get("page") or 1)),
        "option_texts": option_texts,
        "provider": SURVEY_PROVIDER_CREDAMO,
        "provider_question_id": str(raw.get("question_id") or question_num),
        "provider_page_id": str(raw.get("page") or 1),
        "provider_type": str(raw.get("provider_type") or question_kind or type_code).strip(),
        "required": bool(raw.get("required")),
        "text_inputs": text_inputs,
        "text_input_labels": [],
        "is_text_like": question_kind in {"text", "multi_text"} or (text_inputs > 0 and not option_texts),
        "is_multi_text": question_kind == "multi_text" or text_inputs > 1,
        "is_rating": False,
        "rating_max": 0,
        "forced_option_index": forced_option_index,
        "forced_option_text": forced_option_text,
        "forced_texts": forced_texts,
        "multi_min_limit": multi_min_limit,
        "multi_max_limit": multi_max_limit,
    }
    if normalized["type_code"] == "5":
        normalized["rating_max"] = max(len(option_texts), 1)
    return normalized


def _extract_questions_from_current_page(page: Any, *, page_number: int) -> List[Dict[str, Any]]:
    script = r"""
() => {
  const visible = (el, minWidth = 8, minHeight = 8) => {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = el.getBoundingClientRect();
    return rect.width >= minWidth && rect.height >= minHeight;
  };
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const uniqueTexts = (values) => {
    const seen = new Set();
    const result = [];
    for (const raw of values || []) {
      const text = clean(raw);
      if (!text || seen.has(text)) continue;
      seen.add(text);
      result.push(text);
    }
    return result;
  };
  const data = [];
  const roots = Array.from(document.querySelectorAll('.answer-page .question'));
  roots.forEach((root, index) => {
    if (!visible(root)) return;

    const editableInputs = Array.from(
      root.querySelectorAll(
        'textarea, input:not([readonly])[type="text"], input:not([readonly])[type="search"], input:not([readonly])[type="number"], input:not([readonly])[type="tel"], input:not([readonly])[type="email"], input:not([readonly]):not([type])'
      )
    ).filter((node) => visible(node, 4, 4));
    const allInputs = Array.from(root.querySelectorAll('input, textarea, [role="radio"], [role="checkbox"]'));

    let kind = '';
    if (root.querySelector('.multi-choice') || root.querySelector('input[type="checkbox"]') || root.querySelector('[role="checkbox"]')) {
      kind = 'multiple';
    } else if (root.querySelector('.pc-dropdown') || root.querySelector('.el-select')) {
      kind = 'dropdown';
    } else if (root.querySelector('.scale') || root.querySelector('.nps-item') || root.querySelector('.el-rate__item')) {
      kind = 'scale';
    } else if (root.querySelector('.rank-order')) {
      kind = 'order';
    } else if (editableInputs.length > 1) {
      kind = 'multi_text';
    } else if (editableInputs.length > 0) {
      kind = 'text';
    } else if (root.querySelector('.single-choice') || root.querySelector('input[type="radio"]') || root.querySelector('[role="radio"]')) {
      kind = 'single';
    }

    const qstNoNode = root.querySelector('.question-title .qstNo');
    const questionTitleRoot = root.querySelector('.question-title');
    const titleTextNode = root.querySelector('.question-title .title-text');
    const titleInnerNode = root.querySelector('.question-title .title-inner');
    const tipNode = root.querySelector('.question-title .tip');
    const qstNo = clean(qstNoNode ? qstNoNode.textContent : '');
    const titleRootText = clean((questionTitleRoot && questionTitleRoot.innerText) || '');
    let titleText = clean((titleTextNode && titleTextNode.innerText) || (titleInnerNode && titleInnerNode.innerText) || '');
    const tipText = clean((tipNode && tipNode.innerText) || '');
    if (tipText && titleText === tipText) {
      titleText = '';
    }
    const fullTitle = clean(titleRootText || [qstNo, titleText, tipText].filter(Boolean).join(' '));

    const choiceTexts = uniqueTexts(Array.from(root.querySelectorAll('.choice-text')).map((node) => node.innerText || node.textContent || ''));
    const dropdownTexts = uniqueTexts(Array.from(root.querySelectorAll('.el-select-dropdown__item, option')).map((node) => node.innerText || node.textContent || ''));
    const scaleTexts = uniqueTexts(Array.from(root.querySelectorAll('.scale .nps-item, .el-rate__item')).map((node) => node.innerText || node.textContent || ''));
    let optionTexts = [];
    if (kind === 'dropdown' && dropdownTexts.length) optionTexts = dropdownTexts;
    else if (kind === 'scale' && scaleTexts.length) optionTexts = scaleTexts;
    else if (choiceTexts.length) optionTexts = choiceTexts;
    else if (dropdownTexts.length) optionTexts = dropdownTexts;
    else optionTexts = scaleTexts;

    const inputTypes = allInputs.map((input) => {
      const role = clean(input.getAttribute('role')).toLowerCase();
      if (role) return role;
      if (input.tagName.toLowerCase() === 'textarea') return 'textarea';
      return clean(input.getAttribute('type')).toLowerCase() || 'text';
    });
    const bodyText = clean(root.innerText || '');
    if (!kind && !optionTexts.length && editableInputs.length <= 0 && !bodyText) return;

    const stableQuestionId = root.getAttribute('data-id') || root.getAttribute('id') || qstNo || fullTitle || String(index + 1);
    data.push({
      question_id: stableQuestionId,
      question_num: qstNo,
      title: fullTitle || bodyText.split(' ').slice(0, 12).join(' '),
      title_full_text: titleRootText,
      title_text: titleText,
      tip_text: tipText,
      body_text: bodyText,
      option_texts: optionTexts,
      input_types: inputTypes,
      text_inputs: editableInputs.length,
      required: /必答|必须|required/i.test(bodyText),
      provider_type: kind || Array.from(new Set(inputTypes)).join(','),
      question_kind: kind,
    });
  });
  return data;
}
"""
    try:
        data = page.evaluate(script)
    except Exception as exc:
        raise CredamoParseError(f"无法读取 Credamo 页面题目结构：{exc}") from exc
    if not isinstance(data, list):
        return []

    questions: List[Dict[str, Any]] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            continue
        normalized = _normalize_question({**item, "page": page_number}, fallback_num=index)
        questions.append(normalized)
    return questions


def _locator_count(locator: Any) -> int:
    try:
        return int(locator.count())
    except Exception:
        return 0


def _text_content(locator: Any) -> str:
    try:
        return _normalize_text(locator.text_content(timeout=500))
    except Exception:
        return ""


def _locator_is_visible(locator: Any) -> bool:
    try:
        return bool(locator.is_visible(timeout=300))
    except Exception:
        return False


def _detect_navigation_action(page: Any) -> Optional[str]:
    locator = page.locator("button, a, [role='button'], input[type='button'], input[type='submit']")
    count = _locator_count(locator)
    found_next = False
    for index in range(count):
        item = locator.nth(index)
        if not _locator_is_visible(item):
            continue
        text = _text_content(item) or _normalize_text(item.get_attribute("value"))
        lowered = text.casefold()
        if any(marker in lowered for marker in _SUBMIT_BUTTON_MARKERS):
            return "submit"
        if any(marker in lowered for marker in _NEXT_BUTTON_MARKERS):
            found_next = True
    return "next" if found_next else None


def _click_navigation(page: Any, action: str) -> bool:
    primary_button = page.locator("#credamo-submit-btn").first
    if _locator_count(primary_button) > 0 and _locator_is_visible(primary_button):
        try:
            primary_text = (_text_content(primary_button) or _normalize_text(primary_button.get_attribute("value"))).casefold()
        except Exception:
            primary_text = ""
        if action == "next" and any(marker in primary_text for marker in _NEXT_BUTTON_MARKERS):
            try:
                primary_button.click(timeout=3000)
                return True
            except Exception:
                try:
                    handle = primary_button.element_handle(timeout=1000)
                    if handle is not None and bool(page.evaluate("el => { el.click(); return true; }", handle)):
                        return True
                except Exception:
                    pass
        if action == "submit" and any(marker in primary_text for marker in _SUBMIT_BUTTON_MARKERS):
            try:
                primary_button.click(timeout=3000)
                return True
            except Exception:
                try:
                    handle = primary_button.element_handle(timeout=1000)
                    if handle is not None and bool(page.evaluate("el => { el.click(); return true; }", handle)):
                        return True
                except Exception:
                    pass

    targets = _NEXT_BUTTON_MARKERS if action == "next" else _SUBMIT_BUTTON_MARKERS
    locator = page.locator("button, a, [role='button'], input[type='button'], input[type='submit']")
    count = _locator_count(locator)
    for index in range(count):
        item = locator.nth(index)
        if not _locator_is_visible(item):
            continue
        text = (_text_content(item) or _normalize_text(item.get_attribute("value"))).casefold()
        if not any(marker in text for marker in targets):
            continue
        try:
            item.scroll_into_view_if_needed(timeout=1000)
        except Exception:
            pass
        try:
            item.click(timeout=3000)
            return True
        except Exception:
            try:
                handle = item.element_handle(timeout=1000)
                if handle is not None and bool(page.evaluate("el => { el.click(); return true; }", handle)):
                    return True
            except Exception:
                continue
    return False


def _extract_page_signature(questions: List[Dict[str, Any]]) -> Tuple[Tuple[str, str], ...]:
    return tuple(
        (str(item.get("provider_question_id") or ""), str(item.get("title") or ""))
        for item in questions
    )


def _question_dedupe_key(question: Dict[str, Any]) -> str:
    page_id = str(question.get("provider_page_id") or question.get("page") or "").strip()
    question_id = str(question.get("provider_question_id") or "").strip()
    return f"page:{page_id}|id:{question_id}|num:{question.get('num')}|title:{question.get('title')}"


def _append_unseen_questions(
    target: List[Dict[str, Any]],
    seen_keys: set[str],
    candidates: List[Dict[str, Any]],
) -> int:
    added = 0
    for question in candidates:
        key = _question_dedupe_key(question)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        target.append(question)
        added += 1
    return added


def _wait_for_page_change(page: Any, previous_signature: Tuple[Tuple[str, str], ...], *, page_number: int) -> bool:
    deadline = time.monotonic() + _PARSE_PAGE_WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(_PARSE_POLL_SECONDS)
        current_questions = _extract_questions_from_current_page(page, page_number=page_number)
        current_signature = _extract_page_signature(current_questions)
        if current_signature and current_signature != previous_signature:
            return True
    return False


def _prime_question_for_next(page: Any, root: Any, question: Dict[str, Any]) -> None:
    from credamo.provider.runtime import (
        _answer_dropdown,
        _answer_multiple,
        _answer_order,
        _answer_scale,
        _answer_single_like,
        _answer_text,
    )

    kind = str(question.get("provider_type") or question.get("type_code") or "").strip().lower()
    option_count = max(1, int(question.get("options") or 0))
    forced_option_index = question.get("forced_option_index")
    try:
        forced_index = int(forced_option_index) if forced_option_index is not None else None
    except Exception:
        forced_index = None
    if forced_index is not None and 0 <= forced_index < option_count:
        first_option_weights = [100.0 if idx == forced_index else 0.0 for idx in range(option_count)]
    else:
        first_option_weights = [100.0] + [0.0] * max(0, option_count - 1)
    middle_index = min(max(option_count // 2, 0), max(option_count - 1, 0))
    middle_weights = [0.0] * option_count
    if middle_weights:
        middle_weights[middle_index] = 100.0
    scale_weights = first_option_weights if forced_index is not None and 0 <= forced_index < option_count else middle_weights
    if kind in {"single", "3"}:
        _answer_single_like(page, root, first_option_weights, option_count)
    elif kind in {"multiple", "4"}:
        _answer_multiple(page, root, first_option_weights)
    elif kind in {"dropdown", "7"}:
        _answer_dropdown(page, root, first_option_weights)
    elif kind in {"scale", "5", "score"}:
        _answer_scale(page, root, scale_weights)
    elif kind in {"order", "11"}:
        _answer_order(page, root)
    else:
        forced_texts = question.get("forced_texts") if isinstance(question.get("forced_texts"), list) else []
        _answer_text(root, forced_texts or [DEFAULT_FILL_TEXT])


def _prime_page_for_next(
    page: Any,
    questions: List[Dict[str, Any]],
    primed_keys: Optional[set[str]] = None,
) -> int:
    from credamo.provider.runtime import _question_roots

    roots = _question_roots(page)
    primed = primed_keys if primed_keys is not None else set()
    primed_count = 0
    for question, root in zip(questions, roots):
        key = _question_dedupe_key(question)
        if key in primed:
            continue
        try:
            _prime_question_for_next(page, root, question)
            primed.add(key)
            primed_count += 1
        except Exception:
            logging.info("Credamo 解析翻页预填题目失败", exc_info=True)
    return primed_count


def _wait_for_dynamic_questions(
    page: Any,
    *,
    page_number: int,
    previous_visible_keys: set[str],
) -> List[Dict[str, Any]]:
    deadline = time.monotonic() + _DYNAMIC_REVEAL_WAIT_SECONDS
    latest_questions = _extract_questions_from_current_page(page, page_number=page_number)
    while time.monotonic() < deadline:
        current_questions = _extract_questions_from_current_page(page, page_number=page_number)
        latest_questions = current_questions
        current_keys = {_question_dedupe_key(question) for question in current_questions}
        if current_keys - previous_visible_keys:
            return current_questions
        time.sleep(_PARSE_POLL_SECONDS)
    return latest_questions


def _collect_current_page_until_stable(page: Any, *, page_number: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    discovered_questions: List[Dict[str, Any]] = []
    discovered_keys: set[str] = set()
    primed_keys: set[str] = set()
    current_questions: List[Dict[str, Any]] = []

    for _ in range(_MAX_DYNAMIC_REVEAL_ROUNDS):
        current_questions = _extract_questions_from_current_page(page, page_number=page_number)
        if not current_questions:
            break
        _append_unseen_questions(discovered_questions, discovered_keys, current_questions)
        visible_keys = {_question_dedupe_key(question) for question in current_questions}
        primed_count = _prime_page_for_next(page, current_questions, primed_keys)
        if primed_count <= 0:
            break

        next_questions = _wait_for_dynamic_questions(
            page,
            page_number=page_number,
            previous_visible_keys=visible_keys,
        )
        _append_unseen_questions(discovered_questions, discovered_keys, next_questions)
        next_keys = {_question_dedupe_key(question) for question in next_questions}
        current_questions = next_questions
        if not (next_keys - visible_keys):
            break
    return current_questions, discovered_questions


def parse_credamo_survey(url: str) -> Tuple[List[Dict[str, Any]], str]:
    driver = None
    try:
        driver, _browser_name = create_playwright_driver(
            headless=True,
            prefer_browsers=["edge", "chrome"],
            persistent_browser=False,
            transient_launch=True,
        )
        driver.get(url, timeout=30000, wait_until="domcontentloaded")
        page = driver.page
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        try:
            page.wait_for_selector(".answer-page .question", timeout=15000)
        except Exception as exc:
            logging.info("Credamo 解析等待题目控件超时：%s", exc)
        questions: List[Dict[str, Any]] = []
        seen_question_keys: set[str] = set()
        title = _normalize_text(page.title())

        for page_number in range(1, _MAX_PARSE_PAGES + 1):
            current_questions, discovered_questions = _collect_current_page_until_stable(page, page_number=page_number)
            if not current_questions:
                if not questions:
                    raise CredamoParseError("没有识别到 Credamo 题目，请确认链接已开放且无需登录")
                break

            for question in discovered_questions:
                question_key = _question_dedupe_key(question)
                if question_key in seen_question_keys:
                    continue
                seen_question_keys.add(question_key)
                questions.append(question)

            navigation_action = _detect_navigation_action(page)
            if navigation_action != "next":
                break

            previous_signature = _extract_page_signature(current_questions)
            if not _click_navigation(page, "next"):
                break
            _wait_for_page_change(page, previous_signature, page_number=page_number + 1)

        if not questions:
            raise CredamoParseError("没有识别到 Credamo 题目，请确认链接已开放且无需登录")
        if not title:
            try:
                title = _normalize_text(
                    page.locator("h1, .title, [class*='title'], [class*='Title']").first.text_content(timeout=1000)
                )
            except Exception:
                title = ""
        return questions, title or "Credamo 见数问卷"
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                logging.info("关闭 Credamo 解析浏览器失败", exc_info=True)

"""Credamo 见数问卷解析实现。"""

from __future__ import annotations

import ast
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from software.app.config import DEFAULT_FILL_TEXT
from software.network.browser.parse_pool import acquire_parse_browser_session
from software.providers.common import SURVEY_PROVIDER_CREDAMO
from software.providers.contracts import LOGIC_PARSE_STATUS_UNKNOWN

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
    r"(?P<count>\d{1,3}|[零〇一二两三四五六七八九十百]{1,4})\s*(?:个)?(?:选项|项)?"
    r"(?:\s*[\]】）)])?"
)
_MULTI_SELECT_RANGE_RE = re.compile(
    r"(?:[\[【（(]\s*)?"
    r"(?:请)?(?:选择|选)\s*"
    r"(?P<min>\d{1,3}|[零〇一二两三四五六七八九十百]{1,4})\s*"
    r"(?:-|~|～|至|到)\s*"
    r"(?P<max>\d{1,3}|[零〇一二两三四五六七八九十百]{1,4})\s*"
    r"(?:个)?(?:选项|项)"
    r"(?:\s*[\]】）)])?"
)
_MAX_PARSE_PAGES = 20
_MAX_DYNAMIC_REVEAL_ROUNDS = 20
_PARSE_POLL_SECONDS = 0.2
_PARSE_PAGE_WAIT_SECONDS = 8.0
_DYNAMIC_REVEAL_WAIT_SECONDS = 2.0
_INITIAL_PARSE_RECOVERY_RETRIES = 2
_INITIAL_QUESTION_WAIT_SECONDS = 12.0
_NEXT_BUTTON_MARKERS = ("下一页", "next", "继续")
_SUBMIT_BUTTON_MARKERS = ("提交", "完成", "交卷", "submit", "finish", "done")
_QUESTION_ROOT_SELECTORS = (
    ".answer-page .question",
    ".question",
    "[class*='question']",
)
_MATRIX_HEADER_TEXT_SELECTORS = (
    "thead th",
    ".matrix-title",
    ".matrix-column",
    ".table-header th",
    ".el-table__header-wrapper th",
    ".el-table__header th",
    "[role='columnheader']",
    ".matrix thead th",
    ".matrix-header th",
    ".matrix-header-cell",
    ".matrix-col-title",
    ".rating-text",
    ".scale-text",
    ".satisfaction-text",
)
_MATRIX_HEADER_CONTAINER_SELECTORS = (
    ".matrix-header",
    ".matrix-header.pc",
    ".pc-matrix .matrix-header",
    ".pc-matrix .matrix-header.pc",
)


class CredamoParseError(RuntimeError):
    """Credamo 页面结构无法解析时抛出的业务异常。"""


def _looks_like_loading_shell(title: str, body_text: str) -> bool:
    normalized_title = str(title or "").strip()
    normalized_body = str(body_text or "").strip()
    if not normalized_body:
        return normalized_title in {"", "答卷"}
    compact_body = normalized_body.replace(" ", "")
    if compact_body in {"载入中", "载入中...", "载入中..", "loading", "loading..."}:
        return True
    if normalized_title == "答卷" and len(compact_body) <= 16:
        return True
    return False


async def _page_loading_snapshot(page: Any) -> tuple[str, str]:
    try:
        title = str(await page.title() or "").strip()
    except Exception:
        title = ""
    try:
        body_text = str(await page.locator("body").text_content(timeout=1000) or "").strip()
    except Exception:
        try:
            body_text = str(await page.locator("body").inner_text(timeout=1000) or "").strip()
        except Exception:
            body_text = ""
    return title, re.sub(r"\s+", " ", body_text).strip()


async def _question_roots(page: Any) -> List[Any]:
    script = r"""
() => {
  const visible = (el, minWidth = 8, minHeight = 8) => {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = el.getBoundingClientRect();
    return rect.width >= minWidth && rect.height >= minHeight;
  };
  return Array.from(document.querySelectorAll('.answer-page .question, .question, [class*="question"]'))
    .map((root, index) => ({ index, visible: visible(root) }))
    .filter((item) => item.visible)
    .map((item) => item.index);
}
"""
    try:
        visible_indexes = await page.evaluate(script) or []
    except Exception:
        visible_indexes = []
    try:
        roots = []
        for selector in _QUESTION_ROOT_SELECTORS:
            try:
                roots = list(await page.query_selector_all(selector) or [])
            except Exception:
                roots = []
            if roots:
                break
    except Exception:
        roots = []
    resolved: List[Any] = []
    for raw_index in list(visible_indexes or []):
        try:
            index = int(raw_index)
        except Exception:
            continue
        if 0 <= index < len(roots):
            resolved.append(roots[index])
    return resolved


async def _retry_initial_question_load_if_needed(page: Any) -> List[Any]:
    roots = await _question_roots(page)
    if roots:
        return roots

    try:
        current_url = str(page.url or "").strip()
    except Exception:
        current_url = ""
    reload_target = current_url or None
    deadline = time.monotonic() + _INITIAL_QUESTION_WAIT_SECONDS
    reload_attempted = False

    while time.monotonic() < deadline:
        if roots:
            return roots
        title, body_text = await _page_loading_snapshot(page)
        loading_shell = _looks_like_loading_shell(title, body_text)
        if loading_shell and not reload_attempted:
            logging.warning(
                "Credamo 解析入口命中载入壳页，准备刷新重试：title=%s body=%s url=%s",
                title or "<empty>",
                (body_text[:80] or "<empty>"),
                reload_target or "<empty>",
            )
            try:
                if reload_target:
                    await page.goto(reload_target, wait_until="domcontentloaded", timeout=45000)
                else:
                    await page.reload(wait_until="domcontentloaded", timeout=45000)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=8000)
                except Exception:
                    pass
                reload_attempted = True
            except Exception:
                logging.info("Credamo 解析入口刷新重试失败", exc_info=True)
        elif not loading_shell:
            logging.info("Credamo 解析入口等待题目后仍未发现可见题目节点")
        await page.wait_for_timeout(int(_PARSE_POLL_SECONDS * 1000))
        roots = await _question_roots(page)

    if not roots:
        logging.info("Credamo 解析入口等待题目超时后仍未发现可见题目节点")
    return roots


async def _recover_initial_parse_questions(page: Any) -> List[Dict[str, Any]]:
    for attempt in range(1, _INITIAL_PARSE_RECOVERY_RETRIES + 1):
        await _retry_initial_question_load_if_needed(page)
        await page.wait_for_timeout(int(_PARSE_POLL_SECONDS * 1000))
        current_questions = await _extract_questions_from_current_page(page, page_number=1)
        if current_questions:
            logging.info("Credamo 解析入口恢复成功：attempt=%s questions=%s", attempt, len(current_questions))
            return current_questions
        logging.warning("Credamo 解析入口首屏仍为空，继续重试：attempt=%s", attempt)
    return []


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


def _parse_count_token(raw: Any) -> Optional[int]:
    text = _normalize_text(raw)
    if not text:
        return None
    if text.isdigit():
        try:
            return int(text)
        except Exception:
            return None
    digit_map = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    total = 0
    current = 0
    for ch in text:
        if ch in digit_map:
            current = digit_map[ch]
            continue
        if ch == "十":
            total += (current or 1) * 10
            current = 0
            continue
        if ch == "百":
            total += (current or 1) * 100
            current = 0
            continue
        return None
    result = total + current
    return result if result > 0 else None


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
            parsed_count = _parse_count_token(match.group("count"))
            if parsed_count is None:
                continue
            count = max(1, parsed_count)
            if upper_bound > 0:
                count = min(count, upper_bound)
            kind = str(match.group("kind") or "")
            if kind in {"至少", "最少", "不少于"}:
                min_limit = count if min_limit is None else max(min_limit, count)
            elif kind in {"至多", "最多", "不超过", "至多可", "最多可"}:
                max_limit = count if max_limit is None else min(max_limit, count)
        for match in _MULTI_SELECT_RANGE_RE.finditer(fragment):
            parsed_min = _parse_count_token(match.group("min"))
            parsed_max = _parse_count_token(match.group("max"))
            if parsed_min is None or parsed_max is None:
                continue
            range_min = max(1, parsed_min)
            range_max = max(range_min, parsed_max)
            if upper_bound > 0:
                range_min = min(range_min, upper_bound)
                range_max = min(range_max, upper_bound)
            min_limit = range_min if min_limit is None else max(min_limit, range_min)
            max_limit = range_max if max_limit is None else min(max_limit, range_max)

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
    if question_kind == "matrix":
        return "6"
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


def _is_generic_matrix_option_text(text: Any) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return bool(re.fullmatch(r"选项\s*\d+", normalized, re.IGNORECASE))


def _resolve_matrix_option_texts(raw: Dict[str, Any], option_texts: List[str]) -> List[str]:
    question_kind = str(raw.get("question_kind") or "").strip().lower()
    provider_type = str(raw.get("provider_type") or "").strip().lower()
    if question_kind != "matrix" and provider_type != "matrix":
        return option_texts

    matrix_column_texts = [_normalize_text(text) for text in raw.get("matrix_column_texts") or []]
    matrix_column_texts = [text for text in matrix_column_texts if text]
    if matrix_column_texts:
        return matrix_column_texts

    if option_texts and not all(_is_generic_matrix_option_text(text) for text in option_texts):
        return option_texts
    return option_texts


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
    option_texts = _resolve_matrix_option_texts(raw, option_texts)
    text_inputs = max(0, int(raw.get("text_inputs") or 0))
    question_kind = str(raw.get("question_kind") or "").strip().lower()
    row_texts = [_normalize_text(text) for text in raw.get("row_texts") or []]
    row_texts = [text for text in row_texts if text]
    type_code = _infer_type_code({**raw, "options": len(option_texts), "text_inputs": text_inputs})
    is_description = not (
        option_texts
        or text_inputs > 0
        or question_kind in {"single", "multiple", "dropdown", "scale", "order", "matrix", "text", "multi_text"}
    )
    if is_description:
        type_code = "0"
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
        "rows": max(1, len(row_texts)),
        "row_texts": row_texts,
        "page": max(1, int(raw.get("page") or 1)),
        "option_texts": option_texts,
        "provider": SURVEY_PROVIDER_CREDAMO,
        "provider_question_id": str(raw.get("question_id") or question_num),
        "provider_page_id": str(raw.get("page") or 1),
        "provider_type": str(raw.get("provider_type") or question_kind or type_code).strip(),
        "has_jump": False,
        "jump_rules": [],
        "has_display_condition": False,
        "display_conditions": [],
        "has_dependent_display_logic": False,
        "controls_display_targets": [],
        "logic_parse_status": LOGIC_PARSE_STATUS_UNKNOWN,
        "question_media": list(raw.get("question_media") or []),
        "required": bool(raw.get("required")),
        "text_inputs": text_inputs,
        "text_input_labels": [],
        "is_description": is_description,
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


def _is_answerable_question(question: Dict[str, Any]) -> bool:
    try:
        option_count = int(question.get("options") or 0)
    except Exception:
        option_count = 0
    try:
        text_inputs = int(question.get("text_inputs") or 0)
    except Exception:
        text_inputs = 0
    type_code = str(question.get("type_code") or "").strip()
    question_kind = str(question.get("question_kind") or "").strip().lower()
    if option_count > 0 or text_inputs > 0:
        return True
    if type_code in {"3", "4", "5", "6", "7", "11"}:
        return True
    return question_kind in {"single", "multiple", "dropdown", "scale", "order", "matrix"}


def _page_has_answerable_questions(questions: List[Dict[str, Any]]) -> bool:
    return any(_is_answerable_question(question) for question in questions)


async def _extract_questions_from_current_page(page: Any, *, page_number: int) -> List[Dict[str, Any]]:
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
    const isLikelyPlaceholder = (text) => /^选项\s*\d+$/i.test(clean(text));
    const matrixHeaderTextSelectors = %s;
    const matrixHeaderContainerSelectors = %s;
    const matrixColumnTexts = (root, detectedRows) => {
      const candidateTexts = uniqueTexts(
        Array.from(root.querySelectorAll(matrixHeaderTextSelectors.join(', ')))
          .map((node) => node.innerText || node.textContent || '')
          .filter((text) => {
            const normalized = clean(text);
            return normalized && !/^Q?\d+$/i.test(normalized);
          })
      );
      const filteredCandidates = candidateTexts.filter((text) => !isLikelyPlaceholder(text));
      const rowLabels = new Set((detectedRows || []).map((row) => clean(row && row.label)).filter(Boolean));
      const matrixLikeCandidates = filteredCandidates.filter((text) => !rowLabels.has(clean(text)));
      if (matrixLikeCandidates.length >= 2) {
        return matrixLikeCandidates;
      }

      const containerTexts = uniqueTexts(
        Array.from(root.querySelectorAll(matrixHeaderContainerSelectors.join(', ')))
          .map((node) => node.innerText || node.textContent || '')
          .filter((text) => clean(text))
      );
      for (const containerText of containerTexts) {
        const fragments = clean(containerText)
          .split(/\s+/)
          .map((text) => clean(text))
          .filter((text) => text && !isLikelyPlaceholder(text) && !rowLabels.has(text));
        const uniqueFragments = uniqueTexts(fragments);
        if (uniqueFragments.length >= 2) {
          return uniqueFragments;
        }
      }

      const fallbackColumns = [];
      const rowNodes = Array.from(root.querySelectorAll('tbody tr, .matrix-row, .el-table__row'));
      for (const row of rowNodes) {
        if (!visible(row, 12, 8)) continue;
        const controls = Array.from(row.querySelectorAll('input[type="radio"], [role="radio"], .el-radio, .el-radio__input')).filter((node) => visible(node, 4, 4));
        if (controls.length < 2) continue;
        const cells = Array.from(row.querySelectorAll('th, td, .el-table__cell'));
        if (cells.length < controls.length + 1) continue;
        const texts = [];
        for (let i = cells.length - controls.length; i < cells.length; i += 1) {
          const cell = cells[i];
          if (!cell) continue;
          const clone = cell.cloneNode(true);
          Array.from(clone.querySelectorAll('input, [role="radio"], .el-radio, .el-radio__input')).forEach((node) => node.remove());
          const text = clean(clone.innerText || clone.textContent || '');
          texts.push(text);
        }
        const usable = texts.filter((text) => text && !isLikelyPlaceholder(text));
        if (usable.length >= 2) {
          fallbackColumns.push(...usable);
          break;
        }
      }
      return uniqueTexts(fallbackColumns);
    };
    const matrixRows = (root) => {
      const rows = [];
      const rowNodes = Array.from(root.querySelectorAll('tbody tr, .matrix-row, .el-table__row'));
      for (const row of rowNodes) {
        if (!visible(row, 12, 8)) continue;
        const controls = Array.from(row.querySelectorAll('input[type="radio"], [role="radio"], .el-radio, .el-radio__input'));
        if (!controls.length) continue;
        const labelNode = row.querySelector('th, td:first-child, .matrix-row-title, .row-title, .statement, .label');
        let label = clean((labelNode && (labelNode.innerText || labelNode.textContent)) || '');
        if (!label) {
          const clone = row.cloneNode(true);
          Array.from(clone.querySelectorAll('input, [role="radio"], .el-radio, .el-radio__input')).forEach((node) => node.remove());
          label = clean(clone.innerText || clone.textContent || '');
        }
        rows.push({ label, columns: controls.length });
      }
      return rows;
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

    const detectedMatrixRows = matrixRows(root);
    const detectedMatrixColumns = matrixColumnTexts(root, detectedMatrixRows);

    let kind = '';
    if (root.querySelector('.multi-choice') || root.querySelector('input[type="checkbox"]') || root.querySelector('[role="checkbox"]')) {
      kind = 'multiple';
    } else if (root.querySelector('.pc-dropdown') || root.querySelector('.el-select')) {
      kind = 'dropdown';
    } else if (detectedMatrixRows.length >= 2 && Math.max(...detectedMatrixRows.map((row) => row.columns || 0)) >= 2) {
      kind = 'matrix';
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
    const normalizeUrl = (value) => {
      const text = clean(value);
      if (!text) return '';
      if (text.startsWith('//')) return `https:${text}`;
      return text;
    };
    const mediaSeen = new Set();
    const questionMedia = [];
    const pushMedia = (scope, indexValue, label, img) => {
      if (!img) return;
      const sourceUrl = normalizeUrl(img.getAttribute('src') || img.getAttribute('data-src') || img.getAttribute('data-original'));
      if (!sourceUrl) return;
      const key = `${scope}|${String(indexValue)}|${sourceUrl}`;
      if (mediaSeen.has(key)) return;
      mediaSeen.add(key);
      questionMedia.push({
        kind: 'image',
        scope,
        index: indexValue,
        source_url: sourceUrl,
        label: clean(label),
      });
    };
    Array.from((questionTitleRoot || root).querySelectorAll('img')).forEach((img) => {
      pushMedia('title', null, '题干图', img);
    });
    Array.from(root.querySelectorAll('.choice-item, .single-choice li, .multi-choice li, .option-item, li')).forEach((item, optionIndex) => {
      const label = clean(item.innerText || item.textContent || '') || `选项 ${optionIndex + 1}`;
      Array.from(item.querySelectorAll('img')).forEach((img) => {
        pushMedia('option', optionIndex, label, img);
      });
    });
    Array.from(root.querySelectorAll('tbody tr, .matrix-row, .el-table__row')).forEach((row, rowIndex) => {
      const labelNode = row.querySelector('th, td:first-child, .matrix-row-title, .row-title, .statement, .label');
      const rowLabel = clean((labelNode && (labelNode.innerText || labelNode.textContent)) || '') || `第 ${rowIndex + 1} 行`;
      Array.from(row.querySelectorAll('img')).forEach((img) => {
        pushMedia('row', rowIndex, rowLabel, img);
      });
    });
    let optionTexts = [];
    if (kind === 'dropdown' && dropdownTexts.length) optionTexts = dropdownTexts;
    else if (kind === 'matrix' && detectedMatrixColumns.length) optionTexts = detectedMatrixColumns;
    else if (kind === 'matrix' && detectedMatrixRows.length) {
      const maxColumns = Math.max(...detectedMatrixRows.map((row) => row.columns || 0));
      optionTexts = Array.from({ length: maxColumns }, (_item, itemIndex) => `选项 ${itemIndex + 1}`);
    }
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
      matrix_column_texts: detectedMatrixColumns,
      row_texts: detectedMatrixRows.map((row, rowIndex) => row.label || `第 ${rowIndex + 1} 行`),
      input_types: inputTypes,
      text_inputs: editableInputs.length,
      required: /必答|必须|required/i.test(bodyText),
      provider_type: kind || Array.from(new Set(inputTypes)).join(','),
      question_kind: kind,
      question_media: questionMedia,
    });
  });
  return data;
}
""" % (
        repr(list(_MATRIX_HEADER_TEXT_SELECTORS)),
        repr(list(_MATRIX_HEADER_CONTAINER_SELECTORS)),
    )
    try:
        data = await page.evaluate(script)
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


async def _locator_count(locator: Any) -> int:
    try:
        return int(await locator.count())
    except Exception:
        return 0


async def _text_content(locator: Any) -> str:
    try:
        return _normalize_text(await locator.text_content(timeout=500))
    except Exception:
        return ""


async def _locator_is_visible(locator: Any) -> bool:
    try:
        return bool(await locator.is_visible(timeout=300))
    except Exception:
        return False


async def _detect_navigation_action(page: Any) -> Optional[str]:
    locator = page.locator("button, a, [role='button'], input[type='button'], input[type='submit']")
    count = await _locator_count(locator)
    found_next = False
    for index in range(count):
        item = locator.nth(index)
        if not await _locator_is_visible(item):
            continue
        text = await _text_content(item) or _normalize_text(await item.get_attribute("value"))
        lowered = text.casefold()
        if any(marker in lowered for marker in _SUBMIT_BUTTON_MARKERS):
            return "submit"
        if any(marker in lowered for marker in _NEXT_BUTTON_MARKERS):
            found_next = True
    return "next" if found_next else None


async def _click_navigation(page: Any, action: str) -> bool:
    primary_button = page.locator("#credamo-submit-btn").first
    if await _locator_count(primary_button) > 0 and await _locator_is_visible(primary_button):
        try:
            primary_text = (await _text_content(primary_button) or _normalize_text(await primary_button.get_attribute("value"))).casefold()
        except Exception:
            primary_text = ""
        if action == "next" and any(marker in primary_text for marker in _NEXT_BUTTON_MARKERS):
            try:
                await primary_button.click(timeout=3000)
                return True
            except Exception:
                try:
                    handle = await primary_button.element_handle(timeout=1000)
                    if handle is not None and bool(await page.evaluate("el => { el.click(); return true; }", handle)):
                        return True
                except Exception:
                    pass
        if action == "submit" and any(marker in primary_text for marker in _SUBMIT_BUTTON_MARKERS):
            try:
                await primary_button.click(timeout=3000)
                return True
            except Exception:
                try:
                    handle = await primary_button.element_handle(timeout=1000)
                    if handle is not None and bool(await page.evaluate("el => { el.click(); return true; }", handle)):
                        return True
                except Exception:
                    pass

    targets = _NEXT_BUTTON_MARKERS if action == "next" else _SUBMIT_BUTTON_MARKERS
    locator = page.locator("button, a, [role='button'], input[type='button'], input[type='submit']")
    count = await _locator_count(locator)
    for index in range(count):
        item = locator.nth(index)
        if not await _locator_is_visible(item):
            continue
        text = (await _text_content(item) or _normalize_text(await item.get_attribute("value"))).casefold()
        if not any(marker in text for marker in targets):
            continue
        try:
            await item.scroll_into_view_if_needed(timeout=1000)
        except Exception:
            pass
        try:
            await item.click(timeout=3000)
            return True
        except Exception:
            try:
                handle = await item.element_handle(timeout=1000)
                if handle is not None and bool(await page.evaluate("el => { el.click(); return true; }", handle)):
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


async def _wait_for_page_change(page: Any, previous_signature: Tuple[Tuple[str, str], ...], *, page_number: int) -> bool:
    deadline = time.time() + _PARSE_PAGE_WAIT_SECONDS
    while time.time() < deadline:
        await page.wait_for_timeout(int(_PARSE_POLL_SECONDS * 1000))
        current_questions = await _extract_questions_from_current_page(page, page_number=page_number)
        current_signature = _extract_page_signature(current_questions)
        if current_signature and current_signature != previous_signature:
            return True
    return False


async def _run_parse_runtime_coroutine(coro: Any) -> None:
    try:
        await coro
    except Exception:
        logging.info("Credamo 解析翻页预填题目失败", exc_info=True)


async def _prime_page_for_next(
    page: Any,
    questions: List[Dict[str, Any]],
    primed_keys: Optional[set[str]] = None,
) -> int:
    from credamo.provider.runtime import _question_roots

    roots = await _question_roots(page)
    primed = primed_keys if primed_keys is not None else set()
    primed_count = 0
    for question, root in zip(questions, roots):
        if not _is_answerable_question(question):
            continue
        key = _question_dedupe_key(question)
        if key in primed:
            continue
        try:
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

            from credamo.provider.runtime import (
                _answer_dropdown,
                _answer_matrix,
                _answer_multiple,
                _answer_order,
                _answer_scale,
                _answer_single_like,
                _answer_text,
            )

            if kind in {"single", "3"}:
                await _run_parse_runtime_coroutine(_answer_single_like(page, root, first_option_weights, option_count))
            elif kind in {"multiple", "4"}:
                await _run_parse_runtime_coroutine(_answer_multiple(page, root, first_option_weights))
            elif kind in {"dropdown", "7"}:
                await _run_parse_runtime_coroutine(_answer_dropdown(page, root, first_option_weights))
            elif kind in {"matrix", "6", "9"}:
                await _run_parse_runtime_coroutine(_answer_matrix(page, root, first_option_weights))
            elif kind in {"scale", "5", "score"}:
                await _run_parse_runtime_coroutine(_answer_scale(page, root, scale_weights))
            elif kind in {"order", "11"}:
                await _run_parse_runtime_coroutine(_answer_order(page, root))
            else:
                forced_texts = question.get("forced_texts") if isinstance(question.get("forced_texts"), list) else []
                await _run_parse_runtime_coroutine(_answer_text(root, forced_texts or [DEFAULT_FILL_TEXT]))
            primed.add(key)
            primed_count += 1
        except Exception:
            logging.info("Credamo 解析翻页预填题目失败", exc_info=True)
    return primed_count


async def _wait_for_dynamic_questions(
    page: Any,
    *,
    page_number: int,
    previous_visible_keys: set[str],
) -> List[Dict[str, Any]]:
    deadline = time.time() + _DYNAMIC_REVEAL_WAIT_SECONDS
    latest_questions = await _extract_questions_from_current_page(page, page_number=page_number)
    while time.time() < deadline:
        current_questions = await _extract_questions_from_current_page(page, page_number=page_number)
        latest_questions = current_questions
        current_keys = {_question_dedupe_key(question) for question in current_questions}
        if current_keys - previous_visible_keys:
            return current_questions
        await page.wait_for_timeout(int(_PARSE_POLL_SECONDS * 1000))
    return latest_questions


async def _collect_current_page_until_stable(page: Any, *, page_number: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    discovered_questions: List[Dict[str, Any]] = []
    discovered_keys: set[str] = set()
    primed_keys: set[str] = set()
    current_questions: List[Dict[str, Any]] = []

    for _ in range(_MAX_DYNAMIC_REVEAL_ROUNDS):
        current_questions = await _extract_questions_from_current_page(page, page_number=page_number)
        if not current_questions:
            break
        _append_unseen_questions(discovered_questions, discovered_keys, current_questions)
        visible_keys = {_question_dedupe_key(question) for question in current_questions}
        primed_count = await _prime_page_for_next(page, current_questions, primed_keys)
        if primed_count <= 0:
            break

        next_questions = await _wait_for_dynamic_questions(
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


async def parse_credamo_survey(url: str) -> Tuple[List[Dict[str, Any]], str]:
    async with acquire_parse_browser_session() as driver:
        await driver.get(url, timeout=45000, wait_until="domcontentloaded")
        page = await driver.page()
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        await _retry_initial_question_load_if_needed(page)
        questions: List[Dict[str, Any]] = []
        seen_question_keys: set[str] = set()
        title = _normalize_text(await page.title())

        for page_number in range(1, _MAX_PARSE_PAGES + 1):
            current_questions, discovered_questions = await _collect_current_page_until_stable(page, page_number=page_number)
            if not current_questions:
                if page_number == 1 and not questions:
                    recovered_questions = await _recover_initial_parse_questions(page)
                    if recovered_questions:
                        current_questions = list(recovered_questions)
                        discovered_questions = list(recovered_questions)
                if not current_questions and not questions:
                    raise CredamoParseError("没有识别到 Credamo 题目，请确认链接已开放且无需登录")
                if not current_questions:
                    break

            if not _page_has_answerable_questions(current_questions):
                navigation_action = await _detect_navigation_action(page)
                if navigation_action == "next":
                    previous_signature = _extract_page_signature(current_questions)
                    if await _click_navigation(page, "next") and await _wait_for_page_change(
                        page,
                        previous_signature,
                        page_number=page_number + 1,
                    ):
                        continue
                if not questions:
                    raise CredamoParseError("没有识别到 Credamo 题目，请确认链接已开放且无需登录")
                break

            for question in discovered_questions:
                question_key = _question_dedupe_key(question)
                if question_key in seen_question_keys:
                    continue
                seen_question_keys.add(question_key)
                questions.append(question)

            navigation_action = await _detect_navigation_action(page)
            if navigation_action != "next":
                break

            previous_signature = _extract_page_signature(current_questions)
            if not await _click_navigation(page, "next"):
                break
            await _wait_for_page_change(page, previous_signature, page_number=page_number + 1)

        if not questions:
            raise CredamoParseError("没有识别到 Credamo 题目，请确认链接已开放且无需登录")
        if not title:
            try:
                title = _normalize_text(
                    await page.locator("h1, .title, [class*='title'], [class*='Title']").first.text_content(timeout=1000)
                )
            except Exception:
                title = ""
        return questions, title or "Credamo 见数问卷"

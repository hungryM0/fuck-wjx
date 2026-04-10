"""问卷星 HTML 解析：矩阵与滑块。"""
import logging
import re
from typing import Any, List, Optional, Tuple

from software.logging.log_utils import log_suppressed_exception
from .html_parser_common import _normalize_html_text


def _postprocess_matrix_option_texts(option_texts: List[str]) -> List[str]:
    """矩阵列标题后处理：保序精确去重，并过滤空文本。"""
    if not option_texts:
        return []
    cleaned: List[str] = []
    seen = set()
    for raw_text in option_texts:
        text = _normalize_html_text(raw_text)
        if not text:
            continue
        # 只按“完全相同文本”判定重复，避免误合并相近选项。
        if text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned

def _collect_matrix_option_texts(soup, question_div, question_number: int) -> Tuple[int, List[str], List[str]]:
    option_texts: List[str] = []
    matrix_rows = 0
    row_texts: List[str] = []
    def _extract_attr_text(node) -> str:
        if node is None:
            return ""
        keys = (
            "title",
            "data-title",
            "data-text",
            "data-label",
            "aria-label",
            "alt",
            "htitle",
            "data-original-title",
        )
        for key in keys:
            try:
                raw = node.get(key)
            except Exception:
                raw = None
            if raw is None:
                continue
            text_value = _normalize_html_text(str(raw))
            if text_value:
                return text_value
        return ""

    def _extract_row_label(row, cells) -> str:
        label_text = ""
        if cells:
            label_text = _normalize_html_text(cells[0].get_text(" ", strip=True))
            if not label_text:
                label_text = _extract_attr_text(cells[0])
        if not label_text:
            label_text = _extract_attr_text(row)
        if not label_text:
            try:
                for selector in (
                    ".label",
                    ".row-title",
                    ".rowtitle",
                    ".row",
                    ".item-title",
                    ".itemTitle",
                    ".itemTitleSpan",
                    ".stitle",
                ):
                    node = row.select_one(selector)
                    if node:
                        label_text = _normalize_html_text(node.get_text(" ", strip=True))
                        if label_text:
                            break
            except Exception as exc:
                log_suppressed_exception("survey.parser._extract_row_label selector", exc, level=logging.ERROR)
        if not label_text:
            try:
                for child in row.find_all(["label", "span", "div", "p"], limit=10):
                    label_text = _extract_attr_text(child)
                    if label_text:
                        break
                    label_text = _normalize_html_text(child.get_text(" ", strip=True))
                    if label_text:
                        break
            except Exception as exc:
                log_suppressed_exception("survey.parser._extract_row_label child", exc, level=logging.ERROR)
        return label_text
    table = None
    if question_div is not None:
        try:
            table = question_div.find(id=f"divRefTab{question_number}")
        except Exception:
            table = None
    if table is None and soup:
        table = soup.find(id=f"divRefTab{question_number}")
    if table:
        # 按HTML中的出现顺序提取行标签，而不是按rowindex排序
        # 这样可以保持与用户看到的顺序一致
        for row in table.find_all("tr"):
            row_index = str(row.get("rowindex") or "").strip()
            if row_index and str(row_index).isdigit():
                matrix_rows += 1
                try:
                    cells = row.find_all(["td", "th"])
                except Exception:
                    cells = []
                if cells:
                    label_text = _extract_row_label(row, cells)
                    # 直接按出现顺序添加到列表，而不是用rowindex作为索引
                    row_texts.append(label_text)
    if matrix_rows > 0:
        # row_texts 已经按HTML顺序填充，无需再从map中提取
        pass
    elif table:
        # 兼容没有 rowindex 的矩阵题：用表格行作为兜底
        data_rows = []
        header_id = f"drv{question_number}_1"
        for row in table.find_all("tr"):
            row_id = str(row.get("id") or "")
            if row_id == header_id:
                continue
            try:
                cells = row.find_all(["td", "th"])
            except Exception:
                cells = []
            if len(cells) <= 1:
                continue
            first_text = _extract_row_label(row, cells)
            other_texts = [_normalize_html_text(cell.get_text(" ", strip=True)) for cell in cells[1:]]
            # 如果首列为空、后面有标题文字，多半是表头行
            if not first_text and any(other_texts):
                continue
            data_rows.append((first_text, cells))
        matrix_rows = len(data_rows)
        row_texts = [label for label, _ in data_rows]
        if not option_texts and data_rows:
            max_cols = 0
            for _, cells in data_rows:
                try:
                    max_cols = max(max_cols, max(0, len(cells) - 1))
                except Exception:
                    continue
            if max_cols > 0:
                option_texts = [str(i + 1) for i in range(max_cols)]
    if matrix_rows == 0 and question_div is not None:
        # 再兜底：从输入控件名推断行列数
        try:
            inputs = question_div.find_all("input")
        except Exception:
            inputs = []
        row_indices: List[int] = []
        col_indices: List[int] = []
        name_pattern = re.compile(rf"q{question_number}[_-](\d+)(?:[_-](\d+))?")
        for item in inputs:
            raw_name = str(item.get("name") or item.get("id") or "")
            if not raw_name:
                continue
            match = name_pattern.search(raw_name)
            if not match:
                continue
            try:
                row_idx = int(match.group(1))
                row_indices.append(row_idx)
            except Exception as exc:
                log_suppressed_exception("survey.parser._collect_matrix_rows row_idx", exc, level=logging.ERROR)
            if match.group(2):
                try:
                    col_idx = int(match.group(2))
                    col_indices.append(col_idx)
                except Exception as exc:
                    log_suppressed_exception("survey.parser._collect_matrix_rows col_idx", exc, level=logging.ERROR)
        if row_indices:
            matrix_rows = max(row_indices)
            row_texts = [""] * matrix_rows
        if not option_texts and col_indices:
            max_cols = max(col_indices)
            if max_cols > 0:
                option_texts = [str(i + 1) for i in range(max_cols)]
    if question_div is not None and (not row_texts or any(not text for text in row_texts)):
        try:
            candidates = []
            for selector in (".itemTitleSpan", ".itemTitle", ".item-title", ".row-title"):
                nodes = question_div.select(selector)
                if nodes:
                    candidates = [_normalize_html_text(node.get_text(" ", strip=True)) for node in nodes]
                    candidates = [text for text in candidates if text]
                    if candidates:
                        break
            if candidates:
                if matrix_rows <= 0:
                    matrix_rows = len(candidates)
                    row_texts = list(candidates)
                else:
                    merged: List[str] = list(row_texts)
                    for idx in range(min(len(candidates), len(merged))):
                        if not merged[idx]:
                            merged[idx] = candidates[idx]
                    row_texts = merged
        except Exception as exc:
            log_suppressed_exception("survey.parser._collect_matrix_rows merge", exc, level=logging.ERROR)
    header_row = soup.find(id=f"drv{question_number}_1") if soup else None
    if header_row:
        cells = header_row.find_all("td")
        if len(cells) > 1:
            option_texts = [_normalize_html_text(td.get_text(" ", strip=True)) for td in cells[1:]]
            option_texts = [text for text in option_texts if text]
    if not option_texts and table:
        header_cells = table.find_all("th")
        if len(header_cells) > 1:
            option_texts = [_normalize_html_text(th.get_text(" ", strip=True)) for th in header_cells[1:]]
            option_texts = [text for text in option_texts if text]
    raw_option_texts = list(option_texts)
    option_texts = _postprocess_matrix_option_texts(option_texts)
    # 兜底：若表头文本全为空或清洗后为空，按已有列数生成数字标题。
    if not option_texts:
        fallback_columns = len([text for text in raw_option_texts if _normalize_html_text(text)])
        if fallback_columns > 0:
            option_texts = [str(i + 1) for i in range(fallback_columns)]
    return matrix_rows, option_texts, row_texts

def _extract_slider_range(question_div, question_number: int) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """尝试解析滑块题的最小值、最大值和步长。"""
    try:
        slider_input = question_div.find("input", id=f"q{question_number}")
        if not slider_input:
            slider_input = question_div.find("input", attrs={"type": "range"})
        if not slider_input:
            slider_input = question_div.find("input", class_=lambda value: value and "ui-slider-input" in str(value))
    except Exception:
        slider_input = None

    def _parse(raw: Any) -> Optional[float]:
        try:
            return float(raw)
        except Exception:
            return None

    if slider_input:
        return (
            _parse(slider_input.get("min")),
            _parse(slider_input.get("max")),
            _parse(slider_input.get("step")),
        )
    return None, None, None

def _question_div_looks_like_slider_matrix(question_div) -> bool:
    """识别问卷星 type=9 的多行滑块题结构。"""
    if question_div is None:
        return False
    try:
        slider_inputs = question_div.select("input.ui-slider-input[rowid]")
    except Exception:
        slider_inputs = []
    if len(slider_inputs) < 2:
        return False
    try:
        slider_tracks = question_div.select(".rangeslider, .range-slider, .wjx-slider")
    except Exception:
        slider_tracks = []
    return len(slider_tracks) >= len(slider_inputs)

def _format_slider_matrix_value(value: float) -> str:
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:.6f}".rstrip("0").rstrip(".")

def _build_slider_matrix_option_texts_from_input(slider_input) -> List[str]:
    def _parse(raw: Any) -> Optional[float]:
        try:
            return float(raw)
        except Exception:
            return None

    min_value = _parse(slider_input.get("min"))
    max_value = _parse(slider_input.get("max"))
    step_value = _parse(slider_input.get("step"))
    if min_value is None or max_value is None:
        return []
    if step_value is None or step_value <= 0:
        step_value = 1.0
    if max_value < min_value:
        min_value, max_value = max_value, min_value
    max_count = 200
    values: List[str] = []
    current = min_value
    while current <= max_value + 1e-9 and len(values) < max_count:
        values.append(_format_slider_matrix_value(current))
        current += step_value
    return values

def _collect_slider_matrix_metadata(question_div) -> Tuple[int, List[str], List[str]]:
    """提取多行滑块题的行标题与刻度值。"""
    if question_div is None:
        return 0, [], []

    row_texts: List[str] = []
    option_texts: List[str] = []

    try:
        row_titles = question_div.select("tr.rowtitletr .itemTitleSpan")
    except Exception:
        row_titles = []
    if not row_titles:
        try:
            row_titles = question_div.select("tr.rowtitletr td.title")
        except Exception:
            row_titles = []
    if not row_titles:
        try:
            row_titles = question_div.select("tr[id$='t'] .itemTitleSpan, tr[id$='t'] td.title")
        except Exception:
            row_titles = []
    for title in row_titles:
        text = _normalize_html_text(title.get_text(" ", strip=True))
        if text:
            row_texts.append(text)

    try:
        scale_nodes = question_div.select(".ruler .cm[data-value]")
    except Exception:
        scale_nodes = []
    seen_values = set()
    for node in scale_nodes:
        value = _normalize_html_text(node.get("data-value") or "")
        if value and value not in seen_values:
            seen_values.add(value)
            option_texts.append(value)

    try:
        slider_inputs = question_div.select("input.ui-slider-input[rowid]")
    except Exception:
        slider_inputs = []
    if not option_texts and slider_inputs:
        option_texts = _build_slider_matrix_option_texts_from_input(slider_inputs[0])

    matrix_rows = len(slider_inputs) if slider_inputs else len(row_texts)
    if matrix_rows <= 0:
        matrix_rows = len(question_div.select("tr[id^='drv']"))

    return matrix_rows, option_texts, row_texts

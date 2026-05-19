"""反填页纯逻辑。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable

from software.core.reverse_fill.schema import (
    REVERSE_FILL_STATUS_FALLBACK,
    REVERSE_FILL_STATUS_REVERSE,
    ReverseFillSpec,
)


_STATUS_LABELS = {
    "reverse": "🟢 正常",
    "reverse_fill": "🟢 正常",
    "fallback": "🟡 需要处理",
    "fallback_config": "🟡 需要处理",
    "blocked": "🔴 不支持",
}

_QUESTION_TYPE_LABELS = {
    "single": "单选题",
    "multiple": "多选题",
    "dropdown": "下拉选择题",
    "scale": "量表题",
    "score": "评价题",
    "text": "填空题",
    "multi_text": "多项填空题",
    "matrix": "矩阵题",
    "order": "排序题",
}

_NON_ACTIONABLE_ISSUE_CATEGORIES = {"auto_handled"}


def status_label_for_plan(plan: Any) -> str:
    status = str(getattr(plan, "status", "") or "")
    if status == REVERSE_FILL_STATUS_FALLBACK and bool(getattr(plan, "fallback_resolved", False)):
        return "🟢 已处理"
    if status == REVERSE_FILL_STATUS_FALLBACK and bool(getattr(plan, "fallback_ready", False)):
        return "🟡 可回退"
    return _STATUS_LABELS.get(status, status)


def question_type_label(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return ""
    return _QUESTION_TYPE_LABELS.get(normalized, str(value or "").strip())


def is_supported_excel_path(file_path: str) -> bool:
    normalized = str(file_path or "").strip()
    return bool(normalized) and os.path.isfile(normalized) and normalized.lower().endswith(".xlsx")


@dataclass(frozen=True)
class ReverseFillPreviewState:
    detected_text: str
    hint_text: str
    controls_enabled: bool
    issue_question_nums: list[int]
    show_open_wizard: bool


def build_plan_rows(spec: ReverseFillSpec) -> list[list[str]]:
    issues_by_question: dict[int, list[Any]] = {}
    for issue in list(spec.issues or []):
        key = int(issue.question_num or 0)
        issues_by_question.setdefault(key, []).append(issue)

    rows: list[list[str]] = []
    plans = list(spec.question_plans or [])
    for plan in plans:
        question_num = int(plan.question_num or 0)
        issues = issues_by_question.get(question_num, [])
        detail_parts = [text for text in [str(plan.detail or "").strip()] if text]
        suggestion_parts: list[str] = []
        for issue in issues:
            reason = str(issue.reason or "").strip()
            if reason and reason not in detail_parts:
                detail_parts.append(reason)
            suggestion = str(issue.suggestion or "").strip()
            if suggestion and suggestion not in suggestion_parts:
                suggestion_parts.append(suggestion)
        if not issues and str(plan.status or "") == REVERSE_FILL_STATUS_REVERSE:
            suggestion_parts.append("无需处理")
        rows.append(
            [
                str(question_num),
                question_type_label(plan.question_type),
                status_label_for_plan(plan),
                " / ".join(list(plan.column_headers or [])),
                "\n".join(detail_parts) or "无",
                "\n".join(suggestion_parts) or "无",
            ]
        )

    for issue in list(issues_by_question.get(0, [])):
        rows.append(
            [
                "全局",
                str(issue.category or "全局"),
                "🔴 不支持",
                "无",
                str(issue.reason or ""),
                str(issue.suggestion or ""),
            ]
        )
    return rows


def actionable_issue_question_nums(spec: ReverseFillSpec) -> list[int]:
    return sorted(
        {
            int(item.question_num or 0)
            for item in list(spec.issues or [])
            if str(getattr(item, "category", "") or "").strip()
            not in _NON_ACTIONABLE_ISSUE_CATEGORIES
            and int(item.question_num or 0) > 0
        }
    )


def iter_supported_drop_paths(urls: Iterable[Any]) -> list[str]:
    paths: list[str] = []
    for url in urls:
        local_file = str(url.toLocalFile() or "").strip()
        if is_supported_excel_path(local_file):
            paths.append(local_file)
    return paths

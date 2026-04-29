"""Build and validate WJX reverse fill specs."""

from __future__ import annotations

import copy
import os
from typing import Any, Dict, List, Optional

from software.core.questions.schema import QuestionEntry
from software.core.questions.validation import validate_question_config
from software.core.reverse_fill.parser import (
    infer_reverse_fill_question_type,
    parse_choice_answer,
    parse_matrix_answer,
    parse_multi_text_answer,
    parse_text_answer,
    resolve_ordered_columns,
    resolve_question_entry,
    supports_reverse_fill_runtime,
)
from software.core.reverse_fill.schema import (
    REVERSE_FILL_FORMAT_AUTO,
    REVERSE_FILL_FORMAT_WJX_SEQUENCE,
    REVERSE_FILL_STATUS_BLOCKED,
    REVERSE_FILL_STATUS_FALLBACK,
    REVERSE_FILL_STATUS_REVERSE,
    ReverseFillIssue,
    ReverseFillQuestionPlan,
    ReverseFillSampleRow,
    ReverseFillSpec,
    reverse_fill_format_label,
)
from software.io.spreadsheets import load_wjx_excel_export
from software.io.config import RuntimeConfig
from software.providers.common import SURVEY_PROVIDER_WJX, normalize_survey_provider
from software.providers.contracts import SurveyQuestionMeta, ensure_survey_question_meta


def _detail_from_columns(columns: List[Any]) -> str:
    headers = [str(getattr(column, "header", "") or "").strip() for column in list(columns or []) if str(getattr(column, "header", "") or "").strip()]
    return " / ".join(headers)


def _regular_config_ready(entry: Optional[QuestionEntry], info: SurveyQuestionMeta | Dict[str, Any], expected_type: str) -> bool:
    if entry is None:
        return False
    if str(getattr(entry, "question_type", "") or "").strip() != str(expected_type or "").strip():
        return False
    copied_entry = copy.deepcopy(entry)
    copied_info = ensure_survey_question_meta(info)
    return validate_question_config([copied_entry], [copied_info]) is None


def _question_issue(
    *,
    question_num: int,
    title: str,
    category: str,
    reason: str,
    fallback_ready: bool,
    sample_rows: Optional[List[int]] = None,
) -> ReverseFillIssue:
    suggestion = "已回退到当前题目的常规配置，可继续运行" if fallback_ready else "请先打开配置向导，把这题的常规配置补齐后再启动"
    severity = "warn" if fallback_ready else "block"
    return ReverseFillIssue(
        question_num=question_num,
        title=title,
        severity=severity,
        category=category,
        reason=reason,
        suggestion=suggestion,
        sample_rows=list(sample_rows or []),
    )


def _build_question_plan(
    *,
    question_num: int,
    title: str,
    question_type: str,
    status: str,
    columns: List[Any],
    detail: str,
    fallback_ready: bool,
) -> ReverseFillQuestionPlan:
    headers = [str(getattr(column, "header", "") or "").strip() for column in list(columns or []) if str(getattr(column, "header", "") or "").strip()]
    return ReverseFillQuestionPlan(
        question_num=question_num,
        title=title,
        question_type=question_type,
        status=status,
        column_headers=headers,
        detail=detail,
        fallback_ready=bool(fallback_ready),
    )


def _build_global_issue(*, target_num: int, available_samples: int) -> ReverseFillIssue:
    return ReverseFillIssue(
        question_num=0,
        title="样本总量",
        severity="block",
        category="sample_shortage",
        reason=f"目标份数为 {target_num}，但从起始样本行开始只剩 {available_samples} 行可用样本",
        suggestion="请降低目标份数，或把起始样本行往前调，或更换样本更多的 Excel",
    )


def build_reverse_fill_spec(
    *,
    source_path: str,
    survey_provider: str,
    questions_info: List[SurveyQuestionMeta | Dict[str, Any]],
    question_entries: List[QuestionEntry],
    selected_format: str = REVERSE_FILL_FORMAT_AUTO,
    start_row: int = 1,
    target_num: int = 0,
) -> ReverseFillSpec:
    provider = normalize_survey_provider(survey_provider, default=SURVEY_PROVIDER_WJX)
    if provider != SURVEY_PROVIDER_WJX:
        raise ValueError("反填 V1 目前只支持问卷星")
    if not questions_info:
        raise ValueError("当前还没有解析出问卷题目，无法校验反填")

    export = load_wjx_excel_export(source_path, preferred_format=selected_format)
    normalized_start_row = max(1, int(start_row or 1))
    total_samples = int(export.total_data_rows or 0)
    available_rows = max(0, total_samples - normalized_start_row + 1)
    selected_rows = list(export.raw_rows or [])[normalized_start_row - 1 :]

    issues: List[ReverseFillIssue] = []
    question_plans: List[ReverseFillQuestionPlan] = []
    answers_by_row: Dict[int, Dict[int, Any]] = {
        int(row.data_row_number): {} for row in selected_rows
    }

    if target_num > 0 and target_num > available_rows:
        issues.append(_build_global_issue(target_num=target_num, available_samples=available_rows))

    for info_index, raw_info in enumerate(list(questions_info or []), start=1):
        if not isinstance(raw_info, (dict, SurveyQuestionMeta)):
            continue
        info = ensure_survey_question_meta(raw_info, index=info_index)
        if bool(info.is_description):
            continue
        question_num = int(info.num or 0)
        if question_num <= 0:
            continue
        title = str(info.title or f"第{question_num}题").strip()
        entry = resolve_question_entry(info, question_entries)
        question_type = infer_reverse_fill_question_type(info, entry)
        columns = list((export.question_columns or {}).get(question_num) or [])
        fallback_ready = _regular_config_ready(entry, info, question_type)

        if bool(info.unsupported):
            reason = str(info.unsupported_reason or "当前程序暂不支持这道题").strip()
            issues.append(
                ReverseFillIssue(
                    question_num=question_num,
                    title=title,
                    severity="block",
                    category="runtime_unsupported",
                    reason=reason,
                    suggestion="这题不是反填没做，是程序本身还不能答，当前版本无法启动",
                )
            )
            question_plans.append(
                _build_question_plan(
                    question_num=question_num,
                    title=title,
                    question_type=question_type,
                    status=REVERSE_FILL_STATUS_BLOCKED,
                    columns=columns,
                    detail=reason,
                    fallback_ready=False,
                )
            )
            continue

        if not supports_reverse_fill_runtime(question_type, info):
            reason = "当前题型或题目结构不在反填 V1 支持范围内"
            issues.append(
                _question_issue(
                    question_num=question_num,
                    title=title,
                    category="unsupported_type",
                    reason=reason,
                    fallback_ready=fallback_ready,
                )
            )
            question_plans.append(
                _build_question_plan(
                    question_num=question_num,
                    title=title,
                    question_type=question_type,
                    status=REVERSE_FILL_STATUS_FALLBACK if fallback_ready else REVERSE_FILL_STATUS_BLOCKED,
                    columns=columns,
                    detail=reason,
                    fallback_ready=fallback_ready,
                )
            )
            continue

        if not columns:
            reason = "Excel 中没有找到这道题对应的列"
            issues.append(
                _question_issue(
                    question_num=question_num,
                    title=title,
                    category="mapping_missing",
                    reason=reason,
                    fallback_ready=fallback_ready,
                )
            )
            question_plans.append(
                _build_question_plan(
                    question_num=question_num,
                    title=title,
                    question_type=question_type,
                    status=REVERSE_FILL_STATUS_FALLBACK if fallback_ready else REVERSE_FILL_STATUS_BLOCKED,
                    columns=columns,
                    detail=reason,
                    fallback_ready=fallback_ready,
                )
            )
            continue

        ordered_columns = columns
        if question_type in {"single", "dropdown", "scale", "score", "text"} and len(columns) != 1:
            reason = "这道题在 Excel 中对应了多列，V1 无法确认唯一答案列"
            issues.append(
                _question_issue(
                    question_num=question_num,
                    title=title,
                    category="mapping_ambiguous",
                    reason=reason,
                    fallback_ready=fallback_ready,
                )
            )
            question_plans.append(
                _build_question_plan(
                    question_num=question_num,
                    title=title,
                    question_type=question_type,
                    status=REVERSE_FILL_STATUS_FALLBACK if fallback_ready else REVERSE_FILL_STATUS_BLOCKED,
                    columns=columns,
                    detail=reason,
                    fallback_ready=fallback_ready,
                )
            )
            continue

        if question_type == "matrix":
            row_texts = list(info.row_texts or [])
            if row_texts and len(columns) != len(row_texts):
                reason = f"矩阵题解析出 {len(row_texts)} 行，但 Excel 里只有 {len(columns)} 列"
                issues.append(
                    _question_issue(
                        question_num=question_num,
                        title=title,
                        category="mapping_mismatch",
                        reason=reason,
                        fallback_ready=fallback_ready,
                    )
                )
                question_plans.append(
                    _build_question_plan(
                        question_num=question_num,
                        title=title,
                        question_type=question_type,
                        status=REVERSE_FILL_STATUS_FALLBACK if fallback_ready else REVERSE_FILL_STATUS_BLOCKED,
                        columns=columns,
                        detail=reason,
                        fallback_ready=fallback_ready,
                    )
                )
                continue
            ordered_columns = resolve_ordered_columns(columns, row_texts)

        if question_type == "multi_text":
            blank_labels = list(info.text_input_labels or [])
            if blank_labels and len(columns) != len(blank_labels):
                reason = f"多项填空解析出 {len(blank_labels)} 个空，但 Excel 里只有 {len(columns)} 列"
                issues.append(
                    _question_issue(
                        question_num=question_num,
                        title=title,
                        category="mapping_mismatch",
                        reason=reason,
                        fallback_ready=fallback_ready,
                    )
                )
                question_plans.append(
                    _build_question_plan(
                        question_num=question_num,
                        title=title,
                        question_type=question_type,
                        status=REVERSE_FILL_STATUS_FALLBACK if fallback_ready else REVERSE_FILL_STATUS_BLOCKED,
                        columns=columns,
                        detail=reason,
                        fallback_ready=fallback_ready,
                    )
                )
                continue
            ordered_columns = resolve_ordered_columns(columns, blank_labels)

        parse_errors: List[int] = []
        for raw_row in selected_rows:
            try:
                if question_type in {"single", "dropdown", "scale", "score"}:
                    answer = parse_choice_answer(
                        question_num=question_num,
                        question_type=question_type,
                        raw_value=(raw_row.values_by_column or {}).get(int(ordered_columns[0].column_index)),
                        export_format=export.selected_format,
                        option_texts=list(info.option_texts or []),
                    )
                elif question_type == "text":
                    answer = parse_text_answer(
                        question_num=question_num,
                        raw_value=(raw_row.values_by_column or {}).get(int(ordered_columns[0].column_index)),
                    )
                elif question_type == "multi_text":
                    answer = parse_multi_text_answer(
                        question_num=question_num,
                        ordered_columns=ordered_columns,
                        raw_row=raw_row,
                    )
                elif question_type == "matrix":
                    answer = parse_matrix_answer(
                        question_num=question_num,
                        ordered_columns=ordered_columns,
                        raw_row=raw_row,
                        export_format=export.selected_format,
                        option_texts=list(info.option_texts or []),
                    )
                else:
                    answer = None
                if answer is not None:
                    answers_by_row[int(raw_row.data_row_number)][question_num] = answer
            except Exception:
                parse_errors.append(int(raw_row.data_row_number))
                break

        if parse_errors:
            if question_type in {"single", "dropdown", "scale", "score", "matrix"}:
                if export.selected_format == REVERSE_FILL_FORMAT_WJX_SEQUENCE:
                    reason = "这道题在样本中出现了超范围序号或 V1 不支持的复合值"
                else:
                    reason = "这道题在样本中出现了无法匹配选项的值或 V1 不支持的复合值"
            else:
                reason = "这道题在样本中出现了 V1 无法稳定回放的值"
            issues.append(
                _question_issue(
                    question_num=question_num,
                    title=title,
                    category="unsupported_value",
                    reason=reason,
                    fallback_ready=fallback_ready,
                    sample_rows=parse_errors[:3],
                )
            )
            question_plans.append(
                _build_question_plan(
                    question_num=question_num,
                    title=title,
                    question_type=question_type,
                    status=REVERSE_FILL_STATUS_FALLBACK if fallback_ready else REVERSE_FILL_STATUS_BLOCKED,
                    columns=columns,
                    detail=reason,
                    fallback_ready=fallback_ready,
                )
            )
            for row_answers in answers_by_row.values():
                row_answers.pop(question_num, None)
            continue

        question_plans.append(
            _build_question_plan(
                question_num=question_num,
                title=title,
                question_type=question_type,
                status=REVERSE_FILL_STATUS_REVERSE,
                columns=ordered_columns,
                detail=f"来源列：{_detail_from_columns(ordered_columns)}",
                fallback_ready=False,
            )
        )

    samples: List[ReverseFillSampleRow] = []
    for raw_row in selected_rows:
        answers = dict(answers_by_row.get(int(raw_row.data_row_number)) or {})
        samples.append(
            ReverseFillSampleRow(
                data_row_number=int(raw_row.data_row_number),
                worksheet_row_number=int(raw_row.worksheet_row_number),
                answers=answers,
            )
        )

    return ReverseFillSpec(
        source_path=os.path.abspath(str(source_path or "").strip()),
        selected_format=str(export.selected_format or REVERSE_FILL_FORMAT_AUTO),
        detected_format=str(export.detected_format or export.selected_format or REVERSE_FILL_FORMAT_AUTO),
        start_row=normalized_start_row,
        total_samples=total_samples,
        available_samples=available_rows,
        target_num=max(0, int(target_num or 0)),
        question_plans=question_plans,
        issues=issues,
        samples=samples,
    )


def format_reverse_fill_blocking_message(spec: ReverseFillSpec) -> str:
    blocking = list(spec.blocking_issues)
    if not blocking:
        return ""
    lines = [
        f"反填配置校验失败（{reverse_fill_format_label(spec.detected_format)}）：",
    ]
    for issue in blocking[:12]:
        prefix = "样本数量" if int(issue.question_num or 0) <= 0 else f"第 {issue.question_num} 题"
        lines.append(f"  - {prefix}：{issue.reason}")
        if issue.suggestion:
            lines.append(f"    {issue.suggestion}")
    if len(blocking) > 12:
        lines.append(f"  - 其余 {len(blocking) - 12} 个阻塞项已省略")
    return "\n".join(lines)


def build_enabled_reverse_fill_spec(
    config: RuntimeConfig,
    questions_info: List[SurveyQuestionMeta | Dict[str, Any]],
    question_entries: List[QuestionEntry],
) -> Optional[ReverseFillSpec]:
    if not bool(getattr(config, "reverse_fill_enabled", False)):
        return None
    source_path = str(getattr(config, "reverse_fill_source_path", "") or "").strip()
    if not source_path:
        raise ValueError("已开启反填，但还没有选择 Excel 文件")
    spec = build_reverse_fill_spec(
        source_path=source_path,
        survey_provider=str(getattr(config, "survey_provider", SURVEY_PROVIDER_WJX) or SURVEY_PROVIDER_WJX),
        questions_info=list(questions_info or []),
        question_entries=list(question_entries or []),
        selected_format=str(getattr(config, "reverse_fill_format", REVERSE_FILL_FORMAT_AUTO) or REVERSE_FILL_FORMAT_AUTO),
        start_row=max(1, int(getattr(config, "reverse_fill_start_row", 1) or 1)),
        target_num=max(0, int(getattr(config, "target", 0) or 0)),
    )
    if spec.blocking_issue_count > 0:
        raise ValueError(format_reverse_fill_blocking_message(spec))
    return spec

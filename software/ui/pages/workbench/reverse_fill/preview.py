"""ReverseFillPage 预检与预览刷新。"""

from __future__ import annotations

from typing import Any

from software.core.reverse_fill.schema import ReverseFillSpec, reverse_fill_format_label
from software.core.reverse_fill.validation import build_reverse_fill_spec
from software.providers.common import SURVEY_PROVIDER_WJX, normalize_survey_provider
from software.ui.pages.workbench.reverse_fill.logic import actionable_issue_question_nums, build_plan_rows
from software.ui.pages.workbench.shared.table_helpers import set_table_text


def clear_tables(page: Any) -> None:
    page._issue_question_nums = []
    page.mapping_table.setRowCount(0)
    page.open_wizard_btn.hide()


def populate_plan_table(page: Any, spec: ReverseFillSpec) -> None:
    rows = build_plan_rows(spec)
    page.mapping_table.setRowCount(len(rows))
    for row_index, row_values in enumerate(rows):
        for column_index, value in enumerate(row_values):
            set_table_text(page.mapping_table, row_index, column_index, value)


def refresh_preview(page: Any) -> None:
    page._last_spec = None
    page._last_error = ""
    source_path = page.file_edit.text().strip()
    context_ready = page._context_ready()
    has_link_text = page._has_survey_link_text()
    page._sync_start_button_state()

    controls_enabled = has_link_text
    page.file_edit.setEnabled(controls_enabled)
    page.browse_btn.setEnabled(controls_enabled)
    page.open_wizard_btn.hide()

    if not context_ready:
        provider = normalize_survey_provider(page._survey_provider, default="")
        if not has_link_text:
            hint = ""
        elif page._parsed_url and page.url_edit.text().strip() != page._parsed_url:
            hint = ""
        elif provider != SURVEY_PROVIDER_WJX:
            hint = "该执行总线暂不能在当前平台环境接管反填覆盖支持，相关控制流已全托管休眠"
        else:
            hint = ""

        page.detected_format_label.setText("验证结果：未接通目标流")
        page.state_hint_label.setText(hint)
        clear_tables(page)
        return

    if not source_path:
        page.detected_format_label.setText("验证结果：待指定 Excel 数据池")
        page.state_hint_label.setText("")
        clear_tables(page)
        return

    try:
        spec = build_reverse_fill_spec(
            source_path=source_path,
            survey_provider=page._survey_provider or SURVEY_PROVIDER_WJX,
            questions_info=page._questions_info,
            question_entries=page._question_entries,
            selected_format=page._selected_format(),
            start_row=max(1, int(page._start_row_value or 1)),
            target_num=0,
        )
    except Exception as exc:
        page._last_error = str(exc)
        page.detected_format_label.setText("验证结果：提取引发崩溃挂起")
        page.state_hint_label.setText(page._last_error)
        clear_tables(page)
        return

    page._last_spec = spec
    page.detected_format_label.setText(
        f"识别格式：{reverse_fill_format_label(spec.detected_format)}"
    )
    page.state_hint_label.setText("")

    page._issue_question_nums = actionable_issue_question_nums(spec)
    page.open_wizard_btn.setVisible(bool(page._issue_question_nums))
    populate_plan_table(page, spec)

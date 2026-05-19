from __future__ import annotations

from types import SimpleNamespace

from software.core.reverse_fill.schema import (
    REVERSE_FILL_FORMAT_AUTO,
    REVERSE_FILL_STATUS_BLOCKED,
    REVERSE_FILL_STATUS_FALLBACK,
    REVERSE_FILL_STATUS_REVERSE,
    ReverseFillIssue,
    ReverseFillQuestionPlan,
    ReverseFillSpec,
)
from software.ui.pages.workbench.reverse_fill import logic


class ReverseFillLogicTests:
    def test_status_and_question_type_labels_cover_known_and_unknown_values(self) -> None:
        assert logic.status_label_for_plan(SimpleNamespace(status=REVERSE_FILL_STATUS_REVERSE)) == "🟢 正常"
        assert logic.status_label_for_plan(SimpleNamespace(status=REVERSE_FILL_STATUS_FALLBACK, fallback_resolved=True)) == "🟢 已处理"
        assert logic.status_label_for_plan(SimpleNamespace(status=REVERSE_FILL_STATUS_FALLBACK, fallback_ready=True)) == "🟡 可回退"
        assert logic.status_label_for_plan(SimpleNamespace(status=REVERSE_FILL_STATUS_BLOCKED)) == "🔴 不支持"
        assert logic.status_label_for_plan(SimpleNamespace(status="custom")) == "custom"
        assert logic.question_type_label("single") == "单选题"
        assert logic.question_type_label("Custom") == "Custom"
        assert logic.question_type_label("") == ""

    def test_supported_excel_path_requires_existing_xlsx_file(self, tmp_path) -> None:
        xlsx = tmp_path / "data.xlsx"
        txt = tmp_path / "data.txt"
        xlsx.write_text("x", encoding="utf-8")
        txt.write_text("x", encoding="utf-8")

        assert logic.is_supported_excel_path(str(xlsx))
        assert not logic.is_supported_excel_path(str(txt))
        assert not logic.is_supported_excel_path(str(tmp_path / "missing.xlsx"))
        assert not logic.is_supported_excel_path("")

    def test_build_plan_rows_merges_plan_details_issues_and_global_issue(self) -> None:
        spec = ReverseFillSpec(
            source_path="demo.xlsx",
            selected_format=REVERSE_FILL_FORMAT_AUTO,
            detected_format=REVERSE_FILL_FORMAT_AUTO,
            start_row=2,
            total_samples=3,
            available_samples=2,
            target_num=2,
            question_plans=[
                ReverseFillQuestionPlan(
                    question_num=1,
                    title="满意度",
                    question_type="single",
                    status=REVERSE_FILL_STATUS_REVERSE,
                    column_headers=["Q1"],
                    detail="已匹配",
                ),
                ReverseFillQuestionPlan(
                    question_num=2,
                    title="说明",
                    question_type="text",
                    status=REVERSE_FILL_STATUS_FALLBACK,
                    column_headers=[],
                    detail="",
                    fallback_ready=True,
                ),
            ],
            issues=[
                ReverseFillIssue(1, "满意度", "warn", "choice", "选项缺失", "补齐选项"),
                ReverseFillIssue(2, "说明", "warn", "auto_handled", "已自动处理", "不用处理"),
                ReverseFillIssue(0, "全局", "block", "format", "格式不支持", "换文件"),
            ],
        )

        rows = logic.build_plan_rows(spec)

        assert rows[0] == ["1", "单选题", "🟢 正常", "Q1", "已匹配\n选项缺失", "补齐选项"]
        assert rows[1][0:3] == ["2", "填空题", "🟡 可回退"]
        assert rows[2] == ["全局", "format", "🔴 不支持", "无", "格式不支持", "换文件"]
        assert logic.actionable_issue_question_nums(spec) == [1]

    def test_iter_supported_drop_paths_filters_non_excel_urls(self, tmp_path) -> None:
        xlsx = tmp_path / "ok.xlsx"
        xlsx.write_text("x", encoding="utf-8")

        urls = [
            SimpleNamespace(toLocalFile=lambda: str(xlsx)),
            SimpleNamespace(toLocalFile=lambda: str(tmp_path / "missing.xlsx")),
            SimpleNamespace(toLocalFile=lambda: ""),
        ]

        assert logic.iter_supported_drop_paths(urls) == [str(xlsx)]

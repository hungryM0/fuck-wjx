"""DashboardPage 题目表格与批量编辑相关方法。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence

from PySide6.QtWidgets import QDialog
from qfluentwidgets import MessageBox
from shiboken6 import isValid

from software.core.questions.config import QuestionEntry
from software.core.questions.utils import (
    describe_random_int_range,
    parse_random_int_token,
)
from software.providers.contracts import SurveyQuestionMeta
from software.ui.pages.workbench.question_editor.constants import (
    _get_entry_type_label,
)
from software.ui.pages.workbench.question_editor.wizard_dialog import (
    QuestionWizardDialog,
)
from software.ui.pages.workbench.question_editor.psycho_config import (
    PSYCHO_SUPPORTED_TYPES,
    entry_supports_psycho_presets,
)
from software.ui.pages.workbench.shared.table_helpers import set_table_text
from software.ui.pages.workbench.strategy.utils import entry_dimension_label

_TEXT_RANDOM_NAME_TOKEN = "__RANDOM_NAME__"
_TEXT_RANDOM_MOBILE_TOKEN = "__RANDOM_MOBILE__"


_TEXT_RANDOM_ID_CARD_TOKEN = "__RANDOM_ID_CARD__"

WizardResultGetter = Callable[[QuestionWizardDialog], Dict[int, Any]]
WizardEntryApplier = Callable[[QuestionEntry, Any], None]
WizardApplyRule = tuple[WizardResultGetter, WizardEntryApplier]


def _pretty_text_answer(value: Any) -> str:
    text = str(value or "").strip()
    random_int_range = parse_random_int_token(text)
    if random_int_range is not None:
        return f"随机整数({describe_random_int_range(random_int_range)})"
    if text == _TEXT_RANDOM_NAME_TOKEN:
        return "随机姓名"
    if text == _TEXT_RANDOM_MOBILE_TOKEN:
        return "随机手机号"
    if text == _TEXT_RANDOM_ID_CARD_TOKEN:
        return "随机身份证号"
    return text


def _normalize_wizard_weights(raw: Any) -> Any:
    if isinstance(raw, list) and any(isinstance(item, (list, tuple)) for item in raw):
        cleaned: List[List[float]] = []
        for row in raw:
            if not isinstance(row, (list, tuple)):
                continue
            cleaned.append([float(max(0, value)) for value in row])
        return cleaned
    if isinstance(raw, list):
        return [float(max(0, value)) for value in raw]
    return raw


def _apply_result_updates(
    entries: List[QuestionEntry],
    updates: Dict[int, Any],
    applier: WizardEntryApplier,
) -> None:
    for idx, value in updates.items():
        if 0 <= idx < len(entries):
            applier(entries[idx], value)


def _apply_distribution_result(entry: QuestionEntry, raw_weights: Any) -> None:
    normalized = _normalize_wizard_weights(raw_weights)
    entry.custom_weights = normalized
    entry.probabilities = normalized
    entry.distribution_mode = "custom"


def _apply_text_result(entry: QuestionEntry, texts: Any) -> None:
    entry.texts = texts


def _apply_location_result(entry: QuestionEntry, parts: Any) -> None:
    entry.location_parts = [str(item or "").strip() for item in list(parts or [])[:3]]


def _apply_option_fill_result(entry: QuestionEntry, option_fill_texts: Any) -> None:
    if entry.question_type not in ("single", "multiple", "dropdown"):
        return
    entry.option_fill_texts = (
        option_fill_texts if any(text for text in option_fill_texts if text) else None
    )


def _apply_text_random_mode_result(entry: QuestionEntry, random_mode: Any) -> None:
    entry.text_random_mode = str(random_mode or "none") if entry.question_type == "text" else "none"


def _apply_text_random_int_range_result(entry: QuestionEntry, int_range: Any) -> None:
    entry.text_random_int_range = int_range if entry.question_type == "text" else []


def _apply_ai_flag_result(entry: QuestionEntry, enabled: Any) -> None:
    entry.ai_enabled = bool(enabled) if entry.question_type in ("text", "multi_text") else False


def _apply_attached_select_result(entry: QuestionEntry, attached_configs: Any) -> None:
    entry.attached_option_selects = attached_configs


def _apply_multi_text_blank_modes_result(entry: QuestionEntry, modes: Any) -> None:
    entry.multi_text_blank_modes = modes


def _apply_multi_text_blank_int_ranges_result(entry: QuestionEntry, int_ranges: Any) -> None:
    entry.multi_text_blank_int_ranges = int_ranges


def _apply_multi_text_blank_ai_flags_result(entry: QuestionEntry, flags: Any) -> None:
    entry.multi_text_blank_ai_flags = flags


def _apply_dimension_result(entry: QuestionEntry, dimension: Any) -> None:
    entry.dimension = dimension


def _apply_bias_preset_result(entry: QuestionEntry, bias: Any) -> None:
    entry.psycho_bias = bias


_WIZARD_DISTRIBUTION_RULES: Sequence[WizardApplyRule] = (
    (QuestionWizardDialog.get_results, _apply_distribution_result),
)

_WIZARD_TEXT_RULES: Sequence[WizardApplyRule] = (
    (QuestionWizardDialog.get_text_results, _apply_text_result),
    (QuestionWizardDialog.get_location_results, _apply_location_result),
    (QuestionWizardDialog.get_option_fill_results, _apply_option_fill_result),
    (QuestionWizardDialog.get_text_random_modes, _apply_text_random_mode_result),
    (QuestionWizardDialog.get_text_random_int_ranges, _apply_text_random_int_range_result),
    (QuestionWizardDialog.get_ai_flags, _apply_ai_flag_result),
    (QuestionWizardDialog.get_attached_select_results, _apply_attached_select_result),
    (QuestionWizardDialog.get_multi_text_blank_modes, _apply_multi_text_blank_modes_result),
    (
        QuestionWizardDialog.get_multi_text_blank_int_ranges,
        _apply_multi_text_blank_int_ranges_result,
    ),
    (QuestionWizardDialog.get_multi_text_blank_ai_flags, _apply_multi_text_blank_ai_flags_result),
)

_WIZARD_META_RULES: Sequence[WizardApplyRule] = (
    (QuestionWizardDialog.get_dimensions, _apply_dimension_result),
    (QuestionWizardDialog.get_bias_presets, _apply_bias_preset_result),
)


def question_summary(entry: QuestionEntry) -> str:
    """生成题目配置摘要"""
    bias = getattr(entry, "psycho_bias", "custom") or "custom"
    if (
        getattr(entry, "question_type", "") in PSYCHO_SUPPORTED_TYPES
        or entry_supports_psycho_presets(entry, list(getattr(entry, "texts", []) or []))
    ) and bias in (
        "left",
        "center",
        "right",
    ):
        bias_text = {"left": "偏左", "center": "居中", "right": "偏右"}.get(bias, bias)
        return f"倾向预设: {bias_text}"

    if entry.question_type in ("text", "multi_text"):
        if bool(getattr(entry, "is_location", False)):
            parts = [part for part in list(getattr(entry, "location_parts", []) or []) if str(part or "").strip()]
            return f"地区: {'-'.join(parts)}" if parts else "地区: 自动选择"
        if entry.question_type == "text":
            random_mode = str(getattr(entry, "text_random_mode", "none") or "none").strip().lower()
            if random_mode == "name":
                return "答案: 随机姓名"
            if random_mode == "mobile":
                return "答案: 随机手机号"
            if random_mode == "id_card":
                return "答案: 随机身份证号"
            if random_mode == "integer":
                int_range = getattr(entry, "text_random_int_range", [])
                range_text = describe_random_int_range(int_range)
                return f"答案: 随机整数({range_text})"
        else:
            blank_modes = list(getattr(entry, "multi_text_blank_modes", []) or [])
            blank_ai_flags = list(getattr(entry, "multi_text_blank_ai_flags", []) or [])
            blank_int_ranges = list(getattr(entry, "multi_text_blank_int_ranges", []) or [])
            if blank_modes or blank_ai_flags:
                config_parts: List[str] = []
                blank_count = max(
                    len(blank_modes),
                    len(blank_ai_flags),
                    len(blank_int_ranges),
                )
                for idx in range(blank_count):
                    if idx < len(blank_ai_flags) and blank_ai_flags[idx]:
                        config_parts.append(f"填空{idx + 1}: AI")
                        continue
                    mode = blank_modes[idx] if idx < len(blank_modes) else "none"
                    if mode == "name":
                        config_parts.append(f"填空{idx + 1}: 随机姓名")
                    elif mode == "mobile":
                        config_parts.append(f"填空{idx + 1}: 随机手机号")
                    elif mode == "id_card":
                        config_parts.append(f"填空{idx + 1}: 随机身份证号")
                    elif mode == "integer":
                        int_range = blank_int_ranges[idx] if idx < len(blank_int_ranges) else []
                        range_text = describe_random_int_range(int_range)
                        config_parts.append(f"填空{idx + 1}: 随机整数({range_text})")
                if config_parts:
                    summary = " | ".join(config_parts[:2])
                    if len(config_parts) > 2:
                        summary += f" (+{len(config_parts) - 2})"
                    return summary
        texts = entry.texts or []
        if texts:
            preview = [_pretty_text_answer(text) for text in texts[:2]]
            summary = f"答案: {' | '.join(preview)}"
            if len(texts) > 2:
                summary += f" (+{len(texts) - 2})"
            if entry.question_type == "text" and getattr(entry, "ai_enabled", False):
                summary += " | AI"
            return summary
        summary = "答案: 无"
        if entry.question_type == "text" and getattr(entry, "ai_enabled", False):
            summary += " | AI"
        return summary
    if entry.question_type == "matrix":
        rows = max(1, int(entry.rows or 1))
        cols = max(1, int(entry.option_count or 1))
        if isinstance(entry.custom_weights, list) or isinstance(entry.probabilities, list):
            return f"{rows} 行 × {cols} 列 - 按行配比"
        return f"{rows} 行 × {cols} 列 - 完全随机"
    if entry.question_type == "order":
        return "排序题 - 自动随机排序"
    if entry.custom_weights and not isinstance(entry.custom_weights[0], list):
        weights = entry.custom_weights
        if entry.question_type == "multiple":
            values = [f"{int(w)}%" for w in weights[:4] if isinstance(w, (int, float))]
            summary = f"自定义概率: {','.join(values)}"
        else:
            values = [str(int(w)) for w in weights[:4] if isinstance(w, (int, float))]
            summary = f"自定义配比: {','.join(values)}"
        if len(weights) > 4:
            summary += "..."
        return summary

    strategy = entry.distribution_mode or "random"
    if strategy not in ("random", "custom"):
        strategy = "random"
    if getattr(entry, "probabilities", None) == -1:
        strategy = "random"
    if entry.question_type == "multiple":
        return "完全随机" if strategy == "random" else "自定义概率"
    return "完全随机" if strategy == "random" else "自定义配比"


def question_dimension(entry: QuestionEntry) -> str:
    return entry_dimension_label(entry)


def _build_entry_row_signature(entry: QuestionEntry, index: int) -> tuple[str, str, str, str]:
    return (
        str(index + 1),
        _get_entry_type_label(entry),
        question_dimension(entry),
        question_summary(entry),
    )


class DashboardEntriesMixin:
    """题目配置表与编辑向导相关方法。"""

    if TYPE_CHECKING:
        workbench_state: Any
        _toast: Any
        entry_table: Any
        count_label: Any
        _sync_start_button_state: Any
        _survey_title: Any
        runtime_page: Any
        window: Any
        controller: Any
        _entry_table_signatures: Any

    def _show_add_question_dialog(self):
        if self.workbench_state.open_add_question_dialog(self.window() or self):
            self._refresh_entry_table()

    def _edit_selected_entries(self):
        selected_rows = self._checked_rows()
        if not selected_rows:
            self._toast("请先勾选要编辑的题目", "warning")
            return
        entries = self.workbench_state.get_entries()
        info = self.workbench_state.entry_questions_info or []
        selected_rows = [row for row in sorted(set(selected_rows)) if 0 <= row < len(entries)]
        if not selected_rows:
            self._toast("未找到可编辑的题目", "warning")
            return
        selected_entries = [entries[row] for row in selected_rows]
        selected_info = [info[row] if row < len(info) else {} for row in selected_rows]
        if self.run_question_wizard(
            selected_entries,
            selected_info,
        ):
            self._refresh_entry_table()

    def _apply_wizard_results(
        self, entries: List[QuestionEntry], dlg: QuestionWizardDialog
    ) -> None:
        for rules in (_WIZARD_DISTRIBUTION_RULES, _WIZARD_TEXT_RULES, _WIZARD_META_RULES):
            for getter, applier in rules:
                _apply_result_updates(entries, getter(dlg), applier)

    def run_question_wizard(
        self,
        entries: List[QuestionEntry],
        info: List[SurveyQuestionMeta | Dict[str, Any]],
        survey_title: Optional[str] = None,
    ) -> bool:
        if not entries:
            self._toast("请先解析问卷或手动添加题目", "warning")
            return False
        title = survey_title if survey_title is not None else self._survey_title
        reliability_mode_enabled = self.runtime_page.reliability_card.switchButton.isChecked()
        dlg = QuestionWizardDialog(
            entries,
            info,
            title,
            parent=self,
            reliability_mode_enabled=reliability_mode_enabled,
        )
        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        try:
            if accepted:
                self._apply_wizard_results(entries, dlg)
                return True
            return False
        except ValueError as exc:
            self._toast(f"配置应用失败：{exc}", "error")
            return False
        finally:
            try:
                if isValid(dlg):
                    dlg.deleteLater()
            except Exception:
                pass

    def _delete_selected_entries(self):
        selected_rows = self._checked_rows()
        if not selected_rows:
            self._toast("请先勾选要删除的题目", "warning")
            return

        count = len(selected_rows)
        box = MessageBox(
            "确认删除",
            f"确定要删除选中的 {count} 个题目吗？\n此操作无法撤销。",
            self.window() or self,
        )
        box.yesButton.setText("确定")
        box.cancelButton.setText("取消")
        if not box.exec():
            return

        entries = self.workbench_state.get_entries()
        for row in sorted(selected_rows, reverse=True):
            if 0 <= row < len(entries):
                entries.pop(row)
        self.workbench_state.set_entries(entries, self.workbench_state.questions_info)
        self._refresh_entry_table()

    def _clear_all_entries(self):
        entries = self.workbench_state.get_entries()
        count = len(entries)
        if count <= 0:
            self._toast("当前没有可清空的题目", "warning")
            return

        box = MessageBox(
            "确认清空",
            f"确定要清空所有已配置的 {count} 个题目吗？\n此操作无法撤销。",
            self.window() or self,
        )
        box.yesButton.setText("确定")
        box.cancelButton.setText("取消")
        if not box.exec():
            return

        self.workbench_state.set_entries([], [])
        self._refresh_entry_table()

    def _refresh_entry_table(self):
        entries = self.workbench_state.get_entries()
        table = self.entry_table
        previous_signatures = list(getattr(self, "_entry_table_signatures", []) or [])
        current_signatures = [_build_entry_row_signature(entry, idx) for idx, entry in enumerate(entries)]
        previous_updates_enabled = table.updatesEnabled()
        previous_sorting_enabled = table.isSortingEnabled()
        table.setUpdatesEnabled(False)
        table.setSortingEnabled(False)
        table.blockSignals(True)
        try:
            previous_row_count = table.rowCount()
            target_row_count = len(entries)
            if previous_row_count != target_row_count:
                table.setRowCount(target_row_count)
            self.count_label.setText(f"{len(entries)} 题")
            for idx, row_signature in enumerate(current_signatures):
                if idx < len(previous_signatures) and previous_signatures[idx] == row_signature:
                    continue
                set_table_text(table, idx, 0, row_signature[0], align_center=True)
                set_table_text(table, idx, 1, row_signature[1], align_center=True)
                set_table_text(table, idx, 2, row_signature[2], align_center=True)
                set_table_text(table, idx, 3, row_signature[3])
        finally:
            table.blockSignals(False)
            table.setSortingEnabled(previous_sorting_enabled)
            table.setUpdatesEnabled(previous_updates_enabled)
        self._entry_table_signatures = current_signatures
        self._sync_start_button_state()

    def _checked_rows(self) -> List[int]:
        return [idx.row() for idx in self.entry_table.selectionModel().selectedRows()]

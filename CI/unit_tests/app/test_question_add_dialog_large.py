from __future__ import annotations

from typing import cast

import pytest
from PySide6.QtWidgets import QApplication

from software.app.config import DEFAULT_FILL_TEXT
from software.ui.pages.workbench.question_editor.add_dialog import QuestionAddDialog


@pytest.fixture(scope="module", autouse=True)
def _app():
    app = QApplication.instance() or QApplication([])
    yield app


class QuestionAddDialogLargeTests:
    def test_text_preview_ai_toggle_and_accept_builds_text_entry(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "software.ui.pages.workbench.question_editor.add_preview.ensure_ai_ready",
            lambda _parent: False,
        )
        dialog = QuestionAddDialog([])
        dialog.type_combo.setCurrentIndex(2)
        assert dialog._resolve_q_type() == "text"
        assert not dialog.answer_count_widget.isHidden()
        assert dialog.option_row_widget.isHidden()

        dialog.ai_toggle.setChecked(True)
        assert dialog._ai_enabled is False
        assert dialog.ai_toggle.isChecked() is False

        first_edit = dialog._text_edits[0]
        first_edit.setText("  第一条答案  ")
        dialog.text_add_btn.click()
        dialog._text_edits[-1].setText("第二条")
        dialog._sync_text_answers_from_edits()
        assert dialog._text_answers == ["第一条答案", "第二条"]
        assert dialog.answer_count_label.text() == "2"

        dialog._on_accept()
        entry = dialog.get_entry()
        assert entry is not None
        assert entry.question_type == "text"
        assert entry.texts == ["第一条答案", "第二条"]
        assert entry.option_count == 2
        assert entry.ai_enabled is False

    def test_multi_text_falls_back_to_default_fill_text(self) -> None:
        dialog = QuestionAddDialog([])
        dialog.type_combo.setCurrentIndex(2)
        dialog.text_add_btn.click()
        for edit in dialog._text_edits:
            edit.setText("")
        dialog.type_combo.setCurrentText("多项填空题")
        dialog.type_combo.setCurrentIndex(2)
        dialog._text_answers = []
        entry = dialog._build_entry()
        assert entry.texts == [DEFAULT_FILL_TEXT]

    def test_slider_and_random_strategy_hide_option_count(self) -> None:
        dialog = QuestionAddDialog([])
        dialog.type_combo.setCurrentText("滑块题")
        dialog.type_combo.setCurrentIndex(7)
        assert dialog._resolve_q_type() == "slider"
        assert not dialog.option_row_widget.isVisible()
        assert dialog.option_spin.value() == 1

        dialog._slider_values = [88.0]
        dialog.strategy_combo.setCurrentIndex(0)
        entry = dialog._build_entry()
        assert entry.question_type == "slider"
        assert entry.probabilities == -1
        assert entry.option_count == 1

    def test_custom_multiple_strategy_builds_custom_weights(self) -> None:
        dialog = QuestionAddDialog([])
        dialog.type_combo.setCurrentIndex(1)
        dialog.strategy_combo.setCurrentIndex(1)
        dialog.option_spin.setValue(3)
        dialog._slider_values = [5.0, 55.0, 105.0]
        entry = dialog._build_entry()
        assert entry.question_type == "multiple"
        assert entry.distribution_mode == "custom"
        assert entry.custom_weights == [5.0, 55.0, 100.0]
        assert entry.probabilities == [5.0, 55.0, 100.0]

    def test_custom_slider_target_keeps_100_cap(self) -> None:
        dialog = QuestionAddDialog([])
        dialog.type_combo.setCurrentIndex(7)
        dialog.strategy_combo.setCurrentIndex(1)
        dialog._slider_values = [188.0]
        entry = dialog._build_entry()
        assert entry.question_type == "slider"
        assert entry.custom_weights == [100.0]
        assert entry.probabilities == [100.0]

    def test_order_entry_ignores_strategy_weights(self) -> None:
        dialog = QuestionAddDialog([])
        dialog.type_combo.setCurrentIndex(8)
        dialog.option_spin.setValue(5)
        entry = dialog._build_entry()
        assert entry.question_type == "order"
        assert entry.probabilities == -1
        assert entry.option_count == 5

    def test_location_type_builds_location_text_entry(self) -> None:
        dialog = QuestionAddDialog([])
        dialog.type_combo.setCurrentText("地区题")
        assert dialog._resolve_q_type() == "location"
        assert dialog.option_row_widget.isHidden()
        assert dialog.answer_count_widget.isHidden()

        entry = dialog._build_entry()
        assert entry.question_type == "text"
        assert entry.is_location is True
        assert entry.location_parts == []
        assert entry.texts == [DEFAULT_FILL_TEXT]

    def test_matrix_preview_and_custom_matrix_entry(self) -> None:
        dialog = QuestionAddDialog([])
        dialog.type_combo.setCurrentIndex(4)
        dialog.option_spin.setValue(3)
        dialog.row_count_spin.setValue(2)
        dialog.matrix_strategy_combo.setCurrentIndex(1)
        assert dialog._resolve_q_type() == "matrix"
        assert not dialog.row_count_widget.isHidden()
        assert not dialog.matrix_strategy_widget.isHidden()
        assert dialog.option_label.text() == "列数："

        dialog._matrix_weights = [[1.0, 2.0], [3.0]]
        dialog._ensure_matrix_weights(2, 3)
        assert dialog._matrix_weights == [[1.0, 2.0, 1.0], [3.0, 1.0, 1.0]]

        entry = dialog._build_entry()
        assert entry.question_type == "matrix"
        assert entry.distribution_mode == "custom"
        assert cast(list[list[float]], entry.custom_weights)[0] == [1.0, 2.0, 1.0]

    def test_sync_base_visibility_restores_option_backup(self) -> None:
        dialog = QuestionAddDialog([])
        dialog.option_spin.setValue(6)
        dialog.type_combo.setCurrentIndex(7)
        assert dialog._option_backup == 6
        dialog.type_combo.setCurrentIndex(0)
        assert not dialog.option_row_widget.isHidden()
        assert dialog.option_spin.value() == 6

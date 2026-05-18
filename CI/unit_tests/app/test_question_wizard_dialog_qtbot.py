from __future__ import annotations

import time

from qfluentwidgets import BodyLabel, InfoBadge, PushButton
from PySide6.QtWidgets import QTreeWidgetItem

from software.app.config import DEFAULT_FILL_TEXT
from software.core.questions.config import QuestionEntry
from software.providers.contracts import (
    LOGIC_PARSE_STATUS_COMPLETE,
    LOGIC_PARSE_STATUS_UNKNOWN,
    SurveyQuestionMeta,
)
from software.ui.pages.workbench.question_editor.wizard_dialog import (
    QuestionWizardDialog,
)
from software.ui.pages.workbench.question_editor.question_media_preview import (
    QuestionMediaThumbnail,
)


def _build_entries() -> list[QuestionEntry]:
    return [
        QuestionEntry(
            question_type="single",
            probabilities=[1, 1],
            texts=None,
            rows=1,
            option_count=2,
            distribution_mode="custom",
            custom_weights=[50, 50],
            question_num=1,
        ),
        QuestionEntry(
            question_type="text",
            probabilities=[1],
            texts=["默认值"],
            rows=1,
            option_count=1,
            distribution_mode="random",
            custom_weights=None,
            question_num=2,
        ),
    ]


def test_question_wizard_dialog_shows_logic_view_and_switches_question(qtbot) -> None:
    info = [
        SurveyQuestionMeta(
            num=1,
            title="第一题",
            page=1,
            option_texts=["显示下一题", "结束"],
            has_dependent_display_logic=True,
            controls_display_targets=[
                {"condition_option_indices": [0], "target_question_num": 2}
            ],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
        SurveyQuestionMeta(
            num=2,
            title="第二题",
            page=1,
            has_display_condition=True,
            display_conditions=[
                {"condition_question_num": 1, "condition_option_indices": [0]}
            ],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
    ]
    dlg = QuestionWizardDialog(_build_entries(), info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: dlg._tree_widget.topLevelItemCount() > 0)
    assert dlg._content_splitter is not None
    assert dlg._content_splitter.count() == 2
    assert dlg._content_splitter.handleWidth() >= 6
    assert dlg._current_view_mode == "logic"

    page_item = dlg._tree_widget.topLevelItem(0)
    question_item = page_item.child(1)
    dlg._on_tree_item_clicked(question_item, 0)
    assert dlg._current_question_idx == 1

    relation_item = page_item.child(0).child(0)
    assert isinstance(relation_item, QTreeWidgetItem)
    dlg._on_tree_item_clicked(relation_item, 0)
    assert dlg._current_question_idx == 1


def test_question_wizard_dialog_tree_uses_compact_question_label_and_type_badge(qtbot) -> None:
    info = [
        SurveyQuestionMeta(
            num=1,
            title="图片选项题",
            page=1,
            option_texts=["A"],
            required=True,
            has_jump=True,
            jump_rules=[{"option_index": 0, "jumpto": 99}],
            question_media=[
                {
                    "kind": "image",
                    "scope": "option",
                    "index": 0,
                    "source_url": "https://example.com/a.png",
                    "label": "选项A",
                }
            ],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        )
    ]
    dlg = QuestionWizardDialog(_build_entries()[:1], info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: dlg._tree_widget.topLevelItemCount() > 0)
    page_item = dlg._tree_widget.topLevelItem(0)
    question_item = page_item.child(0)
    assert question_item.text(0) == ""

    row = dlg._tree_widget.itemWidget(question_item, 0)
    assert row is not None
    labels = [label.text() for label in row.findChildren(BodyLabel)]
    badges = [badge.text() for badge in row.findChildren(InfoBadge)]
    assert labels[0] == "1."
    assert badges == ["单选题"]
    assert question_item.child(0).text(0) == "选中“A” -> 结束"


def test_question_wizard_dialog_hides_logic_view_when_unknown(qtbot) -> None:
    info = [
        SurveyQuestionMeta(
            num=1,
            title="第一题",
            page=1,
            logic_parse_status=LOGIC_PARSE_STATUS_UNKNOWN,
        )
    ]
    entries = [
        QuestionEntry(
            question_type="text",
            probabilities=[1],
            texts=["a"],
            rows=1,
            option_count=1,
            distribution_mode="random",
            custom_weights=None,
            question_num=1,
        )
    ]
    dlg = QuestionWizardDialog(entries, info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: dlg._tree_widget.topLevelItemCount() > 0)
    assert dlg._current_view_mode == "sequential"


def test_question_wizard_dialog_detail_keeps_visible_content_width(qtbot) -> None:
    info = [
        SurveyQuestionMeta(
            num=1,
            title="第一题",
            page=1,
            option_texts=["A", "B"],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
        SurveyQuestionMeta(
            num=2,
            title="第二题",
            page=1,
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        ),
    ]
    dlg = QuestionWizardDialog(_build_entries(), info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: bool(dlg._entry_card_widgets))
    assert dlg._detail_stack is not None
    assert dlg._detail_scroll is not None
    assert dlg._detail_stack.currentWidget() is dlg._question_cards[0]

    dlg._sync_detail_content_width()
    card = dlg._entry_card_widgets[0]
    assert card.maximumWidth() <= dlg._detail_scroll.viewport().width()
    assert card.maximumWidth() >= 320

    dlg._select_question(1)
    qtbot.waitUntil(lambda: 1 in dlg._entry_card_widgets)
    assert dlg._detail_stack.currentWidget() is dlg._question_cards[1]


def test_question_wizard_dialog_multi_text_stays_inside_detail_width(qtbot) -> None:
    entries = [
        QuestionEntry(
            question_type="multi_text",
            probabilities=[1],
            texts=["无|||填空2|||填空3"],
            rows=1,
            option_count=1,
            distribution_mode="random",
            custom_weights=None,
            question_num=1,
        )
    ]
    info = [
        SurveyQuestionMeta(
            num=1,
            title="多项填空测试",
            page=1,
            text_inputs=3,
            is_multi_text=True,
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        )
    ]
    dlg = QuestionWizardDialog(entries, info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: bool(dlg._entry_card_widgets))
    assert dlg._detail_scroll is not None

    dlg._sync_detail_content_width()
    card = dlg._entry_card_widgets[0]
    qtbot.waitUntil(
        lambda: card.width() <= dlg._detail_scroll.viewport().width(),
        timeout=2000,
    )
    assert card.maximumWidth() <= dlg._detail_scroll.viewport().width()


def test_question_wizard_dialog_text_stays_inside_detail_width(qtbot) -> None:
    entries = [
        QuestionEntry(
            question_type="text",
            probabilities=[1],
            texts=["默认答案"],
            rows=1,
            option_count=1,
            distribution_mode="random",
            custom_weights=None,
            question_num=1,
        )
    ]
    info = [
        SurveyQuestionMeta(
            num=1,
            title="普通填空测试",
            page=1,
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        )
    ]
    dlg = QuestionWizardDialog(entries, info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: bool(dlg._entry_card_widgets))
    assert dlg._detail_scroll is not None

    dlg._sync_detail_content_width()
    card = dlg._entry_card_widgets[0]
    qtbot.waitUntil(
        lambda: card.width() <= dlg._detail_scroll.viewport().width(),
        timeout=2000,
    )
    assert card.maximumWidth() <= dlg._detail_scroll.viewport().width()


def test_question_wizard_dialog_accept_shows_validation_error_without_navigation_crash(qtbot) -> None:
    entries = [
        QuestionEntry(
            question_type="text",
            probabilities=[1],
            texts=["默认答案"],
            rows=1,
            option_count=1,
            distribution_mode="random",
            custom_weights=None,
            question_num=1,
        )
    ]
    info = [
        SurveyQuestionMeta(
            num=1,
            title="随机整数测试",
            page=1,
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        )
    ]
    dlg = QuestionWizardDialog(entries, info, "demo")
    qtbot.addWidget(dlg)
    dlg.text_random_mode_map[0] = "integer"
    dlg.show()

    dlg.accept()

    qtbot.waitUntil(lambda: dlg._validation_error_dialog is not None)
    assert dlg._validation_error_dialog is not None
    assert dlg._current_question_idx == 0


def test_question_media_thumbnail_can_be_deleted_before_worker_finishes(qtbot, monkeypatch) -> None:
    class _Resp:
        content = b""

        def raise_for_status(self) -> None:
            return None

    def _slow_get(*_args, **_kwargs):
        time.sleep(0.2)
        return _Resp()

    from software.ui.pages.workbench.question_editor import question_media_preview as preview_module

    monkeypatch.setattr(preview_module.http_client, "get", _slow_get)
    widget = QuestionMediaThumbnail(
        {"source_url": "https://example.com/a.png", "label": "题干图"}
    )
    qtbot.addWidget(widget)
    widget.show()

    widget.deleteLater()
    qtbot.wait(350)


def test_question_media_thumbnail_blocks_private_address_fetch(monkeypatch, qtbot) -> None:
    calls: list[str] = []

    def _fake_get(url, **kwargs):
        calls.append(url)
        raise AssertionError("private address should not be fetched")

    from software.ui.pages.workbench.question_editor import question_media_preview as preview_module

    monkeypatch.setattr(preview_module.http_client, "get", _fake_get)
    widget = QuestionMediaThumbnail({"source_url": "http://127.0.0.1/a.png", "label": "题干图"})
    qtbot.addWidget(widget)
    widget.show()
    qtbot.wait(100)

    assert calls == []


def test_question_wizard_dialog_multi_text_ignores_empty_answer_group(qtbot) -> None:
    entries = [
        QuestionEntry(
            question_type="multi_text",
            probabilities=[1],
            texts=["甲||乙"],
            rows=1,
            option_count=1,
            distribution_mode="random",
            custom_weights=None,
            question_num=1,
        )
    ]
    info = [
        SurveyQuestionMeta(
            num=1,
            title="多项填空测试",
            page=1,
            text_inputs=2,
            is_multi_text=True,
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        )
    ]
    dlg = QuestionWizardDialog(entries, info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: bool(dlg.text_edit_map))
    row_edits = dlg.text_edit_map[0][0]
    for edit in row_edits:
        edit.setText("")

    assert dlg.get_text_results()[0] == [DEFAULT_FILL_TEXT]


def test_question_wizard_dialog_shows_media_badge_for_option_image(qtbot) -> None:
    info = [
        SurveyQuestionMeta(
            num=1,
            title="图片选项题",
            page=1,
            option_texts=["A"],
            question_media=[
                {
                    "kind": "image",
                    "scope": "option",
                    "index": 0,
                    "source_url": "https://example.com/a.png",
                    "label": "选项A",
                }
            ],
            logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE,
        )
    ]
    dlg = QuestionWizardDialog(_build_entries()[:1], info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: bool(dlg._entry_card_widgets))
    card = dlg._entry_card_widgets[0]
    badges = [widget.text() for widget in card.findChildren(InfoBadge)]
    assert "图片题" in badges


def test_question_wizard_dialog_delete_answer_row_renumbers(qtbot) -> None:
    entry = QuestionEntry(
        question_type="text",
        probabilities=[1],
        texts=["甲", "乙"],
        rows=1,
        option_count=1,
        distribution_mode="random",
        custom_weights=None,
        question_num=1,
    )
    info = [SurveyQuestionMeta(num=1, title="普通填空测试", page=1, logic_parse_status=LOGIC_PARSE_STATUS_COMPLETE)]
    dlg = QuestionWizardDialog([entry], info, "demo")
    qtbot.addWidget(dlg)
    dlg.show()

    qtbot.waitUntil(lambda: bool(dlg.text_edit_map))
    container = dlg.text_container_map[0]
    buttons = [btn for btn in container.findChildren(PushButton) if btn.text() == "×"]
    assert len(buttons) == 2

    buttons[0].click()
    qtbot.wait(50)

    labels = [label.text() for label in container.findChildren(BodyLabel) if label.text().endswith(".")]
    assert labels[0] == "1."

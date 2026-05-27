from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from PySide6.QtWidgets import QTableWidget

import software.ui.pages.workbench.dashboard.parts.entries as entries_module
import software.ui.pages.workbench.dashboard.parts.run_actions as run_actions_module
from software.core.config.schema import RuntimeConfig
from software.core.questions.config import QuestionEntry
from software.providers.contracts import SurveyQuestionMeta
from software.ui.pages.workbench.dashboard.parts.entries import (
    DashboardEntriesMixin,
    _apply_result_updates,
    _build_entry_row_signature,
    _normalize_wizard_weights,
    question_dimension,
    question_summary,
)
from software.ui.pages.workbench.dashboard.parts.run_actions import DashboardRunActionsMixin


class _EntriesPage(DashboardEntriesMixin, DashboardRunActionsMixin):
    def __init__(self) -> None:
        self.entry_table = QTableWidget()
        self.entry_table.setColumnCount(4)
        self.count_label = SimpleNamespace(text="", setText=lambda value: setattr(self.count_label, "text", value))
        self.title_label = SimpleNamespace(text="", setText=lambda value: setattr(self.title_label, "text", value))
        self.url_edit = SimpleNamespace(text=lambda: "https://www.wjx.cn/vm/demo.aspx", setText=MagicMock())
        self.target_spin = SimpleNamespace(
            _value=1,
            value=lambda: self.target_spin._value,
            setValue=lambda value: setattr(self.target_spin, "_value", value),
            blockSignals=MagicMock(),
        )
        self.thread_spin = SimpleNamespace(
            _value=1,
            _range=(1, 1),
            value=lambda: self.thread_spin._value,
            setValue=lambda value: setattr(self.thread_spin, "_value", value),
            setRange=lambda minimum, maximum: setattr(self.thread_spin, "_range", (minimum, maximum)),
            blockSignals=MagicMock(),
        )
        self.random_ip_cb = SimpleNamespace(
            _checked=False,
            isChecked=lambda: self.random_ip_cb._checked,
            setChecked=lambda value: setattr(self.random_ip_cb, "_checked", bool(value)),
            blockSignals=MagicMock(),
        )
        self.runtime_page = SimpleNamespace(
            reliability_card=SimpleNamespace(switchButton=SimpleNamespace(isChecked=lambda: False)),
            update_config=MagicMock(),
            focus_answer_duration_setting=MagicMock(),
            set_proxy_source=MagicMock(return_value="default"),
            set_custom_proxy_api=MagicMock(),
        )
        self.strategy_page = SimpleNamespace(
            get_rules=MagicMock(return_value=[{"id": "r1"}]),
            get_dimension_groups=MagicMock(return_value=["体验"]),
        )
        self.controller = SimpleNamespace(survey_provider="wjx")
        self.workbench_state = SimpleNamespace(
            entries=[],
            questions_info=[],
            entry_questions_info=[],
            get_entries=lambda: self.workbench_state.entries,
            set_entries=lambda entries, info: (
                setattr(self.workbench_state, "entries", entries),
                setattr(self.workbench_state, "questions_info", info),
            ),
            open_add_question_dialog=MagicMock(return_value=True),
        )
        self._survey_title = ""
        self._entry_table_signatures = []
        self.toasts: list[tuple[str, str]] = []
        self.synced = 0
        self.cost_refreshed = 0
        self.toggle_states: list[bool] = []
        self._window = SimpleNamespace()

    def _toast(self, text: str, level: str = "info", **_kwargs) -> None:
        self.toasts.append((text, level))

    def _sync_start_button_state(self, running=None) -> None:
        _ = running
        self.synced += 1

    def _refresh_ip_cost_infobar(self) -> None:
        self.cost_refreshed += 1

    def _sync_random_ip_toggle_presentation(self, enabled: bool) -> None:
        self.toggle_states.append(enabled)

    def window(self):
        return self._window


def test_question_summary_covers_text_matrix_choice_and_dimension_branches() -> None:
    assert question_summary(QuestionEntry("text", None, is_location=True)) == "地区: 自动选择"
    assert (
        question_summary(
            QuestionEntry("text", None, is_location=True, location_parts=["北京", "北京", "东城区"])
        )
        == "地区: 北京-北京-东城区"
    )
    assert question_summary(QuestionEntry("text", None, text_random_mode="name")) == "答案: 随机姓名"
    assert question_summary(QuestionEntry("text", None, text_random_mode="mobile")) == "答案: 随机手机号"
    assert question_summary(QuestionEntry("text", None, text_random_mode="id_card")) == "答案: 随机身份证号"
    assert question_summary(QuestionEntry("text", None, text_random_mode="integer", text_random_int_range=[1, 9])) == "答案: 随机整数(1-9)"
    assert question_summary(QuestionEntry("text", None, texts=["__RANDOM_NAME__", "x", "y"], ai_enabled=True)) == "答案: 随机姓名 | x (+1) | AI"
    assert question_summary(QuestionEntry("text", None, texts=[], ai_enabled=True)) == "答案: 无 | AI"
    assert question_summary(
        QuestionEntry(
            "multi_text",
            None,
            multi_text_blank_modes=["name", "mobile", "integer"],
            multi_text_blank_int_ranges=[[], [], [3, 5]],
        )
    ) == "填空1: 随机姓名 | 填空2: 随机手机号 (+1)"
    assert question_summary(QuestionEntry("multi_text", None, multi_text_blank_ai_flags=[True])) == "填空1: AI"
    assert question_summary(QuestionEntry("matrix", [[1, 2]], rows=2, option_count=3, custom_weights=[[1, 2]])) == "2 行 × 3 列 - 按行配比"
    assert question_summary(QuestionEntry("matrix", None, rows=2, option_count=3)) == "2 行 × 3 列 - 完全随机"
    assert question_summary(QuestionEntry("order", None)) == "排序题 - 自动随机排序"
    assert question_summary(QuestionEntry("multiple", [1, 2], custom_weights=[10, 20, 30, 40, 50])) == "自定义概率: 10%,20%,30%,40%..."
    assert question_summary(QuestionEntry("single", [1, 2], custom_weights=[1, 2])) == "自定义配比: 1,2"
    assert question_summary(QuestionEntry("multiple", -1, distribution_mode="custom")) == "完全随机"
    assert question_summary(QuestionEntry("single", [1, 2], distribution_mode="custom")) == "自定义配比"

    psycho = QuestionEntry("scale", [1, 1], psycho_bias="left", dimension="体验")
    assert question_summary(psycho) == "倾向预设: 偏左"
    assert question_dimension(psycho) == "体验"
    assert _build_entry_row_signature(psycho, 2)[0] == "3"


def test_entry_result_appliers_and_table_refresh(monkeypatch, qtbot) -> None:
    page = _EntriesPage()
    qtbot.addWidget(page.entry_table)
    entries = [
        QuestionEntry("single", [1, 1], question_num=1, question_title="Q1"),
        QuestionEntry("text", None, question_num=2, question_title="Q2"),
    ]
    page.workbench_state.entries = entries

    assert _normalize_wizard_weights([[1, -2], [3]]) == [[1.0, 0.0], [3.0]]
    assert _normalize_wizard_weights([1, -2]) == [1.0, 0.0]
    assert _normalize_wizard_weights("raw") == "raw"

    _apply_result_updates(entries, {0: [5, 0], 10: [1]}, entries_module._apply_distribution_result)
    assert entries[0].distribution_mode == "custom"
    assert entries[0].custom_weights == [5.0, 0.0]

    _apply_result_updates(entries, {1: ["A"]}, entries_module._apply_text_result)
    entries_module._apply_option_fill_result(entries[0], ["x"])
    entries_module._apply_option_fill_result(entries[1], ["ignored"])
    entries_module._apply_text_random_mode_result(entries[1], "name")
    entries_module._apply_text_random_int_range_result(entries[1], [1, 2])
    entries_module._apply_ai_flag_result(entries[1], True)
    entries_module._apply_attached_select_result(entries[0], [{"a": 1}])
    entries_module._apply_multi_text_blank_modes_result(entries[1], ["name"])
    entries_module._apply_multi_text_blank_int_ranges_result(entries[1], [[1, 2]])
    entries_module._apply_multi_text_blank_ai_flags_result(entries[1], [False])
    entries_module._apply_dimension_result(entries[0], "体验")
    entries_module._apply_bias_preset_result(entries[0], "center")

    assert entries[0].option_fill_texts == ["x"]
    assert entries[1].text_random_mode == "name"
    assert entries[1].ai_enabled is True
    assert entries[0].dimension == "体验"

    page._refresh_entry_table()
    assert page.entry_table.rowCount() == 2
    assert page.count_label.text == "2 题"
    assert page.entry_table.item(0, 0).text() == "1"
    assert page.synced == 1

    signatures = list(page._entry_table_signatures)
    page._refresh_entry_table()
    assert page._entry_table_signatures == signatures


def test_entry_dialog_actions_and_wizard_paths(monkeypatch, qtbot) -> None:
    page = _EntriesPage()
    qtbot.addWidget(page.entry_table)
    page.workbench_state.entries = [QuestionEntry("single", [1, 1]), QuestionEntry("text", None)]
    page.workbench_state.entry_questions_info = [SurveyQuestionMeta(num=1, title="Q1"), SurveyQuestionMeta(num=2, title="Q2")]

    page._show_add_question_dialog()
    assert page.entry_table.rowCount() == 2

    monkeypatch.setattr(page, "_checked_rows", lambda: [])
    page._edit_selected_entries()
    assert page.toasts[-1] == ("请先勾选要编辑的题目", "warning")

    monkeypatch.setattr(page, "_checked_rows", lambda: [5])
    page._edit_selected_entries()
    assert page.toasts[-1] == ("未找到可编辑的题目", "warning")

    monkeypatch.setattr(page, "_checked_rows", lambda: [0, 0, 1])
    monkeypatch.setattr(page, "run_question_wizard", lambda selected, info: len(selected) == 2 and len(info) == 2)
    page._edit_selected_entries()
    assert page.entry_table.rowCount() == 2

    class _Box:
        def __init__(self, *_args, **_kwargs) -> None:
            self.yesButton = SimpleNamespace(setText=lambda _text: None)
            self.cancelButton = SimpleNamespace(setText=lambda _text: None)

        def exec(self) -> bool:
            return True

    monkeypatch.setattr(entries_module, "MessageBox", _Box)
    monkeypatch.setattr(page, "_checked_rows", lambda: [0])
    page._delete_selected_entries()
    assert len(page.workbench_state.entries) == 1

    page._clear_all_entries()
    assert page.workbench_state.entries == []
    page._clear_all_entries()
    assert page.toasts[-1] == ("当前没有可清空的题目", "warning")


def test_run_question_wizard_and_run_actions(monkeypatch, qtbot) -> None:
    page = _EntriesPage()
    qtbot.addWidget(page.entry_table)

    assert page.run_question_wizard([], []) is False
    assert page.toasts[-1] == ("请先解析问卷或手动添加题目", "warning")

    class _AcceptedDialog:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

        @staticmethod
        def get_results(_dlg):
            return {0: [3, 7]}

        @staticmethod
        def get_text_results(_dlg):
            return {}

        @staticmethod
        def get_option_fill_results(_dlg):
            return {}

        @staticmethod
        def get_text_random_modes(_dlg):
            return {}

        @staticmethod
        def get_text_random_int_ranges(_dlg):
            return {}

        @staticmethod
        def get_ai_flags(_dlg):
            return {}

        @staticmethod
        def get_attached_select_results(_dlg):
            return {}

        @staticmethod
        def get_multi_text_blank_modes(_dlg):
            return {}

        @staticmethod
        def get_multi_text_blank_int_ranges(_dlg):
            return {}

        @staticmethod
        def get_multi_text_blank_ai_flags(_dlg):
            return {}

        @staticmethod
        def get_dimensions(_dlg):
            return {}

        @staticmethod
        def get_bias_presets(_dlg):
            return {}

        def deleteLater(self):
            return None

    monkeypatch.setattr(entries_module, "QuestionWizardDialog", _AcceptedDialog)
    monkeypatch.setattr(entries_module, "isValid", lambda _dlg: True)
    monkeypatch.setattr(
        entries_module,
        "_WIZARD_DISTRIBUTION_RULES",
        ((lambda _dlg: {0: [3, 7]}, entries_module._apply_distribution_result),),
    )
    monkeypatch.setattr(entries_module, "_WIZARD_TEXT_RULES", ())
    monkeypatch.setattr(entries_module, "_WIZARD_META_RULES", ())
    selected_entries = [QuestionEntry("single", [1, 1])]
    assert page.run_question_wizard(selected_entries, [SurveyQuestionMeta(num=1, title="Q1")]) is True
    assert selected_entries[0].custom_weights == [3.0, 7.0]

    class _BadDialog(_AcceptedDialog):
        pass

    monkeypatch.setattr(entries_module, "QuestionWizardDialog", _BadDialog)
    monkeypatch.setattr(
        entries_module,
        "_WIZARD_DISTRIBUTION_RULES",
        ((lambda _dlg: (_ for _ in ()).throw(ValueError("bad weights")), entries_module._apply_distribution_result),),
    )
    assert page.run_question_wizard([QuestionEntry("single", [1, 1])], [{}]) is False
    assert page.toasts[-1] == ("配置应用失败：bad weights", "error")

    page.run_coordinator = SimpleNamespace(start=MagicMock(), build_config=MagicMock(return_value=RuntimeConfig(target=8)))
    page._on_start_clicked(enable_reverse_fill=True)
    page.run_coordinator.start.assert_called_once_with(
        enable_reverse_fill=True,
    )
    assert page._build_config().target == 8

    delattr(page, "run_coordinator")
    monkeypatch.setattr(run_actions_module, "log_action", lambda *_args, **_kwargs: None)
    page._on_start_clicked()
    assert page.toasts[-1] == ("运行编排器未初始化，无法开始执行", "error")

    page.update_question_meta("标题", 3)
    assert page.title_label.text == "标题"
    assert page.cost_refreshed >= 1

    page._apply_runtime_ui_state({"target": 5, "threads": 9, "random_ip_enabled": True})
    assert page.target_spin._value == 5
    assert page.thread_spin._value == 9
    assert page.random_ip_cb._checked is True

    cfg = RuntimeConfig(url="https://wjx.cn/vm/demo.aspx", target=4, threads=2, random_ip_enabled=True)
    page.apply_config(cfg)
    assert page.url_edit.setText.call_args.args[0] == cfg.url
    assert page.toggle_states[-1] is True

    built = page.build_base_config()
    assert built.target == 4
    assert built.threads == 2
    assert built.answer_rules == [{"id": "r1"}]
    assert built.dimension_groups == ["体验"]

    page._window = SimpleNamespace(runtime_page="runtime", switched=None, switchTo=lambda target: setattr(page._window, "switched", target))
    page._go_to_runtime_answer_duration()
    assert page._window.switched == "runtime"
    page.runtime_page.focus_answer_duration_setting.assert_called_once()


def test_build_base_config_keeps_qq_provider_when_runtime_state_is_stale(qtbot) -> None:
    page = _EntriesPage()
    qtbot.addWidget(page.entry_table)
    page.url_edit = SimpleNamespace(text=lambda: "https://wj.qq.com/s2/26778849/5e9e/")
    page.controller.survey_provider = "qq"
    page.controller.write_runtime_ui_state_to_config = MagicMock(
        side_effect=lambda cfg: setattr(cfg, "survey_provider", "wjx")
    )

    built = page.build_base_config()

    assert built.survey_provider == "qq"

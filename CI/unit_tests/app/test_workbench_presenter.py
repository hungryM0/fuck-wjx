from __future__ import annotations

from typing import Any, cast

from software.core.questions.config import QuestionEntry
from software.core.config.schema import RuntimeConfig
from software.providers.contracts import SurveyQuestionMeta
from software.ui.pages.workbench.presenter import WorkbenchPresenter
from software.ui.pages.workbench.session import WorkbenchState


class _FakeController:
    def __init__(self) -> None:
        self.config = RuntimeConfig(
            url="https://www.wjx.cn/vm/demo.aspx",
            survey_provider="wjx",
        )
        self.survey_provider = "wjx"
        self.question_entries: list[QuestionEntry] = []
        self.synced_configs: list[RuntimeConfig] = []
        self.counter_refreshes = 0

    def sync_runtime_ui_state_from_config(self, cfg: RuntimeConfig) -> None:
        self.synced_configs.append(cfg)

    def refresh_random_ip_counter(self) -> None:
        self.counter_refreshes += 1


class _FakeRuntimePage:
    def __init__(self) -> None:
        self.applied: list[RuntimeConfig] = []

    def apply_config(self, cfg: RuntimeConfig) -> None:
        self.applied.append(cfg)


class _FakeDashboard:
    def __init__(self) -> None:
        self.url_edit = _FakeLineEdit()
        self.applied: list[RuntimeConfig] = []
        self.meta: tuple[str, int] | None = None
        self._survey_title = ""
        self._open_wizard_after_parse = False
        self.wizard_calls: list[tuple[list[QuestionEntry], list, str | None]] = []
        self.wizard_result = True
        self.toasts: list[tuple[str, str]] = []
        self.parse_success_calls: list[tuple[list, str]] = []
        self.parse_failed_calls: list[str] = []

    def apply_config(self, cfg: RuntimeConfig) -> None:
        self.applied.append(cfg)

    def update_question_meta(self, title: str, count: int) -> None:
        self.meta = (title, count)
        self._survey_title = title

    def build_base_config(self) -> RuntimeConfig:
        return RuntimeConfig(url=self.url_edit.text(), target=3, threads=2)

    def run_question_wizard(
        self,
        entries: list[QuestionEntry],
        info: list,
        survey_title: str | None = None,
    ) -> bool:
        self.wizard_calls.append((entries, info, survey_title))
        return self.wizard_result

    def _toast(self, text: str, level: str = "info", *_args, **_kwargs) -> None:
        self.toasts.append((text, level))

    def _on_survey_parsed(self, info: list, title: str) -> None:
        self.parse_success_calls.append((list(info or []), title))

    def _on_survey_parse_failed(self, error_msg: str) -> None:
        self.parse_failed_calls.append(str(error_msg or ""))


class _FakeReverseFillPage:
    def __init__(self) -> None:
        self.url_edit = _FakeLineEdit()
        self.applied: list[RuntimeConfig] = []
        self.contexts: list[dict] = []
        self.preview_refreshes = 0

    def apply_config(self, cfg: RuntimeConfig) -> None:
        self.applied.append(cfg)

    def update_config(self, cfg: RuntimeConfig) -> None:
        cfg.reverse_fill_source_path = "D:/source.xlsx"

    def set_question_context(
        self,
        questions_info,
        question_entries,
        *,
        survey_title: str,
        survey_provider: str,
    ) -> None:
        self.contexts.append(
            {
                "questions_info": list(questions_info or []),
                "question_entries": list(question_entries or []),
                "survey_title": survey_title,
                "survey_provider": survey_provider,
            }
        )

    def _refresh_preview(self) -> None:
        self.preview_refreshes += 1


class _FakeStrategyPage:
    def __init__(self) -> None:
        self.questions_info: list = []
        self.entries_calls: list[tuple[list, list]] = []
        self.rules: list = []
        self.dimension_groups: list = ["old"]

    def set_questions_info(self, info) -> None:
        self.questions_info = list(info or [])

    def set_entries(self, entries, info) -> None:
        self.entries_calls.append((list(entries or []), list(info or [])))

    def set_rules(self, rules) -> None:
        self.rules = list(rules or [])

    def set_dimension_groups(self, groups) -> None:
        self.dimension_groups = list(groups or [])


class _FakeHost:
    def __init__(self) -> None:
        self.toasts: list[tuple[str, str]] = []

    def _toast(self, text: str, level: str = "info", *_args, **_kwargs) -> None:
        self.toasts.append((text, level))


class _FakeLineEdit:
    def __init__(self, text: str = "") -> None:
        self._text = text
        self.blocked: list[bool] = []

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = str(text or "")

    def blockSignals(self, blocked: bool) -> None:
        self.blocked.append(bool(blocked))


def _presenter_with_fakes() -> WorkbenchPresenter:
    presenter = object.__new__(WorkbenchPresenter)
    dynamic = cast(Any, presenter)
    dynamic.controller = _FakeController()
    dynamic.host = _FakeHost()
    presenter.state = WorkbenchState()
    dynamic.runtime_page = _FakeRuntimePage()
    dynamic.dashboard = _FakeDashboard()
    dynamic.reverse_fill_page = _FakeReverseFillPage()
    dynamic.strategy_page = _FakeStrategyPage()
    return presenter


def _question_entry(num: int = 1) -> QuestionEntry:
    return QuestionEntry(
        question_type="single",
        probabilities=[1.0],
        question_num=num,
        question_title=f"Q{num}",
    )


def _question_meta(num: int = 1) -> SurveyQuestionMeta:
    return SurveyQuestionMeta(num=num, title=f"Q{num}", type_code="3", options=1)


def test_workbench_presenter_applies_config_to_workbench_pages() -> None:
    presenter = _presenter_with_fakes()
    runtime_page = cast(_FakeRuntimePage, presenter.runtime_page)
    dashboard = cast(_FakeDashboard, presenter.dashboard)
    reverse_fill_page = cast(_FakeReverseFillPage, presenter.reverse_fill_page)
    strategy_page = cast(_FakeStrategyPage, presenter.strategy_page)
    entry = _question_entry()
    meta = _question_meta()
    cfg = RuntimeConfig(
        url="https://www.wjx.cn/vm/demo.aspx",
        target=5,
        threads=2,
        survey_title="Demo",
        question_entries=[entry],
        questions_info=[meta],
        answer_rules=[{"kind": "demo"}],
        dimension_groups=["A"],
    )

    presenter.apply_config(cfg)

    assert runtime_page.applied == [cfg]
    assert dashboard.applied == [cfg]
    assert reverse_fill_page.applied == [cfg]
    assert presenter.state.get_entries() == [entry]
    assert strategy_page.questions_info == [meta]
    assert strategy_page.entries_calls[-1][0] == [entry]
    assert strategy_page.rules == [{"kind": "demo"}]
    assert strategy_page.dimension_groups == ["A"]
    assert dashboard.meta == ("Demo", 1)
    assert reverse_fill_page.contexts[-1]["survey_title"] == "Demo"
    assert reverse_fill_page.contexts[-1]["survey_provider"] == "wjx"


def test_workbench_presenter_survey_parsed_updates_state_and_context() -> None:
    presenter = _presenter_with_fakes()
    dashboard = cast(_FakeDashboard, presenter.dashboard)
    reverse_fill_page = cast(_FakeReverseFillPage, presenter.reverse_fill_page)
    strategy_page = cast(_FakeStrategyPage, presenter.strategy_page)
    entry = _question_entry()
    meta = _question_meta()
    cast(_FakeController, presenter.controller).question_entries = [entry]

    presenter.on_survey_parsed([meta], "Parsed")

    assert presenter.state.get_entries() == [entry]
    assert [(item.num, item.title) for item in dashboard.parse_success_calls[-1][0]] == [(1, "Q1")]
    assert dashboard.parse_success_calls[-1][1] == "Parsed"
    assert [(item.num, item.title) for item in strategy_page.questions_info] == [(1, "Q1")]
    assert strategy_page.dimension_groups == []
    assert dashboard.meta == ("Parsed", 1)
    assert reverse_fill_page.contexts[-1]["question_entries"] == [entry]


def test_workbench_presenter_syncs_urls_without_looping() -> None:
    presenter = _presenter_with_fakes()
    dashboard = cast(_FakeDashboard, presenter.dashboard)
    reverse_fill_page = cast(_FakeReverseFillPage, presenter.reverse_fill_page)
    dashboard.url_edit.setText("https://old.example")
    reverse_fill_page.url_edit.setText("https://reverse.old")

    presenter.sync_dashboard_url_from_reverse_fill(" https://reverse.example ")
    presenter.sync_reverse_fill_url_from_dashboard(" https://dashboard.example ")

    assert dashboard.url_edit.text() == "https://reverse.example"
    assert dashboard.url_edit.blocked == [True, False]
    assert reverse_fill_page.preview_refreshes == 1
    assert reverse_fill_page.url_edit.text() == "https://dashboard.example"
    assert reverse_fill_page.url_edit.blocked == [True, False]

    presenter.sync_dashboard_url_from_reverse_fill("https://reverse.example")
    presenter.sync_reverse_fill_url_from_dashboard("https://dashboard.example")

    assert dashboard.url_edit.blocked == [True, False]
    assert reverse_fill_page.url_edit.blocked == [True, False]


def test_workbench_presenter_builds_config_snapshot_from_single_builder_path() -> None:
    presenter = _presenter_with_fakes()
    dashboard = cast(_FakeDashboard, presenter.dashboard)
    controller = cast(_FakeController, presenter.controller)
    entry = _question_entry()
    meta = _question_meta()
    presenter.state.set_entries([entry], [meta])
    dashboard.url_edit.setText("https://www.wjx.cn/vm/demo.aspx")

    cfg = presenter.build_current_config_snapshot()

    assert cfg.url == "https://www.wjx.cn/vm/demo.aspx"
    assert cfg.target == 3
    assert cfg.threads == 2
    assert cfg.question_entries == [entry]
    assert [(item.num, item.title) for item in cfg.questions_info] == [(1, "Q1")]
    assert cfg.reverse_fill_source_path == "D:/source.xlsx"
    assert controller.config is cfg

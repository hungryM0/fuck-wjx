from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import software.ui.pages.workbench.dashboard.parts.config_io as config_io_module
import software.ui.pages.workbench.dashboard.parts.survey_parse as survey_parse_module
from software.core.config.schema import RuntimeConfig
from software.core.questions.config import QuestionEntry
from software.providers.contracts import SurveyQuestionMeta
from software.ui.pages.workbench.dashboard.parts.config_io import DashboardConfigIOMixin
from software.ui.pages.workbench.dashboard.parts.survey_parse import (
    _QQ_LOGIN_REQUIRED_MESSAGE,
    DashboardSurveyParseMixin,
)


class _FakeProgress:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.closed = 0

    def close(self) -> None:
        self.closed += 1
        if self.fail:
            raise RuntimeError("close failed")


class _FakeWindow:
    def __init__(self, workbench=None) -> None:
        self.workbench = workbench


class _DashboardDouble(DashboardSurveyParseMixin, DashboardConfigIOMixin):
    def __init__(self) -> None:
        self.url_edit = SimpleNamespace(text=lambda: "")
        self.controller = SimpleNamespace(
            parse_calls=[],
            parse_survey=lambda url: self.controller.parse_calls.append(url),
            load_saved_config=MagicMock(),
            save_current_config=MagicMock(),
            refresh_random_ip_counter=MagicMock(),
        )
        self.runtime_page = SimpleNamespace(apply_config=MagicMock())
        self.strategy_page = SimpleNamespace(
            set_questions_info=MagicMock(),
            set_entries=MagicMock(),
        )
        self.workbench_state = SimpleNamespace(
            entries=[],
            entry_questions_info=[],
            questions_info=[],
            set_entries=MagicMock(
                side_effect=lambda entries, info: (
                    setattr(self.workbench_state, "entries", entries),
                    setattr(self.workbench_state, "entry_questions_info", info),
                )
            ),
            get_entries=MagicMock(return_value=[]),
        )
        self.config_drawer = SimpleNamespace(open_drawer=MagicMock())
        self._survey_title = "问卷"
        self._progress_infobar = None
        self._open_wizard_after_parse = False
        self.toasts: list[tuple[str, str, int, bool]] = []
        self.applied_configs: list[RuntimeConfig] = []
        self.refreshed = 0
        self.meta_updates: list[tuple[str, int]] = []
        self.synced = 0
        self._window = _FakeWindow()

    def _toast(
        self,
        text: str,
        level: str = "info",
        duration: int = 2000,
        show_progress: bool = False,
    ):
        self.toasts.append((text, level, duration, show_progress))
        if show_progress:
            self._progress_infobar = _FakeProgress()
        return self._progress_infobar

    def apply_config(self, cfg: RuntimeConfig) -> None:
        self.applied_configs.append(cfg)

    def _build_config(self) -> RuntimeConfig:
        return RuntimeConfig(target=2, threads=1)

    def _refresh_entry_table(self) -> None:
        self.refreshed += 1

    def update_question_meta(self, title: str, count: int) -> None:
        self.meta_updates.append((title, count))

    def _sync_start_button_state(self, running: bool | None = None) -> None:
        _ = running
        self.synced += 1

    def window(self):
        return self._window


def test_dashboard_parse_blocks_empty_unsupported_and_invalid_urls(monkeypatch) -> None:
    page = _DashboardDouble()
    monkeypatch.setattr(survey_parse_module, "log_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(survey_parse_module, "is_supported_survey_url", lambda url: url.startswith("supported"))
    monkeypatch.setattr(survey_parse_module, "detect_survey_provider", lambda _url: "wjx")
    monkeypatch.setattr(survey_parse_module, "is_wjx_survey_url", lambda url: url.endswith("/survey"))

    page.url_edit = SimpleNamespace(text=lambda: "")
    page._on_parse_clicked()
    assert page.toasts[-1][0] == "请粘贴问卷链接"

    page.url_edit = SimpleNamespace(text=lambda: "bad")
    page._on_parse_clicked()
    assert page.toasts[-1][0] == "仅支持问卷星、腾讯问卷与 Credamo 见数链接"

    page.url_edit = SimpleNamespace(text=lambda: "supported/not-survey")
    page._on_parse_clicked()
    assert page.toasts[-1][0] == "链接不是可解析的公开问卷"

    page.url_edit = SimpleNamespace(text=lambda: "supported/survey")
    page._on_parse_clicked()
    assert page._open_wizard_after_parse is True
    assert page.controller.parse_calls == ["supported/survey"]
    assert page.toasts[-1] == ("正在解析问卷...", "info", -1, True)


def test_dashboard_parse_result_closes_progress_and_maps_errors(monkeypatch) -> None:
    page = _DashboardDouble()
    monkeypatch.setattr(survey_parse_module, "log_action", lambda *_args, **_kwargs: None)

    page._progress_infobar = _FakeProgress()
    page._on_survey_parsed(
        [SurveyQuestionMeta(num=1, title="Q1", type_code="3", option_texts=["A"])],
        "标题",
    )
    assert page._progress_infobar is None

    page._progress_infobar = _FakeProgress(fail=True)
    page._on_survey_parsed(
        [SurveyQuestionMeta(num=2, title="坏题", type_code="99", unsupported=True)],
        "标题",
    )
    assert page._progress_infobar is None

    for raw_error, expected in [
        (_QQ_LOGIN_REQUIRED_MESSAGE, _QQ_LOGIN_REQUIRED_MESSAGE),
        ("问卷已暂停", "问卷已暂停，需要前往问卷星后台重新发布"),
        ("问卷已停止", "问卷已停止，无法作答"),
        ("企业标准版", "问卷发布者企业标准版未购买或已到期，暂时不能填写"),
        ("暂未开放", "暂未开放"),
        ("", "解析失败：请确认链接有效且网络正常"),
        ("其他错误", "解析失败：其他错误"),
    ]:
        page._progress_infobar = _FakeProgress()
        page._open_wizard_after_parse = True
        page._on_survey_parse_failed(raw_error)
        assert page.toasts[-1][0] == expected
        assert page._open_wizard_after_parse is False


def test_dashboard_config_drawer_load_cancel_missing_and_workbench_paths(monkeypatch, tmp_path) -> None:
    page = _DashboardDouble()
    monkeypatch.setattr(config_io_module, "log_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(config_io_module, "get_user_config_directory", lambda: str(tmp_path))

    page._on_show_config_list()
    page.config_drawer.open_drawer.assert_called_once()

    monkeypatch.setattr(config_io_module.QFileDialog, "getOpenFileName", lambda *_args, **_kwargs: ("", ""))
    page._on_load_config()
    assert not page.controller.load_saved_config.called

    page._load_config_from_path("")
    assert not page.controller.load_saved_config.called

    page._load_config_from_path(str(tmp_path / "missing.json"))
    assert page.toasts[-1][0] == "文件不存在，可能已被删除"

    config_path = tmp_path / "cfg.json"
    config_path.write_text("{}", encoding="utf-8")
    workbench = SimpleNamespace(load_config_from_path=MagicMock())
    page._window = _FakeWindow(workbench)
    page._load_config_from_path(str(config_path))
    workbench.load_config_from_path.assert_called_once_with(str(config_path))
    assert page.toasts[-1][0] == "已载入配置"

    workbench.load_config_from_path.side_effect = RuntimeError("bad")
    page._load_config_from_path(str(config_path))
    assert page.toasts[-1][0] == "载入失败：bad"


def test_dashboard_config_load_and_save_without_workbench(monkeypatch, tmp_path) -> None:
    page = _DashboardDouble()
    page._window = _FakeWindow()
    monkeypatch.setattr(config_io_module, "log_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(config_io_module, "get_user_config_directory", lambda: str(tmp_path))

    cfg = RuntimeConfig(
        target=4,
        threads=2,
        survey_title="载入标题",
        question_entries=[QuestionEntry("single", [1, 1], question_num=1)],
        questions_info=[SurveyQuestionMeta(num=1, title="Q1", type_code="3", option_texts=["A"])],
    )
    config_path = tmp_path / "ok.json"
    config_path.write_text("{}", encoding="utf-8")
    page.controller.load_saved_config.return_value = cfg

    page._load_config_from_path(str(config_path))

    page.controller.load_saved_config.assert_called_once_with(str(config_path), strict=True)
    page.runtime_page.apply_config.assert_called_once_with(cfg)
    assert page.applied_configs == [cfg]
    assert page.workbench_state.entries == cfg.question_entries
    assert page.strategy_page.set_questions_info.call_args.args[0] == cfg.questions_info
    assert page.refreshed == 1
    assert page.meta_updates == [("载入标题", 1)]
    assert page.synced == 1
    page.controller.refresh_random_ip_counter.assert_called_once()

    page.controller.load_saved_config.side_effect = ValueError("broken")
    page._load_config_from_path(str(config_path))
    assert page.toasts[-1][0] == "载入失败：broken"

    monkeypatch.setattr(config_io_module.QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: ("", ""))
    page._on_save_config()
    assert not page.controller.save_current_config.called

    save_path = tmp_path / "saved.json"
    monkeypatch.setattr(config_io_module.QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(save_path), ""))
    page._on_save_config()
    page.controller.save_current_config.assert_called_once_with(str(save_path))
    assert page.toasts[-1][0] == "配置已保存"

    page.controller.save_current_config.side_effect = RuntimeError("no disk")
    page._on_save_config()
    assert page.toasts[-1][0] == "保存失败：no disk"


def test_dashboard_save_uses_workbench_snapshot_when_available(monkeypatch, tmp_path) -> None:
    page = _DashboardDouble()
    monkeypatch.setattr(config_io_module, "log_action", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(config_io_module, "get_user_config_directory", lambda: str(tmp_path))
    monkeypatch.setattr(
        config_io_module.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(tmp_path / "saved.json"), ""),
    )
    snapshot = RuntimeConfig(target=9, threads=1)
    page._window = _FakeWindow(SimpleNamespace(build_current_config_snapshot=MagicMock(return_value=snapshot)))

    page._on_save_config()

    assert not hasattr(page.controller, "config")
    page.controller.save_current_config.assert_called_once()

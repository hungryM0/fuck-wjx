from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from software.ui.pages.workbench.reverse_fill import actions


class _Edit:
    def __init__(self, text: str = "") -> None:
        self._text = text

    def text(self) -> str:
        return self._text

    def setText(self, value: str) -> None:
        self._text = value


class _Signal:
    def __init__(self) -> None:
        self.values: list[str] = []

    def emit(self, value: str) -> None:
        self.values.append(value)


class _ProgressBar:
    def __init__(self) -> None:
        self.values: list[int] = []

    def setValue(self, value: int) -> None:
        self.values.append(value)


class _Label:
    def __init__(self) -> None:
        self.values: list[str] = []

    def setText(self, value: str) -> None:
        self.values.append(value)


def _make_page() -> SimpleNamespace:
    return SimpleNamespace(
        _last_spec=None,
        _last_error="",
        _parsed_url="https://www.wjx.cn/vm/test.aspx",
        _survey_provider="",
        _survey_title="",
        _parse_requested_from_reverse_fill=False,
        _reverse_fill_threads_value=1,
        _issue_question_nums=[],
        _open_wizard_handler=None,
        _toast=MagicMock(),
        _refresh_preview=MagicMock(),
        surveyUrlChanged=_Signal(),
        url_edit=_Edit("https://www.wjx.cn/vm/test.aspx"),
        file_edit=_Edit(""),
        progress_bar=_ProgressBar(),
        progress_pct=_Label(),
        controller=SimpleNamespace(parse_survey=MagicMock(), survey_provider="wjx"),
    )


class ReverseFillActionsTests:
    def test_prepare_start_target_and_start_clicked_cover_reset_flow(self) -> None:
        coordinator = SimpleNamespace(
            set_reverse_fill_target=MagicMock(),
            is_completed_run=MagicMock(return_value=True),
            start_reverse_fill=MagicMock(return_value=True),
        )
        page = _make_page()
        page._last_spec = SimpleNamespace(target_num=3)
        page._run_coordinator = coordinator

        with patch.object(actions, "set_last_progress") as set_progress, patch.object(actions, "set_completion_notified") as set_notified:
            assert actions.prepare_reverse_fill_start_target(page) is True
            actions.on_start_clicked(page)

        coordinator.set_reverse_fill_target.assert_called_with(3)
        assert page.progress_bar.values == [0]
        assert page.progress_pct.values == ["0%"]
        set_progress.assert_called_once_with(page, 0)
        set_notified.assert_called_once_with(page, False)

        bad_page = _make_page()
        bad_page._last_spec = SimpleNamespace(target_num=0)
        assert actions.prepare_reverse_fill_start_target(bad_page) is False
        bad_page._toast.assert_called()

    def test_validate_parse_and_file_path_actions_cover_main_branches(self, tmp_path) -> None:
        page = _make_page()
        xlsx_path = tmp_path / "data.xlsx"
        xlsx_path.write_text("ok", encoding="utf-8")

        with patch.object(actions, "is_supported_survey_url", return_value=True), patch.object(
            actions,
            "is_wjx_survey_url",
            return_value=True,
        ):
            assert actions.validate_reverse_fill_start_url(page) is True

        page.url_edit.setText("https://bad")
        with patch.object(actions, "is_supported_survey_url", return_value=False):
            assert actions.validate_reverse_fill_start_url(page) is False

        actions.apply_excel_source_path(page, str(xlsx_path))
        assert page.file_edit.text() == str(xlsx_path)
        page._refresh_preview.assert_called()

        page._refresh_preview.reset_mock()
        actions.apply_excel_source_path(page, str(tmp_path / "bad.txt"))
        page._toast.assert_called()

        page.url_edit.setText("https://wjx.cn/test")
        with patch.object(actions, "is_supported_survey_url", return_value=True), patch.object(
            actions,
            "detect_survey_provider",
            return_value="wjx",
        ), patch.object(actions, "is_wjx_survey_url", return_value=True), patch.object(actions, "log_action") as log_action:
            actions.on_parse_clicked(page)
        assert page._parse_requested_from_reverse_fill is True
        assert page.surveyUrlChanged.values == ["https://wjx.cn/test"]
        page.controller.parse_survey.assert_called_once_with("https://wjx.cn/test")
        log_action.assert_called_once()

    def test_parse_result_failure_and_open_wizard_cover_feedback_paths(self) -> None:
        page = _make_page()
        page._parse_requested_from_reverse_fill = True
        page.url_edit.setText("https://wjx.cn/test")
        page.controller.survey_provider = "wjx"
        page._issue_question_nums = [0, "3", 5]

        actions.on_survey_parsed(
            page,
            [{"num": 1, "title": "Q1", "unsupported": True}, {"num": 2, "title": "Q2"}],
            "标题",
        )
        assert page._survey_title == "标题"
        assert page._parsed_url == "https://wjx.cn/test"
        page._toast.assert_called()

        page._parse_requested_from_reverse_fill = True
        actions.on_survey_parse_failed(page, "问卷已暂停")
        assert page._parse_requested_from_reverse_fill is False

        page._open_wizard_handler = MagicMock()
        actions.open_wizard(page)
        page._open_wizard_handler.assert_called_once_with([3, 5])

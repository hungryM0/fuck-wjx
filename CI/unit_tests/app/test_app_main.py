from __future__ import annotations

from pathlib import Path

from software.app import main as app_main


def test_should_run_update_test_probe_reads_flag_and_arg(monkeypatch, tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    monkeypatch.setenv("SURVEYCONTROLLER_UPDATE_TEST_MODE", "1")
    monkeypatch.setenv("SURVEYCONTROLLER_UPDATE_TEST_RESULT", str(result_path))
    monkeypatch.setattr(app_main.sys, "argv", ["SurveyController.exe", "--ci-update-probe"])

    assert app_main._should_run_update_test_probe() is True


def test_should_run_update_test_probe_requires_result_path(monkeypatch) -> None:
    monkeypatch.delenv("SURVEYCONTROLLER_UPDATE_TEST_MODE", raising=False)
    monkeypatch.delenv("SURVEYCONTROLLER_UPDATE_TEST_RESULT", raising=False)
    monkeypatch.setattr(app_main.sys, "argv", ["SurveyController.exe", "--ci-update-probe"])

    assert app_main._should_run_update_test_probe() is False

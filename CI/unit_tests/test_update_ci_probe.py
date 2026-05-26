from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from software.update import ci_probe


def _patch_probe_imports(version_text: str, update_manager) -> tuple[object, dict[str, object]]:
    original_import = __import__
    fake_imports = {
        "software.app.version": SimpleNamespace(__VERSION__=version_text),
        "software.update.updater": SimpleNamespace(UpdateManager=update_manager),
    }

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in fake_imports:
            return fake_imports[name]
        return original_import(name, globals, locals, fromlist, level)

    return _fake_import, fake_imports


def test_ci_probe_writes_restarted_payload(monkeypatch, tmp_path: Path) -> None:
    result_path = tmp_path / "probe.json"
    monkeypatch.setenv("SURVEYCONTROLLER_UPDATE_TEST_RESULT", str(result_path))
    monkeypatch.setenv("SURVEYCONTROLLER_UPDATE_TEST_RESTARTED", "1")
    monkeypatch.setenv("SURVEYCONTROLLER_UPDATE_EXPECTED_VERSION", "9.9.2")
    monkeypatch.setattr(ci_probe.sys, "argv", ["SurveyController.exe", "--ci-update-probe"])

    fake_import, _ = _patch_probe_imports("9.9.2", object())
    with patch("builtins.__import__", side_effect=fake_import):
        assert ci_probe.run() == 0

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["status"] == "restarted"
    assert payload["version"] == "9.9.2"


def test_ci_probe_reports_missing_velopack_update(monkeypatch, tmp_path: Path) -> None:
    result_path = tmp_path / "probe.json"
    monkeypatch.setenv("SURVEYCONTROLLER_UPDATE_TEST_RESULT", str(result_path))
    monkeypatch.delenv("SURVEYCONTROLLER_UPDATE_TEST_RESTARTED", raising=False)

    class _UpdateManager:
        @staticmethod
        def check_updates():
            return {"has_update": True}

    fake_import, _ = _patch_probe_imports("9.9.1", _UpdateManager)
    with patch("builtins.__import__", side_effect=fake_import):
        assert ci_probe.run() == 1

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["status"] == "missing-velopack-update"


def test_ci_probe_writes_serializable_update_summary(monkeypatch, tmp_path: Path) -> None:
    result_path = tmp_path / "probe.json"
    update_object = object()
    monkeypatch.setenv("SURVEYCONTROLLER_UPDATE_TEST_RESULT", str(result_path))
    monkeypatch.delenv("SURVEYCONTROLLER_UPDATE_TEST_RESTARTED", raising=False)

    class _UpdateManager:
        @staticmethod
        def check_updates():
            return {
                "has_update": False,
                "status": "latest",
                "current_version": "9.9.2",
                "_velopack_update": update_object,
            }

    fake_import, _ = _patch_probe_imports("9.9.2", _UpdateManager)
    with patch("builtins.__import__", side_effect=fake_import):
        assert ci_probe.run() == 0

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["status"] == "no-update"
    assert payload["update_info"] == {
        "has_update": False,
        "status": "latest",
        "current_version": "9.9.2",
    }

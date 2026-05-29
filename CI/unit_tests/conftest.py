from __future__ import annotations

import os
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QObject, QMimeData, Signal
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication


class _InMemoryClipboard(QObject):
    dataChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._mime_data = QMimeData()
        self._image = QImage()

    def clear(self) -> None:
        self._mime_data = QMimeData()
        self._image = QImage()
        self.dataChanged.emit()

    def mimeData(self, *_args, **_kwargs) -> QMimeData:
        return self._mime_data

    def setMimeData(self, mime_data: QMimeData | None, *_args, **_kwargs) -> None:
        self._mime_data = mime_data or QMimeData()
        image_data = self._mime_data.imageData() if self._mime_data.hasImage() else None
        self._image = image_data if isinstance(image_data, QImage) else QImage()
        self.dataChanged.emit()

    def image(self, *_args, **_kwargs) -> QImage:
        return self._image

    def setImage(self, image: QImage, *_args, **_kwargs) -> None:
        self._image = QImage(image)
        self._mime_data = QMimeData()
        self._mime_data.setImageData(self._image)
        self.dataChanged.emit()


@pytest.fixture(autouse=True)
def isolate_qsettings(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    settings_file = tmp_path / "qsettings.ini"
    monkeypatch.setenv("SURVEYCONTROLLER_QSETTINGS_FILE", os.fspath(settings_file))

    from software.integrations.ai import settings as ai_settings

    ai_settings._RUNTIME_AI_SETTINGS = None

    yield

    ai_settings._RUNTIME_AI_SETTINGS = None


@pytest.fixture(autouse=True)
def isolate_system_clipboard(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_clipboard = _InMemoryClipboard()
    monkeypatch.setattr(QApplication, "clipboard", staticmethod(lambda *_args, **_kwargs: fake_clipboard))
    monkeypatch.setattr(QGuiApplication, "clipboard", staticmethod(lambda *_args, **_kwargs: fake_clipboard))
    yield


@pytest.fixture
def patch_attrs(monkeypatch: pytest.MonkeyPatch):
    def apply(*entries: tuple[object, str, object]) -> None:
        for target, name, value in entries:
            monkeypatch.setattr(target, name, value)

    return apply


@pytest.fixture
def make_runtime_state():
    def factory(
        questions_metadata: dict[Any, Any] | None = None,
        question_config_index_map: dict[Any, Any] | None = None,
        *,
        config_defaults: dict[str, Any] | None = None,
        config_overrides: dict[str, Any] | None = None,
        base_overrides: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        config_payload = {
            "questions_metadata": dict(questions_metadata or {}),
            "question_config_index_map": dict(question_config_index_map or {}),
            "answer_duration_range_seconds": [0, 0],
        }
        if config_defaults:
            config_payload.update(config_defaults)
        if config_overrides:
            config_payload.update(config_overrides)

        state = SimpleNamespace(
            config=SimpleNamespace(**config_payload),
            stop_event=threading.Event(),
            step_updates=[],
            status_updates=[],
        )
        if base_overrides:
            for name, value in base_overrides.items():
                setattr(state, name, value)

        def update_thread_step(
            _thread_name: str,
            current: int,
            total: int,
            *,
            status_text: str,
            running: bool,
        ) -> None:
            state.step_updates.append((current, total, status_text, running))

        def update_thread_status(
            _thread_name: str,
            status_text: str,
            *,
            running: bool,
        ) -> None:
            state.status_updates.append((status_text, running))

        state.update_thread_step = update_thread_step
        state.update_thread_status = update_thread_status
        return state

    return factory


@pytest.fixture
def make_mock_event():
    def factory(
        *,
        is_set: bool = False,
        wait_return: bool = False,
        spec: object = threading.Event,
    ) -> MagicMock:
        event = MagicMock(spec=spec)
        event.is_set.return_value = is_set
        event.wait.return_value = wait_return
        return event

    return factory


@pytest.fixture
def make_stop_policy_mock():
    def factory(
        *,
        record_success_return: bool = False,
        record_failure_return: bool = False,
    ) -> MagicMock:
        policy = MagicMock()
        policy.record_success.return_value = record_success_return
        policy.record_failure.return_value = record_failure_return
        return policy

    return factory


@pytest.fixture
def make_gui_mock():
    def factory(*method_names: str) -> SimpleNamespace:
        return SimpleNamespace(
            **{name: MagicMock() for name in method_names},
        )

    return factory


@pytest.fixture
def make_http_response():
    def factory(*, json_payload: Any | None = None) -> MagicMock:
        response = MagicMock()
        response.json.return_value = {} if json_payload is None else json_payload
        return response

    return factory


@pytest.fixture
def make_settings_mock():
    def factory(*, value_return: Any = None) -> MagicMock:
        settings = MagicMock()
        settings.value.return_value = value_return
        return settings

    return factory


@pytest.fixture
def make_callable_mock():
    def factory(*, return_value: Any = None, side_effect: Any = None) -> MagicMock:
        mock = MagicMock()
        if side_effect is not None:
            mock.side_effect = side_effect
        else:
            mock.return_value = return_value
        return mock

    return factory

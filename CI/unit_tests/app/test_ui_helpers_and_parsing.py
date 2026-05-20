from __future__ import annotations

import queue
import threading
from types import SimpleNamespace
from typing import Any, cast

import pytest
from PySide6.QtCore import QAbstractAnimation, QEvent

import software.ui.controller.run_controller_parts.parsing as parsing_module
import software.ui.controller.ui_dispatcher as ui_dispatcher_module
import software.ui.helpers.qfluent_compat as qfluent_compat
from software.providers.errors import SurveyPausedError


class _FakeAniGroup:
    def __init__(self, state: QAbstractAnimation.State = QAbstractAnimation.State.Stopped) -> None:
        self._state = state
        self.pause_calls = 0
        self.resume_calls = 0

    def state(self) -> QAbstractAnimation.State:
        return self._state

    def pause(self) -> None:
        self.pause_calls += 1
        self._state = QAbstractAnimation.State.Paused

    def resume(self) -> None:
        self.resume_calls += 1
        self._state = QAbstractAnimation.State.Running


class _FakeRing:
    def __init__(
        self,
        *,
        state: QAbstractAnimation.State | None = QAbstractAnimation.State.Stopped,
        start_raises: bool = False,
        stop_raises: bool = False,
    ) -> None:
        self.aniGroup = _FakeAniGroup(state) if state is not None else None
        self._start_raises = start_raises
        self._stop_raises = stop_raises
        self.shown = 0
        self.hidden = 0
        self.started = 0
        self.stopped = 0

    def show(self) -> None:
        self.shown += 1

    def hide(self) -> None:
        self.hidden += 1

    def start(self) -> None:
        self.started += 1
        if self._start_raises:
            raise RuntimeError("start failed")

    def stop(self) -> None:
        self.stopped += 1
        if self._stop_raises:
            raise RuntimeError("stop failed")


class _FakeProgressBar:
    _surveycontroller_resume_guard_installed = False

    def __init__(self, *, state: QAbstractAnimation.State, is_error: bool = False) -> None:
        self.aniGroup = _FakeAniGroup(state)
        self._isError = is_error
        self.start_calls = 0
        self.update_calls = 0

    def start(self) -> None:
        self.start_calls += 1
        self.aniGroup._state = QAbstractAnimation.State.Running

    def update(self) -> None:
        self.update_calls += 1


class _FakeSignal:
    def __init__(self) -> None:
        self.callbacks: list[Any] = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in list(self.callbacks):
            callback(*args)


class _FakeAnimation:
    def __init__(self, *_args, **_kwargs) -> None:
        self.started = 0
        self.start_value = None
        self.end_value = None

    def start(self) -> None:
        self.started += 1

    def setDuration(self, _duration: int) -> None:
        return

    def setStartValue(self, value) -> None:
        self.start_value = value

    def setEndValue(self, value) -> None:
        self.end_value = value


class _FakeAnimationGroup:
    def __init__(self, *_args, **_kwargs) -> None:
        self.animations: list[Any] = []
        self.started = 0

    def addAnimation(self, animation) -> None:
        self.animations.append(animation)

    def removeAnimation(self, animation) -> None:
        if animation in self.animations:
            self.animations.remove(animation)

    def start(self) -> None:
        self.started += 1


class _FakeQtApp:
    def processEvents(self) -> None:
        return


class _FakeParent:
    def __init__(self) -> None:
        self.filters: list[Any] = []
        self.invalid = False

    def installEventFilter(self, obj) -> None:
        self.filters.append(obj)


class _FakeBar:
    def __init__(self, parent: _FakeParent) -> None:
        self._parent = parent
        self._props: dict[str, Any] = {}
        self.closedSignal = _FakeSignal()
        self.destroyed = _FakeSignal()
        self.invalid = False
        self.moved_to = None

    def parent(self):
        return self._parent

    def setProperty(self, key: str, value: Any) -> None:
        self._props[key] = value

    def property(self, key: str) -> Any:
        return self._props.get(key)

    def pos(self):
        return (0, 0)

    def move(self, value) -> None:
        self.moved_to = value


class _FakeManager:
    managers: dict[str, type] = {}

    def __init__(self) -> None:
        self.infoBars: dict[Any, list[Any]] = {}
        self.aniGroups: dict[Any, _FakeAnimationGroup] = {}
        self.dropAnis: list[Any] = []
        self.slideAnis: list[Any] = []

    def _createSlideAni(self, _bar) -> _FakeAnimation:
        return _FakeAnimation()

    def _pos(self, _bar, size=None):
        return ("pos", size)


class _FakeEvent:
    def __init__(self, event_type: QEvent.Type) -> None:
        self._type = event_type

    def type(self) -> QEvent.Type:
        return self._type

    def size(self):
        return "resized"


class _FakeFuture:
    def __init__(self, result: Any = None, error: BaseException | None = None) -> None:
        self._result = result
        self._error = error

    def result(self):
        if self._error is not None:
            raise self._error
        return self._result

    def add_done_callback(self, callback) -> None:
        callback(self)


class _FakeParsingController:
    parse_survey = parsing_module.RunControllerParsingMixin.parse_survey

    def __init__(self, future: _FakeFuture | None = None) -> None:
        self.surveyParsed = SimpleNamespace(emit=lambda *args: self.parsed.append(args))
        self.surveyParseFailed = SimpleNamespace(emit=lambda message: self.failures.append(message))
        self.config = SimpleNamespace(
            url="",
            survey_provider="",
            survey_title="",
            questions_info=[],
            question_entries=[],
        )
        self.questions_info = []
        self.question_entries = []
        self.survey_title = ""
        self.survey_provider = ""
        self.parsed: list[Any] = []
        self.failures: list[str] = []
        self._async_engine_client = SimpleNamespace(parse_survey=lambda _url: future)
        self._dispatch_to_ui_async = lambda callback: callback()


class UiHelperAndParsingTests:
    def test_set_indeterminate_progress_ring_active_handles_resume_start_and_hide(self) -> None:
        paused_ring = _FakeRing(state=QAbstractAnimation.State.Paused)
        qfluent_compat.set_indeterminate_progress_ring_active(paused_ring, True)
        assert paused_ring.shown == 1
        assert paused_ring.aniGroup is not None
        assert paused_ring.aniGroup.resume_calls == 1

        stopped_ring = _FakeRing(state=QAbstractAnimation.State.Stopped)
        qfluent_compat.set_indeterminate_progress_ring_active(stopped_ring, True)
        assert stopped_ring.started == 1

        no_group_ring = _FakeRing(state=None)
        qfluent_compat.set_indeterminate_progress_ring_active(no_group_ring, True)
        assert no_group_ring.started == 1

        running_ring = _FakeRing(state=QAbstractAnimation.State.Running)
        qfluent_compat.set_indeterminate_progress_ring_active(running_ring, False)
        assert running_ring.stopped == 1
        assert running_ring.hidden == 1

    def test_set_indeterminate_progress_ring_active_swallows_runtime_errors(self) -> None:
        ring = _FakeRing(state=QAbstractAnimation.State.Running, stop_raises=True)
        qfluent_compat.set_indeterminate_progress_ring_active(ring, False)
        assert ring.hidden == 0

        fallback_ring = _FakeRing(state=None, stop_raises=True)
        qfluent_compat.set_indeterminate_progress_ring_active(fallback_ring, False)
        assert fallback_ring.hidden == 0

    def test_install_qfluentwidgets_animation_guards_patches_progress_class(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_info_bar_manager = type("FakeInfoBarManager", (), {"managers": {}})
        monkeypatch.setattr(qfluent_compat, "_install_infobar_manager_guards", lambda cls: setattr(cls, "patched", True))
        monkeypatch.setattr("qfluentwidgets.IndeterminateProgressBar", _FakeProgressBar)
        monkeypatch.setattr(
            "qfluentwidgets.components.widgets.info_bar.InfoBarManager",
            fake_info_bar_manager,
        )

        qfluent_compat.install_qfluentwidgets_animation_guards()

        paused = cast(Any, _FakeProgressBar(state=QAbstractAnimation.State.Paused))
        paused.resume()
        assert paused.aniGroup.resume_calls == 1
        assert paused.update_calls == 1

        stopped = cast(Any, _FakeProgressBar(state=QAbstractAnimation.State.Stopped))
        stopped.resume()
        assert stopped.start_calls == 1

        running = cast(Any, _FakeProgressBar(state=QAbstractAnimation.State.Running))
        running.setPaused(True)
        assert running.aniGroup.pause_calls == 1
        running.setPaused(False)
        assert running.update_calls >= 1
        assert getattr(_FakeProgressBar, "_surveycontroller_resume_guard_installed", False) is True
        assert getattr(fake_info_bar_manager, "patched", False) is True

    def test_install_infobar_manager_guards_handles_add_remove_and_event_filter(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(qfluent_compat, "QParallelAnimationGroup", _FakeAnimationGroup)
        monkeypatch.setattr(qfluent_compat, "QPropertyAnimation", _FakeAnimation)
        monkeypatch.setattr(qfluent_compat, "isValid", lambda obj: not getattr(obj, "invalid", False))
        qfluent_compat._install_infobar_manager_guards(_FakeManager)

        manager = cast(Any, _FakeManager())
        parent = _FakeParent()
        bar = _FakeBar(parent)

        manager.add(bar)
        assert parent in manager.infoBars
        assert bar in manager.infoBars[parent]
        assert bar.property("slideAni") is not None

        second_bar = _FakeBar(parent)
        manager.add(second_bar)
        second_drop_ani = second_bar.property("dropAni")
        assert second_drop_ani is not None
        assert second_drop_ani.start_value == ("pos", None)
        assert second_drop_ani.end_value == ("pos", None)

        manager._updateDropAni(parent)
        assert manager.slideAnis

        manager.eventFilter(parent, _FakeEvent(QEvent.Type.Resize))
        assert bar.moved_to == ("pos", "resized")

        bar.closedSignal.emit()
        assert id(bar) not in manager._surveycontroller_signal_callbacks

    def test_ui_callback_dispatcher_covers_enqueue_drain_and_async_paths(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        emitted: list[str] = []
        dispatcher = ui_dispatcher_module.UiCallbackDispatcher(lambda: emitted.append("emit"))
        calls: list[str] = []

        assert dispatcher.enqueue(lambda: calls.append("queued")) is True
        dispatcher.drain()
        assert emitted == ["emit"]
        assert calls == ["queued"]

        dispatcher._queue.put_nowait("not-callable")
        dispatcher.drain()

        monkeypatch.setattr(ui_dispatcher_module.QCoreApplication, "instance", lambda: None)
        dispatcher.dispatch_async(lambda: calls.append("no-app"))

        monkeypatch.setattr(
            ui_dispatcher_module.QCoreApplication,
            "instance",
            lambda: _FakeQtApp(),
        )
        monkeypatch.setattr(ui_dispatcher_module.threading, "current_thread", threading.main_thread)
        dispatcher.dispatch_async(lambda: calls.append("main-thread"))

        queued: list[Any] = []
        monkeypatch.setattr(ui_dispatcher_module.threading, "current_thread", lambda: object())
        monkeypatch.setattr(dispatcher, "enqueue", lambda callback: queued.append(callback) or True)
        dispatcher.dispatch_async(lambda: calls.append("background"))
        assert len(queued) == 1
        queued[0]()

        assert calls == ["queued", "no-app", "main-thread", "background"]

    def test_ui_callback_dispatcher_handles_enqueue_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dispatcher = ui_dispatcher_module.UiCallbackDispatcher(lambda: None)

        def _boom(_callback) -> None:
            raise queue.Full

        monkeypatch.setattr(dispatcher._queue, "put_nowait", _boom)
        assert dispatcher.enqueue(lambda: None) is False

    def test_parse_survey_validates_url_and_handles_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        definition = SimpleNamespace(
            title="问卷A",
            provider="wjx",
            questions=[
                SimpleNamespace(is_description=False, name="q1"),
                SimpleNamespace(is_description=True, name="desc"),
            ],
        )
        controller = _FakeParsingController(_FakeFuture(result=definition))
        monkeypatch.setattr(parsing_module, "is_supported_survey_url", lambda url: url.startswith("http"))
        monkeypatch.setattr(
            parsing_module,
            "build_default_question_entries",
            lambda info, survey_url, existing_entries: [f"{survey_url}:{len(info)}"],
        )

        controller.parse_survey(" http://survey ")

        assert controller.parsed == [([definition.questions[0]], "问卷A")]
        assert controller.config.url == "http://survey"
        assert controller.config.survey_provider == "wjx"
        assert controller.question_entries == ["http://survey:1"]

    def test_parse_survey_handles_empty_unsupported_and_known_business_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        controller = _FakeParsingController()
        controller.parse_survey("")
        assert controller.failures == ["请填写问卷链接"]

        monkeypatch.setattr(parsing_module, "is_supported_survey_url", lambda _url: False)
        controller.parse_survey("bad")
        assert controller.failures[-1] == "仅支持问卷星、腾讯问卷与 Credamo 见数链接"

        monkeypatch.setattr(parsing_module, "is_supported_survey_url", lambda _url: True)
        paused = _FakeParsingController(_FakeFuture(error=SurveyPausedError("暂停中")))
        paused.parse_survey("http://survey")
        assert paused.failures == ["暂停中"]

    def test_parse_survey_handles_unexpected_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(parsing_module, "is_supported_survey_url", lambda _url: True)
        controller = _FakeParsingController(_FakeFuture(error=RuntimeError("炸了")))

        controller.parse_survey("http://survey")

        assert controller.failures == ["炸了"]

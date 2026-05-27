from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from software.core.questions.config import QuestionEntry
from software.core.config.schema import RuntimeConfig
from software.ui.pages.workbench.session import WorkbenchRunCoordinator, WorkbenchState


class _FakeController:
    def __init__(self) -> None:
        self.running = False
        self._starting = False
        self._initializing = False
        self.runtime_updates: list[dict] = []
        self.started_configs: list[RuntimeConfig] = []

    def set_runtime_ui_state(self, **updates):
        self.runtime_updates.append(dict(updates))

    def start_run(self, cfg: RuntimeConfig) -> None:
        self.started_configs.append(cfg)

    def is_initializing(self) -> bool:
        return bool(self._initializing)


class _FakeSpinBox:
    def __init__(self, value: int) -> None:
        self._value = int(value)
        self.blocked: list[bool] = []

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:
        self._value = int(value)

    def blockSignals(self, blocked: bool) -> None:
        self.blocked.append(bool(blocked))


class _FakeStartButton:
    def __init__(self) -> None:
        self.enabled = True

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)


class _FakeSlider:
    def __init__(self) -> None:
        self.enabled = True

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)


class _FakeDashboard:
    def __init__(self, *, target: int = 1) -> None:
        self.controller: Any = None
        self.target_spin = _FakeSpinBox(target)
        self.progress_bar = SimpleNamespace(setValue=lambda _value: None)
        self.progress_pct = SimpleNamespace(setText=lambda _value: None)
        self.status_label = SimpleNamespace(setText=lambda _value: None)
        self.start_btn = _FakeStartButton()
        self.thread_slider = _FakeSlider()
        self._completion_notified = False
        self._last_progress = 0
        self.synced_start_states: list[bool] = []
        self.toasts: list[tuple[str, str]] = []

    def build_base_config(self) -> RuntimeConfig:
        return RuntimeConfig(
            url="https://example.com/survey",
            target=self.target_spin.value(),
            threads=4,
            random_ip_enabled=True,
        )

    def _sync_start_button_state(self, running=None) -> None:
        if running is None:
            running = bool(
                getattr(self.controller, "running", False)
                or getattr(self.controller, "_starting", False)
                or getattr(self.controller, "is_initializing", lambda: False)()
            )
        self.synced_start_states.append(bool(running))
        can_start = (not bool(running)) and self._has_question_entries()
        self.start_btn.setEnabled(bool(can_start))

    def _sync_thread_slider_enabled(self, running=None) -> None:
        if running is None:
            running = bool(
                getattr(self.controller, "running", False)
                or getattr(self.controller, "_starting", False)
                or getattr(self.controller, "is_initializing", lambda: False)()
            )
        self.thread_slider.setEnabled(not bool(running))

    def _has_question_entries(self) -> bool:
        return True

    def _toast(self, text: str, level: str = "info", *_args, **_kwargs) -> None:
        self.toasts.append((text, level))


class _FakeReverseFillPage:
    def __init__(self, source_path: str = "D:/demo.xlsx") -> None:
        self.source_path = source_path

    def update_config(self, cfg: RuntimeConfig) -> None:
        cfg.reverse_fill_source_path = self.source_path
        cfg.reverse_fill_enabled = bool(self.source_path)


def _state_with_one_entry() -> WorkbenchState:
    state = WorkbenchState()
    state.set_entries(
        [
            QuestionEntry(
                question_type="single",
                probabilities=[1.0],
                question_num=1,
                question_title="Q1",
            )
        ],
        [],
    )
    return state


def test_set_reverse_fill_target_updates_controller_without_touching_dashboard_spinbox() -> None:
    controller = _FakeController()
    dashboard = _FakeDashboard(target=9)
    coordinator = WorkbenchRunCoordinator(
        controller=controller,
        state=_state_with_one_entry(),
        dashboard=dashboard,
    )

    coordinator.set_reverse_fill_target(20)

    assert controller.runtime_updates == [{"target": 20}]
    assert dashboard.target_spin.value() == 9
    assert dashboard.target_spin.blocked == []


def test_set_reverse_fill_target_normalizes_small_values_to_one() -> None:
    controller = _FakeController()
    dashboard = _FakeDashboard(target=9)
    coordinator = WorkbenchRunCoordinator(
        controller=controller,
        state=_state_with_one_entry(),
        dashboard=dashboard,
    )

    coordinator.set_reverse_fill_target(0)

    assert controller.runtime_updates == [{"target": 1}]
    assert dashboard.target_spin.value() == 9


def test_start_reverse_fill_uses_reverse_fill_target_override() -> None:
    controller = _FakeController()
    dashboard = _FakeDashboard(target=1)
    coordinator = WorkbenchRunCoordinator(
        controller=controller,
        state=_state_with_one_entry(),
        dashboard=dashboard,
    )
    coordinator.bind_reverse_fill_page(_FakeReverseFillPage())

    coordinator.set_reverse_fill_target(20)
    started = coordinator.start_reverse_fill()

    assert started is True
    assert len(controller.started_configs) == 1
    cfg = controller.started_configs[0]
    assert cfg.target == 20
    assert cfg.reverse_fill_enabled is True


def test_normal_start_ignores_reverse_fill_target_override() -> None:
    controller = _FakeController()
    dashboard = _FakeDashboard(target=3)
    coordinator = WorkbenchRunCoordinator(
        controller=controller,
        state=_state_with_one_entry(),
        dashboard=dashboard,
    )
    coordinator.bind_reverse_fill_page(_FakeReverseFillPage())

    coordinator._reverse_fill_target_override = 20
    started = coordinator.start(enable_reverse_fill=False)

    assert started is True
    assert len(controller.started_configs) == 1
    cfg = controller.started_configs[0]
    assert cfg.target == 3
    assert cfg.reverse_fill_enabled is False


def test_starting_state_locks_dashboard_run_controls() -> None:
    controller = _FakeController()
    dashboard = _FakeDashboard(target=3)
    dashboard.controller = controller

    controller._starting = True
    dashboard._sync_start_button_state()
    dashboard._sync_thread_slider_enabled()

    assert dashboard.start_btn.enabled is False
    assert dashboard.thread_slider.enabled is False

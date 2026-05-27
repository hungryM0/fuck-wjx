from __future__ import annotations

import software.ui.pages.workbench.runtime_panel.random_ip_card as random_ip_module
from software.ui.pages.workbench.runtime_panel.cards import (
    FluentIcon,
    RandomUASettingCard,
    ReliabilitySettingCard,
    TimeRangeSettingCard,
)


class TestRuntimePanelCardsQtBot:
    def test_random_ua_card_enables_and_disables_content(self, qtbot) -> None:
        card = RandomUASettingCard()
        qtbot.addWidget(card)

        card.setUAEnabled(False)
        assert card._groupContainer.isEnabled() is False

        card.setUAEnabled(True)
        assert card._groupContainer.isEnabled() is True

    def test_reliability_card_syncs_alpha_and_toggle_state(self, qtbot) -> None:
        card = ReliabilitySettingCard()
        qtbot.addWidget(card)

        card.setChecked(True)
        card.set_alpha(0.92)

        assert card.isChecked() is True
        assert card.get_alpha() == 0.92

    def test_time_range_card_emits_value_changed_and_clamps(self, qtbot) -> None:
        card = TimeRangeSettingCard(FluentIcon.HISTORY, "标题", "说明", max_seconds=10)
        qtbot.addWidget(card)

        values: list[int] = []
        card.valueChanged.connect(values.append)

        card.setValue(12)
        assert card.getValue() == 10
        assert values[-1] == 10


class _FakeThread:
    def __init__(self) -> None:
        self.started = _SignalStub()
        self.finished = _SignalStub()
        self.quit_called = 0
        self.start_called = 0
        self.deleted = 0

    def start(self) -> None:
        self.start_called += 1
        self.started.emit()

    def quit(self, *args) -> None:
        self.quit_called += 1
        self.finished.emit()

    def deleteLater(self, *args) -> None:
        self.deleted += 1


class _FakeWorker:
    def __init__(self) -> None:
        self.finished = _SignalStub()
        self.move_to_thread_calls: list[object] = []
        self.deleted = 0

    def moveToThread(self, thread) -> None:
        self.move_to_thread_calls.append(thread)

    def run(self) -> None:
        self.finished.emit(True, "")

    def deleteLater(self, *args) -> None:
        self.deleted += 1


class _SignalStub:
    def __init__(self) -> None:
        self.callbacks: list[object] = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in list(self.callbacks):
            callback(*args)


def test_random_ip_prefetch_flow_uses_worker_thread(monkeypatch, qtbot) -> None:
    card = random_ip_module.RandomIPSettingCard()
    qtbot.addWidget(card)

    fake_thread = _FakeThread()
    fake_worker = _FakeWorker()

    monkeypatch.setattr(random_ip_module, "QThread", lambda _parent=None: fake_thread)
    monkeypatch.setattr(
        random_ip_module,
        "_BenefitAreaPrefetchWorker",
        lambda force_refresh=False: fake_worker,
    )
    monkeypatch.setattr(
        random_ip_module,
        "load_benefit_supported_areas",
        lambda force_refresh=False: [],
    )

    card._start_benefit_area_prefetch()

    assert fake_thread.start_called == 1
    assert fake_worker.move_to_thread_calls == [fake_thread]

from __future__ import annotations

import software.ui.pages.workbench.runtime_panel.random_ip_card as random_ip_module
import software.ui.pages.workbench.shared.random_ip_toggle_row as toggle_row_module
from PySide6.QtCore import QDateTime
from software.ui.pages.workbench.runtime_panel.cards import (
    AnswerDateTimeWindowSettingCard,
    FluentIcon,
    RandomUASettingCard,
    ReliabilitySettingCard,
    TimeRangeSettingCard,
)
from software.ui.pages.workbench.shared.random_ip_toggle_row import RandomIpToggleRow


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

    def test_time_range_card_preserves_range_and_normalizes_end(self, qtbot) -> None:
        card = TimeRangeSettingCard(FluentIcon.HISTORY, "标题", "说明", max_seconds=30)
        qtbot.addWidget(card)

        ranges: list[tuple[int, int]] = []
        card.rangeChanged.connect(ranges.append)

        card.setRange((5, 20))
        assert card.getRange() == (5, 20)
        assert ranges[-1] == (5, 20)

        card.setRange((25, 10))
        assert card.getRange() == (25, 25)
        assert ranges[-1] == (25, 25)

    def test_duration_picker_accepts_formatted_confirmed_values(self, qtbot) -> None:
        card = TimeRangeSettingCard(FluentIcon.HISTORY, "标题", "说明", max_seconds=300)
        qtbot.addWidget(card)

        card.startPicker._onConfirmed(["2 分", "30 秒"])

        assert card.getRange() == (150, 150)

    def test_answer_datetime_window_card_switches_provider_enabled_state(self, qtbot) -> None:
        card = AnswerDateTimeWindowSettingCard(FluentIcon.HISTORY, "标题", "说明", max_seconds=300)
        qtbot.addWidget(card)

        card.set_provider("wjx")
        assert card._input_container.isEnabled() is False

        card.set_provider("credamo")
        assert card._input_container.isEnabled() is True

    def test_answer_datetime_window_card_shows_credamo_badge(self, qtbot) -> None:
        card = AnswerDateTimeWindowSettingCard(FluentIcon.HISTORY, "标题", "说明", max_seconds=300)
        qtbot.addWidget(card)

        assert card.credamo_badge.text() == "见数"
        assert card.CREDAMO_BADGE_COLOR == "#1f4f99"

    def test_answer_datetime_window_card_keeps_datetime_values(self, qtbot) -> None:
        card = AnswerDateTimeWindowSettingCard(FluentIcon.HISTORY, "标题", "说明", max_seconds=300)
        qtbot.addWidget(card)

        card.setDateTimeWindow(("2026-02-10 09:00:00", "2026-02-10 10:00:00"))

        assert card.getDateTimeWindow() == ("2026-02-10 09:00:00", "2026-02-10 10:00:00")
        assert card.startTimePicker.columns[0].name() == "时"
        assert card.startTimePicker.columns[1].name() == "分"
        assert card.startTimePicker.isSecondVisible() is False

    def test_answer_datetime_window_card_clamps_future_datetime(self, monkeypatch, qtbot) -> None:
        fake_now = QDateTime.fromString("2026-02-10 09:15:00", "yyyy-MM-dd HH:mm:ss")
        monkeypatch.setattr(
            AnswerDateTimeWindowSettingCard,
            "_now",
            staticmethod(lambda: fake_now),
        )
        card = AnswerDateTimeWindowSettingCard(FluentIcon.HISTORY, "标题", "说明", max_seconds=300)
        qtbot.addWidget(card)

        card.setDateTimeWindow(("2026-02-10 10:00:00", "2026-02-11 08:00:00"))

        assert card.getDateTimeWindow() == ("2026-02-10 09:15:00", "2026-02-10 08:00:00")

    def test_random_ip_card_loading_uses_progress_ring_helper(self, monkeypatch, qtbot) -> None:
        card = random_ip_module.RandomIPSettingCard()
        qtbot.addWidget(card)

        calls: list[tuple[object, bool]] = []
        monkeypatch.setattr(
            random_ip_module,
            "set_indeterminate_progress_ring_active",
            lambda ring, active: calls.append((ring, bool(active))),
        )

        card.setLoading(True, "同步中")
        card.setLoading(False, "")

        assert calls == [(card.loadingRing, True), (card.loadingRing, False)]


def test_random_ip_toggle_row_loading_uses_progress_ring_helper(monkeypatch, qtbot) -> None:
    row = RandomIpToggleRow(toggle_row_module.BodyLabel)
    qtbot.addWidget(row)

    calls: list[tuple[object, bool]] = []
    monkeypatch.setattr(
        toggle_row_module,
        "set_indeterminate_progress_ring_active",
        lambda ring, active: calls.append((ring, bool(active))),
    )

    row.set_loading(True, "处理中")
    row.set_loading(False, "")

    assert calls == [(row.loading_ring, True), (row.loading_ring, False)]


def test_random_ip_toggle_row_supports_switch_style(qtbot) -> None:
    row = RandomIpToggleRow(
        toggle_row_module.BodyLabel,
        use_switch_style=True,
        leading_label_text="随机IP：",
    )
    qtbot.addWidget(row)

    assert row.leading_label is not None
    assert row.leading_label.text() == "随机IP："

    row.sync_toggle_presentation(True)
    assert row.toggle_button.isChecked() is True

    row.sync_toggle_presentation(False)
    assert row.toggle_button.isChecked() is False


def test_random_ip_toggle_row_loading_disables_with_opacity(qtbot) -> None:
    row = RandomIpToggleRow(toggle_row_module.BodyLabel, use_switch_style=True)
    qtbot.addWidget(row)

    row.set_loading(True, "处理中")
    effect = row.toggle_button.graphicsEffect()
    assert row.toggle_button.isEnabled() is False
    assert effect is not None
    assert round(float(effect.opacity()), 2) == 0.40

    row.set_loading(False, "")
    effect = row.toggle_button.graphicsEffect()
    assert row.toggle_button.isEnabled() is True
    assert effect is not None
    assert round(float(effect.opacity()), 2) == 1.00


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

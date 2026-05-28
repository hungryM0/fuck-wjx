"""运行参数页事件绑定。"""

from __future__ import annotations

from typing import Any

from software.logging.action_logger import bind_logged_action


def bind_runtime_page_events(page: Any) -> None:
    page.target_card.spinBox.valueChanged.connect(
        lambda value: page.controller.set_runtime_ui_state(target=int(value))
    )
    page.thread_card.slider.valueChanged.connect(
        lambda value: page.controller.set_runtime_ui_state(threads=int(value))
    )
    bind_logged_action(
        page.random_ip_card.switchButton.checkedChanged,
        page._on_random_ip_toggled,
        scope="CONFIG",
        event="toggle_random_ip",
        target="random_ip_switch",
        page="runtime",
        payload_factory=lambda enabled: {"enabled": bool(enabled)},
    )
    bind_logged_action(
        page.random_ua_card.switchButton.checkedChanged,
        page._on_random_ua_toggled,
        scope="CONFIG",
        event="toggle_random_ua",
        target="random_ua_switch",
        page="runtime",
        payload_factory=lambda enabled: {"enabled": bool(enabled)},
    )
    bind_logged_action(
        page.random_ip_card.proxyCombo.currentIndexChanged,
        page._on_proxy_source_changed,
        scope="CONFIG",
        event="change_proxy_source",
        target="proxy_source_combo",
        page="runtime",
        payload_factory=lambda _index: {"source": page.selected_proxy_source()},
        forward_signal_args=False,
    )
    page.interval_card.rangeChanged.connect(page._on_time_settings_changed)
    page.answer_duration_card.rangeChanged.connect(page._on_time_settings_changed)
    page.answer_card.datetimeWindowChanged.connect(page._on_answer_datetime_window_changed)
    bind_logged_action(
        page.reliability_card.switchButton.checkedChanged,
        page._on_reliability_mode_toggled,
        scope="CONFIG",
        event="toggle_reliability_mode",
        target="reliability_switch",
        page="runtime",
        payload_factory=lambda enabled: {"enabled": bool(enabled)},
    )

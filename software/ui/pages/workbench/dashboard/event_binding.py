"""Dashboard 页面事件绑定。"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtWidgets import QApplication

from software.logging.action_logger import bind_logged_action
from software.logging.log_utils import log_suppressed_exception


def bind_dashboard_events(page: Any) -> None:
    bind_logged_action(
        page.parse_btn.clicked,
        page._on_parse_clicked,
        scope="UI",
        event="parse_survey",
        target="parse_btn",
        page="dashboard",
        forward_signal_args=False,
    )
    bind_logged_action(
        page.config_list_action.triggered,
        page._on_show_config_list,
        scope="UI",
        event="open_config_list",
        target="config_list_btn",
        page="dashboard",
        forward_signal_args=False,
    )
    bind_logged_action(
        page.load_cfg_action.triggered,
        page._on_load_config,
        scope="CONFIG",
        event="load_config",
        target="load_cfg_btn",
        page="dashboard",
        forward_signal_args=False,
    )
    bind_logged_action(
        page.save_cfg_action.triggered,
        page._on_save_config,
        scope="CONFIG",
        event="save_config",
        target="save_cfg_btn",
        page="dashboard",
        forward_signal_args=False,
    )
    bind_logged_action(
        page.qr_btn.clicked,
        page._on_qr_clicked,
        scope="UI",
        event="parse_qr_image",
        target="qr_btn",
        page="dashboard",
        forward_signal_args=False,
    )
    page._bind_progress_events()
    page.thread_view_seg.currentItemChanged.connect(page._on_thread_view_changed)
    page.target_spin.valueChanged.connect(
        lambda value: page.controller.set_runtime_ui_state(target=int(value))
    )
    page.thread_spin.valueChanged.connect(
        lambda value: page.controller.set_runtime_ui_state(threads=int(value))
    )
    page.random_ip_cb.toggled.connect(page._on_random_ip_toggled)
    bind_logged_action(
        page.card_btn.clicked,
        page._on_request_quota_clicked,
        scope="UI",
        event="open_quota_request",
        target="card_btn",
        page="dashboard",
        forward_signal_args=False,
    )
    page.random_ip_quota_card.backgroundClicked.connect(page.refresh_random_ip_heartbeat_async)
    bind_logged_action(
        page.runtime_settings_hint_card.openRequested,
        page._go_to_runtime_page,
        scope="NAV",
        event="open_runtime_settings",
        target="runtime_settings_hint_card",
        page="dashboard",
        forward_signal_args=False,
    )
    page.controller.runtimeUiStateChanged.connect(page._apply_runtime_ui_state)
    page.controller.randomIpLoadingChanged.connect(page.set_random_ip_loading)
    QApplication.clipboard().dataChanged.connect(page._on_clipboard_changed)
    page.add_action.triggered.connect(page._show_add_question_dialog)
    page.edit_action.triggered.connect(page._edit_selected_entries)
    page.del_action.triggered.connect(page._delete_selected_entries)
    page.clear_all_action.triggered.connect(page._clear_all_entries)
    page.controller.surveyParsed.connect(page._on_survey_parsed)
    page.controller.surveyParseFailed.connect(page._on_survey_parse_failed)
    page._ipBalanceChecked.connect(page._on_ip_balance_checked)
    try:
        page.workbench_state.entriesChanged.connect(page._on_question_entries_changed)
    except Exception as exc:
        log_suppressed_exception(
            "_bind_events: self.workbench_state.entriesChanged.connect(self._on_question_entries_changed)",
            exc,
            level=logging.WARNING,
        )
    try:
        page.strategy_page.strategyChanged.connect(page._on_strategy_page_changed)
    except Exception as exc:
        log_suppressed_exception(
            "_bind_events: self.strategy_page.strategyChanged.connect(self._on_strategy_page_changed)",
            exc,
            level=logging.WARNING,
        )
    page._randomIpHeartbeatUpdated.connect(page._apply_random_ip_heartbeat_status)

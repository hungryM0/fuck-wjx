"""运行参数设置页面。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget
from qfluentwidgets import ScrollArea

from software.app.config import HTTP_MAX_THREADS
from software.ui.controller.run_controller import RunController
from software.ui.pages.workbench.runtime_panel.config_sync import RuntimeConfigSyncMixin
from software.ui.pages.workbench.runtime_panel.control_sync import RuntimeControlSyncMixin
from software.ui.pages.workbench.runtime_panel.events import bind_runtime_page_events
from software.ui.pages.workbench.runtime_panel.proxy_sync import RuntimeProxySyncMixin
from software.ui.pages.workbench.runtime_panel.ui_builder import build_runtime_page_ui

if TYPE_CHECKING:
    from software.ui.pages.workbench.runtime_panel.ai import RuntimeAISection
    from software.ui.pages.workbench.runtime_panel.cards import (
        RandomUASettingCard,
        ReliabilitySettingCard,
        TimeRangeSettingCard,
    )
    from software.ui.pages.workbench.runtime_panel.random_ip_card import RandomIPSettingCard
    from software.ui.widgets.setting_cards import (
        SliderSettingCard,
        SpinBoxSettingCard,
    )


class RuntimePage(
    RuntimeConfigSyncMixin,
    RuntimeControlSyncMixin,
    RuntimeProxySyncMixin,
    ScrollArea,
):
    """独立的运行参数/开关页，方便在侧边栏查看。"""

    MIN_THREADS = 1
    HTTP_MAX_THREADS = HTTP_MAX_THREADS
    SUBMIT_INTERVAL_MAX_SECONDS = 300
    view: QWidget
    target_card: "SpinBoxSettingCard"
    thread_card: "SliderSettingCard"
    random_ip_card: "RandomIPSettingCard"
    random_ua_card: "RandomUASettingCard"
    reliability_card: "ReliabilitySettingCard"
    interval_card: "TimeRangeSettingCard"
    answer_card: "TimeRangeSettingCard"
    ai_section: "RuntimeAISection"

    def __init__(self, controller: RunController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._last_benefit_proxy_compatible = None
        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self.view.setObjectName("settings_view")
        build_runtime_page_ui(self)
        bind_runtime_page_events(self)
        self.controller.runtimeUiStateChanged.connect(self._apply_runtime_ui_state)
        self.controller.runStateChanged.connect(self.on_run_state_changed)
        self.controller.randomIpLoadingChanged.connect(self._apply_random_ip_loading)
        self._sync_random_ua(self.random_ua_card.isChecked())
        self._apply_thread_limit()
        self.controller.set_runtime_ui_state(
            emit=False,
            target=self.target_card.spinBox.value(),
            threads=self.thread_card.slider.value(),
            random_ip_enabled=self.random_ip_card.switchButton.isChecked(),
            proxy_source=self.selected_proxy_source(),
            submit_interval=self._card_value_as_range(self.interval_card),
            answer_duration=self._card_value_as_range(self.answer_card),
        )
        self.on_run_state_changed(self._thread_edit_locked())

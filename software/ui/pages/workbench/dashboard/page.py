import logging
import threading
from typing import Any, Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget
from software.logging.log_utils import log_suppressed_exception
from software.ui.dialogs.quota_redeem import load_shop_icon
from software.ui.pages.workbench.dashboard.event_binding import bind_dashboard_events
from software.ui.pages.workbench.dashboard.feedback import dashboard_toast
from software.ui.pages.workbench.dashboard.ui_builder import build_dashboard_page_ui
from software.ui.pages.workbench.dashboard.parts.config_io import (
    DashboardConfigIOMixin,
)
from software.ui.pages.workbench.dashboard.parts.entries import (
    DashboardEntriesMixin,
)
from software.ui.pages.workbench.dashboard.parts.progress import (
    DashboardProgressMixin,
)
from software.ui.pages.workbench.dashboard.parts.random_ip import (
    DashboardRandomIPMixin,
)
from software.ui.pages.workbench.dashboard.parts.run_actions import (
    DashboardRunActionsMixin,
)
from software.ui.pages.workbench.dashboard.parts.survey_parse import (
    DashboardSurveyParseMixin,
)
from software.ui.pages.workbench.shared.clipboard import SurveyClipboardMixin
from software.ui.pages.workbench.shared.run_feedback import init_run_feedback_state
from software.ui.widgets.config_drawer import ConfigDrawer
from software.ui.widgets.full_width_infobar import FullWidthInfoBar
from software.ui.controller.run_controller import RunController
from software.core.config.schema import RuntimeConfig
from software.ui.pages.workbench.runtime_panel.main import RuntimePage
from software.ui.pages.workbench.strategy.page import QuestionStrategyPage
from software.ui.pages.workbench.session import WorkbenchState

_COMPAT_LOAD_SHOP_ICON = load_shop_icon

class DashboardPage(
    SurveyClipboardMixin,
    DashboardSurveyParseMixin,
    DashboardConfigIOMixin,
    DashboardRunActionsMixin,
    DashboardRandomIPMixin,
    DashboardEntriesMixin,
    DashboardProgressMixin,
    QWidget,
):
    """主页：左侧配置 + 底部状态，不再包含日志。"""

    thread_slider: Any

    _ipBalanceChecked = Signal(float)  # 发送剩余IP数信号
    _randomIpHeartbeatUpdated = Signal(object)  # 发送随机IP服务状态信号
    def __init__(
        self,
        controller: RunController,
        workbench_state: WorkbenchState,
        runtime_page: RuntimePage,
        strategy_page: QuestionStrategyPage,
        parent=None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.controller = controller
        self.workbench_state = workbench_state
        self.runtime_page = runtime_page
        self.strategy_page = strategy_page
        self.run_coordinator = None
        self.config_builder: Optional[Callable[[], RuntimeConfig]] = None
        self._open_wizard_after_parse = False
        self._survey_title = ""
        self._pending_restart = False
        self._entry_table_signatures = []
        init_run_feedback_state(self)
        self._ip_low_infobar: Optional[FullWidthInfoBar] = None
        self._ip_cost_infobar: Optional[FullWidthInfoBar] = None
        self._ip_benefit_infobar: Optional[FullWidthInfoBar] = None
        self._ip_low_infobar_dismissed = False
        self._ip_low_threshold = 5000
        self._api_balance_cache: Optional[float] = None  # 缓存 API 余额
        self._ip_balance_fetch_lock = threading.Lock()
        self._ip_balance_fetching = False
        self._last_ip_balance_fetch_ts = 0.0
        self._ip_balance_fetch_interval_sec = 30.0
        self._random_ip_status_fetch_lock = threading.Lock()
        self._random_ip_status_fetching = False
        self._is_closing = False
        self._clipboard_parse_ticket = 0
        self._init_progress_state()
        self._build_ui()
        self.config_drawer = ConfigDrawer(self, self._load_config_from_path)
        self._bind_events()
        if hasattr(self.controller, "get_runtime_snapshot"):
            runtime_snapshot = self.controller.get_runtime_snapshot()
            self._apply_runtime_ui_state(runtime_snapshot.get("settings") or {})
            self.set_random_ip_loading(
                bool(runtime_snapshot.get("random_ip", {}).get("loading")),
                str(runtime_snapshot.get("random_ip", {}).get("loading_message") or ""),
            )
        elif hasattr(self.controller, "get_runtime_ui_state"):
            self._apply_runtime_ui_state(self.controller.get_runtime_ui_state())
        self._sync_thread_slider_enabled()
        self._sync_start_button_state()
        self._refresh_ip_cost_infobar()
        self._init_random_ip_status_refresh()

    def set_run_coordinator(self, coordinator) -> None:
        self.run_coordinator = coordinator

    def _build_ui(self):
        build_dashboard_page_ui(self)

    def _bind_events(self):
        bind_dashboard_events(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            self.config_drawer.sync_to_parent()
        except Exception as exc:
            log_suppressed_exception(
                "resizeEvent: self.config_drawer.sync_to_parent()",
                exc,
                level=logging.WARNING,
            )

    def _has_question_entries(self) -> bool:
        try:
            return bool(self.workbench_state.has_question_entries())
        except Exception:
            return False

    def _sync_start_button_state(self, running: Optional[bool] = None):
        if running is None:
            running = bool(
                getattr(self.controller, "running", False)
                or getattr(self.controller, "_starting", False)
                or getattr(self.controller, "is_initializing", lambda: False)()
            )
        can_start = (not running) and self._has_question_entries()
        self.start_btn.setEnabled(bool(can_start))

    def _sync_thread_slider_enabled(self, running: Optional[bool] = None) -> None:
        if running is None:
            running = bool(
                getattr(self.controller, "running", False)
                or getattr(self.controller, "_starting", False)
                or getattr(self.controller, "is_initializing", lambda: False)()
            )
        self.thread_slider.setEnabled(not bool(running))

    def _on_question_entries_changed(self, _count: int):
        self.strategy_page.set_entries(
            self.workbench_state.entries,
            self.workbench_state.entry_questions_info,
        )
        self._refresh_entry_table()
        self._sync_start_button_state()

    def _on_strategy_page_changed(self):
        self._refresh_entry_table()

    def _toast(
        self,
        text: str,
        level: str = "info",
        duration: int = 2000,
        show_progress: bool = False,
    ):
        return dashboard_toast(
            self,
            text,
            level=level,
            duration=duration,
            show_progress=show_progress,
        )

    @staticmethod
    def _infobar_none_position():
        from qfluentwidgets import InfoBarPosition

        return InfoBarPosition.NONE

"""主控制面板：卡片式配置区 + 底部状态条（不包含日志）"""

import threading
from typing import Callable, Optional
import logging
from software.app.config import NON_HEADLESS_MAX_THREADS
from software.logging.action_logger import bind_logged_action
from software.logging.log_utils import log_suppressed_exception


from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSizePolicy,
    QStackedWidget,
)
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    BodyLabel,
    CardWidget,
    PushButton,
    TableWidget,
    ProgressRing,
    CommandBar,
    Action,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    InfoBarIcon,
    IndeterminateProgressRing,
    HyperlinkButton,
    SegmentedWidget,
)

from software.ui.pages.workbench.dashboard.cards import (
    RuntimeSettingsHintCard,
)
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
from software.ui.pages.workbench.shared.random_ip_toggle_row import (
    RandomIpToggleRow,
)
from software.ui.pages.workbench.shared.survey_entry_card import (
    SurveyEntryCard,
)
from software.ui.helpers.fluent_tooltip import install_tooltip_filter
from software.ui.helpers.message_bar import (
    replace_message_bar,
    reposition_message_bar,
    show_message_bar,
)
from software.ui.dialogs.quota_redeem import load_shop_icon
from software.ui.widgets.config_drawer import ConfigDrawer
from software.ui.widgets.clickable_card import ClickableElevatedCardWidget
from software.ui.widgets.full_width_infobar import FullWidthInfoBar
from software.ui.widgets.no_wheel import NoWheelSpinBox
from software.ui.widgets.value_slider import ValueSlider
from software.ui.controller.run_controller import RunController
from software.io.config import RuntimeConfig
from software.ui.pages.workbench.runtime_panel.main import RuntimePage
from software.ui.pages.workbench.strategy.page import QuestionStrategyPage
from software.ui.pages.workbench.session import WorkbenchState


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
        self._last_pause_reason = ""
        self._completion_notified = False
        self._pending_restart = False
        self._show_end_toast_after_cleanup = False
        self._last_progress = 0
        self._entry_table_signatures = []
        self._progress_infobar: Optional[InfoBar] = None  # 存储进度消息条的引用
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
        self._clipboard_parse_ticket = 0
        self._init_progress_state()
        self._build_ui()
        self.config_drawer = ConfigDrawer(self, self._load_config_from_path)
        self._bind_events()
        self._apply_runtime_ui_state(self.controller.get_runtime_ui_state())
        self._sync_thread_slider_enabled()
        self._sync_start_button_state()
        self._refresh_ip_cost_infobar()
        self._init_random_ip_status_refresh()

    def set_run_coordinator(self, coordinator) -> None:
        self.run_coordinator = coordinator

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(10)

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        inner = QWidget(self)
        scroll.setWidget(inner)
        scroll.enableTransparentBackground()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._ip_low_infobar = FullWidthInfoBar(
            icon=InfoBarIcon.WARNING,
            title="",
            content="随机IP已用额度接近上限，如需继续使用请及时补充额度",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.NONE,
            duration=-1,
            parent=inner,
        )
        self._ip_low_infobar.hide()
        self._ip_low_infobar.closeButton.clicked.connect(self._on_ip_low_infobar_closed)
        self._ip_low_contact_link = HyperlinkButton(
            FluentIcon.LINK, "", "前往兑换", self._ip_low_infobar
        )
        self._ip_low_contact_link.clicked.connect(
            lambda: self._open_quota_redeem_dialog()
        )
        self._ip_low_infobar.addWidget(self._ip_low_contact_link)
        layout.addWidget(self._ip_low_infobar)

        self.config_command_bar = CommandBar(self)
        self.config_command_bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.config_list_action = Action(FluentIcon.MENU, "配置列表", self.config_command_bar)
        self.load_cfg_action = Action(FluentIcon.DOCUMENT, "载入配置", self.config_command_bar)
        self.save_cfg_action = Action(FluentIcon.SAVE, "保存配置", self.config_command_bar)
        self.config_command_bar.addActions(
            [
                self.config_list_action,
                self.load_cfg_action,
                self.save_cfg_action,
            ]
        )
        self.config_command_bar.resizeToSuitableWidth()
        survey_entry = SurveyEntryCard(
            self,
            event_filter_owner=self,
            trailing_widget=self.config_command_bar,
            show_parse_button=True,
        )
        self.link_card = survey_entry
        self.qr_btn = survey_entry.qr_btn
        self.url_edit = survey_entry.url_edit
        if survey_entry.parse_btn is None:
            raise RuntimeError("SurveyEntryCard 缺少解析按钮，无法初始化主页入口")
        self.parse_btn = survey_entry.parse_btn
        layout.addWidget(self.link_card)

        self._link_entry_widgets = survey_entry.entry_widgets()

        exec_card = CardWidget(self)
        exec_layout = QVBoxLayout(exec_card)
        exec_layout.setContentsMargins(12, 12, 12, 12)
        exec_layout.setSpacing(6)

        # 头部标题与跳转按钮
        title_row = QHBoxLayout()
        title_row.addWidget(SubtitleLabel("快捷设置", self))
        title_row.addStretch(1)
        exec_layout.addLayout(title_row)

        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        left_column = QVBoxLayout()
        left_column.setContentsMargins(0, 0, 0, 0)
        left_column.setSpacing(8)

        spin_row = QHBoxLayout()
        spin_row.addWidget(BodyLabel("目标份数：", self))
        self.target_spin = NoWheelSpinBox(self)
        self.target_spin.setRange(1, 99999)
        self.target_spin.setMinimumWidth(140)
        self.target_spin.setMinimumHeight(36)
        spin_row.addWidget(self.target_spin)
        spin_row.addSpacing(12)
        spin_row.addWidget(BodyLabel("并发数：", self))
        self.thread_slider = ValueSlider(1, NON_HEADLESS_MAX_THREADS, 1, parent=self)
        self.thread_slider.setMinimumWidth(220)
        self.thread_spin = self.thread_slider
        spin_row.addWidget(self.thread_slider)
        spin_row.addStretch(1)
        left_column.addLayout(spin_row)

        self.random_ip_row = RandomIpToggleRow(BodyLabel, self)
        self.random_ip_cb = self.random_ip_row.toggle_button
        self.random_ip_loading_ring = self.random_ip_row.loading_ring
        self.random_ip_loading_label = self.random_ip_row.loading_label
        self.random_ip_loading_label.setStyleSheet("color: #606060; font-size: 12px;")
        left_column.addWidget(self.random_ip_row)
        quick_action_column = QVBoxLayout()
        quick_action_column.setContentsMargins(0, 0, 0, 0)
        quick_action_column.setSpacing(8)
        self.runtime_settings_hint_card = RuntimeSettingsHintCard(exec_card)
        quick_action_column.addWidget(self.runtime_settings_hint_card)
        left_column.addLayout(quick_action_column)
        content_row.addLayout(left_column, 1)
        content_row.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.random_ip_quota_card = ClickableElevatedCardWidget(exec_card)
        self.random_ip_quota_card.setMinimumWidth(248)
        quota_layout = QVBoxLayout(self.random_ip_quota_card)
        quota_layout.setContentsMargins(18, 14, 18, 14)
        quota_layout.setSpacing(8)
        quota_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        quota_title_label = BodyLabel("剩余随机IP额度", self.random_ip_quota_card)
        quota_layout.addWidget(quota_title_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self.random_ip_status_row = QWidget(self.random_ip_quota_card)
        random_ip_status_layout = QHBoxLayout(self.random_ip_status_row)
        random_ip_status_layout.setContentsMargins(0, 0, 0, 0)
        random_ip_status_layout.setSpacing(6)
        self.random_ip_status_spinner = IndeterminateProgressRing(
            self.random_ip_status_row,
            start=False,
        )
        self.random_ip_status_spinner.setFixedSize(14, 14)
        self.random_ip_status_spinner.setStrokeWidth(2)
        self.random_ip_status_spinner.hide()
        self.random_ip_status_dot = QWidget(self.random_ip_status_row)
        self.random_ip_status_dot.setFixedSize(10, 10)
        self.random_ip_status_label = BodyLabel("", self.random_ip_status_row)
        self.random_ip_status_label.setStyleSheet("color: #6b6b6b; font-size: 12px;")
        random_ip_status_layout.addWidget(
            self.random_ip_status_spinner, 0, Qt.AlignmentFlag.AlignVCenter
        )
        random_ip_status_layout.addWidget(
            self.random_ip_status_dot, 0, Qt.AlignmentFlag.AlignVCenter
        )
        random_ip_status_layout.addWidget(
            self.random_ip_status_label, 0, Qt.AlignmentFlag.AlignVCenter
        )
        quota_layout.addWidget(self.random_ip_status_row, 0, Qt.AlignmentFlag.AlignHCenter)

        self.random_ip_usage_ring = ProgressRing(self.random_ip_quota_card)
        self.random_ip_usage_ring.setRange(0, 100)
        self.random_ip_usage_ring.setValue(0)
        self.random_ip_usage_ring.setTextVisible(True)
        self.random_ip_usage_ring.setFormat("--")
        self.random_ip_usage_ring.setFixedSize(96, 96)
        self.random_ip_usage_ring.setStrokeWidth(8)
        quota_layout.addWidget(self.random_ip_usage_ring, 0, Qt.AlignmentFlag.AlignHCenter)

        self.card_btn = PushButton("额度兑换", self.random_ip_quota_card)
        shop_icon = load_shop_icon()
        if shop_icon is not None:
            self.card_btn.setIcon(shop_icon)
        install_tooltip_filter(self.card_btn)
        quota_layout.addWidget(self.card_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        self.random_ip_quota_card.set_ignored_click_widgets([self.card_btn])

        content_row.addWidget(self.random_ip_quota_card, 0, Qt.AlignmentFlag.AlignTop)
        exec_layout.addLayout(content_row)

        self._ip_cost_infobar = FullWidthInfoBar(
            icon=InfoBarIcon.WARNING,
            title="",
            content="",
            orient=Qt.Orientation.Horizontal,
            isClosable=False,
            position=InfoBarPosition.NONE,
            duration=-1,
            parent=exec_card,
        )
        self._ip_cost_adjust_link = HyperlinkButton(
            FluentIcon.LINK, "", "前往调整作答时长", self._ip_cost_infobar
        )
        self._ip_cost_adjust_link.clicked.connect(self._go_to_runtime_answer_duration)
        self._ip_cost_infobar.addWidget(self._ip_cost_adjust_link)
        self._ip_cost_infobar.hide()
        exec_layout.addWidget(self._ip_cost_infobar)

        self._ip_benefit_infobar = FullWidthInfoBar(
            icon=InfoBarIcon.SUCCESS,
            title="",
            content=(
                "该代理源按 0.5 倍率缓慢扣费。仅支持少部分城市。"
            ),
            orient=Qt.Orientation.Horizontal,
            isClosable=False,
            position=InfoBarPosition.NONE,
            duration=-1,
            parent=exec_card,
        )
        self._ip_benefit_infobar.hide()
        exec_layout.addWidget(self._ip_benefit_infobar)
        layout.addWidget(exec_card)

        switch_row = QHBoxLayout()
        switch_row.setContentsMargins(0, 0, 0, 0)
        switch_row.setSpacing(8)
        self.thread_view_seg = SegmentedWidget(self)
        self.thread_view_seg.addItem(routeKey=self.THREAD_VIEW_QUESTION_LIST, text="题目清单")
        self.thread_view_seg.addItem(routeKey=self.THREAD_VIEW_PROGRESS, text="会话进度")
        self.thread_view_seg.setCurrentItem(self.THREAD_VIEW_QUESTION_LIST)
        switch_row.addWidget(self.thread_view_seg)
        switch_row.addStretch(1)
        layout.addLayout(switch_row)

        self.thread_view_stack = QStackedWidget(self)

        self.thread_view_question_card = CardWidget(self.thread_view_stack)
        question_list_layout = QVBoxLayout(self.thread_view_question_card)
        question_list_layout.setContentsMargins(12, 12, 12, 12)
        question_list_layout.setSpacing(8)

        question_title_row = QHBoxLayout()
        question_title_row.setSpacing(8)
        self.title_label = SubtitleLabel("题目清单与操作", self.thread_view_question_card)
        self.title_label.setWordWrap(True)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.count_label = BodyLabel("0 题", self.thread_view_question_card)
        self.count_label.setStyleSheet("color: #6b6b6b;")
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        question_title_row.addWidget(self.title_label, 1)
        question_title_row.addWidget(self.count_label, 0, Qt.AlignmentFlag.AlignTop)
        question_list_layout.addLayout(question_title_row)

        # 使用 CommandBar 替代普通按钮布局
        self.command_bar = CommandBar(self.thread_view_question_card)
        self.command_bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        # 新增题目
        self.add_action = Action(FluentIcon.ADD, "新增题目")
        self.command_bar.addAction(self.add_action)

        # 编辑选中
        self.edit_action = Action(FluentIcon.EDIT, "编辑选中")
        self.command_bar.addAction(self.edit_action)

        # 删除选中
        self.del_action = Action(FluentIcon.DELETE, "删除选中")
        self.command_bar.addAction(self.del_action)

        # 清空全部
        self.clear_all_action = Action(FluentIcon.BROOM, "清空所有已配置题目")
        self.command_bar.addAction(self.clear_all_action)

        question_list_layout.addWidget(self.command_bar)
        self.entry_table = TableWidget(self.thread_view_question_card)
        self.entry_table.setRowCount(0)
        self.entry_table.setColumnCount(4)
        self.entry_table.setHorizontalHeaderLabels(["序号", "类型", "维度", "策略"])
        self.entry_table.verticalHeader().setVisible(False)
        self.entry_table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.entry_table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.entry_table.setAlternatingRowColors(True)
        self.entry_table.setMinimumHeight(360)
        # 设置列宽策略：序号、类型、维度固定，策略列自动拉伸。
        header = self.entry_table.horizontalHeader()
        header.setSectionResizeMode(0, header.ResizeMode.Fixed)
        header.setSectionResizeMode(1, header.ResizeMode.Fixed)
        header.setSectionResizeMode(2, header.ResizeMode.Fixed)
        header.setSectionResizeMode(3, header.ResizeMode.Stretch)
        self.entry_table.setColumnWidth(0, 60)
        self.entry_table.setColumnWidth(1, 140)
        self.entry_table.setColumnWidth(2, 140)
        question_list_layout.addWidget(self.entry_table, 1)

        self.thread_view_progress_card = CardWidget(self.thread_view_stack)
        progress_card_layout = QVBoxLayout(self.thread_view_progress_card)
        progress_card_layout.setContentsMargins(12, 12, 12, 12)
        progress_card_layout.setSpacing(8)
        progress_title_row = QHBoxLayout()
        progress_title_row.setSpacing(8)
        progress_title_row.addWidget(SubtitleLabel("会话进度", self.thread_view_progress_card))
        progress_title_row.addStretch(1)
        progress_card_layout.addLayout(progress_title_row)
        thread_progress_page = self._build_thread_progress_panel(self.thread_view_progress_card)
        progress_card_layout.addWidget(thread_progress_page, 1)

        self.thread_view_stack.addWidget(self.thread_view_question_card)
        self.thread_view_stack.addWidget(self.thread_view_progress_card)
        self._set_thread_view(self.THREAD_VIEW_QUESTION_LIST, animate=False)
        layout.addWidget(self.thread_view_stack, 1)

        layout.addStretch(1)
        outer.addWidget(scroll, 1)
        self._build_bottom_status_card(outer)

    def _bind_events(self):
        bind_logged_action(
            self.parse_btn.clicked,
            self._on_parse_clicked,
            scope="UI",
            event="parse_survey",
            target="parse_btn",
            page="dashboard",
            forward_signal_args=False,
        )
        bind_logged_action(
            self.config_list_action.triggered,
            self._on_show_config_list,
            scope="UI",
            event="open_config_list",
            target="config_list_btn",
            page="dashboard",
            forward_signal_args=False,
        )
        bind_logged_action(
            self.load_cfg_action.triggered,
            self._on_load_config,
            scope="CONFIG",
            event="load_config",
            target="load_cfg_btn",
            page="dashboard",
            forward_signal_args=False,
        )
        bind_logged_action(
            self.save_cfg_action.triggered,
            self._on_save_config,
            scope="CONFIG",
            event="save_config",
            target="save_cfg_btn",
            page="dashboard",
            forward_signal_args=False,
        )
        bind_logged_action(
            self.qr_btn.clicked,
            self._on_qr_clicked,
            scope="UI",
            event="parse_qr_image",
            target="qr_btn",
            page="dashboard",
            forward_signal_args=False,
        )
        self._bind_progress_events()
        self.thread_view_seg.currentItemChanged.connect(self._on_thread_view_changed)
        self.target_spin.valueChanged.connect(
            lambda v: self.controller.set_runtime_ui_state(target=int(v))
        )
        self.thread_spin.valueChanged.connect(
            lambda v: self.controller.set_runtime_ui_state(threads=int(v))
        )
        self.random_ip_cb.toggled.connect(self._on_random_ip_toggled)
        bind_logged_action(
            self.card_btn.clicked,
            self._on_request_quota_clicked,
            scope="UI",
            event="open_quota_request",
            target="card_btn",
            page="dashboard",
            forward_signal_args=False,
        )
        self.random_ip_quota_card.backgroundClicked.connect(self.refresh_random_ip_heartbeat_async)
        bind_logged_action(
            self.runtime_settings_hint_card.openRequested,
            self._go_to_runtime_page,
            scope="NAV",
            event="open_runtime_settings",
            target="runtime_settings_hint_card",
            page="dashboard",
            forward_signal_args=False,
        )
        self.controller.runtimeUiStateChanged.connect(self._apply_runtime_ui_state)
        self.controller.randomIpLoadingChanged.connect(self.set_random_ip_loading)
        # 监听剪贴板变化，自动处理粘贴的图片
        from PySide6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        clipboard.dataChanged.connect(self._on_clipboard_changed)
        # CommandBar Actions
        self.add_action.triggered.connect(self._show_add_question_dialog)
        self.edit_action.triggered.connect(self._edit_selected_entries)
        self.del_action.triggered.connect(self._delete_selected_entries)
        self.clear_all_action.triggered.connect(self._clear_all_entries)
        # 连接问卷解析信号
        self.controller.surveyParsed.connect(self._on_survey_parsed)
        self.controller.surveyParseFailed.connect(self._on_survey_parse_failed)
        # 连接 IP 余额检查信号
        self._ipBalanceChecked.connect(self._on_ip_balance_checked)
        try:
            self.workbench_state.entriesChanged.connect(self._on_question_entries_changed)
        except Exception as exc:
            context = (
                "_bind_events: self.workbench_state.entriesChanged.connect("
                "self._on_question_entries_changed)"
            )
            log_suppressed_exception(
                context,
                exc,
                level=logging.WARNING,
            )
        try:
            self.strategy_page.strategyChanged.connect(self._on_strategy_page_changed)
        except Exception as exc:
            context = (
                "_bind_events: self.strategy_page.strategyChanged.connect("
                "self._on_strategy_page_changed)"
            )
            log_suppressed_exception(
                context,
                exc,
                level=logging.WARNING,
            )
        self._randomIpHeartbeatUpdated.connect(self._apply_random_ip_heartbeat_status)

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
        """显示消息提示"""
        try:
            replace_message_bar(self._progress_infobar)
        except Exception as exc:
            log_suppressed_exception(
                "_toast: replace_message_bar(self._progress_infobar)",
                exc,
                level=logging.WARNING,
            )
        self._progress_infobar = None

        parent = self.window() or self
        kind = level.lower()
        position = InfoBarPosition.TOP

        if show_progress:
            infobar = show_message_bar(
                parent=parent,
                message=text,
                level=kind,
                position=position,
                duration=duration,
            )
            spinner = IndeterminateProgressRing()
            spinner.setFixedSize(20, 20)
            spinner.setStrokeWidth(3)
            infobar.addWidget(spinner)
            reposition_message_bar(infobar)
            self._progress_infobar = infobar
            return infobar

        # 普通InfoBar（不带进度条）
        if kind == "success":
            InfoBar.success(
                "",
                text,
                parent=parent,
                position=position,
                duration=duration,
            )
        elif kind == "warning":
            InfoBar.warning(
                "",
                text,
                parent=parent,
                position=position,
                duration=duration,
            )
        elif kind == "error":
            InfoBar.error(
                "",
                text,
                parent=parent,
                position=position,
                duration=duration,
            )
        else:
            InfoBar.info(
                "",
                text,
                parent=parent,
                position=position,
                duration=duration,
            )
        return None

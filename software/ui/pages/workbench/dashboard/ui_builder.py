"""Dashboard 页面 UI 构建。"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget, QSizePolicy
from qfluentwidgets import (
    Action,
    BodyLabel,
    CardWidget,
    CommandBar,
    ComboBox,
    FluentIcon,
    HyperlinkButton,
    IndeterminateProgressRing,
    InfoBarIcon,
    LineEdit,
    ProgressRing,
    PopUpAniStackedWidget,
    PushButton,
    ScrollArea,
    SegmentedWidget,
    SubtitleLabel,
    TableWidget,
)

from software.app.config import NON_HEADLESS_MAX_THREADS
from software.ui.dialogs.quota_redeem import load_shop_icon
from software.ui.helpers.fluent_tooltip import install_tooltip_filter
from software.ui.pages.workbench.dashboard.cards import RuntimeSettingsHintCard
from software.ui.pages.workbench.shared.random_ip_toggle_row import RandomIpToggleRow
from software.ui.pages.workbench.shared.survey_entry_card import SurveyEntryCard
from software.ui.widgets.clickable_card import ClickableElevatedCardWidget
from software.ui.widgets.full_width_infobar import FullWidthInfoBar
from software.ui.widgets.no_wheel import NoWheelSpinBox
from software.ui.widgets.value_slider import ValueSlider


def build_dashboard_page_ui(page: Any) -> None:
    outer = QVBoxLayout(page)
    outer.setContentsMargins(12, 10, 12, 10)
    outer.setSpacing(10)

    scroll = ScrollArea(page)
    scroll.setWidgetResizable(True)
    inner = QWidget(page)
    scroll.setWidget(inner)
    scroll.enableTransparentBackground()
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)

    page._ip_low_infobar = FullWidthInfoBar(
        icon=InfoBarIcon.WARNING,
        title="",
        content="随机IP已用额度接近上限，如需继续使用请及时补充额度",
        orient=Qt.Orientation.Horizontal,
        isClosable=True,
        position=page._infobar_none_position(),
        duration=-1,
        parent=inner,
    )
    page._ip_low_infobar.hide()
    page._ip_low_infobar.closeButton.clicked.connect(page._on_ip_low_infobar_closed)
    page._ip_low_contact_link = HyperlinkButton(
        FluentIcon.LINK, "", "前往兑换", page._ip_low_infobar
    )
    page._ip_low_contact_link.clicked.connect(lambda: page._open_quota_redeem_dialog())
    page._ip_low_infobar.addWidget(page._ip_low_contact_link)
    layout.addWidget(page._ip_low_infobar)

    page.config_command_bar = CommandBar(page)
    page.config_command_bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    page.config_list_action = Action(FluentIcon.MENU, "配置列表", page.config_command_bar)
    page.load_cfg_action = Action(FluentIcon.DOCUMENT, "载入配置", page.config_command_bar)
    page.save_cfg_action = Action(FluentIcon.SAVE, "保存配置", page.config_command_bar)
    page.config_command_bar.addActions(
        [page.config_list_action, page.load_cfg_action, page.save_cfg_action]
    )
    page.config_command_bar.resizeToSuitableWidth()
    survey_entry = SurveyEntryCard(
        page,
        event_filter_owner=page,
        trailing_widget=page.config_command_bar,
        show_parse_button=True,
    )
    page.link_card = survey_entry
    page.qr_btn = survey_entry.qr_btn
    page.url_edit = survey_entry.url_edit
    if survey_entry.parse_btn is None:
        raise RuntimeError("SurveyEntryCard 缺少解析按钮，无法初始化主页入口")
    page.parse_btn = survey_entry.parse_btn
    layout.addWidget(page.link_card)
    page._link_entry_widgets = survey_entry.entry_widgets()

    exec_card = CardWidget(page)
    exec_layout = QVBoxLayout(exec_card)
    exec_layout.setContentsMargins(12, 12, 12, 12)
    exec_layout.setSpacing(6)

    title_row = QHBoxLayout()
    title_row.addWidget(SubtitleLabel("快捷设置", page))
    title_row.addStretch(1)
    exec_layout.addLayout(title_row)

    content_row = QHBoxLayout()
    content_row.setSpacing(16)

    left_column = QVBoxLayout()
    left_column.setContentsMargins(0, 0, 0, 0)
    left_column.setSpacing(8)

    spin_row = QHBoxLayout()
    spin_row.addWidget(BodyLabel("目标份数：", page))
    page.target_spin = NoWheelSpinBox(page)
    page.target_spin.setRange(1, 99999)
    page.target_spin.setMinimumWidth(140)
    page.target_spin.setMinimumHeight(36)
    spin_row.addWidget(page.target_spin)
    spin_row.addSpacing(12)
    spin_row.addWidget(BodyLabel("并发数：", page))
    page.thread_slider = ValueSlider(1, NON_HEADLESS_MAX_THREADS, 1, parent=page)
    page.thread_slider.setMinimumWidth(220)
    page.thread_spin = page.thread_slider
    spin_row.addWidget(page.thread_slider)
    spin_row.addStretch(1)
    left_column.addLayout(spin_row)

    page.random_ip_row = RandomIpToggleRow(BodyLabel, page)
    page.random_ip_cb = page.random_ip_row.toggle_button
    page.random_ip_loading_ring = page.random_ip_row.loading_ring
    page.random_ip_loading_label = page.random_ip_row.loading_label
    page.random_ip_loading_label.setStyleSheet("color: #606060; font-size: 12px;")
    left_column.addWidget(page.random_ip_row)

    proxy_source_row = QHBoxLayout()
    proxy_source_row.addWidget(BodyLabel("代理源：", page))
    page.proxy_source_combo = ComboBox(page)
    page.proxy_source_combo.addItem("默认", userData="default")
    page.proxy_source_combo.addItem("限时福利", userData="benefit")
    page.proxy_source_combo.addItem("自定义", userData="custom")
    page.proxy_source_combo.setMinimumWidth(140)
    proxy_source_row.addWidget(page.proxy_source_combo)
    page.custom_proxy_api_edit = LineEdit(page)
    page.custom_proxy_api_edit.setPlaceholderText("请输入代理api地址")
    page.custom_proxy_api_edit.setMinimumWidth(260)
    page.custom_proxy_api_edit.hide()
    proxy_source_row.addWidget(page.custom_proxy_api_edit, 1)
    page.custom_proxy_trial_link = HyperlinkButton(
        FluentIcon.LINK,
        "https://surveydoc.hungrym0.top/random.html#%E8%87%AA%E5%AE%9A%E4%B9%89%E4%BB%A3%E7%90%86%E6%BA%90",
        "使用教程",
        page,
    )
    page.custom_proxy_trial_link.hide()
    proxy_source_row.addWidget(page.custom_proxy_trial_link)
    proxy_source_row.addStretch(1)
    left_column.addLayout(proxy_source_row)
    quick_action_column = QVBoxLayout()
    quick_action_column.setContentsMargins(0, 0, 0, 0)
    quick_action_column.setSpacing(8)
    page.runtime_settings_hint_card = RuntimeSettingsHintCard(exec_card)
    quick_action_column.addWidget(page.runtime_settings_hint_card)
    left_column.addLayout(quick_action_column)
    content_row.addLayout(left_column, 1)
    content_row.setAlignment(Qt.AlignmentFlag.AlignTop)

    page.random_ip_quota_card = ClickableElevatedCardWidget(exec_card)
    page.random_ip_quota_card.setMinimumWidth(248)
    quota_layout = QVBoxLayout(page.random_ip_quota_card)
    quota_layout.setContentsMargins(18, 14, 18, 14)
    quota_layout.setSpacing(8)
    quota_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    quota_layout.addWidget(
        BodyLabel("剩余随机IP额度", page.random_ip_quota_card),
        0,
        Qt.AlignmentFlag.AlignHCenter,
    )

    page.random_ip_status_row = QWidget(page.random_ip_quota_card)
    random_ip_status_layout = QHBoxLayout(page.random_ip_status_row)
    random_ip_status_layout.setContentsMargins(0, 0, 0, 0)
    random_ip_status_layout.setSpacing(6)
    page.random_ip_status_spinner = IndeterminateProgressRing(
        page.random_ip_status_row,
        start=False,
    )
    page.random_ip_status_spinner.setFixedSize(14, 14)
    page.random_ip_status_spinner.setStrokeWidth(2)
    page.random_ip_status_spinner.hide()
    page.random_ip_status_dot = QWidget(page.random_ip_status_row)
    page.random_ip_status_dot.setFixedSize(10, 10)
    page.random_ip_status_label = BodyLabel("", page.random_ip_status_row)
    page.random_ip_status_label.setStyleSheet("color: #6b6b6b; font-size: 12px;")
    random_ip_status_layout.addWidget(page.random_ip_status_spinner, 0, Qt.AlignmentFlag.AlignVCenter)
    random_ip_status_layout.addWidget(page.random_ip_status_dot, 0, Qt.AlignmentFlag.AlignVCenter)
    random_ip_status_layout.addWidget(page.random_ip_status_label, 0, Qt.AlignmentFlag.AlignVCenter)
    quota_layout.addWidget(page.random_ip_status_row, 0, Qt.AlignmentFlag.AlignHCenter)

    page.random_ip_usage_ring = ProgressRing(page.random_ip_quota_card)
    page.random_ip_usage_ring.setRange(0, 100)
    page.random_ip_usage_ring.setValue(0)
    page.random_ip_usage_ring.setTextVisible(True)
    page.random_ip_usage_ring.setFormat("--")
    page.random_ip_usage_ring.setFixedSize(96, 96)
    page.random_ip_usage_ring.setStrokeWidth(8)
    quota_layout.addWidget(page.random_ip_usage_ring, 0, Qt.AlignmentFlag.AlignHCenter)

    page.card_btn = PushButton("额度兑换", page.random_ip_quota_card)
    shop_icon = load_shop_icon()
    if shop_icon is not None:
        page.card_btn.setIcon(shop_icon)
    install_tooltip_filter(page.card_btn)
    quota_layout.addWidget(page.card_btn, 0, Qt.AlignmentFlag.AlignHCenter)
    page.random_ip_quota_card.set_ignored_click_widgets([page.card_btn])
    content_row.addWidget(page.random_ip_quota_card, 0, Qt.AlignmentFlag.AlignTop)
    exec_layout.addLayout(content_row)

    page._ip_cost_infobar = FullWidthInfoBar(
        icon=InfoBarIcon.WARNING,
        title="",
        content="",
        orient=Qt.Orientation.Horizontal,
        isClosable=False,
        position=page._infobar_none_position(),
        duration=-1,
        parent=exec_card,
    )
    page._ip_cost_adjust_link = HyperlinkButton(
        FluentIcon.LINK, "", "前往调整作答时长", page._ip_cost_infobar
    )
    page._ip_cost_adjust_link.clicked.connect(page._go_to_runtime_answer_duration)
    page._ip_cost_infobar.addWidget(page._ip_cost_adjust_link)
    page._ip_cost_infobar.hide()
    exec_layout.addWidget(page._ip_cost_infobar)

    page._ip_benefit_infobar = FullWidthInfoBar(
        icon=InfoBarIcon.SUCCESS,
        title="",
        content="该代理源按 0.5 倍率缓慢扣费。仅支持少部分城市。",
        orient=Qt.Orientation.Horizontal,
        isClosable=False,
        position=page._infobar_none_position(),
        duration=-1,
        parent=exec_card,
    )
    page._ip_benefit_infobar.hide()
    exec_layout.addWidget(page._ip_benefit_infobar)
    layout.addWidget(exec_card)

    switch_row = QHBoxLayout()
    switch_row.setContentsMargins(0, 0, 0, 0)
    switch_row.setSpacing(8)
    page.thread_view_seg = SegmentedWidget(page)
    page.thread_view_seg.addItem(routeKey=page.THREAD_VIEW_QUESTION_LIST, text="题目清单")
    page.thread_view_seg.addItem(routeKey=page.THREAD_VIEW_PROGRESS, text="会话进度")
    page.thread_view_seg.setCurrentItem(page.THREAD_VIEW_QUESTION_LIST)
    switch_row.addWidget(page.thread_view_seg)
    switch_row.addStretch(1)
    layout.addLayout(switch_row)

    page.thread_view_stack = PopUpAniStackedWidget(page)

    page.thread_view_question_card = CardWidget(page.thread_view_stack)
    question_list_layout = QVBoxLayout(page.thread_view_question_card)
    question_list_layout.setContentsMargins(12, 12, 12, 12)
    question_list_layout.setSpacing(8)

    question_title_row = QHBoxLayout()
    question_title_row.setSpacing(8)
    page.title_label = SubtitleLabel("题目清单与操作", page.thread_view_question_card)
    page.title_label.setWordWrap(True)
    page.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    page.count_label = BodyLabel("0 题", page.thread_view_question_card)
    page.count_label.setStyleSheet("color: #6b6b6b;")
    page.count_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
    question_title_row.addWidget(page.title_label, 1)
    question_title_row.addWidget(page.count_label, 0, Qt.AlignmentFlag.AlignTop)
    question_list_layout.addLayout(question_title_row)

    page.command_bar = CommandBar(page.thread_view_question_card)
    page.command_bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    page.add_action = Action(FluentIcon.ADD, "新增题目")
    page.edit_action = Action(FluentIcon.EDIT, "编辑选中")
    page.del_action = Action(FluentIcon.DELETE, "删除选中")
    page.clear_all_action = Action(FluentIcon.BROOM, "清空所有已配置题目")
    page.command_bar.addAction(page.add_action)
    page.command_bar.addAction(page.edit_action)
    page.command_bar.addAction(page.del_action)
    page.command_bar.addAction(page.clear_all_action)
    question_list_layout.addWidget(page.command_bar)

    page.entry_table = TableWidget(page.thread_view_question_card)
    page.entry_table.setRowCount(0)
    page.entry_table.setColumnCount(4)
    page.entry_table.setHorizontalHeaderLabels(["序号", "类型", "维度", "策略"])
    page.entry_table.verticalHeader().setVisible(False)
    page.entry_table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
    page.entry_table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
    page.entry_table.setAlternatingRowColors(True)
    page.entry_table.setMinimumHeight(360)
    header = page.entry_table.horizontalHeader()
    header.setSectionResizeMode(0, header.ResizeMode.Fixed)
    header.setSectionResizeMode(1, header.ResizeMode.Fixed)
    header.setSectionResizeMode(2, header.ResizeMode.Fixed)
    header.setSectionResizeMode(3, header.ResizeMode.Stretch)
    page.entry_table.setColumnWidth(0, 60)
    page.entry_table.setColumnWidth(1, 140)
    page.entry_table.setColumnWidth(2, 140)
    question_list_layout.addWidget(page.entry_table, 1)

    page.thread_view_progress_card = CardWidget(page.thread_view_stack)
    progress_card_layout = QVBoxLayout(page.thread_view_progress_card)
    progress_card_layout.setContentsMargins(12, 12, 12, 12)
    progress_card_layout.setSpacing(8)
    progress_title_row = QHBoxLayout()
    progress_title_row.setSpacing(8)
    progress_title_row.addWidget(SubtitleLabel("会话进度", page.thread_view_progress_card))
    progress_title_row.addStretch(1)
    progress_card_layout.addLayout(progress_title_row)
    progress_card_layout.addWidget(page._build_thread_progress_panel(page.thread_view_progress_card), 1)

    page.thread_view_stack.addWidget(page.thread_view_question_card)
    page.thread_view_stack.addWidget(page.thread_view_progress_card)
    page._set_thread_view(page.THREAD_VIEW_QUESTION_LIST, animate=False)
    layout.addWidget(page.thread_view_stack, 1)

    layout.addStretch(1)
    outer.addWidget(scroll, 1)
    page._build_bottom_status_card(outer)

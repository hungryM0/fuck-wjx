"""运行参数页 UI 组装。"""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout
from qfluentwidgets import FluentIcon, SettingCardGroup

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


def build_runtime_page_ui(page) -> None:
    """把运行参数页的布局一次性装好。"""
    layout = QVBoxLayout(page.view)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.setSpacing(20)

    feature_group = SettingCardGroup("特性开关", page.view)
    page.random_ip_card = RandomIPSettingCard(parent=feature_group)
    page.random_ua_card = RandomUASettingCard(parent=feature_group)
    feature_group.addSettingCard(page.random_ip_card)
    feature_group.addSettingCard(page.random_ua_card)
    layout.addWidget(feature_group)

    run_group = SettingCardGroup("作答设置", page.view)
    page.target_card = SpinBoxSettingCard(
        FluentIcon.DOCUMENT,
        "目标份数",
        "设置要提交的问卷数量",
        min_val=1,
        max_val=9999,
        default=10,
        parent=run_group,
    )
    page.thread_card = SliderSettingCard(
        FluentIcon.APPLICATION,
        "并发会话",
        "控制同时运行的独立 HTTP 会话数量",
        min_val=page.MIN_THREADS,
        max_val=page.HTTP_MAX_THREADS,
        default=2,
        parent=run_group,
    )
    page.target_card.setSpinBoxWidth(page.target_card.suggestSpinBoxWidthForDigits(4))
    page.reliability_card = ReliabilitySettingCard(parent=run_group)
    page.reliability_card.setChecked(True)
    page.reliability_card.set_alpha(0.85)
    for card in (
        page.target_card,
        page.thread_card,
        page.reliability_card,
    ):
        run_group.addSettingCard(card)
    layout.addWidget(run_group)

    time_group = SettingCardGroup("时间控制", page.view)
    page.interval_card = TimeRangeSettingCard(
        FluentIcon.HISTORY,
        "提交间隔",
        f"两次提交之间的等待时间范围（0-{page.SUBMIT_INTERVAL_MAX_SECONDS} 秒）",
        max_seconds=page.SUBMIT_INTERVAL_MAX_SECONDS,
        parent=time_group,
    )
    page.answer_card = TimeRangeSettingCard(
        FluentIcon.STOP_WATCH,
        "作答时长",
        "设置单份作答耗时范围，默认 1-2 分钟，最长 30 分钟",
        max_seconds=30 * 60,
        parent=time_group,
    )
    for card in (page.interval_card, page.answer_card):
        time_group.addSettingCard(card)
    layout.addWidget(time_group)

    page.ai_section = RuntimeAISection(page.view, page)
    page.ai_section.bind_to_layout(layout)
    layout.addStretch(1)

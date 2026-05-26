"""反填页 UI 组装。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    IconWidget,
    InfoBadge,
    IndeterminateProgressBar,
    LineEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    ScrollArea,
    SimpleCardWidget,
    StrongBodyLabel,
    SubtitleLabel,
    TableWidget,
)

from software.app.config import HEADLESS_MAX_THREADS
from software.ui.helpers.fluent_tooltip import install_tooltip_filter
from software.ui.pages.workbench.shared.random_ip_toggle_row import RandomIpToggleRow
from software.ui.pages.workbench.shared.survey_entry_card import SurveyEntryCard
from software.ui.widgets.no_wheel import NoWheelSpinBox


def build_reverse_fill_page_ui(page) -> None:
    page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    outer = QVBoxLayout(page)
    outer.setContentsMargins(12, 10, 12, 10)
    outer.setSpacing(10)

    page.scroll_area = ScrollArea(page)
    page.scroll_area.setWidgetResizable(True)
    page.scroll_area.enableTransparentBackground()
    page.scroll_area.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    page.view = QWidget(page.scroll_area)
    page.view.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    page.view.setStyleSheet("background: transparent;")
    page.scroll_area.setWidget(page.view)
    viewport = page.scroll_area.viewport()
    if viewport is not None:
        viewport.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        viewport.setStyleSheet("background: transparent;")

    layout = QVBoxLayout(page.view)
    layout.setContentsMargins(32, 32, 32, 32)
    layout.setSpacing(24)

    _build_title_area(page, layout)
    _build_survey_entry_card(page, layout)
    _build_file_picker(page, layout)
    _build_details_tables(page, layout)
    layout.addStretch(1)
    outer.addWidget(page.scroll_area, 1)
    _build_bottom_status_card(page, outer)


def _build_title_area(page, layout: QVBoxLayout) -> None:
    title_row = QWidget(page.view)
    title_row_layout = QHBoxLayout(title_row)
    title_row_layout.setContentsMargins(0, 0, 0, 0)
    title_row_layout.setSpacing(10)

    title_row_layout.addWidget(SubtitleLabel("Excel 反填", title_row))
    page.preview_badge = InfoBadge.custom(
        "预览",
        QColor("#fbbf24"),
        QColor("#f59e0b"),
        parent=title_row,
    )
    title_row_layout.addWidget(page.preview_badge)
    title_row_layout.addStretch(1)
    layout.addWidget(title_row)
    layout.addSpacing(4)


def _build_survey_entry_card(page, layout: QVBoxLayout) -> None:
    page.parse_btn = PrimaryPushButton(FluentIcon.PLAY, "解析", page.view)
    page.parse_btn.setToolTip("仅解析问卷结构，不打开配置向导")
    install_tooltip_filter(page.parse_btn)
    survey_entry = SurveyEntryCard(
        page.view,
        event_filter_owner=page,
        trailing_widget=page.parse_btn,
        show_parse_button=False,
    )
    page.link_card = survey_entry
    page.qr_btn = survey_entry.qr_btn
    page.url_edit = survey_entry.url_edit
    page._link_entry_widgets = survey_entry.entry_widgets()
    layout.addWidget(page.link_card)


def _build_file_picker(page, layout: QVBoxLayout) -> None:
    page.file_panel = SimpleCardWidget(page.view)
    page.file_panel.setAcceptDrops(True)
    file_layout = QVBoxLayout(page.file_panel)
    file_layout.setContentsMargins(20, 18, 20, 20)
    file_layout.setSpacing(14)

    header_row = QHBoxLayout()
    header_icon = IconWidget(FluentIcon.DOCUMENT, page.file_panel)
    header_icon.setFixedSize(20, 20)
    header_row.addWidget(header_icon)
    header_row.addWidget(StrongBodyLabel("Excel 数据源指定", page.file_panel))
    header_row.addStretch(1)
    file_layout.addLayout(header_row)

    desc_label = CaptionLabel("在此处导入/拖入用于反填的 .xlsx 文件。", page.file_panel)
    desc_label.setContentsMargins(0, 0, 0, 4)
    file_layout.addWidget(desc_label)

    input_row = QHBoxLayout()
    input_row.setSpacing(12)
    page.file_edit = LineEdit(page.file_panel)
    page.file_edit.setPlaceholderText("assets/reverse_fill_example.xlsx")
    page.file_edit.setReadOnly(True)
    page.file_edit.setClearButtonEnabled(False)
    page.browse_btn = PushButton(FluentIcon.FOLDER_ADD, "选择文件", page.file_panel)
    input_row.addWidget(page.file_edit, 1)
    input_row.addWidget(page.browse_btn)
    file_layout.addLayout(input_row)

    info_row = QHBoxLayout()
    info_row.setSpacing(24)
    page.detected_format_label = BodyLabel("检测结果：等待校验事件", page.file_panel)
    page.state_hint_label = CaptionLabel("暂无有效数据装载", page.file_panel)
    info_row.addWidget(page.detected_format_label)
    info_row.addWidget(page.state_hint_label)
    info_row.addStretch(1)
    file_layout.addLayout(info_row)

    concurrency_row = QHBoxLayout()
    concurrency_row.setSpacing(12)
    page.reverse_fill_threads_spin = NoWheelSpinBox(page.file_panel)
    page.reverse_fill_threads_spin.setRange(1, HEADLESS_MAX_THREADS)
    page.reverse_fill_threads_spin.setValue(page._reverse_fill_threads_value)
    page.reverse_fill_threads_spin.setFixedWidth(160)
    page.reverse_fill_threads_spin.setFixedHeight(36)
    page.random_ip_row = RandomIpToggleRow(
        CaptionLabel,
        page.file_panel,
        leading_label_text="反填并发数",
        stretch_tail=False,
    )
    page.random_ip_cb = page.random_ip_row.toggle_button
    page.random_ip_loading_ring = page.random_ip_row.loading_ring
    page.random_ip_loading_label = page.random_ip_row.loading_label
    if page.random_ip_row.leading_label is not None:
        page.random_ip_row.leading_label.setParent(page.file_panel)
        concurrency_row.addWidget(page.random_ip_row.leading_label)
    concurrency_row.addWidget(page.reverse_fill_threads_spin)
    concurrency_row.addStretch(1)
    concurrency_row.addWidget(page.random_ip_row)
    file_layout.addLayout(concurrency_row)

    page._file_drop_widgets = (
        page.file_panel,
        header_icon,
        desc_label,
        page.file_edit,
    )
    for widget in page._file_drop_widgets:
        try:
            widget.setAcceptDrops(True)
        except Exception:
            pass
        widget.installEventFilter(page)

    layout.addWidget(page.file_panel)


def _build_details_tables(page, layout: QVBoxLayout) -> None:
    page.table_panel = SimpleCardWidget(page.view)
    table_layout = QVBoxLayout(page.table_panel)
    table_layout.setContentsMargins(0, 0, 0, 0)
    table_layout.setSpacing(0)

    header_widget = QWidget(page.table_panel)
    header_layout = QHBoxLayout(header_widget)
    header_layout.setContentsMargins(24, 16, 24, 12)
    header_layout.addStretch(1)
    page.open_wizard_btn = PrimaryPushButton(FluentIcon.EDIT, "处理异常题目", header_widget)
    page.open_wizard_btn.hide()
    header_layout.addWidget(page.open_wizard_btn)
    table_layout.addWidget(header_widget)

    table_wrapper = QWidget(page.table_panel)
    table_vbox = QVBoxLayout(table_wrapper)
    table_vbox.setContentsMargins(24, 0, 24, 24)

    page.mapping_table = TableWidget(table_wrapper)
    page.mapping_table.setColumnCount(6)
    page.mapping_table.setHorizontalHeaderLabels(
        ["题号", "题型", "状态", "关联列", "异常说明", "处理建议"]
    )
    page.mapping_table.verticalHeader().setVisible(False)
    page.mapping_table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
    page.mapping_table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
    page.mapping_table.setAlternatingRowColors(True)
    page.mapping_table.setMinimumHeight(420)
    header = page.mapping_table.horizontalHeader()
    header.setSectionResizeMode(0, header.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(1, header.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(2, header.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(3, header.ResizeMode.Stretch)
    header.setSectionResizeMode(4, header.ResizeMode.Stretch)
    header.setSectionResizeMode(5, header.ResizeMode.Stretch)
    table_vbox.addWidget(page.mapping_table)
    table_layout.addWidget(table_wrapper)
    layout.addWidget(page.table_panel)


def _build_bottom_status_card(page, outer_layout: QVBoxLayout) -> None:
    bottom = SimpleCardWidget(page)
    bottom_layout = QVBoxLayout(bottom)
    bottom_layout.setContentsMargins(12, 10, 12, 10)
    bottom_layout.setSpacing(8)

    top_row = QHBoxLayout()
    top_row.setSpacing(10)
    page.status_label = StrongBodyLabel("等待配置...", bottom)
    page.progress_bar = ProgressBar(bottom)
    page.progress_bar.setRange(0, 100)
    page.progress_bar.setValue(0)
    page.progress_indeterminate_bar = IndeterminateProgressBar(start=True, parent=bottom)
    page.progress_indeterminate_bar.hide()
    page.progress_pct = StrongBodyLabel("0%", bottom)
    page.progress_pct.setMinimumWidth(50)
    page.progress_pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
    page.progress_pct.setStyleSheet("font-size: 13px; font-weight: bold;")
    page.start_btn = PrimaryPushButton("开始执行", bottom)
    page.resume_btn = PrimaryPushButton("继续", bottom)
    page.resume_btn.setEnabled(False)
    page.resume_btn.hide()
    page.stop_btn = PushButton("停止", bottom)
    page.stop_btn.setEnabled(False)
    page.start_btn.setToolTip("请先完成问卷解析、题目配置，并导入 Excel 数据源")
    install_tooltip_filter(page.start_btn)

    for widget, stretch in (
        (page.status_label, 0),
        (page.progress_bar, 1),
        (page.progress_indeterminate_bar, 1),
        (page.progress_pct, 0),
        (page.start_btn, 0),
        (page.resume_btn, 0),
        (page.stop_btn, 0),
    ):
        top_row.addWidget(widget, stretch)
    bottom_layout.addLayout(top_row)
    outer_layout.addWidget(bottom)

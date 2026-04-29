
"""问卷星 Excel 反填管理页。"""

from __future__ import annotations

import copy
import logging
import os
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QTableWidgetItem, QVBoxLayout, QWidget, QStackedWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    InfoBadge,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SettingCardGroup,
    StrongBodyLabel,
    SubtitleLabel,
    TableWidget,
    CardWidget,
    ElevatedCardWidget,
    SegmentedWidget,
    IconWidget,
    ToolButton,
)

from software.core.reverse_fill.schema import (
    REVERSE_FILL_FORMAT_AUTO,
    REVERSE_FILL_FORMAT_WJX_SCORE,
    REVERSE_FILL_FORMAT_WJX_SEQUENCE,
    REVERSE_FILL_FORMAT_WJX_TEXT,
    REVERSE_FILL_STATUS_BLOCKED,
    REVERSE_FILL_STATUS_FALLBACK,
    REVERSE_FILL_STATUS_REVERSE,
    ReverseFillSpec,
    reverse_fill_format_label,
)
from software.core.reverse_fill.validation import build_reverse_fill_spec
from software.io.config import RuntimeConfig
from software.logging.action_logger import log_action
from software.providers.common import SURVEY_PROVIDER_WJX, normalize_survey_provider
from software.providers.common import (
    SURVEY_PROVIDER_CREDAMO,
    SURVEY_PROVIDER_QQ,
    detect_survey_provider,
    is_supported_survey_url,
    is_wjx_survey_url,
)
from software.providers.contracts import SurveyQuestionMeta, ensure_survey_question_metas
from software.ui.helpers.fluent_tooltip import install_tooltip_filter
from software.ui.pages.workbench.dashboard.parts.clipboard import DashboardClipboardMixin
from software.ui.widgets.paste_only_menu import PasteOnlyMenu
from software.ui.widgets.setting_cards import SwitchSettingCard

if TYPE_CHECKING:
    from software.ui.controller import RunController


_FORMAT_CHOICES = [
    (REVERSE_FILL_FORMAT_AUTO, "自动识别 (推荐)"),
    (REVERSE_FILL_FORMAT_WJX_SEQUENCE, "问卷星按序号"),
    (REVERSE_FILL_FORMAT_WJX_SCORE, "问卷星按分数"),
    (REVERSE_FILL_FORMAT_WJX_TEXT, "问卷星按文本"),
]

_STATUS_LABELS = {
    REVERSE_FILL_STATUS_REVERSE: "🟢 反填覆盖",
    REVERSE_FILL_STATUS_FALLBACK: "🟡 常规回退",
    REVERSE_FILL_STATUS_BLOCKED: "🔴 阻塞",
}


class ReverseFillPage(DashboardClipboardMixin, ScrollArea):
    """独立的反填数据源管理页。"""

    surveyUrlChanged = Signal(str)

    def __init__(self, controller: "RunController", parent=None):
        super().__init__(parent)
        self.controller = controller
        self._questions_info: List[SurveyQuestionMeta] = []
        self._question_entries: List[Any] = []
        self._survey_provider: str = ""
        self._survey_title: str = ""
        self._target_num: int = 1
        self._selected_format_value: str = REVERSE_FILL_FORMAT_AUTO
        self._start_row_value: int = 1
        self._last_spec: Optional[ReverseFillSpec] = None
        self._last_error: str = ""
        self._open_wizard_handler: Optional[Callable[[], None]] = None
        self._clipboard_parse_ticket = 0
        self._parse_requested_from_reverse_fill = False

        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        
        self.setObjectName("reverseFillPage")
        
        self._build_ui()
        self._bind_events()
        self._refresh_preview()

    def _build_title_area(self, layout: QVBoxLayout) -> None:
        title_row = QWidget(self.view)
        title_row_layout = QHBoxLayout(title_row)
        title_row_layout.setContentsMargins(0, 0, 0, 0)
        title_row_layout.setSpacing(10)

        title_label = SubtitleLabel("反填配置", title_row)
        title_row_layout.addWidget(title_label)

        self.preview_badge = InfoBadge.custom(
            "预览",
            QColor("#fbbf24"),
            QColor("#f59e0b"),
            parent=title_row,
        )
        title_row_layout.addWidget(self.preview_badge)
        title_row_layout.addStretch(1)

        layout.addWidget(title_row)
        layout.addSpacing(4)

    def _build_survey_entry_card(self, layout: QVBoxLayout) -> None:
        self.link_card = CardWidget(self.view)
        self.link_card.setAcceptDrops(True)
        link_layout = QVBoxLayout(self.link_card)
        link_layout.setContentsMargins(12, 12, 12, 12)
        link_layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        self.qr_btn = ToolButton(self.link_card)
        self.qr_btn.setIcon(FluentIcon.QRCODE)
        self.qr_btn.setFixedSize(36, 36)
        self.qr_btn.setToolTip("上传问卷二维码图片")
        install_tooltip_filter(self.qr_btn)
        title_row.addWidget(self.qr_btn)

        self.url_edit = LineEdit(self.link_card)
        self.url_edit.setPlaceholderText("在此拖入/粘贴问卷二维码图片或输入问卷链接")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.setAcceptDrops(True)
        self.url_edit.installEventFilter(self)
        self._paste_only_menu = PasteOnlyMenu(self)
        self.url_edit.installEventFilter(self._paste_only_menu)
        title_row.addWidget(self.url_edit, 1)

        link_layout.addLayout(title_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.parse_btn = PrimaryPushButton(FluentIcon.PLAY, "解析问卷结构", self.link_card)
        btn_row.addWidget(self.parse_btn)
        btn_row.addStretch(1)
        link_layout.addLayout(btn_row)

        self._link_entry_widgets = (
            self.link_card,
            self.qr_btn,
            self.url_edit,
            self.parse_btn,
        )
        for widget in self._link_entry_widgets:
            if widget is self.url_edit:
                continue
            widget.installEventFilter(self)

        layout.addWidget(self.link_card)

    def _build_config_cards(self, layout: QVBoxLayout) -> None:
        config_group = SettingCardGroup("数据源管理", self.view)
        
        self.enable_card = SwitchSettingCard(
            FluentIcon.SYNC,
            "启用自动反填",
            "开启该功能后，会在受支持题型上生效，将其按 Excel 样本行级答卷数据执行点选回填。",
            parent=config_group,
        )
        config_group.addSettingCard(self.enable_card)

        layout.addWidget(config_group)

    def _build_file_picker(self, layout: QVBoxLayout) -> None:
        self.file_panel = ElevatedCardWidget(self.view)
        file_layout = QVBoxLayout(self.file_panel)
        file_layout.setContentsMargins(20, 18, 20, 20)
        file_layout.setSpacing(14)

        header_row = QHBoxLayout()
        header_icon = IconWidget(FluentIcon.DOCUMENT, self.file_panel)
        header_icon.setFixedSize(20, 20)
        header_title = StrongBodyLabel("Excel 数据源指定", self.file_panel)
        header_row.addWidget(header_icon)
        header_row.addWidget(header_title)
        header_row.addStretch(1)
        file_layout.addLayout(header_row)

        desc_label = CaptionLabel("点击以选择需要调取和读取逻辑的 .xlsx 扩展名样本数据源文件。", self.file_panel)
        desc_label.setContentsMargins(0, 0, 0, 4)
        file_layout.addWidget(desc_label)

        input_row = QHBoxLayout()
        input_row.setSpacing(12)
        self.file_edit = LineEdit(self.file_panel)
        self.file_edit.setPlaceholderText("C:/Users/Administrator/Desktop/待填答卷数据.xlsx")
        self.file_edit.setClearButtonEnabled(True)
        self.browse_btn = PushButton(FluentIcon.FOLDER_ADD, "选择路径", self.file_panel)
        input_row.addWidget(self.file_edit, 1)
        input_row.addWidget(self.browse_btn)
        file_layout.addLayout(input_row)

        info_row = QHBoxLayout()
        info_row.setSpacing(24)
        self.detected_format_label = BodyLabel("检测结果：等待校验事件", self.file_panel)
        self.state_hint_label = CaptionLabel("暂无有效数据装载", self.file_panel)
        info_row.addWidget(self.detected_format_label)
        info_row.addWidget(self.state_hint_label)
        info_row.addStretch(1)
        file_layout.addLayout(info_row)

        layout.addWidget(self.file_panel)

    def _build_summary_banner(self, layout: QVBoxLayout) -> None:
        self.summary_card = CardWidget(self.view)
        self.summary_card.setObjectName("summaryCard")
        sum_layout = QHBoxLayout(self.summary_card)
        sum_layout.setContentsMargins(24, 20, 24, 20)
        sum_layout.setSpacing(20)

        self.summary_icon = IconWidget(FluentIcon.INFO, self.summary_card)
        self.summary_icon.setFixedSize(28, 28)
        sum_layout.addWidget(self.summary_icon)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(6)
        self.summary_title = StrongBodyLabel("等待基础样本解析装配", self.summary_card)
        self.summary_desc = CaptionLabel("指定数据源后立刻按目标额度与题目树约束进行自动探测预诊，诊断是否存在数据风险。此过程自动完成。", self.summary_card)
        text_layout.addWidget(self.summary_title)
        text_layout.addWidget(self.summary_desc)
        
        sum_layout.addLayout(text_layout)
        sum_layout.addStretch(1)

        layout.addWidget(self.summary_card)

    def _build_details_tables(self, layout: QVBoxLayout) -> None:
        self.table_panel = ElevatedCardWidget(self.view)
        table_layout = QVBoxLayout(self.table_panel)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)

        header_widget = QWidget(self.table_panel)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(24, 16, 24, 12)
        
        self.segment = SegmentedWidget(header_widget)
        
        header_layout.addWidget(self.segment)
        header_layout.addStretch(1)
        
        self.open_wizard_btn = PrimaryPushButton(FluentIcon.EDIT, "一键定位处理缺失依赖", header_widget)
        self.open_wizard_btn.hide()
        header_layout.addWidget(self.open_wizard_btn)
        
        table_layout.addWidget(header_widget)

        self.stacked_widget = QStackedWidget(self.table_panel)
        
        # 1. Mapping Table
        mapping_wrapper = QWidget()
        mapping_vbox = QVBoxLayout(mapping_wrapper)
        mapping_vbox.setContentsMargins(24, 0, 24, 24)
        
        self.mapping_table = TableWidget(mapping_wrapper)
        self.mapping_table.setColumnCount(5)
        self.mapping_table.setHorizontalHeaderLabels(["对应题号", "解析特征题型", "挂载支持判定", "关联表头列标", "执行策略附注"])
        self.mapping_table.verticalHeader().setVisible(False)
        self.mapping_table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.mapping_table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.mapping_table.setAlternatingRowColors(True)
        self.mapping_table.setMinimumHeight(420)
        m_header = self.mapping_table.horizontalHeader()
        m_header.setSectionResizeMode(0, m_header.ResizeMode.ResizeToContents)
        m_header.setSectionResizeMode(1, m_header.ResizeMode.ResizeToContents)
        m_header.setSectionResizeMode(2, m_header.ResizeMode.ResizeToContents)
        m_header.setSectionResizeMode(3, m_header.ResizeMode.Stretch)
        m_header.setSectionResizeMode(4, m_header.ResizeMode.Stretch)
        mapping_vbox.addWidget(self.mapping_table)
        
        # 2. Issues Table
        issue_wrapper = QWidget()
        issue_vbox = QVBoxLayout(issue_wrapper)
        issue_vbox.setContentsMargins(24, 0, 24, 24)
        
        self.issue_table = TableWidget(issue_wrapper)
        self.issue_table.setColumnCount(5)
        self.issue_table.setHorizontalHeaderLabels(["溯源题号", "诊断风险类目", "严重等级分布", "异常原因明细追查", "系统推荐化解方案"])
        self.issue_table.verticalHeader().setVisible(False)
        self.issue_table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.issue_table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.issue_table.setAlternatingRowColors(True)
        self.issue_table.setMinimumHeight(420)
        i_header = self.issue_table.horizontalHeader()
        i_header.setSectionResizeMode(0, i_header.ResizeMode.ResizeToContents)
        i_header.setSectionResizeMode(1, i_header.ResizeMode.ResizeToContents)
        i_header.setSectionResizeMode(2, i_header.ResizeMode.ResizeToContents)
        i_header.setSectionResizeMode(3, i_header.ResizeMode.Stretch)
        i_header.setSectionResizeMode(4, i_header.ResizeMode.Stretch)
        issue_vbox.addWidget(self.issue_table)
        
        self.stacked_widget.addWidget(mapping_wrapper)
        self.stacked_widget.addWidget(issue_wrapper)

        self.segment.addItem("mapping", "映射预览检查", lambda: self._switch_tab(0))
        self.segment.addItem("issues", "异常与回退拦截项", lambda: self._switch_tab(1))
        
        table_layout.addWidget(self.stacked_widget)
        layout.addWidget(self.table_panel)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)

        self._build_title_area(layout)
        self._build_survey_entry_card(layout)
        self._build_config_cards(layout)
        self._build_file_picker(layout)
        self._build_summary_banner(layout)
        self._build_details_tables(layout)
        layout.addStretch(1)
        self.segment.setCurrentItem("mapping")

    def _switch_tab(self, index: int) -> None:
        self.stacked_widget.setCurrentIndex(index)
        if index == 1 and self._questions_info:
            self.open_wizard_btn.show()
        else:
            self.open_wizard_btn.hide()

    def _bind_events(self) -> None:
        self.enable_card.switchButton.checkedChanged.connect(lambda _checked: self._refresh_preview())
        self.qr_btn.clicked.connect(self._on_qr_clicked)
        self.parse_btn.clicked.connect(self._on_parse_clicked)
        self.url_edit.returnPressed.connect(self._on_parse_clicked)
        self.url_edit.textChanged.connect(self.surveyUrlChanged.emit)
        self.file_edit.editingFinished.connect(self._refresh_preview)
        self.browse_btn.clicked.connect(self._browse_excel_file)
        self.open_wizard_btn.clicked.connect(self._open_wizard)
        clipboard = QApplication.clipboard()
        clipboard.dataChanged.connect(self._on_clipboard_changed)
        self.controller.surveyParsed.connect(self._on_survey_parsed)
        self.controller.surveyParseFailed.connect(self._on_survey_parse_failed)

    def set_open_wizard_handler(self, handler: Optional[Callable[[], None]]) -> None:
        self._open_wizard_handler = handler

    def set_question_context(
        self,
        questions_info: Sequence[SurveyQuestionMeta],
        question_entries: Sequence[Any],
        *,
        survey_title: str = "",
        survey_provider: str = "",
    ) -> None:
        self._questions_info = ensure_survey_question_metas(questions_info or [])
        self._question_entries = list(copy.deepcopy(list(question_entries or [])))
        self._survey_title = str(survey_title or "").strip()
        self._survey_provider = str(survey_provider or "").strip()
        self._refresh_preview()

    def update_config(self, cfg: RuntimeConfig) -> None:
        self._target_num = max(1, int(getattr(cfg, "target", self._target_num) or self._target_num))
        cfg.reverse_fill_enabled = bool(self.enable_card.isChecked())
        cfg.reverse_fill_source_path = self.file_edit.text().strip()
        cfg.reverse_fill_format = self._selected_format()
        cfg.reverse_fill_start_row = max(1, int(self._start_row_value or 1))

    def apply_config(self, cfg: RuntimeConfig) -> None:
        self._target_num = max(1, int(getattr(cfg, "target", 1) or 1))
        self.enable_card.blockSignals(True)
        self.enable_card.setChecked(bool(getattr(cfg, "reverse_fill_enabled", False)))
        self.enable_card.blockSignals(False)
        self.url_edit.blockSignals(True)
        self.url_edit.setText(str(getattr(cfg, "url", "") or ""))
        self.url_edit.blockSignals(False)
        self.file_edit.setText(str(getattr(cfg, "reverse_fill_source_path", "") or ""))
        self._start_row_value = max(1, int(getattr(cfg, "reverse_fill_start_row", 1) or 1))

        selected_format = str(getattr(cfg, "reverse_fill_format", REVERSE_FILL_FORMAT_AUTO) or REVERSE_FILL_FORMAT_AUTO)
        valid_formats = {value for value, _label in _FORMAT_CHOICES}
        self._selected_format_value = selected_format if selected_format in valid_formats else REVERSE_FILL_FORMAT_AUTO
        self._refresh_preview()

    def _selected_format(self) -> str:
        return str(self._selected_format_value or REVERSE_FILL_FORMAT_AUTO)

    def _toast(self, message: str, level: str = "warning", duration: int = 2400) -> None:
        parent = self.window() or self
        if level == "error":
            InfoBar.error("反填页提示", message, parent=parent, position=InfoBarPosition.TOP, duration=duration)
            return
        if level == "success":
            InfoBar.success("反填页提示", message, parent=parent, position=InfoBarPosition.TOP, duration=duration)
            return
        if level == "info":
            InfoBar.info("反填页提示", message, parent=parent, position=InfoBarPosition.TOP, duration=duration)
            return
        InfoBar.warning("反填页提示", message, parent=parent, position=InfoBarPosition.TOP, duration=duration)

    def _context_ready(self) -> bool:
        provider = normalize_survey_provider(self._survey_provider, default="")
        return provider == SURVEY_PROVIDER_WJX and bool(self._questions_info)

    def _browse_excel_file(self) -> None:
        start_dir = os.path.dirname(self.file_edit.text().strip()) if self.file_edit.text().strip() else ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择源数据 Excel 文件",
            start_dir,
            "Excel 数据工作表 (*.xlsx);;所有包含的文件 (*.*)",
        )
        if not path:
            return
        self.file_edit.setText(path)
        self._refresh_preview()

    def _on_parse_clicked(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            self._toast("请先输入问卷链接或贴入二维码", "warning")
            return
        if not is_supported_survey_url(url):
            self._toast("仅支持问卷星、腾讯问卷与 Credamo 见数链接", "error", duration=3000)
            return
        provider = detect_survey_provider(url)
        if not (provider in {SURVEY_PROVIDER_QQ, SURVEY_PROVIDER_CREDAMO} or is_wjx_survey_url(url)):
            self._toast("链接不是可解析的公开问卷", "error", duration=3000)
            return

        self._parse_requested_from_reverse_fill = True
        self.surveyUrlChanged.emit(url)
        self._toast("正在解析问卷结构...", "info", duration=-1)
        self.controller.parse_survey(url)
        log_action(
            "UI",
            "parse_survey",
            "parse_btn",
            "reverse_fill",
            result="started",
            payload={"provider": provider},
        )

    def _on_survey_parsed(self, info: list, title: str) -> None:
        if not self._parse_requested_from_reverse_fill:
            return
        self._parse_requested_from_reverse_fill = False
        parsed_info = ensure_survey_question_metas(info or [])
        unsupported_count = sum(1 for item in parsed_info if bool(item.unsupported))
        self._survey_title = str(title or "").strip()
        self._survey_provider = normalize_survey_provider(
            getattr(self.controller, "survey_provider", "") or detect_survey_provider(self.url_edit.text().strip(), default=""),
            default=self._survey_provider or "",
        )
        self._refresh_preview()
        if unsupported_count > 0:
            self._toast(f"问卷已解析，发现 {unsupported_count} 道反填不能直接覆盖的题型", "warning", duration=3600)
            return
        self._toast("问卷已解析，可以继续选择 Excel 做反填预检", "success", duration=2600)

    def _on_survey_parse_failed(self, error_msg: str) -> None:
        if not self._parse_requested_from_reverse_fill:
            return
        self._parse_requested_from_reverse_fill = False
        text = str(error_msg or "").strip() or "请确认链接有效且网络正常"
        self._toast(f"解析失败：{text}", "error", duration=3200)

    def _open_wizard(self) -> None:
        if not callable(self._open_wizard_handler):
            self._toast("目前无法直接导航至系统向导。您需优先在仪表盘主页完成问卷解析方可继续。", "warning")
            return
        try:
            self._open_wizard_handler()
        except Exception as exc:
            logging.info("打开配置向导异常崩溃", exc_info=True)
            self._toast(f"触发配置交互向导意外阻断：{exc}", "error")

    def _set_table_text(self, table: TableWidget, row: int, column: int, text: str) -> None:
        item = table.item(row, column)
        if item is None:
            table.setItem(row, column, QTableWidgetItem(text))
            return
        item.setText(text)

    def _clear_tables(self) -> None:
        self.mapping_table.setRowCount(0)
        self.issue_table.setRowCount(0)
        self.segment.setItemText("issues", "异常与回退拦截项 (0)")

    def _populate_plan_table(self, spec: ReverseFillSpec) -> None:
        plans = list(spec.question_plans or [])
        self.mapping_table.setRowCount(len(plans))
        for row, plan in enumerate(plans):
            self._set_table_text(self.mapping_table, row, 0, str(int(plan.question_num or 0)))
            self._set_table_text(self.mapping_table, row, 1, str(plan.question_type or ""))
            self._set_table_text(self.mapping_table, row, 2, _STATUS_LABELS.get(str(plan.status or ""), str(plan.status or "")))
            self._set_table_text(self.mapping_table, row, 3, " / ".join(list(plan.column_headers or [])))
            self._set_table_text(self.mapping_table, row, 4, str(plan.detail or ""))

    def _populate_issue_table(self, spec: ReverseFillSpec) -> None:
        issues = list(spec.issues or [])
        self.issue_table.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            question_text = "全局逻辑阻断" if int(issue.question_num or 0) <= 0 else str(int(issue.question_num or 0))
            self._set_table_text(self.issue_table, row, 0, question_text)
            self._set_table_text(self.issue_table, row, 1, str(issue.category or ""))
            severity = str(issue.severity or "").strip().lower()
            if severity in {"block", "error"}:
                severity = "🔴 严重缺陷 (运行时阻塞)"
            elif severity in {"warn", "warning"}:
                severity = "🟡 低危警告 (人工注意)"
            self._set_table_text(self.issue_table, row, 2, severity)
            reason = str(issue.reason or "")
            if issue.sample_rows:
                reason = f"{reason}\n（参考样例数据源定位行码：{', '.join(str(int(item)) for item in issue.sample_rows[:3])}）"
            self._set_table_text(self.issue_table, row, 3, reason)
            self._set_table_text(self.issue_table, row, 4, str(issue.suggestion or ""))

    def _refresh_preview(self) -> None:
        self._last_spec = None
        self._last_error = ""
        source_path = self.file_edit.text().strip()
        context_ready = self._context_ready()

        controls_enabled = context_ready
        self.file_edit.setEnabled(controls_enabled)
        self.browse_btn.setEnabled(controls_enabled)
        if hasattr(self, 'open_wizard_btn'):
            if self.stacked_widget.currentIndex() == 1:
                self.open_wizard_btn.setVisible(bool(self._questions_info))

        if not context_ready:
            provider = normalize_survey_provider(self._survey_provider, default="")
            if provider != SURVEY_PROVIDER_WJX:
                hint = "该执行总线暂不能在当前平台环境接管反填覆盖支持，相关控制流已全托管休眠"
            else:
                hint = "未在内存缓冲探测到最新的结构特征表。须优先通过核心解析引擎提取目标网络题库方可对表"
                
            self.detected_format_label.setText("验证结果：未接通目标流")
            self.state_hint_label.setText(hint)
            self.summary_icon.setIcon(FluentIcon.CANCEL)
            self.summary_title.setText("脱机阻隔状态，验证功能暂被冻结")
            self.summary_desc.setText(hint)
            self._clear_tables()
            return

        if not source_path:
            self.detected_format_label.setText("验证结果：待指定 Excel 数据池")
            self.state_hint_label.setText("必须提供用于特征分析的前置样卷数据路径")
            self.summary_icon.setIcon(FluentIcon.INFO)
            self.summary_title.setText("需您补充指定本地存放的 Excel 源文件")
            self.summary_desc.setText("完成路径引用关联以后将即时生成详细映射自诊、挂载清单并完成业务规则审查。")
            self._clear_tables()
            return

        try:
            spec = build_reverse_fill_spec(
                source_path=source_path,
                survey_provider=self._survey_provider or SURVEY_PROVIDER_WJX,
                questions_info=self._questions_info,
                question_entries=self._question_entries,
                selected_format=self._selected_format(),
                start_row=max(1, int(self._start_row_value or 1)),
                target_num=max(0, int(self._target_num or 0)),
            )
        except Exception as exc:
            self._last_error = str(exc)
            self.detected_format_label.setText("验证结果：提取引发崩溃挂起")
            self.state_hint_label.setText(self._last_error)
            self.summary_icon.setIcon(FluentIcon.INFO)
            self.summary_title.setText("构建本地提取层中抛出了预料外中断")
            self.summary_desc.setText(self._last_error)
            self._clear_tables()
            return

        self._last_spec = spec
        self.detected_format_label.setText(
            f"归一分析识别格式：{reverse_fill_format_label(spec.detected_format)}"
        )
        enabled_text = "运行时将切入主动控制流拦截执行" if self.enable_card.isChecked() else "全局切断触发链路验证仅用作演示"
        self.state_hint_label.setText(
            f"行为定性预判：{enabled_text} （自 Excel 原始单元格界限第 {spec.start_row} 起进行数据锚定）"
        )
        
        issue_cnt = len(spec.issues or [])
        block_cnt = spec.blocking_issue_count
        
        if block_cnt > 0:
            self.summary_icon.setIcon(FluentIcon.INFO)
        else:
            self.summary_icon.setIcon(FluentIcon.COMPLETED)
            
        self.summary_title.setText(
            f"通过前置模拟检查就绪！有效净容量 {spec.available_samples} 份 （数据原尺寸总池深 {spec.total_samples} 份）"
        )
        
        self.summary_desc.setText(
            f"配置目标输出配额量 {spec.target_num or self._target_num} 份，共排定覆盖题型推演线路图 {len(spec.question_plans or [])} 条，核查出隐患支点项 {issue_cnt} 枚 (导致运行时直接致命崩溃项 {block_cnt} 个)。"
        )
        
        self.segment.setItemText("issues", f"异常与回退拦截项 ({issue_cnt})")
        self._populate_plan_table(spec)
        self._populate_issue_table(spec)


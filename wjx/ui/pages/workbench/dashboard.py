"""主控制面板：卡片式配置区 + 底部状态条（不包含日志）"""
import os
import threading
from typing import Optional
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception


from PySide6.QtCore import Qt, QObject, QEvent, Signal
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFileDialog,
)
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    BodyLabel,
    CardWidget,
    PushButton,
    PrimaryPushButton,
    TableWidget,
    LineEdit,
    CheckBox,
    IndeterminateProgressRing,
    CommandBar,
    Action,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    InfoBarIcon,
    HyperlinkButton,
    SegmentedWidget,
    DrillInTransitionStackedWidget,
)
from qfluentwidgets import RoundMenu

from wjx.ui.pages.workbench.dashboard_parts.clipboard import DashboardClipboardMixin
from wjx.ui.pages.workbench.dashboard_parts.entries import DashboardEntriesMixin
from wjx.ui.pages.workbench.dashboard_parts.progress import DashboardProgressMixin
from wjx.ui.pages.workbench.dashboard_parts.random_ip import DashboardRandomIPMixin
from wjx.ui.widgets import ConfigDrawer
from wjx.ui.widgets.full_width_infobar import FullWidthInfoBar
from wjx.ui.widgets.no_wheel import NoWheelSpinBox
from wjx.ui.controller import RunController
from wjx.ui.pages.workbench.answer_rules import AnswerRulesPage
from wjx.ui.pages.workbench.question import QuestionPage
from wjx.ui.pages.workbench.runtime import RuntimePage
from wjx.utils.io.load_save import RuntimeConfig, build_default_config_filename, get_runtime_directory
from wjx.network.proxy import (
    refresh_ip_counter_display,
)


class _PasteOnlyMenu(QObject):
    """只保留 qfluentwidgets 风格的“粘贴”菜单"""



    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ContextMenu and isinstance(watched, LineEdit):
            if isinstance(event, QContextMenuEvent):
                menu = RoundMenu(parent=watched)
                paste_action = Action(FluentIcon.PASTE, "粘贴", parent=menu)
                paste_action.triggered.connect(watched.paste)
                menu.addAction(paste_action)
                menu.exec(event.globalPos())
                return True
        return super().eventFilter(watched, event)


class DashboardPage(
    DashboardClipboardMixin,
    DashboardRandomIPMixin,
    DashboardEntriesMixin,
    DashboardProgressMixin,
    QWidget,
):
    """主页：左侧配置 + 底部状态，不再包含日志。"""

    _ipBalanceChecked = Signal(int)  # 发送剩余IP数信号

    def __init__(
        self,
        controller: RunController,
        question_page: QuestionPage,
        runtime_page: RuntimePage,
        answer_rules_page: AnswerRulesPage,
        parent=None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.controller = controller
        self.question_page = question_page
        self.runtime_page = runtime_page
        self.answer_rules_page = answer_rules_page
        self._open_wizard_after_parse = False
        self._survey_title = ""
        self._last_pause_reason = ""
        self._completion_notified = False
        self._pending_restart = False
        self._show_end_toast_after_cleanup = False
        self._last_progress = 0
        self._progress_infobar: Optional[InfoBar] = None  # 存储进度消息条的引用
        self._ip_low_infobar: Optional[FullWidthInfoBar] = None
        self._ip_cost_infobar: Optional[FullWidthInfoBar] = None
        self._ip_low_infobar_dismissed = False
        self._ip_low_threshold = 5000
        self._api_balance_cache: Optional[float] = None  # 缓存 API 余额
        self._ip_balance_fetch_lock = threading.Lock()
        self._ip_balance_fetching = False
        self._last_ip_balance_fetch_ts = 0.0
        self._ip_balance_fetch_interval_sec = 30.0
        self._clipboard_parse_ticket = 0
        self._init_progress_state()
        self._build_ui()
        self.config_drawer = ConfigDrawer(self, self._load_config_from_path)
        self._bind_events()
        self._sync_start_button_state()
        self._refresh_ip_cost_infobar()

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
            content="随机IP剩余额度较低，如需继续使用请及时补充额度",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.NONE,
            duration=-1,
            parent=inner,
        )
        self._ip_low_infobar.hide()
        self._ip_low_infobar.closeButton.clicked.connect(self._on_ip_low_infobar_closed)
        self._ip_low_contact_link = HyperlinkButton(FluentIcon.LINK, "", "前往联系", self._ip_low_infobar)
        self._ip_low_contact_link.clicked.connect(lambda: self._open_contact_dialog(default_type="额度申请"))
        self._ip_low_infobar.addWidget(self._ip_low_contact_link)
        layout.addWidget(self._ip_low_infobar)

        self.link_card = CardWidget(self)
        self.link_card.setAcceptDrops(True)
        self.link_card.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        link_layout = QVBoxLayout(self.link_card)
        link_layout.setContentsMargins(12, 12, 12, 12)
        link_layout.setSpacing(8)
        
        # 标题行：左侧是标题，右侧是载入/保存按钮
        title_row = QHBoxLayout()
        title_row.addWidget(SubtitleLabel("问卷入口", self))
        title_row.addStretch(1)
        # 使用 QFluentWidgets 原生图标
        self.config_list_btn = PushButton("配置列表", self, FluentIcon.MENU)
        self.load_cfg_btn = PushButton("载入配置", self, FluentIcon.DOCUMENT)
        self.save_cfg_btn = PushButton("保存配置", self, FluentIcon.SAVE)
        title_row.addWidget(self.config_list_btn)
        title_row.addWidget(self.load_cfg_btn)
        title_row.addWidget(self.save_cfg_btn)
        link_layout.addLayout(title_row)
        
        link_layout.addWidget(BodyLabel("问卷链接：", self))
        # 创建水平布局：按钮在前，输入框在后
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.qr_btn = PushButton("上传问卷二维码图片", self, FluentIcon.QRCODE)
        input_row.addWidget(self.qr_btn)
        self.url_edit = LineEdit(self)
        self.url_edit.setPlaceholderText("在此拖入/粘贴问卷二维码图片或输入问卷链接")
        self.url_edit.setClearButtonEnabled(True)
        # 启用拖放功能
        self.url_edit.setAcceptDrops(True)
        self.url_edit.installEventFilter(self)
        # 仅问卷链接输入框需要 qfluentwidgets 风格的"粘贴"单项菜单
        self._paste_only_menu = _PasteOnlyMenu(self)
        self.url_edit.installEventFilter(self._paste_only_menu)
        input_row.addWidget(self.url_edit, 1)
        link_layout.addLayout(input_row)
        
        # 只保留"自动配置问卷"按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.parse_btn = PrimaryPushButton("自动配置问卷", self)
        btn_row.addWidget(self.parse_btn)
        btn_row.addStretch(1)
        link_layout.addLayout(btn_row)
        layout.addWidget(self.link_card)

        # 整个“问卷入口”卡片都支持粘贴/拖入二维码
        self._link_entry_widgets = (
            self.link_card,
            self.config_list_btn,
            self.load_cfg_btn,
            self.save_cfg_btn,
            self.qr_btn,
            self.url_edit,
            self.parse_btn,
        )
        for widget in self._link_entry_widgets:
            if widget is self.url_edit:
                continue
            widget.installEventFilter(self)

        exec_card = CardWidget(self)
        exec_layout = QVBoxLayout(exec_card)
        exec_layout.setContentsMargins(12, 12, 12, 12)
        exec_layout.setSpacing(10)
        
        # 头部标题与跳转按钮
        title_row = QHBoxLayout()
        title_row.addWidget(SubtitleLabel("快捷设置", self))
        title_row.addStretch(1)
        self.more_settings_btn = HyperlinkButton(FluentIcon.SETTING, "", "更多设置请前往“运行参数”页仔细调整", self)
        title_row.addWidget(self.more_settings_btn)
        exec_layout.addLayout(title_row)

        spin_row = QHBoxLayout()
        spin_row.addWidget(BodyLabel("目标份数：", self))
        self.target_spin = NoWheelSpinBox(self)
        self.target_spin.setRange(1, 99999)
        self.target_spin.setMinimumWidth(140)
        self.target_spin.setMinimumHeight(36)
        spin_row.addWidget(self.target_spin)
        spin_row.addSpacing(12)
        spin_row.addWidget(BodyLabel("并发数：", self))
        self.thread_spin = NoWheelSpinBox(self)
        self.thread_spin.setRange(1, 8)
        self.thread_spin.setMinimumWidth(140)
        self.thread_spin.setMinimumHeight(36)
        spin_row.addWidget(self.thread_spin)
        spin_row.addStretch(1)
        exec_layout.addLayout(spin_row)

        self.random_ip_cb = CheckBox("启用随机 IP 提交（在触发智能验证时开启）", self)
        random_ip_row = QHBoxLayout()
        random_ip_row.setSpacing(8)
        random_ip_row.addWidget(self.random_ip_cb)
        self.random_ip_loading_ring = IndeterminateProgressRing(self)
        self.random_ip_loading_ring.setFixedSize(18, 18)
        self.random_ip_loading_ring.setStrokeWidth(2)
        self.random_ip_loading_ring.hide()
        random_ip_row.addWidget(self.random_ip_loading_ring)
        self.random_ip_loading_label = BodyLabel("", self)
        self.random_ip_loading_label.setStyleSheet("color: #606060; font-size: 12px;")
        self.random_ip_loading_label.hide()
        random_ip_row.addWidget(self.random_ip_loading_label)
        random_ip_row.addStretch(1)
        exec_layout.addLayout(random_ip_row)
        ip_row = QHBoxLayout()
        ip_row.setSpacing(8)
        ip_row.addWidget(BodyLabel("随机IP额度：", self))
        self.random_ip_hint = BodyLabel("--/--", self)
        ip_row.addWidget(self.random_ip_hint)
        ip_row.addSpacing(4)
        self.card_btn = PushButton("申请额度", self, FluentIcon.FINGERPRINT)
        ip_row.addWidget(self.card_btn)
        ip_row.addStretch(1)
        exec_layout.addLayout(ip_row)

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
        self._ip_cost_adjust_link = HyperlinkButton(FluentIcon.LINK, "", "前往调整作答时长", self._ip_cost_infobar)
        self._ip_cost_adjust_link.clicked.connect(self._go_to_runtime_answer_duration)
        self._ip_cost_infobar.addWidget(self._ip_cost_adjust_link)
        self._ip_cost_infobar.hide()
        exec_layout.addWidget(self._ip_cost_infobar)
        layout.addWidget(exec_card)

        switch_row = QHBoxLayout()
        switch_row.setContentsMargins(0, 0, 0, 0)
        switch_row.setSpacing(8)
        self.thread_view_seg = SegmentedWidget(self)
        self.thread_view_seg.addItem(routeKey=self.THREAD_VIEW_QUESTION_LIST, text="题目清单")
        self.thread_view_seg.addItem(routeKey=self.THREAD_VIEW_PROGRESS, text="线程进度")
        self.thread_view_seg.setCurrentItem(self.THREAD_VIEW_QUESTION_LIST)
        switch_row.addWidget(self.thread_view_seg)
        switch_row.addStretch(1)
        layout.addLayout(switch_row)

        self.thread_view_stack = DrillInTransitionStackedWidget(self)

        self.thread_view_question_card = CardWidget(self.thread_view_stack)
        question_list_layout = QVBoxLayout(self.thread_view_question_card)
        question_list_layout.setContentsMargins(12, 12, 12, 12)
        question_list_layout.setSpacing(8)

        question_title_row = QHBoxLayout()
        question_title_row.setSpacing(8)
        self.title_label = SubtitleLabel("题目清单与操作", self.thread_view_question_card)
        self.count_label = BodyLabel("0 题", self.thread_view_question_card)
        self.count_label.setStyleSheet("color: #6b6b6b;")
        question_title_row.addWidget(self.title_label)
        question_title_row.addStretch(1)
        question_title_row.addWidget(self.count_label)
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
        self.entry_table.setColumnCount(3)
        self.entry_table.setHorizontalHeaderLabels(["序号", "类型", "策略"])
        self.entry_table.verticalHeader().setVisible(False)
        self.entry_table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.entry_table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.entry_table.setAlternatingRowColors(True)
        self.entry_table.setMinimumHeight(360)
        # 设置列宽策略：第0列序号固定60px，第1列类型固定180px，第2列策略自动拉伸
        header = self.entry_table.horizontalHeader()
        header.setSectionResizeMode(0, header.ResizeMode.Fixed)
        header.setSectionResizeMode(1, header.ResizeMode.Fixed)
        header.setSectionResizeMode(2, header.ResizeMode.Stretch)
        self.entry_table.setColumnWidth(0, 60)
        self.entry_table.setColumnWidth(1, 180)
        question_list_layout.addWidget(self.entry_table, 1)

        self.thread_view_progress_card = CardWidget(self.thread_view_stack)
        progress_card_layout = QVBoxLayout(self.thread_view_progress_card)
        progress_card_layout.setContentsMargins(12, 12, 12, 12)
        progress_card_layout.setSpacing(8)
        progress_title_row = QHBoxLayout()
        progress_title_row.setSpacing(8)
        progress_title_row.addWidget(SubtitleLabel("线程进度", self.thread_view_progress_card))
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
        self.parse_btn.clicked.connect(self._on_parse_clicked)
        self.config_list_btn.clicked.connect(self._on_show_config_list)
        self.load_cfg_btn.clicked.connect(self._on_load_config)
        self.save_cfg_btn.clicked.connect(self._on_save_config)
        self.qr_btn.clicked.connect(self._on_qr_clicked)
        self._bind_progress_events()
        self.thread_view_seg.currentItemChanged.connect(self._on_thread_view_changed)
        self.target_spin.valueChanged.connect(lambda v: self.runtime_page.target_spin.setValue(int(v)))
        self.thread_spin.valueChanged.connect(lambda v: self.runtime_page.thread_spin.setValue(int(v)))
        self.random_ip_cb.stateChanged.connect(self._on_random_ip_toggled)
        self.card_btn.clicked.connect(self._on_request_quota_clicked)
        self.more_settings_btn.clicked.connect(self._go_to_runtime_page)
        self.runtime_page.answer_card.valueChanged.connect(lambda _v: self._refresh_ip_cost_infobar())
        self.runtime_page.timed_switch.checkedChanged.connect(lambda _v: self._refresh_ip_cost_infobar())
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
            self.question_page.entriesChanged.connect(self._on_question_entries_changed)
        except Exception as exc:
            log_suppressed_exception("_bind_events: self.question_page.entriesChanged.connect(self._on_question_entries_changed)", exc, level=logging.WARNING)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            self.config_drawer.sync_to_parent()
        except Exception as exc:
            log_suppressed_exception("resizeEvent: self.config_drawer.sync_to_parent()", exc, level=logging.WARNING)

    def _has_question_entries(self) -> bool:
        try:
            return bool(self.question_page.get_entries())
        except Exception:
            return False

    def _sync_start_button_state(self, running: Optional[bool] = None):
        if running is None:
            running = bool(getattr(self.controller, "running", False))
        can_start = (not running) and self._has_question_entries()
        self.start_btn.setEnabled(bool(can_start))

    def _on_question_entries_changed(self, _count: int):
        self._refresh_entry_table()
        self._sync_start_button_state()

    def _on_parse_clicked(self):
        url = self.url_edit.text().strip()
        if not url:
            self._toast("请粘贴问卷链接", "warning")
            return
        # 第一层检测：是否为问卷星域名
        if not self._is_wjx_domain(url):
            self._toast("仅支持问卷星链接", "error")
            return
        # 第二层检测：是否为问卷域名（排除投票和考试）
        if not self._is_survey_domain(url):
            self._toast("不支持投票与考试链接", "error")
            return
        # 使用进度消息条显示解析状态，duration=-1 表示不自动关闭
        self._toast("正在解析问卷...", "info", duration=-1, show_progress=True)
        self._open_wizard_after_parse = True
        self.controller.parse_survey(url)

    def _on_survey_parsed(self, info: list, title: str):
        """问卷解析成功的处理（仅负责关闭进度条和提示，向导弹出由 MainWindow 处理）"""
        # 关闭进度消息条
        if self._progress_infobar:
            try:
                self._progress_infobar.close()
            except Exception as exc:
                log_suppressed_exception("_on_survey_parsed: self._progress_infobar.close()", exc, level=logging.WARNING)
            self._progress_infobar = None

        # 显示解析成功消息
        count = len(info) if info else 0
        self._toast(f"解析成功，已识别 {count} 个题目", "success", duration=2500)

    def _on_survey_parse_failed(self, error_msg: str):
        """问卷解析失败的处理"""
        # 关闭进度消息条
        if self._progress_infobar:
            try:
                self._progress_infobar.close()
            except Exception as exc:
                log_suppressed_exception("_on_survey_parse_failed: self._progress_infobar.close()", exc, level=logging.WARNING)
            self._progress_infobar = None

        text = str(error_msg or "").strip()
        if "问卷已暂停" in text:
            self._toast("问卷已暂停，需要前往问卷星后台重新发布", "warning", duration=4500)
        else:
            # 显示解析失败消息
            self._toast(f"解析失败：{text or '请确认链接有效且网络正常'}", "error", duration=3000)
        self._open_wizard_after_parse = False

    @staticmethod
    def _is_wjx_domain(url: str) -> bool:
        """前端轻量域名白名单：wjx.top、wjx.cn、wjx.com 及其子域。"""
        if not url:
            return False
        text = str(url).strip()
        if not text:
            return False
        candidate = text if "://" in text else f"http://{text}"
        try:
            from urllib.parse import urlparse
            parsed = urlparse(candidate)
        except Exception:
            return False
        host = (parsed.netloc or "").split(":", 1)[0].lower()
        # 支持 wjx.top、wjx.cn、wjx.com 及其子域名
        allowed_domains = ["wjx.top", "wjx.cn", "wjx.com"]
        for domain in allowed_domains:
            if host == domain or host.endswith(f".{domain}"):
                return True
        return False

    @staticmethod
    def _is_survey_domain(url: str) -> bool:
        """检查是否为问卷域名（仅允许 v.wjx.cn、www.wjx.cn 及其子域）。"""
        if not url:
            return False
        text = str(url).strip()
        if not text:
            return False
        candidate = text if "://" in text else f"http://{text}"
        try:
            from urllib.parse import urlparse
            parsed = urlparse(candidate)
        except Exception:
            return False
        host = (parsed.netloc or "").split(":", 1)[0].lower()
        # 白名单：只接受 v.wjx.cn、www.wjx.cn 及其子域名
        return host in ("v.wjx.cn", "www.wjx.cn") or host.endswith(".v.wjx.cn")

    def _on_show_config_list(self):
        try:
            self.config_drawer.open_drawer()
        except Exception as exc:
            self._toast(f"无法打开配置列表：{exc}", "error")

    def _on_load_config(self):
        configs_dir = os.path.join(get_runtime_directory(), "configs")
        if not os.path.exists(configs_dir):
            os.makedirs(configs_dir, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(self, "载入配置", configs_dir, "JSON 文件 (*.json);;所有文件 (*.*)")
        if not path:
            return
        self._load_config_from_path(path)

    def _load_config_from_path(self, path: str):
        if not path:
            return
        if not os.path.exists(path):
            self._toast("文件不存在，可能已被删除", "warning")
            return
        try:
            cfg = self.controller.load_saved_config(path, strict=True)
        except Exception as exc:
            logging.error("手动载入配置失败: %s", exc, exc_info=True)
            self._toast(f"载入失败：{exc}", "error")
            return
        # 应用到界面
        self.runtime_page.apply_config(cfg)
        self.apply_config(cfg)
        self.question_page.set_entries(cfg.question_entries or [], cfg.questions_info or [])
        self.answer_rules_page.set_questions_info(cfg.questions_info or [])
        self._refresh_entry_table()
        try:
            self.update_question_meta(cfg.survey_title or "", len(cfg.question_entries or []))
        except Exception as exc:
            log_suppressed_exception("_load_config_from_path: self.update_question_meta(...)", exc, level=logging.WARNING)
        self._sync_start_button_state()
        refresh_ip_counter_display(self.controller.adapter)
        self._toast("已载入配置", "success")

    def _on_save_config(self):
        cfg = self._build_config()
        # 序列化过滤 UI 组件
        from wjx.utils.io.load_save import serialize_question_entry, deserialize_question_entry
        cfg.question_entries = [deserialize_question_entry(serialize_question_entry(entry)) for entry in self.question_page.get_entries()]
        cfg.questions_info = list(self.question_page.questions_info or [])
        self.controller.config = cfg
        configs_dir = os.path.join(get_runtime_directory(), "configs")
        os.makedirs(configs_dir, exist_ok=True)
        default_name = build_default_config_filename(self._survey_title)
        default_path = os.path.join(configs_dir, default_name)
        path, _ = QFileDialog.getSaveFileName(self, "保存配置", default_path, "JSON 文件 (*.json);;所有文件 (*.*)")
        if not path:
            return
        try:
            self.controller.save_current_config(path)
            self._toast("配置已保存", "success")
        except Exception as exc:
            self._toast(f"保存失败：{exc}", "error")

    def _on_start_clicked(self):
        if getattr(self.controller, "running", False):
            if self._completion_notified:
                self._pending_restart = True
                self.controller.stop_run()
                self._toast("正在重新开始，请稍候...", "info", 1200)
            return

        cfg = self._build_config()
        from wjx.utils.io.load_save import serialize_question_entry, deserialize_question_entry
        cfg.question_entries = [deserialize_question_entry(serialize_question_entry(entry)) for entry in self.question_page.get_entries()]
        cfg.questions_info = list(self.question_page.questions_info or [])
        if not cfg.question_entries:
            self._toast("未配置任何题目，无法开始执行（请先在'题目配置'页添加/配置题目）", "warning")
            self._sync_start_button_state(running=False)
            return
        # 只有在任务完成后的重新开始才重置进度，暂停后继续不重置
        if self._completion_notified or self._last_progress >= 100:
            self.progress_bar.setValue(0)
            self.progress_pct.setText("0%")
            self._last_progress = 0
            self._completion_notified = False
            if cfg.random_ip_enabled:
                self.status_label.setText(f"已提交 0/{cfg.target} 份 | 提交连续失败 0 次 | 代理异常 0/5 次")
            else:
                self.status_label.setText(f"已提交 0/{cfg.target} 份 | 提交连续失败 0 次")
        self.controller.start_run(cfg)

    def update_question_meta(self, title: str, count: int):
        self.count_label.setText(f"{count} 题")
        self.title_label.setText(title or "已配置的题目")
        self._survey_title = title or ""
        self._refresh_entry_table()
        self._sync_start_button_state()
        self._refresh_ip_cost_infobar()

    def apply_config(self, cfg: RuntimeConfig):
        self.url_edit.setText(cfg.url)
        self.target_spin.setValue(max(1, int(cfg.target or 1)))
        self.thread_spin.setValue(max(1, int(cfg.threads or 1)))
        # 阻塞信号避免加载配置时触发弹窗或多余同步
        self.random_ip_cb.blockSignals(True)
        self.random_ip_cb.setChecked(bool(cfg.random_ip_enabled))
        self.random_ip_cb.blockSignals(False)

        try:
            self.answer_rules_page.set_rules(getattr(cfg, "answer_rules", []) or [])
        except Exception as exc:
            log_suppressed_exception("apply_config: self.answer_rules_page.set_rules(...)", exc, level=logging.WARNING)

        self._refresh_entry_table()
        self._sync_start_button_state()

    def _go_to_runtime_page(self):
        main_win = self.window()
        if hasattr(main_win, "switchTo") and hasattr(main_win, "runtime_page"):
            main_win.switchTo(main_win.runtime_page)

    def _go_to_runtime_answer_duration(self):
        self._go_to_runtime_page()
        try:
            if hasattr(self.runtime_page, "focus_answer_duration_setting"):
                self.runtime_page.focus_answer_duration_setting()
        except Exception as exc:
            log_suppressed_exception("_go_to_runtime_answer_duration", exc, level=logging.WARNING)

    def _build_config(self) -> RuntimeConfig:
        cfg = RuntimeConfig()
        cfg.url = self.url_edit.text().strip()
        cfg.survey_title = str(self._survey_title or "")
        self.runtime_page.update_config(cfg)
        cfg.target = max(1, self.target_spin.value())
        cfg.threads = max(1, self.thread_spin.value())
        cfg.random_ip_enabled = self.random_ip_cb.isChecked()
        cfg.answer_rules = list(self.answer_rules_page.get_rules() or [])
        return cfg

    def _toast(self, text: str, level: str = "info", duration: int = 2000, show_progress: bool = False):
        """显示消息提示"""
        # 如果之前有进度消息条正在显示，先关闭它
        if self._progress_infobar:
            try:
                self._progress_infobar.close()
            except Exception as exc:
                log_suppressed_exception("_toast: self._progress_infobar.close()", exc, level=logging.WARNING)
            self._progress_infobar = None
        
        parent = self.window() or self
        kind = level.lower()
        
        # 如果需要显示进度条，创建带进度条的InfoBar
        if show_progress:
            # 创建InfoBar实例
            if kind == "success":
                infobar = InfoBar.success("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)
            elif kind == "warning":
                infobar = InfoBar.warning("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)
            elif kind == "error":
                infobar = InfoBar.error("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)
            else:
                infobar = InfoBar.info("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)
            
            # 添加转圈的加载动画
            spinner = IndeterminateProgressRing()
            spinner.setFixedSize(20, 20)  # 设置spinner大小
            spinner.setStrokeWidth(3)  # 设置环的粗细
            infobar.addWidget(spinner)
            
            # 保存引用以便后续关闭
            self._progress_infobar = infobar
            return infobar
        else:
            # 普通InfoBar（不带进度条）
            if kind == "success":
                InfoBar.success("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)
            elif kind == "warning":
                InfoBar.warning("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)
            elif kind == "error":
                InfoBar.error("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)
            else:
                InfoBar.info("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)
            return None

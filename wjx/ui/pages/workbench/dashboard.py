"""主控制面板：卡片式配置区 + 底部状态条（不包含日志）"""
import os
import copy
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
    StrongBodyLabel,
    CardWidget,
    PushButton,
    PrimaryPushButton,
    TableWidget,
    LineEdit,
    CheckBox,
    ProgressBar,
    IndeterminateProgressRing,
    CommandBar,
    Action,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    InfoBarIcon,
    HyperlinkButton,
    MessageBox,
)
from qfluentwidgets import RoundMenu

from wjx.ui.pages.workbench.dashboard_parts.clipboard import DashboardClipboardMixin
from wjx.ui.pages.workbench.dashboard_parts.entries import DashboardEntriesMixin
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
    QWidget,
):
    """主页：左侧配置 + 底部状态，不再包含日志。"""

    _ipBalanceChecked = Signal(int)  # 发送剩余IP数信号
    _debugResetFinished = Signal(object)  # 后台 reset 完成后回传结果

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
        self._ip_low_infobar_dismissed = False
        self._ip_low_threshold = 5000
        self._api_balance_cache: Optional[float] = None  # 缓存 API 余额
        self._ip_balance_fetch_lock = threading.Lock()
        self._ip_balance_fetching = False
        self._last_ip_balance_fetch_ts = 0.0
        self._ip_balance_fetch_interval_sec = 30.0
        self._debug_reset_in_progress = False
        self._clipboard_parse_ticket = 0
        self._build_ui()
        self.config_drawer = ConfigDrawer(self, self._load_config_from_path)
        self._bind_events()
        self._sync_start_button_state()

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
            content="随机IP剩余不足 5000，请提醒开发者及时充值",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.NONE,
            duration=-1,
            parent=inner,
        )
        self._ip_low_infobar.hide()
        self._ip_low_infobar.closeButton.clicked.connect(self._on_ip_low_infobar_closed)
        self._ip_low_contact_link = HyperlinkButton(FluentIcon.LINK, "", "前往联系", self._ip_low_infobar)
        self._ip_low_contact_link.clicked.connect(lambda: self._open_contact_dialog(default_type="报错反馈"))
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
        self.more_settings_btn = HyperlinkButton(FluentIcon.SETTING, "", "前往“运行参数”页仔细调整", self)
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
        spin_row.addWidget(BodyLabel("并发数（提交速度）：", self))
        self.thread_spin = NoWheelSpinBox(self)
        self.thread_spin.setRange(1, 8)
        self.thread_spin.setMinimumWidth(140)
        self.thread_spin.setMinimumHeight(36)
        spin_row.addWidget(self.thread_spin)
        spin_row.addStretch(1)
        exec_layout.addLayout(spin_row)

        self.random_ua_cb = CheckBox("启用随机 UA（模拟微信/PC浏览器访问）", self)
        exec_layout.addWidget(self.random_ua_cb)

        self.random_ip_cb = CheckBox("启用随机 IP 提交（在触发智能验证时开启）", self)
        exec_layout.addWidget(self.random_ip_cb)
        ip_row = QHBoxLayout()
        ip_row.setSpacing(8)
        ip_row.addWidget(BodyLabel("随机IP计数：", self))
        self.random_ip_hint = BodyLabel("--/--", self)
        ip_row.addWidget(self.random_ip_hint)
        ip_row.addSpacing(4)
        self.card_btn = PushButton("解锁大额IP", self, FluentIcon.FINGERPRINT)
        ip_row.addWidget(self.card_btn)
        ip_row.addStretch(1)
        exec_layout.addLayout(ip_row)
        layout.addWidget(exec_card)

        list_card = CardWidget(self)
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(12, 12, 12, 12)
        list_layout.setSpacing(8)
        title_row = QHBoxLayout()
        self.title_label = SubtitleLabel("题目清单与操作", self)
        self.count_label = BodyLabel("0 题", self)
        self.count_label.setStyleSheet("color: #6b6b6b;")
        title_row.addWidget(self.title_label)
        title_row.addStretch(1)
        title_row.addWidget(self.count_label)
        list_layout.addLayout(title_row)
        # 使用 CommandBar 替代普通按钮布局
        self.command_bar = CommandBar(self)
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
        
        # 分隔符
        self.command_bar.addSeparator()
        
        # 全选（可勾选）
        self.select_all_action = Action(FluentIcon.CHECKBOX, "全选", checkable=True)
        self.command_bar.addAction(self.select_all_action)
        
        list_layout.addWidget(self.command_bar)
        self.entry_table = TableWidget(self)
        self.entry_table.setRowCount(0)
        self.entry_table.setColumnCount(3)
        self.entry_table.setHorizontalHeaderLabels(["选择", "类型", "策略"])
        self.entry_table.verticalHeader().setVisible(False)
        self.entry_table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.entry_table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.entry_table.setAlternatingRowColors(True)
        self.entry_table.setMinimumHeight(360)
        # 设置列宽策略：前2列固定宽度，最后一列自动拉伸填充剩余空间
        header = self.entry_table.horizontalHeader()
        header.setSectionResizeMode(0, header.ResizeMode.Fixed)
        header.setSectionResizeMode(1, header.ResizeMode.Fixed)
        header.setSectionResizeMode(2, header.ResizeMode.Stretch)
        self.entry_table.setColumnWidth(0, 100)
        self.entry_table.setColumnWidth(1, 180)
        list_layout.addWidget(self.entry_table)
        layout.addWidget(list_card, 1)

        layout.addStretch(1)
        outer.addWidget(scroll, 1)

        bottom = CardWidget(self)
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(12, 10, 12, 10)
        bottom_layout.setSpacing(10)
        self.status_label = StrongBodyLabel("等待配置...", self)
        self.progress_bar = ProgressBar(self)
        self.progress_bar.setValue(0)
        self.progress_pct = StrongBodyLabel("0%", self)
        self.progress_pct.setMinimumWidth(50)
        self.progress_pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_pct.setStyleSheet("font-size: 13px; font-weight: bold;")
        self.start_btn = PrimaryPushButton("开始执行", self)
        self.resume_btn = PrimaryPushButton("继续", self)
        self.resume_btn.setEnabled(False)
        self.resume_btn.hide()
        self.stop_btn = PushButton("停止", self)
        self.stop_btn.setEnabled(False)
        self.start_btn.setToolTip("请先配置题目（至少 1 题）")
        bottom_layout.addWidget(self.status_label)
        bottom_layout.addWidget(self.progress_bar, 1)
        bottom_layout.addWidget(self.progress_pct)
        bottom_layout.addWidget(self.start_btn)
        bottom_layout.addWidget(self.resume_btn)
        bottom_layout.addWidget(self.stop_btn)
        outer.addWidget(bottom)

    def _bind_events(self):
        self.parse_btn.clicked.connect(self._on_parse_clicked)
        self.config_list_btn.clicked.connect(self._on_show_config_list)
        self.load_cfg_btn.clicked.connect(self._on_load_config)
        self.save_cfg_btn.clicked.connect(self._on_save_config)
        self.qr_btn.clicked.connect(self._on_qr_clicked)
        self.start_btn.clicked.connect(self._on_start_clicked)
        self.resume_btn.clicked.connect(self._on_resume_clicked)
        self.stop_btn.clicked.connect(lambda: self.controller.stop_run())
        self.target_spin.valueChanged.connect(lambda v: self.runtime_page.target_spin.setValue(int(v)))
        self.thread_spin.valueChanged.connect(lambda v: self.runtime_page.thread_spin.setValue(int(v)))
        self.random_ip_cb.stateChanged.connect(self._on_random_ip_toggled)
        self.random_ua_cb.stateChanged.connect(self._on_random_ua_toggled)
        self.card_btn.clicked.connect(self._on_card_code_clicked)
        self.more_settings_btn.clicked.connect(self._go_to_runtime_page)
        # 监听问卷链接输入框的文本变化（用于检测 reset 命令）
        self.url_edit.textChanged.connect(self._on_url_text_changed)
        # 监听剪贴板变化，自动处理粘贴的图片
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.dataChanged.connect(self._on_clipboard_changed)
        # CommandBar Actions
        self.select_all_action.triggered.connect(self._toggle_select_all_action)
        self.add_action.triggered.connect(self._show_add_question_dialog)
        self.edit_action.triggered.connect(self._edit_selected_entries)
        self.del_action.triggered.connect(self._delete_selected_entries)
        # 连接问卷解析信号
        self.controller.surveyParsed.connect(self._on_survey_parsed)
        self.controller.surveyParseFailed.connect(self._on_survey_parse_failed)
        # 连接 IP 余额检查信号
        self._ipBalanceChecked.connect(self._on_ip_balance_checked)
        self._debugResetFinished.connect(self._on_debug_reset_finished)
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
            return bool(self.question_page.table.rowCount())
        except Exception:
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
        
        # 显示解析失败消息
        self._toast(f"解析失败：{error_msg}", "error", duration=3000)
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
        """检查是否为问卷域名（v.wjx.cn 及其子域），排除投票和考试链接。"""
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
        # 只接受 v.wjx.cn 及其子域名（问卷链接）
        return bool(host == "v.wjx.cn" or host.endswith(".v.wjx.cn"))

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
            cfg = self.controller.load_saved_config(path)
        except Exception as exc:
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
        # 运行时使用深拷贝，避免执行过程污染用户配置
        cfg.question_entries = [copy.deepcopy(entry) for entry in self.question_page.get_entries()]
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
        cfg.question_entries = list(self.question_page.get_entries())
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
            self.status_label.setText(f"已提交 0/{cfg.target} 份 | 失败 0 次")
        self.controller.start_run(cfg)

    def update_status(self, text: str, current: int, target: int):
        self.status_label.setText(text)
        progress = 0
        if target > 0:
            progress = min(100, int((current / max(target, 1)) * 100))
        self.progress_bar.setValue(progress)
        self.progress_pct.setText(f"{progress}%")
        self._last_progress = progress
        if (
            target > 0
            and current >= target
            and not self._completion_notified
        ):
            self._completion_notified = True
            self._toast("全部份数已完成", "success", duration=5000)
            self.stop_btn.setEnabled(False)
            self.start_btn.setEnabled(True)
            self.start_btn.setText("重新开始")

    def on_run_state_changed(self, running: bool):
        self._sync_start_button_state(running=running)
        self.stop_btn.setEnabled(running)
        if not running:
            self.resume_btn.setEnabled(False)
            self.resume_btn.hide()
        if running:
            self._completion_notified = False
            self.start_btn.setText("执行中...")
            self.start_btn.setEnabled(False)
            self._toast("已启动任务", "success", 1500)
        else:
            # 停止后根据进度调整按钮提示
            if self._completion_notified or self._last_progress >= 100:
                self.start_btn.setText("重新开始")
            else:
                self.start_btn.setText("开始执行")
            self.start_btn.setEnabled(self._has_question_entries())
            self.stop_btn.setEnabled(False)
            if not self._completion_notified:
                self._show_end_toast_after_cleanup = True
            if self._pending_restart:
                self._pending_restart = False
                self._on_start_clicked()

    def on_cleanup_finished(self):
        if self._show_end_toast_after_cleanup:
            self._show_end_toast_after_cleanup = False
            self._toast("任务结束", "info", 1500)

    def on_pause_state_changed(self, paused: bool, reason: str = ""):
        self._last_pause_reason = str(reason or "")
        if not getattr(self.controller, "running", False):
            self.resume_btn.setEnabled(False)
            self.resume_btn.hide()
            return
        if paused:
            self.resume_btn.show()
            self.resume_btn.setEnabled(True)
            msg = f"已暂停：{reason}" if reason else "已暂停"
            self._toast(msg, "warning", 2200)
        else:
            self.resume_btn.setEnabled(False)
            self.resume_btn.hide()
            self._toast("已继续执行", "success", 1500)

    def _on_resume_clicked(self):
        if not getattr(self.controller, "running", False):
            return
        reason = str(self._last_pause_reason or "")
        if "扣费" in reason or ("代理" in reason and "连续" in reason):
            box = MessageBox(
                "继续执行？",
                "当前处于“代理不可用保护暂停”状态。\n继续执行会重新请求代理并产生费用，确定继续吗？",
                self.window() or self,
            )
            box.yesButton.setText("继续执行")
            box.cancelButton.setText("取消")
            if not box.exec():
                return
        self.controller.resume_run()

    def update_question_meta(self, title: str, count: int):
        self.count_label.setText(f"{count} 题")
        self.title_label.setText(title or "已配置的题目")
        self._survey_title = title or ""
        self._refresh_entry_table()
        self._sync_start_button_state()

    def apply_config(self, cfg: RuntimeConfig):
        self.url_edit.setText(cfg.url)
        self.target_spin.setValue(max(1, int(cfg.target or 1)))
        self.thread_spin.setValue(max(1, int(cfg.threads or 1)))
        # 阻塞信号避免加载配置时触发弹窗或多余同步
        self.random_ip_cb.blockSignals(True)
        self.random_ip_cb.setChecked(bool(cfg.random_ip_enabled))
        self.random_ip_cb.blockSignals(False)

        self.random_ua_cb.blockSignals(True)
        self.random_ua_cb.setChecked(bool(cfg.random_ua_enabled))
        self.random_ua_cb.blockSignals(False)

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

    def _on_random_ua_toggled(self, state: int):
        is_checked = (state == Qt.CheckState.Checked.value)
        try:
            self.runtime_page.random_ua_switch.blockSignals(True)
            self.runtime_page.random_ua_switch.setChecked(is_checked)
            self.runtime_page.random_ua_switch.blockSignals(False)
            if hasattr(self.runtime_page, "_sync_random_ua"):
                self.runtime_page._sync_random_ua(is_checked)
        except Exception as exc:
            log_suppressed_exception("_on_random_ua_toggled dashboard", exc, level=logging.WARNING)

    def _build_config(self) -> RuntimeConfig:
        cfg = RuntimeConfig()
        cfg.url = self.url_edit.text().strip()
        cfg.survey_title = str(self._survey_title or "")
        self.runtime_page.update_config(cfg)
        cfg.target = max(1, self.target_spin.value())
        cfg.threads = max(1, self.thread_spin.value())
        cfg.random_ip_enabled = self.random_ip_cb.isChecked()
        cfg.random_ua_enabled = self.random_ua_cb.isChecked()
        cfg.answer_rules = list(self.answer_rules_page.get_rules() or [])
        return cfg

    def _toast(self, text: str, level: str = "info", duration: int = 2000, show_progress: bool = False):
        """
        显示消息提示
        
        Args:
            text: 消息内容
            level: 消息级别 (info/success/warning/error)
            duration: 显示时长（毫秒），-1 表示不自动关闭
            show_progress: 是否显示进度条（适用于耗时操作）
        """
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


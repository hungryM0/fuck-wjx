"""主控制面板：卡片式配置区 + 底部状态条（不包含日志）"""
import os
import copy
import threading
import time
from typing import List, Dict, Any, Optional
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception


from PySide6.QtCore import Qt, QObject, QEvent, Signal
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QDialog,
    QTableWidgetItem,
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
    ComboBox,
    MessageBox,
)
from qfluentwidgets import RoundMenu

from wjx.ui.widgets import ConfigDrawer
from wjx.ui.widgets.full_width_infobar import FullWidthInfoBar
from wjx.ui.widgets.no_wheel import NoWheelSlider, NoWheelSpinBox
from wjx.ui.controller import RunController
from wjx.ui.dialogs.card_unlock import CardUnlockDialog
from wjx.ui.dialogs.contact import ContactDialog
from wjx.ui.pages.workbench.question import QuestionPage, QuestionWizardDialog, TYPE_CHOICES, STRATEGY_CHOICES, _get_entry_type_label
from wjx.ui.pages.workbench.runtime import RuntimePage
from wjx.utils.io.load_save import RuntimeConfig, build_default_config_filename, get_runtime_directory
from wjx.utils.io.qrcode_utils import decode_qrcode
from wjx.core.questions.config import QuestionEntry, configure_probabilities
from wjx.utils.app.config import DEFAULT_FILL_TEXT
from wjx.utils.system.registry_manager import RegistryManager
from wjx.network.proxy import (
    get_status,
    _format_status_payload,
    on_random_ip_toggle,
    refresh_ip_counter_display,
    _validate_card,
    get_random_ip_counter_snapshot_local,
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


def _question_summary(entry: QuestionEntry) -> str:
    """生成题目配置摘要"""
    if entry.question_type in ("text", "multi_text"):
        texts = entry.texts or []
        if texts:
            summary = f"答案: {' | '.join(texts[:2])}"
            if len(texts) > 2:
                summary += f" (+{len(texts)-2})"
            if entry.question_type == "text" and getattr(entry, "ai_enabled", False):
                summary += " | AI"
            return summary
        summary = "答案: 无"
        if entry.question_type == "text" and getattr(entry, "ai_enabled", False):
            summary += " | AI"
        return summary
    if entry.question_type == "matrix":
        rows = max(1, int(entry.rows or 1))
        cols = max(1, int(entry.option_count or 1))
        if isinstance(entry.custom_weights, list) or isinstance(entry.probabilities, list):
            return f"{rows} 行 × {cols} 列 - 按行配比"
        return f"{rows} 行 × {cols} 列 - 完全随机"
    if entry.question_type == "order":
        return "排序题 - 自动随机排序"
    elif entry.custom_weights:
        weights = entry.custom_weights
        if entry.question_type == "multiple":
            summary = f"自定义概率: {','.join(f'{int(w)}%' for w in weights[:4])}"
        else:
            summary = f"自定义配比: {','.join(str(int(w)) for w in weights[:4])}"
        if len(weights) > 4:
            summary += "..."
        return summary
    else:
        strategy = entry.distribution_mode or "random"
        if strategy not in ("random", "custom"):
            strategy = "random"
        if getattr(entry, "probabilities", None) == -1:
            strategy = "random"
        if entry.question_type == "multiple":
            return "完全随机" if strategy == "random" else "自定义概率"
        return "完全随机" if strategy == "random" else "自定义配比"


class DashboardPage(QWidget):
    """主页：左侧配置 + 底部状态，不再包含日志。"""

    _ipBalanceChecked = Signal(int)  # 发送剩余IP数信号
    _debugResetFinished = Signal(object)  # 后台 reset 完成后回传结果

    def __init__(self, controller: RunController, question_page: QuestionPage, runtime_page: RuntimePage, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.controller = controller
        self.question_page = question_page
        self.runtime_page = runtime_page
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

        link_card = CardWidget(self)
        link_layout = QVBoxLayout(link_card)
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
        self.url_edit.setPlaceholderText("在此处输入问卷链接")
        self.url_edit.setClearButtonEnabled(True)
        # 仅问卷链接输入框需要 qfluentwidgets 风格的“粘贴”单项菜单
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
        layout.addWidget(link_card)

        exec_card = CardWidget(self)
        exec_layout = QVBoxLayout(exec_card)
        exec_layout.setContentsMargins(12, 12, 12, 12)
        exec_layout.setSpacing(10)
        exec_layout.addWidget(SubtitleLabel("执行设置", self))

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
        self.thread_spin.setRange(1, 12)
        self.thread_spin.setMinimumWidth(140)
        self.thread_spin.setMinimumHeight(36)
        spin_row.addWidget(self.thread_spin)
        spin_row.addStretch(1)
        exec_layout.addLayout(spin_row)

        self.random_ip_cb = CheckBox("启用随机 IP 提交", self)
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
        self.card_btn.clicked.connect(self._on_card_code_clicked)
        # 监听问卷链接输入框的文本变化（用于检测 reset 命令）
        self.url_edit.textChanged.connect(self._on_url_text_changed)
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

    def _on_url_text_changed(self, text: str):
        """监听问卷链接输入框文本变化，检测 reset 命令（仅调试模式下可用）"""
        if text.strip().lower() != "reset":
            return

        # 检查是否启用了调试模式
        from PySide6.QtCore import QSettings
        from wjx.utils.app.config import get_bool_from_qsettings

        settings = QSettings("FuckWjx", "Settings")
        debug_mode = get_bool_from_qsettings(settings.value("debug_mode"), False)
        if not debug_mode:
            return

        if self._debug_reset_in_progress:
            self.url_edit.clear()
            return

        self._debug_reset_in_progress = True
        self.url_edit.clear()
        self._toast("正在后台重置随机IP额度...", "info", duration=-1, show_progress=True)

        thread = threading.Thread(
            target=self._run_debug_reset_worker,
            daemon=True,
            name="DebugResetWorker",
        )
        thread.start()

    def _run_debug_reset_worker(self) -> None:
        """后台执行 debug reset，避免阻塞 GUI。"""
        from wjx.network.proxy import _get_default_quota_with_cache

        payload: Dict[str, Any] = {"ok": False, "quota": None, "error": ""}
        try:
            default_quota = _get_default_quota_with_cache()
            if default_quota is None:
                payload["error"] = "default_quota_unavailable"
                return

            RegistryManager.write_submit_count(0)
            RegistryManager.write_quota_limit(default_quota)
            RegistryManager.set_card_verified(False)
            payload["ok"] = True
            payload["quota"] = int(default_quota)
        except Exception as exc:
            payload["error"] = str(exc)
            log_suppressed_exception("dashboard._run_debug_reset_worker", exc, level=logging.WARNING)
        finally:
            self._debugResetFinished.emit(payload)

    def _on_debug_reset_finished(self, payload: Any) -> None:
        self._debug_reset_in_progress = False
        data = payload if isinstance(payload, dict) else {}
        success = bool(data.get("ok"))
        quota = data.get("quota")

        if not success:
            logging.warning("调试重置：默认额度API不可用，保持 --/-- 状态")
            refresh_ip_counter_display(self.controller.adapter)
            self._toast("默认额度API不可用，随机IP额度保持未初始化（--/--）", "warning", duration=3000)
            return

        refresh_ip_counter_display(self.controller.adapter)
        self._toast(f"已重置随机IP额度为 0/{quota}", "success", duration=2500)

    def _on_parse_clicked(self):
        url = self.url_edit.text().strip()
        if not url:
            self._toast("请粘贴问卷链接", "warning")
            return
        if not self._is_wjx_domain(url):
            self._toast("仅支持问卷星链接", "error")
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
        """前端轻量域名白名单：wjx.cn 及其子域。"""
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
        return bool(host == "wjx.cn" or host.endswith(".wjx.cn"))

    def _on_show_config_list(self):
        try:
            self.config_drawer.open_drawer()
        except Exception as exc:
            self._toast(f"无法打开配置列表：{exc}", "error")

    def _on_qr_clicked(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择二维码图片", get_runtime_directory(), "含有二维码的图片 (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        url = decode_qrcode(path)
        if not url:
            self._toast("未能识别二维码中的链接", "error")
            return
        self.url_edit.setText(url)
        self._on_parse_clicked()

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
        try:
            configure_probabilities(cfg.question_entries)
        except Exception as exc:
            self._toast(str(exc), "error")
            return
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
        # 阻塞信号避免加载配置时触发弹窗
        self.random_ip_cb.blockSignals(True)
        self.random_ip_cb.setChecked(bool(cfg.random_ip_enabled))
        self.random_ip_cb.blockSignals(False)
        self._refresh_entry_table()
        self._sync_start_button_state()

    def _build_config(self) -> RuntimeConfig:
        cfg = RuntimeConfig()
        cfg.url = self.url_edit.text().strip()
        cfg.survey_title = str(self._survey_title or "")
        self.runtime_page.update_config(cfg)
        cfg.target = max(1, self.target_spin.value())
        cfg.threads = max(1, self.thread_spin.value())
        cfg.random_ip_enabled = self.random_ip_cb.isChecked()
        return cfg

    def update_random_ip_counter(self, count: int, limit: int, custom_api: bool):
        # 检查是否已验证过卡密
        is_verified = RegistryManager.is_card_verified()
        if is_verified:
            self.card_btn.setEnabled(False)
            self.card_btn.setText("已解锁")
        else:
            self.card_btn.setEnabled(True)
            self.card_btn.setText("解锁大额IP")

        if custom_api:
            self.random_ip_hint.setText("自定义接口")
            self.random_ip_hint.setStyleSheet("color:#ff8c00;")
            self._update_ip_low_infobar(count, limit, custom_api)
            return
        if limit <= 0:
            self.random_ip_hint.setText("--/--")
            self.random_ip_hint.setStyleSheet("color:#6b6b6b;")
            self._update_ip_low_infobar(count, limit, custom_api)
            if self.random_ip_cb.isChecked():
                self.random_ip_cb.blockSignals(True)
                self.random_ip_cb.setChecked(False)
                self.random_ip_cb.blockSignals(False)
            return
        self.random_ip_hint.setText(f"{count}/{limit}")
        # 额度耗尽时变红
        if count >= limit:
            self.random_ip_hint.setStyleSheet("color:red;")
        else:
            self.random_ip_hint.setStyleSheet("color:#6b6b6b;")
        self._update_ip_low_infobar(count, limit, custom_api)
        # 达到上限时自动关闭随机IP开关
        if count >= limit and self.random_ip_cb.isChecked():
            self.random_ip_cb.blockSignals(True)
            self.random_ip_cb.setChecked(False)
            self.random_ip_cb.blockSignals(False)
            try:
                self.runtime_page.random_ip_switch.blockSignals(True)
                self.runtime_page.random_ip_switch.setChecked(False)
                self.runtime_page.random_ip_switch.blockSignals(False)
            except Exception as exc:
                log_suppressed_exception("update_random_ip_counter: self.runtime_page.random_ip_switch.blockSignals(True)", exc, level=logging.WARNING)

    def _on_random_ip_toggled(self, state: int):
        enabled = state != 0
        # 先同步检查限制，防止快速点击绕过
        if enabled:
            count, limit, custom_api = get_random_ip_counter_snapshot_local()
            if (not custom_api) and limit <= 0:
                self._toast("随机IP额度不可用（本地未初始化且默认额度API不可用）", "warning")
                self.random_ip_cb.blockSignals(True)
                self.random_ip_cb.setChecked(False)
                self.random_ip_cb.blockSignals(False)
                try:
                    self.runtime_page.random_ip_switch.blockSignals(True)
                    self.runtime_page.random_ip_switch.setChecked(False)
                    self.runtime_page.random_ip_switch.blockSignals(False)
                except Exception as exc:
                    log_suppressed_exception("_on_random_ip_toggled disable: runtime random_ip_switch sync", exc, level=logging.WARNING)
                refresh_ip_counter_display(self.controller.adapter)
                return
            if (not custom_api) and count >= limit:
                self._toast(f"随机IP已达{limit}份限制，请验证卡密后再启用。", "warning")
                self.random_ip_cb.blockSignals(True)
                self.random_ip_cb.setChecked(False)
                self.random_ip_cb.blockSignals(False)
                try:
                    self.runtime_page.random_ip_switch.blockSignals(True)
                    self.runtime_page.random_ip_switch.setChecked(False)
                    self.runtime_page.random_ip_switch.blockSignals(False)
                except Exception as exc:
                    log_suppressed_exception("_on_random_ip_toggled: self.runtime_page.random_ip_switch.blockSignals(True)", exc, level=logging.WARNING)
                return
        try:
            self.controller.adapter.random_ip_enabled_var.set(bool(enabled))
            on_random_ip_toggle(self.controller.adapter)
            enabled = bool(self.controller.adapter.random_ip_enabled_var.get())
        except Exception:
            enabled = bool(enabled)
        self.random_ip_cb.blockSignals(True)
        self.random_ip_cb.setChecked(enabled)
        self.random_ip_cb.blockSignals(False)
        try:
            self.runtime_page.random_ip_switch.blockSignals(True)
            self.runtime_page.random_ip_switch.setChecked(enabled)
            self.runtime_page.random_ip_switch.blockSignals(False)
        except Exception as exc:
            log_suppressed_exception("_on_random_ip_toggled: self.runtime_page.random_ip_switch.blockSignals(True)", exc, level=logging.WARNING)
        # 刷新计数显示
        refresh_ip_counter_display(self.controller.adapter)

    def _ask_card_code(self) -> Optional[str]:
        """向主窗口请求卡密输入，兜底弹出输入框。"""
        win = self.window()
        if hasattr(win, "_ask_card_code"):
            try:
                return win._ask_card_code()  # type: ignore[union-attr]
            except Exception as exc:
                log_suppressed_exception("_ask_card_code: return win._ask_card_code()", exc, level=logging.WARNING)
        dialog = CardUnlockDialog(
            self,
            status_fetcher=get_status,
            status_formatter=_format_status_payload,
            contact_handler=lambda: self._open_contact_dialog(default_type="卡密获取"),
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.get_card_code()
        return None

    def _open_contact_dialog(self, default_type: str = "报错反馈"):
        """打开联系对话框"""
        win = self.window()
        if hasattr(win, "_open_contact_dialog"):
            try:
                return win._open_contact_dialog(default_type)  # type: ignore[union-attr]
            except Exception as exc:
                log_suppressed_exception("_open_contact_dialog: return win._open_contact_dialog(default_type)", exc, level=logging.WARNING)
        dlg = ContactDialog(self, default_type=default_type, status_fetcher=get_status, status_formatter=_format_status_payload)
        dlg.exec()

    def _on_card_code_clicked(self):
        """用户主动输入卡密解锁大额随机IP。"""
        dialog = CardUnlockDialog(
            self,
            status_fetcher=get_status,
            status_formatter=_format_status_payload,
            contact_handler=lambda: self._open_contact_dialog(default_type="卡密获取"),
            card_validator=_validate_card,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        # 验证成功后处理解锁逻辑：在原有额度基础上增加卡密提供的额度
        if dialog.get_validation_result():
            quota = dialog.get_validation_quota()
            if quota is None:
                self._toast("卡密验证返回缺少额度信息，拒绝解锁，请联系开发者。", "error")
                return
            quota_to_add = max(1, int(quota))
            # 读取当前额度上限，在此基础上增加
            current_limit = int(RegistryManager.read_quota_limit(0) or 0)
            new_limit = current_limit + quota_to_add
            RegistryManager.write_quota_limit(new_limit)
            # 标记为已验证过卡密
            RegistryManager.set_card_verified(True)
            refresh_ip_counter_display(self.controller.adapter)
            self.random_ip_cb.setChecked(True)
            try:
                self.runtime_page.random_ip_switch.blockSignals(True)
                self.runtime_page.random_ip_switch.setChecked(True)
                self.runtime_page.random_ip_switch.blockSignals(False)
            except Exception as exc:
                log_suppressed_exception("_on_card_code_clicked: self.runtime_page.random_ip_switch.blockSignals(True)", exc, level=logging.WARNING)

    def _on_ip_low_infobar_closed(self):
        self._ip_low_infobar_dismissed = True
        if self._ip_low_infobar:
            self._ip_low_infobar.hide()

    def _update_ip_low_infobar(self, count: int, limit: int, custom_api: bool):
        """更新IP余额不足提示条，基于API余额换算的剩余IP数判断"""
        if not self._ip_low_infobar:
            return
        if custom_api:
            self._ip_low_infobar.hide()
            self._ip_low_infobar_dismissed = False
            return

        # 先用缓存快速更新，避免每次刷新都走网络
        if self._api_balance_cache is not None:
            cached_remaining = int(max(0.0, float(self._api_balance_cache)) / 0.0035)
            self._on_ip_balance_checked(cached_remaining)

        now = time.monotonic()
        with self._ip_balance_fetch_lock:
            # 正在请求或尚未到刷新间隔，直接跳过
            if self._ip_balance_fetching or (now - self._last_ip_balance_fetch_ts) < self._ip_balance_fetch_interval_sec:
                return
            self._ip_balance_fetching = True
            self._last_ip_balance_fetch_ts = now

        # 异步获取 API 余额并判断
        def _fetch_and_check():
            try:
                import wjx.network.http_client as http_client
                response = http_client.get(
                    "https://service.ipzan.com/userProduct-get",
                    params={"no": "20260112572376490874", "userId": "72FH7U4E0IG"},
                    timeout=5,
                )
                data = response.json()
                if data.get("code") in (0, 200) and data.get("status") in (200, "200", None):
                    balance = data.get("data", {}).get("balance", 0)
                    # 使用关于页相同的公式：剩余IP数 = balance / 0.0035
                    remaining_ip = int(float(balance) / 0.0035)
                    self._api_balance_cache = float(balance)
                    # 发送信号到主线程更新 UI
                    self._ipBalanceChecked.emit(remaining_ip)
            except Exception as exc:
                timeout_error_names = {"ReadTimeout", "ConnectTimeout", "PoolTimeout", "TimeoutException"}
                level = logging.DEBUG if exc.__class__.__name__ in timeout_error_names else logging.WARNING
                log_suppressed_exception("_fetch_and_check: API balance fetch failed", exc, level=level)
            finally:
                with self._ip_balance_fetch_lock:
                    self._ip_balance_fetching = False

        # 启动后台线程获取余额
        threading.Thread(target=_fetch_and_check, daemon=True, name="IPBalanceCheck").start()

    def _on_ip_balance_checked(self, remaining_ip: int):
        """处理IP余额检查结果（在主线程中执行）"""
        if not self._ip_low_infobar:
            return
        if remaining_ip < self._ip_low_threshold:
            if not self._ip_low_infobar_dismissed:
                self._ip_low_infobar.show()
        else:
            self._ip_low_infobar.hide()
            self._ip_low_infobar_dismissed = False

    def _show_add_question_dialog(self):
        """新增题目 - 委托给 QuestionPage"""
        self.question_page._add_entry()
        self._refresh_entry_table()

    def _open_question_wizard(self):
        if self._run_question_wizard(self.question_page.entries, self.question_page.questions_info):
            self._refresh_entry_table()

    def _edit_selected_entries(self):
        selected_rows = self._checked_rows()
        if not selected_rows:
            self._toast("请先勾选要编辑的题目", "warning")
            return
        entries = self.question_page.get_entries()
        info = self.question_page.questions_info or []
        selected_rows = [row for row in sorted(set(selected_rows)) if 0 <= row < len(entries)]
        if not selected_rows:
            self._toast("未找到可编辑的题目", "warning")
            return
        selected_entries = [entries[row] for row in selected_rows]
        selected_info = [info[row] if row < len(info) else {} for row in selected_rows]
        if self._run_question_wizard(selected_entries, selected_info):
            self._refresh_entry_table()

    def _apply_wizard_results(self, entries: List[QuestionEntry], dlg: QuestionWizardDialog) -> None:
        def _normalize_weights(raw: Any) -> Any:
            if isinstance(raw, list) and any(isinstance(item, (list, tuple)) for item in raw):
                cleaned: List[List[float]] = []
                for row in raw:
                    if not isinstance(row, (list, tuple)):
                        continue
                    cleaned.append([float(max(0, v)) for v in row])
                return cleaned
            if isinstance(raw, list):
                return [float(max(0, v)) for v in raw]
            return raw

        updates = dlg.get_results()
        for idx, weights in updates.items():
            if 0 <= idx < len(entries):
                entry = entries[idx]
                normalized = _normalize_weights(weights)
                if entry.question_type == "matrix":
                    entry.custom_weights = normalized
                    entry.probabilities = normalized
                    entry.distribution_mode = "custom"
                elif isinstance(normalized, list):
                    entry.custom_weights = normalized
                    entry.probabilities = normalized
                    entry.distribution_mode = "custom"
        text_updates = dlg.get_text_results()
        for idx, texts in text_updates.items():
            if 0 <= idx < len(entries):
                entries[idx].texts = texts
        ai_updates = dlg.get_ai_flags()
        for idx, enabled in ai_updates.items():
            if 0 <= idx < len(entries):
                entry = entries[idx]
                entry.ai_enabled = bool(enabled) if entry.question_type == "text" else False

    def _run_question_wizard(self, entries: List[QuestionEntry], info: List[Dict[str, Any]], survey_title: Optional[str] = None) -> bool:
        if not entries:
            self._toast("请先解析问卷或手动添加题目", "warning")
            return False
        title = survey_title if survey_title is not None else self._survey_title
        dlg = QuestionWizardDialog(entries, info, title, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._apply_wizard_results(entries, dlg)
            return True
        return False

    def _delete_selected_entries(self):
        selected_rows = self._checked_rows()
        if not selected_rows:
            self._toast("请先勾选要删除的题目", "warning")
            return
        
        # 添加确认对话框
        count = len(selected_rows)
        box = MessageBox(
            "确认删除",
            f"确定要删除选中的 {count} 个题目吗？\n此操作无法撤销。",
            self.window() or self
        )
        box.yesButton.setText("确定")
        box.cancelButton.setText("取消")
        if not box.exec():
            return
        
        entries = self.question_page.get_entries()
        for row in sorted(selected_rows, reverse=True):
            if 0 <= row < len(entries):
                entries.pop(row)
        self.question_page.set_entries(entries, self.question_page.questions_info)
        self._refresh_entry_table()
        # 删除后自动取消“全选”勾选，避免误导
        self.select_all_action.setChecked(False)
        self._toast(f"已删除 {count} 个题目", "success")

    def _refresh_entry_table(self):
        entries = self.question_page.get_entries()
        self.entry_table.setRowCount(len(entries))
        # 更新题目数量标签
        self.count_label.setText(f"{len(entries)} 题")
        for idx, entry in enumerate(entries):
            type_label = _get_entry_type_label(entry)
            summary = _question_summary(entry)
            check_item = QTableWidgetItem("")
            check_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsSelectable
            )
            check_item.setCheckState(Qt.CheckState.Unchecked)
            check_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.entry_table.setItem(idx, 0, check_item)
            type_item = QTableWidgetItem(type_label)
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.entry_table.setItem(idx, 1, type_item)
            self.entry_table.setItem(idx, 2, QTableWidgetItem(summary))
        self._sync_start_button_state()

    def _checked_rows(self) -> List[int]:
        rows: List[int] = []
        for r in range(self.entry_table.rowCount()):
            item = self.entry_table.item(r, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                rows.append(r)
        if not rows:
            rows = [idx.row() for idx in self.entry_table.selectionModel().selectedRows()]
        return rows

    def _toggle_select_all_action(self):
        """CommandBar 全选 Action 触发时切换所有行的选中状态"""
        checked = self.select_all_action.isChecked()
        for r in range(self.entry_table.rowCount()):
            item = self.entry_table.item(r, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

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
            from PySide6.QtCore import Qt
            
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


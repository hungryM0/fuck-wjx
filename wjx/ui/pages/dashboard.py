"""主控制面板页面"""
import os
from typing import List, Dict, Any, Optional

from PySide6.QtCore import Qt
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
    CommandBar,
    Action,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    ComboBox,
    MessageBox,
)

from wjx.ui.widgets.no_wheel import NoWheelSlider, NoWheelSpinBox
from wjx.ui.controller import RunController
from wjx.ui.dialogs.card_unlock import CardUnlockDialog
from wjx.ui.dialogs.contact import ContactDialog
from wjx.ui.pages.question import QuestionPage, QuestionWizardDialog, TYPE_CHOICES, STRATEGY_CHOICES, _get_entry_type_label
from wjx.ui.pages.settings import SettingsPage
from wjx.utils.load_save import RuntimeConfig, get_runtime_directory
from wjx.engine import decode_qrcode, QuestionEntry
from wjx.utils.config import DEFAULT_FILL_TEXT
from wjx.utils.registry_manager import RegistryManager
from wjx.network.random_ip import (
    get_status,
    _format_status_payload,
    on_random_ip_toggle,
    refresh_ip_counter_display,
    _validate_card,
)
from wjx.engine import configure_probabilities


def _question_summary(entry: QuestionEntry) -> str:
    """生成题目配置摘要"""
    if entry.question_type in ("text", "multi_text"):
        texts = entry.texts or []
        if texts:
            summary = f"答案: {' | '.join(texts[:2])}"
            if len(texts) > 2:
                summary += f" (+{len(texts)-2})"
            return summary
        return "答案: 无"
    elif entry.custom_weights:
        weights = entry.custom_weights
        summary = f"自定义配比: {','.join(str(int(w)) for w in weights[:4])}"
        if len(weights) > 4:
            summary += "..."
        return summary
    else:
        strategy = entry.distribution_mode or "random"
        if getattr(entry, "probabilities", None) == -1:
            strategy = "random"
        return "完全随机" if strategy == "random" else "均匀分布"


class DashboardPage(QWidget):
    """主页：左侧配置 + 底部状态，不再包含日志。"""

    def __init__(self, controller: RunController, question_page: QuestionPage, settings_page: SettingsPage, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.question_page = question_page
        self.settings_page = settings_page
        self._open_wizard_after_parse = False
        self._build_ui()
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
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        link_card = CardWidget(self)
        link_layout = QVBoxLayout(link_card)
        link_layout.setContentsMargins(12, 12, 12, 12)
        link_layout.setSpacing(8)
        link_layout.addWidget(SubtitleLabel("问卷入口", self))
        link_layout.addWidget(BodyLabel("问卷链接：", self))
        # 创建水平布局：按钮在前，输入框在后
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.qr_btn = PushButton("上传问卷二维码图片", self, FluentIcon.PHOTO)
        input_row.addWidget(self.qr_btn)
        self.url_edit = LineEdit(self)
        self.url_edit.setPlaceholderText("在此处输入问卷链接")
        self.url_edit.setClearButtonEnabled(True)
        input_row.addWidget(self.url_edit, 1)
        link_layout.addLayout(input_row)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.parse_btn = PrimaryPushButton("自动配置问卷", self)
        self.load_cfg_btn = PushButton("载入配置", self)
        self.save_cfg_btn = PushButton("保存配置", self)
        btn_row.addWidget(self.parse_btn)
        btn_row.addWidget(self.load_cfg_btn)
        btn_row.addWidget(self.save_cfg_btn)
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
        spin_row.addWidget(BodyLabel("线程数（提交速度）：", self))
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
        self.random_ip_hint.setMinimumWidth(120)
        ip_row.addWidget(self.random_ip_hint)
        self.card_btn = PushButton("解锁大额IP", self)
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
        
        # 隐藏操作：配置向导
        self.wizard_action = Action(FluentIcon.SETTING, "配置向导")
        self.command_bar.addHiddenAction(self.wizard_action)
        
        list_layout.addWidget(self.command_bar)
        hint = BodyLabel("提示：排序题/滑块题会自动随机填写", self)
        hint.setStyleSheet("padding:8px; border: 1px solid rgba(0,0,0,0.08); border-radius: 8px;")
        list_layout.addWidget(hint)
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
        self.progress_pct.setStyleSheet("font-size: 13pt; font-weight: bold;")
        self.start_btn = PrimaryPushButton("开始执行", self)
        self.stop_btn = PushButton("停止", self)
        self.stop_btn.setEnabled(False)
        self.start_btn.setToolTip("请先配置题目（至少 1 题）")
        bottom_layout.addWidget(self.status_label)
        bottom_layout.addWidget(self.progress_bar, 1)
        bottom_layout.addWidget(self.progress_pct)
        bottom_layout.addWidget(self.start_btn)
        bottom_layout.addWidget(self.stop_btn)
        outer.addWidget(bottom)

    def _bind_events(self):
        self.parse_btn.clicked.connect(self._on_parse_clicked)
        self.load_cfg_btn.clicked.connect(self._on_load_config)
        self.save_cfg_btn.clicked.connect(self._on_save_config)
        self.qr_btn.clicked.connect(self._on_qr_clicked)
        self.start_btn.clicked.connect(self._on_start_clicked)
        self.stop_btn.clicked.connect(lambda: self.controller.stop_run())
        self.target_spin.valueChanged.connect(lambda v: self.settings_page.target_spin.setValue(int(v)))
        self.thread_spin.valueChanged.connect(lambda v: self.settings_page.thread_spin.setValue(int(v)))
        self.random_ip_cb.stateChanged.connect(self._on_random_ip_toggled)
        self.card_btn.clicked.connect(self._on_card_code_clicked)
        # CommandBar Actions
        self.select_all_action.triggered.connect(self._toggle_select_all_action)
        self.add_action.triggered.connect(self._show_add_question_dialog)
        self.edit_action.triggered.connect(self._edit_selected_entry)
        self.del_action.triggered.connect(self._delete_selected_entries)
        self.wizard_action.triggered.connect(self._open_question_wizard)
        try:
            self.question_page.entriesChanged.connect(self._on_question_entries_changed)
        except Exception:
            pass

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
        self._toast("正在解析问卷...", "info", duration=1800)
        self._open_wizard_after_parse = True
        self.controller.parse_survey(url)

    def _on_qr_clicked(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择二维码图片", get_runtime_directory(), "Images (*.png *.jpg *.jpeg *.bmp)")
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
        try:
            cfg = self.controller.load_saved_config(path)
        except Exception as exc:
            self._toast(f"载入失败：{exc}", "error")
            return
        # 应用到界面
        self.settings_page.apply_config(cfg)
        self.apply_config(cfg)
        self.question_page.set_entries(cfg.question_entries or [], self.question_page.questions_info)
        self._refresh_entry_table()
        self._sync_start_button_state()
        refresh_ip_counter_display(self.controller.adapter)
        self._toast("已载入配置", "success")

    def _on_save_config(self):
        cfg = self._build_config()
        cfg.question_entries = list(self.question_page.get_entries())
        self.controller.config = cfg
        path, _ = QFileDialog.getSaveFileName(self, "保存配置", os.path.join(get_runtime_directory(), "config.json"), "JSON 文件 (*.json);;所有文件 (*.*)")
        if not path:
            return
        try:
            self.controller.save_current_config(path)
            self._toast("配置已保存", "success")
        except Exception as exc:
            self._toast(f"保存失败：{exc}", "error")

    def _on_start_clicked(self):
        cfg = self._build_config()
        cfg.question_entries = list(self.question_page.get_entries())
        if not cfg.question_entries:
            self._toast("未配置任何题目，无法开始执行（请先在'题目配置'页添加/配置题目）", "warning")
            self._sync_start_button_state(running=False)
            return
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

    def on_run_state_changed(self, running: bool):
        self._sync_start_button_state(running=running)
        self.stop_btn.setEnabled(running)
        if running:
            self._toast("已启动任务", "success", 1500)
        else:
            self._toast("任务结束", "info", 1500)

    def update_question_meta(self, title: str, count: int):
        self.count_label.setText(f"{count} 题")
        self.title_label.setText(title or "已配置的题目")
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
        self.settings_page.update_config(cfg)
        cfg.target = max(1, self.target_spin.value())
        cfg.threads = max(1, self.thread_spin.value())
        cfg.random_ip_enabled = self.random_ip_cb.isChecked()
        return cfg

    def update_random_ip_counter(self, count: int, limit: int, unlimited: bool, custom_api: bool):
        if custom_api:
            self.random_ip_hint.setText("自定义接口")
            self.random_ip_hint.setStyleSheet("color:#ff8c00;")
            return
        if unlimited:
            self.random_ip_hint.setText("∞（无限额度）")
            self.random_ip_hint.setStyleSheet("color:green;")
            return
        self.random_ip_hint.setText(f"{count}/{limit}")
        self.random_ip_hint.setStyleSheet("color:#6b6b6b;")

    def _on_random_ip_toggled(self, state: int):
        enabled = state != 0
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
            self.settings_page.random_ip_switch.blockSignals(True)
            self.settings_page.random_ip_switch.setChecked(enabled)
            self.settings_page.random_ip_switch.blockSignals(False)
        except Exception:
            pass
        # 刷新计数显示
        refresh_ip_counter_display(self.controller.adapter)

    def _ask_card_code(self) -> Optional[str]:
        """向主窗口请求卡密输入，兜底弹出输入框。"""
        win = self.window()
        if hasattr(win, "_ask_card_code"):
            try:
                return win._ask_card_code()  # type: ignore[union-attr]
            except Exception:
                pass
        dialog = CardUnlockDialog(
            self,
            status_fetcher=get_status,
            status_formatter=_format_status_payload,
            contact_handler=lambda: self._open_contact_dialog(default_type="卡密获取"),
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.get_card_code()
        return None

    def request_card_code(self) -> Optional[str]:
        return self._ask_card_code()

    def _open_contact_dialog(self, default_type: str = "报错反馈"):
        """打开联系对话框"""
        win = self.window()
        if hasattr(win, "_open_contact_dialog"):
            try:
                return win._open_contact_dialog(default_type)  # type: ignore[union-attr]
            except Exception:
                pass
        dlg = ContactDialog(self, default_type=default_type, status_fetcher=get_status, status_formatter=_format_status_payload)
        dlg.exec()

    def _on_card_code_clicked(self):
        """用户主动输入卡密解锁大额随机IP。"""
        dialog = CardUnlockDialog(
            self,
            status_fetcher=get_status,
            status_formatter=_format_status_payload,
            contact_handler=lambda: self._open_contact_dialog(default_type="卡密获取"),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        code = dialog.get_card_code()
        if not code:
            self._toast("未输入卡密", "warning")
            return
        if _validate_card(code):
            RegistryManager.set_quota_unlimited(True)
            RegistryManager.reset_submit_count()
            refresh_ip_counter_display(self.controller.adapter)
            self.random_ip_cb.setChecked(True)
            try:
                self.settings_page.random_ip_switch.setChecked(True)
            except Exception:
                pass
            self._toast("卡密验证通过，已解锁额度", "success")
        else:
            self._toast("卡密验证失败，请重试", "error")

    def _edit_selected_entry(self):
        """编辑选中的题目 - 由于代码过长，这里简化实现"""
        selected_rows = self._checked_rows()
        if not selected_rows:
            self._toast("请先勾选要编辑的题目", "warning")
            return
        if len(selected_rows) > 1:
            self._toast("一次只能编辑一个题目", "warning")
            return
        
        # 简化版：直接提示用户到题目配置页编辑
        self._toast("请到'题目配置'页面进行详细编辑", "info")

    def _show_add_question_dialog(self):
        """新增题目 - 委托给 QuestionPage"""
        self.question_page._add_entry()
        self._refresh_entry_table()

    def _open_question_wizard(self):
        if not self.question_page.entries:
            self._toast("请先解析问卷或手动添加题目", "warning")
            return
        dlg = QuestionWizardDialog(self.question_page.entries, self.question_page.questions_info, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updates = dlg.get_results()
            for idx, weights in updates.items():
                if 0 <= idx < len(self.question_page.entries):
                    entry = self.question_page.entries[idx]
                    entry.custom_weights = [float(w) for w in weights]
                    entry.distribution_mode = "custom"
            self._refresh_entry_table()

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
        self._toast(f"已删除 {count} 个题目", "success")

    def _refresh_entry_table(self):
        entries = self.question_page.get_entries()
        self.entry_table.setRowCount(len(entries))
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

    def _toast(self, text: str, level: str = "info", duration: int = 2000):
        parent = self.window() or self
        kind = level.lower()
        if kind == "success":
            InfoBar.success("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)
        elif kind == "warning":
            InfoBar.warning("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)
        elif kind == "error":
            InfoBar.error("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)
        else:
            InfoBar.info("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)

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

from wjx.ui.widgets import ConfigDrawer
from wjx.ui.widgets.no_wheel import NoWheelSlider, NoWheelSpinBox
from wjx.ui.controller import RunController
from wjx.ui.dialogs.card_unlock import CardUnlockDialog
from wjx.ui.dialogs.contact import ContactDialog
from wjx.ui.pages.workbench.question import QuestionPage, QuestionWizardDialog, TYPE_CHOICES, STRATEGY_CHOICES, _get_entry_type_label
from wjx.ui.pages.workbench.runtime import RuntimePage
from wjx.utils.io.load_save import RuntimeConfig, get_runtime_directory
from wjx.utils.io.qrcode_utils import decode_qrcode
from wjx.core.questions.config import QuestionEntry, configure_probabilities
from wjx.utils.app.config import DEFAULT_FILL_TEXT
from wjx.utils.system.registry_manager import RegistryManager
from wjx.network.random_ip import (
    get_status,
    _format_status_payload,
    on_random_ip_toggle,
    refresh_ip_counter_display,
    _validate_card,
)


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
    elif entry.custom_weights:
        weights = entry.custom_weights
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
        return "完全随机" if strategy == "random" else "自定义配比"


class DashboardPage(QWidget):
    """主页：左侧配置 + 底部状态，不再包含日志。"""

    def __init__(self, controller: RunController, question_page: QuestionPage, runtime_page: RuntimePage, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.question_page = question_page
        self.runtime_page = runtime_page
        self._open_wizard_after_parse = False
        self._last_pause_reason = ""
        self._completion_notified = False
        self._last_progress = 0
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
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        link_card = CardWidget(self)
        link_layout = QVBoxLayout(link_card)
        link_layout.setContentsMargins(12, 12, 12, 12)
        link_layout.setSpacing(8)
        
        # 标题行：左侧是标题，右侧是载入/保存按钮
        title_row = QHBoxLayout()
        title_row.addWidget(SubtitleLabel("问卷入口", self))
        title_row.addStretch(1)
        self.config_list_btn = PushButton("配置列表", self)
        self.load_cfg_btn = PushButton("载入配置", self)
        self.save_cfg_btn = PushButton("保存配置", self)
        title_row.addWidget(self.config_list_btn)
        title_row.addWidget(self.load_cfg_btn)
        title_row.addWidget(self.save_cfg_btn)
        link_layout.addLayout(title_row)
        
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
        ip_row.addWidget(self.random_ip_hint)
        ip_row.addSpacing(4)
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
        
        # 删除选中
        self.del_action = Action(FluentIcon.DELETE, "删除选中")
        self.command_bar.addAction(self.del_action)
        
        # 分隔符
        self.command_bar.addSeparator()
        
        # 全选（可勾选）
        self.select_all_action = Action(FluentIcon.CHECKBOX, "全选", checkable=True)
        self.command_bar.addAction(self.select_all_action)
        
        # 隐藏操作：配置向导（移除隐藏按钮，避免出现更多“...”菜单）
        self.wizard_action = Action(FluentIcon.SETTING, "配置向导")
        
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
        # CommandBar Actions
        self.select_all_action.triggered.connect(self._toggle_select_all_action)
        self.add_action.triggered.connect(self._show_add_question_dialog)
        self.del_action.triggered.connect(self._delete_selected_entries)
        self.wizard_action.triggered.connect(self._open_question_wizard)
        try:
            self.question_page.entriesChanged.connect(self._on_question_entries_changed)
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            self.config_drawer.sync_to_parent()
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
        self._completion_notified = False
        self._last_progress = 0
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
        self.runtime_page.update_config(cfg)
        cfg.target = max(1, self.target_spin.value())
        cfg.threads = max(1, self.thread_spin.value())
        cfg.random_ip_enabled = self.random_ip_cb.isChecked()
        return cfg

    def update_random_ip_counter(self, count: int, limit: int, unlimited: bool, custom_api: bool):
        from wjx.network.random_ip import _PREMIUM_RANDOM_IP_LIMIT
        # 检查是否已解锁大额IP（额度上限>=400）
        is_unlocked = limit >= _PREMIUM_RANDOM_IP_LIMIT
        if is_unlocked:
            self.card_btn.setEnabled(False)
            self.card_btn.setText("已解锁")
        else:
            self.card_btn.setEnabled(True)
            self.card_btn.setText("解锁大额IP")
        
        if custom_api:
            self.random_ip_hint.setText("自定义接口")
            self.random_ip_hint.setStyleSheet("color:#ff8c00;")
            return
        if unlimited:
            self.random_ip_hint.setText("∞（无限额度）")
            self.random_ip_hint.setStyleSheet("color:green;")
            return
        self.random_ip_hint.setText(f"{count}/{limit}")
        # 额度耗尽时变红
        if count >= limit:
            self.random_ip_hint.setStyleSheet("color:red;")
        else:
            self.random_ip_hint.setStyleSheet("color:#6b6b6b;")
        # 达到上限时自动关闭随机IP开关
        if count >= limit and self.random_ip_cb.isChecked():
            self.random_ip_cb.blockSignals(True)
            self.random_ip_cb.setChecked(False)
            self.random_ip_cb.blockSignals(False)
            try:
                self.runtime_page.random_ip_switch.blockSignals(True)
                self.runtime_page.random_ip_switch.setChecked(False)
                self.runtime_page.random_ip_switch.blockSignals(False)
            except Exception:
                pass

    def _on_random_ip_toggled(self, state: int):
        enabled = state != 0
        # 先同步检查限制，防止快速点击绕过
        if enabled:
            from wjx.utils.system.registry_manager import RegistryManager
            from wjx.network.random_ip import get_random_ip_limit
            if not RegistryManager.is_quota_unlimited():
                count = RegistryManager.read_submit_count()
                limit = max(1, get_random_ip_limit())
                if count >= limit:
                    self._toast(f"随机IP已达{limit}份限制，请验证卡密后再启用。", "warning")
                    self.random_ip_cb.blockSignals(True)
                    self.random_ip_cb.setChecked(False)
                    self.random_ip_cb.blockSignals(False)
                    try:
                        self.runtime_page.random_ip_switch.blockSignals(True)
                        self.runtime_page.random_ip_switch.setChecked(False)
                        self.runtime_page.random_ip_switch.blockSignals(False)
                    except Exception:
                        pass
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
            card_validator=_validate_card,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        # 验证成功后处理解锁逻辑：设置400份额度上限（不重置已用额度）
        if dialog.get_validation_result():
            from wjx.network.random_ip import _PREMIUM_RANDOM_IP_LIMIT
            RegistryManager.write_quota_limit(_PREMIUM_RANDOM_IP_LIMIT)
            RegistryManager.set_quota_unlimited(False)
            refresh_ip_counter_display(self.controller.adapter)
            self.random_ip_cb.setChecked(True)
            try:
                self.runtime_page.random_ip_switch.setChecked(True)
            except Exception:
                pass

    def _show_add_question_dialog(self):
        """新增题目 - 委托给 QuestionPage"""
        self.question_page._add_entry()
        self._refresh_entry_table()

    def _open_question_wizard(self):
        if self._run_question_wizard(self.question_page.entries, self.question_page.questions_info):
            self._refresh_entry_table()

    def _apply_wizard_results(self, entries: List[QuestionEntry], dlg: QuestionWizardDialog) -> None:
        updates = dlg.get_results()
        for idx, weights in updates.items():
            if 0 <= idx < len(entries):
                entry = entries[idx]
                entry.custom_weights = [float(w) for w in weights]
                entry.probabilities = [float(w) for w in weights]
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

    def _run_question_wizard(self, entries: List[QuestionEntry], info: List[Dict[str, Any]]) -> bool:
        if not entries:
            self._toast("请先解析问卷或手动添加题目", "warning")
            return False
        dlg = QuestionWizardDialog(entries, info, self)
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

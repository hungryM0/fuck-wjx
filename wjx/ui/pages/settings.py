"""运行参数设置页面"""
from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QDialog,
    QToolButton,
)
from qfluentwidgets import (
    ScrollArea,
    SubtitleLabel,
    BodyLabel,
    StrongBodyLabel,
    CardWidget,
    PushButton,
    PrimaryPushButton,
    SwitchButton,
    CheckBox,
    ComboBox,
    LineEdit,
    FluentIcon,
    PopupTeachingTip,
    TeachingTipTailPosition,
)

from wjx.ui.widgets.no_wheel import NoWheelSlider, NoWheelSpinBox
from wjx.ui.controller import RunController
from wjx.utils.load_save import RuntimeConfig
from wjx.utils.config import USER_AGENT_PRESETS


class SettingsPage(ScrollArea):
    """独立的运行参数/开关页，方便在侧边栏查看。"""

    def __init__(self, controller: RunController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.view = QWidget(self)
        self.view.setStyleSheet("background: transparent;")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.view.setObjectName("settings_view")
        self.ua_checkboxes: Dict[str, CheckBox] = {}
        self._build_ui()
        self._bind_events()
        self._sync_random_ua(self.random_ua_switch.isChecked())

    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        run_group = CardWidget(self.view)
        run_layout = QVBoxLayout(run_group)
        run_layout.setContentsMargins(16, 16, 16, 16)
        run_layout.setSpacing(12)
        run_layout.addWidget(SubtitleLabel("运行参数", self.view))

        self.target_spin = NoWheelSpinBox(self.view)
        self.target_spin.setRange(1, 99999)
        self.target_spin.setValue(10)
        self.target_spin.setMinimumWidth(110)
        self.target_spin.setFixedHeight(36)
        self.target_spin.setStyleSheet("QSpinBox { padding: 4px 8px; font-size: 11pt; }")
        self.thread_spin = NoWheelSpinBox(self.view)
        self.thread_spin.setRange(1, 12)
        self.thread_spin.setValue(2)
        self.thread_spin.setMinimumWidth(110)
        self.thread_spin.setFixedHeight(36)
        self.thread_spin.setStyleSheet("QSpinBox { padding: 4px 8px; font-size: 11pt; }")
        self.fail_stop_switch = SwitchButton("失败过多自动停止", self.view)
        self.fail_stop_switch.setChecked(True)
        self._pin_switch_label(self.fail_stop_switch, "失败过多自动停止")

        target_row = QHBoxLayout()
        target_row.addWidget(BodyLabel("目标份数"))
        target_row.addWidget(self.target_spin)
        target_row.addStretch(1)
        run_layout.addLayout(target_row)

        thread_row = QHBoxLayout()
        thread_row.addWidget(BodyLabel("并发浏览器"))
        thread_row.addWidget(self.thread_spin)
        thread_row.addStretch(1)
        run_layout.addLayout(thread_row)

        run_layout.addWidget(self.fail_stop_switch)
        layout.addWidget(run_group)

        time_group = CardWidget(self.view)
        time_layout = QVBoxLayout(time_group)
        time_layout.setContentsMargins(16, 16, 16, 16)
        time_layout.setSpacing(12)
        time_layout.addWidget(SubtitleLabel("时间控制", self.view))

        # 提交间隔 - 使用按钮显示时间
        self.interval_min_seconds = 0
        self.interval_max_seconds = 0
        self.answer_min_seconds = 0
        self.answer_max_seconds = 0
        
        interval_row = QHBoxLayout()
        interval_row.addWidget(BodyLabel("提交间隔"))
        self.interval_min_btn = PushButton("0分0秒", self.view)
        self.interval_min_btn.setMinimumWidth(100)
        interval_row.addWidget(self.interval_min_btn)
        interval_row.addWidget(BodyLabel("~"))
        self.interval_max_btn = PushButton("0分0秒", self.view)
        self.interval_max_btn.setMinimumWidth(100)
        interval_row.addWidget(self.interval_max_btn)
        interval_row.addStretch(1)
        time_layout.addLayout(interval_row)

        answer_row = QHBoxLayout()
        answer_row.addWidget(BodyLabel("作答时长"))
        self.answer_min_btn = PushButton("0分0秒", self.view)
        self.answer_min_btn.setMinimumWidth(100)
        answer_row.addWidget(self.answer_min_btn)
        answer_row.addWidget(BodyLabel("~"))
        self.answer_max_btn = PushButton("0分0秒", self.view)
        self.answer_max_btn.setMinimumWidth(100)
        answer_row.addWidget(self.answer_max_btn)
        answer_row.addStretch(1)
        time_layout.addLayout(answer_row)
        
        timed_row = QHBoxLayout()
        timed_row.setSpacing(8)
        self.timed_switch = SwitchButton("定时模式", self.view)
        self._pin_switch_label(self.timed_switch, "定时模式")
        timed_row.addWidget(self.timed_switch)
        
        # 添加帮助按钮 - 使用 Qt 原生 QToolButton
        help_btn = QToolButton(self.view)
        help_btn.setIcon(FluentIcon.INFO.icon())
        help_btn.setFixedSize(32, 32)
        help_btn.setAutoRaise(True)
        help_btn.setToolTip("")  # 显式设置空 tooltip
        help_btn.setStyleSheet("""
            QToolButton {
                background: transparent;
                border: none;
                border-radius: 6px;
            }
            QToolButton:hover {
                background: rgba(0, 0, 0, 0.05);
            }
            QToolButton:pressed {
                background: rgba(0, 0, 0, 0.08);
            }
        """)
        help_btn.clicked.connect(self._show_timed_mode_help)
        timed_row.addWidget(help_btn)
        timed_row.addStretch(1)
        
        time_layout.addLayout(timed_row)
        layout.addWidget(time_group)

        feature_group = CardWidget(self.view)
        feature_layout = QVBoxLayout(feature_group)
        feature_layout.setContentsMargins(16, 16, 16, 16)
        feature_layout.setSpacing(12)
        feature_layout.addWidget(SubtitleLabel("特性开关", self.view))

        feature_row = QHBoxLayout()
        self.random_ip_switch = SwitchButton("随机IP", self.view)
        self.random_ua_switch = SwitchButton("随机 UA", self.view)
        self._pin_switch_label(self.random_ip_switch, "随机IP")
        self._pin_switch_label(self.random_ua_switch, "随机 UA")
        feature_row.addWidget(self.random_ip_switch)
        feature_row.addWidget(self.random_ua_switch)
        feature_row.addStretch(1)
        feature_layout.addLayout(feature_row)

        # 代理源选择
        proxy_source_row = QHBoxLayout()
        proxy_source_row.setSpacing(8)
        proxy_source_row.addWidget(BodyLabel("代理源：", self.view))
        self.proxy_source_combo = ComboBox(self.view)
        self.proxy_source_combo.addItem("默认", userData="default")
        self.proxy_source_combo.addItem("皮卡丘代理站 (中国大陆)", userData="pikachu")
        self.proxy_source_combo.addItem("自定义", userData="custom")
        self.proxy_source_combo.setMinimumWidth(200)
        proxy_source_row.addWidget(self.proxy_source_combo)
        proxy_source_row.addStretch(1)
        feature_layout.addLayout(proxy_source_row)

        # 自定义API地址输入框 - 使用容器widget便于整体隐藏/显示
        self.custom_api_container = QWidget(feature_group)
        custom_api_layout = QHBoxLayout(self.custom_api_container)
        custom_api_layout.setContentsMargins(0, 0, 0, 0)
        custom_api_layout.setSpacing(8)
        self.custom_api_label = BodyLabel("API地址：", self.custom_api_container)
        custom_api_layout.addWidget(self.custom_api_label)
        self.custom_api_edit = LineEdit(self.custom_api_container)
        self.custom_api_edit.setPlaceholderText("仅支持json返回格式")
        self.custom_api_edit.setMinimumWidth(300)
        self.custom_api_edit.setFixedHeight(36)
        custom_api_layout.addWidget(self.custom_api_edit)
        custom_api_layout.addStretch(1)
        feature_layout.addWidget(self.custom_api_container)
        # 默认隐藏
        self.custom_api_container.hide()

        ua_group = CardWidget(self.view)
        ua_layout = QVBoxLayout(ua_group)
        ua_layout.setContentsMargins(12, 12, 12, 12)
        ua_layout.setSpacing(8)
        ua_layout.addWidget(SubtitleLabel("随机 UA 类型", self.view))
        ua_grid = QGridLayout()
        ua_grid.setSpacing(8)
        col = 0
        row = 0
        for key, preset in USER_AGENT_PRESETS.items():
            label = preset.get("label") or key
            cb = CheckBox(label, self.view)
            cb.setChecked(key == "pc_web")
            self.ua_checkboxes[key] = cb
            ua_grid.addWidget(cb, row, col)
            col += 1
            if col >= 3:
                col = 0
                row += 1
        ua_layout.addLayout(ua_grid)
        feature_layout.addWidget(ua_group)
        layout.addWidget(feature_group)

        layout.addStretch(1)

    def _bind_events(self):
        self.random_ip_switch.checkedChanged.connect(self._on_random_ip_toggled)
        self.random_ua_switch.checkedChanged.connect(self._sync_random_ua)
        self.timed_switch.checkedChanged.connect(self._sync_timed_mode)
        self.interval_min_btn.clicked.connect(lambda: self._show_time_picker("interval_min"))
        self.interval_max_btn.clicked.connect(lambda: self._show_time_picker("interval_max"))
        self.answer_min_btn.clicked.connect(lambda: self._show_time_picker("answer_min"))
        self.answer_max_btn.clicked.connect(lambda: self._show_time_picker("answer_max"))
        self.proxy_source_combo.currentIndexChanged.connect(lambda idx: self._on_proxy_source_changed())

    def _on_random_ip_toggled(self, enabled: bool):
        """参数页随机IP开关切换时，同步到主页并显示弹窗"""
        main_win = self.window()
        # 调用主页的处理逻辑（包含弹窗和同步）
        if hasattr(main_win, "dashboard"):
            # 阻止信号避免循环
            self.random_ip_switch.blockSignals(True)
            try:
                main_win.dashboard._on_random_ip_toggled(2 if enabled else 0)  # type: ignore[union-attr]
            finally:
                self.random_ip_switch.blockSignals(False)

    def _on_proxy_source_changed(self, text: str = ""):
        """代理源选择变化时更新设置"""
        idx = self.proxy_source_combo.currentIndex()
        source = str(self.proxy_source_combo.itemData(idx)) if idx >= 0 else "default"
        if not source or source == "None":
            source = "default"
        is_custom = source == "custom"
        # 显示/隐藏自定义API输入框容器
        if is_custom:
            self.custom_api_container.show()
        else:
            self.custom_api_container.hide()
        try:
            from wjx.network.random_ip import set_proxy_source, set_proxy_api_override
            if is_custom:
                api_url = self.custom_api_edit.text().strip()
                set_proxy_api_override(api_url if api_url else None)
            set_proxy_source(source)
        except Exception:
            pass

    def request_card_code(self) -> Optional[str]:
        """为解锁弹窗提供卡密输入。"""
        main_win = self.window()
        if hasattr(main_win, "_ask_card_code"):
            try:
                return main_win._ask_card_code()  # type: ignore[union-attr]
            except Exception:
                return None
        return None

    def _sync_random_ua(self, enabled: bool):
        try:
            for cb in self.ua_checkboxes.values():
                cb.setEnabled(bool(enabled))
        except Exception:
            pass
    
    def _sync_timed_mode(self, enabled: bool):
        """定时模式切换时禁用/启用时间控制按钮"""
        try:
            disabled = bool(enabled)
            self.interval_min_btn.setEnabled(not disabled)
            self.interval_max_btn.setEnabled(not disabled)
            self.answer_min_btn.setEnabled(not disabled)
            self.answer_max_btn.setEnabled(not disabled)
        except Exception:
            pass
    
    def _show_time_picker(self, field: str):
        """显示时间选择对话框（全新设计）"""
        # 获取当前值
        if field == "interval_min":
            current_seconds = self.interval_min_seconds
            title = "设置提交间隔最小值"
        elif field == "interval_max":
            current_seconds = self.interval_max_seconds
            title = "设置提交间隔最大值"
        elif field == "answer_min":
            current_seconds = self.answer_min_seconds
            title = "设置作答时长最小值"
        else:  # answer_max
            current_seconds = self.answer_max_seconds
            title = "设置作答时长最大值"
        
        # 创建对话框
        dialog = QDialog(self.window() or self)
        dialog.setWindowTitle(title)
        dialog.setFixedSize(480, 360)
        main_layout = QVBoxLayout(dialog)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)
        
        # 标题区域
        title_label = SubtitleLabel(title, dialog)
        main_layout.addWidget(title_label)
        
        # 卡片容器
        card = CardWidget(dialog)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(20)
        
        # 实时预览区域
        preview_container = QWidget(card)
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(4)
        preview_hint = BodyLabel("当前设置", card)
        preview_hint.setStyleSheet("color: #888; font-size: 11pt;")
        preview_value = StrongBodyLabel("0分0秒", card)
        preview_value.setStyleSheet("font-size: 18pt; color: #2563EB;")
        preview_layout.addWidget(preview_hint, alignment=Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(preview_value, alignment=Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(preview_container)
        
        # 分钟控制区域
        minutes_container = QWidget(card)
        minutes_layout = QHBoxLayout(minutes_container)
        minutes_layout.setContentsMargins(0, 0, 0, 0)
        minutes_layout.setSpacing(12)
        
        minutes_label = BodyLabel("分钟", card)
        minutes_label.setFixedWidth(50)
        minutes_slider = NoWheelSlider(Qt.Orientation.Horizontal, card)
        minutes_slider.setRange(0, 10)
        minutes_slider.setValue(current_seconds // 60)
        minutes_spin = NoWheelSpinBox(card)
        minutes_spin.setRange(0, 10)
        minutes_spin.setValue(current_seconds // 60)
        minutes_spin.setFixedWidth(70)
        
        minutes_layout.addWidget(minutes_label)
        minutes_layout.addWidget(minutes_slider, 1)
        minutes_layout.addWidget(minutes_spin)
        card_layout.addWidget(minutes_container)
        
        # 秒控制区域
        seconds_container = QWidget(card)
        seconds_layout = QHBoxLayout(seconds_container)
        seconds_layout.setContentsMargins(0, 0, 0, 0)
        seconds_layout.setSpacing(12)
        
        seconds_label = BodyLabel("秒", card)
        seconds_label.setFixedWidth(50)
        seconds_slider = NoWheelSlider(Qt.Orientation.Horizontal, card)
        seconds_slider.setRange(0, 59)
        seconds_slider.setValue(current_seconds % 60)
        seconds_spin = NoWheelSpinBox(card)
        seconds_spin.setRange(0, 59)
        seconds_spin.setValue(current_seconds % 60)
        seconds_spin.setFixedWidth(70)
        
        seconds_layout.addWidget(seconds_label)
        seconds_layout.addWidget(seconds_slider, 1)
        seconds_layout.addWidget(seconds_spin)
        card_layout.addWidget(seconds_container)
        
        main_layout.addWidget(card)
        main_layout.addStretch(1)
        
        # 更新预览函数
        def update_preview():
            m = minutes_spin.value()
            s = seconds_spin.value()
            preview_value.setText(f"{m}分{s}秒")
        
        # 联动逻辑
        minutes_slider.valueChanged.connect(minutes_spin.setValue)
        minutes_spin.valueChanged.connect(minutes_slider.setValue)
        minutes_spin.valueChanged.connect(lambda: update_preview())
        
        seconds_slider.valueChanged.connect(seconds_spin.setValue)
        seconds_spin.valueChanged.connect(seconds_slider.setValue)
        seconds_spin.valueChanged.connect(lambda: update_preview())
        
        # 初始化预览
        update_preview()
        
        # 按钮区域
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = PushButton("取消", dialog)
        cancel_btn.setMinimumWidth(90)
        ok_btn = PrimaryPushButton("确定", dialog)
        ok_btn.setMinimumWidth(90)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        main_layout.addLayout(btn_row)
        
        cancel_btn.clicked.connect(dialog.reject)
        ok_btn.clicked.connect(dialog.accept)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            total_seconds = minutes_spin.value() * 60 + seconds_spin.value()
            # 更新值和按钮文本
            if field == "interval_min":
                self.interval_min_seconds = total_seconds
                self.interval_min_btn.setText(f"{minutes_spin.value()}分{seconds_spin.value()}秒")
            elif field == "interval_max":
                self.interval_max_seconds = total_seconds
                self.interval_max_btn.setText(f"{minutes_spin.value()}分{seconds_spin.value()}秒")
            elif field == "answer_min":
                self.answer_min_seconds = total_seconds
                self.answer_min_btn.setText(f"{minutes_spin.value()}分{seconds_spin.value()}秒")
            else:  # answer_max
                self.answer_max_seconds = total_seconds
                self.answer_max_btn.setText(f"{minutes_spin.value()}分{seconds_spin.value()}秒")

    def update_config(self, cfg: RuntimeConfig):
        cfg.target = max(1, self.target_spin.value())
        cfg.threads = max(1, self.thread_spin.value())
        
        # 直接使用秒数变量
        cfg.submit_interval = (
            max(0, self.interval_min_seconds),
            max(self.interval_min_seconds, self.interval_max_seconds),
        )
        
        cfg.answer_duration = (
            max(0, self.answer_min_seconds),
            max(self.answer_min_seconds, self.answer_max_seconds),
        )
        
        cfg.timed_mode_enabled = self.timed_switch.isChecked()
        cfg.random_ip_enabled = self.random_ip_switch.isChecked()
        cfg.random_ua_enabled = self.random_ua_switch.isChecked()
        cfg.random_ua_keys = [k for k, cb in self.ua_checkboxes.items() if cb.isChecked()] if cfg.random_ua_enabled else []
        cfg.fail_stop_enabled = self.fail_stop_switch.isChecked()
        
        # 保存代理源设置
        try:
            idx = self.proxy_source_combo.currentIndex()
            source = str(self.proxy_source_combo.itemData(idx)) if idx >= 0 else "default"
            if not source or source == "None":
                source = "default"
            cfg.proxy_source = source
            cfg.custom_proxy_api = self.custom_api_edit.text().strip() if source == "custom" else ""
        except Exception:
            cfg.proxy_source = "default"
            cfg.custom_proxy_api = ""

    def apply_config(self, cfg: RuntimeConfig):
        self.target_spin.setValue(max(1, cfg.target))
        self.thread_spin.setValue(max(1, cfg.threads))
        
        # 更新秒数变量和按钮文本
        interval_min_seconds = max(0, cfg.submit_interval[0])
        self.interval_min_seconds = interval_min_seconds
        self.interval_min_btn.setText(f"{interval_min_seconds // 60}分{interval_min_seconds % 60}秒")
        
        interval_max_seconds = max(cfg.submit_interval[0], cfg.submit_interval[1])
        self.interval_max_seconds = interval_max_seconds
        self.interval_max_btn.setText(f"{interval_max_seconds // 60}分{interval_max_seconds % 60}秒")
        
        answer_min_seconds = max(0, cfg.answer_duration[0])
        self.answer_min_seconds = answer_min_seconds
        self.answer_min_btn.setText(f"{answer_min_seconds // 60}分{answer_min_seconds % 60}秒")
        
        answer_max_seconds = max(cfg.answer_duration[0], cfg.answer_duration[1])
        self.answer_max_seconds = answer_max_seconds
        self.answer_max_btn.setText(f"{answer_max_seconds // 60}分{answer_max_seconds % 60}秒")
        
        self.timed_switch.setChecked(cfg.timed_mode_enabled)
        self._sync_timed_mode(cfg.timed_mode_enabled)
        # 阻塞信号避免加载配置时触发弹窗
        self.random_ip_switch.blockSignals(True)
        self.random_ip_switch.setChecked(cfg.random_ip_enabled)
        self.random_ip_switch.blockSignals(False)
        self.random_ua_switch.setChecked(cfg.random_ua_enabled)
        # 应用 UA 选项
        active = set(cfg.random_ua_keys or [])
        for key, cb in self.ua_checkboxes.items():
            cb.setChecked((not active and key == "pc_web") or key in active)
            cb.setEnabled(self.random_ua_switch.isChecked())
        self.fail_stop_switch.setChecked(cfg.fail_stop_enabled)
        
        # 应用代理源设置
        try:
            proxy_source = getattr(cfg, "proxy_source", "default")
            custom_api = getattr(cfg, "custom_proxy_api", "")
            idx = self.proxy_source_combo.findData(proxy_source)
            if idx >= 0:
                self.proxy_source_combo.setCurrentIndex(idx)
            # 设置自定义API地址并显示/隐藏输入框容器
            self.custom_api_edit.setText(custom_api)
            is_custom = proxy_source == "custom"
            self.custom_api_container.setVisible(is_custom)
            from wjx.network.random_ip import set_proxy_source, set_proxy_api_override
            if is_custom and custom_api:
                set_proxy_api_override(custom_api)
            set_proxy_source(proxy_source)
        except Exception:
            pass

    def _show_timed_mode_help(self):
        """显示定时模式说明TeachingTip"""
        # 获取触发按钮
        sender = self.sender()
        if not sender or not isinstance(sender, QWidget):
            return
        
        # 创建内容文本
        content = (
            "启用后，程序会忽略「提交间隔」和「作答时长」设置，改为高频刷新并在开放后立即提交。\n\n"
            "典型应用场景：\n"
            "• 抢志愿填报名额\n"
            "• 抢课程选课名额（如大学选课问卷）\n"
            "• 抢活动报名名额（如讲座、比赛报名）\n"
            "• 其他在特定时间点开放的问卷"
        )
        
        PopupTeachingTip.create(
            target=sender,
            icon=FluentIcon.INFO,
            title='定时模式说明',
            content=content,
            isClosable=True,
            tailPosition=TeachingTipTailPosition.BOTTOM,
            duration=-1,
            parent=self.view
        )
    
    def _pin_switch_label(self, sw: SwitchButton, text: str):
        """保持开关两侧文本一致，避免切换为 On/Off。"""
        try:
            sw.setOnText(text)
            sw.setOffText(text)
            sw.setText(text)
        except Exception:
            sw.setText(text)

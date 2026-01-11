"""运行参数设置页面 - 使用 SettingCard 组件重构"""
from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QDialog,
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
    SettingCardGroup,
    SettingCard,
    ExpandGroupSettingCard,
    IndicatorPosition,
    TransparentToolButton,
)

from wjx.ui.widgets.no_wheel import NoWheelSlider, NoWheelSpinBox
from wjx.ui.controller import RunController
from wjx.utils.load_save import RuntimeConfig
from wjx.utils.config import USER_AGENT_PRESETS


class SpinBoxSettingCard(SettingCard):
    """带 SpinBox 的设置卡"""

    def __init__(self, icon, title, content, min_val=1, max_val=99999, default=10, parent=None):
        super().__init__(icon, title, content, parent)
        self.spinBox = NoWheelSpinBox(self)
        self.spinBox.setRange(min_val, max_val)
        self.spinBox.setValue(default)
        self.spinBox.setFixedWidth(110)
        self.spinBox.setFixedHeight(36)
        self.hBoxLayout.addWidget(self.spinBox, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def value(self):
        return self.spinBox.value()

    def setValue(self, value):
        self.spinBox.setValue(value)


class SwitchSettingCard(SettingCard):
    """带开关的设置卡"""

    def __init__(self, icon, title, content, parent=None):
        super().__init__(icon, title, content, parent)
        self.switchButton = SwitchButton(self, IndicatorPosition.RIGHT)
        self.switchButton.setOnText("开")
        self.switchButton.setOffText("关")
        self.hBoxLayout.addWidget(self.switchButton, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def isChecked(self):
        return self.switchButton.isChecked()

    def setChecked(self, checked):
        self.switchButton.setChecked(checked)

    def blockSignals(self, block):
        return self.switchButton.blockSignals(block)


class RandomIPSettingCard(ExpandGroupSettingCard):
    """随机IP设置卡 - 包含代理源选择"""

    def __init__(self, parent=None):
        super().__init__(FluentIcon.GLOBE, "随机 IP", "使用代理 IP 来模拟不同地区的访问，并绕过智能验证", parent)

        # 开关
        self.switchButton = SwitchButton(self, IndicatorPosition.RIGHT)
        self.switchButton.setOnText("开")
        self.switchButton.setOffText("关")
        self.addWidget(self.switchButton)

        # 代理源选择容器
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(48, 12, 48, 12)
        layout.setSpacing(12)

        # 代理源下拉框
        source_row = QHBoxLayout()
        source_label = BodyLabel("代理源", container)
        self.proxyCombo = ComboBox(container)
        self.proxyCombo.addItem("默认", userData="default")
        self.proxyCombo.addItem("皮卡丘代理站 (中国大陆)", userData="pikachu")
        self.proxyCombo.addItem("自定义", userData="custom")
        self.proxyCombo.setMinimumWidth(200)
        source_row.addWidget(source_label)
        source_row.addStretch(1)
        source_row.addWidget(self.proxyCombo)
        layout.addLayout(source_row)

        # 自定义API输入
        self.customApiRow = QWidget(container)
        api_layout = QHBoxLayout(self.customApiRow)
        api_layout.setContentsMargins(0, 0, 0, 0)
        api_label = BodyLabel("API 地址", self.customApiRow)
        api_hint = BodyLabel("*仅支持json返回格式", self.customApiRow)
        api_hint.setStyleSheet("color: red; font-size: 11px;")
        self.customApiEdit = LineEdit(self.customApiRow)
        self.customApiEdit.setPlaceholderText("请输入代理api地址")
        self.customApiEdit.setMinimumWidth(280)
        api_layout.addWidget(api_label)
        api_layout.addWidget(api_hint)
        api_layout.addStretch(1)
        api_layout.addWidget(self.customApiEdit)
        self.customApiRow.hide()
        layout.addWidget(self.customApiRow)

        self.addGroupWidget(container)

        # 代理源变化时显示/隐藏自定义API
        self.proxyCombo.currentIndexChanged.connect(self._on_source_changed)

    def _on_source_changed(self):
        idx = self.proxyCombo.currentIndex()
        source = str(self.proxyCombo.itemData(idx)) if idx >= 0 else "default"
        self.customApiRow.setVisible(source == "custom")
        # 刷新布局 - 重新触发展开/收起来更新高度
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._refreshLayout)

    def _refreshLayout(self):
        """刷新展开卡片的布局"""
        # 通过重新设置展开状态来刷新高度
        if self.isExpand:
            self._adjustViewSize()

    def isChecked(self):
        return self.switchButton.isChecked()

    def setChecked(self, checked):
        self.switchButton.setChecked(checked)


class TimedModeSettingCard(SettingCard):
    """定时模式设置卡 - 带帮助按钮"""

    def __init__(self, icon, title, content, parent=None):
        super().__init__(icon, title, content, parent)
        from PySide6.QtCore import QSize
        self.helpButton = TransparentToolButton(FluentIcon.INFO, self)
        self.helpButton.setFixedSize(18, 18)
        self.helpButton.setIconSize(QSize(14, 14))
        self.helpButton.setCursor(Qt.CursorShape.PointingHandCursor)
        # 创建标题行布局，把图标放在标题右边
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(4)
        self.vBoxLayout.removeWidget(self.titleLabel)
        title_row.addWidget(self.titleLabel)
        title_row.addWidget(self.helpButton)
        title_row.addStretch()
        self.vBoxLayout.insertLayout(0, title_row)
        self.switchButton = SwitchButton(self, IndicatorPosition.RIGHT)
        self.switchButton.setOnText("开")
        self.switchButton.setOffText("关")
        self.hBoxLayout.addWidget(self.switchButton, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def isChecked(self):
        return self.switchButton.isChecked()

    def setChecked(self, checked):
        self.switchButton.setChecked(checked)


class RandomUASettingCard(ExpandGroupSettingCard):
    """随机UA设置卡 - 包含UA类型选择"""

    def __init__(self, parent=None):
        super().__init__(FluentIcon.ROBOT, "随机 UA", "模拟不同的 User-Agent，例如微信环境或浏览器直链环境", parent)
        self.checkboxes: Dict[str, CheckBox] = {}

        # 开关
        self.switchButton = SwitchButton(self, IndicatorPosition.RIGHT)
        self.switchButton.setOnText("开")
        self.switchButton.setOffText("关")
        self.addWidget(self.switchButton)

        # UA 类型选择容器
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(48, 12, 48, 12)
        grid.setSpacing(12)

        col, row = 0, 0
        for key, preset in USER_AGENT_PRESETS.items():
            label = preset.get("label") or key
            cb = CheckBox(label, container)
            cb.setChecked(key == "pc_web")
            self.checkboxes[key] = cb
            grid.addWidget(cb, row, col)
            col += 1
            if col >= 3:
                col = 0
                row += 1

        self.addGroupWidget(container)

    def isChecked(self):
        return self.switchButton.isChecked()

    def setChecked(self, checked):
        self.switchButton.setChecked(checked)

    def setUAEnabled(self, enabled):
        for cb in self.checkboxes.values():
            cb.setEnabled(enabled)


class TimeRangeSettingCard(SettingCard):
    """时间范围设置卡"""

    def __init__(self, icon, title, content, parent=None):
        super().__init__(icon, title, content, parent)
        self.min_seconds = 0
        self.max_seconds = 0

        self.minBtn = PushButton("0分0秒", self)
        self.minBtn.setMinimumWidth(90)
        self.maxBtn = PushButton("0分0秒", self)
        self.maxBtn.setMinimumWidth(90)

        self.hBoxLayout.addWidget(self.minBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addWidget(BodyLabel("~", self))
        self.hBoxLayout.addWidget(self.maxBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def setEnabled(self, enabled):
        self.minBtn.setEnabled(enabled)
        self.maxBtn.setEnabled(enabled)


class RuntimePage(ScrollArea):
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
        self._sync_random_ua(self.random_ua_card.isChecked())

    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # ========== 运行参数组 ==========
        run_group = SettingCardGroup("运行参数", self.view)

        self.target_card = SpinBoxSettingCard(
            FluentIcon.DOCUMENT, "目标份数", "设置要提交的问卷数量",
            min_val=1, max_val=99999, default=10, parent=run_group
        )
        self.thread_card = SpinBoxSettingCard(
            FluentIcon.APPLICATION, "并发浏览器", "同时运行的浏览器数量 (1-12)",
            min_val=1, max_val=12, default=2, parent=run_group
        )
        self.fail_stop_card = SwitchSettingCard(
            FluentIcon.CANCEL, "失败过多自动停止", "连续失败次数过多时自动停止运行",
            parent=run_group
        )
        self.fail_stop_card.setChecked(True)

        run_group.addSettingCard(self.target_card)
        run_group.addSettingCard(self.thread_card)
        run_group.addSettingCard(self.fail_stop_card)
        layout.addWidget(run_group)

        # ========== 时间控制组 ==========
        time_group = SettingCardGroup("时间控制", self.view)

        self.interval_card = TimeRangeSettingCard(
            FluentIcon.HISTORY, "提交间隔", "两次提交之间的等待时间范围",
            parent=time_group
        )
        self.answer_card = TimeRangeSettingCard(
            FluentIcon.STOP_WATCH, "作答时长", "模拟作答所需的时间范围",
            parent=time_group
        )
        self.timed_card = TimedModeSettingCard(
            FluentIcon.SPEED_HIGH, "定时模式", "启用后忽略时间设置，在开放后立即提交",
            parent=time_group
        )

        time_group.addSettingCard(self.interval_card)
        time_group.addSettingCard(self.answer_card)
        time_group.addSettingCard(self.timed_card)
        layout.addWidget(time_group)

        # ========== 特性开关组 ==========
        feature_group = SettingCardGroup("特性开关", self.view)

        self.random_ip_card = RandomIPSettingCard(parent=feature_group)
        self.random_ua_card = RandomUASettingCard(parent=feature_group)
        self.ua_checkboxes = self.random_ua_card.checkboxes

        feature_group.addSettingCard(self.random_ip_card)
        feature_group.addSettingCard(self.random_ua_card)
        layout.addWidget(feature_group)

        layout.addStretch(1)

        # 兼容旧代码的属性别名
        self.target_spin = self.target_card.spinBox
        self.thread_spin = self.thread_card.spinBox
        self.fail_stop_switch = self.fail_stop_card.switchButton
        self.interval_min_btn = self.interval_card.minBtn
        self.interval_max_btn = self.interval_card.maxBtn
        self.answer_min_btn = self.answer_card.minBtn
        self.answer_max_btn = self.answer_card.maxBtn
        self.timed_switch = self.timed_card.switchButton
        self.random_ip_switch = self.random_ip_card.switchButton
        self.random_ua_switch = self.random_ua_card.switchButton
        self.proxy_source_combo = self.random_ip_card.proxyCombo
        self.custom_api_edit = self.random_ip_card.customApiEdit

        # 时间秒数存储
        self.interval_min_seconds = 0
        self.interval_max_seconds = 0
        self.answer_min_seconds = 0
        self.answer_max_seconds = 0

    def _bind_events(self):
        self.random_ip_switch.checkedChanged.connect(self._on_random_ip_toggled)
        self.random_ua_switch.checkedChanged.connect(self._sync_random_ua)
        self.timed_switch.checkedChanged.connect(self._sync_timed_mode)
        self.timed_card.helpButton.clicked.connect(self._show_timed_mode_help)
        self.interval_min_btn.clicked.connect(lambda: self._show_time_picker("interval_min"))
        self.interval_max_btn.clicked.connect(lambda: self._show_time_picker("interval_max"))
        self.answer_min_btn.clicked.connect(lambda: self._show_time_picker("answer_min"))
        self.answer_max_btn.clicked.connect(lambda: self._show_time_picker("answer_max"))
        self.proxy_source_combo.currentIndexChanged.connect(self._on_proxy_source_changed)

    def _show_timed_mode_help(self):
        """显示定时模式说明"""
        content = (
            "启用后，程序会忽略「提交间隔」和「作答时长」设置，改为高频刷新并在开放后立即提交。\n\n"
            "典型应用场景：\n"
            "- 抢志愿填报名额\n"
            "- 抢课程选课名额（如大学选课问卷）\n"
            "- 抢活动报名名额（如讲座、比赛报名）\n"
            "- 其他在特定时间点开放的问卷"
        )
        PopupTeachingTip.create(
            target=self.timed_card.helpButton,
            icon=FluentIcon.INFO,
            title='定时模式说明',
            content=content,
            isClosable=True,
            tailPosition=TeachingTipTailPosition.BOTTOM,
            duration=-1,
            parent=self.view
        )

    def _on_random_ip_toggled(self, enabled: bool):
        """参数页随机IP开关切换时，同步到主页并显示弹窗"""
        main_win = self.window()
        dashboard = getattr(main_win, "dashboard", None)
        if dashboard is not None:
            self.random_ip_switch.blockSignals(True)
            try:
                dashboard._on_random_ip_toggled(2 if enabled else 0)
            finally:
                self.random_ip_switch.blockSignals(False)

    def _on_proxy_source_changed(self):
        """代理源选择变化时更新设置"""
        idx = self.proxy_source_combo.currentIndex()
        source = str(self.proxy_source_combo.itemData(idx)) if idx >= 0 else "default"
        if not source or source == "None":
            source = "default"
        try:
            from wjx.network.random_ip import set_proxy_source, set_proxy_api_override
            if source == "custom":
                api_url = self.custom_api_edit.text().strip()
                set_proxy_api_override(api_url if api_url else None)
            set_proxy_source(source)
        except Exception:
            pass

    def _sync_random_ua(self, enabled: bool):
        try:
            self.random_ua_card.setUAEnabled(bool(enabled))
        except Exception:
            pass

    def _sync_timed_mode(self, enabled: bool):
        """定时模式切换时禁用/启用时间控制按钮"""
        try:
            self.interval_card.setEnabled(not enabled)
            self.answer_card.setEnabled(not enabled)
        except Exception:
            pass

    def _show_time_picker(self, field: str):
        """显示时间选择对话框"""
        if field == "interval_min":
            current_seconds = self.interval_min_seconds
            title = "设置提交间隔最小值"
        elif field == "interval_max":
            current_seconds = self.interval_max_seconds
            title = "设置提交间隔最大值"
        elif field == "answer_min":
            current_seconds = self.answer_min_seconds
            title = "设置作答时长最小值"
        else:
            current_seconds = self.answer_max_seconds
            title = "设置作答时长最大值"

        dialog = QDialog(self.window() or self)
        dialog.setWindowTitle(title)
        dialog.setFixedSize(480, 360)
        main_layout = QVBoxLayout(dialog)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        title_label = SubtitleLabel(title, dialog)
        main_layout.addWidget(title_label)

        card = CardWidget(dialog)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(20)

        # 实时预览
        preview_container = QWidget(card)
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(4)
        preview_hint = BodyLabel("当前设置", card)
        preview_hint.setStyleSheet("color: #888; font-size: 11px;")
        preview_value = StrongBodyLabel("0分0秒", card)
        preview_value.setStyleSheet("font-size: 18px; color: #2563EB;")
        preview_layout.addWidget(preview_hint, alignment=Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(preview_value, alignment=Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(preview_container)

        # 分钟控制
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

        # 秒控制
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

        def update_preview():
            m = minutes_spin.value()
            s = seconds_spin.value()
            preview_value.setText(f"{m}分{s}秒")

        minutes_slider.valueChanged.connect(minutes_spin.setValue)
        minutes_spin.valueChanged.connect(minutes_slider.setValue)
        minutes_spin.valueChanged.connect(lambda: update_preview())
        seconds_slider.valueChanged.connect(seconds_spin.setValue)
        seconds_spin.valueChanged.connect(seconds_slider.setValue)
        seconds_spin.valueChanged.connect(lambda: update_preview())
        update_preview()

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
            text = f"{minutes_spin.value()}分{seconds_spin.value()}秒"
            if field == "interval_min":
                self.interval_min_seconds = total_seconds
                self.interval_min_btn.setText(text)
            elif field == "interval_max":
                self.interval_max_seconds = total_seconds
                self.interval_max_btn.setText(text)
            elif field == "answer_min":
                self.answer_min_seconds = total_seconds
                self.answer_min_btn.setText(text)
            else:
                self.answer_max_seconds = total_seconds
                self.answer_max_btn.setText(text)

    def update_config(self, cfg: RuntimeConfig):
        cfg.target = max(1, self.target_spin.value())
        cfg.threads = max(1, self.thread_spin.value())
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

        self.random_ip_switch.blockSignals(True)
        self.random_ip_switch.setChecked(cfg.random_ip_enabled)
        self.random_ip_switch.blockSignals(False)
        self.random_ua_switch.setChecked(cfg.random_ua_enabled)

        active = set(cfg.random_ua_keys or [])
        for key, cb in self.ua_checkboxes.items():
            cb.setChecked((not active and key == "pc_web") or key in active)
        self._sync_random_ua(self.random_ua_switch.isChecked())
        self.fail_stop_switch.setChecked(cfg.fail_stop_enabled)

        try:
            proxy_source = getattr(cfg, "proxy_source", "default")
            custom_api = getattr(cfg, "custom_proxy_api", "")
            idx = self.proxy_source_combo.findData(proxy_source)
            if idx >= 0:
                self.proxy_source_combo.setCurrentIndex(idx)
            self.custom_api_edit.setText(custom_api)
            self.random_ip_card.customApiRow.setVisible(proxy_source == "custom")
            from wjx.network.random_ip import set_proxy_source, set_proxy_api_override
            if proxy_source == "custom" and custom_api:
                set_proxy_api_override(custom_api)
            set_proxy_source(proxy_source)
        except Exception:
            pass

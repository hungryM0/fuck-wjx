"""运行参数设置页面"""
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception


from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    FluentIcon,
    PopupTeachingTip,
    ScrollArea,
    SettingCard,
    SettingCardGroup,
    TeachingTipTailPosition,
)

from wjx.ui.controller import RunController
from wjx.ui.pages.workbench.runtime.ai import RuntimeAISection
from wjx.ui.pages.workbench.runtime.cards import (
    RandomIPSettingCard,
    RandomUASettingCard,
    TimeRangeSettingCard,
    TimedModeSettingCard,
)
from wjx.ui.widgets.setting_cards import SpinBoxSettingCard, SwitchSettingCard
from wjx.utils.io.load_save import RuntimeConfig


class RuntimePage(ScrollArea):
    """独立的运行参数/开关页，方便在侧边栏查看。"""



    def __init__(self, controller: RunController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self.view.setObjectName("settings_view")
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
            min_val=1, max_val=9999, default=10, parent=run_group
        )
        self.thread_card = SpinBoxSettingCard(
            FluentIcon.APPLICATION, "并发浏览器", "同时运行的浏览器数量 (1-12)",
            min_val=1, max_val=12, default=2, parent=run_group
        )
        spin_width = self.target_card.suggestSpinBoxWidthForDigits(4)
        self.target_card.setSpinBoxWidth(spin_width)
        self.thread_card.setSpinBoxWidth(spin_width)

        self.reliability_mode_card = SwitchSettingCard(
            FluentIcon.CERTIFICATE, "提升问卷信效度", "启用后量表/矩阵/评价题将共享答题倾向，针对信效度优化作答策略",
            parent=run_group
        )
        self.reliability_mode_card.setChecked(True)

        # 信效度模式类型选择（使用自定义卡片）
        self.reliability_type_card = SettingCard(
            FluentIcon.SETTING,
            "信效度模式",
            "选择信效度保证的实现方式",
            run_group
        )
        # 添加下拉框
        self.reliability_type_combo = ComboBox(self.reliability_type_card)
        self.reliability_type_combo.addItems(["简单倾向模式（快速）", "潜变量模型（精确）"])
        self.reliability_type_combo.setCurrentIndex(0)
        self.reliability_type_combo.setFixedWidth(200)
        self.reliability_type_card.hBoxLayout.addWidget(self.reliability_type_combo)
        self.reliability_type_card.hBoxLayout.addSpacing(16)
        self.reliability_type_card.setVisible(False)  # 默认隐藏，开启信效度时显示

        # 目标 Alpha 设置（仅潜变量模式显示）
        self.alpha_card = SpinBoxSettingCard(
            FluentIcon.CERTIFICATE,
            "目标 Cronbach's Alpha",
            "设置期望的信效度系数（0.70-0.95，推荐0.85）",
            min_val=70, max_val=95, default=85, parent=run_group
        )
        self.alpha_card.setVisible(False)  # 默认隐藏

        self.fail_stop_card = SwitchSettingCard(
            FluentIcon.CANCEL, "失败过多自动停止", "连续失败次数过多时自动停止运行",
            parent=run_group
        )
        self.fail_stop_card.setChecked(True)

        self.pause_on_aliyun_card = SwitchSettingCard(
            FluentIcon.PAUSE,
            "触发智能验证自动暂停",
            "检测到阿里云智能验证时暂停执行（默认开启，建议配合随机 IP）",
            parent=run_group,
        )
        self.pause_on_aliyun_card.setChecked(True)

        self.headless_card = SwitchSettingCard(
            FluentIcon.SPEED_HIGH,
            "无头模式",
            "开启后浏览器在后台运行，不显示窗口，可提高并发性能",
            parent=run_group,
        )
        self.headless_card.setChecked(False)

        run_group.addSettingCard(self.target_card)
        run_group.addSettingCard(self.thread_card)
        run_group.addSettingCard(self.reliability_mode_card)
        run_group.addSettingCard(self.reliability_type_card)
        run_group.addSettingCard(self.alpha_card)
        run_group.addSettingCard(self.fail_stop_card)
        run_group.addSettingCard(self.pause_on_aliyun_card)
        run_group.addSettingCard(self.headless_card)
        layout.addWidget(run_group)

        # ========== 时间控制组 ==========
        time_group = SettingCardGroup("时间控制", self.view)
        # 在标题后添加小字提示（保持原标题字号）
        time_hint = BodyLabel("（其实问卷星官方并不会因为你提交过快就封你号）", time_group)
        time_hint.setStyleSheet("color: green; font-size: 12px;")
        # 创建水平布局放置标题和提示
        title_container = QWidget(time_group)
        title_h_layout = QHBoxLayout(title_container)
        title_h_layout.setContentsMargins(0, 0, 0, 0)
        title_h_layout.setSpacing(8)
        # 移动标题到新容器
        time_group.titleLabel.setParent(title_container)
        title_h_layout.addWidget(time_group.titleLabel)
        title_h_layout.addWidget(time_hint)
        title_h_layout.addStretch()
        # 替换原标题位置
        time_group.vBoxLayout.insertWidget(0, title_container)

        self.interval_card = TimeRangeSettingCard(
            FluentIcon.HISTORY, "提交间隔", "两次提交之间的等待时间",
            max_seconds=300,
            parent=time_group
        )
        self.answer_card = TimeRangeSettingCard(
            FluentIcon.STOP_WATCH, "作答时长", "设置单份作答消耗的时间",
            max_seconds=120,
            parent=time_group
        )
        self.timed_card = TimedModeSettingCard(
            FluentIcon.RINGER, "定时模式", "启用后忽略时间设置，在开放后立即提交",
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

        feature_group.addSettingCard(self.random_ip_card)
        feature_group.addSettingCard(self.random_ua_card)
        layout.addWidget(feature_group)

        # ========== AI 填空助手组 ==========
        self.ai_section = RuntimeAISection(self.view, self)
        self.ai_section.bind_to_layout(layout)

        layout.addStretch(1)

        # 兼容旧代码的属性别名
        self.target_spin = self.target_card.spinBox
        self.thread_spin = self.thread_card.spinBox
        self.fail_stop_switch = self.fail_stop_card.switchButton
        self.pause_on_aliyun_switch = self.pause_on_aliyun_card.switchButton
        self.reliability_mode_switch = self.reliability_mode_card.switchButton
        self.timed_switch = self.timed_card.switchButton
        self.random_ip_switch = self.random_ip_card.switchButton
        self.random_ua_switch = self.random_ua_card.switchButton
        self.proxy_source_combo = self.random_ip_card.proxyCombo
        self.custom_api_edit = self.random_ip_card.customApiEdit

    def _bind_events(self):
        self.random_ip_switch.checkedChanged.connect(self._on_random_ip_toggled)
        self.random_ua_switch.checkedChanged.connect(self._on_random_ua_toggled)
        self.timed_switch.checkedChanged.connect(self._sync_timed_mode)
        self.timed_card.helpButton.clicked.connect(self._show_timed_mode_help)
        self.proxy_source_combo.currentIndexChanged.connect(self._on_proxy_source_changed)
        self.reliability_mode_switch.checkedChanged.connect(self._on_reliability_mode_toggled)
        self.reliability_type_combo.currentIndexChanged.connect(self._on_reliability_type_changed)

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

    def _on_random_ua_toggled(self, enabled: bool):
        main_win = self.window()
        dashboard = getattr(main_win, "dashboard", None)
        if dashboard is not None and hasattr(dashboard, "random_ua_cb"):
            dashboard.random_ua_cb.blockSignals(True)
            dashboard.random_ua_cb.setChecked(enabled)
            dashboard.random_ua_cb.blockSignals(False)
        self._sync_random_ua(enabled)

    def _on_proxy_source_changed(self):
        """代理源选择变化时更新设置"""
        idx = self.proxy_source_combo.currentIndex()
        source = str(self.proxy_source_combo.itemData(idx)) if idx >= 0 else "default"
        if not source or source == "None":
            source = "default"
        try:
            from wjx.network.proxy import set_proxy_source, set_proxy_api_override
            if source == "custom":
                api_url = self.custom_api_edit.text().strip()
                set_proxy_api_override(api_url if api_url else None)
            set_proxy_source(source)
        except Exception as exc:
            log_suppressed_exception("_on_proxy_source_changed: from wjx.network.proxy import set_proxy_source, set_proxy_api_override", exc, level=logging.WARNING)

    def _sync_random_ua(self, enabled: bool):
        try:
            self.random_ua_card.setUAEnabled(bool(enabled))
        except Exception as exc:
            log_suppressed_exception("_sync_random_ua: self.random_ua_card.setUAEnabled(bool(enabled))", exc, level=logging.WARNING)

    def _sync_timed_mode(self, enabled: bool):
        """定时模式切换时禁用/启用时间控制按钮"""
        try:
            self.interval_card.setEnabled(not enabled)
            self.answer_card.setEnabled(not enabled)
        except Exception as exc:
            log_suppressed_exception("_sync_timed_mode: self.interval_card.setEnabled(not enabled)", exc, level=logging.WARNING)

    def _on_reliability_mode_toggled(self, enabled: bool):
        """信效度模式开关切换"""
        self.reliability_type_card.setVisible(enabled)
        if enabled:
            self._on_reliability_type_changed(self.reliability_type_combo.currentIndex())
        else:
            self.alpha_card.setVisible(False)

    def _on_reliability_type_changed(self, index: int):
        """信效度模式类型切换"""
        # 0: 简单模式, 1: 潜变量模式
        is_psychometric = (index == 1)
        self.alpha_card.setVisible(is_psychometric)

    def update_config(self, cfg: RuntimeConfig):
        cfg.target = max(1, self.target_spin.value())
        cfg.threads = max(1, self.thread_spin.value())
        cfg.browser_preference = []  # 固定使用默认顺序：Edge → Chrome → Chromium
        interval_min, interval_max = self.interval_card.getRange()
        cfg.submit_interval = (interval_min, interval_max)
        answer_min, answer_max = self.answer_card.getRange()
        cfg.answer_duration = (answer_min, answer_max)
        cfg.timed_mode_enabled = self.timed_switch.isChecked()
        cfg.random_ip_enabled = self.random_ip_switch.isChecked()
        cfg.random_ua_enabled = self.random_ua_switch.isChecked()
        cfg.random_ua_ratios = self.random_ua_card.getRatios() if cfg.random_ua_enabled else {"wechat": 33, "mobile": 33, "pc": 34}
        cfg.fail_stop_enabled = self.fail_stop_switch.isChecked()
        cfg.pause_on_aliyun_captcha = self.pause_on_aliyun_switch.isChecked()
        cfg.reliability_mode_enabled = self.reliability_mode_switch.isChecked()
        cfg.reliability_mode_type = "psychometric" if self.reliability_type_combo.currentIndex() == 1 else "simple"
        cfg.psycho_target_alpha = self.alpha_card.spinBox.value() / 100.0  # 转换为 0.70-0.95
        cfg.headless_mode = self.headless_card.switchButton.isChecked()
        try:
            idx = self.proxy_source_combo.currentIndex()
            source = str(self.proxy_source_combo.itemData(idx)) if idx >= 0 else "default"
            if not source or source == "None":
                source = "default"
            cfg.proxy_source = source
            cfg.custom_proxy_api = self.custom_api_edit.text().strip() if source == "custom" else ""
            cfg.proxy_area_code = self.random_ip_card.get_area_code()
        except Exception:
            cfg.proxy_source = "default"
            cfg.custom_proxy_api = ""
            cfg.proxy_area_code = None
        self.ai_section.update_config(cfg)

    def apply_config(self, cfg: RuntimeConfig):
        self.target_spin.setValue(max(1, cfg.target))
        self.thread_spin.setValue(max(1, cfg.threads))

        interval_min = max(0, cfg.submit_interval[0])
        interval_max = max(interval_min, cfg.submit_interval[1])
        self.interval_card.setRange(interval_min, interval_max)

        answer_min = max(0, cfg.answer_duration[0])
        answer_max = max(answer_min, cfg.answer_duration[1])
        self.answer_card.setRange(answer_min, answer_max)

        self.timed_switch.setChecked(cfg.timed_mode_enabled)
        self._sync_timed_mode(cfg.timed_mode_enabled)

        self.random_ip_switch.blockSignals(True)
        self.random_ip_switch.setChecked(cfg.random_ip_enabled)
        self.random_ip_switch.blockSignals(False)
        self.random_ip_card._sync_ip_enabled(cfg.random_ip_enabled)
        self.random_ua_switch.setChecked(cfg.random_ua_enabled)

        # 应用UA占比配置
        try:
            ratios = getattr(cfg, "random_ua_ratios", None)
            if ratios and isinstance(ratios, dict):
                self.random_ua_card.setRatios(ratios)
            else:
                self.random_ua_card.setRatios({"wechat": 33, "mobile": 33, "pc": 34})
        except Exception as exc:
            log_suppressed_exception("apply_config: self.random_ua_card.setRatios(ratios)", exc, level=logging.WARNING)
            self.random_ua_card.setRatios({"wechat": 33, "mobile": 33, "pc": 34})

        self._sync_random_ua(self.random_ua_switch.isChecked())
        self.fail_stop_switch.setChecked(cfg.fail_stop_enabled)
        self.pause_on_aliyun_switch.setChecked(getattr(cfg, "pause_on_aliyun_captcha", True))
        self.reliability_mode_switch.setChecked(getattr(cfg, "reliability_mode_enabled", True))
        
        # 应用信效度模式类型
        reliability_type = getattr(cfg, "reliability_mode_type", "simple")
        self.reliability_type_combo.setCurrentIndex(1 if reliability_type == "psychometric" else 0)
        
        # 应用目标 Alpha
        alpha_value = int(getattr(cfg, "psycho_target_alpha", 0.85) * 100)
        self.alpha_card.spinBox.setValue(alpha_value)
        
        # 同步可见性
        self._on_reliability_mode_toggled(self.reliability_mode_switch.isChecked())
        
        self.headless_card.setChecked(getattr(cfg, "headless_mode", False))

        try:
            proxy_source = getattr(cfg, "proxy_source", "default")
            custom_api = getattr(cfg, "custom_proxy_api", "")
            idx = self.proxy_source_combo.findData(proxy_source)
            if idx >= 0:
                self.proxy_source_combo.setCurrentIndex(idx)
            self.custom_api_edit.setText(custom_api)
            self.random_ip_card.customApiRow.setVisible(proxy_source == "custom")
            from wjx.network.proxy import set_proxy_source, set_proxy_api_override
            if proxy_source == "custom" and custom_api:
                set_proxy_api_override(custom_api)
            set_proxy_source(proxy_source)
            area_code = getattr(cfg, "proxy_area_code", None)
            self.random_ip_card.set_area_code(area_code)
        except Exception as exc:
            log_suppressed_exception("apply_config: proxy_source = getattr(cfg, \"proxy_source\", \"default\")", exc, level=logging.WARNING)
        self.ai_section.apply_config(cfg)


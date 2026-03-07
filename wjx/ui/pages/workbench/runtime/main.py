"""运行参数设置页面"""
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception


from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PopupTeachingTip,
    ScrollArea,
    SettingCardGroup,
    TeachingTipTailPosition,
)

from wjx.ui.controller import RunController
from wjx.ui.pages.workbench.runtime.ai import RuntimeAISection
from wjx.ui.pages.workbench.runtime.cards import (
    RandomIPSettingCard,
    RandomUASettingCard,
    ReliabilitySettingCard,
    TimeRangeSettingCard,
    TimedModeSettingCard,
)
from wjx.ui.widgets.setting_cards import SpinBoxSettingCard, SwitchSettingCard
from wjx.utils.io.load_save import RuntimeConfig


class RuntimePage(ScrollArea):
    """独立的运行参数/开关页，方便在侧边栏查看。"""

    MIN_THREADS = 1
    NON_HEADLESS_MAX_THREADS = 8
    HEADLESS_MAX_THREADS = 16
    SUBMIT_INTERVAL_MAX_SECONDS = 300
    ANSWER_DURATION_MAX_SECONDS = 600


    def __init__(self, controller: RunController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._suppress_headless_tip = False
        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self.view.setObjectName("settings_view")
        self._build_ui()
        self._bind_events()
        self._sync_random_ua(self.random_ua_card.isChecked())
        self._apply_thread_limit_by_headless(self.headless_card.isChecked())

    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # ========== 特性开关组 ==========
        feature_group = SettingCardGroup("特性开关", self.view)

        self.random_ip_card = RandomIPSettingCard(parent=feature_group)
        self.random_ua_card = RandomUASettingCard(parent=feature_group)

        feature_group.addSettingCard(self.random_ip_card)
        feature_group.addSettingCard(self.random_ua_card)
        layout.addWidget(feature_group)

        # ========== 作答设置组 ==========
        run_group = SettingCardGroup("作答设置", self.view)

        self.target_card = SpinBoxSettingCard(
            FluentIcon.DOCUMENT, "目标份数", "设置要提交的问卷数量",
            min_val=1, max_val=9999, default=10, parent=run_group
        )
        self.thread_card = SpinBoxSettingCard(
            FluentIcon.APPLICATION, "并发浏览器", "同时开多个浏览器窗口提交问卷，启用无头模式可设置更高的并发数",
            min_val=self.MIN_THREADS, max_val=self.NON_HEADLESS_MAX_THREADS, default=2, parent=run_group
        )
        spin_width = self.target_card.suggestSpinBoxWidthForDigits(4)
        self.target_card.setSpinBoxWidth(spin_width)
        self.thread_card.setSpinBoxWidth(spin_width)

        self.reliability_card = ReliabilitySettingCard(parent=run_group)
        self.reliability_card.setChecked(True)
        self.reliability_card.set_alpha(0.85)

        self.headless_card = SwitchSettingCard(
            FluentIcon.SPEED_HIGH,
            "无头模式",
            "开启后浏览器在后台运行，不显示窗口，可提高并发性能",
            parent=run_group,
        )
        self.headless_card.setChecked(True)

        run_group.addSettingCard(self.target_card)
        run_group.addSettingCard(self.thread_card)
        run_group.addSettingCard(self.reliability_card)
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
            FluentIcon.HISTORY,
            "提交间隔",
            f"两次提交之间的等待时间（0-{self.SUBMIT_INTERVAL_MAX_SECONDS} 秒）",
            max_seconds=self.SUBMIT_INTERVAL_MAX_SECONDS,
            parent=time_group
        )
        self.answer_card = TimeRangeSettingCard(
            FluentIcon.STOP_WATCH,
            "作答时长",
            f"设置单份作答耗时（0-{self.ANSWER_DURATION_MAX_SECONDS} 秒），按20%比例随机上下抖动",
            max_seconds=self.ANSWER_DURATION_MAX_SECONDS,
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

        # ========== AI 填空助手组 ==========
        self.ai_section = RuntimeAISection(self.view, self)
        self.ai_section.bind_to_layout(layout)

        layout.addStretch(1)

        # 兼容旧代码的属性别名
        self.target_spin = self.target_card.spinBox
        self.thread_spin = self.thread_card.spinBox
        self.reliability_mode_switch = self.reliability_card.switchButton
        self.timed_switch = self.timed_card.switchButton
        self.random_ip_switch = self.random_ip_card.switchButton
        self.random_ua_switch = self.random_ua_card.switchButton
        self.proxy_source_combo = self.random_ip_card.proxyCombo
        self.custom_api_edit = self.random_ip_card.customApiEdit

    def _bind_events(self):
        self.target_spin.valueChanged.connect(self._sync_target_to_dashboard)
        self.thread_spin.valueChanged.connect(self._sync_threads_to_dashboard)
        self.random_ip_switch.checkedChanged.connect(self._on_random_ip_toggled)
        self.random_ua_switch.checkedChanged.connect(self._on_random_ua_toggled)
        self.headless_card.switchButton.checkedChanged.connect(self._on_headless_toggled)
        self.timed_switch.checkedChanged.connect(self._sync_timed_mode)
        self.timed_card.helpButton.clicked.connect(self._show_timed_mode_help)
        self.proxy_source_combo.currentIndexChanged.connect(self._on_proxy_source_changed)
        self.reliability_mode_switch.checkedChanged.connect(self._on_reliability_mode_toggled)

    def focus_answer_duration_setting(self):
        """跳转并聚焦到“作答时长”设置项。"""

        def _focus_target():
            target_edit = getattr(self.answer_card, "inputEdit", None)
            try:
                # 把“作答时长”滚动到视口靠上位置，而不是仅仅可见
                top_y = self.answer_card.mapTo(self.view, QPoint(0, 0)).y()
                target_scroll = max(0, int(top_y - 16))
                self.verticalScrollBar().setValue(target_scroll)
            except Exception as exc:
                log_suppressed_exception("focus_answer_duration_setting: verticalScrollBar().setValue(...)", exc, level=logging.DEBUG)
            try:
                if target_edit is not None:
                    target_edit.setFocus()
                    target_edit.selectAll()
            except Exception as exc:
                log_suppressed_exception("focus_answer_duration_setting: self.answer_card.inputEdit.setFocus()", exc, level=logging.DEBUG)
            try:
                # 兜底：极端布局场景下再做一次“至少可见”
                self.ensureWidgetVisible(self.answer_card, 0, 24)
            except Exception as exc:
                log_suppressed_exception("focus_answer_duration_setting: ensureWidgetVisible", exc, level=logging.DEBUG)

        # 页面切换后做两次定位，避免首帧布局尚未稳定导致的偏移
        QTimer.singleShot(0, _focus_target)
        QTimer.singleShot(80, _focus_target)

    def _resolve_thread_max(self, headless_enabled: bool) -> int:
        return self.HEADLESS_MAX_THREADS if headless_enabled else self.NON_HEADLESS_MAX_THREADS

    def _apply_thread_limit_by_headless(self, headless_enabled: bool) -> bool:
        max_threads = self._resolve_thread_max(bool(headless_enabled))
        previous_value = int(self.thread_spin.value())
        clamped = previous_value > max_threads

        self.thread_spin.setRange(self.MIN_THREADS, max_threads)
        if clamped:
            self.thread_spin.setValue(max_threads)

        main_win = self.window()
        dashboard = getattr(main_win, "dashboard", None)
        if dashboard is not None and hasattr(dashboard, "thread_spin"):
            dashboard.thread_spin.setRange(self.MIN_THREADS, max_threads)
            if dashboard.thread_spin.value() > max_threads:
                dashboard.thread_spin.blockSignals(True)
                dashboard.thread_spin.setValue(max_threads)
                dashboard.thread_spin.blockSignals(False)

        return clamped

    def _show_headless_limit_tip(self):
        parent = self.window() or self.view
        InfoBar.info(
            "",
            f"已关闭无头模式，并发上限为 {self.NON_HEADLESS_MAX_THREADS}，已自动调整",
            parent=parent,
            position=InfoBarPosition.TOP,
            duration=2200,
        )

    def _on_headless_toggled(self, enabled: bool):
        clamped = self._apply_thread_limit_by_headless(bool(enabled))
        if (not enabled) and clamped and not self._suppress_headless_tip:
            self._show_headless_limit_tip()

    def _sync_target_to_dashboard(self, value: int):
        main_win = self.window()
        dashboard = getattr(main_win, "dashboard", None)
        if dashboard is not None and hasattr(dashboard, "target_spin"):
            dashboard.target_spin.blockSignals(True)
            dashboard.target_spin.setValue(int(value))
            dashboard.target_spin.blockSignals(False)

    def _sync_threads_to_dashboard(self, value: int):
        main_win = self.window()
        dashboard = getattr(main_win, "dashboard", None)
        if dashboard is not None and hasattr(dashboard, "thread_spin"):
            dashboard.thread_spin.blockSignals(True)
            dashboard.thread_spin.setValue(int(value))
            dashboard.thread_spin.blockSignals(False)

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
        try:
            self.reliability_card._sync_enabled(bool(enabled))
        except Exception as exc:
            log_suppressed_exception("_on_reliability_mode_toggled: reliability_card._sync_enabled", exc, level=logging.DEBUG)

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
        cfg.fail_stop_enabled = True
        cfg.pause_on_aliyun_captcha = True
        cfg.reliability_mode_enabled = self.reliability_mode_switch.isChecked()
        try:
            cfg.psycho_target_alpha = self.reliability_card.get_alpha()
        except Exception as exc:
            log_suppressed_exception("update_config: reliability_card.get_alpha()", exc, level=logging.DEBUG)
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
        self.reliability_mode_switch.setChecked(getattr(cfg, "reliability_mode_enabled", True))
        try:
            self.reliability_card.set_alpha(getattr(cfg, "psycho_target_alpha", 0.85))
            self.reliability_card._sync_enabled(self.reliability_mode_switch.isChecked())
        except Exception as exc:
            log_suppressed_exception("apply_config: reliability_card.set_alpha", exc, level=logging.DEBUG)

        self._suppress_headless_tip = True
        try:
            self.headless_card.setChecked(getattr(cfg, "headless_mode", True))
            self._apply_thread_limit_by_headless(self.headless_card.isChecked())
        finally:
            self._suppress_headless_tip = False

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


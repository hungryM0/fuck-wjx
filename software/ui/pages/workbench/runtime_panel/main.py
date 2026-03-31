"""运行参数设置页面"""
import logging
from software.logging.action_logger import bind_logged_action, log_action
from software.logging.log_utils import log_suppressed_exception


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

from software.ui.controller import RunController
from software.ui.pages.workbench.runtime_panel.ai import RuntimeAISection
from software.ui.pages.workbench.runtime_panel.cards import (
    RandomIPSettingCard,
    RandomUASettingCard,
    ReliabilitySettingCard,
    TimeRangeSettingCard,
    TimedModeSettingCard,
)
from software.ui.widgets.setting_cards import SpinBoxSettingCard, SwitchSettingCard
from software.io.config import RuntimeConfig
from software.ui.helpers.proxy_access import apply_proxy_source_settings, get_proxy_minute_by_answer_seconds

_PROXY_SOURCE_DEFAULT = "default"
_PROXY_SOURCE_BENEFIT = "benefit"
_PROXY_SOURCE_CUSTOM = "custom"


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
        self._last_benefit_proxy_compatible = None
        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self.view.setObjectName("settings_view")
        self._build_ui()
        self._bind_events()
        self.controller.runtimeUiStateChanged.connect(self._apply_runtime_ui_state)
        self.controller.randomIpLoadingChanged.connect(self._apply_random_ip_loading)
        self._sync_random_ua(self.random_ua_card.isChecked())
        self._apply_thread_limit_by_headless(self.headless_card.isChecked())
        self.controller.set_runtime_ui_state(
            emit=False,
            target=self.target_card.spinBox.value(),
            threads=self.thread_card.spinBox.value(),
            random_ip_enabled=self.random_ip_card.switchButton.isChecked(),
            headless_mode=self.headless_card.switchButton.isChecked(),
            timed_mode_enabled=self.timed_card.switchButton.isChecked(),
            proxy_source=self._get_selected_proxy_source(),
            answer_duration=self._card_value_as_range(self.answer_card),
        )

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
        self.reliability_card.set_alpha(0.9)

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
        time_hint = BodyLabel("（其实官方并不会因为你提交过快就封你号）", time_group)
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

    def _bind_events(self):
        self.target_card.spinBox.valueChanged.connect(lambda value: self.controller.set_runtime_ui_state(target=int(value)))
        self.thread_card.spinBox.valueChanged.connect(lambda value: self.controller.set_runtime_ui_state(threads=int(value)))
        bind_logged_action(
            self.random_ip_card.switchButton.checkedChanged,
            self._on_random_ip_toggled,
            scope="CONFIG",
            event="toggle_random_ip",
            target="random_ip_switch",
            page="runtime",
            payload_factory=lambda enabled: {"enabled": bool(enabled)},
        )
        bind_logged_action(
            self.random_ua_card.switchButton.checkedChanged,
            self._on_random_ua_toggled,
            scope="CONFIG",
            event="toggle_random_ua",
            target="random_ua_switch",
            page="runtime",
            payload_factory=lambda enabled: {"enabled": bool(enabled)},
        )
        bind_logged_action(
            self.headless_card.switchButton.checkedChanged,
            self._on_headless_toggled,
            scope="CONFIG",
            event="toggle_headless_mode",
            target="headless_switch",
            page="runtime",
            payload_factory=lambda enabled: {"enabled": bool(enabled)},
        )
        bind_logged_action(
            self.timed_card.switchButton.checkedChanged,
            self._on_timed_mode_toggled,
            scope="CONFIG",
            event="toggle_timed_mode",
            target="timed_mode_switch",
            page="runtime",
            payload_factory=lambda enabled: {"enabled": bool(enabled)},
        )
        bind_logged_action(
            self.timed_card.helpButton.clicked,
            self._show_timed_mode_help,
            scope="UI",
            event="open_timed_mode_help",
            target="timed_mode_help",
            page="runtime",
            forward_signal_args=False,
        )
        bind_logged_action(
            self.random_ip_card.proxyCombo.currentIndexChanged,
            self._on_proxy_source_changed,
            scope="CONFIG",
            event="change_proxy_source",
            target="proxy_source_combo",
            page="runtime",
            payload_factory=lambda _index: {"source": self._get_selected_proxy_source()},
            forward_signal_args=False,
        )
        self.answer_card.valueChanged.connect(self._on_answer_duration_changed)
        bind_logged_action(
            self.reliability_card.switchButton.checkedChanged,
            self._on_reliability_mode_toggled,
            scope="CONFIG",
            event="toggle_reliability_mode",
            target="reliability_switch",
            page="runtime",
            payload_factory=lambda enabled: {"enabled": bool(enabled)},
        )

    @staticmethod
    def _normalize_proxy_source(source: str) -> str:
        normalized = str(source or _PROXY_SOURCE_DEFAULT).strip().lower()
        return normalized if normalized in {_PROXY_SOURCE_DEFAULT, _PROXY_SOURCE_BENEFIT, _PROXY_SOURCE_CUSTOM} else _PROXY_SOURCE_DEFAULT

    def _get_selected_proxy_source(self) -> str:
        idx = self.random_ip_card.proxyCombo.currentIndex()
        source = str(self.random_ip_card.proxyCombo.itemData(idx)) if idx >= 0 else _PROXY_SOURCE_DEFAULT
        return self._normalize_proxy_source(source)

    def _current_proxy_required_minute(self) -> int:
        try:
            return int(get_proxy_minute_by_answer_seconds(self.answer_card.getValue()))
        except Exception as exc:
            log_suppressed_exception("_current_proxy_required_minute", exc, level=logging.WARNING)
            return 1

    def _current_proxy_required_minute_for_benefit(self) -> int:
        """限时福利兼容性判断按用户输入作答时长计算，不叠加安全缓冲。"""
        try:
            from software.app.config import PROXY_TTL_GRACE_SECONDS

            raw_answer_seconds = max(0, int(self.answer_card.getValue()))
            # get_proxy_minute_by_answer_seconds() 内部会自动加缓冲秒，这里先减掉，
            # 等价于“按用户输入时长本身判断”，避免 50 秒被提示为 3 分钟。
            normalized_seconds = max(0, raw_answer_seconds - int(PROXY_TTL_GRACE_SECONDS))
            return int(get_proxy_minute_by_answer_seconds(normalized_seconds))
        except Exception as exc:
            log_suppressed_exception("_current_proxy_required_minute_for_benefit", exc, level=logging.WARNING)
            return 1

    def _show_benefit_proxy_limit_tip(self, minute: int) -> None:
        parent = self.window() or self.view
        InfoBar.warning(
            "",
            f"当前作答时长会要求 {minute} 分钟代理，但“限时福利”只支持 1 分钟。请切回默认代理源，或缩短作答时长后再试。",
            parent=parent,
            position=InfoBarPosition.TOP,
            duration=4500,
        )

    def _evaluate_benefit_proxy_compatibility(self, *, show_tip: bool) -> bool:
        if self._get_selected_proxy_source() != _PROXY_SOURCE_BENEFIT:
            self._last_benefit_proxy_compatible = None
            return True
        minute = self._current_proxy_required_minute_for_benefit()
        compatible = minute <= 1
        previous = self._last_benefit_proxy_compatible
        self._last_benefit_proxy_compatible = compatible
        if show_tip and (not compatible) and previous is not False:
            self._show_benefit_proxy_limit_tip(minute)
        return compatible

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
                log_suppressed_exception("focus_answer_duration_setting: verticalScrollBar().setValue(...)", exc, level=logging.INFO)
            try:
                if target_edit is not None:
                    target_edit.setFocus()
                    target_edit.selectAll()
            except Exception as exc:
                log_suppressed_exception("focus_answer_duration_setting: self.answer_card.inputEdit.setFocus()", exc, level=logging.INFO)
            try:
                # 兜底：极端布局场景下再做一次“至少可见”
                self.ensureWidgetVisible(self.answer_card, 0, 24)
            except Exception as exc:
                log_suppressed_exception("focus_answer_duration_setting: ensureWidgetVisible", exc, level=logging.INFO)

        # 页面切换后做两次定位，避免首帧布局尚未稳定导致的偏移
        QTimer.singleShot(0, _focus_target)
        QTimer.singleShot(80, _focus_target)

    def _resolve_thread_max(self, headless_enabled: bool) -> int:
        return self.HEADLESS_MAX_THREADS if headless_enabled else self.NON_HEADLESS_MAX_THREADS

    def _apply_thread_limit_by_headless(self, headless_enabled: bool) -> bool:
        max_threads = self._resolve_thread_max(bool(headless_enabled))
        previous_value = int(self.thread_card.spinBox.value())
        clamped = previous_value > max_threads

        self.thread_card.spinBox.setRange(self.MIN_THREADS, max_threads)
        if clamped:
            self.thread_card.spinBox.setValue(max_threads)

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
        self.controller.set_runtime_ui_state(
            headless_mode=bool(enabled),
            threads=int(self.thread_card.spinBox.value()),
        )
        log_action(
            "CONFIG",
            "toggle_headless_mode",
            "headless_switch",
            "runtime",
            result="changed",
            payload={"enabled": bool(enabled), "threads": int(self.thread_card.spinBox.value()), "clamped": clamped},
        )
        if (not enabled) and clamped and not self._suppress_headless_tip:
            self._show_headless_limit_tip()

    def _show_timed_mode_help(self):
        """显示定时模式说明"""
        log_action("UI", "open_timed_mode_help", "timed_mode_help", "runtime", result="opened")
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
        """参数页随机IP开关切换时，异步执行网络校验，避免阻塞界面。"""
        if self.controller.toggle_random_ip_async(bool(enabled)):
            log_action(
                "CONFIG",
                "toggle_random_ip",
                "random_ip_switch",
                "runtime",
                result="validation_started",
                payload={"enabled": bool(enabled)},
            )
            return

        final_enabled = bool(self.controller.get_runtime_ui_state().get("random_ip_enabled", False))
        self.random_ip_card.switchButton.blockSignals(True)
        try:
            self.random_ip_card.switchButton.setChecked(final_enabled)
            self.random_ip_card._sync_ip_enabled(final_enabled)
        finally:
            self.random_ip_card.switchButton.blockSignals(False)
        log_action(
            "CONFIG",
            "toggle_random_ip",
            "random_ip_switch",
            "runtime",
            result="changed" if final_enabled == bool(enabled) else "reverted",
            level=logging.INFO if final_enabled == bool(enabled) else logging.WARNING,
            payload={"requested": bool(enabled), "enabled": final_enabled},
        )

    def _on_random_ua_toggled(self, enabled: bool):
        self._sync_random_ua(enabled)
        log_action(
            "CONFIG",
            "toggle_random_ua",
            "random_ua_switch",
            "runtime",
            result="changed",
            payload={"enabled": bool(enabled)},
        )

    def _on_proxy_source_changed(self):
        """代理源选择变化时更新设置"""
        source = self._get_selected_proxy_source()
        try:
            if source == _PROXY_SOURCE_CUSTOM:
                api_url = self.random_ip_card.customApiEdit.text().strip()
                apply_proxy_source_settings(source, custom_api_url=api_url if api_url else None)
            else:
                apply_proxy_source_settings(source, custom_api_url=None)
        except Exception as exc:
            log_suppressed_exception("_on_proxy_source_changed: apply_proxy_source_settings", exc, level=logging.WARNING)
        self._evaluate_benefit_proxy_compatibility(show_tip=(source == _PROXY_SOURCE_BENEFIT))
        self.controller.set_runtime_ui_state(proxy_source=source)
        log_action(
            "CONFIG",
            "change_proxy_source",
            "proxy_source_combo",
            "runtime",
            result="changed",
            payload={"source": source},
        )

    def _on_answer_duration_changed(self, _value: int):
        self._evaluate_benefit_proxy_compatibility(show_tip=True)
        self.controller.set_runtime_ui_state(answer_duration=self._card_value_as_range(self.answer_card))

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

    def _on_timed_mode_toggled(self, enabled: bool):
        self._sync_timed_mode(bool(enabled))
        self.controller.set_runtime_ui_state(timed_mode_enabled=bool(enabled))
        log_action(
            "CONFIG",
            "toggle_timed_mode",
            "timed_mode_switch",
            "runtime",
            result="changed",
            payload={"enabled": bool(enabled)},
        )

    def _on_reliability_mode_toggled(self, enabled: bool):
        try:
            self.reliability_card._sync_enabled(bool(enabled))
        except Exception as exc:
            log_suppressed_exception("_on_reliability_mode_toggled: reliability_card._sync_enabled", exc, level=logging.INFO)
        log_action(
            "CONFIG",
            "toggle_reliability_mode",
            "reliability_switch",
            "runtime",
            result="changed",
            payload={"enabled": bool(enabled)},
        )

    def update_config(self, cfg: RuntimeConfig):
        cfg.target = max(1, self.target_card.spinBox.value())
        cfg.threads = max(1, self.thread_card.spinBox.value())
        cfg.browser_preference = []  # 固定使用默认顺序：Edge → Chrome
        cfg.submit_interval = self._card_value_as_range(self.interval_card)
        cfg.answer_duration = self._card_value_as_range(self.answer_card)
        cfg.timed_mode_enabled = self.timed_card.switchButton.isChecked()
        cfg.random_ip_enabled = self.random_ip_card.switchButton.isChecked()
        cfg.random_ua_enabled = self.random_ua_card.switchButton.isChecked()
        cfg.random_ua_ratios = self.random_ua_card.getRatios() if cfg.random_ua_enabled else {"wechat": 33, "mobile": 33, "pc": 34}
        cfg.fail_stop_enabled = True
        cfg.pause_on_aliyun_captcha = True
        cfg.reliability_mode_enabled = self.reliability_card.switchButton.isChecked()
        try:
            cfg.psycho_target_alpha = self.reliability_card.get_alpha()
        except Exception as exc:
            log_suppressed_exception("update_config: reliability_card.get_alpha()", exc, level=logging.INFO)
        cfg.headless_mode = self.headless_card.switchButton.isChecked()
        try:
            source = self._get_selected_proxy_source()
            cfg.proxy_source = source
            cfg.custom_proxy_api = self.random_ip_card.customApiEdit.text().strip() if source == _PROXY_SOURCE_CUSTOM else ""
            cfg.proxy_area_code = self.random_ip_card.get_area_code()
        except Exception:
            cfg.proxy_source = _PROXY_SOURCE_DEFAULT
            cfg.custom_proxy_api = ""
            cfg.proxy_area_code = None
        self.ai_section.update_config(cfg)

    def apply_config(self, cfg: RuntimeConfig):
        self.target_card.spinBox.setValue(max(1, cfg.target))
        self.thread_card.spinBox.setValue(max(1, cfg.threads))

        interval_value = self._range_start_value(cfg.submit_interval)
        self.interval_card.setValue(interval_value)

        answer_value = self._range_start_value(cfg.answer_duration)
        self.answer_card.setValue(answer_value)

        self.timed_card.switchButton.setChecked(cfg.timed_mode_enabled)
        self._sync_timed_mode(cfg.timed_mode_enabled)

        self.random_ip_card.switchButton.blockSignals(True)
        self.random_ip_card.switchButton.setChecked(cfg.random_ip_enabled)
        self.random_ip_card.switchButton.blockSignals(False)
        self.random_ip_card._sync_ip_enabled(cfg.random_ip_enabled)
        self.random_ua_card.switchButton.setChecked(cfg.random_ua_enabled)

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

        self._sync_random_ua(self.random_ua_card.switchButton.isChecked())
        self.reliability_card.switchButton.setChecked(getattr(cfg, "reliability_mode_enabled", True))
        try:
            self.reliability_card.set_alpha(getattr(cfg, "psycho_target_alpha", 0.9))
            self.reliability_card._sync_enabled(self.reliability_card.switchButton.isChecked())
        except Exception as exc:
            log_suppressed_exception("apply_config: reliability_card.set_alpha", exc, level=logging.INFO)

        self._suppress_headless_tip = True
        try:
            self.headless_card.setChecked(getattr(cfg, "headless_mode", True))
            self._apply_thread_limit_by_headless(self.headless_card.isChecked())
        finally:
            self._suppress_headless_tip = False

        try:
            proxy_source = self._normalize_proxy_source(getattr(cfg, "proxy_source", _PROXY_SOURCE_DEFAULT))
            custom_api = getattr(cfg, "custom_proxy_api", "")
            idx = self.random_ip_card.proxyCombo.findData(proxy_source)
            if idx < 0:
                proxy_source = _PROXY_SOURCE_DEFAULT
                idx = self.random_ip_card.proxyCombo.findData(proxy_source)
            if idx >= 0:
                self.random_ip_card.proxyCombo.setCurrentIndex(idx)
            self.random_ip_card.customApiEdit.setText(custom_api)
            self.random_ip_card._on_source_changed()
            apply_proxy_source_settings(
                proxy_source,
                custom_api_url=custom_api if (proxy_source == _PROXY_SOURCE_CUSTOM and custom_api) else None,
            )
            area_code = getattr(cfg, "proxy_area_code", None)
            self.random_ip_card.set_area_code(area_code)
            self._evaluate_benefit_proxy_compatibility(show_tip=False)
        except Exception as exc:
            log_suppressed_exception("apply_config: proxy_source = getattr(cfg, \"proxy_source\", \"default\")", exc, level=logging.WARNING)
        self.ai_section.apply_config(cfg)
        self.controller.sync_runtime_ui_state_from_config(cfg)

    def _apply_runtime_ui_state(self, state: dict) -> None:
        target = state.get("target")
        if target is not None and int(self.target_card.spinBox.value()) != int(target):
            self.target_card.spinBox.blockSignals(True)
            self.target_card.spinBox.setValue(max(1, int(target)))
            self.target_card.spinBox.blockSignals(False)

        threads = state.get("threads")
        headless = state.get("headless_mode")
        if headless is not None and bool(self.headless_card.switchButton.isChecked()) != bool(headless):
            self._suppress_headless_tip = True
            try:
                self.headless_card.switchButton.blockSignals(True)
                self.headless_card.switchButton.setChecked(bool(headless))
            finally:
                self.headless_card.switchButton.blockSignals(False)
                self._suppress_headless_tip = False
        if headless is not None:
            self._apply_thread_limit_by_headless(bool(headless))
        if threads is not None and int(self.thread_card.spinBox.value()) != int(threads):
            self.thread_card.spinBox.blockSignals(True)
            self.thread_card.spinBox.setValue(max(1, int(threads)))
            self.thread_card.spinBox.blockSignals(False)

        random_ip_enabled = state.get("random_ip_enabled")
        if random_ip_enabled is not None and bool(self.random_ip_card.switchButton.isChecked()) != bool(random_ip_enabled):
            self.random_ip_card.switchButton.blockSignals(True)
            self.random_ip_card.switchButton.setChecked(bool(random_ip_enabled))
            self.random_ip_card.switchButton.blockSignals(False)
            self.random_ip_card._sync_ip_enabled(bool(random_ip_enabled))

        timed_mode_enabled = state.get("timed_mode_enabled")
        if timed_mode_enabled is not None and bool(self.timed_card.switchButton.isChecked()) != bool(timed_mode_enabled):
            self.timed_card.switchButton.blockSignals(True)
            self.timed_card.switchButton.setChecked(bool(timed_mode_enabled))
            self.timed_card.switchButton.blockSignals(False)
            self._sync_timed_mode(bool(timed_mode_enabled))

        answer_duration = state.get("answer_duration")
        if isinstance(answer_duration, (list, tuple)) and len(answer_duration) >= 2:
            current_value = int(self.answer_card.getValue())
            desired_value = self._range_start_value(answer_duration)
            if current_value != desired_value:
                self.answer_card.blockSignals(True)
                self.answer_card.setValue(desired_value)
                self.answer_card.blockSignals(False)

        proxy_source = state.get("proxy_source")
        if proxy_source is not None:
            idx = self.random_ip_card.proxyCombo.findData(self._normalize_proxy_source(proxy_source))
            if idx >= 0 and self.random_ip_card.proxyCombo.currentIndex() != idx:
                self.random_ip_card.proxyCombo.blockSignals(True)
                self.random_ip_card.proxyCombo.setCurrentIndex(idx)
                self.random_ip_card.proxyCombo.blockSignals(False)
                self.random_ip_card._on_source_changed()

    def _apply_random_ip_loading(self, loading: bool, message: str) -> None:
        try:
            self.random_ip_card.setLoading(bool(loading), str(message or ""))
        except Exception as exc:
            log_suppressed_exception("_apply_random_ip_loading", exc, level=logging.WARNING)

    @staticmethod
    def _card_value_as_range(card: TimeRangeSettingCard) -> tuple[int, int]:
        value = max(0, int(card.getValue()))
        return value, value

    @staticmethod
    def _range_start_value(raw_range) -> int:
        if isinstance(raw_range, (list, tuple)):
            if raw_range:
                try:
                    return max(0, int(raw_range[0]))
                except Exception:
                    pass
            return 0
        try:
            from typing import Any, cast
            return max(0, int(cast(Any, raw_range)))
        except Exception:
            return 0





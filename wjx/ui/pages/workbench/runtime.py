"""运行参数设置页面"""
from typing import Dict, List, Optional
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception


from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QStandardItemModel, QStandardItem
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    FluentIcon,
    ModelComboBox,
    PopupTeachingTip,
    ScrollArea,
    SettingCard,
    SettingCardGroup,
    TeachingTipTailPosition,
)

from wjx.ui.controller import RunController
from wjx.ui.pages.workbench.runtime_ai import RuntimeAISection
from wjx.ui.pages.workbench.runtime_cards import (
    RandomIPSettingCard,
    RandomUASettingCard,
    TimeRangeSettingCard,
    TimedModeSettingCard,
)
from wjx.ui.widgets.setting_cards import SpinBoxSettingCard, SwitchSettingCard
from wjx.ui.pages.workbench.runtime_dialogs import pick_time_value
from wjx.utils.app.runtime_paths import _get_resource_path
from wjx.utils.io.load_save import RuntimeConfig


class RuntimePage(ScrollArea):
    """独立的运行参数/开关页，方便在侧边栏查看。"""



    BROWSER_OPTION_MAP = {
        "auto": {
            "text": "自动",
            "preference": [],
            "hint": "优先 Edge，缺失回落 Chrome/Chromium",
        },
        "edge": {
            "text": "Edge",
            "preference": ["edge"],
            "hint": "仅使用 Edge",
        },
        "chrome": {
            "text": "Chrome",
            "preference": ["chrome", "edge", "chromium"],
            "hint": "优先 Chrome，缺失回落 Edge/Chromium",
        },
        "chromium": {
            "text": "Chromium",
            "preference": ["chromium", "edge", "chrome"],
            "hint": "内置 Chromium（无需系统浏览器）",
        },
    }

    def __init__(self, controller: RunController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._browser_icons = self._load_browser_icons()
        self.view = QWidget(self)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self.view.setObjectName("settings_view")
        self.ua_checkboxes: Dict[str, CheckBox] = {}
        self._build_ui()
        self._bind_events()
        self._sync_random_ua(self.random_ua_card.isChecked())
        self._sync_browser_icon()

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
        self.browser_card = SettingCard(
            FluentIcon.GLOBE,
            "调用浏览器",
            "选择用于自动化的浏览器，Edge 缺失时可改用 Chrome 或内置 Chromium",
            parent=run_group,
        )

        # 使用 ModelComboBox 以支持图标显示
        self.browser_combo = ModelComboBox(self.browser_card)
        self.browser_combo.setFixedWidth(170)
        self.browser_combo.setStyleSheet(
            "QPushButton { padding-left: 14px; padding-right: 12px; text-align: left; }"
        )

        # 创建 Model 并添加带图标的项
        browser_model = QStandardItemModel()
        for key, option in self.BROWSER_OPTION_MAP.items():
            icon = self._browser_icons.get(key)
            text = option.get("text", key)
            hint = option.get("hint")

            item = QStandardItem(text)
            if icon and not icon.isNull():
                item.setIcon(icon)
            if hint:
                item.setToolTip(hint)
            item.setData(key, Qt.ItemDataRole.UserRole)
            browser_model.appendRow(item)

        self.browser_combo.setModel(browser_model)

        self.browser_card.hBoxLayout.addWidget(
            self.browser_combo,
            0,
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )
        self.browser_card.hBoxLayout.addSpacing(16)
        self.browser_combo.currentIndexChanged.connect(self._sync_browser_icon)
        spin_width = self.target_card.suggestSpinBoxWidthForDigits(4)
        self.target_card.setSpinBoxWidth(spin_width)
        self.thread_card.setSpinBoxWidth(spin_width)
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

        run_group.addSettingCard(self.target_card)
        run_group.addSettingCard(self.thread_card)
        run_group.addSettingCard(self.browser_card)
        run_group.addSettingCard(self.fail_stop_card)
        run_group.addSettingCard(self.pause_on_aliyun_card)
        layout.addWidget(run_group)

        # ========== 时间控制组 ==========
        time_group = SettingCardGroup("时间控制", self.view)
        # 在标题后添加小字提示（保持原标题字号）
        time_hint = BodyLabel("（其实问卷星官方并不会因为你提交过快就封你号）", time_group)
        time_hint.setStyleSheet("color: blue; font-size: 12px;")
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
            FluentIcon.HISTORY, "提交间隔", "两次提交之间的等待时间范围",
            max_seconds=300,
            parent=time_group
        )
        self.answer_card = TimeRangeSettingCard(
            FluentIcon.STOP_WATCH, "作答时长", "模拟作答所需的时间范围",
            max_seconds=120,
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

        # ========== AI 填空助手组 ==========
        self.ai_section = RuntimeAISection(self.view, self)
        self.ai_section.bind_to_layout(layout)

        layout.addStretch(1)

        # 兼容旧代码的属性别名
        self.target_spin = self.target_card.spinBox
        self.thread_spin = self.thread_card.spinBox
        self.fail_stop_switch = self.fail_stop_card.switchButton
        self.pause_on_aliyun_switch = self.pause_on_aliyun_card.switchButton
        self.timed_switch = self.timed_card.switchButton
        self.random_ip_switch = self.random_ip_card.switchButton
        self.random_ua_switch = self.random_ua_card.switchButton
        self.proxy_source_combo = self.random_ip_card.proxyCombo
        self.custom_api_edit = self.random_ip_card.customApiEdit

    def _bind_events(self):
        self.random_ip_switch.checkedChanged.connect(self._on_random_ip_toggled)
        self.random_ua_switch.checkedChanged.connect(self._sync_random_ua)
        self.timed_switch.checkedChanged.connect(self._sync_timed_mode)
        self.timed_card.helpButton.clicked.connect(self._show_timed_mode_help)
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

    def _load_browser_icons(self) -> Dict[str, QIcon]:
        icons: Dict[str, QIcon] = {}
        candidates = {
            "edge": [
                "assets/browser-icons/edge.png",
                "assets/browser-icons/edge.svg",
            ],
            "chrome": [
                "assets/browser-icons/chrome.png",
                "assets/browser-icons/chrome.svg",
            ],
            "chromium": [
                "assets/browser-icons/chromium.png",
                "assets/browser-icons/chromium.svg",
            ],
        }
        for key, rel_paths in candidates.items():
            for rel_path in rel_paths:
                try:
                    abs_path = _get_resource_path(rel_path)
                    icon = QIcon(abs_path)
                    if icon and not icon.isNull():
                        icons[key] = icon
                        break
                except Exception:
                    continue
        return icons

    def _get_selected_browser_preference(self) -> List[str]:
        idx = self.browser_combo.currentIndex()
        key = str(self.browser_combo.itemData(idx)) if idx >= 0 else "auto"
        option = self.BROWSER_OPTION_MAP.get(key) or self.BROWSER_OPTION_MAP["auto"]
        prefs = option.get("preference") or []
        return list(prefs)

    def _apply_browser_preference(self, prefs: Optional[List[str]]) -> None:
        normalized = [str(x or "").strip().lower() for x in (prefs or []) if str(x or "").strip()]
        target_key = "auto" if not normalized else None
        if normalized:
            for key, option in self.BROWSER_OPTION_MAP.items():
                option_pref = [str(p).lower() for p in option.get("preference") or []]
                if normalized == option_pref:
                    target_key = key
                    break
            if target_key is None:
                first = normalized[0]
                for key, option in self.BROWSER_OPTION_MAP.items():
                    option_pref = option.get("preference") or []
                    if option_pref and str(option_pref[0]).lower() == first:
                        target_key = key
                        break
        if target_key is None:
            target_key = "auto"
        idx = self.browser_combo.findData(target_key)
        if idx >= 0:
            self.browser_combo.setCurrentIndex(idx)
        elif self.browser_combo.count() > 0:
            self.browser_combo.setCurrentIndex(0)
        self._sync_browser_icon()

    def _sync_browser_icon(self):
        """让当前选中项的图标显示在下拉框按钮上"""
        idx = self.browser_combo.currentIndex()
        key = str(self.browser_combo.itemData(idx)) if idx >= 0 else ""
        icon = self._browser_icons.get(key)
        if (not icon or icon.isNull()) and idx >= 0:
            # 兜底：用显示文本匹配图标（防止 userData 丢失）
            text_key = (self.browser_combo.itemText(idx) or "").strip().lower()
            icon = self._browser_icons.get(text_key)
        if icon and not icon.isNull():
            self.browser_combo.setIcon(icon)
            self.browser_combo.setIconSize(QSize(20, 20))
        else:
            self.browser_combo.setIcon(QIcon())



    def update_config(self, cfg: RuntimeConfig):
        cfg.target = max(1, self.target_spin.value())
        cfg.threads = max(1, self.thread_spin.value())
        cfg.browser_preference = self._get_selected_browser_preference()
        interval_min, interval_max = self.interval_card.getRange()
        cfg.submit_interval = (interval_min, interval_max)
        answer_min, answer_max = self.answer_card.getRange()
        cfg.answer_duration = (answer_min, answer_max)
        cfg.timed_mode_enabled = self.timed_switch.isChecked()
        cfg.random_ip_enabled = self.random_ip_switch.isChecked()
        cfg.random_ua_enabled = self.random_ua_switch.isChecked()
        cfg.random_ua_keys = [k for k, cb in self.ua_checkboxes.items() if cb.isChecked()] if cfg.random_ua_enabled else []
        cfg.fail_stop_enabled = self.fail_stop_switch.isChecked()
        cfg.pause_on_aliyun_captcha = self.pause_on_aliyun_switch.isChecked()
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
        try:
            self._apply_browser_preference(getattr(cfg, "browser_preference", None))
        except Exception as exc:
            log_suppressed_exception("apply_config: self._apply_browser_preference(getattr(cfg, \"browser_preference\", None))", exc, level=logging.WARNING)

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
        self.random_ua_switch.setChecked(cfg.random_ua_enabled)
        self._sync_browser_icon()

        active = set(cfg.random_ua_keys or [])
        for key, cb in self.ua_checkboxes.items():
            cb.setChecked((not active and key == "pc_web") or key in active)
        self._sync_random_ua(self.random_ua_switch.isChecked())
        self.fail_stop_switch.setChecked(cfg.fail_stop_enabled)
        self.pause_on_aliyun_switch.setChecked(getattr(cfg, "pause_on_aliyun_captcha", True))

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


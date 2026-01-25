"""运行参数设置页面 - 使用 SettingCard 组件重构"""
import logging
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QThread, QSize
from PySide6.QtGui import QIcon, QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QDialog,
    QSizePolicy,
    QPlainTextEdit,
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
    ModelComboBox,
    LineEdit,
    PasswordLineEdit,
    PushSettingCard,
    FluentIcon,
    PopupTeachingTip,
    TeachingTipTailPosition,
    SettingCardGroup,
    SettingCard,
    ExpandGroupSettingCard,
    IndicatorPosition,
    TransparentToolButton,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarIcon,
    InfoBarPosition,
)

from wjx.ui.widgets.no_wheel import NoWheelSlider, NoWheelSpinBox
from wjx.ui.widgets.full_width_infobar import FullWidthInfoBar
from wjx.ui.controller import RunController
from wjx.ui.workers.ai_test_worker import AITestWorker
from wjx.utils.load_save import RuntimeConfig
from wjx.utils.config import USER_AGENT_PRESETS
from wjx.utils.ai_service import AI_PROVIDERS, get_ai_settings, save_ai_settings, DEFAULT_SYSTEM_PROMPT
from wjx.utils.runtime_paths import _get_resource_path


class SpinBoxSettingCard(SettingCard):
    """带 SpinBox 的设置卡"""

    def __init__(self, icon, title, content, min_val=1, max_val=99999, default=10, parent=None):
        super().__init__(icon, title, content, parent)
        self.spinBox = NoWheelSpinBox(self)
        self.spinBox.setRange(min_val, max_val)
        self.spinBox.setValue(default)
        self.spinBox.setMinimumWidth(90)
        self.spinBox.setFixedHeight(36)
        self.hBoxLayout.addWidget(self.spinBox, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def value(self):
        return self.spinBox.value()

    def setValue(self, value):
        self.spinBox.setValue(value)

    def setSpinBoxWidth(self, width: int) -> None:
        if width and width > 0:
            self.spinBox.setFixedWidth(int(width))

    def suggestSpinBoxWidthForDigits(self, digits: int) -> int:
        digits = max(1, int(digits))
        metrics = self.spinBox.fontMetrics()
        sample = "8" * digits
        target_width = metrics.horizontalAdvance(sample)
        try:
            current_text = self.spinBox.text()
        except Exception:
            current_text = str(self.spinBox.value())
        current_width = metrics.horizontalAdvance(current_text or "0")
        base_width = self.spinBox.sizeHint().width()
        extra = max(0, target_width - current_width)
        return int(base_width + extra + 8)


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

        # 地区选择（仅默认代理源）
        self.areaRow = QWidget(container)
        area_layout = QHBoxLayout(self.areaRow)
        area_layout.setContentsMargins(0, 0, 0, 0)
        area_label = BodyLabel("指定地区", self.areaRow)
        self.provinceCombo = ComboBox(self.areaRow)
        self.cityCombo = ComboBox(self.areaRow)
        self.provinceCombo.setMinimumWidth(160)
        self.cityCombo.setMinimumWidth(200)
        area_layout.addWidget(area_label)
        area_layout.addStretch(1)
        area_layout.addWidget(self.provinceCombo)
        area_layout.addWidget(self.cityCombo)
        layout.addWidget(self.areaRow)

        # 自定义API输入
        self.customApiRow = QWidget(container)
        api_layout = QHBoxLayout(self.customApiRow)
        api_layout.setContentsMargins(0, 0, 0, 0)
        api_label = BodyLabel("API 地址", self.customApiRow)
        api_hint = BodyLabel("*仅支持json返回格式", self.customApiRow)
        api_hint.setStyleSheet("color: red; font-size: 11px;")
        self.customApiEdit = LineEdit(self.customApiRow)
        self.customApiEdit.setPlaceholderText("请输入代理api地址")
        self.customApiEdit.setMinimumWidth(420)
        
        # 检测按钮容器（包含按钮、加载动画、状态图标）
        self.testBtnContainer = QWidget(self.customApiRow)
        test_btn_layout = QHBoxLayout(self.testBtnContainer)
        test_btn_layout.setContentsMargins(0, 0, 0, 0)
        test_btn_layout.setSpacing(4)
        
        self.testApiBtn = PushButton("检测", self.testBtnContainer)
        self.testApiBtn.setFixedWidth(60)
        self.testApiBtn.clicked.connect(self._on_test_api_clicked)
        
        self.testApiSpinner = IndeterminateProgressRing(self.testBtnContainer)
        self.testApiSpinner.setFixedSize(20, 20)
        self.testApiSpinner.hide()
        
        self.testApiStatus = BodyLabel("", self.testBtnContainer)
        self.testApiStatus.setFixedWidth(20)
        self.testApiStatus.hide()
        
        test_btn_layout.addWidget(self.testApiBtn)
        test_btn_layout.addWidget(self.testApiSpinner)
        test_btn_layout.addWidget(self.testApiStatus)
        
        api_layout.addWidget(api_label)
        api_layout.addWidget(api_hint)
        api_layout.addStretch(1)
        api_layout.addWidget(self.customApiEdit)
        api_layout.addWidget(self.testBtnContainer)
        self.customApiRow.hide()
        layout.addWidget(self.customApiRow)

        self._area_updating = False
        self._area_data = []
        self._supported_area_codes = set()
        self._supported_has_all = False
        self._cities_by_province = {}
        self._province_index_by_code = {}
        self._load_area_options()
        self.areaRow.setVisible(True)
        self.provinceCombo.currentIndexChanged.connect(self._on_province_changed)
        self.cityCombo.currentIndexChanged.connect(self._on_city_changed)

        self.addGroupWidget(container)

        # 代理源变化时显示/隐藏自定义API
        self.proxyCombo.currentIndexChanged.connect(self._on_source_changed)
        # API地址输入完成时同步到全局变量
        self.customApiEdit.editingFinished.connect(self._on_api_edit_finished)

    def _on_source_changed(self):
        idx = self.proxyCombo.currentIndex()
        source = str(self.proxyCombo.itemData(idx)) if idx >= 0 else "default"
        self.customApiRow.setVisible(source == "custom")
        self.areaRow.setVisible(source == "default")
        if source != "default":
            self._apply_area_override(None)
        else:
            self._apply_area_override(self.get_area_code())
        # 刷新布局 - 重新触发展开/收起来更新高度
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._refreshLayout)

    def _load_area_options(self):
        try:
            from wjx.data.area_codes import load_area_codes
            from wjx.data.area_support import load_supported_area_codes
            self._supported_area_codes, self._supported_has_all = load_supported_area_codes()
            self._area_data = load_area_codes(supported_only=True)
            if not self._area_data:
                logging.warning("地区数据加载为空，可能是数据文件损坏或格式错误")
        except Exception as e:
            logging.error(f"加载地区数据失败: {e}", exc_info=True)
            self._area_data = []
            self._supported_area_codes = set()
            self._supported_has_all = False
        self._cities_by_province = {}
        self._province_index_by_code = {}

        self.provinceCombo.clear()
        if self._supported_has_all or not self._supported_area_codes:
            self.provinceCombo.addItem("不限制", userData="")
        for item in self._area_data:
            code = str(item.get("code") or "")
            name = str(item.get("name") or "")
            if not code or not name:
                continue
            self._cities_by_province[code] = list(item.get("cities") or [])
            self.provinceCombo.addItem(name, userData=code)
            self._province_index_by_code[code] = self.provinceCombo.count() - 1

        self.cityCombo.clear()
        self.cityCombo.setEnabled(False)

    def _populate_cities(self, province_code: str, preferred_city_code: Optional[str] = None) -> None:
        self.cityCombo.clear()
        if province_code and province_code in self._supported_area_codes:
            self.cityCombo.addItem("全省/全市", userData=province_code)
        cities = self._cities_by_province.get(province_code, [])
        for city in cities:
            code = str(city.get("code") or "")
            name = str(city.get("name") or "")
            if code and name:
                self.cityCombo.addItem(name, userData=code)
        self.cityCombo.setEnabled(bool(cities))
        if preferred_city_code:
            idx = self.cityCombo.findData(preferred_city_code)
            if idx >= 0:
                self.cityCombo.setCurrentIndex(idx)

    def _on_province_changed(self):
        if self._area_updating:
            return
        province_code = self.provinceCombo.currentData()
        self._area_updating = True
        if not province_code:
            self.cityCombo.clear()
            self.cityCombo.setEnabled(False)
            self._area_updating = False
            self._apply_area_override("")
            return
        self._populate_cities(province_code)
        self._area_updating = False
        self._apply_area_override(self.cityCombo.currentData())

    def _on_city_changed(self):
        if self._area_updating:
            return
        if not self.cityCombo.isEnabled():
            self._apply_area_override("")
            return
        self._apply_area_override(self.cityCombo.currentData())

    def _apply_area_override(self, area_code: Optional[str]) -> None:
        from wjx.network.random_ip import set_proxy_area_code
        if not self.areaRow.isVisible():
            set_proxy_area_code(None)
            return
        if area_code is None:
            set_proxy_area_code(None)
            return
        set_proxy_area_code(str(area_code))

    def get_area_code(self) -> Optional[str]:
        if not self.areaRow.isVisible():
            return None
        province_code = self.provinceCombo.currentData()
        if not province_code:
            return ""
        city_code = self.cityCombo.currentData()
        return str(city_code or "")

    def set_area_code(self, area_code: Optional[str]) -> None:
        from wjx.network.random_ip import get_default_proxy_area_code
        if area_code is None:
            area_code = get_default_proxy_area_code()
        area_code = str(area_code or "").strip()
        self._area_updating = True
        if not area_code:
            self.provinceCombo.setCurrentIndex(0)
            self.cityCombo.clear()
            self.cityCombo.setEnabled(False)
            self._area_updating = False
            self._apply_area_override("")
            return
        province_code = f"{area_code[:2]}0000" if len(area_code) >= 2 else ""
        province_index = self._province_index_by_code.get(province_code)
        if province_index is None:
            self.provinceCombo.setCurrentIndex(0)
            self.cityCombo.clear()
            self.cityCombo.setEnabled(False)
            self._area_updating = False
            self._apply_area_override("")
            return
        self.provinceCombo.setCurrentIndex(province_index)
        self._populate_cities(province_code, preferred_city_code=area_code)
        self._area_updating = False
        self._apply_area_override(self.cityCombo.currentData())

    def _refreshLayout(self):
        """刷新展开卡片的布局"""
        # 通过重新设置展开状态来刷新高度
        if self.isExpand:
            self._adjustViewSize()

    def _on_test_api_clicked(self):
        """检测API按钮点击事件"""
        import logging
        from PySide6.QtCore import QThread, Signal, QObject
        
        api_url = self.customApiEdit.text().strip()
        if not api_url:
            InfoBar.warning("", "请先输入API地址", parent=self.window(), position=InfoBarPosition.TOP, duration=3000)
            return
        
        # 显示加载状态
        self.testApiBtn.hide()
        self.testApiStatus.hide()
        self.testApiSpinner.show()
        
        # 创建工作线程
        class TestWorker(QObject):
            finished = Signal(bool, str, list)
            
            def __init__(self, url):
                super().__init__()
                self.url = url
            
            def run(self):
                from wjx.network.random_ip import test_custom_proxy_api
                success, error, proxies = test_custom_proxy_api(self.url)
                self.finished.emit(success, error, proxies)
        
        self._test_thread = QThread()
        self._test_worker = TestWorker(api_url)
        self._test_worker.moveToThread(self._test_thread)
        self._test_thread.started.connect(self._test_worker.run)
        self._test_worker.finished.connect(self._on_test_finished)
        self._test_worker.finished.connect(self._test_thread.quit)
        self._test_worker.finished.connect(self._test_worker.deleteLater)
        self._test_thread.finished.connect(self._test_thread.deleteLater)
        self._test_thread.start()
    
    def _on_test_finished(self, success: bool, error: str, proxies: list):
        """检测完成回调"""
        import logging
        
        self.testApiSpinner.hide()
        self.testApiStatus.show()
        
        if success:
            self.testApiStatus.setText("✔")
            self.testApiStatus.setStyleSheet("color: green; font-size: 16px; font-weight: bold;")
            logging.info(f"API检测成功，获取到 {len(proxies)} 个代理")
        else:
            self.testApiStatus.setText("✖")
            self.testApiStatus.setStyleSheet("color: red; font-size: 16px; font-weight: bold;")
            logging.error(f"API检测失败: {error}")
            InfoBar.error("API检测失败", error, parent=self.window(), position=InfoBarPosition.TOP, duration=5000)
        
        # 3秒后恢复按钮
        from PySide6.QtCore import QTimer
        QTimer.singleShot(3000, self._reset_test_button)
    
    def _reset_test_button(self):
        """重置检测按钮状态"""
        self.testApiStatus.hide()
        self.testApiBtn.show()

    def _on_api_edit_finished(self):
        """API地址输入完成时同步到全局变量"""
        from wjx.network.random_ip import set_proxy_api_override
        api_url = self.customApiEdit.text().strip()
        set_proxy_api_override(api_url if api_url else None)

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
        self.view.setStyleSheet("background: transparent;")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.view.setObjectName("settings_view")
        self.ua_checkboxes: Dict[str, CheckBox] = {}
        self._ai_loading = False
        self._ai_test_thread = None
        self._ai_test_worker = None
        self._ai_system_prompt = DEFAULT_SYSTEM_PROMPT
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
        time_hint = BodyLabel("（其实问卷星不会因为你提交过快就封你号）", time_group)
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

        # ========== AI 填空助手组 ==========
        self.ai_group = SettingCardGroup("AI 填空助手", self.view)
        ai_config = get_ai_settings()
        self._ai_system_prompt = ai_config.get("system_prompt") or DEFAULT_SYSTEM_PROMPT

        self.ai_privacy_bar = FullWidthInfoBar(
            InfoBarIcon.SUCCESS,
            "隐私声明：不会上传 API Key 等隐私信息，所有配置仅保存在本地。",
            "",
            orient=Qt.Orientation.Horizontal,
            isClosable=False,
            duration=-1,
            position=InfoBarPosition.NONE,
            parent=self.ai_group,
        )
        self.ai_privacy_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.ai_privacy_bar.setMinimumWidth(0)
        self.ai_privacy_bar.setMaximumWidth(16777215)
        self.ai_privacy_bar.contentLabel.setVisible(False)
        self.ai_group.addSettingCard(self.ai_privacy_bar)

        self.ai_enabled_card = SwitchSettingCard(
            FluentIcon.ROBOT,
            "启用 AI 填空",
            "开启后可使用 AI 自动生成填空题答案",
            parent=self.ai_group,
        )
        self.ai_enabled_card.setChecked(bool(ai_config.get("enabled")))
        self.ai_group.addSettingCard(self.ai_enabled_card)

        self.ai_provider_card = SettingCard(
            FluentIcon.CLOUD,
            "AI 服务提供商",
            "选择 AI 服务，自定义模式支持任意 OpenAI 兼容接口",
            self.ai_group,
        )
        self.ai_provider_combo = ComboBox(self.ai_provider_card)
        self.ai_provider_combo.setMinimumWidth(200)
        for key, provider in AI_PROVIDERS.items():
            self.ai_provider_combo.addItem(provider.get("label", key), userData=key)
        saved_provider = ai_config.get("provider") or "openai"
        idx = self.ai_provider_combo.findData(saved_provider)
        if idx >= 0:
            self.ai_provider_combo.setCurrentIndex(idx)
        self.ai_provider_card.hBoxLayout.addWidget(self.ai_provider_combo, 0, Qt.AlignmentFlag.AlignRight)
        self.ai_provider_card.hBoxLayout.addSpacing(16)
        self.ai_group.addSettingCard(self.ai_provider_card)

        self.ai_baseurl_card = SettingCard(
            FluentIcon.LINK,
            "Base URL",
            "自定义模式下的 API 地址（如 https://api.example.com/v1）",
            self.ai_group,
        )
        self.ai_baseurl_edit = LineEdit(self.ai_baseurl_card)
        self.ai_baseurl_edit.setMinimumWidth(280)
        self.ai_baseurl_edit.setPlaceholderText("https://api.example.com/v1")
        self.ai_baseurl_edit.setText(ai_config.get("base_url") or "")
        self.ai_baseurl_card.hBoxLayout.addWidget(self.ai_baseurl_edit, 0, Qt.AlignmentFlag.AlignRight)
        self.ai_baseurl_card.hBoxLayout.addSpacing(16)
        self.ai_group.addSettingCard(self.ai_baseurl_card)

        self.ai_apikey_card = SettingCard(
            FluentIcon.FINGERPRINT,
            "API Key",
            "输入对应服务的 API 密钥",
            self.ai_group,
        )
        self.ai_apikey_edit = PasswordLineEdit(self.ai_apikey_card)
        self.ai_apikey_edit.setMinimumWidth(280)
        self.ai_apikey_edit.setPlaceholderText("sk-...")
        self.ai_apikey_edit.setText(ai_config.get("api_key") or "")
        self.ai_apikey_card.hBoxLayout.addWidget(self.ai_apikey_edit, 0, Qt.AlignmentFlag.AlignRight)
        self.ai_apikey_card.hBoxLayout.addSpacing(16)
        self.ai_group.addSettingCard(self.ai_apikey_card)

        self.ai_model_card = SettingCard(
            FluentIcon.DEVELOPER_TOOLS,
            "模型",
            "选择或输入模型名称",
            self.ai_group,
        )
        self.ai_model_edit = LineEdit(self.ai_model_card)
        self.ai_model_edit.setMinimumWidth(200)
        self.ai_model_edit.setPlaceholderText("gpt-3.5-turbo")
        self.ai_model_edit.setText(ai_config.get("model") or "")
        self.ai_model_card.hBoxLayout.addWidget(self.ai_model_edit, 0, Qt.AlignmentFlag.AlignRight)
        self.ai_model_card.hBoxLayout.addSpacing(16)
        self.ai_group.addSettingCard(self.ai_model_card)

        self.ai_test_card = PushSettingCard(
            text="测试",
            icon=FluentIcon.SEND,
            title="测试 AI 连接",
            content="验证 API 配置是否正确",
            parent=self.ai_group,
        )
        self.ai_group.addSettingCard(self.ai_test_card)
        self.ai_test_spinner = IndeterminateProgressRing(self.ai_test_card)
        self.ai_test_spinner.setFixedSize(20, 20)
        self.ai_test_spinner.setStrokeWidth(2)
        self.ai_test_spinner.hide()
        insert_index = self.ai_test_card.hBoxLayout.indexOf(self.ai_test_card.button)
        if insert_index >= 0:
            self.ai_test_card.hBoxLayout.insertWidget(
                insert_index,
                self.ai_test_spinner,
                0,
                Qt.AlignmentFlag.AlignRight,
            )
            self.ai_test_card.hBoxLayout.insertSpacing(insert_index + 1, 6)

        self.ai_prompt_card = SettingCard(
            FluentIcon.EDIT,
            "系统提示词",
            "自定义 AI 填空的系统提示词（留空使用默认）",
            self.ai_group,
        )
        self.ai_prompt_edit = QPlainTextEdit(self.ai_prompt_card)
        self.ai_prompt_edit.setPlaceholderText("留空使用默认提示词...")
        self.ai_prompt_edit.setPlainText(self._ai_system_prompt)
        self.ai_prompt_edit.setMaximumHeight(100)
        self.ai_prompt_edit.setMinimumHeight(80)
        prompt_container = QWidget(self.ai_prompt_card)
        prompt_layout = QVBoxLayout(prompt_container)
        prompt_layout.setContentsMargins(0, 0, 0, 0)
        prompt_layout.addWidget(self.ai_prompt_edit)
        self.ai_prompt_card.hBoxLayout.addWidget(prompt_container, 1)
        self.ai_prompt_card.hBoxLayout.addSpacing(16)
        self.ai_group.addSettingCard(self.ai_prompt_card)

        layout.addWidget(self.ai_group)
        self._update_ai_visibility()

        layout.addStretch(1)

        # 兼容旧代码的属性别名
        self.target_spin = self.target_card.spinBox
        self.thread_spin = self.thread_card.spinBox
        self.fail_stop_switch = self.fail_stop_card.switchButton
        self.pause_on_aliyun_switch = self.pause_on_aliyun_card.switchButton
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
        self.ai_enabled_card.switchButton.checkedChanged.connect(self._on_ai_enabled_toggled)
        self.ai_provider_combo.currentIndexChanged.connect(self._on_ai_provider_changed)
        self.ai_apikey_edit.editingFinished.connect(self._on_ai_apikey_changed)
        self.ai_baseurl_edit.editingFinished.connect(self._on_ai_baseurl_changed)
        self.ai_model_edit.editingFinished.connect(self._on_ai_model_changed)
        self.ai_test_card.clicked.connect(self._on_ai_test_clicked)
        self.ai_prompt_edit.textChanged.connect(self._on_ai_prompt_changed)

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

    def _set_ai_controls_blocked(self, blocked: bool):
        try:
            self.ai_enabled_card.switchButton.blockSignals(blocked)
            self.ai_provider_combo.blockSignals(blocked)
        except Exception:
            pass

    def _set_ai_test_loading(self, loading: bool):
        self.ai_test_spinner.setVisible(loading)
        self.ai_test_card.button.setEnabled(not loading)

    def _update_ai_visibility(self):
        """根据选择的提供商更新 AI 配置项的可见性"""
        idx = self.ai_provider_combo.currentIndex()
        provider_key = str(self.ai_provider_combo.itemData(idx)) if idx >= 0 else "openai"
        is_custom = provider_key == "custom"
        self.ai_baseurl_card.setVisible(is_custom)
        provider_config = AI_PROVIDERS.get(provider_key, {})
        default_model = provider_config.get("default_model", "")
        self.ai_model_edit.setPlaceholderText(default_model or "模型名称")

    def _apply_ai_config(self, cfg: RuntimeConfig):
        ai_config_present = getattr(cfg, "_ai_config_present", False)
        if not ai_config_present:
            ai_config = get_ai_settings()
            cfg.ai_enabled = bool(ai_config.get("enabled"))
            cfg.ai_provider = str(ai_config.get("provider") or "openai")
            cfg.ai_api_key = str(ai_config.get("api_key") or "")
            cfg.ai_base_url = str(ai_config.get("base_url") or "")
            cfg.ai_model = str(ai_config.get("model") or "")
            cfg.ai_system_prompt = str(ai_config.get("system_prompt") or DEFAULT_SYSTEM_PROMPT)
        if not getattr(cfg, "ai_provider", ""):
            cfg.ai_provider = "openai"
        if not getattr(cfg, "ai_system_prompt", ""):
            cfg.ai_system_prompt = DEFAULT_SYSTEM_PROMPT

        self._ai_loading = True
        self._set_ai_controls_blocked(True)
        self.ai_enabled_card.setChecked(bool(cfg.ai_enabled))
        idx = self.ai_provider_combo.findData(cfg.ai_provider)
        if idx >= 0:
            self.ai_provider_combo.setCurrentIndex(idx)
        else:
            self.ai_provider_combo.setCurrentIndex(0)
        self.ai_apikey_edit.setText(cfg.ai_api_key or "")
        self.ai_baseurl_edit.setText(cfg.ai_base_url or "")
        self.ai_model_edit.setText(cfg.ai_model or "")
        self._ai_system_prompt = cfg.ai_system_prompt or DEFAULT_SYSTEM_PROMPT
        self.ai_prompt_edit.setPlainText(self._ai_system_prompt)
        self._update_ai_visibility()
        self._set_ai_controls_blocked(False)
        self._ai_loading = False

        save_ai_settings(
            enabled=bool(cfg.ai_enabled),
            provider=cfg.ai_provider,
            api_key=cfg.ai_api_key or "",
            base_url=cfg.ai_base_url or "",
            model=cfg.ai_model or "",
            system_prompt=self._ai_system_prompt,
        )

    def _on_ai_enabled_toggled(self, checked: bool):
        """AI 功能开关切换"""
        if self._ai_loading:
            return
        save_ai_settings(enabled=checked)
        InfoBar.success(
            "",
            f"AI 填空功能已{'开启' if checked else '关闭'}",
            parent=self.window(),
            position=InfoBarPosition.TOP,
            duration=2000,
        )

    def _on_ai_provider_changed(self):
        """AI 提供商选择变化"""
        if self._ai_loading:
            return
        idx = self.ai_provider_combo.currentIndex()
        provider_key = str(self.ai_provider_combo.itemData(idx)) if idx >= 0 else "openai"
        save_ai_settings(provider=provider_key)
        self._update_ai_visibility()
        provider_config = AI_PROVIDERS.get(provider_key, {})
        InfoBar.success(
            "",
            f"AI 服务已切换为：{provider_config.get('label', provider_key)}",
            parent=self.window(),
            position=InfoBarPosition.TOP,
            duration=2000,
        )

    def _on_ai_apikey_changed(self):
        """API Key 变化"""
        if self._ai_loading:
            return
        save_ai_settings(api_key=self.ai_apikey_edit.text())

    def _on_ai_baseurl_changed(self):
        """Base URL 变化"""
        if self._ai_loading:
            return
        save_ai_settings(base_url=self.ai_baseurl_edit.text())

    def _on_ai_model_changed(self):
        """模型变化"""
        if self._ai_loading:
            return
        save_ai_settings(model=self.ai_model_edit.text())

    def _on_ai_prompt_changed(self):
        """系统提示词变化"""
        if self._ai_loading:
            return
        self._ai_system_prompt = self.ai_prompt_edit.toPlainText().strip() or DEFAULT_SYSTEM_PROMPT
        save_ai_settings(system_prompt=self._ai_system_prompt)

    def _on_ai_test_clicked(self):
        """测试 AI 连接"""
        if self._ai_loading:
            return
        if self._ai_test_thread is not None and self._ai_test_thread.isRunning():
            return
        save_ai_settings(
            enabled=True,
            api_key=self.ai_apikey_edit.text(),
            base_url=self.ai_baseurl_edit.text(),
            model=self.ai_model_edit.text(),
            system_prompt=self._ai_system_prompt,
        )
        self._set_ai_test_loading(True)
        self._ai_test_thread = QThread()
        self._ai_test_worker = AITestWorker()
        self._ai_test_worker.moveToThread(self._ai_test_thread)
        self._ai_test_thread.started.connect(self._ai_test_worker.run)
        self._ai_test_worker.finished.connect(self._on_ai_test_finished)
        self._ai_test_worker.finished.connect(self._ai_test_thread.quit)
        self._ai_test_worker.finished.connect(self._ai_test_worker.deleteLater)
        self._ai_test_thread.finished.connect(self._ai_test_thread.deleteLater)
        self._ai_test_thread.finished.connect(self._on_ai_test_thread_finished)
        self._ai_test_thread.start()

    def _on_ai_test_finished(self, success: bool, message: str):
        """测试 AI 连接完成"""
        self._set_ai_test_loading(False)
        if success:
            InfoBar.success("", message, parent=self.window(), position=InfoBarPosition.TOP, duration=3000)
        else:
            logging.error("AI 连接测试失败: %s", message)
            InfoBar.error("", message, parent=self.window(), position=InfoBarPosition.TOP, duration=5000)
        save_ai_settings(enabled=self.ai_enabled_card.isChecked())

    def _on_ai_test_thread_finished(self):
        self._ai_test_thread = None
        self._ai_test_worker = None

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
        cfg.browser_preference = self._get_selected_browser_preference()
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
        cfg.ai_enabled = bool(self.ai_enabled_card.isChecked())
        idx = self.ai_provider_combo.currentIndex()
        cfg.ai_provider = str(self.ai_provider_combo.itemData(idx)) if idx >= 0 else "openai"
        cfg.ai_api_key = self.ai_apikey_edit.text().strip()
        cfg.ai_base_url = self.ai_baseurl_edit.text().strip()
        cfg.ai_model = self.ai_model_edit.text().strip()
        cfg.ai_system_prompt = self._ai_system_prompt or DEFAULT_SYSTEM_PROMPT

    def apply_config(self, cfg: RuntimeConfig):
        self.target_spin.setValue(max(1, cfg.target))
        self.thread_spin.setValue(max(1, cfg.threads))
        try:
            self._apply_browser_preference(getattr(cfg, "browser_preference", None))
        except Exception:
            pass

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
            from wjx.network.random_ip import set_proxy_source, set_proxy_api_override
            if proxy_source == "custom" and custom_api:
                set_proxy_api_override(custom_api)
            set_proxy_source(proxy_source)
            area_code = getattr(cfg, "proxy_area_code", None)
            self.random_ip_card.set_area_code(area_code)
        except Exception:
            pass
        self._apply_ai_config(cfg)

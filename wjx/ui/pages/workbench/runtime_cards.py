"""运行参数页 - 专属设置卡片组件（随机IP、随机UA、定时模式等）"""
import logging
from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    ComboBox,
    ExpandGroupSettingCard,
    FluentIcon,
    HyperlinkButton,
    IndicatorPosition,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PushButton,
    SettingCard,
    SwitchButton,
    TransparentToolButton,
)

from wjx.ui.widgets.no_wheel import NoWheelSpinBox
from wjx.ui.widgets.setting_cards import SpinBoxSettingCard, SwitchSettingCard
from wjx.utils.app.config import USER_AGENT_PRESETS


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
        self.proxyTrialLink = HyperlinkButton(
            FluentIcon.LINK, "https://www.ipzan.com?pid=v6bf6iabg",
            "API免费试用", container
        )
        self.proxyTrialLink.hide()
        source_row.addWidget(self.proxyTrialLink)
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
        self.proxyTrialLink.setVisible(source == "custom")
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
            from wjx.core.services.area_service import load_area_codes
            from wjx.core.services.area_service import load_supported_area_codes
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
        from wjx.network.proxy import set_proxy_area_code
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
        from wjx.network.proxy import get_default_proxy_area_code
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
                from wjx.network.proxy import test_custom_proxy_api
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
        from wjx.network.proxy import set_proxy_api_override
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
    """时间范围设置卡 - 使用双向滑块"""

    def __init__(self, icon, title, content, max_seconds: int = 300, parent=None):
        super().__init__(icon, title, content, parent)
        from wjx.ui.widgets.time_range_slider import TimeRangeSlider
        
        self.max_seconds = max_seconds
        self.slider = TimeRangeSlider(
            min_value=0,
            max_value=max_seconds,
            tick_interval=5,
            parent=self
        )
        self.slider.setMinimumWidth(350)
        
        self.hBoxLayout.addWidget(self.slider, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def setEnabled(self, enabled):
        super().setEnabled(enabled)
        self.slider.setEnabled(enabled)
    
    def getRange(self) -> tuple:
        """获取当前范围（秒）"""
        return self.slider.getRange()
    
    def setRange(self, min_sec: int, max_sec: int):
        """设置范围（秒）"""
        self.slider.setRange(min_sec, max_sec)



"""运行参数页 - 专属设置卡片组件（随机IP、随机UA、定时模式等）"""
import logging
from typing import Optional

from PySide6.QtCore import QObject, QThread, Qt, QStringListModel, Signal
from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import QCompleter, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    EditableComboBox,
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
from software.ui.helpers.fluent_tooltip import install_tooltip_filter
from software.ui.helpers.proxy_access import (
    apply_custom_proxy_api,
    apply_proxy_area_code,
    get_proxy_settings,
    load_area_codes,
    load_benefit_supported_areas,
    load_supported_area_codes,
    test_custom_proxy_api,
)


class SearchableComboBox(EditableComboBox):
    """带搜索过滤的下拉框：聚焦时展开全量列表，打字时按包含关系过滤。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._str_model = QStringListModel(self)
        completer = QCompleter(self._str_model, self)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setCompleter(completer)

    def addItem(self, text, icon=None, userData=None):
        super().addItem(text, icon, userData)
        self._sync_model()

    def clear(self):
        super().clear()
        self._sync_model()

    def _sync_model(self):
        self._str_model.setStringList([item.text for item in self.items])

    def _onComboTextChanged(self, text: str):
        # 打字时关闭全量菜单，交给 completer 过滤
        if text:
            self._closeComboMenu()
        super()._onComboTextChanged(text)


# 直辖市省级编码：这些地区用"市辖区"代替"全省/全市"
_MUNICIPALITY_PROVINCE_CODES = {"110000", "120000", "310000", "500000"}
_PROXY_SOURCE_DEFAULT = "default"
_PROXY_SOURCE_BENEFIT = "benefit"
_PROXY_SOURCE_CUSTOM = "custom"


class _BenefitAreaPrefetchWorker(QObject):
    """后台预加载限时福利地区，避免切换代理源时阻塞 UI。"""

    finished = Signal(bool, str)

    def __init__(self, force_refresh: bool = False):
        super().__init__()
        self._force_refresh = bool(force_refresh)

    def run(self):
        try:
            load_benefit_supported_areas(force_refresh=self._force_refresh)
            self.finished.emit(True, "")
        except Exception as exc:
            self.finished.emit(False, str(exc))


class RandomIPSettingCard(ExpandGroupSettingCard):
    """随机IP设置卡 - 包含代理源选择"""

    def __init__(self, parent=None):
        super().__init__(FluentIcon.GLOBE, "随机 IP", "使用代理 IP 来模拟不同地区的访问，并绕过智能验证", parent)

        # 开关
        self.loadingRing = IndeterminateProgressRing(self)
        self.loadingRing.setFixedSize(18, 18)
        self.loadingRing.setStrokeWidth(2)
        self.loadingRing.hide()
        self.addWidget(self.loadingRing)

        self.loadingLabel = BodyLabel("", self)
        self.loadingLabel.setStyleSheet("color: #606060; font-size: 12px;")
        self.loadingLabel.hide()
        self.addWidget(self.loadingLabel)

        self.switchButton = SwitchButton(self, IndicatorPosition.RIGHT)
        self.switchButton.setOnText("开")
        self.switchButton.setOffText("关")
        self.addWidget(self.switchButton)

        # 代理源选择容器
        self._groupContainer = QWidget()
        layout = QVBoxLayout(self._groupContainer)
        layout.setContentsMargins(48, 12, 48, 12)
        layout.setSpacing(12)

        # 代理源下拉框
        source_row = QHBoxLayout()
        source_label = BodyLabel("代理源", self._groupContainer)
        self.proxyCombo = ComboBox(self._groupContainer)
        self.proxyCombo.addItem("默认", userData=_PROXY_SOURCE_DEFAULT)
        self.proxyCombo.addItem("限时福利", userData=_PROXY_SOURCE_BENEFIT)
        self.proxyCombo.addItem("自定义", userData=_PROXY_SOURCE_CUSTOM)
        self.proxyCombo.setMinimumWidth(200)
        source_row.addWidget(source_label)
        source_row.addStretch(1)
        self.proxyTrialLink = HyperlinkButton(
            FluentIcon.LINK, "https://www.ipzan.com?pid=v6bf6iabg",
            "API免费试用", self._groupContainer
        )
        self.proxyTrialLink.hide()
        source_row.addWidget(self.proxyTrialLink)
        source_row.addWidget(self.proxyCombo)
        layout.addLayout(source_row)

        # 地区选择（仅默认代理源）
        self.areaRow = QWidget(self._groupContainer)
        area_layout = QHBoxLayout(self.areaRow)
        area_layout.setContentsMargins(0, 0, 0, 0)
        area_label = BodyLabel("指定地区", self.areaRow)
        self.provinceCombo = SearchableComboBox(self.areaRow)
        self.cityCombo = SearchableComboBox(self.areaRow)
        self.provinceCombo.setMinimumWidth(160)
        self.cityCombo.setMinimumWidth(200)
        area_layout.addWidget(area_label)
        area_layout.addStretch(1)
        area_layout.addWidget(self.provinceCombo)
        area_layout.addWidget(self.cityCombo)
        layout.addWidget(self.areaRow)

        self.benefitHintLabel = BodyLabel(
            "限时福利仅支持 1 分钟以内的作答时长，且只能支持少部分特定城市。如有更高需求请切换至默认或自备代理源",
            self._groupContainer,
        )
        self.benefitHintLabel.setStyleSheet("color: #D46B08; font-size: 12px;")
        self.benefitHintLabel.hide()
        layout.addWidget(self.benefitHintLabel)

        # 自定义API输入
        self.customApiRow = QWidget(self._groupContainer)
        api_layout = QHBoxLayout(self.customApiRow)
        api_layout.setContentsMargins(0, 0, 0, 0)
        api_label = BodyLabel("API 地址", self.customApiRow)
        api_hint = BodyLabel("*不计费。仅支持json返回格式", self.customApiRow)
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
        self._area_source = _PROXY_SOURCE_DEFAULT
        self._benefit_prefetch_done = False
        self._benefit_prefetch_running = False
        self._benefit_prefetch_thread: Optional[QThread] = None
        self._benefit_prefetch_worker: Optional[_BenefitAreaPrefetchWorker] = None
        self._pending_benefit_area_code: Optional[str] = None
        self._load_area_options(_PROXY_SOURCE_DEFAULT)
        self.areaRow.setVisible(True)
        self.provinceCombo.currentIndexChanged.connect(self._on_province_changed)
        self.cityCombo.currentIndexChanged.connect(self._on_city_changed)

        self.addGroupWidget(self._groupContainer)
        self.setExpand(True)

        # 代理源变化时显示/隐藏自定义API
        self.proxyCombo.currentIndexChanged.connect(self._on_source_changed)
        # API地址输入完成时同步到全局变量
        self.customApiEdit.editingFinished.connect(self._on_api_edit_finished)
        # 开关联动：关闭时禁用展开内容
        self.switchButton.checkedChanged.connect(self._sync_ip_enabled)
        self._sync_ip_enabled(False)

    def _get_selected_source(self) -> str:
        idx = self.proxyCombo.currentIndex()
        source = str(self.proxyCombo.itemData(idx)) if idx >= 0 else _PROXY_SOURCE_DEFAULT
        return source if source in {_PROXY_SOURCE_DEFAULT, _PROXY_SOURCE_BENEFIT, _PROXY_SOURCE_CUSTOM} else _PROXY_SOURCE_DEFAULT

    @staticmethod
    def _collect_area_codes(area_data: list) -> set[str]:
        codes: set[str] = set()
        for province in area_data:
            if not isinstance(province, dict):
                continue
            province_code = str(province.get("code") or "")
            if province_code:
                codes.add(province_code)
            for city in list(province.get("cities") or []):
                if not isinstance(city, dict):
                    continue
                city_code = str(city.get("code") or "")
                if city_code:
                    codes.add(city_code)
        return codes

    def _on_source_changed(self):
        source = self._get_selected_source()
        current_area = self.get_area_code()
        self.customApiRow.setVisible(source == _PROXY_SOURCE_CUSTOM)
        self.proxyTrialLink.setVisible(source == _PROXY_SOURCE_CUSTOM)
        self.benefitHintLabel.setVisible(source == _PROXY_SOURCE_BENEFIT)
        self.areaRow.setVisible(source in {_PROXY_SOURCE_DEFAULT, _PROXY_SOURCE_BENEFIT})
        if source == _PROXY_SOURCE_CUSTOM:
            self._apply_area_override(None)
        else:
            if source == _PROXY_SOURCE_BENEFIT and not self._benefit_prefetch_done:
                self._pending_benefit_area_code = current_area
                if not self._benefit_prefetch_running:
                    self._start_benefit_area_prefetch()
                self._area_source = _PROXY_SOURCE_BENEFIT
                self.provinceCombo.clear()
                self.provinceCombo.addItem("正在加载可用城市...", userData="")
                self.cityCombo.clear()
                self.cityCombo.setEnabled(False)
                self._apply_area_override("")
            else:
                self._load_area_options(source)
                self.set_area_code(current_area)
        # 刷新布局 - 重新触发展开/收起来更新高度
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._refreshLayout)

    def _start_benefit_area_prefetch(self, force_refresh: bool = False) -> None:
        if self._benefit_prefetch_running:
            return
        if self._benefit_prefetch_done and not force_refresh:
            return
        self._benefit_prefetch_running = True
        self._benefit_prefetch_thread = QThread(self)
        self._benefit_prefetch_worker = _BenefitAreaPrefetchWorker(force_refresh=force_refresh)
        self._benefit_prefetch_worker.moveToThread(self._benefit_prefetch_thread)
        self._benefit_prefetch_thread.started.connect(self._benefit_prefetch_worker.run)
        self._benefit_prefetch_worker.finished.connect(self._on_benefit_prefetch_finished)
        self._benefit_prefetch_worker.finished.connect(self._benefit_prefetch_thread.quit)
        self._benefit_prefetch_worker.finished.connect(self._benefit_prefetch_worker.deleteLater)
        self._benefit_prefetch_thread.finished.connect(self._benefit_prefetch_thread.deleteLater)
        self._benefit_prefetch_thread.finished.connect(self._on_benefit_prefetch_thread_finished)
        self._benefit_prefetch_thread.start()

    def _on_benefit_prefetch_finished(self, success: bool, error: str) -> None:
        self._benefit_prefetch_running = False
        self._benefit_prefetch_done = bool(success)
        if not success:
            logging.warning("限时福利地区预加载失败: %s", error)
        if self._get_selected_source() != _PROXY_SOURCE_BENEFIT:
            return
        target_area_code = self._pending_benefit_area_code
        self._pending_benefit_area_code = None
        self._load_area_options(_PROXY_SOURCE_BENEFIT)
        self.set_area_code(target_area_code)
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, self._refreshLayout)

    def _on_benefit_prefetch_thread_finished(self) -> None:
        self._benefit_prefetch_thread = None
        self._benefit_prefetch_worker = None

    def _load_area_options(self, source: Optional[str] = None):
        source = str(source or self._get_selected_source() or _PROXY_SOURCE_DEFAULT).strip().lower()
        if source not in {_PROXY_SOURCE_DEFAULT, _PROXY_SOURCE_BENEFIT, _PROXY_SOURCE_CUSTOM}:
            source = _PROXY_SOURCE_DEFAULT
        self._area_source = source
        try:
            if source == _PROXY_SOURCE_BENEFIT:
                self._area_data = load_benefit_supported_areas()
                self._supported_area_codes = self._collect_area_codes(self._area_data)
                self._supported_has_all = True
            else:
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
        if source == _PROXY_SOURCE_BENEFIT or self._supported_has_all or not self._supported_area_codes:
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
        is_municipality = province_code in _MUNICIPALITY_PROVINCE_CODES
        is_benefit = self._area_source == _PROXY_SOURCE_BENEFIT
        # 直辖市不显示"全省/全市"，直接用"市辖区"代表全市
        if (not is_benefit) and not is_municipality and province_code and province_code in self._supported_area_codes:
            self.cityCombo.addItem("全省/全市", userData=province_code)
        cities = self._cities_by_province.get(province_code, [])
        if is_benefit and cities:
            self.cityCombo.addItem("请选择城市", userData="")
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
            elif is_municipality and self.cityCombo.count() > 0:
                # 直辖市找不到 preferred_city_code（如省级码110000）时，回退到第一项（市辖区）
                self.cityCombo.setCurrentIndex(0)

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
        if not self.areaRow.isVisible():
            apply_proxy_area_code(None)
            return
        if area_code is None:
            apply_proxy_area_code(None)
            return
        apply_proxy_area_code(str(area_code))

    def get_area_code(self) -> Optional[str]:
        if not self.areaRow.isVisible():
            return None
        province_code = self.provinceCombo.currentData()
        if not province_code:
            return ""
        city_code = self.cityCombo.currentData()
        return str(city_code or "")

    def set_area_code(self, area_code: Optional[str]) -> None:
        if area_code is None:
            area_code = get_proxy_settings().default_area_code
        area_code = str(area_code or "").strip()
        is_benefit = self._area_source == _PROXY_SOURCE_BENEFIT
        self._area_updating = True
        if not area_code:
            self.provinceCombo.setCurrentIndex(0)
            self.cityCombo.clear()
            self.cityCombo.setEnabled(False)
            self._area_updating = False
            self._apply_area_override("")
            return
        province_code = f"{area_code[:2]}0000" if len(area_code) >= 2 else ""
        if is_benefit and province_code == area_code:
            self.provinceCombo.setCurrentIndex(0)
            self.cityCombo.clear()
            self.cityCombo.setEnabled(False)
            self._area_updating = False
            self._apply_area_override("")
            return
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
        if is_benefit and self.cityCombo.findData(area_code) < 0:
            self.provinceCombo.setCurrentIndex(0)
            self.cityCombo.clear()
            self.cityCombo.setEnabled(False)
            self._area_updating = False
            self._apply_area_override("")
            return
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
            if error:
                self.testApiStatus.setText("⚠")
                self.testApiStatus.setStyleSheet("color: orange; font-size: 16px; font-weight: bold;")
                logging.warning(f"API检测成功但有警告: {error}")
                InfoBar.warning("API检测警告", error, parent=self.window(), position=InfoBarPosition.TOP, duration=5000)
            else:
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
        api_url = self.customApiEdit.text().strip()
        if self._get_selected_source() == _PROXY_SOURCE_CUSTOM:
            apply_custom_proxy_api(api_url if api_url else None)
        else:
            apply_custom_proxy_api(None)

    def isChecked(self):
        return self.switchButton.isChecked()

    def setChecked(self, checked):
        self.switchButton.setChecked(checked)

    def _sync_ip_enabled(self, enabled: bool):
        """开关联动：开启时启用展开内容，关闭时仅灰掉地区/自定义API行。
        代理源选择始终可用，方便用户在额度耗尽时切换到自定义代理源。
        """
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        self.areaRow.setEnabled(bool(enabled))
        self.proxyCombo.setEnabled(True)
        self.customApiRow.setEnabled(True)
        # 清除容器级别的透明度，避免代理源行也变灰
        self._groupContainer.setGraphicsEffect(None)  # type: ignore[arg-type]
        # 只对地区行加半透明效果（指定地区在开关关闭时无意义）
        eff = self.areaRow.graphicsEffect()
        if eff is None:
            eff = QGraphicsOpacityEffect(self.areaRow)
            self.areaRow.setGraphicsEffect(eff)
        eff.setOpacity(1.0 if enabled else 0.4)  # type: ignore[union-attr]

    def setLoading(self, loading: bool, message: str = "") -> None:
        active = bool(loading)
        self.loadingRing.setVisible(active)
        self.loadingLabel.setVisible(active)
        self.loadingLabel.setText(str(message or "正在处理...") if active else "")
        self.switchButton.setEnabled(not active)


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
    """随机UA设置卡 - 包含设备类型占比配置"""

    def __init__(self, parent=None):
        super().__init__(FluentIcon.ROBOT, "随机 UA", "模拟不同的 User-Agent，例如微信环境或浏览器直链环境", parent)

        # 开关
        self.switchButton = SwitchButton(self, IndicatorPosition.RIGHT)
        self.switchButton.setOnText("开")
        self.switchButton.setOffText("关")
        self.addWidget(self.switchButton)

        # 设备占比配置容器
        self._groupContainer = QWidget()
        layout = QVBoxLayout(self._groupContainer)
        layout.setContentsMargins(48, 12, 48, 12)
        layout.setSpacing(16)

        # 提示信息
        hint_label = BodyLabel("配置不同设备类型的访问占比，三个滑块占比总和必须为 100%", self._groupContainer)
        hint_label.setStyleSheet("color: #606060; font-size: 12px;")
        layout.addWidget(hint_label)

        # 三联动占比滑块
        from software.ui.widgets.ratio_slider import RatioSlider
        self.ratioSlider = RatioSlider(
            labels={
                "wechat": "微信访问占比",
                "mobile": "手机访问占比",
                "pc": "链接访问占比",
            },
            parent=self._groupContainer
        )
        layout.addWidget(self.ratioSlider)

        self.addGroupWidget(self._groupContainer)
        self.setExpand(True)
        # 开关联动：关闭时禁用展开内容
        self.switchButton.checkedChanged.connect(self.setUAEnabled)
        self.setUAEnabled(False)

    def isChecked(self):
        return self.switchButton.isChecked()

    def setChecked(self, checked):
        self.switchButton.setChecked(checked)

    def setUAEnabled(self, enabled):
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        self._groupContainer.setEnabled(bool(enabled))
        effect = self._groupContainer.graphicsEffect()
        if effect is None:
            effect = QGraphicsOpacityEffect(self._groupContainer)
            self._groupContainer.setGraphicsEffect(effect)
        effect.setOpacity(1.0 if enabled else 0.4)  # type: ignore[union-attr]

    def getRatios(self) -> dict:
        """获取当前设备占比配置"""
        return self.ratioSlider.getValues()

    def setRatios(self, ratios: dict):
        """设置设备占比配置"""
        self.ratioSlider.setValues(ratios)


class ReliabilitySettingCard(ExpandGroupSettingCard):
    """信效度设置卡 - 开关 + 目标 Alpha 输入框

    使用 ExpandGroupSettingCard 承载一个总开关和一行数值输入：
    - 开关：控制是否启用信效度优化
    - 输入框：目标 Cronbach's Alpha 系数，范围 0.70-0.95
    """
    def __init__(self, parent=None):
        super().__init__(
            FluentIcon.CERTIFICATE,
            "提升问卷信效度",
            "启用后仅优化随机/预设题的一致性；手动自定义配比始终绝对优先，不会被改写。",
            parent,
        )

        # 顶部开关
        self.switchButton = SwitchButton(self, IndicatorPosition.RIGHT)
        self.switchButton.setOnText("开")
        self.switchButton.setOffText("关")
        self.addWidget(self.switchButton)

        # 展开区域容器
        self._groupContainer = QWidget(self)
        layout = QVBoxLayout(self._groupContainer)
        layout.setContentsMargins(48, 12, 48, 12)
        layout.setSpacing(12)

        # 目标信度 Alpha 行
        alpha_row = QHBoxLayout()
        alpha_row.setContentsMargins(0, 0, 0, 0)
        alpha_row.setSpacing(8)

        alpha_label = BodyLabel("目标 Cronbach's α 系数", self._groupContainer)
        self.alphaEdit = LineEdit(self._groupContainer)
        self.alphaEdit.setPlaceholderText("0.70 - 0.95（默认 0.9）")
        self.alphaEdit.setFixedWidth(120)
        self.alphaEdit.setFixedHeight(36)
        self.alphaEdit.setText("0.9")

        # 仅允许 0.70 - 0.95 的两位小数
        validator = QDoubleValidator(0.70, 0.95, 2, self.alphaEdit)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.alphaEdit.setValidator(validator)

        alpha_row.addWidget(alpha_label)
        alpha_row.addStretch(1)
        alpha_row.addWidget(self.alphaEdit)

        layout.addLayout(alpha_row)


        self.addGroupWidget(self._groupContainer)
        self.setExpand(True)

        # 开关联动：关闭时禁用展开内容
        self.switchButton.checkedChanged.connect(self._sync_enabled)
        self._sync_enabled(False)

    def _sync_enabled(self, enabled: bool) -> None:
        """根据开关状态启用/禁用内部控件。"""

        self._groupContainer.setEnabled(bool(enabled))

    def isChecked(self) -> bool:
        return self.switchButton.isChecked()

    def setChecked(self, checked: bool) -> None:
        self.switchButton.setChecked(bool(checked))

    def get_alpha(self) -> float:
        """读取并裁剪目标 Alpha 值，落在 0.70-0.95 之间。

        输入非法或为空时回退到 0.9。
        """

        text = (self.alphaEdit.text() or "").strip()
        try:
            value = float(text)
        except Exception:
            value = 0.9

        if value != value:  # NaN 兜底
            value = 0.9

        value = max(0.70, min(0.95, value))
        return value

    def set_alpha(self, value: float) -> None:
        """设置目标 Alpha，并同步到输入框文本。"""

        try:
            num = float(value)
        except Exception:
            num = 0.9
        num = max(0.70, min(0.95, num))
        # 保留两位小数，去掉多余 0
        text = f"{num:.2f}".rstrip("0").rstrip(".")
        if not text:
            text = "0.9"
        if self.alphaEdit.text() != text:
            self.alphaEdit.setText(text)

class TimeRangeSettingCard(SettingCard):
    """时间设置卡 - 使用普通数字输入框（秒）"""

    valueChanged = Signal(int)

    def __init__(self, icon, title, content, max_seconds: int = 300, parent=None):
        super().__init__(icon, title, content, parent)

        self.max_seconds = max_seconds
        self._current_value = 0

        self._input_container = QWidget(self)
        input_layout = QHBoxLayout(self._input_container)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(8)

        self.inputEdit = LineEdit(self._input_container)
        self.inputEdit.setValidator(QIntValidator(0, max_seconds, self.inputEdit))
        self.inputEdit.setFixedWidth(128)
        self.inputEdit.setFixedHeight(36)
        self.inputEdit.setText("0")
        self.inputEdit.setToolTip(f"允许范围：0-{max_seconds} 秒")
        install_tooltip_filter(self.inputEdit)
        self.inputEdit.textChanged.connect(self._on_text_changed)
        self.inputEdit.editingFinished.connect(self._normalize_text)

        sec_label = BodyLabel("秒", self._input_container)
        sec_label.setStyleSheet("color: #606060;")

        input_layout.addWidget(self.inputEdit)
        input_layout.addWidget(sec_label)

        self.hBoxLayout.addWidget(self._input_container, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def _clamp_value(self, value: int) -> int:
        return max(0, min(int(value), self.max_seconds))

    @staticmethod
    def _parse_digits(text: str, fallback: int) -> int:
        raw = str(text or "").strip()
        return int(raw) if raw.isdigit() else int(fallback)

    def _on_text_changed(self, text: str):
        value = self._clamp_value(self._parse_digits(text, fallback=0))
        if value != self._current_value:
            self._current_value = value
            self.valueChanged.emit(value)

    def _normalize_text(self):
        self.setValue(self.getValue())

    def setEnabled(self, enabled):
        super().setEnabled(enabled)
        self.inputEdit.setEnabled(enabled)

    def getValue(self) -> int:
        """获取当前秒数"""
        value = self._clamp_value(self._parse_digits(self.inputEdit.text(), fallback=self._current_value))
        self._current_value = value
        return value

    def setValue(self, value: int):
        """设置当前秒数"""
        value = self._clamp_value(value)
        previous = self._current_value
        self._current_value = value
        display = str(value)
        if self.inputEdit.text() != display:
            self.inputEdit.blockSignals(True)
            self.inputEdit.setText(display)
            self.inputEdit.blockSignals(False)
        if value != previous:
            self.valueChanged.emit(value)




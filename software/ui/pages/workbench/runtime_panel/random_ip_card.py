"""随机 IP 设置卡。"""

from __future__ import annotations

import logging
from typing import Optional, cast

from PySide6.QtCore import QObject, QThread, Qt, QStringListModel, Signal
from PySide6.QtWidgets import QCompleter, QGraphicsEffect, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    EditableComboBox,
    ExpandGroupSettingCard,
    FluentIcon,
    HyperlinkButton,
    IndicatorPosition,
    IndeterminateProgressRing,
    InfoBarPosition,
    LineEdit,
    PushButton,
    SwitchButton,
)

from software.ui.helpers.message_bar import show_message_bar
from software.ui.helpers.proxy_access import (
    apply_custom_proxy_api,
    apply_proxy_area_code,
    get_proxy_settings,
    load_area_codes,
    load_benefit_supported_areas,
    load_supported_area_codes,
    test_custom_proxy_api,
)
from software.ui.widgets.setting_cards import set_widget_enabled_with_opacity

_MUNICIPALITY_PROVINCE_CODES = {"110000", "120000", "310000", "500000"}
_PROXY_SOURCE_DEFAULT = "default"
_PROXY_SOURCE_BENEFIT = "benefit"
_PROXY_SOURCE_CUSTOM = "custom"


class SearchableComboBox(EditableComboBox):
    """带搜索过滤的下拉框。"""

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
        if text:
            self._closeComboMenu()
        super()._onComboTextChanged(text)


class _BenefitAreaPrefetchWorker(QObject):
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


class _ProxyApiTestWorker(QObject):
    finished = Signal(bool, str, list)

    def __init__(self, url: str):
        super().__init__()
        self.url = str(url or "")

    def run(self):
        success, error, proxies = test_custom_proxy_api(self.url)
        self.finished.emit(success, error, proxies)


class RandomIPSettingCard(ExpandGroupSettingCard):
    """随机IP设置卡。"""

    def __init__(self, parent=None):
        super().__init__(
            FluentIcon.GLOBE,
            "随机 IP",
            "使用代理 IP 来模拟不同地区的访问，并绕过智能验证",
            parent,
        )
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
        self._test_thread: Optional[QThread] = None
        self._test_worker: Optional[_ProxyApiTestWorker] = None

        self._build_header_widgets()
        self._build_group_container()
        self._load_area_options(_PROXY_SOURCE_DEFAULT)
        self._bind_events()
        self._sync_ip_enabled(False)

    def _build_header_widgets(self) -> None:
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

    def _build_group_container(self) -> None:
        self._groupContainer = QWidget(self)
        layout = QVBoxLayout(self._groupContainer)
        layout.setContentsMargins(48, 12, 48, 12)
        layout.setSpacing(12)

        self._build_source_row(layout)
        self._build_area_row(layout)
        self._build_benefit_hint(layout)
        self._build_custom_api_row(layout)

        self.addGroupWidget(self._groupContainer)
        self.setExpand(True)

    def _build_source_row(self, layout: QVBoxLayout) -> None:
        source_row = QHBoxLayout()
        source_row.addWidget(BodyLabel("代理源", self._groupContainer))
        source_row.addStretch(1)

        self.proxyTrialLink = HyperlinkButton(
            FluentIcon.LINK,
            "https://www.ipzan.com?pid=v6bf6iabg",
            "API免费试用",
            self._groupContainer,
        )
        self.proxyTrialLink.hide()
        source_row.addWidget(self.proxyTrialLink)

        self.proxyCombo = ComboBox(self._groupContainer)
        self.proxyCombo.addItem("默认", userData=_PROXY_SOURCE_DEFAULT)
        self.proxyCombo.addItem("限时福利", userData=_PROXY_SOURCE_BENEFIT)
        self.proxyCombo.addItem("自定义", userData=_PROXY_SOURCE_CUSTOM)
        self.proxyCombo.setMinimumWidth(200)
        source_row.addWidget(self.proxyCombo)
        layout.addLayout(source_row)

    def _build_area_row(self, layout: QVBoxLayout) -> None:
        self.areaRow = QWidget(self._groupContainer)
        area_layout = QHBoxLayout(self.areaRow)
        area_layout.setContentsMargins(0, 0, 0, 0)
        area_layout.addWidget(BodyLabel("指定地区", self.areaRow))
        area_layout.addStretch(1)
        self.provinceCombo = SearchableComboBox(self.areaRow)
        self.cityCombo = SearchableComboBox(self.areaRow)
        self.provinceCombo.setMinimumWidth(160)
        self.cityCombo.setMinimumWidth(200)
        area_layout.addWidget(self.provinceCombo)
        area_layout.addWidget(self.cityCombo)
        layout.addWidget(self.areaRow)

    def _build_benefit_hint(self, layout: QVBoxLayout) -> None:
        self.benefitHintLabel = BodyLabel(
            "限时福利源只支持少部分特定城市，如有更高需求请切换至默认或自备代理源",
            self._groupContainer,
        )
        self.benefitHintLabel.setStyleSheet("color: #D46B08; font-size: 12px;")
        self.benefitHintLabel.hide()
        layout.addWidget(self.benefitHintLabel)

    def _build_custom_api_row(self, layout: QVBoxLayout) -> None:
        self.customApiRow = QWidget(self._groupContainer)
        api_layout = QHBoxLayout(self.customApiRow)
        api_layout.setContentsMargins(0, 0, 0, 0)
        api_layout.addWidget(BodyLabel("API 地址", self.customApiRow))
        api_hint = BodyLabel("*不计费。仅支持json返回格式", self.customApiRow)
        api_hint.setStyleSheet("color: red; font-size: 11px;")
        api_layout.addWidget(api_hint)
        api_layout.addStretch(1)

        self.customApiEdit = LineEdit(self.customApiRow)
        self.customApiEdit.setPlaceholderText("请输入代理api地址")
        self.customApiEdit.setMinimumWidth(420)
        api_layout.addWidget(self.customApiEdit)

        self.testBtnContainer = QWidget(self.customApiRow)
        test_layout = QHBoxLayout(self.testBtnContainer)
        test_layout.setContentsMargins(0, 0, 0, 0)
        test_layout.setSpacing(4)
        self.testApiBtn = PushButton("检测", self.testBtnContainer)
        self.testApiBtn.setFixedWidth(60)
        self.testApiSpinner = IndeterminateProgressRing(self.testBtnContainer)
        self.testApiSpinner.setFixedSize(20, 20)
        self.testApiSpinner.hide()
        self.testApiStatus = BodyLabel("", self.testBtnContainer)
        self.testApiStatus.setFixedWidth(20)
        self.testApiStatus.hide()
        for widget in (self.testApiBtn, self.testApiSpinner, self.testApiStatus):
            test_layout.addWidget(widget)
        api_layout.addWidget(self.testBtnContainer)
        self.customApiRow.hide()
        layout.addWidget(self.customApiRow)

    def _bind_events(self) -> None:
        self.provinceCombo.currentIndexChanged.connect(self._on_province_changed)
        self.cityCombo.currentIndexChanged.connect(self._on_city_changed)
        self.proxyCombo.currentIndexChanged.connect(self._on_source_changed)
        self.customApiEdit.editingFinished.connect(self._on_api_edit_finished)
        self.switchButton.checkedChanged.connect(self._sync_ip_enabled)
        self.testApiBtn.clicked.connect(self._on_test_api_clicked)

    def _window_parent(self):
        return self.window() or self

    def _toast(self, level: str, message: str, duration: int = 3000) -> None:
        show_message_bar(
            parent=self._window_parent(),
            title="",
            message=message,
            level=level,
            position=InfoBarPosition.TOP,
            duration=duration,
        )

    def _get_selected_source(self) -> str:
        source = str(self.proxyCombo.currentData() or _PROXY_SOURCE_DEFAULT)
        if source in {_PROXY_SOURCE_DEFAULT, _PROXY_SOURCE_BENEFIT, _PROXY_SOURCE_CUSTOM}:
            return source
        return _PROXY_SOURCE_DEFAULT

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
                if isinstance(city, dict) and city.get("code"):
                    codes.add(str(city["code"]))
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
        elif source == _PROXY_SOURCE_BENEFIT and not self._benefit_prefetch_done:
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

        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, self._refreshLayout)

    def _start_benefit_area_prefetch(self, force_refresh: bool = False) -> None:
        if self._benefit_prefetch_running or (self._benefit_prefetch_done and not force_refresh):
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
        selected_source = str(source or self._get_selected_source() or _PROXY_SOURCE_DEFAULT).strip().lower()
        if selected_source not in {_PROXY_SOURCE_DEFAULT, _PROXY_SOURCE_BENEFIT, _PROXY_SOURCE_CUSTOM}:
            selected_source = _PROXY_SOURCE_DEFAULT
        self._area_source = selected_source
        try:
            if selected_source == _PROXY_SOURCE_BENEFIT:
                self._area_data = load_benefit_supported_areas()
                self._supported_area_codes = self._collect_area_codes(self._area_data)
                self._supported_has_all = True
            else:
                self._supported_area_codes, self._supported_has_all = load_supported_area_codes()
                self._area_data = load_area_codes(supported_only=True)
        except Exception as exc:
            logging.error("加载地区数据失败: %s", exc, exc_info=True)
            self._area_data = []
            self._supported_area_codes = set()
            self._supported_has_all = False

        self._cities_by_province = {}
        self._province_index_by_code = {}
        self.provinceCombo.clear()
        if (
            selected_source == _PROXY_SOURCE_BENEFIT
            or self._supported_has_all
            or not self._supported_area_codes
        ):
            self.provinceCombo.addItem("不限制", userData="")
        for province in self._area_data:
            code = str(province.get("code") or "")
            name = str(province.get("name") or "")
            if not code or not name:
                continue
            self._cities_by_province[code] = list(province.get("cities") or [])
            self.provinceCombo.addItem(name, userData=code)
            self._province_index_by_code[code] = self.provinceCombo.count() - 1
        self.cityCombo.clear()
        self.cityCombo.setEnabled(False)

    def _populate_cities(
        self,
        province_code: str,
        preferred_city_code: Optional[str] = None,
    ) -> None:
        self.cityCombo.clear()
        is_municipality = province_code in _MUNICIPALITY_PROVINCE_CODES
        is_benefit = self._area_source == _PROXY_SOURCE_BENEFIT
        if (
            not is_benefit
            and not is_municipality
            and province_code
            and province_code in self._supported_area_codes
        ):
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
            index = self.cityCombo.findData(preferred_city_code)
            if index >= 0:
                self.cityCombo.setCurrentIndex(index)
            elif is_municipality and self.cityCombo.count() > 0:
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
        if not self.areaRow.isVisible() or area_code is None:
            apply_proxy_area_code(None)
            return
        apply_proxy_area_code(str(area_code))

    def get_area_code(self) -> Optional[str]:
        if not self.areaRow.isVisible():
            return None
        province_code = self.provinceCombo.currentData()
        if not province_code:
            return ""
        return str(self.cityCombo.currentData() or "")

    def set_area_code(self, area_code: Optional[str]) -> None:
        if area_code is None:
            area_code = get_proxy_settings().default_area_code
        normalized = str(area_code or "").strip()
        is_benefit = self._area_source == _PROXY_SOURCE_BENEFIT
        self._area_updating = True
        if not normalized:
            self.provinceCombo.setCurrentIndex(0)
            self.cityCombo.clear()
            self.cityCombo.setEnabled(False)
            self._area_updating = False
            self._apply_area_override("")
            return
        province_code = f"{normalized[:2]}0000" if len(normalized) >= 2 else ""
        if is_benefit and province_code == normalized:
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
        self._populate_cities(province_code, preferred_city_code=normalized)
        if is_benefit and self.cityCombo.findData(normalized) < 0:
            self.provinceCombo.setCurrentIndex(0)
            self.cityCombo.clear()
            self.cityCombo.setEnabled(False)
            self._area_updating = False
            self._apply_area_override("")
            return
        self._area_updating = False
        self._apply_area_override(self.cityCombo.currentData())

    def _refreshLayout(self):
        if self.isExpand:
            self._adjustViewSize()

    def _on_test_api_clicked(self):
        api_url = self.customApiEdit.text().strip()
        if not api_url:
            self._toast("warning", "请先输入API地址")
            return
        self.testApiBtn.hide()
        self.testApiStatus.hide()
        self.testApiSpinner.show()

        self._test_thread = QThread(self)
        self._test_worker = _ProxyApiTestWorker(api_url)
        self._test_worker.moveToThread(self._test_thread)
        self._test_thread.started.connect(self._test_worker.run)
        self._test_worker.finished.connect(self._on_test_finished)
        self._test_worker.finished.connect(self._test_thread.quit)
        self._test_worker.finished.connect(self._test_worker.deleteLater)
        self._test_thread.finished.connect(self._test_thread.deleteLater)
        self._test_thread.finished.connect(self._on_test_thread_finished)
        self._test_thread.start()

    def _on_test_finished(self, success: bool, error: str, proxies: list):
        self.testApiSpinner.hide()
        self.testApiStatus.show()
        if success:
            if error:
                self.testApiStatus.setText("⚠")
                self.testApiStatus.setStyleSheet("color: orange; font-size: 16px; font-weight: bold;")
                logging.warning("API检测成功但有警告: %s", error)
                self._toast("warning", error, duration=5000)
            else:
                self.testApiStatus.setText("✔")
                self.testApiStatus.setStyleSheet("color: green; font-size: 16px; font-weight: bold;")
                logging.info("API检测成功，获取到 %s 个代理", len(proxies))
        else:
            self.testApiStatus.setText("✖")
            self.testApiStatus.setStyleSheet("color: red; font-size: 16px; font-weight: bold;")
            logging.error("API检测失败: %s", error)
            self._toast("error", error, duration=5000)

        from PySide6.QtCore import QTimer

        QTimer.singleShot(3000, self._reset_test_button)

    def _on_test_thread_finished(self) -> None:
        self._test_thread = None
        self._test_worker = None

    def _reset_test_button(self):
        self.testApiStatus.hide()
        self.testApiBtn.show()

    def _on_api_edit_finished(self):
        api_url = self.customApiEdit.text().strip()
        if self._get_selected_source() == _PROXY_SOURCE_CUSTOM:
            apply_custom_proxy_api(api_url if api_url else None)
            return
        apply_custom_proxy_api(None)

    def isChecked(self):
        return self.switchButton.isChecked()

    def setChecked(self, checked):
        self.switchButton.setChecked(checked)

    def _sync_ip_enabled(self, enabled: bool):
        self.areaRow.setEnabled(bool(enabled))
        self.proxyCombo.setEnabled(True)
        self.customApiRow.setEnabled(True)
        self._groupContainer.setGraphicsEffect(cast(QGraphicsEffect, None))
        set_widget_enabled_with_opacity(self.areaRow, bool(enabled))

    def setLoading(self, loading: bool, message: str = "") -> None:
        active = bool(loading)
        self.loadingRing.setVisible(active)
        self.loadingLabel.setVisible(active)
        self.loadingLabel.setText(str(message or "正在处理...") if active else "")
        self.switchButton.setEnabled(not active)

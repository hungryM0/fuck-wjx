"""向导地区题配置区。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, ComboBox

from software.core.questions.config import QuestionEntry

from .location_options import (
    AUTO_LOCATION_TEXT,
    load_location_provinces,
    _normalize_area_display_name,
    _normalize_province_display_name,
)
from .utils import _apply_label_color


class WizardSectionsLocationMixin:
    if TYPE_CHECKING:
        _has_content: bool
        location_combo_map: Dict[int, List[Any]]

    def _build_location_section(
        self,
        idx: int,
        entry: QuestionEntry,
        card: CardWidget,
        card_layout: QVBoxLayout,
    ) -> None:
        self._has_content = True
        saved_parts = [str(item or "").strip() for item in list(getattr(entry, "location_parts", []) or [])[:3]]

        container = QWidget(card)
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        province_combo = ComboBox(container)
        city_combo = ComboBox(container)
        area_combo = ComboBox(container)
        for combo in (province_combo, city_combo, area_combo):
            combo.setMinimumWidth(150)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        provinces = load_location_provinces()
        province_combo.addItem(AUTO_LOCATION_TEXT, userData="")
        for province in provinces:
            province_combo.addItem(
                str(province.get("display_name") or _normalize_province_display_name(province.get("name")) or province.get("name") or "").strip(),
                userData=province,
            )

        city_combo.addItem(AUTO_LOCATION_TEXT, userData="")
        area_combo.addItem(AUTO_LOCATION_TEXT, userData="")
        area_combo.setText(AUTO_LOCATION_TEXT)

        def add_labeled_combo(label_text: str, combo: QWidget) -> None:
            group = QWidget(container)
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(3)
            label = BodyLabel(label_text, group)
            label.setStyleSheet("font-size: 12px;")
            _apply_label_color(label, "#666666", "#bfbfbf")
            group_layout.addWidget(label)
            group_layout.addWidget(combo)
            row.addWidget(group, 1, Qt.AlignmentFlag.AlignTop)

        add_labeled_combo("省份", province_combo)
        add_labeled_combo("城市", city_combo)
        add_labeled_combo("区县", area_combo)
        layout.addLayout(row)
        card_layout.addWidget(container)

        def populate_areas(city_data: Any, preferred: str = "") -> None:
            area_combo.clear()
            area_combo.addItem(AUTO_LOCATION_TEXT, userData="")
            if isinstance(city_data, dict):
                area_nodes = list(city_data.get("areas") or [])
                for area in area_nodes:
                    if not isinstance(area, dict):
                        continue
                    name = _normalize_area_display_name(area.get("name"))
                    if name:
                        area_combo.addItem(name, userData=area)
            preferred = _normalize_area_display_name(preferred)
            target_index = 0
            if preferred:
                for area_index in range(area_combo.count()):
                    if area_combo.itemText(area_index) == preferred:
                        target_index = area_index
                        break
            area_combo.setCurrentIndex(target_index)

        def populate_cities(province_data: Any, preferred_city: str = "", preferred_area: str = "") -> None:
            city_combo.clear()
            city_combo.addItem(AUTO_LOCATION_TEXT, userData="")
            if isinstance(province_data, dict):
                for city in list(province_data.get("cities") or []):
                    if not isinstance(city, dict):
                        continue
                    name = str(city.get("display_name") or city.get("name") or "").strip()
                    if name:
                        city_combo.addItem(name, userData=city)
            preferred_city = str(preferred_city or "").strip()
            target_index = 0
            if preferred_city:
                for city_index in range(city_combo.count()):
                    if city_combo.itemText(city_index) == preferred_city:
                        target_index = city_index
                        break
            city_combo.setCurrentIndex(target_index)
            city_data = city_combo.currentData()
            populate_areas(city_data, preferred_area)

        def on_city_changed(_index: int) -> None:
            populate_areas(city_combo.currentData())

        def on_province_changed(_index: int) -> None:
            populate_cities(province_combo.currentData())

        province_combo.currentIndexChanged.connect(on_province_changed)
        city_combo.currentIndexChanged.connect(on_city_changed)

        preferred_province = str(saved_parts[0] if saved_parts else "").strip()
        if preferred_province:
            for province_index in range(province_combo.count()):
                if province_combo.itemText(province_index) == preferred_province:
                    province_combo.setCurrentIndex(province_index)
                    break
        populate_cities(
            province_combo.currentData(),
            saved_parts[1] if len(saved_parts) > 1 else "",
            saved_parts[2] if len(saved_parts) > 2 else "",
        )

        self.location_combo_map[idx] = [province_combo, city_combo, area_combo]

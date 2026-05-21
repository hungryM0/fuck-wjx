"""向导地区题配置区。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, ComboBox, EditableComboBox

from software.core.questions.config import QuestionEntry

from .location_options import AUTO_LOCATION_TEXT, load_location_provinces, simplify_location_name
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
        area_combo = EditableComboBox(container)
        for combo in (province_combo, city_combo, area_combo):
            combo.setMinimumWidth(150)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        provinces = load_location_provinces()
        province_combo.addItem(AUTO_LOCATION_TEXT, userData="")
        for province in provinces:
            province_combo.addItem(simplify_location_name(province.get("name")), userData=province)

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

        def populate_cities(province_data: Any, preferred: str = "") -> None:
            city_combo.clear()
            city_combo.addItem(AUTO_LOCATION_TEXT, userData="")
            if isinstance(province_data, dict):
                for city in list(province_data.get("cities") or []):
                    if not isinstance(city, dict):
                        continue
                    name = simplify_location_name(city.get("name"))
                    if name and name != "市辖区":
                        city_combo.addItem(name, userData=city)
            preferred = simplify_location_name(preferred)
            target_index = 0
            if preferred:
                for city_index in range(city_combo.count()):
                    if city_combo.itemText(city_index) == preferred:
                        target_index = city_index
                        break
            city_combo.setCurrentIndex(target_index)

        def on_province_changed(_index: int) -> None:
            populate_cities(province_combo.currentData())

        province_combo.currentIndexChanged.connect(on_province_changed)

        preferred_province = simplify_location_name(saved_parts[0] if saved_parts else "")
        if preferred_province:
            for province_index in range(province_combo.count()):
                if province_combo.itemText(province_index) == preferred_province:
                    province_combo.setCurrentIndex(province_index)
                    break
        populate_cities(province_combo.currentData(), saved_parts[1] if len(saved_parts) > 1 else "")

        preferred_area = str(saved_parts[2] if len(saved_parts) > 2 else "").strip()
        if preferred_area:
            area_combo.setText(preferred_area)

        self.location_combo_map[idx] = [province_combo, city_combo, area_combo]

"""配置向导地区题选项。"""

from __future__ import annotations

from typing import Any, List

from software.network.proxy.areas import load_area_codes

AUTO_LOCATION_TEXT = "自动选择"


def load_location_provinces() -> List[dict[str, Any]]:
    provinces: List[dict[str, Any]] = []
    for province in load_area_codes(supported_only=False):
        if not isinstance(province, dict):
            continue
        name = str(province.get("name") or "").strip()
        if not name:
            continue
        cities = province.get("cities")
        provinces.append({**province, "name": name, "cities": cities if isinstance(cities, list) else []})
    return provinces


def simplify_location_name(value: Any) -> str:
    text = str(value or "").strip()
    for suffix in ("省", "市"):
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break
    return text

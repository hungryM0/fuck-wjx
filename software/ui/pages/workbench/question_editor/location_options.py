"""配置向导地区题选项。"""

from __future__ import annotations

import json
import re
import copy
from functools import lru_cache
from importlib import resources
from typing import Any, List

from software.network.proxy.areas import load_area_codes

AUTO_LOCATION_TEXT = "自动选择"
_LOCATION_TREE_RESOURCE = "location_tree_2022.json"
_PROVINCE_SUFFIXES = (
    "维吾尔自治区",
    "回族自治区",
    "壮族自治区",
    "特别行政区",
    "自治区",
    "省",
    "市",
)
_CITY_SUFFIXES = (
    "自治州",
    "地区",
    "盟",
    "市",
)


def _read_location_tree() -> List[dict[str, Any]]:
    try:
        tree_file = resources.files("software.assets").joinpath(_LOCATION_TREE_RESOURCE)
        payload = json.loads(tree_file.read_text(encoding="utf-8"))
    except Exception:
        payload = []
    return payload if isinstance(payload, list) else []


def _normalize_location_name(value: Any, *, suffixes: tuple[str, ...]) -> str:
    text = re.sub(r"\s+", "", str(value or "").strip())
    for suffix in suffixes:
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break
    return text


def _normalize_province_display_name(value: Any) -> str:
    return _normalize_location_name(value, suffixes=_PROVINCE_SUFFIXES)


def _normalize_city_display_name(value: Any) -> str:
    return _normalize_location_name(value, suffixes=_CITY_SUFFIXES)


def _normalize_area_display_name(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _normalize_city_node(raw_city: dict[str, Any], province_name: str, *, is_municipality: bool) -> dict[str, Any]:
    city_name = str(raw_city.get("name") or "").strip()
    raw_children = raw_city.get("children")
    city_children = raw_children if isinstance(raw_children, list) else []
    display_name = province_name if is_municipality else city_name
    return {
        **raw_city,
        "name": city_name,
        "display_name": display_name or city_name,
        "areas": [item for item in city_children if isinstance(item, dict)],
    }


def _normalize_province_node(raw_province: dict[str, Any]) -> dict[str, Any]:
    province_name = str(raw_province.get("name") or "").strip()
    raw_children = raw_province.get("children")
    province_children = raw_children if isinstance(raw_children, list) else []
    province_code = str(raw_province.get("code") or "").strip()
    is_municipality = province_code in {"110000", "120000", "310000", "500000"}
    if is_municipality:
        cities = [
            {
                "code": str(raw_province.get("code") or "").strip(),
                "name": province_name,
                "display_name": province_name,
                "areas": [item for item in province_children if isinstance(item, dict)],
            }
        ]
    else:
        cities = [_normalize_city_node(city, province_name, is_municipality=False) for city in province_children if isinstance(city, dict)]
    return {
        **raw_province,
        "name": province_name,
        "display_name": _normalize_province_display_name(province_name),
        "cities": cities,
    }


@lru_cache(maxsize=1)
def _load_location_provinces_cached() -> tuple[dict[str, Any], ...]:
    provinces: List[dict[str, Any]] = []
    location_tree = _read_location_tree()
    if location_tree:
        for province in location_tree:
            if not isinstance(province, dict):
                continue
            name = str(province.get("name") or "").strip()
            if not name:
                continue
            provinces.append(_normalize_province_node(province))
        return tuple(provinces)

    for province in load_area_codes(supported_only=False):
        if not isinstance(province, dict):
            continue
        name = str(province.get("name") or "").strip()
        if not name:
            continue
        raw_cities = province.get("cities")
        provinces.append(
            {
                **province,
                "name": name,
                "display_name": _normalize_province_display_name(name),
                "cities": raw_cities if isinstance(raw_cities, list) else [],
            }
        )
    return tuple(provinces)


def load_location_provinces() -> List[dict[str, Any]]:
    return copy.deepcopy(list(_load_location_provinces_cached()))


def simplify_location_name(value: Any) -> str:
    return _normalize_province_display_name(value)

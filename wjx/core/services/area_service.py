"""地区编码与支持列表读取服务。"""
from __future__ import annotations

import json
from importlib import resources
from typing import Any, Dict, List, Set, Tuple


def _read_asset_text(filename: str) -> str:
    try:
        asset_file = resources.files("wjx.assets").joinpath(filename)
        return asset_file.read_text(encoding="utf-8")
    except Exception:
        return ""


def load_supported_area_codes() -> Tuple[Set[str], bool]:
    """返回支持的地区编码集合，以及是否包含 all 标记。"""
    codes: Set[str] = set()
    has_all = False
    content = _read_asset_text("area.txt")
    if not content:
        return codes, has_all

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        code = str(parts[-1]).strip()
        if not code:
            continue
        if code.lower() == "all":
            has_all = True
            continue
        if code.isdigit() and len(code) == 6:
            codes.add(code)
    return codes, has_all


def load_area_codes(supported_only: bool = False) -> List[Dict[str, Any]]:
    """读取省市区编码。"""
    try:
        payload = json.loads(_read_asset_text("area_codes_2022.json") or "{}")
    except Exception:
        return []
    provinces = payload.get("provinces")
    if not isinstance(provinces, list):
        return []
    if not supported_only:
        return provinces

    supported_codes, _ = load_supported_area_codes()
    if not supported_codes:
        return []

    filtered: List[Dict[str, Any]] = []
    for province in provinces:
        if not isinstance(province, dict):
            continue
        province_code = str(province.get("code") or "")
        cities = province.get("cities") or []
        if not isinstance(cities, list):
            cities = []
        supported_cities = [
            city
            for city in cities
            if isinstance(city, dict) and str(city.get("code") or "") in supported_codes
        ]
        if province_code not in supported_codes and not supported_cities:
            continue
        filtered.append({**province, "cities": supported_cities})
    return filtered


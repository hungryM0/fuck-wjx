"""地区编码、支持列表与 benefit 上游地区解析服务。"""
from __future__ import annotations

import copy
import json
import logging
import re
import threading
from importlib import resources
from typing import Any, Dict, List, Optional, Set, Tuple

import software.network.http as http_client
from software.app.config import DEFAULT_HTTP_HEADERS

_BENEFIT_AREA_INFO_URL = "https://www.juliangip.com/downLoadAreaInfo"
_BENEFIT_FETCH_TIMEOUT_SECONDS = 10
_AREA_CODE_PATTERN = re.compile(r"^\d{6}$")
_ONLINE_PROVINCE_PATTERN = re.compile(r"^\s*省份[:：]\s*(?P<province>.+?)\s*$")
_ONLINE_CITY_PATTERN = re.compile(r"^\s*城市[:：]\s*(?P<city>.+?)(?:\s+运营商[:：].*)?$")

_MUNICIPALITY_REQUEST_NAMES = {
    "110000": "北京",
    "120000": "天津",
    "310000": "上海",
    "500000": "重庆",
}
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
    "特别行政区",
    "自治州",
    "地区",
    "盟",
    "市",
)


def _read_asset_text(filename: str) -> str:
    try:
        asset_file = resources.files("software.assets").joinpath(filename)
        return asset_file.read_text(encoding="utf-8")
    except Exception:
        return ""


# 模块级缓存
_AREA_CODES_CACHE: Dict[str, Any] | None = None
_SUPPORTED_CODES_CACHE: Tuple[Set[str], bool] | None = None
_BENEFIT_CACHE_LOCK = threading.RLock()
_BENEFIT_SUPPORTED_AREAS_CACHE: List[Dict[str, Any]] | None = None
_BENEFIT_CITY_CODE_INDEX_CACHE: Dict[str, str] | None = None


def _normalize_province_name(name: Any) -> str:
    text = re.sub(r"\s+", "", str(name or "").strip())
    for suffix in _PROVINCE_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text


def _normalize_city_name(name: Any) -> str:
    text = re.sub(r"\s+", "", str(name or "").strip())
    if text == "市辖区":
        return text
    for suffix in _CITY_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text


def _normalize_area_code(area_code: Any) -> str:
    text = str(area_code or "").strip()
    return text if _AREA_CODE_PATTERN.fullmatch(text) else ""


def load_supported_area_codes() -> Tuple[Set[str], bool]:
    """返回默认官方代理支持的地区编码集合，以及是否包含 all 标记。"""
    global _SUPPORTED_CODES_CACHE

    if _SUPPORTED_CODES_CACHE is not None:
        return _SUPPORTED_CODES_CACHE

    codes: Set[str] = set()
    has_all = False
    content = _read_asset_text("area.txt")
    if not content:
        _SUPPORTED_CODES_CACHE = (codes, has_all)
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
        if _AREA_CODE_PATTERN.fullmatch(code):
            codes.add(code)

    _SUPPORTED_CODES_CACHE = (codes, has_all)
    return codes, has_all


def load_area_codes(supported_only: bool = False) -> List[Dict[str, Any]]:
    """读取省市编码树；`supported_only=True` 时按本地 area.txt 过滤。"""
    global _AREA_CODES_CACHE

    if _AREA_CODES_CACHE is None:
        try:
            _AREA_CODES_CACHE = json.loads(_read_asset_text("area_codes_2022.json") or "{}")
        except Exception:
            _AREA_CODES_CACHE = {}

    provinces = _AREA_CODES_CACHE.get("provinces")
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


def _build_local_area_lookup() -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    provinces = load_area_codes(supported_only=False)
    province_lookup: Dict[str, Dict[str, Any]] = {}

    for province in provinces:
        if not isinstance(province, dict):
            continue
        province_code = _normalize_area_code(province.get("code"))
        province_name = str(province.get("name") or "").strip()
        if not province_code or not province_name:
            continue
        province_request_name = _MUNICIPALITY_REQUEST_NAMES.get(province_code, _normalize_province_name(province_name))
        cities = province.get("cities") or []
        if not isinstance(cities, list):
            cities = []
        city_entries: List[Dict[str, Any]] = []
        for city in cities:
            if not isinstance(city, dict):
                continue
            city_code = _normalize_area_code(city.get("code"))
            city_name = str(city.get("name") or "").strip()
            if not city_code or not city_name:
                continue
            request_name = province_request_name if city_name == "市辖区" and province_code in _MUNICIPALITY_REQUEST_NAMES else _normalize_city_name(city_name)
            city_entries.append(
                {
                    "code": city_code,
                    "name": city_name,
                    "normalized_name": _normalize_city_name(request_name),
                    "request_name": request_name,
                    "raw": city,
                }
            )
        province_lookup[_normalize_province_name(province_name)] = {
            "code": province_code,
            "name": province_name,
            "request_name": province_request_name,
            "raw": province,
            "cities": city_entries,
        }

    return provinces, province_lookup


def _download_benefit_area_text() -> str:
    response = http_client.get(
        _BENEFIT_AREA_INFO_URL,
        timeout=_BENEFIT_FETCH_TIMEOUT_SECONDS,
        headers=DEFAULT_HTTP_HEADERS,
        proxies={},
    )
    response.raise_for_status()
    return str(response.text or "")


def _parse_benefit_area_text(content: str) -> Dict[str, Set[str]]:
    provinces: Dict[str, Set[str]] = {}
    current_province = ""

    for raw_line in str(content or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        province_match = _ONLINE_PROVINCE_PATTERN.match(line)
        if province_match:
            current_province = _normalize_province_name(province_match.group("province"))
            provinces.setdefault(current_province, set())
            continue
        city_match = _ONLINE_CITY_PATTERN.match(line)
        if city_match and current_province:
            city_name = _normalize_city_name(city_match.group("city"))
            if city_name:
                provinces.setdefault(current_province, set()).add(city_name)

    return {key: value for key, value in provinces.items() if value}


def _build_benefit_supported_data_from_online() -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    _, province_lookup = _build_local_area_lookup()
    online_supported = _parse_benefit_area_text(_download_benefit_area_text())
    filtered_provinces: List[Dict[str, Any]] = []
    city_code_index: Dict[str, str] = {}

    for normalized_province, online_cities in online_supported.items():
        local_province = province_lookup.get(normalized_province)
        if not local_province:
            continue
        matched_cities: List[Dict[str, Any]] = []
        for city_entry in local_province["cities"]:
            city_normalized = str(city_entry.get("normalized_name") or "")
            if city_normalized in online_cities:
                matched_cities.append(dict(city_entry["raw"]))
                city_code_index[str(city_entry["code"])] = str(city_entry["request_name"])
        if matched_cities:
            filtered_provinces.append({**local_province["raw"], "cities": matched_cities})

    return filtered_provinces, city_code_index


def _build_benefit_supported_data_from_local_fallback() -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    supported_codes, _ = load_supported_area_codes()
    _, province_lookup = _build_local_area_lookup()
    filtered_provinces: List[Dict[str, Any]] = []
    city_code_index: Dict[str, str] = {}

    for province in province_lookup.values():
        matched_cities: List[Dict[str, Any]] = []
        for city_entry in province["cities"]:
            city_code = str(city_entry.get("code") or "")
            if city_code not in supported_codes:
                continue
            matched_cities.append(dict(city_entry["raw"]))
            city_code_index[city_code] = str(city_entry["request_name"])
        if matched_cities:
            filtered_provinces.append({**province["raw"], "cities": matched_cities})

    return filtered_provinces, city_code_index


def _ensure_benefit_cache(force_refresh: bool = False) -> None:
    global _BENEFIT_SUPPORTED_AREAS_CACHE, _BENEFIT_CITY_CODE_INDEX_CACHE

    with _BENEFIT_CACHE_LOCK:
        if (
            not force_refresh
            and _BENEFIT_SUPPORTED_AREAS_CACHE is not None
            and _BENEFIT_CITY_CODE_INDEX_CACHE is not None
        ):
            return
        try:
            supported_areas, city_code_index = _build_benefit_supported_data_from_online()
            if not supported_areas or not city_code_index:
                raise RuntimeError("benefit 在线地区列表为空")
            logging.info("benefit 地区支持列表已从在线 TXT 刷新：省份=%s 城市=%s", len(supported_areas), len(city_code_index))
        except Exception as exc:
            logging.warning("benefit 在线地区查询失败，回退本地地区交集：%s", exc)
            supported_areas, city_code_index = _build_benefit_supported_data_from_local_fallback()
        _BENEFIT_SUPPORTED_AREAS_CACHE = supported_areas
        _BENEFIT_CITY_CODE_INDEX_CACHE = city_code_index


def load_benefit_supported_areas(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """返回 benefit 官方上游支持的地区树，仅保留具体城市。"""
    _ensure_benefit_cache(force_refresh=force_refresh)
    with _BENEFIT_CACHE_LOCK:
        return copy.deepcopy(_BENEFIT_SUPPORTED_AREAS_CACHE or [])


def build_benefit_city_code_index(force_refresh: bool = False) -> Dict[str, str]:
    """返回 benefit 上游地区映射：`城市码 -> 请求城市名`。"""
    _ensure_benefit_cache(force_refresh=force_refresh)
    with _BENEFIT_CACHE_LOCK:
        return dict(_BENEFIT_CITY_CODE_INDEX_CACHE or {})


def resolve_proxy_area_for_source(source: str, area_code: Optional[str]) -> str:
    """按代理源解析地区参数：default 返回地区码，benefit 返回城市名文本。"""
    normalized_code = _normalize_area_code(area_code)
    if not normalized_code:
        return ""
    source_key = str(source or "").strip().lower()
    if source_key == "benefit":
        return str(build_benefit_city_code_index().get(normalized_code) or "")
    return normalized_code



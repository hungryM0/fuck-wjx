"""代理地区数据。"""

from software.network.proxy.areas.service import (
    build_benefit_city_code_index,
    load_area_codes,
    load_benefit_supported_areas,
    load_supported_area_codes,
    resolve_proxy_area_for_source,
)

__all__ = [
    "build_benefit_city_code_index",
    "load_area_codes",
    "load_benefit_supported_areas",
    "load_supported_area_codes",
    "resolve_proxy_area_for_source",
]


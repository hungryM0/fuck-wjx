"""代理配置门面 - 统一读写代理源、自定义 API 与地区设置。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from software.network.proxy.policy.source import (
    get_custom_proxy_api_override,
    get_default_proxy_area_code,
    get_proxy_area_code,
    get_proxy_occupy_minute,
    get_proxy_source,
    normalize_proxy_source,
    set_proxy_api_override,
    set_proxy_area_code,
    set_proxy_source,
)


@dataclass(frozen=True)
class ProxySettings:
    """当前代理配置快照。"""

    source: str
    custom_api_url: str
    area_code: Optional[str]
    default_area_code: str
    occupy_minute: int


def get_proxy_settings() -> ProxySettings:
    """读取当前代理配置。"""
    return ProxySettings(
        source=normalize_proxy_source(get_proxy_source()),
        custom_api_url=get_custom_proxy_api_override(),
        area_code=get_proxy_area_code(),
        default_area_code=get_default_proxy_area_code(),
        occupy_minute=int(get_proxy_occupy_minute() or 1),
    )


def apply_proxy_source_settings(source: str, *, custom_api_url: Optional[str] = None) -> ProxySettings:
    """统一更新代理源与自定义 API 地址。"""
    normalized = normalize_proxy_source(source)
    if normalized == "custom":
        set_proxy_api_override(custom_api_url if custom_api_url else None)
    else:
        set_proxy_api_override(None)
    set_proxy_source(normalized)
    return get_proxy_settings()


def apply_proxy_area_code(area_code: Optional[str]) -> ProxySettings:
    """统一更新地区覆盖。"""
    set_proxy_area_code(area_code)
    return get_proxy_settings()


def apply_custom_proxy_api(custom_api_url: Optional[str]) -> ProxySettings:
    """统一更新自定义代理 API 地址。"""
    set_proxy_api_override(custom_api_url if custom_api_url else None)
    return get_proxy_settings()



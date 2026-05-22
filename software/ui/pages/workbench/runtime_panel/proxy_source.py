"""运行参数页代理源常量。"""

from __future__ import annotations

PROXY_SOURCE_DEFAULT = "default"
PROXY_SOURCE_BENEFIT = "benefit"
PROXY_SOURCE_CUSTOM = "custom"
VALID_PROXY_SOURCES = {
    PROXY_SOURCE_DEFAULT,
    PROXY_SOURCE_BENEFIT,
    PROXY_SOURCE_CUSTOM,
}


def normalize_proxy_source(source: str) -> str:
    normalized = str(source or PROXY_SOURCE_DEFAULT).strip().lower()
    return normalized if normalized in VALID_PROXY_SOURCES else PROXY_SOURCE_DEFAULT

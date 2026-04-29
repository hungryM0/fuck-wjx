"""浏览器 selector、代理与 launch/context 参数拼装。"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from software.app.config import HEADLESS_WINDOW_SIZE, get_proxy_auth
from software.logging.log_utils import log_suppressed_exception
from software.network.proxy.policy.source import PROXY_SOURCE_CUSTOM, get_proxy_source
from software.network.proxy.pool import normalize_proxy_address

_COMMON_BROWSER_SAFE_ARGS = [
    "--disable-gpu",
]
_EDGE_CLEAN_ARGS = [
    "--disable-extensions",
    "--disable-background-networking",
]
_BROWSER_DISCONNECT_MARKERS = (
    "target page, context or browser has been closed",
    "browser has been closed",
    "browser closed",
    "connection closed",
    "not connected",
    "has been disconnected",
)
_PROXY_TUNNEL_ERRORS = (
    "ERR_TUNNEL_CONNECTION_FAILED",
    "ERR_PROXY_CONNECTION_FAILED",
    "ERR_NO_SUPPORTED_PROXIES",
)

__all__ = [
    "_build_context_args",
    "_build_launch_args",
    "_build_selector",
    "_is_browser_disconnected_error",
    "_is_proxy_tunnel_error",
]


def _build_selector(by: str, value: str) -> str:
    if by == "xpath":
        return f"xpath={value}"
    if by == "id":
        if value.startswith("#") or value.startswith("xpath=") or value.startswith("css="):
            return value
        return f"#{value}"
    return value


def _is_proxy_tunnel_error(exc: Exception) -> bool:
    message = str(exc)
    if not message:
        return False
    return any(code in message for code in _PROXY_TUNNEL_ERRORS)


def _is_browser_disconnected_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    if not message:
        return False
    return any(marker in message for marker in _BROWSER_DISCONNECT_MARKERS)


def _parse_proxy_context_args(proxy_address: Optional[str]) -> Dict[str, Any]:
    normalized_proxy = normalize_proxy_address(proxy_address)
    if not normalized_proxy:
        return {}

    proxy_settings: Dict[str, Any] = {"server": normalized_proxy}
    try:
        parsed = urlparse(normalized_proxy)
        if parsed.scheme and parsed.hostname:
            server = f"{parsed.scheme}://{parsed.hostname}"
            if parsed.port:
                server += f":{parsed.port}"
            proxy_settings["server"] = server
        if parsed.username:
            proxy_settings["username"] = parsed.username
        if parsed.password:
            proxy_settings["password"] = parsed.password
    except Exception as exc:
        log_suppressed_exception("browser_driver._parse_proxy_context_args parse proxy", exc, level=logging.WARNING)

    if get_proxy_source() == PROXY_SOURCE_CUSTOM and "username" not in proxy_settings:
        try:
            auth = get_proxy_auth()
            username, password = auth.split(":", 1)
            proxy_settings["username"] = username
            proxy_settings["password"] = password
        except Exception:
            logging.info("代理认证解析失败", exc_info=True)

    return {"proxy": proxy_settings}


def _build_context_args(
    *,
    headless: bool,
    proxy_address: Optional[str],
    user_agent: Optional[str],
) -> Dict[str, Any]:
    context_args: Dict[str, Any] = {}
    context_args.update(_parse_proxy_context_args(proxy_address))
    if user_agent:
        context_args["user_agent"] = user_agent
    if headless and HEADLESS_WINDOW_SIZE:
        try:
            width, height = [int(x) for x in HEADLESS_WINDOW_SIZE.split(",")]
            context_args["viewport"] = {"width": width, "height": height}
        except Exception as exc:
            log_suppressed_exception("browser_driver._build_context_args parse headless size", exc, level=logging.WARNING)
    return context_args


def _build_launch_args(
    *,
    browser_name: str,
    headless: bool,
    window_position: Optional[Tuple[int, int]],
    append_no_proxy: bool,
) -> Dict[str, Any]:
    launch_args: Dict[str, Any] = {"headless": headless, "args": list(_COMMON_BROWSER_SAFE_ARGS)}
    if browser_name == "edge":
        launch_args["channel"] = "msedge"
        launch_args["args"].extend(_EDGE_CLEAN_ARGS)
    elif browser_name == "chrome":
        launch_args["channel"] = "chrome"

    if window_position and not headless:
        x, y = window_position
        launch_args["args"].append(f"--window-position={x},{y}")

    if append_no_proxy:
        launch_args["args"].append("--no-proxy-server")

    return launch_args

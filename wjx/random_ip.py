import logging
import random
import re
import threading
import time
from typing import List, Optional, Dict, Any, Set

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

from .config import (
    DEFAULT_HTTP_HEADERS,
    PROXY_REMOTE_URL,
    PROXY_MAX_PROXIES,
    PROXY_HEALTH_CHECK_URL,
    PROXY_HEALTH_CHECK_TIMEOUT,
)


def _parse_proxy_line(line: str) -> Optional[str]:
    if not line:
        return None
    cleaned = line.strip()
    if not cleaned or cleaned.startswith("#"):
        return None
    if "://" in cleaned:
        return cleaned
    if ":" in cleaned and cleaned.count(":") == 1:
        host, port = cleaned.split(":", 1)
    else:
        parts = re.split(r"[\s,]+", cleaned)
        if len(parts) < 2:
            return None
        host, port = parts[0], parts[1]
    host = host.strip()
    port = port.strip()
    if not host or not port:
        return None
    try:
        int(port)
    except ValueError:
        return None
    return f"{host}:{port}"


def _load_proxy_ip_pool() -> List[str]:
    if requests is None:
        raise RuntimeError("requests 模块不可用，无法从远程获取代理列表")
    proxy_url = PROXY_REMOTE_URL
    try:
        response = requests.get(proxy_url, headers=DEFAULT_HTTP_HEADERS, timeout=12)
        response.raise_for_status()
    except Exception as exc:
        raise OSError(f"获取远程代理列表失败：{exc}") from exc

    try:
        payload = response.json()
    except Exception as exc:
        raise ValueError(f"远程代理接口返回格式错误（期望 JSON）：{exc}") from exc

    proxy_items: List[Dict[str, Any]] = []
    if isinstance(payload, dict):
        error_code = payload.get("code")
        status_code = payload.get("status")
        if isinstance(error_code, str) and error_code.isdigit():
            error_code = int(error_code)
        if isinstance(status_code, str) and status_code.isdigit():
            status_code = int(status_code)
        if not isinstance(error_code, int):
            raise ValueError("远程代理接口缺少 code 字段或格式不正确")
        if error_code != 0:
            message = payload.get("message") or payload.get("msg") or "未知错误"
            status_hint = f"，status={status_code}" if status_code is not None else ""
            raise ValueError(f"远程代理接口返回错误：{message}（code={error_code}{status_hint}）")
        data_section = payload.get("data")
        if isinstance(data_section, dict):
            proxy_items = data_section.get("list") or []
        if not proxy_items:
            proxy_items = payload.get("list") or payload.get("proxies") or []
    if not isinstance(proxy_items, list):
        proxy_items = []

    proxies: List[str] = []
    seen: Set[str] = set()
    for item in proxy_items:
        if not isinstance(item, dict):
            continue
        host = str(item.get("ip") or item.get("host") or "").strip()
        port = str(item.get("port") or "").strip()
        if not host or not port:
            continue
        try:
            int(port)
        except ValueError:
            continue
        expired = item.get("expired")
        if isinstance(expired, str) and expired.isdigit():
            try:
                expired = int(expired)
            except Exception:
                expired = None
        if isinstance(expired, (int, float)):
            now_ms = int(time.time() * 1000)
            if expired <= now_ms:
                continue
        username = str(item.get("account") or item.get("username") or "").strip()
        password = str(item.get("password") or item.get("pwd") or "").strip()
        auth_prefix = f"{username}:{password}@" if username and password else ""
        candidate = f"http://{auth_prefix}{host}:{port}"
        scheme = candidate.split("://", 1)[0].lower()
        if scheme not in ("http", "https"):
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        proxies.append(candidate)
    if not proxies:
        raise ValueError(f"代理列表为空，请检查远程地址：{proxy_url}")
    random.shuffle(proxies)
    if len(proxies) > PROXY_MAX_PROXIES:
        proxies = proxies[:PROXY_MAX_PROXIES]
    return proxies


def _fetch_new_proxy_batch(expected_count: int = 1) -> List[str]:
    try:
        expected = int(expected_count)
    except Exception:
        expected = 1
    expected = max(1, expected)
    proxies: List[str] = []
    # 多尝试几次，尽量拿到足够数量的 IP
    attempts = max(2, expected)
    for _ in range(attempts):
        batch = _load_proxy_ip_pool()
        for proxy in batch:
            if proxy not in proxies:
                proxies.append(proxy)
                if len(proxies) >= expected:
                    break
        if len(proxies) >= expected:
            break
    return proxies


def _proxy_is_responsive(
    proxy_address: str,
    timeout: float = PROXY_HEALTH_CHECK_TIMEOUT,
    stop_signal: Optional[threading.Event] = None,
) -> bool:
    """验证代理是否能在限定时间内连通，可用返回 True。"""
    if stop_signal and stop_signal.is_set():
        return False
    if not proxy_address:
        return True
    if requests is None:
        logging.debug("requests 模块不可用，跳过代理超时验证")
        return True
    normalized = proxy_address.strip()
    if not normalized:
        return False
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    proxies = {"http": normalized, "https": normalized}
    # 减少超时时间到 2 秒，以便更快地响应停止信号
    effective_timeout = min(timeout, 2.0)
    start_ts = time.monotonic()
    try:
        response = requests.get(
            PROXY_HEALTH_CHECK_URL,
            headers=DEFAULT_HTTP_HEADERS,
            proxies=proxies,
            timeout=effective_timeout,
        )
        elapsed = time.monotonic() - start_ts
    except requests.exceptions.Timeout:
        logging.warning(f"代理 {proxy_address} 超过 {effective_timeout} 秒无响应，跳过本次提交")
        return False
    except requests.exceptions.RequestException as exc:
        logging.warning(f"代理 {proxy_address} 验证失败：{exc}")
        return False
    except Exception as exc:
        logging.warning(f"代理 {proxy_address} 验证出现异常：{exc}")
        return False
    if response.status_code >= 400:
        logging.warning(f"代理 {proxy_address} 验证返回状态码 {response.status_code}，跳过本次提交")
        return False
    logging.debug(f"代理 {proxy_address} 验证通过，耗时 {elapsed:.2f} 秒")
    return True


def _normalize_proxy_address(proxy_address: Optional[str]) -> Optional[str]:
    if not proxy_address:
        return None
    normalized = proxy_address.strip()
    if not normalized:
        return None
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    return normalized

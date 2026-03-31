"""随机 IP / 代理管理 - 代理获取主逻辑"""
import json
import logging
import re
import threading
from urllib.parse import parse_qsl, urlsplit
from typing import Any, List, Optional, Set

import software.network.http as http_client
from software.core.task import ProxyLease
from software.network.proxy.session.auth import extract_proxy, format_random_ip_error
from software.app.config import (
    DEFAULT_HTTP_HEADERS,
    PROXY_MAX_PROXIES,
    PROXY_POOL_ORDINARY,
    PROXY_SOURCE_CUSTOM,
    PROXY_SOURCE_DEFAULT,
    PROXY_STATUS_TIMEOUT_SECONDS,
    STATUS_ENDPOINT,
)
from software.logging.log_utils import (
    log_popup_error,
    log_suppressed_exception,
)

# 从 source.py 导入配置管理函数
from software.network.proxy.policy.source import (
    PROXY_SOURCE_BENEFIT,
    PROXY_UPSTREAM_BENEFIT,
    PROXY_UPSTREAM_DEFAULT,
    _normalize_area_code,
    _resolve_default_pool_by_area,
    get_effective_proxy_api_url,
    get_proxy_area_code,
    get_proxy_occupy_minute,
    get_proxy_source,
    get_proxy_upstream,
    has_custom_proxy_api_override,
    is_custom_proxy_source,
    is_official_proxy_source,
)

# 从 pool.py 导入租约和代理池函数
from software.network.proxy.pool.pool import (
    _build_default_proxy_lease,
    _build_default_proxy_leases_from_batch,
    _build_proxy_lease,
    _mask_proxy_for_log,
)

_IP_PORT_RE = re.compile(
    r'(?:https?://)?'
    r'(?:([^\s:@/,]+):([^\s:@/,]+)@)?'
    r'((?:\d{1,3}\.){3}\d{1,3})'
    r':(\d{2,5})'
)

_FATAL_PATTERNS = [
    (r"白名单", "请先添加当前IP到代理商白名单"),
    (r"secret.*密匙错误", "API密钥错误，请检查配置"),
    (r"套餐余量不足", "套餐余量不足，请充值"),
    (r"套餐已过期", "套餐已过期，请续费"),
    (r"套餐被禁用", "套餐已被禁用，请联系代理商"),
    (r"身份未认证", "请先完成实名认证"),
    (r"用户被禁用", "账号已被禁用，请联系代理商"),
]


class AreaProxyQualityError(RuntimeError):
    """地区代理质量差导致无法使用时抛出。"""


class ProxyApiFatalError(RuntimeError):
    """代理API致命错误（需要用户干预）时抛出。"""


# ==================== 状态查询 ====================

def get_status() -> Any:
    response = http_client.get(STATUS_ENDPOINT, timeout=PROXY_STATUS_TIMEOUT_SECONDS, headers=DEFAULT_HTTP_HEADERS, proxies={})
    response.raise_for_status()
    return response.json()


def _format_status_payload(payload: Any) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "未知：返回数据格式异常", "#666666"
    online = payload.get("online", None)
    message = str(payload.get("message") or "").strip()
    if not message:
        message = "系统正常运行中" if online is True else ("系统当前不在线" if online is False else "状态未知")
    color = "#228B22" if online is True else ("#cc0000" if online is False else "#666666")
    prefix = "在线" if online is True else ("离线" if online is False else "未知")
    return f"{prefix}：{message}", color


def format_status_payload(payload: Any) -> tuple[str, str]:
    """公开的状态文案格式化接口。"""
    return _format_status_payload(payload)


# ==================== 代理解析 ====================

def _normalize_expected_proxy_count(expected_count: Any) -> int:
    try:
        parsed = int(expected_count)
    except Exception:
        parsed = 1
    return max(1, min(PROXY_MAX_PROXIES, parsed))


def _normalize_final_upstream(value: Any) -> str:
    upstream = str(value or "").strip().lower()
    if upstream in {PROXY_UPSTREAM_DEFAULT, PROXY_UPSTREAM_BENEFIT}:
        return upstream
    return ""


def _resolve_final_source(final_upstream: str, fallback_source: str) -> str:
    if final_upstream == PROXY_UPSTREAM_BENEFIT:
        return PROXY_SOURCE_BENEFIT
    if final_upstream == PROXY_UPSTREAM_DEFAULT:
        return PROXY_SOURCE_DEFAULT
    return fallback_source


def _extract_proxy_from_string(s: str) -> Optional[str]:
    if not isinstance(s, str):
        return None
    m = _IP_PORT_RE.search(s.strip())
    if not m:
        return None
    user, pwd, ip, port = m.group(1), m.group(2), m.group(3), m.group(4)
    return f"{user}:{pwd}@{ip}:{port}" if user and pwd else f"{ip}:{port}"


def _extract_proxy_from_dict(obj: dict) -> Optional[str]:
    if not isinstance(obj, dict):
        return None
    ip = str(obj.get("ip") or obj.get("IP") or obj.get("host") or "").strip()
    port = str(obj.get("port") or obj.get("Port") or obj.get("PORT") or "").strip()
    if ip and port:
        username = str(obj.get("account") or obj.get("username") or obj.get("user") or "").strip()
        password = str(obj.get("password") or obj.get("pwd") or obj.get("pass") or "").strip()
        return f"{username}:{password}@{ip}:{port}" if username and password else f"{ip}:{port}"
    for v in obj.values():
        if isinstance(v, str):
            proxy = _extract_proxy_from_string(v)
            if proxy:
                return proxy
    return None


def _recursive_find_proxies(data: Any, results: List[str], depth: int = 0) -> None:
    if depth > 10:
        return
    if isinstance(data, dict):
        proxy = _extract_proxy_from_dict(data)
        if proxy:
            results.append(proxy)
            return
        for value in data.values():
            _recursive_find_proxies(value, results, depth + 1)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                proxy = _extract_proxy_from_string(item)
                if proxy:
                    results.append(proxy)
            else:
                _recursive_find_proxies(item, results, depth + 1)
    elif isinstance(data, str):
        proxy = _extract_proxy_from_string(data)
        if proxy:
            results.append(proxy)


def _parse_proxy_payload(text: str) -> List[str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON解析失败: {e}")
    candidates: List[str] = []
    _recursive_find_proxies(data, candidates)
    if not candidates:
        raise ValueError("返回数据中无有效代理地址")
    seen: Set[str] = set()
    unique: List[str] = []
    for addr in candidates:
        if addr not in seen:
            seen.add(addr)
            unique.append(addr)
            logging.info(f"获取到代理: {_mask_proxy_for_log(addr)}")
    return unique


# ==================== 错误检测 ====================

def _is_area_quality_retry_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    return (
        str(payload.get("code")) == "-1"
        and str(payload.get("status")) == "200"
        and str(payload.get("message") or "").strip() == "请重试"
        and payload.get("data") is None
    )


def _handle_area_quality_failure(stop_signal: Optional[threading.Event] = None) -> None:
    log_popup_error("地区代理不可用", "当前地区IP质量差，建议切换其他地区")
    if stop_signal:
        try:
            if not stop_signal.is_set():
                stop_signal.set()
        except Exception as exc:
            log_suppressed_exception("random_ip._handle_area_quality_failure set stop_signal", exc)


def _is_default_batch_extract_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("items"), list)


def _extract_custom_api_error(data: Any) -> Optional[str]:
    """从常见代理商响应中提取明确的致命错误。"""
    if not isinstance(data, dict):
        return None
    code = data.get("code")
    if code == 0:
        return None
    message = str(data.get("message") or "").strip()
    if not message:
        return None
    for pattern, user_msg in _FATAL_PATTERNS:
        if re.search(pattern, message, re.IGNORECASE):
            return user_msg
    return None


# ==================== API 候选和测试 ====================

def _proxy_api_candidates(expected_count: int, proxy_url: Optional[str]) -> List[str]:
    url = proxy_url or get_effective_proxy_api_url()
    if not url:
        raise RuntimeError("自定义代理API地址不能为空，请先在设置中填写API地址")
    if "{num}" in url:
        return [url.format(num=max(1, expected_count))]
    if "num=" in url.lower() or "count=" in url.lower():
        return [url]
    separator = "&" if "?" in url else "?"
    return [f"{url}{separator}num={max(1, expected_count)}", url]


def _extract_minute_from_url(url: str) -> Optional[int]:
    """从URL中提取minute参数"""
    try:
        split = urlsplit(url)
        for key, value in parse_qsl(split.query):
            if key.lower() == "minute":
                return int(value)
    except Exception:
        pass
    return None


def _check_minute_conflict(url: str) -> Optional[str]:
    """检查URL中的minute参数是否与作答时长冲突"""
    minute = _extract_minute_from_url(url)
    if minute is None:
        return "建议在自定义API地址中添加 minute 参数（如 &minute=5）以确保代理时长足够"
    occupy_minute = get_proxy_occupy_minute()
    if minute < occupy_minute:
        return f"代理时长 ({minute}分钟) 小于当前建议值 ({occupy_minute}分钟，已含安全缓冲)，可能导致作答过程中代理失效"
    return None


def test_custom_proxy_api(url: str) -> tuple[bool, str, List[str]]:
    if not url or not url.strip():
        return False, "API地址不能为空", []
    url = url.strip()
    if not (url.lower().startswith("http://") or url.lower().startswith("https://")):
        return False, "API地址必须以 http:// 或 https:// 开头", []
    try:
        resp = http_client.get(url, timeout=10, headers=DEFAULT_HTTP_HEADERS, proxies={})
        resp.raise_for_status()
    except http_client.Timeout:
        return False, "请求超时，请检查网络或API地址", []
    except http_client.ConnectionError:
        return False, "连接失败，请检查API地址是否正确", []
    except http_client.HTTPError as e:
        return False, f"HTTP错误: {e.response.status_code}", []
    except Exception as e:
        return False, f"请求失败: {e}", []

    try:
        data = json.loads(resp.text)
        error = _extract_custom_api_error(data)
        if error:
            return False, error, []
    except Exception:
        pass

    try:
        proxies = _parse_proxy_payload(resp.text)
        if not proxies:
            return False, "未能从返回数据中解析出代理地址", []
        warning = _check_minute_conflict(url)
        return True, warning or "", proxies
    except ValueError as e:
        return False, str(e), []
    except Exception as e:
        return False, f"解析失败: {e}", []


# ==================== 核心获取函数 ====================

def _resolve_official_area_request_value(source: str, area_code: Optional[str]) -> str:
    normalized_area = _normalize_area_code(area_code)
    if not normalized_area:
        return ""
    try:
        from software.network.proxy.areas import resolve_proxy_area_for_source
    except Exception:
        return normalized_area
    try:
        resolved = resolve_proxy_area_for_source(source, normalized_area)
    except Exception as exc:
        log_suppressed_exception("random_ip._resolve_official_area_request_value", exc)
        return normalized_area
    return str(resolved or "").strip()


def _fetch_new_proxy_batch(
    expected_count: int = 1,
    proxy_url: Optional[str] = None,
    notify_on_area_error: bool = True,
    stop_signal: Optional[threading.Event] = None,
) -> List[ProxyLease]:
    expected_count = _normalize_expected_proxy_count(expected_count)
    current_source = get_proxy_source()
    is_custom = is_custom_proxy_source(current_source)
    is_official = is_official_proxy_source(current_source)

    if is_custom:
        if not has_custom_proxy_api_override():
            raise RuntimeError("自定义代理API地址未配置，请在设置中填写API地址")
        proxy_url = get_effective_proxy_api_url()
        logging.info(f"使用自定义代理API: {proxy_url}")

    area_code = get_proxy_area_code()
    has_area = bool(_normalize_area_code(area_code))
    if is_official and not is_custom:
        minute = int(get_proxy_occupy_minute() or 1)
        upstream = get_proxy_upstream(current_source)
        if upstream != "default":
            minute = 1
        pool = _resolve_default_pool_by_area(area_code) or PROXY_POOL_ORDINARY
        area_value = _resolve_official_area_request_value(current_source, area_code)
        fetched: List[ProxyLease] = []
        errors: List[str] = []
        remaining = expected_count
        while remaining > 0:
            try:
                payload = extract_proxy(
                    minute=minute,
                    pool=pool,
                    area=area_value,
                    num=remaining,
                    upstream=upstream,
                )
                final_upstream = _normalize_final_upstream(payload.get("provider"))
                final_source = _resolve_final_source(final_upstream, current_source)
                if _is_default_batch_extract_payload(payload):
                    batch_items = _build_default_proxy_leases_from_batch(payload, source=final_source)
                    fetched.extend(batch_items)
                    logging.info(
                        "随机IP提取成功：请求上游=%s，最终成功上游=%s，返回数量=%s",
                        upstream,
                        final_upstream or "unknown",
                        len(batch_items),
                    )
                    break
                lease = _build_default_proxy_lease(payload, source=final_source)
                if lease is not None:
                    fetched.append(lease)
                    logging.info(
                        "随机IP提取成功：请求上游=%s，最终成功上游=%s",
                        upstream,
                        final_upstream or "unknown",
                    )
                    logging.info("获取到代理: %s", _mask_proxy_for_log(lease.address))
                    remaining = max(0, expected_count - len(fetched))
                    if remaining <= 0:
                        break
                    continue
            except Exception as exc:
                message = format_random_ip_error(exc)
                errors.append(message)
                break
        if not fetched:
            raise RuntimeError(f"获取随机IP失败: {'; '.join(errors) if errors else '无可用接口'}")
        return fetched[:expected_count]

    candidates: List[str] = []
    errors: List[str] = []
    for url in _proxy_api_candidates(expected_count, proxy_url):
        try:
            resp = http_client.get(url, timeout=10, headers=DEFAULT_HTTP_HEADERS, proxies={})
            resp.raise_for_status()

            if is_custom:
                try:
                    payload = json.loads(resp.text)
                    error = _extract_custom_api_error(payload)
                    if error:
                        log_popup_error("代理API错误", error)
                        if stop_signal and not stop_signal.is_set():
                            stop_signal.set()
                        raise ProxyApiFatalError(error)
                except (json.JSONDecodeError, ProxyApiFatalError):
                    raise
                except Exception:
                    pass

            if current_source == PROXY_SOURCE_DEFAULT and has_area:
                try:
                    payload = json.loads(resp.text)
                except Exception:
                    payload = None
                if _is_area_quality_retry_payload(payload):
                    if notify_on_area_error:
                        _handle_area_quality_failure(stop_signal)
                    raise AreaProxyQualityError("当前地区IP质量差，建议切换其他地区")
            parsed = _parse_proxy_payload(resp.text)
            candidates.extend(parsed)
            if candidates:
                break
        except (ProxyApiFatalError, AreaProxyQualityError):
            raise
        except Exception as exc:
            errors.append(str(exc))
            continue
    if not candidates:
        raise RuntimeError(f"获取随机IP失败: {'; '.join(errors) if errors else '无可用接口'}")
    seen: Set[str] = set()
    normalized: List[ProxyLease] = []
    for item in candidates:
        lease = _build_proxy_lease(item, source=current_source or PROXY_SOURCE_CUSTOM)
        addr = lease.address if lease is not None else ""
        if not addr or addr in seen:
            continue
        seen.add(addr)
        normalized.append(lease)
        if len(normalized) >= PROXY_MAX_PROXIES:
            break
    if not normalized:
        raise RuntimeError("随机IP接口返回为空")
    return normalized[:expected_count]


def fetch_proxy_batch(
    expected_count: int = 1,
    *,
    proxy_url: Optional[str] = None,
    notify_on_area_error: bool = True,
    stop_signal: Optional[threading.Event] = None,
) -> List[ProxyLease]:
    """公开的代理批量获取接口。"""
    return _fetch_new_proxy_batch(
        expected_count=expected_count,
        proxy_url=proxy_url,
        notify_on_area_error=notify_on_area_error,
        stop_signal=stop_signal,
    )


__all__ = [
    "AreaProxyQualityError",
    "ProxyApiFatalError",
    "fetch_proxy_batch",
    "format_status_payload",
    "get_status",
    "test_custom_proxy_api",
]



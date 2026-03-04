"""随机 IP / 代理管理 - 获取和切换代理 IP"""
import json
import logging
import random
import re
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any, List, Optional, Set, Tuple

import wjx.network.http_client as http_client
from wjx.utils.app.config import (
    DEFAULT_HTTP_HEADERS,
    PIKACHU_PROXY_API,
    PROXY_HEALTH_CHECK_TIMEOUT,
    PROXY_HEALTH_CHECK_URL,
    PROXY_MAX_PROXIES,
    get_proxy_remote_url,
    STATUS_ENDPOINT,
)
from wjx.utils.logging.log_utils import (
    log_suppressed_exception,
    log_popup_error,
)

STATUS_TIMEOUT_SECONDS = 5
_proxy_api_url_override: Optional[str] = None
_proxy_area_code_override: Optional[str] = None

# 代理源常量
PROXY_SOURCE_DEFAULT = "default"
PROXY_SOURCE_PIKACHU = "pikachu"
PROXY_SOURCE_CUSTOM = "custom"

_current_proxy_source: str = PROXY_SOURCE_DEFAULT
_IP_PORT_RE = re.compile(
    r'(?:https?://)?'
    r'(?:([^\s:@/,]+):([^\s:@/,]+)@)?'
    r'((?:\d{1,3}\.){3}\d{1,3})'
    r':(\d{2,5})'
)
_IPZAN_MINUTE_OPTIONS: Tuple[int, ...] = (1, 3, 5, 10, 15, 30)
_proxy_occupy_minute: int = 1
_IPZAN_POOL_ORDINARY = "ordinary"
_IPZAN_POOL_QUALITY = "quality"
_IPZAN_ORDINARY_PROVINCE_CODES: Set[str] = {
    "110000", "120000", "130000", "140000", "150000", "210000", "220000",
    "230000", "320000", "330000", "340000", "350000", "360000", "370000",
    "410000", "420000", "430000", "440000", "460000", "500000", "510000",
    "610000", "620000", "640000",
}


class AreaProxyQualityError(RuntimeError):
    """地区代理质量差导致无法使用时抛出。"""


def set_proxy_source(source: str) -> None:
    global _current_proxy_source
    _current_proxy_source = source
    logging.debug(f"代理源已切换为: {source}")


def get_proxy_source() -> str:
    return _current_proxy_source


def _to_non_negative_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except Exception:
        return max(0, int(default))
    return max(0, parsed)


def _map_answer_seconds_to_ipzan_minute(total_seconds: int) -> int:
    seconds = max(0, int(total_seconds))
    if seconds < 60:
        return 1
    if seconds <= 180:
        return 3
    if seconds <= 300:
        return 5
    if seconds <= 600:
        return 10
    if seconds <= 900:
        return 15
    return 30


def set_proxy_occupy_minute_by_answer_duration(answer_duration_range_seconds: Optional[Tuple[int, int]]) -> int:
    global _proxy_occupy_minute
    min_seconds = max_seconds = 0
    if isinstance(answer_duration_range_seconds, (list, tuple)):
        if len(answer_duration_range_seconds) >= 1:
            min_seconds = _to_non_negative_int(answer_duration_range_seconds[0], 0)
        max_seconds = _to_non_negative_int(answer_duration_range_seconds[1], min_seconds) if len(answer_duration_range_seconds) >= 2 else min_seconds
    max_seconds = max(max_seconds, min_seconds)
    minute = _map_answer_seconds_to_ipzan_minute(max_seconds)
    if minute not in _IPZAN_MINUTE_OPTIONS:
        minute = 1
    _proxy_occupy_minute = minute
    logging.debug("已根据作答时长更新代理 minute=%s（min=%s秒, max=%s秒）", minute, min_seconds, max_seconds)
    return minute


def _fetch_cn_http_proxies_from_pikachu() -> List[str]:
    try:
        resp = http_client.get(PIKACHU_PROXY_API, timeout=15, headers=DEFAULT_HTTP_HEADERS, proxies={})
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"获取皮卡丘代理失败: {exc}")

    proxy_data = data.get("data", [])
    if isinstance(proxy_data, dict):
        proxy_data = proxy_data.get("list", [])
    if not isinstance(proxy_data, list):
        proxy_data = []

    cn_http_proxies: List[str] = []
    for proxy in proxy_data:
        if not isinstance(proxy, dict):
            continue
        if proxy.get("country") == "CN" and "http" in str(proxy.get("protocol", "")).lower():
            ip = proxy.get("ip", "")
            port = proxy.get("port", "")
            if ip and port:
                username = str(proxy.get("account") or proxy.get("username") or "").strip()
                password = str(proxy.get("password") or proxy.get("pwd") or "").strip()
                addr = f"http://{username}:{password}@{ip}:{port}" if username and password else f"http://{ip}:{port}"
                cn_http_proxies.append(addr)

    if not cn_http_proxies:
        logging.warning("皮卡丘代理站未找到中国大陆 HTTP 代理")
    else:
        logging.info(f"从皮卡丘代理站获取到 {len(cn_http_proxies)} 个中国大陆 HTTP 代理")
    return cn_http_proxies


def _validate_proxy_api_url(api_url: Optional[str]) -> str:
    try:
        cleaned = str(api_url or "").strip()
    except Exception:
        cleaned = ""
    if not cleaned:
        return ""
    if not (cleaned.lower().startswith("http://") or cleaned.lower().startswith("https://")):
        raise ValueError("随机IP提取接口必须以 http:// 或 https:// 开头")
    return cleaned


def _normalize_area_code(area_code: Optional[str]) -> str:
    try:
        cleaned = str(area_code or "").strip()
    except Exception:
        cleaned = ""
    if not cleaned or not cleaned.isdigit() or len(cleaned) != 6:
        return ""
    return cleaned


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


def _apply_query_param(url: str, param_name: str, param_value: str, insert_after: Optional[str] = None) -> str:
    """通用的 URL 查询参数操作函数"""
    try:
        split = urlsplit(url)
    except Exception:
        return url
    query_items = [(k, v) for k, v in parse_qsl(split.query, keep_blank_values=True) if k.lower() != param_name.lower()]

    if insert_after:
        insert_at = len(query_items)
        for idx, (key, _) in enumerate(query_items):
            if str(key).lower() == insert_after.lower():
                insert_at = idx + 1
                break
        query_items.insert(insert_at, (param_name, param_value))
    else:
        query_items.append((param_name, param_value))

    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query_items, doseq=True), split.fragment))


def _apply_area_to_proxy_url(url: str, area_code: Optional[str]) -> str:
    if area_code is None:
        return url
    normalized_area = _normalize_area_code(area_code)
    if not normalized_area:
        return url
    return _apply_query_param(url, "area", normalized_area, insert_after="format")


def _is_province_level_area_code(area_code: str) -> bool:
    return bool(area_code) and len(area_code) == 6 and area_code.isdigit() and area_code.endswith("0000")


def _resolve_ipzan_pool_by_area(area_code: Optional[str]) -> Optional[str]:
    normalized_area = _normalize_area_code(area_code)
    if not normalized_area:
        return None
    if _is_province_level_area_code(normalized_area) and normalized_area in _IPZAN_ORDINARY_PROVINCE_CODES:
        return _IPZAN_POOL_ORDINARY
    return _IPZAN_POOL_QUALITY


def _is_ipzan_core_extract_url(url: str) -> bool:
    try:
        split = urlsplit(url)
    except Exception:
        return False
    return str(split.netloc or "").lower().endswith("ipzan.com") and "core-extract" in str(split.path or "").lower()


def _apply_minute_to_proxy_url(url: str, minute: int) -> str:
    if not _is_ipzan_core_extract_url(url):
        return url
    safe_minute = int(minute) if int(minute) in _IPZAN_MINUTE_OPTIONS else 1
    return _apply_query_param(url, "minute", str(safe_minute))


def _apply_pool_to_proxy_url(url: str, pool: Optional[str]) -> str:
    if not pool or not _is_ipzan_core_extract_url(url):
        return url
    return _apply_query_param(url, "pool", pool)


def get_default_proxy_area_code() -> str:
    url = get_proxy_remote_url().strip()
    if not url:
        return ""
    try:
        split = urlsplit(url)
    except Exception:
        return ""
    for key, value in parse_qsl(split.query, keep_blank_values=True):
        if key.lower() == "area":
            return _normalize_area_code(value)
    return ""


def get_effective_proxy_api_url() -> str:
    override = (_proxy_api_url_override or "").strip()
    url = override or get_proxy_remote_url()
    if get_proxy_source() != PROXY_SOURCE_DEFAULT:
        return url
    url = _apply_area_to_proxy_url(url, _proxy_area_code_override)
    pool = _resolve_ipzan_pool_by_area(_proxy_area_code_override)
    url = _apply_pool_to_proxy_url(url, pool)
    return _apply_minute_to_proxy_url(url, _proxy_occupy_minute)


def is_custom_proxy_api_active() -> bool:
    if _current_proxy_source != PROXY_SOURCE_DEFAULT:
        return True
    return bool((_proxy_api_url_override or "").strip())


def get_proxy_area_code() -> Optional[str]:
    return _proxy_area_code_override


def set_proxy_area_code(area_code: Optional[str]) -> Optional[str]:
    global _proxy_area_code_override
    if area_code is None:
        _proxy_area_code_override = None
        return None
    _proxy_area_code_override = _normalize_area_code(area_code)
    return _proxy_area_code_override


def set_proxy_api_override(api_url: Optional[str]) -> str:
    global _proxy_api_url_override
    cleaned = _validate_proxy_api_url(api_url)
    _proxy_api_url_override = cleaned or None
    return get_effective_proxy_api_url()


def get_status() -> Any:
    response = http_client.get(STATUS_ENDPOINT, timeout=STATUS_TIMEOUT_SECONDS, headers=DEFAULT_HTTP_HEADERS, proxies={})
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


def _proxy_api_candidates(expected_count: int, proxy_url: Optional[str]) -> List[str]:
    url = proxy_url or get_effective_proxy_api_url()
    if get_proxy_source() == PROXY_SOURCE_DEFAULT:
        url = _apply_minute_to_proxy_url(url, _proxy_occupy_minute)
    if not url:
        raise RuntimeError("随机IP接口未配置，请先在界面中填写或在 .env 中设置 RANDOM_IP_API_URL")
    if "{num}" in url:
        return [url.format(num=max(1, expected_count))]
    if "num=" in url.lower() or "count=" in url.lower():
        return [url]
    separator = "&" if "?" in url else "?"
    return [f"{url}{separator}num={max(1, expected_count)}", url]


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


def test_custom_proxy_api(url: str) -> tuple[bool, str, List[str]]:
    if not url or not url.strip():
        return False, "API地址不能为空", []
    url = url.strip()
    if not (url.lower().startswith("http://") or url.lower().startswith("https://")):
        return False, "API地址必须以 http:// 或 https:// 开头", []
    try:
        resp = http_client.get(url, timeout=10, headers=DEFAULT_HTTP_HEADERS, proxies={})
        resp.raise_for_status()
    except http_client.exceptions.Timeout:
        return False, "请求超时，请检查网络或API地址", []
    except http_client.exceptions.ConnectionError:
        return False, "连接失败，请检查API地址是否正确", []
    except http_client.exceptions.HTTPError as e:
        return False, f"HTTP错误: {e.response.status_code}", []
    except Exception as e:
        return False, f"请求失败: {e}", []
    try:
        proxies = _parse_proxy_payload(resp.text)
        if not proxies:
            return False, "未能从返回数据中解析出代理地址", []
        return True, "", proxies
    except ValueError as e:
        return False, str(e), []
    except Exception as e:
        return False, f"解析失败: {e}", []


def _normalize_proxy_address(proxy_address: Optional[str]) -> Optional[str]:
    if not proxy_address:
        return None
    normalized = proxy_address.strip()
    if not normalized:
        return None
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    return normalized


def _format_host_port(hostname: str, port: Optional[int]) -> str:
    if not hostname:
        return ""
    if port is None:
        return hostname
    if ":" in hostname and not hostname.startswith("["):
        return f"[{hostname}]:{port}"
    return f"{hostname}:{port}"


def _mask_proxy_for_log(proxy_address: Optional[str]) -> str:
    if not proxy_address:
        return ""
    text = str(proxy_address).strip()
    if not text:
        return ""
    if get_proxy_source() != PROXY_SOURCE_DEFAULT:
        return text
    candidate = text if "://" in text else f"http://{text}"
    try:
        parsed = urlsplit(candidate)
        host_port = _format_host_port(parsed.hostname or "", parsed.port)
        if host_port:
            return host_port
    except Exception as exc:
        log_suppressed_exception("random_ip._mask_proxy_for_log parse proxy", exc)
    raw = text
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    raw = raw.split("/", 1)[0]
    if "@" in raw:
        raw = raw.split("@", 1)[1]
    return raw


def _proxy_is_responsive(proxy_address: str, skip_for_default: bool = True) -> bool:
    masked_proxy = _mask_proxy_for_log(proxy_address)
    if skip_for_default and get_proxy_source() == PROXY_SOURCE_DEFAULT:
        logging.debug(f"默认代理源，跳过健康检查: {masked_proxy}")
        return True
    proxy_address = _normalize_proxy_address(proxy_address) or ""
    if not proxy_address:
        return False
    proxies = {"http": proxy_address, "https": proxy_address}
    try:
        start = time.perf_counter()
        response = http_client.get(PROXY_HEALTH_CHECK_URL, proxies=proxies, timeout=PROXY_HEALTH_CHECK_TIMEOUT)
        elapsed = time.perf_counter() - start
    except Exception as exc:
        logging.debug(f"代理 {masked_proxy} 验证失败: {exc}")
        return False
    if response.status_code >= 400:
        logging.warning(f"代理 {masked_proxy} 返回状态码 {response.status_code}")
        return False
    logging.debug(f"代理 {masked_proxy} 验证通过，耗时 {elapsed:.2f}s")
    return True


def _proxy_is_responsive_fast(proxy_address: str) -> bool:
    proxy_address = _normalize_proxy_address(proxy_address) or ""
    if not proxy_address:
        return False
    proxies = {"http": proxy_address, "https": proxy_address}
    try:
        response = http_client.get(PROXY_HEALTH_CHECK_URL, proxies=proxies, timeout=3)
        return response.status_code < 400
    except Exception:
        return False


def _fetch_new_proxy_batch(
    expected_count: int = 1,
    proxy_url: Optional[str] = None,
    notify_on_area_error: bool = True,
    stop_signal: Optional[threading.Event] = None,
) -> List[str]:
    current_source = get_proxy_source()
    is_custom = current_source == PROXY_SOURCE_CUSTOM or is_custom_proxy_api_active()

    if current_source == PROXY_SOURCE_PIKACHU:
        try:
            all_proxies = _fetch_cn_http_proxies_from_pikachu()
            if not all_proxies:
                raise RuntimeError("皮卡丘代理站未返回任何中国大陆 HTTP 代理")
            random.shuffle(all_proxies)
            max_check = min(10, len(all_proxies))
            valid_proxies: List[str] = []
            for i, proxy in enumerate(all_proxies[:max_check]):
                if len(valid_proxies) >= expected_count:
                    break
                logging.info(f"正在验证代理 ({i+1}/{max_check}): {proxy}")
                if _proxy_is_responsive_fast(proxy):
                    valid_proxies.append(proxy)
                    logging.info(f"代理可用: {proxy}")
                else:
                    logging.info(f"代理不可用: {proxy}")
            if not valid_proxies:
                raise RuntimeError(f"已验证{max_check}个代理均不可用，请稍后重试或切换代理源")
            return valid_proxies
        except Exception as exc:
            raise RuntimeError(f"获取皮卡丘代理失败: {exc}")

    if is_custom:
        if not is_custom_proxy_api_active():
            raise RuntimeError("自定义代理API地址未配置，请在设置中填写API地址")
        proxy_url = _proxy_api_url_override
        logging.info(f"使用自定义代理API: {proxy_url}")

    candidates: List[str] = []
    errors: List[str] = []
    area_code = get_proxy_area_code()
    has_area = bool(_normalize_area_code(area_code))
    for url in _proxy_api_candidates(expected_count, proxy_url):
        try:
            resp = http_client.get(url, timeout=10, headers=DEFAULT_HTTP_HEADERS, proxies={})
            resp.raise_for_status()
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
        except Exception as exc:
            errors.append(str(exc))
            continue
    if not candidates:
        raise RuntimeError(f"获取随机IP失败: {'; '.join(errors) if errors else '无可用接口'}")
    seen: Set[str] = set()
    normalized: List[str] = []
    for item in candidates:
        addr = _normalize_proxy_address(item)
        if not addr or addr in seen:
            continue
        seen.add(addr)
        normalized.append(addr)
        if len(normalized) >= PROXY_MAX_PROXIES:
            break
    if not normalized:
        raise RuntimeError("随机IP接口返回为空")
    return normalized[: max(1, expected_count)]


# 向后兼容重新导出
from .quota import get_random_ip_limit, get_random_ip_counter_snapshot_local, normalize_random_ip_enabled_value  # noqa: F401
from .gui_bridge import (  # noqa: F401
    confirm_random_ip_usage,
    on_random_ip_toggle,
    ensure_random_ip_ready,
    refresh_ip_counter_display,
    handle_random_ip_submission,
    show_card_validation_dialog,
)

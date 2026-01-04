import json
import logging
import os
import random
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

from wjx.utils.config import (
    DEFAULT_HTTP_HEADERS,
    PROXY_REMOTE_URL,
    PROXY_MAX_PROXIES,
    PROXY_HEALTH_CHECK_URL,
    PROXY_HEALTH_CHECK_TIMEOUT,
)
from wjx.utils.log_utils import (
    log_popup_confirm,
    log_popup_error,
    log_popup_info,
    log_popup_warning,
)
from wjx.utils.registry_manager import RegistryManager

_DEFAULT_RANDOM_IP_FREE_LIMIT = 20
_PREMIUM_RANDOM_IP_LIMIT = 400
CARD_VALIDATION_ENDPOINT = "https://hungrym0.top/password.txt"
STATUS_ENDPOINT = "https://wjx.hungrym0.top/status"
STATUS_TIMEOUT_SECONDS = 5
_quota_limit_dialog_shown = False
_proxy_api_url_override: Optional[str] = None
_CUSTOM_PROXY_CONFIG_FILENAME = "custom_ip.json"

# 代理源常量
PROXY_SOURCE_DEFAULT = "default"  # 默认代理源
PROXY_SOURCE_PIKACHU = "pikachu"  # 皮卡丘代理站

PIKACHU_PROXY_API = "https://raw.githubusercontent.com/CharlesPikachu/freeproxy/master/proxies.json"

# 当前选择的代理源
_current_proxy_source: str = PROXY_SOURCE_DEFAULT


def set_proxy_source(source: str) -> None:
    """设置代理源"""
    global _current_proxy_source
    _current_proxy_source = source
    logging.info(f"代理源已切换为: {source}")


def get_proxy_source() -> str:
    """获取当前代理源"""
    return _current_proxy_source


def _fetch_cn_http_proxies_from_pikachu() -> List[str]:
    """从皮卡丘代理站获取中国大陆 HTTP 代理"""
    if not requests:
        raise RuntimeError("缺少 requests 模块，无法获取代理")
    
    try:
        resp = requests.get(PIKACHU_PROXY_API, timeout=15, headers=DEFAULT_HTTP_HEADERS)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logging.error(f"从皮卡丘代理站获取代理失败: {exc}")
        raise RuntimeError(f"获取皮卡丘代理失败: {exc}")
    
    cn_http_proxies: List[str] = []
    
    # 增强解析：支持多种格式
    proxy_data = data.get("data", [])
    if isinstance(proxy_data, dict):
        # 如果 data 是 dict，尝试获取 list 字段
        proxy_data = proxy_data.get("list", [])
    if not isinstance(proxy_data, list):
        proxy_data = []
    
    for proxy in proxy_data:
        if not isinstance(proxy, dict):
            continue
        # 筛选：国家是 CN 且协议包含 Http
        country = proxy.get("country", "")
        protocol = proxy.get("protocol", "")
        
        if country == "CN" and "Http" in protocol:
            ip = proxy.get("ip", "")
            port = proxy.get("port", "")
            if ip and port:
                # 处理认证信息
                username = str(proxy.get("account") or proxy.get("username") or "").strip()
                password = str(proxy.get("password") or proxy.get("pwd") or "").strip()
                if username and password:
                    addr = f"http://{username}:{password}@{ip}:{port}"
                else:
                    addr = f"http://{ip}:{port}"
                cn_http_proxies.append(addr)
    
    if not cn_http_proxies:
        logging.warning("皮卡丘代理站未找到中国大陆 HTTP 代理")
    else:
        logging.info(f"从皮卡丘代理站获取到 {len(cn_http_proxies)} 个中国大陆 HTTP 代理")
    
    return cn_http_proxies


def get_random_ip_limit() -> int:
    """Read quota from registry with sane defaults."""
    try:
        limit = RegistryManager.read_quota_limit(_DEFAULT_RANDOM_IP_FREE_LIMIT)  # type: ignore[attr-defined]
        limit = int(limit)
        if limit > 0:
            return limit
    except Exception:
        pass
    return _DEFAULT_RANDOM_IP_FREE_LIMIT


def _validate_proxy_api_url(api_url: Optional[str]) -> str:
    try:
        cleaned = str(api_url or "").strip()
    except Exception:
        cleaned = ""
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        raise ValueError("随机IP提取接口必须以 http:// 或 https:// 开头")
    return cleaned


def get_effective_proxy_api_url() -> str:
    override = (_proxy_api_url_override or "").strip()
    return override or PROXY_REMOTE_URL


def is_custom_proxy_api_active() -> bool:
    return bool((_proxy_api_url_override or "").strip())


def set_proxy_api_override(api_url: Optional[str]) -> str:
    global _proxy_api_url_override
    cleaned = _validate_proxy_api_url(api_url)
    _proxy_api_url_override = cleaned or None
    return get_effective_proxy_api_url()


def _get_runtime_directory(base_dir: Optional[str] = None) -> str:
    import os
    import sys

    if base_dir:
        return os.fspath(base_dir)
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    return parent_dir or current_dir


def get_custom_proxy_api_config_path(base_dir: Optional[str] = None) -> str:
    runtime_dir = _get_runtime_directory(base_dir)
    return os.path.join(runtime_dir, _CUSTOM_PROXY_CONFIG_FILENAME)


def _extract_custom_proxy_api(data: Any) -> str:
    if isinstance(data, dict):
        raw = data.get("random_proxy_api") or data.get("api") or data.get("url")
    else:
        raw = data
    try:
        return str(raw).strip()
    except Exception:
        return ""


def load_custom_proxy_api_config(
    config_path: Optional[str] = None,
    base_dir: Optional[str] = None,
) -> str:
    path = os.fspath(config_path) if config_path else get_custom_proxy_api_config_path(base_dir)
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except FileNotFoundError:
        return ""
    except Exception as exc:
        logging.error(f"加载自定义随机IP接口失败: {exc}")
        return ""
    api_value = _extract_custom_proxy_api(data)
    cleaned_api = _validate_proxy_api_url(api_value)
    set_proxy_api_override(cleaned_api)
    return cleaned_api


def save_custom_proxy_api_config(
    api_url: Optional[str],
    config_path: Optional[str] = None,
    base_dir: Optional[str] = None,
) -> str:
    path = os.fspath(config_path) if config_path else get_custom_proxy_api_config_path(base_dir)
    cleaned = _validate_proxy_api_url(api_url)
    if not cleaned:
        return reset_custom_proxy_api_config(config_path=path)
    effective = set_proxy_api_override(cleaned)
    payload = {"random_proxy_api": cleaned}
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    return effective


def reset_custom_proxy_api_config(
    config_path: Optional[str] = None,
    base_dir: Optional[str] = None,
) -> str:
    path = os.fspath(config_path) if config_path else get_custom_proxy_api_config_path(base_dir)
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        logging.debug("删除自定义随机IP配置失败", exc_info=True)
    return set_proxy_api_override(None)


def get_status() -> Any:
    """Fetch developer status endpoint."""
    if requests is None:
        raise RuntimeError("requests 模块未安装，无法获取在线状态")
    response = requests.get(STATUS_ENDPOINT, timeout=STATUS_TIMEOUT_SECONDS, headers=DEFAULT_HTTP_HEADERS)
    response.raise_for_status()
    return response.json()


def _format_status_payload(payload: Any) -> tuple[str, str]:
    """Format online status payload into (text, color)."""
    if not isinstance(payload, dict):
        return "作者当前在线状态：返回数据格式异常", "#cc0000"
    online = payload.get("online", None)
    online_text = "在线" if online is True else ("离线" if online is False else "未知")
    color = "#228B22" if online is True else ("#cc0000" if online is False else "#666666")
    return f"作者当前在线状态：{online_text}", color


def _proxy_api_candidates(expected_count: int, proxy_url: Optional[str]) -> List[str]:
    url = proxy_url or get_effective_proxy_api_url()
    if not url:
        raise RuntimeError("随机IP接口未配置，请先在界面中填写或在 .env 中设置 RANDOM_IP_API_URL")
    if "{num}" in url:
        return [url.format(num=max(1, expected_count))]
    if "num=" in url.lower() or "count=" in url.lower():
        return [url]
    # 兜底：尝试附加 num 参数
    separator = "&" if "?" in url else "?"
    return [f"{url}{separator}num={max(1, expected_count)}", url]


def _parse_proxy_payload(text: str) -> List[str]:
    # JSON payload
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            candidates: List[str] = []
            
            # 处理嵌套结构：data.data.list (如 {"code":0, "data":{"list":[{"ip":"x.x.x.x","port":"8080"}]}})
            data_section = data.get("data")
            if isinstance(data_section, dict):
                nested_list = data_section.get("list")
                if isinstance(nested_list, list):
                    for item in nested_list:
                        if isinstance(item, dict):
                            ip = str(item.get("ip") or item.get("host") or "").strip()
                            port = str(item.get("port") or "").strip()
                            if ip and port:
                                # 处理认证信息
                                username = str(item.get("account") or item.get("username") or "").strip()
                                password = str(item.get("password") or item.get("pwd") or "").strip()
                                if username and password:
                                    candidates.append(f"http://{username}:{password}@{ip}:{port}")
                                else:
                                    candidates.append(f"{ip}:{port}")
                    if candidates:
                        return candidates
            
            # 原有逻辑：处理其他格式
            for key in ("data", "list", "proxy", "proxies"):
                value = data.get(key)
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            candidates.append(item.strip())
                        elif isinstance(item, dict):
                            for k in ("proxy", "ip", "addr", "address"):
                                raw = item.get(k)
                                if raw:
                                    candidates.append(str(raw).strip())
                    if candidates:
                        return candidates
                elif isinstance(value, str):
                    return [value.strip()]
            if "proxy" in data and isinstance(data["proxy"], str):
                return [data["proxy"].strip()]
        elif isinstance(data, list):
            return [str(item).strip() for item in data if str(item).strip()]
    except Exception:
        pass
    # Plain text lines
    lines = [line.strip() for line in re.split(r"[\r\n,]+", text) if line.strip()]
    return lines


def _normalize_proxy_address(proxy_address: Optional[str]) -> Optional[str]:
    if not proxy_address:
        return None
    normalized = proxy_address.strip()
    if not normalized:
        return None
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    return normalized


def _proxy_is_responsive(proxy_address: str) -> bool:
    if not requests:
        logging.warning("requests 模块未安装，无法检测代理可用性")
        return False
    proxy_address = _normalize_proxy_address(proxy_address) or ""
    if not proxy_address:
        return False
    proxies = {"http": proxy_address, "https": proxy_address}
    try:
        start = time.perf_counter()
        response = requests.get(PROXY_HEALTH_CHECK_URL, proxies=proxies, timeout=PROXY_HEALTH_CHECK_TIMEOUT)
        elapsed = time.perf_counter() - start
    except Exception as exc:
        logging.debug(f"代理 {proxy_address} 验证失败: {exc}")
        return False
    if response.status_code >= 400:
        logging.warning(f"代理 {proxy_address} 返回状态码 {response.status_code}")
        return False
    logging.debug(f"代理 {proxy_address} 验证通过，耗时 {elapsed:.2f}s")
    return True


def _fetch_new_proxy_batch(expected_count: int = 1, proxy_url: Optional[str] = None) -> List[str]:
    """Fetch a batch of proxy addresses."""
    if not requests:
        raise RuntimeError("缺少 requests 模块，无法获取随机IP")
    
    # 根据代理源选择不同的获取方式
    current_source = get_proxy_source()
    
    if current_source == PROXY_SOURCE_PIKACHU:
        # 使用皮卡丘代理站
        try:
            all_proxies = _fetch_cn_http_proxies_from_pikachu()
            if not all_proxies:
                raise RuntimeError("皮卡丘代理站未返回任何中国大陆 HTTP 代理")
            # 随机选择指定数量的代理
            count = min(expected_count, len(all_proxies))
            selected = random.sample(all_proxies, count)
            return selected
        except Exception as exc:
            logging.error(f"从皮卡丘代理站获取代理失败: {exc}")
            raise RuntimeError(f"获取皮卡丘代理失败: {exc}")
    
    # 默认代理源：使用原有逻辑
    candidates: List[str] = []
    errors: List[str] = []
    for url in _proxy_api_candidates(expected_count, proxy_url):
        try:
            resp = requests.get(url, timeout=10, headers=DEFAULT_HTTP_HEADERS)
            resp.raise_for_status()
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


def _invoke_popup(gui: Any, kind: str, title: str, message: str) -> Any:
    """Dispatch popup requests to the GUI if it exposes explicit hooks; otherwise fall back to global handlers."""
    gui_handler = None
    if gui is not None:
        gui_handler = getattr(gui, f"_log_popup_{kind}", None)
    if callable(gui_handler):
        try:
            return gui_handler(title, message)
        except Exception:
            logging.debug("GUI popup handler failed; falling back to global handler", exc_info=True)

    popup_map = {
        "info": log_popup_info,
        "warning": log_popup_warning,
        "error": log_popup_error,
        "confirm": log_popup_confirm,
    }
    handler = popup_map.get(kind)
    if handler:
        return handler(title, message)
    return None


def _set_random_ip_enabled(gui: Any, enabled: bool):
    if gui is None:
        return
    var = getattr(gui, "random_ip_enabled_var", None)
    if var and hasattr(var, "set"):
        try:
            var.set(bool(enabled))
        except Exception:
            logging.debug("无法更新随机IP开关状态", exc_info=True)


def _schedule_on_gui_thread(gui: Any, callback: Callable[[], None]):
    if gui is None:
        callback()
        return
    dispatcher = getattr(gui, "_post_to_ui_thread", None)
    if callable(dispatcher):
        try:
            dispatcher(callback)
            return
        except Exception:
            logging.debug("派发到 GUI 线程失败", exc_info=True)
    try:
        callback()
    except Exception:
        logging.debug("执行回调失败", exc_info=True)


def reset_quota_limit_dialog_flag():
    global _quota_limit_dialog_shown
    _quota_limit_dialog_shown = False


def confirm_random_ip_usage(gui: Any) -> bool:
    notice = (
        "启用随机IP提交前请确认：\n\n"
        "1) 代理来源于网络，确认启用视为已知悉风险并自愿承担后果；\n"
        "2) 禁止用于污染他人问卷数据，否则可能被封禁或承担法律责任；\n"
        "3) 随机IP维护成本高昂，如需大量使用需要付费。\n\n"
        "是否继续启用随机IP提交？"
    )
    confirmed = bool(_invoke_popup(gui, "confirm", "随机IP使用声明", notice))
    if confirmed and gui is not None:
        setattr(gui, "_random_ip_disclaimer_ack", True)
    return confirmed


def on_random_ip_toggle(gui: Any):
    if gui is None:
        return
    var = getattr(gui, "random_ip_enabled_var", None)
    enabled = bool(var.get() if var and hasattr(var, "get") else False)
    if not enabled:
        return
    if not RegistryManager.is_quota_unlimited():
        count = RegistryManager.read_submit_count()
        limit = max(1, get_random_ip_limit())
        if count >= limit:
            _invoke_popup(gui, "warning", "提示", f"随机IP已达{limit}份限制，请验证卡密后再启用。")
            _set_random_ip_enabled(gui, False)
            return
    if confirm_random_ip_usage(gui):
        return
    _set_random_ip_enabled(gui, False)


def ensure_random_ip_ready(gui: Any) -> bool:
    if getattr(gui, "_random_ip_disclaimer_ack", False):
        return True
    if confirm_random_ip_usage(gui):
        return True
    _set_random_ip_enabled(gui, False)
    _invoke_popup(gui, "info", "已取消随机IP提交", "未同意免责声明，已禁用随机IP提交。")
    return False


def refresh_ip_counter_display(gui: Any):
    """Notify GUI about current random IP counter."""
    if gui is None:
        return
    handler = getattr(gui, "update_random_ip_counter", None)
    if not callable(handler):
        return
    limit = max(1, get_random_ip_limit())
    count = RegistryManager.read_submit_count()
    handler(count, limit, RegistryManager.is_quota_unlimited(), is_custom_proxy_api_active())


def reset_ip_counter(gui: Any = None):
    RegistryManager.reset_submit_count()
    refresh_ip_counter_display(gui)


def _validate_card(card_code: str) -> bool:
    if not card_code:
        logging.warning("卡密为空")
        return False
    if requests is None:
        logging.warning("requests 模块未安装，无法验证卡密")
        return False
    code = card_code.strip()
    try:
        response = requests.get(CARD_VALIDATION_ENDPOINT, timeout=10, headers=DEFAULT_HTTP_HEADERS)
        response.raise_for_status()
        valid_cards = {line.strip() for line in response.text.strip().split("\n") if line.strip()}
        if code in valid_cards:
            display = f"{code[:4]}***{code[-4:]}" if len(code) > 8 else "***"
            logging.info(f"卡密 {display} 验证通过")
            return True
        logging.warning("卡密验证失败：输入的卡密不在有效列表中")
        return False
    except Exception as exc:
        logging.error(f"卡密验证失败: {exc}")
        return False


def show_card_validation_dialog(gui: Any = None) -> bool:
    """Simplified card validation flow: ask user to输入卡密，验证通过后解除额度。"""
    prompt = (
        "随机IP额度已用尽。\n\n"
        "如已获取卡密，请输入卡密以解锁大额额度；否则可选择取消并继续使用自定义代理接口。"
    )
    if not _invoke_popup(gui, "confirm", "随机IP额度", prompt):
        return False
    code_getter = getattr(gui, "request_card_code", None)
    if callable(code_getter):
        card_code = code_getter()
    else:
        # 无 GUI 交互时直接失败
        log_popup_warning("需要卡密", "请在界面中输入卡密解锁随机IP额度")
        return False
    if _validate_card(str(card_code) if card_code else ""):
        RegistryManager.set_quota_unlimited(True)
        RegistryManager.reset_submit_count()
        _invoke_popup(gui, "info", "验证成功", "卡密验证通过，已解锁随机IP提交额度。")
        return True
    _invoke_popup(gui, "error", "验证失败", "卡密验证失败，请检查后重试。")
    return False


def _disable_random_ip_and_show_dialog(gui: Any):
    global _quota_limit_dialog_shown

    def _action():
        global _quota_limit_dialog_shown
        if _quota_limit_dialog_shown:
            return
        _quota_limit_dialog_shown = True
        _set_random_ip_enabled(gui, False)
        show_card_validation_dialog(gui)

    _schedule_on_gui_thread(gui, _action)


def handle_random_ip_submission(gui: Any, stop_signal: Optional[threading.Event]):
    if RegistryManager.is_quota_unlimited():
        return
    limit = max(1, get_random_ip_limit())
    ip_count = RegistryManager.increment_submit_count()
    logging.info(f"随机IP提交计数: {ip_count}/{limit}")
    try:
        _schedule_on_gui_thread(gui, lambda: refresh_ip_counter_display(gui))
    except Exception:
        pass
    if ip_count >= limit:
        logging.warning(f"随机IP提交已达{limit}份，停止任务并弹出卡密验证窗口")
        if stop_signal:
            stop_signal.set()
        _disable_random_ip_and_show_dialog(gui)


def normalize_random_ip_enabled_value(desired_enabled: bool) -> bool:
    if not desired_enabled:
        return False
    if RegistryManager.is_quota_unlimited():
        return True
    limit = max(1, get_random_ip_limit())
    count = RegistryManager.read_submit_count()
    if count >= limit:
        logging.warning(f"配置中启用了随机IP，但已达到{limit}份限制，已禁用此选项")
        return False
    return True

import json
import logging
import os
import random
import re
import sys
import threading
import time
from typing import List, Optional, Dict, Any, Set, Callable

import tkinter as tk
from tkinter import ttk

try:
    import winsound
except ImportError:  # pragma: no cover
    winsound = None

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
from .log_utils import log_popup_info, log_popup_error, log_popup_warning, log_popup_confirm
from .registry_manager import RegistryManager


_DEFAULT_RANDOM_IP_FREE_LIMIT = 20
_PREMIUM_RANDOM_IP_LIMIT = 400
def get_random_ip_limit() -> int:
    try:
        limit = RegistryManager.read_quota_limit(_DEFAULT_RANDOM_IP_FREE_LIMIT)
        limit = int(limit)
        if limit > 0:
            return limit
    except Exception:
        pass
    return _DEFAULT_RANDOM_IP_FREE_LIMIT


RANDOM_IP_FREE_LIMIT = get_random_ip_limit()  # 兼容旧代码，实际逻辑使用 get_random_ip_limit()


CARD_VALIDATION_ENDPOINT = "https://hungrym0.top/password.txt"
_quota_limit_dialog_shown = False
_proxy_api_url_override: Optional[str] = None
_CUSTOM_PROXY_CONFIG_FILENAME = "custom_ip.json"


def _validate_proxy_api_url(api_url: Optional[str]) -> str:
    """
    校验并清洗随机 IP 接口地址。
    要求以 http:// 或 https:// 开头，否则抛出 ValueError。
    """
    try:
        cleaned = str(api_url).strip()
    except Exception:
        cleaned = ""
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        raise ValueError("随机IP提取接口必须以 http:// 或 https:// 开头")
    return cleaned


def get_effective_proxy_api_url() -> str:
    """返回当前生效的随机 IP 提取接口。为空时回退到配置/环境变量。"""
    override = (_proxy_api_url_override or "").strip()
    return override or PROXY_REMOTE_URL


def is_custom_proxy_api_active() -> bool:
    """当前是否启用了用户自定义的随机 IP 接口。"""
    return bool((_proxy_api_url_override or "").strip())


def set_proxy_api_override(api_url: Optional[str]) -> str:
    """
    设置自定义随机 IP 提取接口地址，并返回最终生效的地址。
    传入空值时会回退到 .env 中的配置。
    """
    global _proxy_api_url_override
    cleaned = _validate_proxy_api_url(api_url)
    _proxy_api_url_override = cleaned or None
    effective = get_effective_proxy_api_url()
    return effective


def _get_runtime_directory(base_dir: Optional[str] = None) -> str:
    """
    获取运行目录，支持 PyInstaller 打包后的运行环境。
    """
    if base_dir:
        return os.fspath(base_dir)
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    return parent_dir or current_dir


def get_custom_proxy_api_config_path(base_dir: Optional[str] = None) -> str:
    """返回保存自定义随机 IP 接口配置的文件路径。"""
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
    """
    读取本地自定义随机 IP 接口配置，返回解析后的接口地址字符串（可能为空）。
    读取成功会同步更新当前生效的接口覆盖值；文件不存在时返回空字符串。
    """
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
    try:
        cleaned_api = _validate_proxy_api_url(api_value)
        set_proxy_api_override(cleaned_api)
    except Exception as exc:
        logging.error(f"自定义随机IP接口格式无效: {exc}")
        raise
    return cleaned_api


def save_custom_proxy_api_config(
    api_url: Optional[str],
    config_path: Optional[str] = None,
    base_dir: Optional[str] = None,
) -> str:
    """
    保存自定义随机 IP 接口配置到本地文件，并返回最终生效的接口地址。
    """
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
    """
    删除自定义接口配置文件并回退到默认接口，返回生效的地址。
    """
    path = os.fspath(config_path) if config_path else get_custom_proxy_api_config_path(base_dir)
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except Exception as exc:
        logging.debug(f"删除自定义随机IP配置时出现问题：{exc}")
    try:
        set_proxy_api_override(None)
    except Exception:
        global _proxy_api_url_override
        _proxy_api_url_override = None
    return get_effective_proxy_api_url()


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


def _load_proxy_ip_pool(proxy_url: Optional[str] = None) -> List[str]:
    if requests is None:
        raise RuntimeError("requests 模块不可用，无法从远程获取代理列表")
    target_url = (proxy_url or "").strip() or get_effective_proxy_api_url()
    _validate_proxy_api_url(target_url)
    try:
        response = requests.get(target_url, headers=DEFAULT_HTTP_HEADERS, timeout=12)
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
        raise ValueError(f"代理列表为空，请检查远程地址：{target_url}")
    random.shuffle(proxies)
    if len(proxies) > PROXY_MAX_PROXIES:
        proxies = proxies[:PROXY_MAX_PROXIES]
    return proxies


def _fetch_new_proxy_batch(expected_count: int = 1, proxy_url: Optional[str] = None) -> List[str]:
    try:
        expected = int(expected_count)
    except Exception:
        expected = 1
    expected = max(1, expected)
    proxies: List[str] = []
    # 多尝试几次，尽量拿到足够数量的 IP
    attempts = max(2, expected)
    for _ in range(attempts):
        batch = _load_proxy_ip_pool(proxy_url)
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


def _invoke_popup(gui: Any, kind: str, *args: Any, **kwargs: Any):
    """调用 GUI 上的弹窗方法，若不存在则退回到全局方法。"""
    popup_map = {
        "info": log_popup_info,
        "warning": log_popup_warning,
        "error": log_popup_error,
        "confirm": log_popup_confirm,
    }
    method_name = f"_log_popup_{kind}"
    method = getattr(gui, method_name, None) if gui else None
    popup_func = method if callable(method) else popup_map.get(kind)
    if popup_func is None:
        raise ValueError(f"Unsupported popup kind: {kind}")
    return popup_func(*args, **kwargs)


def _set_random_ip_enabled(gui: Any, enabled: bool):
    """在 GUI 上设置随机 IP 复选框，同时避免触发多余提示。"""
    if gui is None:
        return
    var = getattr(gui, "random_ip_enabled_var", None)
    if var is None or not hasattr(var, "set"):
        return
    suspend_attr = "_suspend_random_ip_notice"
    previous = getattr(gui, suspend_attr, False)
    setattr(gui, suspend_attr, True)
    try:
        var.set(bool(enabled))
    finally:
        setattr(gui, suspend_attr, previous)


def _schedule_on_gui_thread(gui: Any, callback: Callable[[], None]):
    """确保回调在 GUI 线程执行。"""
    if gui is None:
        callback()
        return
    dispatcher = getattr(gui, "_post_to_ui_thread", None)
    if callable(dispatcher):
        try:
            dispatcher(callback)
            return
        except Exception:
            logging.debug("将回调派发到 GUI 线程失败", exc_info=True)
    root = getattr(gui, "root", None)
    if root is None:
        callback()
        return
    try:
        root.after(0, callback)
    except Exception:
        callback()


def reset_quota_limit_dialog_flag():
    """外部调用时重置配额提示弹窗标记。"""
    global _quota_limit_dialog_shown
    _quota_limit_dialog_shown = False


def _play_success_sound(gui: Any):
    """卡密验证成功后的提示音，优先使用系统声音，失败则忽略。"""
    try:
        if winsound:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
            return
    except Exception:
        logging.debug("播放系统提示音失败", exc_info=True)
    try:
        root = getattr(gui, "root", None)
        if root:
            root.bell()
    except Exception:
        logging.debug("播放Tk提示音失败", exc_info=True)


def confirm_random_ip_usage(gui: Any) -> bool:
    """显示随机 IP 使用声明，返回用户是否确认。"""
    notice = (
        "启用随机IP提交前请确认：\n\n"
        "1) 代理来源于网络，确认启用视为已知悉风险并自愿承担一切后果；\n"
        "2) 禁止用于污染他问卷数据，否则可能被封禁或承担法律责任。\n"
        "3) 目前技术暂无法指定地区ip，有可能后续会支持。\n"
        "4) 随机IP维护成本高昂，如需大量使用需要付费。\n\n"
        "是否确认已知悉并继续启用随机IP提交？"
    )
    confirmed = bool(
        _invoke_popup(gui, "confirm", "随机IP使用声明", notice, icon="warning")
    )
    if confirmed and gui is not None:
        setattr(gui, "_random_ip_disclaimer_ack", True)
    return confirmed


def on_random_ip_toggle(gui: Any):
    """处理随机 IP 开关的逻辑，包括额度校验与免责声明确认。"""
    if gui is None:
        return
    if getattr(gui, "_suspend_random_ip_notice", False):
        return
    var = getattr(gui, "random_ip_enabled_var", None)
    if var is None or not hasattr(var, "get") or not bool(var.get()):
        return
    if not RegistryManager.is_quota_unlimited():
        count = RegistryManager.read_submit_count()
        limit = max(1, get_random_ip_limit())
        if count >= limit:
            _invoke_popup(
                gui,
                "warning",
                "提示",
                f"随机IP已达{limit}份限制，请通过卡密验证解锁额度后再启用。",
                parent=getattr(gui, "root", None),
            )
            _set_random_ip_enabled(gui, False)
            return
    if confirm_random_ip_usage(gui):
        return
    _set_random_ip_enabled(gui, False)


def ensure_random_ip_ready(gui: Any) -> bool:
    """
    在开始任务前二次确认免责声明是否已勾选。
    返回 True 表示可以继续执行。
    """
    if getattr(gui, "_random_ip_disclaimer_ack", False):
        return True
    if confirm_random_ip_usage(gui):
        return True
    _set_random_ip_enabled(gui, False)
    _invoke_popup(
        gui,
        "info",
        "已取消随机IP提交",
        "未同意免责声明，已禁用随机IP提交。",
    )
    return False


def _validate_card(card_code: str) -> bool:
    """
    验证卡密是否有效。
    通过远程接口 https://hungrym0.top/password.txt 获取合法卡密列表。
    """
    if not card_code:
        logging.warning("卡密为空")
        return False
    if requests is None:
        logging.warning("requests 模块未安装，无法验证卡密")
        return False
    code = card_code.strip()
    try:
        response = requests.get(CARD_VALIDATION_ENDPOINT, timeout=10, headers=DEFAULT_HTTP_HEADERS)
        if response.status_code != 200:
            logging.warning(f"无法获取卡密列表，服务器返回: {response.status_code}")
            return False
        valid_cards = {line.strip() for line in response.text.strip().split("\n") if line.strip()}
        if code in valid_cards:
            display = f"{code[:4]}***{code[-4:]}" if len(code) > 8 else "***"
            logging.info(f"卡密 {display} 验证通过")
            return True
        logging.warning("卡密验证失败：输入的卡密不在有效列表中")
        return False
    except requests.exceptions.Timeout:
        logging.error("获取卡密列表超时（10秒）")
        return False
    except requests.exceptions.ConnectionError as exc:
        logging.error(f"无法连接到卡密服务器: {exc}")
        return False
    except Exception as exc:
        logging.error(f"获取卡密列表出错: {exc}")
        return False


def show_card_validation_dialog(gui: Any) -> bool:
    """显示卡密验证弹窗，返回是否验证成功。"""
    parent = getattr(gui, "root", None)
    dialog = tk.Toplevel(parent)
    dialog.title("随机IP额度限制")
    dialog.resizable(False, False)
    if parent is not None:
        dialog.transient(parent)
    dialog.protocol("WM_DELETE_WINDOW", lambda: dialog.destroy())
    dialog.grab_set()

    container = ttk.Frame(dialog, padding=15)
    container.pack(fill=tk.BOTH, expand=True)

    ttk.Label(container, text="解锁无限随机IP提交额度", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, pady=(0, 10))

    style = ttk.Style()
    bg_color = style.lookup("TFrame", "background") or (parent.cget("background") if parent else "#ffffff")
    text_widget = tk.Text(
        container,
        wrap=tk.WORD,
        height=10,
        font=("Microsoft YaHei", 10),
        relief=tk.FLAT,
        borderwidth=0,
        background=bg_color,
        cursor="arrow",
    )
    text_widget.pack(anchor=tk.W, pady=(0, 15), fill=tk.X)

    text_widget.insert(
        "1.0",
        "作者只是一个大一小登，但是由于ip池及开发成本较高，用户量大，问卷份数要求多，\n",
    )
    text_widget.insert(tk.END, "加上学业压力，导致长期如此无偿经营困难……\n\n")
    text_widget.insert(tk.END, "1.捐助")

    blue_start = text_widget.index(tk.END + "-1c")
    text_widget.insert(tk.END, "任意金额")
    blue_end = text_widget.index(tk.END + "-1c")
    text_widget.tag_add("blue", blue_start, blue_end)
    text_widget.tag_config("blue", foreground="#0066CC")

    text_widget.insert(tk.END, "（多少都行♥）\n")
    text_widget.insert(tk.END, "2.在“联系”中找到开发者，并留下联系邮箱\n")
    text_widget.insert(tk.END, "3.开发者会发送卡密到你的邮箱，输入卡密后即可解锁无限随机IP提交额度\n")

    gray_start = text_widget.index(tk.END + "-1c")
    text_widget.insert(tk.END, "4.你也可以通过自己的口才白嫖卡密（误）")
    gray_end = text_widget.index(tk.END + "-1c")
    text_widget.tag_add("gray", gray_start, gray_end)
    text_widget.tag_config("gray", foreground="#918A8A")
    text_widget.insert(tk.END, "\n\n感谢您的支持与理解！🙏")
    text_widget.config(state=tk.DISABLED)

    thanks_button_frame = ttk.Frame(container)
    thanks_button_frame.pack(fill=tk.X, pady=(10, 15), anchor=tk.W)

    ttk.Button(
        thanks_button_frame,
        text="📧 联系",
        command=lambda: [
            dialog.destroy(),
            getattr(gui, "_open_contact_dialog", lambda **kwargs: None)(default_type="卡密获取"),
        ],
        width=10,
    ).pack(side=tk.LEFT, padx=(0, 5))

    ttk.Button(
        thanks_button_frame,
        text="💰 捐助",
        command=lambda: [dialog.destroy(), getattr(gui, "_open_donation_dialog", lambda: None)()],
        width=10,
    ).pack(side=tk.LEFT, padx=(0, 5))

    ttk.Label(container, text="请输入卡密：", font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(0, 5))
    card_var = tk.StringVar()
    card_entry = ttk.Entry(container, textvariable=card_var, width=30, show="*")
    card_entry.pack(fill=tk.X, pady=(0, 15))
    card_entry.focus()

    button_frame = ttk.Frame(container)
    button_frame.pack(fill=tk.X, pady=(10, 0))

    result_var = tk.BooleanVar(value=False)

    def on_validate():
        card_input = card_var.get().strip()
        if not card_input:
            log_popup_warning("提示", "请输入卡密", parent=dialog)
            return
        if _validate_card(card_input):
            RegistryManager.reset_submit_count()
            RegistryManager.write_card_validate_result(True)
            RegistryManager.write_quota_limit(_PREMIUM_RANDOM_IP_LIMIT)
            RegistryManager.set_quota_unlimited(False)
            logging.info(f"卡密验证成功，已扩容随机IP额度至 {_PREMIUM_RANDOM_IP_LIMIT}")
            refresh_ip_counter_display(gui)
            reset_quota_limit_dialog_flag()
            result_var.set(True)
            _play_success_sound(gui)
            enable_now = log_popup_confirm(
                "成功",
                f"卡密验证成功！已解锁随机IP额度 {_PREMIUM_RANDOM_IP_LIMIT} 份。\n\n是否立即开启随机IP提交？",
                parent=dialog,
                icon="question",
            )
            if enable_now:
                try:
                    _set_random_ip_enabled(gui, True)
                    on_random_ip_toggle(gui)
                except Exception:
                    logging.debug("立即启用随机IP失败", exc_info=True)
            dialog.destroy()
        else:
            log_popup_error("失败", "卡密无效，请检查后重试。", parent=dialog)

    ttk.Button(button_frame, text="验证", command=on_validate).pack(side=tk.RIGHT, padx=(5, 0))
    ttk.Button(button_frame, text="取消", command=dialog.destroy).pack(side=tk.RIGHT, padx=(5, 0))

    apply_scaling = getattr(gui, "_apply_window_scaling", None)
    if callable(apply_scaling):
        apply_scaling(dialog, base_width=380, base_height=250, min_height=200)
    center_child = getattr(gui, "_center_child_window", None)
    if callable(center_child):
        center_child(dialog)

    dialog.wait_window()
    return bool(result_var.get())


def refresh_ip_counter_display(gui: Any):
    """刷新随机 IP 提交计数显示。"""
    if gui is None:
        return
    try:
        limit = max(1, get_random_ip_limit())
        label = getattr(gui, "_ip_counter_label", None)
        button = getattr(gui, "_ip_reset_button", None)
        pack_opts = getattr(gui, "_ip_reset_button_pack_opts", None) or {"side": tk.LEFT, "padx": 2}
        hint_label = getattr(gui, "_ip_limit_hint_label", None)
        using_custom_api = is_custom_proxy_api_active()
        if label and label.winfo_exists():
            is_unlimited = RegistryManager.is_quota_unlimited()
            if using_custom_api:
                label.config(text="--/-- (已启用自定义接口)", foreground="#ff8c00")
            elif is_unlimited:
                label.config(text="∞ (无限额度)", foreground="green")
                if button and button.winfo_exists():
                    button.config(text="恢复限制", state=tk.NORMAL)
            else:
                count = RegistryManager.read_submit_count()
                percentage = min(100, int((count / limit) * 100)) if count < limit else 100
                if count >= limit:
                    label.config(text=f"{count}/{limit} (已达上限)", foreground="red")
                else:
                    label.config(text=f"{count}/{limit} ({percentage}%)", foreground="blue")
                if button and button.winfo_exists():
                    if limit >= _PREMIUM_RANDOM_IP_LIMIT:
                        button.config(text="已解锁", state=tk.DISABLED)
                    else:
                        button.config(text="解锁无限IP", state=tk.NORMAL)
        if button and button.winfo_exists():
            if using_custom_api:
                if button.winfo_manager():
                    button.pack_forget()
            else:
                if not button.winfo_manager():
                    try:
                        button.pack(**{k: v for k, v in pack_opts.items() if k != "in"})
                    except Exception:
                        button.pack(side=tk.LEFT, padx=2)
        if hint_label and hint_label.winfo_exists():
            if using_custom_api:
                hint_label.config(text="")
                if hint_label.winfo_manager():
                    hint_label.pack_forget()
            elif limit >= _PREMIUM_RANDOM_IP_LIMIT and not RegistryManager.is_quota_unlimited():
                hint_label.config(text="❕如需更多额度请联系开发者说明情况", fg="#d2691e")
                if not hint_label.winfo_manager():
                    hint_label.pack(fill=tk.X, padx=5, pady=(2, 0))
            else:
                hint_label.config(text="")
                if hint_label.winfo_manager():
                    hint_label.pack_forget()
    except Exception as exc:
        logging.debug(f"刷新IP计数显示出错: {exc}")


def reset_ip_counter(gui: Any):
    """重置随机 IP 提交计数，或在无限额度状态下恢复限制。"""
    if gui is None:
        return
    if RegistryManager.is_quota_unlimited():
        limit = max(1, get_random_ip_limit())
        result = _invoke_popup(
            gui,
            "confirm",
            "确认",
            "当前已启用无限额度。\n是否要禁用无限额度并恢复计数限制？",
        )
        if result:
            RegistryManager.set_quota_unlimited(False)
            RegistryManager.reset_submit_count()
            logging.info("已禁用无限额度，恢复计数限制")
            refresh_ip_counter_display(gui)
            _invoke_popup(gui, "info", "成功", f"已禁用无限额度，恢复为{limit}份限制。")
    else:
        result = _invoke_popup(
            gui,
            "confirm",
            "确认",
            "确定要启用无限额度吗？\n(需要卡密验证)",
        )
        if result:
            show_card_validation_dialog(gui)


def _disable_random_ip_and_show_dialog(gui: Any):
    """限制到达时禁用随机 IP 并弹出卡密验证窗口。"""
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
    """每次随机 IP 成功提交后更新计数并判断是否需要触发卡密验证。"""
    if RegistryManager.is_quota_unlimited():
        logging.info("已启用无限额度，无需验证")
        return
    limit = max(1, get_random_ip_limit())
    ip_count = RegistryManager.increment_submit_count()
    logging.info(f"随机IP提交计数: {ip_count}/{limit}")
    # 计数发生在工作线程中，这里主动把 UI 刷新调度到 Tk 主线程，避免主界面计数不更新
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
    """
    加载配置时根据当前额度判断是否可以启用随机 IP。
    返回实际允许的开关值。
    """
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

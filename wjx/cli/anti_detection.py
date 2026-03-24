"""
CLI 反检测策略模块

提供浏览器指纹伪装、代理轮换、反检测等功能。
"""

import json
import logging
import os
import random
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from wjx.utils.app.runtime_paths import get_runtime_directory

logger = logging.getLogger(__name__)


@dataclass
class FingerprintProfile:
    user_agent: str = ""
    platform: str = "Win32"
    vendor: str = "Google Inc."
    webgl_vendor: str = "Intel Inc."
    webgl_renderer: str = "Intel Iris OpenGL Engine"
    language: str = "zh-CN"
    timezone: str = "Asia/Shanghai"
    screen_resolution: str = "1920,1080"
    color_depth: int = 24
    canvas_mode: str = "noise"
    do_not_track: bool = False
    hardware_concurrency: int = 8
    device_memory: int = 8


@dataclass
class ProxyConfig:
    enabled: bool = False
    proxy_list: List[str] = field(default_factory=list)
    proxy_source: str = "default"
    custom_api_url: str = ""
    rotation_strategy: str = "random"
    area_code: Optional[str] = None


class AntiDetectionManager:
    _instance: Optional["AntiDetectionManager"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs) -> "AntiDetectionManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._fingerprint_profiles: Dict[str, FingerprintProfile] = {}
        self._active_profile: Optional[str] = None
        self._proxy_config = ProxyConfig()
        self._proxy_index = 0
        self._proxy_lock = threading.Lock()
        self._initialized = True

    def set_proxy_config(self, config: ProxyConfig) -> None:
        self._proxy_config = config
        self._proxy_index = 0
        logger.info(f"代理配置已更新: enabled={config.enabled}, source={config.proxy_source}")

    def get_next_proxy(self) -> Optional[str]:
        if not self._proxy_config.enabled or not self._proxy_config.proxy_list:
            return None

        with self._proxy_lock:
            if self._proxy_config.rotation_strategy == "random":
                return random.choice(self._proxy_config.proxy_list)
            elif self._proxy_config.rotation_strategy == "round_robin":
                proxy = self._proxy_config.proxy_list[self._proxy_index]
                self._proxy_index = (self._proxy_index + 1) % len(self._proxy_config.proxy_list)
                return proxy
            return None

    def create_fingerprint_profile(
        self,
        name: str,
        profile_type: str = "default",
    ) -> FingerprintProfile:
        profile = FingerprintProfile()

        if profile_type == "windows_chrome":
            profile.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            profile.platform = "Win32"
            profile.vendor = "Google Inc."
        elif profile_type == "mac_safari":
            profile.user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15"
            profile.platform = "MacIntel"
            profile.vendor = "Apple Computer, Inc."
        elif profile_type == "android_chrome":
            profile.user_agent = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36"
            profile.platform = "Linux"
            profile.vendor = "Google Inc."
        elif profile_type == "ios_safari":
            profile.user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"
            profile.platform = "iPhone"
            profile.vendor = "Apple Computer, Inc."
        else:
            profile.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            profile.platform = "Win32"
            profile.vendor = "Google Inc."

        profile.webgl_vendor = random.choice([
            "Intel Inc.",
            "NVIDIA Corporation",
            "AMD",
            "VMware, Inc.",
        ])
        profile.webgl_renderer = random.choice([
            "Intel Iris OpenGL Engine",
            "NVIDIA GeForce GTX 1060",
            "AMD Radeon Pro 555",
            "llvmpipe (LLVM 15.0.1, 256 bits)",
        ])
        profile.language = random.choice(["zh-CN", "zh-Hans-CN", "en-US"])
        profile.timezone = random.choice(["Asia/Shanghai", "Asia/Hong_Kong", "Asia/Tokyo", "America/New_York"])
        profile.screen_resolution = random.choice(["1920,1080", "1366,768", "1536,864", "2560,1440"])
        profile.color_depth = random.choice([24, 32])
        profile.hardware_concurrency = random.choice([4, 8, 16])
        profile.device_memory = random.choice([4, 8, 16])

        self._fingerprint_profiles[name] = profile
        logger.info(f"指纹配置文件已创建: {name} ({profile_type})")
        return profile

    def get_fingerprint_profile(self, name: str) -> Optional[FingerprintProfile]:
        return self._fingerprint_profiles.get(name)

    def set_active_profile(self, name: str) -> bool:
        if name in self._fingerprint_profiles:
            self._active_profile = name
            logger.info(f"激活指纹配置文件: {name}")
            return True
        return False

    def get_active_profile(self) -> Optional[FingerprintProfile]:
        if self._active_profile:
            return self._fingerprint_profiles.get(self._active_profile)
        return None

    def generate_stealth_browser_args(self) -> List[str]:
        args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-features=IsolateOrigins,site-per-process",
        ]
        if self._proxy_config.enabled:
            pass
        return args


_anti_detection_instance: Optional[AntiDetectionManager] = None


def get_anti_detection() -> AntiDetectionManager:
    global _anti_detection_instance
    if _anti_detection_instance is None:
        _anti_detection_instance = AntiDetectionManager()
    return _anti_detection_instance


def load_proxy_list_from_file(filepath: str) -> List[str]:
    proxies = []
    if not os.path.exists(filepath):
        logger.warning(f"代理列表文件不存在: {filepath}")
        return proxies

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                proxies.append(line)

    logger.info(f"从文件加载了 {len(proxies)} 个代理: {filepath}")
    return proxies


def test_proxy(proxy_address: str, timeout: int = 5) -> Tuple[bool, str]:
    import socket
    try:
        parts = proxy_address.replace("://", "://").split(":")
        if len(parts) >= 2:
            host = parts[-2].split("@")[-1]
            port = int(parts[-1])
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                return True, "连接成功"
            return False, "连接失败"
        return False, "格式错误"
    except Exception as e:
        return False, str(e)
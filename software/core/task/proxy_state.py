"""ExecutionState 的代理与运行态同步相关方法。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Protocol

from software.core.engine.stop_signal import StopSignalLike


@dataclass
class ProxyLease:
    """代理租约对象，保存地址与过期时间信息。"""

    address: str = ""
    expire_at: str = ""
    expire_ts: float = 0.0
    poolable: bool = True
    source: str = ""


if TYPE_CHECKING:
    class _ProxyRuntimeHost(Protocol):
        lock: threading.Lock
        proxy_waiting_threads: int
        proxy_in_use_by_thread: dict[str, ProxyLease]
        successful_proxy_addresses: set[str]
        proxy_cooldown_until_by_address: dict[str, float]
        _runtime_condition: threading.Condition

        def _purge_expired_proxy_cooldowns_locked(self, *, now_ts: Optional[float] = None) -> None: ...
        def _is_proxy_in_cooldown_locked(self, proxy_address: str, *, now_ts: Optional[float] = None) -> bool: ...
        def active_proxy_addresses_locked(self, *, exclude_thread_name: str = "") -> set[str]: ...
        def successful_proxy_addresses_locked(self) -> set[str]: ...
        def notify_runtime_change(self) -> None: ...


class ProxyRuntimeMixin:
    def register_proxy_waiter(self: "_ProxyRuntimeHost") -> None:
        with self.lock:
            self.proxy_waiting_threads = max(0, int(self.proxy_waiting_threads or 0)) + 1

    def unregister_proxy_waiter(self: "_ProxyRuntimeHost") -> None:
        with self.lock:
            self.proxy_waiting_threads = max(0, int(self.proxy_waiting_threads or 0) - 1)

    def mark_proxy_in_use(self: "_ProxyRuntimeHost", thread_name: str, lease: ProxyLease) -> None:
        key = str(thread_name or "").strip()
        if not key or not isinstance(lease, ProxyLease):
            return
        with self.lock:
            self.proxy_in_use_by_thread[key] = lease

    def _purge_expired_proxy_cooldowns_locked(
        self: "_ProxyRuntimeHost",
        *,
        now_ts: Optional[float] = None,
    ) -> None:
        current = float(now_ts if now_ts is not None else time.time())
        expired = [
            address
            for address, cooldown_until in self.proxy_cooldown_until_by_address.items()
            if float(cooldown_until or 0.0) <= current
        ]
        for address in expired:
            self.proxy_cooldown_until_by_address.pop(address, None)

    def purge_expired_proxy_cooldowns(self: "_ProxyRuntimeHost", *, now_ts: Optional[float] = None) -> None:
        with self.lock:
            self._purge_expired_proxy_cooldowns_locked(now_ts=now_ts)

    def _is_proxy_in_cooldown_locked(
        self: "_ProxyRuntimeHost",
        proxy_address: str,
        *,
        now_ts: Optional[float] = None,
    ) -> bool:
        normalized = str(proxy_address or "").strip()
        if not normalized:
            return False
        self._purge_expired_proxy_cooldowns_locked(now_ts=now_ts)
        current = float(now_ts if now_ts is not None else time.time())
        return float(self.proxy_cooldown_until_by_address.get(normalized, 0.0) or 0.0) > current

    def is_proxy_in_cooldown(
        self: "_ProxyRuntimeHost",
        proxy_address: str,
        *,
        now_ts: Optional[float] = None,
    ) -> bool:
        normalized = str(proxy_address or "").strip()
        if not normalized:
            return False
        with self.lock:
            return self._is_proxy_in_cooldown_locked(normalized, now_ts=now_ts)

    def mark_proxy_in_cooldown(
        self: "_ProxyRuntimeHost",
        proxy_address: str,
        cooldown_seconds: float,
    ) -> None:
        normalized = str(proxy_address or "").strip()
        if not normalized:
            return
        try:
            seconds = max(0.0, float(cooldown_seconds))
        except Exception:
            seconds = 0.0
        if seconds <= 0:
            return
        cooldown_until = time.time() + seconds
        with self.lock:
            previous_until = float(self.proxy_cooldown_until_by_address.get(normalized, 0.0) or 0.0)
            self.proxy_cooldown_until_by_address[normalized] = max(previous_until, cooldown_until)
        self.notify_runtime_change()

    def active_proxy_addresses_locked(
        self: "_ProxyRuntimeHost",
        *,
        exclude_thread_name: str = "",
    ) -> set[str]:
        excluded = str(exclude_thread_name or "").strip()
        active = set()
        for thread_name, lease in self.proxy_in_use_by_thread.items():
            if excluded and str(thread_name or "").strip() == excluded:
                continue
            address = str(getattr(lease, "address", "") or "").strip()
            if address:
                active.add(address)
        return active

    def successful_proxy_addresses_locked(self: "_ProxyRuntimeHost") -> set[str]:
        return {
            str(address or "").strip()
            for address in set(self.successful_proxy_addresses or set())
            if str(address or "").strip()
        }

    def snapshot_active_proxy_addresses(
        self: "_ProxyRuntimeHost",
        *,
        exclude_thread_name: str = "",
    ) -> set[str]:
        with self.lock:
            return self.active_proxy_addresses_locked(exclude_thread_name=exclude_thread_name)

    def snapshot_successful_proxy_addresses(self: "_ProxyRuntimeHost") -> set[str]:
        with self.lock:
            return self.successful_proxy_addresses_locked()

    def snapshot_blocked_proxy_addresses(
        self: "_ProxyRuntimeHost",
        *,
        exclude_thread_name: str = "",
    ) -> set[str]:
        with self.lock:
            blocked = self.active_proxy_addresses_locked(exclude_thread_name=exclude_thread_name)
            blocked.update(self.successful_proxy_addresses_locked())
            return blocked

    def is_proxy_address_in_use(
        self: "_ProxyRuntimeHost",
        proxy_address: str,
        *,
        exclude_thread_name: str = "",
    ) -> bool:
        normalized = str(proxy_address or "").strip()
        if not normalized:
            return False
        with self.lock:
            return normalized in self.active_proxy_addresses_locked(exclude_thread_name=exclude_thread_name)

    def mark_successful_proxy_address(self: "_ProxyRuntimeHost", proxy_address: str) -> bool:
        normalized = str(proxy_address or "").strip()
        if not normalized:
            return False
        with self.lock:
            previous_size = len(self.successful_proxy_addresses)
            self.successful_proxy_addresses.add(normalized)
            changed = len(self.successful_proxy_addresses) != previous_size
        if changed:
            self.notify_runtime_change()
        return changed

    def is_successful_proxy_address(self: "_ProxyRuntimeHost", proxy_address: str) -> bool:
        normalized = str(proxy_address or "").strip()
        if not normalized:
            return False
        with self.lock:
            return normalized in self.successful_proxy_addresses_locked()

    def notify_runtime_change(self: "_ProxyRuntimeHost") -> None:
        with self._runtime_condition:
            self._runtime_condition.notify_all()

    def wait_for_runtime_change(
        self: "_ProxyRuntimeHost",
        *,
        stop_signal: Optional[StopSignalLike] = None,
        timeout: Optional[float] = None,
    ) -> bool:
        if stop_signal is not None and stop_signal.is_set():
            return True
        wait_timeout = None if timeout is None else max(0.0, float(timeout))
        with self._runtime_condition:
            self._runtime_condition.wait(timeout=wait_timeout)
        return bool(stop_signal is not None and stop_signal.is_set())

    def release_proxy_in_use(self: "_ProxyRuntimeHost", thread_name: str) -> Optional[ProxyLease]:
        key = str(thread_name or "").strip()
        if not key:
            return None
        with self.lock:
            released = self.proxy_in_use_by_thread.pop(key, None)
        if released is not None:
            self.notify_runtime_change()
        return released

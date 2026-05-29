"""运行内核访问外层控制服务的最小端口。"""

from __future__ import annotations

from typing import Optional, Protocol

from software.core.engine.stop_signal import StopSignalLike


class RuntimeControlPort(Protocol):
    def wait_if_paused(self, stop_signal: Optional[StopSignalLike]) -> None: ...

    def on_random_ip_submission(self, stop_signal: Optional[StopSignalLike] = None) -> None: ...

    def on_random_ip_loading_changed(self, loading: bool, message: str = "") -> None: ...


def wait_if_paused(runtime_port: RuntimeControlPort | None, stop_signal: Optional[StopSignalLike]) -> None:
    if runtime_port is None:
        return
    runtime_port.wait_if_paused(stop_signal)


def on_random_ip_submission(
    runtime_port: RuntimeControlPort | None,
    stop_signal: Optional[StopSignalLike],
) -> None:
    if runtime_port is None:
        return
    runtime_port.on_random_ip_submission(stop_signal)


def on_random_ip_loading_changed(
    runtime_port: RuntimeControlPort | None,
    loading: bool,
    message: str = "",
) -> None:
    if runtime_port is None:
        return
    setter = getattr(runtime_port, "on_random_ip_loading_changed", None)
    if callable(setter):
        setter(bool(loading), str(message or ""))


__all__ = [
    "RuntimeControlPort",
    "on_random_ip_loading_changed",
    "on_random_ip_submission",
    "wait_if_paused",
]

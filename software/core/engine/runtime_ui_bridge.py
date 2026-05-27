"""运行内核访问外层 UI/控制器能力的最小桥接接口。"""

from __future__ import annotations

from typing import Optional, Protocol

from software.core.engine.stop_signal import StopSignalLike


class RuntimeUiBridge(Protocol):
    def wait_if_paused(self, stop_signal: Optional[StopSignalLike]) -> None: ...

    def handle_random_ip_submission(self, stop_signal: Optional[StopSignalLike] = None) -> None: ...

    def set_random_ip_loading(self, loading: bool, message: str = "") -> None: ...


def wait_if_paused(runtime_bridge: RuntimeUiBridge | None, stop_signal: Optional[StopSignalLike]) -> None:
    if runtime_bridge is None:
        return
    runtime_bridge.wait_if_paused(stop_signal)


def handle_random_ip_submission(
    runtime_bridge: RuntimeUiBridge | None,
    stop_signal: Optional[StopSignalLike],
) -> None:
    if runtime_bridge is None:
        return
    runtime_bridge.handle_random_ip_submission(stop_signal)


def set_random_ip_loading(
    runtime_bridge: RuntimeUiBridge | None,
    loading: bool,
    message: str = "",
) -> None:
    if runtime_bridge is None:
        return
    setter = getattr(runtime_bridge, "set_random_ip_loading", None)
    if callable(setter):
        setter(bool(loading), str(message or ""))


__all__ = [
    "RuntimeUiBridge",
    "handle_random_ip_submission",
    "set_random_ip_loading",
    "wait_if_paused",
]

"""运行内核访问外层 UI/控制器能力的最小桥接接口。"""

from __future__ import annotations

from typing import Optional, Protocol

from software.core.engine.stop_signal import StopSignalLike


class RuntimeUiBridge(Protocol):
    def wait_if_paused(self, stop_signal: Optional[StopSignalLike]) -> None: ...

    def handle_random_ip_submission(self, stop_signal: Optional[StopSignalLike] = None) -> None: ...


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


__all__ = [
    "RuntimeUiBridge",
    "handle_random_ip_submission",
    "wait_if_paused",
]

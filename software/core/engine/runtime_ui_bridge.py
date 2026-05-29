"""兼容导出：运行内核控制端口。"""

from software.core.engine.runtime_control_port import (
    RuntimeControlPort,
    on_random_ip_loading_changed as set_random_ip_loading,
    on_random_ip_submission as handle_random_ip_submission,
    wait_if_paused,
)

RuntimeUiBridge = RuntimeControlPort

__all__ = [
    "RuntimeControlPort",
    "RuntimeUiBridge",
    "handle_random_ip_submission",
    "set_random_ip_loading",
    "wait_if_paused",
]

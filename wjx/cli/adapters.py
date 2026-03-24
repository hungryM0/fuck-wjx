"""
GUI 适配器抽象层

将 GUI 依赖抽象为协议，使得核心逻辑可以在 CLI 模式下运行。
"""

from typing import TYPE_CHECKING, Any, Optional, Protocol
from dataclasses import dataclass

if TYPE_CHECKING:
    from wjx.core.task_context import TaskContext


class GUIBridge(Protocol):
    """GUI桥接协议 - 定义GUI需要提供的回调接口"""

    def pause_run(self, reason: str) -> None:
        """暂停运行"""
        ...

    def resume_run(self) -> None:
        """恢复运行"""
        ...

    def show_message_dialog(self, title: str, message: str, level: str = "info") -> None:
        """显示消息对话框"""
        ...

    def is_random_ip_enabled(self) -> bool:
        """检查是否启用随机IP"""
        ...

    def get_random_ip_counter_snapshot(self) -> tuple[int, int, bool]:
        """获取随机IP计数器快照 (已用, 总额, 是否使用自定义API)"""
        ...


@dataclass
class CLIGuiAdapter:
    """CLI模式下的GUI适配器 - 将GUI回调重定向到CLI输出"""

    silent: bool = False
    verbose: bool = False

    def pause_run(self, reason: str) -> None:
        if not self.silent:
            print(f"\n⚠️ 任务已暂停: {reason}")

    def resume_run(self) -> None:
        if not self.silent:
            print("\n▶️ 任务已恢复")

    def show_message_dialog(self, title: str, message: str, level: str = "info") -> None:
        if self.silent:
            return
        prefix = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "success": "✅",
        }.get(level, "ℹ️")
        print(f"\n{prefix} {title}: {message}")

    def is_random_ip_enabled(self) -> bool:
        return True

    def get_random_ip_counter_snapshot(self) -> tuple[int, int, bool]:
        return (0, 0, False)


class NoOpGuiAdapter:
    """无操作适配器 - 完全静默，不输出任何信息"""

    def pause_run(self, reason: str) -> None:
        pass

    def resume_run(self) -> None:
        pass

    def show_message_dialog(self, title: str, message: str, level: str = "info") -> None:
        pass

    def is_random_ip_enabled(self) -> bool:
        return False

    def get_random_ip_counter_snapshot(self) -> tuple[int, int, bool]:
        return (0, 0, False)


def get_cli_adapter(silent: bool = False, verbose: bool = False) -> CLIGuiAdapter:
    """获取CLI适配器实例"""
    return CLIGuiAdapter(silent=silent, verbose=verbose)
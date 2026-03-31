"""AI 自动填充辅助 - 检查 AI 配置就绪状态"""
from qfluentwidgets import InfoBar, InfoBarPosition

from software.integrations.ai import get_ai_readiness_error


def ensure_ai_ready(parent) -> bool:
    """检查 AI 配置是否可用，不可用时给出提示。"""
    readiness_error = get_ai_readiness_error()
    if readiness_error:
        InfoBar.warning(
            "",
            f"请先到“运行参数”页补全 AI 配置：{readiness_error}",
            parent=parent,
            position=InfoBarPosition.TOP,
            duration=3500,
        )
        return False
    return True


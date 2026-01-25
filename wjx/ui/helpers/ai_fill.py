# -*- coding: utf-8 -*-
from qfluentwidgets import InfoBar, InfoBarPosition

from wjx.utils.integrations.ai_service import get_ai_settings


def ensure_ai_ready(parent) -> bool:
    """检查 AI 配置是否可用，不可用时给出提示。"""
    ai_config = get_ai_settings()
    if not ai_config.get("enabled"):
        InfoBar.warning(
            "",
            "请先到“运行参数”页启用 AI 填空助手",
            parent=parent,
            position=InfoBarPosition.TOP,
            duration=3000,
        )
        return False
    if not ai_config.get("api_key"):
        InfoBar.warning(
            "",
            "请先到“运行参数”页配置 API Key",
            parent=parent,
            position=InfoBarPosition.TOP,
            duration=3000,
        )
        return False
    return True

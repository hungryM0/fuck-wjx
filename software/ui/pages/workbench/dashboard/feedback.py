"""Dashboard 页面运行反馈。"""

from __future__ import annotations

from typing import Any

from software.ui.pages.workbench.shared.run_feedback import show_feedback_toast


def dashboard_toast(
    page: Any,
    text: str,
    *,
    level: str = "info",
    duration: int = 2000,
    show_progress: bool = False,
):
    return show_feedback_toast(
        page,
        text,
        level=level,
        duration=duration,
        show_progress=show_progress,
        reposition=True,
    )

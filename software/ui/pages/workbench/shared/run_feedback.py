"""Workbench 页面共享运行反馈。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from qfluentwidgets import IndeterminateProgressRing, InfoBar, InfoBarPosition

from software.logging.log_utils import log_suppressed_exception
from software.ui.helpers.message_bar import replace_message_bar, reposition_message_bar, show_message_bar


@dataclass
class RunFeedbackState:
    progress_infobar: InfoBar | None = None
    completion_notified: bool = False
    show_end_toast_after_cleanup: bool = False
    last_progress: int = 0
    last_pause_reason: str = ""


def init_run_feedback_state(owner: Any) -> None:
    owner._run_feedback = RunFeedbackState()
    owner._progress_infobar = None
    owner._completion_notified = False
    owner._show_end_toast_after_cleanup = False
    owner._last_progress = 0
    owner._last_pause_reason = ""


def _state(owner: Any) -> RunFeedbackState:
    state = getattr(owner, "_run_feedback", None)
    if state is None:
        state = RunFeedbackState()
        owner._run_feedback = state
    return state


def feedback_progress_infobar(owner: Any) -> InfoBar | None:
    return _state(owner).progress_infobar


def set_feedback_progress_infobar(owner: Any, infobar: InfoBar | None) -> None:
    _state(owner).progress_infobar = infobar
    owner._progress_infobar = infobar


def replace_feedback_progress_infobar(owner: Any) -> None:
    current = feedback_progress_infobar(owner)
    try:
        replace_message_bar(current)
    except Exception as exc:
        log_suppressed_exception(
            "_toast: replace_message_bar(self._progress_infobar)",
            exc,
            level=logging.WARNING,
        )
    set_feedback_progress_infobar(owner, None)


def show_feedback_toast(
    owner: Any,
    text: str,
    *,
    level: str = "info",
    duration: int = 2000,
    show_progress: bool = False,
    title: str = "",
    reposition: bool = False,
) -> InfoBar | None:
    replace_feedback_progress_infobar(owner)
    parent = owner.window() or owner
    if show_progress:
        infobar = show_message_bar(
            parent=parent,
            title=title,
            message=text,
            level=level.lower(),
            position=InfoBarPosition.TOP,
            duration=duration,
        )
        spinner = IndeterminateProgressRing()
        spinner.setFixedSize(20, 20)
        spinner.setStrokeWidth(3)
        infobar.addWidget(spinner)
        if reposition:
            reposition_message_bar(infobar)
        set_feedback_progress_infobar(owner, infobar)
        return infobar

    kind = level.lower()
    if kind == "success":
        InfoBar.success("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)
    elif kind == "warning":
        InfoBar.warning("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)
    elif kind == "error":
        InfoBar.error("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)
    else:
        InfoBar.info("", text, parent=parent, position=InfoBarPosition.TOP, duration=duration)
    return None


def get_completion_notified(owner: Any) -> bool:
    return bool(_state(owner).completion_notified)


def set_completion_notified(owner: Any, value: bool) -> None:
    _state(owner).completion_notified = bool(value)
    owner._completion_notified = bool(value)


def get_show_end_toast_after_cleanup(owner: Any) -> bool:
    return bool(_state(owner).show_end_toast_after_cleanup)


def set_show_end_toast_after_cleanup(owner: Any, value: bool) -> None:
    _state(owner).show_end_toast_after_cleanup = bool(value)
    owner._show_end_toast_after_cleanup = bool(value)


def get_last_progress(owner: Any) -> int:
    return int(_state(owner).last_progress or 0)


def set_last_progress(owner: Any, value: int) -> None:
    _state(owner).last_progress = int(value or 0)
    owner._last_progress = int(value or 0)


def get_last_pause_reason(owner: Any) -> str:
    return str(_state(owner).last_pause_reason or "")


def set_last_pause_reason(owner: Any, value: str) -> None:
    _state(owner).last_pause_reason = str(value or "")
    owner._last_pause_reason = str(value or "")

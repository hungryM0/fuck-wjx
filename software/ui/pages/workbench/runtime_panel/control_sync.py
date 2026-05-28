"""运行参数页开关和运行态同步。"""

from __future__ import annotations

import logging
from typing import Any, cast

from PySide6.QtCore import QPoint, QTimer

from software.logging.action_logger import log_action
from software.logging.log_utils import log_suppressed_exception
from software.providers.common import normalize_survey_provider


class RuntimeControlSyncMixin:
    controller: Any
    view: Any
    answer_card: Any
    answer_duration_card: Any
    thread_card: Any
    interval_card: Any
    random_ip_card: Any
    random_ua_card: Any
    reliability_card: Any
    MIN_THREADS: Any
    HTTP_MAX_THREADS: int

    def focus_answer_duration_setting(self):
        """跳转并聚焦到“作答时长”设置项。"""
        page = cast(Any, self)

        def _focus_target():
            target_edit = getattr(self.answer_duration_card, "startPicker", None)
            try:
                top_y = self.answer_duration_card.mapTo(self.view, QPoint(0, 0)).y()
                target_scroll = max(0, int(top_y - 16))
                page.verticalScrollBar().setValue(target_scroll)
            except Exception as exc:
                log_suppressed_exception(
                    "focus_answer_duration_setting: scroll",
                    exc,
                    level=logging.INFO,
                )
            try:
                if target_edit is not None:
                    target_edit.setFocus()
            except Exception as exc:
                log_suppressed_exception(
                    "focus_answer_duration_setting: focus input",
                    exc,
                    level=logging.INFO,
                )
            try:
                page.ensureWidgetVisible(self.answer_duration_card, 0, 24)
            except Exception as exc:
                log_suppressed_exception(
                    "focus_answer_duration_setting: ensureWidgetVisible",
                    exc,
                    level=logging.INFO,
                )

        QTimer.singleShot(0, _focus_target)
        QTimer.singleShot(80, _focus_target)

    def _resolve_thread_max(self) -> int:
        return self.HTTP_MAX_THREADS

    def _apply_thread_limit(self) -> bool:
        max_threads = self._resolve_thread_max()
        previous_value = int(self.thread_card.slider.value())
        clamped = previous_value > max_threads

        self.thread_card.slider.setRange(self.MIN_THREADS, max_threads)
        if clamped:
            self.thread_card.slider.setValue(max_threads)

        return clamped

    def _thread_edit_locked(self) -> bool:
        return bool(
            getattr(self.controller, "running", False)
            or getattr(self.controller, "_starting", False)
            or getattr(self.controller, "is_initializing", lambda: False)()
        )

    def on_run_state_changed(self, running: bool) -> None:
        self.thread_card.slider.setEnabled(not bool(running or self._thread_edit_locked()))

    def _on_random_ip_toggled(self, enabled: bool):
        if self.controller.request_toggle_random_ip(bool(enabled)):
            log_action(
                "CONFIG",
                "toggle_random_ip",
                "random_ip_switch",
                "runtime",
                result="validation_started",
                payload={"enabled": bool(enabled)},
            )
            return

        final_enabled = bool(self.controller.get_runtime_ui_state().get("random_ip_enabled", False))
        self.random_ip_card.switchButton.blockSignals(True)
        try:
            self.random_ip_card.switchButton.setChecked(final_enabled)
            self.random_ip_card._sync_ip_enabled(final_enabled)
        finally:
            self.random_ip_card.switchButton.blockSignals(False)
        log_action(
            "CONFIG",
            "toggle_random_ip",
            "random_ip_switch",
            "runtime",
            result="changed" if final_enabled == bool(enabled) else "reverted",
            level=logging.INFO if final_enabled == bool(enabled) else logging.WARNING,
            payload={"requested": bool(enabled), "enabled": final_enabled},
        )

    def _on_random_ua_toggled(self, enabled: bool):
        self._sync_random_ua(enabled)
        log_action(
            "CONFIG",
            "toggle_random_ua",
            "random_ua_switch",
            "runtime",
            result="changed",
            payload={"enabled": bool(enabled)},
        )

    def _sync_random_ua(self, enabled: bool):
        try:
            self.random_ua_card.setUAEnabled(bool(enabled))
        except Exception as exc:
            log_suppressed_exception(
                "_sync_random_ua: self.random_ua_card.setUAEnabled(bool(enabled))",
                exc,
                level=logging.WARNING,
            )

    def _on_reliability_mode_toggled(self, enabled: bool):
        try:
            self.reliability_card._sync_enabled(bool(enabled))
        except Exception as exc:
            log_suppressed_exception(
                "_on_reliability_mode_toggled: reliability_card._sync_enabled",
                exc,
                level=logging.INFO,
            )
        log_action(
            "CONFIG",
            "toggle_reliability_mode",
            "reliability_switch",
            "runtime",
            result="changed",
            payload={"enabled": bool(enabled)},
        )

    def _apply_random_ip_loading(self, loading: bool, message: str) -> None:
        try:
            self.random_ip_card.setLoading(bool(loading), str(message or ""))
        except Exception as exc:
            log_suppressed_exception("_apply_random_ip_loading", exc, level=logging.WARNING)

    def _sync_answer_datetime_window_card(self) -> None:
        try:
            provider = normalize_survey_provider(
                getattr(self.controller, "survey_provider", "")
                or self.controller.get_runtime_ui_state().get("survey_provider")
                or "wjx"
            )
            self.answer_card.set_provider(provider)
        except Exception as exc:
            log_suppressed_exception("_sync_answer_datetime_window_card", exc, level=logging.WARNING)

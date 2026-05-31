"""DashboardPage 启动运行与配置同步。"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any

from PySide6.QtGui import QColor

from software.app.config import HTTP_MAX_THREADS
from software.logging.action_logger import log_action
from software.logging.log_utils import log_suppressed_exception
from software.core.config.schema import RuntimeConfig
from software.providers.common import (
    SURVEY_PROVIDER_CREDAMO,
    SURVEY_PROVIDER_QQ,
    SURVEY_PROVIDER_WJX,
    detect_survey_provider,
    normalize_survey_provider,
)
from software.ui.helpers.proxy_access import apply_proxy_source_settings
from software.ui.pages.workbench.runtime_panel.proxy_source import (
    PROXY_SOURCE_CUSTOM as _PROXY_SOURCE_CUSTOM,
    PROXY_SOURCE_DEFAULT as _PROXY_SOURCE_DEFAULT,
    normalize_proxy_source,
)


class DashboardRunActionsMixin:
    if TYPE_CHECKING:
        controller: Any
        workbench_state: Any
        runtime_page: Any
        strategy_page: Any
        target_spin: Any
        thread_spin: Any
        proxy_source_combo: Any
        custom_proxy_trial_link: Any
        custom_proxy_api_edit: Any
        random_ip_cb: Any
        progress_bar: Any
        progress_pct: Any
        status_label: Any
        count_label: Any
        title_label: Any
        url_edit: Any
        _survey_title: str
        _completion_notified: bool
        _last_progress: int

        def _toast(
            self,
            text: str,
            level: str = "info",
            duration: int = 2000,
            show_progress: bool = False,
        ) -> Any: ...
        def _sync_start_button_state(self, running: bool | None = None) -> None: ...
        def _refresh_entry_table(self) -> None: ...
        def _refresh_ip_cost_infobar(self) -> None: ...
        def _sync_random_ip_toggle_presentation(self, enabled: bool) -> None: ...
        def window(self) -> Any: ...

    _PROVIDER_BADGES = {
        SURVEY_PROVIDER_WJX: ("问卷星", "#d18a00"),
        SURVEY_PROVIDER_QQ: ("腾讯问卷", "#008b8b"),
        SURVEY_PROVIDER_CREDAMO: ("见数", "#1f4f99"),
    }

    def _on_start_clicked(self, enable_reverse_fill: bool = False):
        coordinator = getattr(self, "run_coordinator", None)
        if coordinator is not None:
            coordinator.start(enable_reverse_fill=enable_reverse_fill)
            return
        log_action(
            "RUN",
            "start_run",
            "start_btn",
            "dashboard",
            result="blocked",
            level=logging.ERROR,
        )
        self._toast("运行编排器未初始化，无法开始执行", "error")

    def update_question_meta(self, title: str, count: int):
        self.count_label.setText(f"{count} 题")
        self.title_label.setText(title or "已配置的题目")
        self._survey_title = title or ""
        self._refresh_platform_badge()
        self._refresh_entry_table()
        self._sync_start_button_state()
        self._refresh_ip_cost_infobar()

    def _current_survey_provider(self) -> str:
        snapshot_getter = getattr(self.controller, "get_survey_snapshot", None)
        raw_snapshot = snapshot_getter() if callable(snapshot_getter) else {}
        snapshot = raw_snapshot if isinstance(raw_snapshot, dict) else {}
        provider = (
            snapshot.get("survey_provider")
            or getattr(self.controller, "survey_provider", "")
            or getattr(getattr(self.controller, "config", None), "survey_provider", "")
            or detect_survey_provider(self.url_edit.text().strip(), default=SURVEY_PROVIDER_WJX)
        )
        return normalize_survey_provider(provider, default=SURVEY_PROVIDER_WJX)

    def _refresh_platform_badge(self) -> None:
        badge = getattr(self, "platform_badge", None)
        if badge is None:
            return
        title = str(getattr(self, "_survey_title", "") or "").strip()
        if not title:
            badge.hide()
            return
        label, background_color = self._PROVIDER_BADGES.get(
            self._current_survey_provider(),
            self._PROVIDER_BADGES[SURVEY_PROVIDER_WJX],
        )
        badge.setText(label)
        badge.setCustomBackgroundColor(QColor(background_color), QColor(background_color))
        badge.setMinimumSize(0, 0)
        badge.setMaximumSize(16777215, 16777215)
        badge.adjustSize()
        native_size = badge.size()
        badge.setFixedSize(
            math.ceil(native_size.width() * 1.2),
            math.ceil(native_size.height() * 1.2),
        )
        badge.show()

    @staticmethod
    def _normalize_proxy_source(source: str) -> str:
        return normalize_proxy_source(source)

    def _selected_proxy_source(self) -> str:
        if not hasattr(self, "proxy_source_combo"):
            return _PROXY_SOURCE_DEFAULT
        combo = self.proxy_source_combo
        index = combo.currentIndex()
        source = str(combo.itemData(index)) if index >= 0 else _PROXY_SOURCE_DEFAULT
        return self._normalize_proxy_source(source)

    def _sync_proxy_source_combo(self, source: str) -> None:
        if not hasattr(self, "proxy_source_combo"):
            return
        combo = self.proxy_source_combo
        normalized = self._normalize_proxy_source(source)
        index = combo.findData(normalized)
        if index < 0:
            return
        if combo.currentIndex() == index:
            return
        combo.blockSignals(True)
        try:
            combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(False)
        self._sync_custom_proxy_api_visible(normalized)

    def _sync_custom_proxy_api_visible(self, source: str | None = None) -> None:
        if not hasattr(self, "custom_proxy_api_edit"):
            return
        selected = self._normalize_proxy_source(source or self._selected_proxy_source())
        visible = selected == _PROXY_SOURCE_CUSTOM
        if hasattr(self, "custom_proxy_trial_link"):
            self.custom_proxy_trial_link.setVisible(visible)
        self.custom_proxy_api_edit.setVisible(visible)

    def _sync_custom_proxy_api_text(self, text: str) -> None:
        if not hasattr(self, "custom_proxy_api_edit"):
            return
        if self.custom_proxy_api_edit.text() == str(text or ""):
            return
        self.custom_proxy_api_edit.blockSignals(True)
        try:
            self.custom_proxy_api_edit.setText(str(text or ""))
        finally:
            self.custom_proxy_api_edit.blockSignals(False)

    def _on_proxy_source_changed(self) -> None:
        source = self._selected_proxy_source()
        try:
            if hasattr(self.runtime_page, "set_proxy_source"):
                api_url = (
                    self.custom_proxy_api_edit.text().strip()
                    if source == _PROXY_SOURCE_CUSTOM and hasattr(self, "custom_proxy_api_edit")
                    else None
                )
                self.runtime_page.set_proxy_source(
                    source,
                    custom_api_url=api_url,
                    emit_state=False,
                    show_tip=True,
                )
            else:
                api_url = (
                    self.custom_proxy_api_edit.text().strip()
                    if source == _PROXY_SOURCE_CUSTOM and hasattr(self, "custom_proxy_api_edit")
                    else None
                )
                apply_proxy_source_settings(source, custom_api_url=api_url)
        except Exception as exc:
            log_suppressed_exception(
                "_on_proxy_source_changed: apply proxy source",
                exc,
                level=logging.WARNING,
            )
        self.controller.update_runtime_settings(proxy_source=source)
        self._sync_custom_proxy_api_visible(source)
        self._refresh_ip_cost_infobar()

    def _on_custom_proxy_api_changed(self) -> None:
        if self._selected_proxy_source() != _PROXY_SOURCE_CUSTOM:
            return
        try:
            api_url = self.custom_proxy_api_edit.text().strip()
            if hasattr(self.runtime_page, "set_custom_proxy_api"):
                self.runtime_page.set_custom_proxy_api(api_url)
            else:
                apply_proxy_source_settings(_PROXY_SOURCE_CUSTOM, custom_api_url=api_url or None)
        except Exception as exc:
            log_suppressed_exception(
                "_on_custom_proxy_api_changed",
                exc,
                level=logging.WARNING,
            )

    def _apply_runtime_ui_state(self, state: dict) -> None:
        target = state.get("target")
        if target is not None and int(self.target_spin.value()) != int(target):
            self.target_spin.blockSignals(True)
            self.target_spin.setValue(max(1, int(target)))
            self.target_spin.blockSignals(False)

        self.thread_spin.setRange(1, HTTP_MAX_THREADS)

        threads = state.get("threads")
        if threads is not None and int(self.thread_spin.value()) != int(threads):
            self.thread_spin.blockSignals(True)
            self.thread_spin.setValue(max(1, int(threads)))
            self.thread_spin.blockSignals(False)

        random_ip_enabled = state.get("random_ip_enabled")
        if random_ip_enabled is not None and bool(self.random_ip_cb.isChecked()) != bool(
            random_ip_enabled
        ):
            self.random_ip_cb.blockSignals(True)
            self.random_ip_cb.setChecked(bool(random_ip_enabled))
            self.random_ip_cb.blockSignals(False)
            self._sync_random_ip_toggle_presentation(bool(random_ip_enabled))

        proxy_source = state.get("proxy_source")
        if proxy_source is not None:
            self._sync_proxy_source_combo(str(proxy_source))
        self._sync_custom_proxy_api_visible()

        self._refresh_ip_cost_infobar()

    def apply_config(self, cfg: RuntimeConfig):
        self.url_edit.setText(cfg.url)
        self.target_spin.setValue(max(1, int(cfg.target or 1)))
        self.thread_spin.setValue(max(1, int(cfg.threads or 1)))
        # 阻塞信号避免加载配置时触发弹窗或多余同步
        self.random_ip_cb.blockSignals(True)
        self.random_ip_cb.setChecked(bool(cfg.random_ip_enabled))
        self.random_ip_cb.blockSignals(False)
        self._sync_random_ip_toggle_presentation(bool(cfg.random_ip_enabled))
        self._sync_proxy_source_combo(getattr(cfg, "proxy_source", _PROXY_SOURCE_DEFAULT))
        self._sync_custom_proxy_api_text(getattr(cfg, "custom_proxy_api", ""))
        self._sync_custom_proxy_api_visible(getattr(cfg, "proxy_source", _PROXY_SOURCE_DEFAULT))

        self._refresh_entry_table()
        self._sync_start_button_state()
        self._refresh_ip_cost_infobar()

    def _go_to_runtime_page(self) -> None:
        main_win = self.window()
        if hasattr(main_win, "switchTo") and hasattr(main_win, "runtime_page"):
            main_win.switchTo(main_win.runtime_page)

    def _go_to_runtime_answer_duration(self):
        self._go_to_runtime_page()
        try:
            if hasattr(self.runtime_page, "focus_answer_duration_setting"):
                self.runtime_page.focus_answer_duration_setting()
        except Exception as exc:
            log_suppressed_exception("_go_to_runtime_answer_duration", exc, level=logging.WARNING)

    def build_base_config(self) -> RuntimeConfig:
        cfg = RuntimeConfig()
        cfg.url = self.url_edit.text().strip()
        cfg.survey_title = str(self._survey_title or "")
        snapshot_getter = getattr(self.controller, "get_survey_snapshot", None)
        raw_survey_snapshot = snapshot_getter() if callable(snapshot_getter) else {}
        survey_snapshot = raw_survey_snapshot if isinstance(raw_survey_snapshot, dict) else {}
        controller_provider = str(
            (survey_snapshot or {}).get("survey_provider")
            or getattr(self.controller, "survey_provider", "")
            or "wjx"
        )
        cfg.survey_provider = detect_survey_provider(
            cfg.url,
            default=controller_provider,
        )
        writer = getattr(self.controller, "write_runtime_ui_state_to_config", None)
        if callable(writer):
            writer(cfg)
            raw_survey_snapshot = snapshot_getter() if callable(snapshot_getter) else {}
            survey_snapshot = raw_survey_snapshot if isinstance(raw_survey_snapshot, dict) else {}
            cfg.survey_provider = detect_survey_provider(
                cfg.url,
                default=str(
                    (survey_snapshot or {}).get("survey_provider")
                    or getattr(self.controller, "survey_provider", "")
                    or cfg.survey_provider
                ),
            )
        else:
            self.runtime_page.update_config(cfg)
            cfg.target = max(1, self.target_spin.value())
            cfg.threads = max(1, self.thread_spin.value())
            cfg.random_ip_enabled = self.random_ip_cb.isChecked()
        try:
            source = self._selected_proxy_source()
            cfg.proxy_source = source
            cfg.custom_proxy_api = (
                self.custom_proxy_api_edit.text().strip()
                if source == _PROXY_SOURCE_CUSTOM and hasattr(self, "custom_proxy_api_edit")
                else ""
            )
        except Exception as exc:
            log_suppressed_exception(
                "build_base_config: proxy source",
                exc,
                level=logging.WARNING,
            )
        cfg.answer_rules = list(self.strategy_page.get_rules() or [])
        cfg.dimension_groups = list(self.strategy_page.get_dimension_groups() or [])
        return cfg

    def _build_config(self) -> RuntimeConfig:
        coordinator = getattr(self, "run_coordinator", None)
        if coordinator is not None:
            return coordinator.build_config()
        return self.build_base_config()

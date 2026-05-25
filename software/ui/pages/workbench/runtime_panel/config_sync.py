"""运行参数页配置读写同步。"""

from __future__ import annotations

import logging
from typing import Any, cast

from software.io.config import RuntimeConfig
from software.logging.log_utils import log_suppressed_exception
from software.ui.pages.workbench.runtime_panel.cards import TimeRangeSettingCard
from software.ui.pages.workbench.runtime_panel.proxy_source import (
    PROXY_SOURCE_CUSTOM,
    PROXY_SOURCE_DEFAULT,
    normalize_proxy_source,
)


class RuntimeConfigSyncMixin:
    controller: Any
    target_card: Any
    thread_card: Any
    headless_card: Any
    interval_card: TimeRangeSettingCard
    answer_card: TimeRangeSettingCard
    timed_card: Any
    random_ip_card: Any
    random_ua_card: Any
    reliability_card: Any
    ai_section: Any
    _suppress_headless_tip: bool
    MIN_THREADS: Any

    def update_config(self, cfg: RuntimeConfig):
        page = cast(Any, self)
        cfg.target = max(1, self.target_card.spinBox.value())
        cfg.threads = max(
            self.MIN_THREADS,
            min(
                page._resolve_thread_max(self.headless_card.isChecked()),
                self.thread_card.slider.value(),
            ),
        )
        cfg.browser_preference = []
        cfg.submit_interval = self._card_value_as_range(self.interval_card)
        cfg.answer_duration = self._card_value_as_range(self.answer_card)
        cfg.timed_mode_enabled = self.timed_card.switchButton.isChecked()
        cfg.random_ip_enabled = self.random_ip_card.switchButton.isChecked()
        cfg.random_ua_enabled = self.random_ua_card.switchButton.isChecked()
        cfg.random_ua_ratios = (
            self.random_ua_card.getRatios()
            if cfg.random_ua_enabled
            else {"wechat": 33, "mobile": 33, "pc": 34}
        )
        cfg.fail_stop_enabled = True
        cfg.pause_on_aliyun_captcha = True
        cfg.reliability_mode_enabled = self.reliability_card.switchButton.isChecked()
        try:
            cfg.psycho_target_alpha = self.reliability_card.get_alpha()
        except Exception as exc:
            log_suppressed_exception(
                "update_config: reliability_card.get_alpha()",
                exc,
                level=logging.INFO,
            )
        cfg.headless_mode = self.headless_card.switchButton.isChecked()
        try:
            source = page.selected_proxy_source()
            cfg.proxy_source = source
            cfg.custom_proxy_api = (
                self.random_ip_card.customApiEdit.text().strip()
                if source == PROXY_SOURCE_CUSTOM
                else ""
            )
            cfg.proxy_area_code = self.random_ip_card.get_area_code()
        except Exception:
            cfg.proxy_source = PROXY_SOURCE_DEFAULT
            cfg.custom_proxy_api = ""
            cfg.proxy_area_code = None
        self.ai_section.update_config(cfg)

    def apply_config(self, cfg: RuntimeConfig):
        page = cast(Any, self)
        self.target_card.spinBox.setValue(max(1, cfg.target))
        self.interval_card.setValue(self._range_start_value(cfg.submit_interval))
        self.answer_card.setValue(self._range_start_value(cfg.answer_duration))

        self.timed_card.switchButton.setChecked(cfg.timed_mode_enabled)
        page._sync_timed_mode(cfg.timed_mode_enabled)

        self.random_ip_card.switchButton.blockSignals(True)
        self.random_ip_card.switchButton.setChecked(cfg.random_ip_enabled)
        self.random_ip_card.switchButton.blockSignals(False)
        self.random_ip_card._sync_ip_enabled(cfg.random_ip_enabled)
        self.random_ua_card.switchButton.setChecked(cfg.random_ua_enabled)

        try:
            ratios = getattr(cfg, "random_ua_ratios", None)
            if ratios and isinstance(ratios, dict):
                self.random_ua_card.setRatios(ratios)
            else:
                self.random_ua_card.setRatios({"wechat": 33, "mobile": 33, "pc": 34})
        except Exception as exc:
            log_suppressed_exception(
                "apply_config: self.random_ua_card.setRatios(ratios)",
                exc,
                level=logging.WARNING,
            )
            self.random_ua_card.setRatios({"wechat": 33, "mobile": 33, "pc": 34})

        page._sync_random_ua(self.random_ua_card.switchButton.isChecked())
        self.reliability_card.switchButton.setChecked(
            getattr(cfg, "reliability_mode_enabled", True)
        )
        try:
            self.reliability_card.set_alpha(getattr(cfg, "psycho_target_alpha", 0.85))
            self.reliability_card._sync_enabled(self.reliability_card.switchButton.isChecked())
        except Exception as exc:
            log_suppressed_exception(
                "apply_config: reliability_card.set_alpha",
                exc,
                level=logging.INFO,
            )

        self._suppress_headless_tip = True
        try:
            self.headless_card.setChecked(getattr(cfg, "headless_mode", True))
            page._apply_thread_limit_by_headless(self.headless_card.isChecked())
            max_threads = page._resolve_thread_max(self.headless_card.isChecked())
            self.thread_card.slider.setValue(
                max(
                    self.MIN_THREADS,
                    min(max_threads, int(cfg.threads or self.MIN_THREADS)),
                )
            )
        finally:
            self._suppress_headless_tip = False

        try:
            proxy_source = normalize_proxy_source(
                getattr(cfg, "proxy_source", PROXY_SOURCE_DEFAULT)
            )
            custom_api = getattr(cfg, "custom_proxy_api", "")
            page.set_proxy_source(
                proxy_source,
                custom_api_url=str(custom_api or ""),
                emit_state=False,
                show_tip=False,
            )
            area_code = getattr(cfg, "proxy_area_code", None)
            self.random_ip_card.set_area_code(area_code)
        except Exception as exc:
            log_suppressed_exception(
                "apply_config: proxy source",
                exc,
                level=logging.WARNING,
            )
        self.ai_section.apply_config(cfg)
        self.controller.sync_runtime_ui_state_from_config(cfg)

    def _apply_runtime_ui_state(self, state: dict) -> None:
        page = cast(Any, self)
        target = state.get("target")
        if target is not None and int(self.target_card.spinBox.value()) != int(target):
            self.target_card.spinBox.blockSignals(True)
            self.target_card.spinBox.setValue(max(1, int(target)))
            self.target_card.spinBox.blockSignals(False)

        threads = state.get("threads")
        headless = state.get("headless_mode")
        if headless is not None and bool(self.headless_card.switchButton.isChecked()) != bool(
            headless
        ):
            self._suppress_headless_tip = True
            try:
                self.headless_card.switchButton.blockSignals(True)
                self.headless_card.switchButton.setChecked(bool(headless))
            finally:
                self.headless_card.switchButton.blockSignals(False)
                self._suppress_headless_tip = False
        if headless is not None:
            page._apply_thread_limit_by_headless(bool(headless))
        if threads is not None and int(self.thread_card.slider.value()) != int(threads):
            self.thread_card.slider.blockSignals(True)
            self.thread_card.slider.setValue(max(1, int(threads)))
            self.thread_card.slider.blockSignals(False)

        random_ip_enabled = state.get("random_ip_enabled")
        if random_ip_enabled is not None and bool(
            self.random_ip_card.switchButton.isChecked()
        ) != bool(random_ip_enabled):
            self.random_ip_card.switchButton.blockSignals(True)
            self.random_ip_card.switchButton.setChecked(bool(random_ip_enabled))
            self.random_ip_card.switchButton.blockSignals(False)
            self.random_ip_card._sync_ip_enabled(bool(random_ip_enabled))

        timed_mode_enabled = state.get("timed_mode_enabled")
        if timed_mode_enabled is not None and bool(
            self.timed_card.switchButton.isChecked()
        ) != bool(timed_mode_enabled):
            self.timed_card.switchButton.blockSignals(True)
            self.timed_card.switchButton.setChecked(bool(timed_mode_enabled))
            self.timed_card.switchButton.blockSignals(False)
            page._sync_timed_mode(bool(timed_mode_enabled))

        answer_duration = state.get("answer_duration")
        if isinstance(answer_duration, (list, tuple)) and len(answer_duration) >= 2:
            current_value = int(self.answer_card.getValue())
            desired_value = self._range_start_value(answer_duration)
            if current_value != desired_value:
                self.answer_card.blockSignals(True)
                self.answer_card.setValue(desired_value)
                self.answer_card.blockSignals(False)

        proxy_source = state.get("proxy_source")
        if proxy_source is not None:
            normalized_proxy_source = normalize_proxy_source(str(proxy_source))
            if page.selected_proxy_source() != normalized_proxy_source:
                page.set_proxy_source(
                    normalized_proxy_source,
                    emit_state=False,
                    show_tip=False,
                )

    @staticmethod
    def _card_value_as_range(card: TimeRangeSettingCard) -> tuple[int, int]:
        value = max(0, int(card.getValue()))
        return value, value

    @staticmethod
    def _range_start_value(raw_range) -> int:
        if isinstance(raw_range, (list, tuple)):
            if raw_range:
                try:
                    return max(0, int(raw_range[0]))
                except Exception:
                    pass
            return 0
        try:
            return max(0, int(cast(Any, raw_range)))
        except Exception:
            return 0

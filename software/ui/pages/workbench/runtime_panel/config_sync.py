"""运行参数页配置读写同步。"""

from __future__ import annotations

import logging
from typing import Any, cast

from software.core.config.schema import RuntimeConfig
from software.logging.log_utils import log_suppressed_exception
from software.ui.pages.workbench.runtime_panel.cards import (
    AnswerDateTimeWindowSettingCard,
    TimeRangeSettingCard,
)
from software.ui.pages.workbench.runtime_panel.proxy_source import (
    PROXY_SOURCE_CUSTOM,
    PROXY_SOURCE_DEFAULT,
    normalize_proxy_source,
)


class RuntimeConfigSyncMixin:
    controller: Any
    target_card: Any
    thread_card: Any
    interval_card: TimeRangeSettingCard
    answer_duration_card: TimeRangeSettingCard
    answer_card: AnswerDateTimeWindowSettingCard
    random_ip_card: Any
    random_ua_card: Any
    reliability_card: Any
    ai_section: Any
    MIN_THREADS: Any

    def update_config(self, cfg: RuntimeConfig):
        page = cast(Any, self)
        cfg.target = max(1, self.target_card.spinBox.value())
        cfg.threads = max(
            self.MIN_THREADS,
            min(
                page._resolve_thread_max(),
                self.thread_card.slider.value(),
            ),
        )
        cfg.submit_interval = self._card_value_as_range(self.interval_card)
        cfg.answer_duration = self._card_value_as_range(self.answer_duration_card)
        cfg.answer_datetime_window = self.answer_card.getDateTimeWindow()
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
        self.interval_card.setRange(cfg.submit_interval)
        self.answer_duration_card.setRange(cfg.answer_duration)
        self.answer_card.setDateTimeWindow(getattr(cfg, "answer_datetime_window", ("", "")))
        page._sync_answer_datetime_window_card()

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

        page._apply_thread_limit()
        max_threads = page._resolve_thread_max()
        self.thread_card.slider.setValue(
            max(
                self.MIN_THREADS,
                min(max_threads, int(cfg.threads or self.MIN_THREADS)),
            )
        )

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
        page._apply_thread_limit()
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

        submit_interval = state.get("submit_interval")
        if submit_interval is not None:
            self._sync_range_card_from_state(self.interval_card, submit_interval)

        answer_duration = state.get("answer_duration")
        if answer_duration is not None:
            self._sync_range_card_from_state(self.answer_duration_card, answer_duration)

        answer_datetime_window = state.get("answer_datetime_window")
        if answer_datetime_window is not None:
            self._sync_datetime_window_card_from_state(self.answer_card, answer_datetime_window)

        proxy_source = state.get("proxy_source")
        if proxy_source is not None:
            normalized_proxy_source = normalize_proxy_source(str(proxy_source))
            if page.selected_proxy_source() != normalized_proxy_source:
                page.set_proxy_source(
                    normalized_proxy_source,
                    emit_state=False,
                    show_tip=False,
                )
        page._sync_answer_datetime_window_card()

    @staticmethod
    def _card_value_as_range(card: TimeRangeSettingCard) -> tuple[int, int]:
        return card.getRange()

    @staticmethod
    def _range_value(raw_range) -> tuple[int, int]:
        if isinstance(raw_range, (list, tuple)):
            try:
                low = max(0, int(raw_range[0] if len(raw_range) >= 1 else 0))
                high = max(low, int(raw_range[1] if len(raw_range) >= 2 else low))
                return low, high
            except Exception:
                return 0, 0
        try:
            value = max(0, int(cast(Any, raw_range)))
            return value, value
        except Exception:
            return 0, 0

    def _sync_range_card_from_state(
        self,
        card: TimeRangeSettingCard,
        raw_range,
    ) -> None:
        current_value = card.getRange()
        desired_value = self._range_value(raw_range)
        if current_value == desired_value:
            return
        card.blockSignals(True)
        try:
            card.setRange(desired_value)
        finally:
            card.blockSignals(False)

    def _sync_datetime_window_card_from_state(
        self,
        card: AnswerDateTimeWindowSettingCard,
        raw_window,
    ) -> None:
        desired_value = tuple(raw_window) if isinstance(raw_window, (list, tuple)) else ("", "")
        if card.getDateTimeWindow() == desired_value:
            return
        card.blockSignals(True)
        try:
            card.setDateTimeWindow(desired_value)
        finally:
            card.blockSignals(False)

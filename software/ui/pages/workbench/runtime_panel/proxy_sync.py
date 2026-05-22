"""运行参数页代理源同步。"""

from __future__ import annotations

import logging
from typing import Any, cast

from qfluentwidgets import InfoBar, InfoBarPosition

from software.logging.action_logger import log_action
from software.logging.log_utils import log_suppressed_exception
from software.ui.helpers.proxy_access import (
    apply_custom_proxy_api,
    apply_proxy_source_settings,
    get_proxy_minute_by_answer_seconds,
)
from software.ui.pages.workbench.runtime_panel.proxy_source import (
    PROXY_SOURCE_BENEFIT,
    PROXY_SOURCE_CUSTOM,
    PROXY_SOURCE_DEFAULT,
    normalize_proxy_source,
)


class RuntimeProxySyncMixin:
    controller: Any
    view: Any
    answer_card: Any
    interval_card: Any
    random_ip_card: Any
    _last_benefit_proxy_compatible: bool | None

    @staticmethod
    def _normalize_proxy_source(source: str) -> str:
        return normalize_proxy_source(source)

    def selected_proxy_source(self) -> str:
        idx = self.random_ip_card.proxyCombo.currentIndex()
        source = (
            str(self.random_ip_card.proxyCombo.itemData(idx)) if idx >= 0 else PROXY_SOURCE_DEFAULT
        )
        return normalize_proxy_source(source)

    def _get_selected_proxy_source(self) -> str:
        return self.selected_proxy_source()

    def set_proxy_source(
        self,
        source: str,
        custom_api_url: str | None = None,
        *,
        emit_state: bool = True,
        show_tip: bool = True,
    ) -> str:
        normalized = normalize_proxy_source(source)
        combo = self.random_ip_card.proxyCombo
        index = combo.findData(normalized)
        if index < 0:
            normalized = PROXY_SOURCE_DEFAULT
            index = combo.findData(normalized)
        if index >= 0 and combo.currentIndex() != index:
            combo.blockSignals(True)
            try:
                combo.setCurrentIndex(index)
            finally:
                combo.blockSignals(False)
        if custom_api_url is not None:
            self.random_ip_card.customApiEdit.setText(str(custom_api_url or ""))
        self.random_ip_card._on_source_changed()
        self._apply_proxy_source_settings(normalized)
        self._evaluate_benefit_proxy_compatibility(
            show_tip=bool(show_tip and normalized == PROXY_SOURCE_BENEFIT)
        )
        if emit_state:
            self.controller.set_runtime_ui_state(proxy_source=normalized)
        return normalized

    def set_custom_proxy_api(self, api_url: str) -> None:
        value = str(api_url or "").strip()
        self.random_ip_card.customApiEdit.setText(value)
        if self.selected_proxy_source() == PROXY_SOURCE_CUSTOM:
            try:
                apply_custom_proxy_api(value if value else None)
            except Exception as exc:
                log_suppressed_exception(
                    "set_custom_proxy_api: apply_custom_proxy_api",
                    exc,
                    level=logging.WARNING,
                )
            self._apply_proxy_source_settings(PROXY_SOURCE_CUSTOM)

    def _apply_proxy_source_settings(self, source: str) -> None:
        try:
            if source == PROXY_SOURCE_CUSTOM:
                api_url = self.random_ip_card.customApiEdit.text().strip()
                apply_proxy_source_settings(source, custom_api_url=api_url if api_url else None)
                return
            apply_proxy_source_settings(source, custom_api_url=None)
        except Exception as exc:
            log_suppressed_exception(
                "_apply_proxy_source_settings",
                exc,
                level=logging.WARNING,
            )

    def _current_survey_provider(self) -> str:
        try:
            return str(
                getattr(self.controller, "survey_provider", "")
                or self.controller.get_runtime_ui_state().get("survey_provider")
                or "wjx"
            ).strip().lower()
        except Exception:
            return "wjx"

    def _current_proxy_required_minute_for_benefit(self) -> int:
        try:
            return int(
                get_proxy_minute_by_answer_seconds(
                    self.answer_card.getValue(),
                    survey_provider=self._current_survey_provider(),
                )
            )
        except Exception as exc:
            log_suppressed_exception(
                "_current_proxy_required_minute_for_benefit",
                exc,
                level=logging.WARNING,
            )
            return 1

    def _show_benefit_proxy_limit_tip(self, minute: int) -> None:
        parent = cast(Any, self).window() or self.view
        if self._current_survey_provider() == "wjx":
            content = (
                "问卷星链路会固定拿 1 分钟代理。"
                "限时福利源仍然只支持少部分城市，不适合长时间保活。"
            )
        else:
            content = (
                f"当前作答时长会要求 {minute} 分钟代理，"
                "但“限时福利”只支持 1 分钟。请切回默认代理源，"
                "或缩短作答时长后再试。"
            )
        InfoBar.warning(
            "",
            content,
            parent=parent,
            position=InfoBarPosition.TOP,
            duration=4500,
        )

    def _evaluate_benefit_proxy_compatibility(self, *, show_tip: bool) -> bool:
        if self.selected_proxy_source() != PROXY_SOURCE_BENEFIT:
            self._last_benefit_proxy_compatible = None
            return True
        minute = self._current_proxy_required_minute_for_benefit()
        compatible = minute <= 1
        previous = self._last_benefit_proxy_compatible
        self._last_benefit_proxy_compatible = compatible
        if show_tip and (not compatible) and previous is not False:
            self._show_benefit_proxy_limit_tip(minute)
        return compatible

    def _on_proxy_source_changed(self):
        source = self.set_proxy_source(
            self.selected_proxy_source(),
            emit_state=True,
            show_tip=True,
        )
        log_action(
            "CONFIG",
            "change_proxy_source",
            "proxy_source_combo",
            "runtime",
            result="changed",
            payload={"source": source},
        )

    def _on_time_settings_changed(self, _value: int):
        self._evaluate_benefit_proxy_compatibility(show_tip=True)
        page = cast(Any, self)
        self.controller.set_runtime_ui_state(
            submit_interval=page._card_value_as_range(self.interval_card),
            answer_duration=page._card_value_as_range(self.answer_card),
        )

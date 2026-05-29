"""Workbench shared random IP toggle row."""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    IndicatorPosition,
    IndeterminateProgressRing,
    SwitchButton,
    TogglePushButton,
)

from software.ui.helpers.qfluent_compat import set_indeterminate_progress_ring_active
from software.ui.widgets.setting_cards import set_widget_enabled_with_opacity


class RandomIpToggleRow(QWidget):
    """Shared random IP toggle row used by dashboard and reverse fill pages."""

    def __init__(
        self,
        loading_label_cls: Any,
        parent: QWidget | None = None,
        *,
        use_switch_style: bool = False,
        leading_label_text: str | None = None,
        stretch_tail: bool = True,
    ) -> None:
        super().__init__(parent)
        self._use_switch_style = bool(use_switch_style)
        self.leading_label = cast(
            BodyLabel | None,
            loading_label_cls(leading_label_text, self) if leading_label_text else None,
        )
        if self._use_switch_style:
            self.toggle_button = cast(Any, SwitchButton(self, IndicatorPosition.RIGHT))
            self.toggle_button.setOnText("开")
            self.toggle_button.setOffText("关")
        else:
            self.toggle_button = cast(Any, TogglePushButton(self))
            self.toggle_button.setMinimumHeight(36)
        self.loading_ring = IndeterminateProgressRing(self)
        self.loading_ring.setFixedSize(18, 18)
        self.loading_ring.setStrokeWidth(2)
        self.loading_ring.hide()
        self.loading_label = cast(BodyLabel, loading_label_cls("", self))
        self.loading_label.hide()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        if self.leading_label is not None:
            layout.addWidget(self.leading_label)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.loading_ring)
        layout.addWidget(self.loading_label)
        if stretch_tail:
            layout.addStretch(1)

        self.sync_toggle_presentation(False)

    def sync_toggle_presentation(self, enabled: bool) -> None:
        active = bool(enabled)
        if self._use_switch_style:
            self.toggle_button.setChecked(active)
            return
        self.toggle_button.setText("已启用随机ip" if active else "点击启用随机ip")
        self.toggle_button.setIcon(FluentIcon.VIEW if active else FluentIcon.HIDE)

    def set_loading(self, loading: bool, message: str = "") -> None:
        active = bool(loading)
        text = str(message or "正在处理...") if active else ""
        set_indeterminate_progress_ring_active(self.loading_ring, active)
        self.loading_label.setVisible(active)
        self.loading_label.setText(text)
        set_widget_enabled_with_opacity(self.toggle_button, not active)
        self.sync_toggle_presentation(self.toggle_button.isChecked())

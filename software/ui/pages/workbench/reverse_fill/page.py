"""问卷星 Excel 反填管理页。"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Sequence

from PySide6.QtCore import QEvent, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QToolButton, QWidget
from qfluentwidgets import (
    CaptionLabel,
    InfoBar,
    IndeterminateProgressRing,
    LineEdit,
    PushButton,
    PrimaryPushButton,
    ProgressBar,
    StrongBodyLabel,
    TableWidget,
)

from software.core.reverse_fill.schema import (
    REVERSE_FILL_FORMAT_AUTO,
    REVERSE_FILL_FORMAT_WJX_SCORE,
    REVERSE_FILL_FORMAT_WJX_SEQUENCE,
    REVERSE_FILL_FORMAT_WJX_TEXT,
    ReverseFillSpec,
)
from software.io.config import RuntimeConfig
from software.providers.common import SURVEY_PROVIDER_WJX, normalize_survey_provider
from software.providers.contracts import (
    SurveyQuestionMeta,
    ensure_survey_question_metas,
)
from software.ui.pages.workbench.reverse_fill.actions import (
    apply_excel_source_path,
    bind_reverse_fill_events,
    browse_excel_file,
    extract_excel_path_from_drop,
    mime_has_excel_file,
    on_parse_clicked,
    on_reverse_fill_threads_changed,
    on_start_clicked,
    on_survey_parse_failed,
    on_survey_parsed,
    on_url_text_changed,
    open_wizard,
    prepare_reverse_fill_start_target,
    validate_reverse_fill_start_url,
)
from software.ui.pages.workbench.reverse_fill.preview import (
    clear_tables,
    populate_plan_table,
    refresh_preview,
)
from software.ui.pages.workbench.reverse_fill.ui_builder import build_reverse_fill_page_ui
from software.ui.pages.workbench.shared.clipboard import SurveyClipboardMixin
from software.ui.pages.workbench.shared.run_feedback import (
    get_completion_notified,
    get_last_progress,
    init_run_feedback_state,
    set_completion_notified,
    set_last_pause_reason,
    set_last_progress,
    set_show_end_toast_after_cleanup,
    show_feedback_toast,
    get_show_end_toast_after_cleanup,
)

if TYPE_CHECKING:
    from software.ui.controller.run_controller import RunController
    from software.ui.pages.workbench.shared.random_ip_toggle_row import RandomIpToggleRow
    from software.ui.pages.workbench.shared.survey_entry_card import SurveyEntryCard
    from software.ui.widgets.no_wheel import NoWheelSpinBox
    from qfluentwidgets import (
        IndeterminateProgressBar,
        InfoBadge,
        ScrollArea,
        SimpleCardWidget,
        TogglePushButton,
    )


_FORMAT_CHOICES = [
    (REVERSE_FILL_FORMAT_AUTO, "自动识别 (推荐)"),
    (REVERSE_FILL_FORMAT_WJX_SEQUENCE, "问卷星按序号"),
    (REVERSE_FILL_FORMAT_WJX_SCORE, "问卷星按分数"),
    (REVERSE_FILL_FORMAT_WJX_TEXT, "问卷星按文本"),
]


class ReverseFillPage(SurveyClipboardMixin, QWidget):
    """独立的反填数据源页。"""

    surveyUrlChanged = Signal(str)
    scroll_area: "ScrollArea"
    view: QWidget
    link_card: "SurveyEntryCard"
    file_panel: "SimpleCardWidget"
    table_panel: "SimpleCardWidget"
    preview_badge: "InfoBadge"
    qr_btn: QToolButton
    url_edit: LineEdit
    file_edit: LineEdit
    browse_btn: "PushButton"
    open_wizard_btn: PrimaryPushButton
    reverse_fill_threads_spin: "NoWheelSpinBox"
    random_ip_row: "RandomIpToggleRow"
    random_ip_cb: "TogglePushButton"
    random_ip_loading_ring: IndeterminateProgressRing
    random_ip_loading_label: CaptionLabel
    detected_format_label: StrongBodyLabel | CaptionLabel
    state_hint_label: CaptionLabel
    mapping_table: TableWidget
    status_label: StrongBodyLabel
    progress_bar: ProgressBar
    progress_indeterminate_bar: "IndeterminateProgressBar"
    progress_pct: StrongBodyLabel
    start_btn: PrimaryPushButton
    resume_btn: PrimaryPushButton
    stop_btn: "PushButton"

    def __init__(self, controller: "RunController", parent=None):
        super().__init__(parent)
        self.controller = controller
        self._questions_info: List[SurveyQuestionMeta] = []
        self._question_entries: List[Any] = []
        self._survey_provider: str = ""
        self._survey_title: str = ""
        self._parsed_url: str = ""
        self._reverse_fill_threads_value: int = 1
        self._selected_format_value: str = REVERSE_FILL_FORMAT_AUTO
        self._start_row_value: int = 1
        self._last_spec: Optional[ReverseFillSpec] = None
        self._last_error: str = ""
        self._open_wizard_handler: Optional[Callable[[List[int]], None]] = None
        self._run_coordinator: Optional[Any] = None
        self._issue_question_nums: List[int] = []
        self._clipboard_parse_ticket = 0
        self._parse_requested_from_reverse_fill = False
        init_run_feedback_state(self)
        self._main_progress_indeterminate = False

        self.setObjectName("reverseFillPage")

        build_reverse_fill_page_ui(self)
        self._bind_events()
        self._refresh_preview()
        self._sync_start_button_state()

    def _bind_events(self) -> None:
        bind_reverse_fill_events(self)

    def set_open_wizard_handler(self, handler: Optional[Callable[[List[int]], None]]) -> None:
        self._open_wizard_handler = handler

    def set_run_coordinator(self, coordinator: Any) -> None:
        self._run_coordinator = coordinator

    def set_question_context(
        self,
        questions_info: Sequence[SurveyQuestionMeta],
        question_entries: Sequence[Any],
        *,
        survey_title: str = "",
        survey_provider: str = "",
    ) -> None:
        self._questions_info = ensure_survey_question_metas(questions_info or [])
        self._question_entries = list(copy.deepcopy(list(question_entries or [])))
        self._survey_title = str(survey_title or "").strip()
        self._survey_provider = str(survey_provider or "").strip()
        if self._questions_info:
            self._parsed_url = self.url_edit.text().strip()
        self._refresh_preview()
        self._sync_start_button_state()

    def update_config(self, cfg: RuntimeConfig) -> None:
        cfg.reverse_fill_source_path = self.file_edit.text().strip()
        cfg.reverse_fill_enabled = bool(cfg.reverse_fill_source_path)
        cfg.reverse_fill_format = self._selected_format()
        cfg.reverse_fill_start_row = max(1, int(self._start_row_value or 1))
        cfg.reverse_fill_threads = max(1, int(self._reverse_fill_threads_value or 1))
        if cfg.reverse_fill_enabled:
            cfg.threads = max(1, int(cfg.reverse_fill_threads or 1))

    def apply_config(self, cfg: RuntimeConfig) -> None:
        self.url_edit.blockSignals(True)
        self.url_edit.setText(str(getattr(cfg, "url", "") or ""))
        self.url_edit.blockSignals(False)
        self.file_edit.setText(str(getattr(cfg, "reverse_fill_source_path", "") or ""))
        self._start_row_value = max(1, int(getattr(cfg, "reverse_fill_start_row", 1) or 1))
        self._reverse_fill_threads_value = max(
            1,
            int(getattr(cfg, "reverse_fill_threads", getattr(cfg, "threads", 1)) or 1),
        )
        self.reverse_fill_threads_spin.blockSignals(True)
        self.reverse_fill_threads_spin.setValue(self._reverse_fill_threads_value)
        self.reverse_fill_threads_spin.blockSignals(False)

        selected_format = str(
            getattr(cfg, "reverse_fill_format", REVERSE_FILL_FORMAT_AUTO)
            or REVERSE_FILL_FORMAT_AUTO
        )
        valid_formats = {value for value, _label in _FORMAT_CHOICES}
        self._selected_format_value = (
            selected_format if selected_format in valid_formats else REVERSE_FILL_FORMAT_AUTO
        )
        self._refresh_preview()

    def _selected_format(self) -> str:
        return str(self._selected_format_value or REVERSE_FILL_FORMAT_AUTO)

    def eventFilter(self, watched, event):
        if watched in getattr(self, "_file_drop_widgets", ()):
            if event.type() == QEvent.Type.DragEnter:
                if not self._has_survey_link_text():
                    return False
                if isinstance(event, QDragEnterEvent) and self._mime_has_excel_file(event):
                    event.acceptProposedAction()
                    return True
                return False
            if event.type() == QEvent.Type.Drop:
                if not self._has_survey_link_text():
                    return False
                if isinstance(event, QDropEvent):
                    file_path = self._extract_excel_path_from_drop(event)
                    if file_path:
                        self._apply_excel_source_path(file_path)
                        event.acceptProposedAction()
                        return True
                return False
        return super().eventFilter(watched, event)

    def _toast(
        self,
        message: str,
        level: str = "warning",
        duration: int = 2400,
        show_progress: bool = False,
    ) -> Optional[InfoBar]:
        return show_feedback_toast(
            self,
            message,
            level=level,
            duration=duration,
            show_progress=show_progress,
            title="反填页提示",
        )

    def _has_question_entries(self) -> bool:
        try:
            coordinator = getattr(self, "_run_coordinator", None)
            if coordinator is not None:
                return bool(coordinator.has_question_entries())
        except Exception:
            pass
        return False

    def _has_excel_source_path(self) -> bool:
        return bool(self.file_edit.text().strip())

    def _has_survey_link_text(self) -> bool:
        return bool(self.url_edit.text().strip())

    def _sync_random_ip_toggle_presentation(self, enabled: bool) -> None:
        self.random_ip_row.sync_toggle_presentation(enabled)

    def _apply_runtime_ui_state(self, state: dict) -> None:
        enabled = bool((state or {}).get("random_ip_enabled", False))
        if bool(self.random_ip_cb.isChecked()) != enabled:
            self.random_ip_cb.blockSignals(True)
            self.random_ip_cb.setChecked(enabled)
            self.random_ip_cb.blockSignals(False)
        self._sync_random_ip_toggle_presentation(enabled)

    def set_random_ip_loading(self, loading: bool, message: str = "") -> None:
        self.random_ip_row.set_loading(loading, message)

    def _on_random_ip_toggled(self, enabled: bool) -> None:
        self._sync_random_ip_toggle_presentation(bool(enabled))
        if self.controller.request_toggle_random_ip(bool(enabled), adapter=self.controller.adapter):
            return
        fallback_enabled = bool(
            self.controller.get_runtime_ui_state().get("random_ip_enabled", False)
        )
        self.random_ip_cb.blockSignals(True)
        self.random_ip_cb.setChecked(fallback_enabled)
        self.random_ip_cb.blockSignals(False)
        self._sync_random_ip_toggle_presentation(fallback_enabled)

    def _sync_start_button_state(self, running: Optional[bool] = None) -> None:
        if running is None:
            running = bool(getattr(self.controller, "running", False))
        enabled = (
            (not bool(running)) and self._has_question_entries() and self._has_excel_source_path()
        )
        self.start_btn.setEnabled(enabled)

    def _set_main_progress_indeterminate(self, enabled: bool) -> None:
        flag = bool(enabled)
        if flag == self._main_progress_indeterminate:
            return
        self._main_progress_indeterminate = flag
        if flag:
            self.progress_bar.hide()
            self.progress_indeterminate_bar.show()
            self.progress_pct.setText("...")
            return
        self.progress_indeterminate_bar.hide()
        self.progress_bar.show()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(max(0, min(100, get_last_progress(self))))

    def update_status(self, text: str, current: int, target: int) -> None:
        if str(text or "").strip() == "正在初始化":
            self.status_label.setText("正在初始化")
            self._set_main_progress_indeterminate(True)
            self.progress_pct.setText("...")
            set_last_progress(self, 0)
            return

        self._set_main_progress_indeterminate(False)
        status_text = str(text or "").strip() or "等待配置..."
        self.status_label.setText(status_text)
        progress = 0
        if int(target or 0) > 0:
            progress = min(100, int((int(current or 0) / max(int(target or 0), 1)) * 100))
        self.progress_bar.setValue(progress)
        self.progress_pct.setText(f"{progress}%")
        set_last_progress(self, progress)
        if (
            int(target or 0) > 0
            and int(current or 0) >= int(target or 0)
            and not get_completion_notified(self)
        ):
            set_completion_notified(self, True)
            self.stop_btn.setEnabled(False)

    def on_run_state_changed(self, running: bool) -> None:
        self._sync_start_button_state(running=running)
        self.stop_btn.setEnabled(bool(running))
        if running:
            self.resume_btn.setEnabled(False)
            self.resume_btn.hide()
            set_completion_notified(self, False)
            self.start_btn.setText("执行中...")
            self.start_btn.setEnabled(False)
            return

        self.resume_btn.setEnabled(False)
        self.resume_btn.hide()
        self._set_main_progress_indeterminate(False)
        if get_completion_notified(self) or get_last_progress(self) >= 100:
            self.start_btn.setText("重新开始")
        else:
            self.start_btn.setText("开始执行")
        self._sync_start_button_state(running=False)
        self.stop_btn.setEnabled(False)
        if not get_completion_notified(self):
            set_show_end_toast_after_cleanup(self, True)

    def on_pause_state_changed(self, paused: bool, reason: str = "") -> None:
        set_last_pause_reason(self, reason)
        if not getattr(self.controller, "running", False):
            self.resume_btn.setEnabled(False)
            self.resume_btn.hide()
            return
        if paused:
            self.resume_btn.show()
            self.resume_btn.setEnabled(True)
            msg = f"已暂停：{reason}" if reason else "已暂停"
            self._toast(msg, "warning", 2200)
            return
        self.resume_btn.setEnabled(False)
        self.resume_btn.hide()

    def on_cleanup_finished(self) -> None:
        if not get_show_end_toast_after_cleanup(self):
            return
        set_show_end_toast_after_cleanup(self, False)

    def _on_start_clicked(self) -> None:
        on_start_clicked(self)

    def _prepare_reverse_fill_start_target(self) -> bool:
        return prepare_reverse_fill_start_target(self)

    def _on_resume_clicked(self) -> None:
        coordinator = getattr(self, "_run_coordinator", None)
        if coordinator is None:
            self._toast("主页尚未完成初始化，暂时不能继续执行", "error", duration=3000)
            return
        coordinator.resume()

    def _context_ready(self) -> bool:
        provider = normalize_survey_provider(self._survey_provider, default="")
        current_url = self.url_edit.text().strip()
        return (
            provider == SURVEY_PROVIDER_WJX
            and bool(self._questions_info)
            and bool(self._parsed_url)
            and current_url == self._parsed_url
        )

    def _validate_reverse_fill_start_url(self) -> bool:
        return validate_reverse_fill_start_url(self)

    def _browse_excel_file(self) -> None:
        browse_excel_file(self)

    def _on_reverse_fill_threads_changed(self, value: int) -> None:
        on_reverse_fill_threads_changed(self, value)

    def _mime_has_excel_file(self, event: QDragEnterEvent | QDropEvent) -> bool:
        return mime_has_excel_file(event)

    def _extract_excel_path_from_drop(self, event: QDropEvent) -> str:
        return extract_excel_path_from_drop(self, event)

    def _apply_excel_source_path(self, file_path: str) -> None:
        apply_excel_source_path(self, file_path)

    def _on_parse_clicked(self) -> None:
        on_parse_clicked(self)

    def _on_url_text_changed(self, text: str) -> None:
        on_url_text_changed(self, text)

    def _on_survey_parsed(self, info: list, title: str) -> None:
        on_survey_parsed(self, info, title)

    def _on_survey_parse_failed(self, error_msg: str) -> None:
        on_survey_parse_failed(self, error_msg)

    def _open_wizard(self) -> None:
        open_wizard(self)

    def _clear_tables(self) -> None:
        clear_tables(self)

    def _populate_plan_table(self, spec: ReverseFillSpec) -> None:
        populate_plan_table(self, spec)

    def _refresh_preview(self) -> None:
        refresh_preview(self)

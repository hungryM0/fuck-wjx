from __future__ import annotations

import logging
from typing import Any, List, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialog, QWidget

from software.core.questions.config import QuestionEntry
from software.core.config.schema import RuntimeConfig
from software.core.config.codec import build_runtime_config_snapshot
from software.logging.action_logger import log_action
from software.providers.contracts import (
    SurveyQuestionMeta,
    ensure_survey_question_metas,
)
from software.ui.pages.workbench.question_editor.add_dialog import (
    QuestionAddDialog,
)
from software.ui.pages.workbench.question_editor.utils import (
    build_entry_info_list,
)


class WorkbenchState(QObject):
    entriesChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: List[QuestionEntry] = []
        self._questions_info: List[SurveyQuestionMeta] = []
        self._entry_questions_info: List[SurveyQuestionMeta] = []

    @property
    def entries(self) -> List[QuestionEntry]:
        return self._entries

    @property
    def questions_info(self) -> List[SurveyQuestionMeta]:
        return self._questions_info

    @property
    def entry_questions_info(self) -> List[SurveyQuestionMeta]:
        return self._entry_questions_info

    def set_questions(self, info: List[SurveyQuestionMeta], entries: List[QuestionEntry]) -> None:
        normalized_info = ensure_survey_question_metas(info or [])
        self._questions_info = normalized_info
        self.set_entries(entries, normalized_info)

    def set_entries(
        self,
        entries: List[QuestionEntry],
        info: Optional[List[SurveyQuestionMeta]] = None,
    ) -> None:
        if info is not None:
            self._questions_info = ensure_survey_question_metas(info or [])
        self._entries = list(entries or [])
        self._entry_questions_info = build_entry_info_list(self._entries, self._questions_info)
        for idx, entry in enumerate(self._entries):
            if getattr(entry, "question_title", None):
                continue
            if idx < len(self._entry_questions_info):
                title = self._entry_questions_info[idx].get("title")
                if title:
                    entry.question_title = str(title).strip()
        self.entriesChanged.emit(len(self._entries))

    def get_entries(self) -> List[QuestionEntry]:
        return list(self._entries)

    def append_entry(self, entry: QuestionEntry) -> None:
        if not entry:
            return
        self._entries.append(entry)
        self._entry_questions_info = build_entry_info_list(self._entries, self._questions_info)
        self.entriesChanged.emit(len(self._entries))

    def open_add_question_dialog(self, parent: QWidget) -> bool:
        dialog = QuestionAddDialog(self._entries, parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        new_entry = dialog.get_entry()
        if not new_entry:
            return False
        self.append_entry(new_entry)
        return True

    def has_question_entries(self) -> bool:
        return bool(self._entries)


class WorkbenchRunCoordinator:
    def __init__(self, *, controller: Any, state: WorkbenchState, dashboard: Any) -> None:
        self.controller = controller
        self.state = state
        self.dashboard = dashboard
        self.reverse_fill_page: Optional[Any] = None
        self._reverse_fill_target_override: Optional[int] = None

    def bind_reverse_fill_page(self, page: Any) -> None:
        self.reverse_fill_page = page

    def has_question_entries(self) -> bool:
        return self.state.has_question_entries()

    def is_completed_run(self) -> bool:
        return bool(
            getattr(self.dashboard, "_completion_notified", False)
            or getattr(self.dashboard, "_last_progress", 0) >= 100
        )

    def set_reverse_fill_target(self, target: int) -> None:
        normalized_target = max(1, int(target or 1))
        self._reverse_fill_target_override = normalized_target
        try:
            updater = getattr(self.controller, "update_runtime_settings", None)
            if not callable(updater):
                updater = getattr(self.controller, "set_runtime_ui_state", None)
            if callable(updater):
                updater(target=normalized_target)
        except Exception:
            logging.debug("同步目标份数到运行态失败", exc_info=True)

    def build_config(self) -> RuntimeConfig:
        builder = getattr(self.dashboard, "config_builder", None)
        if callable(builder):
            cfg = builder()
            if not isinstance(cfg, RuntimeConfig):
                raise TypeError("config_builder 必须返回 RuntimeConfig")
            return cfg
        cfg = self.dashboard.build_base_config()
        if self.reverse_fill_page is not None:
            try:
                self.reverse_fill_page.update_config(cfg)
            except Exception:
                logging.debug("构建配置时同步反填配置失败", exc_info=True)
        return cfg

    def start(self, *, enable_reverse_fill: bool = False) -> bool:
        dashboard = self.dashboard
        if getattr(self.controller, "running", False):
            if getattr(dashboard, "_completion_notified", False):
                dashboard._pending_restart = True
                self.controller.stop_run()
                log_action(
                    "RUN",
                    "restart_run",
                    "start_btn",
                    "dashboard",
                    result="queued",
                )
                dashboard._toast("正在重新开始，请稍候...", "info", 1200)
            return False

        cfg = build_runtime_config_snapshot(
            self.build_config(),
            question_entries=self.state.get_entries(),
            questions_info=self.state.questions_info,
        )
        cfg.reverse_fill_enabled = bool(
            enable_reverse_fill and str(getattr(cfg, "reverse_fill_source_path", "") or "").strip()
        )
        if enable_reverse_fill and self._reverse_fill_target_override is not None:
            cfg.target = self._reverse_fill_target_override
        if not cfg.question_entries:
            log_action(
                "RUN",
                "start_run",
                "start_btn",
                "dashboard",
                result="blocked",
                level=logging.WARNING,
                payload={"reason": "no_question_entries"},
            )
            dashboard._toast(
                "未配置任何题目，无法开始执行（请先在'题目配置'页添加/配置题目）",
                "warning",
            )
            dashboard._sync_start_button_state(running=False)
            return False

        if self.is_completed_run():
            dashboard.progress_bar.setValue(0)
            dashboard.progress_pct.setText("0%")
            dashboard._last_progress = 0
            dashboard._completion_notified = False
            dashboard.status_label.setText(f"已提交 0/{cfg.target} 份 | 提交连续失败 0 次")

        self.controller.start_run(cfg)
        log_action(
            "RUN",
            "start_run",
            "start_btn",
            "dashboard",
            result="started",
            payload={
                "target": cfg.target,
                "threads": cfg.threads,
                "reverse_fill_enabled": cfg.reverse_fill_enabled,
            },
        )
        return True

    def start_reverse_fill(self) -> bool:
        return self.start(enable_reverse_fill=True)

    def resume(self) -> None:
        self.dashboard.resume_run_from_ui()

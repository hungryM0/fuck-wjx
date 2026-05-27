"""工作台页面装配与状态同步。"""

from __future__ import annotations

import copy
import logging
from typing import Any, List, Mapping, Sequence

from PySide6.QtCore import QTimer, Qt, Slot

from software.core.config.schema import RuntimeConfig
from software.core.config.codec import build_runtime_config_snapshot
from software.logging.action_logger import log_action
from software.providers.common import detect_survey_provider
from software.providers.contracts import (
    SurveyQuestionMeta,
    ensure_survey_question_metas,
)
from software.ui.pages.workbench.dashboard.page import DashboardPage
from software.ui.pages.workbench.reverse_fill.page import ReverseFillPage
from software.ui.pages.workbench.runtime_panel.main import RuntimePage
from software.ui.pages.workbench.session import (
    WorkbenchRunCoordinator,
    WorkbenchState,
)
from software.ui.pages.workbench.strategy.page import QuestionStrategyPage


class WorkbenchPresenter:
    """集中处理工作台内部页面关系，避免主窗口直接管页面细节。"""

    def __init__(self, *, controller: Any, host: Any) -> None:
        self.controller = controller
        self.host = host
        self.state = WorkbenchState(host)
        self.runtime_page = RuntimePage(controller, host)
        self.strategy_page = QuestionStrategyPage(host)
        self.dashboard = DashboardPage(
            controller,
            self.state,
            self.runtime_page,
            self.strategy_page,
            host,
        )
        self.run_coordinator = WorkbenchRunCoordinator(
            controller=controller,
            state=self.state,
            dashboard=self.dashboard,
        )
        self.dashboard.config_builder = self.build_current_config
        self.dashboard.set_run_coordinator(self.run_coordinator)
        self.reverse_fill_page = ReverseFillPage(controller, host)
        self.run_coordinator.bind_reverse_fill_page(self.reverse_fill_page)
        self.reverse_fill_page.set_run_coordinator(self.run_coordinator)
        self._configure_pages()
        self._bind_workbench_signals()

    def _configure_pages(self) -> None:
        self.dashboard.setObjectName("dashboard")
        self.runtime_page.setObjectName("runtime")
        self.strategy_page.setObjectName("strategy")
        self.reverse_fill_page.setObjectName("reverse_fill")
        self.reverse_fill_page.set_open_wizard_handler(self.open_reverse_fill_wizard)

    def _bind_workbench_signals(self) -> None:
        self.reverse_fill_page.surveyUrlChanged.connect(self.sync_dashboard_url_from_reverse_fill)
        self.dashboard.url_edit.textChanged.connect(self.sync_reverse_fill_url_from_dashboard)
        self.state.entriesChanged.connect(lambda _count: self.sync_reverse_fill_context())
        self.controller.surveyParsed.connect(
            self.on_survey_parsed,
            Qt.ConnectionType.QueuedConnection,
        )
        self.controller.surveyParseFailed.connect(
            self.on_survey_parse_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        self.controller.runStateChanged.connect(self.dashboard.on_run_state_changed)
        self.controller.runStateChanged.connect(self.reverse_fill_page.on_run_state_changed)
        self.controller.statusUpdated.connect(self.dashboard.update_status)
        self.controller.statusUpdated.connect(self.reverse_fill_page.update_status)
        self.controller.threadProgressUpdated.connect(self.dashboard.update_thread_progress)
        self.controller.pauseStateChanged.connect(self.dashboard.on_pause_state_changed)
        self.controller.pauseStateChanged.connect(self.reverse_fill_page.on_pause_state_changed)
        self.controller.cleanupFinished.connect(self.dashboard.on_cleanup_finished)
        self.controller.cleanupFinished.connect(self.reverse_fill_page.on_cleanup_finished)

    def apply_config(self, cfg: RuntimeConfig) -> None:
        self.runtime_page.apply_config(cfg)
        self.dashboard.apply_config(cfg)
        self.reverse_fill_page.apply_config(cfg)
        self.state.set_entries(cfg.question_entries or [], cfg.questions_info or [])
        self.strategy_page.set_questions_info(cfg.questions_info or [])
        self.strategy_page.set_entries(
            self.state.entries,
            self.state.entry_questions_info,
        )
        self.strategy_page.set_rules(getattr(cfg, "answer_rules", []) or [])
        self.strategy_page.set_dimension_groups(getattr(cfg, "dimension_groups", []) or [])
        self.dashboard.update_question_meta(cfg.survey_title or "", len(cfg.question_entries or []))
        self.sync_reverse_fill_context()

    def load_saved_config(self, *, strict: bool = False) -> RuntimeConfig:
        cfg = self.controller.load_saved_config(strict=strict)
        self.apply_config(cfg)
        self.controller.refresh_random_ip_counter()
        return cfg

    def load_config_from_path(self, path: str) -> RuntimeConfig:
        cfg = self.controller.load_saved_config(path, strict=True)
        self.apply_config(cfg)
        self.controller.refresh_random_ip_counter()
        return cfg

    def build_current_config(self) -> RuntimeConfig:
        cfg = self.dashboard.build_base_config()
        try:
            self.reverse_fill_page.update_config(cfg)
        except Exception:
            logging.debug("构建配置时同步反填配置失败", exc_info=True)
        return cfg

    def build_current_config_snapshot(self) -> RuntimeConfig:
        cfg = build_runtime_config_snapshot(
            self.build_current_config(),
            question_entries=self.state.get_entries(),
            questions_info=self.state.questions_info,
        )
        self.controller.config = cfg
        return cfg

    @Slot(list, str)
    def on_survey_parsed(self, info: list[Any], title: str) -> None:
        questions = ensure_survey_question_metas(info or [])
        parsed_title = title or "问卷"
        parsed_url = str(getattr(getattr(self.controller, "config", None), "url", "") or "")
        self.sync_dashboard_url_from_reverse_fill(parsed_url)
        self.sync_reverse_fill_url_from_dashboard(parsed_url)
        self.strategy_page.set_questions_info(questions)
        if getattr(self.dashboard, "_open_wizard_after_parse", False):
            self.dashboard._open_wizard_after_parse = False
            info_snapshot = copy.deepcopy(questions)
            QTimer.singleShot(
                0,
                lambda: self.open_parse_wizard_after_parse(info_snapshot, parsed_title),
            )
            return
        self.state.set_questions(questions, self.controller.question_entries)
        self.strategy_page.set_dimension_groups([])
        self.strategy_page.set_entries(
            self.state.entries,
            self.state.entry_questions_info,
        )
        self.dashboard.update_question_meta(parsed_title, len(self.controller.question_entries))
        self.sync_reverse_fill_context()

    @Slot(str)
    def on_survey_parse_failed(self, msg: str) -> None:
        text = str(msg or "").strip()
        if "问卷已暂停" in text:
            self.dashboard._open_wizard_after_parse = False
            return
        self.dashboard._open_wizard_after_parse = False

    def sync_reverse_fill_context(self) -> None:
        try:
            url_edit = getattr(self.dashboard, "url_edit", None)
            url_text = url_edit.text() if url_edit is not None and hasattr(url_edit, "text") else ""
            survey_provider = str(
                getattr(self.controller, "survey_provider", "")
                or getattr(
                    getattr(self.controller, "config", None),
                    "survey_provider",
                    "",
                )
                or detect_survey_provider(url_text, default="")
                or ""
            )
            self.reverse_fill_page.set_question_context(
                self.state.questions_info,
                self.state.get_entries(),
                survey_title=getattr(self.dashboard, "_survey_title", "") or "",
                survey_provider=survey_provider,
            )
        except Exception:
            logging.info("同步反填页上下文失败", exc_info=True)

    def sync_dashboard_url_from_reverse_fill(self, url: str) -> None:
        text = str(url or "").strip()
        url_edit = getattr(self.dashboard, "url_edit", None)
        if url_edit is None or not hasattr(url_edit, "text") or not hasattr(url_edit, "setText"):
            return
        if str(url_edit.text() or "").strip() == text:
            return
        url_edit.blockSignals(True)
        url_edit.setText(text)
        url_edit.blockSignals(False)
        refresh_preview = getattr(self.reverse_fill_page, "_refresh_preview", None)
        if callable(refresh_preview):
            refresh_preview()

    def sync_reverse_fill_url_from_dashboard(self, url: str) -> None:
        text = str(url or "").strip()
        url_edit = getattr(self.reverse_fill_page, "url_edit", None)
        if url_edit is None or not hasattr(url_edit, "text") or not hasattr(url_edit, "setText"):
            return
        if str(url_edit.text() or "").strip() == text:
            return
        url_edit.blockSignals(True)
        url_edit.setText(text)
        url_edit.blockSignals(False)

    def open_reverse_fill_wizard(self, issue_question_nums: List[int]) -> None:
        info = list(self.state.questions_info or [])
        if not info:
            self.host._toast("当前还没有解析出题目，无法打开配置向导。", "warning")
            return
        issue_nums = {int(num) for num in list(issue_question_nums or []) if int(num) > 0}
        if not issue_nums:
            self.host._toast("当前没有需要处理的异常题目。", "warning")
            return
        self.open_parse_wizard_after_parse(
            copy.deepcopy(info),
            str(getattr(self.dashboard, "_survey_title", "") or "问卷"),
            issue_question_nums=sorted(issue_nums),
        )

    def open_parse_wizard_after_parse(
        self,
        info: Sequence[SurveyQuestionMeta | Mapping[str, Any]],
        parsed_title: str,
        *,
        issue_question_nums: List[int] | None = None,
    ) -> None:
        normalized_info = ensure_survey_question_metas(info or [])
        try:
            pending_entries = copy.deepcopy(self.controller.question_entries)
            selected_info: list[SurveyQuestionMeta | dict[str, Any]] = list(
                copy.deepcopy(normalized_info)
            )
            selected_entries = pending_entries
            selected_issue_nums = {
                int(num) for num in list(issue_question_nums or []) if int(num) > 0
            }
            if selected_issue_nums:
                info_by_num = {int(getattr(item, "num", 0) or 0): item for item in selected_info}
                entry_by_num = {
                    int(getattr(entry, "question_num", 0) or 0): entry
                    for entry in selected_entries
                    if int(getattr(entry, "question_num", 0) or 0) > 0
                }
                selected_info = [
                    copy.deepcopy(info_by_num[num])
                    for num in selected_issue_nums
                    if num in info_by_num
                ]
                selected_entries = [
                    copy.deepcopy(entry_by_num[num])
                    for num in selected_issue_nums
                    if num in entry_by_num
                ]
                if not selected_info or not selected_entries:
                    self.host._toast(
                        "异常题目配置数据不完整，暂时无法打开配置向导。",
                        "warning",
                    )
                    return
            accepted = self.dashboard.run_question_wizard(
                selected_entries, selected_info, parsed_title
            )
        except Exception as exc:
            logging.exception("自动配置向导打开失败")
            log_action(
                "UI",
                "open_parse_wizard",
                "question_wizard",
                "main_window",
                result="failed",
                level=logging.ERROR,
                detail=exc,
                payload={"question_count": len(normalized_info)},
            )
            current_entries = self.state.get_entries()
            self.dashboard.update_question_meta(parsed_title, len(current_entries))
            self.dashboard._toast(
                "自动配置向导打开失败，已保留原有题目设置；详细原因已写入日志",
                "error",
                duration=4200,
            )
            return

        if accepted:
            if selected_issue_nums:
                updated_entries_by_num = {
                    int(getattr(entry, "question_num", 0) or 0): entry
                    for entry in selected_entries
                    if int(getattr(entry, "question_num", 0) or 0) > 0
                }
                merged_entries = []
                for entry in pending_entries:
                    question_num = int(getattr(entry, "question_num", 0) or 0)
                    merged_entries.append(
                        copy.deepcopy(updated_entries_by_num.get(question_num, entry))
                    )
                pending_entries = merged_entries
            self.state.set_questions(normalized_info, pending_entries)
            self.controller.question_entries = pending_entries
            if not selected_issue_nums:
                self.strategy_page.set_dimension_groups([])
            self.strategy_page.set_entries(
                self.state.entries,
                self.state.entry_questions_info,
            )
            self.sync_reverse_fill_context()
            self.dashboard.update_question_meta(parsed_title, len(pending_entries))
            log_action(
                "UI",
                "open_parse_wizard",
                "question_wizard",
                "main_window",
                result="accepted",
                payload={"question_count": len(normalized_info)},
            )
            return

        current_entries = self.state.get_entries()
        self.dashboard.update_question_meta(parsed_title, len(current_entries))
        log_action(
            "UI",
            "open_parse_wizard",
            "question_wizard",
            "main_window",
            result="cancelled",
            payload={"question_count": len(normalized_info)},
        )
        self.host._toast("已取消自动配置，保留原有题目设置", "warning")

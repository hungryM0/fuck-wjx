"""DashboardPage 启动运行与配置同步。"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from software.logging.action_logger import log_action
from software.logging.log_utils import log_suppressed_exception
from software.io.config import RuntimeConfig
from software.providers.common import detect_survey_provider

_QQ_LOGIN_REQUIRED_MESSAGE = "作答该问卷需要登录，请自行在后台开放访问权限"


class DashboardRunActionsMixin:
    if TYPE_CHECKING:
        controller: Any
        question_page: Any
        runtime_page: Any
        strategy_page: Any
        target_spin: Any
        thread_spin: Any
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

        def _toast(self, text: str, level: str = "info", duration: int = 2000, show_progress: bool = False) -> Any: ...
        def _sync_start_button_state(self, running: bool | None = None) -> None: ...
        def _refresh_entry_table(self) -> None: ...
        def _refresh_ip_cost_infobar(self) -> None: ...
        def _sync_random_ip_toggle_presentation(self, enabled: bool) -> None: ...
        def window(self) -> Any: ...

    def _on_start_clicked(self):
        if getattr(self.controller, "running", False):
            if self._completion_notified:
                self._pending_restart = True
                self.controller.stop_run()
                log_action("RUN", "restart_run", "start_btn", "dashboard", result="queued")
                self._toast("正在重新开始，请稍候...", "info", 1200)
            return

        cfg = self._build_config()
        from software.io.config import deserialize_question_entry, serialize_question_entry
        cfg.question_entries = [deserialize_question_entry(serialize_question_entry(entry)) for entry in self.question_page.get_entries()]
        cfg.questions_info = list(self.question_page.questions_info or [])
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
            self._toast("未配置任何题目，无法开始执行（请先在'题目配置'页添加/配置题目）", "warning")
            self._sync_start_button_state(running=False)
            return
        
        # 验证反填模式配置
        if cfg.backfill_enabled:
            is_valid, error_msg = self.validate_backfill_config()
            if not is_valid:
                log_action(
                    "RUN",
                    "start_run",
                    "start_btn",
                    "dashboard",
                    result="blocked",
                    level=logging.WARNING,
                    payload={"reason": "invalid_backfill_config", "error": error_msg},
                )
                self._toast(f"反填模式配置错误: {error_msg}", "warning", duration=3000)
                self._sync_start_button_state(running=False)
                return
        
        # 只有在任务完成后的重新开始才重置进度，暂停后继续不重置
        if self._completion_notified or self._last_progress >= 100:
            self.progress_bar.setValue(0)
            self.progress_pct.setText("0%")
            self._last_progress = 0
            self._completion_notified = False
            self.status_label.setText(f"已提交 0/{cfg.target} 份 | 提交连续失败 0 次")
        self.controller.start_run(cfg)
        log_action(
            "RUN",
            "start_run",
            "start_btn",
            "dashboard",
            result="started",
            payload={"target": cfg.target, "threads": cfg.threads, "backfill_enabled": cfg.backfill_enabled},
        )
    def update_question_meta(self, title: str, count: int):
        self.count_label.setText(f"{count} 题")
        self.title_label.setText(title or "已配置的题目")
        self._survey_title = title or ""
        self._refresh_entry_table()
        self._sync_start_button_state()
        self._refresh_ip_cost_infobar()
    def _apply_runtime_ui_state(self, state: dict) -> None:
        target = state.get("target")
        if target is not None and int(self.target_spin.value()) != int(target):
            self.target_spin.blockSignals(True)
            self.target_spin.setValue(max(1, int(target)))
            self.target_spin.blockSignals(False)

        headless_enabled = bool(state.get("headless_mode", True))
        self.thread_spin.setRange(1, 16 if headless_enabled else 8)

        threads = state.get("threads")
        if threads is not None and int(self.thread_spin.value()) != int(threads):
            self.thread_spin.blockSignals(True)
            self.thread_spin.setValue(max(1, int(threads)))
            self.thread_spin.blockSignals(False)

        random_ip_enabled = state.get("random_ip_enabled")
        if random_ip_enabled is not None and bool(self.random_ip_cb.isChecked()) != bool(random_ip_enabled):
            self.random_ip_cb.blockSignals(True)
            self.random_ip_cb.setChecked(bool(random_ip_enabled))
            self.random_ip_cb.blockSignals(False)
            self._sync_random_ip_toggle_presentation(bool(random_ip_enabled))

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

        try:
            self.strategy_page.set_rules(getattr(cfg, "answer_rules", []) or [])
            self.strategy_page.set_dimension_groups(getattr(cfg, "dimension_groups", []) or [])
        except Exception as exc:
            log_suppressed_exception("apply_config: self.strategy_page.set_rules(...)", exc, level=logging.WARNING)

        # 恢复反填模式配置
        backfill_enabled = bool(getattr(cfg, "backfill_enabled", False))
        backfill_excel_path = str(getattr(cfg, "backfill_excel_path", "") or "")
        
        self.backfill_switch.blockSignals(True)
        self.backfill_switch.setChecked(backfill_enabled)
        self.backfill_switch.blockSignals(False)
        
        self._backfill_enabled = backfill_enabled
        self._backfill_excel_path = backfill_excel_path
        
        if backfill_enabled and backfill_excel_path:
            import os
            file_name = os.path.basename(backfill_excel_path)
            self.backfill_path_label.setText(file_name)
            self.backfill_path_label.setStyleSheet("color: black;")
            self.backfill_excel_btn.setEnabled(True)
            self.backfill_preview_btn.setEnabled(True)
        else:
            self.backfill_path_label.setText("未选择文件")
            self.backfill_path_label.setStyleSheet("color: gray;")
            self.backfill_excel_btn.setEnabled(backfill_enabled)
            self.backfill_preview_btn.setEnabled(False)

        self._refresh_entry_table()
        self._sync_start_button_state()
        self._refresh_ip_cost_infobar()
        self.controller.sync_runtime_ui_state_from_config(cfg)
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
    def _build_config(self) -> RuntimeConfig:
        cfg = RuntimeConfig()
        cfg.url = self.url_edit.text().strip()
        cfg.survey_title = str(self._survey_title or "")
        cfg.survey_provider = detect_survey_provider(
            cfg.url,
            default=str(getattr(self.controller, "survey_provider", "wjx") or "wjx"),
        )
        self.runtime_page.update_config(cfg)
        cfg.target = max(1, self.target_spin.value())
        cfg.threads = max(1, self.thread_spin.value())
        cfg.random_ip_enabled = self.random_ip_cb.isChecked()
        cfg.answer_rules = list(self.strategy_page.get_rules() or [])
        cfg.dimension_groups = list(self.strategy_page.get_dimension_groups() or [])
        
        # 反填模式配置
        cfg.backfill_enabled = self._backfill_enabled
        cfg.backfill_excel_path = self._backfill_excel_path
        
        return cfg

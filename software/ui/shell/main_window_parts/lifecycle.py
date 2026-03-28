"""MainWindow 生命周期与配置落盘相关方法。"""
from __future__ import annotations

import logging
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog
from qfluentwidgets import MessageBox, PushButton

from software.network.proxy.session import get_session_snapshot
from software.app.config import app_settings, get_bool_from_qsettings
from software.app.runtime_paths import get_runtime_directory
from software.io.config import RuntimeConfig
from software.logging.log_utils import LOG_BUFFER_HANDLER, log_suppressed_exception


class MainWindowLifecycleMixin:
    """收口主窗口的保存、启动恢复、标题刷新与关闭清理。"""

    def _cleanup_runtime_resources_on_close(self) -> None:
        try:
            if self._boot_splash:
                self._boot_splash.cleanup()
        except Exception as exc:
            log_suppressed_exception("closeEvent: self._boot_splash.cleanup()", exc)

        try:
            if self._log_page and hasattr(self._log_page, "_refresh_timer"):
                self._log_page._refresh_timer.stop()
        except Exception as exc:
            log_suppressed_exception("closeEvent: self._log_page._refresh_timer.stop()", exc)

        try:
            if self._support_page and hasattr(self._support_page, "contact_form"):
                self._support_page.contact_form.stop_status_polling()
        except Exception as exc:
            log_suppressed_exception("closeEvent: self._support_page.contact_form.stop_status_polling()", exc)

        try:
            self._stop_update_check_worker()
        except Exception as exc:
            log_suppressed_exception("closeEvent: self._stop_update_check_worker()", exc)

    def _persist_last_session_log(self) -> None:
        try:
            log_path = os.path.join(get_runtime_directory(), "logs", "last_session.log")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            records = LOG_BUFFER_HANDLER.get_records()
            with open(log_path, "w", encoding="utf-8") as file:
                file.write("\n".join(entry.text for entry in records))
        except Exception as exc:
            logging.warning("保存日志失败: %s", exc)

    def _collect_current_config_snapshot(self):
        cfg = self.dashboard._build_config()
        cfg.question_entries = list(self.question_page.get_entries())
        self.controller.config = cfg
        return cfg

    def _save_config_via_dialog(self, cfg) -> bool:
        configs_dir = os.path.join(get_runtime_directory(), "configs")
        os.makedirs(configs_dir, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存配置",
            configs_dir,
            "JSON 文件 (*.json);;所有文件 (*.*)",
        )
        if not path:
            continue_box = MessageBox("确认", "未保存配置，是否继续退出？", self)
            continue_box.yesButton.setText("退出")
            continue_box.cancelButton.setText("取消")
            return bool(continue_box.exec())

        from software.io.config import save_config

        save_config(cfg, path)
        logging.info("配置已保存到: %s", path)
        return True

    def _confirm_close_with_optional_save(self) -> bool:
        if self._skip_save_on_close:
            self._persist_last_session_log()
            return True

        settings = app_settings()
        ask_save = get_bool_from_qsettings(settings.value("ask_save_on_close"), True)
        if not ask_save:
            self._persist_last_session_log()
            return True

        box = MessageBox("保存配置", "是否保存当前配置？", self)
        box.yesButton.setText("保存")
        box.cancelButton.setText("取消")
        no_btn = PushButton("不保存", self)
        box.buttonLayout.insertWidget(1, no_btn)
        no_btn.clicked.connect(lambda: box.done(2))
        reply = box.exec()

        if reply == 0 or not reply:
            return False

        if reply == 1 or reply is True:
            try:
                cfg = self._collect_current_config_snapshot()
                if not self._save_config_via_dialog(cfg):
                    return False
            except Exception as exc:
                logging.error("保存配置失败: %s", exc, exc_info=True)
                error_box = MessageBox("错误", f"保存配置失败：{exc}\n\n是否继续退出？", self)
                error_box.yesButton.setText("退出")
                error_box.cancelButton.setText("取消")
                if not error_box.exec():
                    return False

        self._persist_last_session_log()
        return True

    def _load_saved_config(self):
        cfg = RuntimeConfig()
        self.runtime_page.apply_config(cfg)
        self.dashboard.apply_config(cfg)
        self.question_page.set_entries(cfg.question_entries or [], self.controller.questions_info)
        self.strategy_page.set_questions_info(self.controller.questions_info)
        self.strategy_page.set_entries(self.question_page.entries, self.question_page.entry_questions_info)
        self.strategy_page.set_rules(getattr(cfg, "answer_rules", []) or [])
        self.strategy_page.set_dimension_groups(getattr(cfg, "dimension_groups", []) or [])
        self.controller.refresh_random_ip_counter()

    def _on_random_ip_counter_update(self, count: float, limit: float, custom_api: bool) -> None:
        try:
            self.dashboard.update_random_ip_counter(count, limit, custom_api)
        except Exception as exc:
            log_suppressed_exception("_on_random_ip_counter_update dashboard", exc, level=logging.WARNING)
        self._refresh_title_random_ip_user_id()

    def _refresh_title_random_ip_user_id(self) -> None:
        user_id = 0
        authenticated = False
        try:
            snapshot = get_session_snapshot()
            authenticated = bool(snapshot.get("authenticated"))
            user_id = int(snapshot.get("user_id") or 0)
        except Exception as exc:
            log_suppressed_exception("_refresh_title_random_ip_user_id snapshot", exc, level=logging.WARNING)

        suffix = ""
        if authenticated and user_id > 0:
            suffix = f" <span style='color:#8A8A8A;'>({user_id})</span>"
        title_label = getattr(getattr(self, "titleBar", None), "titleLabel", None)
        if title_label is None:
            return
        try:
            title_label.setTextFormat(Qt.TextFormat.RichText)
            title_label.setText(f"{self._base_window_title}{suffix}")
            title_label.adjustSize()
        except Exception as exc:
            log_suppressed_exception("_refresh_title_random_ip_user_id render", exc, level=logging.WARNING)



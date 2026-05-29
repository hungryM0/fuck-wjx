"""MainWindow 生命周期与配置落盘相关方法。"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFileDialog, QWidget
from qfluentwidgets import MessageBox, PushButton

from software.network.proxy.session import get_session_snapshot
from software.app.config import app_settings, get_bool_from_qsettings
from software.app.user_paths import (
    get_user_config_directory,
    get_user_local_data_root,
)
from software.core.config.schema import RuntimeConfig
from software.core.config.codec import build_runtime_config_snapshot
from software.logging.log_utils import (
    finalize_session_log_persistence,
    log_suppressed_exception,
)


class MainWindowLifecycleMixin:
    """收口主窗口的保存、启动恢复、标题刷新与关闭清理。"""

    if TYPE_CHECKING:
        _async_dialog_refs: Any
        _boot_splash: Any
        _contact_dialog: Any
        _quota_redeem_dialog: Any
        _log_page: Any
        _random_ip_quota_auto_sync_timer: Any
        _skip_save_on_close: bool
        _base_window_title: str
        _close_request_pending: bool
        _close_request_confirmed: bool
        dashboard: Any
        workbench_state: Any
        runtime_page: Any
        strategy_page: Any
        controller: Any

        def close(self) -> bool: ...
        def _stop_update_check_worker(self) -> None: ...
        def _cancel_startup_update_check(self) -> None: ...

    def _cleanup_runtime_resources_on_close(self) -> None:
        try:
            setattr(self, "_is_closing", True)
        except Exception:
            pass

        try:
            dashboard = getattr(self, "dashboard", None)
            if dashboard is not None:
                setattr(dashboard, "_is_closing", True)
        except Exception as exc:
            log_suppressed_exception("closeEvent: mark dashboard closing", exc)

        try:
            self._random_ip_quota_auto_sync_timer.stop()
        except Exception as exc:
            log_suppressed_exception(
                "closeEvent: self._random_ip_quota_auto_sync_timer.stop()", exc
            )

        try:
            self.controller.request_shutdown_for_close()
        except Exception as exc:
            log_suppressed_exception(
                "closeEvent: self.controller.request_shutdown_for_close()", exc
            )

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
            self._stop_update_check_worker()
        except Exception as exc:
            log_suppressed_exception("closeEvent: self._stop_update_check_worker()", exc)

        try:
            self._cancel_startup_update_check()
        except Exception as exc:
            log_suppressed_exception("closeEvent: self._cancel_startup_update_check()", exc)

        try:
            dialog = getattr(self, "_contact_dialog", None)
            if dialog is not None:
                dialog.close()
        except Exception as exc:
            log_suppressed_exception("closeEvent: self._contact_dialog.close()", exc)

        try:
            dialog = getattr(self, "_quota_redeem_dialog", None)
            if dialog is not None:
                dialog.close()
        except Exception as exc:
            log_suppressed_exception("closeEvent: self._quota_redeem_dialog.close()", exc)

        try:
            for dialog in list(getattr(self, "_async_dialog_refs", []) or []):
                try:
                    dialog.close()
                except Exception as dialog_exc:
                    log_suppressed_exception("closeEvent: async_dialog.close()", dialog_exc)
        except Exception as exc:
            log_suppressed_exception("closeEvent: async dialogs cleanup", exc)

    def _persist_last_session_log(self) -> None:
        try:
            finalize_session_log_persistence(get_user_local_data_root())
        except Exception as exc:
            logging.warning("保存日志失败: %s", exc)

    def _collect_current_config_snapshot(self):
        workbench = getattr(self, "workbench", None)
        if workbench is not None and hasattr(workbench, "build_current_config_snapshot"):
            return workbench.build_current_config_snapshot()
        cfg = build_runtime_config_snapshot(
            self.dashboard._build_config(),
            question_entries=self.workbench_state.get_entries(),
            questions_info=self.workbench_state.questions_info,
        )
        if hasattr(self.controller, "config"):
            self.controller.config = cfg
        return cfg

    def _save_config_via_dialog(self, cfg) -> bool:
        configs_dir = get_user_config_directory()
        os.makedirs(configs_dir, exist_ok=True)
        parent_widget = cast(QWidget, self)
        path, _ = QFileDialog.getSaveFileName(
            parent_widget,
            "保存配置",
            configs_dir,
            "JSON 文件 (*.json);;所有文件 (*.*)",
        )
        if not path:
            continue_box = MessageBox("确认", "未保存配置，是否继续退出？", parent_widget)
            continue_box.yesButton.setText("退出")
            continue_box.cancelButton.setText("取消")
            return bool(continue_box.exec())

        from software.io.config.store import save_config

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

        parent_widget = cast(QWidget, self)
        box = MessageBox("保存配置", "是否保存当前配置？", parent_widget)
        box.yesButton.setText("保存")
        box.cancelButton.setText("取消")
        button_parent = getattr(box, "buttonGroup", box)
        no_btn = PushButton("不保存", button_parent)
        box.buttonLayout.insertWidget(1, no_btn)
        no_btn.clicked.connect(lambda: box.done(2))
        widget = getattr(box, "widget", None)
        if widget is not None and hasattr(widget, "raise_"):
            widget.raise_()
        reply = box.exec()

        if reply == 0 or not reply:
            return False

        try:
            if (
                bool(getattr(self.controller, "running", False))
                or bool(getattr(self.controller, "_starting", False))
                or bool(getattr(self.controller, "is_initializing", lambda: False)())
            ):
                self.controller.stop_run()
        except Exception as exc:
            log_suppressed_exception(
                "_confirm_close_with_optional_save: stop_run",
                exc,
                level=logging.WARNING,
            )

        if reply == 1 or reply is True:
            try:
                cfg = self._collect_current_config_snapshot()
                if not self._save_config_via_dialog(cfg):
                    return False
            except Exception as exc:
                logging.error("保存配置失败: %s", exc, exc_info=True)
                error_box = MessageBox(
                    "错误",
                    f"保存配置失败：{exc}\n\n是否继续退出？",
                    parent_widget,
                )
                error_box.yesButton.setText("退出")
                error_box.cancelButton.setText("取消")
                if not error_box.exec():
                    return False

        self._persist_last_session_log()
        return True

    def _schedule_deferred_close_confirmation(self) -> None:
        if bool(getattr(self, "_close_request_pending", False)):
            return
        if bool(getattr(self, "_close_request_confirmed", False)):
            return

        self._close_request_pending = True
        parent_widget = cast(QWidget, self)

        def _continue_close() -> None:
            self._close_request_pending = False
            if not self._confirm_close_with_optional_save():
                return
            self._close_request_confirmed = True
            try:
                self.close()
            except Exception as exc:
                self._close_request_confirmed = False
                log_suppressed_exception(
                    "_schedule_deferred_close_confirmation: self.close()",
                    exc,
                    level=logging.WARNING,
                )

        QTimer.singleShot(0, parent_widget, _continue_close)

    def _finalize_confirmed_close(self) -> None:
        self._close_request_confirmed = False
        self._cleanup_runtime_resources_on_close()

    def _load_saved_config(self):
        try:
            cfg = self.controller.load_saved_config(strict=False)
        except Exception as exc:
            logging.warning("加载默认配置失败: %s", exc)
            cfg = RuntimeConfig()
        workbench = getattr(self, "workbench", None)
        if workbench is not None and hasattr(workbench, "apply_config"):
            workbench.apply_config(cfg)
            self.controller.refresh_random_ip_counter()
            return
        self.runtime_page.apply_config(cfg)
        self.dashboard.apply_config(cfg)
        self.workbench_state.set_entries(cfg.question_entries or [], cfg.questions_info or [])
        self.strategy_page.set_questions_info(cfg.questions_info or [])
        self.strategy_page.set_entries(
            self.workbench_state.entries,
            self.workbench_state.entry_questions_info,
        )
        self.strategy_page.set_rules(getattr(cfg, "answer_rules", []) or [])
        self.strategy_page.set_dimension_groups(getattr(cfg, "dimension_groups", []) or [])
        self.controller.refresh_random_ip_counter()

    def _on_random_ip_counter_update(self, count: float, limit: float, custom_api: bool) -> None:
        try:
            self.dashboard.update_random_ip_counter(count, limit, custom_api)
        except Exception as exc:
            log_suppressed_exception(
                "_on_random_ip_counter_update dashboard",
                exc,
                level=logging.WARNING,
            )
        self._refresh_title_random_ip_user_id()

    def _refresh_title_random_ip_user_id(self) -> None:
        user_id = 0
        authenticated = False
        try:
            snapshot = get_session_snapshot()
            authenticated = bool(snapshot.get("authenticated"))
            user_id = int(snapshot.get("user_id") or 0)
        except Exception as exc:
            log_suppressed_exception(
                "_refresh_title_random_ip_user_id snapshot",
                exc,
                level=logging.WARNING,
            )

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
            log_suppressed_exception(
                "_refresh_title_random_ip_user_id render",
                exc,
                level=logging.WARNING,
            )

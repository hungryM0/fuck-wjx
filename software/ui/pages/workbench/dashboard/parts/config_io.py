"""DashboardPage 配置导入导出。"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtWidgets import QFileDialog, QWidget

from software.app.runtime_paths import get_runtime_directory
from software.io.config import build_default_config_filename
from software.logging.action_logger import log_action
from software.logging.log_utils import log_suppressed_exception


class DashboardConfigIOMixin:
    if TYPE_CHECKING:
        controller: Any
        config_drawer: Any
        runtime_page: Any
        question_page: Any
        strategy_page: Any
        _survey_title: str

        def _toast(self, text: str, level: str = "info", duration: int = 2000, show_progress: bool = False) -> Any: ...
        def apply_config(self, cfg: Any) -> None: ...
        def _build_config(self) -> Any: ...
        def _refresh_entry_table(self) -> None: ...
        def update_question_meta(self, title: str, count: int) -> None: ...
        def _sync_start_button_state(self, running: bool | None = None) -> None: ...

    def _on_show_config_list(self):
        try:
            self.config_drawer.open_drawer()
            log_action("UI", "open_config_list", "config_list_btn", "dashboard", result="opened")
        except Exception as exc:
            log_action(
                "UI",
                "open_config_list",
                "config_list_btn",
                "dashboard",
                result="failed",
                level=logging.ERROR,
                detail=exc,
            )
            self._toast(f"无法打开配置列表：{exc}", "error")
    def _on_load_config(self):
        configs_dir = os.path.join(get_runtime_directory(), "configs")
        if not os.path.exists(configs_dir):
            os.makedirs(configs_dir, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(cast(QWidget, self), "载入配置", configs_dir, "JSON 文件 (*.json);;所有文件 (*.*)")
        if not path:
            log_action("CONFIG", "load_config", "load_cfg_btn", "dashboard", result="cancelled")
            return
        self._load_config_from_path(path)
    def _load_config_from_path(self, path: str):
        if not path:
            log_action("CONFIG", "load_config", "load_cfg_btn", "dashboard", result="cancelled")
            return
        if not os.path.exists(path):
            log_action(
                "CONFIG",
                "load_config",
                "load_cfg_btn",
                "dashboard",
                result="failed",
                level=logging.WARNING,
                payload={"reason": "missing_file", "file": os.path.basename(path)},
            )
            self._toast("文件不存在，可能已被删除", "warning")
            return
        try:
            cfg = self.controller.load_saved_config(path, strict=True)
        except Exception as exc:
            logging.error("[CONFIG] load_saved_config failed: %s", exc, exc_info=True)
            log_action(
                "CONFIG",
                "load_config",
                "load_cfg_btn",
                "dashboard",
                result="failed",
                level=logging.ERROR,
                payload={"file": os.path.basename(path)},
                detail=exc,
            )
            logging.error("手动载入配置失败: %s", exc, exc_info=True)
            self._toast(f"载入失败：{exc}", "error")
            return
        # 应用到界面
        self.runtime_page.apply_config(cfg)
        self.apply_config(cfg)
        self.question_page.set_entries(cfg.question_entries or [], cfg.questions_info or [])
        self.strategy_page.set_questions_info(cfg.questions_info or [])
        self.strategy_page.set_entries(self.question_page.entries, self.question_page.entry_questions_info)
        self._refresh_entry_table()
        try:
            self.update_question_meta(cfg.survey_title or "", len(cfg.question_entries or []))
        except Exception as exc:
            log_suppressed_exception("_load_config_from_path: self.update_question_meta(...)", exc, level=logging.WARNING)
        self._sync_start_button_state()
        self.controller.refresh_random_ip_counter()
        log_action(
            "CONFIG",
            "load_config",
            "load_cfg_btn",
            "dashboard",
            result="success",
            payload={"file": os.path.basename(path)},
        )
        self._toast("已载入配置", "success")
    def _on_save_config(self):
        cfg = self._build_config()
        # 序列化过滤 UI 组件
        from software.io.config import deserialize_question_entry, serialize_question_entry
        cfg.question_entries = [deserialize_question_entry(serialize_question_entry(entry)) for entry in self.question_page.get_entries()]
        cfg.questions_info = list(self.question_page.questions_info or [])
        self.controller.config = cfg
        configs_dir = os.path.join(get_runtime_directory(), "configs")
        os.makedirs(configs_dir, exist_ok=True)
        default_name = build_default_config_filename(self._survey_title)
        default_path = os.path.join(configs_dir, default_name)
        path, _ = QFileDialog.getSaveFileName(cast(QWidget, self), "保存配置", default_path, "JSON 文件 (*.json);;所有文件 (*.*)")
        if not path:
            log_action("CONFIG", "save_config", "save_cfg_btn", "dashboard", result="cancelled")
            return
        try:
            self.controller.save_current_config(path)
            log_action(
                "CONFIG",
                "save_config",
                "save_cfg_btn",
                "dashboard",
                result="success",
                payload={"file": os.path.basename(path)},
            )
            self._toast("配置已保存", "success")
        except Exception as exc:
            log_action(
                "CONFIG",
                "save_config",
                "save_cfg_btn",
                "dashboard",
                result="failed",
                level=logging.ERROR,
                payload={"file": os.path.basename(path)},
                detail=exc,
            )
            self._toast(f"保存失败：{exc}", "error")

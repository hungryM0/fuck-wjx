"""DashboardPage 配置导入导出。"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtWidgets import QFileDialog, QWidget

from software.app.user_paths import get_user_config_directory
from software.core.config.codec import build_runtime_config_snapshot
from software.io.config.store import build_default_config_filename
from software.logging.action_logger import log_action
from software.logging.log_utils import log_suppressed_exception


class DashboardConfigIOMixin:
    if TYPE_CHECKING:
        controller: Any
        config_drawer: Any
        runtime_page: Any
        workbench_state: Any
        strategy_page: Any
        _survey_title: str

        def _toast(
            self,
            text: str,
            level: str = "info",
            duration: int = 2000,
            show_progress: bool = False,
        ) -> Any: ...
        def apply_config(self, cfg: Any) -> None: ...
        def _build_config(self) -> Any: ...
        def _refresh_entry_table(self) -> None: ...
        def update_question_meta(self, title: str, count: int) -> None: ...
        def _sync_start_button_state(self, running: bool | None = None) -> None: ...
        def window(self) -> Any: ...

    @staticmethod
    def _format_load_config_error(exc: Exception) -> str:
        text = str(exc or "").strip()
        if "已移除的旧字段" in text:
            return "配置加载失败：字段已过期"
        if "配置文件版本不受支持" in text or "配置不兼容" in text:
            return "配置加载失败：版本不兼容"
        if "配置文件为空" in text:
            return "配置加载失败：文件为空"
        if "JSON" in text and "顶层必须是对象" in text:
            return "配置加载失败：文件格式错误"
        if "读取配置失败" in text:
            return "配置加载失败：文件损坏"
        return f"载入失败：{text}" if text else "载入失败"

    def _on_show_config_list(self):
        try:
            self.config_drawer.open_drawer()
            log_action(
                "UI",
                "open_config_list",
                "config_list_btn",
                "dashboard",
                result="opened",
            )
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
        configs_dir = get_user_config_directory()
        if not os.path.exists(configs_dir):
            os.makedirs(configs_dir, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(
            cast(QWidget, self),
            "载入配置",
            configs_dir,
            "JSON 文件 (*.json);;所有文件 (*.*)",
        )
        if not path:
            log_action(
                "CONFIG",
                "load_config",
                "load_cfg_btn",
                "dashboard",
                result="cancelled",
            )
            return
        self._load_config_from_path(path)

    def _load_config_from_path(self, path: str):
        if not path:
            log_action(
                "CONFIG",
                "load_config",
                "load_cfg_btn",
                "dashboard",
                result="cancelled",
            )
            return
        if not os.path.exists(path):
            log_action(
                "CONFIG",
                "load_config",
                "load_cfg_btn",
                "dashboard",
                result="failed",
                level=logging.WARNING,
                payload={
                    "reason": "missing_file",
                    "file": os.path.basename(path),
                },
            )
            self._toast("文件不存在，可能已被删除", "warning")
            return
        workbench = getattr(self.window(), "workbench", None)
        if workbench is not None and hasattr(workbench, "load_config_from_path"):
            try:
                workbench.load_config_from_path(path)
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
                self._toast(self._format_load_config_error(exc), "error")
                return
            log_action(
                "CONFIG",
                "load_config",
                "load_cfg_btn",
                "dashboard",
                result="success",
                payload={"file": os.path.basename(path)},
            )
            self._toast("已载入配置", "success")
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
            self._toast(self._format_load_config_error(exc), "error")
            return
        # 应用到界面
        self.runtime_page.apply_config(cfg)
        self.apply_config(cfg)
        self.workbench_state.set_entries(cfg.question_entries or [], cfg.questions_info or [])
        self.strategy_page.set_questions_info(cfg.questions_info or [])
        self.strategy_page.set_entries(
            self.workbench_state.entries,
            self.workbench_state.entry_questions_info,
        )
        self._refresh_entry_table()
        try:
            self.update_question_meta(cfg.survey_title or "", len(cfg.question_entries or []))
        except Exception as exc:
            log_suppressed_exception(
                "_load_config_from_path: self.update_question_meta(...)",
                exc,
                level=logging.WARNING,
            )
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
        workbench = getattr(self.window(), "workbench", None)
        if workbench is not None and hasattr(workbench, "build_current_config_snapshot"):
            cfg = workbench.build_current_config_snapshot()
        else:
            cfg = build_runtime_config_snapshot(
                self._build_config(),
                question_entries=self.workbench_state.get_entries(),
                questions_info=self.workbench_state.questions_info,
            )
        configs_dir = get_user_config_directory()
        os.makedirs(configs_dir, exist_ok=True)
        default_name = build_default_config_filename(self._survey_title)
        default_path = os.path.join(configs_dir, default_name)
        path, _ = QFileDialog.getSaveFileName(
            cast(QWidget, self),
            "保存配置",
            default_path,
            "JSON 文件 (*.json);;所有文件 (*.*)",
        )
        if not path:
            log_action(
                "CONFIG",
                "save_config",
                "save_cfg_btn",
                "dashboard",
                result="cancelled",
            )
            return
        try:
            self.controller.save_current_config(path, config=cfg)
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

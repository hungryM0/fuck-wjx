"""主窗口模块 - 精简版，使用拆分后的组件"""
from __future__ import annotations

import os
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtGui import QIcon, QGuiApplication
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog
from qfluentwidgets import (
    FluentIcon,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    NavigationItemPosition,
    PushButton,
    Theme,
    qconfig,
    setTheme,
    setThemeColor,
)

# 导入拆分后的页面
from wjx.ui.pages.dashboard import DashboardPage
from wjx.ui.pages.settings import SettingsPage
from wjx.ui.pages.question import QuestionPage
from wjx.ui.pages.log import LogPage
from wjx.ui.pages.help import HelpPage
from wjx.ui.pages.about import AboutPage

# 导入对话框
from wjx.ui.dialogs.card_unlock import CardUnlockDialog
from wjx.ui.dialogs.contact import ContactDialog

# 导入控制器和工具
from wjx.ui.controller import RunController
from wjx.utils.config import APP_ICON_RELATIVE_PATH
from wjx.utils.load_save import RuntimeConfig, get_runtime_directory
from wjx.utils.log_utils import LOG_BUFFER_HANDLER, register_popup_handler
from wjx.utils.version import __VERSION__, ISSUE_FEEDBACK_URL
from wjx.network.random_ip import (
    get_status,
    _format_status_payload,
    refresh_ip_counter_display,
)
from wjx.engine import _get_resource_path as get_resource_path


class MainWindow(FluentWindow):
    """主窗口，PowerToys 风格导航 + 圆角布局，支持主题动态切换。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        qconfig.load(os.path.join(get_runtime_directory(), "wjx", "ui", "theme.json"))
        setTheme(Theme.AUTO)
        setThemeColor("#2563EB")
        self._skip_save_on_close = False
        
        self.setWindowTitle(f"问卷星速填 v{__VERSION__}")
        icon_path = get_resource_path(APP_ICON_RELATIVE_PATH)
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setMinimumSize(1080, 720)

        self.controller = RunController(self)
        self.controller.on_ip_counter = None  # will be set after dashboard creation
        self.controller.card_code_provider = self._ask_card_code

        self.settings_page = SettingsPage(self.controller, self)
        self.question_page = QuestionPage(self)
        # QuestionPage 仅用作题目配置的数据载体，不作为主界面子页面展示；
        # 若不隐藏会以默认几何 (0,0,100,30) 叠在窗口左上角，造成标题栏错乱。
        self.question_page.hide()
        self.dashboard = DashboardPage(self.controller, self.question_page, self.settings_page, self)
        self.log_page = LogPage(self)
        self.help_page = HelpPage(self._open_contact_dialog, self)
        self.about_page = AboutPage(self)

        self.dashboard.setObjectName("dashboard")
        self.question_page.setObjectName("question")
        self.settings_page.setObjectName("settings")
        self.log_page.setObjectName("logs")
        self.help_page.setObjectName("help")
        self.about_page.setObjectName("about")

        self._init_navigation()
        # 设置侧边栏宽度和默认不可折叠
        try:
            self.navigationInterface.setExpandWidth(140)
            self.navigationInterface.setCollapsible(False)
        except Exception:
            pass
        self._sidebar_expanded = False  # 标记侧边栏是否已展开
        self._bind_controller_signals()
        # 确保初始 adapter 也能回调随机 IP 计数
        self.controller.adapter.update_random_ip_counter = self.dashboard.update_random_ip_counter
        self._register_popups()
        self._load_saved_config()
        self._center_on_screen()

    def showEvent(self, e):
        """窗口显示时展开侧边栏"""
        super().showEvent(e)
        if not self._sidebar_expanded:
            self._sidebar_expanded = True
            try:
                self.navigationInterface.expand(useAni=False)
            except Exception:
                pass

    def closeEvent(self, e):
        """窗口关闭时询问用户是否保存配置"""
        # 先停止所有定时器，防止在关闭过程中触发回调
        try:
            if hasattr(self.log_page, '_refresh_timer'):
                self.log_page._refresh_timer.stop()
            if hasattr(self.help_page, '_status_timer'):
                self.help_page._status_timer.stop()
        except Exception:
            pass
        
        if not self._skip_save_on_close:
            # 询问用户是否保存配置
            box = MessageBox("保存配置", "是否保存当前配置？", self)
            box.yesButton.setText("保存")
            box.cancelButton.setText("取消")
            
            # 添加"不保存"按钮
            no_btn = PushButton("不保存", self)
            box.buttonLayout.insertWidget(1, no_btn)
            no_btn.clicked.connect(lambda: box.done(2))  # 2 表示"不保存"
            
            reply = box.exec()
            
            if reply == 0 or not reply:  # 取消
                # 用户取消关闭
                e.ignore()
                return
            elif reply == 1 or reply == True:  # 保存
                # 用户选择保存
                try:
                    cfg = self.dashboard._build_config()
                    cfg.question_entries = list(self.question_page.get_entries())
                    self.controller.config = cfg
                    
                    # 弹出文件保存对话框，默认位置在 configs 目录
                    configs_dir = os.path.join(get_runtime_directory(), "configs")
                    os.makedirs(configs_dir, exist_ok=True)
                    
                    # 使用问卷标题作为默认文件名
                    from wjx.utils.load_save import _sanitize_filename
                    survey_title = self.dashboard.title_label.text()
                    if survey_title and survey_title != "题目清单与操作" and survey_title != "已配置的题目":
                        default_filename = f"{_sanitize_filename(survey_title)}.json"
                    else:
                        default_filename = f"config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                    default_path = os.path.join(configs_dir, default_filename)
                    
                    path, _ = QFileDialog.getSaveFileName(
                        self,
                        "保存配置",
                        default_path,
                        "JSON 文件 (*.json);;所有文件 (*.*)"
                    )
                    
                    if path:
                        from wjx.utils.load_save import save_config
                        save_config(cfg, path)
                        import logging
                        logging.info(f"配置已保存到: {path}")
                    else:
                        # 用户取消了保存对话框，询问是否继续退出
                        continue_box = MessageBox("确认", "未保存配置，是否继续退出？", self)
                        continue_box.yesButton.setText("退出")
                        continue_box.cancelButton.setText("取消")
                        if not continue_box.exec():
                            e.ignore()
                            return
                except Exception as exc:
                    import logging
                    logging.error(f"保存配置失败: {exc}", exc_info=True)
                    error_box = MessageBox("错误", f"保存配置失败：{exc}\n\n是否继续退出？", self)
                    error_box.yesButton.setText("退出")
                    error_box.cancelButton.setText("取消")
                    if not error_box.exec():
                        e.ignore()
                        return
            
            # 自动保存日志到固定文件
            try:
                log_path = os.path.join(get_runtime_directory(), "logs", "last_session.log")
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                records = LOG_BUFFER_HANDLER.get_records()
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write("\n".join([entry.text for entry in records]))
            except Exception as log_exc:
                import logging
                logging.warning(f"保存日志失败: {log_exc}")
        
        super().closeEvent(e)

    def _open_contact_dialog(self, default_type: str = "报错反馈"):
        dlg = ContactDialog(self, default_type=default_type, status_fetcher=get_status, status_formatter=_format_status_payload)
        dlg.exec()

    # ---------- init helpers ----------
    def _init_navigation(self):
        self.addSubInterface(self.dashboard, FluentIcon.HOME, "概览", NavigationItemPosition.TOP)
        self.addSubInterface(self.settings_page, FluentIcon.SETTING, "运行参数", NavigationItemPosition.TOP)
        self.addSubInterface(self.log_page, FluentIcon.INFO, "日志", NavigationItemPosition.TOP)
        self.addSubInterface(self.help_page, FluentIcon.HELP, "帮助", NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.about_page, FluentIcon.INFO, "关于", NavigationItemPosition.BOTTOM)
        self.navigationInterface.setCurrentItem(self.dashboard.objectName())

    def _center_on_screen(self):
        """窗口居中显示，适配多显示器与缩放。"""
        try:
            screen = self.screen() or QGuiApplication.primaryScreen()
            if not screen:
                return
            available = screen.availableGeometry()
            frame = self.frameGeometry()
            frame.moveCenter(available.center())
            self.move(frame.topLeft())
        except Exception:
            pass

    def _bind_controller_signals(self):
        self.controller.surveyParsed.connect(self._on_survey_parsed)
        self.controller.surveyParseFailed.connect(self._on_survey_parse_failed)
        self.controller.runFailed.connect(lambda msg: self._toast(msg, "error"))
        self.controller.runStateChanged.connect(self.dashboard.on_run_state_changed)
        self.controller.statusUpdated.connect(self.dashboard.update_status)
        self.controller.on_ip_counter = self.dashboard.update_random_ip_counter

    def _register_popups(self):
        def handler(kind: str, title: str, message: str):
            def _show():
                if kind == "confirm":
                    box = MessageBox(title, message, self)
                    box.yesButton.setText("确定")
                    box.cancelButton.setText("取消")
                    return bool(box.exec())
                if kind == "error":
                    InfoBar.error(title, message, parent=self, position=InfoBarPosition.TOP, duration=3000)
                    return False
                if kind == "warning":
                    InfoBar.warning(title, message, parent=self, position=InfoBarPosition.TOP, duration=3000)
                    return True
                InfoBar.info(title, message, parent=self, position=InfoBarPosition.TOP, duration=2500)
                return True

            return self._dispatch_to_ui(_show)

        register_popup_handler(handler)

    def _load_saved_config(self):
        try:
            cfg = self.controller.load_saved_config()
        except Exception:
            cfg = RuntimeConfig()
        self.settings_page.apply_config(cfg)
        self.dashboard.apply_config(cfg)
        self.question_page.set_entries(cfg.question_entries or [], self.controller.questions_info)
        # 初始刷新随机 IP 计数
        refresh_ip_counter_display(self.controller.adapter)

    # ---------- controller callbacks ----------
    def _on_survey_parsed(self, info: List[Dict[str, Any]], title: str):
        self.question_page.set_questions(info, self.controller.question_entries)
        self.dashboard.update_question_meta(title or "问卷", len(info))
        self._toast("解析完成，可在'题目配置'页查看", "success")
        if getattr(self.dashboard, "_open_wizard_after_parse", False):
            self.dashboard._open_wizard_after_parse = False
            self.dashboard._open_question_wizard()

    def _on_survey_parse_failed(self, msg: str):
        self._toast(msg, "error")
        self.dashboard._open_wizard_after_parse = False

    def _ask_card_code(self) -> Optional[str]:
        dialog = CardUnlockDialog(
            self,
            status_fetcher=get_status,
            status_formatter=_format_status_payload,
            contact_handler=lambda: self._open_contact_dialog(default_type="卡密获取"),
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.get_card_code()
        return None

    # ---------- utilities ----------
    def _dispatch_to_ui(self, func):
        if self.thread() == QThread.currentThread():
            return func()
        done = threading.Event()
        result: Dict[str, Any] = {}

        def _wrapper():
            try:
                result["value"] = func()
            finally:
                done.set()

        QTimer.singleShot(0, _wrapper)
        done.wait()
        return result.get("value")

    def _toast(self, text: str, level: str = "info", duration: int = 2000):
        kind = level.lower()
        if kind == "success":
            InfoBar.success("", text, parent=self, position=InfoBarPosition.TOP, duration=duration)
        elif kind == "warning":
            InfoBar.warning("", text, parent=self, position=InfoBarPosition.TOP, duration=duration)
        elif kind == "error":
            InfoBar.error("", text, parent=self, position=InfoBarPosition.TOP, duration=duration)
        else:
            InfoBar.info("", text, parent=self, position=InfoBarPosition.TOP, duration=duration)

    # ---------- updater 兼容方法 ----------
    def _log_popup_confirm(self, title: str, message: str) -> bool:
        """显示确认对话框，返回用户是否确认。"""
        box = MessageBox(title, message, self)
        box.yesButton.setText("确定")
        box.cancelButton.setText("取消")
        return bool(box.exec())

    def _log_popup_info(self, title: str, message: str):
        """显示信息对话框。"""
        box = MessageBox(title, message, self)
        box.yesButton.setText("确定")
        box.cancelButton.hide()
        box.exec()

    def _log_popup_error(self, title: str, message: str):
        """显示错误对话框。"""
        box = MessageBox(title, message, self)
        box.yesButton.setText("确定")
        box.cancelButton.hide()
        box.exec()


def create_window() -> MainWindow:
    """供入口调用的工厂函数。"""
    return MainWindow()

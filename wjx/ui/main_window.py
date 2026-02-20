"""主窗口模块 - 精简版，使用拆分后的组件"""
from __future__ import annotations

import copy
import logging
import os
import sys
import threading
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, QSettings, Signal, QEvent
from PySide6.QtGui import QIcon, QGuiApplication
from PySide6.QtWidgets import QDialog, QFileDialog
from qfluentwidgets import (
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    PushButton,
    Theme,
    qconfig,
    setTheme,
    setThemeColor,
)

from wjx.ui.pages.workbench.dashboard import DashboardPage
from wjx.ui.pages.workbench.runtime import RuntimePage
from wjx.ui.pages.workbench.question import QuestionPage

from wjx.ui.dialogs.card_unlock import CardUnlockDialog
from wjx.ui.dialogs.contact import ContactDialog

from wjx.ui.controller import RunController
from wjx.ui.main_window_parts.lazy_pages import MainWindowLazyPagesMixin
from wjx.ui.main_window_parts.popup_compat import MainWindowPopupCompatMixin
from wjx.ui.main_window_parts.update import MainWindowUpdateMixin
from wjx.utils.app.config import APP_ICON_RELATIVE_PATH, get_bool_from_qsettings
from wjx.utils.io.load_save import RuntimeConfig, get_runtime_directory
from wjx.utils.logging.log_utils import LOG_BUFFER_HANDLER, register_popup_handler, log_suppressed_exception
from wjx.utils.app.version import __VERSION__
from wjx.network.proxy import (
    get_status,
    _format_status_payload,
    get_random_ip_counter_snapshot_local,
    refresh_ip_counter_display,
)
from wjx.utils.app.runtime_paths import _get_resource_path as get_resource_path

from wjx.boot import create_boot_splash, finish_boot_splash


class MainWindow(
    MainWindowLazyPagesMixin,
    MainWindowPopupCompatMixin,
    MainWindowUpdateMixin,
    FluentWindow,
):
    """主窗口，PowerToys 风格导航 + 圆角布局，支持主题动态切换。"""

    # 更新通知信号（用于跨线程通信）


    updateAvailable = Signal()
    # 最新版本信号
    isLatestVersion = Signal()
    # 版本状态信号（latest/preview/unknown），用于从后台线程安全通知主线程
    versionStatus = Signal(str)
    # 下载开始信号（显示转圈动画）
    downloadStarted = Signal()
    # 下载进度信号
    downloadProgress = Signal(int, int, float)  # downloaded, total, speed
    # 下载完成信号
    downloadFinished = Signal(str)  # downloaded_file_path
    # 下载失败信号
    downloadFailed = Signal(str)  # error_message
    # 镜像源切换信号
    mirrorSwitched = Signal(str)  # new_mirror_key

    def __init__(self, parent=None):
        self._boot_splash = None
        super().__init__(parent)
        theme_path = get_resource_path(os.path.join("wjx", "ui", "theme.json"))
        if os.path.exists(theme_path):
            qconfig.load(theme_path)
        self._theme_sync_pending = False
        self._apply_theme_mode(qconfig.get(qconfig.themeMode))
        setThemeColor("#2563EB")
        qconfig.themeChanged.connect(self._on_theme_changed)
        self._skip_save_on_close = False
        
        self.setWindowTitle(f"问卷星速填 v{__VERSION__}")
        icon_path = get_resource_path(APP_ICON_RELATIVE_PATH)
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setMinimumSize(1080, 720)
        self._enable_window_material_effect()

        # 应用窗口置顶设置
        settings = QSettings("FuckWjx", "Settings")
        if get_bool_from_qsettings(settings.value("window_topmost"), False):
            self.apply_topmost_state(True, show=False)

        # 创建启动页面
        self._boot_splash = create_boot_splash(self)

        self.controller = RunController(self)
        self.controller.on_ip_counter = None  # will be set after dashboard creation
        self.controller.card_code_provider = self._ask_card_code

        # 立即初始化关键页面
        self.runtime_page = RuntimePage(self.controller, self)
        self.question_page = QuestionPage(self)
        # QuestionPage 仅用作题目配置的数据载体，不作为主界面子页面展示；
        # 若不隐藏会以默认几何 (0,0,100,30) 叠在窗口左上角，造成标题栏错乱。
        self.question_page.hide()
        self.dashboard = DashboardPage(self.controller, self.question_page, self.runtime_page, self)

        # 延迟初始化非关键页面（懒加载）
        self._log_page = None
        self._support_page = None
        self._community_page = None
        self._about_page = None
        self._changelog_page = None
        self._changelog_detail_page = None
        self._donate_page = None
        self._login_page = None
        self._settings_page = None

        # 设置对象名称
        self.dashboard.setObjectName("dashboard")
        self.question_page.setObjectName("question")
        self.runtime_page.setObjectName("runtime")

        self._init_navigation()
        self._init_changelog_navigation()

        self._init_github_avatar()
        # 设置侧边栏宽度和折叠策略（延迟到事件循环中，避免时序问题）
        self.navigationInterface.setExpandWidth(140)
        QTimer.singleShot(0, self._setup_sidebar_state)
        self._sidebar_expanded = False  # 标记侧边栏是否已展开
        self._bind_controller_signals()
        # 确保初始 adapter 也能回调随机 IP 计数
        self.controller.adapter.update_random_ip_counter = self.dashboard.update_random_ip_counter
        self._register_popups()
        self._load_saved_config()
        self._center_on_screen()

        finish_boot_splash(1500)

        # 连接更新通知信号
        self.updateAvailable.connect(self._do_show_update_notification)
        self.updateAvailable.connect(self._show_outdated_badge)
        # 连接最新版本信号（兼容旧路径）
        self.isLatestVersion.connect(self._show_latest_version_badge)
        # 连接版本状态信号（新路径，区分 latest/preview/unknown）
        self.versionStatus.connect(self._apply_version_status_badge)
        # 连接下载开始信号（显示转圈动画）
        self.downloadStarted.connect(self._on_download_started)
        # 连接下载进度信号
        self.downloadProgress.connect(self._update_download_progress)
        # 连接下载完成/失败信号
        self.downloadFinished.connect(self._on_download_finished)
        self.downloadFailed.connect(self._on_download_failed)
        # 连接镜像源切换信号
        self.mirrorSwitched.connect(self._on_mirror_switched)
        self._latest_badge = None
        self._outdated_badge = None
        self._preview_badge = None
        self._unknown_badge = None
        self._update_checking_spinner = None
        self._download_infobar = None
        self._download_progress_bar = None
        self._download_cancelled = False

        # 检查是否为预览版本，如果是则显示预览徽章
        self._check_preview_version()

        # 根据设置检查更新
        self._check_update_on_startup()

    def _apply_theme_mode(self, theme_mode: Theme):
        """按指定主题模式应用样式（不覆盖用户配置文件）。"""
        try:
            setTheme(theme_mode, save=False, lazy=False)
        except Exception:
            logging.debug("应用主题模式失败", exc_info=True)

    def _enable_window_material_effect(self):
        """启用窗口材质效果（Windows 下优先使用 Mica）。"""
        if not sys.platform.startswith("win"):
            return
        if not hasattr(self, "setMicaEffectEnabled"):
            return
        try:
            self.setMicaEffectEnabled(True)
        except Exception:
            logging.debug("启用窗口材质效果失败", exc_info=True)

    def _on_theme_changed(self, _theme: Theme):
        """主题变化后刷新主题敏感组件。"""
        self._enable_window_material_effect()
        try:
            drawer = getattr(getattr(self, "dashboard", None), "config_drawer", None)
            if drawer and hasattr(drawer, "_apply_theme"):
                drawer._apply_theme()
        except Exception:
            logging.debug("主题变更后刷新组件失败", exc_info=True)

    def changeEvent(self, event):
        """系统主题/调色板变化时，在 AUTO 模式下重同步主题。"""
        super().changeEvent(event)
        watched_events = {
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.PaletteChange,
        }
        if hasattr(QEvent.Type, "ThemeChange"):
            watched_events.add(QEvent.Type.ThemeChange)
        if event.type() in watched_events:
            self._schedule_auto_theme_sync()

    def _schedule_auto_theme_sync(self):
        if self._theme_sync_pending:
            return
        self._theme_sync_pending = True
        QTimer.singleShot(0, self._sync_auto_theme_if_needed)

    def _sync_auto_theme_if_needed(self):
        self._theme_sync_pending = False
        try:
            theme_mode = qconfig.get(qconfig.themeMode)
        except Exception:
            theme_mode = Theme.AUTO
        if theme_mode != Theme.AUTO:
            return
        # setTheme(AUTO) 在 themeMode 已经是 AUTO 时会被 qconfig.set 短路，
        # 导致内部 theme 属性不会被重新检测。这里手动强制刷新。
        from qfluentwidgets.common.style_sheet import updateStyleSheet
        old_theme = qconfig.theme
        qconfig.theme = Theme.AUTO          # 触发 darkdetect 重新检测
        if qconfig.theme != old_theme:
            updateStyleSheet()
            qconfig.themeChangedFinished.emit()
            qconfig._cfg.themeChanged.emit(Theme.AUTO)

    def resizeEvent(self, e):
        """调整启动页面组件位置"""
        super().resizeEvent(e)
        if self._boot_splash:
            self._boot_splash.update_layout(self.width(), self.height())

    def _setup_sidebar_state(self):
        """设置侧边栏折叠状态（在事件循环中调用以避免时序问题）"""
        try:
            settings = QSettings("FuckWjx", "Settings")
            always_expand = get_bool_from_qsettings(settings.value("sidebar_always_expand"), True)
            self.navigationInterface.setCollapsible(not always_expand)
            if always_expand:
                self.navigationInterface.expand(useAni=False)
        except Exception:
            logging.debug("设置侧边栏状态失败", exc_info=True)

    def showEvent(self, e):
        """窗口显示时展开侧边栏"""
        super().showEvent(e)
        if self._sidebar_expanded:
            return
        self._sidebar_expanded = True
        settings = QSettings("FuckWjx", "Settings")
        always_expand = get_bool_from_qsettings(settings.value("sidebar_always_expand"), True)
        if not always_expand:
            return
        try:
            self.navigationInterface.expand(useAni=False)
        except Exception:
            logging.debug("showEvent 展开侧边栏失败", exc_info=True)

    def closeEvent(self, e):
        """窗口关闭时询问用户是否保存配置"""
        # 先停止所有定时器和网络请求，防止在关闭过程中触发回调
        try:
            # 停止启动画面的进度条和定时器
            if self._boot_splash:
                try:
                    self._boot_splash.cleanup()
                except Exception as exc:
                    log_suppressed_exception("closeEvent: self._boot_splash.cleanup()", exc)

            # 断开网络管理器的所有信号连接，避免回调对象析构警告
            if hasattr(self, '_network_manager') and self._network_manager:
                try:
                    self._network_manager.blockSignals(True)
                except Exception as exc:
                    log_suppressed_exception("closeEvent: self._network_manager.blockSignals(True)", exc)

            # 停止日志页面定时器
            if self._log_page and hasattr(self._log_page, '_refresh_timer'):
                self._log_page._refresh_timer.stop()

            # 停止联系表单轮询
            if self._support_page and hasattr(self._support_page, 'contact_form'):
                try:
                    self._support_page.contact_form.stop_status_polling()
                except Exception as exc:
                    log_suppressed_exception("closeEvent: self._support_page.contact_form.stop_status_polling()", exc)
        except Exception as exc:
            log_suppressed_exception("closeEvent: 清理资源时出错", exc)
        
        if not self._skip_save_on_close:
            settings = QSettings("FuckWjx", "Settings")
            ask_save = get_bool_from_qsettings(settings.value("ask_save_on_close"), True)
            if ask_save:
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
                        
                        default_path = configs_dir
                        
                        path, _ = QFileDialog.getSaveFileName(
                            self,
                            "保存配置",
                            default_path,
                            "JSON 文件 (*.json);;所有文件 (*.*)"
                        )
                        
                        if path:
                            from wjx.utils.io.load_save import save_config
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
            logging.debug("窗口居中失败", exc_info=True)

    def apply_topmost_state(self, checked: bool, show: bool = False):
        """应用窗口置顶状态，并刷新无边框特效以保留圆角。"""
        flags = self.windowFlags()
        already_checked = bool(flags & Qt.WindowType.WindowStaysOnTopHint)
        if already_checked == checked:
            return
        if checked:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if hasattr(self, "updateFrameless"):
            try:
                self.updateFrameless()
            except Exception:
                logging.debug("刷新无边框窗口状态失败", exc_info=True)
        self._enable_window_material_effect()
        if show:
            self.show()

    def _bind_controller_signals(self):
        self.controller.surveyParsed.connect(self._on_survey_parsed)
        self.controller.surveyParseFailed.connect(self._on_survey_parse_failed)
        self.controller.runFailed.connect(lambda msg: self._toast(msg, "error"))
        self.controller.runStateChanged.connect(self.dashboard.on_run_state_changed)
        self.controller.statusUpdated.connect(self.dashboard.update_status)
        self.controller.pauseStateChanged.connect(self.dashboard.on_pause_state_changed)
        self.controller.cleanupFinished.connect(self.dashboard.on_cleanup_finished)
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
        cfg = RuntimeConfig()
        self.runtime_page.apply_config(cfg)
        self.dashboard.apply_config(cfg)
        self.question_page.set_entries(cfg.question_entries or [], self.controller.questions_info)
        # 先显示本地快照，避免启动阶段显示 --/--
        try:
            count, limit, custom_api = get_random_ip_counter_snapshot_local()
            self.dashboard.update_random_ip_counter(count, limit, custom_api)
        except Exception:
            logging.debug("初始化随机IP本地计数失败", exc_info=True)
        # 后台异步刷新随机 IP 计数，避免阻塞启动
        threading.Thread(
            target=lambda: refresh_ip_counter_display(self.controller.adapter),
            daemon=True
        ).start()

    # ---------- controller callbacks ----------
    def _on_survey_parsed(self, info: List[Dict[str, Any]], title: str):
        parsed_title = title or "问卷"
        if getattr(self.dashboard, "_open_wizard_after_parse", False):
            self.dashboard._open_wizard_after_parse = False
            pending_entries = copy.deepcopy(self.controller.question_entries)
            accepted = self.dashboard._run_question_wizard(pending_entries, info, parsed_title)
            if accepted:
                self.question_page.set_questions(info, pending_entries)
                self.controller.question_entries = pending_entries
                self.dashboard.update_question_meta(parsed_title, len(pending_entries))
                self._toast("解析完成，可在'题目配置'页查看", "success")
            else:
                current_entries = self.question_page.get_entries()
                self.dashboard.update_question_meta(parsed_title, len(current_entries))
                self._toast("已取消自动配置，保留原有题目设置", "warning")
            return
        self.question_page.set_questions(info, self.controller.question_entries)
        self.dashboard.update_question_meta(parsed_title, len(self.controller.question_entries))
        self._toast("解析完成，可在'题目配置'页查看", "success")

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


def create_window() -> MainWindow:
    """供入口调用的工厂函数。"""
    return MainWindow()


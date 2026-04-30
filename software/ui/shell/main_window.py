"""主窗口模块 - 精简版，使用拆分后的组件"""
from __future__ import annotations

import copy
import logging
import os
import sys
from typing import Any, Dict, List

from PySide6.QtCore import Qt, QTimer, Signal, QEvent, Slot
from PySide6.QtGui import QIcon, QGuiApplication, QColor
from PySide6.QtWidgets import QDialog
from qfluentwidgets import (
    DotInfoBadge,
    InfoBadgePosition,
    InfoBar,
    InfoBarPosition,
    MSFluentWindow,
    Theme,
    qconfig,
    setTheme,
    setThemeColor,
)
from shiboken6 import isValid

from software.ui.pages.workbench.dashboard import DashboardPage
from software.ui.pages.workbench.reverse_fill import ReverseFillPage
from software.ui.pages.workbench.runtime_panel import RuntimePage
from software.ui.pages.workbench.question_editor.page import QuestionPage
from software.ui.pages.workbench.strategy import QuestionStrategyPage

from software.ui.dialogs.contact import ContactDialog

from software.ui.controller import RunController
from software.ui.shell.main_window_parts.dialogs import MainWindowDialogsMixin
from software.ui.shell.main_window_parts.lifecycle import MainWindowLifecycleMixin
from software.ui.shell.main_window_parts.lazy_pages import MainWindowLazyPagesMixin
from software.ui.shell.main_window_parts.update import MainWindowUpdateMixin
from software.app.config import (
    APP_ICON_RELATIVE_PATH,
    NAVIGATION_TEXT_VISIBLE_SETTING_KEY,
    STATUS_ENDPOINT,
    app_settings,
    get_bool_from_qsettings,
)
from software.logging.action_logger import log_action
from software.logging.log_utils import register_popup_handler
from software.app.version import __VERSION__
from software.network.proxy import (
    format_status_payload,
)
from software.app.runtime_paths import get_resource_path
from software.providers.common import detect_survey_provider

from software.ui.shell.boot import create_boot_splash, finish_boot_splash


class MainWindow(
    MainWindowDialogsMixin,
    MainWindowLifecycleMixin,
    MainWindowLazyPagesMixin,
    MainWindowUpdateMixin,
    MSFluentWindow,
):
    """主窗口，采用微软商店风格导航，支持主题动态切换。"""

    # 下载开始信号（显示转圈动画）
    downloadStarted = Signal()
    # 下载进度信号
    downloadProgress = Signal(int, int, float)  # downloaded, total, speed
    # 下载完成信号
    downloadFinished = Signal(str)  # downloaded_file_path
    # 下载失败信号
    downloadFailed = Signal(str)  # error_message
    # 下载源切换信号
    downloadSourceSwitched = Signal(str)  # new_source_key

    def __init__(self, parent=None):
        self._boot_splash = None
        super().__init__(parent)
        theme_path = get_resource_path(os.path.join("software", "ui", "theme.json"))
        if os.path.exists(theme_path):
            qconfig.load(theme_path)
        self._theme_sync_pending = False
        self._apply_theme_mode(qconfig.get(qconfig.themeMode))
        setThemeColor("#2563EB")
        qconfig.themeChanged.connect(self._on_theme_changed)
        self._skip_save_on_close = False
        self._community_hint_setting_key = "community_card_request_badge_pending"
        self._community_hint_pending = False
        self._community_hint_badge = None
        self._async_dialog_refs = []
        self._contact_dialog = None
        self._contact_dialog_active = False
        self._startup_update_check_timer = None
        self._startup_update_check_completed = False
        self._startup_update_check_suspended = False
        self._startup_update_notification_timer = None
        self._startup_update_pending_info = None
        self._random_ip_quota_auto_sync_interval_ms = 90000
        self._random_ip_quota_auto_sync_timer = QTimer(self)
        self._random_ip_quota_auto_sync_timer.setInterval(self._random_ip_quota_auto_sync_interval_ms)
        self._random_ip_quota_auto_sync_timer.timeout.connect(self._sync_random_ip_quota_silently)
        
        self._base_window_title = f"SurveyController v{__VERSION__}"
        self.setWindowTitle(self._base_window_title)
        icon_path = get_resource_path(os.path.join("assets", "icon.png"))
        if not os.path.exists(icon_path):
            icon_path = get_resource_path(APP_ICON_RELATIVE_PATH)
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setMinimumSize(900, 640)
        self._apply_default_window_size()
        self._enable_window_material_effect()

        # 应用窗口置顶设置
        settings = app_settings()
        if get_bool_from_qsettings(settings.value("window_topmost"), False):
            self.apply_topmost_state(True, show=False)

        # 创建启动页面
        self._boot_splash = create_boot_splash(self)

        self.controller = RunController(self)
        # 立即初始化关键页面
        self.runtime_page = RuntimePage(self.controller, self)
        self.question_page = QuestionPage(self)
        self.strategy_page = QuestionStrategyPage(self)
        self.reverse_fill_page = ReverseFillPage(self.controller, self)
        # QuestionPage 仅用作题目配置的数据载体，不作为主界面子页面展示；
        # 若不隐藏会以默认几何 (0,0,100,30) 叠在窗口左上角，造成标题栏错乱。
        self.question_page.hide()
        self.dashboard = DashboardPage(
            self.controller,
            self.question_page,
            self.runtime_page,
            self.strategy_page,
            self,
        )

        # 延迟初始化非关键页面（懒加载）
        self._log_page = None
        self._support_page = None
        self._community_page = None
        self._about_page = None
        self._changelog_page = None
        self._donate_page = None
        self._ip_usage_page = None
        self._settings_page = None
        self._last_logged_page = ""

        # 设置对象名称
        self.dashboard.setObjectName("dashboard")
        self.question_page.setObjectName("question")
        self.runtime_page.setObjectName("runtime")
        self.strategy_page.setObjectName("strategy")
        self.reverse_fill_page.setObjectName("reverse_fill")
        self.reverse_fill_page.set_open_wizard_handler(self._open_reverse_fill_wizard)
        self.reverse_fill_page.surveyUrlChanged.connect(self._sync_dashboard_url_from_reverse_fill)
        self.dashboard.url_edit.textChanged.connect(self._sync_reverse_fill_url_from_dashboard)
        self.question_page.entriesChanged.connect(lambda _count: self._sync_reverse_fill_context())

        self._init_navigation()
        self._init_community_hint_badge_state()
        self.stackedWidget.currentChanged.connect(self._on_stack_widget_changed)
        # 微软商店风格导航栏需要在事件循环后应用显示偏好，避免初始化时序抖动
        QTimer.singleShot(0, self._configure_navigation_interface)
        self._bind_controller_signals()
        self.controller.configure_ui_bridge(
            quota_request_form_opener=self._open_quota_request_form,
            on_ip_counter=self._on_random_ip_counter_update,
            message_handler=self._show_dialog_message,
            confirm_handler=self.show_confirm_dialog,
            custom_confirm_handler=self.show_custom_confirm_dialog_ui,
        )
        self._refresh_title_random_ip_user_id()
        self._sync_reverse_fill_context()
        self._register_popups()
        self._load_saved_config()
        self._start_random_ip_quota_auto_sync()
        self._center_on_screen()

        finish_boot_splash(1500)

        # 连接下载开始信号（显示转圈动画）
        self.downloadStarted.connect(self._on_download_started)
        # 连接下载进度信号
        self.downloadProgress.connect(self._update_download_progress)
        # 连接下载完成/失败信号
        self.downloadFinished.connect(self._on_download_finished)
        self.downloadFailed.connect(self._on_download_failed)
        # 连接下载源切换信号
        self.downloadSourceSwitched.connect(self._on_download_source_switched)
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
            logging.info("应用主题模式失败", exc_info=True)

    def _enable_window_material_effect(self):
        """启用窗口材质效果（Windows 下优先使用 Mica）。"""
        if not sys.platform.startswith("win"):
            return
        if not hasattr(self, "setMicaEffectEnabled"):
            return
        try:
            self.setMicaEffectEnabled(True)
        except Exception:
            logging.info("启用窗口材质效果失败", exc_info=True)

    def _read_navigation_text_visible_setting(self) -> bool:
        """读取导航标签可见性设置。"""
        settings = app_settings()
        stored_value = settings.value(NAVIGATION_TEXT_VISIBLE_SETTING_KEY)
        return get_bool_from_qsettings(stored_value, True)

    def _configure_navigation_interface(self):
        """应用微软商店风格导航栏偏好。"""
        nav = getattr(self, "navigationInterface", None)
        if nav is None:
            return
        try:
            if hasattr(nav, "setSelectedTextVisible"):
                nav.setSelectedTextVisible(self._read_navigation_text_visible_setting())
        except Exception:
            logging.info("应用导航栏显示偏好失败", exc_info=True)

    def _apply_default_window_size(self):
        """按屏幕可用区域设置默认窗口尺寸，避免高缩放场景越界。"""
        fallback_width, fallback_height = 1100, 780
        try:
            screen = self.screen() or QGuiApplication.primaryScreen()
            if not screen:
                self.resize(fallback_width, fallback_height)
                return

            available = screen.availableGeometry()
            target_width = int(available.width() * 0.78)
            target_height = int(available.height() * 0.88)

            target_width = max(900, min(target_width, 1120))
            target_height = max(640, min(target_height, 860))

            self.resize(
                min(target_width, available.width()),
                min(target_height, available.height()),
            )
        except Exception:
            logging.info("设置默认窗口尺寸失败", exc_info=True)
            self.resize(fallback_width, fallback_height)

    def _on_theme_changed(self, _theme: Theme):
        """主题变化后刷新主题敏感组件。"""
        self._enable_window_material_effect()
        try:
            drawer = getattr(getattr(self, "dashboard", None), "config_drawer", None)
            if drawer and hasattr(drawer, "_apply_theme"):
                drawer._apply_theme()
        except Exception:
            logging.info("主题变更后刷新组件失败", exc_info=True)

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

    def closeEvent(self, e):
        """窗口关闭时询问用户是否保存配置"""
        if getattr(self, "_close_request_confirmed", False):
            self._finalize_confirmed_close()
            super().closeEvent(e)
            return
        e.ignore()
        self._schedule_deferred_close_confirmation()

    def _init_community_hint_badge_state(self):
        settings = app_settings()
        self._community_hint_pending = get_bool_from_qsettings(
            settings.value(self._community_hint_setting_key),
            False,
        )
        self._refresh_community_hint_badge()

    def _set_community_hint_pending(self, pending: bool):
        self._community_hint_pending = bool(pending)
        settings = app_settings()
        settings.setValue(self._community_hint_setting_key, self._community_hint_pending)
        self._refresh_community_hint_badge()

    def _refresh_community_hint_badge(self):
        nav_item = self.navigationInterface.widget("community")
        if nav_item is None:
            return

        if not self._community_hint_pending:
            self._clear_community_hint_badge()
            return

        if self._community_hint_badge is None:
            badge_parent = nav_item.parentWidget() or self.navigationInterface
            self._community_hint_badge = DotInfoBadge.custom(
                QColor("#2563EB"),
                QColor("#60A5FA"),
                parent=badge_parent,
                target=nav_item,
                position=InfoBadgePosition.NAVIGATION_ITEM,
            )
            self._community_hint_badge.setFixedSize(8, 8)

        self._community_hint_badge.show()

    def _clear_community_hint_badge(self):
        badge = self._community_hint_badge
        if badge is None:
            return
        badge.hide()
        badge.deleteLater()
        self._community_hint_badge = None

    def _on_quota_request_sent(self):
        self._set_community_hint_pending(True)

    def _start_random_ip_quota_auto_sync(self) -> None:
        try:
            self._random_ip_quota_auto_sync_timer.start()
            QTimer.singleShot(1500, self._sync_random_ip_quota_silently)
        except Exception:
            logging.info("启动随机IP额度自动同步失败", exc_info=True)

    def _sync_random_ip_quota_silently(self) -> None:
        try:
            if self.controller.is_initializing() or bool(getattr(self.controller, "running", False)):
                return
            self.controller.sync_random_ip_counter_from_server(
                silent=True,
                min_interval_seconds=45.0,
            )
        except Exception:
            logging.info("静默同步随机IP额度失败", exc_info=True)

    def _on_stack_widget_changed(self, _index: int):
        current_widget = self.stackedWidget.currentWidget()
        current_name = current_widget.objectName() if current_widget else ""
        if current_name and current_name != self._last_logged_page:
            log_action("NAV", "switch_page", current_name, "main_window", result="opened")
            self._last_logged_page = current_name
        if current_widget and current_widget.objectName() == "community":
            self._set_community_hint_pending(False)

    def _open_contact_dialog(self, default_type: str = "报错反馈", lock_message_type: bool = False):
        dialog = getattr(self, "_contact_dialog", None)
        if dialog is not None and isValid(dialog):
            try:
                dialog.raise_()
                dialog.activateWindow()
            except Exception:
                logging.info("联系开发者窗口前置失败", exc_info=True)
            return False

        log_action(
            "UI",
            "open_contact_dialog",
            "contact_dialog",
            "main_window",
            result="shown",
            payload={"locked_type": bool(lock_message_type)},
        )
        dlg = ContactDialog(
            self,
            default_type=default_type,
            lock_message_type=lock_message_type,
            status_endpoint=STATUS_ENDPOINT,
            status_formatter=format_status_payload,
        )
        async_mode = str(default_type or "").strip() == "报错反馈"
        self._contact_dialog = dlg
        self._contact_dialog_active = True
        self._set_startup_update_check_suspended(True)
        dlg.setProperty("_lock_message_type", bool(lock_message_type))
        dlg.form.quotaRequestSucceeded.connect(self._on_quota_request_sent)
        dlg.finished.connect(self._on_contact_dialog_finished_event)
        dlg.destroyed.connect(self._on_contact_dialog_destroyed_event)
        if async_mode:
            dlg.open()
            try:
                dlg.raise_()
                dlg.activateWindow()
            except Exception:
                logging.info("异步打开联系开发者窗口后前置失败", exc_info=True)
            return False
        return dlg.exec() == QDialog.DialogCode.Accepted

    def _on_contact_dialog_finished(self, dialog: QDialog, result: int, lock_message_type: bool) -> None:
        accepted = int(result) == int(QDialog.DialogCode.Accepted)
        log_action(
            "UI",
            "open_contact_dialog",
            "contact_dialog",
            "main_window",
            result="submitted" if accepted else "cancelled",
            payload={"locked_type": bool(lock_message_type)},
        )
        self._on_contact_dialog_destroyed(dialog)

    @Slot(int)
    def _on_contact_dialog_finished_event(self, result: int) -> None:
        dialog = self.sender()
        if not isinstance(dialog, QDialog):
            return
        lock_message_type = bool(dialog.property("_lock_message_type"))
        self._on_contact_dialog_finished(dialog, result, lock_message_type)

    def _on_contact_dialog_destroyed(self, dialog: QDialog) -> None:
        current_dialog = getattr(self, "_contact_dialog", None)
        if current_dialog is dialog:
            self._contact_dialog = None
            self._contact_dialog_active = False
            self._set_startup_update_check_suspended(False)

    @Slot()
    def _on_contact_dialog_destroyed_event(self, *_args) -> None:
        dialog = getattr(self, "_contact_dialog", None)
        if isinstance(dialog, QDialog):
            self._on_contact_dialog_destroyed(dialog)

    def _show_dialog_message(self, title: str, message: str, level: str = "info") -> None:
        self.show_message_dialog(title, message, level=level)

    def _prompt_quick_bug_report(self) -> None:
        confirmed = self.show_confirm_dialog(
            "运行异常",
            "本次运行因异常提前终止，是否打开报错反馈？",
        )
        if confirmed:
            self._open_contact_dialog(default_type="报错反馈", lock_message_type=True)

    def _notify_free_ai_unstable(self) -> None:
        self._toast("目前免费AI不稳定，请稍后再试", "warning", duration=3500)

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
            logging.info("窗口居中失败", exc_info=True)

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
                logging.info("刷新无边框窗口状态失败", exc_info=True)
        self._enable_window_material_effect()
        if show:
            self.show()

    def _bind_controller_signals(self):
        self.controller.surveyParsed.connect(
            self._on_survey_parsed,
            Qt.ConnectionType.QueuedConnection,
        )
        self.controller.surveyParseFailed.connect(
            self._on_survey_parse_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        self.controller.runFailed.connect(lambda msg: self._toast(msg, "error"))
        self.controller.runStateChanged.connect(self.dashboard.on_run_state_changed)
        self.controller.runStateChanged.connect(self.reverse_fill_page.on_run_state_changed)
        self.controller.statusUpdated.connect(self.dashboard.update_status)
        self.controller.statusUpdated.connect(self.reverse_fill_page.update_status)
        self.controller.threadProgressUpdated.connect(self.dashboard.update_thread_progress)
        self.controller.pauseStateChanged.connect(self.dashboard.on_pause_state_changed)
        self.controller.pauseStateChanged.connect(self.reverse_fill_page.on_pause_state_changed)
        self.controller.cleanupFinished.connect(self.dashboard.on_cleanup_finished)
        self.controller.cleanupFinished.connect(self.reverse_fill_page.on_cleanup_finished)
        self.controller.quickBugReportSuggested.connect(self._prompt_quick_bug_report)
        self.controller.freeAiUnstableSuggested.connect(self._notify_free_ai_unstable)
        self.controller.startupHintEmitted.connect(
            lambda message, level, duration: self._toast(str(message), str(level), int(duration)),
            Qt.ConnectionType.QueuedConnection,
        )
        self.controller.on_ip_counter = self._on_random_ip_counter_update

    def _register_popups(self):
        def handler(kind: str, title: str, message: str):
            def _show():
                if kind == "confirm":
                    return self.show_confirm_dialog(title, message)
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

    # ---------- controller callbacks ----------
    @Slot(list, str)
    def _on_survey_parsed(self, info: List[Dict[str, Any]], title: str):
        parsed_title = title or "问卷"
        parsed_url = str(getattr(getattr(self.controller, "config", None), "url", "") or "")
        self._sync_dashboard_url_from_reverse_fill(parsed_url)
        self._sync_reverse_fill_url_from_dashboard(parsed_url)
        self.strategy_page.set_questions_info(info or [])
        if getattr(self.dashboard, "_open_wizard_after_parse", False):
            self.dashboard._open_wizard_after_parse = False
            info_snapshot = copy.deepcopy(info or [])
            QTimer.singleShot(
                0,
                lambda info_snapshot=info_snapshot, parsed_title=parsed_title: self._open_parse_wizard_after_parse(
                    info_snapshot,
                    parsed_title,
                ),
            )
            return
        self.question_page.set_questions(info, self.controller.question_entries)
        self.strategy_page.set_dimension_groups([])
        self.strategy_page.set_entries(self.question_page.entries, self.question_page.entry_questions_info)
        self.dashboard.update_question_meta(parsed_title, len(self.controller.question_entries))
        self._sync_reverse_fill_context()

    @Slot(str)
    def _on_survey_parse_failed(self, msg: str):
        text = str(msg or "").strip()
        if "问卷已暂停" in text:
            # 该提示已由 dashboard 处理为专用引导文案，主窗口层不重复弹出。
            self.dashboard._open_wizard_after_parse = False
            return
        self.dashboard._open_wizard_after_parse = False

    def _open_quota_request_form(self) -> bool:
        return self._open_contact_dialog(default_type="额度申请", lock_message_type=True)

    def _sync_reverse_fill_context(self) -> None:
        try:
            url_edit = getattr(self.dashboard, "url_edit", None)
            url_text = url_edit.text() if url_edit is not None and hasattr(url_edit, "text") else ""
            survey_provider = str(
                getattr(self.controller, "survey_provider", "")
                or getattr(getattr(self.controller, "config", None), "survey_provider", "")
                or detect_survey_provider(url_text, default="")
                or ""
            )
            self.reverse_fill_page.set_question_context(
                self.question_page.questions_info,
                self.question_page.get_entries(),
                survey_title=getattr(self.dashboard, "_survey_title", "") or "",
                survey_provider=survey_provider,
            )
        except Exception:
            logging.info("同步反填页上下文失败", exc_info=True)

    def _sync_dashboard_url_from_reverse_fill(self, url: str) -> None:
        text = str(url or "").strip()
        url_edit = getattr(self.dashboard, "url_edit", None)
        if url_edit is None or not hasattr(url_edit, "text") or not hasattr(url_edit, "setText"):
            return
        if str(url_edit.text() or "").strip() == text:
            return
        url_edit.blockSignals(True)
        url_edit.setText(text)
        url_edit.blockSignals(False)

    def _sync_reverse_fill_url_from_dashboard(self, url: str) -> None:
        text = str(url or "").strip()
        url_edit = getattr(self.reverse_fill_page, "url_edit", None)
        if url_edit is None or not hasattr(url_edit, "text") or not hasattr(url_edit, "setText"):
            return
        if str(url_edit.text() or "").strip() == text:
            return
        url_edit.blockSignals(True)
        url_edit.setText(text)
        url_edit.blockSignals(False)

    def _open_reverse_fill_wizard(self) -> None:
        info = list(self.question_page.questions_info or [])
        if not info:
            self._toast("当前还没有解析出题目，无法打开配置向导。", "warning")
            return
        self._open_parse_wizard_after_parse(
            copy.deepcopy(info),
            str(getattr(self.dashboard, "_survey_title", "") or "问卷"),
        )

    def _open_parse_wizard_after_parse(self, info: List[Dict[str, Any]], parsed_title: str) -> None:
        try:
            pending_entries = copy.deepcopy(self.controller.question_entries)
            accepted = self.dashboard._run_question_wizard(pending_entries, info, parsed_title)
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
                payload={"question_count": len(info or [])},
            )
            current_entries = self.question_page.get_entries()
            self.dashboard.update_question_meta(parsed_title, len(current_entries))
            self.dashboard._toast(
                "自动配置向导打开失败，已保留原有题目设置；详细原因已写入日志",
                "error",
                duration=4200,
            )
            return

        if accepted:
            self.question_page.set_questions(info, pending_entries)
            self.controller.question_entries = pending_entries
            self.strategy_page.set_dimension_groups([])
            self.strategy_page.set_entries(self.question_page.entries, self.question_page.entry_questions_info)
            self.dashboard.update_question_meta(parsed_title, len(pending_entries))
            log_action(
                "UI",
                "open_parse_wizard",
                "question_wizard",
                "main_window",
                result="accepted",
                payload={"question_count": len(info or [])},
            )
            return

        current_entries = self.question_page.get_entries()
        self.dashboard.update_question_meta(parsed_title, len(current_entries))
        log_action(
            "UI",
            "open_parse_wizard",
            "question_wizard",
            "main_window",
            result="cancelled",
            payload={"question_count": len(info or [])},
        )
        self._toast("已取消自动配置，保留原有题目设置", "warning")


def create_window() -> MainWindow:
    """供入口调用的工厂函数。"""
    return MainWindow()





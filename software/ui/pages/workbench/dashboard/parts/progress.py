"""DashboardPage 运行状态与进度展示相关方法。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, cast

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    IndeterminateProgressBar,
    MessageBox,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SegmentedWidget,
    StrongBodyLabel,
)
from software.logging.action_logger import bind_logged_action, log_action
from software.ui.helpers.fluent_tooltip import install_tooltip_filter

if TYPE_CHECKING:
    from software.ui.controller import RunController


class DashboardProgressMixin:
    """任务运行状态、总进度、线程进度面板。"""

    THREAD_VIEW_QUESTION_LIST = "question_list"
    THREAD_VIEW_PROGRESS = "thread_progress"
    _THREAD_BUSY_STATUSES = {"提交中", "等待结果确认"}

    if TYPE_CHECKING:
        controller: RunController
        status_label: StrongBodyLabel
        progress_bar: ProgressBar
        progress_indeterminate_bar: IndeterminateProgressBar
        progress_pct: StrongBodyLabel
        start_btn: PrimaryPushButton
        resume_btn: PrimaryPushButton
        stop_btn: PushButton
        thread_view_seg: SegmentedWidget
        thread_view_stack: Any
        thread_view_question_card: QWidget
        thread_view_progress_card: QWidget
        thread_progress_panel: QWidget
        thread_progress_hint: BodyLabel
        thread_progress_rows_container: QWidget
        thread_progress_rows_layout: QVBoxLayout
        _thread_progress_rows: Dict[str, Dict[str, Any]]
        _thread_view_current: str
        _thread_clear_timer: QTimer
        _completion_notified: bool
        _pending_restart: bool
        _show_end_toast_after_cleanup: bool
        _last_progress: int
        _last_pause_reason: str
        _main_progress_indeterminate: bool
        _last_device_quota_fail_count: int
        _progress_paused_visual: bool

        def _sync_start_button_state(self, running: Optional[bool] = None) -> None: ...
        def _has_question_entries(self) -> bool: ...
        def _toast(self, text: str, level: str = "info", duration: int = 2000, show_progress: bool = False) -> Optional[Any]: ...
        def _on_start_clicked(self) -> None: ...
        def window(self) -> Any: ...

    def _init_progress_state(self):
        self._thread_progress_rows = {}
        self._thread_view_current = self.THREAD_VIEW_QUESTION_LIST
        self._main_progress_indeterminate = False
        self._last_device_quota_fail_count = 0
        self._progress_paused_visual = False
        self._thread_clear_timer = QTimer(cast(QObject, self))
        self._thread_clear_timer.setSingleShot(True)
        self._thread_clear_timer.setInterval(4000)
        self._thread_clear_timer.timeout.connect(self._clear_thread_progress_rows)

    def _set_progress_bar_paused(self, bar: Any, paused: bool) -> None:
        if bar is None:
            return
        setter = getattr(bar, "setPaused", None)
        if callable(setter):
            setter(bool(paused))
            return
        if bool(paused):
            pauser = getattr(bar, "pause", None)
            if callable(pauser):
                pauser()
            return
        resumer = getattr(bar, "resume", None)
        if callable(resumer):
            resumer()

    def _apply_progress_visual_state(self, paused: bool) -> None:
        self._progress_paused_visual = bool(paused)
        self._set_progress_bar_paused(getattr(self, "progress_bar", None), paused)
        self._set_progress_bar_paused(getattr(self, "progress_indeterminate_bar", None), paused)
        for row in self._thread_progress_rows.values():
            self._set_progress_bar_paused(row.get("step_bar"), paused)
            self._set_progress_bar_paused(row.get("step_busy_bar"), paused)
            self._set_progress_bar_paused(row.get("cum_bar"), paused)

    def _status_requires_attention_visual(self, status_text: str) -> bool:
        text = str(status_text or "").strip()
        if not text:
            return False
        return "已暂停" in text or "触发智能验证" in text

    def _controller_initializing(self) -> bool:
        checker = getattr(self.controller, "is_initializing", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return False
        return False

    def _set_main_progress_indeterminate(self, enabled: bool) -> None:
        flag = bool(enabled)
        if flag == bool(getattr(self, "_main_progress_indeterminate", False)):
            return
        self._main_progress_indeterminate = flag
        bar = getattr(self, "progress_bar", None)
        indeterminate_bar = getattr(self, "progress_indeterminate_bar", None)
        if flag:
            if bar is not None:
                bar.hide()
            if indeterminate_bar is not None:
                indeterminate_bar.show()
            self.progress_pct.setText("...")
        else:
            if indeterminate_bar is not None:
                indeterminate_bar.hide()
            if bar is not None:
                bar.show()
                bar.setRange(0, 100)
                bar.setValue(max(0, min(100, int(getattr(self, "_last_progress", 0) or 0))))

    def _build_thread_progress_panel(self, parent: QWidget) -> QWidget:
        self.thread_progress_panel = QWidget(parent)
        thread_panel_layout = QVBoxLayout(self.thread_progress_panel)
        thread_panel_layout.setContentsMargins(0, 4, 0, 0)
        thread_panel_layout.setSpacing(6)
        thread_panel_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.thread_progress_hint = BodyLabel("线程进度会在任务开始后显示", self.thread_progress_panel)
        self.thread_progress_hint.setWordWrap(True)
        self.thread_progress_hint.setStyleSheet("color: #6b6b6b;")
        thread_panel_layout.addWidget(self.thread_progress_hint)
        self.thread_progress_rows_container = QWidget(self.thread_progress_panel)
        self.thread_progress_rows_layout = QVBoxLayout(self.thread_progress_rows_container)
        self.thread_progress_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.thread_progress_rows_layout.setSpacing(8)
        self.thread_progress_rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.thread_progress_rows_container.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )
        thread_panel_layout.addWidget(self.thread_progress_rows_container, 0)
        thread_panel_layout.addStretch(1)
        return self.thread_progress_panel

    def _on_thread_view_changed(self, route_key: str):
        self._set_thread_view(route_key, sync_segment=False, animate=True)

    def _set_thread_view(self, route_key: str, *, sync_segment: bool = True, animate: bool = True):
        key = route_key if route_key in (self.THREAD_VIEW_QUESTION_LIST, self.THREAD_VIEW_PROGRESS) else self.THREAD_VIEW_QUESTION_LIST
        prev = getattr(self, "_thread_view_current", self.THREAD_VIEW_QUESTION_LIST)
        self._thread_view_current = key

        if sync_segment:
            seg = getattr(self, "thread_view_seg", None)
            if seg is not None:
                current_key = None
                try:
                    route_getter = getattr(seg, "currentRouteKey", None)
                    if callable(route_getter):
                        current_key = route_getter()
                    else:
                        current_key = seg.currentItem()
                except Exception:
                    current_key = None
                if current_key != key:
                    seg.blockSignals(True)
                    seg.setCurrentItem(key)
                    seg.blockSignals(False)

        stack = getattr(self, "thread_view_stack", None)
        if stack is None:
            return

        target = self.thread_view_progress_card if key == self.THREAD_VIEW_PROGRESS else self.thread_view_question_card
        is_back = key == self.THREAD_VIEW_QUESTION_LIST and prev != key

        if hasattr(stack, "setCurrentWidget"):
            if animate:
                try:
                    stack.setCurrentWidget(target, isBack=is_back)
                    return
                except TypeError:
                    pass
            try:
                stack.setCurrentWidget(target)
                return
            except TypeError:
                stack.setCurrentWidget(target, isBack=is_back)
                return

        if hasattr(stack, "setCurrentIndex"):
            stack.setCurrentIndex(1 if key == self.THREAD_VIEW_PROGRESS else 0)

    def _build_bottom_status_card(self, outer_layout: QVBoxLayout):
        bottom = CardWidget(self)
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(12, 10, 12, 10)
        bottom_layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        self.status_label = StrongBodyLabel("等待配置...", self)
        self.progress_bar = ProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_indeterminate_bar = IndeterminateProgressBar(start=True, parent=self)
        self.progress_indeterminate_bar.hide()
        self.progress_pct = StrongBodyLabel("0%", self)
        self.progress_pct.setMinimumWidth(50)
        self.progress_pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_pct.setStyleSheet("font-size: 13px; font-weight: bold;")
        self.start_btn = PrimaryPushButton("开始执行", self)
        self.resume_btn = PrimaryPushButton("继续", self)
        self.resume_btn.setEnabled(False)
        self.resume_btn.hide()
        self.stop_btn = PushButton("停止", self)
        self.stop_btn.setEnabled(False)
        self.start_btn.setToolTip("请先配置题目（至少 1 题）")
        install_tooltip_filter(self.start_btn)

        top_row.addWidget(self.status_label)
        top_row.addWidget(self.progress_bar, 1)
        top_row.addWidget(self.progress_indeterminate_bar, 1)
        top_row.addWidget(self.progress_pct)
        top_row.addWidget(self.start_btn)
        top_row.addWidget(self.resume_btn)
        top_row.addWidget(self.stop_btn)
        bottom_layout.addLayout(top_row)
        outer_layout.addWidget(bottom)

    def _bind_progress_events(self):
        bind_logged_action(
            self.start_btn.clicked,
            self._on_start_clicked,
            scope="RUN",
            event="start_run",
            target="start_btn",
            page="dashboard",
            forward_signal_args=False,
        )
        bind_logged_action(
            self.resume_btn.clicked,
            self._on_resume_clicked,
            scope="RUN",
            event="resume_run",
            target="resume_btn",
            page="dashboard",
            forward_signal_args=False,
        )
        bind_logged_action(
            self.stop_btn.clicked,
            self.controller.stop_run,
            scope="RUN",
            event="stop_run",
            target="stop_btn",
            page="dashboard",
            forward_signal_args=False,
        )

    def update_status(self, text: str, current: int, target: int):
        if self._controller_initializing():
            self.status_label.setText("正在初始化")
            self._set_main_progress_indeterminate(True)
            self.progress_pct.setText("...")
            self._last_progress = 0
            return

        self._set_main_progress_indeterminate(False)
        status_text = str(text or "")
        quota_fail_count = max(0, int(getattr(self, "_last_device_quota_fail_count", 0) or 0))
        if (
            quota_fail_count > 0
            and "设备限制拦截" not in status_text
            and "设备达到填写次数上限" not in status_text
        ):
            status_text = f"{status_text} | 设备限制拦截 {quota_fail_count} 次"
        self.status_label.setText(status_text)
        self._apply_progress_visual_state(self._status_requires_attention_visual(status_text))
        progress = 0
        if target > 0:
            progress = min(100, int((current / max(target, 1)) * 100))
        self.progress_bar.setValue(progress)
        self.progress_pct.setText(f"{progress}%")
        self._last_progress = progress
        if (
            target > 0
            and current >= target
            and not self._completion_notified
        ):
            self._completion_notified = True
            self._toast("全部份数已完成", "success", duration=5000)
            self.stop_btn.setEnabled(False)
            self.start_btn.setEnabled(True)
            self.start_btn.setText("重新开始")

    def _clear_thread_progress_rows(self):
        while self.thread_progress_rows_layout.count():
            item = self.thread_progress_rows_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._thread_progress_rows.clear()
        self._last_device_quota_fail_count = 0
        self.thread_progress_hint.show()
        self.thread_progress_hint.setText("线程进度会在任务开始后显示")

    def _set_thread_step_busy(self, row: Dict[str, Any], busy: bool) -> None:
        step_bar = row.get("step_bar")
        step_busy_bar = row.get("step_busy_bar")
        if bool(busy):
            if step_bar is not None:
                step_bar.hide()
            if step_busy_bar is not None:
                step_busy_bar.show()
            return
        if step_busy_bar is not None:
            step_busy_bar.hide()
        if step_bar is not None:
            step_bar.show()

    def _create_thread_progress_row(self, thread_name: str) -> Dict[str, Any]:
        row_widget = QWidget(self.thread_progress_rows_container)
        row_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        row_layout = QVBoxLayout(row_widget)
        row_layout.setContentsMargins(8, 6, 8, 6)
        row_layout.setSpacing(4)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        name_label = StrongBodyLabel(thread_name, row_widget)
        status_label = BodyLabel("等待中", row_widget)
        status_label.setStyleSheet("color: #6b6b6b;")
        counter_label = BodyLabel("成功 0 | 提交失败 0", row_widget)
        counter_label.setStyleSheet("color: #6b6b6b;")
        header_layout.addWidget(name_label)
        header_layout.addWidget(status_label)
        header_layout.addStretch(1)
        header_layout.addWidget(counter_label)
        row_layout.addLayout(header_layout)

        step_layout = QHBoxLayout()
        step_layout.setContentsMargins(0, 0, 0, 0)
        step_layout.setSpacing(8)
        step_prefix = BodyLabel("步骤", row_widget)
        step_prefix.setStyleSheet("color: #6b6b6b;")
        step_bar = ProgressBar(row_widget)
        step_bar.setRange(0, 100)
        step_bar.setValue(0)
        step_busy_bar = IndeterminateProgressBar(start=True, parent=row_widget)
        step_busy_bar.hide()
        step_value = BodyLabel("0/0", row_widget)
        step_value.setMinimumWidth(58)
        step_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        step_layout.addWidget(step_prefix)
        step_layout.addWidget(step_bar, 1)
        step_layout.addWidget(step_busy_bar, 1)
        step_layout.addWidget(step_value)
        row_layout.addLayout(step_layout)

        cumulative_layout = QHBoxLayout()
        cumulative_layout.setContentsMargins(0, 0, 0, 0)
        cumulative_layout.setSpacing(8)
        cumulative_prefix = BodyLabel("累计", row_widget)
        cumulative_prefix.setStyleSheet("color: #6b6b6b;")
        cumulative_bar = ProgressBar(row_widget)
        cumulative_bar.setRange(0, 100)
        cumulative_bar.setValue(0)
        cumulative_value = BodyLabel("0%", row_widget)
        cumulative_value.setMinimumWidth(58)
        cumulative_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cumulative_layout.addWidget(cumulative_prefix)
        cumulative_layout.addWidget(cumulative_bar, 1)
        cumulative_layout.addWidget(cumulative_value)
        row_layout.addLayout(cumulative_layout)

        self.thread_progress_rows_layout.addWidget(row_widget)
        row = {
            "widget": row_widget,
            "name": name_label,
            "status": status_label,
            "counter": counter_label,
            "step_bar": step_bar,
            "step_busy_bar": step_busy_bar,
            "step_value": step_value,
            "cum_bar": cumulative_bar,
            "cum_value": cumulative_value,
        }
        self._set_progress_bar_paused(step_bar, self._progress_paused_visual)
        self._set_progress_bar_paused(step_busy_bar, self._progress_paused_visual)
        self._set_progress_bar_paused(cumulative_bar, self._progress_paused_visual)
        return row

    def update_thread_progress(self, payload: dict):
        if not isinstance(payload, dict):
            return
        if bool(payload.get("initializing")):
            self._set_main_progress_indeterminate(True)
            if self._thread_progress_rows:
                self._clear_thread_progress_rows()
            init_logs = payload.get("initialization_logs")
            lines = []
            if isinstance(init_logs, list):
                for item in init_logs:
                    text = str(item or "").strip()
                    if text:
                        lines.append(text)
            self.thread_progress_hint.show()
            if lines:
                self.thread_progress_hint.setText("\n".join(lines))
            else:
                self.thread_progress_hint.setText(str(payload.get("initializing_text") or "正在初始化..."))
            return

        self._set_main_progress_indeterminate(False)
        self._last_device_quota_fail_count = max(0, int(payload.get("device_quota_fail_count") or 0))
        thread_rows = payload.get("threads")
        if not isinstance(thread_rows, list):
            return

        running_now = bool(getattr(self.controller, "running", False))
        if running_now:
            self._thread_clear_timer.stop()
        if not thread_rows:
            if running_now:
                self.thread_progress_hint.show()
                self.thread_progress_hint.setText("正在等待线程状态...")
            return

        self.thread_progress_hint.hide()
        target = max(0, int(payload.get("target") or 0))
        num_threads = max(1, int(payload.get("num_threads") or 1))
        per_thread_target = max(0, int(payload.get("per_thread_target") or 0))
        if per_thread_target <= 0:
            per_thread_target = max(1, int((target + num_threads - 1) / num_threads)) if target > 0 else 1

        seen_names = set()
        for item in thread_rows:
            if not isinstance(item, dict):
                continue
            thread_name = str(item.get("thread_name") or "").strip()
            if not thread_name:
                continue
            thread_display_name = str(item.get("thread_display_name") or thread_name).strip() or thread_name
            seen_names.add(thread_name)
            row = self._thread_progress_rows.get(thread_name)
            if row is None:
                row = self._create_thread_progress_row(thread_display_name)
                self._thread_progress_rows[thread_name] = row
            else:
                row["name"].setText(thread_display_name)

            status_text = str(item.get("status_text") or "运行中")
            if not bool(item.get("running", True)) and not status_text:
                status_text = "已停止"

            success_count = max(0, int(item.get("success_count") or 0))
            fail_count = max(0, int(item.get("fail_count") or 0))
            step_total = max(0, int(item.get("step_total") or 0))
            step_current = max(0, int(item.get("step_current") or 0))
            if step_total > 0:
                step_current = min(step_current, step_total)
                step_percent = int(min(100, (step_current / float(step_total)) * 100))
            else:
                step_percent = 0
            cumulative_percent = int(min(100, (success_count / float(max(1, per_thread_target))) * 100))
            step_busy = status_text in self._THREAD_BUSY_STATUSES

            row["status"].setText(status_text)
            row["counter"].setText(f"成功 {success_count} | 提交失败 {fail_count}")
            self._set_thread_step_busy(row, step_busy)
            row["step_bar"].setValue(step_percent)
            row["step_value"].setText(f"{step_current}/{step_total}" if step_total > 0 else "0/0")
            row["cum_bar"].setValue(cumulative_percent)
            row["cum_value"].setText(f"{cumulative_percent}%")

        stale = [name for name in self._thread_progress_rows.keys() if name not in seen_names]
        for name in stale:
            row = self._thread_progress_rows.pop(name, None)
            if row and row.get("widget") is not None:
                row["widget"].deleteLater()

    def on_run_state_changed(self, running: bool):
        self._sync_start_button_state(running=running)
        self.stop_btn.setEnabled(running)
        log_action(
            "RUN",
            "run_state",
            "controller",
            "dashboard",
            result="running" if running else "stopped",
        )
        if not running:
            self.resume_btn.setEnabled(False)
            self.resume_btn.hide()
            self._set_main_progress_indeterminate(False)
            self._apply_progress_visual_state(
                self._status_requires_attention_visual(self.status_label.text())
            )
        if running:
            self._thread_clear_timer.stop()
            self._clear_thread_progress_rows()
            self._last_device_quota_fail_count = 0
            self._apply_progress_visual_state(False)
            if self._controller_initializing():
                self.thread_progress_hint.setText("正在初始化...")
                self.status_label.setText("正在初始化")
                self._set_main_progress_indeterminate(True)
                self.progress_pct.setText("...")
            else:
                self.thread_progress_hint.setText("正在准备线程进度...")
                self._set_main_progress_indeterminate(False)
            self._set_thread_view(self.THREAD_VIEW_PROGRESS)
            self._completion_notified = False
            self.start_btn.setText("执行中...")
            self.start_btn.setEnabled(False)
        else:
            if self._thread_progress_rows:
                self._thread_clear_timer.start()
            if self._completion_notified or self._last_progress >= 100:
                self.start_btn.setText("重新开始")
            else:
                self.start_btn.setText("开始执行")
            self.start_btn.setEnabled(self._has_question_entries())
            self.stop_btn.setEnabled(False)
            if not self._completion_notified:
                self._show_end_toast_after_cleanup = True
            if self._pending_restart:
                self._pending_restart = False
                self._on_start_clicked()

    def on_cleanup_finished(self):
        if self._show_end_toast_after_cleanup:
            self._show_end_toast_after_cleanup = False
            quota_fail_count = max(0, int(getattr(self, "_last_device_quota_fail_count", 0) or 0))
            if quota_fail_count > 0 and not self._completion_notified:
                self._toast(
                    f"任务结束，设备填写次数上限拦截 {quota_fail_count} 次",
                    "warning",
                    2200,
                )

    def on_pause_state_changed(self, paused: bool, reason: str = ""):
        self._last_pause_reason = str(reason or "")
        if not getattr(self.controller, "running", False):
            self.resume_btn.setEnabled(False)
            self.resume_btn.hide()
            return
        if paused:
            log_action(
                "RUN",
                "pause_state",
                "controller",
                "dashboard",
                result="paused",
                payload={"reason": reason or "manual"},
            )
            self._apply_progress_visual_state(True)
            self.resume_btn.show()
            self.resume_btn.setEnabled(True)
            msg = f"已暂停：{reason}" if reason else "已暂停"
            self._toast(msg, "warning", 2200)
        else:
            log_action("RUN", "pause_state", "controller", "dashboard", result="resumed")
            self._apply_progress_visual_state(
                self._status_requires_attention_visual(self.status_label.text())
            )
            self.resume_btn.setEnabled(False)
            self.resume_btn.hide()

    def _on_resume_clicked(self):
        if not getattr(self.controller, "running", False):
            log_action("RUN", "resume_run", "resume_btn", "dashboard", result="blocked")
            return
        reason = str(self._last_pause_reason or "")
        if "扣费" in reason or ("代理" in reason and "连续" in reason):
            box = MessageBox(
                "继续执行？",
                "当前处于“代理不可用保护暂停”状态。\n继续执行会重新请求代理并产生费用，确定继续吗？",
                self.window() or self,
            )
            box.yesButton.setText("继续执行")
            box.cancelButton.setText("取消")
            if not box.exec():
                log_action("RUN", "resume_run", "resume_btn", "dashboard", result="cancelled")
                return
        self.controller.resume_run()
        log_action("RUN", "resume_run", "resume_btn", "dashboard", result="submitted")


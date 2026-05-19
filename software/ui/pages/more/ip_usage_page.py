"""IP 使用记录页面主体。"""

from __future__ import annotations

import logging
import math
import threading
from typing import Any

from PySide6.QtCharts import QChart, QDateTimeAxis, QLineSeries, QValueAxis
from PySide6.QtCore import QDate, QDateTime, QPoint, QPointF, QRect, QTime, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarPosition,
    ScrollArea,
    StrongBodyLabel,
    TitleLabel,
    isDarkTheme,
    qconfig,
    themeColor,
)

from software.logging.log_utils import log_suppressed_exception
from software.system.registry_manager import RegistryManager
from software.ui.helpers.proxy_access import (
    RandomIPAuthError,
    claim_easter_egg_bonus_async,
    format_quota_value,
    format_random_ip_error,
    has_authenticated_session,
)

from .ip_usage_chart import InteractiveChartView
from .ip_usage_math import compute_monotone_slopes
from .ip_usage_overlays import ConfettiOverlay


class IpUsagePage(ScrollArea):
    _dataLoaded = Signal(object, str)
    _bonusClaimFinished = Signal(object)
    _ENABLE_CONFETTI = True

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dataLoaded.connect(self._on_data_loaded, Qt.ConnectionType.QueuedConnection)
        self._bonusClaimFinished.connect(
            self._on_bonus_claim_finished, Qt.ConnectionType.QueuedConnection
        )
        self._load_requested_once = False
        self._last_load_failed = False
        self._load_scheduled = False
        self._confetti_overlay: ConfettiOverlay | None = None
        self._confetti_played = RegistryManager.is_confetti_played()
        self._confetti_pending = False
        self._bonus_claim_in_progress = False
        self._confetti_retry_timer = QTimer(self)
        self._confetti_retry_timer.setSingleShot(True)
        self._confetti_retry_timer.timeout.connect(self._try_launch_confetti)
        self._loading = False
        self._point_meta: dict[int, tuple[str, int]] = {}
        self._data_points: list = []
        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self._build_ui()

    def _dispose_confetti_overlay(self) -> None:
        overlay = self._confetti_overlay
        if overlay is None:
            return
        try:
            overlay.hide()
            overlay.close()
            overlay.deleteLater()
        except Exception as exc:
            log_suppressed_exception("_dispose_confetti_overlay", exc, level=logging.WARNING)
        finally:
            self._confetti_overlay = None

    def _mark_confetti_played(self, played: bool = True) -> None:
        self._confetti_played = bool(played)
        try:
            RegistryManager.set_confetti_played(self._confetti_played)
        except Exception as exc:
            log_suppressed_exception("_mark_confetti_played", exc, level=logging.WARNING)

    def _build_ui(self):
        layout = QVBoxLayout(self.view)
        layout.setContentsMargins(36, 20, 36, 20)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title_row = QHBoxLayout()
        title_row.addWidget(TitleLabel("IP 使用记录", self))
        title_row.addStretch(1)
        self._ip_balance_label = StrongBodyLabel("IP池剩余数量：同步中...", self)
        title_row.addWidget(self._ip_balance_label)
        layout.addLayout(title_row)

        card = CardWidget(self)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        card_layout.setSpacing(8)
        card_layout.addWidget(StrongBodyLabel("每日提取 IP 数", self))

        self._series = QLineSeries()
        self._chart = QChart()
        self._chart.addSeries(self._series)
        self._chart.legend().hide()

        self._axis_x = QDateTimeAxis()
        self._axis_x.setFormat("MM-dd")
        self._axis_x.setTickCount(3)
        self._chart.addAxis(self._axis_x, Qt.AlignmentFlag.AlignBottom)
        self._series.attachAxis(self._axis_x)

        self._axis_y = QValueAxis()
        self._axis_y.setRange(0, 1000)
        self._axis_y.setLabelFormat("%d")
        self._axis_y.setTickType(QValueAxis.TickType.TicksDynamic)
        self._axis_y.setTickAnchor(0)
        self._axis_y.setTickInterval(1000)
        self._axis_y.setMinorTickCount(0)
        self._chart.addAxis(self._axis_y, Qt.AlignmentFlag.AlignLeft)
        self._series.attachAxis(self._axis_y)

        self._chart_view = InteractiveChartView(
            self._chart, self._series, self._point_meta, self._data_points
        )
        self._chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._chart_view.setStyleSheet("background: transparent; border: none;")
        self._chart_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._chart_view.setMinimumHeight(400)
        card_layout.addWidget(self._chart_view, 1)

        self._date_label = CaptionLabel("", self)
        self._date_label.setStyleSheet("color: #888;")
        card_layout.addWidget(self._date_label)

        layout.addWidget(card)
        layout.addStretch(1)

        self._loading_overlay = QWidget(self.viewport())
        overlay_layout = QVBoxLayout(self._loading_overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(8)
        overlay_layout.addStretch(1)
        self._loading_ring = IndeterminateProgressRing(self._loading_overlay)
        self._loading_ring.setFixedSize(44, 44)
        self._loading_ring.setStrokeWidth(3)
        overlay_layout.addWidget(self._loading_ring, 0, Qt.AlignmentFlag.AlignHCenter)
        overlay_layout.addWidget(
            BodyLabel("正在加载 IP 使用记录...", self._loading_overlay),
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        overlay_layout.addStretch(1)
        self._loading_overlay.hide()
        self._update_overlay_geometry()
        self._apply_chart_theme()
        qconfig.themeChanged.connect(self._apply_chart_theme)

    def _apply_chart_theme(self, *args) -> None:
        _ = args
        dark = isDarkTheme()
        axis_label_color = QColor(220, 225, 235) if dark else QColor(85, 90, 100)
        axis_line_color = QColor(255, 255, 255, 65) if dark else QColor(0, 0, 0, 65)
        grid_color = QColor(255, 255, 255, 28) if dark else QColor(0, 0, 0, 28)
        chart_bg_color = QColor(41, 46, 62, 225) if dark else QColor(255, 255, 255, 235)
        plot_bg_color = QColor(26, 30, 42, 220) if dark else QColor(248, 249, 252, 245)

        self._chart.setTheme(
            QChart.ChartTheme.ChartThemeDark if dark else QChart.ChartTheme.ChartThemeLight
        )
        self._chart.setBackgroundRoundness(10)
        self._chart.setBackgroundBrush(QBrush(chart_bg_color))
        self._chart.setBackgroundPen(QPen(grid_color, 1))
        self._chart.setPlotAreaBackgroundVisible(True)
        self._chart.setPlotAreaBackgroundBrush(QBrush(plot_bg_color))
        self._chart.setPlotAreaBackgroundPen(QPen(grid_color, 1))

        self._series.setPen(QPen(themeColor(), 2))
        for axis in (self._axis_x, self._axis_y):
            axis.setLabelsColor(axis_label_color)
            axis.setGridLineColor(grid_color)
            axis.setLinePenColor(axis_line_color)
            if hasattr(axis, "setMinorGridLineColor"):
                axis.setMinorGridLineColor(grid_color)

        self._date_label.setStyleSheet(
            "color: rgba(198, 205, 218, 0.78);" if dark else "color: rgba(95, 102, 114, 0.9);"
        )
        self._loading_overlay.setStyleSheet(
            "background-color: rgba(16, 19, 27, 155);"
            if dark
            else "background-color: rgba(255, 255, 255, 175);"
        )

    def _load_data(self):
        if self._loading:
            return
        self._set_loading(True)

        def _do():
            try:
                from software.io.reports.ip_usage_log import get_usage_summary

                self._dataLoaded.emit(get_usage_summary(), "")
            except Exception as exc:
                self._dataLoaded.emit({}, str(exc))

        threading.Thread(target=_do, daemon=True).start()

    @Slot(object, str)
    def _on_data_loaded(self, payload: Any, error: str):
        self._set_loading(False)
        self._last_load_failed = bool(error)

        if error:
            InfoBar.error(
                "",
                f"获取失败：{error}",
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=4000,
            )
            self._date_label.setText("加载失败，请切换页面后重试")
            self._ip_balance_label.setText("IP池剩余数量：同步失败")
            return

        data = payload if isinstance(payload, dict) else {}
        records = data.get("records")
        if not isinstance(records, list):
            records = []
        remaining_ip = self._try_int(data.get("remaining_ip"))
        self._ip_balance_label.setText(
            f"IP池剩余数量：{max(0, remaining_ip)}" if remaining_ip is not None else "IP池剩余数量：未知"
        )

        self._series.clear()
        self._point_meta.clear()
        if not records:
            self._date_label.setText("暂无数据")
            self._axis_y.setRange(0, 1000)
            now = QDateTime.currentDateTime()
            self._axis_x.setRange(now.addDays(-1), now.addDays(1))
            return

        points: list[tuple[int, int, str]] = []
        for record in records:
            label = str(record.get("label", "")).strip()
            date = QDate.fromString(label, "yyyy-MM-dd")
            if not date.isValid():
                continue
            total = self._to_int(record.get("total", 0))
            ts = int(QDateTime(date, QTime(0, 0)).toMSecsSinceEpoch())
            points.append((ts, total, label))

        if not points:
            self._date_label.setText("暂无有效日期数据")
            self._axis_y.setRange(0, 1000)
            now = QDateTime.currentDateTime()
            self._axis_x.setRange(now.addDays(-1), now.addDays(1))
            return

        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
        self._data_points.clear()
        for ts, total, label in points:
            self._data_points.append(QPointF(float(ts), float(total)))
            self._point_meta[ts] = (label, total)

        if len(xs) >= 2:
            ms = compute_monotone_slopes(xs, ys)
            self._chart_view.set_interp_data(xs, ys, ms)
            for i in range(len(xs) - 1):
                h = xs[i + 1] - xs[i]
                for j in range(12):
                    t = j / 12
                    t2, t3 = t * t, t * t * t
                    yi = (
                        (2 * t3 - 3 * t2 + 1) * ys[i]
                        + (t3 - 2 * t2 + t) * h * ms[i]
                        + (-2 * t3 + 3 * t2) * ys[i + 1]
                        + (t3 - t2) * h * ms[i + 1]
                    )
                    self._series.append(QPointF(xs[i] + t * h, yi))
            self._series.append(QPointF(xs[-1], ys[-1]))
        else:
            self._chart_view.set_interp_data(xs, ys, [0.0] * len(xs))
            for point in self._data_points:
                self._series.append(point)

        x_values = [p[0] for p in points]
        y_values = [p[1] for p in points]
        min_x = min(x_values)
        max_x = max(x_values)
        if min_x == max_x:
            center = QDateTime.fromMSecsSinceEpoch(min_x)
            self._axis_x.setRange(center.addDays(-1), center.addDays(1))
            self._axis_x.setTickCount(3)
        else:
            total_days = max(2, round((max_x - min_x) / 86400000))
            if total_days % 2 != 0:
                total_days += 1
            self._axis_x.setRange(
                QDateTime.fromMSecsSinceEpoch(min_x),
                QDateTime.fromMSecsSinceEpoch(min_x + total_days * 86400000),
            )
            self._axis_x.setTickCount(total_days // 2 + 1)

        max_val = max(y_values)
        top = max(1000, int(math.ceil(max_val / 1000.0) * 1000))
        if top == max_val:
            top += 1000
        self._axis_y.setRange(0, top)
        self._axis_y.setTickAnchor(0.0)
        self._axis_y.setTickInterval(1000.0)
        self._date_label.setText(f"{points[0][2]} ~ {points[-1][2]}")

    @staticmethod
    def _to_int(raw: Any) -> int:
        try:
            return int(raw)
        except Exception:
            try:
                return int(float(str(raw).strip()))
            except Exception:
                return 0

    @staticmethod
    def _try_int(raw: Any) -> int | None:
        try:
            return int(raw)
        except Exception:
            try:
                return int(float(str(raw).strip()))
            except Exception:
                return None

    def _set_loading(self, loading: bool) -> None:
        self._loading = bool(loading)
        if loading:
            self._update_overlay_geometry()
            self._loading_overlay.show()
        else:
            self._loading_overlay.hide()

    def _trigger_load_if_needed(self) -> None:
        self._load_scheduled = False
        if self._loading:
            return
        if (not self._load_requested_once) or self._last_load_failed:
            self._load_requested_once = True
            self._load_data()

    def _update_chart_height(self) -> None:
        viewport_height = max(self.viewport().height(), 480)
        self._chart_view.setMinimumHeight(max(400, int(viewport_height * 0.65)))

    def _update_overlay_geometry(self) -> None:
        self._loading_overlay.setGeometry(self.viewport().rect())
        self._loading_overlay.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_chart_height()
        self._update_overlay_geometry()

    def showEvent(self, event):
        super().showEvent(event)
        self._update_chart_height()
        self._update_overlay_geometry()
        if self._ENABLE_CONFETTI and (not self._confetti_played) and (not self._confetti_pending):
            self._start_bonus_claim()
        if not self._load_scheduled:
            self._load_scheduled = True
            QTimer.singleShot(0, self._trigger_load_if_needed)

    def _schedule_confetti_launch(self, delay_ms: int) -> None:
        if self._confetti_pending and not self._confetti_retry_timer.isActive():
            self._confetti_retry_timer.start(max(0, int(delay_ms)))

    def _try_launch_confetti(self):
        if not self._ENABLE_CONFETTI:
            self._confetti_pending = False
            self._dispose_confetti_overlay()
            return
        if not self._confetti_pending:
            return
        if self._loading or (not self.isVisible()):
            self._confetti_retry_timer.start(80)
            return
        top = self.window()
        if top is None:
            self._confetti_retry_timer.start(80)
            return
        size = top.size()
        if size.width() <= 0 or size.height() <= 0:
            self._confetti_retry_timer.start(80)
            return
        if self._confetti_overlay is None:
            self._confetti_overlay = ConfettiOverlay()
        global_rect = QRect(top.mapToGlobal(QPoint(0, 0)), size)
        try:
            self._confetti_overlay.setGeometry(global_rect)
            self._confetti_overlay.launch()
        except Exception as exc:
            log_suppressed_exception("_try_launch_confetti", exc, level=logging.WARNING)
            self._dispose_confetti_overlay()
            self._confetti_pending = False
            return
        self._confetti_pending = False
        self._mark_confetti_played(True)

    def _start_bonus_claim(self) -> None:
        if self._bonus_claim_in_progress:
            return
        self._bonus_claim_in_progress = True
        win = self.window()
        controller = getattr(win, "controller", None) if win is not None else None
        if controller is not None and hasattr(controller, "_async_engine_client"):
            try:
                controller._async_engine_client.submit_ui_task(
                    "claim_easter_egg_bonus",
                    self._claim_bonus_task,
                )
                return
            except Exception as exc:
                log_suppressed_exception("_start_bonus_claim submit_ui_task", exc, level=logging.WARNING)
        self._bonusClaimFinished.emit(
            {
                "level": "warning",
                "message": "领取彩蛋奖励失败：异步引擎不可用",
                "play_confetti": False,
            }
        )

    async def _claim_bonus_task(self) -> None:
        payload: dict[str, Any] = {
            "level": "success",
            "message": "🎉恭喜发现彩蛋",
            "play_confetti": True,
        }
        try:
            if not has_authenticated_session():
                payload = {
                    "level": "info",
                    "message": "🎉恭喜发现彩蛋，激活随机IP后可领取隐藏福利",
                    "play_confetti": True,
                }
            else:
                result = await claim_easter_egg_bonus_async()
                claimed = bool(result.get("claimed"))
                bonus_quota = float(result.get("bonus_quota") or 0.0)
                detail = str(result.get("detail") or "").strip()
                if claimed and bonus_quota > 0:
                    payload = {
                        "level": "success",
                        "message": f"🎉恭喜发现彩蛋，额度+{format_quota_value(bonus_quota)}",
                        "play_confetti": True,
                    }
                elif claimed:
                    payload = {
                        "level": "success",
                        "message": "🎉恭喜发现彩蛋，隐藏福利已到账",
                        "play_confetti": True,
                    }
                elif detail in {"bonus_already_claimed", "easter_egg_already_claimed"}:
                    payload = {
                        "skip_infobar": True,
                        "play_confetti": False,
                        "mark_confetti_played": True,
                    }
                else:
                    payload = {"skip_infobar": True, "play_confetti": False}
        except RandomIPAuthError as exc:
            detail = str(exc.detail or "").strip()
            if detail in {"bonus_already_claimed", "easter_egg_already_claimed"}:
                payload = {
                    "skip_infobar": True,
                    "play_confetti": False,
                    "mark_confetti_played": True,
                }
            else:
                payload = {
                    "level": "warning",
                    "message": format_random_ip_error(exc),
                    "play_confetti": False,
                }
        except Exception as exc:
            payload = {
                "level": "warning",
                "message": f"领取彩蛋奖励失败：{exc}",
                "play_confetti": False,
            }
        finally:
            self._bonusClaimFinished.emit(payload)

    @Slot(object)
    def _on_bonus_claim_finished(self, payload: Any) -> None:
        self._bonus_claim_in_progress = False
        if isinstance(payload, dict) and "mark_confetti_played" in payload:
            self._mark_confetti_played(bool(payload.get("mark_confetti_played")))
        if (
            isinstance(payload, dict)
            and bool(payload.get("play_confetti"))
            and self._ENABLE_CONFETTI
            and (not self._confetti_played)
            and (not self._confetti_pending)
        ):
            self._confetti_pending = True
            self._schedule_confetti_launch(100)
        try:
            win = self.window()
            controller = getattr(win, "controller", None) if win is not None else None
            if controller is not None:
                controller.refresh_random_ip_counter()
        except Exception as exc:
            log_suppressed_exception(
                "_on_bonus_claim_finished refresh counter",
                exc,
                level=logging.WARNING,
            )
        if isinstance(payload, dict) and bool(payload.get("skip_infobar")):
            return
        QTimer.singleShot(400, lambda current_payload=payload: self._show_easter_egg_infobar(current_payload))

    def _show_easter_egg_infobar(self, payload: Any = None):
        data = payload if isinstance(payload, dict) else {}
        level = str(data.get("level") or "success").strip().lower()
        message = str(data.get("message") or "🎉恭喜发现彩蛋").strip()
        try:
            factory = {
                "warning": InfoBar.warning,
                "error": InfoBar.error,
                "info": InfoBar.info,
                "success": InfoBar.success,
            }.get(level, InfoBar.success)
            factory(
                title="",
                content=message,
                parent=self.window(),
                position=InfoBarPosition.TOP,
                duration=5000,
            )
        except Exception as exc:
            log_suppressed_exception("_show_easter_egg_infobar", exc, level=logging.WARNING)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._load_scheduled = False
        self._confetti_retry_timer.stop()
        self._dispose_confetti_overlay()

    def closeEvent(self, event):
        self._confetti_retry_timer.stop()
        self._dispose_confetti_overlay()
        super().closeEvent(event)

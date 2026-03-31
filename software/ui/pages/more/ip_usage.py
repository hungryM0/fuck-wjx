"""IP 使用记录页面"""
from __future__ import annotations

import math
import random
import threading
import logging

from software.logging.log_utils import log_suppressed_exception
from software.system.registry_manager import RegistryManager
from software.ui.helpers.proxy_access import (
    RandomIPAuthError,
    claim_easter_egg_bonus,
    format_quota_value,
    format_random_ip_error,
    has_authenticated_session,
)

from PySide6.QtCore import Qt, QPoint, QPointF, QDate, QDateTime, QTime, Signal, QRectF, QPropertyAnimation, QEasingCurve, Property, QTimer, QByteArray
from typing import Any
from PySide6.QtCharts import QChart, QLineSeries, QChartView, QValueAxis, QDateTimeAxis
from PySide6.QtGui import QPainter, QPen, QColor, QBrush
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSizePolicy,
)
from qfluentwidgets import (
    ScrollArea,
    TitleLabel,
    CardWidget,
    StrongBodyLabel,
    CaptionLabel,
    BodyLabel,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarPosition,
    isDarkTheme,
    themeColor,
    qconfig,
)

class ConfettiOverlay(QWidget):
    """礼炮彩带动画覆盖层，透明背景、鼠标穿透，只播放一次。"""

    _COLORS = [
        QColor(255, 75, 75),
        QColor(255, 210, 0),
        QColor(60, 180, 255),
        QColor(60, 220, 110),
        QColor(200, 90, 255),
        QColor(255, 130, 0),
        QColor(255, 90, 170),
        QColor(0, 215, 195),
    ]

    def __init__(self, parent=None):
        super().__init__(None)  # 顶层窗口，不挂父控件，避免子控件透明属性崩溃
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)  # 顶层窗口才能安全使用
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._particles: list = []
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def launch(self):
        self._particles.clear()
        w, h = self.width(), self.height()
        for cannon_x, base_angle in [(w * 0.15, 65), (w * 0.85, 115)]:
            for _ in range(90):
                angle_rad = math.radians(base_angle + random.uniform(-28, 28))
                speed = random.uniform(10, 22)
                self._particles.append({
                    'x': float(cannon_x), 'y': float(h),
                    'vx': math.cos(angle_rad) * speed,
                    'vy': -math.sin(angle_rad) * speed,
                    'angle': random.uniform(0, 360),
                    'av': random.uniform(-9, 9),
                    'color': random.choice(self._COLORS),
                    'w': random.uniform(7, 13),
                    'h': random.uniform(3, 7),
                    'life': 1.0,
                    'decay': random.uniform(0.005, 0.010),
                })
        self.show()
        self.raise_()
        self._timer.start()

    def _tick(self):
        alive = []
        for p in self._particles:
            p['vy'] += 0.32
            p['vx'] *= 0.992
            p['x'] += p['vx']
            p['y'] += p['vy']
            p['angle'] += p['av']
            p['life'] -= p['decay']
            if p['life'] > 0:
                alive.append(p)
        self._particles = alive
        if not self._particles:
            self._timer.stop()
            self.hide()
        else:
            self.update()

    def paintEvent(self, event):
        if not self._particles:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for p in self._particles:
            painter.save()
            painter.translate(p['x'], p['y'])
            painter.rotate(p['angle'])
            c = QColor(p['color'])
            c.setAlphaF(min(1.0, p['life'] * 1.8))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(c)
            hw, hh = p['w'] / 2, p['h'] / 2
            painter.drawRect(int(-hw), int(-hh), int(p['w']), int(p['h']))
            painter.restore()
        painter.end()


def _compute_monotone_slopes(xs, ys):
    n = len(xs)
    d = [(ys[i+1]-ys[i])/(xs[i+1]-xs[i]) for i in range(n-1)]
    m = [0.0]*n
    m[0], m[-1] = d[0], d[-1]
    for i in range(1, n-1):
        m[i] = (d[i-1]+d[i])/2
    for i in range(n-1):
        if abs(d[i]) < 1e-10:
            m[i] = m[i+1] = 0.0
        else:
            a, b = m[i]/d[i], m[i+1]/d[i]
            s = a*a+b*b
            if s > 9:
                t = 3/math.sqrt(s)
                m[i] = t*a*d[i]; m[i+1] = t*b*d[i]
    return m

def _eval_monotone_cubic(xs, ys, ms, x):
    if x <= xs[0]: return ys[0]
    if x >= xs[-1]: return ys[-1]
    lo, hi = 0, len(xs)-2
    while lo < hi:
        mid = (lo+hi)//2
        if xs[mid+1] < x: lo = mid+1
        else: hi = mid
    i = lo; h = xs[i+1]-xs[i]; t = (x-xs[i])/h; t2, t3 = t*t, t*t*t
    return (2*t3-3*t2+1)*ys[i]+(t3-2*t2+t)*h*ms[i]+(-2*t3+3*t2)*ys[i+1]+(t3-t2)*h*ms[i+1]

class ChartOverlay(QWidget):
    def __init__(self, parent=None, curve_y_fn=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._current_x = -1.0
        self._current_y = -1.0
        self._target_x = -1.0
        self._target_y = -1.0
        self.date_str = ""
        self.ip_count = 0
        self.plot_area = QRectF()
        self._opacity = 0.0
        self._curve_y_fn = curve_y_fn
        self._anim = QPropertyAnimation(self, QByteArray(b"opacity"), self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._smooth_timer = QTimer(self)
        self._smooth_timer.setInterval(16)
        self._smooth_timer.timeout.connect(self._smooth_step)

    def _get_opacity(self): return self._opacity
    def _set_opacity(self, v): self._opacity = v; self.update()
    opacity = Property(float, _get_opacity, _set_opacity)  # type: ignore[call-arg]

    def _smooth_step(self):
        dx = self._target_x - self._current_x
        dy = self._target_y - self._current_y
        if abs(dx) < 0.5 and abs(dy) < 0.5:
            self._current_x = self._target_x
            self._current_y = self._target_y
            self._smooth_timer.stop()
        else:
            self._current_x += dx * 0.2
            if self._curve_y_fn:
                cy = self._curve_y_fn(self._current_x)
                self._current_y = cy if cy is not None else self._current_y + dy * 0.2
            else:
                self._current_y += dy * 0.2
        self.update()

    def update_point(self, x, y, date_str, ip_count, plot_area):
        self.date_str = date_str
        self.ip_count = ip_count
        self.plot_area = plot_area
        self._target_x = float(x)
        self._target_y = float(y)
        if self._opacity < 0.01:  # 首次出现直接跳到位置，不做位移缓动
            self._current_x = self._target_x
            self._current_y = self._target_y
        if not self._smooth_timer.isActive():
            self._smooth_timer.start()
        self._anim.stop()
        self._anim.setStartValue(self._opacity)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def hide_line(self):
        self._smooth_timer.stop()
        self._anim.stop()
        self._anim.setStartValue(self._opacity)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def paintEvent(self, event):
        if self._opacity < 0.01 or not self.plot_area.isValid():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)
        
        top_y = self.plot_area.top()
        bottom_y = self.plot_area.bottom()
        
        c = themeColor()
        
        # 竖线
        pen = QPen(c, 1.5, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(QPointF(self._current_x, top_y), QPointF(self._current_x, bottom_y))
        
        # 关键点小圆圈
        painter.setPen(QPen(c, 2.5))
        painter.setBrush(QColor(255, 255, 255) if not isDarkTheme() else QColor(30, 30, 30))
        painter.drawEllipse(QPointF(self._current_x, self._current_y), 5, 5)
        
        # 提示内容
        text1 = f"{self.date_str}"
        text2 = f"提取数量: {self.ip_count}"
        
        font = self.font()
        font.setPointSize(10)
        painter.setFont(font)
        fm = painter.fontMetrics()
        w1 = fm.horizontalAdvance(text1)
        w2 = fm.horizontalAdvance(text2)
        box_w = max(w1, w2) + 32
        box_h = fm.height() * 2 + 20
        
        # 计算 tooltip 位置，防越界
        box_x = self._current_x + 12
        if box_x + box_w > self.width() - 10:
            box_x = self._current_x - box_w - 12
            
        box_y = self._current_y - box_h / 2
        if box_y < top_y:
            box_y = top_y
        if box_y + box_h > bottom_y:
            box_y = bottom_y - box_h
            
        dark = isDarkTheme()
        bg_col = QColor(43, 43, 43, 245) if dark else QColor(255, 255, 255, 245)
        border_col = QColor(255, 255, 255, 20) if dark else QColor(0, 0, 0, 20)
        text_col1 = QColor(200, 200, 200) if dark else QColor(100, 100, 100)
        text_col2 = QColor(255, 255, 255) if dark else QColor(30, 30, 30)
        
        # 阴影
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 40 if not dark else 80))
        painter.drawRoundedRect(QRectF(box_x+2, box_y+3, box_w, box_h), 8, 8)
        
        # 背景卡片
        painter.setPen(QPen(border_col, 1))
        painter.setBrush(bg_col)
        painter.drawRoundedRect(QRectF(box_x, box_y, box_w, box_h), 8, 8)
        
        # 文本
        painter.setPen(text_col1)
        painter.drawText(int(box_x + 16), int(box_y + 10 + fm.ascent()), text1)
        
        painter.setPen(text_col2)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(int(box_x + 16), int(box_y + 10 + fm.height() + 6 + fm.ascent()), text2)

class InteractiveChartView(QChartView):
    def __init__(self, chart, series, point_meta_ref, data_points_ref, parent=None):
        super().__init__(chart, parent)
        self.setMouseTracking(True)
        if self.viewport():
            self.viewport().setMouseTracking(True)
        self._series = series
        self._point_meta = point_meta_ref
        self._data_points = data_points_ref
        self._interp_xs: list = []
        self._interp_ys: list = []
        self._interp_ms: list = []
        self.overlay = ChartOverlay(self, self._get_view_y_for_view_x)

    def set_interp_data(self, xs, ys, ms):
        self._interp_xs, self._interp_ys, self._interp_ms = xs, ys, ms

    def _get_view_y_for_view_x(self, view_x):
        if len(self._interp_xs) < 2:
            return None
        scene_pt = self.mapToScene(QPointF(view_x, 0).toPoint())
        data_x = self.chart().mapToValue(self.chart().mapFromScene(scene_pt), self._series).x()
        data_y = _eval_monotone_cubic(self._interp_xs, self._interp_ys, self._interp_ms, data_x)
        item_pos = self.chart().mapToPosition(QPointF(data_x, data_y), self._series)
        return self.mapFromScene(self.chart().mapToScene(item_pos)).y()
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.overlay.resize(self.size())

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        points = self._data_points
        if not points:
            self.overlay.hide_line()
            return

        pos = event.position()
        scene_pos = self.mapToScene(pos.toPoint())
        chart_item_pos = self.chart().mapFromScene(scene_pos)
        
        plot_area = self.chart().plotArea()
        # 扩大一点包围盒区域，增加图表边缘处的鼠标捕捉容错范围
        extended_area = plot_area.adjusted(-30, -30, 30, 30)
        
        if not extended_area.contains(chart_item_pos):
            self.overlay.hide_line()
            return
        
        # 抛弃逻辑坐标系计算，直接通过转化到真实屏幕试图 (View) 中的物理像素坐标来计算横向距离
        closest_p = None
        closest_view_pos = None
        min_dist = float('inf')
        
        for p in points:
            # 完整坐标系映射: 逻辑数据 -> QChart 元素 -> QGraphicsScene 场景 -> QChartView 视图组件物理像素
            item_pos = self.chart().mapToPosition(p, self._series)
            scene_pos_point = self.chart().mapToScene(item_pos)
            view_pos = self.mapFromScene(scene_pos_point)
            
            # 使用视口中的纯物理 X 像素坐标做差，获得最直观的跟随
            dist = abs(view_pos.x() - pos.x())
            if dist < min_dist:
                min_dist = dist
                closest_p = p
                closest_view_pos = view_pos
                
        if closest_p is not None:
            assert closest_view_pos is not None
            # 用于约束实线垂直上下高度的边界矩形，同样映射到当前物理视图
            top_left = self.mapFromScene(self.chart().mapToScene(plot_area.topLeft()))
            bottom_right = self.mapFromScene(self.chart().mapToScene(plot_area.bottomRight()))
            view_plot_area = QRectF(top_left, bottom_right)
            
            ts = int(round(closest_p.x()))
            label, total = self._point_meta.get(ts, (QDateTime.fromMSecsSinceEpoch(ts).toString("yyyy-MM-dd"), int(round(closest_p.y()))))
            
            self.overlay.update_point(closest_view_pos.x(), closest_view_pos.y(), label, total, view_plot_area)
        else:
            self.overlay.hide_line()
            
    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.overlay.hide_line()


class IpUsagePage(ScrollArea):
    _dataLoaded = Signal(object, str)
    _bonusClaimFinished = Signal(object)
    _ENABLE_CONFETTI = True

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dataLoaded.connect(self._on_data_loaded)
        self._bonusClaimFinished.connect(self._on_bonus_claim_finished)
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

        self._chart_view = InteractiveChartView(self._chart, self._series, self._point_meta, self._data_points)
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

        series_pen = QPen(themeColor(), 2)
        self._series.setPen(series_pen)

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
            "background-color: rgba(16, 19, 27, 155);" if dark else "background-color: rgba(255, 255, 255, 175);"
        )

    def _load_data(self):
        if self._loading:
            return
        self._set_loading(True)

        def _do():
            try:
                from software.io.reports import get_usage_summary

                summary = get_usage_summary()
                self._dataLoaded.emit(summary, "")
            except Exception as exc:
                self._dataLoaded.emit({}, str(exc))

        threading.Thread(target=_do, daemon=True).start()

    def _on_data_loaded(self, payload: Any, error: str):
        self._set_loading(False)
        self._last_load_failed = bool(error)

        if error:
            InfoBar.error("", f"获取失败：{error}", parent=self.window(), position=InfoBarPosition.TOP, duration=4000)
            self._date_label.setText("加载失败，请切换页面后重试")
            self._ip_balance_label.setText("IP池剩余数量：同步失败")
            return

        data = payload if isinstance(payload, dict) else {}
        records = data.get("records")
        if not isinstance(records, list):
            records = []
        remaining_ip = self._try_int(data.get("remaining_ip"))
        if remaining_ip is None:
            self._ip_balance_label.setText("IP池剩余数量：未知")
        else:
            self._ip_balance_label.setText(f"IP池剩余数量：{max(0, remaining_ip)}")

        self._series.clear()
        self._point_meta.clear()
        if not records:
            self._date_label.setText("暂无数据")
            self._axis_y.setRange(0, 1000)
            now = QDateTime.currentDateTime()
            self._axis_x.setRange(now.addDays(-1), now.addDays(1))
            return

        points: list[tuple[int, int, str]] = []
        for r in records:
            label = str(r.get("label", "")).strip()
            date = QDate.fromString(label, "yyyy-MM-dd")
            if not date.isValid():
                continue
            total = self._to_int(r.get("total", 0))
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
            ms = _compute_monotone_slopes(xs, ys)
            self._chart_view.set_interp_data(xs, ys, ms)
            for i in range(len(xs)-1):
                h = xs[i+1]-xs[i]
                for j in range(12):
                    t = j/12; t2, t3 = t*t, t*t*t
                    yi = (2*t3-3*t2+1)*ys[i]+(t3-2*t2+t)*h*ms[i]+(-2*t3+3*t2)*ys[i+1]+(t3-t2)*h*ms[i+1]
                    self._series.append(QPointF(xs[i]+t*h, yi))
            self._series.append(QPointF(xs[-1], ys[-1]))
        else:
            self._chart_view.set_interp_data(xs, ys, [0.0]*len(xs))
            for p in self._data_points:
                self._series.append(p)

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
                total_days += 1  # 补齐到偶数天，保证每 2 天一个刻度精确对齐
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
        target_height = max(400, int(viewport_height * 0.65))
        self._chart_view.setMinimumHeight(target_height)

    def _update_overlay_geometry(self) -> None:
        rect = self.viewport().rect()
        self._loading_overlay.setGeometry(rect)
        self._loading_overlay.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_chart_height()
        self._update_overlay_geometry()

    def showEvent(self, event):
        super().showEvent(event)
        self._update_chart_height()
        self._update_overlay_geometry()
        # 首次进入页面立即触发彩带
        if self._ENABLE_CONFETTI and (not self._confetti_played) and (not self._confetti_pending):
            self._start_bonus_claim()
        if not self._load_scheduled:
            self._load_scheduled = True
            QTimer.singleShot(0, self._trigger_load_if_needed)

    def _schedule_confetti_launch(self, delay_ms: int) -> None:
        if not self._confetti_pending:
            return
        if self._confetti_retry_timer.isActive():
            return
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
        # 懒创建：独立顶层窗口，WA_TranslucentBackground 只对顶层窗口安全
        if self._confetti_overlay is None:
            self._confetti_overlay = ConfettiOverlay()
        # 用全局坐标覆盖主窗口区域
        from PySide6.QtCore import QRect
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
        threading.Thread(target=self._claim_bonus_worker, daemon=True, name="EasterEggBonusClaim").start()

    def _claim_bonus_worker(self) -> None:
        payload: dict[str, Any] = {"level": "success", "message": "🎉恭喜发现彩蛋", "play_confetti": True}
        try:
            if not has_authenticated_session():
                payload = {"level": "info", "message": "🎉恭喜发现彩蛋，激活随机IP后可领取隐藏福利", "play_confetti": True}
            else:
                result = claim_easter_egg_bonus()
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
                    payload = {"level": "success", "message": "🎉恭喜发现彩蛋，隐藏福利已到账", "play_confetti": True}
                elif detail in {"bonus_already_claimed", "easter_egg_already_claimed"}:
                    payload = {"skip_infobar": True, "play_confetti": False, "mark_confetti_played": True}
                else:
                    payload = {"skip_infobar": True, "play_confetti": False}
        except RandomIPAuthError as exc:
            detail = str(exc.detail or "").strip()
            if detail in {"bonus_already_claimed", "easter_egg_already_claimed"}:
                payload = {"skip_infobar": True, "play_confetti": False, "mark_confetti_played": True}
            else:
                payload = {"level": "warning", "message": format_random_ip_error(exc), "play_confetti": False}
        except Exception as exc:
            payload = {"level": "warning", "message": f"领取彩蛋奖励失败：{exc}", "play_confetti": False}
        finally:
            self._bonusClaimFinished.emit(payload)

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
            log_suppressed_exception("_on_bonus_claim_finished refresh counter", exc, level=logging.WARNING)
        if isinstance(payload, dict) and bool(payload.get("skip_infobar")):
            return
        QTimer.singleShot(400, lambda p=payload: self._show_easter_egg_infobar(p))

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
            factory(title="", content=message, parent=self.window(), position=InfoBarPosition.TOP, duration=5000)
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



"""IP 使用页图表视图。"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtCharts import QChartView

from .ip_usage_math import eval_monotone_cubic
from .ip_usage_overlays import ChartOverlay


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
        data_y = eval_monotone_cubic(self._interp_xs, self._interp_ys, self._interp_ms, data_x)
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
        extended_area = plot_area.adjusted(-30, -30, 30, 30)
        if not extended_area.contains(chart_item_pos):
            self.overlay.hide_line()
            return

        closest_p = None
        closest_view_pos = None
        min_dist = float("inf")
        for p in points:
            item_pos = self.chart().mapToPosition(p, self._series)
            scene_pos_point = self.chart().mapToScene(item_pos)
            view_pos = self.mapFromScene(scene_pos_point)
            dist = abs(view_pos.x() - pos.x())
            if dist < min_dist:
                min_dist = dist
                closest_p = p
                closest_view_pos = view_pos

        if closest_p is not None:
            assert closest_view_pos is not None
            top_left = self.mapFromScene(self.chart().mapToScene(plot_area.topLeft()))
            bottom_right = self.mapFromScene(self.chart().mapToScene(plot_area.bottomRight()))
            view_plot_area = QRectF(top_left, bottom_right)
            ts = int(round(closest_p.x()))
            label, total = self._point_meta.get(
                ts,
                (
                    self._fallback_date_label(ts),
                    int(round(closest_p.y())),
                ),
            )
            self.overlay.update_point(
                closest_view_pos.x(),
                closest_view_pos.y(),
                label,
                total,
                view_plot_area,
            )
            return

        self.overlay.hide_line()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.overlay.hide_line()

    @staticmethod
    def _fallback_date_label(ts: int) -> str:
        from PySide6.QtCore import QDateTime

        return QDateTime.fromMSecsSinceEpoch(ts).toString("yyyy-MM-dd")

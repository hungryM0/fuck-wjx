"""双向时间范围滑块组件"""
from typing import Tuple, Optional
from PySide6.QtCore import Qt, Signal, QRect, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QMouseEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from qfluentwidgets import BodyLabel


class TimeRangeSlider(QWidget):
    """双向滑块，用于选择时间范围（秒）"""
    
    rangeChanged = Signal(int, int)  # (min_seconds, max_seconds)
    
    def __init__(
        self,
        min_value: int = 0,
        max_value: int = 300,
        tick_interval: int = 5,
        parent=None
    ):
        super().__init__(parent)
        self._min_value = min_value
        self._max_value = max_value
        self._tick_interval = tick_interval
        self._range_min = min_value
        self._range_max = max_value
        self._dragging_handle: Optional[str] = None  # 'min' or 'max'
        self._handle_radius = 8
        self._build_ui()
        
    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        # 显示当前范围的标签（左侧）
        self._range_label = BodyLabel(self._format_range(), self)
        self._range_label.setMinimumWidth(150)
        layout.addWidget(self._range_label)
        
        # 滑块绘制区域
        self._slider_widget = _SliderWidget(self)
        self._slider_widget.setMinimumHeight(36)
        layout.addWidget(self._slider_widget, 1)
        
    def _format_range(self) -> str:
        """格式化时间范围为 "X分Y秒 ~ X分Y秒" """
        min_m, min_s = divmod(self._range_min, 60)
        max_m, max_s = divmod(self._range_max, 60)
        return f"{min_m:01d}分{min_s:02d}秒 ~ {max_m:01d}分{max_s:02d}秒"
    
    def setRange(self, min_sec: int, max_sec: int):
        """设置范围（秒）"""
        # 对齐到分度值
        min_sec = (min_sec // self._tick_interval) * self._tick_interval
        max_sec = (max_sec // self._tick_interval) * self._tick_interval
        
        # 限制在有效范围内
        min_sec = max(self._min_value, min(min_sec, self._max_value))
        max_sec = max(self._min_value, min(max_sec, self._max_value))
        
        # 确保 min <= max
        if min_sec > max_sec:
            min_sec, max_sec = max_sec, min_sec
            
        if self._range_min != min_sec or self._range_max != max_sec:
            self._range_min = min_sec
            self._range_max = max_sec
            self._range_label.setText(self._format_range())
            self._slider_widget.update()
            self.rangeChanged.emit(self._range_min, self._range_max)
    
    def getRange(self) -> Tuple[int, int]:
        """获取当前范围（秒）"""
        return (self._range_min, self._range_max)


class _SliderWidget(QWidget):
    """内部滑块绘制组件"""
    
    def __init__(self, parent: TimeRangeSlider):
        super().__init__(parent)
        self._parent_slider = parent
        self.setMouseTracking(True)
        self._hovered_handle: Optional[str] = None
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 计算滑块轨道区域
        track_rect = self._get_track_rect()
        handle_radius = self._parent_slider._handle_radius
        
        # 绘制背景轨道
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(220, 220, 220)))
        painter.drawRoundedRect(track_rect, 3, 3)
        
        # 计算手柄位置
        min_pos = self._value_to_position(self._parent_slider._range_min)
        max_pos = self._value_to_position(self._parent_slider._range_max)
        
        # 绘制选中区域
        selected_rect = QRect(
            min_pos, track_rect.top(),
            max_pos - min_pos, track_rect.height()
        )
        painter.setBrush(QBrush(QColor(0, 120, 212)))
        painter.drawRoundedRect(selected_rect, 3, 3)
        
        # 绘制手柄
        self._draw_handle(painter, min_pos, track_rect.center().y(), 'min')
        self._draw_handle(painter, max_pos, track_rect.center().y(), 'max')
        
    def _get_track_rect(self) -> QRect:
        """获取轨道矩形"""
        margin = 12
        height = 6
        y = (self.height() - height) // 2
        return QRect(margin, y, self.width() - 2 * margin, height)
    
    def _value_to_position(self, value: int) -> int:
        """将值转换为像素位置"""
        track_rect = self._get_track_rect()
        total_range = self._parent_slider._max_value - self._parent_slider._min_value
        if total_range <= 0:
            return track_rect.left()
        ratio = (value - self._parent_slider._min_value) / total_range
        return int(track_rect.left() + ratio * track_rect.width())
    
    def _position_to_value(self, pos: int) -> int:
        """将像素位置转换为值"""
        track_rect = self._get_track_rect()
        if track_rect.width() <= 0:
            return self._parent_slider._min_value
        ratio = (pos - track_rect.left()) / track_rect.width()
        ratio = max(0.0, min(1.0, ratio))
        total_range = self._parent_slider._max_value - self._parent_slider._min_value
        value = int(self._parent_slider._min_value + ratio * total_range)
        # 对齐到分度值
        tick = self._parent_slider._tick_interval
        return (value // tick) * tick
    
    def _draw_handle(self, painter: QPainter, x: int, y: int, handle_type: str):
        """绘制手柄"""
        radius = self._parent_slider._handle_radius
        is_hovered = (self._hovered_handle == handle_type)
        is_dragging = (self._parent_slider._dragging_handle == handle_type)
        
        # 绘制圆形手柄
        if is_dragging:
            painter.setPen(QPen(QColor(0, 120, 212), 2))
            painter.setBrush(QBrush(QColor(255, 255, 255)))
        elif is_hovered:
            painter.setPen(QPen(QColor(0, 120, 212), 1))
            painter.setBrush(QBrush(QColor(255, 255, 255)))
        else:
            painter.setPen(QPen(QColor(200, 200, 200), 1))
            painter.setBrush(QBrush(QColor(255, 255, 255)))
        
        painter.drawEllipse(QPoint(x, y), radius, radius)
    
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        
        pos = event.pos()
        handle = self._get_handle_at_position(pos)
        if handle:
            self._parent_slider._dragging_handle = handle
            self.update()
    
    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.pos()
        
        if self._parent_slider._dragging_handle:
            # 拖动手柄
            new_value = self._position_to_value(pos.x())
            if self._parent_slider._dragging_handle == 'min':
                self._parent_slider.setRange(new_value, self._parent_slider._range_max)
            else:
                self._parent_slider.setRange(self._parent_slider._range_min, new_value)
        else:
            # 更新悬停状态
            handle = self._get_handle_at_position(pos)
            if handle != self._hovered_handle:
                self._hovered_handle = handle
                self.setCursor(Qt.CursorShape.PointingHandCursor if handle else Qt.CursorShape.ArrowCursor)
                self.update()
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._parent_slider._dragging_handle = None
            self.update()
    
    def _get_handle_at_position(self, pos: QPoint) -> Optional[str]:
        """检测鼠标位置下的手柄"""
        track_rect = self._get_track_rect()
        min_pos = self._value_to_position(self._parent_slider._range_min)
        max_pos = self._value_to_position(self._parent_slider._range_max)
        radius = self._parent_slider._handle_radius + 4  # 增加点击容错
        
        y_center = track_rect.center().y()
        
        # 优先检测 max 手柄（防止重叠时总是选中 min）
        if abs(pos.x() - max_pos) <= radius and abs(pos.y() - y_center) <= radius:
            return 'max'
        if abs(pos.x() - min_pos) <= radius and abs(pos.y() - y_center) <= radius:
            return 'min'
        return None

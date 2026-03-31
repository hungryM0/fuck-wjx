"""三联动占比滑块组件 - 三个滑块占比总和始终为100%"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget
from qfluentwidgets import BodyLabel, Slider as QfSlider


class RatioSlider(QWidget):
    """三联动占比滑块 - 拖动任意一个滑块时，自动调整其他两个滑块使总和保持100%"""

    valueChanged = Signal(dict)  # 发射 {"key1": value1, "key2": value2, "key3": value3}

    def __init__(self, labels: dict, parent=None):
        """初始化三联动占比滑块"""
        super().__init__(parent)

        if len(labels) != 3:
            raise ValueError("RatioSlider 必须包含恰好3个滑块")

        self.keys = list(labels.keys())
        self.labels = labels
        self._updating = False  # 防止递归更新

        # 创建布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # 创建三个滑块
        self.sliders = {}
        self.value_labels = {}

        for key in self.keys:
            row = QHBoxLayout()
            row.setSpacing(12)

            # 标签
            label = BodyLabel(labels[key], self)
            label.setFixedWidth(100)
            row.addWidget(label)

            # 滑块 - 使用 qfluentwidgets 的 Slider
            slider = QfSlider(Qt.Orientation.Horizontal, self)
            slider.setRange(0, 100)
            slider.setValue(33)  # 默认平均分配
            slider.setMinimumWidth(250)
            slider.valueChanged.connect(lambda v, k=key: self._on_slider_changed(k, v))
            self.sliders[key] = slider
            row.addWidget(slider, 1)

            # 百分比显示
            value_label = BodyLabel("33%", self)
            value_label.setFixedWidth(50)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.value_labels[key] = value_label
            row.addWidget(value_label)

            layout.addLayout(row)

        # 初始化为平均分配
        self._set_values_silently({key: 33 for key in self.keys})
        self._normalize_values()

    def _on_slider_changed(self, changed_key: str, new_value: int):
        """滑块值改变时的回调"""
        if self._updating:
            return

        self._updating = True

        # 获取当前所有值
        values = {key: self.sliders[key].value() for key in self.keys}
        values[changed_key] = new_value

        # 计算其他两个滑块的键
        other_keys = [k for k in self.keys if k != changed_key]

        # 计算剩余占比
        remaining = 100 - new_value

        if remaining < 0:
            remaining = 0

        # 获取其他两个滑块的当前值
        other_values = [values[k] for k in other_keys]
        other_sum = sum(other_values)

        # 按比例分配剩余占比
        if other_sum > 0:
            # 按原比例分配
            for k in other_keys:
                ratio = values[k] / other_sum
                values[k] = int(remaining * ratio)
        else:
            # 平均分配
            for i, k in enumerate(other_keys):
                if i == 0:
                    values[k] = remaining // 2
                else:
                    values[k] = remaining - values[other_keys[0]]

        # 确保总和为100（处理整数舍入误差）
        total = sum(values.values())
        if total != 100:
            diff = 100 - total
            # 将差值加到第一个其他滑块上
            values[other_keys[0]] += diff

        # 更新滑块和标签
        for key in self.keys:
            self.sliders[key].setValue(values[key])
            self.value_labels[key].setText(f"{values[key]}%")

        self._updating = False

        # 发射信号
        self.valueChanged.emit(values)

    def _set_values_silently(self, values: dict):
        """静默设置值（不触发信号）"""
        self._updating = True
        for key, value in values.items():
            if key in self.sliders:
                self.sliders[key].setValue(value)
                self.value_labels[key].setText(f"{value}%")
        self._updating = False

    def _normalize_values(self):
        """归一化值，确保总和为100%"""
        values = {key: self.sliders[key].value() for key in self.keys}
        total = sum(values.values())

        if total == 100:
            return

        # 按比例调整
        if total > 0:
            for key in self.keys:
                values[key] = int(values[key] * 100 / total)
        else:
            # 平均分配
            for i, key in enumerate(self.keys):
                if i < 2:
                    values[key] = 33
                else:
                    values[key] = 34

        # 处理舍入误差
        total = sum(values.values())
        if total != 100:
            diff = 100 - total
            values[self.keys[0]] += diff

        self._set_values_silently(values)

    def getValues(self) -> dict:
        """获取当前所有滑块的值"""
        return {key: self.sliders[key].value() for key in self.keys}

    def setValues(self, values: dict):
        """设置滑块的值"""
        # 验证总和
        total = sum(values.values())
        if total != 100:
            raise ValueError(f"滑块值总和必须为100%，当前为{total}%")

        self._set_values_silently(values)
        self.valueChanged.emit(values)

    def setEnabled(self, enabled: bool):
        """启用/禁用所有滑块"""
        super().setEnabled(enabled)
        for slider in self.sliders.values():
            slider.setEnabled(enabled)

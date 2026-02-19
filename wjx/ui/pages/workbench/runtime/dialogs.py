"""运行参数页 - 时间选择弹窗等辅助对话框"""
from typing import Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
)

from wjx.ui.widgets.no_wheel import NoWheelSlider, NoWheelSpinBox


def pick_time_value(parent: QWidget, title: str, current_seconds: int) -> Optional[Tuple[int, str]]:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setFixedSize(480, 360)
    main_layout = QVBoxLayout(dialog)
    main_layout.setContentsMargins(20, 20, 20, 20)
    main_layout.setSpacing(16)

    title_label = SubtitleLabel(title, dialog)
    main_layout.addWidget(title_label)

    card = CardWidget(dialog)
    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(20, 20, 20, 20)
    card_layout.setSpacing(20)

    # 实时预览
    preview_container = QWidget(card)
    preview_layout = QVBoxLayout(preview_container)
    preview_layout.setContentsMargins(0, 0, 0, 0)
    preview_layout.setSpacing(4)
    preview_hint = BodyLabel("当前设置", card)
    preview_hint.setStyleSheet("color: #888; font-size: 11px;")
    preview_value = StrongBodyLabel("0分0秒", card)
    preview_value.setStyleSheet("font-size: 18px; color: #2563EB;")
    preview_layout.addWidget(preview_hint, alignment=Qt.AlignmentFlag.AlignCenter)
    preview_layout.addWidget(preview_value, alignment=Qt.AlignmentFlag.AlignCenter)
    card_layout.addWidget(preview_container)

    # 分钟控制
    minutes_container = QWidget(card)
    minutes_layout = QHBoxLayout(minutes_container)
    minutes_layout.setContentsMargins(0, 0, 0, 0)
    minutes_layout.setSpacing(12)
    minutes_label = BodyLabel("分钟", card)
    minutes_label.setFixedWidth(50)
    minutes_slider = NoWheelSlider(Qt.Orientation.Horizontal, card)
    minutes_slider.setRange(0, 10)
    minutes_slider.setValue(current_seconds // 60)
    minutes_spin = NoWheelSpinBox(card)
    minutes_spin.setRange(0, 10)
    minutes_spin.setValue(current_seconds // 60)
    minutes_spin.setFixedWidth(70)
    minutes_layout.addWidget(minutes_label)
    minutes_layout.addWidget(minutes_slider, 1)
    minutes_layout.addWidget(minutes_spin)
    card_layout.addWidget(minutes_container)

    # 秒控制
    seconds_container = QWidget(card)
    seconds_layout = QHBoxLayout(seconds_container)
    seconds_layout.setContentsMargins(0, 0, 0, 0)
    seconds_layout.setSpacing(12)
    seconds_label = BodyLabel("秒", card)
    seconds_label.setFixedWidth(50)
    seconds_slider = NoWheelSlider(Qt.Orientation.Horizontal, card)
    seconds_slider.setRange(0, 59)
    seconds_slider.setValue(current_seconds % 60)
    seconds_spin = NoWheelSpinBox(card)
    seconds_spin.setRange(0, 59)
    seconds_spin.setValue(current_seconds % 60)
    seconds_spin.setFixedWidth(70)
    seconds_layout.addWidget(seconds_label)
    seconds_layout.addWidget(seconds_slider, 1)
    seconds_layout.addWidget(seconds_spin)
    card_layout.addWidget(seconds_container)

    main_layout.addWidget(card)
    main_layout.addStretch(1)

    def update_preview(_value=None):
        """更新预览文本（接受但忽略 valueChanged 信号的参数）"""
        m = minutes_spin.value()
        s = seconds_spin.value()
        preview_value.setText(f"{m}分{s}秒")

    minutes_slider.valueChanged.connect(minutes_spin.setValue)
    minutes_spin.valueChanged.connect(minutes_slider.setValue)
    minutes_spin.valueChanged.connect(update_preview)
    seconds_slider.valueChanged.connect(seconds_spin.setValue)
    seconds_spin.valueChanged.connect(seconds_slider.setValue)
    seconds_spin.valueChanged.connect(update_preview)
    update_preview()

    btn_row = QHBoxLayout()
    btn_row.addStretch(1)
    cancel_btn = PushButton("取消", dialog)
    cancel_btn.setMinimumWidth(90)
    ok_btn = PrimaryPushButton("确定", dialog)
    ok_btn.setMinimumWidth(90)
    btn_row.addWidget(cancel_btn)
    btn_row.addWidget(ok_btn)
    main_layout.addLayout(btn_row)

    cancel_btn.clicked.connect(dialog.reject)
    ok_btn.clicked.connect(dialog.accept)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None

    total_seconds = minutes_spin.value() * 60 + seconds_spin.value()
    label = f"{minutes_spin.value()}分{seconds_spin.value()}秒"
    return total_seconds, label

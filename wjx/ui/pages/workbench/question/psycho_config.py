"""潜变量模式配置组件"""
from typing import Any, Dict

from PySide6.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CheckBox, ComboBox

from wjx.core.questions.config import QuestionEntry


# 支持潜变量模式的题型
PSYCHO_SUPPORTED_TYPES = {"single", "scale", "score", "dropdown", "matrix"}

# 偏向选项
PSYCHO_BIAS_CHOICES = [
    ("left", "偏左（低分倾向）"),
    ("center", "居中（无偏向）"),
    ("right", "偏右（高分倾向）"),
]


def build_psycho_config_row(
    parent: QWidget,
    entry: QuestionEntry,
    psycho_check_map: Dict[int, CheckBox],
    psycho_bias_map: Dict[int, ComboBox],
    idx: int,
) -> QHBoxLayout:
    """构建潜变量模式配置行
    
    Args:
        parent: 父组件
        entry: 题目配置
        psycho_check_map: 复选框映射表
        psycho_bias_map: 偏向下拉框映射表
        idx: 题目索引
        
    Returns:
        配置行的布局
    """
    psycho_row = QHBoxLayout()
    psycho_row.setSpacing(12)
    
    # 启用潜变量模式复选框
    psycho_cb = CheckBox("启用潜变量模式", parent)
    psycho_cb.setToolTip(
        "启用后，该题将使用心理测量学模型生成答案，\n"
        "可精确控制 Cronbach's Alpha 信效度系数"
    )
    psycho_cb.setChecked(getattr(entry, "psycho_enabled", False))
    psycho_row.addWidget(psycho_cb)
    
    # 偏向选择下拉框
    bias_label = BodyLabel("偏向:", parent)
    bias_label.setStyleSheet("font-size: 12px; color: #666666;")
    psycho_row.addWidget(bias_label)
    
    bias_combo = ComboBox(parent)
    bias_combo.setFixedWidth(160)
    for value, text in PSYCHO_BIAS_CHOICES:
        bias_combo.addItem(text, userData=value)
    
    # 设置当前值
    current_bias = getattr(entry, "psycho_bias", "center")
    for i, (value, _) in enumerate(PSYCHO_BIAS_CHOICES):
        if value == current_bias:
            bias_combo.setCurrentIndex(i)
            break
    
    bias_combo.setEnabled(psycho_cb.isChecked())
    psycho_row.addWidget(bias_combo)
    
    psycho_row.addStretch(1)
    
    # 信号连接
    def on_psycho_toggled(checked: bool):
        entry.psycho_enabled = checked
        bias_combo.setEnabled(checked)
    
    def on_bias_changed(index: int):
        if 0 <= index < len(PSYCHO_BIAS_CHOICES):
            entry.psycho_bias = PSYCHO_BIAS_CHOICES[index][0]
    
    psycho_cb.toggled.connect(on_psycho_toggled)
    bias_combo.currentIndexChanged.connect(on_bias_changed)
    
    # 保存到映射表
    psycho_check_map[idx] = psycho_cb
    psycho_bias_map[idx] = bias_combo
    
    return psycho_row


def get_psycho_results(
    psycho_check_map: Dict[int, CheckBox],
    psycho_bias_map: Dict[int, ComboBox],
) -> Dict[int, Dict[str, Any]]:
    """获取潜变量模式配置结果
    
    Args:
        psycho_check_map: 复选框映射表
        psycho_bias_map: 偏向下拉框映射表
        
    Returns:
        配置结果字典
    """
    result: Dict[int, Dict[str, Any]] = {}
    for idx, cb in psycho_check_map.items():
        bias_combo = psycho_bias_map.get(idx)
        bias_value = "center"
        if bias_combo:
            bias_index = bias_combo.currentIndex()
            if 0 <= bias_index < len(PSYCHO_BIAS_CHOICES):
                bias_value = PSYCHO_BIAS_CHOICES[bias_index][0]
        result[idx] = {
            "psycho_enabled": cb.isChecked(),
            "psycho_bias": bias_value,
        }
    return result

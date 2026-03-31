"""倾向预设配置：常量与权重生成工具函数"""
from typing import List


# 支持倾向预设的题型
PSYCHO_SUPPORTED_TYPES = {"scale", "score", "dropdown", "matrix"}

# 倾向预设选项（用于 SegmentedWidget）
BIAS_PRESET_CHOICES = [
    ("left", "低分倾向"),
    ("center", "居中"),
    ("right", "高分倾向"),
    ("custom", "自定义"),
]


def build_bias_weights(option_count: int, bias: str) -> List[float]:
    """根据倾向方向生成一组权重（归一化到 0-100，使用指数曲线使倾向更激进）。"""
    import math
    count = max(1, int(option_count or 1))
    if count == 1:
        return [100.0]
    # 生成 0~1 的线性位置，再用指数放大差距
    if bias == "left":
        linear = [1.0 - i / (count - 1) for i in range(count)]
    elif bias == "right":
        linear = [i / (count - 1) for i in range(count)]
    else:
        # center: 越靠近中间越高
        center = (count - 1) / 2.0
        linear = [1.0 - abs(i - center) / center for i in range(count)]
    # 居中用3次曲线（两端适度衰减），左右倾向用8次曲线（极端压制低端）
    power = 3 if bias == "center" else 8
    raw = [math.pow(v, power) for v in linear]
    max_val = max(raw)
    if not max_val:
        return [round(100 / count)] * count
    return [round(v / max_val * 100) for v in raw]

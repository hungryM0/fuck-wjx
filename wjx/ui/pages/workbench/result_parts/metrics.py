"""信效度指标评分与文案格式化。"""
from __future__ import annotations

from typing import Optional, Tuple


def alpha_level(alpha: float) -> Tuple[str, str]:
    """Cronbach's Alpha 的颜色与等级描述。"""
    if alpha >= 0.9:
        return "#22c55e", "优秀"
    if alpha >= 0.8:
        return "#22c55e", "良好"
    if alpha >= 0.7:
        return "#f59e0b", "可接受"
    if alpha >= 0.6:
        return "#f59e0b", "勉强可接受"
    return "#ef4444", "较差"


def kmo_level(kmo: float) -> Tuple[str, str]:
    """KMO 的颜色与等级描述。"""
    if kmo >= 0.9:
        return "#22c55e", "非常适合因子分析"
    if kmo >= 0.8:
        return "#22c55e", "适合因子分析"
    if kmo >= 0.7:
        return "#3b82f6", "中等适合"
    if kmo >= 0.6:
        return "#f59e0b", "勉强适合"
    return "#ef4444", "不适合因子分析"


def bartlett_level(p: float) -> Tuple[str, str, str]:
    """Bartlett p 值的颜色、描述与文本。"""
    if p < 0.001:
        return "#22c55e", "显著（适合因子分析）", "< 0.001"
    if p < 0.01:
        return "#22c55e", "显著（适合因子分析）", f"{p:.4f}"
    if p < 0.05:
        return "#f59e0b", "边缘显著", f"{p:.4f}"
    return "#ef4444", "不显著（不适合因子分析）", f"{p:.4f}"


def bartlett_display_text(p: float, chi2: Optional[float] = None) -> Tuple[str, str, str]:
    """生成 Bartlett 展示文本（可包含卡方值）。"""
    color, desc, p_text = bartlett_level(p)
    display_text = f"p = {p_text}"
    if chi2 is not None:
        display_text = f"χ² = {chi2:.2f}, {display_text}"
    return display_text, color, desc

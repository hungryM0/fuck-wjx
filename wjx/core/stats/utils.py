"""
数学工具函数 - 从 demo/wjx/core/statistics/utils.py 移植
用于信效度计算和潜变量模型
"""
import math
import random
from typing import List

# 逆正态分布函数的系数
_NORMAL_INV_COEFFS = {
    "a": [
        -39.69683028665376,
        220.9460984245205,
        -275.9285104469687,
        138.3577518672690,
        -30.66479806614716,
        2.506628277459239,
    ],
    "b": [
        -54.47609879822406,
        161.5858368580409,
        -155.6989798598866,
        66.80131188771972,
        -13.28068155288572,
    ],
    "c": [
        -0.007784894002430293,
        -0.3223964580411365,
        -2.400758277161838,
        -2.549732539343734,
        4.374664141464968,
        2.938163982698783,
    ],
    "d": [
        0.007784695709041462,
        0.3224671290700398,
        2.445134137142996,
        3.754408661907416,
    ],
}


def randn() -> float:
    """
    生成标准正态分布随机数（Box-Muller变换）
    
    Returns:
        标准正态分布的随机数 (均值=0, 标准差=1)
    """
    u = 0.0
    v = 0.0
    while u == 0:
        u = random.random()
    while v == 0:
        v = random.random()
    return math.sqrt(-2.0 * math.log(u)) * math.cos(2.0 * math.pi * v)


def normal_inv(p: float) -> float:
    """
    逆正态分布函数（分位数函数）
    将概率值转换为对应的 Z 分数
    
    Args:
        p: 概率值 (0, 1)
        
    Returns:
        对应的 Z 分数
    """
    if p <= 0:
        return float("-inf")
    if p >= 1:
        return float("inf")
    
    plow = 0.02425
    phigh = 1 - plow
    
    a = _NORMAL_INV_COEFFS["a"]
    b = _NORMAL_INV_COEFFS["b"]
    c = _NORMAL_INV_COEFFS["c"]
    d = _NORMAL_INV_COEFFS["d"]
    
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (
            ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
        ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(
            ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
        ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


def z_to_category(z: float, option_count: int) -> int:
    """
    将连续的 Z 分数转换为离散的选项索引
    
    使用正态分布的分位点将连续值划分到离散类别中。
    例如，5个选项时，会在 -1.28, -0.52, 0.52, 1.28 处划分。
    
    Args:
        z: Z 分数（标准正态分布值）
        option_count: 选项数量（2-50）
        
    Returns:
        选项索引（0-based，范围 0 到 option_count-1）
    """
    m = max(2, min(50, option_count))
    
    for j in range(1, m):
        threshold = normal_inv(j / m)
        if z <= threshold:
            return j - 1
    
    return m - 1


def variance(values: List[float]) -> float:
    """
    计算样本方差
    
    Args:
        values: 数值列表
        
    Returns:
        样本方差（使用 n-1 作为分母）
    """
    if not values or len(values) < 2:
        return 0.0
    
    n = len(values)
    mean = sum(values) / n
    return sum((x - mean) ** 2 for x in values) / (n - 1)


def correlation(xs: List[float], ys: List[float]) -> float:
    """
    计算 Pearson 相关系数
    
    Args:
        xs: 第一组数值
        ys: 第二组数值
        
    Returns:
        相关系数 (-1 到 1)
    """
    if not xs or not ys or len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    
    num = 0.0
    dx = 0.0
    dy = 0.0
    
    for i in range(n):
        a = xs[i] - mx
        b = ys[i] - my
        num += a * b
        dx += a * a
        dy += b * b
    
    den = math.sqrt(dx * dy)
    return num / den if den != 0 else 0.0


def cronbach_alpha(matrix: List[List[float]]) -> float:
    """
    计算 Cronbach's Alpha 系数
    
    Args:
        matrix: 数据矩阵，每行是一个样本，每列是一个题目
        
    Returns:
        Cronbach's Alpha 系数
    """
    if not matrix or len(matrix) == 0:
        return 0.0
    
    k = len(matrix[0])  # 题目数
    if k < 2:
        return 0.0
    
    # 计算总分的方差
    totals = [sum(row) for row in matrix]
    var_total = variance(totals)
    
    if var_total == 0:
        return 0.0
    
    # 计算各题目方差之和
    sum_item_var = 0.0
    for j in range(k):
        item_values = [row[j] for row in matrix]
        sum_item_var += variance(item_values)
    
    return (k / (k - 1)) * (1 - (sum_item_var / var_total))

"""统一的类型转换和验证工具"""


def safe_int(value, default=0):
    """安全转换为整数"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_float(value, default=0.0):
    """安全转换为浮点数"""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_str(value, default=""):
    """安全转换为字符串"""
    return str(value) if value is not None else default


def is_sequence(value):
    """检查是否为序列类型（列表或元组）"""
    return isinstance(value, (list, tuple))


def normalize_text(text):
    """标准化文本（去除空白、None处理）"""
    if not text:
        return ""
    return str(text).strip()

"""代理相关常量和枚举"""
from enum import Enum


class ProxySource(str, Enum):
    """代理源类型"""
    DEFAULT = "default"
    PIKACHU = "pikachu"
    CUSTOM = "custom"

"""题目相关常量和枚举"""
from enum import Enum


class QuestionType(str, Enum):
    """题型代码"""
    SINGLE = "3"
    MULTIPLE = "4"
    SCALE = "5"
    SCORE = "6"
    DROPDOWN = "7"
    TEXT = "8"
    MATRIX = "9"
    SLIDER = "10"
    REORDER = "11"

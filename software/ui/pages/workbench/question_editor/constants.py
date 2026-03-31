"""题目配置常量定义"""
from typing import Dict

from software.core.questions.config import QuestionEntry

# 题目类型选项
TYPE_CHOICES = [
    ("single", "单选题"),
    ("multiple", "多选题"),
    ("text", "填空题"),
    ("dropdown", "下拉题"),
    ("matrix", "矩阵题"),
    ("scale", "量表题"),
    ("score", "评价题"),
    ("slider", "滑块题"),
    ("order", "排序题"),
]

# 填写策略选项
STRATEGY_CHOICES = [
    ("random", "完全随机"),
    ("custom", "自定义配比"),
]

TYPE_LABEL_MAP: Dict[str, str] = {value: label for value, label in TYPE_CHOICES}
TYPE_LABEL_MAP.update(
    {
        "multi_text": "多项填空题",
    }
)


def _get_entry_type_label(entry: QuestionEntry) -> str:
    """获取题目类型的中文标签"""
    return TYPE_LABEL_MAP.get(entry.question_type, entry.question_type)


def _get_type_label(q_type: str) -> str:
    return TYPE_LABEL_MAP.get(q_type, q_type)



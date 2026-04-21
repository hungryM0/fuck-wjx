"""数据结构定义。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class OptionSchema:
    """选项结构。"""
    text: str                           # 选项文本
    value: Any = None                   # 选项值（可选）
    aliases: list[str] = field(default_factory=list)  # 别名列表


@dataclass
class QuestionSchema:
    """题目结构。"""
    qid: str                            # Q1, Q2, Q3...
    index: int                          # 1, 2, 3...
    title: str                          # 题干
    qtype: str                          # single_choice / multi_choice / text / matrix / scale
    required: bool = True               # 是否必填
    options: list[OptionSchema] = field(default_factory=list)  # 选项列表


@dataclass
class SurveySchema:
    """问卷结构。"""
    title: str
    questions: list[QuestionSchema]


@dataclass
class SampleRow:
    """Excel 样本行。"""
    row_no: int                         # 行号
    values: dict[str, Any]              # Excel列名 → 单元格值
    normalized_answers: dict[str, Any] = field(default_factory=dict)  # qid → 标准答案
    status: str = "pending"             # pending / running / success / failed
    error: Optional[str] = None         # 错误信息


@dataclass
class MappingItem:
    """单个映射项。"""
    excel_col: str                      # Excel 列名
    survey_qid: str                     # 问卷题目 ID
    survey_index: int                   # 问卷题目序号
    survey_title: str                   # 问卷题目标题
    confidence: float                   # 匹配置信度
    mode: str                           # by_index / by_title_exact / by_title_fuzzy


@dataclass
class MappingPlan:
    """映射计划。"""
    items: list[MappingItem]
    by_qid: dict[str, MappingItem] = field(default_factory=dict)

    def build_index(self):
        """构建 qid 索引。"""
        self.by_qid = {x.survey_qid: x for x in self.items}

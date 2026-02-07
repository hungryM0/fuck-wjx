"""统计数据模型"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional


@dataclass
class OptionStats:
    """单个选项的统计数据"""
    option_index: int       # 选项索引 (0-based)
    option_text: str = ""   # 选项文本（可选，用于显示）
    count: int = 0          # 被选中的次数


@dataclass
class QuestionStats:
    """单道题目的统计数据"""
    question_num: int                           # 题号
    question_type: str                          # 题型 (single/multiple/matrix/scale/text...)
    question_title: Optional[str] = None        # 题目标题
    options: Dict[int, OptionStats] = field(default_factory=dict)  # 选项索引 -> 统计
    total_responses: int = 0                    # 该题的总作答次数
    # 矩阵题专用：每行独立统计
    rows: Optional[Dict[int, Dict[int, int]]] = None  # row_index -> {col_index: count}
    # 填空题专用：记录填写的文本
    text_answers: Optional[Dict[str, int]] = None     # answer_text -> count
    # 配置元数据：用于展示时补全所有选项/行列（即使计数为0）
    option_count: Optional[int] = None          # 总选项数
    matrix_rows: Optional[int] = None           # 矩阵题总行数
    matrix_cols: Optional[int] = None           # 矩阵题总列数

    def record_selection(self, option_index: int) -> None:
        """记录一次选项选择"""
        if option_index not in self.options:
            self.options[option_index] = OptionStats(option_index=option_index, option_text="")
        self.options[option_index].count += 1
        self.total_responses += 1

    def record_matrix_selection(self, row_index: int, col_index: int) -> None:
        """记录矩阵题选择"""
        if self.rows is None:
            self.rows = {}
        if row_index not in self.rows:
            self.rows[row_index] = {}
        self.rows[row_index][col_index] = self.rows[row_index].get(col_index, 0) + 1
        self.total_responses += 1

    def record_text_answer(self, text: str) -> None:
        """记录填空题答案"""
        if self.text_answers is None:
            self.text_answers = {}
        self.text_answers[text] = self.text_answers.get(text, 0) + 1
        self.total_responses += 1

    def get_option_percentage(self, option_index: int) -> float:
        """获取某选项的占比（百分比）"""
        if self.total_responses == 0:
            return 0.0
        option = self.options.get(option_index)
        if option is None:
            return 0.0
        return (option.count / self.total_responses) * 100.0


@dataclass
class SurveyStats:
    """问卷级别统计数据"""
    survey_url: str                             # 问卷URL
    survey_title: Optional[str] = None          # 问卷标题
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    total_submissions: int = 0                  # 总提交份数
    failed_submissions: int = 0                 # 失败次数
    questions: Dict[int, QuestionStats] = field(default_factory=dict)  # 题号 -> 统计

    def get_or_create_question(self, question_num: int, question_type: str) -> QuestionStats:
        """获取或创建题目统计"""
        if question_num not in self.questions:
            self.questions[question_num] = QuestionStats(
                question_num=question_num,
                question_type=question_type
            )
        return self.questions[question_num]

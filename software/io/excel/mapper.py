"""题目映射器。"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

from rapidfuzz import fuzz

if TYPE_CHECKING:
    from software.io.excel.schema import SurveySchema, MappingPlan

from software.io.excel.schema import MappingItem, MappingPlan as _MappingPlan


def normalize_text(s: str) -> str:
    """标准化文本：去括号、去题号前缀、去标点、转小写。
    
    Args:
        s: 原始文本
        
    Returns:
        标准化后的文本
    """
    s = str(s or "").strip().lower()
    # 去括号及括号内容
    s = re.sub(r"[（(].*?[）)]", "", s)
    # 去题号前缀（支持多种格式：1、 1. Q1 等）
    s = re.sub(r"^[qQ]?\d+[、.．\s_-]+", "", s)
    # 去空格
    s = re.sub(r"\s+", "", s)
    # 去标点
    s = re.sub(r"[，。、""''：:；;！？!?—]", "", s)
    s = s.replace("-", "")
    # 去"—"符号（矩阵题常用）
    s = s.replace("—", "")
    return s


def extract_question_index(text: str) -> Optional[int]:
    """提取题号。
    
    支持格式：
    - Q1 → 1
    - q1 → 1
    - 1、 → 1
    - 1. → 1
    - 1 → 1
    
    Args:
        text: 文本
        
    Returns:
        题号，如果无法提取则返回 None
    """
    text = str(text or "").strip()
    
    # 匹配 Q1、q1 格式
    m = re.match(r"^[qQ](\d+)", text)
    if m:
        return int(m.group(1))
    
    # 匹配 1、、1.、1．格式
    m = re.match(r"^(\d+)[、.．\s_-]", text)
    if m:
        return int(m.group(1))
    
    # 匹配纯数字开头
    m = re.match(r"^(\d+)$", text)
    if m:
        return int(m.group(1))
    
    return None


class QuestionMatcher:
    """题目映射器。
    
    按优先级匹配 Excel 列到问卷题目：
    1. 题号匹配
    2. 标题精确匹配
    3. 模糊匹配（相似度 ≥ 90%）
    4. 否则报错
    """

    def __init__(self, fuzzy_threshold: float = 90.0):
        """初始化。
        
        Args:
            fuzzy_threshold: 模糊匹配阈值（0-100）
        """
        self.fuzzy_threshold = fuzzy_threshold

    def build_mapping(
        self, 
        excel_columns: list[str], 
        survey: SurveySchema,
        skip_unmatchable: bool = True,
    ) -> MappingPlan:
        """构建映射计划。
        
        Args:
            excel_columns: Excel 列名列表
            survey: 问卷结构
            skip_unmatchable: 是否跳过无法匹配的列（默认 True）
            
        Returns:
            映射计划
            
        Raises:
            ValueError: 当 skip_unmatchable=False 且无法自动匹配某列时
        """
        items = []
        
        # 构建问卷题目索引
        q_by_index = {q.index: q for q in survey.questions}
        q_by_norm_title = {normalize_text(q.title): q for q in survey.questions}
        used_qids = set()
        
        # 常见的非题目列名（需要跳过）
        skip_keywords = [
            '序号', '编号', 'id', 'no', 'number',
            '时间', 'time', '日期', 'date',
            '来源', 'source', '渠道', 'channel',
            'ip', '地址', 'address',
            '总分', '得分', 'score', 'total',
            '状态', 'status',
        ]

        for col in excel_columns:
            # 检查是否是需要跳过的列
            col_lower = col.lower()
            if any(keyword in col_lower for keyword in skip_keywords):
                continue
            
            matched = None
            mode = None
            confidence = 0.0

            # 1) 按题号匹配
            col_idx = extract_question_index(col)
            if col_idx is not None and col_idx in q_by_index:
                q = q_by_index[col_idx]
                if q.qid not in used_qids:
                    matched = q
                    mode = "by_index"
                    confidence = 1.0

            # 2) 按标题精确匹配
            if matched is None:
                norm_col = normalize_text(col)
                q = q_by_norm_title.get(norm_col)
                if q is not None and q.qid not in used_qids:
                    matched = q
                    mode = "by_title_exact"
                    confidence = 0.98

            # 3) 按模糊匹配
            if matched is None:
                norm_col = normalize_text(col)
                best_q = None
                best_score = -1.0
                
                for q in survey.questions:
                    if q.qid in used_qids:
                        continue
                    score = fuzz.ratio(norm_col, normalize_text(q.title))
                    if score > best_score:
                        best_score = score
                        best_q = q
                
                if best_q is not None and best_score >= self.fuzzy_threshold:
                    matched = best_q
                    mode = "by_title_fuzzy"
                    confidence = best_score / 100.0

            # 4) 无法匹配的处理
            if matched is None:
                if skip_unmatchable:
                    # 跳过无法匹配的列
                    continue
                else:
                    # 报错
                    raise ValueError(
                        f"Excel 列无法自动匹配到问卷题目: '{col}'\n"
                        f"请检查列名是否包含题号（如 Q1、1、）或与题目标题相似"
                    )

            used_qids.add(matched.qid)
            items.append(
                MappingItem(
                    excel_col=col,
                    survey_qid=matched.qid,
                    survey_index=matched.index,
                    survey_title=matched.title,
                    confidence=confidence,
                    mode=mode,
                )
            )

        plan = _MappingPlan(items=items)
        plan.build_index()
        return plan

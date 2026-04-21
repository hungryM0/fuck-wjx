"""答案标准化器。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from rapidfuzz import fuzz

if TYPE_CHECKING:
    from software.io.excel.schema import QuestionSchema

from software.io.excel.mapper import normalize_text


# 7级量表数值映射
LIKERT7 = {
    1: "非常不同意",
    2: "不同意",
    3: "有点不同意",
    4: "中立",
    5: "有点同意",
    6: "同意",
    7: "非常同意",
}

# 5级量表数值映射
LIKERT5 = {
    1: "非常不满意",
    2: "不满意",
    3: "一般",
    4: "满意",
    5: "非常满意",
}

# 全局别名字典
GLOBAL_ALIASES = {
    "是": ["是", "yes", "y", "1", "true", "对"],
    "否": ["否", "no", "n", "0", "false", "错"],
    "男": ["男", "male", "m", "先生", "boy"],
    "女": ["女", "female", "f", "女士", "girl"],
    "中立": ["中立", "一般", "普通", "neutral", "不确定"],
    "非常同意": ["非常同意", "完全同意", "strongly agree"],
    "同意": ["同意", "agree"],
    "有点同意": ["有点同意", "比较同意", "somewhat agree"],
    "有点不同意": ["有点不同意", "比较不同意", "somewhat disagree"],
    "不同意": ["不同意", "disagree"],
    "非常不同意": ["非常不同意", "完全不同意", "strongly disagree"],
}


class AnswerNormalizer:
    """答案标准化器。
    
    按优先级标准化答案：
    1. 选项文本精确匹配
    2. 别名表匹配
    3. 量表数值映射
    4. 模糊匹配（相似度 ≥ 90%）
    5. 否则报错
    """

    def __init__(self, fuzzy_threshold: float = 90.0):
        """初始化。
        
        Args:
            fuzzy_threshold: 模糊匹配阈值（0-100）
        """
        self.fuzzy_threshold = fuzzy_threshold

    def normalize_answer(
        self, 
        question: QuestionSchema, 
        raw_value: Any
    ) -> Any:
        """标准化答案。
        
        Args:
            question: 题目结构
            raw_value: 原始答案值
            
        Returns:
            标准化后的答案
            
        Raises:
            ValueError: 答案无法识别或必填题缺少答案
        """
        # 处理空值
        if raw_value is None or str(raw_value).strip() == "":
            if question.required:
                raise ValueError(f"{question.qid} 缺少答案")
            return None

        raw_text = str(raw_value).strip()

        # 文本题直接返回
        if question.qtype == "text":
            return raw_text

        # 多选题处理（支持逗号、分号、顿号分隔）
        if question.qtype == "multi_choice":
            import re
            parts = re.split(r"[,，;；、]", raw_text)
            normalized_parts = []
            for part in parts:
                part = part.strip()
                if part:
                    normalized_part = self._normalize_single_option(question, part)
                    normalized_parts.append(normalized_part)
            return normalized_parts if normalized_parts else None

        # 单选题、量表题处理
        return self._normalize_single_option(question, raw_text)

    def _normalize_single_option(
        self, 
        question: QuestionSchema, 
        raw_text: str
    ) -> str:
        """标准化单个选项。
        
        Args:
            question: 题目结构
            raw_text: 原始文本
            
        Returns:
            标准化后的选项文本
            
        Raises:
            ValueError: 选项无法识别
        """
        raw_text = raw_text.strip()

        # 1) 选项文本精确匹配
        for opt in question.options:
            if raw_text == opt.text:
                return opt.text

        # 2) 选项别名匹配（大小写不敏感）
        raw_lower = raw_text.lower()
        for opt in question.options:
            candidates = [opt.text] + list(opt.aliases or [])
            for c in candidates:
                if raw_lower == str(c).strip().lower():
                    return opt.text

        # 3) 全局别名映射
        for standard, aliases in GLOBAL_ALIASES.items():
            # 检查原始值是否在别名列表中
            for alias in aliases:
                if raw_lower == str(alias).strip().lower():
                    # 在选项中查找标准名称
                    for opt in question.options:
                        if opt.text == standard or normalize_text(opt.text) == normalize_text(standard):
                            return opt.text

        # 4) 量表数值映射
        if question.qtype in ("single_choice", "scale"):
            try:
                n = int(float(raw_text))
                
                # 尝试 7 级量表
                if n in LIKERT7:
                    mapped = LIKERT7[n]
                    for opt in question.options:
                        if opt.text == mapped or normalize_text(opt.text) == normalize_text(mapped):
                            return opt.text
                
                # 尝试 5 级量表（满意度）
                if n in LIKERT5:
                    mapped = LIKERT5[n]
                    for opt in question.options:
                        if opt.text == mapped or normalize_text(opt.text) == normalize_text(mapped):
                            return opt.text
                
                # 尝试直接数字匹配（如选项就是 "1", "2", "3"）
                for opt in question.options:
                    try:
                        if int(float(opt.text)) == n:
                            return opt.text
                    except (ValueError, TypeError):
                        pass
                        
            except (ValueError, TypeError):
                pass

        # 5) 模糊匹配
        best_opt = None
        best_score = -1.0
        norm_raw = normalize_text(raw_text)
        
        for opt in question.options:
            score = fuzz.ratio(norm_raw, normalize_text(opt.text))
            if score > best_score:
                best_score = score
                best_opt = opt

        if best_opt is not None and best_score >= self.fuzzy_threshold:
            return best_opt.text

        # 6) 无法识别，报错
        available_options = ", ".join([opt.text for opt in question.options[:5]])
        if len(question.options) > 5:
            available_options += "..."
        
        raise ValueError(
            f"{question.qid} 答案无法识别: '{raw_text}'\n"
            f"可用选项: {available_options}"
        )

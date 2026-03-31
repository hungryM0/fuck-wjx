"""上下文追踪与画像约束引擎

职责：
1. 追踪每份问卷中已答题目的选择，供后续题目参考
2. 根据画像关键词匹配选项文本，给匹配的选项加权（x3）
3. 为 AI 填空题提供完整的上下文信息
"""
import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from software.core.persona.generator import get_current_persona


# ── 已答题目记录 ────────────────────────────────────────────

@dataclass
class AnsweredQuestion:
    """单题作答记录"""
    question_num: int
    question_type: str          # "single" / "multiple" / "text" / "scale" 等
    selected_indices: List[int] = field(default_factory=list)   # 选中的选项索引
    selected_texts: List[str] = field(default_factory=list)     # 选中的选项文本
    text_answer: str = ""       # 填空题答案
    row_answers: Dict[int, List[int]] = field(default_factory=dict)  # 矩阵题行级答案：行索引(0-based) -> 选项索引列表


# ── 线程局部上下文 ──────────────────────────────────────────

_thread_local = threading.local()

# 权重加成倍数：匹配画像的选项权重乘以此值
PERSONA_BOOST_FACTOR = 3.0


def reset_context() -> None:
    """清空当前线程的作答上下文（每份问卷开始时调用）。"""
    _thread_local.answered = {}


def record_answer(
    question_num: int,
    question_type: str,
    selected_indices: Optional[List[int]] = None,
    selected_texts: Optional[List[str]] = None,
    text_answer: str = "",
    row_index: Optional[int] = None,
) -> None:
    """记录一道题的作答结果。row_index 非 None 时表示矩阵题的行级记录。"""
    ctx = getattr(_thread_local, "answered", None)
    if ctx is None:
        _thread_local.answered = {}
        ctx = _thread_local.answered
    if row_index is not None:
        # 矩阵题行级记录：更新或新建该题的记录
        if question_num not in ctx:
            ctx[question_num] = AnsweredQuestion(
                question_num=question_num,
                question_type=question_type,
            )
        ctx[question_num].row_answers[row_index] = selected_indices or []
    else:
        ctx[question_num] = AnsweredQuestion(
            question_num=question_num,
            question_type=question_type,
            selected_indices=selected_indices or [],
            selected_texts=selected_texts or [],
            text_answer=text_answer,
        )


def get_answered() -> Dict[int, AnsweredQuestion]:
    """获取当前线程的全部已答题目。"""
    return getattr(_thread_local, "answered", {})


# ── 画像约束：给选项加权 ───────────────────────────────────

def apply_persona_boost(
    option_texts: List[str],
    base_weights: List[float],
) -> List[float]:
    """根据当前画像，对匹配的选项进行权重加成。"""
    persona = get_current_persona()
    if persona is None:
        return list(base_weights)

    keyword_map = persona.to_keyword_map()
    if not keyword_map:
        return list(base_weights)

    # 把所有关键词扁平化
    all_keywords: List[str] = []
    for keywords in keyword_map.values():
        all_keywords.extend(keywords)

    if not all_keywords:
        return list(base_weights)

    boosted = list(base_weights)
    for i, text in enumerate(option_texts):
        if not text or i >= len(boosted):
            continue
        text_lower = text.strip()
        for keyword in all_keywords:
            if keyword in text_lower:
                boosted[i] *= PERSONA_BOOST_FACTOR
                logging.info(
                    "画像约束：选项[%d]「%s」匹配关键词「%s」，权重 x%.1f",
                    i, text[:20], keyword, PERSONA_BOOST_FACTOR,
                )
                break  # 一个选项只加成一次
    return boosted


# TODO(清理): 疑似未使用，先保留，确认外部是否有引用再决定删除。
def get_persona_name_gender() -> Tuple[Optional[str], Optional[str]]:
    """获取当前画像的性别信息，用于填空题生成姓名时保持一致。"""
    persona = get_current_persona()
    if persona is None:
        return None, None
    return persona.gender, None


# ── AI 上下文构建 ───────────────────────────────────────────

def build_ai_context_prompt() -> str:
    """构建 AI 填空题的上下文 prompt 片段。"""
    parts: List[str] = []

    # 画像信息
    persona = get_current_persona()
    if persona:
        desc = persona.to_description()
        parts.append(f"你扮演的角色是：{desc}。")

    # 已答题目摘要
    answered = get_answered()
    if answered:
        sorted_questions = sorted(answered.items(), key=lambda x: x[0])
        # 只取最近 10 题，避免 prompt 太长
        recent = sorted_questions[-10:]
        if recent:
            summary_lines = []
            for q_num, record in recent:
                if record.question_type == "text" and record.text_answer:
                    summary_lines.append(f"  第{q_num}题(填空): {record.text_answer[:50]}")
                elif record.selected_texts:
                    texts = "、".join(record.selected_texts[:3])
                    summary_lines.append(f"  第{q_num}题: 选了「{texts}」")
            if summary_lines:
                parts.append("你在这份问卷中前面的作答记录：")
                parts.extend(summary_lines)
                parts.append("请保持与前面回答的一致性。")

    return "\n".join(parts)



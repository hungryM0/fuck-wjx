"""反填模式的答案提供器。

在填写问卷时，从样本中获取答案，替代随机生成。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from software.core.task.task_context import ExecutionState

import threading


def get_backfill_answer(
    execution_state: ExecutionState,
    question_id: str,
    *,
    thread_name: Optional[str] = None,
) -> Optional[Any]:
    """从反填样本中获取答案。
    
    Args:
        execution_state: 执行状态对象
        question_id: 题目 ID（如 "Q1", "Q2"）
        thread_name: 线程名称，默认为当前线程
        
    Returns:
        答案值，如果不是反填模式或没有答案则返回 None
        
    Example:
        >>> answer = get_backfill_answer(execution_state, "Q1")
        >>> if answer is not None:
        ...     # 使用反填答案
        ...     fill_with_answer(answer)
        ... else:
        ...     # 使用随机答案
        ...     fill_with_random()
    """
    # 检查是否启用反填模式
    if not hasattr(execution_state, 'is_backfill_mode') or not execution_state.is_backfill_mode():
        return None
    
    # 获取当前样本
    sample = execution_state.get_current_sample(thread_name)
    if sample is None:
        return None
    
    # 从标准化答案中获取
    return sample.normalized_answers.get(question_id)


def has_backfill_answer(
    execution_state: ExecutionState,
    question_id: str,
    *,
    thread_name: Optional[str] = None,
) -> bool:
    """检查是否有反填答案。
    
    Args:
        execution_state: 执行状态对象
        question_id: 题目 ID
        thread_name: 线程名称，默认为当前线程
        
    Returns:
        如果有反填答案返回 True
    """
    answer = get_backfill_answer(execution_state, question_id, thread_name=thread_name)
    return answer is not None


def get_all_backfill_answers(
    execution_state: ExecutionState,
    *,
    thread_name: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """获取当前样本的所有答案。
    
    Args:
        execution_state: 执行状态对象
        thread_name: 线程名称，默认为当前线程
        
    Returns:
        答案字典 {question_id: answer}，如果不是反填模式则返回 None
    """
    if not hasattr(execution_state, 'is_backfill_mode') or not execution_state.is_backfill_mode():
        return None
    
    sample = execution_state.get_current_sample(thread_name)
    if sample is None:
        return None
    
    return dict(sample.normalized_answers)


class BackfillAnswerProvider:
    """反填答案提供器（面向对象接口）。
    
    提供更高级的答案获取功能，支持默认值、类型转换等。
    支持两种初始化方式：
    1. 传入 ExecutionState（用于运行时）
    2. 传入标准化答案字典（用于测试和独立使用）
    """
    
    def __init__(
        self, 
        execution_state_or_answers: Any,
        thread_name: Optional[str] = None,
        question_mapping: Optional[dict[int, str]] = None
    ):
        """初始化。
        
        Args:
            execution_state_or_answers: ExecutionState 对象或标准化答案字典
            thread_name: 线程名称，默认为当前线程（仅当传入 ExecutionState 时使用）
            question_mapping: 题号到 QID 的映射，如 {1: "Q1", 2: "Q2", 3: "Q3_1"}
        """
        # 判断是 ExecutionState 还是字典
        if isinstance(execution_state_or_answers, dict):
            # 直接使用答案字典
            self.execution_state = None
            self.normalized_answers = execution_state_or_answers
            self.thread_name = None
        else:
            # 使用 ExecutionState
            self.execution_state = execution_state_or_answers
            self.normalized_answers = None
            self.thread_name = thread_name or threading.current_thread().name
        
        # 题号映射
        self.question_mapping = question_mapping or self._build_default_mapping()
    
    def _build_default_mapping(self) -> dict[int, str]:
        """构建默认的题号映射。
        
        默认规则：
        - Q1 -> 1
        - Q2 -> 2
        - Q3_1 -> 3 (矩阵题的第一行)
        - Q3_2 -> 3 (矩阵题的第二行，会被覆盖，只保留第一个)
        
        Returns:
            题号到 QID 的映射字典
        """
        mapping = {}
        answers = self._get_answers_dict()
        
        for qid in answers.keys():
            if not isinstance(qid, str) or not qid.startswith("Q"):
                continue
            
            try:
                # 提取题号（Q3_1 -> 3, Q10 -> 10）
                num_part = qid[1:].split("_")[0]
                num = int(num_part)
                
                # 只保留第一个匹配（避免矩阵题的多行覆盖）
                if num not in mapping:
                    mapping[num] = qid
            except (ValueError, IndexError):
                pass
        
        return mapping
    
    def _get_answers_dict(self) -> dict[str, Any]:
        """获取答案字典。"""
        if self.normalized_answers is not None:
            return self.normalized_answers
        
        if self.execution_state is not None:
            answers = get_all_backfill_answers(
                self.execution_state,
                thread_name=self.thread_name,
            )
            return answers or {}
        
        return {}
    
    def get(self, question_id: str, default: Any = None) -> Any:
        """获取答案，支持默认值。
        
        Args:
            question_id: 题目 ID（如 "Q1"）
            default: 默认值
            
        Returns:
            答案值或默认值
        """
        if self.normalized_answers is not None:
            return self.normalized_answers.get(question_id, default)
        
        if self.execution_state is not None:
            answer = get_backfill_answer(
                self.execution_state,
                question_id,
                thread_name=self.thread_name,
            )
            return answer if answer is not None else default
        
        return default
    
    def get_answer_for_question(self, question_num: int) -> Optional[Any]:
        """根据题号获取答案（用于 answer_context）。
        
        Args:
            question_num: 题号（如 1, 2, 3）
            
        Returns:
            答案值，如果未找到则返回 None
        """
        # 查找题号对应的 QID
        qid = self.question_mapping.get(question_num)
        if qid is None:
            return None
        
        return self.get(qid)
    
    def has(self, question_id: str) -> bool:
        """检查是否有答案。"""
        if self.normalized_answers is not None:
            return question_id in self.normalized_answers
        
        if self.execution_state is not None:
            return has_backfill_answer(
                self.execution_state,
                question_id,
                thread_name=self.thread_name,
            )
        
        return False
    
    def get_all(self) -> dict[str, Any]:
        """获取所有答案。"""
        return self._get_answers_dict()
    
    def is_enabled(self) -> bool:
        """检查反填模式是否启用。"""
        if self.normalized_answers is not None:
            return True
        
        if self.execution_state is not None:
            return (
                hasattr(self.execution_state, 'is_backfill_mode')
                and self.execution_state.is_backfill_mode()
            )
        
        return False

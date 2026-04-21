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
    """
    
    def __init__(self, execution_state: ExecutionState, thread_name: Optional[str] = None):
        """初始化。
        
        Args:
            execution_state: 执行状态对象
            thread_name: 线程名称，默认为当前线程
        """
        self.execution_state = execution_state
        self.thread_name = thread_name or threading.current_thread().name
    
    def get(self, question_id: str, default: Any = None) -> Any:
        """获取答案，支持默认值。
        
        Args:
            question_id: 题目 ID
            default: 默认值
            
        Returns:
            答案值或默认值
        """
        answer = get_backfill_answer(
            self.execution_state,
            question_id,
            thread_name=self.thread_name,
        )
        return answer if answer is not None else default
    
    def has(self, question_id: str) -> bool:
        """检查是否有答案。"""
        return has_backfill_answer(
            self.execution_state,
            question_id,
            thread_name=self.thread_name,
        )
    
    def get_all(self) -> dict[str, Any]:
        """获取所有答案。"""
        answers = get_all_backfill_answers(
            self.execution_state,
            thread_name=self.thread_name,
        )
        return answers or {}
    
    def is_enabled(self) -> bool:
        """检查反填模式是否启用。"""
        return (
            hasattr(self.execution_state, 'is_backfill_mode')
            and self.execution_state.is_backfill_mode()
        )

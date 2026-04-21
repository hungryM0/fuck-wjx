"""反填模式工作流集成。

展示如何在执行循环中集成反填模式。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Callable, Any
import threading

if TYPE_CHECKING:
    from software.core.task.task_context import ExecutionState


def backfill_workflow_wrapper(
    execution_state: ExecutionState,
    fill_survey_func: Callable,
    *args,
    **kwargs,
) -> Any:
    """反填模式工作流包装器。
    
    在执行填写问卷前后处理样本的获取和状态更新。
    
    Args:
        execution_state: 执行状态对象
        fill_survey_func: 填写问卷的函数
        *args: 传递给 fill_survey_func 的参数
        **kwargs: 传递给 fill_survey_func 的关键字参数
        
    Returns:
        fill_survey_func 的返回值
        
    Raises:
        Exception: 填写失败时抛出
        
    Example:
        >>> def my_fill_survey(driver, ctx, ...):
        ...     # 填写逻辑
        ...     pass
        >>> 
        >>> result = backfill_workflow_wrapper(
        ...     execution_state,
        ...     my_fill_survey,
        ...     driver, ctx, ...
        ... )
    """
    # 检查是否启用反填模式
    if not hasattr(execution_state, 'is_backfill_mode') or not execution_state.is_backfill_mode():
        # 不是反填模式，直接执行
        return fill_survey_func(*args, **kwargs)
    
    # 获取分发器
    if not hasattr(execution_state, '_backfill_state') or execution_state._backfill_state is None:
        raise RuntimeError("反填模式未正确初始化")
    
    dispatcher = execution_state._backfill_state.dispatcher
    if dispatcher is None:
        raise RuntimeError("样本分发器未初始化")
    
    thread_name = threading.current_thread().name
    
    # 1. 从分发器获取样本
    sample = dispatcher.next_sample()
    if sample is None:
        # 没有待处理样本了
        return None
    
    # 2. 设置为当前样本
    execution_state.set_current_sample(sample, thread_name)
    
    try:
        # 3. 执行填写
        result = fill_survey_func(*args, **kwargs)
        
        # 4. 标记成功
        dispatcher.mark_success(sample)
        
        return result
        
    except Exception as e:
        # 5. 标记失败
        dispatcher.mark_failed(sample, str(e), retry=False)
        raise
        
    finally:
        # 6. 清除当前样本
        execution_state.set_current_sample(None, thread_name)


def should_continue_backfill(execution_state: ExecutionState) -> bool:
    """检查是否应该继续反填。
    
    Args:
        execution_state: 执行状态对象
        
    Returns:
        如果还有待处理样本返回 True
    """
    if not hasattr(execution_state, 'is_backfill_mode') or not execution_state.is_backfill_mode():
        return True  # 不是反填模式，继续正常流程
    
    if not hasattr(execution_state, '_backfill_state') or execution_state._backfill_state is None:
        return False
    
    dispatcher = execution_state._backfill_state.dispatcher
    if dispatcher is None:
        return False
    
    return dispatcher.has_pending()


def get_backfill_stats(execution_state: ExecutionState) -> Optional[dict]:
    """获取反填模式统计信息。
    
    Args:
        execution_state: 执行状态对象
        
    Returns:
        统计信息字典，如果不是反填模式则返回 None
    """
    if not hasattr(execution_state, 'is_backfill_mode') or not execution_state.is_backfill_mode():
        return None
    
    if not hasattr(execution_state, '_backfill_state') or execution_state._backfill_state is None:
        return None
    
    dispatcher = execution_state._backfill_state.dispatcher
    if dispatcher is None:
        return None
    
    return dispatcher.get_stats()


# ========== 集成示例 ==========

def example_runner_integration(execution_state: ExecutionState):
    """示例：如何在 runner 中集成反填模式。
    
    这是一个示例函数，展示如何修改现有的 runner 代码。
    """
    
    # 原有的执行循环
    while not execution_state.stop_event.is_set():
        
        # ===== 新增：反填模式检查 =====
        if hasattr(execution_state, 'is_backfill_mode') and execution_state.is_backfill_mode():
            # 反填模式：检查是否还有样本
            if not should_continue_backfill(execution_state):
                break  # 所有样本已处理完
        else:
            # 正常模式：检查是否达到目标
            if execution_state.cur_num >= execution_state.target_num:
                break
        # ===== 新增结束 =====
        
        try:
            # 原有的填写逻辑
            # fill_survey(driver, execution_state, ...)
            
            # ===== 修改：使用包装器 =====
            # 原来：
            # fill_survey(driver, execution_state, ...)
            
            # 现在：
            # backfill_workflow_wrapper(
            #     execution_state,
            #     fill_survey,
            #     driver, execution_state, ...
            # )
            # ===== 修改结束 =====
            
            pass  # 实际代码在这里
            
        except Exception as e:
            # 错误处理
            pass


def example_provider_integration(execution_state: ExecutionState, question_id: str):
    """示例：如何在 provider 中集成反填模式。
    
    这是一个示例函数，展示如何修改现有的 provider 代码。
    """
    from software.core.backfill import get_backfill_answer
    
    # ===== 新增：尝试从反填样本获取答案 =====
    answer = get_backfill_answer(execution_state, question_id)
    if answer is not None:
        # 使用反填答案
        return answer
    # ===== 新增结束 =====
    
    # 原有的随机生成逻辑
    # answer = generate_random_answer(...)
    # return answer
    
    return None  # 示例

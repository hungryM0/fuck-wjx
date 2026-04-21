"""答案上下文管理器 - 支持反填模式和随机模式的无缝切换。

使用线程本地存储 (Thread-Local Storage) 保存当前线程的答案提供者，
实现线程安全的答案选择策略。
"""
from __future__ import annotations

import logging
import random
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    from software.core.backfill.answer_provider import BackfillAnswerProvider

# 线程本地存储
_thread_local = threading.local()


def set_answer_provider(provider: Optional[BackfillAnswerProvider]) -> None:
    """设置当前线程的答案提供者。
    
    Args:
        provider: 答案提供者实例，None 表示使用随机模式
    """
    _thread_local.provider = provider


def get_answer_provider() -> Optional[BackfillAnswerProvider]:
    """获取当前线程的答案提供者。
    
    Returns:
        答案提供者实例，None 表示随机模式
    """
    return getattr(_thread_local, 'provider', None)


def clear_answer_provider() -> None:
    """清除当前线程的答案提供者。"""
    if hasattr(_thread_local, 'provider'):
        delattr(_thread_local, 'provider')


@contextmanager
def backfill_answer_context(provider: BackfillAnswerProvider):
    """反填答案上下文管理器。
    
    在此上下文中，所有答案选择函数将使用反填数据而非随机生成。
    
    Args:
        provider: 反填答案提供者
        
    Example:
        >>> from software.core.backfill.answer_provider import BackfillAnswerProvider
        >>> provider = BackfillAnswerProvider(normalized_answers)
        >>> with backfill_answer_context(provider):
        ...     # 在此上下文中，答案将从 provider 获取
        ...     answer = smart_select_option(1, ["A", "B", "C"], [1.0, 1.0, 1.0])
    """
    old_provider = get_answer_provider()
    set_answer_provider(provider)
    try:
        yield
    finally:
        if old_provider is None:
            clear_answer_provider()
        else:
            set_answer_provider(old_provider)


def smart_select_option(
    question_num: int,
    option_texts: List[str],
    probabilities: List[float]
) -> int:
    """智能选择单选题答案索引。
    
    - 反填模式：从反填数据中获取答案文本，在选项中查找匹配的索引
    - 随机模式：根据概率权重随机选择
    
    Args:
        question_num: 题号（如 1, 2, 3）
        option_texts: 选项文本列表
        probabilities: 选项概率权重列表
        
    Returns:
        选中的选项索引（0-based）
        
    Example:
        >>> # 随机模式
        >>> idx = smart_select_option(1, ["A", "B", "C"], [0.5, 0.3, 0.2])
        >>> 
        >>> # 反填模式
        >>> with backfill_answer_context(provider):
        ...     idx = smart_select_option(1, ["A", "B", "C"], [1.0, 1.0, 1.0])
    """
    provider = get_answer_provider()
    
    if provider is None:
        # 随机模式：使用原有的 weighted_index 逻辑
        from software.core.questions.utils import weighted_index
        return weighted_index(probabilities)
    
    # 反填模式：从反填数据获取答案
    try:
        answer_text = provider.get_answer_for_question(question_num)
        
        if answer_text is None:
            logging.warning(f"Q{question_num} 反填数据中未找到答案，使用随机选择")
            from software.core.questions.utils import weighted_index
            return weighted_index(probabilities)
        
        # 在选项中查找匹配的索引
        answer_str = str(answer_text).strip()
        for idx, opt_text in enumerate(option_texts):
            if str(opt_text).strip() == answer_str:
                logging.debug(f"Q{question_num} 反填答案匹配: '{answer_str}' -> 选项 {idx + 1}")
                return idx
        
        # 未找到精确匹配，尝试模糊匹配
        answer_lower = answer_str.lower()
        for idx, opt_text in enumerate(option_texts):
            if answer_lower == str(opt_text).strip().lower():
                logging.debug(f"Q{question_num} 反填答案模糊匹配: '{answer_str}' -> 选项 {idx + 1}")
                return idx
        
        # 仍未找到匹配，记录警告并使用随机选择
        logging.warning(
            f"Q{question_num} 反填答案 '{answer_str}' 未在选项中找到匹配\n"
            f"可用选项: {', '.join([str(t) for t in option_texts[:5]])}"
            f"{'...' if len(option_texts) > 5 else ''}\n"
            f"使用随机选择"
        )
        from software.core.questions.utils import weighted_index
        return weighted_index(probabilities)
        
    except Exception as exc:
        logging.error(f"Q{question_num} 反填答案选择失败: {exc}", exc_info=True)
        from software.core.questions.utils import weighted_index
        return weighted_index(probabilities)


def smart_select_multiple_options(
    question_num: int,
    option_texts: List[str],
    probabilities: List[float]
) -> List[int]:
    """智能选择多选题答案索引列表。
    
    - 反填模式：从反填数据中获取答案文本列表，在选项中查找匹配的索引
    - 随机模式：根据概率权重随机选择多个选项
    
    Args:
        question_num: 题号
        option_texts: 选项文本列表
        probabilities: 选项概率权重列表（每个选项被选中的概率）
        
    Returns:
        选中的选项索引列表（0-based）
        
    Example:
        >>> # 随机模式
        >>> indices = smart_select_multiple_options(1, ["A", "B", "C"], [50.0, 30.0, 20.0])
        >>> 
        >>> # 反填模式
        >>> with backfill_answer_context(provider):
        ...     indices = smart_select_multiple_options(1, ["A", "B", "C"], [50.0, 50.0, 50.0])
    """
    provider = get_answer_provider()
    
    if provider is None:
        # 随机模式：使用原有的概率选择逻辑
        from software.core.questions.utils import weighted_index
        selected = []
        for idx, prob in enumerate(probabilities):
            if random.random() * 100 < prob:
                selected.append(idx)
        # 如果一个都没选中，至少选一个
        return selected if selected else [weighted_index(probabilities)]
    
    # 反填模式：从反填数据获取答案列表
    try:
        answer_data = provider.get_answer_for_question(question_num)
        
        if answer_data is None:
            logging.warning(f"Q{question_num} 反填数据中未找到答案，使用随机选择")
            from software.core.questions.utils import weighted_index
            selected = []
            for idx, prob in enumerate(probabilities):
                if random.random() * 100 < prob:
                    selected.append(idx)
            return selected if selected else [weighted_index(probabilities)]
        
        # 确保答案是列表
        if not isinstance(answer_data, list):
            answer_texts = [answer_data]
        else:
            answer_texts = answer_data
        
        # 在选项中查找匹配的索引
        selected = []
        for answer_text in answer_texts:
            answer_str = str(answer_text).strip()
            matched = False
            
            # 精确匹配
            for idx, opt_text in enumerate(option_texts):
                if str(opt_text).strip() == answer_str:
                    if idx not in selected:
                        selected.append(idx)
                    matched = True
                    break
            
            # 模糊匹配
            if not matched:
                answer_lower = answer_str.lower()
                for idx, opt_text in enumerate(option_texts):
                    if answer_lower == str(opt_text).strip().lower():
                        if idx not in selected:
                            selected.append(idx)
                        matched = True
                        break
            
            if not matched:
                logging.warning(f"Q{question_num} 反填答案 '{answer_str}' 未在选项中找到匹配")
        
        if not selected:
            logging.warning(f"Q{question_num} 所有反填答案均未匹配，使用随机选择")
            from software.core.questions.utils import weighted_index
            selected = []
            for idx, prob in enumerate(probabilities):
                if random.random() * 100 < prob:
                    selected.append(idx)
            return selected if selected else [weighted_index(probabilities)]
        
        logging.debug(f"Q{question_num} 反填多选答案匹配: {len(selected)} 个选项")
        return selected
        
    except Exception as exc:
        logging.error(f"Q{question_num} 反填多选答案选择失败: {exc}", exc_info=True)
        from software.core.questions.utils import weighted_index
        selected = []
        for idx, prob in enumerate(probabilities):
            if random.random() * 100 < prob:
                selected.append(idx)
        return selected if selected else [weighted_index(probabilities)]


def smart_get_text_answer(
    question_num: int,
    candidates: List[str]
) -> str:
    """智能获取填空题答案。
    
    - 反填模式：从反填数据中获取答案文本
    - 随机模式：从候选列表中随机选择
    
    Args:
        question_num: 题号
        candidates: 候选答案列表
        
    Returns:
        选中的答案文本
        
    Example:
        >>> # 随机模式
        >>> answer = smart_get_text_answer(1, ["答案1", "答案2", "答案3"])
        >>> 
        >>> # 反填模式
        >>> with backfill_answer_context(provider):
        ...     answer = smart_get_text_answer(1, ["答案1", "答案2", "答案3"])
    """
    provider = get_answer_provider()
    
    if provider is None:
        # 随机模式：从候选列表中随机选择
        from software.core.questions.utils import weighted_index
        if not candidates:
            return ""
        probabilities = [1.0] * len(candidates)
        idx = weighted_index(probabilities)
        return candidates[idx]
    
    # 反填模式：从反填数据获取答案
    try:
        answer = provider.get_answer_for_question(question_num)
        
        if answer is None:
            logging.warning(f"Q{question_num} 反填数据中未找到答案，使用随机选择")
            from software.core.questions.utils import weighted_index
            if not candidates:
                return ""
            probabilities = [1.0] * len(candidates)
            idx = weighted_index(probabilities)
            return candidates[idx]
        
        # 返回答案文本
        answer_str = str(answer).strip()
        logging.debug(f"Q{question_num} 反填文本答案: '{answer_str}'")
        return answer_str
        
    except Exception as exc:
        logging.error(f"Q{question_num} 反填文本答案获取失败: {exc}", exc_info=True)
        from software.core.questions.utils import weighted_index
        if not candidates:
            return ""
        probabilities = [1.0] * len(candidates)
        idx = weighted_index(probabilities)
        return candidates[idx]


def smart_select_order(
    question_num: int,
    option_texts: List[str]
) -> List[int]:
    """智能选择排序题答案。
    
    - 反填模式：从反填数据中获取排序后的选项文本列表，转换为索引列表
    - 随机模式：随机打乱选项顺序
    
    Args:
        question_num: 题号
        option_texts: 选项文本列表
        
    Returns:
        排序后的选项索引列表（0-based）
        
    Example:
        >>> # 随机模式
        >>> order = smart_select_order(1, ["A", "B", "C", "D"])
        >>> # 可能返回 [2, 0, 3, 1]
        >>> 
        >>> # 反填模式（假设反填数据为 ["C", "A", "D", "B"]）
        >>> with backfill_answer_context(provider):
        ...     order = smart_select_order(1, ["A", "B", "C", "D"])
        >>> # 返回 [2, 0, 3, 1]
    """
    provider = get_answer_provider()
    
    if provider is None:
        # 随机模式：随机打乱顺序
        indices = list(range(len(option_texts)))
        random.shuffle(indices)
        return indices
    
    # 反填模式：从反填数据获取排序
    try:
        answer_data = provider.get_answer_for_question(question_num)
        
        if answer_data is None or not isinstance(answer_data, list):
            logging.warning(f"Q{question_num} 反填排序数据无效，使用随机排序")
            indices = list(range(len(option_texts)))
            random.shuffle(indices)
            return indices
        
        # 将答案文本列表转换为索引列表
        ordered_indices = []
        for answer_text in answer_data:
            answer_str = str(answer_text).strip()
            matched = False
            
            # 查找匹配的选项索引
            for idx, opt_text in enumerate(option_texts):
                if str(opt_text).strip() == answer_str:
                    if idx not in ordered_indices:
                        ordered_indices.append(idx)
                    matched = True
                    break
            
            if not matched:
                # 尝试模糊匹配
                answer_lower = answer_str.lower()
                for idx, opt_text in enumerate(option_texts):
                    if answer_lower == str(opt_text).strip().lower():
                        if idx not in ordered_indices:
                            ordered_indices.append(idx)
                        matched = True
                        break
            
            if not matched:
                logging.warning(f"Q{question_num} 反填排序答案 '{answer_str}' 未在选项中找到匹配")
        
        # 补充未匹配的选项
        for idx in range(len(option_texts)):
            if idx not in ordered_indices:
                ordered_indices.append(idx)
        
        if len(ordered_indices) != len(option_texts):
            logging.warning(f"Q{question_num} 反填排序结果不完整，使用随机排序")
            indices = list(range(len(option_texts)))
            random.shuffle(indices)
            return indices
        
        logging.debug(f"Q{question_num} 反填排序答案匹配成功")
        return ordered_indices
        
    except Exception as exc:
        logging.error(f"Q{question_num} 反填排序答案选择失败: {exc}", exc_info=True)
        indices = list(range(len(option_texts)))
        random.shuffle(indices)
        return indices


__all__ = [
    'set_answer_provider',
    'get_answer_provider',
    'clear_answer_provider',
    'backfill_answer_context',
    'smart_select_option',
    'smart_select_multiple_options',
    'smart_get_text_answer',
    'smart_select_order',
]

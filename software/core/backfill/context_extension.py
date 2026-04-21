"""反填模式的上下文扩展。

这个模块通过扩展而不是修改的方式，为 ExecutionConfig 和 ExecutionState 添加反填模式支持。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from software.io.excel.schema import SurveySchema, MappingPlan, SampleRow
    from software.core.backfill.dispatcher import SampleDispatcher


@dataclass
class BackfillConfig:
    """反填模式的静态配置。"""
    
    enabled: bool = False                           # 是否启用反填模式
    excel_path: str = ""                            # Excel 文件路径
    survey_schema: Optional[SurveySchema] = None    # 问卷结构
    mapping_plan: Optional[MappingPlan] = None      # 映射计划
    fuzzy_threshold: float = 90.0                   # 模糊匹配阈值
    qualification_rules: dict[str, list[str]] = field(default_factory=dict)  # 资格题规则


@dataclass
class BackfillState:
    """反填模式的运行时状态。"""
    
    dispatcher: Optional[SampleDispatcher] = None                   # 样本分发器
    current_sample_by_thread: dict[str, SampleRow] = field(default_factory=dict)  # 线程当前样本
    lock: threading.Lock = field(default_factory=threading.Lock)    # 状态锁


class BackfillContextMixin:
    """反填模式上下文混入类。
    
    通过混入的方式为 ExecutionState 添加反填模式支持，避免修改原有代码。
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._backfill_config: Optional[BackfillConfig] = None
        self._backfill_state: Optional[BackfillState] = None
    
    @property
    def backfill_config(self) -> BackfillConfig:
        """获取反填配置（懒加载）。"""
        if self._backfill_config is None:
            self._backfill_config = BackfillConfig()
        return self._backfill_config
    
    @property
    def backfill_state(self) -> BackfillState:
        """获取反填状态（懒加载）。"""
        if self._backfill_state is None:
            self._backfill_state = BackfillState()
        return self._backfill_state
    
    def is_backfill_mode(self) -> bool:
        """检查是否启用反填模式。"""
        return self._backfill_config is not None and self._backfill_config.enabled
    
    def get_current_sample(self, thread_name: Optional[str] = None) -> Optional[SampleRow]:
        """获取当前线程的样本（线程安全）。
        
        Args:
            thread_name: 线程名称，默认为当前线程
            
        Returns:
            当前样本，如果没有则返回 None
        """
        if not self.is_backfill_mode():
            return None
        
        key = str(thread_name or threading.current_thread().name or "").strip()
        if not key:
            return None
        
        state = self.backfill_state
        with state.lock:
            return state.current_sample_by_thread.get(key)
    
    def set_current_sample(self, sample: Optional[SampleRow], thread_name: Optional[str] = None):
        """设置当前线程的样本（线程安全）。
        
        Args:
            sample: 样本对象
            thread_name: 线程名称，默认为当前线程
        """
        if not self.is_backfill_mode():
            return
        
        key = str(thread_name or threading.current_thread().name or "").strip()
        if not key:
            return
        
        state = self.backfill_state
        with state.lock:
            if sample is None:
                state.current_sample_by_thread.pop(key, None)
            else:
                state.current_sample_by_thread[key] = sample


def enable_backfill_mode(
    execution_state,
    excel_path: str,
    survey_schema: SurveySchema,
    mapping_plan: MappingPlan,
    dispatcher: SampleDispatcher,
    *,
    fuzzy_threshold: float = 90.0,
    qualification_rules: Optional[dict[str, list[str]]] = None,
):
    """为 ExecutionState 启用反填模式（非侵入式）。
    
    Args:
        execution_state: ExecutionState 实例
        excel_path: Excel 文件路径
        survey_schema: 问卷结构
        mapping_plan: 映射计划
        dispatcher: 样本分发器
        fuzzy_threshold: 模糊匹配阈值
        qualification_rules: 资格题规则
    """
    # 如果还没有混入反填功能，动态添加
    if not hasattr(execution_state, '_backfill_config'):
        execution_state._backfill_config = None
        execution_state._backfill_state = None
        
        # 绑定方法
        execution_state.backfill_config = property(lambda self: self._get_backfill_config())
        execution_state.backfill_state = property(lambda self: self._get_backfill_state())
        execution_state._get_backfill_config = lambda: _get_or_create_backfill_config(execution_state)
        execution_state._get_backfill_state = lambda: _get_or_create_backfill_state(execution_state)
        execution_state.is_backfill_mode = lambda: _is_backfill_mode(execution_state)
        execution_state.get_current_sample = lambda thread_name=None: _get_current_sample(execution_state, thread_name)
        execution_state.set_current_sample = lambda sample, thread_name=None: _set_current_sample(execution_state, sample, thread_name)
    
    # 初始化配置
    config = BackfillConfig(
        enabled=True,
        excel_path=excel_path,
        survey_schema=survey_schema,
        mapping_plan=mapping_plan,
        fuzzy_threshold=fuzzy_threshold,
        qualification_rules=qualification_rules or {},
    )
    execution_state._backfill_config = config
    
    # 初始化状态
    state = BackfillState(dispatcher=dispatcher)
    execution_state._backfill_state = state


def _get_or_create_backfill_config(execution_state) -> BackfillConfig:
    """获取或创建反填配置。"""
    if execution_state._backfill_config is None:
        execution_state._backfill_config = BackfillConfig()
    return execution_state._backfill_config


def _get_or_create_backfill_state(execution_state) -> BackfillState:
    """获取或创建反填状态。"""
    if execution_state._backfill_state is None:
        execution_state._backfill_state = BackfillState()
    return execution_state._backfill_state


def _is_backfill_mode(execution_state) -> bool:
    """检查是否启用反填模式。"""
    return (
        execution_state._backfill_config is not None 
        and execution_state._backfill_config.enabled
    )


def _get_current_sample(execution_state, thread_name: Optional[str] = None) -> Optional[SampleRow]:
    """获取当前线程的样本。"""
    if not _is_backfill_mode(execution_state):
        return None
    
    key = str(thread_name or threading.current_thread().name or "").strip()
    if not key:
        return None
    
    state = _get_or_create_backfill_state(execution_state)
    with state.lock:
        return state.current_sample_by_thread.get(key)


def _set_current_sample(execution_state, sample: Optional[SampleRow], thread_name: Optional[str] = None):
    """设置当前线程的样本。"""
    if not _is_backfill_mode(execution_state):
        return
    
    key = str(thread_name or threading.current_thread().name or "").strip()
    if not key:
        return
    
    state = _get_or_create_backfill_state(execution_state)
    with state.lock:
        if sample is None:
            state.current_sample_by_thread.pop(key, None)
        else:
            state.current_sample_by_thread[key] = sample

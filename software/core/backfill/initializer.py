"""反填模式初始化器。

提供便捷的函数来初始化反填模式，避免在 RunController 中写大量代码。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from software.core.task.task_context import ExecutionState
    from software.io.excel.schema import SurveySchema

from software.io.excel import (
    ExcelReader,
    QuestionMatcher,
    AnswerNormalizer,
    SampleValidator,
)
from software.core.backfill.dispatcher import SampleDispatcher
from software.core.backfill.context_extension import enable_backfill_mode


class BackfillInitializer:
    """反填模式初始化器。"""
    
    def __init__(
        self,
        excel_path: str,
        survey_schema: SurveySchema,
        *,
        fuzzy_threshold: float = 90.0,
        qualification_rules: Optional[dict[str, list[str]]] = None,
    ):
        """初始化。
        
        Args:
            excel_path: Excel 文件路径
            survey_schema: 问卷结构
            fuzzy_threshold: 模糊匹配阈值
            qualification_rules: 资格题规则
        """
        self.excel_path = excel_path
        self.survey_schema = survey_schema
        self.fuzzy_threshold = fuzzy_threshold
        self.qualification_rules = qualification_rules or {}
    
    def initialize(self, execution_state: ExecutionState) -> dict:
        """初始化反填模式。
        
        Args:
            execution_state: 执行状态对象
            
        Returns:
            初始化结果，包含统计信息
            
        Raises:
            ValueError: 初始化失败
        """
        # 1. 读取 Excel
        reader = ExcelReader()
        samples = reader.read(self.excel_path)
        
        # 2. 建立映射
        matcher = QuestionMatcher(fuzzy_threshold=self.fuzzy_threshold)
        excel_columns = list(samples[0].values.keys())
        mapping_plan = matcher.build_mapping(excel_columns, self.survey_schema)
        
        # 3. 校验并标准化
        normalizer = AnswerNormalizer(fuzzy_threshold=self.fuzzy_threshold)
        validator = SampleValidator(normalizer)
        validator.validate_and_normalize(
            samples,
            self.survey_schema,
            mapping_plan,
            self.qualification_rules,
        )
        
        # 4. 获取有效样本
        valid_samples = [s for s in samples if s.status == "pending"]
        if not valid_samples:
            raise ValueError("没有有效的样本可以处理")
        
        # 5. 创建分发器
        dispatcher = SampleDispatcher(valid_samples)
        
        # 6. 启用反填模式
        enable_backfill_mode(
            execution_state,
            excel_path=self.excel_path,
            survey_schema=self.survey_schema,
            mapping_plan=mapping_plan,
            dispatcher=dispatcher,
            fuzzy_threshold=self.fuzzy_threshold,
            qualification_rules=self.qualification_rules,
        )
        
        # 7. 返回统计信息
        summary = validator.get_validation_summary(samples)
        return {
            "total_rows": len(samples),
            "valid_samples": len(valid_samples),
            "failed_samples": summary["failed"],
            "mapping_items": len(mapping_plan.items),
            "excel_path": self.excel_path,
        }


def initialize_backfill_mode(
    execution_state: ExecutionState,
    excel_path: str,
    survey_schema: SurveySchema,
    *,
    fuzzy_threshold: float = 90.0,
    qualification_rules: Optional[dict[str, list[str]]] = None,
) -> dict:
    """便捷函数：初始化反填模式。
    
    Args:
        execution_state: 执行状态对象
        excel_path: Excel 文件路径
        survey_schema: 问卷结构
        fuzzy_threshold: 模糊匹配阈值
        qualification_rules: 资格题规则
        
    Returns:
        初始化结果，包含统计信息
        
    Raises:
        ValueError: 初始化失败
        
    Example:
        >>> from software.core.backfill import initialize_backfill_mode
        >>> result = initialize_backfill_mode(
        ...     execution_state,
        ...     "data.xlsx",
        ...     survey_schema,
        ...     qualification_rules={"Q1": ["否"]}
        ... )
        >>> print(f"有效样本: {result['valid_samples']}")
    """
    initializer = BackfillInitializer(
        excel_path,
        survey_schema,
        fuzzy_threshold=fuzzy_threshold,
        qualification_rules=qualification_rules,
    )
    return initializer.initialize(execution_state)

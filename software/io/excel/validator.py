"""样本校验器。"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from software.io.excel.schema import SampleRow, SurveySchema, MappingPlan
    from software.io.excel.normalizer import AnswerNormalizer


class SampleValidator:
    """样本校验器。
    
    校验内容：
    1. 每个必答题都能从 Excel 找到列
    2. 每行样本都能映射到所有必答题
    3. 每个值都能标准化成合法选项
    4. 资格题逻辑（可选）
    """

    def __init__(self, normalizer: AnswerNormalizer):
        """初始化。
        
        Args:
            normalizer: 答案标准化器
        """
        self.normalizer = normalizer

    def validate_and_normalize(
        self,
        samples: list[SampleRow],
        survey: SurveySchema,
        plan: MappingPlan,
        qualification_rules: dict[str, list[str]] | None = None,
    ):
        """校验并标准化所有样本。
        
        Args:
            samples: 样本列表
            survey: 问卷结构
            plan: 映射计划
            qualification_rules: 资格题规则，格式为 {qid: [不合格的答案列表]}
                例如: {"Q1": ["否"], "Q2": ["否"]}
                
        Note:
            此方法会直接修改 samples 中每个 SampleRow 的状态：
            - 成功：status="pending", normalized_answers 填充
            - 失败：status="failed", error 填充
        """
        q_by_qid = {q.qid: q for q in survey.questions}

        for sample in samples:
            normalized = {}

            try:
                # 标准化所有题目的答案
                for item in plan.items:
                    q = q_by_qid[item.survey_qid]
                    raw_value = sample.values.get(item.excel_col)
                    normalized[q.qid] = self.normalizer.normalize_answer(q, raw_value)

                # 检查资格题逻辑
                if qualification_rules:
                    for qid, disqualified_answers in qualification_rules.items():
                        answer = normalized.get(qid)
                        if answer in disqualified_answers:
                            raise ValueError(
                                f"不符合资格要求: {qid} 的答案为 '{answer}'"
                            )

                # 校验成功
                sample.normalized_answers = normalized
                sample.status = "pending"
                sample.error = None

            except Exception as e:
                # 校验失败
                sample.status = "failed"
                sample.error = str(e)
                sample.normalized_answers = {}

    def get_validation_summary(self, samples: list[SampleRow]) -> dict:
        """获取校验摘要。
        
        Args:
            samples: 样本列表
            
        Returns:
            摘要信息，包含总数、成功数、失败数、失败详情
        """
        total = len(samples)
        failed = [s for s in samples if s.status == "failed"]
        success = total - len(failed)

        failed_details = []
        for s in failed:
            failed_details.append({
                "row_no": s.row_no,
                "error": s.error,
            })

        return {
            "total": total,
            "success": success,
            "failed": len(failed),
            "failed_details": failed_details,
        }

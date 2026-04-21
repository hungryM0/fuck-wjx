"""问卷结构转换器。

将 RunController 的问卷信息转换为 SurveySchema。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from software.ui.controller.run_controller import RunController

from software.io.excel.schema import SurveySchema, QuestionSchema, OptionSchema


def convert_to_survey_schema(controller: RunController) -> SurveySchema:
    """将 RunController 的问卷信息转换为 SurveySchema。
    
    Args:
        controller: RunController 实例
        
    Returns:
        SurveySchema 对象
        
    Raises:
        ValueError: 如果问卷未解析
    """
    if not hasattr(controller, 'surveyParsed') or not controller.surveyParsed:
        raise ValueError("问卷未解析")
    
    # 获取问卷标题
    survey_title = getattr(controller, 'survey_title', '未命名问卷')
    
    # 获取题目信息
    questions_info = getattr(controller, 'questions_info', None)
    if not questions_info:
        raise ValueError("问卷题目信息为空")
    
    # 转换题目
    questions = []
    for q_info in questions_info:
        # 跳过描述性题目
        if q_info.get('is_description', False):
            continue
        
        # 对于矩阵题，需要为每一行创建一个题目
        if q_info.get('rows', 1) > 1 and q_info.get('row_texts'):
            # 矩阵题：为每一行创建一个子题目
            for row_idx, row_text in enumerate(q_info['row_texts']):
                question = _convert_matrix_row_question(q_info, row_idx, row_text)
                if question:
                    questions.append(question)
        else:
            # 普通题目
            question = _convert_question(q_info)
            if question:
                questions.append(question)
    
    if not questions:
        raise ValueError("没有有效的题目")
    
    return SurveySchema(
        title=survey_title,
        questions=questions,
    )


def _convert_question(q_info: dict) -> QuestionSchema:
    """转换单个题目。
    
    Args:
        q_info: 题目信息字典（来自 questions_info）
        
    Returns:
        QuestionSchema 对象
    """
    # 获取题号
    num = q_info.get('num', 0)
    qid = f"Q{num}"
    
    # 获取题目标题
    title = q_info.get('title', f"题目 {num}")
    
    # 获取题目类型
    type_code = q_info.get('type_code', '3')
    qtype = _normalize_question_type_from_code(type_code, q_info)
    
    # 获取是否必填
    required = q_info.get('required', False)
    
    # 获取选项
    options = []
    option_texts = q_info.get('option_texts', [])
    
    if isinstance(option_texts, list):
        for opt_text in option_texts:
            if opt_text:
                options.append(OptionSchema(text=str(opt_text)))
    
    return QuestionSchema(
        qid=qid,
        index=num,
        title=title,
        qtype=qtype,
        required=required,
        options=options,
    )


def _convert_matrix_row_question(q_info: dict, row_idx: int, row_text: str) -> QuestionSchema:
    """转换矩阵题的一行为单独的题目。
    
    Args:
        q_info: 题目信息字典
        row_idx: 行索引
        row_text: 行文本
        
    Returns:
        QuestionSchema 对象
    """
    # 获取题号
    num = q_info.get('num', 0)
    qid = f"Q{num}_{row_idx + 1}"  # 例如 Q3_1, Q3_2
    
    # 组合标题：主题目 + 行文本
    main_title = q_info.get('title', '')
    title = f"{main_title}—{row_text}" if main_title else row_text
    
    # 矩阵题通常是量表类型
    qtype = "scale"
    
    # 获取是否必填
    required = q_info.get('required', False)
    
    # 获取选项
    options = []
    option_texts = q_info.get('option_texts', [])
    
    if isinstance(option_texts, list):
        for opt_text in option_texts:
            if opt_text:
                options.append(OptionSchema(text=str(opt_text)))
    
    return QuestionSchema(
        qid=qid,
        index=num * 100 + row_idx + 1,  # 确保唯一性
        title=title,
        qtype=qtype,
        required=required,
        options=options,
    )


def _convert_option(opt_info: Any) -> OptionSchema:
    """转换选项。
    
    Args:
        opt_info: 选项信息（可能是字符串或字典）
        
    Returns:
        OptionSchema 对象
    """
    if isinstance(opt_info, str):
        # 简单字符串选项
        return OptionSchema(text=opt_info)
    
    elif isinstance(opt_info, dict):
        # 字典选项
        text = opt_info.get('text', '') or opt_info.get('label', '') or str(opt_info.get('value', ''))
        value = opt_info.get('value')
        
        return OptionSchema(text=text, value=value)
    
    else:
        # 其他类型，转为字符串
        return OptionSchema(text=str(opt_info))


def _normalize_question_type_from_code(type_code: str, q_info: dict) -> str:
    """根据问卷星的 type_code 标准化题目类型。
    
    Args:
        type_code: 问卷星的题目类型代码
        q_info: 题目信息字典（用于判断特殊类型）
        
    Returns:
        标准化后的题目类型
    """
    code = str(type_code).strip()
    
    # 获取额外信息用于判断
    is_text_like = q_info.get('is_text_like', False)
    is_multi_text = q_info.get('is_multi_text', False)
    is_slider_matrix = q_info.get('is_slider_matrix', False)
    is_rating = q_info.get('is_rating', False)
    text_inputs = int(q_info.get('text_inputs') or 0)
    
    # 问卷星类型代码映射（参考 default_builder.py）
    # 1, 2: 文本题
    # 3: 单选题
    # 4: 多选题
    # 5: 量表题/评分题
    # 6: 矩阵题
    # 7: 下拉题
    # 8: 滑块题
    # 11: 排序题
    
    # 特殊类型优先判断
    if is_slider_matrix:
        return 'matrix'
    elif is_multi_text or (is_text_like and text_inputs > 1):
        return 'multi_text'
    elif is_text_like or code in ('1', '2'):
        return 'text'
    
    # 按 type_code 映射
    if code == '3':
        return 'single_choice'
    elif code == '4':
        return 'multi_choice'
    elif code == '5':
        # 评分题和量表题
        return 'score' if is_rating else 'scale'
    elif code == '6':
        return 'matrix'
    elif code == '7':
        return 'dropdown'
    elif code == '8':
        return 'slider'
    elif code == '11':
        return 'order'
    else:
        # 默认单选题
        return 'single_choice'

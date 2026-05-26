from __future__ import annotations
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from credamo.provider import parser
from software.core.questions.default_builder import build_default_question_entries
from software.core.questions.normalization import configure_probabilities
from software.core.questions.schema import QuestionEntry


class CredamoParserTests:
    def test_infer_type_code_uses_page_block_kind(self) -> None:
        assert parser._infer_type_code({'question_kind': 'dropdown'}) == '7'
        assert parser._infer_type_code({'question_kind': 'scale'}) == '5'
        assert parser._infer_type_code({'question_kind': 'order'}) == '11'
        assert parser._infer_type_code({'question_kind': 'multiple'}) == '4'

    def test_normalize_question_keeps_credamo_specific_type(self) -> None:
        question = parser._normalize_question({'question_num': 'Q3', 'title': 'Q3', 'question_kind': 'dropdown', 'provider_type': 'dropdown', 'option_texts': ['选项 1', '选项 2', '选项 3'], 'text_inputs': 0, 'page': 2, 'question_id': 'question-2'}, fallback_num=3)
        assert question['num'] == 3
        assert question['type_code'] == '7'
        assert question['provider_type'] == 'dropdown'
        assert question['provider_page_id'] == '2'
        assert question['options'] == 3
        assert question['logic_parse_status'] == 'none'

    def test_normalize_question_detects_matrix_scale(self) -> None:
        question = parser._normalize_question({'question_num': 'Q11', 'title': 'Q11', 'question_kind': 'matrix', 'provider_type': 'matrix', 'option_texts': ['选项 1', '选项 2', '选项 3', '选项 4', '选项 5'], 'row_texts': ['陈述 1', '陈述 2', '陈述 3', '陈述 4', '陈述 5', '陈述 6', '陈述 7'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-5'}, fallback_num=11)
        assert question['num'] == 11
        assert question['type_code'] == '6'
        assert question['provider_type'] == 'matrix'
        assert question['options'] == 5
        assert question['rows'] == 7
        assert question['row_texts'][0] == '陈述 1'

    def test_normalize_question_prefers_matrix_column_texts_over_placeholder_options(self) -> None:
        question = parser._normalize_question({'question_num': 'Q8', 'title': 'Q8 生成基于专业与目标的大学四年成长路径', 'question_kind': 'matrix', 'provider_type': 'matrix', 'option_texts': ['选项 1', '选项 2', '选项 3', '选项 4', '选项 5'], 'matrix_column_texts': ['非常满意', '比较满意', '满意', '比较不满意', '非常不满意'], 'row_texts': ['如果提供此服务，您觉得', '如果不提供此服务，您觉得'], 'text_inputs': 0, 'page': 2, 'question_id': 'question-3'}, fallback_num=8)
        assert question['option_texts'] == ['非常满意', '比较满意', '满意', '比较不满意', '非常不满意']
        assert question['options'] == 5
        assert question['rows'] == 2

    def test_normalize_question_detects_force_select_instruction(self) -> None:
        question = parser._normalize_question({'question_num': 'Q7', 'title': 'Q7 本题检测是否认真作答，请选 非常不满意', 'title_text': '本题检测是否认真作答，请选 非常不满意', 'question_kind': 'single', 'provider_type': 'single', 'option_texts': ['非常不满意', '不满意', '满意', '非常满意'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-7'}, fallback_num=7)
        assert question['num'] == 7
        assert question['forced_option_index'] == 0
        assert question['forced_option_text'] == '非常不满意'

    def test_normalize_question_detects_arithmetic_trap_answer(self) -> None:
        question = parser._normalize_question({'question_num': 'Q8', 'title': 'Q8 请问100+100等于多少', 'question_kind': 'single', 'provider_type': 'single', 'option_texts': ['300', '200', '500', '600'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-8'}, fallback_num=8)
        assert question['forced_option_index'] == 1
        assert question['forced_option_text'] == '200'

    def test_normalize_question_detects_forced_text_answer(self) -> None:
        question = parser._normalize_question({'question_num': 'Q10', 'title': 'Q10 本题检测是否认真作答，请输入：“你好”（仅输入引号内文字）', 'question_kind': 'text', 'provider_type': 'text', 'option_texts': [], 'text_inputs': 1, 'page': 1, 'question_id': 'question-10'}, fallback_num=10)
        assert question['forced_texts'] == ['你好']

    def test_normalize_question_detects_title_max_multi_select_limit(self) -> None:
        question = parser._normalize_question({'question_num': 'Q17', 'title': 'Q17 正餐替代时，你最看重的3个属性？ [至多选3项]', 'title_text': '正餐替代时，你最看重的3个属性？', 'tip_text': '[至多选3项]', 'question_kind': 'multiple', 'provider_type': 'multiple', 'option_texts': ['分量足', '方便', '便宜', '口味好', '可宿舍煮'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-17'}, fallback_num=17)
        assert question['multi_min_limit'] is None
        assert question['multi_max_limit'] == 3

    def test_normalize_question_detects_title_min_multi_select_limit(self) -> None:
        question = parser._normalize_question({'question_num': 'Q30', 'title': 'Q30 哪种周边会让你更想集体购买？ [至少选2项]', 'title_text': '哪种周边会让你更想集体购买？', 'tip_text': '[至少选2项]', 'question_kind': 'multiple', 'provider_type': 'multiple', 'option_texts': ['宿舍小煮锅', '超大分享碗', '非遗文创', '趣味贴纸'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-30'}, fallback_num=30)
        assert question['multi_min_limit'] == 2
        assert question['multi_max_limit'] is None

    def test_normalize_question_detects_range_multi_select_limit(self) -> None:
        question = parser._normalize_question({'question_num': 'Q32', 'title': 'Q32 请选择2-4项你最常用的功能', 'question_kind': 'multiple', 'provider_type': 'multiple', 'option_texts': ['功能A', '功能B', '功能C', '功能D', '功能E'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-32'}, fallback_num=32)
        assert question['multi_min_limit'] == 2
        assert question['multi_max_limit'] == 4

    def test_normalize_question_detects_chinese_multi_select_limit(self) -> None:
        question = parser._normalize_question({'question_num': 'Q33', 'title': 'Q33 以下渠道最少选两项', 'question_kind': 'multiple', 'provider_type': 'multiple', 'option_texts': ['渠道A', '渠道B', '渠道C', '渠道D'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-33'}, fallback_num=33)
        assert question['multi_min_limit'] == 2

    def test_normalize_question_ignores_multi_select_limit_for_single_choice(self) -> None:
        question = parser._normalize_question({'question_num': 'Q31', 'title': 'Q31 单选题示例 [至多选2项]', 'question_kind': 'single', 'provider_type': 'single', 'option_texts': ['愿意', '不愿意', '无所谓'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-31'}, fallback_num=31)
        assert question['multi_min_limit'] is None
        assert question['multi_max_limit'] is None

    def test_normalize_question_does_not_treat_plain_select_prompt_as_forced_choice(self) -> None:
        question = parser._normalize_question({'question_num': 'Q2', 'title': 'Q2 请选择你的年龄段', 'title_text': '请选择你的年龄段', 'body_text': '请选择你的年龄段 1. 15-25岁 2. 26-35岁 3. 36-45岁 4. 46-55岁 5. 56-65岁 6. 65岁以上', 'question_kind': 'single', 'provider_type': 'single', 'option_texts': ['15-25岁', '26-35岁', '36-45岁', '46-55岁', '56-65岁', '65岁以上'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-2'}, fallback_num=2)
        assert question['forced_option_index'] is None
        assert question['forced_option_text'] is None

    def test_normalize_question_does_not_match_option_from_body_text_only(self) -> None:
        question = parser._normalize_question({'question_num': 'Q5', 'title': 'Q5 请选择你的职业类型', 'title_text': '请选择你的职业类型', 'body_text': '请选择你的职业类型 1. 学生 2. 国有企业 3. 事业单位 4. 公务员 5. 民营企业/个体工商户 6. 外资企业 7. 退休人员', 'question_kind': 'single', 'provider_type': 'single', 'option_texts': ['学生', '国有企业', '事业单位', '公务员', '民营企业/个体工商户', '外资企业', '退休人员'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-5'}, fallback_num=5)
        assert question['forced_option_index'] is None
        assert question['forced_option_text'] is None

    def test_normalize_question_prefers_full_title_text_and_strips_type_tag(self) -> None:
        question = parser._normalize_question({'question_num': 'Q7', 'title': '本题检测是否认真作答', 'title_full_text': 'Q7 [单选题] 本题检测是否认真作答，请选 非常不满意', 'title_text': '本题检测是否认真作答', 'question_kind': 'single', 'provider_type': 'single', 'option_texts': ['非常不满意', '不满意', '满意', '非常满意'], 'text_inputs': 0, 'page': 1, 'question_id': 'question-7'}, fallback_num=7)
        assert question['num'] == 7
        assert question['title'] == '[单选题] 本题检测是否认真作答，请选 非常不满意'
        assert question['forced_option_index'] == 0
        assert question['forced_option_text'] == '非常不满意'

    def test_helper_parsers_cover_arithmetic_counts_and_forced_texts(self) -> None:
        assert parser._safe_eval_arithmetic_expression("100 + 20 / 2") == 110.0
        assert parser._safe_eval_arithmetic_expression("1/0") is None
        assert parser._parse_count_token("十二") == 12
        assert parser._parse_count_token("abc") is None
        assert parser._extract_forced_texts('请填写：“你好”', extra_fragments=['请填写：“你好”']) == ['你好']
        assert parser._extract_arithmetic_option("请问100+100等于多少", ["300", "200", "500"])[0] == 1

    def test_extract_multi_select_limits_clamps_and_merges_range(self) -> None:
        min_limit, max_limit = parser._extract_multi_select_limits(
            "请至少选三项，最多选十项，也可以选择2-4项",
            option_count=4,
            extra_fragments=["最少选两项"],
        )

        assert min_limit == 3
        assert max_limit == 4

    def test_normalize_question_defaults_blank_text_title_and_rating_max(self) -> None:
        question = parser._normalize_question(
            {
                'question_num': '',
                'title': '',
                'question_kind': 'scale',
                'provider_type': 'scale',
                'option_texts': ['1', '2', '3'],
                'text_inputs': 0,
                'page': 1,
                'question_id': 'question-5',
            },
            fallback_num=5,
        )

        assert question['title'] == 'Q5'
        assert question['type_code'] == '5'
        assert question['rating_max'] == 3

    def test_normalize_question_marks_plain_text_block_as_description(self) -> None:
        question = parser._normalize_question(
            {
                'question_num': 'Q1',
                'title': '请您根据您与AI购物助手交互过程中的感受，判断下面句子描述和个人感受的差异，1分代表您非常不同意句子的内容，7分代表您非常同意句子的内容。',
                'title_full_text': '请您根据您与AI购物助手交互过程中的感受，判断下面句子描述和个人感受的差异，1分代表您非常不同意句子的内容，7分代表您非常同意句子的内容。',
                'question_kind': '',
                'provider_type': '',
                'option_texts': [],
                'text_inputs': 0,
                'page': 1,
                'question_id': 'question-1',
            },
            fallback_num=1,
        )

        assert question['is_description'] is True
        assert question['type_code'] == '0'
        assert question['is_text_like'] is False

    def test_page_has_answerable_questions_filters_out_intro_blocks(self) -> None:
        intro_only = [
            {'type_code': '1', 'question_kind': '', 'options': 0, 'text_inputs': 0, 'title': '知情同意书'},
            {'type_code': '1', 'question_kind': '', 'options': 0, 'text_inputs': 0, 'title': '购物情境'},
        ]
        real_questions = intro_only + [
            {'type_code': '5', 'question_kind': 'scale', 'options': 7, 'text_inputs': 0, 'title': '我认为AI购物助手...'}
        ]

        assert not parser._page_has_answerable_questions(intro_only)
        assert parser._page_has_answerable_questions(real_questions)

    def test_default_builder_locks_credamo_force_select_question(self) -> None:
        entries = build_default_question_entries([{'num': 7, 'title': '本题检测是否认真作答，请选 非常不满意', 'type_code': '3', 'options': 4, 'option_texts': ['非常不满意', '不满意', '满意', '非常满意'], 'provider': 'credamo', 'provider_question_id': 'question-7', 'provider_page_id': '1', 'forced_option_index': 0, 'forced_option_text': '非常不满意'}], survey_url='https://www.credamo.com/answer.html#/s/demo')
        assert len(entries) == 1
        assert entries[0].question_num == 7
        assert entries[0].question_type == 'single'
        assert entries[0].distribution_mode == 'custom'
        assert entries[0].probabilities == [1.0, 0.0, 0.0, 0.0]
        assert entries[0].custom_weights == [1.0, 0.0, 0.0, 0.0]

    def test_default_builder_locks_credamo_forced_text_question(self) -> None:
        entries = build_default_question_entries([{'num': 10, 'title': '本题检测是否认真作答，请输入：你好', 'type_code': '1', 'options': 1, 'provider': 'credamo', 'provider_question_id': 'question-10', 'provider_page_id': '1', 'forced_texts': ['你好'], 'is_text_like': True, 'text_inputs': 1}], survey_url='https://www.credamo.com/answer.html#/s/demo')
        assert len(entries) == 1
        assert entries[0].question_num == 10
        assert entries[0].question_type == 'text'
        assert entries[0].texts == ['你好']

    @pytest.mark.asyncio
    async def test_parse_credamo_survey_reads_detail_interface_questions(self) -> None:
        detail_data = {
            "surveyTitle": "Credamo 标题",
            "questions": [
                {
                    "qstNo": "Q1",
                    "qstTitle": "正式题目",
                    "questionType": 2,
                    "selector": 1,
                    "questionId": "q1",
                    "choices": [{"display": "A"}, {"display": "B"}],
                },
                {
                    "qstNo": "Q2",
                    "qstTitle": "矩阵题",
                    "questionType": 4,
                    "questionId": "q2",
                    "choices": [{"display": "行1"}, {"display": "行2"}],
                    "answers": [{"display": "满意"}, {"display": "不满意"}],
                },
            ],
        }

        with patch('credamo.provider.parser._fetch_detail', new=AsyncMock(return_value=detail_data)):
            info, title = await parser.parse_credamo_survey('https://www.credamo.com/answer.html#/s/demo_')

        assert title == 'Credamo 标题'
        assert [item['title'] for item in info] == ['正式题目', '矩阵题']
        assert info[0]['provider_type'] == 'single'
        assert info[0]['option_texts'] == ['A', 'B']
        assert info[1]['provider_type'] == 'matrix'
        assert info[1]['row_texts'] == ['行1', '行2']

    @pytest.mark.asyncio
    async def test_parse_credamo_survey_rejects_empty_detail_questions(self) -> None:
        with patch('credamo.provider.parser._fetch_detail', new=AsyncMock(return_value={"surveyTitle": "空问卷", "questions": []})):
            with pytest.raises(parser.CredamoParseError, match="未返回可解析题目"):
                await parser.parse_credamo_survey('https://www.credamo.com/answer.html#/s/demo_')

    def test_order_entry_is_exposed_to_runtime_mapping(self) -> None:
        entry = QuestionEntry(question_type='order', probabilities=-1, option_count=4, question_num=6, question_title='排序题', survey_provider='credamo')
        ctx = SimpleNamespace()
        configure_probabilities([entry], ctx)
        assert ctx.question_config_index_map[6] == ('order', -1)

from __future__ import annotations
from software.core.questions.meta_helpers import count_positive_weights, find_all_zero_attached_selects, find_all_zero_matrix_rows, infer_question_entry_type, normalize_attached_option_selects, normalize_fillable_option_indices
from software.providers.contracts import (
    LOGIC_PARSE_STATUS_COMPLETE,
    SurveyQuestionMeta,
    build_survey_definition,
)

class QuestionMetaHelperTests:

    def test_infer_question_entry_type_prefers_multi_text_and_text_like_flags(self) -> None:
        meta = SurveyQuestionMeta(num=1, title='姓名和电话', type_code='9', is_text_like=True, is_multi_text=True, text_inputs=2)
        assert infer_question_entry_type(meta) == 'multi_text'

    def test_infer_question_entry_type_falls_back_to_matrix_for_type_code_9(self) -> None:
        meta = SurveyQuestionMeta(num=2, title='矩阵', type_code='9')
        assert infer_question_entry_type(meta) == 'matrix'

    def test_infer_question_entry_type_keeps_location_as_text_entry_for_runtime(self) -> None:
        meta = SurveyQuestionMeta(num=3, title='地区', type_code='1', is_location=True, text_inputs=0, is_text_like=False)
        assert infer_question_entry_type(meta) == 'text'

    def test_normalize_fillable_option_indices_deduplicates_and_clamps(self) -> None:
        result = normalize_fillable_option_indices([0, 2, 2, -1, 5], 3)
        assert result == [0, 2]

    def test_normalize_attached_option_selects_reuses_existing_positive_weights(self) -> None:
        parsed = [{'option_index': 0, 'option_text': '其他', 'select_options': ['A', 'B']}]
        existing = [{'option_index': 0, 'weights': [20, 80]}]
        result = normalize_attached_option_selects(parsed, existing)
        assert result[0]['weights'] == [20.0, 80.0]

    def test_count_positive_weights_and_zero_detectors(self) -> None:
        assert count_positive_weights([0, -1, 3, 4]) == 2
        assert find_all_zero_matrix_rows([[1, 0], [0, 0], [0, 2]]) == [2]
        assert find_all_zero_matrix_rows([0, 0, 0]) == [0]
        assert find_all_zero_attached_selects([{'option_text': '其他', 'weights': [0, 0]}, {'option_text': '正常', 'weights': [1, 0]}]) == [(1, '其他')]

    def test_build_survey_definition_preserves_display_logic_metadata(self) -> None:
        definition = build_survey_definition('wjx', '条件显示问卷', [{'num': 1, 'title': '题目一', 'type_code': '3', 'has_dependent_display_logic': True, 'controls_display_targets': [{'target_question_num': 2, 'condition_option_indices': [0]}]}])
        question = definition.questions[0]
        assert question.has_dependent_display_logic
        assert question.controls_display_targets == [{'target_question_num': 2, 'condition_option_indices': [0]}]
        assert question.get('has_dependent_display_logic')
        assert question.get('controls_display_targets') == [{'target_question_num': 2, 'condition_option_indices': [0]}]

    def test_build_survey_definition_preserves_logic_status_and_media(self) -> None:
        definition = build_survey_definition(
            'wjx',
            '图题问卷',
            [{
                'num': 1,
                'title': '题目一',
                'type_code': '3',
                'logic_parse_status': LOGIC_PARSE_STATUS_COMPLETE,
                'question_media': [
                    {
                        'kind': 'image',
                        'scope': 'title',
                        'index': None,
                        'source_url': 'https://example.com/title.png',
                        'label': '题干图',
                    }
                ],
            }],
        )
        question = definition.questions[0]
        assert question.logic_parse_status == LOGIC_PARSE_STATUS_COMPLETE
        assert question.question_media == [
            {
                'kind': 'image',
                'scope': 'title',
                'index': None,
                'source_url': 'https://example.com/title.png',
                'label': '题干图',
            }
        ]

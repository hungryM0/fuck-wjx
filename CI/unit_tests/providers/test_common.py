from __future__ import annotations
from software.providers.common import SURVEY_PROVIDER_CREDAMO, SURVEY_PROVIDER_QQ, SURVEY_PROVIDER_WJX, detect_survey_provider, ensure_question_provider_fields, ensure_questions_provider_fields, is_credamo_survey_url, is_qq_survey_url, is_supported_survey_url, is_wjx_domain, is_wjx_survey_url, normalize_survey_provider

class ProviderCommonTests:

    def test_normalize_survey_provider_returns_default_for_unknown_value(self) -> None:
        assert normalize_survey_provider('unknown', default=SURVEY_PROVIDER_QQ) == SURVEY_PROVIDER_QQ

    def test_detect_survey_provider_distinguishes_three_platforms(self) -> None:
        assert detect_survey_provider('https://www.credamo.com/answer.html#/s/demo') == SURVEY_PROVIDER_CREDAMO
        assert detect_survey_provider('https://www.credamo.com/s/demo') == SURVEY_PROVIDER_CREDAMO
        assert detect_survey_provider('https://wj.qq.com/s2/123/abc') == SURVEY_PROVIDER_QQ
        assert detect_survey_provider('https://www.wjx.cn/vm/demo.aspx') == SURVEY_PROVIDER_WJX

    def test_wjx_helpers_accept_subdomains(self) -> None:
        assert is_wjx_domain('https://foo.wjx.top/demo')
        assert is_wjx_survey_url('https://sub.v.wjx.cn/m/demo.aspx')
        assert is_wjx_survey_url('https://www.wjx.top/vm/wx9ez4J.aspx')

    def test_qq_and_credamo_helpers_reject_non_matching_paths(self) -> None:
        assert not is_qq_survey_url('https://wj.qq.com/not-a-survey')
        assert not is_credamo_survey_url('https://www.credamo.com/profile')
        assert is_credamo_survey_url('https://www.credamo.com/s/demo')

    def test_is_supported_survey_url_returns_false_for_unknown_domain(self) -> None:
        assert not is_supported_survey_url('https://example.com/form')

    def test_ensure_question_provider_fields_normalizes_provider_metadata(self) -> None:
        result = ensure_question_provider_fields({'provider': '  CREDAMO  ', 'provider_question_id': ' question-7 ', 'provider_page_id': ' 1 ', 'provider_type': ' dropdown ', 'unsupported': 1, 'unsupported_reason': '  暂不支持  '})
        assert result['provider'] == SURVEY_PROVIDER_CREDAMO
        assert result['provider_question_id'] == 'question-7'
        assert result['provider_page_id'] == '1'
        assert result['provider_type'] == 'dropdown'
        assert result['unsupported']
        assert result['unsupported_reason'] == '暂不支持'

    def test_ensure_question_provider_fields_returns_empty_dict_for_non_mapping(self) -> None:
        assert ensure_question_provider_fields('bad') == {}

    def test_ensure_questions_provider_fields_filters_invalid_items(self) -> None:
        result = ensure_questions_provider_fields([{'provider': 'qq', 'provider_question_id': ' q1 '}, 'bad', {'provider': 'nope'}], default_provider=SURVEY_PROVIDER_WJX)
        assert len(result) == 2
        assert result[0]['provider'] == SURVEY_PROVIDER_QQ
        assert result[0]['provider_question_id'] == 'q1'
        assert result[1]['provider'] == SURVEY_PROVIDER_WJX

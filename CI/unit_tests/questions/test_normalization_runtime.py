from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from software.core.questions.normalization import configure_probabilities
from software.core.questions.schema import (
    GLOBAL_RELIABILITY_DIMENSION,
    QuestionEntry,
    _TEXT_RANDOM_ID_CARD,
    _TEXT_RANDOM_ID_CARD_TOKEN,
    _TEXT_RANDOM_INTEGER,
    _TEXT_RANDOM_MOBILE,
    _TEXT_RANDOM_MOBILE_TOKEN,
    _TEXT_RANDOM_NAME,
    _TEXT_RANDOM_NAME_TOKEN,
)
from software.providers.contracts import SurveyQuestionMeta


class NormalizationRuntimeTests:
    def test_configure_probabilities_maps_all_supported_question_types(self) -> None:
        ctx = SimpleNamespace()
        entries = [
            QuestionEntry(
                "single",
                [0, 3, 0],
                option_count=3,
                question_num=1,
                option_fill_texts=["", "补充", None],
                attached_option_selects=[{"option_index": 1, "weights": [1, 0]}],
            ),
            QuestionEntry(
                "dropdown",
                [1, 1],
                option_count=2,
                question_num=2,
                dimension="满意度",
                psycho_bias="positive",
            ),
            QuestionEntry("multiple", [25, 75], option_count=2, question_num=3, option_fill_texts=["A", "B"]),
            QuestionEntry(
                "matrix",
                [[1, 0, 0], [0, 2, 0]],
                rows=3,
                option_count=3,
                question_num=4,
                dimension="态度",
                psycho_bias=["positive", "negative"],
            ),
            QuestionEntry("scale", [1, 3], option_count=2, question_num=5, psycho_bias="negative"),
            QuestionEntry("score", [2, 2], option_count=2, question_num=6),
            QuestionEntry("slider", [75], option_count=1, question_num=7, distribution_mode="custom"),
            QuestionEntry("slider", -1, option_count=1, question_num=8, distribution_mode="random"),
            QuestionEntry("order", -1, question_num=9),
            QuestionEntry("text", [1, 3], texts=["甲", "乙"], question_num=10, ai_enabled=True, question_title="填空"),
            QuestionEntry(
                "multi_text",
                -1,
                texts=[],
                question_num=11,
                ai_enabled=False,
                multi_text_blank_modes=[_TEXT_RANDOM_INTEGER, "none"],
                multi_text_blank_ai_flags=[True, True],
                multi_text_blank_int_ranges=[[9, 3], []],
            ),
            QuestionEntry(
                "text",
                -1,
                texts=["位置"],
                question_num=12,
                is_location=True,
                location_parts=["北京", "北京", "东城区"],
            ),
        ]

        configure_probabilities(entries, ctx)

        assert ctx.question_config_index_map[1] == ("single", 0)
        assert ctx.provider_question_config_index_map == {}
        assert ctx.single_prob == [[0.0, 1.0, 0.0]]
        assert ctx.single_option_fill_texts == [[None, "补充", None]]
        assert ctx.single_attached_option_selects == [[{"option_index": 1, "weights": [1, 0]}]]
        assert ctx.question_dimension_map[2] == "满意度"
        assert ctx.question_psycho_bias_map[2] == "positive"
        assert ctx.multiple_prob == [[25.0, 75.0]]
        assert ctx.multiple_option_fill_texts == [["A", "B"]]
        assert ctx.matrix_prob == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 1.0, 0.0]]
        assert ctx.question_dimension_map[4] == "态度"
        assert ctx.question_psycho_bias_map[4] == ["positive", "negative"]
        assert ctx.scale_prob == [[0.25, 0.75], [0.5, 0.5]]
        assert ctx.slider_targets[0] == 75.0
        assert math.isnan(ctx.slider_targets[1])
        assert ctx.question_config_index_map[9] == ("order", -1)
        assert ctx.texts[0] == ["甲", "乙"]
        assert ctx.texts_prob[0] == [0.25, 0.75]
        assert ctx.text_ai_flags[0] is True
        assert ctx.text_titles[0] == "填空"
        assert ctx.text_entry_types == ["text", "multi_text", "text"]
        assert ctx.text_ai_flags[1] is True
        assert ctx.multi_text_blank_int_ranges[1] == [[3, 9], []]
        assert ctx.question_config_index_map[12] == ("location", -1)
        assert ctx.location_parts[12] == ["北京", "北京", "东城区"]

    def test_configure_probabilities_builds_provider_question_mapping(self) -> None:
        ctx = SimpleNamespace()
        entries = [
            QuestionEntry(
                "scale",
                [1, 2, 3],
                option_count=3,
                question_num=2,
                survey_provider="credamo",
                provider_page_id="4",
                provider_question_id="question-1",
            ),
            QuestionEntry(
                "scale",
                [3, 2, 1],
                option_count=3,
                question_num=2,
                survey_provider="credamo",
                provider_page_id="5",
                provider_question_id="question-1",
            ),
        ]

        configure_probabilities(entries, ctx)

        assert ctx.question_config_index_map[2] == ("scale", 1)
        assert ctx.provider_question_config_index_map == {
            "credamo:4:question-1": ("scale", 0),
            "credamo:5:question-1": ("scale", 1),
        }

    def test_configure_probabilities_assigns_global_reliability_dimension_when_none_explicit(self) -> None:
        ctx = SimpleNamespace()
        entries = [
            QuestionEntry("dropdown", [1, 1], option_count=2, question_num=1),
            QuestionEntry("scale", [1, 1], option_count=2, question_num=2),
        ]

        configure_probabilities(entries, ctx)

        assert ctx.question_dimension_map == {
            1: GLOBAL_RELIABILITY_DIMENSION,
            2: GLOBAL_RELIABILITY_DIMENSION,
        }

    def test_configure_probabilities_adds_only_ordinal_single_to_reliability(self) -> None:
        ctx = SimpleNamespace(
            questions_metadata={
                1: SurveyQuestionMeta(
                    num=1,
                    title="满意度",
                    type_code="3",
                    options=5,
                    option_texts=["非常满意", "满意", "一般", "不满意", "非常不满意"],
                ),
                2: SurveyQuestionMeta(
                    num=2,
                    title="性别",
                    type_code="3",
                    options=2,
                    option_texts=["男", "女"],
                ),
            }
        )
        entries = [
            QuestionEntry("single", [1, 1, 1, 1, 1], option_count=5, question_num=1),
            QuestionEntry("single", [1, 1], option_count=2, question_num=2),
        ]

        configure_probabilities(entries, ctx)

        assert ctx.question_dimension_map == {1: GLOBAL_RELIABILITY_DIMENSION}
        assert ctx.question_ordinal_score_map == {1: [4, 3, 2, 1, 0]}

    @pytest.mark.parametrize(
        ("entry", "message"),
        [
            (QuestionEntry("single", [0, 0], option_count=2, question_num=1), "所有选项配比均为 0"),
            (QuestionEntry("dropdown", [0, 0], option_count=2, question_num=2), "所有选项配比均为 0"),
            (QuestionEntry("matrix", [[1, 0], [0, 0]], rows=2, option_count=2, question_num=3), "第 2 行配比全部为 0"),
            (QuestionEntry("matrix", [0, 0], rows=1, option_count=2, question_num=4), "矩阵题"),
            (QuestionEntry("multiple", -1, option_count=2, question_num=5), "多选题必须提供概率列表"),
            (QuestionEntry("text", -1, texts=[], question_num=6), "填空题至少需要一个候选答案"),
            (
                QuestionEntry(
                    "text",
                    -1,
                    texts=[],
                    question_num=7,
                    text_random_mode=_TEXT_RANDOM_INTEGER,
                    text_random_int_range=[],
                ),
                "随机整数范围未设置完整",
            ),
            (
                QuestionEntry(
                    "multi_text",
                    -1,
                    texts=["x"],
                    question_num=8,
                    multi_text_blank_modes=[_TEXT_RANDOM_INTEGER],
                    multi_text_blank_int_ranges=[[]],
                ),
                "多项填空题第1个空位",
            ),
            (
                QuestionEntry(
                    "single",
                    [1, 1],
                    option_count=2,
                    question_num=9,
                    attached_option_selects=[{"option_text": "A", "weights": [0, 0]}],
                ),
                "嵌入式下拉",
            ),
        ],
    )
    def test_configure_probabilities_rejects_invalid_configs(self, entry: QuestionEntry, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            configure_probabilities([entry], SimpleNamespace())

    @pytest.mark.parametrize(
        ("mode", "expected"),
        [
            (_TEXT_RANDOM_NAME, _TEXT_RANDOM_NAME_TOKEN),
            (_TEXT_RANDOM_MOBILE, _TEXT_RANDOM_MOBILE_TOKEN),
            (_TEXT_RANDOM_ID_CARD, _TEXT_RANDOM_ID_CARD_TOKEN),
        ],
    )
    def test_text_random_modes_override_ai_and_candidate_text(self, mode: str, expected: str) -> None:
        ctx = SimpleNamespace()
        configure_probabilities(
            [QuestionEntry("text", -1, texts=["原值"], question_num=1, ai_enabled=True, text_random_mode=mode)],
            ctx,
        )

        assert ctx.texts == [[expected]]
        assert ctx.text_ai_flags == [False]

    def test_text_random_integer_builds_runtime_token(self) -> None:
        ctx = SimpleNamespace()

        configure_probabilities(
            [
                QuestionEntry(
                    "text",
                    -1,
                    texts=["原值"],
                    question_num=1,
                    text_random_mode=_TEXT_RANDOM_INTEGER,
                    text_random_int_range=[9, 3],
                )
            ],
            ctx,
        )

        assert ctx.texts == [["__RANDOM_INT__:3:9"]]

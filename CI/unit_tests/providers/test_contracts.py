from __future__ import annotations

import pytest

from credamo.provider import parser as credamo_parser
from software.providers.common import (
    SURVEY_PROVIDER_CREDAMO,
    SURVEY_PROVIDER_QQ,
    SURVEY_PROVIDER_WJX,
)
from software.providers.contracts import (
    LOGIC_PARSE_STATUS_COMPLETE,
    LOGIC_PARSE_STATUS_NONE,
    LOGIC_PARSE_STATUS_UNKNOWN,
    build_survey_definition,
    ensure_survey_question_meta,
    serialize_survey_question_metas,
)
from tencent.provider import parser as qq_parser
from wjx.provider.html_parser import parse_survey_questions_from_html


def _build_wjx_question():
    html = """
    <html>
      <body>
        <div id="divQuestion">
          <fieldset>
            <div topic="1" id="div1" type="3">
              <div class="topichtml">1. 单选题<img src="//cdn.example.com/wjx-title.png" /></div>
              <div class="ui-controlgroup">
                <div><span class="label">选项A</span></div>
                <div><span class="label">选项B</span></div>
              </div>
            </div>
          </fieldset>
        </div>
      </body>
    </html>
    """
    return parse_survey_questions_from_html(html)[0]


def _build_qq_question():
    return qq_parser._standardize_qq_questions(
        [
            {
                "id": "qq-q1",
                "type": "checkbox",
                "title": "  腾讯多选题  ",
                "description": "  说明  ",
                "options": [
                    {"text": "选项A", "image_url": "//cdn.example.com/qq-option-a.png"},
                    {"text": "其他 {fillblank-1}", "extra": {"fillblank": True}},
                ],
                "page_id": "qq-page-1",
                "page": "9",
                "min_length": 1,
                "max_length": 2,
                "required": True,
            }
        ]
    )[0]


def _build_credamo_question():
    return credamo_parser._normalize_question(
        {
            "question_num": "Q3",
            "title": "  Credamo 评分题  ",
            "question_kind": "scale",
            "provider_type": "scale",
            "option_texts": ["1", "2", "3"],
            "text_inputs": 0,
            "page": 4,
            "question_id": "question-3",
            "question_media": [
                {
                    "kind": "image",
                    "scope": "title",
                    "index": None,
                    "source_url": "https://example.com/credamo-title.png",
                    "label": "题干图",
                }
            ],
        },
        fallback_num=3,
    )


class ProviderContractsTests:
    def test_ensure_survey_question_meta_normalizes_media_and_missing_provider_fields(self) -> None:
        meta = ensure_survey_question_meta(
            {
                "num": 0,
                "page": 0,
                "title": "  测试题  ",
                "type_code": "3",
                "options": 2,
                "logic_parse_status": "bad-status",
                "provider": "unknown",
                "provider_question_id": "",
                "provider_page_id": "",
                "unsupported": True,
                "unsupported_reason": "",
                "question_media": [
                    {
                        "kind": "image",
                        "scope": "title",
                        "index": 99,
                        "source_url": " https://example.com/title.png ",
                        "label": " 题干图 ",
                    },
                    {
                        "kind": "image",
                        "scope": "option",
                        "index": "1",
                        "source_url": "https://example.com/option-b.png",
                        "label": " 选项B ",
                    },
                    {
                        "kind": "image",
                        "scope": "row",
                        "index": "-1",
                        "source_url": "https://example.com/bad-row.png",
                        "label": "坏行",
                    },
                    {
                        "kind": "video",
                        "scope": "title",
                        "index": None,
                        "source_url": "https://example.com/video.mp4",
                        "label": "坏媒体",
                    },
                ],
            },
            default_provider=SURVEY_PROVIDER_QQ,
            index=7,
        )

        assert meta.num == 1
        assert meta.page == 1
        assert meta.provider == SURVEY_PROVIDER_QQ
        assert meta.provider_question_id == "1"
        assert meta.provider_page_id == "1"
        assert meta.logic_parse_status == LOGIC_PARSE_STATUS_UNKNOWN
        assert meta.unsupported_reason == "当前平台暂不支持该题型"
        assert meta.question_media == [
            {
                "kind": "image",
                "scope": "title",
                "index": None,
                "source_url": "https://example.com/title.png",
                "label": "题干图",
            },
            {
                "kind": "image",
                "scope": "option",
                "index": 1,
                "source_url": "https://example.com/option-b.png",
                "label": "选项B",
            },
        ]

    def test_description_provider_type_is_not_treated_as_unsupported(self) -> None:
        meta = ensure_survey_question_meta(
            {
                "num": 5,
                "title": "模特A：无眼镜",
                "type_code": "0",
                "provider_type": "description",
                "unsupported": True,
                "unsupported_reason": "暂不支持腾讯题型：description",
            },
            default_provider=SURVEY_PROVIDER_QQ,
        )

        assert meta.is_description is True
        assert meta.unsupported is False

    def test_legacy_logic_status_is_inferred_from_saved_rules(self) -> None:
        jump_meta = ensure_survey_question_meta(
            {
                "num": 1,
                "title": "跳题",
                "has_jump": True,
                "jump_rules": [{"option_index": 1, "jumpto": 5}],
            }
        )
        plain_meta = ensure_survey_question_meta({"num": 2, "title": "普通题"})
        unknown_meta = ensure_survey_question_meta({"num": 3, "title": "未知跳题", "has_jump": True})

        assert jump_meta.logic_parse_status == LOGIC_PARSE_STATUS_COMPLETE
        assert plain_meta.logic_parse_status == LOGIC_PARSE_STATUS_NONE
        assert unknown_meta.logic_parse_status == LOGIC_PARSE_STATUS_UNKNOWN

    @pytest.mark.parametrize(
        ("provider", "question_builder"),
        [
            (SURVEY_PROVIDER_WJX, _build_wjx_question),
            (SURVEY_PROVIDER_QQ, _build_qq_question),
            (SURVEY_PROVIDER_CREDAMO, _build_credamo_question),
        ],
    )
    def test_parser_outputs_share_same_normalized_contract(self, provider: str, question_builder) -> None:
        question = question_builder()

        definition = build_survey_definition(provider, "  解析标题  ", [question])
        normalized = definition.questions[0]
        dumped = normalized.to_dict()

        assert definition.provider == provider
        assert definition.title == "解析标题"
        assert dumped["provider"] == provider
        assert dumped["title"]
        assert dumped["provider_question_id"]
        assert dumped["provider_page_id"]
        assert dumped["logic_parse_status"] in {"none", "complete", "unknown"}
        assert dumped["rows"] >= 1
        assert isinstance(dumped["question_media"], list)

    def test_serialized_question_meta_preserves_provider_identity_fields(self) -> None:
        meta = ensure_survey_question_meta(
            {
                "num": 8,
                "title": "联系方式",
                "provider": SURVEY_PROVIDER_QQ,
                "provider_question_id": "question-8",
                "provider_page_id": "page-2",
                "provider_type": "text",
                "required": True,
                "option_texts": ["姓名", "电话"],
            },
            default_provider=SURVEY_PROVIDER_WJX,
        )

        dumped = serialize_survey_question_metas([meta])[0]
        cloned = ensure_survey_question_meta(dumped, default_provider=SURVEY_PROVIDER_WJX)

        assert dumped["provider"] == SURVEY_PROVIDER_QQ
        assert dumped["provider_question_id"] == "question-8"
        assert dumped["provider_page_id"] == "page-2"
        assert dumped["provider_type"] == "text"
        assert dumped["required"] is True
        assert cloned.provider == SURVEY_PROVIDER_QQ

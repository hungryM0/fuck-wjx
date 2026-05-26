from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tencent.provider import parser as qq_parser


class _FakeHttpResponse:
    def __init__(
        self,
        *,
        json_payload=None,
        text: str = "",
        url: str = "https://wj.qq.com/api/demo",
        headers=None,
        history=None,
        should_raise: Exception | None = None,
    ) -> None:
        self._json_payload = json_payload
        self.text = text
        self.url = url
        self.headers = headers or {}
        self.history = history or []
        self._should_raise = should_raise

    def raise_for_status(self) -> None:
        if self._should_raise is not None:
            raise self._should_raise

    def json(self):
        if isinstance(self._json_payload, Exception):
            raise self._json_payload
        return self._json_payload


class TencentParserTests:
    def test_parser_module_no_longer_exposes_parse_browser_fallback(self) -> None:
        assert not hasattr(qq_parser, "acquire_parse_browser_session")

    def test_login_required_helpers_cover_url_error_and_response(self) -> None:
        assert qq_parser._is_qq_login_required_url("https://open.weixin.qq.com/connect/confirm?a=1")
        assert qq_parser._is_qq_login_required_url("wj.qq.com/r/login.html")
        assert qq_parser._is_qq_login_required_error({"msg": ["need login"]})
        assert not qq_parser._is_qq_login_required_error("all good")

        response = _FakeHttpResponse(
            text="normal",
            headers={"location": "https://wj.qq.com/r/login.html"},
            history=[SimpleNamespace(url="https://foo.example")],
        )
        assert qq_parser._is_qq_login_required_response(response)

    @pytest.mark.asyncio
    async def test_request_qq_api_raises_on_invalid_json_and_non_dict_payload(self, patch_attrs) -> None:
        bad_json_response = _FakeHttpResponse(json_payload=ValueError("bad json"), text="not login")
        bad_json_aget = AsyncMock(return_value=bad_json_response)
        patch_attrs((qq_parser.http_client, "aget", bad_json_aget))

        with pytest.raises(RuntimeError, match="无法解析的响应：meta"):
            await qq_parser._request_qq_api("123", "meta", hash_value="hash", headers={})
        assert bad_json_aget.await_args.kwargs.get("proxies") == {}

        non_dict_response = _FakeHttpResponse(json_payload=["bad"])
        non_dict_aget = AsyncMock(return_value=non_dict_response)
        patch_attrs((qq_parser.http_client, "aget", non_dict_aget))

        with pytest.raises(RuntimeError, match="非对象响应：questions"):
            await qq_parser._request_qq_api("123", "questions", hash_value="hash", headers={})
        assert non_dict_aget.await_args.kwargs.get("proxies") == {}

    @pytest.mark.asyncio
    async def test_ensure_api_ok_and_http_fetch_locale_fallback(self, patch_attrs) -> None:
        calls: list[str] = []

        async def fake_request(_survey_id, endpoint, *, hash_value, headers, extra_params=None):
            _ = hash_value, headers
            locale = (extra_params or {}).get("locale")
            calls.append(f"{endpoint}:{locale or ''}")
            if endpoint == "session":
                return {"code": "OK", "data": {}}
            if endpoint == "meta" and locale == "zhs":
                return {"code": "FAIL", "data": {}}
            if endpoint == "questions" and locale == "zht":
                return {"code": "OK", "data": {"questions": []}}
            if endpoint == "meta" and locale == "zh":
                return {"code": "OK", "data": {"title": "腾讯问卷标题 - 腾讯问卷"}}
            if endpoint == "questions" and locale == "zh":
                return {
                    "code": "OK",
                    "data": {
                        "questions": [
                            {"id": "q1", "type": "radio", "title": "题目1", "options": [{"text": "A"}], "page_id": "p1", "page": 1}
                        ]
                    },
                }
            return {"code": "OK", "data": {}}

        patch_attrs((qq_parser, "_request_qq_api", fake_request))

        info, title = await qq_parser._fetch_qq_survey_via_http("123", "hash")

        assert title == "腾讯问卷标题 - 腾讯问卷"
        assert qq_parser._normalize_qq_title("标题 - 腾讯问卷") == "标题"
        assert info[0]["provider_question_id"] == "q1"
        assert "meta:zhs" in calls
        assert "questions:zh" in calls

        with pytest.raises(RuntimeError, match="接口返回异常（meta）：FAIL"):
            qq_parser._ensure_qq_api_ok({"code": "FAIL", "data": {}}, "meta")

        with pytest.raises(RuntimeError, match="缺少 data 对象：meta"):
            qq_parser._ensure_qq_api_ok({"code": "OK", "data": []}, "meta")

    def test_builders_and_standardize_questions_cover_fillblank_rating_and_unsupported(self) -> None:
        question = {
            "id": "q1",
            "type": "checkbox",
            "title": "  题目1  ",
            "description": " 描述 ",
            "options": [
                {"text": "正常选项", "image_url": "https://example.com/option-a.png"},
                {"text": "其他 {fillblank-1}", "extra": {"fillblank": True}},
            ],
            "sub_titles": [{"text": " 行1 "}, {"text": "行2"}],
            "page_id": "page-a",
            "page": "2",
            "min_length": 1,
            "max_length": 3,
            "required": True,
        }
        rating_question = {
            "id": "q2",
            "type": "star",
            "title": "评分题",
            "star_begin_num": 3,
            "star_num": 4,
            "page_id": "page-b",
            "page": "4",
        }
        unsupported_question = {
            "id": "q3",
            "type": "upload",
            "title": "上传题",
            "page_id": "page-b",
            "page": "4",
        }

        normalized = qq_parser._standardize_qq_questions([question, rating_question, unsupported_question])

        first = normalized[0]
        assert qq_parser._normalize_qq_option_text(" 其他 _{fillblank-1} ") == "其他"
        assert qq_parser._option_payload_contains_fillblank({"nested": ["x", "{fillblank-a}"]})
        assert first["fillable_options"] == [1]
        assert first["row_texts"] == ["行1", "行2"]
        assert first["multi_min_limit"] == 1
        assert first["multi_max_limit"] == 3
        assert first["page"] == 1
        assert first["logic_parse_status"] == "unknown"
        assert first["question_media"][0]["scope"] == "option"
        assert first["question_media"][0]["source_url"] == "https://example.com/option-a.png"

        second = normalized[1]
        assert second["is_rating"]
        assert second["option_texts"] == ["3", "4", "5", "6"]
        assert second["rating_max"] == 4

        third = normalized[2]
        assert third["unsupported"]
        assert "暂不支持腾讯题型" in third["unsupported_reason"]
        assert first["display_num"] == 1
        assert second["display_num"] == 2
        assert third["display_num"] == 3

    def test_standardize_qq_questions_marks_description_and_merges_into_next_question(self) -> None:
        description_question = {
            "id": "q5",
            "type": "description",
            "title": "模特A：无眼镜",
            "description": "请观察以下模特照片",
            "page_id": "page-a",
            "page": "2",
        }
        matrix_question = {
            "id": "q6",
            "type": "matrix_radio",
            "title": "请根据您对模特的第一印象进行评价",
            "options": [{"text": "1"}, {"text": "2"}, {"text": "3"}],
            "sub_titles": [{"text": "专业"}, {"text": "时尚"}],
            "page_id": "page-a",
            "page": "2",
        }

        normalized = qq_parser._standardize_qq_questions([description_question, matrix_question])

        first = normalized[0]
        assert first["is_description"] is True
        assert first["unsupported"] is False
        assert first["display_num"] is None

        second = normalized[1]
        assert second["is_description"] is False
        assert second["display_num"] == 1
        assert second["title"] == "模特A：无眼镜 请根据您对模特的第一印象进行评价"
        assert second["description"] == "请观察以下模特照片"

    def test_standardize_questions_extracts_option_level_jump_and_display_logic(self) -> None:
        questions = [
            {
                "id": "q-1",
                "type": "radio",
                "title": "来源题",
                "page_id": "p-1",
                "page": 1,
                "options": [
                    {"text": "显示后续题", "display": {"targets": ["q-2", "q-3"]}},
                    {"text": "跳到第二页", "goto": {"page": "p-2"}},
                ],
            },
            {
                "id": "q-2",
                "type": "text",
                "title": "条件题一",
                "page_id": "p-1",
                "page": 1,
                "hidden": True,
                "refer": {"source": "q-1"},
            },
            {
                "id": "q-3",
                "type": "text",
                "title": "条件题二",
                "page_id": "p-1",
                "page": 1,
                "hidden": True,
                "refer": "q-1",
            },
            {
                "id": "q-4",
                "type": "text",
                "title": "第二页首题",
                "page_id": "p-2",
                "page": 2,
            },
        ]

        normalized = qq_parser._standardize_qq_questions(questions)

        source = normalized[0]
        assert source["has_dependent_display_logic"] is True
        assert source["controls_display_targets"] == [
            {
                "target_question_num": 2,
                "condition_option_indices": [0],
                "condition_mode": "selected",
            },
            {
                "target_question_num": 3,
                "condition_option_indices": [0],
                "condition_mode": "selected",
            },
        ]
        assert source["has_jump"] is True
        assert source["jump_rules"] == [
            {
                "option_index": 1,
                "jumpto": 4,
                "option_text": "跳到第二页",
            }
        ]
        assert source["logic_parse_status"] == "complete"

        target_one = normalized[1]
        assert target_one["has_display_condition"] is True
        assert target_one["display_conditions"] == [
            {
                "condition_question_num": 1,
                "condition_mode": "selected",
                "condition_option_indices": [0],
            }
        ]
        assert target_one["logic_parse_status"] == "complete"

        target_two = normalized[2]
        assert target_two["has_display_condition"] is True
        assert target_two["display_conditions"] == [
            {
                "condition_question_num": 1,
                "condition_mode": "selected",
                "condition_option_indices": [0],
            }
        ]
        assert target_two["logic_parse_status"] == "complete"

    def test_build_question_media_from_payload_normalizes_protocol_relative_urls_and_deduplicates(self) -> None:
        media = qq_parser._build_question_media_from_payload(
            {
                "title": {"image_url": "//cdn.example.com/title.png", "nested": {"src": "//cdn.example.com/title.png"}},
                "description": {"img": "//cdn.example.com/title.png"},
                "options": [
                    {"text": " 选项A ", "image_url": "//cdn.example.com/option-a.png", "extra": {"src": "//cdn.example.com/option-a.png"}},
                    {"text": "选项B", "pic_url": "https://example.com/option-b.jpg"},
                ],
                "sub_titles": [
                    {"text": " 行1 ", "image": "//cdn.example.com/row-1.png", "nested": {"src": "//cdn.example.com/row-1.png"}}
                ],
            },
            "radio",
        )

        assert media == [
            {
                "kind": "image",
                "scope": "title",
                "index": None,
                "source_url": "https://cdn.example.com/title.png",
                "label": "题干图",
            },
            {
                "kind": "image",
                "scope": "option",
                "index": 0,
                "source_url": "https://cdn.example.com/option-a.png",
                "label": "选项A",
            },
            {
                "kind": "image",
                "scope": "option",
                "index": 1,
                "source_url": "https://example.com/option-b.jpg",
                "label": "选项B",
            },
            {
                "kind": "image",
                "scope": "row",
                "index": 0,
                "source_url": "https://cdn.example.com/row-1.png",
                "label": "行1",
            },
        ]

    async def test_parse_qq_survey_returns_http_result_without_browser_fallback(self, patch_attrs) -> None:
        patch_attrs(
            (qq_parser, "_fetch_qq_survey_via_http", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("http failed"))),
        )

        with pytest.raises(RuntimeError, match="腾讯问卷 HTTP 解析失败：http failed"):
            await qq_parser.parse_qq_survey("https://wj.qq.com/s2/123/hash/")

    @pytest.mark.asyncio
    async def test_parse_qq_survey_rejects_login_url_and_http_failure_without_browser_fallback(self, patch_attrs) -> None:
        with pytest.raises(RuntimeError, match="需要登录"):
            await qq_parser.parse_qq_survey("https://wj.qq.com/r/login.html")

        patch_attrs(
            (qq_parser, "_fetch_qq_survey_via_http", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("http failed"))),
        )

        with pytest.raises(RuntimeError, match="腾讯问卷 HTTP 解析失败：http failed"):
            await qq_parser.parse_qq_survey("https://wj.qq.com/s2/123/hash/")

    @pytest.mark.asyncio
    async def test_parse_qq_survey_login_required_http_error_is_terminal(self, patch_attrs) -> None:
        patch_attrs(
            (qq_parser, "_fetch_qq_survey_via_http", AsyncMock(side_effect=RuntimeError("need login"))),
        )

        with pytest.raises(RuntimeError, match="需要登录"):
            await qq_parser.parse_qq_survey("https://wj.qq.com/s2/123/hash/")

    @pytest.mark.asyncio
    async def test_parse_qq_survey_http_failure_is_terminal(self, patch_attrs) -> None:
        patch_attrs(
            (qq_parser, "_fetch_qq_survey_via_http", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("http failed"))),
        )

        with pytest.raises(RuntimeError, match="腾讯问卷 HTTP 解析失败：http failed"):
            await qq_parser.parse_qq_survey("https://wj.qq.com/s2/123/hash/")

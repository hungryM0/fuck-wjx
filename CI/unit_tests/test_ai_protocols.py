from __future__ import annotations
import asyncio
from types import SimpleNamespace

import pytest

from software.integrations.ai.client import AI_MODE_PROVIDER, FREE_QUESTION_TYPE_FILL, save_ai_settings
import software.integrations.ai.protocols as protocols
from software.integrations.ai.protocols import _extract_chat_completion_text, _extract_responses_text, _resolve_custom_endpoint

class AIProtocolTests:

    def setup_method(self, _method) -> None:
        save_ai_settings(ai_mode=AI_MODE_PROVIDER, provider='custom', api_key='test-key', base_url='https://example.com/v1', api_protocol='responses', model='demo-model', system_prompt='测试提示词')

    def test_resolve_custom_endpoint_appends_protocol_suffix(self) -> None:
        protocol, url, explicit = _resolve_custom_endpoint('https://example.com/v1', 'responses')
        assert protocol == 'responses'
        assert url == 'https://example.com/v1/responses'
        assert not explicit

    def test_resolve_custom_endpoint_handles_explicit_and_invalid_urls(self) -> None:
        assert _resolve_custom_endpoint(" https://example.com/v1/chat/completions/ ", "auto") == (
            "chat_completions",
            "https://example.com/v1/chat/completions",
            True,
        )
        assert _resolve_custom_endpoint("https://example.com/v1/responses", "chat") == (
            "responses",
            "https://example.com/v1/responses",
            True,
        )
        with pytest.raises(RuntimeError, match="旧版 /completions"):
            _resolve_custom_endpoint("https://example.com/v1/completions", "auto")
        with pytest.raises(RuntimeError, match="Base URL"):
            _resolve_custom_endpoint("   ", "auto")

    def test_extract_chat_completion_text_prefers_message_content(self) -> None:
        text = _extract_chat_completion_text({'choices': [{'message': {'content': [{'type': 'text', 'text': '第一句'}, {'type': 'output_text', 'text': '第二句'}]}}]})
        assert text == '第一句\n第二句'

    def test_extract_responses_text_reads_output_content(self) -> None:
        text = _extract_responses_text({'output': [{'content': [{'type': 'output_text', 'text': '连接成功'}]}]})
        assert text == '连接成功'

    def test_extract_text_helpers_cover_strings_empty_and_top_level_responses(self) -> None:
        assert _extract_chat_completion_text({"choices": [{"message": {"content": "  直接文本  "}}]}) == "直接文本"
        assert _extract_responses_text({"output_text": "  顶层文本  "}) == "顶层文本"
        with pytest.raises(RuntimeError, match="choices"):
            _extract_chat_completion_text({})
        with pytest.raises(RuntimeError, match="内容为空"):
            _extract_chat_completion_text({"choices": [{"message": {"content": []}}]})
        with pytest.raises(RuntimeError, match="内容为空"):
            _extract_responses_text({"output": [{"content": [{"type": "image", "text": "忽略"}]}]})

    def test_extract_json_dict_and_error_classifiers(self) -> None:
        assert protocols._extract_json_dict(SimpleNamespace(json=lambda: {"ok": True})) == {"ok": True}
        assert protocols._extract_json_dict(SimpleNamespace(json=lambda: ["bad"])) == {}

        def _boom():
            raise ValueError("bad json")

        assert protocols._extract_json_dict(SimpleNamespace(json=_boom)) == {}
        assert protocols._is_endpoint_mismatch_error(RuntimeError("405 method not allowed"))
        assert not protocols._is_endpoint_mismatch_error(RuntimeError("quota exceeded"))
        assert protocols._is_ai_timeout_exception(protocols.http_client.Timeout("slow"))

    @pytest.mark.asyncio
    async def test_retry_wrapper_retries_temporary_failure_and_stops_on_permanent_error(self, monkeypatch) -> None:
        async def _no_sleep(_seconds):
            return None

        monkeypatch.setattr(protocols.asyncio, "sleep", _no_sleep)
        calls = 0

        async def _temporary_then_ok():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise protocols.http_client.Timeout("slow")
            return "ok"

        assert await protocols._aexecute_ai_request_with_retry("demo", _temporary_then_ok) == "ok"
        assert calls == 2

        async def _permanent():
            raise ValueError("bad request")

        with pytest.raises(ValueError, match="bad request"):
            await protocols._aexecute_ai_request_with_retry("demo", _permanent)

    @pytest.mark.asyncio
    async def test_ai_calls_build_expected_payloads_and_wrap_failures(self, monkeypatch) -> None:
        captured = []

        class _Response:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        async def _apost(url, **kwargs):
            captured.append((url, kwargs))
            if url.endswith("/chat"):
                return _Response({"choices": [{"message": {"content": "chat ok"}}]})
            return _Response({"output_text": "responses ok"})

        monkeypatch.setattr(protocols.http_client, "apost", _apost)
        assert await protocols.acall_chat_completions("https://api/chat", "k", "m", "问题", "系统") == "chat ok"
        assert await protocols.acall_responses_api("https://api/responses", "k", "m", "问题", "系统") == "responses ok"
        assert captured[0][1]["headers"]["Authorization"] == "Bearer k"
        assert captured[0][1]["json"]["messages"][1]["content"] == "请简短回答这个问卷问题：问题"
        assert captured[1][1]["json"]["input"] == "请简短回答这个问卷问题：问题"

        async def _fail(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(protocols.http_client, "apost", _fail)
        with pytest.raises(RuntimeError, match="API 调用失败"):
            await protocols.acall_chat_completions("https://api/chat", "k", "m", "问题", "系统")

    def test_generate_answer_tries_chat_then_falls_back_to_responses_in_auto_mode(self) -> None:
        import software.integrations.ai.client as client_module
        original_chat = client_module.acall_chat_completions
        original_responses = client_module.acall_responses_api
        save_ai_settings(api_protocol='auto')
        calls: list[str] = []

        async def _fake_chat(*_args, **_kwargs):
            calls.append('chat')
            raise RuntimeError('404 not found')

        async def _fake_responses(*_args, **_kwargs):
            calls.append('responses')
            return '回退成功'
        client_module.acall_chat_completions = _fake_chat
        client_module.acall_responses_api = _fake_responses
        try:
            answer = asyncio.run(
                client_module.agenerate_answer(
                    '测试问题',
                    question_type=FREE_QUESTION_TYPE_FILL,
                    blank_count=1,
                )
            )
        finally:
            client_module.acall_chat_completions = original_chat
            client_module.acall_responses_api = original_responses
        assert answer == '回退成功'
        assert calls == ['chat', 'responses']

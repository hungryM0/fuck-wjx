from __future__ import annotations

import unittest

from software.integrations.ai.client import (
    AI_MODE_PROVIDER,
    FREE_QUESTION_TYPE_FILL,
    generate_answer,
    save_ai_settings,
)
from software.integrations.ai.protocols import (
    _extract_chat_completion_text,
    _extract_responses_text,
    _resolve_custom_endpoint,
)


class AIProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        save_ai_settings(
            ai_mode=AI_MODE_PROVIDER,
            provider="custom",
            api_key="test-key",
            base_url="https://example.com/v1",
            api_protocol="responses",
            model="demo-model",
            system_prompt="测试提示词",
        )

    def test_resolve_custom_endpoint_appends_protocol_suffix(self) -> None:
        protocol, url, explicit = _resolve_custom_endpoint("https://example.com/v1", "responses")

        self.assertEqual(protocol, "responses")
        self.assertEqual(url, "https://example.com/v1/responses")
        self.assertFalse(explicit)

    def test_extract_chat_completion_text_prefers_message_content(self) -> None:
        text = _extract_chat_completion_text(
            {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "text", "text": "第一句"},
                                {"type": "output_text", "text": "第二句"},
                            ]
                        }
                    }
                ]
            }
        )

        self.assertEqual(text, "第一句\n第二句")

    def test_extract_responses_text_reads_output_content(self) -> None:
        text = _extract_responses_text(
            {
                "output": [
                    {
                        "content": [
                            {"type": "output_text", "text": "连接成功"},
                        ]
                    }
                ]
            }
        )

        self.assertEqual(text, "连接成功")

    def test_generate_answer_tries_chat_then_falls_back_to_responses_in_auto_mode(self) -> None:
        import software.integrations.ai.client as client_module

        original_chat = client_module.call_chat_completions
        original_responses = client_module.call_responses_api
        save_ai_settings(api_protocol="auto")
        calls: list[str] = []

        def _fake_chat(*_args, **_kwargs):
            calls.append("chat")
            raise RuntimeError("404 not found")

        def _fake_responses(*_args, **_kwargs):
            calls.append("responses")
            return "回退成功"

        client_module.call_chat_completions = _fake_chat
        client_module.call_responses_api = _fake_responses
        try:
            answer = generate_answer("测试问题", question_type=FREE_QUESTION_TYPE_FILL, blank_count=1)
        finally:
            client_module.call_chat_completions = original_chat
            client_module.call_responses_api = original_responses

        self.assertEqual(answer, "回退成功")
        self.assertEqual(calls, ["chat", "responses"])


if __name__ == "__main__":
    unittest.main()

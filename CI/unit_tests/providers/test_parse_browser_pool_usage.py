from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest

from credamo.provider import parser as credamo_parser


class _FakeDriver:
    def __init__(self, *, html: str = "", title: str = "", payload: dict | None = None) -> None:
        self._html = html
        self._title = title
        self._payload = payload or {}
        self._page = self._FakePage(self)

    class _FakePage:
        def __init__(self, owner: "_FakeDriver") -> None:
            self._owner = owner
            self.url = "https://example.com"
            self.locator_obj = self._FakeLocator()

        class _FakeLocator:
            @property
            def first(self) -> "_FakeDriver._FakePage._FakeLocator":
                return self

            async def text_content(self, _timeout: int = 0) -> str:
                return ""

        async def wait_for_selector(self, *_args, **_kwargs) -> None:
            return None

        async def wait_for_load_state(self, *_args, **_kwargs) -> None:
            return None

        async def evaluate(self, *_args, **_kwargs):
            return self._owner._payload

        async def title(self) -> str:
            return self._owner._title

        def locator(self, _selector: str):
            return self.locator_obj

    async def get(self, url: str, timeout: int = 20000, wait_until: str = "domcontentloaded") -> None:
        _ = url, timeout, wait_until

    async def page(self):
        return self._page

    async def page_source(self) -> str:
        return self._html

    async def title(self) -> str:
        return self._title

    async def current_url(self) -> str:
        return getattr(self._page, "url", "")

    def mark_cleanup_done(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


class ParseBrowserPoolUsageTests:
    @pytest.mark.asyncio
    async def test_credamo_parser_uses_parse_browser_pool(self) -> None:
        used_pool = {"value": False}
        normalized_question = {
            "num": 1,
            "title": "Q1",
            "type_code": "3",
            "question_kind": "single",
            "provider_type": "single",
            "option_texts": ["A"],
            "options": 1,
            "text_inputs": 0,
            "page": 1,
            "question_id": "q1",
        }

        @asynccontextmanager
        async def fake_pool():
            used_pool["value"] = True
            yield _FakeDriver(title="Credamo 标题")

        with patch("credamo.provider.parser.acquire_parse_browser_session", fake_pool), patch("credamo.provider.parser._retry_initial_question_load_if_needed", return_value=[object()]), patch("credamo.provider.parser._collect_current_page_until_stable", return_value=([normalized_question], [normalized_question])), patch("credamo.provider.parser._detect_navigation_action", return_value="submit"):
            info, title = await credamo_parser.parse_credamo_survey("https://www.credamo.com/answer.html#/s/demo")
        assert used_pool["value"]
        assert title == "Credamo 标题"
        assert len(info) == 1

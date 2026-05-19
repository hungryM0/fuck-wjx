from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from wjx.provider import parser as wjx_parser


async def _raise_browser_error(exc: Exception) -> None:
    raise exc


class _FakeHttpResponse:
    def __init__(self, html: str, *, should_raise: Exception | None = None) -> None:
        self.text = html
        self._should_raise = should_raise

    def raise_for_status(self) -> None:
        if self._should_raise is not None:
            raise self._should_raise


class _FakeBrowserDriver:
    def __init__(self, html: str) -> None:
        self._html = html
        self._page = self._FakePage()
        self.get_calls: list[tuple[str, int, str]] = []

    class _FakePage:
        async def wait_for_selector(self, *_args, **_kwargs) -> None:
            return None

        async def wait_for_load_state(self, *_args, **_kwargs) -> None:
            return None

    async def get(self, url: str, timeout: int = 20000, wait_until: str = "domcontentloaded") -> None:
        self.get_calls.append((url, timeout, wait_until))

    async def page(self):
        return self._page

    async def page_source(self) -> str:
        return self._html

    def mark_cleanup_done(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


class WjxParserTests:
    def test_is_paused_survey_page_accepts_pause_copy(self) -> None:
        html = "<html><body>此问卷（123）已暂停，不能填写</body></html>"
        assert wjx_parser.is_paused_survey_page(html)

    def test_is_stopped_survey_page_accepts_work_error_copy(self) -> None:
        html = """
        <html>
          <body>
            <div id="divWorkError">
              <div><div><p>此问卷处于停止状态，无法作答！</p></div></div>
            </div>
          </body>
        </html>
        """
        assert wjx_parser.is_stopped_survey_page(html)

    def test_is_stopped_survey_page_skips_question_content_with_same_copy(self) -> None:
        html = """
        <html>
          <body>
            <div id="divQuestion">
              <fieldset><div topic="1" type="1">为什么此问卷处于停止状态，无法作答？</div></fieldset>
            </div>
          </body>
        </html>
        """
        assert not wjx_parser.is_stopped_survey_page(html)

    def test_is_stopped_survey_page_accepts_div_tip_even_with_questions(self) -> None:
        html = """
        <html>
          <body>
            <div id="divTip">此问卷处于停止状态，无法作答！</div>
            <div id="divQuestion">
              <fieldset><div topic="1" type="3">题目 1</div></fieldset>
            </div>
          </body>
        </html>
        """
        assert wjx_parser.is_stopped_survey_page(html)

    def test_is_enterprise_unavailable_survey_page_accepts_banner_with_questions(self) -> None:
        html = """
        <html>
          <body>
            <div class="banner">问卷发布者还未购买企业标准版或企业标准版已到期，此问卷暂时不能被填写！</div>
            <div id="divQuestion">
              <fieldset><div topic="1" type="3">题目 1</div></fieldset>
            </div>
          </body>
        </html>
        """
        assert wjx_parser.is_enterprise_unavailable_survey_page(html)

    def test_is_enterprise_unavailable_survey_page_skips_plain_question_copy(self) -> None:
        html = """
        <html>
          <body>
            <div id="divQuestion">
              <fieldset><div topic="1" type="1">你是否购买企业标准版？</div></fieldset>
            </div>
          </body>
        </html>
        """
        assert not wjx_parser.is_enterprise_unavailable_survey_page(html)

    def test_build_not_open_survey_message_returns_time_when_gate_page_detected(self) -> None:
        html = """
        <html>
          <body>
            此问卷将于 2026-05-06 09:30 开放
            请到时再进入此页面进行填写
          </body>
        </html>
        """
        assert (
            wjx_parser.build_not_open_survey_message(html)
            == "该问卷暂未开放，无法解析，开放时间：2026-05-06 09:30"
        )

    def test_build_not_open_survey_message_skips_open_question_container(self) -> None:
        html = """
        <html>
          <body>
            <div id="divQuestion">
              <fieldset>
                <div topic="1" type="3">题目 1</div>
              </fieldset>
            </div>
            此问卷将于 2026-05-06 09:30 开放
          </body>
        </html>
        """
        assert wjx_parser.build_not_open_survey_message(html) is None

    @pytest.mark.asyncio
    async def test_parse_wjx_survey_raises_paused_error_from_http_html(self, patch_attrs) -> None:
        patch_attrs(
            (wjx_parser.http_client, "aget", AsyncMock(return_value=_FakeHttpResponse("<html><body>问卷已暂停，不能填写</body></html>"))),
        )

        with pytest.raises(wjx_parser.SurveyPausedError, match="问卷已暂停"):
            await wjx_parser.parse_wjx_survey("https://www.wjx.cn/vm/demo.aspx")

    @pytest.mark.asyncio
    async def test_parse_wjx_survey_raises_stopped_error_from_http_html(self, patch_attrs) -> None:
        html = "<html><body><div id='divWorkError'>此问卷处于停止状态，无法作答！</div></body></html>"
        patch_attrs(
            (wjx_parser.http_client, "aget", AsyncMock(return_value=_FakeHttpResponse(html))),
        )

        with pytest.raises(wjx_parser.SurveyStoppedError, match="问卷已停止"):
            await wjx_parser.parse_wjx_survey("https://www.wjx.cn/vm/demo.aspx")

    @pytest.mark.asyncio
    async def test_parse_wjx_survey_raises_enterprise_unavailable_from_http_html(self, patch_attrs) -> None:
        html = """
        <html><body>
          <div>问卷发布者还未购买企业标准版或企业标准版已到期，此问卷暂时不能被填写！</div>
          <div id="divQuestion"><fieldset><div topic="1" type="3">Q1</div></fieldset></div>
        </body></html>
        """
        patch_attrs(
            (wjx_parser.http_client, "aget", AsyncMock(return_value=_FakeHttpResponse(html))),
        )

        with pytest.raises(wjx_parser.SurveyEnterpriseUnavailableError, match="企业标准版"):
            await wjx_parser.parse_wjx_survey("https://www.wjx.cn/vm/demo.aspx")

    @pytest.mark.asyncio
    async def test_parse_wjx_survey_raises_not_open_error_from_http_html(self, patch_attrs) -> None:
        html = "<html><body>此问卷将于 2026-05-06 09:30 开放，请到时再进入此页面进行填写</body></html>"
        patch_attrs(
            (wjx_parser.http_client, "aget", AsyncMock(return_value=_FakeHttpResponse(html))),
        )

        with pytest.raises(wjx_parser.SurveyNotOpenError, match="开放时间：2026-05-06 09:30"):
            await wjx_parser.parse_wjx_survey("https://www.wjx.cn/vm/demo.aspx")

    @pytest.mark.asyncio
    async def test_parse_wjx_survey_returns_http_parse_result_without_browser_fallback(self, patch_attrs) -> None:
        browser_used = {"value": False}
        aget = AsyncMock(return_value=_FakeHttpResponse("<html><body>ok</body></html>"))

        @asynccontextmanager
        async def fake_pool():
            browser_used["value"] = True
            yield _FakeBrowserDriver("<html></html>")

        patch_attrs(
            (wjx_parser.http_client, "aget", aget),
            (wjx_parser, "parse_survey_questions_from_html", lambda _html: [{"num": 1, "title": "Q1", "type_code": "3"}]),
            (wjx_parser, "extract_survey_title_from_html", lambda _html: "  标题  "),
            (wjx_parser, "acquire_parse_browser_session", fake_pool),
        )

        info, title = await wjx_parser.parse_wjx_survey("https://www.wjx.cn/vm/demo.aspx")

        assert info == [{"num": 1, "title": "Q1", "type_code": "3"}]
        assert title == "标题"
        assert not browser_used["value"]
        assert aget.await_args.kwargs.get("proxies") == {}

    @pytest.mark.asyncio
    async def test_parse_wjx_survey_does_not_fall_back_to_browser_when_http_parse_result_is_empty(self, patch_attrs) -> None:
        browser_used = {"value": False}

        @asynccontextmanager
        async def fake_pool():
            browser_used["value"] = True
            yield _FakeBrowserDriver("<html><body>browser-ok</body></html>")

        patch_attrs(
            (wjx_parser.http_client, "aget", AsyncMock(return_value=_FakeHttpResponse("<html><body>http-empty</body></html>"))),
            (wjx_parser, "parse_survey_questions_from_html", lambda _html: []),
            (wjx_parser, "extract_survey_title_from_html", lambda _html: "HTTP 标题"),
            (wjx_parser, "acquire_parse_browser_session", fake_pool),
        )

        with pytest.raises(RuntimeError, match="无法打开问卷链接"):
            await wjx_parser.parse_wjx_survey("https://www.wjx.cn/vm/demo.aspx")

        assert not browser_used["value"]

    @pytest.mark.asyncio
    async def test_parse_wjx_survey_keeps_http_fast_path_even_when_static_page_has_hidden_questions(self, patch_attrs) -> None:
        static_html = """
        <html><body>
          <div id="divQuestion">
            <fieldset>
              <div id="div20" topic="20" type="5" style="display:none;"><div class="topicnumber">20.</div></div>
              <div id="div23" topic="23" type="2"><div class="topicnumber">23.</div></div>
            </fieldset>
          </div>
        </body></html>
        """
        browser_used = {"value": False}

        @asynccontextmanager
        async def fake_pool():
            browser_used["value"] = True
            yield _FakeBrowserDriver("<html></html>")

        patch_attrs(
            (wjx_parser.http_client, "aget", AsyncMock(return_value=_FakeHttpResponse(static_html))),
            (wjx_parser, "parse_survey_questions_from_html", lambda _html: [{"num": 23, "display_num": 22, "title": "Q23", "type_code": "2"}]),
            (wjx_parser, "extract_survey_title_from_html", lambda _html: "标题"),
            (wjx_parser, "acquire_parse_browser_session", fake_pool),
        )

        info, title = await wjx_parser.parse_wjx_survey("https://www.wjx.cn/vm/demo.aspx")

        assert info == [{"num": 23, "display_num": 22, "title": "Q23", "type_code": "2"}]
        assert title == "标题"
        assert not browser_used["value"]

    @pytest.mark.asyncio
    async def test_parse_wjx_survey_skips_browser_fallback_for_paused_gate_page(self, patch_attrs) -> None:
        browser_used = {"value": False}

        @asynccontextmanager
        async def fake_pool():
            browser_used["value"] = True
            yield _FakeBrowserDriver("<html></html>")

        patch_attrs(
            (wjx_parser.http_client, "aget", AsyncMock(return_value=_FakeHttpResponse("<html><body>问卷已暂停，不能填写</body></html>"))),
            (wjx_parser, "acquire_parse_browser_session", fake_pool),
        )

        with pytest.raises(wjx_parser.SurveyPausedError, match="问卷已暂停"):
            await wjx_parser.parse_wjx_survey("https://www.wjx.cn/vm/demo.aspx")

        assert not browser_used["value"]

    @pytest.mark.asyncio
    async def test_parse_wjx_survey_raises_combined_environment_message(self, patch_attrs) -> None:
        http_exc = OSError("socket blocked")
        http_exc.winerror = 10013
        browser_exc = RuntimeError("playwright blocked")

        @asynccontextmanager
        async def fake_pool_with_error():
            await _raise_browser_error(browser_exc)
            yield

        patch_attrs(
            (wjx_parser.http_client, "aget", AsyncMock(side_effect=http_exc)),
            (wjx_parser, "acquire_parse_browser_session", fake_pool_with_error),
            (wjx_parser, "is_playwright_startup_environment_error", lambda exc: exc is browser_exc),
            (wjx_parser, "describe_playwright_startup_error", lambda _exc: "不该走到这里"),
        )

        with pytest.raises(RuntimeError, match="WinError 10013"):
            await wjx_parser.parse_wjx_survey("https://www.wjx.cn/vm/demo.aspx")

    @pytest.mark.asyncio
    async def test_parse_wjx_survey_uses_browser_fallback_message_when_http_error_is_plain(self, patch_attrs) -> None:
        http_exc = RuntimeError("http failed")
        browser_exc = RuntimeError("browser failed")

        @asynccontextmanager
        async def fake_pool():
            await _raise_browser_error(browser_exc)
            yield

        patch_attrs(
            (wjx_parser.http_client, "aget", AsyncMock(side_effect=http_exc)),
            (wjx_parser, "acquire_parse_browser_session", fake_pool),
            (wjx_parser, "is_playwright_startup_environment_error", lambda exc: False),
        )

        with pytest.raises(RuntimeError, match="无法获取问卷网页：http failed"):
            await wjx_parser.parse_wjx_survey("https://www.wjx.cn/vm/demo.aspx")

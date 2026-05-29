from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from software.core.task import ExecutionConfig, ExecutionState
from software.providers import registry
from software.providers.common import SURVEY_PROVIDER_CREDAMO, SURVEY_PROVIDER_QQ, SURVEY_PROVIDER_WJX
from software.providers.contracts import SurveyDefinition
from software.providers.hooks import build_fill_http_hook, build_parse_hook


async def test_parse_survey_routes_detected_provider_directly() -> None:
    qq_url = "https://wj.qq.com/s2/123/demo"
    adapter = SimpleNamespace(parse_survey_async=AsyncMock(return_value="qq-definition"))

    with patch.object(registry, "_get_provider_adapter", return_value=adapter):
        result = await registry.parse_survey(qq_url)

    assert result == "qq-definition"
    adapter.parse_survey_async.assert_awaited_once_with(qq_url)


async def test_parse_survey_normalizes_credamo_short_url_before_dispatch() -> None:
    short_url = "https://www.credamo.com/s/demo/"
    normalized_url = "https://www.credamo.com/answer.html#/s/demo/"
    adapter = SimpleNamespace(parse_survey_async=AsyncMock(return_value="credamo-definition"))

    with patch.object(registry, "_get_provider_adapter", return_value=adapter) as adapter_mock:
        result = await registry.parse_survey(short_url)

    assert result == "credamo-definition"
    adapter_mock.assert_called_once_with(url=normalized_url)
    adapter.parse_survey_async.assert_awaited_once_with(normalized_url)


async def test_fill_survey_uses_provider_run_context_and_selected_adapter() -> None:
    state = ExecutionState(config=ExecutionConfig(survey_provider=SURVEY_PROVIDER_WJX))
    status_updates: list[tuple[str, bool]] = []

    def _capture_update_thread_status(thread_name: str, status_text: str, *, running: bool | None = None) -> None:
        del thread_name
        status_updates.append((status_text, bool(running)))

    state.update_thread_status = _capture_update_thread_status
    adapter = registry._PROVIDER_REGISTRY[SURVEY_PROVIDER_WJX]

    @contextmanager
    def fake_provider_run_context(*_args, **_kwargs):
        yield "resolved-plan"

    with (
        patch.object(adapter, "fill_survey_async", new=AsyncMock(return_value=True)) as fill_mock,
        patch.object(registry, "provider_run_context", fake_provider_run_context),
    ):
        result = await registry.fill_survey(
            object(),
            ExecutionConfig(survey_provider=SURVEY_PROVIDER_WJX),
            state,
            stop_signal="stop",
            thread_name="Worker-1",
            psycho_plan="ignored-plan",
            provider=SURVEY_PROVIDER_WJX,
        )

    assert result is True
    assert status_updates == [("识别题目", True)]
    assert fill_mock.await_args.kwargs["psycho_plan"] == "resolved-plan"


async def test_fill_survey_http_routes_credamo_adapter() -> None:
    state = ExecutionState(config=ExecutionConfig(survey_provider=SURVEY_PROVIDER_CREDAMO))
    adapter = registry._PROVIDER_REGISTRY[SURVEY_PROVIDER_CREDAMO]

    @contextmanager
    def fake_provider_run_context(*_args, **_kwargs):
        yield "resolved-plan"

    with (
        patch.object(adapter, "fill_survey_http_async", new=AsyncMock(return_value=True)) as fill_mock,
        patch.object(registry, "provider_run_context", fake_provider_run_context),
    ):
        result = await registry.fill_survey_http(
            ExecutionConfig(survey_provider=SURVEY_PROVIDER_CREDAMO),
            state,
            stop_signal="stop",
            thread_name="Worker-1",
            psycho_plan="ignored-plan",
            provider=SURVEY_PROVIDER_CREDAMO,
            proxy_address="http://1.1.1.1:80",
            user_agent="UA",
        )

    assert result is True
    assert fill_mock.await_args.kwargs["psycho_plan"] == "resolved-plan"
    assert fill_mock.await_args.kwargs["proxy_address"] == "http://1.1.1.1:80"
    assert fill_mock.await_args.kwargs["user_agent"] == "UA"


async def test_wjx_fill_survey_browser_entry_is_removed() -> None:
    state = ExecutionState(config=ExecutionConfig(survey_provider=SURVEY_PROVIDER_WJX))

    try:
        await registry.fill_survey(
            object(),
            ExecutionConfig(survey_provider=SURVEY_PROVIDER_WJX),
            state,
            provider=SURVEY_PROVIDER_WJX,
        )
    except RuntimeError as exc:
        assert "纯 HTTP 提交链路" in str(exc)
    else:
        raise AssertionError("问卷星不应继续暴露浏览器填答入口")


async def test_qq_fill_survey_browser_entry_is_removed() -> None:
    state = ExecutionState(config=ExecutionConfig(survey_provider=SURVEY_PROVIDER_QQ))

    try:
        await registry.fill_survey(
            object(),
            ExecutionConfig(survey_provider=SURVEY_PROVIDER_QQ),
            state,
            provider=SURVEY_PROVIDER_QQ,
        )
    except RuntimeError as exc:
        assert "纯 HTTP 提交链路" in str(exc)
    else:
        raise AssertionError("腾讯问卷不应继续暴露浏览器填答入口")


async def test_handle_submission_verification_detected_uses_ctx_config_provider() -> None:
    ctx = SimpleNamespace(config=SimpleNamespace(survey_provider=SURVEY_PROVIDER_CREDAMO))
    adapter = registry._PROVIDER_REGISTRY[SURVEY_PROVIDER_CREDAMO]

    with patch.object(adapter, "handle_submission_verification_detected_async", new=AsyncMock()) as handler_mock:
        await registry.handle_submission_verification_detected(ctx, "stop")

    handler_mock.assert_awaited_once_with(ctx, "stop")


async def test_wait_for_submission_verification_routes_timeout_and_stop_signal() -> None:
    adapter = registry._PROVIDER_REGISTRY[SURVEY_PROVIDER_QQ]
    driver = object()

    with patch.object(adapter, "wait_for_submission_verification_async", new=AsyncMock(return_value=True)) as wait_mock:
        result = await registry.wait_for_submission_verification(
            driver,
            provider=SURVEY_PROVIDER_QQ,
            timeout=9,
            stop_signal="stop",
        )

    assert result is True
    wait_mock.assert_awaited_once_with(driver, timeout=9, stop_signal="stop")


async def test_attempt_submission_recovery_routes_to_selected_provider() -> None:
    adapter = registry._PROVIDER_REGISTRY[SURVEY_PROVIDER_CREDAMO]
    driver = object()
    ctx = object()

    with patch.object(adapter, "attempt_submission_recovery_async", new=AsyncMock(return_value=True)) as recovery_mock:
        result = await registry.attempt_submission_recovery(
            driver,
            ctx,
            "gui",
            "stop",
            provider=SURVEY_PROVIDER_CREDAMO,
            thread_name="Worker-7",
        )

    assert result is True
    recovery_mock.assert_awaited_once_with(driver, ctx, "gui", "stop", thread_name="Worker-7")


async def test_provider_hook_rejects_non_async_return_value() -> None:
    with patch("software.providers.hooks._load_hook", return_value=lambda *_args, **_kwargs: True):
        hook = build_fill_http_hook(("fake.module", "sync_http_fill"))
        try:
            await hook(ExecutionConfig(), ExecutionState())
        except TypeError as exc:
            assert "provider hook 必须返回 awaitable" in str(exc)
        else:
            raise AssertionError("同步 provider hook 不应再被接受")


async def test_parse_hook_normalizes_tuple_result_to_survey_definition() -> None:
    async def fake_parse(_url: str):
        return ([{"num": 1, "title": "Q1", "type_code": "3"}], "  标题  ")

    with patch("software.providers.hooks._load_hook", return_value=fake_parse):
        hook = build_parse_hook(SURVEY_PROVIDER_QQ, ("fake.module", "parse"))
        definition = await hook("https://wj.qq.com/s2/demo")

    assert isinstance(definition, SurveyDefinition)
    assert definition.provider == SURVEY_PROVIDER_QQ
    assert definition.title == "标题"
    assert definition.questions[0].provider == SURVEY_PROVIDER_QQ


async def test_parse_hook_rejects_sync_parser_result() -> None:
    with patch("software.providers.hooks._load_hook", return_value=lambda _url: ([], "标题")):
        hook = build_parse_hook(SURVEY_PROVIDER_WJX, ("fake.module", "parse"))
        try:
            await hook("https://www.wjx.cn/vm/demo.aspx")
        except TypeError as exc:
            assert "解析 hook 必须返回 awaitable" in str(exc)
        else:
            raise AssertionError("同步解析 hook 不应再被接受")

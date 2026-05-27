from __future__ import annotations

import os
import tempfile
import threading
import time
from unittest.mock import AsyncMock

import pytest

import software.providers.survey_cache as survey_cache
from software.providers.contracts import build_survey_definition
from software.providers.survey_cache import parse_survey_with_cache


def _async_parser(result_builder):
    async def _runner(url: str):
        return result_builder(url)

    return _runner


class SurveyCacheTests:
    def _patch_cache_directory(self, temp_dir: str):
        original_cache_directory = survey_cache.get_user_cache_directory
        survey_cache.get_user_cache_directory = lambda: temp_dir
        return original_cache_directory

    def teardown_method(self, _method) -> None:
        survey_cache.clear_survey_parse_cache()

    @pytest.mark.asyncio
    async def test_same_fingerprint_reuses_cached_definition(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            calls: list[str] = []
            original_runtime_directory = self._patch_cache_directory(temp_dir)
            original_fetch_fingerprint = survey_cache._fetch_remote_fingerprint

            async def parser(url: str):
                calls.append(url)
                return build_survey_definition("wjx", "旧标题", [{"num": 1, "title": "旧题目", "type_code": "3"}])

            try:
                survey_cache._fetch_remote_fingerprint = lambda url, provider: "same"
                first = await parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
                second = await parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
            finally:
                survey_cache.get_user_cache_directory = original_runtime_directory
                survey_cache._fetch_remote_fingerprint = original_fetch_fingerprint
            assert len(calls) == 1
            assert first.title == "旧标题"
            assert second.title == "旧标题"
            assert second.questions[0]["title"] == "旧题目"
            assert os.path.isdir(os.path.join(temp_dir, "survey_cache"))

    @pytest.mark.asyncio
    async def test_credamo_url_fragment_is_preserved_for_parser(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            seen_urls: list[str] = []
            original_runtime_directory = self._patch_cache_directory(temp_dir)

            async def parser(url: str):
                seen_urls.append(url)
                return build_survey_definition("credamo", "见数标题", [{"num": 1, "title": "见数题目", "type_code": "3"}])

            try:
                await parse_survey_with_cache("https://www.credamo.com/answer.html#/s/Bvyyaaano/", parser)
            finally:
                survey_cache.get_user_cache_directory = original_runtime_directory
            assert seen_urls == ["https://www.credamo.com/answer.html#/s/Bvyyaaano/"]

    @pytest.mark.asyncio
    async def test_credamo_short_url_is_canonicalized_for_parser(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            seen_urls: list[str] = []
            original_runtime_directory = self._patch_cache_directory(temp_dir)

            async def parser(url: str):
                seen_urls.append(url)
                return build_survey_definition("credamo", "见数标题", [{"num": 1, "title": "见数题目", "type_code": "3"}])

            try:
                await parse_survey_with_cache("https://www.credamo.com/s/Bvyyaaano/", parser)
            finally:
                survey_cache.get_user_cache_directory = original_runtime_directory
            assert seen_urls == ["https://www.credamo.com/answer.html#/s/Bvyyaaano/"]

    @pytest.mark.asyncio
    async def test_changed_fingerprint_refreshes_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fingerprints = ["old", "new", "new"]
            titles = ["旧标题", "新标题"]
            original_runtime_directory = self._patch_cache_directory(temp_dir)
            original_fetch_fingerprint = survey_cache._fetch_remote_fingerprint
            original_now = survey_cache._now
            now_values = [1000, 1000 + survey_cache._SURVEY_PARSE_CACHE_TTL_SECONDS + 1, 2000, 2000]

            async def parser(_url: str):
                title = titles.pop(0)
                return build_survey_definition("wjx", title, [{"num": 1, "title": title, "type_code": "3"}])

            def next_fingerprint(_url: str, _provider: str) -> str:
                return fingerprints.pop(0)

            try:
                survey_cache._fetch_remote_fingerprint = next_fingerprint
                survey_cache._now = lambda: now_values.pop(0)
                first = await parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
                second = await parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
            finally:
                survey_cache.get_user_cache_directory = original_runtime_directory
                survey_cache._fetch_remote_fingerprint = original_fetch_fingerprint
                survey_cache._now = original_now
            assert first.title == "旧标题"
            assert second.title == "新标题"
            assert titles == []

    @pytest.mark.asyncio
    async def test_parser_failure_does_not_poison_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            calls = 0
            original_runtime_directory = self._patch_cache_directory(temp_dir)

            async def parser(_url: str):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("parse failed")
                return build_survey_definition(
                    "wjx",
                    "恢复标题",
                    [{"num": 1, "title": "恢复题目", "type_code": "3"}],
                )

            try:
                with pytest.raises(RuntimeError):
                    await parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
                result = await parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
            finally:
                survey_cache.get_user_cache_directory = original_runtime_directory

            assert calls == 2
            assert result.title == "恢复标题"

    @pytest.mark.asyncio
    async def test_credamo_reuses_cache_within_short_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            calls: list[str] = []
            original_runtime_directory = self._patch_cache_directory(temp_dir)

            async def parser(url: str):
                calls.append(url)
                return build_survey_definition("credamo", "见数标题", [{"num": 1, "title": "见数题目", "type_code": "3"}])

            try:
                first = await parse_survey_with_cache("https://www.credamo.com/answer.html#/s/demo", parser)
                second = await parse_survey_with_cache("https://www.credamo.com/answer.html#/s/demo", parser)
            finally:
                survey_cache.get_user_cache_directory = original_runtime_directory
            assert len(calls) == 1
            assert first.title == "见数标题"
            assert second.title == "见数标题"

    @pytest.mark.asyncio
    async def test_credamo_short_url_and_redirect_url_share_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            calls: list[str] = []
            original_runtime_directory = self._patch_cache_directory(temp_dir)

            async def parser(url: str):
                calls.append(url)
                return build_survey_definition("credamo", "见数标题", [{"num": 1, "title": "见数题目", "type_code": "3"}])

            try:
                first = await parse_survey_with_cache("https://www.credamo.com/s/demo", parser)
                second = await parse_survey_with_cache("https://www.credamo.com/answer.html#/s/demo", parser)
            finally:
                survey_cache.get_user_cache_directory = original_runtime_directory
            assert len(calls) == 1
            assert first.title == "见数标题"
            assert second.title == "见数标题"

    @pytest.mark.asyncio
    async def test_credamo_refreshes_after_short_ttl_expires(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_directory = self._patch_cache_directory(temp_dir)
            original_now = survey_cache._now
            now_values = [1000, 1000 + survey_cache._CREDAMO_TTL_SECONDS + 1, 2000]
            titles = ["旧见数", "新见数"]

            async def parser(_url: str):
                title = titles.pop(0)
                return build_survey_definition("credamo", title, [{"num": 1, "title": title, "type_code": "3"}])

            try:
                survey_cache._now = lambda: now_values.pop(0)
                first = await parse_survey_with_cache("https://www.credamo.com/answer.html#/s/demo", parser)
                second = await parse_survey_with_cache("https://www.credamo.com/answer.html#/s/demo", parser)
            finally:
                survey_cache.get_user_cache_directory = original_runtime_directory
                survey_cache._now = original_now
            assert first.title == "旧见数"
            assert second.title == "新见数"
            assert titles == []

    @pytest.mark.asyncio
    async def test_remote_fingerprint_unavailable_reuses_recent_cache_temporarily(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            calls: list[str] = []
            original_runtime_directory = self._patch_cache_directory(temp_dir)
            original_fetch_fingerprint = survey_cache._fetch_remote_fingerprint
            original_now = survey_cache._now
            now_values = [1000, 1005]

            async def parser(url: str):
                calls.append(url)
                return build_survey_definition("wjx", "旧标题", [{"num": 1, "title": "旧题目", "type_code": "3"}])

            try:
                survey_cache._fetch_remote_fingerprint = lambda url, provider: "same" if len(calls) == 0 else None
                survey_cache._now = lambda: now_values.pop(0)
                first = await parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
                second = await parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
            finally:
                survey_cache.get_user_cache_directory = original_runtime_directory
                survey_cache._fetch_remote_fingerprint = original_fetch_fingerprint
                survey_cache._now = original_now
            assert len(calls) == 1
            assert first.title == "旧标题"
            assert second.title == "旧标题"

    @pytest.mark.asyncio
    async def test_recent_wjx_cache_hit_still_checks_remote_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            calls: list[str] = []
            fingerprint_calls: list[str] = []
            original_runtime_directory = self._patch_cache_directory(temp_dir)
            original_fetch_fingerprint = survey_cache._fetch_remote_fingerprint
            original_now = survey_cache._now
            now_values = [1000, 1005]

            async def parser(url: str):
                calls.append(url)
                return build_survey_definition("wjx", "缓存标题", [{"num": 1, "title": "缓存题目", "type_code": "3"}])

            def fingerprint(url: str, _provider: str) -> str:
                fingerprint_calls.append(url)
                return "same"

            try:
                survey_cache._fetch_remote_fingerprint = fingerprint
                survey_cache._now = lambda: now_values.pop(0)
                first = await parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
                second = await parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
            finally:
                survey_cache.get_user_cache_directory = original_runtime_directory
                survey_cache._fetch_remote_fingerprint = original_fetch_fingerprint
                survey_cache._now = original_now
            assert len(calls) == 1
            assert len(fingerprint_calls) == 2
            assert first.title == "缓存标题"
            assert second.title == "缓存标题"

    @pytest.mark.asyncio
    async def test_recent_credamo_cache_hit_does_not_fetch_remote_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            calls: list[str] = []
            fingerprint_calls: list[str] = []
            original_runtime_directory = self._patch_cache_directory(temp_dir)
            original_fetch_fingerprint = survey_cache._fetch_remote_fingerprint
            original_now = survey_cache._now
            now_values = [1000, 1005]

            async def parser(url: str):
                calls.append(url)
                return build_survey_definition("credamo", "缓存标题", [{"num": 1, "title": "缓存题目", "type_code": "3"}])

            def fingerprint(url: str, _provider: str) -> str:
                fingerprint_calls.append(url)
                return "same"

            try:
                survey_cache._fetch_remote_fingerprint = fingerprint
                survey_cache._now = lambda: now_values.pop(0)
                first = await parse_survey_with_cache("https://www.credamo.com/answer.html#/s/demo", parser)
                second = await parse_survey_with_cache("https://www.credamo.com/answer.html#/s/demo", parser)
            finally:
                survey_cache.get_user_cache_directory = original_runtime_directory
                survey_cache._fetch_remote_fingerprint = original_fetch_fingerprint
                survey_cache._now = original_now
            assert len(calls) == 1
            assert len(fingerprint_calls) == 0
            assert first.title == "缓存标题"
            assert second.title == "缓存标题"

    def test_clear_survey_parse_cache_removes_cached_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_directory = self._patch_cache_directory(temp_dir)
            cache_dir = os.path.join(temp_dir, "survey_cache")
            os.makedirs(os.path.join(cache_dir, "nested"), exist_ok=True)
            with open(os.path.join(cache_dir, "cache.json"), "w", encoding="utf-8") as file:
                file.write("{}")
            with open(os.path.join(cache_dir, "nested", "orphan.txt"), "w", encoding="utf-8") as file:
                file.write("x")
            try:
                removed_count = survey_cache.clear_survey_parse_cache()
            finally:
                survey_cache.get_user_cache_directory = original_runtime_directory
            assert removed_count == 2
            assert os.listdir(cache_dir) == []

    def test_clear_survey_parse_cache_blocks_late_background_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_directory = self._patch_cache_directory(temp_dir)
            cache_dir = os.path.join(temp_dir, "survey_cache")
            os.makedirs(cache_dir, exist_ok=True)
            cache_path = os.path.join(cache_dir, "stale.json")
            wrote_attempt = threading.Event()
            try:
                epoch_before_clear = survey_cache._cache_clear_epoch_snapshot()
                survey_cache.clear_survey_parse_cache()
                survey_cache._write_cached_definition(
                    cache_path,
                    build_survey_definition("wjx", "标题", [{"num": 1, "title": "Q1", "type_code": "3"}]),
                    "fingerprint",
                    expected_epoch=epoch_before_clear,
                )
                wrote_attempt.set()
            finally:
                survey_cache.get_user_cache_directory = original_runtime_directory
            assert wrote_attempt.is_set()
            assert not os.path.exists(cache_path)

    def test_same_url_concurrent_requests_share_singleflight_parse(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_directory = self._patch_cache_directory(temp_dir)
            original_fetch_fingerprint = survey_cache._fetch_remote_fingerprint
            call_count = 0
            call_lock = threading.Lock()
            results: list[str] = []
            start_event = threading.Event()
            errors: list[BaseException] = []

            async def parser(url: str):
                nonlocal call_count
                with call_lock:
                    call_count += 1
                start_event.wait(timeout=1)
                time.sleep(0.05)
                return build_survey_definition("wjx", "并发标题", [{"num": 1, "title": url, "type_code": "3"}])

            def worker() -> None:
                try:
                    definition = asyncio.run(parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser))
                    results.append(definition.title)
                except BaseException as exc:
                    errors.append(exc)

            import asyncio

            threads = [threading.Thread(target=worker) for _ in range(5)]
            try:
                survey_cache._fetch_remote_fingerprint = lambda url, provider: None
                for thread in threads:
                    thread.start()
                time.sleep(0.05)
                start_event.set()
                for thread in threads:
                    thread.join(timeout=5)
            finally:
                survey_cache.get_user_cache_directory = original_runtime_directory
                survey_cache._fetch_remote_fingerprint = original_fetch_fingerprint
            assert errors == []
            assert call_count == 1
            assert results == ["并发标题"] * 5

    @pytest.mark.asyncio
    async def test_stale_cache_refreshes_immediately_when_fingerprint_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_directory = self._patch_cache_directory(temp_dir)
            original_fetch_fingerprint = survey_cache._fetch_remote_fingerprint
            original_now = survey_cache._now
            now_values = [1000, 1000 + survey_cache._SURVEY_PARSE_CACHE_TTL_SECONDS + 10]
            titles = ["旧标题", "新标题"]
            parser_calls: list[str] = []

            async def parser(url: str):
                parser_calls.append(url)
                title = titles.pop(0)
                return build_survey_definition("wjx", title, [{"num": 1, "title": title, "type_code": "3"}])

            fingerprint_calls = iter(["old", "changed", "changed"])
            try:
                survey_cache._now = (
                    lambda: now_values.pop(0) if now_values else 1000 + survey_cache._SURVEY_PARSE_CACHE_TTL_SECONDS + 20
                )
                survey_cache._fetch_remote_fingerprint = lambda url, provider: next(fingerprint_calls, "changed")
                first = await parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
                second = await parse_survey_with_cache("https://www.wjx.cn/vm/demo.aspx", parser)
            finally:
                survey_cache.get_user_cache_directory = original_runtime_directory
                survey_cache._fetch_remote_fingerprint = original_fetch_fingerprint
                survey_cache._now = original_now
            assert first.title == "旧标题"
            assert second.title == "新标题"
            assert len(parser_calls) == 2

    @pytest.mark.asyncio
    async def test_fetch_json_fingerprint_bypasses_environment_proxy(self, patch_attrs) -> None:
        response = type("Resp", (), {"raise_for_status": lambda self: None, "json": lambda self: {"ok": True}})()
        aget = AsyncMock(return_value=response)
        patch_attrs((survey_cache.http_client, "aget", aget))

        fingerprint = await survey_cache._fetch_json_fingerprint("https://wj.qq.com/api/demo", params={"a": 1}, headers={"x": "y"})

        assert fingerprint
        assert aget.await_args.kwargs.get("proxies") == {}

    @pytest.mark.asyncio
    async def test_html_fingerprint_bypasses_environment_proxy(self, patch_attrs) -> None:
        response = type("Resp", (), {"text": "<html>ok</html>", "raise_for_status": lambda self: None})()
        aget = AsyncMock(return_value=response)
        patch_attrs((survey_cache.http_client, "aget", aget))

        fingerprint = await survey_cache._html_fingerprint("https://www.wjx.cn/vm/demo.aspx")

        assert fingerprint
        assert aget.await_args.kwargs.get("proxies") == {}

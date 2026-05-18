"""问卷解析结果缓存。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
import asyncio
import inspect
from dataclasses import asdict
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from software.app.config import DEFAULT_HTTP_HEADERS
from software.app.user_paths import get_user_cache_directory
from software.providers.common import (
    SURVEY_PROVIDER_CREDAMO,
    SURVEY_PROVIDER_QQ,
    SURVEY_PROVIDER_WJX,
    detect_survey_provider,
)
from software.providers.contracts import SurveyDefinition, build_survey_definition
import software.network.http as http_client


_CACHE_VERSION = 2
_CACHE_DIR_NAME = "survey_cache"
_SURVEY_PARSE_CACHE_TTL_SECONDS = 5 * 60
_FALLBACK_TTL_SECONDS = _SURVEY_PARSE_CACHE_TTL_SECONDS
_CREDAMO_TTL_SECONDS = _SURVEY_PARSE_CACHE_TTL_SECONDS
_STALE_WHILE_REVALIDATE_MAX_SECONDS = 24 * 60 * 60
_REGISTRY_LOCK = threading.RLock()
_CACHE_CLEAR_EPOCH = 0


class _InflightEntry:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: Optional[SurveyDefinition] = None
        self.error: Optional[BaseException] = None


_INFLIGHT_BY_URL: dict[str, _InflightEntry] = {}
_REFRESH_IN_PROGRESS: set[str] = set()
_REFRESH_THREADS: set[threading.Thread] = set()


def _now() -> float:
    return time.time()


def _cache_clear_epoch_snapshot() -> int:
    with _REGISTRY_LOCK:
        return int(_CACHE_CLEAR_EPOCH)


def _bump_cache_clear_epoch() -> int:
    global _CACHE_CLEAR_EPOCH
    with _REGISTRY_LOCK:
        _CACHE_CLEAR_EPOCH += 1
        return int(_CACHE_CLEAR_EPOCH)


def _normalize_credamo_url_parts(
    scheme: str,
    netloc: str,
    path: str,
    query: str,
    fragment: str,
) -> tuple[str, str, str, str, str]:
    normalized_path = str(path or "")
    normalized_fragment = str(fragment or "")
    if detect_survey_provider(urlunsplit((scheme, netloc, normalized_path, query, normalized_fragment)), default="") != SURVEY_PROVIDER_CREDAMO:
        return scheme, netloc, normalized_path, query, normalized_fragment

    if normalized_path.lower().startswith("/s/") and not normalized_fragment:
        normalized_fragment = normalized_path
        normalized_path = "/answer.html"
    return scheme, netloc, normalized_path, query, normalized_fragment


def _normalize_cache_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    candidate = text if "://" in text else f"https://{text}"
    try:
        parsed = urlsplit(candidate)
    except Exception:
        return text
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or ""
    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.startswith("_")
    ]
    query = urlencode(sorted(query_items), doseq=True)
    scheme, netloc, path, query, fragment = _normalize_credamo_url_parts(
        scheme,
        netloc,
        path,
        query,
        parsed.fragment or "",
    )
    return urlunsplit((scheme, netloc, path, query, fragment))


def _cache_key(url: str) -> str:
    normalized = _normalize_cache_url(url)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _cache_directory() -> str:
    return os.path.join(get_user_cache_directory(), _CACHE_DIR_NAME)


def _cache_path(url: str) -> str:
    return os.path.join(_cache_directory(), f"{_cache_key(url)}.json")


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="ignore")).hexdigest()


def _hash_json(value: Any) -> str:
    return _hash_text(_stable_json(value))


async def _fetch_json_fingerprint(url: str, *, params: dict[str, Any], headers: dict[str, str]) -> Optional[str]:
    response = await http_client.aget(url, params=params, timeout=8, headers=headers, proxies={})
    response.raise_for_status()
    return _hash_json(response.json())


async def _qq_fingerprint(url: str) -> Optional[str]:
    parsed = urlsplit(str(url or "").strip())
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 3:
        return None
    survey_id = segments[1]
    hash_value = segments[2]
    headers = {
        **DEFAULT_HTTP_HEADERS,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://wj.qq.com",
        "Referer": url,
    }
    params = {
        "_": str(int(time.time() * 1000)),
        "hash": hash_value,
        "locale": "zhs",
    }
    fingerprints: list[str] = []
    for endpoint in ("meta", "questions"):
        api_url = f"https://wj.qq.com/api/v2/respondent/surveys/{survey_id}/{endpoint}"
        fingerprint = await _fetch_json_fingerprint(api_url, params=params, headers=headers)
        if fingerprint:
            fingerprints.append(f"{endpoint}:{fingerprint}")
    return _hash_text("|".join(fingerprints)) if fingerprints else None


async def _html_fingerprint(url: str) -> Optional[str]:
    response = await http_client.aget(url, timeout=10, headers=DEFAULT_HTTP_HEADERS, proxies={})
    response.raise_for_status()
    return _hash_text(response.text)


async def _fetch_remote_fingerprint(url: str, provider: str) -> Optional[str]:
    try:
        if provider == SURVEY_PROVIDER_QQ:
            return await _qq_fingerprint(url)
        if provider == SURVEY_PROVIDER_WJX:
            return await _html_fingerprint(url)
    except Exception as exc:
        logging.info("获取问卷缓存指纹失败，url=%r provider=%s：%s", url, provider, exc)
    return None


def _ttl_only_cache_seconds(provider: str) -> Optional[int]:
    if provider == SURVEY_PROVIDER_CREDAMO:
        return _CREDAMO_TTL_SECONDS
    return None


def _load_cached_definition(path: str) -> Optional[tuple[SurveyDefinition, str, float]]:
    try:
        with open(path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except FileNotFoundError:
        return None
    except Exception as exc:
        logging.info("读取问卷解析缓存失败，path=%r：%s", path, exc)
        return None

    if not isinstance(payload, dict) or payload.get("version") != _CACHE_VERSION:
        return None
    definition_payload = payload.get("definition")
    if not isinstance(definition_payload, dict):
        return None
    questions = definition_payload.get("questions")
    if not isinstance(questions, list):
        return None
    definition = build_survey_definition(
        str(definition_payload.get("provider") or ""),
        str(definition_payload.get("title") or ""),
        questions,
    )
    fingerprint = str(payload.get("fingerprint") or "").strip()
    cached_at = float(payload.get("cached_at") or 0)
    return definition, fingerprint, cached_at


def _write_cached_definition(
    path: str,
    definition: SurveyDefinition,
    fingerprint: Optional[str],
    *,
    expected_epoch: Optional[int] = None,
) -> None:
    if not fingerprint:
        return
    if expected_epoch is not None and int(expected_epoch) != _cache_clear_epoch_snapshot():
        logging.info("跳过过期问卷解析缓存写回，path=%r expected_epoch=%s", path, expected_epoch)
        return
    payload = {
        "version": _CACHE_VERSION,
        "cached_at": _now(),
        "fingerprint": fingerprint,
        "definition": asdict(definition),
    }
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, sort_keys=True)
        os.replace(temp_path, path)
    except Exception as exc:
        logging.info("写入问卷解析缓存失败，path=%r：%s", path, exc)


def _stale_while_revalidate_window_seconds(provider: str) -> Optional[int]:
    if provider == SURVEY_PROVIDER_CREDAMO:
        return None
    return _STALE_WHILE_REVALIDATE_MAX_SECONDS


def _cache_age_seconds(cached_at: float) -> float:
    return max(0.0, _now() - float(cached_at or 0.0))


async def _resolve_maybe_awaitable(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _begin_inflight(normalized_url: str) -> tuple[_InflightEntry, bool]:
    with _REGISTRY_LOCK:
        entry = _INFLIGHT_BY_URL.get(normalized_url)
        if entry is not None:
            return entry, False
        entry = _InflightEntry()
        _INFLIGHT_BY_URL[normalized_url] = entry
        return entry, True


def _finish_inflight(normalized_url: str, entry: _InflightEntry, *, result: Optional[SurveyDefinition] = None, error: Optional[BaseException] = None) -> None:
    entry.result = result
    entry.error = error
    entry.event.set()
    with _REGISTRY_LOCK:
        current = _INFLIGHT_BY_URL.get(normalized_url)
        if current is entry:
            _INFLIGHT_BY_URL.pop(normalized_url, None)


def _wait_inflight(entry: _InflightEntry) -> SurveyDefinition:
    entry.event.wait()
    if entry.error is not None:
        raise entry.error
    if entry.result is None:
        raise RuntimeError("问卷解析 singleflight 完成后结果为空")
    return entry.result


async def _run_singleflight_parse(
    normalized_url: str,
    parser: Callable[[str], Awaitable[SurveyDefinition]],
    *,
    on_success: Optional[Callable[[SurveyDefinition], Awaitable[None] | None]] = None,
) -> SurveyDefinition:
    entry, is_leader = _begin_inflight(normalized_url)
    if not is_leader:
        return await asyncio.to_thread(_wait_inflight, entry)
    try:
        definition = await parser(normalized_url)
        if on_success is not None:
            persist_result = on_success(definition)
            if asyncio.iscoroutine(persist_result):
                await persist_result
        _finish_inflight(normalized_url, entry, result=definition)
        return definition
    except BaseException as exc:
        _finish_inflight(normalized_url, entry, error=exc)
        raise


def _start_background_refresh(
    normalized_url: str,
    provider: str,
    path: str,
    parser: Callable[[str], Awaitable[SurveyDefinition]],
) -> None:
    refresh_epoch = _cache_clear_epoch_snapshot()
    with _REGISTRY_LOCK:
        if normalized_url in _REFRESH_IN_PROGRESS:
            return
        _REFRESH_IN_PROGRESS.add(normalized_url)

    def _refresh_worker() -> None:
        try:
            async def _persist(definition: SurveyDefinition) -> None:
                fingerprint = await _resolve_maybe_awaitable(_fetch_remote_fingerprint(normalized_url, provider))
                _write_cached_definition(
                    path,
                    definition,
                    fingerprint,
                    expected_epoch=refresh_epoch,
                )

            refreshed = asyncio.run(_run_singleflight_parse(normalized_url, parser, on_success=_persist))
            logging.info(
                "后台刷新问卷解析缓存成功，url=%r provider=%s questions=%s",
                normalized_url,
                provider,
                len(getattr(refreshed, "questions", []) or []),
            )
        except Exception as exc:
            logging.info("后台刷新问卷解析缓存失败，url=%r provider=%s：%s", normalized_url, provider, exc)
        finally:
            with _REGISTRY_LOCK:
                _REFRESH_IN_PROGRESS.discard(normalized_url)
                _REFRESH_THREADS.discard(threading.current_thread())

    thread = threading.Thread(
        target=_refresh_worker,
        daemon=True,
        name=f"SurveyCacheRefresh-{_cache_key(normalized_url)[:8]}",
    )
    with _REGISTRY_LOCK:
        _REFRESH_THREADS.add(thread)
    thread.start()


def _wait_refresh_threads(timeout: float = 5.0) -> None:
    deadline = time.time() + max(0.0, float(timeout or 0.0))
    while True:
        with _REGISTRY_LOCK:
            threads = [thread for thread in _REFRESH_THREADS if thread.is_alive()]
            _REFRESH_THREADS.clear()
            _REFRESH_THREADS.update(threads)
        if not threads:
            return
        now = time.time()
        remaining = deadline - now
        if remaining <= 0:
            return
        for thread in threads:
            thread.join(timeout=min(remaining, 0.1))


async def parse_survey_with_cache(url: str, parser: Callable[[str], Awaitable[SurveyDefinition]]) -> SurveyDefinition:
    """解析问卷；远端指纹未变时复用本地缓存。"""
    normalized_url = _normalize_cache_url(url)
    cache_epoch = _cache_clear_epoch_snapshot()
    provider = detect_survey_provider(normalized_url)
    path = _cache_path(normalized_url)
    ttl_only_seconds = _ttl_only_cache_seconds(provider)
    stale_window_seconds = _stale_while_revalidate_window_seconds(provider)
    refresh_after_seconds = _SURVEY_PARSE_CACHE_TTL_SECONDS

    cached = _load_cached_definition(path)
    if cached is not None and ttl_only_seconds is not None:
        definition, _cached_fingerprint, cached_at = cached
        cache_age = _cache_age_seconds(cached_at)
        if cache_age <= ttl_only_seconds:
            logging.info("短时命中问卷解析缓存，url=%r provider=%s", normalized_url, provider)
            return definition

        logging.info("问卷短时缓存已过期，重新解析，url=%r provider=%s", normalized_url, provider)
        return await _run_singleflight_parse(
            normalized_url,
            parser,
            on_success=lambda refreshed: _write_cached_definition(path, refreshed, f"ttl-only:{provider}", expected_epoch=cache_epoch),
        )

    if ttl_only_seconds is not None:
        return await _run_singleflight_parse(
            normalized_url,
            parser,
            on_success=lambda refreshed: _write_cached_definition(path, refreshed, f"ttl-only:{provider}", expected_epoch=cache_epoch),
        )

    remote_fingerprint = await _resolve_maybe_awaitable(_fetch_remote_fingerprint(normalized_url, provider))
    if cached is not None:
        definition, cached_fingerprint, cached_at = cached
        cache_age = _cache_age_seconds(cached_at)
        if remote_fingerprint and remote_fingerprint == cached_fingerprint:
            logging.info("命中问卷解析缓存，url=%r", normalized_url)
            return definition
        if not remote_fingerprint and cached_fingerprint and cache_age <= _FALLBACK_TTL_SECONDS:
            logging.info("远端指纹不可用，短时复用问卷解析缓存，url=%r", normalized_url)
            return definition
        if (
            stale_window_seconds is not None
            and not remote_fingerprint
            and cache_age > refresh_after_seconds
            and cache_age <= stale_window_seconds
        ):
            logging.info("返回陈旧问卷解析缓存并触发后台刷新，url=%r provider=%s", normalized_url, provider)
            _start_background_refresh(normalized_url, provider, path, parser)
            return definition

    async def _persist(definition: SurveyDefinition) -> None:
        fingerprint = remote_fingerprint or await _resolve_maybe_awaitable(_fetch_remote_fingerprint(normalized_url, provider))
        _write_cached_definition(
            path,
            definition,
            fingerprint,
            expected_epoch=cache_epoch,
        )

    return await _run_singleflight_parse(normalized_url, parser, on_success=_persist)


def clear_survey_parse_cache() -> int:
    """清空问卷解析缓存目录，返回删除的文件/目录数量。"""
    cache_dir = _cache_directory()
    _bump_cache_clear_epoch()
    _wait_refresh_threads(timeout=2.0)
    with _REGISTRY_LOCK:
        _INFLIGHT_BY_URL.clear()
        _REFRESH_IN_PROGRESS.clear()
    if not os.path.isdir(cache_dir):
        return 0

    removed_count = 0
    for entry in os.scandir(cache_dir):
        try:
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path)
            else:
                os.remove(entry.path)
            removed_count += 1
        except FileNotFoundError:
            continue
    return removed_count


__all__ = [
    "clear_survey_parse_cache",
    "parse_survey_with_cache",
]

"""问卷解析结果缓存。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
from dataclasses import asdict
from typing import Any, Callable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from software.app.config import DEFAULT_HTTP_HEADERS
from software.app.runtime_paths import get_runtime_directory
from software.providers.common import (
    SURVEY_PROVIDER_CREDAMO,
    SURVEY_PROVIDER_QQ,
    SURVEY_PROVIDER_WJX,
    detect_survey_provider,
)
from software.providers.contracts import SurveyDefinition, build_survey_definition
import software.network.http as http_client


_CACHE_VERSION = 1
_CACHE_DIR_NAME = "survey_cache"
_SURVEY_PARSE_CACHE_TTL_SECONDS = 2 * 60 * 60
_FALLBACK_TTL_SECONDS = _SURVEY_PARSE_CACHE_TTL_SECONDS
_CREDAMO_TTL_SECONDS = _SURVEY_PARSE_CACHE_TTL_SECONDS
_LOCK = threading.RLock()


def _now() -> float:
    return time.time()


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
    return urlunsplit((scheme, netloc, path, query, parsed.fragment or ""))


def _cache_key(url: str) -> str:
    normalized = _normalize_cache_url(url)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _cache_directory() -> str:
    return os.path.join(get_runtime_directory(), "configs", _CACHE_DIR_NAME)


def _cache_path(url: str) -> str:
    return os.path.join(_cache_directory(), f"{_cache_key(url)}.json")


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="ignore")).hexdigest()


def _hash_json(value: Any) -> str:
    return _hash_text(_stable_json(value))


def _fetch_json_fingerprint(url: str, *, params: dict[str, Any], headers: dict[str, str]) -> Optional[str]:
    response = http_client.get(url, params=params, timeout=8, headers=headers, proxies={})
    response.raise_for_status()
    return _hash_json(response.json())


def _qq_fingerprint(url: str) -> Optional[str]:
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
        fingerprint = _fetch_json_fingerprint(api_url, params=params, headers=headers)
        if fingerprint:
            fingerprints.append(f"{endpoint}:{fingerprint}")
    return _hash_text("|".join(fingerprints)) if fingerprints else None


def _html_fingerprint(url: str) -> Optional[str]:
    response = http_client.get(url, timeout=10, headers=DEFAULT_HTTP_HEADERS, proxies={})
    response.raise_for_status()
    return _hash_text(response.text)


def _fetch_remote_fingerprint(url: str, provider: str) -> Optional[str]:
    try:
        if provider == SURVEY_PROVIDER_QQ:
            return _qq_fingerprint(url)
        if provider == SURVEY_PROVIDER_WJX:
            return _html_fingerprint(url)
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


def _write_cached_definition(path: str, definition: SurveyDefinition, fingerprint: Optional[str]) -> None:
    if not fingerprint:
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


def parse_survey_with_cache(url: str, parser: Callable[[str], SurveyDefinition]) -> SurveyDefinition:
    """解析问卷；远端指纹未变时复用本地缓存。"""
    normalized_url = _normalize_cache_url(url)
    provider = detect_survey_provider(normalized_url)
    path = _cache_path(normalized_url)

    with _LOCK:
        cached = _load_cached_definition(path)
        ttl_only_seconds = _ttl_only_cache_seconds(provider)
        if cached is not None and ttl_only_seconds is not None:
            definition, _cached_fingerprint, cached_at = cached
            if (_now() - cached_at) <= ttl_only_seconds:
                logging.info("短时命中问卷解析缓存，url=%r provider=%s", normalized_url, provider)
                return definition

            logging.info("问卷短时缓存已过期，重新解析，url=%r provider=%s", normalized_url, provider)
            definition = parser(normalized_url)
            _write_cached_definition(path, definition, f"ttl-only:{provider}")
            return definition

        if ttl_only_seconds is not None:
            definition = parser(normalized_url)
            _write_cached_definition(path, definition, f"ttl-only:{provider}")
            return definition

        remote_fingerprint = _fetch_remote_fingerprint(normalized_url, provider)
        if cached is not None:
            definition, cached_fingerprint, cached_at = cached
            if remote_fingerprint and remote_fingerprint == cached_fingerprint:
                logging.info("命中问卷解析缓存，url=%r", normalized_url)
                return definition
            if not remote_fingerprint and cached_fingerprint and (_now() - cached_at) <= _FALLBACK_TTL_SECONDS:
                logging.info("远端指纹不可用，短时复用问卷解析缓存，url=%r", normalized_url)
                return definition

        definition = parser(normalized_url)
        if not remote_fingerprint:
            remote_fingerprint = _fetch_remote_fingerprint(normalized_url, provider)
        _write_cached_definition(path, definition, remote_fingerprint)
        return definition


def clear_survey_parse_cache() -> int:
    """清空问卷解析缓存目录，返回删除的文件/目录数量。"""
    cache_dir = _cache_directory()
    if not os.path.isdir(cache_dir):
        return 0

    removed_count = 0
    with _LOCK:
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

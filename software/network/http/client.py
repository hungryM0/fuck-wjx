"""基于 httpx 的统一 HTTP 客户端（同步连接池封装）。"""
from __future__ import annotations

import atexit
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional, Tuple, Union
from urllib.parse import urlsplit

import httpx

from software.logging.log_utils import log_suppressed_exception


_CLIENT_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)
_MAX_CLIENTS = 20
_CLIENT_TTL = 300
_PREWARM_LOCK = threading.Lock()
_PREWARMED = False


RequestException = httpx.HTTPError
Timeout = httpx.TimeoutException
ConnectTimeout = httpx.ConnectTimeout
ReadTimeout = httpx.ReadTimeout
ConnectionError = httpx.ConnectError
HTTPError = httpx.HTTPStatusError


@dataclass(frozen=True)
class _ClientKey:
    proxy: Optional[str]
    verify: Union[bool, str]
    follow_redirects: bool
    trust_env: bool


@dataclass
class _ClientEntry:
    client: httpx.Client
    last_used: float
    active_requests: int = 0


class _StreamResponse:
    """给同步流响应补一个 requests 风格的 iter_content 接口。"""

    def __init__(
        self,
        response: httpx.Response,
        stream_ctx: Any,
        release: Any,
    ):
        self._response = response
        self._stream_ctx = stream_ctx
        self._release = release
        self._closed = False

    @property
    def status_code(self) -> int:
        return self._response.status_code

    @property
    def headers(self) -> httpx.Headers:
        return self._response.headers

    @property
    def text(self) -> str:
        return self._response.text

    @property
    def content(self) -> bytes:
        return self._response.content

    def json(self) -> Any:
        return self._response.json()

    def raise_for_status(self) -> None:
        self._response.raise_for_status()

    def iter_content(self, chunk_size: int = 8192) -> Iterator[bytes]:
        try:
            for chunk in self._response.iter_bytes(chunk_size=max(int(chunk_size), 1)):
                if chunk:
                    yield chunk
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._stream_ctx.__exit__(None, None, None)
        except Exception as exc:
            log_suppressed_exception("_StreamResponse.close stream_ctx.__exit__", exc, level=logging.WARNING)
        finally:
            try:
                self._release()
            except Exception as exc:
                log_suppressed_exception("_StreamResponse.close release()", exc, level=logging.WARNING)

    def __del__(self) -> None:  # pragma: no cover
        self.close()


class _SyncClientManager:
    """按配置缓存同步 Client，统一管理生命周期。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._clients: Dict[_ClientKey, _ClientEntry] = {}

    def _create_client(
        self,
        *,
        proxy: Optional[str],
        verify: Union[bool, str],
        follow_redirects: bool,
        trust_env: bool,
    ) -> httpx.Client:
        return httpx.Client(
            timeout=None,
            verify=verify,
            proxy=proxy,
            follow_redirects=follow_redirects,
            trust_env=trust_env,
            limits=_CLIENT_LIMITS,
        )

    def _cleanup_stale_clients_locked(self) -> list[httpx.Client]:
        now = time.time()
        stale_keys = [
            key
            for key, entry in self._clients.items()
            if entry.active_requests <= 0 and (now - entry.last_used) > _CLIENT_TTL
        ]
        closed: list[httpx.Client] = []
        for key in stale_keys:
            entry = self._clients.pop(key, None)
            if entry is not None:
                closed.append(entry.client)
        return closed

    def _evict_oldest_idle_client_locked(self) -> Optional[httpx.Client]:
        idle_items = [
            (key, entry)
            for key, entry in self._clients.items()
            if entry.active_requests <= 0
        ]
        if not idle_items:
            return None
        oldest_key, oldest_entry = min(idle_items, key=lambda item: item[1].last_used)
        self._clients.pop(oldest_key, None)
        return oldest_entry.client

    def _close_clients(self, clients: list[httpx.Client]) -> None:
        for client in clients:
            try:
                client.close()
            except Exception as exc:
                log_suppressed_exception("_SyncClientManager._close_clients client.close()", exc, level=logging.WARNING)

    def acquire(
        self,
        *,
        proxy: Optional[str],
        verify: Union[bool, str],
        follow_redirects: bool,
        trust_env: bool,
    ) -> tuple[_ClientKey, _ClientEntry]:
        key = _ClientKey(
            proxy=proxy,
            verify=verify,
            follow_redirects=follow_redirects,
            trust_env=trust_env,
        )

        clients_to_close: list[httpx.Client] = []
        now = time.time()
        with self._lock:
            clients_to_close.extend(self._cleanup_stale_clients_locked())

            entry = self._clients.get(key)
            if entry is None:
                if len(self._clients) >= _MAX_CLIENTS:
                    evicted = self._evict_oldest_idle_client_locked()
                    if evicted is not None:
                        clients_to_close.append(evicted)
                entry = _ClientEntry(
                    client=self._create_client(
                        proxy=proxy,
                        verify=verify,
                        follow_redirects=follow_redirects,
                        trust_env=trust_env,
                    ),
                    last_used=now,
                )
                self._clients[key] = entry

            entry.last_used = now
            entry.active_requests += 1

        self._close_clients(clients_to_close)
        return key, entry

    def release(self, key: _ClientKey) -> None:
        with self._lock:
            entry = self._clients.get(key)
            if entry is None:
                return
            entry.active_requests = max(0, entry.active_requests - 1)
            entry.last_used = time.time()

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Any = None,
        content: Any = None,
        data: Any = None,
        headers: Any = None,
        cookies: Any = None,
        files: Any = None,
        auth: Any = None,
        timeout: Any = None,
        allow_redirects: bool = True,
        proxies: Any = None,
        stream: bool = False,
        verify: Union[bool, str] = True,
        json: Any = None,
    ) -> Union[httpx.Response, _StreamResponse]:
        proxy, trust_env = _resolve_proxy(proxies, url)
        key, entry = self.acquire(
            proxy=proxy,
            verify=verify,
            follow_redirects=allow_redirects,
            trust_env=trust_env,
        )
        normalized_timeout = _normalize_timeout(timeout)

        try:
            if stream:
                stream_ctx = entry.client.stream(
                    method=method,
                    url=url,
                    params=params,
                    content=content,
                    data=data,
                    headers=headers,
                    cookies=cookies,
                    files=files,
                    auth=auth,
                    json=json,
                    timeout=normalized_timeout,
                )
                response = stream_ctx.__enter__()
                return _StreamResponse(response, stream_ctx, lambda: self.release(key))

            response = entry.client.request(
                method=method,
                url=url,
                params=params,
                content=content,
                data=data,
                headers=headers,
                cookies=cookies,
                files=files,
                auth=auth,
                json=json,
                timeout=normalized_timeout,
            )
            self.release(key)
            return response
        except Exception:
            self.release(key)
            raise

    def close(self) -> None:
        with self._lock:
            clients = [entry.client for entry in self._clients.values()]
            self._clients.clear()
        self._close_clients(clients)


def _resolve_proxy(proxies: Any, url: str) -> Tuple[Optional[str], bool]:
    """把 requests 风格 proxies 参数映射到 httpx。"""
    if proxies is None:
        return None, True
    if proxies == {}:
        return None, False
    if isinstance(proxies, str):
        return proxies, False
    if isinstance(proxies, dict):
        scheme = urlsplit(url).scheme.lower()
        http_proxy = proxies.get("http") or proxies.get("http://")
        https_proxy = proxies.get("https") or proxies.get("https://")
        if not http_proxy and not https_proxy:
            return None, False
        if scheme == "https":
            return str(https_proxy or http_proxy), False
        return str(http_proxy or https_proxy), False
    return None, False


def _normalize_timeout(timeout: Any) -> Any:
    """兼容 requests 的 timeout 形态。"""
    if timeout is None:
        return None
    if isinstance(timeout, (int, float)):
        return float(timeout)
    if isinstance(timeout, tuple):
        if len(timeout) == 2:
            connect, read = timeout
            connect_val = float(connect) if connect is not None else None
            read_val = float(read) if read is not None else None
            return httpx.Timeout(connect=connect_val, read=read_val, write=read_val, pool=connect_val)
        if len(timeout) == 4:
            connect, read, write, pool = timeout
            return httpx.Timeout(
                connect=float(connect) if connect is not None else None,
                read=float(read) if read is not None else None,
                write=float(write) if write is not None else None,
                pool=float(pool) if pool is not None else None,
            )
    return timeout


_client_manager = _SyncClientManager()


def prewarm() -> None:
    """在主线程预热 httpx/httpcore/ssl 导入链，规避首次后台初始化的原生崩溃。"""
    global _PREWARMED

    if _PREWARMED:
        return

    with _PREWARM_LOCK:
        if _PREWARMED:
            return
        temp_client: httpx.Client | None = None
        try:
            # 这里只做传输层与 SSL 上下文初始化，不发送真实请求。
            temp_client = httpx.Client(timeout=None, limits=_CLIENT_LIMITS)
            _PREWARMED = True
        except Exception as exc:
            log_suppressed_exception("http_client.prewarm httpx.Client()", exc, level=logging.WARNING)
        finally:
            if temp_client is not None:
                try:
                    temp_client.close()
                except Exception as exc:
                    log_suppressed_exception("http_client.prewarm temp_client.close()", exc, level=logging.WARNING)


def close() -> None:
    """关闭客户端池。"""
    try:
        _client_manager.close()
    except Exception as exc:
        log_suppressed_exception("http_client.close _client_manager.close()", exc, level=logging.WARNING)


atexit.register(close)


def request(method: str, url: str, **kwargs: Any):
    return _client_manager.request(method, url, **kwargs)


def get(url: str, **kwargs: Any):
    return request("GET", url, **kwargs)


def post(url: str, **kwargs: Any):
    return request("POST", url, **kwargs)


def put(url: str, **kwargs: Any):
    return request("PUT", url, **kwargs)


def delete(url: str, **kwargs: Any):
    return request("DELETE", url, **kwargs)


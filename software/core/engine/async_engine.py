"""Background asyncio runtime engine."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from typing import Any, Callable, Optional

from software.core.engine.async_events import AsyncRunContext
from software.core.engine.async_runtime_loop import AsyncSlotRunner
from software.core.engine.async_scheduler import AsyncScheduler
from software.core.engine.async_status_bus import AsyncStatusBus
from software.core.engine.runtime_ui_bridge import RuntimeUiBridge, set_random_ip_loading
from software.core.task import ExecutionConfig, ExecutionState
from software.network.proxy.api import fetch_proxy_batch_async
from software.network.session_policy import (
    _acquire_proxy_fetch_lock_async,
    merge_prefetched_proxy_leases,
    release_proxy_fetch_lock,
    resolve_proxy_prefetch_request_count,
)
from software.providers.registry import parse_survey


class AsyncRuntimeEngine:
    """Owns the single background asyncio loop used by fill runtime."""

    def __init__(self, *, status_bus: Optional[AsyncStatusBus] = None) -> None:
        self._status_bus = status_bus or AsyncStatusBus()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_ready = threading.Event()
        self._start_lock = threading.Lock()
        self._run_future: Optional[concurrent.futures.Future[Any]] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._pause_event: Optional[asyncio.Event] = None
        self._closed = False
        self._state: Optional[ExecutionState] = None

    @property
    def thread(self) -> Optional[threading.Thread]:
        return self._thread

    def start(self) -> None:
        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._loop_ready.clear()

            def _runner() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                self._loop_ready.set()
                try:
                    loop.run_forever()
                finally:
                    pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
                    for task in pending:
                        task.cancel()
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.close()

            self._thread = threading.Thread(target=_runner, daemon=True, name="AsyncRuntimeEngine")
            self._thread.start()
        self._loop_ready.wait()

    def _submit(self, coro: Any) -> concurrent.futures.Future[Any]:
        self.start()
        if self._loop is None:
            raise RuntimeError("AsyncRuntimeEngine loop 未启动")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def start_run(
        self,
        *,
        config: ExecutionConfig,
        state: ExecutionState,
        runtime_bridge: RuntimeUiBridge | None = None,
    ) -> concurrent.futures.Future[Any]:
        if self._run_future is not None and not self._run_future.done():
            raise RuntimeError("任务已在运行中")
        future = self._submit(self._run(config=config, state=state, runtime_bridge=runtime_bridge))
        self._run_future = future
        return future

    async def _run(
        self,
        *,
        config: ExecutionConfig,
        state: ExecutionState,
        runtime_bridge: RuntimeUiBridge | None = None,
    ) -> None:
        self._stop_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._state = state
        state.stop_event.clear()
        worker_count = max(1, int(config.num_threads or 1))
        state.ensure_worker_threads(worker_count, prefix="Slot")
        scheduler = AsyncScheduler(concurrency=worker_count)
        run_context = AsyncRunContext(
            state=state,
            stop_event=self._stop_event,
            pause_event=self._pause_event,
            status_sink=self._status_bus.emit,
        )
        logging.info(
            "AsyncRuntimeEngine 已启动：总并发=%s，纯 HTTP 运行时",
            worker_count,
        )
        logging.info("目标份数: %s, 当前进度: %s/%s", config.target_num, state.cur_num, config.target_num)
        stop_event = self._stop_event
        if stop_event is None:
            raise RuntimeError("AsyncRuntimeEngine stop_event 未初始化")

        async def _prefetch_proxy_pool() -> None:
            request_count = resolve_proxy_prefetch_request_count(state)
            if request_count <= 0:
                return
            set_random_ip_loading(runtime_bridge, True, f"正在准备代理 0/{request_count}")
            fetch_lock_acquired = False
            try:
                fetch_lock_acquired = await _acquire_proxy_fetch_lock_async(state, state.stop_event)
                if not fetch_lock_acquired or state.stop_event.is_set() or stop_event.is_set():
                    return
                fetched = await fetch_proxy_batch_async(
                    expected_count=request_count,
                    stop_signal=state.stop_event,
                )
                if state.stop_event.is_set() or stop_event.is_set():
                    return
                merged_count = merge_prefetched_proxy_leases(state, fetched)
                if merged_count:
                    set_random_ip_loading(
                        runtime_bridge,
                        True,
                        f"正在准备代理 {min(merged_count, request_count)}/{request_count}",
                    )
            except Exception:
                logging.info("随机IP异步预热失败", exc_info=True)
            finally:
                if fetch_lock_acquired:
                    try:
                        release_proxy_fetch_lock(state)
                    except Exception:
                        logging.info("释放随机IP异步预热锁失败", exc_info=True)
                set_random_ip_loading(runtime_bridge, False, "")

        prefetch_task = asyncio.create_task(_prefetch_proxy_pool(), name="AsyncProxyPrefetch")
        try:
            async with asyncio.TaskGroup() as task_group:
                for slot_index in range(worker_count):
                    task_group.create_task(
                        AsyncSlotRunner(
                            slot_id=slot_index + 1,
                            config=config,
                            state=state,
                            run_context=run_context,
                            scheduler=scheduler,
                            runtime_bridge=runtime_bridge,
                        ).run(),
                        name=f"AsyncSlotRunner-{slot_index + 1}",
                    )
        except* Exception as exc_group:
            errors = [exc for exc in exc_group.exceptions if not isinstance(exc, asyncio.CancelledError)]
            if not errors:
                raise
            if len(errors) == 1:
                raise errors[0]
            raise ExceptionGroup("AsyncRuntimeEngine slot 运行失败", errors)
        finally:
            prefetch_task.cancel()
            await asyncio.gather(prefetch_task, return_exceptions=True)
            if self._stop_event is not None:
                self._stop_event.set()
            await scheduler.close()
            state.stop_event.set()
            self._stop_event = None
            self._pause_event = None
            self._state = None

    def stop_run(self) -> None:
        stop_event = self._stop_event
        state = self._state
        if state is not None:
            try:
                state.stop_event.set()
            except Exception:
                logging.debug("设置 ExecutionState.stop_event 失败", exc_info=True)
        if self._loop is not None and stop_event is not None:
            self._loop.call_soon_threadsafe(stop_event.set)
        future = self._run_future
        if future is not None and future.done():
            self._run_future = None

    def pause_run(self, reason: str = "") -> None:
        del reason
        pause_event = self._pause_event
        if self._loop is not None and pause_event is not None:
            self._loop.call_soon_threadsafe(pause_event.set)

    def resume_run(self) -> None:
        pause_event = self._pause_event
        if self._loop is not None and pause_event is not None:
            self._loop.call_soon_threadsafe(pause_event.clear)

    def parse_survey(self, url: str) -> concurrent.futures.Future[Any]:
        return self._submit(parse_survey(url))

    def submit_ui_task(self, task_name: str, coro_factory: Callable[[], Any]) -> concurrent.futures.Future[Any]:
        async def _run_task() -> Any:
            logging.debug("AsyncUiTaskService 执行任务：%s", task_name)
            return await coro_factory()

        return self._submit(_run_task())

    def shutdown(self, *, timeout: float = 5.0) -> None:
        if self._closed:
            return
        self._closed = True
        self.stop_run()
        future = self._run_future
        if future is not None:
            try:
                future.result(timeout=max(0.0, float(timeout or 0.0)))
            except Exception:
                logging.debug("AsyncRuntimeEngine shutdown 等待运行结束失败", exc_info=True)
        loop = self._loop
        thread = self._thread
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout or 0.0)))
        self._thread = None
        self._loop = None


class AsyncEngineClient:
    """Synchronous UI-facing client for AsyncRuntimeEngine."""

    def __init__(self, engine: Optional[AsyncRuntimeEngine] = None) -> None:
        self._engine = engine or AsyncRuntimeEngine()

    @property
    def thread(self) -> Optional[threading.Thread]:
        return self._engine.thread

    def start_run(
        self,
        config: ExecutionConfig,
        state: ExecutionState,
        *,
        runtime_bridge: RuntimeUiBridge | None = None,
    ) -> concurrent.futures.Future[Any]:
        return self._engine.start_run(config=config, state=state, runtime_bridge=runtime_bridge)

    def stop_run(self) -> None:
        self._engine.stop_run()

    def pause_run(self, reason: str = "") -> None:
        self._engine.pause_run(reason)

    def resume_run(self) -> None:
        self._engine.resume_run()

    def parse_survey(self, url: str) -> concurrent.futures.Future[Any]:
        return self._engine.parse_survey(url)

    def submit_ui_task(self, task_name: str, coro_factory: Callable[[], Any]) -> concurrent.futures.Future[Any]:
        return self._engine.submit_ui_task(task_name, coro_factory)

    def shutdown(self, *, timeout: float = 5.0) -> None:
        self._engine.shutdown(timeout=timeout)


__all__ = ["AsyncEngineClient", "AsyncRuntimeEngine"]

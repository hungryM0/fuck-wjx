"""Background asyncio runtime engine."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from typing import Any, Callable, Optional

from software.app.config import BROWSER_PREFERENCE
from software.core.engine.async_events import AsyncRunContext
from software.core.engine.async_runtime_loop import AsyncSlotRunner
from software.core.engine.async_scheduler import AsyncScheduler
from software.core.engine.async_status_bus import AsyncStatusBus
from software.core.engine.runtime_layout import build_owner_window_positions
from software.core.task import ExecutionConfig, ExecutionState
from software.network.browser.async_owner_pool import AsyncBrowserOwnerPool
from software.network.browser.pool_config import BrowserPoolConfig
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
        self._browser_pool: Optional[AsyncBrowserOwnerPool] = None
        self._retained_no_submit_browser_pool: Optional[AsyncBrowserOwnerPool] = None
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

    def start_run(self, *, config: ExecutionConfig, state: ExecutionState, gui_instance: Any = None) -> concurrent.futures.Future[Any]:
        if self._run_future is not None and not self._run_future.done():
            raise RuntimeError("任务已在运行中")
        future = self._submit(self._run(config=config, state=state, gui_instance=gui_instance))
        self._run_future = future
        return future

    async def _run(self, *, config: ExecutionConfig, state: ExecutionState, gui_instance: Any = None) -> None:
        retained_pool = self._retained_no_submit_browser_pool
        if retained_pool is not None:
            try:
                await retained_pool.shutdown()
            except Exception:
                logging.debug("清理上一次单测保留浏览器失败", exc_info=True)
            self._retained_no_submit_browser_pool = None
        self._stop_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._state = state
        state.stop_event.clear()
        worker_count = max(1, int(config.num_threads or 1))
        state.ensure_worker_threads(worker_count, prefix="Slot")
        pool_config = BrowserPoolConfig.from_concurrency(
            worker_count,
            headless=bool(config.headless_mode),
        )
        self._browser_pool = AsyncBrowserOwnerPool(
            config=pool_config,
            headless=bool(config.headless_mode),
            prefer_browsers=list(config.browser_preference or BROWSER_PREFERENCE),
            window_positions=build_owner_window_positions(pool_config.owner_count),
        )
        scheduler = AsyncScheduler(concurrency=worker_count)
        run_context = AsyncRunContext(
            state=state,
            stop_event=self._stop_event,
            pause_event=self._pause_event,
            status_sink=self._status_bus.emit,
        )
        logging.info(
            "AsyncRuntimeEngine 已启动：总并发=%s owner数=%s 每owner上下文上限=%s",
            worker_count,
            pool_config.owner_count,
            pool_config.contexts_per_owner,
        )
        logging.info("目标份数: %s, 当前进度: %s/%s", config.target_num, state.cur_num, config.target_num)
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
                            browser_pool=self._browser_pool,
                            gui_instance=gui_instance,
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
            if self._stop_event is not None:
                self._stop_event.set()
            await scheduler.close()
            if self._browser_pool is not None:
                should_retain_browser_pool = bool(
                    not getattr(config, "submit_enabled", True)
                    and state.cur_num >= max(1, int(getattr(config, "target_num", 0) or 0))
                    and str(state.get_terminal_stop_snapshot()[0] or "") == "target_reached"
                )
                if should_retain_browser_pool:
                    self._retained_no_submit_browser_pool = self._browser_pool
                else:
                    await self._browser_pool.shutdown()
                self._browser_pool = None
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
        retained_pool = self._retained_no_submit_browser_pool
        if retained_pool is not None and self._loop is not None and not self._loop.is_closed():
            try:
                close_future = asyncio.run_coroutine_threadsafe(retained_pool.shutdown(), self._loop)
                close_future.result(timeout=max(0.0, float(timeout or 0.0)))
            except Exception:
                logging.debug("AsyncRuntimeEngine shutdown 清理单测保留浏览器失败", exc_info=True)
            finally:
                self._retained_no_submit_browser_pool = None
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

    def start_run(self, config: ExecutionConfig, state: ExecutionState, *, gui_instance: Any = None) -> concurrent.futures.Future[Any]:
        return self._engine.start_run(config=config, state=state, gui_instance=gui_instance)

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

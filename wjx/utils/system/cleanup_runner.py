"""异步清理任务执行器 - 后台回收浏览器实例等资源"""
from __future__ import annotations
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception


import subprocess
import threading
import time
from collections import deque
from typing import Callable, Deque, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# 需要清理的浏览器进程名
_BROWSER_PROCESS_NAMES = ("chrome.exe", "msedge.exe", "chromium.exe")

# Windows 隐藏控制台窗口标志
_NO_WINDOW = 0x08000000


class CleanupRunner:
    """Run cleanup tasks in a single background worker to avoid blocking the UI.



    新增批量进程清理机制：
    - Worker 线程只需将 PID 放入待清理集合
    - 清理器会自动聚合 PID，批量执行 taskkill
    - 大幅减少进程创建开销，消除 CPU 峰值
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: Deque[Tuple[Callable[[], None], float]] = deque()
        self._thread: Optional[threading.Thread] = None

        # 批量进程清理相关
        self._pending_pids: Set[int] = set()  # 待清理的 PID 集合
        self._batch_timer: Optional[threading.Timer] = None  # 去抖定时器
        self._batch_delay = 0.3  # 聚合延迟（秒）

    def submit(self, task: Callable[[], None], delay_seconds: float = 0.0) -> None:
        """提交普通清理任务（非 PID 清理）"""
        delay = max(0.0, float(delay_seconds or 0.0))
        with self._lock:
            self._queue.append((task, delay))
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._worker, daemon=True, name="CleanupWorker")
            self._thread.start()

    def submit_pid_cleanup(self, pids: Set[int]) -> None:
        """提交 PID 清理请求（批量聚合模式）

        Args:
            pids: 需要清理的进程 PID 集合
        """
        if not pids:
            return

        with self._lock:
            self._pending_pids.update(pids)

            # 取消之前的定时器，重新设置去抖延迟
            if self._batch_timer:
                self._batch_timer.cancel()

            # 设置新的定时器：延迟执行批量清理
            self._batch_timer = threading.Timer(
                self._batch_delay,
                self._execute_batch_cleanup
            )
            self._batch_timer.daemon = True
            self._batch_timer.start()

    def _execute_batch_cleanup(self) -> None:
        """执行批量 PID 清理（由定时器触发）"""
        with self._lock:
            pids_to_kill = set(self._pending_pids)
            self._pending_pids.clear()
            self._batch_timer = None

        if not pids_to_kill:
            return

        logger.debug(f"[批量清理] 开始清理 {len(pids_to_kill)} 个浏览器进程")

        try:
            # 构造批量 taskkill 命令：taskkill /F /PID 101 /PID 102 ...
            cmd = ["taskkill", "/F"]
            for pid in pids_to_kill:
                cmd.extend(["/PID", str(pid)])

            # 一次性杀掉所有进程
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                creationflags=_NO_WINDOW,
            )
            logger.debug(f"[批量清理] 已终止 {len(pids_to_kill)} 个进程")
        except Exception as exc:
            logger.debug(f"[批量清理] 终止进程失败: {exc}")

    def flush_pending_pids(self) -> None:
        """立即执行所有待清理的 PID（不等待去抖延迟）

        用于强制停止时立即清理所有浏览器进程

        优化：异步执行，不阻塞调用线程
        """
        with self._lock:
            if self._batch_timer:
                self._batch_timer.cancel()
                self._batch_timer = None

        # 异步执行批量清理，不阻塞调用线程
        cleanup_thread = threading.Thread(
            target=self._execute_batch_cleanup,
            daemon=True,
            name="FlushPIDCleanup"
        )
        cleanup_thread.start()

    def _worker(self) -> None:
        """后台工作线程：处理普通清理任务队列"""
        while True:
            with self._lock:
                if not self._queue:
                    self._thread = None
                    return
                task, delay = self._queue.popleft()
            if delay > 0:
                time.sleep(delay)
            try:
                task()
            except Exception as exc:
                log_suppressed_exception("_worker: task()", exc, level=logging.WARNING)


def kill_browser_processes() -> None:
    """使用 taskkill 强制关闭所有浏览器进程（异步执行，不阻塞调用线程）。"""

    def _do_kill():
        logger.info("开始清理浏览器进程: %s", ", ".join(_BROWSER_PROCESS_NAMES))
        for name in _BROWSER_PROCESS_NAMES:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    creationflags=_NO_WINDOW,
                )
            except Exception as exc:
                log_suppressed_exception("_do_kill: subprocess.run( [\"taskkill\", \"/F\", \"/IM\", name], stdout=subprocess.DEVNULL, s...", exc, level=logging.WARNING)
        logger.info("浏览器进程清理完成")

    threading.Thread(target=_do_kill, daemon=True, name="BrowserKiller").start()

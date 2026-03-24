"""
定时任务调度器模块
"""

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from wjx.utils.app.runtime_paths import get_runtime_directory

logger = logging.getLogger(__name__)


class TaskScheduler:
    _instance: Optional["TaskScheduler"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs) -> "TaskScheduler":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        self._task_jobs: Dict[int, str] = {}
        self._task_callbacks: Dict[int, Callable] = {}
        self._running_tasks: Dict[int, bool] = {}
        self._initialized = True
        self._started = False

    def start(self) -> None:
        if not self._started:
            self._scheduler.start()
            self._started = True
            logger.info("任务调度器已启动")

    def stop(self) -> None:
        if self._started:
            self._scheduler.shutdown(wait=True)
            self._started = False
            logger.info("任务调度器已停止")

    def add_task(
        self,
        task_id: int,
        trigger_type: str,
        trigger_args: str,
        callback: Callable[[], None],
    ) -> bool:
        try:
            if trigger_type == "cron":
                trigger = CronTrigger.from_crontab(trigger_args)
            elif trigger_type == "interval":
                trigger = self._parse_interval_trigger(trigger_args)
            else:
                logger.error(f"不支持的触发器类型: {trigger_type}")
                return False

            job = self._scheduler.add_job(
                callback,
                trigger=trigger,
                id=str(task_id),
                replace_existing=True,
            )
            self._task_jobs[task_id] = job.id
            self._task_callbacks[task_id] = callback
            logger.info(f"任务 {task_id} 已添加到调度器: {trigger_type} {trigger_args}")
            return True
        except Exception as e:
            logger.error(f"添加任务 {task_id} 失败: {e}")
            return False

    def remove_task(self, task_id: int) -> bool:
        try:
            if task_id in self._task_jobs:
                job_id = self._task_jobs[task_id]
                self._scheduler.remove_job(job_id)
                del self._task_jobs[task_id]
                if task_id in self._task_callbacks:
                    del self._task_callbacks[task_id]
                logger.info(f"任务 {task_id} 已从调度器移除")
                return True
            return False
        except Exception as e:
            logger.error(f"移除任务 {task_id} 失败: {e}")
            return False

    def pause_task(self, task_id: int) -> bool:
        try:
            if task_id in self._task_jobs:
                job_id = self._task_jobs[task_id]
                self._scheduler.pause_job(job_id)
                logger.info(f"任务 {task_id} 已暂停")
                return True
            return False
        except Exception as e:
            logger.error(f"暂停任务 {task_id} 失败: {e}")
            return False

    def resume_task(self, task_id: int) -> bool:
        try:
            if task_id in self._task_jobs:
                job_id = self._task_jobs[task_id]
                self._scheduler.resume_job(job_id)
                logger.info(f"任务 {task_id} 已恢复")
                return True
            return False
        except Exception as e:
            logger.error(f"恢复任务 {task_id} 失败: {e}")
            return False

    def run_task_now(self, task_id: int) -> bool:
        try:
            if task_id in self._task_callbacks:
                callback = self._task_callbacks[task_id]
                threading.Thread(target=callback, daemon=True).start()
                logger.info(f"任务 {task_id} 已立即执行")
                return True
            return False
        except Exception as e:
            logger.error(f"立即执行任务 {task_id} 失败: {e}")
            return False

    def get_task_status(self, task_id: int) -> Optional[Dict[str, Any]]:
        try:
            if task_id not in self._task_jobs:
                return None
            job_id = self._task_jobs[task_id]
            job = self._scheduler.get_job(job_id)
            if job is None:
                return None
            return {
                "id": task_id,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                "pending": job.pending,
            }
        except Exception as e:
            logger.error(f"获取任务 {task_id} 状态失败: {e}")
            return None

    def get_all_jobs(self) -> List[Dict[str, Any]]:
        try:
            jobs = self._scheduler.get_jobs()
            result = []
            for job in jobs:
                task_id = int(job.id)
                task_info = self.get_task_status(task_id)
                if task_info:
                    result.append(task_info)
            return result
        except Exception as e:
            logger.error(f"获取所有任务状态失败: {e}")
            return []

    @staticmethod
    def _parse_interval_trigger(trigger_args: str) -> IntervalTrigger:
        parts = trigger_args.split(",")
        kwargs = {}
        for part in parts:
            if "=" in part:
                key, value = part.split("=", 1)
                key = key.strip()
                value = int(value.strip())
                kwargs[key] = value
        return IntervalTrigger(**kwargs)


_scheduler_instance: Optional[TaskScheduler] = None


def get_scheduler() -> TaskScheduler:
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = TaskScheduler()
        _scheduler_instance.start()
    return _scheduler_instance


def _get_tasks_db_path() -> str:
    runtime_dir = get_runtime_directory()
    tasks_dir = os.path.join(runtime_dir, "tasks")
    os.makedirs(tasks_dir, exist_ok=True)
    return os.path.join(tasks_dir, "tasks.db")


def _init_tasks_db() -> None:
    db_path = _get_tasks_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            trigger_args TEXT NOT NULL,
            config_path TEXT NOT NULL,
            priority TEXT DEFAULT 'normal',
            enabled INTEGER DEFAULT 1,
            status TEXT DEFAULT 'pending',
            last_run TEXT,
            next_run TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            message TEXT,
            executed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        )
    """)
    conn.commit()
    conn.close()


def get_all_tasks_from_db() -> List[Dict[str, Any]]:
    _init_tasks_db()
    db_path = _get_tasks_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks ORDER BY id")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_task_from_db(task_id: int) -> Optional[Dict[str, Any]]:
    _init_tasks_db()
    db_path = _get_tasks_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_task_status_in_db(
    task_id: int,
    status: str,
    last_run_time: Optional[str] = None,
    next_run_time: Optional[str] = None,
) -> None:
    _init_tasks_db()
    db_path = _get_tasks_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE tasks
        SET status = ?, last_run = ?, next_run = ?
        WHERE id = ?
        """,
        (status, last_run_time, next_run_time, task_id),
    )
    conn.commit()
    conn.close()


def log_task_execution(
    task_id: int,
    status: str,
    message: Optional[str] = None,
) -> None:
    _init_tasks_db()
    db_path = _get_tasks_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO task_logs (task_id, status, message)
        VALUES (?, ?, ?)
        """,
        (task_id, status, message),
    )
    conn.commit()
    conn.close()


def get_task_logs(task_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    _init_tasks_db()
    db_path = _get_tasks_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM task_logs WHERE task_id = ? ORDER BY executed_at DESC LIMIT ?",
        (task_id, limit),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def create_task_executor(task_config: Dict[str, Any]) -> Callable:
    def executor() -> None:
        task_id = task_config["id"]
        config_path = task_config["config_path"]
        try:
            update_task_status_in_db(task_id, "running")
            log_task_execution(task_id, "started", "任务开始执行")
            if os.path.exists(config_path):
                logger.info(f"执行任务 {task_id}: {config_path}")
                update_task_status_in_db(task_id, "success", datetime.now().isoformat())
                log_task_execution(task_id, "success", "任务执行成功")
            else:
                logger.error(f"配置文件不存在: {config_path}")
                update_task_status_in_db(task_id, "failed", datetime.now().isoformat())
                log_task_execution(task_id, "failed", f"配置文件不存在: {config_path}")
        except Exception as e:
            logger.error(f"任务 {task_id} 执行失败: {e}")
            update_task_status_in_db(task_id, "failed", datetime.now().isoformat())
            log_task_execution(task_id, "failed", str(e))
    return executor


def sync_scheduler_with_db() -> None:
    scheduler = get_scheduler()
    tasks = get_all_tasks_from_db()
    for task in tasks:
        if task["enabled"]:
            executor = create_task_executor(task)
            scheduler.add_task(
                task["id"],
                task["trigger_type"],
                task["trigger_args"],
                executor,
            )
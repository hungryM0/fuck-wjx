"""
task 命令 - 定时任务管理
"""

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

import click

from wjx.cli.scheduler import (
    get_scheduler,
    get_all_tasks_from_db,
    get_task_from_db,
    update_task_status_in_db,
    log_task_execution,
    sync_scheduler_with_db,
    create_task_executor,
)
from wjx.utils.app.runtime_paths import get_runtime_directory


@click.group()
@click.pass_context
def task_command(ctx: click.Context) -> None:
    """
    定时任务管理命令

    用于创建、管理和查看定时任务。
    """
    pass


@task_command.command(name="list")
@click.option("--status", "-s", help="按状态筛选 (pending/running/completed/failed)")
@click.option("--format", "-f", type=click.Choice(["table", "json", "simple"]), default="table")
@click.pass_context
def list_tasks(
    ctx: click.Context,
    status: Optional[str],
    format: str,
) -> None:
    """
    列出所有定时任务

    示例:
        fuck-wjx task list
        fuck-wjx task list --status pending --format json
    """
    silent = ctx.obj.get("silent", False)
    tasks = _get_tasks_from_db(status)

    if not tasks:
        if not silent:
            click.echo("\n暂无定时任务")
        return

    if format == "json":
        click.echo(json.dumps(tasks, indent=2, ensure_ascii=False))
    elif format == "simple":
        for task in tasks:
            click.echo(f"{task['id']}: {task['name']} ({task['status']})")
    else:
        _print_tasks_table(tasks)


@task_command.command(name="add")
@click.option("--name", "-n", required=True, help="任务名称")
@click.option("--cron", "-c", help="Cron表达式 (如: 0 9 * * *)")
@click.option("--interval", "-i", help="间隔表达式 (如: hours=1 或 minutes=30)")
@click.option("--config", "-f", required=True, help="配置文件路径")
@click.option("--priority", "-p", type=click.Choice(["high", "normal", "low"]), default="normal")
@click.pass_context
def add_task(
    ctx: click.Context,
    name: str,
    cron: Optional[str],
    interval: Optional[str],
    config: str,
    priority: str,
) -> None:
    """
    添加新的定时任务

    示例:
        fuck-wjx task add --name "daily" --cron "0 9 * * *" --config config.json
        fuck-wjx task add --name "hourly" --interval "hours=1" --config config.json
    """
    silent = ctx.obj.get("silent", False)

    if not cron and not interval:
        click.echo("\n❌ 必须指定 --cron 或 --interval", err=True)
        raise SystemExit(1)

    if cron and interval:
        click.echo("\n❌ 不能同时指定 --cron 和 --interval", err=True)
        raise SystemExit(1)

    config_path = Path(config)
    if not config_path.exists():
        click.echo(f"\n❌ 配置文件不存在: {config}", err=True)
        raise SystemExit(1)

    task_data = {
        "name": name,
        "trigger_type": "cron" if cron else "interval",
        "trigger_args": cron if cron else interval,
        "config_path": str(config_path.absolute()),
        "priority": priority,
        "enabled": True,
    }

    _save_task_to_db(task_data)

    task_id = _get_last_inserted_task_id()
    if task_id:
        scheduler = get_scheduler()
        executor = create_task_executor(task_data)
        scheduler.add_task(task_id, task_data["trigger_type"], task_data["trigger_args"], executor)

    if not silent:
        click.echo(f"\n✅ 定时任务已添加: {name}")
        click.echo(f"   触发类型: {task_data['trigger_type']}")
        click.echo(f"   触发参数: {task_data['trigger_args']}")
        click.echo(f"   优先级: {priority}")


@task_command.command(name="delete")
@click.argument("task_id", type=int)
@click.pass_context
def delete_task(ctx: click.Context, task_id: int) -> None:
    """
    删除定时任务

    示例:
        fuck-wjx task delete 1
    """
    silent = ctx.obj.get("silent", False)

    if _delete_task_from_db(task_id):
        scheduler = get_scheduler()
        scheduler.remove_task(task_id)
        if not silent:
            click.echo(f"\n✅ 任务 {task_id} 已删除")
    else:
        click.echo(f"\n❌ 任务 {task_id} 不存在", err=True)
        raise SystemExit(1)


@task_command.command(name="enable")
@click.argument("task_id", type=int)
@click.pass_context
def enable_task(ctx: click.Context, task_id: int) -> None:
    """
    启用定时任务

    示例:
        fuck-wjx task enable 1
    """
    silent = ctx.obj.get("silent", False)

    task = _get_task_by_id(task_id)
    if not task:
        click.echo(f"\n❌ 任务 {task_id} 不存在", err=True)
        raise SystemExit(1)

    if _update_task_enabled_status(task_id, True):
        scheduler = get_scheduler()
        executor = create_task_executor(task)
        scheduler.add_task(task_id, task["trigger_type"], task["trigger_args"], executor)
        if not silent:
            click.echo(f"\n✅ 任务 {task_id} 已启用")
    else:
        click.echo(f"\n❌ 任务 {task_id} 不存在", err=True)
        raise SystemExit(1)


@task_command.command(name="disable")
@click.argument("task_id", type=int)
@click.pass_context
def disable_task(ctx: click.Context, task_id: int) -> None:
    """
    禁用定时任务

    示例:
        fuck-wjx task disable 1
    """
    silent = ctx.obj.get("silent", False)

    if _update_task_enabled_status(task_id, False):
        scheduler = get_scheduler()
        scheduler.remove_task(task_id)
        if not silent:
            click.echo(f"\n✅ 任务 {task_id} 已禁用")
    else:
        click.echo(f"\n❌ 任务 {task_id} 不存在", err=True)
        raise SystemExit(1)


@task_command.command(name="run")
@click.argument("task_id", type=int)
@click.option("--wait", "-w", is_flag=True, help="等待任务完成")
@click.pass_context
def run_task_now(ctx: click.Context, task_id: int, wait: bool) -> None:
    """
    立即执行定时任务

    示例:
        fuck-wjx task run 1
        fuck-wjx task run 1 --wait
    """
    silent = ctx.obj.get("silent", False)

    task = _get_task_by_id(task_id)
    if not task:
        click.echo(f"\n❌ 任务 {task_id} 不存在", err=True)
        raise SystemExit(1)

    if not silent:
        click.echo(f"\n▶️ 开始执行任务: {task['name']}")

    result = _execute_task(task)

    if result["success"]:
        if not silent:
            click.echo(f"\n✅ 任务执行完成")
            click.echo(f"   成功: {result['success_count']}/{result['total']}")
    else:
        click.echo(f"\n❌ 任务执行失败: {result.get('error', '未知错误')}", err=True)
        raise SystemExit(1)


@task_command.command(name="logs")
@click.argument("task_id", type=int)
@click.option("--limit", "-l", type=int, default=10, help="显示最近N条日志")
@click.pass_context
def show_task_logs(ctx: click.Context, task_id: int, limit: int) -> None:
    """
    显示任务执行日志

    示例:
        fuck-wjx task logs 1
        fuck-wjx task logs 1 --limit 20
    """
    silent = ctx.obj.get("silent", False)

    task = _get_task_by_id(task_id)
    if not task:
        click.echo(f"\n❌ 任务 {task_id} 不存在", err=True)
        raise SystemExit(1)

    logs = _get_task_logs(task_id, limit)
    if not logs:
        if not silent:
            click.echo("\n暂无执行日志")
        return

    click.echo(f"\n任务 '{task['name']}' 执行日志 (最近 {len(logs)} 条):")
    click.echo("-" * 60)
    for log in logs:
        status_icon = {"started": "▶️", "success": "✅", "failed": "❌"}.get(log["status"], "ℹ️")
        click.echo(f"{status_icon} [{log['executed_at']}] {log['message'] or '无消息'}")


@task_command.command(name="sync")
@click.pass_context
def sync_scheduler(ctx: click.Context) -> None:
    """
    同步调度器与数据库

    示例:
        fuck-wjx task sync
    """
    silent = ctx.obj.get("silent", False)

    sync_scheduler_with_db()
    if not silent:
        click.echo("\n✅ 调度器已同步")


def _print_tasks_table(tasks: List[Dict[str, Any]]) -> None:
    """打印任务表格"""
    header = f"{'ID':<4} | {'名称':<20} | {'触发类型':<10} | {'触发参数':<20} | {'状态':<10} | {'优先级':<8}"
    separator = "-" * 90
    click.echo(f"\n{separator}")
    click.echo(header)
    click.echo(separator)
    for task in tasks:
        status = task.get("status", "pending")
        status_display = {
            "pending": "待执行",
            "running": "执行中",
            "success": "成功",
            "failed": "失败",
        }.get(status, status)
        row = (
            f"{task['id']:<4} | "
            f"{task['name'][:18]:<20} | "
            f"{task['trigger_type']:<10} | "
            f"{task['trigger_args'][:18]:<20} | "
            f"{status_display:<10} | "
            f"{task.get('priority', 'normal'):<8}"
        )
        click.echo(row)
    click.echo(separator)
    click.echo(f"共 {len(tasks)} 个任务")


def _execute_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """执行任务"""
    try:
        update_task_status_in_db(task["id"], "running")
        log_task_execution(task["id"], "started", "任务开始执行")
        if not os.path.exists(task["config_path"]):
            raise FileNotFoundError(f"配置文件不存在: {task['config_path']}")
        update_task_status_in_db(task["id"], "success")
        log_task_execution(task["id"], "success", "任务执行成功")
        return {
            "success": True,
            "success_count": 1,
            "total": 1,
        }
    except Exception as e:
        update_task_status_in_db(task["id"], "failed")
        log_task_execution(task["id"], "failed", str(e))
        return {
            "success": False,
            "error": str(e),
        }


def _get_tasks_db_path() -> str:
    """获取任务数据库路径"""
    runtime_dir = get_runtime_directory()
    tasks_dir = os.path.join(runtime_dir, "tasks")
    os.makedirs(tasks_dir, exist_ok=True)
    return os.path.join(tasks_dir, "tasks.db")


def _init_tasks_db() -> None:
    """初始化任务数据库"""
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
            executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        )
    """)
    conn.commit()
    conn.close()


def _get_tasks_from_db(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """从数据库获取任务列表"""
    _init_tasks_db()
    db_path = _get_tasks_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if status:
        cursor.execute("SELECT * FROM tasks WHERE status = ? ORDER BY id DESC", (status,))
    else:
        cursor.execute("SELECT * FROM tasks ORDER BY id DESC")

    tasks = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return tasks


def _get_task_by_id(task_id: int) -> Optional[Dict[str, Any]]:
    """根据ID获取任务"""
    _init_tasks_db()
    db_path = _get_tasks_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def _get_last_inserted_task_id() -> Optional[int]:
    """获取最后插入的任务ID"""
    _init_tasks_db()
    db_path = _get_tasks_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT last_insert_rowid()")
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def _save_task_to_db(task_data: Dict[str, Any]) -> None:
    """保存任务到数据库"""
    _init_tasks_db()
    db_path = _get_tasks_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO tasks (name, trigger_type, trigger_args, config_path, priority, enabled, status)
        VALUES (?, ?, ?, ?, ?, ?, 'pending')
    """, (
        task_data["name"],
        task_data["trigger_type"],
        task_data["trigger_args"],
        task_data["config_path"],
        task_data["priority"],
        1 if task_data["enabled"] else 0,
    ))
    conn.commit()
    conn.close()


def _delete_task_from_db(task_id: int) -> bool:
    """从数据库删除任务"""
    _init_tasks_db()
    db_path = _get_tasks_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
    if not cursor.fetchone():
        conn.close()
        return False
    cursor.execute("DELETE FROM task_logs WHERE task_id = ?", (task_id,))
    cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return True


def _update_task_status(task_id: int, enabled: bool) -> bool:
    """更新任务启用/禁用状态"""
    _init_tasks_db()
    db_path = _get_tasks_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
    if not cursor.fetchone():
        conn.close()
        return False
    cursor.execute(
        "UPDATE tasks SET enabled = ?, status = 'pending' WHERE id = ?",
        (1 if enabled else 0, task_id),
    )
    conn.commit()
    conn.close()
    return True


def _update_task_enabled_status(task_id: int, enabled: bool) -> bool:
    """更新任务启用/禁用状态"""
    return _update_task_status(task_id, enabled)


def _get_task_logs(task_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    """获取任务执行日志"""
    _init_tasks_db()
    db_path = _get_tasks_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM task_logs WHERE task_id = ? ORDER BY executed_at DESC LIMIT ?",
        (task_id, limit),
    )
    logs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return logs
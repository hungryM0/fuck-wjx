"""
CLI 命令模块

包含所有 CLI 子命令的实现
"""

from wjx.cli.commands.run import run_command
from wjx.cli.commands.parse import parse_command
from wjx.cli.commands.config import config_command
from wjx.cli.commands.task import task_command
from wjx.cli.commands.completion import completion_command
from wjx.cli.commands.report import report_command

__all__ = [
    "run_command",
    "parse_command",
    "config_command",
    "task_command",
    "completion_command",
    "report_command",
]
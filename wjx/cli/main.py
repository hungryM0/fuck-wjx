"""
CLI 主入口 - 使用 Click 框架
"""

import sys
import logging
from typing import Optional

import click

from wjx.cli.commands.run import run_command
from wjx.cli.commands.parse import parse_command
from wjx.cli.commands.config import config_command
from wjx.cli.commands.task import task_command
from wjx.cli.commands.completion import completion_command
from wjx.cli.commands.report import report_command


@click.group()
@click.version_option(version="1.0.0", prog_name="fuck-wjx")
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], case_sensitive=False),
    default="INFO",
    help="设置日志级别",
)
@click.option("--verbose", "-v", is_flag=True, help="启用详细输出")
@click.option("--silent", "-s", is_flag=True, help="静默模式，最小化输出")
@click.pass_context
def cli(ctx: click.Context, log_level: str, verbose: bool, silent: bool) -> None:
    """
    fuck-wjx - 问卷星速填 CLI 工具

    一个支持命令行操作的问卷星自动填写工具，支持自定义答案分布与智能配置。
    """
    ctx.ensure_object(dict)
    ctx.obj["log_level"] = log_level.upper()
    ctx.obj["verbose"] = verbose
    ctx.obj["silent"] = silent

    _setup_logging(log_level.upper(), verbose)


def _setup_logging(level: str, verbose: bool) -> None:
    """配置日志系统"""
    log_format = "%(asctime)s | %(levelname)-8s | %(message)s"
    if verbose:
        log_format = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"

    logging.basicConfig(
        level=getattr(logging, level),
        format=log_format,
        datefmt="%Y-%m-%d %H:%M:%S",
    )


cli.add_command(run_command, name="run")
cli.add_command(parse_command, name="parse")
cli.add_command(config_command, name="config")
cli.add_command(task_command, name="task")
cli.add_command(completion_command, name="completion")
cli.add_command(report_command, name="report")


def main() -> int:
    """CLI 主入口函数"""
    try:
        return cli(obj={})
    except KeyboardInterrupt:
        click.echo("\n\n⚠️ 操作已取消", err=True)
        return 130
    except Exception as e:
        click.echo(f"\n❌ 错误: {e}", err=True)
        if "--debug" in sys.argv or "-d" in sys.argv:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
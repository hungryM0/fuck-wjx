"""
fuck-wjx 命令行接口 (CLI)

提供无GUI的命令行界面，支持批处理和自动化执行。

使用方式:
    fuck-wjx run --url <url> --config <config.json> --count 100 --concurrency 5
    fuck-wjx parse --url <url>
    fuck-wjx config generate
    fuck-wjx task list
    fuck-wjx task add --cron "0 9 * * *" --config config.json
"""

from wjx.cli.main import cli

__all__ = ["cli"]
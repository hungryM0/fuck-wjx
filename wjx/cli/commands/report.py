"""
report 命令 - 日志与报告管理
"""

import click
from wjx.cli.reports import get_report_generator


@click.group()
@click.pass_context
def report_command(ctx: click.Context) -> None:
    """
    日志与报告管理命令

    用于查看、导出和管理执行报告。
    """
    pass


@report_command.command(name="list")
@click.option("--format", "-f", type=click.Choice(["table", "json"]), default="table")
@click.pass_context
def list_reports(ctx: click.Context, format: str) -> None:
    """
    列出所有报告

    示例:
        fuck-wjx report list
        fuck-wjx report list --format json
    """
    generator = get_report_generator()
    reports = generator.get_reports_list()

    if not reports:
        click.echo("\n暂无报告")
        return

    if format == "json":
        import json
        click.echo(json.dumps(reports, indent=2, ensure_ascii=False))
    else:
        click.echo(f"\n{'文件名':<40} | {'大小':<10} | {'修改时间':<25}")
        click.echo("-" * 80)
        for report in reports:
            size = report["size"]
            size_str = f"{size} B" if size < 1024 else f"{size/1024:.1f} KB"
            click.echo(f"{report['filename']:<40} | {size_str:<10} | {report['modified']:<25}")
        click.echo(f"\n共 {len(reports)} 个报告")


@report_command.command(name="show")
@click.argument("filename")
@click.pass_context
def show_report(ctx: click.Context, filename: str) -> None:
    """
    显示报告内容

    示例:
        fuck-wjx report show report_20240101_120000.json
    """
    import json
    generator = get_report_generator()
    reports = generator.get_reports_list()

    report_file = next((r for r in reports if r["filename"] == filename), None)
    if not report_file:
        click.echo(f"\n❌ 报告不存在: {filename}", err=True)
        raise SystemExit(1)

    try:
        with open(report_file["filepath"], "r", encoding="utf-8") as f:
            content = json.load(f)
        click.echo(json.dumps(content, indent=2, ensure_ascii=False))
    except Exception as e:
        click.echo(f"\n❌ 读取报告失败: {e}", err=True)
        raise SystemExit(1)


@report_command.command(name="export")
@click.argument("filename")
@click.option("--format", "-f", type=click.Choice(["json", "text"]), default="json")
@click.pass_context
def export_report(ctx: click.Context, filename: str, format: str) -> None:
    """
    导出报告

    示例:
        fuck-wjx report export report_20240101_120000.json
        fuck-wjx report export report_20240101_120000.json --format text
    """
    generator = get_report_generator()
    reports = generator.get_reports_list()

    report_file = next((r for r in reports if r["filename"] == filename), None)
    if not report_file:
        click.echo(f"\n❌ 报告不存在: {filename}", err=True)
        raise SystemExit(1)

    try:
        with open(report_file["filepath"], "r", encoding="utf-8") as f:
            import json
            content = json.load(f)

        output_path = generator.save_report(content, filename.rsplit(".", 1)[0], format)
        click.echo(f"\n✅ 报告已导出: {output_path}")
    except Exception as e:
        click.echo(f"\n❌ 导出报告失败: {e}", err=True)
        raise SystemExit(1)


@report_command.command(name="delete")
@click.argument("filename")
@click.pass_context
def delete_report(ctx: click.Context, filename: str) -> None:
    """
    删除报告

    示例:
        fuck-wjx report delete report_20240101_120000.json
    """
    generator = get_report_generator()
    if generator.delete_report(filename):
        click.echo(f"\n✅ 报告已删除: {filename}")
    else:
        click.echo(f"\n❌ 报告不存在: {filename}", err=True)
        raise SystemExit(1)
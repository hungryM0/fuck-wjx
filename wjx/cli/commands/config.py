"""
config 命令 - 配置管理
"""

from pathlib import Path
from typing import Optional

import click

from wjx.utils.io.load_save import RuntimeConfig, serialize_runtime_config


@click.group()
@click.pass_context
def config_command(ctx: click.Context) -> None:
    """
    配置管理命令

    用于生成、验证和查看配置文件。
    """
    pass


@config_command.command(name="generate")
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default="wjx_config.json",
    help="输出配置文件路径 (默认: wjx_config.json)",
)
@click.option(
    "--template",
    "-t",
    type=click.Choice(["default", "simple", "full"]),
    default="default",
    help="配置模板 (默认: default)",
)
@click.pass_context
def generate_config(
    ctx: click.Context,
    output: str,
    template: str,
) -> None:
    """
    生成配置文件模板

    示例:
        fuck-wjx config generate
        fuck-wjx config generate --template full --output my_config.json
    """
    silent = ctx.obj.get("silent", False)

    template_data = _get_template(template)

    output_path = Path(output)
    if output_path.exists() and not silent:
        click.confirm(f"文件 {output} 已存在，是否覆盖？", abort=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    import json
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(template_data, f, indent=2, ensure_ascii=False)

    if not silent:
        click.echo(f"\n✅ 配置文件已生成: {output}")
        click.echo(f"   模板类型: {template}")


@config_command.command(name="validate")
@click.argument("config_file", type=click.Path(exists=True))
@click.pass_context
def validate_config(
    ctx: click.Context,
    config_file: str,
) -> None:
    """
    验证配置文件格式和内容

    示例:
        fuck-wjx config validate config.json
    """
    silent = ctx.obj.get("silent", False)
    verbose = ctx.obj.get("verbose", False)

    try:
        import json
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        errors = _validate_config_data(data)

        if errors:
            click.echo(f"\n❌ 配置文件验证失败:", err=True)
            for error in errors:
                click.echo(f"   - {error}", err=True)
            raise SystemExit(1)
        else:
            if not silent:
                click.echo(f"\n✅ 配置文件验证通过")
                if verbose:
                    click.echo(f"   文件: {config_file}")
                    click.echo(f"   题目数量: {len(data.get('questions', []))}")

    except json.JSONDecodeError as e:
        click.echo(f"\n❌ JSON 格式错误: {e}", err=True)
        raise SystemExit(1)


@config_command.command(name="show")
@click.argument("config_file", type=click.Path(exists=True))
@click.option(
    "--key",
    "-k",
    help="只显示指定配置项",
)
@click.pass_context
def show_config(
    ctx: click.Context,
    config_file: str,
    key: Optional[str],
) -> None:
    """
    显示配置文件内容

    示例:
        fuck-wjx config show config.json
        fuck-wjx config show config.json --key questions
    """
    import json

    with open(config_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    if key:
        if key in data:
            import yaml
            click.echo(yaml.dump({key: data[key]}, allow_unicode=True, default_flow_style=False))
        else:
            click.echo(f"配置项 '{key}' 不存在", err=True)
            raise SystemExit(1)
    else:
        import yaml
        click.echo(yaml.dump(data, allow_unicode=True, default_flow_style=False))


def _get_template(template_type: str) -> dict:
    """获取配置模板"""
    templates = {
        "default": {
            "version": 3,
            "url": "",
            "title": "",
            "target_count": 10,
            "num_threads": 2,
            "random_ip_enabled": False,
            "random_ua_enabled": False,
            "questions": [],
        },
        "simple": {
            "version": 3,
            "url": "https://www.wjx.cn/vm/XXXX.aspx",
            "title": "简单问卷示例",
            "target_count": 5,
            "num_threads": 1,
            "questions": [
                {
                    "id": 1,
                    "type": "single",
                    "title": "您的性别是？",
                    "options": ["男", "女"],
                    "probability": [0.5, 0.5],
                },
            ],
        },
        "full": {
            "version": 3,
            "url": "https://www.wjx.cn/vm/XXXX.aspx",
            "title": "完整配置示例",
            "target_count": 100,
            "num_threads": 5,
            "random_ip_enabled": True,
            "random_ua_enabled": True,
            "duration_control": {
                "enabled": True,
                "min_duration": 30,
                "max_duration": 120,
            },
            "questions": [
                {
                    "id": 1,
                    "type": "single",
                    "title": "单选题示例",
                    "options": ["A", "B", "C", "D"],
                    "probability": [0.25, 0.25, 0.25, 0.25],
                },
                {
                    "id": 2,
                    "type": "multiple",
                    "title": "多选题示例",
                    "options": ["选项1", "选项2", "选项3"],
                    "min_select": 1,
                    "max_select": 2,
                    "probability": [[0.6, 0.4], [0.4, 0.6], [0.5, 0.5]],
                },
                {
                    "id": 3,
                    "type": "text",
                    "title": "填空题示例",
                    "required": True,
                    "ai_fill": True,
                    "fill_texts": ["测试答案1", "测试答案2"],
                },
            ],
        },
    }
    return templates.get(template_type, templates["default"])


def _validate_config_data(data: dict) -> list:
    """验证配置数据"""
    errors = []

    if "version" not in data:
        errors.append("缺少 'version' 字段")

    if "url" not in data:
        errors.append("缺少 'url' 字段")
    elif not data["url"]:
        errors.append("'url' 不能为空")

    target_count = data.get("target_count", 0)
    if not isinstance(target_count, int) or target_count < 1:
        errors.append("'target_count' 必须是大于0的整数")

    num_threads = data.get("num_threads", 0)
    if not isinstance(num_threads, int) or num_threads < 1:
        errors.append("'num_threads' 必须是大于0的整数")

    questions = data.get("questions", [])
    if not isinstance(questions, list):
        errors.append("'questions' 必须是数组")
    else:
        for i, q in enumerate(questions):
            if "id" not in q:
                errors.append(f"题目 {i+1}: 缺少 'id' 字段")
            if "type" not in q:
                errors.append(f"题目 {i+1}: 缺少 'type' 字段")

    return errors
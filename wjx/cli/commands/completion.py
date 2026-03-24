"""
completion 命令 - Shell 补全脚本生成
"""

import os
import sys

import click


def _get_default_shell() -> str:
    """获取默认Shell类型"""
    if sys.platform == "win32":
        return "powershell"
    shell = os.environ.get("SHELL", "")
    if "zsh" in shell:
        return "zsh"
    elif "fish" in shell:
        return "fish"
    return "bash"


def _generate_completion_script(shell: str) -> str:
    """生成补全脚本"""
    scripts = {
        "bash": _bash_completion,
        "zsh": _zsh_completion,
        "fish": _fish_completion,
        "powershell": _powershell_completion,
    }
    return scripts.get(shell, _bash_completion)()


@click.command(name="completion")
@click.option(
    "--shell",
    "-s",
    type=click.Choice(["bash", "zsh", "fish", "powershell"]),
    default="powershell",
    help="目标Shell类型",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="输出文件路径 (默认: 输出到stdout)",
)
@click.pass_context
def completion_command(ctx: click.Context, shell: str, output: str) -> None:
    """
    生成 Shell 补全脚本

    示例:
        # Bash
        fuck-wjx completion --shell bash >> ~/.bashrc

        # Zsh
        fuck-wjx completion --shell zsh >> ~/.zshrc

        # PowerShell
        fuck-wjx completion --shell powershell >> $PROFILE
    """
    script = _generate_completion_script(shell)

    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(script)
        click.echo(f"补全脚本已保存到: {output}")
    else:
        click.echo(script)


def _bash_completion() -> str:
    """Bash 补全脚本"""
    return '''# fuck-wjx bash completion
_fuck_wjx()
{
    local cur prev opts subcommands
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    subcommands="run parse config task completion"
    opts="--help --version --verbose --silent --log-level"

    case "${prev}" in
        fuck-wjx)
            COMPREPLY=($(compgen -W "${subcommands} ${opts}" -- "${cur}"))
            return 0
            ;;
        run)
            opts="--url --config --count --concurrency --random-ip --random-ua --output --overrides"
            COMPREPLY=($(compgen -W "${opts}" -- "${cur}"))
            return 0
            ;;
        parse)
            opts="--url --output --format"
            COMPREPLY=($(compgen -W "${opts}" -- "${cur}"))
            return 0
            ;;
        config)
            COMPREPLY=($(compgen -W "generate validate show" -- "${cur}"))
            return 0
            ;;
        task)
            COMPREPLY=($(compgen -W "list add delete enable disable run" -- "${cur}"))
            return 0
            ;;
        --log-level)
            COMPREPLY=($(compgen -W "DEBUG INFO WARNING ERROR CRITICAL" -- "${cur}"))
            return 0
            ;;
        --format)
            COMPREPLY=($(compgen -W "json yaml text" -- "${cur}"))
            return 0
            ;;
        *)
            ;;
    esac

    COMPREPLY=($(compgen -W "${opts}" -- "${cur}"))
    return 0
}

complete -F _fuck_wjx fuck-wjx
'''


def _zsh_completion() -> str:
    """Zsh 补全脚本"""
    return '''# fuck-wjx zsh completion
_fuck_wjx() {
    local -a commands opts subcommands

    commands=(
        "run:执行问卷填写任务"
        "parse:解析问卷结构"
        "config:配置管理"
        "task:定时任务管理"
        "completion:生成补全脚本"
    )

    opts=(
        "--help:显示帮助信息"
        "--version:显示版本信息"
        "--verbose:启用详细输出"
        "--silent:静默模式"
        "--log-level:设置日志级别"
    )

    subcommands=(
        "run:run"
        "parse:parse"
        "config:config"
        "task:task"
        "completion:completion"
    )

    case "${words[1]}" in
        run)
            _arguments -s \\
                '(--url -u)'{--url,-u}'[问卷链接]:URL:' \\
                '(--config -c)'{--config,-c}'[配置文件]:file:_files' \\
                '(--count -n)'{--count,-n}'[目标份数]:number:' \\
                '(--concurrency -j)'{--concurrency,-j}'[并发数]:number:' \\
                '(--random-ip)'{--random-ip}'[启用随机IP]' \\
                '(--random-ua)'{--random-ua}'[启用随机UA]' \\
                '(--output -o)'{--output,-o}'[输出文件]:file:_files'
            ;;
        parse)
            _arguments -s \\
                '(--url -u)'{--url,-u}'[问卷链接]:URL:' \\
                '(--output -o)'{--output,-o}'[输出文件]:file:_files' \\
                '(--format -f)'{--format,-f}'[输出格式]:(json yaml text)'
            ;;
        task)
            local -a task_cmds
            task_cmds=(
                "list:列出任务"
                "add:添加任务"
                "delete:删除任务"
                "enable:启用任务"
                "disable:禁用任务"
                "run:立即执行任务"
            )
            _describe 'task command' task_cmds
            ;;
        config)
            local -a config_cmds
            config_cmds=(
                "generate:生成配置"
                "validate:验证配置"
                "show:显示配置"
            )
            _describe 'config command' config_cmds
            ;;
        *)
            _describe 'command' commands
            ;;
    esac

    return 0
}

compdef _fuck_wjx fuck-wjx
'''


def _fish_completion() -> str:
    """Fish 补全脚本"""
    return '''# fuck-wjx fish completion
complete -c fuck-wjx -n "__fish_use_subcommand" -a "run" -d "执行问卷填写任务"
complete -c fuck-wjx -n "__fish_use_subcommand" -a "parse" -d "解析问卷结构"
complete -c fuck-wjx -n "__fish_use_subcommand" -a "config" -d "配置管理"
complete -c fuck-wjx -n "__fish_use_subcommand" -a "task" -d "定时任务管理"
complete -c fuck-wjx -n "__fish_use_subcommand" -a "completion" -d "生成补全脚本"

# run 命令补全
complete -c fuck-wjx -n "__fish_seen_subcommand_from run" -l url -s u -d "问卷链接" -r
complete -c fuck-wjx -n "__fish_seen_subcommand_from run" -l config -s c -d "配置文件" -r -f
complete -c fuck-wjx -n "__fish_seen_subcommand_from run" -l count -s n -d "目标份数" -r
complete -c fuck-wjx -n "__fish_seen_subcommand_from run" -l concurrency -s j -d "并发数" -r
complete -c fuck-wjx -n "__fish_seen_subcommand_from run" -l random-ip -d "启用随机IP"
complete -c fuck-wjx -n "__fish_seen_subcommand_from run" -l random-ua -d "启用随机UA"
complete -c fuck-wjx -n "__fish_seen_subcommand_from run" -l output -s o -d "输出文件" -r -f

# parse 命令补全
complete -c fuck-wjx -n "__fish_seen_subcommand_from parse" -l url -s u -d "问卷链接" -r
complete -c fuck-wjx -n "__fish_seen_subcommand_from parse" -l output -s o -d "输出文件" -r -f
complete -c fuck-wjx -n "__fish_seen_subcommand_from parse" -l format -s f -d "输出格式" -a "json yaml text"

# 全局选项
complete -c fuck-wjx -l help -s h -d "显示帮助"
complete -c fuck-wjx -l version -d "显示版本"
complete -c fuck-wjx -l verbose -s v -d "详细输出"
complete -c fuck-wjx -l silent -s s -d "静默模式"
complete -c fuck-wjx -l log-level -d "日志级别" -a "DEBUG INFO WARNING ERROR CRITICAL"
'''


def _powershell_completion() -> str:
    """PowerShell 补全脚本"""
    return '''# fuck-wjx PowerShell completion

$script:MyCommand_Completion = {
    param($wordToComplete, $commandAst, $cursorPosition)

    $subcommands = @(
        @{ Name = "run"; Description = "执行问卷填写任务" }
        @{ Name = "parse"; Description = "解析问卷结构" }
        @{ Name = "config"; Description = "配置管理" }
        @{ Name = "task"; Description = "定时任务管理" }
        @{ Name = "completion"; Description = "生成补全脚本" }
    )

    $global_opts = @(
        "--help", "-h", "--version", "--verbose", "-v", "--silent", "-s", "--log-level"
    )

    $run_opts = @(
        "--url", "-u", "--config", "-c", "--count", "-n",
        "--concurrency", "-j", "--random-ip", "--random-ua", "--output", "-o", "--overrides"
    )

    $parse_opts = @(
        "--url", "-u", "--output", "-o", "--format", "-f"
    )

    $task_cmds = @("list", "add", "delete", "enable", "disable", "run")
    $config_cmds = @("generate", "validate", "show")

    $command = $commandAst.CommandElements[0].Value

    if ($command -eq "fuck-wjx") {
        if ($commandAst.CommandElements.Count -eq 1) {
            $subcommands | ForEach-Object {
                [System.Management.Automation.CompletionResult]::new($_.Name, $_.Name, "Command", $_.Description)
            }
            $global_opts | ForEach-Object {
                [System.Management.Automation.CompletionResult]::new($_, $_, "GlobalParameter", $_)
            }
        }
        else {
            $subcmd = $commandAst.CommandElements[1].Value
            switch ($subcmd) {
                "run" { $run_opts | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object { [System.Management.Automation.CompletionResult]::new($_, $_, "Parameter", $_) } }
                "parse" { $parse_opts | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object { [System.Management.Automation.CompletionResult]::new($_, $_, "Parameter", $_) } }
                "task" { $task_cmds | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object { [System.Management.Automation.CompletionResult]::new($_, $_, "Parameter", $_) } }
                "config" { $config_cmds | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object { [System.Management.Automation.CompletionResult]::new($_, $_, "Parameter", $_) } }
            }
        }
    }
}

Register-ArgumentCompleter -CommandName "fuck-wjx" -ScriptBlock $script:MyCommand_Completion
'''
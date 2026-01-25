# -*- coding: utf-8 -*-
"""
GitHub Hosts 优化工具

通过修改 hosts 文件加速 GitHub 访问
"""

import ctypes
import logging
import os
import re
import sys
import tempfile
from typing import Optional, Tuple

import requests

# GitHub520 hosts API
GITHUB_HOSTS_API = "https://raw.hellogithub.com/hosts"

# hosts 文件标记
HOSTS_MARKER_START = "# FuckWjx GitHub Hosts Start"
HOSTS_MARKER_END = "# FuckWjx GitHub Hosts End"

# Windows hosts 文件路径
HOSTS_FILE_PATH = r"C:\Windows\System32\drivers\etc\hosts"

# 需要加速的域名
GITHUB_DOMAINS = ["github.com", "api.github.com", "raw.githubusercontent.com"]


def is_admin() -> bool:
    """检查当前是否以管理员权限运行"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def fetch_github_hosts() -> Optional[str]:
    """从 GitHub520 API 获取最新的 hosts 配置"""
    try:
        resp = requests.get(GITHUB_HOSTS_API, timeout=15)
        resp.raise_for_status()
        content = resp.text
        
        # 提取我们需要的域名
        lines = []
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # 检查是否包含我们需要的域名
            for domain in GITHUB_DOMAINS:
                if domain in line:
                    lines.append(line)
                    break
        
        if not lines:
            logging.warning("未能从 API 获取到有效的 hosts 配置")
            return None
        
        return "\n".join(lines)
    except requests.exceptions.Timeout:
        logging.error("获取 GitHub hosts 超时")
        return None
    except Exception as exc:
        logging.error(f"获取 GitHub hosts 失败: {exc}")
        return None


def check_hosts_status() -> Tuple[bool, str]:
    """
    检查当前 hosts 文件状态
    
    Returns:
        (是否已添加配置, 当前配置内容)
    """
    try:
        with open(HOSTS_FILE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        try:
            with open(HOSTS_FILE_PATH, "r", encoding="gbk") as f:
                content = f.read()
        except Exception:
            return False, ""
    except Exception:
        return False, ""
    
    # 查找标记区块
    pattern = re.compile(
        rf"{re.escape(HOSTS_MARKER_START)}\s*(.*?)\s*{re.escape(HOSTS_MARKER_END)}",
        re.DOTALL
    )
    match = pattern.search(content)
    if match:
        return True, match.group(1).strip()
    return False, ""


def _read_hosts_file() -> str:
    """读取 hosts 文件内容"""
    try:
        with open(HOSTS_FILE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(HOSTS_FILE_PATH, "r", encoding="gbk") as f:
            return f.read()


def _write_hosts_file(content: str) -> bool:
    """写入 hosts 文件内容"""
    try:
        with open(HOSTS_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except PermissionError:
        logging.error("没有权限写入 hosts 文件，需要管理员权限")
        return False
    except Exception as exc:
        logging.error(f"写入 hosts 文件失败: {exc}")
        return False


def update_hosts_file(hosts_entries: str) -> Tuple[bool, str]:
    """
    更新 hosts 文件，添加 GitHub 加速配置
    
    Args:
        hosts_entries: 要添加的 hosts 条目
        
    Returns:
        (是否成功, 消息)
    """
    try:
        content = _read_hosts_file()
        
        # 构建新的配置块
        new_block = f"\n{HOSTS_MARKER_START}\n{hosts_entries}\n{HOSTS_MARKER_END}\n"
        
        # 检查是否已存在配置
        pattern = re.compile(
            rf"{re.escape(HOSTS_MARKER_START)}.*?{re.escape(HOSTS_MARKER_END)}\n?",
            re.DOTALL
        )
        
        if pattern.search(content):
            # 替换现有配置
            content = pattern.sub(new_block, content)
        else:
            # 添加新配置
            content = content.rstrip() + new_block
        
        if _write_hosts_file(content):
            return True, "GitHub hosts 配置已更新"
        else:
            return False, "写入 hosts 文件失败，请确保以管理员权限运行"
    except Exception as exc:
        return False, f"更新 hosts 文件失败: {exc}"


def remove_hosts_entries() -> Tuple[bool, str]:
    """
    移除本程序添加的 hosts 配置
    
    Returns:
        (是否成功, 消息)
    """
    try:
        content = _read_hosts_file()
        
        # 查找并移除配置块
        pattern = re.compile(
            rf"\n?{re.escape(HOSTS_MARKER_START)}.*?{re.escape(HOSTS_MARKER_END)}\n?",
            re.DOTALL
        )
        
        if not pattern.search(content):
            return True, "未找到本程序添加的 hosts 配置"
        
        content = pattern.sub("\n", content)
        # 清理多余空行
        content = re.sub(r"\n{3,}", "\n\n", content)
        
        if _write_hosts_file(content):
            return True, "已移除 GitHub hosts 配置"
        else:
            return False, "写入 hosts 文件失败，请确保以管理员权限运行"
    except Exception as exc:
        return False, f"移除 hosts 配置失败: {exc}"


def run_hosts_operation_as_admin(operation: str) -> Tuple[bool, str]:
    """
    以管理员权限执行 hosts 操作
    
    Args:
        operation: "add" 添加配置, "remove" 移除配置
        
    Returns:
        (是否成功, 消息)
    """
    if is_admin():
        # 已经是管理员权限，直接执行
        if operation == "add":
            hosts_entries = fetch_github_hosts()
            if not hosts_entries:
                return False, "无法获取 GitHub hosts 配置，请检查网络连接"
            return update_hosts_file(hosts_entries)
        elif operation == "remove":
            return remove_hosts_entries()
        else:
            return False, f"未知操作: {operation}"
    
    # 需要请求管理员权限 - 创建完全独立的临时脚本
    result_path = os.path.join(tempfile.gettempdir(), "hosts_result.txt")
    
    # 内联所有必要的代码，不依赖任何项目模块
    script_content = f'''# -*- coding: utf-8 -*-
import re
import requests

GITHUB_HOSTS_API = "https://raw.hellogithub.com/hosts"
HOSTS_MARKER_START = "# FuckWjx GitHub Hosts Start"
HOSTS_MARKER_END = "# FuckWjx GitHub Hosts End"
HOSTS_FILE_PATH = r"C:\\Windows\\System32\\drivers\\etc\\hosts"
GITHUB_DOMAINS = ["github.com", "api.github.com", "raw.githubusercontent.com"]
RESULT_PATH = r"{result_path}"

def fetch_github_hosts():
    try:
        resp = requests.get(GITHUB_HOSTS_API, timeout=15)
        resp.raise_for_status()
        lines = []
        for line in resp.text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            for domain in GITHUB_DOMAINS:
                if domain in line:
                    lines.append(line)
                    break
        return "\\n".join(lines) if lines else None
    except Exception:
        return None

def read_hosts():
    try:
        with open(HOSTS_FILE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(HOSTS_FILE_PATH, "r", encoding="gbk") as f:
            return f.read()

def write_hosts(content):
    with open(HOSTS_FILE_PATH, "w", encoding="utf-8") as f:
        f.write(content)

def update_hosts(entries):
    content = read_hosts()
    new_block = f"\\n{{HOSTS_MARKER_START}}\\n{{entries}}\\n{{HOSTS_MARKER_END}}\\n"
    pattern = re.compile(rf"{{re.escape(HOSTS_MARKER_START)}}.*?{{re.escape(HOSTS_MARKER_END)}}\\n?", re.DOTALL)
    if pattern.search(content):
        content = pattern.sub(new_block, content)
    else:
        content = content.rstrip() + new_block
    write_hosts(content)
    return True, "GitHub hosts 配置已更新"

def remove_hosts():
    content = read_hosts()
    pattern = re.compile(rf"\\n?{{re.escape(HOSTS_MARKER_START)}}.*?{{re.escape(HOSTS_MARKER_END)}}\\n?", re.DOTALL)
    if not pattern.search(content):
        return True, "未找到本程序添加的 hosts 配置"
    content = pattern.sub("\\n", content)
    content = re.sub(r"\\n{{3,}}", "\\n\\n", content)
    write_hosts(content)
    return True, "已移除 GitHub hosts 配置"

try:
    operation = "{operation}"
    if operation == "add":
        entries = fetch_github_hosts()
        if entries:
            success, msg = update_hosts(entries)
        else:
            success, msg = False, "无法获取 GitHub hosts 配置"
    elif operation == "remove":
        success, msg = remove_hosts()
    else:
        success, msg = False, "未知操作"
except PermissionError:
    success, msg = False, "没有权限修改 hosts 文件"
except Exception as e:
    success, msg = False, str(e)

with open(RESULT_PATH, "w", encoding="utf-8") as f:
    f.write(f"{{1 if success else 0}}|{{msg}}")
'''
    
    script_path = os.path.join(tempfile.gettempdir(), "hosts_admin_script.py")
    
    try:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_content)
        
        if os.path.exists(result_path):
            os.remove(result_path)
        
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{script_path}"', None, 0
        )
        
        if ret <= 32:
            return False, "用户取消了管理员权限请求"
        
        import time
        for _ in range(30):
            time.sleep(1)
            if os.path.exists(result_path):
                with open(result_path, "r", encoding="utf-8") as f:
                    result = f.read().strip()
                parts = result.split("|", 1)
                if len(parts) == 2:
                    return parts[0] == "1", parts[1]
                break
        
        return False, "操作超时或执行失败"
    except Exception as exc:
        return False, f"执行管理员操作失败: {exc}"
    finally:
        for path in [script_path, result_path]:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

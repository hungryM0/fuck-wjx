"""Markdown 处理工具函数"""
import re


def convert_github_admonitions(text: str) -> str:
    """将 GitHub Flavored Markdown 的 admonition 语法转换为标准格式
    
    支持的类型: NOTE, TIP, IMPORTANT, WARNING, CAUTION
    """
    admonition_map = {
        "NOTE": "**注意：**",
        "TIP": "**提示：**",
        "IMPORTANT": "**重要：**",
        "WARNING": "**警告：**",
        "CAUTION": "**警告：**",
    }
    
    def replace_multiline(match):
        admonition_type = match.group(1).upper()
        content_lines = match.group(2)
        content = re.sub(r'^>\s?', '', content_lines, flags=re.MULTILINE).strip()
        prefix = admonition_map.get(admonition_type, f"**{admonition_type}：**")
        return f"{prefix}\n\n{content}"
    
    # 匹配多行 admonition: > [!TYPE]\n> content
    pattern = r'>\s*\[!(\w+)\]\s*\n((?:>.*\n?)*)'
    text = re.sub(pattern, replace_multiline, text)
    
    def replace_admonition(match):
        admonition_type = match.group(1).upper()
        content = match.group(2).strip()
        prefix = admonition_map.get(admonition_type, f"**{admonition_type}：**")
        return f"{prefix} {content}"
    
    # 匹配单行 admonition: > [!TYPE] content
    single_pattern = r'>\s*\[!(\w+)\]\s*(.+)'
    text = re.sub(single_pattern, replace_admonition, text)
    
    return text

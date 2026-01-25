"""Markdown 处理工具函数"""
import re


def strip_markdown(text: str) -> str:
    """清理 Markdown 格式，保留粗体、标题和emoji"""
    if not text:
        return "暂无更新说明"
    # 移除图片 ![alt](url) 或 ![alt][ref]
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'!\[.*?\]\[.*?\]', '', text)
    # 移除 HTML img 标签
    text = re.sub(r'<img[^>]*/?>', '', text, flags=re.IGNORECASE)
    # 移除仅指向本页锚点的链接，避免 Qt 输出 “link # is undefined”
    text = re.sub(r'\[([^\]]+)\]\(#.*?\)', r'\1', text)
    text = re.sub(r'<a[^>]+href="#[^"]*"[^>]*>(.*?)</a>', r'\1', text, flags=re.IGNORECASE | re.DOTALL)
    # 移除分隔线
    text = re.sub(r'^---+\s*$', '', text, flags=re.MULTILINE)
    # 移除删除线标记 ~~text~~ -> text
    text = re.sub(r'~~(.+?)~~', r'\1', text)
    # 移除下划线格式 __text__ -> text（但保留粗体 **text**）
    text = re.sub(r'__(.+?)__', r'\1', text)
    # 移除多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


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

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

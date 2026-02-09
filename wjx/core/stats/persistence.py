"""统计数据持久化"""

import hashlib
import json
import os
import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse

from wjx.core.stats.models import OptionStats, QuestionStats, SurveyStats
from wjx.utils.app.runtime_paths import _get_project_root

STATS_DIR_NAME = "stats"


def _ensure_stats_dir() -> str:
    """确保统计目录存在（项目根目录下的 stats/）"""
    base = _get_project_root()
    stats_dir = os.path.join(base, STATS_DIR_NAME)
    os.makedirs(stats_dir, exist_ok=True)
    return stats_dir


def _sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    # 替换 Windows 文件名非法字符为下划线
    sanitized = re.sub(r'[\\/:*?"<>|]', '_', name)
    # 去除首尾空白和点号
    sanitized = sanitized.strip('. ')
    # 限制长度
    if len(sanitized) > 50:
        sanitized = sanitized[:50].rstrip('. ')
    return sanitized or "未命名问卷"


def _generate_stats_filename(stats: SurveyStats) -> str:
    """生成统计文件名：标题.json（固定文件名，覆盖保存）
    
    Args:
        stats: 统计数据对象
    
    Returns:
        文件名字符串
    """
    # 获取标题，如果没有则使用 URL 路径部分
    if stats.survey_title:
        title = _sanitize_filename(stats.survey_title)
    else:
        parsed = urlparse(stats.survey_url)
        path_part = parsed.path.replace("/", "_").strip("_")
        title = path_part if path_part else "未命名问卷"
    
    # 不再包含提交份数，固定文件名（每次保存覆盖旧文件）
    return f"{title}.json"


def save_stats(stats: SurveyStats, path: Optional[str] = None, target_num: Optional[int] = None) -> str:
    """保存统计数据到文件

    Args:
        stats: 统计数据对象
        path: 可选的保存路径，不指定则自动生成
        target_num: 目标执行份数（已废弃，保留仅为向后兼容）

    Returns:
        保存的文件路径
    """
    if path is None:
        stats_dir = _ensure_stats_dir()
        filename = _generate_stats_filename(stats)
        path = os.path.join(stats_dir, filename)

    # 序列化数据
    data = {
        "version": 1,
        "survey_url": stats.survey_url,
        "survey_title": stats.survey_title,
        "created_at": stats.created_at,
        "updated_at": stats.updated_at,
        "total_submissions": stats.total_submissions,
        "failed_submissions": stats.failed_submissions,
        "questions": {}
    }

    # 保存信效度分析结果（如果有）
    if stats.reliability_validity is not None:
        data["reliability_validity"] = stats.reliability_validity

    for q_num, q_stats in stats.questions.items():
        q_data = {
            "question_type": q_stats.question_type,
            "question_title": q_stats.question_title,
            "total_responses": q_stats.total_responses,
            "options": {
                str(idx): {"count": opt.count, "text": opt.option_text}
                for idx, opt in q_stats.options.items()
            }
        }
        # 保存配置元数据（选项数、矩阵行列数等）
        if q_stats.option_count is not None:
            q_data["option_count"] = q_stats.option_count
        if q_stats.matrix_rows is not None:
            q_data["matrix_rows"] = q_stats.matrix_rows
        if q_stats.matrix_cols is not None:
            q_data["matrix_cols"] = q_stats.matrix_cols
        
        if q_stats.rows:
            q_data["rows"] = {
                str(r): {str(c): cnt for c, cnt in cols.items()}
                for r, cols in q_stats.rows.items()
            }
        if q_stats.text_answers:
            q_data["text_answers"] = q_stats.text_answers
        data["questions"][str(q_num)] = q_data

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return path


def load_stats(path: str) -> Optional[SurveyStats]:
    """从文件加载统计数据

    Args:
        path: 统计文件路径

    Returns:
        统计数据对象，文件不存在或格式错误则返回 None
    """
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

    stats = SurveyStats(
        survey_url=data.get("survey_url", ""),
        survey_title=data.get("survey_title"),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        total_submissions=data.get("total_submissions", 0),
        failed_submissions=data.get("failed_submissions", 0),
        reliability_validity=data.get("reliability_validity"),  # 加载信效度分析结果
    )

    for q_num_str, q_data in data.get("questions", {}).items():
        try:
            q_num = int(q_num_str)
        except ValueError:
            continue

        q_stats = QuestionStats(
            question_num=q_num,
            question_type=q_data.get("question_type", "unknown"),
            question_title=q_data.get("question_title"),
            total_responses=q_data.get("total_responses", 0),
            option_count=q_data.get("option_count"),
            matrix_rows=q_data.get("matrix_rows"),
            matrix_cols=q_data.get("matrix_cols"),
        )

        for idx_str, opt_data in q_data.get("options", {}).items():
            try:
                idx = int(idx_str)
            except ValueError:
                continue
            q_stats.options[idx] = OptionStats(
                option_index=idx,
                option_text=opt_data.get("text", ""),
                count=opt_data.get("count", 0),
            )

        if "rows" in q_data:
            q_stats.rows = {}
            for r_str, cols in q_data["rows"].items():
                try:
                    r = int(r_str)
                    q_stats.rows[r] = {int(c): cnt for c, cnt in cols.items()}
                except ValueError:
                    continue

        if "text_answers" in q_data:
            q_stats.text_answers = q_data["text_answers"]

        stats.questions[q_num] = q_stats

    return stats


def list_stats_files() -> List[str]:
    """列出所有统计文件（按修改时间降序）

    Returns:
        统计文件路径列表
    """
    stats_dir = _ensure_stats_dir()
    files = []
    try:
        for filename in os.listdir(stats_dir):
            # 只检查 .json 后缀，不限制前缀（兼容各种文件名格式）
            if filename.endswith(".json"):
                files.append(os.path.join(stats_dir, filename))
    except OSError:
        return []
    return sorted(files, key=lambda f: os.path.getmtime(f), reverse=True)

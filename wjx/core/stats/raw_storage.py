"""原始答卷数据持久化

将每一份成功提交的问卷原始作答数据追加写入 JSONL 文件，
供 analysis.py 读取后进行真实的信效度分析。

JSONL 格式设计（每行一个 JSON 对象）：
{
    "submission_index": 1,
    "timestamp": "2026-02-09T10:00:00",
    "answers": {
        "1": {"type": "single", "value": 2},
        "3": {"type": "scale", "value": 4},
        "5": {"type": "multiple", "value": [0, 2, 3]},
        "7": {"type": "matrix", "value": {"0": 2, "1": 3}},
        "9": {"type": "text", "value": "很满意"}
    }
}
"""

import json
import os
import re
import threading
from typing import Any, Dict, Optional
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception




from wjx.core.stats.models import ResponseRecord
from wjx.utils.app.runtime_paths import _get_project_root

STATS_DIR_NAME = "stats"
RAW_DATA_SUBDIR = "raw"  # 原始答卷数据子目录

# 适合进行信效度分析的题型（有序数值型选项）
SCALE_TYPES = {"single", "scale", "score", "dropdown", "slider"}


def _ensure_stats_dir() -> str:
    """确保统计目录存在"""
    base = _get_project_root()
    stats_dir = os.path.join(base, STATS_DIR_NAME)
    os.makedirs(stats_dir, exist_ok=True)
    return stats_dir


def _ensure_raw_data_dir() -> str:
    """确保原始数据子目录存在（stats/raw/）"""
    stats_dir = _ensure_stats_dir()
    raw_dir = os.path.join(stats_dir, RAW_DATA_SUBDIR)
    os.makedirs(raw_dir, exist_ok=True)
    return raw_dir


def _sanitize_for_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    sanitized = re.sub(r'[\\/:*?"<>|]', '_', name)
    sanitized = sanitized.strip('. ')
    if len(sanitized) > 50:
        sanitized = sanitized[:50].rstrip('. ')
    return sanitized or "未命名问卷"


def _serialize_answer(value: Any, question_type: str) -> Dict[str, Any]:
    """将作答值序列化为 JSON 友好的结构

    Args:
        value: 原始作答值
        question_type: 题型

    Returns:
        {"type": "...", "value": ...}
    """
    if question_type in ("single", "scale", "score", "dropdown", "slider"):
        return {"type": question_type, "value": int(value) if value is not None else None}

    elif question_type == "multiple":
        # 多选：tuple/list → sorted list
        if isinstance(value, (list, tuple)):
            return {"type": "multiple", "value": sorted(int(v) for v in value)}
        return {"type": "multiple", "value": value}

    elif question_type == "matrix":
        # 矩阵：dict[row_idx, col_idx] → {"行号": 列号}
        if isinstance(value, dict):
            return {"type": "matrix", "value": {str(k): int(v) for k, v in value.items()}}
        return {"type": "matrix", "value": value}

    elif question_type == "text":
        return {"type": "text", "value": str(value) if value is not None else ""}

    return {"type": question_type, "value": value}


class RawDataStorage:
    """原始答卷数据存储器

    线程安全地将每份答卷追加写入 JSONL 文件（每行一个 JSON 对象）。
    文件名格式：raw_{问卷标题}.jsonl

    使用方式：
        storage = RawDataStorage()
        storage.open_session("https://...", "问卷标题")
        storage.append_record(record)
        storage.close_session()
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._file_path: Optional[str] = None
        self._session_active = False

    def open_session(self, survey_url: str, survey_title: Optional[str] = None) -> None:
        """开始新的存储会话，准备 JSONL 文件

        如果文件已存在（之前的会话），会清空旧数据，从头开始写入。
        """
        with self._lock:
            raw_dir = _ensure_raw_data_dir()

            # 生成文件名
            if survey_title:
                name_part = _sanitize_for_filename(survey_title)
            else:
                from urllib.parse import urlparse
                parsed = urlparse(survey_url)
                path_part = parsed.path.replace("/", "_").strip("_")
                name_part = path_part if path_part else "未命名问卷"

            self._file_path = os.path.join(raw_dir, f"raw_{name_part}.jsonl")
            
            # 清空旧数据：如果文件存在，删除它
            if os.path.exists(self._file_path):
                try:
                    os.remove(self._file_path)
                except OSError as exc:
                    log_suppressed_exception("open_session: os.remove(self._file_path)", exc, level=logging.WARNING)
            
            self._session_active = True

    def close_session(self) -> None:
        """关闭存储会话"""
        with self._lock:
            self._session_active = False

    def append_record(self, record: ResponseRecord) -> None:
        """追加一份答卷到 JSONL 文件

        Args:
            record: 单份答卷记录
        """
        with self._lock:
            if not self._session_active or not self._file_path:
                return

            # 构建 JSON 对象
            obj: Dict[str, Any] = {
                "submission_index": record.submission_index,
                "timestamp": record.timestamp,
                "answers": {},
            }

            for q_num in sorted(record.answers.keys()):
                q_type = record.question_types.get(q_num, "unknown")
                obj["answers"][str(q_num)] = _serialize_answer(record.answers[q_num], q_type)

            # 追加写入（一行一个 JSON 对象）
            with open(self._file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def get_file_path(self) -> Optional[str]:
        """获取当前 JSONL 文件路径"""
        with self._lock:
            return self._file_path


# 全局单例
raw_data_storage = RawDataStorage()

"""
CLI 日志与报告模块

提供CLI模式下的日志处理、报告生成和导出功能。
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from wjx.utils.logging.log_utils import LogBufferEntry, save_log_records_to_file
from wjx.utils.app.runtime_paths import get_runtime_directory


logger = logging.getLogger(__name__)


class CLILogHandler(logging.Handler):
    def __init__(self, output_callback=None):
        super().__init__()
        self.output_callback = output_callback

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            if self.output_callback:
                self.output_callback(msg, record.levelno)
            else:
                print(msg)
        except Exception:
            self.handleError(record)


class CLIReportGenerator:
    def __init__(self, runtime_directory: Optional[str] = None):
        self.runtime_directory = runtime_directory or get_runtime_directory()
        self.reports_dir = os.path.join(self.runtime_directory, "reports")
        os.makedirs(self.reports_dir, exist_ok=True)

    def generate_execution_report(
        self,
        success_count: int,
        total_count: int,
        duration_seconds: float,
        errors: Optional[List[Dict[str, Any]]] = None,
        config_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """生成执行报告"""
        success_rate = (success_count / total_count * 100) if total_count > 0 else 0
        report = {
            "report_type": "execution_summary",
            "generated_at": datetime.now().isoformat(),
            "execution": {
                "total": total_count,
                "success": success_count,
                "failed": total_count - success_count,
                "success_rate": f"{success_rate:.2f}%",
                "duration_seconds": round(duration_seconds, 2),
                "avg_time_per_task": round(duration_seconds / total_count, 2) if total_count > 0 else 0,
            },
            "config": config_summary or {},
            "errors": errors or [],
        }
        return report

    def generate_task_report(
        self,
        task_id: int,
        task_name: str,
        status: str,
        start_time: str,
        end_time: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """生成任务执行报告"""
        report = {
            "report_type": "task_execution",
            "generated_at": datetime.now().isoformat(),
            "task": {
                "id": task_id,
                "name": task_name,
                "status": status,
                "start_time": start_time,
                "end_time": end_time,
            },
            "result": result or {},
        }
        return report

    def save_report(
        self,
        report: Dict[str, Any],
        filename: Optional[str] = None,
        format: str = "json",
    ) -> str:
        """保存报告到文件"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"report_{timestamp}"

        if format == "json":
            filepath = os.path.join(self.reports_dir, f"{filename}.json")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
        elif format == "text":
            filepath = os.path.join(self.reports_dir, f"{filename}.txt")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(self._format_report_as_text(report))
        else:
            raise ValueError(f"不支持的格式: {format}")

        logger.info(f"报告已保存: {filepath}")
        return filepath

    def _format_report_as_text(self, report: Dict[str, Any]) -> str:
        """将报告格式化为文本"""
        lines = []
        lines.append("=" * 60)
        lines.append(f"报告类型: {report.get('report_type', 'unknown')}")
        lines.append(f"生成时间: {report.get('generated_at', 'unknown')}")
        lines.append("=" * 60)

        if "execution" in report:
            lines.append("\n执行摘要:")
            lines.append("-" * 40)
            exec_info = report["execution"]
            lines.append(f"  总数: {exec_info.get('total', 0)}")
            lines.append(f"  成功: {exec_info.get('success', 0)}")
            lines.append(f"  失败: {exec_info.get('failed', 0)}")
            lines.append(f"  成功率: {exec_info.get('success_rate', '0%')}")
            lines.append(f"  耗时: {exec_info.get('duration_seconds', 0)}秒")
            lines.append(f"  平均耗时: {exec_info.get('avg_time_per_task', 0)}秒/任务")

        if "task" in report:
            lines.append("\n任务信息:")
            lines.append("-" * 40)
            task_info = report["task"]
            lines.append(f"  ID: {task_info.get('id', 'unknown')}")
            lines.append(f"  名称: {task_info.get('name', 'unknown')}")
            lines.append(f"  状态: {task_info.get('status', 'unknown')}")
            lines.append(f"  开始时间: {task_info.get('start_time', 'unknown')}")
            lines.append(f"  结束时间: {task_info.get('end_time', 'N/A')}")

        if "errors" in report and report["errors"]:
            lines.append("\n错误详情:")
            lines.append("-" * 40)
            for i, err in enumerate(report["errors"], 1):
                lines.append(f"  [{i}] {err}")

        lines.append("=" * 60)
        return "\n".join(lines)

    def export_logs(
        self,
        logs: List[LogBufferEntry],
        filename: Optional[str] = None,
        format: str = "json",
    ) -> str:
        """导出一系列日志记录"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"logs_{timestamp}"

        if format == "json":
            filepath = os.path.join(self.reports_dir, f"{filename}.json")
            log_data = [
                {
                    "timestamp": getattr(entry, "timestamp", ""),
                    "text": entry.text if hasattr(entry, "text") else str(entry),
                    "category": entry.category if hasattr(entry, "category") else "UNKNOWN",
                }
                for entry in logs
            ]
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(log_data, f, indent=2, ensure_ascii=False)
        elif format == "text":
            filepath = os.path.join(self.reports_dir, f"{filename}.txt")
            with open(filepath, "w", encoding="utf-8") as f:
                for entry in logs:
                    text = entry.text if hasattr(entry, "text") else str(entry)
                    f.write(f"{text}\n")
        else:
            raise ValueError(f"不支持的格式: {format}")

        logger.info(f"日志已导出: {filepath}")
        return filepath

    def get_reports_list(self) -> List[Dict[str, Any]]:
        """获取报告列表"""
        reports = []
        if not os.path.exists(self.reports_dir):
            return reports

        for filename in os.listdir(self.reports_dir):
            filepath = os.path.join(self.reports_dir, filename)
            if os.path.isfile(filepath):
                stat = os.stat(filepath)
                reports.append({
                    "filename": filename,
                    "filepath": filepath,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })

        return sorted(reports, key=lambda x: x["modified"], reverse=True)

    def delete_report(self, filename: str) -> bool:
        """删除指定报告"""
        filepath = os.path.join(self.reports_dir, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            logger.info(f"报告已删除: {filepath}")
            return True
        return False


_report_generator_instance: Optional[CLIReportGenerator] = None


def get_report_generator() -> CLIReportGenerator:
    global _report_generator_instance
    if _report_generator_instance is None:
        _report_generator_instance = CLIReportGenerator()
    return _report_generator_instance
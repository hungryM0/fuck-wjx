"""样本分发器。"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from software.io.excel.schema import SampleRow


class SampleDispatcher:
    """样本分发器。
    
    线程安全地分发样本，确保每行只被消费一次。
    支持并发场景下的样本分配、状态更新和统计。
    """

    def __init__(self, samples: list[SampleRow]):
        """初始化分发器。
        
        Args:
            samples: 样本列表（应该都是 status="pending" 的样本）
        """
        self.samples = samples
        self.lock = threading.Lock()
        self._total = len(samples)
        self._initial_pending = sum(1 for s in samples if s.status == "pending")

    def next_sample(self) -> Optional[SampleRow]:
        """取下一个待处理样本（线程安全）。
        
        Returns:
            待处理的样本，如果没有则返回 None
            
        Note:
            此方法会自动将样本状态从 "pending" 改为 "running"
        """
        with self.lock:
            for s in self.samples:
                if s.status == "pending":
                    s.status = "running"
                    return s
        return None

    def mark_success(self, sample: SampleRow):
        """标记样本成功（线程安全）。
        
        Args:
            sample: 要标记的样本
        """
        with self.lock:
            sample.status = "success"
            sample.error = None

    def mark_failed(self, sample: SampleRow, error: str, retry: bool = False):
        """标记样本失败（线程安全）。
        
        Args:
            sample: 要标记的样本
            error: 错误信息
            retry: 是否允许重试（如果为 True，状态改为 pending；否则为 failed）
        """
        with self.lock:
            sample.error = error
            sample.status = "pending" if retry else "failed"

    def get_stats(self) -> dict:
        """获取统计信息（线程安全）。
        
        Returns:
            统计信息字典，包含：
            - total: 总样本数
            - pending: 待处理数
            - running: 运行中数
            - success: 成功数
            - failed: 失败数
            - progress: 进度百分比（0-100）
        """
        with self.lock:
            pending = sum(1 for s in self.samples if s.status == "pending")
            running = sum(1 for s in self.samples if s.status == "running")
            success = sum(1 for s in self.samples if s.status == "success")
            failed = sum(1 for s in self.samples if s.status == "failed")
            
            # 计算进度（成功 + 失败）/ 总数
            completed = success + failed
            progress = (completed / self._total * 100) if self._total > 0 else 0
            
            return {
                "total": self._total,
                "pending": pending,
                "running": running,
                "success": success,
                "failed": failed,
                "progress": round(progress, 2),
            }

    def has_pending(self) -> bool:
        """检查是否还有待处理的样本（线程安全）。
        
        Returns:
            如果还有待处理样本返回 True，否则返回 False
        """
        with self.lock:
            return any(s.status == "pending" for s in self.samples)

    def get_failed_samples(self) -> list[SampleRow]:
        """获取所有失败的样本（线程安全）。
        
        Returns:
            失败样本列表
        """
        with self.lock:
            return [s for s in self.samples if s.status == "failed"]

    def get_success_samples(self) -> list[SampleRow]:
        """获取所有成功的样本（线程安全）。
        
        Returns:
            成功样本列表
        """
        with self.lock:
            return [s for s in self.samples if s.status == "success"]

    def reset_failed_samples(self):
        """重置所有失败样本为待处理状态（线程安全）。
        
        用于重试失败的样本。
        """
        with self.lock:
            for s in self.samples:
                if s.status == "failed":
                    s.status = "pending"
                    s.error = None

    def is_completed(self) -> bool:
        """检查是否所有样本都已处理完成（线程安全）。
        
        Returns:
            如果所有样本都是 success 或 failed 状态返回 True
        """
        with self.lock:
            return all(s.status in ("success", "failed") for s in self.samples)
    
    def is_all_success(self) -> bool:
        """检查是否所有样本都已成功（线程安全）。
        
        Returns:
            如果所有样本都是 success 状态返回 True
        """
        with self.lock:
            return all(s.status == "success" for s in self.samples)
    
    def get_next_sample(self, thread_name: str) -> Optional[SampleRow]:
        """获取下一个待处理样本（线程安全）。
        
        这是 next_sample() 的别名方法，提供更明确的命名。
        
        Args:
            thread_name: 线程名称（用于日志记录）
            
        Returns:
            待处理的样本，如果没有则返回 None
            
        Note:
            此方法会自动将样本状态从 "pending" 改为 "running"
        """
        return self.next_sample()
    
    def mark_sample_success(self, row_no: int):
        """根据行号标记样本成功（线程安全）。
        
        Args:
            row_no: 样本行号
            
        Raises:
            ValueError: 如果找不到对应行号的样本
        """
        with self.lock:
            for sample in self.samples:
                if sample.row_no == row_no:
                    sample.status = "success"
                    sample.error = None
                    return
            raise ValueError(f"未找到行号为 {row_no} 的样本")
    
    def mark_sample_failed(self, row_no: int, error: str, retry: bool = True):
        """根据行号标记样本失败（线程安全）。
        
        Args:
            row_no: 样本行号
            error: 错误信息
            retry: 是否允许重试（如果为 True，状态改为 pending；否则为 failed）
            
        Raises:
            ValueError: 如果找不到对应行号的样本
        """
        with self.lock:
            for sample in self.samples:
                if sample.row_no == row_no:
                    sample.error = error
                    sample.status = "pending" if retry else "failed"
                    return
            raise ValueError(f"未找到行号为 {row_no} 的样本")
    
    def get_sample_by_row_no(self, row_no: int) -> Optional[SampleRow]:
        """根据行号获取样本（线程安全）。
        
        Args:
            row_no: 样本行号
            
        Returns:
            样本对象，如果未找到则返回 None
        """
        with self.lock:
            for sample in self.samples:
                if sample.row_no == row_no:
                    return sample
        return None
    
    def get_summary(self) -> dict:
        """获取详细的统计摘要（线程安全）。
        
        Returns:
            统计摘要字典，包含：
            - total: 总样本数
            - pending: 待处理数
            - running: 运行中数
            - success: 成功数
            - failed: 失败数
            - progress: 进度百分比（0-100）
            - success_rate: 成功率（0-100）
            - failed_samples: 失败样本的行号列表
        """
        with self.lock:
            # 直接计算统计信息，避免调用 get_stats() 导致死锁
            pending = sum(1 for s in self.samples if s.status == "pending")
            running = sum(1 for s in self.samples if s.status == "running")
            success = sum(1 for s in self.samples if s.status == "success")
            failed = sum(1 for s in self.samples if s.status == "failed")
            
            # 计算进度（成功 + 失败）/ 总数
            completed = success + failed
            progress = (completed / self._total * 100) if self._total > 0 else 0
            
            # 计算成功率
            success_rate = (success / completed * 100) if completed > 0 else 0
            
            # 获取失败样本的行号
            failed_row_nos = [s.row_no for s in self.samples if s.status == "failed"]
            
            return {
                "total": self._total,
                "pending": pending,
                "running": running,
                "success": success,
                "failed": failed,
                "progress": round(progress, 2),
                "success_rate": round(success_rate, 2),
                "failed_samples": failed_row_nos,
            }

    def export_incomplete_samples(self, original_excel_path: str) -> Optional[str]:
        """导出未完成的样本到 Excel 文件。
        
        Args:
            original_excel_path: 原始 Excel 文件路径
            
        Returns:
            导出文件路径，如果没有未完成样本则返回 None
        """
        with self.lock:
            # 获取未完成的样本（pending 和 failed）
            incomplete_samples = [
                s for s in self.samples
                if s.status in ("pending", "failed")
            ]
            
            if not incomplete_samples:
                return None
            
            # 导出到 Excel
            from software.io.excel.writer import ExcelWriter
            writer = ExcelWriter()
            output_path = writer.export_failed_samples(incomplete_samples, original_excel_path)
            
            return output_path
    
    def get_incomplete_samples(self) -> list[SampleRow]:
        """获取所有未完成的样本（线程安全）。
        
        Returns:
            未完成样本列表（pending + failed）
        """
        with self.lock:
            return [
                s for s in self.samples
                if s.status in ("pending", "failed")
            ]

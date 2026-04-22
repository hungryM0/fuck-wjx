"""反填模式映射预览对话框。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView
from qfluentwidgets import MessageBoxBase, SubtitleLabel, BodyLabel, PushButton

if TYPE_CHECKING:
    from software.ui.controller.run_controller import RunController


class BackfillPreviewDialog(MessageBoxBase):
    """反填模式映射预览对话框。
    
    显示 Excel 列到问卷题目的映射关系，以及样本校验结果。
    """
    
    def __init__(
        self,
        excel_path: str,
        controller: RunController,
        parent=None,
    ):
        super().__init__(parent)
        
        self.excel_path = excel_path
        self.controller = controller
        
        self.titleLabel = SubtitleLabel("反填模式预览", self)
        
        # 创建内容
        self._create_content()
        
        # 设置对话框大小
        self.widget.setMinimumWidth(700)
        self.widget.setMinimumHeight(500)
    
    def _create_content(self):
        """创建对话框内容。"""
        layout = QVBoxLayout()
        
        try:
            # 1. 读取并分析 Excel
            result = self._analyze_excel()
            
            # 2. 显示文件信息
            info_label = BodyLabel(
                f"Excel 文件: {result['file_name']}\n"
                f"总行数: {result['total_rows']} | "
                f"有效样本: {result['valid_samples']} | "
                f"失败样本: {result['failed_samples']}"
            )
            layout.addWidget(info_label)
            
            # 3. 显示映射表
            mapping_label = SubtitleLabel("列映射关系")
            layout.addWidget(mapping_label)
            
            mapping_table = self._create_mapping_table(result['mapping_items'])
            layout.addWidget(mapping_table)
            
            # 4. 显示失败样本（如果有）
            if result['failed_samples'] > 0:
                failed_label = SubtitleLabel(f"失败样本 ({result['failed_samples']} 个)")
                layout.addWidget(failed_label)
                
                failed_table = self._create_failed_table(result['failed_details'][:10])
                layout.addWidget(failed_table)
                
                if result['failed_samples'] > 10:
                    more_label = BodyLabel(f"... 还有 {result['failed_samples'] - 10} 个失败样本")
                    layout.addWidget(more_label)
            
        except Exception as e:
            error_label = BodyLabel(f"预览失败: {str(e)}")
            error_label.setStyleSheet("color: red;")
            layout.addWidget(error_label)
        
        self.viewLayout.addLayout(layout)
    
    def _analyze_excel(self) -> dict:
        """分析 Excel 文件。"""
        from software.io.excel import (
            ExcelReader,
            QuestionMatcher,
            AnswerNormalizer,
            SampleValidator,
        )
        from software.core.backfill.survey_converter import convert_to_survey_schema
        
        # 读取 Excel
        reader = ExcelReader()
        samples = reader.read(self.excel_path)
        
        # 转换问卷结构
        survey_schema = convert_to_survey_schema(self.controller)
        
        # 建立映射
        matcher = QuestionMatcher()
        excel_columns = list(samples[0].values.keys())
        mapping_plan = matcher.build_mapping(excel_columns, survey_schema)
        
        # 校验并标准化
        normalizer = AnswerNormalizer()
        validator = SampleValidator(normalizer)
        validator.validate_and_normalize(samples, survey_schema, mapping_plan)
        
        # 获取统计
        summary = validator.get_validation_summary(samples)
        
        import os
        return {
            "file_name": os.path.basename(self.excel_path),
            "total_rows": len(samples),
            "valid_samples": summary["success"],
            "failed_samples": summary["failed"],
            "mapping_items": mapping_plan.items,
            "failed_details": summary["failed_details"],
        }
    
    def _create_mapping_table(self, mapping_items) -> QTableWidget:
        """创建映射表。"""
        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["Excel 列", "问卷题目", "匹配方式", "置信度"])
        table.setRowCount(len(mapping_items))
        
        for i, item in enumerate(mapping_items):
            # Excel 列
            table.setItem(i, 0, QTableWidgetItem(item.excel_col))
            
            # 问卷题目
            table.setItem(i, 1, QTableWidgetItem(f"{item.survey_qid}: {item.survey_title}"))
            
            # 匹配方式
            mode_text = {
                "by_index": "题号匹配",
                "by_title_exact": "标题精确匹配",
                "by_title_fuzzy": "模糊匹配",
            }.get(item.mode, item.mode or "未知")
            table.setItem(i, 2, QTableWidgetItem(str(mode_text)))
            
            # 置信度
            confidence_text = f"{item.confidence * 100:.0f}%"
            table.setItem(i, 3, QTableWidgetItem(confidence_text))
        
        # 调整列宽
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        
        table.setMaximumHeight(200)
        
        return table
    
    def _create_failed_table(self, failed_details) -> QTableWidget:
        """创建失败样本表。"""
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["行号", "错误信息"])
        table.setRowCount(len(failed_details))
        
        for i, detail in enumerate(failed_details):
            table.setItem(i, 0, QTableWidgetItem(str(detail["row_no"])))
            table.setItem(i, 1, QTableWidgetItem(detail["error"]))
        
        # 调整列宽
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        
        table.setMaximumHeight(200)
        
        return table

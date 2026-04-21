"""Dashboard 反填模式 Mixin。

提供反填模式的 UI 控件和逻辑。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QHBoxLayout, QLabel
from qfluentwidgets import (
    SwitchButton,
    PushButton,
    InfoBar,
    InfoBarPosition,
    MessageBox,
)

if TYPE_CHECKING:
    from software.ui.controller.run_controller import RunController


class DashboardBackfillMixin:
    """Dashboard 反填模式 Mixin。
    
    添加反填模式的 UI 控件：
    - 反填模式开关
    - Excel 文件选择按钮
    - 映射预览对话框
    """
    
    if TYPE_CHECKING:
        controller: RunController
        
    def _init_backfill_ui(self):
        """初始化反填模式 UI。
        
        在 Dashboard 初始化时调用此方法来添加反填模式控件。
        """
        # 创建反填模式区域
        self._backfill_enabled = False
        self._backfill_excel_path = ""
        
        # 添加说明标签
        hint_label = QLabel("💡 提示：启用反填模式前，请先在上方输入问卷链接并完成“自动配置问卷”")
        hint_label.setStyleSheet("color: #606060; font-size: 12px; padding: 4px;")
        hint_label.setWordWrap(True)
        
        # 1. 反填模式开关
        self.backfill_switch = SwitchButton()
        self.backfill_switch.setOnText("反填模式")
        self.backfill_switch.setOffText("反填模式")
        self.backfill_switch.checkedChanged.connect(self._on_backfill_mode_changed)
        
        # 2. Excel 文件选择按钮
        self.backfill_excel_btn = PushButton("选择 Excel 文件")
        self.backfill_excel_btn.clicked.connect(self._on_select_excel)
        self.backfill_excel_btn.setEnabled(False)
        
        # 3. 文件路径标签
        self.backfill_path_label = QLabel("未选择文件")
        self.backfill_path_label.setStyleSheet("color: gray;")
        
        # 4. 映射预览按钮
        self.backfill_preview_btn = PushButton("预览映射")
        self.backfill_preview_btn.clicked.connect(self._on_preview_mapping)
        self.backfill_preview_btn.setEnabled(False)
        
        # 布局
        backfill_layout = QVBoxLayout()
        
        # 提示信息
        backfill_layout.addWidget(hint_label)
        
        # 第一行：开关
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("数据反填:"))
        row1.addWidget(self.backfill_switch)
        row1.addStretch()
        backfill_layout.addLayout(row1)
        
        # 第二行：文件选择
        row2 = QHBoxLayout()
        row2.addWidget(self.backfill_excel_btn)
        row2.addWidget(self.backfill_path_label, 1)
        backfill_layout.addLayout(row2)
        
        # 第三行：预览按钮
        row3 = QHBoxLayout()
        row3.addWidget(self.backfill_preview_btn)
        row3.addStretch()
        backfill_layout.addLayout(row3)
        
        return backfill_layout
    
    def _on_backfill_mode_changed(self, checked: bool):
        """反填模式开关变化。"""
        # 检查是否已解析问卷
        if checked and (not hasattr(self.controller, 'surveyParsed') or not self.controller.surveyParsed):
            # 未解析问卷，不允许启用
            self.backfill_switch.setChecked(False)
            InfoBar.warning(
                title="请先解析问卷",
                content="启用反填模式前，请先输入问卷链接或上传二维码，并点击“自动配置问卷”",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self,
            )
            return
        
        self._backfill_enabled = checked
        self.backfill_excel_btn.setEnabled(checked)
        
        if checked:
            InfoBar.info(
                title="反填模式已启用",
                content="请选择包含样本数据的 Excel 文件",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )
        else:
            # 清除选择
            self._backfill_excel_path = ""
            self.backfill_path_label.setText("未选择文件")
            self.backfill_path_label.setStyleSheet("color: gray;")
            self.backfill_preview_btn.setEnabled(False)
    
    def _on_select_excel(self):
        """选择 Excel 文件。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Excel 文件",
            "",
            "Excel 文件 (*.xlsx *.xls)"
        )
        
        if file_path:
            self._backfill_excel_path = file_path
            
            # 显示文件名
            import os
            file_name = os.path.basename(file_path)
            self.backfill_path_label.setText(file_name)
            self.backfill_path_label.setStyleSheet("color: black;")
            
            # 启用预览按钮
            self.backfill_preview_btn.setEnabled(True)
            
            InfoBar.success(
                title="文件已选择",
                content=f"已选择: {file_name}",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self,
            )
    
    def _on_preview_mapping(self):
        """预览映射关系。"""
        if not self._backfill_excel_path:
            InfoBar.warning(
                title="未选择文件",
                content="请先选择 Excel 文件",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self,
            )
            return
        
        # 检查是否已解析问卷
        if not hasattr(self.controller, 'surveyParsed') or not self.controller.surveyParsed:
            InfoBar.warning(
                title="未解析问卷",
                content="请先解析问卷 URL",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self,
            )
            return
        
        try:
            # 显示映射预览对话框
            self._show_mapping_preview_dialog()
        except Exception as e:
            InfoBar.error(
                title="预览失败",
                content=str(e),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )
    
    def _show_mapping_preview_dialog(self):
        """显示映射预览对话框。"""
        from software.ui.dialogs.backfill_preview import BackfillPreviewDialog
        
        dialog = BackfillPreviewDialog(
            excel_path=self._backfill_excel_path,
            controller=self.controller,
            parent=self,
        )
        dialog.exec()
    
    def get_backfill_config(self) -> Optional[dict]:
        """获取反填模式配置。
        
        Returns:
            配置字典，如果未启用则返回 None
        """
        if not self._backfill_enabled or not self._backfill_excel_path:
            return None
        
        return {
            "enabled": True,
            "excel_path": self._backfill_excel_path,
        }
    
    def validate_backfill_config(self) -> tuple[bool, str]:
        """验证反填模式配置。
        
        Returns:
            (是否有效, 错误信息)
        """
        if not self._backfill_enabled:
            return True, ""
        
        if not self._backfill_excel_path:
            return False, "请选择 Excel 文件"
        
        import os
        if not os.path.exists(self._backfill_excel_path):
            return False, f"文件不存在: {self._backfill_excel_path}"
        
        return True, ""

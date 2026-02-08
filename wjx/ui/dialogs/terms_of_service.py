"""服务条款对话框"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout
from qfluentwidgets import (
    ScrollArea,
    BodyLabel,
    TitleLabel,
    PrimaryPushButton,
)


# 服务条款内容
TERMS_CONTENT = """
───────────────────────────────────────────────────────────────────────
  服务条款
───────────────────────────────────────────────────────────────────────

【第一条 接受条款】

  在安装和使用本软件之前，您已在安装程序中阅读过本服务条款。继续使用本软件即表示您已充分理解并同意接受本条款的全部内容。若您不同意本条款的任何一条内容，请立即停止使用并卸载软件。


【第二条 软件用途】

  本软件系开源学习交流工具，仅供个人学习、研究和技术交流使用。严禁将本软件用于以下用途：

  · 伪造不实数据或用于学术研究
  · 商业性质的数据采集或问卷填写服务
  · 污染、破坏他人问卷调查数据
  · 侵犯他人合法权益的行为
  · 违反国家法律法规的其他行为


【第三条 免责声明】

  1. 本软件按"现状"提供，不对软件的适用性、准确性、完整性或可靠性作任何形式的明示或暗示保证

  2. 使用本软件所产生的一切法律责任及后果均由使用者自行承担，软件开发者不承担任何责任

  3. 因使用本软件而导致的任何直接或间接损失，软件开发者概不负责


【第四条 知识产权】

  本软件采用 GPL v3 开源许可证在 GitHub 开放全部源代码，版权与软件著作权归开发者所有，未经允许禁止闭源分发衍生作品与软件。


【第五条 条款变更】

  开发者保留随时修改本服务条款的权利。条款变更后，继续使用本软件即视为接受变更后的条款。


───────────────────────────────────────────────────────────────────────
  隐私声明
───────────────────────────────────────────────────────────────────────

【信息收集】

  本软件承诺：

  · 不收集用户的任何个人身份信息
  · 不收集用户填写的问卷内容数据
  · 不向第三方传输或分享用户数据
  · 所有配置信息仅存储于本地设备


【第三方服务】

  本软件可能调用以下第三方服务，这些服务有其独立的隐私政策：

  · 浏览器驱动下载服务（ChromeDriver、EdgeDriver 等官方源）
  · AI 服务提供商（若用户主动配置并启用 AI 功能）
  · 随机 IP 代理服务商（若用户主动启用该功能）

  使用第三方服务时，请注意该服务提供商的隐私政策。


【数据安全】

  · 用户配置的 API 密钥等敏感信息将仅存储于本地
  · 软件运行日志仅记录技术诊断信息，不包含个人隐私数据
  · 用户可随时删除本地配置文件以清除所有存储数据

═══════════════════════════════════════════════════════════════════════

  最后修订日期：2026 年 2 月 1 日
"""


class TermsOfServiceDialog(QDialog):
    """服务条款对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle("服务条款")
        self.resize(800, 600)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # 标题
        title = TitleLabel("服务条款与隐私声明", self)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title)

        # 滚动区域显示条款内容
        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        
        content_widget = BodyLabel(self)
        content_widget.setWordWrap(True)
        content_widget.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        
        # 使用硬编码的服务条款内容
        content_widget.setText(TERMS_CONTENT)
        content_widget.setStyleSheet("""
            BodyLabel {
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 15px;
                line-height: 1.6;
                padding: 12px;
            }
        """)
        
        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)

        # 关闭按钮
        close_btn = PrimaryPushButton("关闭", self)
        close_btn.setFixedWidth(120)
        close_btn.clicked.connect(self.accept)
        
        btn_layout = QVBoxLayout()
        btn_layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignCenter)
        main_layout.addLayout(btn_layout)

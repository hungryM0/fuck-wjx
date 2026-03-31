"""运行参数页 - AI 提供商和 API Key 配置组件"""
from typing import Optional
import logging
from software.logging.log_utils import log_suppressed_exception


from PySide6.QtCore import QObject, Qt, QThread
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    ComboBox,
    EditableComboBox,
    ExpandGroupSettingCard,
    FluentIcon,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarIcon,
    InfoBarPosition,
    HyperlinkButton,
    LineEdit,
    PasswordLineEdit,
    PlainTextEdit,
    PushSettingCard,
    SettingCard,
    SettingCardGroup,
)

from software.ui.widgets.full_width_infobar import FullWidthInfoBar
from software.ui.workers.ai_test_worker import AITestWorker
from software.integrations.ai import (
    AI_PROVIDERS,
    get_ai_settings,
    get_default_system_prompt,
    save_ai_settings,
)
from software.io.config import RuntimeConfig


class AIPromptSettingCard(ExpandGroupSettingCard):
    """AI 系统提示词展开卡。"""

    def __init__(self, prompt_text: str, default_prompt: str, parent=None):
        super().__init__(
            FluentIcon.EDIT,
            "系统提示词",
            "在此处编辑 AI 填空的系统提示词",
            parent,
        )
        self._default_prompt = (default_prompt or "").strip() or get_default_system_prompt("provider")

        self._group_container = QWidget(self)
        layout = QVBoxLayout(self._group_container)
        layout.setContentsMargins(48, 12, 48, 16)
        layout.setSpacing(8)

        self.promptEdit = PlainTextEdit(self._group_container)
        self.promptEdit.setPlaceholderText("留空使用默认提示词...")
        self.promptEdit.setMinimumHeight(180)
        self.promptEdit.setMaximumHeight(230)
        self.promptEdit.setPlainText(prompt_text or self._default_prompt)

        layout.addWidget(self.promptEdit)

        self.addGroupWidget(self._group_container)
        self.setExpand(True)

    def prompt_text(self) -> str:
        return self.promptEdit.toPlainText().strip() or self._default_prompt

    def set_default_prompt(self, default_prompt: str) -> None:
        self._default_prompt = (default_prompt or "").strip() or self._default_prompt

    def set_prompt_text(self, value: str, default_prompt: Optional[str] = None) -> None:
        if default_prompt is not None:
            self.set_default_prompt(default_prompt)
        self.promptEdit.setPlainText((value or "").strip() or self._default_prompt)


class RuntimeAISection(QObject):

    _AI_MODES = {
        "free": "限时免费",
        "provider": "自定义服务商",
    }

    _PROVIDER_DOCS = {
        "deepseek": "https://api-docs.deepseek.com/zh-cn/",
        "qwen": "https://help.aliyun.com/zh/model-studio/get-api-key",
        "siliconflow": "https://docs.siliconflow.cn/cn/userguide/quickstart#2-%E6%9F%A5%E7%9C%8B%E6%A8%A1%E5%9E%8B%E5%88%97%E8%A1%A8%E5%92%8C%E6%A8%A1%E5%9E%8B%E8%AF%A6%E6%83%85",
        "volces": "https://www.volcengine.com/docs/82379/1399008?lang=zh#da0e9d90",
        "custom": "https://platform.openai.com/docs/api-reference/introduction",
    }

    def __init__(self, parent_view: QWidget, owner: QWidget):
        super().__init__(parent_view)
        self._owner = owner
        self.group = SettingCardGroup("AI 填空助手", parent_view)
        self._ai_loading = False
        self._ai_test_thread: Optional[QThread] = None
        self._ai_test_worker: Optional[AITestWorker] = None
        self._current_infobar: Optional[InfoBar] = None  # 存储当前显示的InfoBar引用
        ai_config = get_ai_settings()
        initial_mode = str(ai_config.get("ai_mode") or "free").strip().lower()
        if initial_mode not in self._AI_MODES:
            initial_mode = "free"
        self._last_ai_mode = initial_mode
        self._ai_system_prompt = str(ai_config.get("system_prompt") or "").strip() or get_default_system_prompt(initial_mode)
        self._build_ui(ai_config)
        self._bind_events()
        self._update_ai_visibility()

    def _build_ui(self, ai_config):
        saved_mode = str(ai_config.get("ai_mode") or "free").strip().lower()
        if saved_mode not in self._AI_MODES:
            saved_mode = "free"

        self.ai_free_mode_bar = FullWidthInfoBar(
            InfoBarIcon.INFORMATION,
            "AI填空限时免费至2026-06-30，如有长期使用需求请自行准备API Key。",
            "",
            orient=Qt.Orientation.Horizontal,
            isClosable=False,
            duration=-1,
            position=InfoBarPosition.NONE,
            parent=self.group,
        )
        self.ai_free_mode_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.ai_free_mode_bar.setMinimumWidth(0)
        self.ai_free_mode_bar.setMaximumWidth(16777215)
        self.ai_free_mode_bar.contentLabel.setVisible(False)
        self.group.addSettingCard(self.ai_free_mode_bar)

        self.ai_privacy_bar = FullWidthInfoBar(
            InfoBarIcon.SUCCESS,
            "隐私声明：不会上传 API Key 等隐私信息，所有配置仅保存在本地。",
            "",
            orient=Qt.Orientation.Horizontal,
            isClosable=False,
            duration=-1,
            position=InfoBarPosition.NONE,
            parent=self.group,
        )
        self.ai_privacy_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.ai_privacy_bar.setMinimumWidth(0)
        self.ai_privacy_bar.setMaximumWidth(16777215)
        self.ai_privacy_bar.contentLabel.setVisible(False)
        self.group.addSettingCard(self.ai_privacy_bar)

        self.ai_mode_card = SettingCard(
            FluentIcon.ROBOT,
            "AI 模式",
            "目前仅可用于填空题、多项填空题的AI填空作答，将在后续再支持其他题型",
            self.group,
        )
        self.ai_mode_combo = ComboBox(self.ai_mode_card)
        self.ai_mode_combo.setMinimumWidth(200)
        for key, label in self._AI_MODES.items():
            self.ai_mode_combo.addItem(label, userData=key)
        mode_idx = self.ai_mode_combo.findData(saved_mode)
        if mode_idx >= 0:
            self.ai_mode_combo.setCurrentIndex(mode_idx)
        self.ai_mode_card.hBoxLayout.addWidget(self.ai_mode_combo, 0, Qt.AlignmentFlag.AlignRight)
        self.ai_mode_card.hBoxLayout.addSpacing(16)
        self.group.addSettingCard(self.ai_mode_card)

        self.ai_provider_card = SettingCard(
            FluentIcon.CLOUD,
            "AI 服务提供商",
            "选择 AI 服务，自定义模式支持任意 OpenAI 兼容接口",
            self.group,
        )
        self.ai_provider_combo = ComboBox(self.ai_provider_card)
        self.ai_provider_combo.setMinimumWidth(200)
        for key, provider in AI_PROVIDERS.items():
            self.ai_provider_combo.addItem(provider.get("label", key), userData=key)
        saved_provider = ai_config.get("provider") or "deepseek"
        idx = self.ai_provider_combo.findData(saved_provider)
        if idx >= 0:
            self.ai_provider_combo.setCurrentIndex(idx)
        self.ai_provider_link = HyperlinkButton(FluentIcon.LINK, "", "API文档", self.ai_provider_card)
        self._update_ai_doc_link(saved_provider)
        self.ai_provider_card.hBoxLayout.addWidget(self.ai_provider_link, 0, Qt.AlignmentFlag.AlignRight)
        self.ai_provider_card.hBoxLayout.addSpacing(8)
        self.ai_provider_card.hBoxLayout.addWidget(self.ai_provider_combo, 0, Qt.AlignmentFlag.AlignRight)
        self.ai_provider_card.hBoxLayout.addSpacing(16)
        self.group.addSettingCard(self.ai_provider_card)

        self.ai_baseurl_card = SettingCard(
            FluentIcon.LINK,
            "Base URL",
            "自定义模式下可填根地址或完整端点，程序会自动识别协议（如 https://api.example.com/v1）",
            self.group,
        )
        self.ai_baseurl_edit = LineEdit(self.ai_baseurl_card)
        self.ai_baseurl_edit.setMinimumWidth(280)
        self.ai_baseurl_edit.setPlaceholderText("https://api.example.com/v1 或完整端点")
        self.ai_baseurl_edit.setText(ai_config.get("base_url") or "")
        self.ai_baseurl_card.hBoxLayout.addWidget(self.ai_baseurl_edit, 0, Qt.AlignmentFlag.AlignRight)
        self.ai_baseurl_card.hBoxLayout.addSpacing(16)
        self.group.addSettingCard(self.ai_baseurl_card)

        self.ai_apikey_card = SettingCard(
            FluentIcon.FINGERPRINT,
            "API Key",
            "输入对应服务的 API 密钥，获取方法请查阅服务商API文档",
            self.group,
        )
        self.ai_apikey_edit = PasswordLineEdit(self.ai_apikey_card)
        self.ai_apikey_edit.setMinimumWidth(280)
        self.ai_apikey_edit.setPlaceholderText("sk-...")
        self.ai_apikey_edit.setText(ai_config.get("api_key") or "")
        self.ai_apikey_card.hBoxLayout.addWidget(self.ai_apikey_edit, 0, Qt.AlignmentFlag.AlignRight)
        self.ai_apikey_card.hBoxLayout.addSpacing(16)
        self.group.addSettingCard(self.ai_apikey_card)

        self.ai_model_card = SettingCard(
            FluentIcon.DEVELOPER_TOOLS,
            "模型 ID",
            "请查阅所选服务商的API文档后再填写准确的模型id号，切勿随意填写",
            self.group,
        )
        # 可编辑下拉框 - 用于有推荐模型的服务商
        self.ai_model_combo = EditableComboBox(self.ai_model_card)
        self.ai_model_combo.setMinimumWidth(280)
        self.ai_model_combo.setPlaceholderText("输入或选择模型名称")
        current_model = ai_config.get("model") or ""
        if current_model:
            self.ai_model_combo.setText(current_model)
        # 纯输入框 - 用于自定义模式
        self.ai_model_edit = LineEdit(self.ai_model_card)
        self.ai_model_edit.setMinimumWidth(280)
        self.ai_model_edit.setPlaceholderText("输入模型名称")
        if current_model:
            self.ai_model_edit.setText(current_model)
        self.ai_model_card.hBoxLayout.addWidget(self.ai_model_combo, 0, Qt.AlignmentFlag.AlignRight)
        self.ai_model_card.hBoxLayout.addWidget(self.ai_model_edit, 0, Qt.AlignmentFlag.AlignRight)
        self.ai_model_card.hBoxLayout.addSpacing(16)
        self.group.addSettingCard(self.ai_model_card)

        self.ai_test_card = PushSettingCard(
            text="测试",
            icon=FluentIcon.SEND,
            title="测试 AI 连接",
            content="验证 API 配置是否正确",
            parent=self.group,
        )
        self.group.addSettingCard(self.ai_test_card)
        self.ai_test_spinner = IndeterminateProgressRing(self.ai_test_card)
        self.ai_test_spinner.setFixedSize(20, 20)
        self.ai_test_spinner.setStrokeWidth(2)
        self.ai_test_spinner.hide()
        insert_index = self.ai_test_card.hBoxLayout.indexOf(self.ai_test_card.button)
        if insert_index >= 0:
            self.ai_test_card.hBoxLayout.insertWidget(
                insert_index,
                self.ai_test_spinner,
                0,
                Qt.AlignmentFlag.AlignRight,
            )
            self.ai_test_card.hBoxLayout.insertSpacing(insert_index + 1, 6)

        self.ai_prompt_card = AIPromptSettingCard(
            self._ai_system_prompt,
            get_default_system_prompt(self._get_current_ai_mode()),
            self.group,
        )
        self.group.addSettingCard(self.ai_prompt_card)

    def bind_to_layout(self, layout):
        layout.addWidget(self.group)

    def _bind_events(self):
        self.ai_mode_combo.currentIndexChanged.connect(self._on_ai_mode_changed)
        self.ai_provider_combo.currentIndexChanged.connect(self._on_ai_provider_changed)
        self.ai_apikey_edit.editingFinished.connect(self._on_ai_apikey_changed)
        self.ai_baseurl_edit.editingFinished.connect(self._on_ai_baseurl_changed)
        self.ai_model_combo.currentTextChanged.connect(self._on_ai_model_changed)
        self.ai_model_edit.editingFinished.connect(self._on_ai_model_edit_changed)
        self.ai_test_card.clicked.connect(self._on_ai_test_clicked)
        self.ai_prompt_card.promptEdit.textChanged.connect(self._on_ai_prompt_changed)

    def update_config(self, cfg: RuntimeConfig):
        cfg.ai_mode = self._get_current_ai_mode()
        idx = self.ai_provider_combo.currentIndex()
        cfg.ai_provider = str(self.ai_provider_combo.itemData(idx)) if idx >= 0 else "deepseek"
        cfg.ai_api_key = self.ai_apikey_edit.text().strip()
        cfg.ai_base_url = self.ai_baseurl_edit.text().strip()
        cfg.ai_api_protocol = "auto"
        cfg.ai_model = self._get_current_model_value()
        cfg.ai_system_prompt = self._ai_system_prompt or get_default_system_prompt(cfg.ai_mode)

    def apply_config(self, cfg: RuntimeConfig):
        self._apply_ai_config(cfg)

    def _set_ai_controls_blocked(self, blocked: bool):
        try:
            self.ai_mode_combo.blockSignals(blocked)
            self.ai_provider_combo.blockSignals(blocked)
        except Exception as exc:
            log_suppressed_exception("_set_ai_controls_blocked: combo controls blockSignals(blocked)", exc, level=logging.WARNING)

    def _get_current_ai_mode(self) -> str:
        idx = self.ai_mode_combo.currentIndex()
        mode = str(self.ai_mode_combo.itemData(idx)) if idx >= 0 else "free"
        return mode if mode in self._AI_MODES else "free"

    def _set_ai_test_loading(self, loading: bool):
        self.ai_test_spinner.setVisible(loading)
        self.ai_test_card.button.setEnabled(not loading)

    def _show_ai_infobar(self, message: str, success: bool = True, duration: int = 2000):
        """安全地显示 InfoBar，关闭之前的避免动画冲突"""
        # 先关闭之前的 InfoBar


        if self._current_infobar is not None:
            try:
                self._current_infobar.close()
            except (RuntimeError, AttributeError):
                pass
            self._current_infobar = None
        
        # 显示新的 InfoBar
        infobar_func = InfoBar.success if success else InfoBar.error
        self._current_infobar = infobar_func(
            "",
            message,
            parent=self._owner.window(),
            position=InfoBarPosition.TOP,
            duration=duration,
        )

    def _show_ai_infobar_with_link(self, message: str, url: str):
        """显示带超链接按钮的警告 InfoBar"""
        if self._current_infobar is not None:
            try:
                self._current_infobar.close()
            except (RuntimeError, AttributeError):
                pass
            self._current_infobar = None

        bar = InfoBar.warning(
            "",
            message,
            parent=self._owner.window(),
            position=InfoBarPosition.TOP,
            duration=5000,
        )
        if url:
            link_btn = HyperlinkButton(FluentIcon.LINK, url, "查看 API 文档", bar)
            bar.addWidget(link_btn)
        self._current_infobar = bar

    def _update_ai_visibility(self):
        """根据当前模式与提供商更新 AI 配置项的可见性和推荐模型"""
        ai_mode = self._get_current_ai_mode()
        is_free_mode = ai_mode == "free"
        idx = self.ai_provider_combo.currentIndex()
        provider_key = str(self.ai_provider_combo.itemData(idx)) if idx >= 0 else "deepseek"
        is_custom = provider_key == "custom"
        self.ai_free_mode_bar.setVisible(is_free_mode)
        self.ai_privacy_bar.setVisible(not is_free_mode)
        self.ai_provider_card.setVisible(not is_free_mode)
        self.ai_apikey_card.setVisible(not is_free_mode)
        self.ai_model_card.setVisible(not is_free_mode)
        self.ai_baseurl_card.setVisible((not is_free_mode) and is_custom)
        if is_free_mode:
            return
        
        # 更新推荐模型列表
        provider_config = AI_PROVIDERS.get(provider_key, {})
        recommended_models = provider_config.get("recommended_models", [])
        default_model = provider_config.get("default_model", "")
        
        # 控制显示哪个输入控件
        self.ai_model_combo.setVisible(not is_custom)
        self.ai_model_edit.setVisible(is_custom)
        
        if is_custom:
            # 自定义模式：切换时清空（除非是初始化加载）
            if not self._ai_loading:
                self.ai_model_edit.setText("")
                save_ai_settings(model="")
        else:
            # 非自定义模式：清空并填充推荐模型
            self.ai_model_combo.clear()
            if recommended_models:
                self.ai_model_combo.addItems(recommended_models)
            
            # 更新占位符
            self.ai_model_combo.setPlaceholderText(default_model or "输入模型名称")
            
            # 切换服务商时使用新的默认模型（除非是初始化加载）
            if not self._ai_loading:
                self.ai_model_combo.setText(default_model)
                save_ai_settings(model=default_model)
        
        self._update_ai_doc_link(provider_key)

    def _apply_ai_config(self, cfg: RuntimeConfig):
        ai_config_present = getattr(cfg, "_ai_config_present", False)
        if not ai_config_present:
            ai_config = get_ai_settings()
            cfg.ai_mode = str(ai_config.get("ai_mode") or "free")
            cfg.ai_provider = str(ai_config.get("provider") or "deepseek")
            cfg.ai_api_key = str(ai_config.get("api_key") or "")
            cfg.ai_base_url = str(ai_config.get("base_url") or "")
            cfg.ai_api_protocol = str(ai_config.get("api_protocol") or "auto")
            cfg.ai_model = str(ai_config.get("model") or "")
            cfg.ai_system_prompt = str(ai_config.get("system_prompt") or "").strip() or get_default_system_prompt(cfg.ai_mode)
        if not getattr(cfg, "ai_provider", ""):
            cfg.ai_provider = "deepseek"
        if not getattr(cfg, "ai_mode", ""):
            cfg.ai_mode = "free"
        if cfg.ai_mode not in self._AI_MODES:
            cfg.ai_mode = "free"
        if not getattr(cfg, "ai_api_protocol", ""):
            cfg.ai_api_protocol = "auto"
        if not getattr(cfg, "ai_system_prompt", ""):
            cfg.ai_system_prompt = get_default_system_prompt(cfg.ai_mode)

        self._ai_loading = True
        self._set_ai_controls_blocked(True)
        mode_idx = self.ai_mode_combo.findData(cfg.ai_mode)
        self.ai_mode_combo.setCurrentIndex(mode_idx if mode_idx >= 0 else 0)
        idx = self.ai_provider_combo.findData(cfg.ai_provider)
        if idx >= 0:
            self.ai_provider_combo.setCurrentIndex(idx)
        else:
            self.ai_provider_combo.setCurrentIndex(0)
        self.ai_apikey_edit.setText(cfg.ai_api_key or "")
        self.ai_baseurl_edit.setText(cfg.ai_base_url or "")
        current_model = (cfg.ai_model or "").strip()
        self.ai_model_combo.setText(current_model)
        self.ai_model_edit.setText(current_model)
        self._last_ai_mode = cfg.ai_mode
        default_prompt = get_default_system_prompt(cfg.ai_mode)
        self._ai_system_prompt = cfg.ai_system_prompt or default_prompt
        self.ai_prompt_card.set_prompt_text(self._ai_system_prompt, default_prompt=default_prompt)
        self._update_ai_visibility()
        self._set_ai_controls_blocked(False)
        self._ai_loading = False

        save_ai_settings(
            ai_mode=cfg.ai_mode,
            provider=cfg.ai_provider,
            api_key=cfg.ai_api_key or "",
            base_url=cfg.ai_base_url or "",
            api_protocol="auto",
            model=cfg.ai_model or "",
            system_prompt=self._ai_system_prompt,
        )

    def _on_ai_mode_changed(self):
        """AI 模式变化"""
        if self._ai_loading:
            return
        ai_mode = self._get_current_ai_mode()
        previous_mode = getattr(self, "_last_ai_mode", "free")
        previous_default = get_default_system_prompt(previous_mode)
        current_prompt = str(self._ai_system_prompt or "").strip()
        next_default = get_default_system_prompt(ai_mode)
        if not current_prompt or current_prompt == previous_default:
            self._ai_system_prompt = next_default
            self.ai_prompt_card.set_prompt_text(self._ai_system_prompt, default_prompt=next_default)
            save_ai_settings(system_prompt=self._ai_system_prompt)
        else:
            self.ai_prompt_card.set_default_prompt(next_default)
        self._last_ai_mode = ai_mode
        save_ai_settings(ai_mode=ai_mode)
        self._update_ai_visibility()

    def _on_ai_provider_changed(self):
        """AI 提供商选择变化"""
        if self._ai_loading:
            return
        idx = self.ai_provider_combo.currentIndex()
        provider_key = str(self.ai_provider_combo.itemData(idx)) if idx >= 0 else "deepseek"
        save_ai_settings(provider=provider_key)
        self._update_ai_visibility()

    def _update_ai_doc_link(self, provider_key: str):
        url = self._PROVIDER_DOCS.get(provider_key, "")
        self.ai_provider_link.setVisible(provider_key != "custom")
        if url:
            self.ai_provider_link.setEnabled(True)
            self.ai_provider_link.setText("API文档")
            self.ai_provider_link.setUrl(url)
        else:
            self.ai_provider_link.setEnabled(False)
            self.ai_provider_link.setText("暂无文档")
            self.ai_provider_link.setUrl("")

    def _on_ai_apikey_changed(self):
        """API Key 变化"""
        if self._ai_loading:
            return
        save_ai_settings(api_key=self.ai_apikey_edit.text())

    def _on_ai_baseurl_changed(self):
        """Base URL 变化"""
        if self._ai_loading:
            return
        save_ai_settings(base_url=self.ai_baseurl_edit.text())

    def _on_ai_model_changed(self, text: str):
        """模型变化（EditableComboBox）"""
        if self._ai_loading:
            return
        save_ai_settings(model=text.strip())

    def _on_ai_model_edit_changed(self):
        """模型变化（LineEdit - 自定义模式）"""
        if self._ai_loading:
            return
        save_ai_settings(model=self.ai_model_edit.text().strip())

    def _get_current_model_value(self) -> str:
        """获取当前模型值"""
        if self.ai_model_edit.isVisible():
            return self.ai_model_edit.text().strip()
        return self.ai_model_combo.currentText().strip()

    def _on_ai_prompt_changed(self):
        """系统提示词变化"""
        if self._ai_loading:
            return
        self._ai_system_prompt = self.ai_prompt_card.prompt_text()
        save_ai_settings(system_prompt=self._ai_system_prompt)

    def _on_ai_test_clicked(self):
        """测试 AI 连接"""
        if self._ai_loading:
            return
        if self._ai_test_thread is not None and self._ai_test_thread.isRunning():
            return
        save_ai_settings(
            ai_mode=self._get_current_ai_mode(),
            api_key=self.ai_apikey_edit.text(),
            base_url=self.ai_baseurl_edit.text(),
            api_protocol="auto",
            model=self._get_current_model_value(),
            system_prompt=self._ai_system_prompt,
        )
        self._set_ai_test_loading(True)
        self._ai_test_thread = QThread()
        self._ai_test_worker = AITestWorker()
        self._ai_test_worker.moveToThread(self._ai_test_thread)
        self._ai_test_thread.started.connect(self._ai_test_worker.run)
        self._ai_test_worker.finished.connect(self._on_ai_test_finished)
        self._ai_test_worker.finished.connect(self._ai_test_thread.quit)
        self._ai_test_worker.finished.connect(self._ai_test_worker.deleteLater)
        self._ai_test_thread.finished.connect(self._ai_test_thread.deleteLater)
        self._ai_test_thread.finished.connect(self._on_ai_test_thread_finished)
        self._ai_test_thread.start()

    def _on_ai_test_finished(self, success: bool, message: str):
        """测试 AI 连接完成"""
        self._set_ai_test_loading(False)
        if success:
            self._show_ai_infobar(message, success=True, duration=3000)
        else:
            logging.error("AI 连接测试失败: %s", message)
            self._show_ai_infobar(message, success=False, duration=5000)

    def _on_ai_test_thread_finished(self):
        self._ai_test_thread = None
        self._ai_test_worker = None



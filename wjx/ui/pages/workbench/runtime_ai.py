import logging
from typing import Optional

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QSizePolicy, QPlainTextEdit, QVBoxLayout, QWidget
from qfluentwidgets import (
    ComboBox,
    FluentIcon,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarIcon,
    InfoBarPosition,
    HyperlinkButton,
    LineEdit,
    PasswordLineEdit,
    PushSettingCard,
    SettingCard,
    SettingCardGroup,
)

from wjx.ui.widgets.full_width_infobar import FullWidthInfoBar
from wjx.ui.workers.ai_test_worker import AITestWorker
from wjx.ui.pages.workbench.runtime_cards import SwitchSettingCard
from wjx.utils.integrations.ai_service import AI_PROVIDERS, DEFAULT_SYSTEM_PROMPT, get_ai_settings, save_ai_settings
from wjx.utils.io.load_save import RuntimeConfig


class RuntimeAISection:
    _PROVIDER_DOCS = {
        "deepseek": "https://api-docs.deepseek.com/zh-cn/",
        "qwen": "https://help.aliyun.com/zh/model-studio/get-api-key",
        "openai": "https://platform.openai.com/docs/quickstart?desktop-os=windows",
        "gemini": "https://ai.google.dev/gemini-api/docs/quickstart?hl=zh-cn",
        "custom": "https://platform.openai.com/docs/api-reference/introduction",
    }

    def __init__(self, parent_view: QWidget, owner: QWidget):
        self._owner = owner
        self.group = SettingCardGroup("AI 填空助手", parent_view)
        self._ai_loading = False
        self._ai_test_thread: Optional[QThread] = None
        self._ai_test_worker: Optional[AITestWorker] = None
        ai_config = get_ai_settings()
        self._ai_system_prompt = ai_config.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
        self._build_ui(ai_config)
        self._bind_events()
        self._update_ai_visibility()

    def _build_ui(self, ai_config):
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

        self.ai_enabled_card = SwitchSettingCard(
            FluentIcon.ROBOT,
            "启用 AI 填空",
            "开启后可使用 AI 自动生成填空题答案",
            parent=self.group,
        )
        self.ai_enabled_card.setChecked(bool(ai_config.get("enabled")))
        self.group.addSettingCard(self.ai_enabled_card)

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
            "自定义模式下的 API 地址（如 https://api.example.com/v1）",
            self.group,
        )
        self.ai_baseurl_edit = LineEdit(self.ai_baseurl_card)
        self.ai_baseurl_edit.setMinimumWidth(280)
        self.ai_baseurl_edit.setPlaceholderText("https://api.example.com/v1")
        self.ai_baseurl_edit.setText(ai_config.get("base_url") or "")
        self.ai_baseurl_card.hBoxLayout.addWidget(self.ai_baseurl_edit, 0, Qt.AlignmentFlag.AlignRight)
        self.ai_baseurl_card.hBoxLayout.addSpacing(16)
        self.group.addSettingCard(self.ai_baseurl_card)

        self.ai_apikey_card = SettingCard(
            FluentIcon.FINGERPRINT,
            "API Key",
            "输入对应服务的 API 密钥",
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
            "模型",
            "选择或输入模型名称",
            self.group,
        )
        self.ai_model_combo = ComboBox(self.ai_model_card)
        self.ai_model_combo.setMinimumWidth(200)
        self.ai_model_combo.addItem("deepseek-chat")
        self.ai_model_combo.addItem("deepseek-reasoner")
        self.ai_model_edit = LineEdit(self.ai_model_card)
        self.ai_model_edit.setMinimumWidth(200)
        self.ai_model_edit.setPlaceholderText("gpt-3.5-turbo")
        self.ai_model_edit.setText(ai_config.get("model") or "")
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

        self.ai_prompt_card = SettingCard(
            FluentIcon.EDIT,
            "系统提示词",
            "自定义 AI 填空的系统提示词（留空使用默认）",
            self.group,
        )
        self.ai_prompt_edit = QPlainTextEdit(self.ai_prompt_card)
        self.ai_prompt_edit.setPlaceholderText("留空使用默认提示词...")
        self.ai_prompt_edit.setPlainText(self._ai_system_prompt)
        self.ai_prompt_edit.setMaximumHeight(100)
        self.ai_prompt_edit.setMinimumHeight(80)
        prompt_container = QWidget(self.ai_prompt_card)
        prompt_layout = QVBoxLayout(prompt_container)
        prompt_layout.setContentsMargins(0, 0, 0, 0)
        prompt_layout.addWidget(self.ai_prompt_edit)
        self.ai_prompt_card.hBoxLayout.addWidget(prompt_container, 1)
        self.ai_prompt_card.hBoxLayout.addSpacing(16)
        self.group.addSettingCard(self.ai_prompt_card)

    def bind_to_layout(self, layout):
        layout.addWidget(self.group)

    def _bind_events(self):
        self.ai_enabled_card.switchButton.checkedChanged.connect(self._on_ai_enabled_toggled)
        self.ai_provider_combo.currentIndexChanged.connect(self._on_ai_provider_changed)
        self.ai_apikey_edit.editingFinished.connect(self._on_ai_apikey_changed)
        self.ai_baseurl_edit.editingFinished.connect(self._on_ai_baseurl_changed)
        self.ai_model_edit.editingFinished.connect(self._on_ai_model_changed)
        self.ai_model_combo.currentIndexChanged.connect(self._on_ai_model_combo_changed)
        self.ai_test_card.clicked.connect(self._on_ai_test_clicked)
        self.ai_prompt_edit.textChanged.connect(self._on_ai_prompt_changed)

    def update_config(self, cfg: RuntimeConfig):
        cfg.ai_enabled = bool(self.ai_enabled_card.switchButton.isChecked())
        idx = self.ai_provider_combo.currentIndex()
        cfg.ai_provider = str(self.ai_provider_combo.itemData(idx)) if idx >= 0 else "deepseek"
        cfg.ai_api_key = self.ai_apikey_edit.text().strip()
        cfg.ai_base_url = self.ai_baseurl_edit.text().strip()
        cfg.ai_model = self._get_current_model_value()
        cfg.ai_system_prompt = self._ai_system_prompt or DEFAULT_SYSTEM_PROMPT

    def apply_config(self, cfg: RuntimeConfig):
        self._apply_ai_config(cfg)

    def _set_ai_controls_blocked(self, blocked: bool):
        try:
            self.ai_enabled_card.switchButton.blockSignals(blocked)
            self.ai_provider_combo.blockSignals(blocked)
        except Exception:
            pass

    def _set_ai_test_loading(self, loading: bool):
        self.ai_test_spinner.setVisible(loading)
        self.ai_test_card.button.setEnabled(not loading)

    def _update_ai_visibility(self):
        """根据选择的提供商更新 AI 配置项的可见性"""
        idx = self.ai_provider_combo.currentIndex()
        provider_key = str(self.ai_provider_combo.itemData(idx)) if idx >= 0 else "deepseek"
        is_custom = provider_key == "custom"
        self.ai_baseurl_card.setVisible(is_custom)
        provider_config = AI_PROVIDERS.get(provider_key, {})
        default_model = provider_config.get("default_model", "")
        self.ai_model_edit.setPlaceholderText(default_model or "模型名称")

        is_deepseek = provider_key == "deepseek"
        self.ai_model_combo.setVisible(is_deepseek)
        self.ai_model_edit.setVisible(not is_deepseek)
        if is_deepseek:
            current_model = self._get_current_model_value().strip()
            if not current_model:
                current_model = "deepseek-chat"
                if not self._ai_loading:
                    save_ai_settings(model=current_model)
            combo_idx = self.ai_model_combo.findText(current_model)
            if combo_idx >= 0:
                self.ai_model_combo.setCurrentIndex(combo_idx)
            else:
                self.ai_model_combo.setCurrentIndex(0)
        self._update_ai_doc_link(provider_key)

    def _apply_ai_config(self, cfg: RuntimeConfig):
        ai_config_present = getattr(cfg, "_ai_config_present", False)
        if not ai_config_present:
            ai_config = get_ai_settings()
            cfg.ai_enabled = bool(ai_config.get("enabled"))
            cfg.ai_provider = str(ai_config.get("provider") or "deepseek")
            cfg.ai_api_key = str(ai_config.get("api_key") or "")
            cfg.ai_base_url = str(ai_config.get("base_url") or "")
            cfg.ai_model = str(ai_config.get("model") or "")
            cfg.ai_system_prompt = str(ai_config.get("system_prompt") or DEFAULT_SYSTEM_PROMPT)
        if not getattr(cfg, "ai_provider", ""):
            cfg.ai_provider = "deepseek"
        if not getattr(cfg, "ai_system_prompt", ""):
            cfg.ai_system_prompt = DEFAULT_SYSTEM_PROMPT

        self._ai_loading = True
        self._set_ai_controls_blocked(True)
        self.ai_enabled_card.switchButton.setChecked(bool(cfg.ai_enabled))
        idx = self.ai_provider_combo.findData(cfg.ai_provider)
        if idx >= 0:
            self.ai_provider_combo.setCurrentIndex(idx)
        else:
            self.ai_provider_combo.setCurrentIndex(0)
        self.ai_apikey_edit.setText(cfg.ai_api_key or "")
        self.ai_baseurl_edit.setText(cfg.ai_base_url or "")
        current_model = (cfg.ai_model or "").strip()
        if not current_model and cfg.ai_provider == "deepseek":
            current_model = "deepseek-chat"
        self.ai_model_edit.setText(current_model)
        combo_idx = self.ai_model_combo.findText(current_model)
        if combo_idx >= 0:
            self.ai_model_combo.setCurrentIndex(combo_idx)
        else:
            self.ai_model_combo.setCurrentIndex(0)
        self._ai_system_prompt = cfg.ai_system_prompt or DEFAULT_SYSTEM_PROMPT
        self.ai_prompt_edit.setPlainText(self._ai_system_prompt)
        self._update_ai_visibility()
        self._set_ai_controls_blocked(False)
        self._ai_loading = False

        save_ai_settings(
            enabled=bool(cfg.ai_enabled),
            provider=cfg.ai_provider,
            api_key=cfg.ai_api_key or "",
            base_url=cfg.ai_base_url or "",
            model=cfg.ai_model or "",
            system_prompt=self._ai_system_prompt,
        )

    def _on_ai_enabled_toggled(self, checked: bool):
        """AI 功能开关切换"""
        if self._ai_loading:
            return
        save_ai_settings(enabled=checked)
        InfoBar.success(
            "",
            f"AI 填空功能已{'开启' if checked else '关闭'}",
            parent=self._owner.window(),
            position=InfoBarPosition.TOP,
            duration=2000,
        )

    def _on_ai_provider_changed(self):
        """AI 提供商选择变化"""
        if self._ai_loading:
            return
        idx = self.ai_provider_combo.currentIndex()
        provider_key = str(self.ai_provider_combo.itemData(idx)) if idx >= 0 else "deepseek"
        save_ai_settings(provider=provider_key)
        self._update_ai_visibility()
        if provider_key != "deepseek":
            if self.ai_model_edit.isVisible():
                current_model = self.ai_model_edit.text().strip()
                if current_model in {"deepseek-chat", "deepseek-reasoner"}:
                    self.ai_model_edit.setText("")
                    save_ai_settings(model="")
        provider_config = AI_PROVIDERS.get(provider_key, {})
        InfoBar.success(
            "",
            f"AI 服务已切换为：{provider_config.get('label', provider_key)}",
            parent=self._owner.window(),
            position=InfoBarPosition.TOP,
            duration=2000,
        )

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

    def _on_ai_model_changed(self):
        """模型变化"""
        if self._ai_loading:
            return
        if not self.ai_model_edit.isVisible():
            return
        save_ai_settings(model=self.ai_model_edit.text())

    def _on_ai_model_combo_changed(self):
        """DeepSeek 模型变化"""
        if self._ai_loading:
            return
        if not self.ai_model_combo.isVisible():
            return
        save_ai_settings(model=self._get_current_model_value())

    def _get_current_model_value(self) -> str:
        if self.ai_model_combo.isVisible():
            return self.ai_model_combo.currentText().strip()
        return self.ai_model_edit.text().strip()

    def _on_ai_prompt_changed(self):
        """系统提示词变化"""
        if self._ai_loading:
            return
        self._ai_system_prompt = self.ai_prompt_edit.toPlainText().strip() or DEFAULT_SYSTEM_PROMPT
        save_ai_settings(system_prompt=self._ai_system_prompt)

    def _on_ai_test_clicked(self):
        """测试 AI 连接"""
        if self._ai_loading:
            return
        if self._ai_test_thread is not None and self._ai_test_thread.isRunning():
            return
        save_ai_settings(
            enabled=True,
            api_key=self.ai_apikey_edit.text(),
            base_url=self.ai_baseurl_edit.text(),
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
            InfoBar.success("", message, parent=self._owner.window(), position=InfoBarPosition.TOP, duration=3000)
        else:
            logging.error("AI 连接测试失败: %s", message)
            InfoBar.error("", message, parent=self._owner.window(), position=InfoBarPosition.TOP, duration=5000)
        save_ai_settings(enabled=self.ai_enabled_card.switchButton.isChecked())

    def _on_ai_test_thread_finished(self):
        self._ai_test_thread = None
        self._ai_test_worker = None

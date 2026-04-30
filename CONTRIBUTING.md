# 贡献指南

感谢愿意改进本项目！在开始之前，请先阅读 [行为准则](CODE_OF_CONDUCT.md)。

## 快速开始
- **交流**：首选 GitHub Issues，或加入 QQ 群（见 README）。
- **参考**：服务接口信息统一改为在线查阅，优先看 API 文档：https://api-wjx.hungrym0.top/api/document
- **环境**：Python 3.11+，Windows 10/11。执行 `pip install -r requirements.txt` 安装依赖。

<details>
<summary><b>📂 点击查看项目目录结构</b></summary>

```markdown
仓库根目录
├── .editorconfig
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── 报错反馈.md
│   │   └── 新功能请求.md
│   └── workflows/
│       ├── deploy-worker.yml
│       ├── python-ci.yml
│       └── release-to-r2.yml
├── .gitignore
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
├── SurveyController.py
├── SurveyController.spec
├── CI/
│   ├── __init__.py
│   ├── python_ci.py
│   ├── live_tests/
│   │   ├── __init__.py
│   │   └── test_survey_parsers.py
│   ├── python_checks/
│   │   ├── __init__.py
│   │   ├── common.py
│   │   ├── compile_check.py
│   │   ├── import_check.py
│   │   ├── pyright_check.py
│   │   ├── ruff_check.py
│   │   ├── unit_test_check.py
│   │   └── window_smoke_check.py
│   ├── unit_tests/
│   │   ├── __init__.py
│   │   ├── app/
│   │   │   ├── __init__.py
│   │   │   ├── test_browser_probe.py
│   │   │   ├── test_config_codec.py
│   │   │   └── test_runtime_paths.py
│   │   ├── engine/
│   │   │   ├── __init__.py
│   │   │   ├── test_browser_session_service.py
│   │   │   ├── test_cleanup.py
│   │   │   ├── test_execution_loop.py
│   │   │   ├── test_provider_common.py
│   │   │   ├── test_reverse_fill_runtime.py
│   │   │   ├── test_run_stop_policy.py
│   │   │   ├── test_runtime_control.py
│   │   │   ├── test_runtime_init_gate.py
│   │   │   └── test_submission_service.py
│   │   ├── providers/
│   │   │   ├── __init__.py
│   │   │   ├── test_common.py
│   │   │   ├── test_credamo_parser.py
│   │   │   ├── test_credamo_runtime.py
│   │   │   ├── test_credamo_runtime_helpers.py
│   │   │   ├── test_credamo_runtime_waits.py
│   │   │   ├── test_survey_cache.py
│   │   │   ├── test_tencent_runtime.py
│   │   │   ├── test_wjx_reverse_fill.py
│   │   │   └── test_wjx_runtime.py
│   │   ├── psychometrics/
│   │   │   ├── __init__.py
│   │   │   ├── test_joint_optimizer.py
│   │   │   ├── test_orientation.py
│   │   │   └── test_psychometric.py
│   │   └── questions/
│   │       ├── __init__.py
│   │       ├── test_meta_helpers.py
│   │       └── test_validation.py
│   └── worker/
│       ├── src/
│       │   ├── constants.js
│       │   ├── github.js
│       │   ├── index.js
│       │   ├── message.js
│       │   ├── request.js
│       │   ├── response.js
│       │   └── telegram.js
│       └── wrangler.toml
├── assets/
├── credamo/
│   ├── __init__.py
│   └── provider/
│       ├── __init__.py
│       ├── parser.py
│       ├── runtime.py
│       ├── runtime_answerers.py
│       ├── runtime_dom.py
│       └── submission.py
├── icon.ico
├── requirements.txt
├── rthook_pyside6.py
├── software/
│   ├── __init__.py
│   ├── app/
│   │   ├── __init__.py
│   │   ├── browser_probe.py
│   │   ├── config.py
│   │   ├── main.py
│   │   ├── runtime_paths.py
│   │   ├── settings_store.py
│   │   └── version.py
│   ├── assets/
│   │   ├── __init__.py
│   │   ├── area.txt
│   │   ├── area_codes_2022.json
│   │   └── legal/
│   │       ├── privacy_statement.txt
│   │       └── service_terms.txt
│   ├── core/
│   │   ├── __init__.py
│   │   ├── ai/
│   │   │   ├── __init__.py
│   │   │   └── runtime.py
│   │   ├── config/
│   │   │   ├── __init__.py
│   │   │   ├── codec.py
│   │   │   └── schema.py
│   │   ├── engine/
│   │   │   ├── __init__.py
│   │   │   ├── browser_session_service.py
│   │   │   ├── cleanup.py
│   │   │   ├── dom_helpers.py
│   │   │   ├── driver_factory.py
│   │   │   ├── execution_loop.py
│   │   │   ├── failure_reason.py
│   │   │   ├── navigation.py
│   │   │   ├── provider_common.py
│   │   │   ├── run_stop_policy.py
│   │   │   ├── runtime_control.py
│   │   │   ├── runner.py
│   │   │   └── submission_service.py
│   │   ├── modes/
│   │   │   ├── __init__.py
│   │   │   ├── duration_control.py
│   │   │   └── timed_mode.py
│   │   ├── persona/
│   │   │   ├── __init__.py
│   │   │   ├── context.py
│   │   │   └── generator.py
│   │   ├── psychometrics/
│   │   │   ├── __init__.py
│   │   │   ├── joint_optimizer.py
│   │   │   ├── orientation.py
│   │   │   ├── psychometric.py
│   │   │   └── utils.py
│   │   ├── questions/
│   │   │   ├── __init__.py
│   │   │   ├── config.py
│   │   │   ├── consistency.py
│   │   │   ├── default_builder.py
│   │   │   ├── distribution.py
│   │   │   ├── meta_helpers.py
│   │   │   ├── normalization.py
│   │   │   ├── reliability_mode.py
│   │   │   ├── schema.py
│   │   │   ├── strict_ratio.py
│   │   │   ├── tendency.py
│   │   │   ├── text_shared.py
│   │   │   ├── types/
│   │   │   │   └── __init__.py
│   │   │   ├── utils.py
│   │   │   └── validation.py
│   │   ├── reverse_fill/
│   │   │   ├── __init__.py
│   │   │   ├── parser.py
│   │   │   ├── runtime.py
│   │   │   ├── schema.py
│   │   │   └── validation.py
│   │   └── task/
│   │       ├── __init__.py
│   │       └── task_context.py
│   ├── integrations/
│   │   ├── __init__.py
│   │   └── ai/
│   │       ├── __init__.py
│   │       ├── client.py
│   │       ├── free_api.py
│   │       ├── protocols.py
│   │       └── settings.py
│   ├── io/
│   │   ├── __init__.py
│   │   ├── config/
│   │   ├── markdown/
│   │   ├── qr/
│   │   ├── reports/
│   │   └── spreadsheets/
│   ├── logging/
│   │   ├── __init__.py
│   │   ├── action_logger.py
│   │   └── log_utils.py
│   ├── network/
│   │   ├── __init__.py
│   │   ├── browser/
│   │   │   ├── __init__.py
│   │   │   ├── driver.py
│   │   │   ├── element.py
│   │   │   ├── exceptions.py
│   │   │   ├── manager.py
│   │   │   ├── options.py
│   │   │   ├── session.py
│   │   │   ├── startup.py
│   │   │   └── transient.py
│   │   ├── http/
│   │   │   ├── __init__.py
│   │   │   └── client.py
│   │   ├── proxy/
│   │   │   ├── __init__.py
│   │   │   ├── api/
│   │   │   │   ├── __init__.py
│   │   │   │   └── provider.py
│   │   │   ├── areas/
│   │   │   │   ├── __init__.py
│   │   │   │   └── service.py
│   │   │   ├── policy/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── quota.py
│   │   │   │   ├── settings.py
│   │   │   │   └── source.py
│   │   │   ├── pool/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── pool.py
│   │   │   │   └── prefetch.py
│   │   │   └── session/
│   │   │       ├── __init__.py
│   │   │       ├── auth.py
│   │   │       ├── client.py
│   │   │       ├── models.py
│   │   │       └── normalize.py
│   │   └── session_policy.py
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── common.py
│   │   ├── contracts.py
│   │   ├── registry.py
│   │   └── survey_cache.py
│   ├── system/
│   │   ├── __init__.py
│   │   ├── power_management.py
│   │   ├── registry_manager.py
│   │   └── secure_store.py
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── theme.json
│   │   ├── controller/
│   │   │   ├── __init__.py
│   │   │   ├── run_controller.py
│   │   │   └── run_controller_parts/
│   │   │       ├── __init__.py
│   │   │       ├── parsing.py
│   │   │       ├── persistence.py
│   │   │       ├── runtime.py
│   │   │       ├── runtime_constants.py
│   │   │       ├── runtime_execution.py
│   │   │       ├── runtime_init_gate.py
│   │   │       └── runtime_random_ip.py
│   │   ├── dialogs/
│   │   │   ├── __init__.py
│   │   │   ├── contact.py
│   │   │   └── terms_of_service.py
│   │   ├── helpers/
│   │   │   ├── __init__.py
│   │   │   ├── ai_fill.py
│   │   │   ├── contact_api.py
│   │   │   ├── fluent_tooltip.py
│   │   │   ├── image_attachments.py
│   │   │   ├── proxy_access.py
│   │   │   └── qfluent_compat.py
│   │   ├── pages/
│   │   │   ├── __init__.py
│   │   │   ├── community.py
│   │   │   ├── more/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── about.py
│   │   │   │   ├── changelog.py
│   │   │   │   ├── donate.py
│   │   │   │   ├── ip_usage.py
│   │   │   │   └── support.py
│   │   │   ├── settings/
│   │   │   │   ├── __init__.py
│   │   │   │   └── settings.py
│   │   │   └── workbench/
│   │   │       ├── __init__.py
│   │   │       ├── dashboard/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── cards.py
│   │   │       │   ├── page.py
│   │   │       │   └── parts/
│   │   │       │       ├── __init__.py
│   │   │       │       ├── clipboard.py
│   │   │       │       ├── config_io.py
│   │   │       │       ├── entries.py
│   │   │       │       ├── progress.py
│   │   │       │       ├── random_ip.py
│   │   │       │       ├── run_actions.py
│   │   │       │       └── survey_parse.py
│   │   │       ├── log_panel/
│   │   │       │   ├── __init__.py
│   │   │       │   └── page.py
│   │   │       ├── question_editor/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── add_dialog.py
│   │   │       │   ├── add_preview.py
│   │   │       │   ├── constants.py
│   │   │       │   ├── page.py
│   │   │       │   ├── psycho_config.py
│   │   │       │   ├── utils.py
│   │   │       │   ├── wizard_cards.py
│   │   │       │   ├── wizard_dialog.py
│   │   │       │   ├── wizard_navigation.py
│   │   │       │   ├── wizard_search.py
│   │   │       │   ├── wizard_sections.py
│   │   │       │   ├── wizard_sections_common.py
│   │   │       │   ├── wizard_sections_matrix.py
│   │   │       │   ├── wizard_sections_slider.py
│   │   │       │   └── wizard_sections_text.py
│   │   │       ├── reverse_fill/
│   │   │       │   ├── __init__.py
│   │   │       │   └── page.py
│   │   │       ├── runtime_panel/
│   │   │       │   ├── __init__.py
│   │   │       │   ├── ai.py
│   │   │       │   ├── cards.py
│   │   │       │   └── main.py
│   │   │       └── strategy/
│   │   │           ├── __init__.py
│   │   │           ├── dimension_panel.py
│   │   │           ├── dimension_sections.py
│   │   │           ├── page.py
│   │   │           ├── question_selector_dialog.py
│   │   │           ├── rule_dialog.py
│   │   │           └── utils.py
│   │   ├── shell/
│   │   │   ├── __init__.py
│   │   │   ├── boot.py
│   │   │   ├── main_window.py
│   │   │   └── main_window_parts/
│   │   │       ├── __init__.py
│   │   │       ├── dialogs.py
│   │   │       ├── lazy_pages.py
│   │   │       ├── lifecycle.py
│   │   │       └── update.py
│   │   ├── widgets/
│   │   │   ├── __init__.py
│   │   │   ├── adaptive_flow_layout.py
│   │   │   ├── config_drawer.py
│   │   │   ├── contact_form/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── attachments.py
│   │   │   │   ├── constants.py
│   │   │   │   ├── donation.py
│   │   │   │   ├── inputs.py
│   │   │   │   ├── submission.py
│   │   │   │   ├── verification.py
│   │   │   │   └── widget.py
│   │   │   ├── full_width_infobar.py
│   │   │   ├── log_highlighter.py
│   │   │   ├── no_wheel.py
│   │   │   ├── paste_only_menu.py
│   │   │   ├── ratio_slider.py
│   │   │   ├── setting_cards.py
│   │   │   └── status_polling_mixin.py
│   │   └── workers/
│   │       ├── __init__.py
│   │       ├── ai_test_worker.py
│   │       └── update_worker.py
│   └── update/
│       ├── __init__.py
│       └── updater.py
├── tencent/
│   ├── __init__.py
│   └── provider/
│       ├── __init__.py
│       ├── navigation.py
│       ├── parser.py
│       ├── runtime.py
│       ├── runtime_answerers.py
│       ├── runtime_flow.py
│       ├── runtime_interactions.py
│       └── submission.py
└── wjx/
   ├── __init__.py
   └── provider/
      ├── __init__.py
      ├── _submission_core.py
      ├── detection.py
      ├── html_parser.py
      ├── html_parser_choice.py
      ├── html_parser_common.py
      ├── html_parser_matrix.py
      ├── html_parser_rules.py
      ├── navigation.py
      ├── parser.py
      ├── questions/
      │   ├── __init__.py
      │   ├── dropdown.py
      │   ├── matrix.py
      │   ├── multiple.py
      │   ├── multiple_dom.py
      │   ├── multiple_limits.py
      │   ├── multiple_rules.py
      │   ├── reorder.py
      │   ├── scale.py
      │   ├── score.py
      │   ├── single.py
      │   ├── slider.py
      │   └── text.py
      ├── runtime.py
      ├── runtime_dispatch.py
      ├── submission.py
      ├── submission_pages.py
      └── submission_proxy.py
```

</details>

## PR 流程
1. **Fork** 本仓库并创建特性分支。
2. **开发**：
   - 共享代码进入 `software/`。
   - 平台专属逻辑进入对应的 `provider/` 子目录。
   - 保持顶层包（`wjx/`、`tencent/`、`credamo/`）简洁，仅保留包标记；Credamo 见数没有旧共享兼容转发层，权威实现直接在 `credamo/provider/`。
3. **自测**：
   - 打开拉取请求先确保能够通过 CI 检查。
   - 最少手动跑一次受影响的核心流程，并在 PR 里写清楚结果。
4. **提交**：
   - PR 描述请写明改动目的、测试结果，如果有的话关联相关 Issue。

## 开发规范
- **模块化**：按职责拆分文件，避免“巨型文件”；新功能应放入对应的子目录。
- **UI 组件**：使用 `QfluentWidgets` 原生组件，保持界面风格统一。
- **友好说明**：输出信息应简洁易懂，面向小白用户，避免过度使用专业术语。
- **文档规范**：尽可能少地使用 emoji 表情符号。使用 HTML 标签折叠过长的文本内容，保持文档清晰。

欢迎贡献新的题型支持、平台适配或性能优化，感谢你的支持！

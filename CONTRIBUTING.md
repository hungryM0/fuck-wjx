# 贡献指南

感谢愿意改进本项目！在开始之前，请先阅读 `CODE_OF_CONDUCT.md`，确保遵守行为准则。

## 交流渠道
- **Bug/功能建议**：首选 GitHub Issues。
- **快速反馈**：QQ群（见 README）。

## 开发环境与依赖
- 操作系统：Windows 10/11 或 Linux。
- Python：3.8+。
- 安装依赖：`pip install -r requirements.txt`。
- 从源码运行：`python fuck-wjx.py`。

## 当前目录结构（`wjx/`）
- `main.py`：GUI 程序入口。
- `boot.py`：启动流程相关。
- `assets/`：针对指定地区随机ip的地区行政编码。
- `core/`：核心业务逻辑。
  - `engine/`：执行引擎（driver/runtime_control/navigation/submission/runner 等）。
  - `survey/`：问卷解析与检测。
  - `questions/`：题目配置与题型实现（`types/`）。
  - `captcha/`：验证码处理。
  - `ai/`：AI 运行时。
  - `persona/`：画像与上下文约束。
  - `stats/`：统计收集、持久化、分析。
  - `services/`：核心服务层（如地区数据加载）。
  - `state.py`：运行状态与全局控制变量。
- `ui/`：界面层。
  - `main_window.py`：主窗口编排。
  - `controller/`：运行控制器（`run_controller.py`）。
  - `pages/`：各页面（workbench/account/settings/more）。
  - `widgets/`：通用 UI 组件。
  - `dialogs/`：对话框。
  - `helpers/`、`workers/`：界面辅助逻辑与后台任务。
- `network/`：网络相关。
  - `browser/driver.py`：浏览器驱动封装。
  - `proxy/provider.py`：随机 IP/代理逻辑。
  - `http_client.py`、`session_policy.py`：请求与会话策略。
- `modes/`：运行模式控制（如定时模式）。
- `utils/`：通用工具（`app/io/integrations/system/logging/update`）。

## PR 流程（推荐）
1. Fork 仓库并创建功能分支（例：`feature/xxx`）。
2. `pip install -r requirements.txt` 安装依赖。
3. 开发时遵守现有分层：核心逻辑放 `wjx/core`，界面相关放 `wjx/ui`，网络放 `wjx/network`，通用工具放 `wjx/utils`。
4. 自测：至少手动跑一次核心流程（启动、加载问卷、配置、开始运行），确保无报错；有脚本/测试时一并运行。
5. 提交：保持清晰提交信息，必要时补充中文注释和变更说明。
6. PR 描述：写明变更目的、主要改动点、测试方式与结果，关联相关 Issue（如有）。

## 代码与文档风格
- 维持现有命名与目录结构，不要把无关功能塞进同一文件。
- GUI 优先使用 `QfluentWidgets` 原生组件。
- 文档、提示信息优先简体中文，保证小白也能看懂。

## 行为要求
- 严禁将本项目用于伪造学术数据、非法刷问卷或任何污染他人数据的行为。
- 如发现违规，请邮件 `mail@hungrym0.top` 举报。

欢迎提交 PR 改进问卷解析、题型支持、性能优化、界面体验等内容。谢谢！

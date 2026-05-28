# 贡献指南

感谢愿意改进本项目。开始前，请先阅读 [行为准则](CODE_OF_CONDUCT.md)。

本文面向开发者。目标是让你能从源码跑起来、提交一份容易 review 的 Pull Request。

## 开发环境

需要准备：

- Windows 10/11
- Python 3.13.13
- Git
- uv 包管理器

安装 uv（如果没有的话）：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## 开发流程

下面按第一次参与贡献的流程来写。

### 1. Fork 仓库

先在本仓库主页点击 **Fork**。

Fork 后，你会得到一份自己的仓库，例如：

```text
https://github.com/你的用户名/SurveyController
```

后续改动**先推送到你自己的仓库**，再向主仓库提交 Pull Request。

### 2. 克隆自己的 Fork

不要直接克隆主仓库——如果你没有被赋予直接推送到主仓库的权限。

假设你的 Fork 仓库名就是 SurveyController，先从你的 Fork 克隆到本地：

```bash
git clone https://github.com/你的用户名/SurveyController.git
cd SurveyController
```

### 3. 安装依赖并启动项目

进入项目目录后，用 uv 安装依赖：

```bash
uv sync
```

启动程序：

```bash
uv run python SurveyController.py
```

### 4. 添加主仓库地址并同步最新代码

把主仓库添加为 `upstream`：

```bash
git remote add upstream https://github.com/SurveyController/SurveyController.git
git remote -v
```

看到 `origin` 和 `upstream` 都存在就行：

```text
origin    你的 Fork 地址
upstream  https://github.com/SurveyController/SurveyController.git
```

**每次开始新功能前，先同步主仓库最新代码：**

```bash
git checkout main
git fetch upstream
git pull upstream main
```

### 5. 创建开发分支

**不建议直接在 `main` 分支上做出改动。**

每个修复或功能都开一个新分支：

```bash
git checkout -b fix/short-description
```

分支名可以这样写：

```bash
fix/login-crash
fix/tencent-parser
feature/export-report
docs/contributing-flow
```

含义：

- `fix/xxx`：修 bug。
- `feature/xxx`：加功能。
- `docs/xxx`：改文档。
- `refactor/xxx`：重构。

> [!IMPORTANT]
> 每个分支只对应单一的改动，**不要在一个分支里猛塞多个新功能！**

### 6. 暂存与提交文件

Git 提交分两步：

1. 暂存：告诉 Git 这次准备提交哪些文件。
2. 提交：把暂存内容保存成一次历史记录。

在此之前，先看一眼实际会进提交的文件：

```bash
git status --short
```

> [!IMPORTANT]
> **不要把 IDE 工作区垃圾、个人本地配置、临时文件一起提交进来！**

比如 `.trae/`、`.idea/`、`.vscode/`、`AGENTS.md`、`.kiro/`、编辑器缓存、截图草稿、临时导出文件。这些东西和项目代码无关，塞进仓库只会污染 review。

暂存所有改动：

```bash
git add .
```

提交已暂存的更改：

```bash
git commit -m "在此处输入你的提交信息"
```

提交信息建议写成：

```text
类型: 简短说明
```

常见类型：

```text
fix: 修复问题
feature: 新增功能
docs: 修改文档
test: 添加或修改测试
refactor: 重构代码
build: 构建或依赖调整
```

例子：

```bash
git commit -m "fix: handle empty tencent question title"
git commit -m "test: add workbench session regression"
git commit -m "docs: explain pull request workflow"
```

### 7. 推送分支

第一次推送当前分支：

```bash
git push -u origin 当前分支名
```

例如：

```bash
git push -u origin docs/contributing-flow
```

以后同一个分支继续提交后，只需要：

```bash
git push
```

### 8. 提交 Pull Request

推送后，GitHub 通常会提示 **Compare & pull request**。

确认方向是：

```text
你的 Fork 分支 -> SurveyController/SurveyController 的 main 分支
```

PR 描述里写清楚：

- 改了什么。
- 为什么改。
- 跑过哪些检查。
- 有没有用户能看见的变化。

### 9. 根据 review 修改

如果维护者提出修改意见，继续在同一个分支上改：

```bash
git add 修改过的文件
git commit -m "fix: address review comments"
git push
```

同一个 PR 会自动更新，不需要重新开 PR。

提交前请确认：

- 改动只包含本次 PR 需要的内容。
- 没有提交 `.trae/`、`.idea/`、`.vscode/` 等 IDE 工作区目录。
- 没有提交 `__pycache__`、`.pyc`、日志、缓存、构建产物。
- 没有提交密钥、代理套餐等敏感信息。
- 用户数据仍写入用户目录，不写回安装目录。

## 常见改动位置

| 目标 | 目录 |
| --- | --- |
| 问卷星解析、提交、题型处理 | `wjx/provider/` |
| 腾讯问卷适配 | `tencent/provider/` |
| Credamo 见数适配 | `credamo/provider/` |
| 通用执行引擎、任务调度 | `software/core/` |
| UI 页面、弹窗、组件 | `software/ui/` |
| 配置读写、表格、二维码、报告 | `software/io/` |
| HTTP、代理配置 | `software/network/` |
| AI 接入 | `software/integrations/ai/`、`software/core/ai/` |
| 更新日志入口、更多菜单 | `software/ui/shell/main_window_parts/lazy_pages.py` |
| 自动更新 | `software/update/` |
| 单元测试 | `CI/unit_tests/` |
| live tests | `CI/live_tests/` |
| CI 检查脚本 | `CI/python_checks/`、`CI/python_ci.py` |

不要把新功能塞进不相干文件。屎山通常就是这么长出来的。

如果新增或删除顶层目录，需同步更新本文档里的结构说明。

## 代码要求

- Python 代码保持简单直白，优先复用现有模块。
- GUI 一律使用 QFluentWidgets 原生组件。
- 尽量**不要使用 emoji 表情符号**，而应该要使用 QFluentWidgets 提供的图标资源。
- 当前分支用纯 HTTP 完成问卷提交，不要新增 Playwright、Selenium 或浏览器自动化依赖。
- `software/app/runtime_paths.py` 只表示安装目录和只读资源目录，不要把它当可写目录。
- 用户配置写入 `%AppData%\SurveyController\`。
- 日志和缓存写入 `%LocalAppData%\SurveyController\`。

## 本地检查

快速检查：

```bash
uv run python CI/python_ci.py
```

完整检查：

```bash
uv run python CI/python_ci.py --full
```

只跑单测：

```bash
uv run pytest CI/unit_tests
```

完整检查会额外做模块导入和主窗口冒烟测试。涉及启动链路、UI、HTTP 提交链路、配置迁移时，建议跑完整检查。

## 测试建议

改哪一块，就补哪一块测试：

- 解析器、题型规则：补 `CI/unit_tests/questions/` 或 `CI/unit_tests/providers/`。
- 配置、路径、迁移：补 `CI/unit_tests/app/`。
- 执行引擎：补 `CI/unit_tests/engine/`。
- 代理、网络策略：补对应已有测试文件。
- UI 纯展示改动可不强制补单测，但要手动启动看一遍。

不要在测试里访问真实问卷、真实账号、真实付费代理。

## Pull Request 要求

PR 描述请写清楚：

- 改了什么。
- 为什么改。
- 影响哪些功能。
- 跑过哪些检查。
- 是否有用户可见变化。

建议格式：

```markdown
## 简述改动
- ...

## 影响
- ...

## 解决的问题
- ...
```

如果修复 Issue，请在 PR 描述里关联：

```markdown
Fixes #123
```

## 仓库结构

```markdown
仓库根目录
├── .github/                 # GitHub Issue 模板和 Actions
├── assets/                  # README、图标等仓库资源
├── CI/                      # 检查脚本、单测、live tests
├── credamo/                 # Credamo 见数平台适配
├── Setup/                   # 安装包相关资源
├── software/                # 桌面应用主体
│   ├── app/                 # 启动、路径、配置、版本、迁移
│   ├── assets/              # 应用内资源
│   ├── core/                # 核心业务、执行引擎、题目模型
│   ├── integrations/        # 外部服务接入
│   ├── io/                  # 文件读写、报告、二维码、表格
│   ├── logging/             # 日志
│   ├── network/             # HTTP、代理配置
│   ├── providers/           # 平台提供方公共层
│   ├── system/              # 系统能力封装
│   ├── ui/                  # PySide6 / QFluentWidgets 界面
│   └── update/              # 应用更新
├── tencent/                 # 腾讯问卷适配
├── wjx/                     # 问卷星适配
└── SurveyController.py      # 桌面应用入口
```

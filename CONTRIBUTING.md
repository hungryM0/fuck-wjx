# 贡献指南

感谢愿意改进本项目！在开始之前，请先阅读 [行为准则](https://github.com/hungryM0/SurveyController/blob/main/CODE_OF_CONDUCT.md)，确保所作的改进能够遵守行为准则。

## 交流渠道
- **Bug/功能建议**：首选 GitHub Issues。
- **快速反馈**：QQ群（见 README）。

## 开发环境与依赖
- 操作系统：仅考虑对 Windows 10/11 的支持
- Python：3.8+
- 安装依赖：`pip install -r requirements.txt`。
- 从源码运行：`python SurveyController.py`。
- 导入检测：`python test_imports.py`（扫描 `wjx/`、`software/`、`tencent/` 下所有 `.py` 文件的 `import` 是否报错）。
- 死代码检测：`python test_deadcode.py`（基于 vulture，扫描 `wjx/`、`software/`、`tencent/` 下未引用的死代码）。

## 仓库根目录

```markdown
仓库根目录
├── .github/
│   ├── workflows/
│   │   └── release-to-r2.yml  # CI/CD 自动发布到 R2
│   └── ISSUE_TEMPLATE/        # Issue 模板（报错反馈、新功能请求）
├── SurveyController.py
├── rthook_pyside6.py     # PySide6 打包钩子
├── test_imports.py       # 导入检测脚本
├── test_deadcode.py      # 死代码检测脚本
├── software/             # 软件主包（应用壳 + 共享核心 + 平台总调度）
├── tencent/              # 腾讯问卷主包
└── wjx/                  # 问卷星主包
```

## 目录结构（`wjx/`、`software/`、`tencent/`）

```markdown
software/
├── app/                   # 启动入口、版本、运行路径、QSettings 门面
├── assets/                # 程序内置资源（地区数据、协议文本等）
├── core/                  # 共享执行核心
│   ├── ai/                # AI 填空共享逻辑
│   ├── config/            # 配置结构与编解码
│   ├── engine/            # 共享执行流程（runner/cleanup/公共预处理）；平台专属导航/提交不再放这里
│   ├── modes/             # 作答模式与时长控制
│   ├── persona/           # 人设与上下文生成
│   ├── psychometrics/     # 心理测量题辅助逻辑
│   ├── questions/         # 题目配置、分布、共享判定与文本共享常量；平台 DOM 执行器不再放这里
│   └── task/              # TaskContext、事件总线、线程进度模型
├── integrations/
│   └── ai/                # AI API 适配器
├── io/
│   ├── config/            # 配置读写、导入导出
│   ├── qr/                # 二维码工具
│   ├── markdown/          # Markdown 工具
│   └── reports/           # 使用记录等输出
├── logging/               # 日志工具
├── network/
│   ├── http/              # httpx 客户端封装
│   ├── browser/           # 浏览器驱动
│   └── proxy/             # 代理 API / 会话 / 策略 / 地区 / 代理池
├── providers/             # 平台识别、注册、分发总入口
├── system/                # Windows/系统级能力（安全存储、注册表）
├── ui/
│   ├── shell/             # 主窗口、启动页、页面装配
│   ├── controller/        # Qt 协调器
│   ├── helpers/           # UI 侧辅助门面
│   │   ├── fluent_tooltip.py # Fluent tooltip 安装器
│   │   └── qfluent_compat.py # QFluentWidgets 动画 / InfoBar 稳定性补丁
│   ├── pages/
│   │   ├── workbench/     # dashboard（page.py 负责首页骨架，cards.py 放首页专用卡片，parts/ 放首页交互拆分）/question_editor（含单栏配置向导）/runtime_panel/strategy（题目策略：条件规则 + 维度分组；dimension_panel.py 负责面板装配，dimension_sections.py 负责分组区块与跨表拖拽）/log_panel
│   │   └── settings/      # 应用程序设置页；settings.py 负责页面骨架，group_widgets.py 放设置页专用右侧控件
│   └── widgets/           # 通用组件（contact_form 已拆成包；旧 time_range_slider 已移除）
└── update/                # 更新检查与升级

tencent/
├── __init__.py            # 包标记文件；真正平台实现请直接看 provider/
└── provider/              # 腾讯问卷专属实现（解析、运行时、导航、提交）

wjx/
├── __init__.py            # 包标记文件；仅保留版本信息，真实实现在 provider/ 子模块
└── provider/              # 问卷星专属实现（解析、检测、导航、运行时、提交、questions/ 题型执行器）
```

## PR 流程（推荐）
1. Fork 仓库本仓库
2. 开发遵守三主包边界原则：
   - **共享代码** → `software/`（GUI、配置、执行引擎等）
   - **问卷星专属** → `wjx/provider/`（平台特定的解析、导航、提交和题型执行）
   - **腾讯问卷专属** → `tencent/provider/`（平台特定的解析、导航、提交和运行逻辑）
   - **顶层包** → 仅保留包标记文件，不要把实现代码再塞回 `tencent/`、`wjx/` 目录
3. 自测：运行 `python test_imports.py` 和 `python test_deadcode.py` 检查 import、语法和死代码错误；至少手动跑一次核心流程（启动APP、加载问卷、配置参数、开始执行），确保无报错
4. 提交：保持清晰提交信息，必要时补充中文注释和变更说明
5. PR 描述：写明变更目的、主要改动点、测试方式与结果，关联相关 Issue（如有）

## 代码与文档风格
- **目录结构** - 维持现有模块划分，新功能按职责放到对应目录，不要把无关功能堆进一个文件
- **UI 组件** - 优先使用 `QfluentWidgets` 原生组件保持统一风格
- **文档/提示信息** - 使用简洁易懂的中文，避免专业术语堆砌，让小白用户也能理解

## 行为要求
- **明确用途** - 仅用于授权测试或学习。严禁伪造学术数据、非法刷问卷、污染他人数据
- **举报违规** - 发现不当使用请邮件 `mail@hungrym0.top` 举报

欢迎贡献 PR 改进以下方向：
- 增加新的问卷题型支持（选择、填空、矩阵等）
- 增加新的问卷平台支持
- 性能优化与用户体验改进
- 文档完善与示例补充

感谢你的贡献！

**结构说明补充**：`software/logging/action_logger.py` 统一了 UI、配置、导航、更新等关键操作的日志封装

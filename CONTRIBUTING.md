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
├── test_wjx_imports.py   # 导入检测脚本
├── test_wjx_deadcode.py  # 死代码检测脚本
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
│   ├── engine/            # 共享执行流程（runner/cleanup/submission 等）
│   ├── modes/             # 作答模式与时长控制
│   ├── persona/           # 人设与上下文生成
│   ├── psychometrics/     # 心理测量题辅助逻辑
│   ├── questions/         # 题目配置、分布、题型实现
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
├── system/                # Windows/系统级能力（安全存储、注册表、进程清理）
├── ui/
│   ├── shell/             # 主窗口、启动页、页面装配
│   ├── controller/        # Qt 协调器
│   ├── helpers/           # UI 侧辅助门面
│   │   ├── fluent_tooltip.py # Fluent tooltip 安装器
│   │   └── qfluent_compat.py # QFluentWidgets 动画 / InfoBar 稳定性补丁
│   ├── pages/
│   │   ├── workbench/     # dashboard/question_editor（含单栏配置向导）/runtime_panel/strategy（题目策略：条件规则+维度分组）/log_panel
│   │   └── settings/      # 应用程序设置页；settings.py 负责页面骨架，group_widgets.py 放设置页专用右侧控件
│   └── widgets/           # 通用组件（contact_form 已拆成包；旧 time_range_slider 已移除）
└── update/                # 更新检查与升级

tencent/
├── __init__.py            # 包标记文件；真正平台实现请直接看 provider/
└── provider/              # 腾讯问卷专属实现（解析/运行时）

wjx/
├── __init__.py            # 包标记文件；仅保留版本信息，真正平台实现请直接看 provider/
└── provider/              # 问卷星专属实现（解析、检测、运行时、提交；导航已归并到 software/core/engine/navigation.py）
```

## PR 流程（推荐）
1. Fork 仓库本仓库
2. 开发时遵守三主包边界：共享业务、GUI、平台总调度放 `software`；问卷星专属实现只放 `wjx/provider`；腾讯问卷专属实现放 `tencent/provider`；顶层包只保留包标记或必要元信息，不要再把实现代码塞回 `tencent/`、`wjx/` 根目录，也不要再堆包级兼容导出层
3. 自测：运行 `python test_imports.py` 检查 import 和语法错误；至少手动跑一次核心流程（启动、加载问卷、配置、开始运行），确保无报错
4. 提交：保持清晰提交信息，必要时补充中文注释和变更说明
5. PR 描述：写明变更目的、主要改动点、测试方式与结果，关联相关 Issue（如有）

## 代码与文档风格
- 维持现有命名与目录结构，不要把无关功能塞进同一文件
- GUI 优先使用 `QfluentWidgets` 原生组件
- 文档、提示信息优先使用小白也能看懂的中文

## 行为要求
- 严禁将本项目用于伪造学术数据、非法刷问卷或任何污染他人数据的行为。
- 如发现违规，请邮件 `mail@hungrym0.top` 举报。

欢迎提交 PR 改进问卷解析、题型支持、性能优化、界面体验等内容。谢谢！

- 仓库结构补充：software/logging/action_logger.py 统一 UI、配置、导航、更新等关键操作日志封装

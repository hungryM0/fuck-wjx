<div align="center">
  <img src="assets/icon.png" alt="SurveyController" width="120" height="120" />
  <h1>SurveyController</h1>
  
  [![Status](https://status.hungrym0.top/api/badge/12/status)](https://status.hungrym0.top/status/surveycontroller)
  [![GitHub Stars](https://img.shields.io/github/stars/hungryM0/SurveyController?style=flat&logo=github&color=yellow)](https://github.com/hungryM0/SurveyController/stargazers)
  [![Contributors](https://img.shields.io/github/contributors/hungryM0/SurveyController?style=flat&logo=github)](https://github.com/hungryM0/SurveyController/graphs/contributors)
  [![GitHub Release](https://img.shields.io/github/v/release/hungryM0/SurveyController?style=flat&logo=github&color=blue)](https://github.com/hungryM0/SurveyController/releases/latest)
  ![Downloads](https://img.shields.io/github/downloads/hungryM0/SurveyController/total?style=flat&logo=github&color=green)
  [![Issues](https://img.shields.io/github/issues/hungryM0/SurveyController?style=flat&logo=github)](https://github.com/hungryM0/SurveyController/issues)
  [![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
  [![License](https://img.shields.io/github/license/hungryM0/SurveyController?style=flat&color=orange)](./LICENSE)

  <p><strong>一站式问卷自动化处理程序，适配问卷星、腾讯问卷、Credamo见数平台</strong></p>
  <p><strong>支持指定ip填写地区、信度系数、作答时长与分布比例。</strong></p>
  
</div>

> [!WARNING]
> **该项目仅供 Playwright 的学习与测试使用。** 请确保拥有目标测试问卷的授权再使用，**严禁污染他人问卷数据！**

> [!NOTE]
> 我们正计划用 Go 重写该项目，以便部署在无图形化界面的服务器环境中。
> 感兴趣的开发者可以查看 [hungryM0/SurveyController-Go](https://github.com/hungryM0/SurveyController-go) 仓库，欢迎参与贡献！

<img width="689" height="626" alt="gui" src="/assets/gui.png" />

---

## 主要特性

1. **多平台支持** - 同时支持问卷星、腾讯问卷、Credamo见数平台，一套工具搞定三个平台
2. **Fluent 界面** - 无需编写代码，通过可视化UI完成所有操作
3. **支持二维码解析** - 上传问卷二维码图片自动转链接（支持问卷星、见数链接平台）
4. **定制答案配置** - 支持自定义各选项权重与多选题命中概率分布
5. **指定ip设置** - 支持随机IP或指定特定地区IP提交
6. **配置导入导出** - 保存配置文件便于后续复用，跨设备同步
7. **AI 主观题作答** - 填空题自动生成作答内容（限时免费），由 [@dAwn-Rebirth](https://github.com/dAwn-Rebirth) 贡献

---

## 开始使用

> [!TIP]
> **安装包：** 前往 [发行版](https://github.com/hungryM0/SurveyController/releases/latest) 中下载已打包好的安装包

### 从源码运行

克隆、安装依赖、运行源码：
```bash
git clone https://github.com/hungryM0/SurveyController.git
cd SurveyController
pip install -r requirements.txt
python SurveyController.py
```

**环境要求：** Windows 10/11，Python 3.11+，Git，Microsoft Edge

---

## 使用方法

1. **输入问卷** - 粘贴问卷链接或上传/拖入二维码图片（支持问卷星和腾讯问卷）
2. **自动解析** - 点击「自动配置问卷」，系统自动识别平台和题目结构
3. **调整配置** - 在配置向导中针对各题设置答案权重和概率分布
4. **设置运行参数** - 指定目标提交份数、并发浏览器数、随机IP等选项
5. **启动任务** - 点击「开始执行」并等待任务完成（可在日志中查看进度）

---

## 关键配置说明

| 配置项 | 说明 |
|--------|------|
| **目标份数** | 计划提交的问卷总数。建议先测试 3~5 份验证配置是否正确 |
| **并发浏览器数** | 同时运行的浏览器窗口数。过高可能导致电脑卡顿 |
| **随机IP** | 是否使用随机IP或指定地区IP。使用代理IP时可能产生额外费用，请确认配额 |
| **User-Agent** | 浏览器标识字符串，影响问卷后台显示的来源信息 |
| **答题时长** | 每份问卷的作答时间。如无特殊需求建议不做设置 |

---

## Mac 系统支持

如果你需要查看支持 macOS 系统的源码，请切换到 [mac 分支](https://github.com/hungryM0/SurveyController/tree/mac)。

**该分支由社区维护，不受长期支持。**

---

## 交流群

如有疑问或需要技术支持，可加入QQ群：

<img width="256" alt="qq" src="assets/community_qr.jpg" />

---

## 参与贡献

欢迎提交 Pull Request，改进方向包括但不限于：
- 增加对更多题型的支持
- 增加对更多问卷平台的支持
- 性能优化与代码重构

---

## 贡献者

感谢以下贡献者对本项目的支持：

<div style="display: flex; gap: 10px;">
  <a href="https://github.com/shiahonb777">
    <img src="https://github.com/shiahonb777.png" width="50" height="50" alt="shiahonb777" style="border-radius: 50%;" />
  </a>
  <a href="https://github.com/BingBuLiang">
    <img src="https://github.com/BingBuLiang.png" width="50" height="50" alt="BingBuLiang" style="border-radius: 50%;" />
  </a>
  <a href="https://github.com/dAwn-Rebirth">
    <img src="https://github.com/dAwn-Rebirth.png" width="50" height="50" alt="dAwn-Rebirth" style="border-radius: 50%;" />
  </a>
  <a href="https://github.com/Moyuin-aka">
    <img src="https://github.com/Moyuin-aka.png" width="50" height="50" alt="Moyuin-aka" style="border-radius: 50%;" />
  </a>
  <a href="https://github.com/zioug">
    <img src="https://github.com/zioug.png" width="50" height="50" alt="zioug" style="border-radius: 50%;" />
  </a>
</div>

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=hungryM0/SurveyController&type=date&legend=top-left)](https://www.star-history.com/#hungryM0/SurveyController&type=date&legend=top-left)

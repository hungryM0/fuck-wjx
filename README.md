<div align="center">
  <img src="assets/icon.png" alt="SurveyController" width="120" height="120" />
  <h1>SurveyController</h1>
  <p>一个支持问卷星、腾讯问卷自动填写的图形化工具，支持定制数据与指定ip。</p>

  [![GitHub Stars](https://img.shields.io/github/stars/hungryM0/SurveyController?style=flat&logo=github&color=yellow)](https://github.com/hungryM0/SurveyController/stargazers)
  [![GitHub Forks](https://img.shields.io/github/forks/hungryM0/SurveyController?style=flat&logo=github)](https://github.com/hungryM0/SurveyController/network/members)
  [![GitHub Release](https://img.shields.io/github/v/release/hungryM0/SurveyController?style=flat&logo=github&color=blue)](https://github.com/hungryM0/SurveyController/releases/latest)
  [![Downloads](https://img.shields.io/github/downloads/hungryM0/SurveyController/total?style=flat&logo=github&color=green)](https://github.com/hungryM0/SurveyController/releases)
  [![License](https://img.shields.io/github/license/hungryM0/SurveyController?style=flat&color=orange)](./LICENSE)
  [![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
  [![Issues](https://img.shields.io/github/issues/hungryM0/SurveyController?style=flat&logo=github)](https://github.com/hungryM0/SurveyController/issues)

</div>

> 参考了 [Zemelee/wjx](https://github.com/Zemelee/wjx)，别忘了给大佬点个star

> [!WARNING]
> **该项目仅供 Playwright 的学习与测试使用。** 请确保拥有目标测试问卷的授权再使用,**严禁污染他人问卷数据！**

<img width="689" height="626" alt="gui" src="/assets/gui.png" />

---

## 主要特性

1. **多平台支持** - 同时支持问卷星和腾讯问卷，一套工具搞定两个平台
2. **图形化界面** - 无需编写代码，通过可视化UI完成所有操作
3. **二维码快速解析** - 上传问卷二维码图片自动转链接（支持问卷星平台）
4. **智能答案配置** - 解析问卷题目结构，支持自定义答案权重与概率分布
5. **灵活代理设置** - 支持随机IP或指定特定地区IP提交
6. **配置导入导出** - 保存配置文件便于后续复用，跨设备同步
7. **AI 智能填空** - 主观题自动生成作答内容（免费），由 [@dAwn-Rebirth](https://github.com/dAwn-Rebirth) 贡献

---

## 开始使用

> [!TIP]
> **安装包：** 前往 [发行版](https://github.com/hungryM0/SurveyController/releases/latest) 中下载已打包好的安装包，无需额外配置环境。

### 从源码运行

克隆本仓库：
```bash
git clone https://github.com/hungryM0/SurveyController.git
```

安装依赖并运行：
```bash
pip install -r requirements.txt
python SurveyController.py
```

**环境要求：** Windows 10/11，Python 3.8+

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
| **并发浏览器数** | 同时运行的浏览器窗口数。普通电脑建议设置 2~5 个，过高可能导致无响应 |
| **随机IP模式** | 是否使用随机IP或指定地区IP。使用代理IP时可能产生额外费用，请确认配额 |
| **User-Agent** | 浏览器标识字符串，影响问卷后台显示的来源信息。建议保持随机以规避检测 |
| **答题时长** | 每份问卷的作答时间。过短可能被识别为机器行为，建议遵循正常作答节奏 |

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

<a href="https://github.com/shiahonb777">
  <img src="https://wsrv.nl/?url=https%3A%2F%2Fgithub.com%2Fshiahonb777.png&mask=circle&w=50&h=50&fit=cover" width="50" height="50" alt="shiahonb777" />
</a>
<a href="https://github.com/BingBuLiang">
  <img src="https://wsrv.nl/?url=https%3A%2F%2Fgithub.com%2FBingBuLiang.png&mask=circle&w=50&h=50&fit=cover" width="50" height="50" alt="BingBuLiang" />
</a>
<a href="https://github.com/dAwn-Rebirth">
  <img src="https://wsrv.nl/?url=https%3A%2F%2Fgithub.com%2FdAwn-Rebirth.png&mask=circle&w=50&h=50&fit=cover" width="50" height="50" alt="dAwn-Rebirth" />
</a>

---

## 捐助

<div align="center">
  <table>
    <tr>
      <td align="center">
        <img width="200" alt="wechat" src="assets/WeDonate.png" /><br/>
        <strong style="color: #07C160;">微信赞赏</strong>
      </td>
      <td align="center">
        <img width="200" alt="alipay" src="assets/AliDonate.jpg" /><br/>
        <strong style="color: #1677FF;">支付宝</strong>
      </td>
    </tr>
  </table>
</div>

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=hungryM0/SurveyController&type=date&legend=top-left)](https://www.star-history.com/#hungryM0/SurveyController&type=date&legend=top-left)

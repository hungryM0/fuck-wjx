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

1. **图形化界面** - 无需另外编写代码，通过可视化UI界面完成所有操作
2. **二维码识别** - 上传问卷二维码图片，自动解析为问卷链接（二维码仅支持问卷星平台）
3. **自定义答案比例** - 解析问卷题目结构，支持自定义答案权重与概率分布
4. **可指定地区IP** - 支持IP随机化或指定特定地区IP
5. **配置复用** - 支持导出与导入配置文件，便于重复使用
6. **AI 智能填空（免费）** - 支持主观题自动生成作答内容，由 [@dAwn-Rebirth](https://github.com/dAwn-Rebirth) 贡献

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

1. 输入问卷链接或上传/拖入二维码图片
2. 点击「自动配置问卷」以解析问卷结构
3. 根据配置向导调整各题答案的权重分布
4. 设置目标提交份数与并发浏览器实例数
5. 按需在「运行参数」中设置随机ip或作答时长设置项
6. 点击「开始执行」并等待任务完成

---

## 关键配置说明

| 配置项 | 作用 |
|--------|------|
| 目标份数 | 需要提交的问卷总数（建议先测试3-5份以验证配置） |
| 并发数 | 同时使用的多个浏览器实例数（普通配置建议2-5个） |
| 随机IP | 使用随机或指定的地区IP（注意：可能产生额外费用） |
| 随机UA | 后台显示的问卷来源 |

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

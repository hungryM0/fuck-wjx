# fuck-wjx (问卷星速填)

[English](./README.md) | 简体中文

> 参考了 [Zemelee/wjx](https://github.com/Zemelee/wjx)，别忘了给大佬点个star

一个支持图形化界面的问卷星自动填写工具，支持自定义答案分布与智能配置。

> [!WARNING]
> **仅供学习与测试使用。** 请确保有授权再使用。**严禁污染他人问卷数据！**

<img width="689" height="626" alt="gui" src="https://github.com/user-attachments/assets/dab85fed-1b28-4d45-8adf-37bb2770cf28" />

---

## 主要特性

1. **图形化界面** - 无需编写代码，通过可视化界面完成所有操作
2. **二维码识别** - 上传问卷二维码图片，自动解析并提取问卷链接
3. **智能配置** - 自动解析问卷题目结构，支持自定义答案权重与概率分布
4. **随机IP** - 支持IP随机化，有效规避IP限制与验证码检测
5. **优雅停止** - 运行过程中可随时中止，已完成的进度不会丢失
6. **配置复用** - 支持导出与导入配置文件，便于重复使用

---

## 快速开始

> [!TIP]
> **快速上手：** 可直接下载 [Release](https://github.com/hungryM0/fuck-wjx/releases/latest) 中的可执行文件，无需配置环境。

### 从源码运行

```bash
pip install -r requirements.txt
python fuck-wjx.py
```

**环境要求：** Windows 10/11 或 Linux，Python 3.8+

---

## 使用方法

1. 输入问卷链接或上传二维码图片
2. 点击「自动配置问卷」以解析问卷结构
3. 根据配置向导调整各题答案的权重分布
4. 设置目标提交份数与并发浏览器实例数
5. 点击「开始执行」并等待任务完成

---

## 关键配置

| 配置项 | 作用 |
|--------|------|
| 目标份数 | 需要提交的问卷总数（建议先测试3-5份以验证配置） |
| 浏览器数量 | 并发执行的浏览器实例数（普通配置建议2-5个） |
| 分布方式 | 答案选择策略：完全随机或按自定义权重分布 |
| 全真模拟 | 模拟真实用户行为（速度较慢但更安全） |
| 随机IP | 使用随机IP绕过限制（注意：可能产生额外费用） |

---

## 交流群

如有疑问或需要技术支持，可加入QQ群：

<img width="256" alt="qq" src="https://github.com/user-attachments/assets/7f25caaa-b157-4185-acae-78882f56871d" />

---

## 参与贡献

欢迎提交 Pull Request，改进方向包括但不限于：
- 提升问卷解析的稳定性与兼容性
- 增加对更多题型的支持
- 性能优化与代码重构

---

## 贡献者

感谢以下贡献者对本项目的支持：

<a href="https://github.com/shiahonb777">
  <img src="https://github.com/shiahonb777.png" width="50" height="50" alt="shiahonb777" style="border-radius: 50%;" />
</a>
<a href="https://github.com/BingBuLiang">
  <img src="https://github.com/BingBuLiang.png" width="50" height="50" alt="BingBuLiang" style="border-radius: 50%;" />
</a>

---

## 捐助

<img width="250" alt="payment" src="assets/payment.png" />

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=hungryM0/fuck-wjx&type=date&legend=top-left)](https://www.star-history.com/#hungryM0/fuck-wjx&type=date&legend=top-left)

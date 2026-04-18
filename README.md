<div align="center">
  <img src="assets/icon.png" alt="fuck-wjx" width="120" height="120" />
  <h1>问卷星速填 macOS</h1>
  <p>自动填写问卷星的 macOS 版本工具。</p>
</div>

> 参考了 [Zemelee/wjx](https://github.com/Zemelee/wjx)，别忘了给大佬点个star⭐

> [!WARNING]
> **仅供学习与测试使用。** 请确保有授权再使用。**严禁污染他人问卷数据！**

## 声明

**本项目 macOS 分支由社区驱动维护，原作者不提供针对 macOS 版本的长期支持或问题解答。**
欢迎提交 PR 修复 BUG 或提升兼容性。

## 运行与打包

环境要求：macOS 10.15+, Python 3.8+

```bash
# 安装依赖
pip install -r requirements.txt
pip install pyinstaller

# 运行
python fuck-wjx.py

# 打包为 .app
chmod +x build_macos.sh
./build_macos.sh
```

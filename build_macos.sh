#!/bin/bash
# macOS 打包脚本
# 使用方法: chmod +x build_macos.sh && ./build_macos.sh

set -e

echo "=========================================="
echo "  问卷星速填 - macOS 打包脚本"
echo "=========================================="

# 检查 Python 环境
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到 python3"
    exit 1
fi

# 检查 PyInstaller
if ! python3 -c "import PyInstaller" &> /dev/null; then
    echo "📦 安装 PyInstaller..."
    pip3 install pyinstaller
fi

# 安装 Playwright 浏览器
echo "🌐 检查 Playwright 浏览器..."
python3 -m playwright install chromium

# 清理旧的构建
echo "🧹 清理旧构建..."
rm -rf build dist

# 执行打包
echo "📦 开始打包..."
python3 -m PyInstaller fuck-wjx-macos.spec --clean

echo ""
echo "=========================================="
echo "✅ 打包完成!"
echo "📁 应用位置: dist/问卷星速填.app"
echo "=========================================="
echo ""
echo "提示: 首次运行可能需要在系统偏好设置中允许运行"
echo "      系统偏好设置 → 安全性与隐私 → 通用 → 仍要打开"

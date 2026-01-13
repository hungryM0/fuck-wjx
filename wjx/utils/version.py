# -*- coding: utf-8 -*-
"""
版本号及相关常量配置

修改版本号时只需修改此文件中的 __VERSION__ 变量即可
"""

# 版本号
__VERSION__ = "2.0.1"

# GitHub 仓库配置
GITHUB_OWNER = "hungryM0"
GITHUB_REPO = "fuck-wjx"

# 以下常量基于上述配置自动生成，一般无需修改
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
ISSUE_FEEDBACK_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/issues/new"

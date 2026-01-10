# -*- coding: utf-8 -*-
"""
GitHub Issue API 模块

提供创建 Issue 的功能
"""

from typing import Optional, Dict, Any, List

import requests

from wjx.utils.version import GITHUB_OWNER, GITHUB_REPO


# GitHub API 配置
GITHUB_ISSUES_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/issues"
GITHUB_LABELS_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/labels"


class GitHubIssueError(Exception):
    """GitHub Issue 操作错误"""
    pass


def create_issue(
    access_token: str,
    title: str,
    body: str,
    labels: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    创建 GitHub Issue
    
    Args:
        access_token: GitHub access token
        title: Issue 标题
        body: Issue 内容（支持 Markdown）
        labels: 标签列表
        
    Returns:
        创建的 Issue 信息
        
    Raises:
        GitHubIssueError: 创建失败时抛出
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    payload: Dict[str, Any] = {
        "title": title,
        "body": body
    }
    
    if labels:
        payload["labels"] = labels
    
    try:
        resp = requests.post(
            GITHUB_ISSUES_API_URL,
            json=payload,
            headers=headers,
            timeout=30
        )
        
        if resp.status_code == 201:
            return resp.json()
        elif resp.status_code == 401:
            raise GitHubIssueError("认证失败，请重新登录 GitHub")
        elif resp.status_code == 403:
            raise GitHubIssueError("没有权限创建 Issue")
        elif resp.status_code == 404:
            raise GitHubIssueError("仓库不存在")
        elif resp.status_code == 422:
            raise GitHubIssueError("请求参数无效")
        else:
            raise GitHubIssueError(f"创建 Issue 失败: {resp.status_code}")
    except requests.RequestException as e:
        raise GitHubIssueError(f"网络请求失败: {e}")


def get_repo_labels(access_token: str) -> List[Dict[str, Any]]:
    """
    获取仓库的标签列表
    
    Args:
        access_token: GitHub access token
        
    Returns:
        标签列表
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    try:
        resp = requests.get(
            GITHUB_LABELS_API_URL,
            headers=headers,
            timeout=30
        )
        
        if resp.status_code == 200:
            return resp.json()
        return []
    except Exception:
        return []


# 预定义的 Issue 类型
ISSUE_TYPES = {
    "bug": {
        "label": "Bug 报告",
        "labels": ["bug"],
        "template": """## Bug 描述
{description}

## 复现步骤
1. 
2. 
3. 

## 预期行为


## 实际行为


## 环境信息
- 操作系统: {os}
- 软件版本: {version}
"""
    },
    "feature": {
        "label": "功能建议",
        "labels": ["enhancement"],
        "template": """## 功能描述
{description}

## 使用场景


## 期望的解决方案

"""
    },
    "question": {
        "label": "问题咨询",
        "labels": ["question"],
        "template": """## 问题描述
{description}

## 相关信息

"""
    }
}

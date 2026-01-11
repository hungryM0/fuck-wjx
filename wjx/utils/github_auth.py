# -*- coding: utf-8 -*-
"""
GitHub Device Flow 认证模块

实现 GitHub OAuth Device Flow，用于桌面应用认证
"""

import json
import os
import time
from typing import Optional, Dict, Any, Callable

import requests

from wjx.utils.load_save import get_runtime_directory


# GitHub OAuth 配置
GITHUB_CLIENT_ID = "Ov23liYNvmNLdg0mBvIH"
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_API_URL = "https://api.github.com/user"
GITHUB_DEVICE_VERIFY_URL = "https://github.com/login/device"

# Token 存储文件名
TOKEN_FILE_NAME = ".github_token"


class GitHubAuthError(Exception):
    """GitHub 认证错误"""
    pass


class GitHubAuth:
    """GitHub Device Flow 认证管理器"""
    
    def __init__(self):
        self._access_token: Optional[str] = None
        self._user_info: Optional[Dict[str, Any]] = None
        self._load_token()
    
    def _get_token_path(self) -> str:
        """获取 Token 存储路径"""
        return os.path.join(get_runtime_directory(), TOKEN_FILE_NAME)
    
    def _load_token(self):
        """从文件加载 Token"""
        token_path = self._get_token_path()
        if os.path.exists(token_path):
            try:
                with open(token_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._access_token = data.get("access_token")
                    self._user_info = data.get("user_info")
            except Exception:
                pass
    
    def _save_token(self):
        """保存 Token 到文件"""
        token_path = self._get_token_path()
        try:
            with open(token_path, "w", encoding="utf-8") as f:
                json.dump({
                    "access_token": self._access_token,
                    "user_info": self._user_info
                }, f, ensure_ascii=False)
        except Exception:
            pass
    
    def _clear_token(self):
        """清除 Token"""
        self._access_token = None
        self._user_info = None
        token_path = self._get_token_path()
        if os.path.exists(token_path):
            try:
                os.remove(token_path)
            except Exception:
                pass
    
    @property
    def is_logged_in(self) -> bool:
        """是否已登录"""
        return self._access_token is not None
    
    @property
    def access_token(self) -> Optional[str]:
        """获取 access token"""
        return self._access_token
    
    @property
    def user_info(self) -> Optional[Dict[str, Any]]:
        """获取用户信息"""
        return self._user_info
    
    @property
    def username(self) -> Optional[str]:
        """获取用户名"""
        if self._user_info:
            return self._user_info.get("login")
        return None
    
    @property
    def avatar_url(self) -> Optional[str]:
        """获取头像URL"""
        if self._user_info:
            return self._user_info.get("avatar_url")
        return None
    
    def request_device_code(self) -> Dict[str, Any]:
        """
        请求设备码
        
        Returns:
            包含 device_code, user_code, verification_uri, expires_in, interval 的字典
        """
        resp = requests.post(
            GITHUB_DEVICE_CODE_URL,
            data={
                "client_id": GITHUB_CLIENT_ID,
                "scope": "public_repo"  # 只需要公开仓库的 issue 权限
            },
            headers={"Accept": "application/json"},
            timeout=30
        )
        
        if resp.status_code != 200:
            raise GitHubAuthError(f"请求设备码失败: {resp.status_code}")
        
        return resp.json()
    
    def poll_for_token(
        self,
        device_code: str,
        interval: int = 5,
        expires_in: int = 900,
        on_progress: Optional[Callable[[str], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None
    ) -> bool:
        """
        轮询获取 access token
        
        Args:
            device_code: 设备码
            interval: 轮询间隔（秒）
            expires_in: 过期时间（秒）
            on_progress: 进度回调
            should_stop: 停止检查回调
            
        Returns:
            是否成功获取 token
        """
        start_time = time.time()
        
        while time.time() - start_time < expires_in:
            if should_stop and should_stop():
                return False
            
            resp = requests.post(
                GITHUB_ACCESS_TOKEN_URL,
                data={
                    "client_id": GITHUB_CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
                },
                headers={"Accept": "application/json"},
                timeout=30
            )
            
            if resp.status_code != 200:
                if on_progress:
                    on_progress("请求失败，重试中...")
                time.sleep(interval)
                continue
            
            data = resp.json()
            
            if "access_token" in data:
                self._access_token = data["access_token"]
                # 获取用户信息
                if on_progress:
                    on_progress("正在获取用户信息...")
                self._fetch_user_info()
                self._save_token()
                return True
            
            error = data.get("error")
            if error == "authorization_pending":
                if on_progress:
                    remaining = int(expires_in - (time.time() - start_time))
                    on_progress(f"等待授权... ({remaining}秒)")
            elif error == "slow_down":
                interval = data.get("interval", interval + 5)
                if on_progress:
                    on_progress("请求过快，减慢轮询...")
            elif error == "expired_token":
                raise GitHubAuthError("设备码已过期，请重新开始")
            elif error == "access_denied":
                raise GitHubAuthError("用户拒绝授权")
            else:
                if on_progress:
                    on_progress(f"未知状态: {error}")
            
            time.sleep(interval)
        
        raise GitHubAuthError("授权超时")
    
    def _fetch_user_info(self):
        """获取用户信息"""
        if not self._access_token:
            return
        
        try:
            resp = requests.get(
                GITHUB_USER_API_URL,
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28"
                },
                timeout=30
            )
            if resp.status_code == 200:
                self._user_info = resp.json()
        except Exception:
            pass
    
    def verify_token(self) -> bool:
        """验证 token 是否有效"""
        if not self._access_token:
            return False
        
        try:
            resp = requests.get(
                GITHUB_USER_API_URL,
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28"
                },
                timeout=30
            )
            if resp.status_code == 200:
                self._user_info = resp.json()
                self._save_token()
                return True
            else:
                self._clear_token()
                return False
        except Exception:
            return False
    
    def logout(self):
        """登出"""
        self._clear_token()
    
    def check_starred(self, owner: str, repo: str) -> bool:
        """检查当前用户是否 star 了指定仓库"""
        if not self._access_token:
            return False
        
        try:
            resp = requests.get(
                f"https://api.github.com/user/starred/{owner}/{repo}",
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28"
                },
                timeout=30
            )
            return resp.status_code == 204
        except Exception:
            return False
    
    def check_starred_this_repo(self) -> bool:
        """检查当前用户是否 star 了本项目仓库"""
        return self.check_starred("hungryM0", "fuck-wjx")
    
    def star_repo(self, owner: str, repo: str) -> bool:
        """Star 指定仓库"""
        if not self._access_token:
            return False
        
        try:
            resp = requests.put(
                f"https://api.github.com/user/starred/{owner}/{repo}",
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28"
                },
                timeout=30
            )
            return resp.status_code == 204
        except Exception:
            return False
    
    def unstar_repo(self, owner: str, repo: str) -> bool:
        """Unstar 指定仓库"""
        if not self._access_token:
            return False
        
        try:
            resp = requests.delete(
                f"https://api.github.com/user/starred/{owner}/{repo}",
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28"
                },
                timeout=30
            )
            return resp.status_code == 204
        except Exception:
            return False
    
    def star_this_repo(self) -> bool:
        """Star 本项目仓库"""
        return self.star_repo("hungryM0", "fuck-wjx")
    
    def unstar_this_repo(self) -> bool:
        """Unstar 本项目仓库"""
        return self.unstar_repo("hungryM0", "fuck-wjx")


# 全局实例
_github_auth: Optional[GitHubAuth] = None


def get_github_auth() -> GitHubAuth:
    """获取全局 GitHubAuth 实例"""
    global _github_auth
    if _github_auth is None:
        _github_auth = GitHubAuth()
    return _github_auth

"""应用更新检测与执行 - 检查新版本、下载安装包"""
import os
import subprocess
import sys
import tempfile
import time
from threading import Thread
from typing import Optional, Dict, Any, Callable
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception


import wjx.network.http_client as http_client

try:
    from packaging import version
except ImportError:  # pragma: no cover
    version = None

try:
    from PySide6.QtCore import QSettings
except ImportError:
    QSettings = None

from wjx.utils.app.version import __VERSION__, GITHUB_API_URL, GITHUB_RELEASES_URL
from wjx.utils.app.config import GITHUB_MIRROR_SOURCES, DEFAULT_GITHUB_MIRROR


def _get_github_mirror() -> str:
    """获取当前选择的 GitHub 镜像源 key"""


    if QSettings is not None:
        try:
            settings = QSettings("FuckWjx", "Settings")
            value = str(settings.value("github_mirror", DEFAULT_GITHUB_MIRROR))
            return value if value else DEFAULT_GITHUB_MIRROR
        except Exception as exc:
            log_suppressed_exception("_get_github_mirror: settings = QSettings(\"FuckWjx\", \"Settings\")", exc, level=logging.WARNING)
    return DEFAULT_GITHUB_MIRROR


def _set_github_mirror(mirror_key: str) -> None:
    """保存当前选择的 GitHub 镜像源 key"""
    if QSettings is not None:
        try:
            settings = QSettings("FuckWjx", "Settings")
            settings.setValue("github_mirror", mirror_key)
            logging.debug(f"已切换镜像源为: {mirror_key}")
        except Exception as exc:
            log_suppressed_exception("_set_github_mirror: settings = QSettings(\"FuckWjx\", \"Settings\")", exc, level=logging.WARNING)


def _get_next_mirror(current_key: str) -> Optional[str]:
    """获取下一个可用的镜像源 key"""
    keys = list(GITHUB_MIRROR_SOURCES.keys())
    if current_key not in keys:
        return keys[0] if keys else None
    current_idx = keys.index(current_key)
    next_idx = (current_idx + 1) % len(keys)
    # 如果回到了起点，返回 None 表示已尝试所有源
    if next_idx == 0 and current_idx != 0:
        return None
    return keys[next_idx]


def _apply_mirror_to_url(url: str, mirror_key: Optional[str] = None) -> str:
    """将下载 URL 转换为镜像 URL"""
    if mirror_key is None:
        mirror_key = _get_github_mirror()
    mirror_config = GITHUB_MIRROR_SOURCES.get(mirror_key, {})
    prefix = mirror_config.get("download_prefix", "")
    if prefix and url.startswith("https://github.com/"):
        mirrored_url = prefix + url
        logging.debug(f"使用镜像源 [{mirror_key}]: {mirrored_url}")
        return mirrored_url
    return url


def _get_runtime_directory() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# 可选：设置 GitHub Token 以避免 API 速率限制
# 优先从环境变量读取，如果没有则尝试从配置文件读取
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
if not GITHUB_TOKEN:
    token_file = os.path.join(_get_runtime_directory(), ".github_token")
    if os.path.exists(token_file):
        try:
            with open(token_file, "r", encoding="utf-8") as f:
                GITHUB_TOKEN = f.read().strip()
        except Exception as exc:
            log_suppressed_exception("module: with open(token_file, \"r\", encoding=\"utf-8\") as f: GITHUB_TOKEN = f.read().st...", exc, level=logging.WARNING)


class UpdateManager:
    """GitHub 自动更新管理器"""

    @staticmethod
    def check_updates() -> Optional[Dict[str, Any]]:
        """检查 GitHub 上是否有新版本。"""
        if not version:
            logging.warning("更新功能依赖 packaging 模块")
            return None

        try:
            headers = {"Accept": "application/vnd.github.v3+json"}
            if GITHUB_TOKEN:
                headers["Authorization"] = f"token {GITHUB_TOKEN}"
            response = http_client.get(GITHUB_API_URL, headers=headers, timeout=(10, 30))
            response.raise_for_status()
            latest_release = response.json()

            latest_version = latest_release["tag_name"].lstrip("v")
            current_version = __VERSION__

            # 比较版本号
            try:
                if version.parse(latest_version) <= version.parse(current_version):
                    return None
            except Exception:
                logging.warning(f"版本比较失败: {latest_version} vs {current_version}")
                return None

            # 查找 .exe 文件资源（Release中的最新exe文件）
            download_url = None
            file_name = None
            for asset in latest_release.get("assets", []):
                if asset.get("name", "").endswith(".exe"):
                    download_url = asset.get("browser_download_url")
                    file_name = asset.get("name")
                    break

            if not download_url:
                logging.warning("Release 中没有找到 .exe 文件")
                return None

            return {
                "has_update": True,
                "version": latest_version,
                "download_url": download_url,
                "release_notes": latest_release.get("body", ""),
                "file_name": file_name,
                "current_version": current_version,
            }

        except http_client.exceptions.Timeout:
            logging.warning("检查更新超时")
            return None
        except http_client.exceptions.RequestException as exc:
            logging.warning(f"检查更新失败: {exc}")
            return None
        except Exception as exc:
            logging.error(f"检查更新时发生错误: {exc}")
            return None

    @staticmethod
    def get_all_releases() -> list:
        """获取所有发行版信息。"""
        try:
            headers = {"Accept": "application/vnd.github.v3+json"}
            if GITHUB_TOKEN:
                headers["Authorization"] = f"token {GITHUB_TOKEN}"
            response = http_client.get(GITHUB_RELEASES_URL, headers=headers, timeout=(10, 30))
            response.raise_for_status()
            releases = response.json()
            
            result = []
            for release in releases:
                result.append({
                    "version": release.get("tag_name", "").lstrip("v"),
                    "name": release.get("name", ""),
                    "body": release.get("body", ""),
                    "published_at": release.get("published_at", ""),
                    "prerelease": release.get("prerelease", False),
                })
            return result
        except Exception as exc:
            logging.warning(f"获取发行版列表失败: {exc}")
            return []

    @staticmethod
    def download_update(
        download_url: str, file_name: str, progress_callback=None, cancel_check=None,
        on_mirror_switch=None
    ) -> Optional[str]:
        """下载更新文件，成功返回文件路径。
        
        Args:
            cancel_check: 可调用对象，返回True表示取消下载
            on_mirror_switch: 镜像源切换时的回调，参数为新的镜像源 key
        """
        # 连接超时时间（秒）
        CONNECT_TIMEOUT = 2
        # 已尝试的镜像源
        tried_mirrors = set()
        current_mirror = _get_github_mirror()
        
        while True:
            tried_mirrors.add(current_mirror)
            actual_url = _apply_mirror_to_url(download_url, current_mirror)
            
            try:
                logging.debug(f"正在连接下载服务器: {actual_url}")
                # 使用较短的连接超时，较长的读取超时
                response = http_client.get(actual_url, timeout=(CONNECT_TIMEOUT, 60), stream=True)
                response.raise_for_status()

                total_size = int(response.headers.get("content-length", 0))

                current_dir = _get_runtime_directory()
                target_file = os.path.join(current_dir, file_name)
                temp_file = target_file + ".tmp"
                downloaded_size = 0
                start_time = time.time()
                last_time = start_time
                last_downloaded = 0

                logging.debug(f"下载目标目录: {current_dir}")

                last_speed = 0
                with open(temp_file, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        # 检查是否取消
                        if cancel_check and cancel_check():
                            logging.info("下载已取消")
                            raise Exception("下载已取消")
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            # 计算下载速度
                            now = time.time()
                            elapsed = now - last_time
                            if elapsed >= 0.3:  # 每0.3秒更新一次速度
                                last_speed = (downloaded_size - last_downloaded) / elapsed
                                last_time = now
                                last_downloaded = downloaded_size
                            if progress_callback:
                                progress_callback(downloaded_size, total_size, last_speed)
                            if total_size > 0:
                                progress = (downloaded_size / total_size) * 100
                                logging.debug(f"下载进度: {progress:.1f}%")

                if os.path.exists(target_file):
                    os.remove(target_file)
                os.rename(temp_file, target_file)

                logging.debug(f"文件已成功下载到: {target_file}")
                
                # 下载成功，保存当前使用的镜像源
                _set_github_mirror(current_mirror)
                if on_mirror_switch:
                    on_mirror_switch(current_mirror)

                UpdateManager.cleanup_old_executables(target_file)

                return target_file

            except (http_client.exceptions.ConnectTimeout, http_client.exceptions.ConnectionError) as exc:
                logging.warning(f"镜像源 [{current_mirror}] 连接失败: {exc}")
                
                # 清理临时文件
                try:
                    current_dir = _get_runtime_directory()
                    target_file = os.path.join(current_dir, file_name)
                    temp_file = target_file + ".tmp"
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                except Exception as exc:
                    log_suppressed_exception("download_update: current_dir = _get_runtime_directory()", exc, level=logging.WARNING)
                
                # 尝试切换到下一个镜像源
                next_mirror = _get_next_mirror(current_mirror)
                if next_mirror and next_mirror not in tried_mirrors:
                    mirror_label = GITHUB_MIRROR_SOURCES.get(next_mirror, {}).get("label", next_mirror)
                    logging.debug(f"自动切换到镜像源: {mirror_label}")
                    current_mirror = next_mirror
                    # 通知 GUI 镜像源已切换
                    if on_mirror_switch:
                        on_mirror_switch(current_mirror)
                    continue
                else:
                    # 所有镜像源都已尝试
                    logging.error("所有镜像源均连接失败")
                    return None
                    
            except Exception as exc:
                logging.error(f"下载文件失败: {exc}")
                try:
                    current_dir = _get_runtime_directory()
                    target_file = os.path.join(current_dir, file_name)
                    temp_file = target_file + ".tmp"
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                except Exception as exc:
                    log_suppressed_exception("download_update: current_dir = _get_runtime_directory()", exc, level=logging.WARNING)
                return None

    @staticmethod
    def cleanup_old_executables(exclude_path: str):
        """删除目录下旧版本的 exe 文件（保留 exclude_path 本体）。"""
        if not exclude_path:
            return
        directory = os.path.dirname(os.path.abspath(exclude_path))
        if not os.path.isdir(directory):
            return

        try:
            exclude_norm = os.path.normcase(os.path.abspath(exclude_path))
            for file in os.listdir(directory):
                if not file.lower().endswith(".exe"):
                    continue
                file_path = os.path.join(directory, file)
                if os.path.normcase(os.path.abspath(file_path)) == exclude_norm:
                    continue
                lower_name = file.lower()
                if "fuck-wjx" not in lower_name and "wjx" not in lower_name:
                    continue
                try:
                    os.remove(file_path)
                    logging.debug(f"已删除旧版本: {file_path}")
                except Exception as exc:
                    logging.warning(f"无法删除旧版本 {file_path}: {exc}")
        except Exception as exc:
            logging.warning(f"清理旧版本时出错: {exc}")

    @staticmethod
    def schedule_running_executable_deletion(exclude_path: str):
        """调度在当前进程退出后删除正在运行的 exe 文件"""
        if not getattr(sys, "frozen", False):
            return
        current_executable = os.path.abspath(sys.executable)
        if not current_executable.lower().endswith(".exe"):
            return
        exclude_norm = os.path.normcase(os.path.abspath(exclude_path)) if exclude_path else ""
        if exclude_norm and os.path.normcase(current_executable) == exclude_norm:
            return

        safe_executable = current_executable.replace("%", "%%")
        script_content = (
            "@echo off\r\n"
            f"set \"target={safe_executable}\"\r\n"
            ":wait_loop\r\n"
            "if exist \"%target%\" (\r\n"
            "    del /f /q \"%target%\" >nul 2>&1\r\n"
            "    if exist \"%target%\" (\r\n"
            "        ping 127.0.0.1 -n 3 >nul\r\n"
            "        goto wait_loop\r\n"
            "    )\r\n"
            ")\r\n"
            "del /f /q \"%~f0\" >nul 2>&1\r\n"
        )

        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", delete=False, suffix=".bat"
            ) as script_file:
                script_file.write(script_content)
                script_path = script_file.name
            subprocess.Popen(
                ["cmd.exe", "/c", script_path],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            logging.debug(f"已调度删除旧版本执行文件: {current_executable}")
        except Exception as exc:
            logging.warning(f"调度删除旧版本失败: {exc}")


def _preview_release_notes(text: str, limit: int) -> str:
    if not text:
        return "暂无更新说明"
    import re
    # 移除 Markdown 标题标记
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    # 移除分隔线
    text = re.sub(r'^---+\s*$', '', text, flags=re.MULTILINE)
    # 移除删除线标记 ~~text~~ -> text
    text = re.sub(r'~~(.+?)~~', r'\1', text)
    # 移除粗体标记 **text** -> text
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    # 移除斜体标记 *text* -> text（但保留列表项的 * ）
    text = re.sub(r'(?<!\n)\*(.+?)\*', r'\1', text)
    # 将列表项 * 或 - 统一为 -
    text = re.sub(r'^\s*[\*\-]\s+', '- ', text, flags=re.MULTILINE)
    # 移除多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()
    preview = text[:limit]
    if len(text) > limit:
        preview += "\n..."
    return preview


def check_updates_on_startup(gui=None, *, on_result=None) -> None:
    """后台检查更新。可传入 gui 或 on_result 回调以接收结果。"""

    def _runner():
        try:
            logging.debug("开始检查更新...")
            update_info = UpdateManager.check_updates()
            logging.debug(f"检查更新结果: {update_info}")
            if update_info:
                if gui is not None:
                    setattr(gui, "update_info", update_info)
                    callback = getattr(gui, "show_update_notification", None) or getattr(
                        gui, "_show_update_notification", None
                    )
                    logging.debug(f"找到回调函数: {callback}")
                    if callable(callback):
                        callback()
                if callable(on_result):
                    on_result(update_info)
            else:
                logging.debug("当前已是最新版本")
                # 通知 GUI 显示最新版本徽章
                if gui is not None:
                    notify_latest = getattr(gui, "_notify_latest_version", None)
                    if callable(notify_latest):
                        notify_latest()
        except Exception as exc:
            logging.warning(f"启动时检查更新失败: {exc}")

    Thread(target=_runner, daemon=True).start()


def show_update_notification(gui) -> None:
    """显示更新通知（如果 gui.update_info 存在）。"""
    if not getattr(gui, "update_info", None):
        return

    info = gui.update_info
    release_notes_preview = _preview_release_notes(info.get("release_notes", ""), 300)

    msg = (
        f"检测到新版本 v{info['version']}\n"
        f"当前版本 v{info['current_version']}\n\n"
        f"发布说明:\n{release_notes_preview}\n\n"
        f"是否要立即下载更新？"
    )

    if gui._log_popup_confirm("检查到更新", msg):
        logging.debug("[Action Log] User accepted update notification")
        perform_update(gui)
    else:
        logging.debug("[Action Log] User declined update notification")


def check_for_updates(gui=None) -> Optional[Dict[str, Any]]:
    """手动检查更新，返回更新信息。若提供 gui，会弹窗提示。"""
    try:
        update_info = UpdateManager.check_updates()
        if not gui:
            return update_info
        if update_info:
            gui.update_info = update_info
            # 使用与启动时检查更新相同的弹窗样式
            show_update_notification(gui)
        else:
            gui._log_popup_info("检查更新", f"当前已是最新版本 v{__VERSION__}")
        return update_info
    except Exception as exc:
        if gui:
            gui._log_popup_error("检查更新失败", f"错误: {str(exc)}")
        else:
            logging.error(f"检查更新失败: {exc}")
        return None


def perform_update(gui, *, on_progress: Optional[Callable[[int, int, float], None]] = None) -> None:
    """执行更新：下载并在完成后询问是否启动新版本。"""
    if not getattr(gui, "update_info", None):
        return

    update_info = gui.update_info
    # 取消标志
    gui._download_cancelled = False

    def cancel_check():
        return getattr(gui, "_download_cancelled", False)

    def update_progress(downloaded, total, speed=0):
        # 优先使用GUI的进度信号
        if hasattr(gui, "_emit_download_progress"):
            try:
                gui._emit_download_progress(downloaded, total, speed)
            except Exception:
                logging.debug("GUI进度回调失败", exc_info=True)
        if on_progress:
            try:
                on_progress(downloaded, total, speed)
            except Exception:
                logging.debug("更新进度回调失败", exc_info=True)

    # 立即显示转圈动画（在开始下载前）
    if hasattr(gui, "downloadStarted"):
        gui.downloadStarted.emit()

    def on_mirror_switch(new_mirror_key):
        """镜像源切换时的回调"""
        if hasattr(gui, "mirrorSwitched"):
            gui.mirrorSwitched.emit(new_mirror_key)

    def do_update():
        try:
            downloaded_file = UpdateManager.download_update(
                update_info["download_url"],
                update_info["file_name"],
                progress_callback=update_progress,
                cancel_check=cancel_check,
                on_mirror_switch=on_mirror_switch,
            )

            if gui._download_cancelled:
                return

            if downloaded_file:
                if on_progress:
                    on_progress(1, 1, 0)
                # 使用信号通知主线程显示弹窗
                if hasattr(gui, "downloadFinished"):
                    gui.downloadFinished.emit(downloaded_file)
                else:
                    # 兼容旧版本
                    logging.debug(f"下载完成: {downloaded_file}")
            else:
                if not gui._download_cancelled:
                    if hasattr(gui, "downloadFailed"):
                        gui.downloadFailed.emit("下载文件失败，请稍后重试")
                    else:
                        logging.error("下载文件失败")
        except Exception as exc:
            if not gui._download_cancelled:
                logging.error(f"更新过程中出错: {exc}")
                if hasattr(gui, "downloadFailed"):
                    gui.downloadFailed.emit(f"更新过程出错: {str(exc)}")

    Thread(target=do_update, daemon=True).start()


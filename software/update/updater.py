"""应用更新检测与执行 - 检查新版本、下载安装包"""
import os
import subprocess
import sys
import tempfile
import time
from threading import Thread
from typing import Optional, Dict, Any, Callable
import logging
from software.logging.action_logger import log_action
from software.logging.log_utils import log_suppressed_exception
import software.network.http as http_client

try:
    from packaging import version
except ImportError:  # pragma: no cover
    version = None

from software.app.version import __VERSION__, GITHUB_API_URL, GITHUB_RELEASES_URL
from software.app.config import DEFAULT_DOWNLOAD_SOURCE, DOWNLOAD_SOURCES
from software.app.settings_store import app_settings
from software.app.runtime_paths import get_runtime_directory


def _get_download_source() -> str:
    """获取当前选择的下载源 key。"""
    try:
        settings = app_settings()
        value = str(settings.value("download_source", DEFAULT_DOWNLOAD_SOURCE)).strip()
        if value:
            return value
    except Exception as exc:
        log_suppressed_exception("_get_download_source", exc, level=logging.WARNING)
    return DEFAULT_DOWNLOAD_SOURCE


def _set_download_source(source_key: str) -> None:
    """保存当前选择的下载源 key"""
    try:
        settings = app_settings()
        settings.setValue("download_source", source_key)
        logging.info(f"已切换下载源为: {source_key}")
    except Exception as exc:
        log_suppressed_exception("_set_download_source", exc, level=logging.WARNING)


def _get_next_download_source(current_key: str) -> Optional[str]:
    """获取下一个可用的下载源 key"""
    keys = list(DOWNLOAD_SOURCES.keys())
    if current_key not in keys:
        return keys[0] if keys else None
    current_idx = keys.index(current_key)
    next_idx = (current_idx + 1) % len(keys)
    # 如果回到了起点，返回 None 表示已尝试所有源
    if next_idx == 0 and current_idx != 0:
        return None
    return keys[next_idx]


def _apply_download_source_to_url(url: str, source_key: Optional[str] = None) -> str:
    """将下载 URL 转换为对应下载源 URL"""
    if source_key is None:
        source_key = _get_download_source()
    source_config = DOWNLOAD_SOURCES.get(source_key, {})
    direct_download_url = str(source_config.get("direct_download_url", "")).strip()
    if direct_download_url:
        logging.info(f"使用下载源 [{source_key}] 直连地址: {direct_download_url}")
        return direct_download_url
    prefix = source_config.get("download_prefix", "")
    if prefix and url.startswith("https://github.com/"):
        mirrored_url = prefix + url
        logging.info(f"使用下载源 [{source_key}]: {mirrored_url}")
        return mirrored_url
    return url
# 可选：设置 GitHub Token 以避免 API 速率限制
# 优先从环境变量读取，如果没有则尝试从配置文件读取
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
if not GITHUB_TOKEN:
    token_file = os.path.join(get_runtime_directory(), ".github_token")
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
        """检查 GitHub 上是否有新版本。

        返回值说明：
        - 有新版本：返回包含 has_update=True 的 dict
        - 当前已是最新：返回 {"has_update": False, "status": "latest", ...}
        - 当前版本高于远程（预览版）：返回 {"has_update": False, "status": "preview", ...}
        - 网络/解析失败：返回 {"has_update": False, "status": "unknown"}
        """
        if not version:
            logging.warning("更新功能依赖 packaging 模块")
            return {"has_update": False, "status": "unknown"}

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
                parsed_latest = version.parse(latest_version)
                parsed_current = version.parse(current_version)
                if parsed_current > parsed_latest:
                    # 本地版本高于远程，属于预览/开发版
                    logging.info(f"当前版本 {current_version} 高于远程最新版 {latest_version}，视为预览版")
                    return {"has_update": False, "status": "preview", "current_version": current_version, "latest_version": latest_version}
                if parsed_current == parsed_latest:
                    return {"has_update": False, "status": "latest", "current_version": current_version}
            except Exception:
                logging.warning(f"版本比较失败: {latest_version} vs {current_version}")
                return {"has_update": False, "status": "unknown"}

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
                return {"has_update": False, "status": "unknown"}

            return {
                "has_update": True,
                "status": "outdated",
                "version": latest_version,
                "download_url": download_url,
                "release_notes": latest_release.get("body", ""),
                "file_name": file_name,
                "current_version": current_version,
            }

        except http_client.Timeout:
            logging.warning("检查更新超时")
            return {"has_update": False, "status": "unknown"}
        except http_client.RequestException as exc:
            logging.warning(f"检查更新失败: {exc}")
            return {"has_update": False, "status": "unknown"}
        except Exception as exc:
            logging.error(f"检查更新时发生错误: {exc}")
            return {"has_update": False, "status": "unknown"}

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
        on_download_source_switch=None
    ) -> Optional[str]:
        """下载更新文件，成功返回文件路径。"""
        # 连接超时时间（秒）
        CONNECT_TIMEOUT = 2
        # 已尝试的下载源
        tried_sources = set()
        current_source = _get_download_source()
        
        while True:
            tried_sources.add(current_source)
            actual_url = _apply_download_source_to_url(download_url, current_source)
            
            try:
                logging.info(f"正在连接下载服务器: {actual_url}")
                # 使用较短的连接超时，较长的读取超时
                response = http_client.get(actual_url, timeout=(CONNECT_TIMEOUT, 60), stream=True)
                response.raise_for_status()

                total_size = int(response.headers.get("content-length", 0))

                current_dir = get_runtime_directory()
                target_file = os.path.join(current_dir, file_name)
                temp_file = target_file + ".tmp"
                downloaded_size = 0
                start_time = time.time()
                last_time = start_time
                last_downloaded = 0

                logging.info(f"下载目标目录: {current_dir}")

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
                                logging.info(f"下载进度: {progress:.1f}%")

                if os.path.exists(target_file):
                    os.remove(target_file)
                os.rename(temp_file, target_file)

                logging.info(f"文件已成功下载到: {target_file}")
                
                # 下载成功，保存当前使用的下载源
                _set_download_source(current_source)
                if on_download_source_switch:
                    on_download_source_switch(current_source)

                UpdateManager.cleanup_old_executables(target_file)

                return target_file

            except (http_client.ConnectTimeout, http_client.ConnectionError) as exc:
                logging.warning(f"下载源 [{current_source}] 连接失败: {exc}")
                
                # 清理临时文件
                try:
                    current_dir = get_runtime_directory()
                    target_file = os.path.join(current_dir, file_name)
                    temp_file = target_file + ".tmp"
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                except Exception as exc:
                    log_suppressed_exception("download_update: current_dir = get_runtime_directory()", exc, level=logging.WARNING)
                
                # 尝试切换到下一个下载源
                next_source = _get_next_download_source(current_source)
                if next_source and next_source not in tried_sources:
                    source_label = DOWNLOAD_SOURCES.get(next_source, {}).get("label", next_source)
                    logging.info(f"已自动切换到下载源: {source_label}")
                    current_source = next_source
                    # 通知 GUI 下载源已切换
                    if on_download_source_switch:
                        on_download_source_switch(current_source)
                    continue
                else:
                    # 所有下载源都已尝试
                    logging.error("所有下载源均连接失败")
                    return None
                    
            except Exception as exc:
                logging.error(f"下载文件失败: {exc}")
                try:
                    current_dir = get_runtime_directory()
                    target_file = os.path.join(current_dir, file_name)
                    temp_file = target_file + ".tmp"
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                except Exception as exc:
                    log_suppressed_exception("download_update: current_dir = get_runtime_directory()", exc, level=logging.WARNING)
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
                if "surveycontroller" not in lower_name:
                    continue
                try:
                    os.remove(file_path)
                    logging.info(f"已删除旧版本: {file_path}")
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
            logging.info(f"已调度删除旧版本执行文件: {current_executable}")
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


def show_update_notification(gui) -> None:
    """显示更新通知（如果 gui.update_info 存在）。"""
    if not getattr(gui, "update_info", None):
        return

    info = gui.update_info
    log_action(
        "UPDATE",
        "show_update_notification",
        "update_dialog",
        "update",
        result="shown",
        payload={"version": info.get("version", "unknown")},
    )
    release_notes_preview = _preview_release_notes(info.get("release_notes", ""), 300)

    msg = (
        f"检测到新版本 v{info['version']}\n"
        f"当前版本 v{info['current_version']}\n\n"
        f"发布说明:\n{release_notes_preview}\n\n"
        f"是否要立即下载更新？"
    )

    if gui.show_confirm_dialog("检查到更新", msg):
        log_action(
            "UPDATE",
            "show_update_notification",
            "update_dialog",
            "update",
            result="accepted",
            payload={"version": info.get("version", "unknown")},
        )
        perform_update(gui)
    else:
        log_action(
            "UPDATE",
            "show_update_notification",
            "update_dialog",
            "update",
            result="declined",
            payload={"version": info.get("version", "unknown")},
        )


def check_for_updates(gui=None) -> Optional[Dict[str, Any]]:
    """手动检查更新，返回更新信息。若提供 gui，会弹窗提示。"""
    try:
        update_info = UpdateManager.check_updates()
        update_info_dict = update_info if isinstance(update_info, dict) else None
        if not gui:
            return update_info
        status = update_info_dict.get("status", "unknown") if update_info_dict else "unknown"
        if status == "outdated":
            gui.update_info = update_info_dict
            # 使用与启动时检查更新相同的弹窗样式
            show_update_notification(gui)
        elif status == "latest":
            gui.show_message_dialog("检查更新", f"当前已是最新版本 v{__VERSION__}")
        elif status == "preview":
            latest = update_info_dict.get("latest_version", "?") if update_info_dict else "?"
            gui.show_message_dialog("检查更新", f"当前版本 v{__VERSION__} 高于远程最新版 v{latest}，属于预览/开发版本")
        else:
            gui.show_message_dialog("检查更新失败", "无法连接到更新服务器，请检查网络连接后重试", level="error")
        return update_info
    except Exception as exc:
        if gui:
            gui.show_message_dialog("检查更新失败", f"错误: {str(exc)}", level="error")
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
        try:
            gui._emit_download_progress(downloaded, total, speed)
        except Exception:
            logging.info("GUI进度回调失败", exc_info=True)
        if on_progress:
            try:
                on_progress(downloaded, total, speed)
            except Exception:
                logging.info("更新进度回调失败", exc_info=True)

    gui.downloadStarted.emit()

    def on_download_source_switch(new_source_key):
        """下载源切换时的回调"""
        gui.downloadSourceSwitched.emit(new_source_key)

    def do_update():
        try:
            downloaded_file = UpdateManager.download_update(
                update_info["download_url"],
                update_info["file_name"],
                progress_callback=update_progress,
                cancel_check=cancel_check,
                on_download_source_switch=on_download_source_switch,
            )

            if gui._download_cancelled:
                return

            if downloaded_file:
                if on_progress:
                    on_progress(1, 1, 0)
                gui.downloadFinished.emit(downloaded_file)
            else:
                if not gui._download_cancelled:
                    gui.downloadFailed.emit("下载文件失败，请稍后重试")
        except Exception as exc:
            if not gui._download_cancelled:
                logging.error(f"更新过程中出错: {exc}")
                gui.downloadFailed.emit(f"更新过程出错: {str(exc)}")

    Thread(target=do_update, daemon=True).start()




import logging
import os
import subprocess
import sys
import tempfile
import time
from threading import Thread
from typing import Optional, Dict, Any

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

try:
    from packaging import version
except ImportError:  # pragma: no cover
    version = None

from .version import __VERSION__, GITHUB_API_URL


def _get_runtime_directory() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# 可选：设置 GitHub Token 以避免 API 速率限制
# 优先从环境变量读取，如果没有则尝试从配置文件读取
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
if not GITHUB_TOKEN:
    token_file = os.path.join(_get_runtime_directory(), ".github_token")
    if os.path.exists(token_file):
        try:
            with open(token_file, "r", encoding="utf-8") as f:
                GITHUB_TOKEN = f.read().strip()
        except Exception:
            pass


class UpdateManager:
    """GitHub 自动更新管理器"""

    @staticmethod
    def check_updates() -> Optional[Dict[str, Any]]:
        """检查 GitHub 上是否有新版本。"""
        if not requests or not version:
            logging.warning("更新功能依赖 requests 和 packaging 模块")
            return None

        try:
            response = requests.get(GITHUB_API_URL, timeout=5)
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

        except requests.exceptions.Timeout:
            logging.warning("检查更新超时")
            return None
        except requests.exceptions.RequestException as exc:
            logging.warning(f"检查更新失败: {exc}")
            return None
        except Exception as exc:
            logging.error(f"检查更新时发生错误: {exc}")
            return None

    @staticmethod
    def download_update(
        download_url: str, file_name: str, progress_callback=None
    ) -> Optional[str]:
        """下载更新文件，成功返回文件路径。"""
        if not requests:
            logging.error("下载更新需要 requests 模块")
            return None

        try:
            logging.info(f"正在下载更新文件: {download_url}")
            response = requests.get(download_url, timeout=30, stream=True)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))

            current_dir = _get_runtime_directory()
            target_file = os.path.join(current_dir, file_name)
            temp_file = target_file + ".tmp"
            downloaded_size = 0

            logging.info(f"下载目标目录: {current_dir}")

            with open(temp_file, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded_size, total_size)
                        if total_size > 0:
                            progress = (downloaded_size / total_size) * 100
                            logging.debug(f"下载进度: {progress:.1f}%")

            if os.path.exists(target_file):
                os.remove(target_file)
            os.rename(temp_file, target_file)

            logging.info(f"文件已成功下载到: {target_file}")

            UpdateManager.cleanup_old_executables(target_file)

            return target_file

        except Exception as exc:
            logging.error(f"下载文件失败: {exc}")
            try:
                current_dir = _get_runtime_directory()
                target_file = os.path.join(current_dir, file_name)
                temp_file = target_file + ".tmp"
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass
            return None

    @staticmethod
    def restart_application():
        """重启应用程序（开发模式下脚本重启）"""
        try:
            python_exe = sys.executable
            script_path = os.path.abspath(__file__)
            subprocess.Popen([python_exe, script_path])
            sys.exit(0)
        except Exception as exc:
            logging.error(f"重启应用失败: {exc}")

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
    preview = text[:limit]
    if len(text) > limit:
        preview += "\n..."
    return preview


def check_updates_on_startup(gui) -> None:
    """启动后后台检查更新，发现新版本则触发通知。"""

    def _runner():
        try:
            update_info = UpdateManager.check_updates()
            if update_info:
                gui.update_info = update_info
                gui.root.after(0, gui._show_update_notification)
        except Exception as exc:
            logging.debug(f"启动时检查更新失败: {exc}")

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
        logging.info("[Action Log] User accepted update notification")
        perform_update(gui)
    else:
        logging.info("[Action Log] User declined update notification")


def check_for_updates(gui) -> None:
    """手动检查更新。"""
    gui.root.config(cursor="wait")
    gui.root.update()

    try:
        update_info = UpdateManager.check_updates()
        if update_info:
            gui.update_info = update_info
            msg = (
                f"检测到新版本！\n\n"
                f"当前版本: v{update_info['current_version']}\n"
                f"新版本: v{update_info['version']}\n\n"
                f"发布说明:\n{(update_info.get('release_notes') or '')[:200]}\n\n"
                f"立即更新？"
            )
            if gui._log_popup_confirm("检查到更新", msg):
                logging.info("[Action Log] User triggered manual update")
                perform_update(gui)
            else:
                logging.info("[Action Log] User postponed manual update")
        else:
            gui._log_popup_info("检查更新", f"当前已是最新版本 v{__VERSION__}")
    except Exception as exc:
        gui._log_popup_error("检查更新失败", f"错误: {str(exc)}")
    finally:
        gui.root.config(cursor="")


def perform_update(gui) -> None:
    """执行更新：弹出进度窗口、下载、询问是否启动新版本。"""
    if not getattr(gui, "update_info", None):
        return

    update_info = gui.update_info

    import tkinter as tk
    from tkinter import ttk

    progress_win = tk.Toplevel(gui.root)
    progress_win.title("正在更新")
    progress_win.geometry("500x200")
    progress_win.resizable(False, False)
    progress_win.transient(gui.root)
    progress_win.grab_set()

    progress_win.update_idletasks()
    win_width = progress_win.winfo_width()
    win_height = progress_win.winfo_height()
    screen_width = progress_win.winfo_screenwidth()
    screen_height = progress_win.winfo_screenheight()

    try:
        import ctypes
        from ctypes.wintypes import RECT

        work_area = RECT()
        ctypes.windll.user32.SystemParametersInfoA(48, 0, ctypes.byref(work_area), 0)
        work_width = work_area.right - work_area.left
        work_height = work_area.bottom - work_area.top
        work_x = work_area.left
        work_y = work_area.top
        x = work_x + (work_width - win_width) // 2
        y = work_y + (work_height - win_height) // 2
    except Exception:
        x = (screen_width - win_width) // 2
        y = (screen_height - win_height) // 2

    x = max(0, x)
    y = max(0, y)
    progress_win.geometry(f"+{x}+{y}")

    frame = ttk.Frame(progress_win, padding=20)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text="正在下载新版本...", font=("", 10, "bold")).pack(
        pady=(0, 10)
    )

    ttk.Label(frame, text=f"文件: {update_info['file_name']}", foreground="gray").pack(
        pady=(0, 5)
    )

    progress = ttk.Progressbar(frame, mode="determinate", maximum=100)
    progress.pack(fill=tk.X, pady=10)

    progress_label = ttk.Label(frame, text="0%", foreground="gray")
    progress_label.pack(pady=(0, 5))

    status_label = ttk.Label(frame, text="准备下载...", foreground="gray", wraplength=450)
    status_label.pack(pady=10)

    progress_win.update()

    def update_progress(downloaded, total):
        if total > 0:
            percent = (downloaded / total) * 100
            progress["value"] = percent
            downloaded_mb = downloaded / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            progress_label.config(
                text=f"{percent:.1f}% ({downloaded_mb:.1f}MB / {total_mb:.1f}MB)"
            )
            progress_win.update()

    def do_update():
        try:
            status_label.config(text="正在更新...")
            progress_win.update()

            downloaded_file = UpdateManager.download_update(
                update_info["download_url"],
                update_info["file_name"],
                progress_callback=update_progress,
            )

            if downloaded_file:
                status_label.config(text="新版本下载成功！合并文件中...")
                progress_label.config(text="100%")
                progress["value"] = 100
                progress_win.update()
                time.sleep(2)
                progress_win.destroy()

                should_launch = gui._log_popup_confirm(
                    "更新完成",
                    f"新版本已下载到:\n{downloaded_file}\n\n是否立即运行新版本？",
                )
                UpdateManager.schedule_running_executable_deletion(downloaded_file)
                if should_launch:
                    try:
                        subprocess.Popen([downloaded_file])
                        gui.on_close()
                    except Exception as exc:
                        logging.error("[Action Log] Failed to launch downloaded update")
                        gui._log_popup_error("启动失败", f"无法启动新版本: {exc}")
                else:
                    logging.info("[Action Log] Deferred launching downloaded update")
            else:
                status_label.config(text="下载失败", foreground="red")
                progress_win.update()
                time.sleep(2)
                progress_win.destroy()
                gui._log_popup_error("更新失败", "下载文件失败，请稍后重试")
        except Exception as exc:
            logging.error(f"更新过程中出错: {exc}")
            status_label.config(text=f"错误: {str(exc)}", foreground="red")
            progress_win.update()
            time.sleep(2)
            progress_win.destroy()
            gui._log_popup_error("更新失败", f"更新过程出错: {str(exc)}")

    Thread(target=do_update, daemon=True).start()

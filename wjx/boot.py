from __future__ import annotations

from typing import Optional

import os
import tkinter as tk
from tkinter import ttk

from wjx.config import APP_ICON_RELATIVE_PATH
from wjx.runtime import get_resource_path as _get_resource_path


class LoadingSplash:
    def __init__(
        self,
        master: Optional[tk.Tk],
        title: str = "正在加载",
        message: str = "程序正在启动，请稍候...",
        width: int = 360,
        height: int = 140,
    ):
        self.master = master or tk.Tk()
        self.width = width
        self.height = height

        self._icon_path = None
        try:
            icon_path = _get_resource_path(APP_ICON_RELATIVE_PATH)
        except Exception:
            icon_path = None
        if icon_path and os.path.exists(icon_path):
            try:
                self.master.iconbitmap(default=icon_path)
            except Exception:
                pass
            self._icon_path = icon_path

        self.window = tk.Toplevel(self.master)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg="#f8fafb")
        self.window.minsize(width, height)
        self.message_var = tk.StringVar(value=message)
        self.progress_value = 0

        if self._icon_path:
            try:
                self.window.iconbitmap(self._icon_path)
            except Exception:
                pass

        frame_bg = "#ffffff"
        self.window.title(title)
        frame = tk.Frame(
            self.window,
            bg=frame_bg,
            padx=15,
            pady=15,
            bd=0,
            relief="flat",
        )
        frame.pack(expand=True, fill=tk.BOTH, padx=15, pady=15)

        tk.Label(frame, text=title, font=("Segoe UI", 11, "bold"), bg=frame_bg).pack(anchor="center")

        message_wrap = width - 40
        message_area = tk.Frame(frame, bg=frame_bg, height=36)
        message_area.pack(fill=tk.X, pady=(8, 12))
        message_area.pack_propagate(False)
        self.message_label = tk.Label(
            message_area,
            textvariable=self.message_var,
            wraplength=message_wrap,
            justify="center",
            bg=frame_bg,
            font=("Microsoft YaHei", 10),
        )
        self.message_label.pack(expand=True, fill=tk.BOTH)

        progress_frame = tk.Frame(frame, bg=frame_bg)
        progress_frame.pack(fill=tk.X)

        self.progress = ttk.Progressbar(progress_frame, mode="determinate", length=width - 60, maximum=100)
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.progress_label = tk.Label(progress_frame, text="0%", width=4, anchor="center", bg=frame_bg)
        self.progress_label.pack(side=tk.LEFT, padx=(5, 0))

    def show(self) -> None:
        self._center(recenter=True)
        self.window.deiconify()
        self.window.update()

    def update_progress(self, percent: int, message: Optional[str] = None) -> None:
        self.progress_value = min(100, max(0, percent))
        self.progress["value"] = self.progress_value
        self.progress_label.config(text=f"{self.progress_value}%")
        if message is not None:
            self._set_message_text(message)
            self._center(recenter=False)
        self.window.update_idletasks()

    def update_message(self, message: str) -> None:
        self._set_message_text(message)
        self._center(recenter=False)
        self.window.update_idletasks()

    def close(self) -> None:
        if self.window.winfo_exists():
            self.window.destroy()

    def _center(self, recenter: bool = False) -> None:
        self.window.update_idletasks()
        desired_width = max(self.width, self.window.winfo_reqwidth())

        wrap_target = max(180, desired_width - 60)
        self.message_label.configure(wraplength=wrap_target)
        self.window.update_idletasks()
        desired_width = max(self.width, self.window.winfo_reqwidth())

        desired_height = max(self.height, self.window.winfo_reqheight())

        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()

        if recenter or not self.window.winfo_viewable():
            x = (screen_width - desired_width) // 2
            y = (screen_height - desired_height) // 2
        else:
            current_x = self.window.winfo_x()
            current_y = self.window.winfo_y()
            max_x = max(0, screen_width - desired_width)
            max_y = max(0, screen_height - desired_height)
            x = min(max(current_x, 0), max_x)
            y = min(max(current_y, 0), max_y)

        self.window.geometry(f"{desired_width}x{desired_height}+{x}+{y}")

    def _set_message_text(self, message: str) -> None:
        if self.message_var.get() == message:
            return
        self.message_var.set("")
        self.window.update_idletasks()
        self.message_var.set(message)
        self.message_label.update_idletasks()


_boot_root: Optional[tk.Tk] = None
_boot_splash: Optional[LoadingSplash] = None


def preload_boot_splash(
    *,
    title: str = "加载中",
    message: str = "正在准备问卷星速填...",
) -> None:
    """Show splash early, before importing heavy modules."""
    global _boot_root, _boot_splash
    if _boot_splash is not None:
        return
    try:
        root = tk.Tk()
        root.withdraw()
        splash = LoadingSplash(root, title=title, message=message)
        splash.show()
        splash.update_progress(5, "正在加载核心模块...")
        _boot_root = root
        _boot_splash = splash
    except Exception:
        _boot_root = None
        _boot_splash = None


def update_boot_splash(percent: int, message: Optional[str] = None) -> None:
    if _boot_splash:
        try:
            _boot_splash.update_progress(percent, message)
        except Exception:
            pass


def get_boot_root() -> Optional[tk.Tk]:
    return _boot_root


def get_boot_splash() -> Optional[LoadingSplash]:
    return _boot_splash


def close_boot_splash() -> None:
    global _boot_root, _boot_splash
    if _boot_splash:
        try:
            _boot_splash.close()
        except Exception:
            pass
    _boot_splash = None

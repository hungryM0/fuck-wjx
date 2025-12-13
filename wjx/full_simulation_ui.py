from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import tkinter as tk
from tkinter import ttk


def refresh_full_simulation_status_label(gui: Any) -> None:
    label = getattr(gui, "_full_sim_status_label", None)
    if not label or not label.winfo_exists():
        return
    enabled = bool(gui.full_simulation_enabled_var.get())
    status_text = "已开启" if enabled else "未开启"
    color = "#2e7d32" if enabled else "#E4A207"
    label.config(text=f"当前状态：{status_text}", foreground=color)


def update_full_simulation_controls_state(gui: Any) -> None:
    state = tk.NORMAL if gui.full_simulation_enabled_var.get() else tk.DISABLED
    cleaned: List[tk.Widget] = []
    for widget in getattr(gui, "_full_simulation_control_widgets", []):
        if widget is None:
            continue
        try:
            if widget.winfo_exists():
                widget.configure(state=state)
                cleaned.append(widget)
        except Exception:
            try:
                if widget.winfo_exists():
                    widget["state"] = state
                    cleaned.append(widget)
            except Exception:
                continue
    gui._full_simulation_control_widgets = cleaned


def update_full_sim_completion_time(gui: Any) -> None:
    label = getattr(gui, "_full_sim_completion_label", None)
    if not label or not label.winfo_exists():
        return
    try:
        minutes = int(str(gui.full_sim_total_minutes_var.get()).strip() or "0")
    except Exception:
        minutes = 0
    try:
        seconds = int(str(gui.full_sim_total_seconds_var.get()).strip() or "0")
    except Exception:
        seconds = 0
    total_seconds = max(0, minutes) * 60 + max(0, seconds)
    if total_seconds <= 0:
        label.config(text="预计完成时间：--")
        return
    finish_time = datetime.now() + timedelta(seconds=total_seconds)
    label.config(text=f"预计完成时间：{finish_time:%Y-%m-%d %H:%M}")


def update_full_sim_time_section_visibility(gui: Any) -> None:
    frame = getattr(gui, "_full_sim_timing_frame", None)
    if not frame or not frame.winfo_exists():
        return
    has_target = bool(str(gui.full_sim_target_var.get()).strip())
    try:
        managed = frame.winfo_manager()
    except Exception:
        managed = ""
    if has_target:
        if not managed:
            frame.pack(fill=tk.X, pady=(4, 0))
    else:
        if managed:
            frame.pack_forget()


def sync_full_sim_target_to_main(gui: Any) -> None:
    if not gui.full_simulation_enabled_var.get():
        return
    target_value = gui.full_sim_target_var.get().strip()
    if target_value:
        gui.target_var.set(target_value)


def get_full_simulation_question_count(gui: Any) -> int:
    count = len(getattr(gui, "question_entries", []) or [])
    if count <= 0 and getattr(gui, "_last_questions_info", None):
        try:
            count = len(gui._last_questions_info)
        except Exception:
            count = 0
    return max(0, count)


def parse_positive_int(value: Any) -> int:
    try:
        parsed = int(str(value).strip())
    except Exception:
        return 0
    return parsed if parsed > 0 else 0


def set_full_sim_duration(minutes_var: tk.StringVar, seconds_var: tk.StringVar, total_seconds: int) -> bool:
    try:
        total = max(0, int(total_seconds))
    except Exception:
        total = 0
    minutes = total // 60
    seconds = total % 60
    try:
        current_minutes = int(str(minutes_var.get()).strip() or "0")
    except Exception:
        current_minutes = 0
    try:
        current_seconds = int(str(seconds_var.get()).strip() or "0")
    except Exception:
        current_seconds = 0
    if current_minutes * 60 + current_seconds == total:
        return False
    minutes_var.set(str(minutes))
    seconds_var.set(str(seconds))
    return True


def auto_update_full_simulation_times(gui: Any) -> None:
    update_full_sim_time_section_visibility(gui)
    if getattr(gui, "_suspend_full_sim_autofill", False):
        return
    question_count = get_full_simulation_question_count(gui)
    if question_count <= 0:
        return
    per_question_seconds = 3
    estimated_seconds = question_count * per_question_seconds
    set_full_sim_duration(gui.full_sim_estimated_minutes_var, gui.full_sim_estimated_seconds_var, estimated_seconds)
    target_value = parse_positive_int(gui.full_sim_target_var.get()) or parse_positive_int(gui.target_var.get())
    if target_value > 0:
        total_seconds = estimated_seconds * target_value
        set_full_sim_duration(gui.full_sim_total_minutes_var, gui.full_sim_total_seconds_var, total_seconds)
    update_full_sim_time_section_visibility(gui)
    update_full_sim_completion_time(gui)


def on_full_sim_target_changed(gui: Any, *_: Any) -> None:
    gui._mark_config_changed()
    sync_full_sim_target_to_main(gui)
    auto_update_full_simulation_times(gui)


def on_main_target_changed(gui: Any, *_: Any) -> None:
    gui._mark_config_changed()
    auto_update_full_simulation_times(gui)


def on_full_simulation_toggle(gui: Any, *_: Any) -> None:
    if gui.full_simulation_enabled_var.get() and not gui.full_sim_target_var.get().strip():
        current_target = gui.target_var.get().strip()
        if current_target:
            gui.full_sim_target_var.set(current_target)

    if gui.full_simulation_enabled_var.get():
        if getattr(gui, "_threads_value_before_full_sim", None) is None:
            gui._threads_value_before_full_sim = gui.thread_var.get().strip() or "1"
        if gui.thread_var.get().strip() != "1":
            gui.thread_var.set("1")
    else:
        if getattr(gui, "_threads_value_before_full_sim", None) is not None:
            gui.thread_var.set(gui._threads_value_before_full_sim or "1")
        gui._threads_value_before_full_sim = None

    sync_full_sim_target_to_main(gui)
    update_full_simulation_controls_state(gui)
    gui._update_parameter_widgets_state()
    refresh_full_simulation_status_label(gui)
    gui._mark_config_changed()


def open_full_simulation_window(gui: Any) -> None:
    existing = getattr(gui, "_full_simulation_window", None)
    if existing:
        try:
            if existing.winfo_exists():
                existing.lift()
                existing.focus_force()
                gui._center_child_window(existing)
                return
            gui._full_simulation_window = None
        except tk.TclError:
            gui._full_simulation_window = None

    window = tk.Toplevel(gui.root)
    window.title("全真模拟设置")
    window.resizable(False, False)
    window.transient(gui.root)
    gui._full_simulation_window = window

    def _on_close() -> None:
        if gui._full_simulation_window is window:
            gui._full_simulation_window = None
            gui._full_simulation_control_widgets = []
            gui._full_sim_completion_label = None
        try:
            window.destroy()
        except Exception:
            pass

    window.protocol("WM_DELETE_WINDOW", _on_close)

    container = ttk.Frame(window, padding=20)
    container.pack(fill=tk.BOTH, expand=True)

    ttk.Label(
        container,
        text="在特定时段内按照真实考试节奏自动填答与提交。",
        wraplength=360,
        justify="left",
    ).pack(anchor="w")

    ttk.Checkbutton(
        container,
        text="启用全真模拟（任务会被节奏管控，仅允许单线程执行）",
        variable=gui.full_simulation_enabled_var,
    ).pack(anchor="w", pady=(8, 6))

    if not gui.full_sim_target_var.get().strip():
        current_target = gui.target_var.get().strip()
        if current_target:
            gui.full_sim_target_var.set(current_target)

    target_frame = ttk.Frame(container)
    target_frame.pack(fill=tk.X, pady=(4, 6))
    ttk.Label(target_frame, text="目标份数：").grid(row=0, column=0, sticky="w")
    target_entry = ttk.Entry(target_frame, textvariable=gui.full_sim_target_var, width=10)
    target_entry.grid(row=0, column=1, padx=(6, 0))
    ttk.Label(target_frame, text="（覆盖主面板的目标设置）", foreground="#616161").grid(
        row=0, column=2, padx=(8, 0), sticky="w"
    )

    timing_frame = ttk.LabelFrame(container, text="时间参数", padding=12)
    timing_frame.pack(fill=tk.X, pady=(4, 0))
    gui._full_sim_timing_frame = timing_frame

    ttk.Label(timing_frame, text="预计单次作答").grid(row=0, column=0, sticky="w")
    est_min_entry = ttk.Entry(timing_frame, textvariable=gui.full_sim_estimated_minutes_var, width=6)
    est_min_entry.grid(row=0, column=1, padx=(8, 4))
    ttk.Label(timing_frame, text="分").grid(row=0, column=2, padx=(0, 8))
    est_sec_entry = ttk.Entry(timing_frame, textvariable=gui.full_sim_estimated_seconds_var, width=6)
    est_sec_entry.grid(row=0, column=3, padx=(0, 4))
    ttk.Label(timing_frame, text="秒").grid(row=0, column=4, padx=(0, 12))

    ttk.Label(timing_frame, text="模拟总时长").grid(row=1, column=0, sticky="w", pady=(10, 0))
    total_min_entry = ttk.Entry(timing_frame, textvariable=gui.full_sim_total_minutes_var, width=6)
    total_min_entry.grid(row=1, column=1, padx=(8, 4), pady=(10, 0))
    ttk.Label(timing_frame, text="分").grid(row=1, column=2, padx=(0, 8), pady=(10, 0))
    total_sec_entry = ttk.Entry(timing_frame, textvariable=gui.full_sim_total_seconds_var, width=6)
    total_sec_entry.grid(row=1, column=3, padx=(0, 4), pady=(10, 0))
    ttk.Label(timing_frame, text="秒").grid(row=1, column=4, padx=(0, 12), pady=(10, 0))
    completion_label = ttk.Label(timing_frame, text="预计完成时间：--", foreground="#424242")
    completion_label.grid(row=2, column=0, columnspan=5, sticky="w", pady=(8, 0))
    gui._full_sim_completion_label = completion_label

    ttk.Label(
        container,
        text="启动后所有执行参数全部锁定，仅使用本窗口中的设置。",
        foreground="#d84315",
        wraplength=360,
        justify="left",
    ).pack(anchor="w", pady=(10, 0))

    action_frame = ttk.Frame(container)
    action_frame.pack(fill=tk.X, pady=(12, 0))
    ttk.Button(action_frame, text="完成", command=_on_close, width=10).pack(side=tk.RIGHT)

    gui._full_simulation_control_widgets = [
        target_entry,
        est_min_entry,
        est_sec_entry,
        total_min_entry,
        total_sec_entry,
    ]
    update_full_simulation_controls_state(gui)
    refresh_full_simulation_status_label(gui)
    update_full_sim_time_section_visibility(gui)
    update_full_sim_completion_time(gui)
    gui._update_parameter_widgets_state()

    window.update_idletasks()
    gui._center_child_window(window)
    window.lift()
    window.focus_force()

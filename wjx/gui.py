import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import queue

from wjx import boot
from wjx.boot import LoadingSplash
from wjx.config import APP_ICON_RELATIVE_PATH
from wjx.runtime import get_runtime_directory as _get_runtime_directory, get_resource_path as _get_resource_path
import wjx.engine as engine
from wjx.engine import *  # noqa: F401,F403
import wjx.timed_mode as timed_mode
from wjx.updater import check_for_updates as _check_for_updates_impl, perform_update as _perform_update_impl
from wjx.version import __VERSION__, GITHUB_OWNER, GITHUB_REPO, ISSUE_FEEDBACK_URL

# 显式引入 engine 中的下划线符号（import * 不会带下划线）
_FULL_SIM_STATE = engine._FULL_SIM_STATE
_click_next_page_button = engine._click_next_page_button
_count_visible_text_inputs_driver = engine._count_visible_text_inputs_driver
_driver_element_contains_text_input = engine._driver_element_contains_text_input
_driver_question_has_shared_text_input = engine._driver_question_has_shared_text_input
_driver_question_is_location = engine._driver_question_is_location
_extract_survey_title_from_html = engine._extract_survey_title_from_html
_fetch_new_proxy_batch = engine._fetch_new_proxy_batch
_generate_random_chinese_name_value = engine._generate_random_chinese_name_value
_generate_random_generic_text_value = engine._generate_random_generic_text_value
_generate_random_mobile_value = engine._generate_random_mobile_value
_get_entry_type_label = engine._get_entry_type_label
_is_fast_mode = engine._is_fast_mode
_kill_playwright_browser_processes = engine._kill_playwright_browser_processes
_kill_processes_by_pid = engine._kill_processes_by_pid
_normalize_html_text = engine._normalize_html_text
_normalize_question_type_code = engine._normalize_question_type_code
_prepare_full_simulation_schedule = engine._prepare_full_simulation_schedule
_reset_full_simulation_runtime_state = engine._reset_full_simulation_runtime_state
_resolve_dynamic_text_token_value = engine._resolve_dynamic_text_token_value
_resume_after_aliyun_captcha_stop = engine._resume_after_aliyun_captcha_stop
_resume_snapshot = engine._resume_snapshot
_safe_positive_int = engine._safe_positive_int
_should_mark_as_multi_text = engine._should_mark_as_multi_text
_should_treat_question_as_text_like = engine._should_treat_question_as_text_like
# 下划线全局默认值（import * 不会带过来）
_aliyun_captcha_stop_triggered = getattr(engine, "_aliyun_captcha_stop_triggered", False)
_target_reached_stop_triggered = getattr(engine, "_target_reached_stop_triggered", False)
_resume_after_aliyun_captcha_stop = getattr(engine, "_resume_after_aliyun_captcha_stop", False)
_resume_snapshot = getattr(engine, "_resume_snapshot", {})


class SurveyNotOpenError(Exception):
    """问卷未开放或已关闭导致无法解析时抛出。"""


class SurveyGUI(ConfigPersistenceMixin):

    def _save_logs_to_file(self):
        records = LOG_BUFFER_HANDLER.get_records()
        parent_window: tk.Misc = self.root
        log_window = getattr(self, "_log_window", None)
        if log_window and getattr(log_window, "winfo_exists", lambda: False)():
            parent_window = log_window
        if not records:
            self._log_popup_info("保存日志文件", "当前尚无日志可保存。", parent=parent_window)
            return

        try:
            file_path = save_log_records_to_file(records, _get_runtime_directory())
            logging.info(f"已保存日志文件: {file_path}")
            self._log_popup_info("保存日志文件", f"日志已保存到:\n{file_path}", parent=parent_window)
        except Exception as exc:
            logging.error(f"保存日志文件失败: {exc}")
            self._log_popup_error("保存日志文件失败", f"无法保存日志: {exc}", parent=parent_window)

    def _refresh_log_viewer(self):
        text_widget = getattr(self, "_log_text_widget", None)
        if not text_widget:
            return
        text_widget.config(state=tk.NORMAL)
        records = LOG_BUFFER_HANDLER.get_records()
        total_records = len(records)
        prev_count = getattr(self, "_log_rendered_count", 0)
        prev_first = getattr(self, "_log_first_rendered_record", None)
        current_first = records[0].text if records else None

        def _append_entries(entries, has_existing_content):
            needs_newline = has_existing_content
            for entry in entries:
                if needs_newline:
                    text_widget.insert(tk.END, "\n")
                text_widget.insert(tk.END, entry.text, entry.category)
                needs_newline = True

        try:
            _, view_bottom = text_widget.yview()
        except tk.TclError:
            view_bottom = 1.0
        auto_follow = view_bottom >= 0.999

        need_full_reload = False
        if prev_count > total_records:
            need_full_reload = True
        elif prev_count and total_records and prev_count == total_records and prev_first != current_first:
            need_full_reload = True

        if need_full_reload:
            text_widget.delete("1.0", tk.END)
            prev_count = 0

        if total_records == 0:
            if prev_count:
                text_widget.delete("1.0", tk.END)
            self._log_rendered_count = 0
            self._log_first_rendered_record = None
            return

        if prev_count == total_records:
            return

        if prev_count == 0:
            text_widget.delete("1.0", tk.END)
            _append_entries(records, False)
        else:
            new_records = records[prev_count:]
            if not new_records:
                return
            _append_entries(new_records, prev_count > 0)

        if auto_follow:
            text_widget.yview_moveto(1.0)
            text_widget.xview_moveto(0.0)

        self._log_rendered_count = total_records
        self._log_first_rendered_record = current_first

    def _on_log_text_keypress(self, event):
        """阻止日志窗口被键盘输入修改"""
        control_pressed = bool(event.state & 0x4)
        navigation_keys = {
            "Left", "Right", "Up", "Down", "Home", "End", "Next", "Prior", "Insert"
        }
        if control_pressed:
            key = event.keysym.lower()
            if key in ("c", "a"):
                return None
            if event.keysym in navigation_keys:
                return None
            return "break"
        if event.keysym in navigation_keys:
            return None
        if event.keysym in ("BackSpace", "Delete"):
            return "break"
        if event.char:
            return "break"
        return None

    def _log_popup_info(self, title: str, message: str, **kwargs):
        return log_popup_info(title, message, **kwargs)

    def _log_popup_error(self, title: str, message: str, **kwargs):
        return log_popup_error(title, message, **kwargs)

    def _log_popup_confirm(self, title: str, message: str, **kwargs) -> bool:
        return log_popup_confirm(title, message, **kwargs)

    def _dump_threads_to_file(self, tag: str = "stop") -> Optional[str]:
        """
        导出当前所有线程的堆栈，便于排查停止后卡顿。
        返回写入的文件路径。
        """
        return dump_threads_to_file(tag, _get_runtime_directory())

    def _post_to_ui_thread(self, callback: Callable[[], None]) -> None:
        """将需要操作 UI 的回调安全地派发到主线程执行。"""
        if callback is None:
            return
        try:
            self._ui_task_queue.put(callback)
        except Exception:
            logging.debug("无法加入 UI 回调队列", exc_info=True)

    def _drain_ui_task_queue(self):
        """周期性拉取队列中的 UI 任务并在主线程执行。"""
        delay_ms = 60
        try:
            while True:
                try:
                    callback = self._ui_task_queue.get_nowait()
                except queue.Empty:
                    break
                delay_ms = 15
                try:
                    callback()
                except Exception:
                    logging.debug("UI 回调执行失败", exc_info=True)
        finally:
            try:
                self._ui_task_job = self.root.after(delay_ms, self._drain_ui_task_queue)
            except Exception:
                self._ui_task_job = None

    def _start_ui_task_loop(self):
        """启动 UI 任务队列的轮询，确保在关闭前始终运行。"""
        if getattr(self, "_ui_task_job", None):
            try:
                if self._ui_task_job is not None:
                    self.root.after_cancel(self._ui_task_job)
            except Exception:
                pass
        try:
            self._ui_task_job = self.root.after(0, self._drain_ui_task_queue)
        except Exception:
            self._ui_task_job = None

    def _exit_app(self):
        """结束应用，优先销毁 Tk，再强制退出以避免残留卡顿。"""
        try:
            self._closing = True
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        try:
            os._exit(0)
        except Exception:
            pass

    def _is_supported_wjx_url(self, url: str) -> bool:
        if not url:
            return False
        candidate = url.strip()
        parsed = None
        try:
            parsed = urlparse(candidate)
            if not parsed.scheme or not parsed.netloc:
                parsed = urlparse(f"https://{candidate}")
        except Exception:
            return False
        host = (parsed.netloc or "").lower()
        supported_domains = ("wjx.cn", "wjx.top", "wjx.com")
        return bool(host) and any(
            host == domain or host.endswith(f".{domain}") for domain in supported_domains
        )

    def _validate_wjx_url(self, url: str) -> bool:
        if not self._is_supported_wjx_url(url):
            self._log_popup_error("链接错误", "当前仅支持 wjx.cn / wjx.top / wjx.com 的问卷链接，请检查后重试。")
            return False
        return True

    def _open_issue_feedback(self):
        message = (
            "将打开浏览器访问 GitHub Issue 页面以反馈问题：\n"
            f"{ISSUE_FEEDBACK_URL}\n\n"
            "提醒：该网站可能在国内访问较慢或需要额外网络配置。\n"
            "是否继续？"
        )
        if not self._log_popup_confirm("问题反馈", message):
            return
        try:
            opened = webbrowser.open(ISSUE_FEEDBACK_URL, new=2, autoraise=True)
            if not opened:
                raise RuntimeError("浏览器未响应")
        except Exception as exc:
            logging.error(f"打开问题反馈链接失败: {exc}")
            self._log_popup_error("打开失败", f"请复制并手动访问：\n{ISSUE_FEEDBACK_URL}\n\n错误: {exc}")


    def _open_qq_group_dialog(self):
        if self._qq_group_window and self._qq_group_window.winfo_exists():
            try:
                self._qq_group_window.deiconify()
                self._qq_group_window.lift()
                self._qq_group_window.focus_force()
            except Exception:
                pass
            return

        qr_image_path = _get_resource_path(QQ_GROUP_QR_RELATIVE_PATH)
        if not os.path.exists(qr_image_path):
            logging.error(f"未找到 QQ 群二维码图片: {qr_image_path}")
            self._log_popup_error("资源缺失", f"没有找到 QQ 群二维码图片：\n{qr_image_path}")
            return

        try:
            with Image.open(qr_image_path) as qr_image:
                display_image = qr_image.copy()
        except Exception as exc:
            logging.error(f"加载 QQ 群二维码失败: {exc}")
            self._log_popup_error("加载失败", f"二维码图片加载失败：\n{exc}")
            return

        max_qr_size = 420
        # 兼容新旧版本的 Pillow
        try:
            from PIL.Image import Resampling
            resample_method = Resampling.LANCZOS
        except (ImportError, AttributeError):
            resample_method = 1  # LANCZOS 的值
        try:
            if display_image.width > max_qr_size or display_image.height > max_qr_size:
                display_image.thumbnail((max_qr_size, max_qr_size), resample=resample_method)  # type: ignore
        except Exception as exc:
            logging.debug(f"调整 QQ 群二维码尺寸失败: {exc}")

        self._qq_group_photo = ImageTk.PhotoImage(display_image)
        self._qq_group_image_path = qr_image_path
        try:
            display_image.close()
        except Exception:
            pass

        window = tk.Toplevel(self.root)
        window.title("加入QQ群")
        window.resizable(False, False)
        window.transient(self.root)
        window.protocol("WM_DELETE_WINDOW", self._close_qq_group_window)

        container = ttk.Frame(window, padding=20)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text="扫描加入官方QQ群\n解决使用过程中的问题，或提出功能建议\n(点击二维码打开原图)").pack(pady=(0, 12))
        qr_label = ttk.Label(container, image=self._qq_group_photo, cursor="hand2")
        qr_label.pack()
        qr_label.bind("<Button-1>", self._show_qq_group_full_image)

        self._qq_group_window = window
        self._center_child_window(window)

    def _close_qq_group_window(self):
        if not self._qq_group_window:
            return
        try:
            if self._qq_group_window.winfo_exists():
                self._qq_group_window.destroy()
        except Exception:
            pass
        finally:
            self._qq_group_window = None
            self._qq_group_photo = None
            self._qq_group_image_path = None

    def _show_qq_group_full_image(self, event=None):
        if not self._qq_group_image_path:
            return
        image_path = self._qq_group_image_path
        try:
            if sys.platform.startswith("win"):
                os.startfile(image_path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", image_path], close_fds=True)
            else:
                subprocess.Popen(["xdg-open", image_path], close_fds=True)
        except Exception as exc:
            logging.error(f"打开 QQ 群二维码原图失败: {exc}")
            self._log_popup_error("打开失败", f"无法打开原图：\n{image_path}\n\n错误: {exc}")

    def _open_contact_dialog(self, default_type: str = "报错反馈"):
        """打开联系对话框，允许用户发送消息
        
        Args:
            default_type: 默认的消息类型，可选值："报错反馈"、"卡密获取"、"新功能建议"、"纯聊天"
        """
        window = tk.Toplevel(self.root)
        window.title("联系开发者")
        window.resizable(True, True)
        window.transient(self.root)

        container = ttk.Frame(window, padding=15)
        container.pack(fill=tk.BOTH, expand=True)

        # 邮箱标签和输入框
        email_label = ttk.Label(container, text="您的邮箱（选填，如果希望收到回复的话）：", font=("Microsoft YaHei", 10))
        email_label.pack(anchor=tk.W, pady=(0, 5))
        email_var = tk.StringVar()
        email_entry = ttk.Entry(container, textvariable=email_var, font=("Microsoft YaHei", 10))
        email_entry.pack(fill=tk.X, pady=(0, 10))

        # 消息类型下拉框
        ttk.Label(container, text="消息类型（可选）：", font=("Microsoft YaHei", 10)).pack(anchor=tk.W, pady=(0, 5))
        message_type_var = tk.StringVar(value=default_type)
        
        # 定义基础选项和完整选项
        base_options = ["报错反馈", "卡密获取", "新功能建议", "纯聊天"]
        full_options = ["报错反馈", "卡密获取", "新功能建议", "白嫖卡密（？）", "纯聊天"]
        
        # 根据默认类型决定初始选项列表
        initial_values = full_options if default_type in ["卡密获取", "白嫖卡密（？）"] else base_options
        
        message_type_combo = ttk.Combobox(
            container, 
            textvariable=message_type_var, 
            values=initial_values,
            state="readonly",
            font=("Microsoft YaHei", 10)
        )
        message_type_combo.pack(fill=tk.X, pady=(0, 10))

        # 消息类型变化回调
        def on_message_type_changed(*args):
            """当消息类型改变时更新邮箱标签和消息框"""
            current_type = message_type_var.get()
            if current_type == "卡密获取":
                email_label.config(text="您的邮箱（必填）：")
                message_prompt_label.config(text="请输入您的消息：")
                # 添加白嫖卡密选项
                message_type_combo['values'] = full_options
                # 检查文本框是否已有前缀
                current_text = text_widget.get("1.0", tk.END).strip()
                if not current_text.startswith("捐(施)助(舍)的金额：￥"):
                    text_widget.delete("1.0", tk.END)
                    text_widget.insert("1.0", "捐(施)助(舍)的金额：￥")
            elif current_type == "白嫖卡密（？）":
                email_label.config(text="您的邮箱（必填）：")
                message_prompt_label.config(text="请输入 白嫖话术：")
                # 保持完整选项（因为当前就是白嫖卡密）
                message_type_combo['values'] = full_options
                # 移除卡密获取的前缀
                current_text = text_widget.get("1.0", tk.END).strip()
                if current_text.startswith("捐(施)助(舍)的金额：￥"):
                    text_widget.delete("1.0", tk.END)
            else:
                email_label.config(text="您的邮箱（选填，如果希望收到回复的话）：")
                message_prompt_label.config(text="请输入您的消息：")
                # 移除白嫖卡密选项
                message_type_combo['values'] = base_options
                # 移除前缀
                current_text = text_widget.get("1.0", tk.END).strip()
                if current_text.startswith("捐(施)助(舍)的金额：￥"):
                    text_widget.delete("1.0", tk.END)
                    text_widget.insert("1.0", current_text[11:])  # 移除前缀
        
        message_type_var.trace("w", on_message_type_changed)

        message_prompt_label = ttk.Label(container, text="请输入您的消息：", font=("Microsoft YaHei", 10))
        message_prompt_label.pack(anchor=tk.W, pady=(0, 5))

        # 创建文本框
        text_frame = ttk.Frame(container)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        text_widget = tk.Text(text_frame, wrap=tk.WORD, yscrollcommand=scrollbar.set, font=("Microsoft YaHei", 10), height=8)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=text_widget.yview)
        
        # 根据默认类型初始化界面状态
        if default_type == "卡密获取":
            email_label.config(text="您的邮箱（必填）：")
            text_widget.insert("1.0", "捐(施)助(舍)的金额：￥")
        elif default_type == "白嫖卡密（？）":
            email_label.config(text="您的邮箱（必填）：")
            message_prompt_label.config(text="请输入白嫖话术：")

        # 按钮框架
        button_frame = ttk.Frame(container)
        button_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(8, 0))

        def send_message():
            """发送消息到API"""
            message_content = text_widget.get("1.0", tk.END).strip()
            email = email_var.get().strip()
            message_type = message_type_var.get()
            
            if not message_content:
                log_popup_warning("提示", "请输入消息内容", parent=window)
                return
            
            # 如果是卡密获取或白嫖卡密类型，邮箱必填；其他类型选填
            if message_type in ["卡密获取", "白嫖卡密（？）"]:
                if not email:
                    log_popup_warning("提示", f"{message_type}必须填写邮箱地址", parent=window)
                    return
            
            # 验证邮箱格式（如果填写了邮箱）
            if email:
                email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                if not re.match(email_pattern, email):
                    log_popup_warning("提示", "邮箱格式不正确，请输入有效的邮箱地址", parent=window)
                    return

            if not requests:
                log_popup_error("错误", "requests 模块未安装，无法发送消息", parent=window)
                return
            # 组合邮箱、来源和消息内容
            try:
                version = __VERSION__
            except NameError:
                version = "unknown"
            
            full_message = f"来源：fuck-wjx v{version}\n"
            full_message += f"类型：{message_type}\n"
            if email:
                full_message += f"联系邮箱： {email}\n"
            full_message += f"消息：{message_content}"

            # 禁用发送按钮，防止重复点击
            send_btn.config(state=tk.DISABLED)
            status_label.config(text="正在发送...")

            def send_request():
                try:
                    if requests is None:
                        def update_ui_no_requests():
                            status_label.config(text="")
                            send_btn.config(state=tk.NORMAL)
                            log_popup_error("错误", "requests 模块未安装", parent=window)
                        window.after(0, update_ui_no_requests)
                        return
                    
                    api_url = "https://bot.hungrym0.top"
                    payload = {
                        "message": full_message,
                        "timestamp": datetime.now().isoformat()
                    }
                    
                    response = requests.post(
                        api_url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=10
                    )
                    
                    def update_ui_success():
                        status_label.config(text="")
                        send_btn.config(state=tk.NORMAL)
                        if response.status_code == 200:
                            # 根据消息类型显示不同的成功提示
                            if message_type == "卡密获取":
                                success_message = "发送成功！请留意邮件信息！如未及时发送请在帮助-加入QQ群进群反馈！"
                            else:
                                success_message = "消息已成功发送！"
                            log_popup_info("成功", success_message, parent=window)
                            window.destroy()
                        else:
                            log_popup_error("错误", f"发送失败，服务器返回: {response.status_code}", parent=window)
                    
                    window.after(0, update_ui_success)
                    
                except Exception as exc:
                    def update_ui_error():
                        status_label.config(text="")
                        send_btn.config(state=tk.NORMAL)
                        logging.error(f"发送联系消息失败: {exc}")
                        log_popup_error("错误", f"发送失败：\n{str(exc)}", parent=window)
                    
                    window.after(0, update_ui_error)

            # 在后台线程发送请求
            thread = threading.Thread(target=send_request, daemon=True)
            thread.start()

        send_btn = ttk.Button(button_frame, text="发送", command=send_message)
        send_btn.pack(side=tk.RIGHT, padx=(0, 8))

        ttk.Button(button_frame, text="取消", command=window.destroy).pack(side=tk.RIGHT, padx=(0, 8))

        status_label = ttk.Label(button_frame, text="", foreground="blue")
        status_label.pack(side=tk.LEFT, padx=(12, 0))

        self._apply_window_scaling(window, base_width=520, base_height=440, min_height=380)
        self._center_child_window(window)
        text_widget.focus_set()

    def _on_root_focus(self, event=None):
        pass

    def _open_donation_dialog(self):
        """打开捐助窗口，显示payment.png"""
        window = tk.Toplevel(self.root)
        window.title("捐助")
        window.resizable(False, False)
        window.transient(self.root)
        opened_at = time.monotonic()
        close_handled = False

        def on_close():
            nonlocal close_handled
            if close_handled:
                try:
                    window.destroy()
                except Exception:
                    pass
                return

            close_handled = True
            stayed_seconds = time.monotonic() - opened_at
            try:
                window.destroy()
            finally:
                if stayed_seconds > 5:
                    try:
                        if self.root and self.root.winfo_exists():
                            self.root.after(0, lambda: self._open_contact_dialog(default_type="卡密获取"))
                    except Exception:
                        pass

        window.protocol("WM_DELETE_WINDOW", on_close)

        # 加载payment.png图片
        payment_image_path = _get_resource_path(os.path.join("assets", "payment.png"))
        
        if not os.path.exists(payment_image_path):
            logging.error(f"未找到支付二维码图片: {payment_image_path}")
            log_popup_error("资源缺失", f"没有找到支付二维码图片：\n{payment_image_path}")
            window.destroy()
            return

        try:
            with Image.open(payment_image_path) as payment_image:
                display_image = payment_image.copy()
        except Exception as exc:
            logging.error(f"加载支付二维码失败: {exc}")
            log_popup_error("加载失败", f"支付二维码图片加载失败：\n{exc}")
            window.destroy()
            return

        max_image_size = 420
        # 兼容新旧版本的 Pillow
        try:
            from PIL.Image import Resampling
            resample_method = Resampling.LANCZOS
        except (ImportError, AttributeError):
            resample_method = 1  # LANCZOS 的值
        try:
            if display_image.width > max_image_size or display_image.height > max_image_size:
                display_image.thumbnail((max_image_size, max_image_size), resample=resample_method)  # type: ignore
        except Exception as exc:
            logging.debug(f"调整支付二维码尺寸失败: {exc}")

        self._payment_photo = ImageTk.PhotoImage(display_image)
        self._payment_image_path = payment_image_path
        try:
            display_image.close()
        except Exception:
            pass

        container = ttk.Frame(window, padding=20)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text="如果你认为这个程序对你有帮助\n可否考虑通过以下方式支持一下求求了呜呜呜\n(点击二维码打开原图)", 
                 justify=tk.CENTER, font=("Microsoft YaHei", 10)).pack(pady=(0, 12))
        
        payment_label = ttk.Label(container, image=self._payment_photo, cursor="hand2")
        payment_label.pack()
        payment_label.bind("<Button-1>", self._show_payment_full_image)

        self._center_child_window(window)

    def _show_payment_full_image(self, event=None):
        """打开支付二维码原图"""
        if not self._payment_image_path:
            return
        image_path = self._payment_image_path
        try:
            if sys.platform.startswith("win"):
                os.startfile(image_path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", image_path], close_fds=True)
            else:
                subprocess.Popen(["xdg-open", image_path], close_fds=True)
        except Exception as exc:
            logging.error(f"打开支付二维码原图失败: {exc}")
            log_popup_error("打开失败", f"无法打开原图：\n{image_path}\n\n错误: {exc}")

    def _clear_logs_display(self):
        """清空日志显示"""
        # 清空日志缓冲区
        LOG_BUFFER_HANDLER.records.clear()
        # 清空 UI 显示
        if self._log_text_widget:
            self._log_text_widget.delete("1.0", tk.END)
        self._log_rendered_count = 0
        self._log_first_rendered_record = None

    def _schedule_log_refresh(self):
        """定期刷新日志显示"""
        if self._log_refresh_job:
            self.root.after_cancel(self._log_refresh_job)

        if self._log_text_widget:
            self._refresh_log_viewer()

        # 继续定期刷新
        self._log_refresh_job = self.root.after(500, self._schedule_log_refresh)

    def _schedule_ip_counter_refresh(self):
        """定期刷新随机IP计数显示"""
        try:
            refresh_ip_counter_display(self)
        except Exception as e:
            logging.debug(f"刷新IP计数显示出错: {e}")

        # 继续定期刷新（每2秒刷新一次）
        if not getattr(self, "_closing", False):
            self._ip_counter_refresh_job = self.root.after(2000, self._schedule_ip_counter_refresh)
        else:
            self._ip_counter_refresh_job = None

    def _on_toggle_log_dark_mode(self):
        """切换日志区域的深色背景"""
        self._apply_log_theme(self.log_dark_mode_var.get())

    def _apply_log_theme(self, use_dark: Optional[bool] = None):
        """根据复选框状态应用日志主题"""
        if not self._log_text_widget:
            return
        if use_dark is None:
            use_dark = bool(self.log_dark_mode_var.get())
        theme = LOG_DARK_THEME if use_dark else LOG_LIGHT_THEME
        self._log_text_widget.configure(
            bg=theme["background"],
            fg=theme["foreground"],
            insertbackground=theme["insert"],
            selectbackground=theme["select_bg"],
            selectforeground=theme["select_fg"],
            highlightbackground=theme["highlight_bg"],
            highlightcolor=theme["highlight_color"],
        )
        self._log_text_widget.tag_configure("INFO", foreground=theme["info_color"])

    def __init__(self, root: Optional[tk.Tk] = None, loading_splash: Optional[LoadingSplash] = None):
        self._shared_root = root is not None
        self.root = root if root is not None else tk.Tk()
        self._loading_splash = loading_splash

        self._app_icon_path: Optional[str] = None
        try:
            icon_path = _get_resource_path(APP_ICON_RELATIVE_PATH)
        except Exception:
            icon_path = None
        if icon_path and os.path.exists(icon_path):
            try:
                self.root.iconbitmap(default=icon_path)
            except Exception:
                pass
            self._app_icon_path = icon_path
            splash_window = getattr(self._loading_splash, "window", None)
            if splash_window:
                try:
                    splash_window.iconbitmap(icon_path)
                except Exception:
                    pass
        self._configs_dir = self._get_configs_directory()
        # 在窗口标题中显示当前版本号
        try:
            ver = __VERSION__
        except NameError:
            ver = "0.0.0"
        self.root.title(f"问卷星速填 v{ver}")
        self.root.bind("<FocusIn>", self._on_root_focus)
        self.question_entries: List[QuestionEntry] = []
        self.runner_thread: Optional[Thread] = None
        self.worker_threads: List[Thread] = []
        self.active_drivers: List[BrowserDriver] = []  # 跟踪活跃的浏览器实例
        self._launched_browser_pids: Set[int] = set()  # 跟踪本次会话启动的浏览器 PID
        self._stop_cleanup_thread_running = False  # 避免重复触发停止清理
        self._force_stop_now = False  # 达到目标后立即停止，不等待线程收尾
        self._ui_task_queue: "queue.SimpleQueue[Callable[[], None]]" = queue.SimpleQueue()
        self._ui_task_job: Optional[str] = None
        # 是否在点击停止后自动退出；可用环境变量 AUTO_EXIT_ON_STOP 控制，默认关闭
        _auto_exit_env = str(os.getenv("AUTO_EXIT_ON_STOP", "")).strip().lower()
        self._auto_exit_on_stop = _auto_exit_env in ("1", "true", "yes", "on")
        # 当首次点击“停止”时自动开启一次“停止后退出”，仅对下一次停止生效
        self._auto_exit_delay_once = False
        self.auto_exit_on_stop_var = tk.BooleanVar(value=self._auto_exit_on_stop)
        self.stop_requested_by_user: bool = False
        self.stop_request_ts: Optional[float] = None
        self.running = False
        self.status_job = None
        self.update_info = None  # 存储更新信息
        self.progress_value = 0  # 进度值 (0-100)
        self.total_submissions = 0  # 总提交数
        self.current_submissions = 0  # 当前提交数
        self._log_window: Optional[tk.Toplevel] = None
        self._settings_window: Optional[tk.Toplevel] = None
        self._log_text_widget: Optional[tk.Text] = None
        self._log_refresh_job: Optional[str] = None
        self._ip_counter_refresh_job: Optional[str] = None
        self._log_rendered_count = 0
        self._log_first_rendered_record: Optional[str] = None
        self._paned_position_restored = False
        self._default_paned_position_applied = False
        self._paned_configure_binding: Optional[str] = None
        self._qq_group_window: Optional[tk.Toplevel] = None

        self._closing = False
        self._qq_group_photo: Optional[ImageTk.PhotoImage] = None
        self._qq_group_image_path: Optional[str] = None
        self._payment_photo: Optional[ImageTk.PhotoImage] = None
        self._payment_image_path: Optional[str] = None
        self._config_changed = False  # 跟踪配置是否有改动
        self._initial_config: Dict[str, Any] = {}  # 存储初始配置以便比较
        self._wizard_history: List[int] = []
        self._wizard_commit_log: List[Dict[str, Any]] = []
        self._last_parsed_url: Optional[str] = None
        self._last_questions_info: Optional[List[Dict[str, Any]]] = None
        self._suspend_full_sim_autofill = False
        self._last_survey_title: Optional[str] = None
        self._threads_value_before_full_sim: Optional[str] = None
        self._timed_mode_prev_target: Optional[str] = None
        self._timed_mode_prev_threads: Optional[str] = None
        self._main_parameter_widgets: List[tk.Widget] = []
        self._settings_window_widgets: List[tk.Widget] = []
        self._random_ua_option_widgets: List[tk.Widget] = []
        self._timed_mode_locked_widgets: List[tk.Widget] = []
        self._full_simulation_window: Optional[tk.Toplevel] = None
        self._full_sim_status_label: Optional[ttk.Label] = None

        self._start_ui_task_loop()
        self._archived_notice_shown = False
        self._random_ip_disclaimer_ack = False
        self._suspend_random_ip_notice = False
        self._random_ip_api_placeholder_text = "API地址（不是卡密）"
        self._random_ip_api_placeholder_active = False
        self.url_var = tk.StringVar()
        self.target_var = tk.StringVar(value="")
        self.thread_var = tk.StringVar(value="2")
        
        # 为线程数输入框添加验证，限制最大值为12
        def _validate_thread_input(*args):
            try:
                val = self.thread_var.get().strip()
                if val and val.isdigit():
                    num = int(val)
                    if num > MAX_THREADS:
                        self.thread_var.set(str(MAX_THREADS))
            except:
                pass
        self.thread_var.trace_add("write", _validate_thread_input)
        
        self.interval_minutes_var = tk.StringVar(value="0")
        self.interval_seconds_var = tk.StringVar(value="0")
        self.interval_max_minutes_var = tk.StringVar(value="0")
        self.interval_max_seconds_var = tk.StringVar(value="0")
        self.answer_duration_min_var = tk.StringVar(value="0")
        self.answer_duration_max_var = tk.StringVar(value="0")
        self.random_ua_enabled_var = tk.BooleanVar(value=False)
        self.random_ua_pc_web_var = tk.BooleanVar(value=False)
        self.random_ua_android_wechat_var = tk.BooleanVar(value=True)
        self.random_ua_ios_wechat_var = tk.BooleanVar(value=True)
        self.random_ua_ipad_wechat_var = tk.BooleanVar(value=False)
        self.random_ua_ipad_web_var = tk.BooleanVar(value=False)
        self.random_ua_android_tablet_wechat_var = tk.BooleanVar(value=False)
        self.random_ua_android_tablet_web_var = tk.BooleanVar(value=False)
        self.random_ua_mac_wechat_var = tk.BooleanVar(value=False)
        self.random_ua_windows_wechat_var = tk.BooleanVar(value=False)
        self.random_ua_mac_web_var = tk.BooleanVar(value=False)
        self.random_ip_enabled_var = tk.BooleanVar(value=False)
        self.fail_stop_enabled_var = tk.BooleanVar(value=True)
        self.random_ip_api_var = tk.StringVar(value="")
        self.full_simulation_enabled_var = tk.BooleanVar(value=False)
        self.full_sim_target_var = tk.StringVar(value="")
        self.full_sim_estimated_minutes_var = tk.StringVar(value="3")
        self.full_sim_estimated_seconds_var = tk.StringVar(value="0")
        self.full_sim_total_minutes_var = tk.StringVar(value="30")
        self.full_sim_total_seconds_var = tk.StringVar(value="0")
        self.log_dark_mode_var = tk.BooleanVar(value=False)
        self._full_simulation_control_widgets: List[tk.Widget] = []
        self.preview_button: Optional[ttk.Button] = None
        self._custom_ip_config_path = get_custom_proxy_api_config_path(_get_runtime_directory())
        try:
            loaded_random_ip_api = load_custom_proxy_api_config(config_path=self._custom_ip_config_path)
        except Exception as exc:
            logging.error(f"加载自定义随机IP接口失败：{exc}")
            try:
                messagebox.showerror("随机 IP 接口错误", f"自定义随机IP接口无效：{exc}")
            except Exception:
                pass
            loaded_random_ip_api = ""
        if isinstance(loaded_random_ip_api, str):
            self.random_ip_api_var.set(loaded_random_ip_api)
        self._build_ui()
        if self._loading_splash:
            self._loading_splash.update_progress(90, "主界面加载完成，即将显示...")
        if self._shared_root:
            self.root.deiconify()
        self._center_window()  # 窗口居中显示
        self._check_updates_on_startup()  # 启动时检查更新
        self._schedule_log_refresh()  # 启动日志刷新
        self._schedule_ip_counter_refresh()  # 启动IP计数刷新

    def _build_ui(self):
        self.root.geometry("950x750")
        self.root.resizable(True, True)

        # 创建菜单栏
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        self._apply_win11_round_corners(menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        self._apply_win11_round_corners(file_menu)
        menubar.add_cascade(label="文件", menu=file_menu)
        file_menu.add_command(label="载入配置", command=self._load_config_from_dialog)
        file_menu.add_command(label="保存配置", command=self._save_config_as_dialog)

        menubar.add_command(label="设置", command=self._open_settings_window)

        help_menu = tk.Menu(menubar, tearoff=0)
        self._apply_win11_round_corners(help_menu)
        menubar.add_cascade(label="帮助", menu=help_menu)
        help_menu.add_command(label="检查更新", command=self.check_for_updates)
        help_menu.add_command(label="问题反馈", command=self._open_issue_feedback)
        help_menu.add_command(label="加入QQ群", command=self._open_qq_group_dialog)
        help_menu.add_separator()
        help_menu.add_command(label="关于", command=self.show_about)

        menubar.add_command(label="联系", command=self._open_contact_dialog)
        menubar.add_command(label="捐助", command=self._open_donation_dialog)

        # 创建主容器，使用 PanedWindow 分左右两部分
        self.main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._paned_configure_binding = self.main_paned.bind("<Configure>", self._on_main_paned_configure)

        # 左侧：配置区域（可滚动）
        config_container = ttk.Frame(self.main_paned)
        self.main_paned.add(config_container, weight=3)
        
        # 创建 Canvas 和 Scrollbar 用于整页滚动
        main_canvas = tk.Canvas(config_container, highlightthickness=0, bg="#f0f0f0")
        main_scrollbar = ttk.Scrollbar(config_container, orient="vertical", command=main_canvas.yview)
        
        # 创建可滚动的内容框架
        self.scrollable_content = ttk.Frame(main_canvas)
        
        # 创建窗口
        canvas_frame = main_canvas.create_window((0, 0), window=self.scrollable_content, anchor="nw")
        
        # 配置 scrollregion - 立即设置，避免空白
        def _update_scrollregion():
            self.scrollable_content.update_idletasks()
            main_canvas.configure(scrollregion=main_canvas.bbox("all"))

        self.scrollable_content.bind("<Configure>", lambda e: _update_scrollregion())
        
        # 当 Canvas 大小改变时，调整内容宽度
        def _on_canvas_configure(event):
            if event.width > 1:
                main_canvas.itemconfig(canvas_frame, width=event.width)
        
        main_canvas.bind("<Configure>", _on_canvas_configure)
        main_canvas.configure(yscrollcommand=main_scrollbar.set)
        
        # 布局 Canvas 和 Scrollbar
        main_canvas.pack(side="left", fill="both", expand=True)
        main_scrollbar.pack(side="right", fill="y")
        
        # 绑定鼠标滚轮事件（仅在鼠标在主窗口时）
        def _on_mousewheel(event):
            # 阻止向上滚动超出顶部
            if event.delta > 0 and main_canvas.yview()[0] <= 0:
                return
            main_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        def _bind_mousewheel(event):
            main_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_mousewheel(event):
            main_canvas.unbind_all("<MouseWheel>")

        # 仅在配置区域获得焦点时启用滚轮
        main_canvas.bind("<Enter>", _bind_mousewheel)
        main_canvas.bind("<Leave>", _unbind_mousewheel)
        
        # 保存引用以便后续使用
        self.main_canvas = main_canvas
        self.main_scrollbar = main_scrollbar

        # 右侧：日志区域
        log_container = ttk.LabelFrame(self.main_paned, text="📋 运行日志", padding=5)
        self.main_paned.add(log_container, weight=2)
        
        # 创建日志显示区域（带水平和垂直滚动条）
        # 使用 Frame 包装 Text 和滚动条
        log_frame = ttk.Frame(log_container)
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建垂直滚动条
        v_scrollbar = ttk.Scrollbar(log_frame, orient="vertical")
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 创建水平滚动条
        h_scrollbar = ttk.Scrollbar(log_frame, orient="horizontal")
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # 创建 Text Widget
        current_log_theme = LOG_DARK_THEME if self.log_dark_mode_var.get() else LOG_LIGHT_THEME
        self._log_text_widget = tk.Text(
            log_frame,
            wrap=tk.NONE,
            state="normal",
            yscrollcommand=v_scrollbar.set,
            xscrollcommand=h_scrollbar.set,
            bg=current_log_theme["background"],
            fg=current_log_theme["foreground"],
            insertbackground=current_log_theme["insert"],
            selectbackground=current_log_theme["select_bg"],
            selectforeground=current_log_theme["select_fg"],
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=2,
            highlightbackground=current_log_theme["highlight_bg"],
            highlightcolor=current_log_theme["highlight_color"],
            font=("SimHei", 10)
        )
        default_log_color = current_log_theme["info_color"]
        self._log_text_widget.tag_configure("INFO", foreground=default_log_color)
        self._log_text_widget.tag_configure("OK", foreground="#1f9525")
        self._log_text_widget.tag_configure("WARNING", foreground="#f5ba23")
        self._log_text_widget.tag_configure("ERROR", foreground="#ff2929")
        self._log_text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._log_text_widget.bind("<Key>", self._on_log_text_keypress)
        for sequence in ("<<Paste>>", "<<Cut>>", "<<Clear>>"):
            self._log_text_widget.bind(sequence, lambda e: "break")
        
        # 配置滚动条
        v_scrollbar.config(command=self._log_text_widget.yview)
        h_scrollbar.config(command=self._log_text_widget.xview)
        
        # 日志按钮区域
        log_button_frame = ttk.Frame(log_container)
        log_button_frame.pack(fill=tk.X, padx=0, pady=(5, 0))

        ttk.Checkbutton(
            log_button_frame,
            text="启用深色背景",
            variable=self.log_dark_mode_var,
            command=self._on_toggle_log_dark_mode
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(log_button_frame, text="保存日志文件", command=self._save_logs_to_file).pack(side=tk.RIGHT, padx=2)
        ttk.Button(log_button_frame, text="清空日志", command=self._clear_logs_display).pack(side=tk.RIGHT, padx=2)

        # 问卷链接输入区域
        step1_frame = ttk.LabelFrame(self.scrollable_content, text="🔗 问卷链接", padding=10)
        step1_frame.pack(fill=tk.X, padx=10, pady=5)

        link_frame = ttk.Frame(step1_frame)
        link_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(link_frame, text="问卷链接：").pack(side=tk.LEFT, padx=(0, 5))
        self.url_var.trace("w", lambda *args: self._mark_config_changed())
        url_entry = ttk.Entry(link_frame, textvariable=self.url_var, width=50)
        url_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        qr_frame = ttk.Frame(step1_frame)
        qr_frame.pack(fill=tk.X, pady=(0, 5))
        qr_upload_button = ttk.Button(
            qr_frame,
            text="📂上传问卷二维码图片",
            command=self.upload_qrcode,
            width=24,
            style="Accent.TButton"
        )
        qr_upload_button.pack(side=tk.LEFT, padx=5, pady=5, ipady=2)

        # 配置题目区域
        step2_frame = ttk.LabelFrame(self.scrollable_content, text="⚙️ 配置题目", padding=10)
        step2_frame.pack(fill=tk.X, padx=10, pady=5)

        auto_config_frame = ttk.Frame(step2_frame)
        auto_config_frame.pack(fill=tk.X, pady=(0, 5))

        button_row = ttk.Frame(auto_config_frame)
        button_row.pack(fill=tk.X)
        self.preview_button = ttk.Button(
            button_row,
            text="⚡ 自动配置问卷",
            command=self.preview_survey,
            style="Accent.TButton"
        )
        self.preview_button.pack(side=tk.LEFT, padx=5)

        # 执行设置区域（放在配置题目下方）
        step3_frame = ttk.LabelFrame(self.scrollable_content, text="💣 执行设置", padding=10)
        step3_frame.pack(fill=tk.X, padx=10, pady=5)

        settings_grid = ttk.Frame(step3_frame)
        settings_grid.pack(fill=tk.X)
        settings_grid.columnconfigure(1, weight=1)
        
        ttk.Label(settings_grid, text="目标份数：").grid(row=0, column=0, sticky="w", padx=5)
        self.target_var.trace_add("write", lambda *args: self._on_main_target_changed())
        target_entry = ttk.Entry(settings_grid, textvariable=self.target_var, width=10)
        target_entry.grid(row=0, column=1, sticky="w", padx=5)
        self._main_parameter_widgets.append(target_entry)

        ttk.Label(
            settings_grid,
            text="线程数（提交速度）：",
            wraplength=220,
            justify="left"
        ).grid(row=1, column=0, sticky="w", padx=5, pady=(8, 0))
        self.thread_var.trace("w", lambda *args: self._mark_config_changed())
        self.interval_minutes_var.trace("w", lambda *args: self._mark_config_changed())
        self.interval_seconds_var.trace("w", lambda *args: self._mark_config_changed())
        self.interval_max_minutes_var.trace("w", lambda *args: self._mark_config_changed())
        self.interval_max_seconds_var.trace("w", lambda *args: self._mark_config_changed())
        self.answer_duration_min_var.trace("w", lambda *args: self._mark_config_changed())
        self.answer_duration_max_var.trace("w", lambda *args: self._mark_config_changed())
        self.timed_mode_enabled_var = tk.BooleanVar(value=False)
        self.timed_mode_enabled_var.trace_add("write", lambda *args: self._on_timed_mode_toggle())
        self.random_ua_enabled_var.trace_add("write", lambda *args: self._on_random_ua_toggle())
        for _ua_var in (
            self.random_ua_pc_web_var,
            self.random_ua_android_wechat_var,
            self.random_ua_ios_wechat_var,
            self.random_ua_ipad_wechat_var,
            self.random_ua_ipad_web_var,
            self.random_ua_android_tablet_wechat_var,
            self.random_ua_android_tablet_web_var,
            self.random_ua_mac_wechat_var,
            self.random_ua_windows_wechat_var,
            self.random_ua_mac_web_var,
        ):
            _ua_var.trace_add("write", lambda *args: self._mark_config_changed())
        self.random_ip_enabled_var.trace_add("write", lambda *args: self._mark_config_changed())
        self.fail_stop_enabled_var.trace_add("write", lambda *args: self._mark_config_changed())
        self.auto_exit_on_stop_var.trace_add("write", lambda *args: self._on_auto_exit_toggle())
        self.full_sim_target_var.trace_add("write", lambda *args: self._on_full_sim_target_changed())
        self.full_sim_estimated_minutes_var.trace("w", lambda *args: self._on_full_sim_estimated_changed())
        self.full_sim_estimated_seconds_var.trace("w", lambda *args: self._on_full_sim_estimated_changed())
        self.full_sim_total_minutes_var.trace("w", lambda *args: self._on_full_sim_total_changed())
        self.full_sim_total_seconds_var.trace("w", lambda *args: self._on_full_sim_total_changed())
        self.full_simulation_enabled_var.trace_add("write", lambda *args: self._on_full_simulation_toggle())

        def adjust_thread_count(delta: int) -> None:
            try:
                current = int(self.thread_var.get())
            except ValueError:
                current = 1
            # 限制线程数在1-12之间
            new_value = max(1, min(current + delta, MAX_THREADS))
            self.thread_var.set(str(new_value))
            self._mark_config_changed()

        thread_control_frame = ttk.Frame(settings_grid)
        thread_control_frame.grid(row=1, column=1, sticky="w", padx=5, pady=(8, 0))
        thread_dec_button = ttk.Button(
            thread_control_frame,
            text="−",
            width=2,
            command=lambda: adjust_thread_count(-1)
        )
        thread_dec_button.grid(row=0, column=0, padx=(0, 2))
        thread_entry = ttk.Entry(thread_control_frame, textvariable=self.thread_var, width=5)
        thread_entry.grid(row=0, column=1, padx=2)
        thread_inc_button = ttk.Button(
            thread_control_frame,
            text="＋",
            width=2,
            command=lambda: adjust_thread_count(1)
        )
        thread_inc_button.grid(row=0, column=2, padx=(2, 0))
        self._main_parameter_widgets.extend([thread_dec_button, thread_entry, thread_inc_button])
        self._timed_mode_locked_widgets.extend([target_entry, thread_dec_button, thread_entry, thread_inc_button])

        # 随机 IP 开关单独一行，放在微信弹窗开关下方
        random_ip_frame = ttk.Frame(step3_frame)
        random_ip_frame.pack(fill=tk.X, padx=4, pady=(0, 4))
        random_ip_toggle = ttk.Checkbutton(
            random_ip_frame,
            text="启用随机 IP 提交",
            variable=self.random_ip_enabled_var,
            command=lambda: on_random_ip_toggle(self),
        )
        random_ip_toggle.pack(side=tk.LEFT)
        self._random_ip_toggle_widget = random_ip_toggle
        self._main_parameter_widgets.append(random_ip_toggle)

        # 随机IP计数显示和管理
        ip_counter_frame = ttk.Frame(step3_frame)
        ip_counter_frame.pack(fill=tk.X, padx=4, pady=(0, 4))
        ttk.Label(ip_counter_frame, text="随机IP计数：").pack(side=tk.LEFT, padx=5)
        self._ip_counter_label = ttk.Label(ip_counter_frame, text="0/20", font=("Segoe UI", 10, "bold"), foreground="blue")
        self._ip_counter_label.pack(side=tk.LEFT, padx=5)
        self._ip_reset_button_pack_opts = {"side": tk.LEFT, "padx": 2}
        self._ip_reset_button = ttk.Button(
            ip_counter_frame,
            text="解锁无限IP",
            command=lambda: reset_ip_counter(self),
        )
        self._ip_reset_button.pack(**self._ip_reset_button_pack_opts)
        refresh_ip_counter_display(self)

        
        # 高级选项：手动配置（始终显示）
        self.manual_config_frame = ttk.LabelFrame(self.scrollable_content, text="🔧 高级选项", padding=10)
        self.manual_config_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 按钮区域（放在这个 LabelFrame 中）
        btn_frame = ttk.Frame(self.manual_config_frame)
        btn_frame.pack(fill=tk.X, pady=5)
        
        # 全选复选框
        self.select_all_var = tk.BooleanVar(value=False)
        self.select_all_check = ttk.Checkbutton(
            btn_frame, 
            text="全选",
            variable=self.select_all_var,
            command=self.toggle_select_all
        )
        self.select_all_check.grid(row=0, column=0, padx=5)
        
        ttk.Button(btn_frame, text="手动添加配置", command=self.add_question_dialog).grid(
            row=0, column=1, padx=5
        )
        ttk.Button(btn_frame, text="编辑选中", command=self.edit_question).grid(
            row=0, column=2, padx=5
        )
        ttk.Button(btn_frame, text="删除选中", command=self.remove_question).grid(
            row=0, column=3, padx=5
        )
        
        # 提示信息（放在按钮下，避免被树状控件遮挡）
        info_frame = ttk.Frame(self.manual_config_frame)
        info_frame.pack(fill=tk.X, padx=5, pady=(0, 6))
        manual_hint_box = tk.Frame(info_frame, bg="#eef2fb", bd=1, relief="solid")
        manual_hint_box.pack(fill=tk.X, expand=True, padx=4, pady=2)
        self._manual_hint_label = ttk.Label(
            manual_hint_box, 
            text="  💡提示：排序题/滑块题会自动随机填写",
            foreground="#0f3d7a",
            font=("Segoe UI", 9),
            wraplength=520,
            justify="left"
        )
        self._manual_hint_label.pack(anchor="w", padx=8, pady=6)
        info_frame.bind("<Configure>", lambda e: self._manual_hint_label.configure(wraplength=max(180, e.width - 30)))

        # 分隔符
        ttk.Separator(self.manual_config_frame, orient='horizontal').pack(fill=tk.X, pady=(0, 5))

        # 题目列表区域（放在最后）
        question_list_frame = ttk.LabelFrame(self.scrollable_content, text="📝 已配置的题目", padding=10)
        question_list_frame.pack(fill=tk.X, padx=10, pady=5)
        self.question_list_frame = question_list_frame
        
        tree_frame = ttk.Frame(question_list_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建带滚动条的Canvas（限制高度）
        canvas = tk.Canvas(tree_frame, highlightthickness=0, height=200)
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self.questions_canvas = canvas
        self.questions_frame = scrollable_frame
        self.question_items = []

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # 执行按钮区域（固定在窗口底部，不参与滚动）
        action_frame = ttk.Frame(self.root, padding=10)
        action_frame.pack(fill=tk.X, side=tk.BOTTOM)

        # 进度条区域（在上面）
        progress_frame = ttk.Frame(action_frame)
        progress_frame.pack(fill=tk.X, pady=(0, 5))
         
        ttk.Label(progress_frame, text="执行进度:", font=("TkDefaultFont", 9)).pack(side=tk.LEFT, padx=(0, 5))
         
        self.progress_bar = ttk.Progressbar(
            progress_frame, 
            mode='determinate', 
            maximum=100,
            length=300
        )
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        self.progress_label = ttk.Label(progress_frame, text="0%", width=5, font=("TkDefaultFont", 9))
        self.progress_label.pack(side=tk.LEFT, padx=5)
        
        # 按钮行（在下面）
        button_frame = ttk.Frame(action_frame)
        button_frame.pack(fill=tk.X)
        
        self.start_button = ttk.Button(
            button_frame, 
            text="开始执行", 
            command=self.start_run,
            style="Accent.TButton"
        )
        self.start_button.pack(side=tk.LEFT, padx=5)
        self.stop_button = ttk.Button(button_frame, text="🚫 停止", command=self.stop_run, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)

        self.status_var = tk.StringVar(value="等待配置...")
        status_label = ttk.Label(button_frame, textvariable=self.status_var)
        status_label.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
          
        self._load_config()
        self._update_full_simulation_controls_state()
        self._update_parameter_widgets_state()
        self.root.after(200, self._ensure_default_paned_position)

    def _apply_win11_round_corners(self, *menus: tk.Misc) -> None:
        """在 Windows 11 上为菜单窗口启用圆角。"""
        if not sys.platform.startswith("win"):
            return

        try:
            import ctypes
            from ctypes import wintypes
        except Exception:
            return

        dwm_api = getattr(ctypes, "windll", None)
        if not dwm_api:
            return
        dwm_api = getattr(dwm_api, "dwmapi", None)
        if not dwm_api:
            return

        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2

        for menu in menus:
            if not menu:
                continue
            try:
                hwnd_value = int(menu.winfo_id())
            except Exception:
                continue
            if hwnd_value <= 0:
                continue
            preference = wintypes.DWORD(DWMWCP_ROUND)
            try:
                dwm_api.DwmSetWindowAttribute(
                    wintypes.HWND(hwnd_value),
                    ctypes.c_uint(DWMWA_WINDOW_CORNER_PREFERENCE),
                    ctypes.byref(preference),
                    ctypes.sizeof(preference),
                )
            except Exception:
                continue

    def _notify_loading(self, message: str):
        if self._loading_splash:
            self._loading_splash.update_message(message)

    def _on_main_paned_configure(self, event):
        width = getattr(event, "width", 0) or self.main_paned.winfo_width()
        if width <= 0:
            return
        if not self._paned_position_restored and not self._default_paned_position_applied:
            desired = max(PANED_MIN_LEFT_WIDTH, width // 2)
            try:
                self.main_paned.sashpos(0, desired)
                self._default_paned_position_applied = True
            except tk.TclError:
                self.root.after(150, self._ensure_default_paned_position)
        self._enforce_paned_minimums()

    def _ensure_default_paned_position(self):
        if self._paned_position_restored or self._default_paned_position_applied:
            return
        pane_width = self.main_paned.winfo_width() or self.root.winfo_width()
        if pane_width <= 0:
            self.root.after(100, self._ensure_default_paned_position)
            return
        desired = max(320, pane_width // 2)
        try:
            self.main_paned.sashpos(0, desired)
            self._default_paned_position_applied = True
        except Exception:
            self.root.after(150, self._ensure_default_paned_position)
        self._enforce_paned_minimums()

    def _enforce_paned_minimums(self):
        try:
            width = self.main_paned.winfo_width()
            if width <= 0:
                return
            sash_pos = self.main_paned.sashpos(0)
        except Exception:
            return
        min_left = PANED_MIN_LEFT_WIDTH
        min_right = PANED_MIN_RIGHT_WIDTH
        max_allowed = max(min_left, width - min_right)
        max_allowed = min(max_allowed, width - 1)
        max_allowed = max(0, max_allowed)
        min_target = min(min_left, max(0, width - 1))
        desired = min(max_allowed, max(min_target, sash_pos))
        if desired != sash_pos:
            try:
                self.main_paned.sashpos(0, desired)
            except Exception:
                pass

    def _update_full_simulation_controls_state(self):
        return full_simulation_ui.update_full_simulation_controls_state(self)

    def _update_parameter_widgets_state(self):
        locking = bool(self.full_simulation_enabled_var.get())
        if locking and self.timed_mode_enabled_var.get():
            try:
                self.timed_mode_enabled_var.set(False)
            except Exception:
                pass
        if locking and not self.random_ua_enabled_var.get():
            self.random_ua_enabled_var.set(True)
        state = tk.DISABLED if locking else tk.NORMAL
        targets = [w for w in getattr(self, '_main_parameter_widgets', []) if w is not None]
        targets += [w for w in getattr(self, '_settings_window_widgets', []) if w is not None]
        allowed_when_locked = []
        if locking:
            allowed_when_locked.extend(
                [
                    getattr(self, "_random_ip_toggle_widget", None),
                    getattr(self, "_fail_stop_toggle_widget", None),
                    getattr(self, "_auto_exit_toggle_widget", None),
                ]
            )
            allowed_when_locked.extend(getattr(self, "_random_ua_option_widgets", []))
            allowed_when_locked = [w for w in allowed_when_locked if w is not None]
        for widget in targets:
            desired_state = state
            if locking and widget in allowed_when_locked:
                desired_state = tk.NORMAL
            try:
                if widget.winfo_exists():
                    widget.configure(state=desired_state)
            except Exception:
                try:
                    if widget.winfo_exists():
                        widget["state"] = desired_state
                except Exception:
                    continue
        self._apply_random_ua_widgets_state()
        self._apply_timed_mode_widgets_state()

    def _apply_random_ua_widgets_state(self):
        option_widgets = getattr(self, "_random_ua_option_widgets", [])
        state = tk.NORMAL if self.random_ua_enabled_var.get() else tk.DISABLED
        cleaned: List[tk.Widget] = []
        for widget in option_widgets:
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
        self._random_ua_option_widgets = cleaned

    def _on_random_ua_toggle(self):
        self._apply_random_ua_widgets_state()
        self._mark_config_changed()

    def _on_auto_exit_toggle(self):
        try:
            self._auto_exit_on_stop = bool(self.auto_exit_on_stop_var.get())
        except Exception:
            self._auto_exit_on_stop = False
        # 手动切换时清除一次性延迟标记，避免状态错乱
        self._auto_exit_delay_once = False
        self._mark_config_changed()

    def _apply_timed_mode_widgets_state(self):
        enabled = bool(self.timed_mode_enabled_var.get())
        locked_state = tk.DISABLED if enabled else tk.NORMAL
        for widget in getattr(self, "_timed_mode_locked_widgets", []):
            if widget is None:
                continue
            try:
                if widget.winfo_exists():
                    widget.configure(state=locked_state)
            except Exception:
                try:
                    if widget.winfo_exists():
                        widget["state"] = locked_state
                except Exception:
                    continue

    def _on_timed_mode_toggle(self, *_: Any):
        enabled = bool(self.timed_mode_enabled_var.get())
        if enabled:
            # 定时模式只提交一份且使用单线程，自动锁定基础参数
            if getattr(self, "full_simulation_enabled_var", None) is not None:
                try:
                    if self.full_simulation_enabled_var.get():
                        self.full_simulation_enabled_var.set(False)
                        self._refresh_full_simulation_status_label()
                        full_simulation_ui.update_full_simulation_controls_state(self)
                        self._update_parameter_widgets_state()
                except Exception:
                    pass
            if self._timed_mode_prev_target is None:
                self._timed_mode_prev_target = self.target_var.get()
            if self._timed_mode_prev_threads is None:
                self._timed_mode_prev_threads = self.thread_var.get()
            if (self.target_var.get() or "").strip() != "1":
                self.target_var.set("1")
            if (self.thread_var.get() or "").strip() != "1":
                self.thread_var.set("1")
            logging.info("定时模式已开启：锁定线程数为 1、目标份数为 1，将等待问卷开放后立即提交。")
        else:
            if self._timed_mode_prev_target is not None:
                self.target_var.set(self._timed_mode_prev_target)
            if self._timed_mode_prev_threads is not None:
                self.thread_var.set(self._timed_mode_prev_threads)
            self._timed_mode_prev_target = None
            self._timed_mode_prev_threads = None
        self._apply_timed_mode_widgets_state()
        self._update_parameter_widgets_state()
        self._mark_config_changed()

    def _get_random_ip_api_text(self) -> str:
        try:
            value = str(self.random_ip_api_var.get()).strip()
            placeholder_text = str(getattr(self, "_random_ip_api_placeholder_text", "") or "").strip()
            if placeholder_text and value == placeholder_text:
                return ""
            if getattr(self, "_random_ip_api_placeholder_active", False):
                return ""
            return value
        except Exception:
            return ""

    def _save_random_ip_api_setting(self):
        api_value = self._get_random_ip_api_text()
        config_path = getattr(self, "_custom_ip_config_path", None) or get_custom_proxy_api_config_path(
            _get_runtime_directory()
        )
        try:
            save_custom_proxy_api_config(api_value, config_path=config_path)
            is_reset = not str(api_value or "").strip()
            if is_reset:
                self.random_ip_api_var.set("")
            if is_reset:
                info_message = "已恢复默认随机 IP 接口。\n"
            else:
                info_message = (
                    "自定义随机 IP 提取接口已保存并生效！\n\n"
                    f"保存位置：{config_path}"
                )
            self._log_popup_info(
                "已保存" if not is_reset else "已重置",
                info_message,
            )
            refresh_ip_counter_display(self)
        except Exception as exc:
            logging.error(f"保存随机 IP 接口失败: {exc}")
            self._log_popup_error("保存失败", f"随机 IP 接口保存失败：{exc}")

    def _reset_random_ip_api_setting(self):
        config_path = getattr(self, "_custom_ip_config_path", None) or get_custom_proxy_api_config_path(
            _get_runtime_directory()
        )
        # 重置时忽略输入框内容是否合规，直接清空并恢复默认
        self.random_ip_api_var.set("")
        try:
            reset_custom_proxy_api_config(config_path=config_path)
            self._log_popup_info(
                "已重置",
                (
                    "已删除自定义随机 IP 接口配置并恢复为默认接口。\n"
                ),
            )
            refresh_ip_counter_display(self)
        except Exception as exc:
            logging.error(f"重置随机 IP 接口失败: {exc}")
            self._log_popup_error("重置失败", f"重置随机 IP 接口失败：{exc}")

    def _refresh_full_simulation_status_label(self):
        return full_simulation_ui.refresh_full_simulation_status_label(self)

    def _update_full_sim_time_section_visibility(self):
        return full_simulation_ui.update_full_sim_time_section_visibility(self)

    def _sync_full_sim_target_to_main(self):
        return full_simulation_ui.sync_full_sim_target_to_main(self)

    def _get_full_simulation_question_count(self) -> int:
        return int(full_simulation_ui.get_full_simulation_question_count(self))

    @staticmethod
    def _parse_positive_int(value: Any) -> int:
        return int(full_simulation_ui.parse_positive_int(value))

    def _set_full_sim_duration(self, minutes_var: tk.StringVar, seconds_var: tk.StringVar, total_seconds: int) -> bool:
        return bool(full_simulation_ui.set_full_sim_duration(minutes_var, seconds_var, total_seconds))

    def _sync_full_sim_total_with_estimated(self):
        return full_simulation_ui.sync_full_sim_total_with_estimated(self)

    def _on_full_sim_estimated_changed(self, *_):
        self._mark_config_changed()
        self._sync_full_sim_total_with_estimated()

    def _auto_update_full_simulation_times(self):
        return full_simulation_ui.auto_update_full_simulation_times(self)

    def _update_full_sim_completion_time(self):
        return full_simulation_ui.update_full_sim_completion_time(self)

    def _on_full_sim_target_changed(self, *_):
        return full_simulation_ui.on_full_sim_target_changed(self)

    def _on_main_target_changed(self, *_):
        return full_simulation_ui.on_main_target_changed(self)

    def _on_full_simulation_toggle(self, *args):
        return full_simulation_ui.on_full_simulation_toggle(self)

    def _on_full_sim_total_changed(self, *_):
        self._mark_config_changed()
        self._update_full_sim_completion_time()

    def _restore_saved_paned_position(self, target_position: int, attempts: int = 5, delay_ms: int = 120) -> None:
        """
        多次尝试恢复保存的分隔线位置，避免布局未稳定时被默认值覆盖。
        """

        def _attempt(remaining: int):
            if remaining <= 0:
                return
            try:
                width = self.main_paned.winfo_width()
                if width <= 0:
                    raise RuntimeError("paned window width is zero")
                max_allowed = max(PANED_MIN_LEFT_WIDTH, width - PANED_MIN_RIGHT_WIDTH)
                max_allowed = min(max_allowed, width - 1)
                max_allowed = max(0, max_allowed)
                adjusted = min(max_allowed, max(PANED_MIN_LEFT_WIDTH, target_position))
                self.main_paned.sashpos(0, adjusted)
                self._paned_position_restored = True
            except Exception:
                pass
            finally:
                if remaining - 1 > 0:
                    self.root.after(delay_ms, lambda: _attempt(remaining - 1))

        self.root.after(0, lambda: _attempt(max(1, attempts)))


    def _open_settings_window(self):
        existing = getattr(self, "_settings_window", None)
        if existing:
            try:
                if existing.winfo_exists():
                    existing.lift()
                    existing.focus_force()
                    self._center_child_window(existing)
                    return
                else:
                    self._settings_window = None
            except tk.TclError:
                self._settings_window = None

        window = tk.Toplevel(self.root)
        window.title("设置")
        window.resizable(False, False)
        window.transient(self.root)
        self._settings_window = window
        self._settings_window_widgets = []
        self._random_ua_option_widgets = []
        self._random_ua_toggle_widget = None
        self._fail_stop_toggle_widget = None
        self._auto_exit_toggle_widget = None
        self._full_sim_status_label = None

        def _on_close():
            if self._settings_window is window:
                self._settings_window = None
                self._settings_window_widgets = []
                self._random_ua_option_widgets = []
                self._random_ua_toggle_widget = None
                self._fail_stop_toggle_widget = None
                self._auto_exit_toggle_widget = None
                self._full_sim_status_label = None
            try:
                window.destroy()
            except Exception:
                pass

        window.protocol("WM_DELETE_WINDOW", _on_close)

        content = ttk.Frame(window, padding=20)
        content.pack(fill=tk.BOTH, expand=True)

        hero_frame = tk.Frame(
            content,
            bg="#f4f7ff",
            highlightbackground="#dbe7ff",
            highlightthickness=1,
            bd=0,
        )
        hero_frame.pack(fill=tk.X, pady=(0, 12))

        hero_left = tk.Frame(hero_frame, bg="#f4f7ff")
        hero_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12, pady=10)
        tk.Label(
            hero_left,
            text="✨ 全真模拟模式",
            bg="#f4f7ff",
            fg="#0f3d7a",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        tk.Label(
            hero_left,
            text="模拟真实作答流程，支持调整问卷作答时长。",
            bg="#f4f7ff",
            fg="#44516b",
        ).pack(anchor="w", pady=(2, 0))

        hero_actions = tk.Frame(hero_frame, bg="#f4f7ff")
        hero_actions.pack(side=tk.RIGHT, padx=12, pady=10)
        status_label = ttk.Label(
            hero_actions,
            text="当前状态：未开启",
            foreground="#E4A207",
            font=("Segoe UI", 10, "bold"),
            padding=(8, 4),
        )
        status_label.pack(anchor="e", fill=tk.X, pady=(0, 6))
        ttk.Button(
            hero_actions,
            text="打开全真模拟设置",
            command=self._open_full_simulation_window,
            style="Accent.TButton",
            width=18,
        ).pack(anchor="e", fill=tk.X)
        self._full_sim_status_label = status_label
        self._refresh_full_simulation_status_label()

        advanced_frame = ttk.LabelFrame(content, text="高级设置", padding=15)
        advanced_frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        advanced_grid = ttk.Frame(advanced_frame)
        advanced_grid.pack(fill=tk.X)
        advanced_grid.columnconfigure(0, weight=1)
        advanced_grid.columnconfigure(1, weight=1)

        safety_card = ttk.LabelFrame(advanced_grid, text="安全与控制", padding=10)
        safety_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        fail_stop_toggle = ttk.Checkbutton(
            safety_card,
            text="失败过多自动停止",
            variable=self.fail_stop_enabled_var,
        )
        fail_stop_toggle.pack(anchor="w", pady=(0, 4))
        ttk.Label(
            safety_card,
            text="避免无限重试造成资源浪费。",
            foreground="#6b6b6b",
        ).pack(anchor="w", padx=(22, 0), pady=(0, 6))
        self._fail_stop_toggle_widget = fail_stop_toggle
        self._settings_window_widgets.append(fail_stop_toggle)

        auto_exit_toggle = ttk.Checkbutton(
            safety_card,
            text="停止时直接退出程序",
            variable=self.auto_exit_on_stop_var,
            command=self._on_auto_exit_toggle,
        )
        auto_exit_toggle.pack(anchor="w", pady=(0, 2))
        ttk.Label(
            safety_card,
            text="点击停止直接退出，防止线程阻塞引发卡顿。",
            foreground="#6b6b6b",
        ).pack(anchor="w", padx=(22, 0), pady=(0, 6))
        self._auto_exit_toggle_widget = auto_exit_toggle
        self._settings_window_widgets.append(auto_exit_toggle)

        ua_toggle = ttk.Checkbutton(
            safety_card,
            text="启用随机 UA",
            variable=self.random_ua_enabled_var,
            command=self._on_random_ua_toggle,
        )
        ua_toggle.pack(anchor="w", pady=(0, 2))
        ttk.Label(
            safety_card,
            text="勾选后按照右侧的范围随机模拟设备。",
            foreground="#6b6b6b",
        ).pack(anchor="w", padx=(22, 0))
        self._random_ua_toggle_widget = ua_toggle
        self._settings_window_widgets.append(ua_toggle)

        ua_options_frame = ttk.LabelFrame(advanced_grid, text="随机 UA 范围", padding=10)
        ua_options_frame.grid(row=0, column=1, sticky="nsew")
        ttk.Label(ua_options_frame, text="选择程序模拟的浏览器类型：").pack(anchor="w", pady=(0, 6))
        ua_options_inner = ttk.Frame(ua_options_frame)
        ua_options_inner.pack(anchor="w")
        ua_option_widgets: List[tk.Widget] = []
        ua_options_list = [
            ("Windows网页端", self.random_ua_pc_web_var),
            ("安卓微信端", self.random_ua_android_wechat_var),
            ("苹果微信端", self.random_ua_ios_wechat_var),
            ("iPad微信端", self.random_ua_ipad_wechat_var),
            ("iPad网页端", self.random_ua_ipad_web_var),
            ("安卓平板微信端", self.random_ua_android_tablet_wechat_var),
            ("安卓平板网页端", self.random_ua_android_tablet_web_var),
            ("Mac微信WebView", self.random_ua_mac_wechat_var),
            ("Windows微信WebView", self.random_ua_windows_wechat_var),
            ("Mac网页端", self.random_ua_mac_web_var),
        ]
        for idx, (text_value, var) in enumerate(ua_options_list):
            row = idx // 3
            col = idx % 3
            cb = ttk.Checkbutton(ua_options_inner, text=text_value, variable=var)
            cb.grid(row=row, column=col, padx=(0, 10), pady=2, sticky="w")
            ua_option_widgets.append(cb)
        self._random_ua_option_widgets.extend(ua_option_widgets)
        self._settings_window_widgets.extend(ua_option_widgets)

        timed_mode_frame = ttk.LabelFrame(advanced_frame, text="⏱️ 定时模式", padding=10)
        timed_mode_frame.pack(fill=tk.X, pady=(10, 0))
        timed_toggle = ttk.Checkbutton(
            timed_mode_frame,
            text="问卷定时开放时启用自动刷新等待（仅提交 1 份）",
            variable=self.timed_mode_enabled_var,
            command=self._on_timed_mode_toggle,
        )
        timed_toggle.pack(anchor="w", pady=(0, 2))
        ttk.Label(
            timed_mode_frame,
            text="开放前保持单实例快速刷新，开放后立即填写并提交后停止。",
            foreground="#6b6b6b",
            wraplength=440,
            justify="left",
        ).pack(anchor="w", padx=(22, 0))
        self._settings_window_widgets.append(timed_toggle)

        ttk.Separator(advanced_frame, orient="horizontal").pack(fill=tk.X, pady=(12, 10))

        ip_api_frame = ttk.LabelFrame(advanced_frame, text="随机 IP 接口", padding=12)
        ip_api_frame.pack(fill=tk.X)
        ttk.Label(ip_api_frame, text="自定义随机 IP 提取 API：").grid(row=0, column=0, sticky="nw", padx=(0, 8))
        ip_api_entry = ttk.Entry(ip_api_frame, textvariable=self.random_ip_api_var, width=52)
        ip_api_entry.grid(row=0, column=1, sticky="we", pady=(0, 4))
        ttk.Label(
            ip_api_frame,
            text="API 仅支持 json 类型的数据格式。如果你不知道这是什么，请留空。",
            foreground="#6b6b6b",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        ip_buttons = ttk.Frame(ip_api_frame)
        ip_buttons.grid(row=0, column=2, rowspan=2, sticky="ne", padx=(10, 0))
        ip_api_frame.columnconfigure(1, weight=1)

        placeholder_text = str(getattr(self, "_random_ip_api_placeholder_text", "") or "").strip() or "API地址（不是卡密）"
        placeholder_style_name = "RandomIpApi.Placeholder.TEntry"
        try:
            normal_style_name = ip_api_entry.cget("style") or "TEntry"
        except Exception:
            normal_style_name = "TEntry"
        try:
            style = ttk.Style(window)
            style.configure(placeholder_style_name, foreground="#9aa0a6")
        except Exception:
            style = None

        def _apply_ip_api_entry_appearance(is_placeholder: bool) -> None:
            try:
                if is_placeholder:
                    if style is not None:
                        ip_api_entry.configure(style=placeholder_style_name)
                    else:
                        ip_api_entry.configure(foreground="#9aa0a6")
                else:
                    if style is not None:
                        ip_api_entry.configure(style=normal_style_name)
                    else:
                        ip_api_entry.configure(foreground="")
            except Exception:
                pass

        def _sync_ip_api_placeholder_from_value() -> None:
            try:
                current = str(self.random_ip_api_var.get() or "")
            except Exception:
                current = ""
            if current.strip() and current.strip() != placeholder_text:
                self._random_ip_api_placeholder_active = False
                _apply_ip_api_entry_appearance(False)
                return
            self._random_ip_api_placeholder_active = True
            try:
                self.random_ip_api_var.set(placeholder_text)
            except Exception:
                pass
            _apply_ip_api_entry_appearance(True)
            try:
                ip_api_entry.icursor(0)
            except Exception:
                pass

        def _on_ip_api_focus_in(_event=None):
            try:
                current = str(self.random_ip_api_var.get() or "").strip()
            except Exception:
                current = ""
            if getattr(self, "_random_ip_api_placeholder_active", False) or current == placeholder_text:
                self._random_ip_api_placeholder_active = False
                try:
                    self.random_ip_api_var.set("")
                except Exception:
                    pass
                _apply_ip_api_entry_appearance(False)

        def _on_ip_api_focus_out(_event=None):
            try:
                current = str(self.random_ip_api_var.get() or "").strip()
            except Exception:
                current = ""
            if not current:
                _sync_ip_api_placeholder_from_value()

        ip_api_entry.bind("<FocusIn>", _on_ip_api_focus_in, add="+")
        ip_api_entry.bind("<FocusOut>", _on_ip_api_focus_out, add="+")
        _sync_ip_api_placeholder_from_value()

        def _on_ip_api_save():
            self._save_random_ip_api_setting()
            _sync_ip_api_placeholder_from_value()

        def _on_ip_api_reset():
            self._reset_random_ip_api_setting()
            _sync_ip_api_placeholder_from_value()

        ip_api_save_btn = ttk.Button(ip_buttons, text="保存", command=_on_ip_api_save, width=10)
        ip_api_save_btn.pack(fill=tk.X)
        ip_api_reset_btn = ttk.Button(ip_buttons, text="重置", command=_on_ip_api_reset, width=10)
        ip_api_reset_btn.pack(fill=tk.X, pady=(6, 0))
        self._settings_window_widgets.extend([ip_api_entry, ip_api_save_btn, ip_api_reset_btn])

        button_frame = ttk.Frame(content)
        button_frame.pack(fill=tk.X, pady=(18, 0))
        ttk.Button(button_frame, text="关闭", command=_on_close, width=10).pack(anchor="e")

        self._update_parameter_widgets_state()
        window.update_idletasks()
        self._center_child_window(window)
        window.lift()
        window.focus_force()


    def _open_full_simulation_window(self):
        return full_simulation_ui.open_full_simulation_window(self)

    def add_question_dialog(self):
        """弹出对话框来添加新的题目配置"""
        dialog = tk.Toplevel(self.root)
        dialog.title("添加题目配置")
        dialog.geometry("650x550")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 创建可滚动的内容区域
        main_canvas = tk.Canvas(dialog, highlightthickness=0)
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=main_canvas.yview)
        main_frame = ttk.Frame(main_canvas, padding=15)
        
        main_frame.bind(
            "<Configure>",
            lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        )
        
        main_canvas.create_window((0, 0), window=main_frame, anchor="nw")
        main_canvas.configure(yscrollcommand=scrollbar.set)
        
        main_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 绑定鼠标滚轮到对话框
        def _on_mousewheel(event):
            # 检查鼠标是否在canvas上方，如果是则处理滚轮事件
            if main_canvas.winfo_containing(event.x_root, event.y_root) == main_canvas:
                main_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        dialog.bind("<MouseWheel>", _on_mousewheel)
        
        def _cleanup():
            dialog.unbind("<MouseWheel>")
            dialog.destroy()
        
        dialog.protocol("WM_DELETE_WINDOW", _cleanup)
        
        # ===== 题型选择 =====
        ttk.Label(main_frame, text="题型：", font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, sticky="w", pady=8, padx=(0, 10))
        question_type_var = tk.StringVar(value=TYPE_OPTIONS[0][1])
        question_type_combo = ttk.Combobox(
            main_frame,
            textvariable=question_type_var,
            state="readonly",
            values=[item[1] for item in TYPE_OPTIONS],
            width=30,
        )
        question_type_combo.grid(row=0, column=1, sticky="w", pady=8)
        
        # 创建一个容器用于动态内容
        dynamic_frame = ttk.Frame(main_frame)
        dynamic_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=10)
        main_frame.rowconfigure(1, weight=1)
        
        # 保存状态变量
        state: Dict[str, Any] = {
             'option_count_var': None,
             'matrix_rows_var': None,
             'distribution_var': None,
             'weights_var': None,
             'multiple_random_var': None,
             'answer_vars': None,
             'weight_frame': None,
             'current_sliders': None,
             'is_location': False,
             'multi_blank_count_var': None,
             'multi_group_vars': None,
         }
        
        def refresh_dynamic_content(*args):
            """根据选择的题型刷新动态内容"""
            # 清空动态框
            for child in dynamic_frame.winfo_children():
                child.destroy()
            
            q_type = LABEL_TO_TYPE.get(question_type_var.get(), "single")
            location_mode = q_type == "location"
            if location_mode:
                q_type = "text"
            state['is_location'] = location_mode

            if q_type == "text":
                # ===== 填空/位置题 =====
                header_text = "位置候选列表：" if location_mode else "填空答案列表："
                ttk.Label(dynamic_frame, text=header_text, font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=5, fill=tk.X)
                
                answer_frame = ttk.Frame(dynamic_frame)
                answer_frame.pack(fill=tk.BOTH, expand=True, pady=5)
                
                state['answer_vars'] = []  # type: ignore
                
                def add_answer_field(initial_value=""):
                    row_frame = ttk.Frame(answer_frame)
                    row_frame.pack(fill=tk.X, pady=3, padx=5)
                    
                    ttk.Label(row_frame, text=f"答案{len(state['answer_vars'])+1}:", width=8).pack(side=tk.LEFT)  # type: ignore
                    
                    var = tk.StringVar(value=initial_value)
                    entry_widget = ttk.Entry(row_frame, textvariable=var, width=35)
                    entry_widget.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
                    
                    def remove_field():
                        row_frame.destroy()
                        state['answer_vars'].remove(var)  # type: ignore
                        update_labels()
                    
                    ttk.Button(row_frame, text="✖", width=3, command=remove_field).pack(side=tk.RIGHT)
                    
                    state['answer_vars'].append(var)  # type: ignore
                    return var
                
                def update_labels():
                    for i, child in enumerate(answer_frame.winfo_children()):
                        if child.winfo_children():
                            label = child.winfo_children()[0]
                            if isinstance(label, ttk.Label):
                                label.config(text=f"答案{i+1}:")
                
                default_value = "" if location_mode else "默认答案"
                add_answer_field(default_value)
                
                add_btn_frame = ttk.Frame(dynamic_frame)
                add_btn_frame.pack(fill=tk.X, pady=(5, 0))
                ttk.Button(add_btn_frame, text="+ 添加答案", command=lambda: add_answer_field()).pack(anchor="w")
                if location_mode:
                    ttk.Label(
                        dynamic_frame,
                        text="支持“地名”或“地名|经度,纬度”格式，未提供经纬度时系统会尝试自动解析。",
                        foreground="gray",
                        wraplength=540,
                    ).pack(anchor="w", pady=(6, 0), fill=tk.X)
                
            elif q_type == "multi_text":
                # ===== 多项填空题 =====
                control_frame = ttk.Frame(dynamic_frame)
                control_frame.pack(fill=tk.X, pady=5)

                ttk.Label(control_frame, text="填空项数量：", font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, padx=(0, 5))
                state['multi_blank_count_var'] = tk.StringVar(value="2")  # type: ignore

                def _get_blank_count() -> int:
                    try:
                        count = int(state['multi_blank_count_var'].get())  # type: ignore
                        return max(2, count)
                    except Exception:
                        return 2

                def update_blank_count(delta: int):
                    current_count = _get_blank_count()
                    new_count = max(2, current_count + delta)
                    state['multi_blank_count_var'].set(str(new_count))  # type: ignore
                    refresh_groups()

                ttk.Button(control_frame, text="−", width=3, command=lambda: update_blank_count(-1)).pack(side=tk.LEFT, padx=2)
                ttk.Entry(control_frame, textvariable=state['multi_blank_count_var'], width=5).pack(side=tk.LEFT, padx=2)  # type: ignore
                ttk.Button(control_frame, text="+", width=3, command=lambda: update_blank_count(1)).pack(side=tk.LEFT, padx=2)

                ttk.Label(
                    dynamic_frame,
                    text="每一行代表一组完整答案，保存后会随机选择一组填写到多个输入框。",
                    foreground="gray",
                    wraplength=540,
                ).pack(anchor="w", pady=(5, 6), fill=tk.X)

                groups_frame = ttk.Frame(dynamic_frame)
                groups_frame.pack(fill=tk.BOTH, expand=True, pady=5)

                group_vars: List[List[tk.StringVar]] = []
                state['multi_group_vars'] = group_vars  # type: ignore

                def add_group(initial_values: Optional[List[str]] = None):
                    row_frame = ttk.Frame(groups_frame)
                    row_frame.pack(fill=tk.X, pady=3, padx=5)
                    row_frame.grid_columnconfigure(1, weight=1)

                    label = ttk.Label(row_frame, text=f"组{len(group_vars)+1}:", width=6)
                    label.grid(row=0, column=0, sticky="nw")

                    # 创建输入框容器，使用 grid，并为删除按钮保留独立列避免溢出
                    inputs_frame = ttk.Frame(row_frame)
                    inputs_frame.grid(row=0, column=1, sticky="ew")

                    # 删除按钮放在右边，确保不被输入框挤出
                    def remove_group():
                        row_frame.destroy()
                        try:
                            group_vars.remove(vars_row)
                        except ValueError:
                            pass
                        update_group_labels()

                    delete_btn = ttk.Button(row_frame, text="删除", width=5, command=remove_group)
                    delete_btn.grid(row=0, column=2, padx=(6, 0), sticky="ne")

                    vars_row: List[tk.StringVar] = []
                    blank_count = _get_blank_count()
                    max_per_row = 4
                    for col in range(max_per_row):
                        inputs_frame.grid_columnconfigure(col, weight=1)
                    for j in range(blank_count):
                        init_val = ""
                        if initial_values and j < len(initial_values):
                            init_val = initial_values[j]
                        var = tk.StringVar(value=init_val)
                        entry_widget = ttk.Entry(inputs_frame, textvariable=var, width=10)
                        grid_row = j // max_per_row
                        grid_col = j % max_per_row
                        entry_widget.grid(row=grid_row, column=grid_col, padx=(0, 4), pady=2, sticky="ew")
                        vars_row.append(var)

                    group_vars.append(vars_row)
                    return vars_row

                def update_group_labels():
                    for i, child in enumerate(groups_frame.winfo_children()):
                        if child.winfo_children():
                            label_widget = child.winfo_children()[0]
                            if isinstance(label_widget, ttk.Label):
                                label_widget.config(text=f"组{i+1}:")

                def refresh_groups():
                    blank_count = _get_blank_count()
                    existing_values: List[List[str]] = []
                    for vars_row in group_vars:
                        existing_values.append([v.get() for v in vars_row])
                    for child in groups_frame.winfo_children():
                        child.destroy()
                    group_vars.clear()
                    if existing_values:
                        for values in existing_values:
                            padded = list(values) + [""] * max(0, blank_count - len(values))
                            add_group(padded[:blank_count])
                    else:
                        add_group()

                refresh_groups()
                state['multi_blank_count_var'].trace_add("write", lambda *args: refresh_groups())  # type: ignore

                add_btn_frame = ttk.Frame(dynamic_frame)
                add_btn_frame.pack(fill=tk.X, pady=(5, 0))
                ttk.Button(add_btn_frame, text="+ 添加答案组", command=lambda: add_group()).pack(anchor="w")

            elif q_type == "multiple":
                # ===== 多选题 =====
                option_control_frame = ttk.Frame(dynamic_frame)
                option_control_frame.pack(fill=tk.X, pady=5)
                
                ttk.Label(option_control_frame, text="选项个数：", font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, padx=(0, 5))
                
                state['option_count_var'] = tk.StringVar(value="4")
                
                def update_option_count(delta):
                    try:
                        current = int(state['option_count_var'].get())
                        new_count = max(1, current + delta)
                        state['option_count_var'].set(str(new_count))
                        refresh_sliders()
                    except ValueError:
                        pass
                
                ttk.Button(option_control_frame, text="-", width=3, command=lambda: update_option_count(-1)).pack(side=tk.LEFT, padx=2)
                ttk.Entry(option_control_frame, textvariable=state['option_count_var'], width=5).pack(side=tk.LEFT, padx=2)
                ttk.Button(option_control_frame, text="+", width=3, command=lambda: update_option_count(1)).pack(side=tk.LEFT, padx=2)
                
                # 多选方式
                ttk.Label(dynamic_frame, text="多选方式：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(10, 5), fill=tk.X)
                
                state['multiple_random_var'] = tk.BooleanVar(value=False)  # type: ignore
                ttk.Checkbutton(
                    dynamic_frame, 
                    text="完全随机选择若干项",
                    variable=state['multiple_random_var']  # type: ignore
                ).pack(anchor="w", pady=3, fill=tk.X)
                
                # 概率设置
                ttk.Label(dynamic_frame, text="选项选中概率（0-100%）：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(10, 5), fill=tk.X)
                
                sliders_frame = ttk.Frame(dynamic_frame)
                sliders_frame.pack(fill=tk.BOTH, expand=True, pady=5)
                
                state['current_sliders'] = []  # type: ignore
                
                def refresh_sliders():
                    for child in sliders_frame.winfo_children():
                        child.destroy()
                    state['current_sliders'] = []  # type: ignore
                    
                    try:
                        option_count = int(state['option_count_var'].get())  # type: ignore
                    except:
                        option_count = 4
                    
                    for i in range(option_count):
                        row_frame = ttk.Frame(sliders_frame)
                        row_frame.pack(fill=tk.X, pady=3, padx=(10, 10))
                        row_frame.columnconfigure(1, weight=1)
                        
                        var = tk.DoubleVar(value=50.0)
                        
                        label_text = ttk.Label(row_frame, text=f"选项 {i+1}:", width=8, anchor="w")
                        label_text.grid(row=0, column=0, sticky="w")
                        
                        slider = ttk.Scale(row_frame, from_=0, to=100, variable=var, orient=tk.HORIZONTAL)
                        slider.grid(row=0, column=1, sticky="ew", padx=5)
                        
                        percent_label = ttk.Label(row_frame, text="50%", width=6, anchor="e")
                        percent_label.grid(row=0, column=2, sticky="e")
                        
                        var.trace_add("write", lambda *args, l=percent_label, v=var: l.config(text=f"{int(v.get())}%"))
                        state['current_sliders'].append(var)  # type: ignore
                
                refresh_sliders()
                state['option_count_var'].trace_add("write", lambda *args: refresh_sliders())  # type: ignore
                
            elif q_type == "matrix":
                # ===== 矩阵题 =====
                option_control_frame = ttk.Frame(dynamic_frame)
                option_control_frame.pack(fill=tk.X, pady=5)
                
                ttk.Label(option_control_frame, text="选项个数（列）：", font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, padx=(0, 5))
                
                state['option_count_var'] = tk.StringVar(value="4")  # type: ignore
                
                def update_option_count(delta):
                    try:
                        current = int(state['option_count_var'].get())  # type: ignore
                        new_count = max(1, current + delta)
                        state['option_count_var'].set(str(new_count))  # type: ignore
                        refresh_matrix_sliders()
                    except ValueError:
                        pass
                
                ttk.Button(option_control_frame, text="-", width=3, command=lambda: update_option_count(-1)).pack(side=tk.LEFT, padx=2)
                ttk.Entry(option_control_frame, textvariable=state['option_count_var'], width=5).pack(side=tk.LEFT, padx=2)  # type: ignore
                ttk.Button(option_control_frame, text="+", width=3, command=lambda: update_option_count(1)).pack(side=tk.LEFT, padx=2)
                
                # 矩阵行数
                matrix_row_frame = ttk.Frame(dynamic_frame)
                matrix_row_frame.pack(fill=tk.X, pady=5)
                
                ttk.Label(matrix_row_frame, text="矩阵行数：", font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, padx=(0, 5))
                
                state['matrix_rows_var'] = tk.StringVar(value="3")  # type: ignore
                
                def update_matrix_rows(delta):
                    try:
                        current = int(state['matrix_rows_var'].get())  # type: ignore
                        new_count = max(1, current + delta)
                        state['matrix_rows_var'].set(str(new_count))  # type: ignore
                    except ValueError:
                        pass
                
                ttk.Button(matrix_row_frame, text="-", width=3, command=lambda: update_matrix_rows(-1)).pack(side=tk.LEFT, padx=2)
                ttk.Entry(matrix_row_frame, textvariable=state['matrix_rows_var'], width=5).pack(side=tk.LEFT, padx=2)  # type: ignore
                ttk.Button(matrix_row_frame, text="+", width=3, command=lambda: update_matrix_rows(1)).pack(side=tk.LEFT, padx=2)
                
                # 分布方式
                ttk.Label(dynamic_frame, text="选择分布方式：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(10, 5), fill=tk.X)
                
                state['distribution_var'] = tk.StringVar(value="random")  # type: ignore
                
                ttk.Radiobutton(dynamic_frame, text="完全随机（每次随机选择）", 
                              variable=state['distribution_var'], value="random",  # type: ignore
                              command=lambda: (state['weight_frame'].pack_forget() if state['weight_frame'] else None)).pack(anchor="w", pady=3, fill=tk.X)  # type: ignore
                ttk.Radiobutton(dynamic_frame, text="自定义权重（使用滑块设置）", 
                              variable=state['distribution_var'], value="custom",  # type: ignore
                              command=lambda: (state['weight_frame'].pack(fill=tk.BOTH, expand=True, pady=5) if state['weight_frame'] else None)).pack(anchor="w", pady=3, fill=tk.X)  # type: ignore
                
                # 权重滑块容器
                state['weight_frame'] = ttk.Frame(dynamic_frame)  # type: ignore
                
                ttk.Label(state['weight_frame'], text="选项权重（用:或,分隔，如 3:2:1）：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(5, 3), fill=tk.X)  # type: ignore
                
                state['weights_var'] = tk.StringVar(value="1:1:1:1")  # type: ignore
                ttk.Entry(state['weight_frame'], textvariable=state['weights_var'], width=40).pack(fill=tk.X, pady=3)  # type: ignore
                
                state['current_sliders'] = []  # type: ignore
                
                def refresh_matrix_sliders():
                    pass  # 矩阵题不需要动态刷新滑块
                
                state['option_count_var'].trace_add("write", lambda *args: refresh_matrix_sliders())  # type: ignore
                
            else:
                # ===== 单选、量表、下拉题 =====
                option_control_frame = ttk.Frame(dynamic_frame)
                option_control_frame.pack(fill=tk.X, pady=5)
                
                ttk.Label(option_control_frame, text="选项个数：", font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, padx=(0, 5))
                
                state['option_count_var'] = tk.StringVar(value="4")  # type: ignore
                
                def update_option_count(delta):
                    try:
                        current = int(state['option_count_var'].get())  # type: ignore
                        new_count = max(1, current + delta)
                        state['option_count_var'].set(str(new_count))  # type: ignore
                        refresh_sliders()
                    except ValueError:
                        pass
                
                ttk.Button(option_control_frame, text="-", width=3, command=lambda: update_option_count(-1)).pack(side=tk.LEFT, padx=2)
                ttk.Entry(option_control_frame, textvariable=state['option_count_var'], width=5).pack(side=tk.LEFT, padx=2)  # type: ignore
                ttk.Button(option_control_frame, text="+", width=3, command=lambda: update_option_count(1)).pack(side=tk.LEFT, padx=2)
                
                # 分布方式
                ttk.Label(dynamic_frame, text="选择分布方式：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(10, 5), fill=tk.X)
                
                state['distribution_var'] = tk.StringVar(value="random")  # type: ignore
                
                ttk.Radiobutton(dynamic_frame, text="完全随机（每次随机选择）", 
                              variable=state['distribution_var'], value="random",  # type: ignore
                              command=lambda: (state['weight_frame'].pack_forget() if state['weight_frame'] else None)).pack(anchor="w", pady=3, fill=tk.X)  # type: ignore
                ttk.Radiobutton(dynamic_frame, text="自定义权重（使用滑块设置）", 
                              variable=state['distribution_var'], value="custom",  # type: ignore
                              command=lambda: (state['weight_frame'].pack(fill=tk.BOTH, expand=True, pady=5) if state['weight_frame'] else None)).pack(anchor="w", pady=3, fill=tk.X)  # type: ignore
                
                # 权重滑块容器
                state['weight_frame'] = ttk.Frame(dynamic_frame)  # type: ignore
                
                ttk.Label(state['weight_frame'], text="选项权重（0-10）：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(5, 3), fill=tk.X)  # type: ignore
                
                sliders_frame = ttk.Frame(state['weight_frame'])  # type: ignore
                sliders_frame.pack(fill=tk.BOTH, expand=True, pady=5)
                
                state['current_sliders'] = []  # type: ignore
                
                def refresh_sliders():
                    for child in sliders_frame.winfo_children():
                        child.destroy()
                    state['current_sliders'] = []  # type: ignore
                    
                    try:
                        option_count = int(state['option_count_var'].get())  # type: ignore
                    except:
                        option_count = 4
                    
                    for i in range(option_count):
                        row_frame = ttk.Frame(sliders_frame)
                        row_frame.pack(fill=tk.X, pady=3, padx=(10, 10))
                        row_frame.columnconfigure(1, weight=1)
                        
                        var = tk.DoubleVar(value=1.0)
                        
                        label_text = ttk.Label(row_frame, text=f"选项 {i+1}:", width=8, anchor="w")
                        label_text.grid(row=0, column=0, sticky="w")
                        
                        slider = ttk.Scale(row_frame, from_=0, to=10, variable=var, orient=tk.HORIZONTAL)
                        slider.grid(row=0, column=1, sticky="ew", padx=5)
                        
                        weight_label = ttk.Label(row_frame, text="1.0", width=6, anchor="e")
                        weight_label.grid(row=0, column=2, sticky="e")
                        
                        def update_label(v=var, l=weight_label):
                            l.config(text=f"{v.get():.1f}")
                        
                        var.trace_add("write", lambda *args, v=var, l=weight_label: update_label(v, l))
                        state['current_sliders'].append(var)  # type: ignore
                
                refresh_sliders()
                state['option_count_var'].trace_add("write", lambda *args: refresh_sliders())  # type: ignore
        
        # 初始化动态内容
        question_type_combo.bind("<<ComboboxSelected>>", refresh_dynamic_content)
        refresh_dynamic_content()
        
        # ===== 按钮区域 =====
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=15, pady=(0, 15), side=tk.BOTTOM)
        
        def save_question():
            try:
                raw_q_type = LABEL_TO_TYPE.get(question_type_var.get(), "single")
                is_location_question = bool(state.get('is_location')) if raw_q_type in ("text", "location") else False
                if raw_q_type == "location":
                    is_location_question = True
                q_type = "text" if raw_q_type == "location" else raw_q_type
                option_count = 0
                distribution_mode = "equal"
                custom_weights = None
                probabilities = None
                texts_values = None
                rows = 1
                
                if q_type == "text":
                    raw = "||".join([var.get().strip() for var in state['answer_vars']]) if state['answer_vars'] else ""
                    if not raw:
                        self._log_popup_error("错误", "请填写至少一个答案")
                        return
                    parts = re.split(r"[|\n,]", raw)
                    texts_values = [item.strip() for item in parts if item.strip()]
                    if not texts_values:
                        self._log_popup_error("错误", "请填写至少一个答案")
                        return
                    option_count = len(texts_values)
                    probabilities = normalize_probabilities([1.0] * option_count)
                elif q_type == "multi_text":
                    group_vars = state.get('multi_group_vars') or []
                    groups: List[str] = []
                    for vars_row in group_vars:
                        if not vars_row:
                            continue
                        parts = [var.get().strip() for var in vars_row]
                        if all(not part for part in parts):
                            continue
                        normalized_parts = [part if part else DEFAULT_FILL_TEXT for part in parts]
                        groups.append(MULTI_TEXT_DELIMITER.join(normalized_parts))
                    if not groups:
                        self._log_popup_error("错误", "请至少填写一组答案")
                        return
                    texts_values = groups
                    option_count = len(groups)
                    probabilities = normalize_probabilities([1.0] * option_count)
                elif q_type == "multiple":
                    option_count = int(state['option_count_var'].get())  # type: ignore
                    if option_count <= 0:
                        raise ValueError("选项个数必须为正整数")
                    if state['multiple_random_var'].get():  # type: ignore
                        probabilities = -1
                        distribution_mode = "random"
                    else:
                        if state['current_sliders']:  # type: ignore
                            custom_weights = [var.get() for var in state['current_sliders']]  # type: ignore
                        else:
                            custom_weights = [50.0] * option_count
                        probabilities = custom_weights
                        distribution_mode = "custom"
                elif q_type == "matrix":
                    option_count = int(state['option_count_var'].get())  # type: ignore
                    rows = int(state['matrix_rows_var'].get())  # type: ignore
                    if option_count <= 0 or rows <= 0:
                        raise ValueError("选项数和行数必须为正整数")
                    distribution_mode = state['distribution_var'].get()  # type: ignore
                    if distribution_mode == "random":
                        probabilities = -1
                    elif distribution_mode == "equal":
                        probabilities = normalize_probabilities([1.0] * option_count)
                    else:
                        raw = state['weights_var'].get().strip()  # type: ignore
                        if not raw:
                            custom_weights = [1.0] * option_count
                        else:
                            parts = raw.replace("：", ":").replace("，", ",").replace(" ", "").split(":" if ":" in raw else ",")
                            custom_weights = [float(item.strip()) for item in parts if item.strip()]
                            if len(custom_weights) != option_count:
                                raise ValueError(f"权重数量({len(custom_weights)})与选项数({option_count})不匹配")
                        probabilities = normalize_probabilities(custom_weights)
                else:
                    option_count = int(state['option_count_var'].get())  # type: ignore
                    if option_count <= 0:
                        raise ValueError("选项个数必须为正整数")
                    distribution_mode = state['distribution_var'].get()  # type: ignore
                    if distribution_mode == "random":
                        probabilities = -1
                    elif distribution_mode == "equal":
                        probabilities = normalize_probabilities([1.0] * option_count)
                    else:
                        if state['current_sliders']:  # type: ignore
                            custom_weights = [var.get() for var in state['current_sliders']]  # type: ignore
                        else:
                            custom_weights = [1.0] * option_count
                        probabilities = normalize_probabilities(custom_weights)
                
                entry = QuestionEntry(
                    question_type=q_type,
                    probabilities=probabilities,
                    texts=texts_values,
                    rows=rows,
                    option_count=option_count,
                    distribution_mode=distribution_mode,
                    custom_weights=custom_weights,
                    option_fill_texts=None,
                    fillable_option_indices=None,
                    is_location=is_location_question,
                )
                logging.info(f"[Action Log] Adding question type={q_type} options={option_count} mode={distribution_mode}")
                self.question_entries.append(entry)
                self._refresh_tree()
                _cleanup()
                logging.info(f"[Action Log] Question added successfully (total={len(self.question_entries)})")
            except ValueError as exc:
                self._log_popup_error("参数错误", str(exc))
        
        ttk.Button(button_frame, text="保存", command=save_question).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="取消", command=_cleanup).pack(side=tk.RIGHT, padx=5)


    def _get_selected_indices(self):
        return sorted([item['index'] for item in self.question_items if item['var'].get()])

    def toggle_select_all(self):
        """全选/取消全选所有题目"""
        select_all = self.select_all_var.get()
        for item in self.question_items:
            item['var'].set(select_all)

    def remove_question(self):
        selected_indices = self._get_selected_indices()
        if not selected_indices:
            logging.info("[Action Log] Remove question requested without selection")
            self._log_popup_info("提示", "请先勾选要删除的题目")
            return
        
        # 添加确认弹窗
        count = len(selected_indices)
        logging.info(f"[Action Log] Remove question requested for {count} items")
        confirm_msg = f"确定要删除选中的 {count} 道题目吗？\n\n此操作无法撤销！"
        if not self._log_popup_confirm("确认删除", confirm_msg, icon='warning'):
            logging.info("[Action Log] Remove question canceled by user")
            return
        
        for index in sorted(selected_indices, reverse=True):
            if 0 <= index < len(self.question_entries):
                self.question_entries.pop(index)
        logging.info(f"[Action Log] Removed {count} question(s)")
        
        self._refresh_tree()

    def edit_question(self):
        selected_indices = self._get_selected_indices()
        if not selected_indices:
            logging.info("[Action Log] Edit question requested without selection")
            self._log_popup_info("提示", "请先勾选要编辑的题目")
            return
        if len(selected_indices) > 1:
            logging.info("[Action Log] Edit question requested with multiple selections")
            self._log_popup_info("提示", "一次只能编辑一道题目")
            return
        index = selected_indices[0]
        if 0 <= index < len(self.question_entries):
            logging.info(f"[Action Log] Opening edit dialog for question #{index+1}")
            entry = self.question_entries[index]
            self._show_edit_dialog(entry, index)

    def _refresh_tree(self):
        # 清除所有旧项目
        for item in self.question_items:
            item['frame'].destroy()
        self.question_items.clear()
        
        # 为每个问题创建一行
        for idx, entry in enumerate(self.question_entries):
            # 创建一行的Frame
            row_frame = ttk.Frame(self.questions_frame)
            row_frame.pack(fill=tk.X, pady=2, padx=5)
            
            # 复选框（使用ttk样式）
            var = tk.BooleanVar(value=False)
            var.trace_add("write", lambda *args: self._update_select_all_state())
            cb = ttk.Checkbutton(row_frame, variable=var)
            cb.pack(side=tk.LEFT, padx=(0, 10))
            
            # 题型标签
            type_label = ttk.Label(row_frame, text=_get_entry_type_label(entry), 
                                  width=12, anchor="w")
            type_label.pack(side=tk.LEFT, padx=(0, 10))
            
            # 配置信息标签
            detail_label = ttk.Label(row_frame, text=entry.summary(), anchor="w")
            detail_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            # 保存引用
            self.question_items.append({
                'frame': row_frame,
                'checkbox': cb,
                'var': var,
                'index': idx
            })
        
        # 标记配置有改动
        self._mark_config_changed()
        
        # 更新全选复选框状态
        self._update_select_all_state()

        self._safe_preview_button_config(text=self._get_preview_button_label())
        self._auto_update_full_simulation_times()

    def _update_select_all_state(self):
        """根据单个复选框状态更新全选复选框"""
        if not self.question_items:
            self.select_all_var.set(False)
            return
        
        all_selected = all(item['var'].get() for item in self.question_items)
        self.select_all_var.set(all_selected)

    def _show_edit_dialog(self, entry, index):
        edit_win = tk.Toplevel(self.root)
        edit_win.title(f"编辑第 {index + 1} 题")
        edit_win.geometry("550x550")
        edit_win.transient(self.root)
        edit_win.grab_set()

        scroll_container = ttk.Frame(edit_win)

        canvas = tk.Canvas(scroll_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        frame = ttk.Frame(canvas, padding=20)
        canvas_window = canvas.create_window((0, 0), window=frame, anchor="nw")

        def _on_frame_configure(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event=None):
            if event and event.width > 1:
                canvas.itemconfigure(canvas_window, width=event.width)

        frame.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        def _close_edit_window():
            canvas.unbind_all("<MouseWheel>")
            try:
                edit_win.grab_release()
            except Exception:
                pass
            edit_win.destroy()

        edit_win.protocol("WM_DELETE_WINDOW", _close_edit_window)

        # 底部固定按钮，避免滚动内容较多时保存按钮溢出窗口
        action_bar = ttk.Frame(edit_win, padding=(16, 12))
        action_bar.pack(side=tk.BOTTOM, fill=tk.X)

        save_button = ttk.Button(action_bar, text="保存", width=12, command=lambda: None)
        save_button.pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Button(action_bar, text="取消", width=10, command=_close_edit_window).pack(side=tk.RIGHT, padx=(0, 6))

        def _set_save_command(handler: Callable[[], None]):
            save_button.configure(command=handler)

        scroll_container.pack(fill=tk.BOTH, expand=True)

        question_identifier = entry.question_num or f"第 {index + 1} 题"
        overview_card = tk.Frame(frame, bg="#f6f8ff", highlightbackground="#cfd8ff", highlightthickness=1, bd=0)
        overview_card.pack(fill=tk.X, pady=(0, 15))
        overview_inner = tk.Frame(overview_card, bg="#f6f8ff")
        overview_inner.pack(fill=tk.X, padx=14, pady=10)

        tk.Label(
            overview_inner,
            text=f"正在编辑：{question_identifier}",
            font=("TkDefaultFont", 11, "bold"),
            fg="#1a237e",
            bg="#f6f8ff"
        ).pack(anchor="w", fill=tk.X)

        summary_line = entry.summary()
        tk.Label(
            overview_inner,
            text=summary_line,
            fg="#455a64",
            bg="#f6f8ff",
            wraplength=420,
            justify="left"
        ).pack(anchor="w", pady=(4, 2), fill=tk.X)

        readable_type = _get_entry_type_label(entry)
        mode_map = {
            "random": "完全随机",
            "equal": "平均分配",
            "custom": "自定义配比",
        }
        mode_label = mode_map.get(entry.distribution_mode, "平均分配")
        tk.Label(
            overview_inner,
            text=f"题型：{readable_type} | 当前策略：{mode_label}",
            fg="#546e7a",
            bg="#f6f8ff"
        ).pack(anchor="w", fill=tk.X)

        chip_frame = tk.Frame(overview_inner, bg="#f6f8ff")
        chip_frame.pack(anchor="w", pady=(6, 0))
        ttk.Label(
            chip_frame,
            text=f"选项数：{entry.option_count}",
        ).pack(side=tk.LEFT, padx=(0, 6))
        fillable_count = len(entry.fillable_option_indices or [])
        filled_values = len([text for text in (entry.option_fill_texts or []) if text])
        if fillable_count:
            tk.Label(
                chip_frame,
                text=f"含 {fillable_count} 个附加填空",
                bg="#e3f2fd",
                fg="#0d47a1",
                font=("TkDefaultFont", 9),
                padx=8,
                pady=2
            ).pack(side=tk.LEFT, padx=(0, 6))
        if filled_values:
            tk.Label(
                chip_frame,
                text=f"{filled_values} 个附加内容已设置",
                bg="#ede7f6",
                fg="#4527a0",
                font=("TkDefaultFont", 9),
                padx=8,
                pady=2
            ).pack(side=tk.LEFT)

        helper_text = self._get_edit_dialog_hint(entry)
        if helper_text:
            helper_box = tk.Frame(frame, bg="#fff8e1", highlightbackground="#ffe082", highlightthickness=1)
            helper_box.pack(fill=tk.X, pady=(0, 12))
            tk.Label(
                helper_box,
                text=helper_text,
                bg="#fff8e1",
                fg="#864a00",
                wraplength=460,
                justify="left",
                padx=12,
                pady=8
            ).pack(fill=tk.X)

        fillable_indices = set(entry.fillable_option_indices or [])
        existing_fill_values = entry.option_fill_texts or []

        def _should_show_inline_fill(option_index: int) -> bool:
            if fillable_indices and option_index in fillable_indices:
                return True
            if option_index < len(existing_fill_values) and existing_fill_values[option_index]:
                return True
            return False

        def _attach_inline_fill_input(row_frame: ttk.Frame, option_index: int, inline_vars: List[Optional[tk.StringVar]]):
            if not inline_vars or option_index < 0 or option_index >= len(inline_vars):
                return
            if not _should_show_inline_fill(option_index):
                return
            inline_row = ttk.Frame(row_frame)
            inline_row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(2, 4))
            ttk.Label(inline_row, text="附加填空：").pack(side=tk.LEFT)
            initial_text = ""
            if option_index < len(existing_fill_values) and existing_fill_values[option_index]:
                initial_text = existing_fill_values[option_index] or ""
            var = tk.StringVar(value=initial_text)
            entry_widget = ttk.Entry(inline_row, textvariable=var, width=32)
            entry_widget.pack(side=tk.LEFT, padx=(6, 6), fill=tk.X, expand=True)
            ttk.Label(inline_row, text="留空将自动填“无”", foreground="gray").pack(side=tk.LEFT)
            inline_vars[option_index] = var

        def _collect_inline_fill_values(inline_vars: List[Optional[tk.StringVar]], option_total: int) -> Optional[List[Optional[str]]]:
            if not inline_vars:
                return None
            existing = list(existing_fill_values)
            if len(existing) < option_total:
                existing.extend([None] * (option_total - len(existing)))
            collected: List[Optional[str]] = []
            has_value = False
            for idx in range(option_total):
                var = inline_vars[idx] if idx < len(inline_vars) else None
                if var is None:
                    value = existing[idx] if idx < len(existing) else None
                    if value:
                        has_value = True
                    collected.append(value)
                    continue
                value = var.get().strip()
                if value:
                    collected.append(value)
                    has_value = True
                elif (fillable_indices and idx in fillable_indices) or (idx < len(existing) and existing[idx]):
                    collected.append(DEFAULT_FILL_TEXT)
                    has_value = True
                else:
                    collected.append(None)
            return collected if has_value else None

        ttk.Label(frame, text=f"题型: {_get_entry_type_label(entry)}",
                 font=("TkDefaultFont", 10, "bold")).pack(pady=(0, 20))
        
        if entry.question_type == "text":
            ttk.Label(frame, text="填空答案列表：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=5, fill=tk.X)
            
            answers_frame = ttk.Frame(frame)
            answers_frame.pack(fill=tk.BOTH, expand=True, pady=10)
            
            canvas = tk.Canvas(answers_frame, height=200)
            scrollbar = ttk.Scrollbar(answers_frame, orient="vertical", command=canvas.yview)
            scrollable_frame = ttk.Frame(canvas)
            
            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )
            
            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
            
            answer_vars = []
            
            def add_answer_field(initial_value=""):
                row_frame = ttk.Frame(scrollable_frame)
                row_frame.pack(fill=tk.X, pady=5, padx=5)
                
                ttk.Label(row_frame, text=f"答案{len(answer_vars)+1}:", width=8).pack(side=tk.LEFT)
                
                var = tk.StringVar(value=initial_value)
                entry_widget = ttk.Entry(row_frame, textvariable=var, width=40)
                entry_widget.pack(side=tk.LEFT, padx=5)
                
                def remove_field():
                    row_frame.destroy()
                    answer_vars.remove(var)
                    update_labels()
                
                if len(answer_vars) > 0:
                    ttk.Button(row_frame, text="✖", width=3, command=remove_field).pack(side=tk.LEFT)
                
                answer_vars.append(var)
                return var
            
            def update_labels():
                for i, child in enumerate(scrollable_frame.winfo_children()):
                    label = child.winfo_children()[0]
                    if isinstance(label, ttk.Label):
                        label.config(text=f"答案{i+1}:")
            
            for answer in (entry.texts if entry.texts else ["默认答案"]):
                add_answer_field(answer)
            
            canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            
            add_btn_frame = ttk.Frame(frame)
            add_btn_frame.pack(fill=tk.X, pady=(5, 0))
            ttk.Button(add_btn_frame, text="+ 添加答案", command=lambda: add_answer_field()).pack(anchor="w", fill=tk.X)
            
            def save_text():
                values = [var.get().strip() for var in answer_vars if var.get().strip()]
                if not values:
                    self._log_popup_error("错误", "请填写至少一个答案")
                    return
                entry.texts = values
                entry.probabilities = normalize_probabilities([1.0] * len(values))
                entry.option_count = len(values)
                self._refresh_tree()
                _close_edit_window()
                logging.info(f"[Action Log] Saved text answers for question #{index+1}")
            
            _set_save_command(save_text)
            
        elif entry.question_type == "multi_text":
            inferred_count = 2
            existing_groups = entry.texts or []
            for sample in existing_groups:
                try:
                    text_value = str(sample)
                except Exception:
                    text_value = ""
                if MULTI_TEXT_DELIMITER in text_value:
                    parts_len = len([p for p in text_value.split(MULTI_TEXT_DELIMITER)])
                    inferred_count = max(inferred_count, parts_len)
                elif text_value.strip():
                    inferred_count = max(inferred_count, 1)
            inferred_count = max(2, inferred_count)

            control_frame = ttk.Frame(frame)
            control_frame.pack(fill=tk.X, pady=5)
            ttk.Label(control_frame, text="填空项数量：", font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, padx=(0, 5))
            blank_count_var = tk.StringVar(value=str(inferred_count))

            def _get_blank_count() -> int:
                try:
                    return max(2, int(blank_count_var.get()))
                except Exception:
                    return 2

            def _set_blank_count(delta: int):
                count = _get_blank_count()
                blank_count_var.set(str(max(2, count + delta)))

            ttk.Button(control_frame, text="−", width=3, command=lambda: _set_blank_count(-1)).pack(side=tk.LEFT, padx=2)
            ttk.Entry(control_frame, textvariable=blank_count_var, width=5).pack(side=tk.LEFT, padx=2)
            ttk.Button(control_frame, text="+", width=3, command=lambda: _set_blank_count(1)).pack(side=tk.LEFT, padx=2)

            ttk.Label(
                frame,
                text="请按填空顺序填写答案，保存后会随机选择一组填写到输入框。",
                foreground="gray",
                wraplength=420,
            ).pack(anchor="w", pady=(6, 6), fill=tk.X)

            groups_frame = ttk.Frame(frame)
            groups_frame.pack(fill=tk.BOTH, expand=True, pady=5)
            group_vars: List[List[tk.StringVar]] = []

            def add_group(initial_values: Optional[List[str]] = None):
                row_frame = ttk.Frame(groups_frame)
                row_frame.pack(fill=tk.X, pady=3, padx=5)
                row_frame.grid_columnconfigure(1, weight=1)

                ttk.Label(row_frame, text=f"组{len(group_vars)+1}:", width=6).grid(row=0, column=0, sticky="nw")

                # 创建输入框容器，使用 grid 布局让输入框自动换行，并为删除按钮预留空间
                inputs_frame = ttk.Frame(row_frame)
                inputs_frame.grid(row=0, column=1, sticky="ew")

                vars_row: List[tk.StringVar] = []
                blank_count = _get_blank_count()
                max_per_row = 4  # 每行最多显示4个输入框
                for col in range(max_per_row):
                    inputs_frame.grid_columnconfigure(col, weight=1)
                for j in range(blank_count):
                    init_val = ""
                    if initial_values and j < len(initial_values):
                        init_val = initial_values[j]
                    var = tk.StringVar(value=init_val)
                    entry_widget = ttk.Entry(inputs_frame, textvariable=var, width=12)
                    grid_row = j // max_per_row
                    grid_col = j % max_per_row
                    entry_widget.grid(row=grid_row, column=grid_col, padx=(0, 6), pady=2, sticky="ew")
                    vars_row.append(var)

                def remove_group():
                    row_frame.destroy()
                    try:
                        group_vars.remove(vars_row)
                    except ValueError:
                        pass
                    update_group_labels()

                if len(group_vars) > 0:
                    ttk.Button(row_frame, text="删除", width=5, command=remove_group).grid(row=0, column=2, padx=(6, 0), sticky="ne")

                group_vars.append(vars_row)
                return vars_row

            def update_group_labels():
                for i, child in enumerate(groups_frame.winfo_children()):
                    if child.winfo_children():
                        label_widget = child.winfo_children()[0]
                        if isinstance(label_widget, ttk.Label):
                            label_widget.config(text=f"组{i+1}:")

            def refresh_groups():
                blank_count = _get_blank_count()
                existing_values: List[List[str]] = []
                for vars_row in group_vars:
                    existing_values.append([v.get() for v in vars_row])
                for child in groups_frame.winfo_children():
                    child.destroy()
                group_vars.clear()
                if existing_values:
                    for values in existing_values:
                        padded = list(values) + [""] * max(0, blank_count - len(values))
                        add_group(padded[:blank_count])
                else:
                    add_group()

            if existing_groups:
                for text_value in existing_groups:
                    try:
                        raw = str(text_value)
                    except Exception:
                        raw = ""
                    parts = [p.strip() for p in raw.split(MULTI_TEXT_DELIMITER)] if raw else []
                    if not parts:
                        parts = ["" for _ in range(_get_blank_count())]
                    add_group(parts)
            else:
                add_group()

            blank_count_var.trace_add("write", lambda *args: refresh_groups())

            add_btn_frame = ttk.Frame(frame)
            add_btn_frame.pack(fill=tk.X, pady=(5, 0))
            ttk.Button(add_btn_frame, text="+ 添加答案组", command=lambda: add_group()).pack(anchor="w")

            def save_multi_text():
                groups: List[str] = []
                for vars_row in group_vars:
                    parts = [var.get().strip() for var in vars_row]
                    if all(not part for part in parts):
                        continue
                    normalized_parts = [part if part else DEFAULT_FILL_TEXT for part in parts]
                    groups.append(MULTI_TEXT_DELIMITER.join(normalized_parts))
                if not groups:
                    self._log_popup_error("错误", "请至少填写一组答案")
                    return
                entry.texts = groups
                entry.probabilities = normalize_probabilities([1.0] * len(groups))
                entry.option_count = len(groups)
                entry.is_location = False
                self._refresh_tree()
                _close_edit_window()
                logging.info(f"[Action Log] Saved multi text answers for question #{index+1}")

            _set_save_command(save_multi_text)

        elif entry.question_type == "multiple":
            ttk.Label(frame, text=f"多选题（{entry.option_count}个选项）").pack(anchor="w", pady=5, fill=tk.X)
            ttk.Label(frame, text="设置每个选项的选中概率（0-100%）：",
                     foreground="gray").pack(anchor="w", pady=5, fill=tk.X)

            sliders = []
            slider_frame = ttk.Frame(frame)
            slider_frame.pack(fill=tk.BOTH, expand=True, pady=10)

            canvas = tk.Canvas(slider_frame, height=250, highlightthickness=0)
            scrollbar = ttk.Scrollbar(slider_frame, orient="vertical", command=canvas.yview)
            scrollable_frame = ttk.Frame(canvas)

            canvas_win = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

            def _on_scroll_config(event):
                canvas.configure(scrollregion=canvas.bbox("all"))
            scrollable_frame.bind("<Configure>", _on_scroll_config)

            def _on_canvas_config(event):
                canvas.itemconfigure(canvas_win, width=event.width)
            canvas.bind("<Configure>", _on_canvas_config)

            canvas.configure(yscrollcommand=scrollbar.set)

            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            current_probs = entry.custom_weights if entry.custom_weights else [50.0] * entry.option_count
            # 获取选项文本（如果有的话）
            option_texts = entry.texts if entry.texts else []
            inline_fill_vars: List[Optional[tk.StringVar]] = [None] * entry.option_count

            for i in range(entry.option_count):
                row_frame = ttk.Frame(scrollable_frame)
                row_frame.pack(fill=tk.X, pady=4, padx=(10, 20))
                row_frame.columnconfigure(1, weight=1)

                # 显示选项文本（如果有的话）- 使用两行布局
                option_text = option_texts[i] if i < len(option_texts) and option_texts[i] else ""
                text_label = ttk.Label(row_frame, text=f"选项 {i+1}: {option_text}" if option_text else f"选项 {i+1}", 
                                       anchor="w", wraplength=450)
                text_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 2))
                
                # 第二行：滑块和百分比
                var = tk.DoubleVar(value=current_probs[i] if i < len(current_probs) else 50.0)
                slider = ttk.Scale(row_frame, from_=0, to=100, variable=var, orient=tk.HORIZONTAL)
                slider.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(20, 5))

                label = ttk.Label(row_frame, text=f"{int(var.get())}%", width=6, anchor="e")
                label.grid(row=1, column=2, sticky="e")

                var.trace_add("write", lambda *args, l=label, v=var: l.config(text=f"{int(v.get())}%"))
                sliders.append(var)
                _attach_inline_fill_input(row_frame, i, inline_fill_vars)

            def save_multiple():
                probs = [var.get() for var in sliders]
                entry.custom_weights = probs
                entry.probabilities = probs
                entry.distribution_mode = "custom"
                entry.option_fill_texts = _collect_inline_fill_values(inline_fill_vars, entry.option_count)
                self._refresh_tree()
                _close_edit_window()
                logging.info(f"[Action Log] Saved custom weights for question #{index+1}")
            
            _set_save_command(save_multiple)
            
        else:
            effective_option_count = engine._infer_option_count(entry)
            if effective_option_count <= 0:
                effective_option_count = max(1, entry.option_count or 1)
            if effective_option_count != entry.option_count:
                entry.option_count = effective_option_count

            ttk.Label(frame, text=f"选项数: {effective_option_count}").pack(anchor="w", pady=5, fill=tk.X)
            if entry.question_type == "matrix":
                ttk.Label(frame, text=f"矩阵行数: {entry.rows}").pack(anchor="w", pady=5, fill=tk.X)

            ttk.Label(frame, text="选择分布方式：").pack(anchor="w", pady=10, fill=tk.X)

            dist_var = tk.StringVar(value=entry.distribution_mode if entry.distribution_mode in ["random", "custom"] else "random")

            weight_frame = ttk.Frame(frame)
            slider_vars: List[tk.DoubleVar] = []
            option_texts = entry.texts if entry.texts else []
            initial_weights = entry.custom_weights if entry.custom_weights else [1.0] * effective_option_count
            slider_hint = "拖动滑块设置每个选项的权重（0-10）：" if entry.question_type != "matrix" else "拖动滑块设置每列被选中的优先级（0-10）："
            ttk.Label(weight_frame, text=slider_hint, foreground="gray").pack(anchor="w", pady=(5, 8), fill=tk.X)

            sliders_container = ttk.Frame(weight_frame)
            sliders_container.pack(fill=tk.BOTH, expand=True)
            inline_fill_vars: List[Optional[tk.StringVar]] = [None] * entry.option_count if entry.question_type in ("single", "dropdown") else []

            for i in range(effective_option_count):
                row_frame = ttk.Frame(sliders_container)
                row_frame.pack(fill=tk.X, pady=4, padx=(10, 20))
                row_frame.columnconfigure(1, weight=1)

                option_text = option_texts[i] if i < len(option_texts) and option_texts[i] else ""
                text_value = f"选项 {i+1}: {option_text}" if option_text else f"选项 {i+1}"
                ttk.Label(row_frame, text=text_value, anchor="w", wraplength=420).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 2))

                initial_value = float(initial_weights[i]) if i < len(initial_weights) else 1.0
                var = tk.DoubleVar(value=initial_value)
                slider = ttk.Scale(row_frame, from_=0, to=10, variable=var, orient=tk.HORIZONTAL)
                slider.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(20, 5))

                value_label = ttk.Label(row_frame, text=f"{initial_value:.1f}", width=6, anchor="e")
                value_label.grid(row=1, column=2, sticky="e")

                def _update_value_label(v=var, lbl=value_label):
                    lbl.config(text=f"{v.get():.1f}")

                var.trace_add("write", lambda *args, v=var, lbl=value_label: _update_value_label(v, lbl))
                slider_vars.append(var)
                _attach_inline_fill_input(row_frame, i, inline_fill_vars)

            ttk.Radiobutton(frame, text="完全随机", variable=dist_var, value="random").pack(anchor="w", fill=tk.X)
            ttk.Radiobutton(frame, text="自定义权重（使用滑块设置）", variable=dist_var, value="custom").pack(anchor="w", fill=tk.X)

            def save_other():
                mode = dist_var.get()
                if mode == "random":
                    entry.probabilities = -1
                    entry.custom_weights = None
                elif mode == "equal":
                    weights = [1.0] * entry.option_count
                    entry.custom_weights = weights
                    entry.probabilities = normalize_probabilities(weights)
                else:
                    weights = [var.get() for var in slider_vars]
                    if not weights or all(w <= 0 for w in weights):
                        self._log_popup_error("错误", "至少需要一个选项的权重大于 0")
                        return
                    entry.custom_weights = weights
                    entry.probabilities = normalize_probabilities(weights)
                    entry.option_count = max(entry.option_count, len(weights))

                entry.distribution_mode = mode
                entry.option_fill_texts = _collect_inline_fill_values(inline_fill_vars, entry.option_count)
                self._refresh_tree()
                _close_edit_window()
                logging.info(f"[Action Log] Saved distribution settings ({mode}) for question #{index+1}")
            _set_save_command(save_other)

            def _toggle_weight_frame(*_):
                if dist_var.get() == "custom":
                    if not weight_frame.winfo_manager():
                        weight_frame.pack(fill=tk.BOTH, expand=True, pady=10)
                else:
                    weight_frame.pack_forget()

            dist_var.trace_add("write", _toggle_weight_frame)
            _toggle_weight_frame()


    def _get_edit_dialog_hint(self, entry: QuestionEntry) -> str:
        """根据题型返回更口语化的编辑提示。"""
        if entry.is_location:
            return "可直接列出多个地名，格式为“地名”或“地名|经度,纬度”；未提供经纬度时，系统会自动尝试解析。"
        hints = {
            "text": "可输入多个候选答案，执行时会在这些答案中轮换填写；建议保留能覆盖不同语气的内容。",
            "multi_text": "多项填空题每一行是一组完整答案，系统会按顺序填入多个输入框。",
            "multiple": "右侧滑块控制每个选项的命中率，百分比越高越常被勾选；可结合下方“选项填写”设置附加文本。",
            "single": "可在“完全随机”和“自定义权重”之间切换，想突出热门选项时直接把滑块调高即可。",
            "dropdown": "与单选题相同，若问卷含“其他”选项，可在底部“附加填空”区写入默认内容。",
            "scale": "量表题通常代表分值，若希望答案集中在某个区间，请在自定义配比里提升对应滑块。",
            "matrix": "矩阵题的滑块作用于每一列，值越大越倾向被选，适合模拟“偏好列”的情况。",
        }
        return hints.get(entry.question_type, "根据右侧控件调整答案或权重，保存后可在列表中随时再次修改。")


    def upload_qrcode(self):
        """上传二维码图片并解析链接"""
        file_path = filedialog.askopenfilename(
            title="选择问卷二维码图片",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.webp *.bmp *.gif")
            ]
        )
        
        if not file_path:
            return
        logging.info(f"[Action Log] QR code image selected: {file_path}")
        
        try:
            # 解码二维码
            url = decode_qrcode(file_path)
            
            if url:
                self.url_var.set(url)
                self._log_popup_info("成功", f"二维码解析成功！\n链接: {url}")
            else:
                self._log_popup_error("错误", "未能从图片中识别出二维码，请确认图片包含有效的二维码。")
        except Exception as e:
            logging.error(f"二维码解析失败: {str(e)}")
            self._log_popup_error("错误", f"二维码解析失败: {str(e)}")

    def preview_survey(self):
        url_value = self.url_var.get().strip()
        if not url_value:
            self._log_popup_error("错误", "请先填写问卷链接")
            return
        if not self._validate_wjx_url(url_value):
            return
        logging.info(f"[Action Log] Preview survey requested for URL: {url_value}")
        if self.question_entries:
            choice = self._show_preview_choice_dialog(len(self.question_entries))
            if choice is None:
                return
            if choice == "preview":
                self._start_preview_only(url_value, preserve_existing=True, show_preview_window=False)
                return
            self._start_auto_config(url_value, preserve_existing=True)
            return
        self._start_auto_config(url_value, preserve_existing=False)

    def _show_preview_choice_dialog(self, configured_count: int) -> Optional[str]:
        dialog = tk.Toplevel(self.root)
        dialog.title("请选择操作")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        message = (
            f"当前已配置 {configured_count} 道题目。\n"
            f"请选择要执行的操作：\n\n"
            f"继续自动配置：解析问卷并根据必要题目追加/覆盖。\n"
            f"仅预览：仅查看问卷结构或快速演示填写。"
        )
        ttk.Label(frame, text=message, justify="left", wraplength=360).pack(pady=(0, 12))

        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X)

        result = tk.StringVar(value="")

        def choose(value: str):
            result.set(value)
            dialog.destroy()

        ttk.Button(button_frame, text="仅预览", command=lambda: choose("preview")).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="继续自动配置", command=lambda: choose("auto")).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=lambda: choose("")).pack(side=tk.RIGHT, padx=5)

        def on_close():
            result.set("")
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", on_close)
        dialog.update_idletasks()
        win_w = dialog.winfo_width()
        win_h = dialog.winfo_height()
        screen_w = dialog.winfo_screenwidth()
        screen_h = dialog.winfo_screenheight()
        x = max(0, (screen_w - win_w) // 2)
        y = max(0, (screen_h - win_h) // 2)
        dialog.geometry(f"+{x}+{y}")

        self.root.wait_window(dialog)
        value = result.get()
        return value if value else None

    def _start_preview_only(self, url_value: str, preserve_existing: bool, *, show_preview_window: bool = True):
        def _launch_after_parse(info):
            if show_preview_window:
                self._show_preview_window(deepcopy(info), preserve_existing=preserve_existing)
            else:
                logging.info(f"[Action Log] Preview-only mode: parsed {len(info)} questions, launching browser preview")
            self._safe_preview_button_config(state=tk.DISABLED, text="正在预览...")
            Thread(target=self._launch_preview_browser_session, args=(url_value,), daemon=True).start()

        if self._last_parsed_url == url_value and self._last_questions_info:
            _launch_after_parse(self._last_questions_info)
            return
        self._start_survey_parsing(
            url_value,
            lambda info: _launch_after_parse(info),
            restore_button_state=False,
        )

    def _start_auto_config(self, url_value: str, preserve_existing: bool):
        if self._last_parsed_url == url_value and self._last_questions_info:
            self._show_preview_window(deepcopy(self._last_questions_info), preserve_existing=preserve_existing)
            return
        self._start_survey_parsing(
            url_value,
            lambda info: self._show_preview_window(info, preserve_existing=preserve_existing),
        )

    def _detect_not_open_reason_from_text(self, text: str, *, has_questions: bool = False) -> Optional[str]:
        """在页面文本中检测未开放/已结束提示，返回错误原因。"""
        if not text:
            return None
        try:
            normalized = "".join(str(text).split())
        except Exception:
            normalized = ""
        if not normalized:
            return None

        lowered = normalized.lower()
        not_started_keywords = getattr(timed_mode, "_NOT_STARTED_KEYWORDS", ())
        ended_keywords = getattr(timed_mode, "_ENDED_KEYWORDS", ())

        for kw in not_started_keywords:
            if not kw:
                continue
            if kw in normalized or kw.lower() in lowered:
                if has_questions:
                    continue
                return "检测到问卷尚未开放（未到开始时间/定时开放），请在开放后再试。"

        patterns = (
            r"将于\d{4}[-/年]\d{1,2}[-/月]\d{1,2}.*开放",
            r"将于\d{1,2}[:点]\d{1,2}开放",
            r"距离开始还有",
        )
        for pat in patterns:
            if re.search(pat, normalized):
                if has_questions:
                    continue
                return "检测到问卷尚未开放（存在倒计时/定时开放提示），请在开放后再试。"

        for kw in ended_keywords:
            if not kw:
                continue
            if kw in normalized or kw.lower() in lowered:
                if has_questions:
                    continue
                return "检测到问卷已结束或关闭，自动配置无法解析。"

        return None

    def _detect_not_open_via_driver(self, driver) -> Optional[str]:
        """使用浏览器实例检测未开放状态，返回错误原因。"""
        try:
            ready, not_started, ended, _ = timed_mode._page_status(driver)
        except Exception:
            return None
        if not_started and not ready:
            return "检测到问卷尚未开放（未到开始时间/定时开放），请在开放后再试。"
        if ended:
            return "检测到问卷已结束或关闭，自动配置无法解析。"
        return None

    def _start_survey_parsing(self, url_value: str, result_handler: Callable[[List[Dict[str, Any]]], None], restore_button_state: bool = True):
        self._last_survey_title = None
        self._safe_preview_button_config(state=tk.DISABLED, text="加载中...")
        progress_win = tk.Toplevel(self.root)
        progress_win.title("正在加载问卷")
        progress_win.geometry("400x200")
        progress_win.resizable(False, False)
        progress_win.transient(self.root)
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

        ttk.Label(frame, text="正在加载问卷...", font=("", 11, "bold")).pack(pady=(0, 15))
        status_label = ttk.Label(frame, text="初始化浏览器...", foreground="gray")
        status_label.pack(pady=(0, 10))

        progress_bar = ttk.Progressbar(frame, mode="determinate", maximum=100, length=300)
        progress_bar.pack(fill=tk.X, pady=5)

        percentage_label = ttk.Label(frame, text="0%", font=("", 10, "bold"))
        percentage_label.pack(pady=(5, 0))

        progress_win.update()

        preview_thread = Thread(
            target=self._parse_and_show_survey,
            args=(url_value, progress_win, status_label, progress_bar, percentage_label, result_handler, restore_button_state),
            daemon=True,
        )
        preview_thread.start()

    def _parse_and_show_survey(
        self,
        survey_url,
        progress_win=None,
        status_label=None,
        progress_bar=None,
        percentage_label=None,
        result_handler: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
        restore_button_state: bool = True,
    ):
        driver = None
        try:
            # 更新进度函数
            def update_progress(percent, status_text):
                if progress_bar is not None:
                    self.root.after(0, lambda p=percent, pb=progress_bar: pb.config(value=p) if pb else None)
                if percentage_label is not None:
                    self.root.after(0, lambda p=percent, pl=percentage_label: pl.config(text=f"{int(p)}%") if pl else None)
                if status_label is not None:
                    self.root.after(0, lambda s=status_text, sl=status_label: sl.config(text=s) if sl else None)
            
            # 更新状态
            update_progress(5, "开始准备解析...")
            
            questions_info = self._try_parse_survey_via_http(survey_url, update_progress)
            if questions_info is not None:
                print(f"已成功通过 HTTP 解析，共 {len(questions_info)} 题")
                update_progress(100, "解析完成，正在显示结果...")
                time.sleep(0.5)
                if progress_win:
                    self.root.after(0, lambda: progress_win.destroy())
                self._cache_parsed_survey(questions_info, survey_url)
                handler = result_handler or (lambda data: self._show_preview_window(data))
                info_copy = deepcopy(questions_info)
                self.root.after(0, lambda data=info_copy: handler(data))
                if restore_button_state:
                    self.root.after(0, lambda: self._safe_preview_button_config(state=tk.NORMAL, text=self._get_preview_button_label()))
                return
            
            update_progress(30, "HTTP 解析失败，准备启动浏览器...")
            
            print(f"正在加载问卷: {survey_url}")
            ua_value, ua_label = self._pick_random_user_agent()
            driver, browser_name = create_playwright_driver(headless=True, user_agent=ua_value)
            if ua_label:
                logging.info(f"[Action Log] 解析使用随机 UA：{ua_label}")
            logging.info(f"Fallback 到 {browser_name.capitalize()} BrowserDriver 解析问卷")
            
            update_progress(45, "正在打开问卷页面...")
            
            driver.get(survey_url)
            time.sleep(3)
            
            page_source = ""
            try:
                page_source = driver.page_source
            except Exception:
                page_source = ""
            extracted_title = _extract_survey_title_from_html(page_source) if page_source else None
            if extracted_title:
                self._last_survey_title = extracted_title
            else:
                try:
                    driver_title = driver.title
                except Exception:
                    driver_title = ""
                cleaned = _normalize_html_text(driver_title)
                cleaned = re.sub(r"(?:[-|]\s*)?(?:问卷星.*)$", "", cleaned, flags=re.IGNORECASE).strip(" -_|")
                if cleaned:
                    self._last_survey_title = cleaned

            not_open_reason = self._detect_not_open_reason_from_text(page_source) if page_source else None
            if not not_open_reason:
                not_open_reason = self._detect_not_open_via_driver(driver)
            if not_open_reason:
                raise SurveyNotOpenError(not_open_reason)
            
            update_progress(60, "正在解析题目结构...")
            
            print("开始解析题目...")
            questions_info = []
            questions_per_page = detect(driver)
            total_questions = sum(questions_per_page)
            print(f"检测到 {len(questions_per_page)} 页，总题数: {total_questions}")
            current_question_num = 0
            
            for page_idx, questions_count in enumerate(questions_per_page, 1):
                print(f"正在解析第{page_idx}页，共{questions_count}题")
                
                for _ in range(questions_count):
                    current_question_num += 1
                    
                    # 计算进度百分比（30%~95%）
                    progress_percent = 30 + (current_question_num / max(total_questions, 1)) * 65
                    update_progress(progress_percent, f"正在解析第 {page_idx}/{len(questions_per_page)} 页 (已解析 {current_question_num}/{total_questions} 题)...")
                    
                    try:
                        question_div = driver.find_element(By.CSS_SELECTOR, f"#div{current_question_num}")
                        question_type = question_div.get_attribute("type")
                        
                        title_text = ""
                        try:
                            title_element = question_div.find_element(By.CSS_SELECTOR, ".topichtml")
                            title_text = title_element.text.strip()
                        except:
                            try:
                                title_element = question_div.find_element(By.CSS_SELECTOR, ".field-label")
                                full_text = title_element.text.strip()
                                lines = [line.strip() for line in full_text.split('\n') if line.strip()]
                                for line in lines:
                                    if not line.startswith('*') and not line.endswith('.'):
                                        title_text = line
                                        break
                            except:
                                pass
                        
                        if not title_text:
                            title_text = f"第{current_question_num}题"
                        
                        is_location_question = question_type in ("1", "2") and _driver_question_is_location(question_div)
                        option_count = 0
                        matrix_rows = 0
                        option_texts = []  # 存储选项文本
                        
                        if question_type in ("3", "4", "5", "7"):
                            if question_type == "7":
                                try:
                                    options = driver.find_elements(By.XPATH, f"//*[@id='q{current_question_num}']/option")
                                    option_count = max(0, len(options) - 1)
                                    # 提取下拉题选项文本
                                    option_texts = [opt.text.strip() for opt in options[1:]] if len(options) > 1 else []
                                except:
                                    option_count = 0
                                    option_texts = []
                            else:
                                try:
                                    options = driver.find_elements(By.XPATH, f'//*[@id="div{current_question_num}"]/div[2]/div')
                                    option_count = len(options)
                                    # 提取单选/多选/量表题选项文本
                                    option_texts = [opt.text.strip() for opt in options]
                                except:
                                    try:
                                        options = driver.find_elements(By.XPATH, f'//*[@id="div{current_question_num}"]//div[@class="ui-radio"]')
                                        option_count = len(options)
                                        option_texts = [opt.text.strip() for opt in options]
                                    except:
                                        option_count = 0
                                        option_texts = []
                        elif question_type == "6":
                            try:
                                rows = driver.find_elements(By.XPATH, f'//*[@id="divRefTab{current_question_num}"]/tbody/tr')
                                matrix_rows = sum(1 for row in rows if row.get_attribute("rowindex") is not None)
                                columns = driver.find_elements(By.XPATH, f'//*[@id="drv{current_question_num}_1"]/td')
                                option_count = max(0, len(columns) - 1)
                                option_texts = [col.text.strip() for col in columns[1:]] if len(columns) > 1 else []
                            except Exception:
                                matrix_rows = 0
                                option_count = 0
                                option_texts = []

                        option_fillable_indices: List[int] = []
                        if question_type in ("3", "4", "5"):
                            try:
                                option_elements = driver.find_elements(By.XPATH, f'//*[@id="div{current_question_num}"]/div[2]/div')
                            except Exception:
                                option_elements = []
                            if not option_elements:
                                try:
                                    option_elements = driver.find_elements(By.XPATH, f'//*[@id="div{current_question_num}"]//div[@class="ui-radio"]')
                                except Exception:
                                    option_elements = []
                            for idx, opt_element in enumerate(option_elements):
                                if _driver_element_contains_text_input(opt_element):
                                    option_fillable_indices.append(idx)
                            if not option_fillable_indices and option_count > 0 and _driver_question_has_shared_text_input(question_div):
                                option_fillable_indices.append(option_count - 1)
                        elif question_type == "7":
                            try:
                                inputs = question_div.find_elements(By.CSS_SELECTOR, ".ui-other input, .ui-other textarea")
                            except Exception:
                                inputs = []
                            if inputs and option_count > 0:
                                option_fillable_indices.append(option_count - 1)

                        text_input_count = _count_visible_text_inputs_driver(question_div)
                        is_multi_text_question = _should_mark_as_multi_text(
                            question_type, option_count, text_input_count, is_location_question
                        )
                        is_text_like_question = _should_treat_question_as_text_like(
                            question_type, option_count, text_input_count
                        )
                        type_name = self._get_question_type_name(
                            question_type,
                            is_location=is_location_question,
                            is_multi_text=is_multi_text_question,
                            is_text_like=is_text_like_question,
                        )

                        has_jump_attr = False
                        try:
                            has_jump_attr = str(question_div.get_attribute("hasjump") or "").strip() == "1"
                        except Exception:
                            has_jump_attr = False
                        jump_rules: List[Dict[str, Any]] = []
                        try:
                            input_elements = question_div.find_elements(
                                By.CSS_SELECTOR,
                                "input[type='radio'], input[type='checkbox']"
                            )
                        except Exception:
                            input_elements = []
                        for idx, input_el in enumerate(input_elements):
                            try:
                                jumpto_raw = input_el.get_attribute("jumpto") or input_el.get_attribute("data-jumpto")
                            except Exception:
                                jumpto_raw = None
                            if not jumpto_raw:
                                continue
                            raw_text = str(jumpto_raw).strip()
                            jumpto_num: Optional[int] = None
                            if raw_text.isdigit():
                                jumpto_num = int(raw_text)
                            else:
                                match = re.search(r"(\d+)", raw_text)
                                if match:
                                    try:
                                        jumpto_num = int(match.group(1))
                                    except Exception:
                                        jumpto_num = None
                            if jumpto_num:
                                jump_rules.append({
                                    "option_index": idx,
                                    "jumpto": jumpto_num,
                                    "option_text": option_texts[idx] if idx < len(option_texts) else None,
                                })
                        has_jump = has_jump_attr or bool(jump_rules)

                        questions_info.append({
                            "num": current_question_num,
                            "title": title_text,
                            "type": type_name,
                            "type_code": question_type,
                            "options": option_count,
                            "rows": matrix_rows,
                            "page": page_idx,
                            "option_texts": option_texts,
                            "fillable_options": option_fillable_indices,
                            "is_location": is_location_question,
                            "text_inputs": text_input_count,
                            "is_multi_text": is_multi_text_question,
                            "is_text_like": is_text_like_question,
                            "has_jump": has_jump,
                            "jump_rules": jump_rules,
                        })
                        print(f"  ✓ 第{current_question_num}题: {type_name} - {title_text[:30]}")
                    except Exception as e:
                        print(f"  ✗ 第{current_question_num}题解析失败: {e}")
                        traceback.print_exc()
                        questions_info.append({
                            "num": current_question_num,
                            "title": "[解析失败]",
                            "type": "未知",
                            "type_code": "0",
                            "options": 0,
                            "rows": 0,
                            "page": page_idx,
                            "option_texts": [],
                            "is_location": False,
                        })
                
                if page_idx < len(questions_per_page):
                    try:
                        clicked = _click_next_page_button(driver)
                        if clicked:
                            time.sleep(1.5)
                            print(f"已翻页到第{page_idx + 1}页")
                        else:
                            print("翻页失败: 未找到“下一页”按钮")
                    except Exception as e:
                        print(f"翻页失败: {e}")
            
            print(f"解析完成，共{len(questions_info)}题")
            update_progress(100, "解析完成，正在显示结果...")
            time.sleep(0.5)
            if progress_win:
                self.root.after(0, lambda: progress_win.destroy())
            self._cache_parsed_survey(questions_info, survey_url)
            handler = result_handler or (lambda data: self._show_preview_window(data))
            info_copy = deepcopy(questions_info)
            self.root.after(0, lambda data=info_copy: handler(data))
            if restore_button_state:
                self.root.after(0, lambda: self._safe_preview_button_config(state=tk.NORMAL, text=self._get_preview_button_label()))
            
        except SurveyNotOpenError as e:
            message = str(e) or "检测到问卷尚未开放，自动配置暂时无法解析。"
            logging.warning(f"[Action Log] Survey not open: {message}")
            if progress_win:
                self.root.after(0, lambda: progress_win.destroy())
            self.root.after(0, lambda msg=message: self._log_popup_error("问卷未开放", msg))
            self.root.after(0, lambda: self._safe_preview_button_config(state=tk.NORMAL, text=self._get_preview_button_label()))
        except Exception as e:
            error_str = str(e)
            error_lower = error_str.lower()
            if "chrome" in error_lower or "edge" in error_lower:
                if "binary" in error_lower or "not found" in error_lower or "browser" in error_lower:
                    error_msg = (
                        "未找到可用浏览器 (Edge/Chrome)\n\n"
                        "请确认系统已安装 Microsoft Edge 或 Google Chrome"
                    )
                elif "BrowserDriver" in error_lower or "driver" in error_lower:
                    error_msg = (
                        f"浏览器驱动初始化失败: {error_str}\n\n"
                        "建议:\n"
                        "1. Edge/Chrome 是否已安装并可独立启动\n"
                        "2. 运行一次 `playwright install chromium` 确保内置浏览器可用\n"
                        "3. 检查安全软件是否拦截浏览器自动化进程"
                    )
                else:
                    error_msg = f"浏览器启动失败: {error_str}\n\n请检查 Edge/Chrome 是否能够手动打开问卷"
            else:
                error_msg = (
                    f"解析问卷失败: {error_str}\n\n"
                    "请检查:\n"
                    "1. 问卷链接是否正确\n"
                    "2. 网络连接是否正常\n"
                    "3. 问卷是否需要额外登录"
                )
            print(f"错误: {error_msg}")
            clean_error_msg = error_msg.replace("\n", " ")
            logging.error(f"[Action Log] Preview parsing failed: {clean_error_msg}")
            traceback.print_exc()
            if progress_win:
                self.root.after(0, lambda: progress_win.destroy())
            self.root.after(0, lambda: self._log_popup_error("错误", error_msg))
            self.root.after(0, lambda: self._safe_preview_button_config(state=tk.NORMAL, text=self._get_preview_button_label()))
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass

    def _try_parse_survey_via_http(self, survey_url: str, progress_callback=None) -> Optional[List[Dict[str, Any]]]:
        if not requests or not BeautifulSoup:
            logging.debug("HTTP 解析依赖缺失，跳过无浏览器解析")
            return None
        try:
            if progress_callback:
                progress_callback(10, "正在获取问卷页面...")
            headers = dict(DEFAULT_HTTP_HEADERS)
            ua_value, _ = self._pick_random_user_agent()
            if ua_value:
                headers["User-Agent"] = ua_value
            headers["Referer"] = survey_url
            response = requests.get(survey_url, headers=headers, timeout=15)
            response.raise_for_status()
            html = response.text
            self._last_survey_title = _extract_survey_title_from_html(html)
            if progress_callback:
                progress_callback(25, "正在解析题目结构...")
            questions_info = parse_survey_questions_from_html(html)
            not_open_reason = self._detect_not_open_reason_from_text(html, has_questions=bool(questions_info))
            if not_open_reason:
                raise SurveyNotOpenError(not_open_reason)
            if not questions_info:
                logging.info("HTTP 解析未能找到任何题目，将回退到浏览器模式")
                return None
            for question in questions_info:
                is_location = bool(question.get("is_location"))
                is_multi_text = bool(question.get("is_multi_text"))
                is_text_like = bool(question.get("is_text_like"))
                question["type"] = self._get_question_type_name(
                    question.get("type_code"),
                    is_location=is_location,
                    is_multi_text=is_multi_text,
                    is_text_like=is_text_like,
                )
            return questions_info
        except Exception as exc:
            logging.debug(f"HTTP 解析问卷失败: {exc}")
            return None

    def _cache_parsed_survey(self, questions_info: List[Dict[str, Any]], url: str):
        """缓存解析结果以便预览和配置向导复用"""
        self._last_parsed_url = url
        self._last_questions_info = deepcopy(questions_info)
        self._auto_update_full_simulation_times()

    def _launch_preview_browser_session(self, url: str):
        driver = None
        try:
            configure_probabilities(self.question_entries)
        except ValueError as exc:
            error_text = str(exc)
            self.root.after(0, lambda msg=error_text: self._log_popup_error("预览失败", msg))
            self.root.after(
                0,
                lambda: self._safe_preview_button_config(state=tk.NORMAL, text=self._get_preview_button_label()),
            )
            return

        try:
            ua_value, ua_label = self._pick_random_user_agent()
            driver, browser_name = create_playwright_driver(headless=False, user_agent=ua_value)
            if ua_label:
                logging.info(f"[Action Log] 预览使用随机 UA：{ua_label}")
            driver.maximize_window()
            driver.get(url)

            logging.info(f"[Action Log] Launching preview session for {url}")
            if self._last_questions_info:
                self._fill_preview_answers(driver, self._last_questions_info)
            self.root.after(0, lambda: self._log_popup_info(
                "预览完成",
                "浏览器已自动填写一份，请在窗口中确认是否满意，提交/关闭请手动操作。"
            ))

        except Exception as exc:
            error_msg = f"预览演示失败: {exc}"
            logging.error(error_msg)
            traceback.print_exc()
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            self.root.after(0, lambda: self._log_popup_error("预览失败", error_msg))
        finally:
            self.root.after(0, lambda: self._safe_preview_button_config(state=tk.NORMAL, text=self._get_preview_button_label()))

    def _fill_preview_answers(self, driver: BrowserDriver, questions_info: List[Dict[str, Any]]) -> None:
        vacancy_idx = single_idx = droplist_idx = multiple_idx = matrix_idx = scale_idx = 0
        for q in questions_info:
            q_type = q.get("type_code")
            current = q.get("num")
            if not current or not q_type:
                continue
            try:
                if q_type in ("1", "2"):
                    vacant(driver, current, vacancy_idx)
                    vacancy_idx += 1
                elif q_type == "3":
                    single(driver, current, single_idx)
                    single_idx += 1
                elif q_type == "4":
                    multiple(driver, current, multiple_idx)
                    multiple_idx += 1
                elif q_type == "5":
                    scale(driver, current, scale_idx)
                    scale_idx += 1
                elif q_type == "6":
                    matrix_idx = matrix(driver, current, matrix_idx)
                elif q_type == "7":
                    droplist(driver, current, droplist_idx)
                    droplist_idx += 1
            except Exception as exc:
                logging.debug(f"预览题目 {current} ({q_type}) 填写失败: {exc}")

    def _safe_preview_button_config(self, **kwargs) -> None:
        if self.preview_button:
            self.preview_button.config(**kwargs)

    def _get_preview_button_label(self) -> str:
        return "预览 / 继续配置" if self.question_entries else "⚡ 自动配置问卷"

    def _get_question_type_name(
        self,
        type_code,
        *,
        is_location: bool = False,
        is_multi_text: bool = False,
        is_text_like: bool = False,
    ):
        normalized_type = _normalize_question_type_code(type_code)
        if is_location:
            return LOCATION_QUESTION_LABEL
        if is_multi_text:
            return "多项填空题"
        type_map = {
            "1": "填空题(单行)",
            "2": "填空题(多行)",
            "3": "单选题",
            "4": "多选题",
            "5": "量表题",
            "6": "矩阵题",
            "7": "下拉题",
            "8": "滑块题",
            "11": "排序题"
        }
        if normalized_type in type_map:
            return type_map[normalized_type]
        if is_text_like:
            return "填空题"
        return f"未知类型({type_code})"

    def _show_preview_window(self, questions_info, preserve_existing: bool = False):
        preview_win = tk.Toplevel(self.root)
        preview_win.title("问卷预览")
        preview_win.geometry("760x500")
        preview_win.minsize(640, 420)
        self._center_child_window(preview_win)
        
        frame = ttk.Frame(preview_win, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text=f"问卷共 {len(questions_info)} 题", font=("TkDefaultFont", 11, "bold")).pack(pady=(0, 10))
        
        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        columns = ("num", "title", "type", "details", "page")
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=14)
        tree.heading("num", text="题号")
        tree.heading("title", text="题目标题")
        tree.heading("type", text="题型")
        tree.heading("details", text="详情")
        tree.heading("page", text="页码")
        
        tree.column("num", width=60, anchor="center")
        tree.column("title", width=340, anchor="w")
        tree.column("type", width=110, anchor="center")
        tree.column("details", width=150, anchor="center")
        tree.column("page", width=70, anchor="center")
        
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        for q in questions_info:
            details = ""
            if q["type_code"] == "6":
                details = f"{q['rows']}行 × {q['options']}列"
            elif q["type_code"] in ("3", "4", "5", "7"):
                details = f"{q['options']}个选项"
            elif q["type_code"] in ("1", "2"):
                details = "文本输入"
            elif q["type_code"] == "8":
                details = "滑块(1-100)"
            elif q["type_code"] == "11":
                details = "拖拽排序"
            
            tree.insert("", "end", values=(
                q["num"],
                q["title"][:80] + "..." if len(q["title"]) > 80 else q["title"],
                q["type"],
                details,
                f"第{q['page']}页"
            ))
        
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=(10, 0))
        
        wizard_btn = ttk.Button(
            btn_frame,
            text="开始配置题目",
            command=lambda: self._start_config_wizard(questions_info, preview_win, preserve_existing=preserve_existing),
        )
        wizard_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(btn_frame, text="关闭", command=preview_win.destroy).pack(side=tk.LEFT, padx=5)

    def _normalize_question_identifier(self, value: Optional[Union[str, int]]) -> Optional[str]:
        if value is None:
            return None
        try:
            normalized = str(value).strip()
            return normalized or None
        except Exception:
            return None

    def _find_entry_index_by_question(self, question_id: Optional[str]) -> Optional[int]:
        if not question_id:
            return None
        for idx, entry in enumerate(self.question_entries):
            if entry.question_num == question_id:
                return idx
        return None

    def _handle_auto_config_entry(
        self,
        entry: QuestionEntry,
        question_meta: Optional[Dict[str, Any]] = None,
        *,
        overwrite_existing: Optional[bool] = None,
    ):
        question_id = None
        question_title = ""
        if question_meta:
            question_id = self._normalize_question_identifier(question_meta.get("num"))
            question_title = question_meta.get("title", "")
        entry.question_num = question_id
        conflict_index = self._find_entry_index_by_question(question_id)
        if conflict_index is not None:
            if overwrite_existing is True:
                previous_entry = deepcopy(self.question_entries[conflict_index])
                self.question_entries[conflict_index] = entry
                self._wizard_commit_log.append(
                    {"action": "replace", "index": conflict_index, "previous": previous_entry}
                )
                logging.info(f"[Action Log] Wizard overwrote configuration for question {question_id or '?'}")
                return
            if overwrite_existing is False:
                self._wizard_commit_log.append({"action": "skip"})
                logging.info(f"[Action Log] Wizard kept existing configuration for question {question_id or '?'}")
                return
            question_label = f"第 {question_id} 题" if question_id else "该题目"
            title_suffix = f"「{question_title[:40]}{'...' if len(question_title) > 40 else ''}」" if question_title else ""
            message = (
                f"{question_label}{title_suffix} 已存在配置。\n\n"
                f"选择“是”：覆盖已有配置并使用最新设置。\n"
                f"选择“否”：跳过本题保留原配置。"
            )
            overwrite = self._log_popup_confirm("检测到重复配置", message, icon="question")
            if overwrite:
                previous_entry = deepcopy(self.question_entries[conflict_index])
                self.question_entries[conflict_index] = entry
                self._wizard_commit_log.append(
                    {"action": "replace", "index": conflict_index, "previous": previous_entry}
                )
                logging.info(f"[Action Log] Wizard overwrote configuration for question {question_id or '?'}")
            else:
                self._wizard_commit_log.append({"action": "skip"})
                logging.info(f"[Action Log] Wizard skipped configuring question {question_id or '?'}")
            return
        self.question_entries.append(entry)
        self._wizard_commit_log.append({"action": "append", "index": len(self.question_entries) - 1})
        logging.info(f"[Action Log] Wizard stored configuration (total={len(self.question_entries)})")

    def _revert_last_wizard_action(self):
        if not self._wizard_commit_log:
            return
        action = self._wizard_commit_log.pop()
        action_type = action.get("action")
        if action_type == "append":
            idx = action.get("index")
            if idx is not None and 0 <= idx < len(self.question_entries):
                self.question_entries.pop(idx)
        elif action_type == "replace":
            idx = action.get("index")
            previous_entry = action.get("previous")
            if (
                idx is not None
                and previous_entry is not None
                and 0 <= idx < len(self.question_entries)
                and isinstance(previous_entry, QuestionEntry)
            ):
                self.question_entries[idx] = previous_entry
        elif action_type == "skip":
            pass

    def _annotate_jump_impacts_for_questions(self, questions_info: List[Dict[str, Any]]) -> None:
        """
        根据每题的跳题规则，为中间被跳过的题打上“skipped_by”标记，方便在向导界面提示。
        例如：第2题某选项 jumpto=4，则第3题会记录为被 2→4 这一跳路径覆盖。
        """
        if not questions_info:
            return
        num_to_index: Dict[int, int] = {}
        for idx, q in enumerate(questions_info):
            num = _safe_positive_int(q.get("num"))
            if num is None:
                continue
            num_to_index[num] = idx
            q["skipped_by"] = []
        for q in questions_info:
            jump_rules = q.get("jump_rules") or []
            if not jump_rules:
                continue
            src_num = _safe_positive_int(q.get("num"))
            if src_num is None:
                continue
            for rule in jump_rules:
                target = rule.get("jumpto")
                tgt_num = _safe_positive_int(target)
                if tgt_num is None:
                    continue
                if tgt_num <= src_num:
                    continue
                for skipped_num in range(src_num + 1, tgt_num):
                    idx = num_to_index.get(skipped_num)
                    if idx is None:
                        continue
                    impact = {
                        "from": src_num,
                        "to": tgt_num,
                        "option_index": rule.get("option_index"),
                        "option_text": rule.get("option_text"),
                    }
                    questions_info[idx].setdefault("skipped_by", []).append(impact)

    def _start_config_wizard(self, questions_info, preview_win, preserve_existing: bool = False):
        preview_win.destroy()
        if not preserve_existing:
            self.question_entries.clear()
        self._wizard_history = []
        self._wizard_commit_log = []
        try:
            self._annotate_jump_impacts_for_questions(questions_info)
        except Exception as exc:
            logging.debug("annotate jump impacts failed: %s", exc)
        self._show_wizard_for_question(questions_info, 0)

    def _get_wizard_hint_text(self, type_code: str, *, is_location: bool = False, is_multi_text: bool = False) -> str:
        """为不同题型提供面向用户的操作提示文本。"""
        if is_location:
            return "建议准备多个真实地名，可选用“地名|经度,纬度”格式显式指定坐标；若只填地名，系统会自动尝试地理编码。"
        if is_multi_text:
            return "多项填空题会按“答案组”逐项填写到同题的多个输入框中；可添加多组用于随机选择。"
        hints = {
            "1": "填空题建议准备 2~5 个真实可用的答案，点击“添加答案”即可增加内容，后续执行会在这些答案中随机选择。",
            "2": "多行填空通常用于意见反馈，可输入若干句式或话术，系统会自动随机抽取并填写。",
            "3": "单选题可直接选择完全随机，也可以切换到自定义权重，将高频选项的滑块调高即可。",
            "4": "多选题常需要控制命中率，拖动每个选项的百分比滑块即可直观设置被勾选的概率。",
            "5": "量表题本质类似单选题，若某些分值更常见，可使用自定义权重突出这些分值。",
            "6": "矩阵题按“行 × 列”处理，每列的权重决定更倾向选择哪一列，可先整体确定策略再微调滑块。",
            "7": "下拉题与单选题一致：先选择随机/自定义，再视需要为特定选项设置额外填空内容。",
        }
        default = "确认题干后，根据下方输入区域逐步设置答案或权重，完成后点击“下一题”即可保存。"
        return hints.get(type_code, default)

    def _generate_random_chinese_name(self) -> str:
        return _generate_random_chinese_name_value()

    def _generate_random_mobile(self) -> str:
        return _generate_random_mobile_value()

    def _generate_random_generic_text(self) -> str:
        return _generate_random_generic_text_value()

    def _resolve_dynamic_text_token(self, token: Any) -> str:
        return _resolve_dynamic_text_token_value(token)

    def _show_wizard_for_question(self, questions_info, current_index):
        existing_wizard = getattr(self, "_wizard_window", None)

        if current_index >= len(questions_info):
            self._refresh_tree()
            logging.info(f"[Action Log] Wizard finished with {len(self.question_entries)} configured questions")
            self._log_popup_info(
                "完成",
                f"配置完成！\n\n已配置 {len(self.question_entries)} 道题目。\n可在下方题目列表中查看和编辑。"
            )
            self._wizard_history.clear()
            self._wizard_commit_log.clear()
            if existing_wizard and getattr(existing_wizard, "winfo_exists", lambda: False)():
                try:
                    existing_wizard.unbind_all("<MouseWheel>")
                except Exception:
                    pass
                try:
                    existing_wizard.grab_release()
                except Exception:
                    pass
                try:
                    existing_wizard.destroy()
                except Exception:
                    pass
                self._wizard_window = None
            return
        
        q = questions_info[current_index]
        question_id = self._normalize_question_identifier(q.get("num"))
        existing_entry: Optional[QuestionEntry] = None
        existing_entry_index = self._find_entry_index_by_question(question_id)
        if existing_entry_index is not None:
            try:
                existing_entry = self.question_entries[existing_entry_index]
            except Exception:
                existing_entry = None
        type_code = q["type_code"]
        is_location_question = bool(q.get("is_location"))
        normalized_type_code = _normalize_question_type_code(type_code)
        is_multi_text_question = bool(q.get("is_multi_text")) and not is_location_question
        is_text_like_question = (
            bool(q.get("is_text_like"))
            or normalized_type_code in ("1", "2")
            or is_location_question
        )
        detected_fillable_indices = q.get('fillable_options') or []
        jump_rules = q.get("jump_rules") or []
        has_jump_logic = bool(q.get("has_jump") or jump_rules)
        skipped_by_info = q.get("skipped_by") or []

        if type_code in ("8", "11"):
            self._show_wizard_for_question(questions_info, current_index + 1)
            return

        self._wizard_history.append(current_index)

        wizard_win = existing_wizard if existing_wizard and existing_wizard.winfo_exists() else None
        if wizard_win is None:
            wizard_win = tk.Toplevel(self.root)
            wizard_win.geometry("800x600")
            wizard_win.minsize(700, 500)  # 设置最小尺寸，防止窗口过小
            wizard_win.transient(self.root)
            wizard_win.grab_set()
            self._center_child_window(wizard_win)
            self._wizard_window = wizard_win
        else:
            try:
                wizard_win.unbind_all("<MouseWheel>")
            except Exception:
                pass
            for child in wizard_win.winfo_children():
                try:
                    child.destroy()
                except Exception:
                    pass
            try:
                wizard_win.deiconify()
                wizard_win.lift()
                wizard_win.grab_set()
            except Exception:
                pass

        wizard_win.title(f"配置向导 - 第 {current_index + 1}/{len(questions_info)} 题")

        # 创建可滚动的内容区域
        canvas = tk.Canvas(wizard_win, highlightthickness=0)
        scrollbar = ttk.Scrollbar(wizard_win, orient="vertical", command=canvas.yview)
        frame = ttk.Frame(canvas, padding=15)
        
        # 让 frame 的宽度跟随 Canvas 的宽度
        canvas_window = canvas.create_window((0, 0), window=frame, anchor="nw")
        
        def on_frame_configure(event=None):
            # 更新滚动区域
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        def on_canvas_configure(event=None):
            # 让 frame 宽度适应 canvas 宽度
            canvas_width = canvas.winfo_width()
            if canvas_width > 1:  # 避免初始化时宽度为1
                canvas.itemconfig(canvas_window, width=canvas_width)
        
        frame.bind("<Configure>", on_frame_configure)
        canvas.bind("<Configure>", on_canvas_configure)
        
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 绑定鼠标滚轮到 Canvas
        def _on_wizard_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        canvas.bind_all("<MouseWheel>", _on_wizard_mousewheel)
        
        def _release_wizard_grab(event=None):
            try:
                wizard_win.grab_release()
            except tk.TclError:
                pass

        def _restore_wizard_grab(event=None):
            try:
                if wizard_win.state() == "normal":
                    wizard_win.grab_set()
                    wizard_win.lift()
            except tk.TclError:
                pass

        wizard_win.bind("<Unmap>", _release_wizard_grab, add="+")
        wizard_win.bind("<Map>", _restore_wizard_grab, add="+")

        def _cleanup_wizard():
            _release_wizard_grab()
            try:
                wizard_win.unbind_all("<MouseWheel>")
            except tk.TclError:
                pass
            try:
                wizard_win.destroy()
            except tk.TclError:
                pass
            self._wizard_window = None
        
        wizard_win.protocol("WM_DELETE_WINDOW", _cleanup_wizard)
        
        progress_text = f"进度：已完成 {current_index + 1} / {len(questions_info)}"
        ttk.Label(frame, text=progress_text, foreground="gray").pack(anchor="w", fill=tk.X)

        readable_title = q.get("title") or "（该题暂无标题）"

        # 顶部信息卡片，集中展示题目关键属性
        header_card = tk.Frame(frame, bg="#f5f8ff", highlightbackground="#cddcfe", highlightthickness=1, bd=0)
        header_card.pack(fill=tk.X, pady=(10, 12))
        header_inner = tk.Frame(header_card, bg="#f5f8ff")
        header_inner.pack(fill=tk.X, padx=14, pady=10)

        tk.Label(
            header_inner,
            text=f"第 {q['num']} 题",
            font=("TkDefaultFont", 12, "bold"),
            fg="#1a237e",
            bg="#f5f8ff"
        ).pack(anchor="w", fill=tk.X)

        # 使用 wraplength 确保题目标题完整显示并自动换行
        title_label = tk.Label(
            header_inner,
            text=readable_title,
            font=("TkDefaultFont", 10),
            wraplength=680,
            justify="left",
            bg="#f5f8ff"
        )
        title_label.pack(pady=(4, 6), anchor="w", fill=tk.X)

        def update_title_wraplength(event=None):
            available = header_inner.winfo_width() or frame.winfo_width()
            wrap = max(240, available - 40)
            title_label.configure(wraplength=wrap)

        header_inner.bind("<Configure>", update_title_wraplength, add="+")

        meta_tokens = [f"题型：{q['type']}"]
        option_count = q.get("options")
        if option_count:
            unit = "选项" if type_code != "6" else "列"
            meta_tokens.append(f"{option_count} 个{unit}")
        if type_code == "6" and q.get("rows"):
            meta_tokens.append(f"{q['rows']} 行")
        if q.get("page"):
            meta_tokens.append(f"所属页面：第{q['page']}页")
        meta_text = " · ".join(meta_tokens)
        tk.Label(
            header_inner,
            text=meta_text,
            fg="#455a64",
            bg="#f5f8ff",
            justify="left"
        ).pack(anchor="w", fill=tk.X)

        jump_summary_text = ""
        if jump_rules:
            summary_parts: List[str] = []
            for rule in jump_rules:
                opt_idx = rule.get("option_index")
                target = rule.get("jumpto")
                opt_label = rule.get("option_text") or (f"选项{opt_idx + 1}" if opt_idx is not None else "某选项")
                if target:
                    summary_parts.append(f"{opt_label} → 第{target}题")
            if summary_parts:
                jump_summary_text = "；".join(summary_parts[:4])
                if len(summary_parts) > 4:
                    jump_summary_text += f" 等 {len(summary_parts)} 条"

        skipped_summary_text = ""
        if skipped_by_info:
            skipped_parts: List[str] = []
            for info in skipped_by_info:
                src_num = info.get("from")
                dst_num = info.get("to")
                opt_idx = info.get("option_index")
                opt_text = info.get("option_text")
                opt_label = opt_text or (f"选项{opt_idx + 1}" if opt_idx is not None else "某选项")
                if src_num and dst_num:
                    skipped_parts.append(f"第{src_num}题 {opt_label} → 第{dst_num}题")
            if skipped_parts:
                skipped_summary_text = "；".join(skipped_parts[:3])
                if len(skipped_parts) > 3:
                    skipped_summary_text += f" 等 {len(skipped_parts)} 条"

        if has_jump_logic and jump_summary_text:
            jump_alert = tk.Frame(frame, bg="#ffebee", highlightbackground="#ef5350", highlightthickness=1)
            jump_alert.pack(fill=tk.X, pady=(6, 4))
            tk.Label(
                jump_alert,
                text=f"⚠ 跳题逻辑：{jump_summary_text}（选择对应选项时，将直接跳过中间题目）",
                bg="#ffebee",
                fg="#b71c1c",
                justify="left",
                wraplength=710,
                padx=12,
                pady=6
            ).pack(fill=tk.X)

        if skipped_summary_text:
            skip_alert = tk.Frame(frame, bg="#e3f2fd", highlightbackground="#64b5f6", highlightthickness=1)
            skip_alert.pack(fill=tk.X, pady=(0, 8))
            tk.Label(
                skip_alert,
                text=f"ℹ 本题在以下路径中会被跳过：{skipped_summary_text}。如果只按这些路径刷卷，本题的配置可以简化。",
                bg="#e3f2fd",
                fg="#0d47a1",
                justify="left",
                wraplength=710,
                padx=12,
                pady=6
            ).pack(fill=tk.X)

        if detected_fillable_indices:
            chip_frame = tk.Frame(header_inner, bg="#f5f8ff")
            chip_frame.pack(anchor="w", pady=(6, 0))
            tk.Label(
                chip_frame,
                text=f"已发现 {len(detected_fillable_indices)} 个选项含附加填空",
                bg="#e3f2fd",
                fg="#0d47a1",
                font=("TkDefaultFont", 9),
                padx=10,
                pady=2
            ).pack(side=tk.LEFT)

        helper_text = self._get_wizard_hint_text(
            type_code,
            is_location=is_location_question,
            is_multi_text=is_multi_text_question,
        )
        if helper_text:
            helper_box = tk.Frame(frame, bg="#fff8e1", highlightbackground="#ffe082", highlightthickness=1)
            helper_box.pack(fill=tk.X, pady=(0, 12))
            tk.Label(
                helper_box,
                text=helper_text,
                bg="#fff8e1",
                fg="#775800",
                justify="left",
                wraplength=710,
                padx=12,
                pady=8
            ).pack(fill=tk.X)
            if detected_fillable_indices:
                tk.Label(
                    helper_box,
                    text="贴士：保留为空时系统会写入“无”，便于顺利提交。",
                    bg="#fff8e1",
                    fg="#946200",
                    justify="left",
                    padx=12
                ).pack(fill=tk.X, pady=(0, 6))

        option_texts_in_question = q.get('option_texts', [])

        def _build_fillable_inputs(
            initial_fill_texts: Optional[List[Optional[str]]] = None,
        ) -> Tuple[List[Optional[tk.StringVar]], Callable[[ttk.Frame, int], None]]:
            option_total = q.get('options') or 0
            valid_indices = {idx for idx in detected_fillable_indices if isinstance(idx, int) and 0 <= idx < option_total}
            if option_total <= 0 or not valid_indices:
                return [], lambda *_: None

            fill_vars: List[Optional[tk.StringVar]] = [None] * option_total

            def attach_inline(parent_frame: ttk.Frame, opt_index: int):
                if opt_index not in valid_indices or opt_index < 0 or opt_index >= option_total:
                    return
                inline_row = ttk.Frame(parent_frame)
                inline_row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(2, 4))
                ttk.Label(inline_row, text="附加填空：").pack(side=tk.LEFT)
                initial_value = ""
                if initial_fill_texts and opt_index < len(initial_fill_texts):
                    initial_value = initial_fill_texts[opt_index] or ""
                var = tk.StringVar(value=initial_value)
                entry_widget = ttk.Entry(inline_row, textvariable=var, width=32)
                entry_widget.pack(side=tk.LEFT, padx=(6, 6), fill=tk.X, expand=True)
                self._bind_ime_candidate_position(entry_widget)
                ttk.Label(inline_row, text='留空将自动填“无”', foreground='gray').pack(side=tk.LEFT)
                fill_vars[opt_index] = var

            return fill_vars, attach_inline

        def _collect_fill_values(fill_vars: List[Optional[tk.StringVar]]) -> Optional[List[Optional[str]]]:
            if not fill_vars:
                return None
            collected: List[Optional[str]] = []
            has_value = False
            for var in fill_vars:
                if var is None:
                    collected.append(None)
                    continue
                value = var.get().strip()
                if value:
                    has_value = True
                    collected.append(value)
                else:
                    has_value = True
                    collected.append(DEFAULT_FILL_TEXT)

            return collected if has_value else None

        config_frame = ttk.Frame(frame)
        config_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        def skip_question():
            self._wizard_commit_log.append({"action": "skip"})
            self._show_wizard_for_question(questions_info, current_index + 1)
        
        if is_multi_text_question:
            blank_count = int(q.get("text_inputs") or 0)
            if blank_count < 2:
                blank_count = 2

            ttk.Label(config_frame, text="多项填空答案组：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=5, fill=tk.X)
            ttk.Label(
                config_frame,
                text=f"本题包含 {blank_count} 个填空项，每一行代表一组完整答案。",
                foreground="gray",
                wraplength=700,
            ).pack(anchor="w", pady=(0, 6), fill=tk.X)

            groups_frame = ttk.Frame(config_frame)
            groups_frame.pack(fill=tk.BOTH, expand=True, pady=6)

            group_vars: List[List[tk.StringVar]] = []

            def add_group(initial_values: Optional[List[str]] = None):
                row_frame = ttk.Frame(groups_frame)
                row_frame.pack(fill=tk.X, pady=3, padx=5)

                # 先添加删除按钮到右边，确保它不被挤出
                def remove_group():
                    row_frame.destroy()
                    try:
                        group_vars.remove(vars_row)
                    except ValueError:
                        pass
                    update_group_labels()

                delete_btn = ttk.Button(row_frame, text="删除", width=5, command=remove_group)
                delete_btn.pack(side=tk.RIGHT, padx=(6, 0), anchor="n")

                label = ttk.Label(row_frame, text=f"组{len(group_vars)+1}:", width=6)
                label.pack(side=tk.LEFT, anchor="n")

                inputs_frame = ttk.Frame(row_frame)
                inputs_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

                vars_row: List[tk.StringVar] = []
                max_per_row = 4
                for j in range(blank_count):
                    init_val = ""
                    if initial_values and j < len(initial_values):
                        init_val = initial_values[j]
                    var = tk.StringVar(value=init_val)
                    entry_widget = ttk.Entry(inputs_frame, textvariable=var, width=10)
                    grid_row = j // max_per_row
                    grid_col = j % max_per_row
                    entry_widget.grid(row=grid_row, column=grid_col, padx=(0, 4), pady=2, sticky="ew")
                    self._bind_ime_candidate_position(entry_widget)
                    vars_row.append(var)

                group_vars.append(vars_row)
                return vars_row

            def update_group_labels():
                for i, child in enumerate(groups_frame.winfo_children()):
                    if child.winfo_children():
                        label_widget = child.winfo_children()[0]
                        if isinstance(label_widget, ttk.Label):
                            label_widget.config(text=f"组{i+1}:")

            add_group()

            add_btn_frame = ttk.Frame(config_frame)
            add_btn_frame.pack(fill=tk.X, pady=(5, 0))
            ttk.Button(add_btn_frame, text="添加答案组", command=lambda: add_group()).pack(anchor="w")

            def save_and_next():
                groups: List[str] = []
                for vars_row in group_vars:
                    parts = [var.get().strip() for var in vars_row]
                    if all(not part for part in parts):
                        continue
                    normalized_parts = [part if part else DEFAULT_FILL_TEXT for part in parts]
                    groups.append(MULTI_TEXT_DELIMITER.join(normalized_parts))
                if not groups:
                    self._log_popup_error("错误", "请至少填写一组答案")
                    return
                entry = QuestionEntry(
                    question_type="multi_text",
                    probabilities=normalize_probabilities([1.0] * len(groups)),
                    texts=groups,
                    rows=1,
                    option_count=len(groups),
                    distribution_mode="equal",
                    custom_weights=None,
                    is_location=False,
                )
                self._handle_auto_config_entry(entry, q, overwrite_existing=True)
                self._show_wizard_for_question(questions_info, current_index + 1)

        elif is_text_like_question:
            answer_header = "位置候选列表：" if is_location_question else "填空答案策略："
            ttk.Label(config_frame, text=answer_header, font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=5, fill=tk.X)

            answer_vars: List[tk.StringVar] = []
            normalized_title = re.sub(r"\s+", "", str(q.get("title") or "").lower())
            name_keywords = ("姓名", "名字", "称呼", "联系人", "收件人", "监护人", "学生", "家长", "name")
            phone_keywords = ("手机号", "手机号码", "电话", "联系电话", "联系方式", "mobile", "phone")
            has_name_hint = any(keyword in normalized_title for keyword in name_keywords)
            has_phone_hint = any(keyword in normalized_title for keyword in phone_keywords)
            allow_random_fill = has_name_hint or has_phone_hint

            mode_var = tk.StringVar(value="custom")

            def add_answer_field(initial_value=""):
                row_frame = ttk.Frame(answers_inner_frame)
                row_frame.pack(fill=tk.X, pady=3, padx=5)

                ttk.Label(row_frame, text=f"答案{len(answer_vars)+1}:", width=8).pack(side=tk.LEFT)

                var = tk.StringVar(value=initial_value)
                entry_widget = ttk.Entry(row_frame, textvariable=var, width=35)
                entry_widget.pack(side=tk.LEFT, padx=5)
                self._bind_ime_candidate_position(entry_widget)

                def remove_field():
                    row_frame.destroy()
                    answer_vars.remove(var)
                    update_labels()

                if len(answer_vars) > 0:
                    ttk.Button(row_frame, text="✖", width=3, command=remove_field).pack(side=tk.LEFT)

                answer_vars.append(var)
                update_labels()
                return var

            def update_labels():
                for i, child in enumerate(answers_inner_frame.winfo_children()):
                    if child.winfo_children():
                        label = child.winfo_children()[0]
                        if isinstance(label, ttk.Label):
                            label.config(text=f"答案{i+1}:")

            def ensure_custom_frame_visibility():
                if mode_var.get() == "custom":
                    answers_inner_frame.pack(fill=tk.BOTH, expand=True, pady=10)
                    add_btn_frame.pack(fill=tk.X, pady=(5, 0))
                else:
                    answers_inner_frame.pack_forget()
                    add_btn_frame.pack_forget()

            def random_token_for_question() -> str:
                if has_name_hint:
                    return "__RANDOM_NAME__"
                if has_phone_hint:
                    return "__RANDOM_MOBILE__"
                return DEFAULT_FILL_TEXT

            mode_frame = ttk.Frame(config_frame)
            mode_frame.pack(fill=tk.X, pady=(0, 6))

            ttk.Radiobutton(
                mode_frame,
                text="每次随机填入" if allow_random_fill else f"填入“{DEFAULT_FILL_TEXT}”",
                variable=mode_var,
                value="random",
                command=ensure_custom_frame_visibility,
            ).pack(side=tk.LEFT, padx=(0, 10))

            ttk.Radiobutton(
                mode_frame,
                text="自定义答案列表",
                variable=mode_var,
                value="custom",
                command=ensure_custom_frame_visibility,
            ).pack(side=tk.LEFT)

            answers_inner_frame = ttk.Frame(config_frame)
            add_btn_frame = ttk.Frame(config_frame)
            add_answer_field("")

            ttk.Button(add_btn_frame, text="+ 添加答案", command=lambda: add_answer_field()).pack(anchor="w")

            if is_location_question:
                ttk.Label(
                    config_frame,
                    text="可填写“地名”或“地名|经度,纬度”，未提供经纬度时系统会尝试自动解析。",
                    foreground="gray"
                ).pack(anchor="w", pady=(4, 0), fill=tk.X)

            ensure_custom_frame_visibility()
            
            def save_and_next():
                if mode_var.get() == "random":
                    values = [random_token_for_question()]
                    probabilities = [1.0]
                else:
                    values = [var.get().strip() for var in answer_vars if var.get().strip()]
                    if not values:
                        self._log_popup_error("错误", "请填写至少一个答案")
                        return
                    probabilities = normalize_probabilities([1.0] * len(values))

                entry = QuestionEntry(
                    question_type="text",
                    probabilities=probabilities,
                    texts=values,
                    rows=1,
                    option_count=len(values),
                    distribution_mode="random" if mode_var.get() == "random" else "equal",
                    custom_weights=None,
                    is_location=bool(q.get("is_location")),
                )
                self._handle_auto_config_entry(entry, q, overwrite_existing=True)
                self._show_wizard_for_question(questions_info, current_index + 1)
        
        elif type_code == "4":
            ttk.Label(config_frame, text=f"多选题（共 {q['options']} 个选项）").pack(anchor="w", pady=5, fill=tk.X)
            ttk.Label(config_frame, text="拖动滑块设置每个选项的选中概率：",
                     foreground="gray").pack(anchor="w", pady=5, fill=tk.X)

            sliders_frame = ttk.Frame(config_frame)
            sliders_frame.pack(fill=tk.BOTH, expand=True, pady=10)

            sliders = []
            existing_prob_weights: Optional[List[float]] = None
            existing_fill_texts: Optional[List[Optional[str]]] = None
            if existing_entry and existing_entry.question_type == "multiple":
                if isinstance(existing_entry.custom_weights, list):
                    existing_prob_weights = existing_entry.custom_weights
                if isinstance(existing_entry.option_fill_texts, list):
                    existing_fill_texts = existing_entry.option_fill_texts

            fill_text_vars, attach_inline_fill = _build_fillable_inputs(existing_fill_texts)
            for i in range(q['options']):
                row_frame = ttk.Frame(sliders_frame)
                row_frame.pack(fill=tk.X, pady=4, padx=(10, 20))
                row_frame.columnconfigure(1, weight=1)

                option_text = ""
                if i < len(q.get('option_texts', [])) and q['option_texts'][i]:
                    option_text = q['option_texts'][i]

                text_label = ttk.Label(row_frame, text=f"选项 {i+1}: {option_text}" if option_text else f"选项 {i+1}",
                                       anchor="w", wraplength=500)
                text_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 2))

                initial_prob = 50.0
                if existing_prob_weights and i < len(existing_prob_weights):
                    try:
                        initial_prob = float(existing_prob_weights[i])
                    except Exception:
                        initial_prob = 50.0
                var = tk.DoubleVar(value=initial_prob)
                slider = ttk.Scale(row_frame, from_=0, to=100, variable=var, orient=tk.HORIZONTAL)
                slider.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(20, 5))

                label = ttk.Label(row_frame, text=f"{int(var.get())}%", width=6, anchor="e")
                label.grid(row=1, column=2, sticky="e")

                var.trace_add("write", lambda *args, l=label, v=var: l.config(text=f"{int(v.get())}%"))
                sliders.append(var)

                attach_inline_fill(row_frame, i)

            def save_and_next():
                probs = [var.get() for var in sliders]
                option_texts_list = q.get('option_texts', [])
                fill_values = _collect_fill_values(fill_text_vars)
                entry = QuestionEntry(
                    question_type="multiple",
                    probabilities=probs,
                    texts=option_texts_list if option_texts_list else None,
                    rows=1,
                    option_count=q['options'],
                    distribution_mode="custom",
                    custom_weights=probs,
                    option_fill_texts=fill_values,
                    fillable_option_indices=detected_fillable_indices if detected_fillable_indices else None
                )
                self._handle_auto_config_entry(entry, q, overwrite_existing=True)
                self._show_wizard_for_question(questions_info, current_index + 1)
        
        else:
            option_text = f"共 {q['options']} 个选项"
            if type_code == "6":
                option_text = f"{q['rows']} 行 × {q['options']} 列"
            ttk.Label(config_frame, text=option_text).pack(anchor="w", pady=10, fill=tk.X)

            if type_code == "6" and q.get('option_texts'):
                ttk.Label(config_frame, text="列标题：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(5, 0), fill=tk.X)
                options_info_text = " | ".join([f"{i+1}: {text[:20]}{'...' if len(text) > 20 else ''}" for i, text in enumerate(q['option_texts'])])
                ttk.Label(config_frame, text=options_info_text, foreground="gray", wraplength=700).pack(anchor="w", pady=(0, 10), fill=tk.X)
            elif q.get('option_texts'):
                ttk.Label(config_frame, text="选项列表：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(5, 0), fill=tk.X)
                options_list_frame = ttk.Frame(config_frame)
                options_list_frame.pack(anchor="w", fill=tk.X, pady=(0, 10), padx=(20, 0))

                max_options_display = min(5, len(q['option_texts']))
                for i in range(max_options_display):
                    option_lbl = ttk.Label(options_list_frame, text=f"  • {q['option_texts'][i]}",
                                          foreground="gray", wraplength=650)
                    option_lbl.pack(anchor="w", fill=tk.X)

                if len(q['option_texts']) > 5:
                    ttk.Label(options_list_frame, text=f"  ... 共 {len(q['option_texts'])} 个选项", foreground="gray").pack(anchor="w", fill=tk.X)

            ttk.Label(config_frame, text="选择分布方式：").pack(anchor="w", pady=10, fill=tk.X)

            initial_mode = "random"
            initial_weights: Optional[List[float]] = None
            existing_fill_texts: Optional[List[Optional[str]]] = None
            if existing_entry:
                if existing_entry.distribution_mode in ("custom", "equal"):
                    initial_mode = "custom"
                else:
                    initial_mode = "random"
                if isinstance(existing_entry.custom_weights, list):
                    initial_weights = existing_entry.custom_weights
                if isinstance(existing_entry.option_fill_texts, list):
                    existing_fill_texts = existing_entry.option_fill_texts
            if initial_weights and len(initial_weights) != q['options']:
                initial_weights = None

            dist_var = tk.StringVar(value=initial_mode)

            weight_frame = ttk.Frame(config_frame)

            ttk.Radiobutton(
                config_frame,
                text="完全随机（每次随机选择）",
                variable=dist_var,
                value="random",
            ).pack(anchor="w", pady=5, fill=tk.X)
            ttk.Radiobutton(
                config_frame,
                text="自定义权重（使用滑块设置）",
                variable=dist_var,
                value="custom",
            ).pack(anchor="w", pady=5, fill=tk.X)

            ttk.Label(weight_frame, text="拖动滑块设置每个选项的权重比例：",
                     foreground="gray").pack(anchor="w", pady=(10, 5), fill=tk.X)

            sliders_weight_frame = ttk.Frame(weight_frame)
            sliders_weight_frame.pack(fill=tk.BOTH, expand=True)

            slider_vars = []
            fill_text_vars: List[Optional[tk.StringVar]] = []
            attach_inline_fill: Callable[[ttk.Frame, int], None] = lambda *_: None
            if type_code in ("3", "7"):
                fill_text_vars, attach_inline_fill = _build_fillable_inputs(existing_fill_texts)
            for i in range(q['options']):
                slider_frame = ttk.Frame(sliders_weight_frame)
                slider_frame.pack(fill=tk.X, pady=4, padx=(10, 20))
                slider_frame.columnconfigure(1, weight=1)

                option_text = ""
                if i < len(q.get('option_texts', [])) and q['option_texts'][i]:
                    option_text = q['option_texts'][i]

                text_label = ttk.Label(slider_frame, text=f"选项 {i+1}: {option_text}" if option_text else f"选项 {i+1}",
                                       anchor="w", wraplength=500)
                text_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 2))

                initial_value = 1.0
                if initial_weights and i < len(initial_weights):
                    try:
                        initial_value = float(initial_weights[i])
                    except Exception:
                        initial_value = 1.0
                var = tk.DoubleVar(value=initial_value)
                slider = ttk.Scale(slider_frame, from_=0, to=10, variable=var, orient=tk.HORIZONTAL)
                slider.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(20, 5))

                value_label = ttk.Label(slider_frame, text=f"{var.get():.1f}", width=6, anchor="e")
                value_label.grid(row=1, column=2, sticky="e")

                def update_label(v=var, l=value_label):
                    l.config(text=f"{v.get():.1f}")

                var.trace_add("write", lambda *args, v=var, l=value_label: update_label(v, l))
                slider_vars.append(var)

                attach_inline_fill(slider_frame, i)

            def save_and_next():
                mode = dist_var.get()
                q_type_map = {"3": "single", "5": "scale", "6": "matrix", "7": "dropdown"}
                q_type = q_type_map.get(type_code, "single")

                if mode == "random":
                    probs = -1
                    weights = None
                elif mode == "equal":
                    weights = [1.0] * q['options']
                    probs = normalize_probabilities(weights)
                else:
                    weights = [var.get() for var in slider_vars]
                    if all(w == 0 for w in weights):
                        self._log_popup_error("错误", "至少要有一个选项的权重大于0")
                        return
                    probs = normalize_probabilities(weights)
                fill_values = _collect_fill_values(fill_text_vars)

                entry = QuestionEntry(
                    question_type=q_type,
                    probabilities=probs,
                    texts=None,
                    rows=q['rows'] if type_code == "6" else 1,
                    option_count=q['options'],
                    distribution_mode=mode,
                    custom_weights=weights,
                    option_fill_texts=fill_values,
                    fillable_option_indices=detected_fillable_indices if detected_fillable_indices else None
                )
                self._handle_auto_config_entry(entry, q, overwrite_existing=True)
                self._show_wizard_for_question(questions_info, current_index + 1)

            def _toggle_weight_frame(*_):
                if dist_var.get() == "custom":
                    if not weight_frame.winfo_manager():
                        weight_frame.pack(fill=tk.BOTH, expand=True, pady=10)
                else:
                    weight_frame.pack_forget()

            dist_var.trace_add("write", _toggle_weight_frame)
            _toggle_weight_frame()
        
        # 按钮区域（固定在窗口底部）- 使用分隔线和更好的布局
        separator = ttk.Separator(wizard_win, orient='horizontal')
        separator.pack(side=tk.BOTTOM, fill=tk.X, before=canvas)
        
        btn_frame = ttk.Frame(wizard_win, padding=(15, 10, 15, 15))
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, before=separator)
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=0)

        nav_frame = ttk.Frame(btn_frame)
        nav_frame.grid(row=0, column=0, sticky="w")
        
        if current_index > 0:
            prev_btn = ttk.Button(
                nav_frame,
                text="← 上一题",
                width=12,
                command=lambda: self._go_back_in_wizard(questions_info, current_index),
            )
            prev_btn.grid(row=0, column=0, padx=(0, 10), pady=2)
        
        skip_btn = ttk.Button(nav_frame, text="跳过本题", width=10, command=skip_question)
        skip_btn.grid(row=0, column=1, padx=8, pady=2)
        
        next_btn = ttk.Button(nav_frame, text="下一题 →", width=12, command=save_and_next)
        next_btn.grid(row=0, column=2, padx=(8, 0), pady=2)
        
        # 右侧取消按钮
        cancel_btn = ttk.Button(btn_frame, text="取消向导", width=12, command=_cleanup_wizard)
        cancel_btn.grid(row=0, column=1, sticky="e", padx=(10, 0), pady=2)

    def _go_back_in_wizard(self, questions_info, current_index):
        if self._wizard_history and self._wizard_history[-1] == current_index:
            self._wizard_history.pop()
        prev_index = 0
        if self._wizard_history:
            prev_index = self._wizard_history.pop()
        self._show_wizard_for_question(questions_info, prev_index)

    def start_run(self):
        url_value = self.url_var.get().strip()
        if not url_value:
            self._log_popup_error("参数错误", "请填写问卷链接")
            return
        if not self._validate_wjx_url(url_value):
            return
        target_value = self.target_var.get().strip()
        full_sim_enabled = bool(self.full_simulation_enabled_var.get())
        timed_mode_enabled = bool(self.timed_mode_enabled_var.get())
        if timed_mode_enabled and full_sim_enabled:
            self._log_popup_error("参数错误", "定时模式与全真模拟不能同时启用")
            return
        if timed_mode_enabled:
            full_sim_enabled = False
        if full_sim_enabled:
            target_value = self.full_sim_target_var.get().strip()
            if not target_value:
                self._log_popup_error("参数错误", "请在全真模拟设置中填写目标份数")
                return
            self.target_var.set(target_value)
        if timed_mode_enabled:
            target_value = "1"
            if self.target_var.get().strip() != "1":
                self.target_var.set("1")
        if not target_value:
            self._log_popup_error("参数错误", "目标份数不能为空")
            return
        threads_text = self.thread_var.get().strip()
        if timed_mode_enabled:
            threads_text = "1"
            if self.thread_var.get().strip() != "1":
                self.thread_var.set("1")
        try:
            target = int(target_value)
            threads_count = int(threads_text or "0")
            if target <= 0 or threads_count <= 0:
                raise ValueError
        except ValueError:
            self._log_popup_error("参数错误", "目标份数和线程数必须为正整数")
            return
        minute_text = self.interval_minutes_var.get().strip()
        second_text = self.interval_seconds_var.get().strip()
        max_minute_text = self.interval_max_minutes_var.get().strip()
        max_second_text = self.interval_max_seconds_var.get().strip()
        answer_min_text = self.answer_duration_min_var.get().strip()
        answer_max_text = self.answer_duration_max_var.get().strip()
        full_sim_est_min_text = self.full_sim_estimated_minutes_var.get().strip()
        full_sim_est_sec_text = self.full_sim_estimated_seconds_var.get().strip()
        full_sim_total_min_text = self.full_sim_total_minutes_var.get().strip()
        full_sim_total_sec_text = self.full_sim_total_seconds_var.get().strip()
        try:
            interval_minutes = int(minute_text) if minute_text else 0
            interval_seconds = int(second_text) if second_text else 0
            interval_max_minutes = int(max_minute_text) if max_minute_text else 0
            interval_max_seconds = int(max_second_text) if max_second_text else 0
        except ValueError:
            self._log_popup_error("参数错误", "提交间隔请输入整数分钟和秒")
            return
        try:
            answer_min_seconds = int(answer_min_text) if answer_min_text else 0
            answer_max_seconds = int(answer_max_text) if answer_max_text else 0
        except ValueError:
            self._log_popup_error("参数错误", "作答时长请输入整数秒")
            return
        full_sim_est_seconds = 0
        full_sim_total_seconds = 0
        if full_sim_enabled:
            try:
                est_minutes = int(full_sim_est_min_text) if full_sim_est_min_text else 0
                est_seconds = int(full_sim_est_sec_text) if full_sim_est_sec_text else 0
                total_minutes = int(full_sim_total_min_text) if full_sim_total_min_text else 0
                total_seconds = int(full_sim_total_sec_text) if full_sim_total_sec_text else 0
            except ValueError:
                self._log_popup_error("参数错误", "全真模拟时间请输入整数")
                return
            if est_minutes < 0 or est_seconds < 0 or total_minutes < 0 or total_seconds < 0:
                self._log_popup_error("参数错误", "全真模拟时间不允许为负数")
                return
            if est_seconds >= 60 or total_seconds >= 60:
                self._log_popup_error("参数错误", "全真模拟时间中的秒数应在 0-59 之间")
                return
            full_sim_est_seconds = est_minutes * 60 + est_seconds
            full_sim_total_seconds = total_minutes * 60 + total_seconds
            if full_sim_est_seconds <= 0:
                self._log_popup_error("参数错误", "请填写预计单次作答时长")
                return
            if full_sim_total_seconds <= 0:
                self._log_popup_error("参数错误", "请填写模拟总时长")
                return
            if threads_count != 1:
                threads_count = 1
                self.thread_var.set("1")
                logging.info("全真模拟模式强制使用单线程执行")
        timed_refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
        max_fields_empty = (not max_minute_text) and (not max_second_text)
        if interval_minutes < 0 or interval_seconds < 0 or interval_max_minutes < 0 or interval_max_seconds < 0:
            self._log_popup_error("参数错误", "提交间隔必须为非负数")
            return
        if interval_seconds >= 60 or interval_max_seconds >= 60:
            self._log_popup_error("参数错误", "秒数范围应为 0-59")
            return
        if answer_min_seconds < 0 or answer_max_seconds < 0:
            self._log_popup_error("参数错误", "作答时长必须为非负秒数")
            return
        if answer_max_seconds < answer_min_seconds:
            self._log_popup_error("参数错误", "最长作答时长需大于或等于最短作答时长")
            return
        if full_sim_enabled and full_sim_total_seconds < full_sim_est_seconds * max(1, target):
            logging.warning("全真模拟总时长可能偏短，作答间隔会自动压缩以完成既定份数")
        interval_total_seconds = interval_minutes * 60 + interval_seconds
        max_interval_total_seconds = (
            interval_total_seconds
            if max_fields_empty
            else interval_max_minutes * 60 + interval_max_seconds
        )
        if max_interval_total_seconds < interval_total_seconds:
            max_interval_total_seconds = interval_total_seconds
            self.interval_max_minutes_var.set(str(interval_minutes))
            self.interval_max_seconds_var.set(str(interval_seconds))
        if not self.question_entries:
            msg = (
                "当前尚未配置任何题目。\n\n"
                "是否先预览问卷页面以确认题目？\n"
                "选择“是”：立即打开预览窗口，不会开始执行。\n"
                "选择“否”：直接开始执行（默认随机填写/跳过未配置题目）。"
            )
            if self._log_popup_confirm("提示", msg):
                self.preview_survey()
                return
        random_proxy_flag = bool(self.random_ip_enabled_var.get())
        effective_proxy_api = get_effective_proxy_api_url()
        random_ua_flag = bool(self.random_ua_enabled_var.get())
        random_ua_keys_list = self._get_selected_random_ua_keys() if random_ua_flag else []
        if random_ua_flag and not random_ua_keys_list:
            self._log_popup_error("参数错误", "启用随机 UA 时至少选择一个终端类型")
            return
        if random_proxy_flag:
            logging.info("[Action Log] 随机IP接口：已配置成功")
        if random_proxy_flag and not ensure_random_ip_ready(self):
            return
        timed_refresh_interval = timed_mode.DEFAULT_REFRESH_INTERVAL
        ctx = {
            "url_value": url_value,
            "target": target,
            "threads_count": threads_count,
            "interval_total_seconds": interval_total_seconds,
            "max_interval_total_seconds": max_interval_total_seconds,
            "answer_min_seconds": answer_min_seconds,
            "answer_max_seconds": answer_max_seconds,
            "full_sim_enabled": full_sim_enabled,
            "full_sim_est_seconds": full_sim_est_seconds,
            "full_sim_total_seconds": full_sim_total_seconds,
            "timed_mode_enabled": timed_mode_enabled,
            "timed_mode_interval": timed_refresh_interval,
            "random_proxy_flag": random_proxy_flag,
            "random_ua_flag": random_ua_flag,
            "random_ua_keys_list": random_ua_keys_list,
            "fail_stop_enabled": bool(self.fail_stop_enabled_var.get()),
            "random_proxy_api": effective_proxy_api,
        }
        if random_proxy_flag:
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.DISABLED)
            self.status_var.set("正在获取代理...")
            Thread(target=self._load_proxies_and_start, args=(ctx,), daemon=True).start()
            return
        self._finish_start_run(ctx, proxy_pool=[])

    def _load_proxies_and_start(self, ctx: Dict[str, Any]):
        if getattr(self, "_closing", False):
            return
        try:
            try:
                need_count = int(ctx.get("threads_count") or 1)
            except Exception:
                need_count = 1
            need_count = max(1, need_count)
            proxy_api = ctx.get("random_proxy_api")
            proxy_pool = _fetch_new_proxy_batch(expected_count=need_count, proxy_url=proxy_api)
        except (OSError, ValueError, RuntimeError) as exc:
            self._post_to_ui_thread(lambda: self._on_proxy_load_failed(str(exc)))
            return
        if getattr(self, "_closing", False):
            return
        self._post_to_ui_thread(lambda: self._finish_start_run(ctx, proxy_pool))

    def _on_proxy_load_failed(self, message: str):
        if getattr(self, "_closing", False):
            return
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED, text="🚫 停止")
        self.status_var.set("准备就绪")
        self._log_popup_error("代理IP错误", message)

    def _finish_start_run(self, ctx: Dict[str, Any], proxy_pool: List[str]):
        if getattr(self, "_closing", False):
            return
        # 启动前重置已记录的浏览器 PID，避免上一轮遗留
        self._launched_browser_pids.clear()
        if not self._log_refresh_job:
            self._schedule_log_refresh()
        random_proxy_flag = bool(ctx.get("random_proxy_flag"))
        random_ua_flag = bool(ctx.get("random_ua_flag"))
        fail_stop_enabled = bool(ctx.get("fail_stop_enabled", True))
        random_ua_keys_list = ctx.get("random_ua_keys_list", [])
        if random_proxy_flag:
            logging.info(f"[Action Log] 启用随机代理 IP（每个浏览器独立分配），已预取 {len(proxy_pool)} 条（{PROXY_REMOTE_URL}）")
        try:
            configure_probabilities(self.question_entries)
        except ValueError as exc:
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED, text="🚫 停止")
            self.status_var.set("准备就绪")
            self._log_popup_error("配置错误", str(exc))
            return

        self.stop_requested_by_user = False
        self.stop_request_ts = None

        url_value = ctx["url_value"]
        if not self._validate_wjx_url(url_value):
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED, text="?? 停止")
            self.status_var.set("准备就绪")
            self._log_popup_error("链接错误", "问卷链接为空或不合法")
            return
        target = ctx["target"]
        threads_count = ctx["threads_count"]
        interval_total_seconds = ctx["interval_total_seconds"]
        max_interval_total_seconds = ctx["max_interval_total_seconds"]
        answer_min_seconds = ctx["answer_min_seconds"]
        answer_max_seconds = ctx["answer_max_seconds"]
        full_sim_enabled = ctx["full_sim_enabled"]
        full_sim_est_seconds = ctx["full_sim_est_seconds"]
        full_sim_total_seconds = ctx["full_sim_total_seconds"]
        timed_mode_flag = bool(ctx.get("timed_mode_enabled"))
        try:
            timed_mode_interval_value = float(ctx.get("timed_mode_interval", timed_mode.DEFAULT_REFRESH_INTERVAL))
        except Exception:
            timed_mode_interval_value = timed_mode.DEFAULT_REFRESH_INTERVAL

        logging.info(
            f"[Action Log] Starting run url={url_value} target={target} threads={threads_count}"
        )

        global url, target_num, num_threads, fail_threshold, cur_num, cur_fail, stop_event, submit_interval_range_seconds, answer_duration_range_seconds, full_simulation_enabled, full_simulation_estimated_seconds, full_simulation_total_duration_seconds, timed_mode_enabled, timed_mode_refresh_interval, random_proxy_ip_enabled, proxy_ip_pool, random_user_agent_enabled, user_agent_pool_keys, stop_on_fail_enabled, _aliyun_captcha_stop_triggered, _target_reached_stop_triggered, _resume_after_aliyun_captcha_stop, _resume_snapshot
        url = url_value
        target_num = target
        # 强制限制线程数不超过12，确保用户电脑流畅
        num_threads = min(threads_count, MAX_THREADS)
        submit_interval_range_seconds = (interval_total_seconds, max_interval_total_seconds)
        answer_duration_range_seconds = (answer_min_seconds, answer_max_seconds)
        full_simulation_enabled = full_sim_enabled
        timed_mode_enabled = timed_mode_flag
        timed_mode_refresh_interval = timed_mode_interval_value
        random_proxy_ip_enabled = random_proxy_flag
        proxy_ip_pool = proxy_pool if random_proxy_flag else []
        random_user_agent_enabled = random_ua_flag
        user_agent_pool_keys = random_ua_keys_list
        stop_on_fail_enabled = fail_stop_enabled
        # 从 engine 模块获取当前值，或初始化为 0
        cur_num = getattr(engine, 'cur_num', 0)
        cur_fail = getattr(engine, 'cur_fail', 0)
        # 同步到 engine 模块全局，避免 import * 的副本和运行线程读到旧值
        engine.url = url
        engine.target_num = target_num
        engine.num_threads = num_threads
        engine.fail_threshold = fail_threshold
        engine.cur_num = cur_num
        engine.cur_fail = cur_fail
        engine.stop_event = stop_event
        engine.submit_interval_range_seconds = submit_interval_range_seconds
        engine.answer_duration_range_seconds = answer_duration_range_seconds
        engine.full_simulation_enabled = full_simulation_enabled
        engine.full_simulation_estimated_seconds = full_simulation_estimated_seconds
        engine.full_simulation_total_duration_seconds = full_simulation_total_duration_seconds
        engine.timed_mode_enabled = timed_mode_enabled
        engine.timed_mode_refresh_interval = timed_mode_refresh_interval
        engine.random_proxy_ip_enabled = random_proxy_ip_enabled
        engine.proxy_ip_pool = proxy_ip_pool
        engine.random_user_agent_enabled = random_user_agent_enabled
        engine.user_agent_pool_keys = user_agent_pool_keys
        engine.stop_on_fail_enabled = stop_on_fail_enabled
        engine._aliyun_captcha_stop_triggered = _aliyun_captcha_stop_triggered
        engine._target_reached_stop_triggered = _target_reached_stop_triggered
        engine._resume_after_aliyun_captcha_stop = _resume_after_aliyun_captcha_stop
        engine._resume_snapshot = _resume_snapshot
        if full_sim_enabled:
            full_simulation_estimated_seconds = full_sim_est_seconds
            full_simulation_total_duration_seconds = full_sim_total_seconds
            _FULL_SIM_STATE.enabled = True
            _FULL_SIM_STATE.estimated_seconds = int(full_sim_est_seconds or 0)
            _FULL_SIM_STATE.total_duration_seconds = int(full_sim_total_seconds or 0)
            schedule = _prepare_full_simulation_schedule(target, full_sim_total_seconds)
            if not schedule:
                self.start_button.config(state=tk.NORMAL)
                self.stop_button.config(state=tk.DISABLED, text="🚫 停止")
                self.status_var.set("准备就绪")
                self._log_popup_error("参数错误", "模拟时间设置无效")
                return
        else:
            full_simulation_estimated_seconds = 0
            full_simulation_total_duration_seconds = 0
            _FULL_SIM_STATE.disable()
            _reset_full_simulation_runtime_state()
        if timed_mode_enabled:
            logging.info(f"[Action Log] 定时模式启用，刷新间隔 {timed_mode_refresh_interval:.2f} 秒，将等待开放后自动提交。")
        fail_threshold = max(1, math.ceil(target_num / 4) + 1)
        stop_event = threading.Event()
        _aliyun_captcha_stop_triggered = False
        _target_reached_stop_triggered = False
        self._force_stop_now = False

        resume_allowed = False
        if _resume_after_aliyun_captcha_stop and isinstance(_resume_snapshot, dict):
            snap_url = str(_resume_snapshot.get("url") or "")
            snap_target = int(_resume_snapshot.get("target") or 0)
            if snap_url and snap_url == url_value and snap_target > 0 and target > 0:
                if 0 < int(cur_num) < int(target):
                    resume_allowed = True

        if not resume_allowed:
            cur_num = engine.cur_num = cur_num  # 保留已有进度，避免失败后清零
            cur_fail = engine.cur_fail = cur_fail
        # 本次点击开始后，无论是否续跑，都清空“续跑标记”，避免下次误触发
        _resume_after_aliyun_captcha_stop = False
        _resume_snapshot = {}
        # 重置对话框标记，允许新的任务达到限制时弹出对话框
        reset_quota_limit_dialog_flag()
        
        # 重置进度条
        self.progress_value = 0
        self.total_submissions = target
        self.current_submissions = cur_num
        self.progress_bar['value'] = 0
        self.progress_label.config(text="0%")
        if target > 0 and cur_num > 0:
            progress = int((cur_num / target) * 100)
            progress = max(0, min(100, progress))
            self.progress_bar['value'] = progress
            self.progress_label.config(text=f"{progress}%")

        self.running = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL, text="🚫 停止")
        if timed_mode_enabled:
            self.status_var.set("定时模式：等待问卷开放...")
        elif resume_allowed:
            self.status_var.set(
                f"继续执行 | 已提交 {engine.cur_num}/{engine.target_num} 份 | 失败 {engine.cur_fail} 次"
            )
        else:
            self.status_var.set("正在启动浏览器...")

        self.runner_thread = Thread(target=self._launch_threads, daemon=True)
        self.runner_thread.start()
        self._schedule_status_update()

    def _launch_threads(self):
        print(f"正在启动 {num_threads} 个浏览器窗口...")
        launch_gap = 0.0 if _is_fast_mode() else 0.1
        threads: List[Thread] = []
        for browser_index in range(num_threads):
            if stop_event.is_set():
                break
            window_x = 50 + browser_index * 60
            window_y = 50 + browser_index * 60
            thread = Thread(target=run, args=(window_x, window_y, stop_event, self), daemon=True)
            threads.append(thread)
        self.worker_threads = threads
        for thread in threads:
            if stop_event.is_set():
                break
            thread.start()
            if launch_gap > 0:
                time.sleep(launch_gap)
        print("浏览器启动中，请稍候...")
        self._wait_for_worker_threads(threads)
        self.root.after(0, self._on_run_finished)

    def _wait_for_worker_threads(self, threads: List[Thread]):
        grace_deadline: Optional[float] = None
        while True:
            if self._force_stop_now:
                return
            alive_threads = [t for t in threads if t.is_alive()]
            self.worker_threads = alive_threads
            if not alive_threads:
                return
            if self.stop_requested_by_user:
                if grace_deadline is None:
                    grace_deadline = time.time() + STOP_FORCE_WAIT_SECONDS
                elif time.time() >= grace_deadline:
                    logging.warning("停止等待提交线程退出超时，剩余线程将在后台自行收尾")
                    return
            for t in alive_threads:
                t.join(timeout=0.2)

    def _schedule_status_update(self):
        current = engine.cur_num
        target = engine.target_num
        failures = engine.cur_fail
        status = f"已提交 {current}/{target} 份 | 失败 {failures} 次"
        self.status_var.set(status)
        
        # 更新进度条
        if target > 0:
            progress = int((current / target) * 100)
            self.progress_bar['value'] = progress
            self.progress_label.config(text=f"{progress}%")
        
        if self.running:
            self.status_job = self.root.after(500, self._schedule_status_update)

    def _on_run_finished(self):
        self.running = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED, text="停止")
        if self.status_job:
            self.root.after_cancel(self.status_job)
            self.status_job = None
        current = engine.cur_num
        target = engine.target_num
        failures = engine.cur_fail
        if current >= target:
            msg = "任务完成"
        elif stop_event.is_set():
            msg = "已停止"
        else:
            msg = "已结束"
        self.status_var.set(f"{msg} | 已提交 {current}/{target} 份 | 失败 {failures} 次")
        self.worker_threads = []
        
        # 最终更新进度条
        if current >= target:
            self.progress_bar['value'] = 100
            self.progress_label.config(text="100%")
        else:
            if target > 0:
                progress = int((current / target) * 100)
                self.progress_bar['value'] = progress
                self.progress_label.config(text=f"{progress}%")

    def _start_stop_cleanup_with_grace(
        self,
        drivers_snapshot: List[BrowserDriver],
        worker_threads_snapshot: List[Thread],
        browser_pids_snapshot: Set[int],
    ):
        """手动停止时先给线程一次“达标式”软退出机会，减少卡顿，再视情况强制清理。"""

        def _runner():
            # 先模仿达到目标份数时的收尾，等待线程自行退出
            soft_wait_seconds = max(3.0, STOP_FORCE_WAIT_SECONDS * 2)
            deadline = time.time() + soft_wait_seconds
            try:
                while time.time() < deadline:
                    alive_threads = [t for t in worker_threads_snapshot if t.is_alive()]
                    if not alive_threads:
                        if not browser_pids_snapshot:
                            logging.info("[Stop] 线程已自然退出，无需强制清理")
                            self._stop_cleanup_thread_running = False
                            return
                        break
                    time.sleep(0.12)
            except Exception:
                logging.debug("停止预等待阶段异常，继续执行强制清理", exc_info=True)

            # 若仍有线程或可能残留的浏览器进程，再进入原有的强制清理流程
            self._async_stop_cleanup(
                drivers_snapshot,
                worker_threads_snapshot,
                browser_pids_snapshot,
                wait_for_threads=False,
            )

        Thread(target=_runner, daemon=True).start()

    def _async_stop_cleanup(
        self,
        drivers_snapshot: List[BrowserDriver],
        worker_threads_snapshot: List[Thread],
        browser_pids_snapshot: Set[int],
        *,
        wait_for_threads: bool = True,
    ):
        """在后台线程中执行分阶段停止，先温和关闭，再必要时强杀，避免主线程卡顿。"""
        deadline = time.time() + (STOP_FORCE_WAIT_SECONDS if wait_for_threads else 0)
        logging.info(f"[Stop] 后台清理启动: drivers={len(drivers_snapshot)} threads={len(worker_threads_snapshot)} pids={len(browser_pids_snapshot)}")
        try:
            # 尽量从 driver 实例里补齐 PID，避免落入全盘扫描（psutil + cmdline）导致停止时 UI 卡顿
            collected_pids: Set[int] = set(browser_pids_snapshot or set())
            for driver in drivers_snapshot:
                try:
                    pid_single = getattr(driver, "browser_pid", None)
                    if pid_single:
                        collected_pids.add(int(pid_single))
                except Exception:
                    pass
                try:
                    pid_set = getattr(driver, "browser_pids", None)
                    if pid_set:
                        collected_pids.update(int(p) for p in pid_set)
                except Exception:
                    pass
                try:
                    browser_obj = getattr(driver, "_browser", None)
                    proc = getattr(browser_obj, "process", None) if browser_obj else None
                    pid = getattr(proc, "pid", None) if proc else None
                    if pid:
                        collected_pids.add(int(pid))
                except Exception:
                    pass

            for driver in drivers_snapshot:
                try:
                    driver.quit()
                except Exception:
                    logging.debug("停止时关闭浏览器实例失败", exc_info=True)
            # 先等待线程退出，再按需清理进程，避免过早强杀导致抖动
            if wait_for_threads:
                while time.time() < deadline:
                    alive = [t for t in worker_threads_snapshot if t.is_alive()]
                    if not alive:
                        break
                    time.sleep(0.1)
            alive_threads = [t for t in worker_threads_snapshot if t.is_alive()]
            killed = 0
            if alive_threads or collected_pids:
                killed = _kill_processes_by_pid(collected_pids)
            # 兜底：仅在完全无法捕获 PID 时，才尝试按命令行特征清理（避免误杀用户浏览器）
            if alive_threads and not collected_pids:
                try:
                    _kill_playwright_browser_processes()
                except Exception as e:
                    logging.warning(f"强制清理浏览器进程时出错: {e}")
        finally:
            self._stop_cleanup_thread_running = False
            logging.info("[Stop] 后台清理结束")

    def force_stop_immediately(self, reason: Optional[str] = None):
        """立即停止所有线程与浏览器实例，不等待线程收尾。"""
        # 允许从后台线程触发：把 UI 操作切回主线程，避免 Tk 在多线程下卡死/异常卡顿
        if threading.current_thread() is not threading.main_thread():
            try:
                self._post_to_ui_thread(lambda: self.force_stop_immediately(reason=reason))
            except Exception:
                pass
            return
        if self._force_stop_now:
            return
        self._force_stop_now = True
        self.stop_requested_by_user = True
        self.stop_request_ts = time.time()
        stop_event.set()
        self.running = False
        try:
            self.stop_button.config(state=tk.DISABLED, text="停止")
            self.start_button.config(state=tk.NORMAL)
        except Exception:
            pass
        if self.status_job:
            try:
                self.root.after_cancel(self.status_job)
            except Exception:
                pass
            self.status_job = None
        if self._log_refresh_job:
            try:
                self.root.after_cancel(self._log_refresh_job)
            except Exception:
                pass
            self._log_refresh_job = None
        if self._ip_counter_refresh_job:
            try:
                self.root.after_cancel(self._ip_counter_refresh_job)
            except Exception:
                pass
            self._ip_counter_refresh_job = None

        label = reason or "已停止"
        try:
            current = engine.cur_num
            target = engine.target_num
            failures = engine.cur_fail
            self.status_var.set(f"{label} | 已提交 {current}/{target} 份 | 失败 {failures} 次")
        except Exception:
            pass

        drivers_snapshot = list(self.active_drivers)
        worker_threads_snapshot = list(self.worker_threads)
        browser_pids_snapshot = set(self._launched_browser_pids)
        self.active_drivers.clear()
        self._launched_browser_pids.clear()
        if not self._stop_cleanup_thread_running:
            self._stop_cleanup_thread_running = True
            try:
                self.root.update_idletasks()
            except Exception:
                pass
            self.root.after(
                10,
                lambda ds=drivers_snapshot, ws=worker_threads_snapshot, ps=browser_pids_snapshot: Thread(
                    target=self._async_stop_cleanup,
                    args=(ds, ws, ps),
                    kwargs={"wait_for_threads": False},
                    daemon=True,
                ).start(),
            )

    def stop_run(self):
        # 允许从后台线程触发：把 UI 操作切回主线程，避免 Tk 在多线程下卡死/异常卡顿
        if threading.current_thread() is not threading.main_thread():
            try:
                self._post_to_ui_thread(self.stop_run)
            except Exception:
                pass
            return
        if not self.running:
            return
        self.stop_requested_by_user = True
        self.stop_request_ts = time.time()
        stop_event.set()
        self.running = False
        self.stop_button.config(state=tk.DISABLED, text="停止中...")
        self.status_var.set("已发送停止请求，正在清理浏览器进程...")
        if self.status_job:
            try:
                self.root.after_cancel(self.status_job)
            except Exception:
                pass
            self.status_job = None
        # 停止日志刷新，避免停止阶段 UI 额外负担
        if self._log_refresh_job:
            try:
                self.root.after_cancel(self._log_refresh_job)
            except Exception:
                pass
            self._log_refresh_job = None
        # 停止随机IP计数刷新，减少停止阶段 UI 额外负担
        if self._ip_counter_refresh_job:
            try:
                self.root.after_cancel(self._ip_counter_refresh_job)
            except Exception:
                pass
            self._ip_counter_refresh_job = None

        # 在后台线程里关闭浏览器并清理 Playwright 进程，避免阻塞主线程
        drivers_snapshot = list(self.active_drivers)
        worker_threads_snapshot = list(self.worker_threads)
        browser_pids_snapshot = set(self._launched_browser_pids)
        self.active_drivers.clear()
        self._launched_browser_pids.clear()
        if not self._stop_cleanup_thread_running:
            self._stop_cleanup_thread_running = True
            try:
                self.root.update_idletasks()
            except Exception:
                pass
            self.root.after(
                10,
                lambda ds=drivers_snapshot, ws=worker_threads_snapshot, ps=browser_pids_snapshot: self._start_stop_cleanup_with_grace(ds, ws, ps),
            )
        auto_exit_now = False
        if self._auto_exit_on_stop:
            if self._auto_exit_delay_once:
                # 首次点击后自动开启的场景，本次不退出，下一次生效
                self._auto_exit_delay_once = False
            else:
                auto_exit_now = True
        else:
            # 第一次点击停止后自动开启一次“停止后退出”，下次点击停止时直接退出
            self._auto_exit_on_stop = True
            self._auto_exit_delay_once = True
            try:
                if not bool(self.auto_exit_on_stop_var.get()):
                    self.auto_exit_on_stop_var.set(True)
            except Exception:
                pass
            logging.info("[Action Log] 首次停止后已开启“停止后自动退出”，下次停止将直接退出程序。")

        if auto_exit_now:
            # 清理线程启动后快速退出，规避 Tk 主线程后续卡顿
            self.root.after(150, self._exit_app)
        
        logging.info("收到停止请求，等待当前提交线程完成")
        print("已暂停新的问卷提交，等待现有流程退出")

    def on_close(self):
        self._closing = True
        if getattr(self, "_ui_task_job", None):
            try:
                if self._ui_task_job is not None:
                    self.root.after_cancel(self._ui_task_job)
            except Exception:
                pass
            self._ui_task_job = None
        # 停止日志刷新
        if self._log_refresh_job:
            try:
                self.root.after_cancel(self._log_refresh_job)
            except Exception:
                pass
        if self._ip_counter_refresh_job:
            try:
                self.root.after_cancel(self._ip_counter_refresh_job)
            except Exception:
                pass
            self._ip_counter_refresh_job = None
        
        self.stop_run()
        
        # 只有在配置有实质性改动时才提示保存
        if not self._has_config_changed():
            # 配置未改动，直接关闭
            if self._log_refresh_job:
                try:
                    self.root.after_cancel(self._log_refresh_job)
                except Exception:
                    pass
            self._exit_app()
            return
        
        # 检查是否有问卷链接或题目配置
        has_url = bool(self.url_var.get().strip())
        has_questions = bool(self.question_entries)
        
        if has_url or has_questions:
            # 生成保存提示信息
            if has_questions:
                msg = f"是否保存配置以便下次使用？\n\n已配置 {len(self.question_entries)} 道题目"
            else:
                msg = "是否保存问卷链接以便下次使用？"
            
            # 创建自定义对话框，包含保存、不保存、取消三个按钮
            dialog = tk.Toplevel(self.root)
            dialog.title("保存配置")
            dialog.geometry("300x150")
            dialog.resizable(False, False)
            dialog.transient(self.root)
            dialog.grab_set()
            
            # 居中显示对话框
            dialog.update_idletasks()
            dialog_width = dialog.winfo_width()
            dialog_height = dialog.winfo_height()
            screen_width = dialog.winfo_screenwidth()
            screen_height = dialog.winfo_screenheight()
            
            try:
                import ctypes
                from ctypes.wintypes import RECT
                work_area = RECT()
                ctypes.windll.user32.SystemParametersInfoA(48, 0, ctypes.byref(work_area), 0)
                work_width = work_area.right - work_area.left
                work_height = work_area.bottom - work_area.top
                work_x = work_area.left
                work_y = work_area.top
                x = work_x + (work_width - dialog_width) // 2
                y = work_y + (work_height - dialog_height) // 2
            except:
                x = (screen_width - dialog_width) // 2
                y = (screen_height - dialog_height) // 2
            
            x = max(0, x)
            y = max(0, y)
            dialog.geometry(f"+{x}+{y}")
            
            # 消息标签
            ttk.Label(dialog, text=msg, wraplength=280, justify=tk.CENTER).pack(pady=20)
            
            # 按钮容器
            button_frame = ttk.Frame(dialog)
            button_frame.pack(pady=(0, 10))
            
            # 结果变量
            result = tk.IntVar(value=None)
            
            def save_config():
                saved = self._save_config_as_dialog(show_popup=False)
                if not saved:
                    return
                logging.info("[Action Log] Saved configuration via dialog before exit")
                result.set(1)
                dialog.destroy()
                if self._log_refresh_job:
                    try:
                        self.root.after_cancel(self._log_refresh_job)
                    except Exception:
                        pass
                self.root.destroy()
            
            def discard_config():
                # 不保存时，保持现有的config文件不删除，下次打开时会读取之前保存的config
                logging.info("[Action Log] Discarded new changes, keeping previous configuration")
                result.set(0)
                dialog.destroy()
                if self._log_refresh_job:
                    try:
                        self.root.after_cancel(self._log_refresh_job)
                    except Exception:
                        pass
                self.root.destroy()
            
            def cancel_close():
                logging.info("[Action Log] Cancelled exit")
                result.set(-1)
                dialog.destroy()
            
            ttk.Button(button_frame, text="保存", command=save_config, width=10).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame, text="不保存", command=discard_config, width=10).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame, text="取消", command=cancel_close, width=10).pack(side=tk.LEFT, padx=5)
            
            # 焦点设置到取消按钮作为默认
            dialog.focus_set()
            
            return
        
        if self._log_refresh_job:
            try:
                self.root.after_cancel(self._log_refresh_job)
            except Exception:
                pass
        self.root.destroy()

    def _bind_ime_candidate_position(self, widget: tk.Widget) -> None:
        """
        尽量让 Windows 输入法的候选/组合窗口贴近插入光标。

        说明：部分新式输入法（TSF）会忽略 ImmSetCandidateWindow，这里改用“系统 caret 位置”驱动，
        再辅以 ImmSetCompositionWindow 作为兼容兜底。
        """
        if getattr(widget, "_wjx_ime_bound", False):
            return
        setattr(widget, "_wjx_ime_bound", True)

        try:
            import sys
            import ctypes
            from ctypes import wintypes
        except Exception:
            return
        if not sys.platform.startswith("win"):
            return

        windll = getattr(ctypes, "windll", None)
        if not windll:
            return
        user32 = getattr(windll, "user32", None)
        imm32 = getattr(windll, "imm32", None)
        if not user32:
            return

        CFS_POINT = 0x0002
        CFS_FORCE_POSITION = 0x0020
        CFS_CANDIDATEPOS = 0x0040

        class COMPOSITIONFORM(ctypes.Structure):
            _fields_ = [
                ("dwStyle", wintypes.DWORD),
                ("ptCurrentPos", wintypes.POINT),
                ("rcArea", wintypes.RECT),
            ]

        class CANDIDATEFORM(ctypes.Structure):
            _fields_ = [
                ("dwIndex", wintypes.DWORD),
                ("dwStyle", wintypes.DWORD),
                ("ptCurrentPos", wintypes.POINT),
                ("rcArea", wintypes.RECT),
            ]

        state = {"caret_owner": 0, "caret_created": False}

        def _destroy_caret():
            if not state["caret_created"]:
                return
            try:
                user32.DestroyCaret()
            except Exception:
                pass
            state["caret_created"] = False
            state["caret_owner"] = 0

        def _ensure_caret(owner_hwnd: int, height: int) -> None:
            if owner_hwnd <= 0:
                return
            if state["caret_owner"] != owner_hwnd:
                _destroy_caret()
                state["caret_owner"] = owner_hwnd
            if state["caret_created"]:
                return
            try:
                ok = bool(user32.CreateCaret(wintypes.HWND(owner_hwnd), None, 1, max(2, int(height))))
            except Exception:
                ok = False
            state["caret_created"] = ok
            if ok:
                try:
                    user32.HideCaret(wintypes.HWND(owner_hwnd))
                except Exception:
                    pass

        def _set_imm_position(owner_hwnd: int, client_x: int, client_y: int) -> None:
            if not imm32 or owner_hwnd <= 0:
                return
            try:
                himc = imm32.ImmGetContext(wintypes.HWND(owner_hwnd))
            except Exception:
                himc = 0
            if not himc:
                return
            try:
                comp = COMPOSITIONFORM()
                comp.dwStyle = CFS_POINT | CFS_FORCE_POSITION
                comp.ptCurrentPos.x = int(client_x)
                comp.ptCurrentPos.y = int(client_y)
                comp.rcArea = wintypes.RECT(int(client_x), int(client_y), int(client_x) + 1, int(client_y) + 1)
                try:
                    imm32.ImmSetCompositionWindow(himc, ctypes.byref(comp))
                except Exception:
                    pass

                cand = CANDIDATEFORM()
                cand.dwIndex = 0
                cand.dwStyle = CFS_CANDIDATEPOS
                cand.ptCurrentPos.x = int(client_x)
                cand.ptCurrentPos.y = int(client_y)
                cand.rcArea = wintypes.RECT(int(client_x), int(client_y), int(client_x) + 1, int(client_y) + 1)
                try:
                    imm32.ImmSetCandidateWindow(himc, ctypes.byref(cand))
                except Exception:
                    pass
            finally:
                try:
                    imm32.ImmReleaseContext(wintypes.HWND(owner_hwnd), himc)
                except Exception:
                    pass

        def _update_ime_pos(event=None):
            try:
                # bbox() 方法对于 Text/Entry 组件返回 (x, y, width, height)
                bbox = widget.bbox(tk.INSERT)  # type: ignore[call-overload]
            except Exception:
                bbox = None
            if not bbox:
                return
            x, y, _, h = bbox
            screen_x = int(widget.winfo_rootx() + x)
            screen_y = int(widget.winfo_rooty() + y + h)

            try:
                focus_hwnd = int(user32.GetFocus() or 0)
            except Exception:
                focus_hwnd = 0
            if focus_hwnd <= 0:
                # 退化使用顶层窗口句柄
                try:
                    focus_hwnd = int(widget.winfo_toplevel().winfo_id() or 0)
                except Exception:
                    focus_hwnd = 0
            if focus_hwnd <= 0:
                return

            # 将屏幕坐标转换为焦点窗口客户区坐标（适配 DPI、多层嵌套窗口）
            pt = wintypes.POINT(screen_x, screen_y)
            try:
                user32.ScreenToClient(wintypes.HWND(focus_hwnd), ctypes.byref(pt))
            except Exception:
                return

            _ensure_caret(focus_hwnd, int(h) if h else 18)
            try:
                user32.SetCaretPos(int(pt.x), int(pt.y))
            except Exception:
                pass
            _set_imm_position(focus_hwnd, int(pt.x), int(pt.y))

        def _on_focus_out(event=None):
            _destroy_caret()

        for seq in ("<FocusIn>", "<KeyPress>", "<KeyRelease>", "<ButtonRelease-1>", "<ButtonRelease-3>"):
            widget.bind(seq, _update_ime_pos, add="+")
        widget.bind("<FocusOut>", _on_focus_out, add="+")
        try:
            widget.after_idle(_update_ime_pos)
        except Exception:
            pass

    def _get_display_scale(self) -> float:
        """获取显示缩放比例。"""
        try:
            # 尝试通过 tkinter 获取 DPI 缩放比例
            dpi = self.root.winfo_fpixels('1i')
            return dpi / 96.0  # 96 DPI 是标准值
        except Exception:
            return 1.0  # 出错时返回默认值

    def _apply_window_scaling(
        self,
        window: Union[tk.Tk, tk.Toplevel],
        *,
        base_width: Optional[int] = None,
        base_height: Optional[int] = None,
        min_width: Optional[int] = None,
        min_height: Optional[int] = None,
    ) -> None:
        """根据 DPI 缩放窗口尺寸并限制最大值，避免控件溢出。"""
        try:
            window.update_idletasks()
            scale = getattr(self, "_ui_scale", self._get_display_scale())
            req_w = window.winfo_reqwidth()
            req_h = window.winfo_reqheight()
            target_w = req_w
            target_h = req_h
            if base_width:
                target_w = max(target_w, int(base_width * scale))
            if base_height:
                target_h = max(target_h, int(base_height * scale))
            if min_width:
                target_w = max(target_w, int(min_width * scale))
            if min_height:
                target_h = max(target_h, int(min_height * scale))

            screen_w = window.winfo_screenwidth()
            screen_h = window.winfo_screenheight()
            max_w = max(320, int(screen_w * 0.95))
            max_h = max(240, int(screen_h * 0.95))
            target_w = min(target_w, max_w)
            target_h = min(target_h, max_h)

            window.geometry(f"{target_w}x{target_h}")
            try:
                window.minsize(min(target_w, max_w), min(target_h, max_h))
            except Exception:
                pass
        except Exception:
            pass

    def _center_child_window(self, window: tk.Toplevel):
        """使指定窗口居中显示。"""
        try:
            window.update_idletasks()
            width = window.winfo_width()
            height = window.winfo_height()
            screen_width = window.winfo_screenwidth()
            screen_height = window.winfo_screenheight()
            x = max(0, (screen_width - width) // 2)
            y = max(0, (screen_height - height) // 2)
            window.geometry(f"+{int(x)}+{int(y)}")
        except Exception:
            pass

    def _center_window(self):
        """将窗口放在屏幕上方中央"""
        self.root.update_idletasks()
        
        # 获取窗口大小
        window_width = self.root.winfo_width()
        window_height = self.root.winfo_height()
        
        # 获取屏幕大小（包括任务栏）
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        # 在 Windows 上获取工作区（不包括任务栏）
        try:
            import ctypes
            from ctypes.wintypes import RECT
            
            # 获取工作区坐标
            work_area = RECT()
            ctypes.windll.user32.SystemParametersInfoA(48, 0, ctypes.byref(work_area), 0)
            
            work_width = work_area.right - work_area.left
            work_height = work_area.bottom - work_area.top
            work_x = work_area.left
            work_y = work_area.top
            
            # 使用工作区计算位置 - 水平居中，垂直放在上方
            x = work_x + (work_width - window_width) // 2
            y = max(work_y + 20, work_y + (work_height - window_height) // 5)
        except:
            # 如果获取工作区失败，回退到简单计算
            x = (screen_width - window_width) // 2
            y = max(20, (screen_height - window_height) // 5)
        
        # 确保坐标不为负数
        x = max(0, x)
        y = max(0, y)
        
        # 设置窗口位置
        self.root.geometry(f"+{x}+{y}")

    def _check_updates_on_startup(self):
        """在启动时后台检查更新"""
        return check_updates_on_startup(self)

    def _show_update_notification(self):
        """显示更新通知"""
        return show_update_notification(self)

    def check_for_updates(self):
        """手动检查更新"""
        return _check_for_updates_impl(self)

    def _perform_update(self):
        """执行更新"""
        return _perform_update_impl(self)

    def show_about(self):
        """显示关于对话框"""
        about_text = (
            f"fuck-wjx（问卷星速填）\n\n"
            f"当前版本 v{__VERSION__}\n\n"
            f"GitHub项目地址: https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}\n"
            f"有问题可在 GitHub 提交 issue 或发送电子邮件至 hungrym0@qq.com\n\n"
            f"官方网站: https://www.hungrym0.top/fuck-wjx.html\n"
            f"©2025 HUNGRY_M0 版权所有  MIT Lisence"
        )
        logging.info("[Action Log] Displaying About dialog")
        self._log_popup_info("关于", about_text)

    def run(self):
        self.root.mainloop()


def main():
    setup_logging()
    boot.preload_boot_splash()

    base_root = boot.get_boot_root() or tk.Tk()
    base_root.withdraw()

    splash = boot.get_boot_splash() or boot.LoadingSplash(
        base_root, title="加载中", message="正在准备问卷星速填..."
    )
    if boot.get_boot_splash() is None:
        splash.show()
    else:
        splash.update_message("正在准备问卷星速填...")

    splash.update_progress(max(getattr(splash, "progress_value", 0), 25), "正在初始化环境...")
    splash.update_progress(max(getattr(splash, "progress_value", 0), 45), "正在加载界面...")

    gui = None
    try:
        gui = SurveyGUI(root=base_root, loading_splash=splash)
        splash.update_progress(max(getattr(splash, "progress_value", 0), 85), "主界面加载完成...")
    finally:
        splash.close()
        if boot.get_boot_splash() is splash:
            boot.close_boot_splash()
    if gui:
        gui.run()


if __name__ == "__main__":
    main()

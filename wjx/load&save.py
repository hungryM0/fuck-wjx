from __future__ import annotations

import json
import logging
import os
import random
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

import tkinter as tk
from tkinter import filedialog

from wjx.config import DEFAULT_RANDOM_UA_KEYS, USER_AGENT_PRESETS
from wjx.random_ip import normalize_random_ip_enabled_value

__all__ = [
    "_sanitize_filename",
    "_filter_valid_user_agent_keys",
    "_select_user_agent_from_keys",
    "ConfigPersistenceMixin",
    "set_question_entry_class",
    "set_runtime_directory_getter",
]

QuestionEntry = None  # 运行时由主程序注入


def _missing_runtime_directory() -> str:
    raise RuntimeError("runtime helper '_get_runtime_directory' 未注入")


_get_runtime_directory = _missing_runtime_directory


def set_question_entry_class(cls: Type[Any]) -> None:
    """由外部注入 QuestionEntry dataclass。"""
    global QuestionEntry
    QuestionEntry = cls


def set_runtime_directory_getter(func: Callable[[], str]) -> None:
    """由外部注入运行目录解析函数。"""
    global _get_runtime_directory
    _get_runtime_directory = func


def _ensure_question_entry_class():
    if QuestionEntry is None:
        raise RuntimeError("QuestionEntry 类尚未注入")
    return QuestionEntry


def _sanitize_filename(value: str, max_length: int = 80) -> str:
    """移除文件名中的非法字符。"""
    normalized = "".join(ch for ch in (value or "") if ch.isprintable())
    normalized = normalized.strip().replace(" ", "_")
    sanitized = "".join(ch for ch in normalized if ch not in '\\/:*?"<>|')
    if not sanitized:
        return "wjx_config"
    return sanitized[:max_length]


def _filter_valid_user_agent_keys(selected_keys: List[str]) -> List[str]:
    """过滤并保留合法的 UA key。"""
    return [key for key in (selected_keys or []) if key in USER_AGENT_PRESETS]


def _select_user_agent_from_keys(selected_keys: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """从给定 key 列表中随机挑选 UA，返回 (ua, label)。"""
    pool = _filter_valid_user_agent_keys(selected_keys)
    if not pool:
        return None, None
    key = random.choice(pool)
    preset = USER_AGENT_PRESETS.get(key) or {}
    return preset.get("ua"), preset.get("label")


class ConfigPersistenceMixin:
    """封装配置加载与保存的通用逻辑，供 GUI 复用。"""

    def _get_config_path(self) -> str:
        return os.path.join(_get_runtime_directory(), "config.json")

    def _get_configs_directory(self) -> str:
        """返回多配置保存目录，并在需要时创建。"""
        configs_dir = os.path.join(_get_runtime_directory(), "configs")
        os.makedirs(configs_dir, exist_ok=True)
        return configs_dir

    def _get_default_config_initial_name(self) -> str:
        """根据问卷标题生成默认的配置文件名。"""
        if getattr(self, "_last_survey_title", None):
            sanitized = _sanitize_filename(self._last_survey_title)
            if sanitized:
                return sanitized
        return f"wjx_config_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def _build_current_config_data(self) -> Dict[str, Any]:
        """收集当前界面上的配置数据。"""
        paned_sash_pos = None
        try:
            paned_sash_pos = self.main_paned.sashpos(0)
        except Exception:
            pass

        return {
            "url": self.url_var.get(),
            "target_num": self.target_var.get(),
            "num_threads": self.thread_var.get(),
            "submit_interval": self._serialize_submit_interval(),
            "answer_duration_range": self._serialize_answer_duration_config(),
            "full_simulation": self._serialize_full_simulation_config(),
            "random_user_agent": self._serialize_random_ua_config(),
            "wechat_login_bypass_enabled": bool(self.wechat_login_bypass_enabled_var.get()),
            "random_proxy_enabled": bool(self.random_ip_enabled_var.get()),
            "paned_position": paned_sash_pos,
            "questions": [
                {
                    "question_type": entry.question_type,
                    "probabilities": entry.probabilities
                    if not isinstance(entry.probabilities, int)
                    else entry.probabilities,
                    "texts": entry.texts,
                    "rows": entry.rows,
                    "option_count": entry.option_count,
                    "distribution_mode": entry.distribution_mode,
                    "custom_weights": entry.custom_weights,
                    "question_num": entry.question_num,
                    "option_fill_texts": entry.option_fill_texts,
                    "fillable_option_indices": entry.fillable_option_indices,
                    "is_location": bool(entry.is_location),
                }
                for entry in self.question_entries
            ],
        }

    def _serialize_submit_interval(self) -> Dict[str, int]:
        def _normalize(value: Any, *, cap_seconds: bool = False) -> int:
            try:
                text = str(value).strip()
            except Exception:
                text = ""
            if not text:
                parsed = 0
            else:
                try:
                    parsed = int(text)
                except ValueError:
                    parsed = 0
            parsed = max(0, parsed)
            if cap_seconds:
                parsed = min(59, parsed)
            return parsed

        minutes_text = self.interval_minutes_var.get()
        seconds_text = self.interval_seconds_var.get()
        max_minutes_text = self.interval_max_minutes_var.get()
        max_seconds_text = self.interval_max_seconds_var.get()

        minutes = _normalize(minutes_text)
        seconds = _normalize(seconds_text, cap_seconds=True)
        max_minutes = _normalize(max_minutes_text, cap_seconds=False)
        max_seconds = _normalize(max_seconds_text, cap_seconds=True)

        min_total = minutes * 60 + seconds
        max_total = max_minutes * 60 + max_seconds
        if (not str(max_minutes_text).strip() and not str(max_seconds_text).strip()) or max_total < min_total:
            max_minutes, max_seconds = minutes, seconds

        return {
            "minutes": minutes,
            "seconds": seconds,
            "max_minutes": max_minutes,
            "max_seconds": max_seconds,
        }

    def _serialize_answer_duration_config(self) -> Dict[str, int]:
        def _normalize(value: Any) -> int:
            try:
                text = str(value).strip()
            except Exception:
                text = ""
            if not text:
                parsed = 0
            else:
                try:
                    parsed = int(text)
                except ValueError:
                    parsed = 0
            return max(0, parsed)

        min_seconds = _normalize(self.answer_duration_min_var.get())
        max_seconds = _normalize(self.answer_duration_max_var.get())
        if max_seconds < min_seconds:
            max_seconds = min_seconds
        return {"min_seconds": min_seconds, "max_seconds": max_seconds}

    def _get_random_ua_option_vars(self) -> List[Tuple[str, tk.BooleanVar]]:
        return [
            ("pc_web", self.random_ua_pc_web_var),
            ("wechat_android", self.random_ua_android_wechat_var),
            ("wechat_ios", self.random_ua_ios_wechat_var),
            ("wechat_ipad", self.random_ua_ipad_wechat_var),
            ("ipad_web", self.random_ua_ipad_web_var),
            ("wechat_android_tablet", self.random_ua_android_tablet_wechat_var),
            ("android_tablet_web", self.random_ua_android_tablet_web_var),
            ("wechat_mac", self.random_ua_mac_wechat_var),
            ("wechat_windows", self.random_ua_windows_wechat_var),
            ("mac_web", self.random_ua_mac_web_var),
        ]

    def _get_selected_random_ua_keys(self) -> List[str]:
        return [key for key, var in self._get_random_ua_option_vars() if var.get()]

    def _serialize_random_ua_config(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.random_ua_enabled_var.get()),
            "selected": _filter_valid_user_agent_keys(self._get_selected_random_ua_keys()),
        }

    def _serialize_full_simulation_config(self) -> Dict[str, Any]:
        def _normalize(value: Any, *, cap_seconds: bool = False) -> int:
            try:
                text = str(value).strip()
            except Exception:
                text = ""
            if not text:
                parsed = 0
            else:
                try:
                    parsed = int(text)
                except ValueError:
                    parsed = 0
            parsed = max(0, parsed)
            if cap_seconds:
                parsed = min(59, parsed)
            return parsed

        return {
            "enabled": bool(self.full_simulation_enabled_var.get()),
            "target": _normalize(self.full_sim_target_var.get()),
            "estimated_minutes": _normalize(self.full_sim_estimated_minutes_var.get()),
            "estimated_seconds": _normalize(self.full_sim_estimated_seconds_var.get(), cap_seconds=True),
            "total_minutes": _normalize(self.full_sim_total_minutes_var.get()),
            "total_seconds": _normalize(self.full_sim_total_seconds_var.get(), cap_seconds=True),
        }

    def _apply_submit_interval_config(self, interval_config: Optional[Dict[str, Any]]):
        if not isinstance(interval_config, dict):
            interval_config = {}

        def _format_value(raw_value: Any, *, cap_seconds: bool = False) -> str:
            try:
                text = str(raw_value).strip()
            except Exception:
                text = ""
            if not text:
                parsed = 0
            else:
                try:
                    parsed = int(text)
                except ValueError:
                    parsed = 0
            parsed = max(0, parsed)
            if cap_seconds:
                parsed = min(59, parsed)
            return str(parsed)

        minutes_value = interval_config.get("minutes")
        seconds_value = interval_config.get("seconds")
        max_minutes_value = interval_config.get("max_minutes")
        max_seconds_value = interval_config.get("max_seconds")

        if max_minutes_value is None and max_seconds_value is None:
            max_minutes_value = minutes_value
            max_seconds_value = seconds_value

        self.interval_minutes_var.set(_format_value(minutes_value))
        self.interval_seconds_var.set(_format_value(seconds_value, cap_seconds=True))
        self.interval_max_minutes_var.set(_format_value(max_minutes_value if max_minutes_value is not None else minutes_value))
        self.interval_max_seconds_var.set(
            _format_value(
                max_seconds_value if max_seconds_value is not None else seconds_value,
                cap_seconds=True,
            )
        )

    def _apply_answer_duration_config(self, config: Optional[Dict[str, Any]]):
        if not isinstance(config, dict):
            config = {}

        def _format_value(raw_value: Any) -> str:
            try:
                text = str(raw_value).strip()
            except Exception:
                text = ""
            if not text:
                parsed = 0
            else:
                try:
                    parsed = int(text)
                except ValueError:
                    parsed = 0
            return str(max(0, parsed))

        self.answer_duration_min_var.set(_format_value(config.get("min_seconds")))
        self.answer_duration_max_var.set(_format_value(config.get("max_seconds")))

    def _apply_random_ua_config(self, config: Optional[Dict[str, Any]]):
        enabled = False
        selected_keys = list(DEFAULT_RANDOM_UA_KEYS)
        if isinstance(config, dict):
            enabled = bool(config.get("enabled"))
            selected_keys = _filter_valid_user_agent_keys(
                config.get("selected") or config.get("options") or list(DEFAULT_RANDOM_UA_KEYS)
            )
            if not selected_keys:
                selected_keys = list(DEFAULT_RANDOM_UA_KEYS)
        self.random_ua_enabled_var.set(enabled)
        for key, var in self._get_random_ua_option_vars():
            var.set(key in selected_keys)
        self._apply_random_ua_widgets_state()

    def _pick_random_user_agent(self) -> Tuple[Optional[str], Optional[str]]:
        if not self.random_ua_enabled_var.get():
            return None, None
        return _select_user_agent_from_keys(self._get_selected_random_ua_keys())

    def _apply_full_simulation_config(self, config: Optional[Dict[str, Any]]):
        if not isinstance(config, dict):
            config = {}

        def _format(raw_value: Any, *, cap_seconds: bool = False) -> str:
            try:
                text = str(raw_value).strip()
            except Exception:
                text = ""
            if not text:
                parsed = 0
            else:
                try:
                    parsed = int(text)
                except ValueError:
                    parsed = 0
            parsed = max(0, parsed)
            if cap_seconds:
                parsed = min(59, parsed)
            return str(parsed)

        self.full_simulation_enabled_var.set(bool(config.get("enabled")))
        self.full_sim_target_var.set(_format(config.get("target")))
        self.full_sim_estimated_minutes_var.set(_format(config.get("estimated_minutes")))
        self.full_sim_estimated_seconds_var.set(_format(config.get("estimated_seconds"), cap_seconds=True))
        self.full_sim_total_minutes_var.set(_format(config.get("total_minutes")))
        self.full_sim_total_seconds_var.set(_format(config.get("total_seconds"), cap_seconds=True))

    def _write_config_file(self, file_path: str, config_data: Optional[Dict[str, Any]] = None):
        """将配置写入指定文件。"""
        config_to_save = config_data if config_data is not None else self._build_current_config_data()
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(config_to_save, f, ensure_ascii=False, indent=2)

    def _save_config(self):
        try:
            self._write_config_file(self._get_config_path())
        except Exception as e:
            print(f"保存配置失败: {e}")

    def _apply_config_data(self, config: Dict[str, Any], *, restore_paned_position: bool = True):
        """将配置数据应用到界面。"""
        if not isinstance(config, dict):
            raise ValueError("配置文件格式不正确")

        self._suspend_full_sim_autofill = True
        try:
            self.url_var.set(config.get("url", ""))
            self.target_var.set(config.get("target_num", ""))
            self.thread_var.set(config.get("num_threads", ""))
            self._apply_random_ua_config(config.get("random_user_agent"))

            random_proxy_enabled_in_config = normalize_random_ip_enabled_value(
                bool(config.get("random_proxy_enabled"))
            )

            self.random_ip_enabled_var.set(random_proxy_enabled_in_config)
            self.wechat_login_bypass_enabled_var.set(bool(config.get("wechat_login_bypass_enabled", False)))
            self._apply_submit_interval_config(config.get("submit_interval"))
            self._apply_answer_duration_config(config.get("answer_duration_range"))
            self._apply_full_simulation_config(config.get("full_simulation"))

            if restore_paned_position:
                paned_position = config.get("paned_position")
                if paned_position is not None:
                    try:
                        desired_position = int(paned_position)
                    except (TypeError, ValueError):
                        desired_position = None
                    if desired_position is not None:
                        self._restore_saved_paned_position(desired_position)

            questions_data = config.get("questions") or []
            self.question_entries.clear()

            def _load_option_fill_texts_from_config(raw_value: Any) -> Optional[List[Optional[str]]]:
                if not isinstance(raw_value, list):
                    return None
                normalized: List[Optional[str]] = []
                has_value = False
                for item in raw_value:
                    if item is None:
                        normalized.append(None)
                        continue
                    try:
                        text_value = str(item).strip()
                    except Exception:
                        text_value = ""
                    if text_value:
                        has_value = True
                        normalized.append(text_value)
                    else:
                        normalized.append(None)
                return normalized if has_value else None

            def _load_fillable_indices_from_config(raw_value: Any) -> Optional[List[int]]:
                if not isinstance(raw_value, list):
                    return None
                parsed: List[int] = []
                for item in raw_value:
                    try:
                        index_value = int(item)
                    except (TypeError, ValueError):
                        continue
                    if index_value >= 0:
                        parsed.append(index_value)
                return parsed if parsed else None

            question_entry_cls = _ensure_question_entry_class()
            if isinstance(questions_data, list):
                for q_data in questions_data:
                    entry = question_entry_cls(
                        question_type=q_data.get("question_type", "single"),
                        probabilities=q_data.get("probabilities", -1),
                        texts=q_data.get("texts"),
                        rows=q_data.get("rows", 1),
                        option_count=q_data.get("option_count", 0),
                        distribution_mode=q_data.get("distribution_mode", "random"),
                        custom_weights=q_data.get("custom_weights"),
                        question_num=q_data.get("question_num"),
                        option_fill_texts=_load_option_fill_texts_from_config(q_data.get("option_fill_texts")),
                        fillable_option_indices=_load_fillable_indices_from_config(q_data.get("fillable_option_indices")),
                        is_location=bool(q_data.get("is_location")),
                    )
                    if entry.fillable_option_indices is None and entry.option_fill_texts:
                        derived = [idx for idx, value in enumerate(entry.option_fill_texts) if value]
                        entry.fillable_option_indices = derived if derived else None
                    self.question_entries.append(entry)
            self._refresh_tree()
        finally:
            self._suspend_full_sim_autofill = False

        self._save_initial_config()
        self._config_changed = False
        self._update_full_simulation_controls_state()
        self._update_parameter_widgets_state()

        def _duration_total_seconds(min_var: tk.StringVar, sec_var: tk.StringVar) -> int:
            try:
                minutes = int(str(min_var.get()).strip() or "0")
            except Exception:
                minutes = 0
            try:
                seconds = int(str(sec_var.get()).strip() or "0")
            except Exception:
                seconds = 0
            return max(0, minutes) * 60 + max(0, seconds)

        if (
            _duration_total_seconds(self.full_sim_estimated_minutes_var, self.full_sim_estimated_seconds_var) == 0
            or _duration_total_seconds(self.full_sim_total_minutes_var, self.full_sim_total_seconds_var) == 0
        ):
            self._auto_update_full_simulation_times()
        else:
            self._update_full_sim_time_section_visibility()

    def _load_config_from_file(self, file_path: str, *, silent: bool = False, restore_paned_position: bool = True):
        """从指定路径加载配置。"""
        with open(file_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        self._apply_config_data(config, restore_paned_position=restore_paned_position)
        if not silent:
            print(f"已加载配置：{os.path.basename(file_path)}")

    def _load_config(self):
        config_path = self._get_config_path()
        if not os.path.exists(config_path):
            return

        should_load_last = True
        try:
            should_load_last = self._log_popup_confirm(
                "加载上次配置",
                "检测到上一次保存的配置。\n是否要继续加载该配置？"
            )
        except Exception as e:
            print(f"询问是否加载上次配置时出错，将默认加载：{e}")

        if not should_load_last:
            print("用户选择在启动时不加载上一次保存的配置")
            return

        try:
            self._load_config_from_file(config_path, silent=True, restore_paned_position=True)
            print(f"已加载上次配置：{len(self.question_entries)} 道题目")
        except Exception as e:
            print(f"加载配置失败: {e}")

    def _save_config_as_dialog(self, *, show_popup: bool = True) -> bool:
        """通过对话框保存配置到用户自定义文件。"""
        configs_dir = self._get_configs_directory()
        default_name = self._get_default_config_initial_name()
        file_path = filedialog.asksaveasfilename(
            parent=self.root,
            title="保存配置",
            defaultextension=".json",
            initialfile=f"{default_name}.json",
            initialdir=configs_dir,
            filetypes=(("JSON 配置文件", "*.json"), ("所有文件", "*.*")),
        )
        if not file_path:
            return False
        try:
            self._write_config_file(file_path)
            if show_popup:
                self._log_popup_info("保存配置", f"配置已保存到:\n{file_path}")
            return True
        except Exception as exc:
            logging.error(f"保存配置失败: {exc}")
            self._log_popup_error("保存配置失败", f"无法保存配置:\n{exc}")
            return False

    def _load_config_from_dialog(self):
        """通过对话框加载用户选择的配置文件。"""
        configs_dir = self._get_configs_directory()
        file_path = filedialog.askopenfilename(
            parent=self.root,
            title="加载配置",
            initialdir=configs_dir,
            filetypes=(("JSON 配置文件", "*.json"), ("所有文件", "*.*")),
        )
        if not file_path:
            return
        try:
            self._load_config_from_file(file_path, restore_paned_position=False)
            self._log_popup_info("加载配置", f"已加载配置:\n{file_path}")
        except Exception as exc:
            logging.error(f"加载配置失败: {exc}")
            self._log_popup_error("加载配置失败", f"无法加载配置:\n{exc}")

    def _save_initial_config(self):
        """保存初始配置状态以便检测后续变化。"""
        self._initial_config = {
            "url": self.url_var.get(),
            "target_num": self.target_var.get(),
            "num_threads": self.thread_var.get(),
            "submit_interval": self._serialize_submit_interval(),
            "answer_duration_range": self._serialize_answer_duration_config(),
            "full_simulation": self._serialize_full_simulation_config(),
            "random_user_agent": self._serialize_random_ua_config(),
            "random_proxy_enabled": bool(self.random_ip_enabled_var.get()),
            "questions": [
                {
                    "question_type": entry.question_type,
                    "probabilities": entry.probabilities if not isinstance(entry.probabilities, int) else entry.probabilities,
                    "texts": entry.texts,
                    "rows": entry.rows,
                    "option_count": entry.option_count,
                    "distribution_mode": entry.distribution_mode,
                    "custom_weights": entry.custom_weights,
                    "question_num": entry.question_num,
                    "option_fill_texts": entry.option_fill_texts,
                    "fillable_option_indices": entry.fillable_option_indices,
                    "is_location": bool(entry.is_location),
                }
                for entry in self.question_entries
            ],
        }

    def _mark_config_changed(self):
        """标记配置已改动。"""
        self._config_changed = True

    def _has_config_changed(self) -> bool:
        """检查配置是否有实质性改动。"""
        current_config = {
            "url": self.url_var.get(),
            "target_num": self.target_var.get(),
            "num_threads": self.thread_var.get(),
            "submit_interval": self._serialize_submit_interval(),
            "answer_duration_range": self._serialize_answer_duration_config(),
            "full_simulation": self._serialize_full_simulation_config(),
            "random_user_agent": self._serialize_random_ua_config(),
            "random_proxy_enabled": bool(self.random_ip_enabled_var.get()),
            "questions": [
                {
                    "question_type": entry.question_type,
                    "probabilities": entry.probabilities if not isinstance(entry.probabilities, int) else entry.probabilities,
                    "texts": entry.texts,
                    "rows": entry.rows,
                    "option_count": entry.option_count,
                    "distribution_mode": entry.distribution_mode,
                    "custom_weights": entry.custom_weights,
                    "question_num": entry.question_num,
                    "option_fill_texts": entry.option_fill_texts,
                    "fillable_option_indices": entry.fillable_option_indices,
                    "is_location": bool(entry.is_location),
                }
                for entry in self.question_entries
            ],
        }
        return current_config != getattr(self, "_initial_config", {})

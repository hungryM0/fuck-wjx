"""RunController 解析与题目默认配置相关逻辑。"""
from __future__ import annotations

import copy
import logging
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from software.core.questions.config import QuestionEntry
from software.core.questions.utils import _normalize_question_type_code
from software.providers.common import (
    SURVEY_PROVIDER_WJX,
    detect_survey_provider,
    is_supported_survey_url,
    normalize_survey_provider,
)
from software.app.config import DEFAULT_FILL_TEXT

if TYPE_CHECKING:
    from software.io.config import RuntimeConfig


class RunControllerParsingMixin:
    if TYPE_CHECKING:
        surveyParsed: Any
        surveyParseFailed: Any
        config: RuntimeConfig
        questions_info: List[Dict[str, Any]]
        question_entries: List[QuestionEntry]
        survey_title: str

    # -------------------- Parsing --------------------
    def parse_survey(self, url: str):
        """Parse survey structure in a worker thread."""
        if not url:
            self.surveyParseFailed.emit("请填写问卷链接")
            return
        normalized_url = str(url or "").strip()
        if not is_supported_survey_url(normalized_url):
            logging.warning("收到不支持的问卷链接：%r", normalized_url)
            self.surveyParseFailed.emit("仅支持问卷星与腾讯问卷链接")
            return

        def _worker():
            try:
                info, title, provider = self._parse_questions(normalized_url)
                info = [q for q in info if not q.get("is_description")]
                self.questions_info = info
                self.question_entries = self._build_default_entries(info, self.question_entries)
                self.config.url = normalized_url
                self.config.survey_provider = provider
                self.config.survey_title = title or ""
                self.config.questions_info = list(info or [])
                self.config.question_entries = list(self.question_entries or [])
                self.survey_title = title or ""
                self.survey_provider = provider
                self.surveyParsed.emit(info, title or "")
            except Exception as exc:
                logging.exception("解析问卷流程失败，url=%r", normalized_url)
                friendly = str(exc) or "解析失败，请稍后重试"
                self.surveyParseFailed.emit(friendly)

        threading.Thread(target=_worker, daemon=True).start()

    def _parse_questions(self, url: str) -> Tuple[List[Dict[str, Any]], str, str]:
        from software.providers.registry import parse_survey
        return parse_survey(url)

    @staticmethod
    def _as_float(val, default):
        """将值转换为浮点数，失败时返回默认值"""
        try:
            return float(val)
        except Exception:
            return default

    @staticmethod
    def _build_mid_bias_weights(option_count: int) -> List[float]:
        """生成等权重（评价题默认）。"""
        count = max(1, int(option_count or 1))
        return [1.0] * count

    def _build_default_entries(
        self,
        questions_info: List[Dict[str, Any]],
        existing_entries: Optional[List[QuestionEntry]] = None,
    ) -> List[QuestionEntry]:
        """构建题目配置列表。优先按题号/题目文本精确复用旧配置，避免同题型串台。"""

        def _normalize_question_num(raw: Any) -> Optional[int]:
            try:
                if raw is None:
                    return None
                return int(raw)
            except Exception:
                return None

        def _normalize_title(raw: Any) -> str:
            try:
                text = str(raw or "").strip()
            except Exception:
                return ""
            if not text:
                return ""
            return "".join(text.split())

        def _normalize_provider_key(raw_provider: Any, raw_question_id: Any) -> Optional[Tuple[str, str]]:
            provider = normalize_survey_provider(raw_provider, default=SURVEY_PROVIDER_WJX)
            question_id = str(raw_question_id or "").strip()
            if not question_id:
                return None
            return provider, question_id

        def _normalize_forced_option_index(raw: Any, option_count: int) -> Optional[int]:
            try:
                idx = int(raw)
            except Exception:
                return None
            total = max(0, int(option_count or 0))
            if 0 <= idx < total:
                return idx
            return None

        def _build_forced_single_weights(option_count: int, forced_index: int) -> List[float]:
            total = max(1, int(option_count or 1))
            return [1.0 if idx == forced_index else 0.0 for idx in range(total)]

        def _normalize_attached_option_selects(
            parsed_configs: Any,
            existing_configs: Any = None,
        ) -> List[Dict[str, Any]]:
            parsed_list = parsed_configs if isinstance(parsed_configs, list) else []
            existing_map: Dict[int, Dict[str, Any]] = {}
            if isinstance(existing_configs, list):
                for item in existing_configs:
                    if not isinstance(item, dict):
                        continue
                    try:
                        option_index = int(item.get("option_index"))
                    except Exception:
                        continue
                    existing_map[option_index] = item
            normalized: List[Dict[str, Any]] = []
            for item in parsed_list:
                if not isinstance(item, dict):
                    continue
                try:
                    option_index = int(item.get("option_index"))
                except Exception:
                    continue
                option_text = str(item.get("option_text") or "").strip()
                select_options_raw = item.get("select_options")
                if not isinstance(select_options_raw, list):
                    continue
                select_options = [str(opt or "").strip() for opt in select_options_raw if str(opt or "").strip()]
                if not select_options:
                    continue
                weights = None
                existing_item = existing_map.get(option_index)
                if existing_item is not None:
                    existing_weights = existing_item.get("weights")
                    if isinstance(existing_weights, list) and existing_weights:
                        weights = []
                        for idx in range(len(select_options)):
                            raw_weight = existing_weights[idx] if idx < len(existing_weights) else 0.0
                            try:
                                weights.append(max(0.0, float(raw_weight)))
                            except Exception:
                                weights.append(0.0)
                        if not any(weight > 0 for weight in weights):
                            weights = None
                normalized.append({
                    "option_index": option_index,
                    "option_text": option_text,
                    "select_options": select_options,
                    "weights": weights,
                })
            return normalized

        def _normalize_fillable_option_indices(
            parsed_indices: Any,
            option_count: int,
            existing_indices: Any = None,
        ) -> List[int]:
            source = parsed_indices if isinstance(parsed_indices, list) else existing_indices
            if not isinstance(source, list):
                return []
            total = max(0, int(option_count or 0))
            normalized: List[int] = []
            seen: set[int] = set()
            for raw in source:
                try:
                    index = int(raw)
                except Exception:
                    continue
                if index < 0 or index >= total or index in seen:
                    continue
                seen.add(index)
                normalized.append(index)
            return normalized

        existing_by_num: Dict[int, QuestionEntry] = {}
        existing_by_title: Dict[str, QuestionEntry] = {}
        existing_by_provider: Dict[Tuple[str, str], QuestionEntry] = {}
        if existing_entries:
            for entry in existing_entries:
                q_num = _normalize_question_num(getattr(entry, "question_num", None))
                if q_num is not None and q_num not in existing_by_num:
                    existing_by_num[q_num] = entry
                title_key = _normalize_title(getattr(entry, "question_title", None))
                if title_key and title_key not in existing_by_title:
                    existing_by_title[title_key] = entry
                provider_key = _normalize_provider_key(
                    getattr(entry, "survey_provider", None),
                    getattr(entry, "provider_question_id", None),
                )
                if provider_key and provider_key not in existing_by_provider:
                    existing_by_provider[provider_key] = entry

        entries: List[QuestionEntry] = []
        for q in questions_info:
            type_code = _normalize_question_type_code(q.get("type_code"))
            if bool(q.get("is_description")):
                continue
            if bool(q.get("unsupported")):
                continue
            option_count = int(q.get("options") or 0)
            rows = int(q.get("rows") or 1)
            is_location = bool(q.get("is_location"))
            is_multi_text = bool(q.get("is_multi_text"))
            is_text_like = bool(q.get("is_text_like"))
            text_inputs = int(q.get("text_inputs") or 0)
            slider_min = q.get("slider_min")
            slider_max = q.get("slider_max")
            is_rating = bool(q.get("is_rating"))
            rating_max = int(q.get("rating_max") or 0)
            title_text = str(q.get("title") or "").strip()
            forced_option_text = str(q.get("forced_option_text") or "").strip()
            attached_option_selects = q.get("attached_option_selects") if isinstance(q.get("attached_option_selects"), list) else []
            survey_provider = normalize_survey_provider(
                q.get("provider"),
                default=detect_survey_provider(getattr(self.config, "url", "")),
            )
            provider_question_id = str(q.get("provider_question_id") or "").strip()
            provider_page_id = str(q.get("provider_page_id") or "").strip()

            if is_multi_text or (is_text_like and text_inputs > 1):
                q_type = "multi_text"
            elif is_text_like or type_code in ("1", "2"):
                q_type = "text"
            elif type_code == "3":
                q_type = "single"
            elif type_code == "4":
                q_type = "multiple"
            elif type_code == "5":
                q_type = "score" if is_rating else "scale"
            elif type_code == "6":
                q_type = "matrix"
            elif type_code == "7":
                q_type = "dropdown"
            elif type_code == "8":
                q_type = "slider"
            elif type_code == "11":
                q_type = "order"
            else:
                q_type = "single"

            base_option_count = max(option_count, rating_max, 1)
            if q_type in ("text", "multi_text"):
                option_count = max(base_option_count, text_inputs, 1)
            else:
                option_count = base_option_count
            forced_option_index = _normalize_forced_option_index(q.get("forced_option_index"), option_count)

            parsed_title_key = _normalize_title(title_text)

            existing_config: Optional[QuestionEntry] = None
            provider_key = _normalize_provider_key(survey_provider, provider_question_id)
            if provider_key:
                candidate = existing_by_provider.get(provider_key)
                if candidate and candidate.question_type == q_type:
                    existing_config = candidate
            parsed_question_num = _normalize_question_num(q.get("num"))
            if existing_config is None and parsed_question_num is not None:
                candidate = existing_by_num.get(parsed_question_num)
                if candidate and candidate.question_type == q_type:
                    candidate_title_key = _normalize_title(getattr(candidate, "question_title", None))
                    if parsed_title_key and candidate_title_key and candidate_title_key != parsed_title_key:
                        candidate = None
                    if candidate is not None:
                        existing_config = candidate
            if existing_config is None and parsed_title_key:
                candidate = existing_by_title.get(parsed_title_key)
                if candidate and candidate.question_type == q_type:
                    existing_config = candidate

            if existing_config:
                probabilities: Any = copy.deepcopy(existing_config.probabilities)
                distribution = existing_config.distribution_mode or "random"
                custom_weights = copy.deepcopy(existing_config.custom_weights)
                texts = copy.deepcopy(existing_config.texts)
                ai_enabled_from_existing = getattr(existing_config, "ai_enabled", False) if q_type in ("text", "multi_text") else False
                text_random_mode_from_existing = (
                    str(getattr(existing_config, "text_random_mode", "none") or "none")
                    if q_type == "text"
                    else "none"
                )
                text_random_int_range_from_existing = (
                    copy.deepcopy(getattr(existing_config, "text_random_int_range", []))
                    if q_type == "text"
                    else []
                )
                multi_text_blank_modes_from_existing = (
                    copy.deepcopy(getattr(existing_config, "multi_text_blank_modes", []))
                    if q_type == "multi_text"
                    else []
                )
                multi_text_blank_ai_flags_from_existing = (
                    copy.deepcopy(getattr(existing_config, "multi_text_blank_ai_flags", []))
                    if q_type == "multi_text"
                    else []
                )
                multi_text_blank_int_ranges_from_existing = (
                    copy.deepcopy(getattr(existing_config, "multi_text_blank_int_ranges", []))
                    if q_type == "multi_text"
                    else []
                )
                option_fill_texts_from_existing = (
                    copy.deepcopy(getattr(existing_config, "option_fill_texts", None))
                    if q_type in ("single", "multiple", "dropdown")
                    else None
                )
                fillable_indices_from_existing = (
                    copy.deepcopy(getattr(existing_config, "fillable_option_indices", None))
                    if q_type in ("single", "multiple", "dropdown")
                    else None
                )
                attached_selects_from_existing = copy.deepcopy(getattr(existing_config, "attached_option_selects", []) or [])
            else:
                ai_enabled_from_existing = False
                text_random_mode_from_existing = "none"
                text_random_int_range_from_existing = []
                multi_text_blank_modes_from_existing = []
                multi_text_blank_ai_flags_from_existing = []
                multi_text_blank_int_ranges_from_existing = []
                option_fill_texts_from_existing = None
                fillable_indices_from_existing = None
                attached_selects_from_existing = []
                if q_type in ("single", "dropdown", "scale"):
                    probabilities = -1
                    distribution = "random"
                    custom_weights = None
                    texts = None
                elif q_type == "score":
                    option_count = max(option_count, 2)
                    weights = self._build_mid_bias_weights(option_count)
                    probabilities = list(weights)
                    distribution = "custom"
                    custom_weights = list(weights)
                    texts = None
                elif q_type == "multiple":
                    probabilities = [50.0] * option_count
                    distribution = "random"
                    custom_weights = None
                    texts = None
                elif q_type == "matrix":
                    probabilities = -1
                    distribution = "random"
                    custom_weights = None
                    texts = None
                elif q_type == "order":
                    probabilities = -1
                    distribution = "random"
                    custom_weights = None
                    texts = None
                elif q_type == "slider":
                    min_val = self._as_float(slider_min, 0.0)
                    max_val = self._as_float(slider_max, 100.0 if slider_max is None else slider_max)
                    if max_val <= min_val:
                        max_val = min_val + 100.0
                    midpoint = min_val + (max_val - min_val) / 2.0
                    probabilities = [midpoint]
                    distribution = "custom"
                    custom_weights = [midpoint]
                    texts = None
                    option_count = 1
                else:
                    probabilities = [1.0]
                    distribution = "random"
                    custom_weights = None
                    texts = [DEFAULT_FILL_TEXT]

            if forced_option_index is not None and q_type in ("single", "dropdown", "scale", "score"):
                if q_type == "score":
                    option_count = max(option_count, 2)
                    forced_option_index = min(forced_option_index, option_count - 1)
                forced_weights = _build_forced_single_weights(option_count, forced_option_index)
                probabilities = list(forced_weights)
                distribution = "custom"
                custom_weights = list(forced_weights)
                logging.info(
                    "题号%s检测到指定作答指令，已强制锁定为第%s项（%s）",
                    q.get("num"),
                    forced_option_index + 1,
                    forced_option_text or "无文本",
                )

            fillable_option_indices = (
                _normalize_fillable_option_indices(
                    q.get("fillable_options"),
                    option_count,
                    fillable_indices_from_existing,
                )
                if q_type in ("single", "multiple", "dropdown")
                else []
            )
            entry = QuestionEntry(
                question_type=q_type,
                probabilities=probabilities,
                texts=texts,
                rows=rows,
                option_count=option_count,
                distribution_mode=distribution,
                custom_weights=custom_weights,
                question_num=q.get("num"),
                question_title=title_text or None,
                survey_provider=survey_provider,
                provider_question_id=provider_question_id or None,
                provider_page_id=provider_page_id or None,
                ai_enabled=ai_enabled_from_existing if q_type in ("text", "multi_text") else False,
                multi_text_blank_modes=multi_text_blank_modes_from_existing if q_type == "multi_text" else [],
                multi_text_blank_ai_flags=multi_text_blank_ai_flags_from_existing if q_type == "multi_text" else [],
                multi_text_blank_int_ranges=multi_text_blank_int_ranges_from_existing if q_type == "multi_text" else [],
                text_random_mode=text_random_mode_from_existing if q_type == "text" else "none",
                text_random_int_range=text_random_int_range_from_existing if q_type == "text" else [],
                option_fill_texts=option_fill_texts_from_existing if q_type in ("single", "multiple", "dropdown") else None,
                fillable_option_indices=fillable_option_indices,
                attached_option_selects=_normalize_attached_option_selects(
                    attached_option_selects,
                    attached_selects_from_existing if q_type == "single" else None,
                ) if q_type == "single" else [],
                is_location=is_location,
            )
            entries.append(entry)
        return entries


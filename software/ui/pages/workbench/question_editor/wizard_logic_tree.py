"""配置向导逻辑树与摘要辅助。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from software.providers.contracts import (
    LOGIC_PARSE_STATUS_UNKNOWN,
    SurveyQuestionMeta,
    ensure_survey_question_meta,
)

from .utils import _shorten_text, resolve_display_question_num


@dataclass(frozen=True)
class LogicRelation:
    kind: str
    source_index: int
    label: str
    target_question_num: Optional[int]
    target_index: Optional[int]
    selectable: bool
    ends_flow: bool = False


@dataclass
class LogicTreeState:
    has_unknown_logic: bool
    page_map: Dict[int, List[int]] = field(default_factory=dict)
    inbound_summary: Dict[int, str] = field(default_factory=dict)
    outbound_summary: Dict[int, str] = field(default_factory=dict)
    search_text: Dict[int, str] = field(default_factory=dict)
    relations: Dict[int, List[LogicRelation]] = field(default_factory=dict)


def _normalize_info_list(info_list: Sequence[SurveyQuestionMeta | Dict[str, Any]]) -> List[SurveyQuestionMeta]:
    normalized: List[SurveyQuestionMeta] = []
    for index, item in enumerate(info_list or [], start=1):
        normalized.append(ensure_survey_question_meta(item or {}, index=index))
    return normalized


def _question_num_map(info_list: Sequence[SurveyQuestionMeta]) -> Dict[int, int]:
    mapping: Dict[int, int] = {}
    for index, info in enumerate(info_list):
        try:
            question_num = int(info.num or 0)
        except Exception:
            question_num = 0
        if question_num > 0 and question_num not in mapping:
            mapping[question_num] = index
    return mapping


def _format_question_ref(question_num: int) -> str:
    return f"第{question_num}题" if question_num > 0 else "后续题目"


def _format_question_refs(question_nums: List[int]) -> str:
    normalized: List[int] = []
    seen = set()
    for raw in question_nums:
        try:
            value = int(raw)
        except Exception:
            continue
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    if not normalized:
        return "无"
    normalized.sort()
    labels = [_format_question_ref(value) for value in normalized]
    if len(labels) <= 4:
        return "、".join(labels)
    return f"{'、'.join(labels[:4])} 等{len(labels)}题"


def _format_option_text(info: SurveyQuestionMeta, option_indices: Sequence[Any]) -> str:
    option_texts = list(info.option_texts or [])
    labels: List[str] = []
    seen = set()
    for raw in option_indices:
        try:
            option_index = int(raw)
        except Exception:
            continue
        if option_index < 0 or option_index in seen:
            continue
        seen.add(option_index)
        if option_index < len(option_texts):
            option_text = str(option_texts[option_index] or "").strip()
            if option_text:
                labels.append(f"“{_shorten_text(option_text, 16)}”")
                continue
        labels.append(f"第{option_index + 1}项")
    if not labels:
        return "指定选项"
    if len(labels) <= 3:
        return "、".join(labels)
    return f"{'、'.join(labels[:3])} 等{len(labels)}项"


def _build_display_inbound_segments(
    info_list: Sequence[SurveyQuestionMeta],
) -> Dict[int, List[str]]:
    segments: Dict[int, List[str]] = {}
    for target_index, info in enumerate(info_list):
        conditions = info.display_conditions or []
        if not isinstance(conditions, list):
            continue
        current_segments: List[str] = []
        for condition in conditions:
            if not isinstance(condition, dict):
                continue
            try:
                source_question_num = int(condition.get("condition_question_num") or 0)
            except Exception:
                source_question_num = 0
            if source_question_num <= 0:
                continue
            source_index = next(
                (
                    idx
                    for idx, candidate in enumerate(info_list)
                    if int(candidate.num or 0) == source_question_num
                ),
                None,
            )
            source_info = info_list[source_index] if source_index is not None else ensure_survey_question_meta({})
            option_text = _format_option_text(
                source_info,
                list(condition.get("condition_option_indices") or []),
            )
            current_segments.append(f"{_format_question_ref(source_question_num)}选中{option_text}")
        if current_segments:
            segments[target_index] = current_segments
    return segments


def _build_jump_relations(
    info_list: Sequence[SurveyQuestionMeta],
    question_num_map: Dict[int, int],
) -> tuple[Dict[int, List[LogicRelation]], Dict[int, List[str]]]:
    relations: Dict[int, List[LogicRelation]] = {}
    inbound_segments: Dict[int, List[str]] = {}
    max_question_num = max((int(info.num or 0) for info in info_list), default=0)
    for source_index, info in enumerate(info_list):
        current_relations: List[LogicRelation] = []
        for rule in list(info.jump_rules or []):
            if not isinstance(rule, dict):
                continue
            try:
                target_question_num = int(rule.get("jumpto") or 0)
            except Exception:
                target_question_num = 0
            option_label = _format_option_text(info, [rule.get("option_index")])
            if target_question_num <= 0:
                continue
            ends_flow = target_question_num > max_question_num
            target_index = question_num_map.get(target_question_num)
            relation = LogicRelation(
                kind="jump",
                source_index=source_index,
                label=f"选中{option_label} -> {'结束' if ends_flow else _format_question_ref(target_question_num)}",
                target_question_num=target_question_num,
                target_index=target_index,
                selectable=(target_index is not None and not ends_flow),
                ends_flow=ends_flow,
            )
            current_relations.append(relation)
            if not ends_flow and target_index is not None:
                inbound_segments.setdefault(target_index, []).append(
                    f"{_format_question_ref(int(info.num or 0))}选中{option_label}后跳到本题"
                )
        if current_relations:
            relations[source_index] = current_relations
    return relations, inbound_segments


def _build_display_relations(
    info_list: Sequence[SurveyQuestionMeta],
    question_num_map: Dict[int, int],
) -> Dict[int, List[LogicRelation]]:
    relations: Dict[int, List[LogicRelation]] = {}
    for source_index, info in enumerate(info_list):
        items: List[LogicRelation] = []
        for target in list(info.controls_display_targets or []):
            if not isinstance(target, dict):
                continue
            try:
                target_question_num = int(target.get("target_question_num") or 0)
            except Exception:
                target_question_num = 0
            if target_question_num <= 0:
                continue
            option_text = _format_option_text(
                info,
                list(target.get("condition_option_indices") or []),
            )
            target_index = question_num_map.get(target_question_num)
            items.append(
                LogicRelation(
                    kind="display",
                    source_index=source_index,
                    label=f"选中{option_text} -> 显示{_format_question_ref(target_question_num)}",
                    target_question_num=target_question_num,
                    target_index=target_index,
                    selectable=target_index is not None,
                    ends_flow=False,
                )
            )
        if items:
            relations[source_index] = items
    return relations


def _merge_relations(
    display_relations: Dict[int, List[LogicRelation]],
    jump_relations: Dict[int, List[LogicRelation]],
) -> Dict[int, List[LogicRelation]]:
    merged: Dict[int, List[LogicRelation]] = {}
    for source_index in set(display_relations) | set(jump_relations):
        merged[source_index] = list(display_relations.get(source_index) or []) + list(
            jump_relations.get(source_index) or []
        )
    return merged


def build_logic_tree_state(
    info_inputs: Sequence[SurveyQuestionMeta | Dict[str, Any]],
) -> LogicTreeState:
    info_list = _normalize_info_list(info_inputs)
    state = LogicTreeState(
        has_unknown_logic=any(
            str(info.logic_parse_status or "").strip().lower() == LOGIC_PARSE_STATUS_UNKNOWN
            for info in info_list
        )
    )
    question_num_map = _question_num_map(info_list)

    for index, info in enumerate(info_list):
        state.page_map.setdefault(max(1, int(info.page or 1)), []).append(index)

    display_inbound = _build_display_inbound_segments(info_list)
    jump_relations, jump_inbound = _build_jump_relations(info_list, question_num_map)
    display_relations = _build_display_relations(info_list, question_num_map)
    state.relations = _merge_relations(display_relations, jump_relations)

    for index, info in enumerate(info_list):
        inbound_segments = list(display_inbound.get(index) or []) + list(jump_inbound.get(index) or [])
        state.inbound_summary[index] = "；".join(inbound_segments) if inbound_segments else "始终显示"

        outbound_segments: List[str] = []
        relation_items = list(state.relations.get(index) or [])
        display_targets: List[int] = []
        jump_targets: List[int] = []
        for relation in relation_items:
            if relation.kind == "display" and relation.target_question_num:
                display_targets.append(relation.target_question_num)
            elif relation.kind == "jump" and relation.target_question_num:
                jump_targets.append(relation.target_question_num)
        if display_targets:
            outbound_segments.append(f"显示 {_format_question_refs(display_targets)}")
        if jump_targets:
            labels: List[str] = []
            max_question_num = max((int(item.num or 0) for item in info_list), default=0)
            for target_num in jump_targets:
                labels.append("结束" if target_num > max_question_num else _format_question_ref(target_num))
            outbound_segments.append(f"跳转 {'、'.join(labels)}")
        state.outbound_summary[index] = "；".join(outbound_segments) if outbound_segments else "无"

        search_chunks = [
            str(resolve_display_question_num(info, index + 1) or index + 1),
            str(info.title or "").strip(),
            str(info.description or "").strip(),
            *[str(text or "").strip() for text in list(info.option_texts or [])],
            *[str(text or "").strip() for text in list(info.row_texts or [])],
            state.inbound_summary[index],
            state.outbound_summary[index],
        ]
        state.search_text[index] = " ".join(chunk for chunk in search_chunks if chunk).lower()
    return state

from __future__ import annotations

from types import SimpleNamespace

import pytest

from wjx.provider import runtime_answerers
from software.core.questions import runtime_async
from software.core.questions.schema import _TEXT_RANDOM_MOBILE, _TEXT_RANDOM_INTEGER


def _question(num: int, **overrides):
    payload = {
        "num": num,
        "option_texts": ["A", "B", "C"],
        "options": 3,
        "rows": 2,
        "title": f"Q{num}",
        "description": "",
        "multi_min_limit": 1,
        "multi_max_limit": 3,
        "text_inputs": 1,
        "forced_option_index": None,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _ctx(**config_overrides):
    config = {
        "single_prob": [[30, 70, 0]],
        "single_option_fill_texts": [["填空A", "填空B"]],
        "droplist_prob": [[20, 80, 0]],
        "droplist_option_fill_texts": [["下拉A", "下拉B"]],
        "texts": [["配置文本"]],
        "texts_prob": [[1.0]],
        "text_ai_flags": [False],
        "scale_prob": [[0, 100, 0]],
        "matrix_prob": [[60, 40, 0], [0, 100, 0]],
        "multiple_prob": [[-1]],
        "multiple_option_fill_texts": [["多选补充"]],
        "slider_targets": [66],
        "question_dimension_map": {},
        "question_config_index_map": {},
    }
    config.update(config_overrides)
    return SimpleNamespace(config=SimpleNamespace(**config))


class WjxRuntimeAnswerersTests:
    def test_valid_forced_choice_index_and_record_answer_action_cover_main_branches(self, monkeypatch) -> None:
        assert runtime_answerers._valid_forced_choice_index("1", 3) == 1
        assert runtime_answerers._valid_forced_choice_index(-1, 3) is None
        assert runtime_answerers._valid_forced_choice_index("x", 3) is None

        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        pending: list[tuple[object, ...]] = []
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs)))
        monkeypatch.setattr(runtime_answerers, "record_pending_distribution_choice", lambda *args, **kwargs: pending.append(args))

        ctx = _ctx()
        runtime_answerers._record_answer_action(
            ctx,
            runtime_answerers.AnswerAction(
                question_num=6,
                kind="matrix",
                matrix_indices=(2, 1),
                record_type="matrix",
                pending_distribution_choices=((1, 3, 0),),
            ),
        )
        runtime_answerers._record_answer_action(
            ctx,
            runtime_answerers.AnswerAction(
                question_num=7,
                kind="text",
                text_values=("甲", "", "乙"),
                record_type="text",
            ),
        )
        runtime_answerers._record_answer_action(
            ctx,
            runtime_answerers.AnswerAction(
                question_num=8,
                kind="slider",
                slider_value=66.0,
                record_type="slider",
            ),
        )
        runtime_answerers._record_answer_action(
            ctx,
            runtime_answerers.AnswerAction(
                question_num=9,
                kind="choice",
                selected_indices=(1, 2),
                selected_texts=("B", "C"),
                record_type="multiple",
            ),
        )

        assert pending == [(ctx, 6, 1, 3)]
        assert recorded == [
            ((6, "matrix"), {"selected_indices": [2], "row_index": 0}),
            ((6, "matrix"), {"selected_indices": [1], "row_index": 1}),
            ((7, "text"), {"text_answer": "甲 | 无 | 乙"}),
            ((8, "slider"), {"text_answer": "66.0"}),
            ((9, "multiple"), {"selected_indices": [1, 2], "selected_texts": ["B", "C"]}),
        ]

    @pytest.mark.asyncio
    async def test_answer_wjx_single_covers_normal_and_strict_ratio_paths(self, monkeypatch) -> None:
        ctx = _ctx()
        question = _question(3, option_texts=["甲", "乙", "丙"])
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        pending: list[tuple[object, ...]] = []
        fills: list[tuple[object, ...]] = []
        monkeypatch.setattr(runtime_answerers, "normalize_droplist_probs", lambda weights, count: [0.2, 0.8, 0.0][:count])
        monkeypatch.setattr(runtime_answerers, "apply_persona_boost", lambda texts, probs: [0.1, 0.9, 0.0])
        monkeypatch.setattr(runtime_answerers, "apply_single_like_consistency", lambda probs, _current: probs)
        monkeypatch.setattr(runtime_answerers, "is_strict_ratio_question", lambda _ctx, _current: False)
        monkeypatch.setattr(runtime_answerers, "weighted_index", lambda _probs: 1)

        async def _click_choice_input(*_args, **_kwargs):
            return True

        async def _resolve_fill(*_args, **_kwargs):
            return "补充"

        async def _fill_choice_option_additional_text(*_args, **_kwargs):
            fills.append(_args)
            return True

        monkeypatch.setattr(runtime_answerers, "_click_choice_input", _click_choice_input)
        monkeypatch.setattr(runtime_answerers, "resolve_runtime_option_fill_text_from_config", _resolve_fill)
        monkeypatch.setattr(runtime_answerers, "_fill_choice_option_additional_text", _fill_choice_option_additional_text)
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs)))
        monkeypatch.setattr(runtime_answerers, "record_pending_distribution_choice", lambda *args: pending.append(args))

        await runtime_answerers._answer_wjx_single(object(), question, 0, ctx)

        assert fills
        assert pending == []
        assert recorded == [((3, "single"), {"selected_indices": [1], "selected_texts": ["乙 / 补充"]})]

        recorded.clear()
        pending.clear()
        monkeypatch.setattr(runtime_answerers, "is_strict_ratio_question", lambda _ctx, _current: True)
        monkeypatch.setattr(runtime_answerers, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: [0.3, 0.7, 0.0])
        monkeypatch.setattr(runtime_answerers, "enforce_reference_rank_order", lambda probs, _reference: probs)
        await runtime_answerers._answer_wjx_single(object(), question, 0, ctx)
        assert pending == [(ctx, 3, 1, 3)]
        assert recorded[-1][1]["selected_indices"] == [1]

    @pytest.mark.asyncio
    async def test_answer_wjx_single_uses_psychometric_plan_when_dimensioned(self, monkeypatch) -> None:
        ctx = _ctx(question_dimension_map={3: "D1"})
        question = _question(3, option_texts=["差", "中", "好"])
        selected: list[int] = []
        monkeypatch.setattr(runtime_answerers, "normalize_droplist_probs", lambda weights, count: [0.2, 0.3, 0.5][:count])
        monkeypatch.setattr(runtime_answerers, "apply_persona_boost", lambda texts, probs: probs)
        monkeypatch.setattr(runtime_answerers, "is_strict_ratio_question", lambda _ctx, _current: False)
        monkeypatch.setattr(runtime_answerers, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: probs)
        monkeypatch.setattr(runtime_answerers, "enforce_reference_rank_order", lambda probs, _reference: probs)
        monkeypatch.setattr(runtime_answerers, "get_tendency_index", lambda *_args, **_kwargs: 2)

        async def _click_choice_input(_driver, _current, _input_type, selected_index):
            selected.append(selected_index)
            return True

        async def _resolve_fill(*_args, **_kwargs):
            return None

        monkeypatch.setattr(runtime_answerers, "_click_choice_input", _click_choice_input)
        monkeypatch.setattr(runtime_answerers, "resolve_runtime_option_fill_text_from_config", _resolve_fill)
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(runtime_answerers, "record_pending_distribution_choice", lambda *_args, **_kwargs: None)

        assert await runtime_answerers._answer_wjx_single(object(), question, 0, ctx, psycho_plan=object())

        assert selected == [2]

    @pytest.mark.asyncio
    async def test_answer_wjx_dropdown_covers_dimension_and_click_fail_paths(self, monkeypatch, caplog) -> None:
        ctx = _ctx(question_dimension_map={7: "D1"})
        question = _question(7, option_texts=["一", "二", "三"])
        pending: list[tuple[object, ...]] = []
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        monkeypatch.setattr(runtime_answerers, "normalize_droplist_probs", lambda weights, count: [0.2, 0.8, 0.0][:count])
        monkeypatch.setattr(runtime_answerers, "is_strict_ratio_question", lambda _ctx, _current: False)
        monkeypatch.setattr(runtime_answerers, "apply_persona_boost", lambda texts, probs: probs)
        monkeypatch.setattr(runtime_answerers, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: [0.1, 0.9, 0.0])
        monkeypatch.setattr(runtime_answerers, "get_tendency_index", lambda *_args, **_kwargs: 1)

        async def _set_select_value(*_args, **_kwargs):
            return True

        async def _resolve_fill(*_args, **_kwargs):
            return None

        monkeypatch.setattr(runtime_answerers, "_set_select_value", _set_select_value)
        monkeypatch.setattr(runtime_answerers, "resolve_runtime_option_fill_text_from_config", _resolve_fill)
        monkeypatch.setattr(runtime_answerers, "record_pending_distribution_choice", lambda *args: pending.append(args))
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs)))

        await runtime_answerers._answer_wjx_dropdown(object(), question, 0, ctx, psycho_plan="plan")

        assert pending == [(ctx, 7, 1, 3)]
        assert recorded == [((7, "dropdown"), {"selected_indices": [1], "selected_texts": ["二"]})]

        async def _select_fail(*_args, **_kwargs):
            return False

        monkeypatch.setattr(runtime_answerers, "_set_select_value", _select_fail)
        with caplog.at_level("WARNING"):
            result = await runtime_answerers._answer_wjx_dropdown(object(), question, 0, ctx, psycho_plan=None)
        assert result is False
        assert "无法选中选项" in caplog.text

    @pytest.mark.asyncio
    async def test_answer_wjx_text_covers_config_ai_and_failure_paths(self, monkeypatch) -> None:
        ctx = _ctx(texts=[["静态配置", "__TOKEN__"]], texts_prob=[[1.0]], text_ai_flags=[False])
        question = _question(9, title="标题", description="说明")
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        monkeypatch.setattr(runtime_async, "normalize_probabilities", lambda probs: [1.0] * len(probs))
        monkeypatch.setattr(runtime_async, "resolve_dynamic_text_token", lambda value: "动态值" if value == "__TOKEN__" else value)
        monkeypatch.setattr(runtime_async, "weighted_index", lambda _probs: 0)

        async def _fill_text(*_args, **_kwargs):
            return True

        monkeypatch.setattr(runtime_answerers, "_fill_text_input", _fill_text)
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs)))

        await runtime_answerers._answer_wjx_text(object(), question, 0, ctx)
        assert recorded == [((9, "text"), {"text_answer": "静态配置"})]

        recorded.clear()
        ctx_ai = _ctx(texts=[["配置"]], texts_prob=[[1.0]], text_ai_flags=[True])

        async def _ai_answer(*_args, **_kwargs):
            return ["AI答案"]

        monkeypatch.setattr(runtime_answerers, "agenerate_ai_answer", _ai_answer)
        await runtime_answerers._answer_wjx_text(object(), question, 0, ctx_ai)
        assert recorded == [((9, "text"), {"text_answer": "AI答案"})]

        async def _ai_fail(*_args, **_kwargs):
            raise runtime_answerers.AIRuntimeError("boom")

        monkeypatch.setattr(runtime_answerers, "agenerate_ai_answer", _ai_fail)
        with pytest.raises(runtime_answerers.AIRuntimeError, match="问卷星第9题 AI 生成失败"):
            await runtime_answerers._answer_wjx_text(object(), question, 0, ctx_ai)

    @pytest.mark.asyncio
    async def test_answer_wjx_text_applies_multi_text_blank_modes(self, monkeypatch) -> None:
        ctx = _ctx(
            texts=[["甲||乙", "丙||丁"]],
            texts_prob=[[1.0]],
            text_ai_flags=[False],
            text_entry_types=["multi_text"],
            multi_text_blank_modes=[["none", _TEXT_RANDOM_MOBILE, _TEXT_RANDOM_INTEGER]],
            multi_text_blank_int_ranges=[[[], [], [3, 9]]],
        )
        question = _question(9, text_inputs=3)
        fill_calls: list[tuple[object, ...]] = []

        monkeypatch.setattr(runtime_answerers, "weighted_index", lambda _probs: 0)
        monkeypatch.setattr(
            runtime_async,
            "resolve_dynamic_text_token",
            lambda value: "13900001111"
            if value == "__RANDOM_MOBILE__"
            else ("3" if str(value).startswith("__RANDOM_INT__:") else str(value)),
        )

        async def _fill_text(*args, **kwargs):
            fill_calls.append((args, kwargs))
            return True

        monkeypatch.setattr(runtime_answerers, "_fill_text_input", _fill_text)
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *args, **kwargs: None)

        await runtime_answerers._answer_wjx_text(object(), question, 0, ctx)

        assert [call[0][2] for call in fill_calls] == ["甲", "13900001111", "3"]

    @pytest.mark.asyncio
    async def test_answer_wjx_location_uses_location_picker(self, monkeypatch) -> None:
        ctx = _ctx()
        question = _question(12)
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []

        ctx.config.location_parts = {12: ["北京", "北京", "东城区"]}

        async def _select_location(_driver, question_num, location_parts):
            assert question_num == 12
            assert location_parts == ["北京", "北京", "东城区"]
            return "北京-北京市-东城区"

        monkeypatch.setattr(runtime_answerers, "_select_location_input", _select_location)
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs)))

        assert await runtime_answerers._answer_wjx_location(object(), question, ctx) is True
        assert recorded == [((12, "text"), {"text_answer": "北京-北京市-东城区"})]

        async def _select_location_fail(_driver, question_num, location_parts):
            return ""

        monkeypatch.setattr(runtime_answerers, "_select_location_input", _select_location_fail)
        assert await runtime_answerers._answer_wjx_location(object(), question, ctx) is False

    @pytest.mark.asyncio
    async def test_answer_wjx_score_matrix_slider_and_order_cover_main_paths(self, monkeypatch) -> None:
        ctx = _ctx(question_dimension_map={10: "D10"})
        question = _question(10, option_texts=["差", "中", "好"], options=3, rows=2)
        pending: list[tuple[object, ...]] = []
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        matrix_clicks = iter([True, False])
        monkeypatch.setattr(runtime_answerers, "normalize_droplist_probs", lambda weights, count: [0.1, 0.9, 0.0][:count])
        monkeypatch.setattr(runtime_answerers, "apply_single_like_consistency", lambda probs, _current: probs)
        monkeypatch.setattr(runtime_answerers, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: probs if isinstance(probs, list) else [1.0, 0.0, 0.0])
        monkeypatch.setattr(runtime_answerers, "get_tendency_index", lambda *_args, **_kwargs: 1)
        monkeypatch.setattr(runtime_answerers, "is_strict_ratio_question", lambda _ctx, _current: True)
        monkeypatch.setattr(runtime_answerers, "apply_matrix_row_consistency", lambda probs, _current, _row_index: probs)
        monkeypatch.setattr(runtime_answerers, "enforce_reference_rank_order", lambda probs, _reference: probs)

        async def _click_choice_input(*_args, **_kwargs):
            return True

        async def _click_matrix_cell(*_args, **_kwargs):
            return next(matrix_clicks)

        async def _set_slider_value(*_args, **_kwargs):
            return True

        async def _click_reorder_sequence(*_args, **_kwargs):
            return True

        monkeypatch.setattr(runtime_answerers, "_click_choice_input", _click_choice_input)
        monkeypatch.setattr(runtime_answerers, "_click_matrix_cell", _click_matrix_cell)
        monkeypatch.setattr(runtime_answerers, "_set_slider_value", _set_slider_value)
        monkeypatch.setattr(runtime_answerers, "_click_reorder_sequence", _click_reorder_sequence)
        monkeypatch.setattr(runtime_answerers, "record_pending_distribution_choice", lambda *args, **kwargs: pending.append(args))
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs)))
        monkeypatch.setattr(runtime_answerers.random, "shuffle", lambda values: values.reverse())

        assert await runtime_answerers._answer_wjx_score_like(object(), question, 0, ctx, psycho_plan=None, answer_type="scale")
        answered = await runtime_answerers._answer_wjx_matrix(object(), question, 0, ctx, psycho_plan=None)
        assert answered is False
        assert await runtime_answerers._answer_wjx_slider(object(), question, 0, ctx)
        assert await runtime_answerers._answer_wjx_order(object(), question)
        assert pending[0] == (ctx, 10, 1, 3)
        assert any(call[1].get("row_index") == 0 for call in recorded if call[0][1] == "matrix")
        assert any(call[0][1] == "slider" for call in recorded)
        assert any(call[0][1] == "order" for call in recorded)

    @pytest.mark.asyncio
    async def test_answer_wjx_multiple_and_dispatch_cover_random_strict_and_missing_config(self, monkeypatch) -> None:
        question = _question(11, option_texts=["甲", "乙", "丙", "丁"], options=4, multi_min_limit=2, multi_max_limit=3)
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        fill_calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(runtime_answerers, "get_multiple_rule_constraint", lambda *_args, **_kwargs: ({0}, {3}, None))
        monkeypatch.setattr(runtime_answerers, "_normalize_selected_indices", lambda values, count: list(dict.fromkeys(v for v in values if 0 <= v < count)))

        async def _click_choice_input(*_args, **_kwargs):
            return True

        async def _resolve_fill(*_args, **_kwargs):
            return "补"

        async def _fill_choice_option_additional_text(*_args, **_kwargs):
            fill_calls.append(_args)
            return None

        monkeypatch.setattr(runtime_answerers, "_click_choice_input", _click_choice_input)
        monkeypatch.setattr(runtime_answerers, "resolve_runtime_option_fill_text_from_config", _resolve_fill)
        monkeypatch.setattr(runtime_answerers, "_fill_choice_option_additional_text", _fill_choice_option_additional_text)
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs)))
        monkeypatch.setattr(runtime_answerers.random, "randint", lambda _start, _end: 1)
        monkeypatch.setattr(runtime_answerers.random, "sample", lambda population, count: list(population)[:count])

        ctx_random = _ctx(multiple_prob=[[-1]], multiple_option_fill_texts=[["填"]])
        assert await runtime_answerers._answer_wjx_multiple(object(), question, 0, ctx_random)
        assert recorded[0][1]["selected_indices"] == [0, 1]
        assert fill_calls

        recorded.clear()
        fill_calls.clear()
        ctx_prob = _ctx(multiple_prob=[[100, 60, 0, 10]])
        monkeypatch.setattr(runtime_answerers, "is_strict_ratio_question", lambda _ctx, _current: True)
        monkeypatch.setattr(runtime_answerers, "stochastic_round", lambda _value: 1)
        monkeypatch.setattr(runtime_answerers, "weighted_sample_without_replacement", lambda candidates, _weights, count: list(candidates)[:count])
        assert await runtime_answerers._answer_wjx_multiple(object(), question, 0, ctx_prob)
        assert recorded[0][1]["selected_indices"][0] == 0

        dispatch_ctx = _ctx(question_config_index_map={1: ("single", 0), 2: ("matrix", 0), 3: ("location", -1)})
        dispatch_record: list[str] = []

        async def _prepare_question_interaction(*_args, **_kwargs):
            dispatch_record.append("prepare")
            return True

        async def _answer_single(*_args, **_kwargs):
            dispatch_record.append("single")
            return True

        async def _answer_matrix(*_args, **_kwargs):
            dispatch_record.append("matrix")
            return True

        async def _answer_location(*_args, **_kwargs):
            dispatch_record.append("location")
            return True

        monkeypatch.setattr(runtime_answerers, "_prepare_question_interaction", _prepare_question_interaction)
        monkeypatch.setattr(runtime_answerers, "_answer_wjx_single", _answer_single)
        monkeypatch.setattr(runtime_answerers, "_answer_wjx_matrix", _answer_matrix)
        monkeypatch.setattr(runtime_answerers, "_answer_wjx_location", _answer_location)

        assert await runtime_answerers.answer_question_by_meta(object(), _question(1), dispatch_ctx, psycho_plan=None) is True
        assert await runtime_answerers.answer_question_by_meta(object(), _question(2), dispatch_ctx, psycho_plan=None) is True
        assert await runtime_answerers.answer_question_by_meta(object(), _question(3), dispatch_ctx, psycho_plan=None) is True
        assert await runtime_answerers.answer_question_by_meta(object(), _question(99), _ctx(), psycho_plan=None) is False
        assert dispatch_record == ["prepare", "single", "prepare", "matrix", "prepare", "location"]

    @pytest.mark.asyncio
    async def test_answer_page_batch_records_applied_and_reports_failed(self, monkeypatch) -> None:
        ctx = _ctx(question_config_index_map={1: ("single", 0), 2: ("text", 0)})
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        actions = {
            1: runtime_answerers.AnswerAction(
                question_num=1,
                kind="choice",
                input_type="radio",
                selected_indices=(1,),
                selected_texts=("B",),
                record_type="single",
            ),
            2: runtime_answerers.AnswerAction(
                question_num=2,
                kind="text",
                text_values=("文本",),
                record_type="text",
            ),
        }

        async def _build(_driver, question, _ctx, *, psycho_plan):
            assert psycho_plan == "plan"
            return actions[int(question.num)]

        async def _apply(_driver, answer_actions):
            assert [action.question_num for action in answer_actions] == [1, 2]
            return runtime_answerers.BatchFillResult(applied=(1,), failed=(2,))

        monkeypatch.setattr(runtime_answerers, "build_answer_action", _build)
        monkeypatch.setattr(runtime_answerers, "apply_answer_actions", _apply)
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs)))

        result = await runtime_answerers.answer_page_batch(
            object(),
            [_question(1), _question(2)],
            ctx,
            psycho_plan="plan",
        )

        assert result.applied == (1,)
        assert result.failed == (2,)
        assert recorded == [((1, "single"), {"selected_indices": [1], "selected_texts": ["B"]})]

    @pytest.mark.asyncio
    async def test_answer_page_batch_answers_popup_questions_outside_batch_script(self, monkeypatch) -> None:
        ctx = _ctx(question_config_index_map={1: ("single", 0), 7: ("location", -1), 15: ("order", -1)})
        calls: list[tuple[str, object]] = []

        async def _build(_driver, question, _ctx, *, psycho_plan):
            del _ctx, psycho_plan
            calls.append(("build", int(question.num)))
            return runtime_answerers.AnswerAction(
                question_num=int(question.num),
                kind="choice",
                input_type="radio",
                selected_indices=(0,),
                selected_texts=("A",),
                record_type="single",
            )

        async def _apply(_driver, answer_actions):
            calls.append(("apply", tuple(action.question_num for action in answer_actions)))
            return runtime_answerers.BatchFillResult(applied=tuple(action.question_num for action in answer_actions))

        async def _prepare(_driver, question_num):
            calls.append(("prepare", question_num))
            return True

        async def _answer_by_meta(_driver, question, _ctx, *, psycho_plan):
            del _ctx, psycho_plan
            calls.append(("direct", int(question.num)))
            return True

        async def _answer_order(_driver, question):
            calls.append(("order", int(question.num)))
            return True

        monkeypatch.setattr(runtime_answerers, "build_answer_action", _build)
        monkeypatch.setattr(runtime_answerers, "apply_answer_actions", _apply)
        monkeypatch.setattr(runtime_answerers, "_prepare_question_interaction", _prepare)
        monkeypatch.setattr(runtime_answerers, "answer_question_by_meta", _answer_by_meta)
        monkeypatch.setattr(runtime_answerers, "_answer_wjx_order", _answer_order)
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *_args, **_kwargs: None)

        result = await runtime_answerers.answer_page_batch(
            object(),
            [_question(1), _question(7), _question(15)],
            ctx,
            psycho_plan=None,
        )

        assert result.applied == (1, 7, 15)
        assert calls == [("build", 1), ("apply", (1,)), ("prepare", 7), ("direct", 7), ("prepare", 15), ("order", 15)]

    @pytest.mark.asyncio
    async def test_answer_page_batch_reports_popup_failures_without_batch_script(self, monkeypatch) -> None:
        ctx = _ctx(question_config_index_map={7: ("location", -1), 15: ("order", -1)})
        calls: list[tuple[str, object]] = []

        async def _apply(_driver, _answer_actions):
            raise AssertionError("地区题和排序题不应进入批量脚本")

        async def _prepare(_driver, question_num):
            calls.append(("prepare", question_num))
            return True

        async def _answer_by_meta(_driver, question, _ctx, *, psycho_plan):
            del _ctx, psycho_plan
            calls.append(("direct", int(question.num)))
            return False

        async def _answer_order(_driver, question):
            calls.append(("order", int(question.num)))
            return False

        monkeypatch.setattr(runtime_answerers, "apply_answer_actions", _apply)
        monkeypatch.setattr(runtime_answerers, "_prepare_question_interaction", _prepare)
        monkeypatch.setattr(runtime_answerers, "answer_question_by_meta", _answer_by_meta)
        monkeypatch.setattr(runtime_answerers, "_answer_wjx_order", _answer_order)

        result = await runtime_answerers.answer_page_batch(
            object(),
            [_question(7), _question(15)],
            ctx,
            psycho_plan=None,
        )

        assert result.applied == ()
        assert result.failed == (7, 15)
        assert calls == [("prepare", 7), ("direct", 7), ("prepare", 15), ("order", 15)]

    @pytest.mark.asyncio
    async def test_apply_answer_actions_returns_failed_when_js_errors(self) -> None:
        class _Driver:
            async def execute_script(self, *_args):
                raise RuntimeError("js boom")

        result = await runtime_answerers.apply_answer_actions(
            _Driver(),
            [runtime_answerers.AnswerAction(question_num=5, kind="choice", input_type="radio", selected_indices=(0,))],
        )

        assert result.failed == (5,)

    @pytest.mark.asyncio
    async def test_apply_answer_actions_excludes_location_action_script(self) -> None:
        class _Driver:
            def __init__(self) -> None:
                self.payload = None
                self.script = ""

            async def execute_script(self, script, payload):
                self.script = script
                self.payload = payload
                return {"applied": [12], "failed": []}

        driver = _Driver()
        result = await runtime_answerers.apply_answer_actions(
            driver,
            [
                runtime_answerers.AnswerAction(
                    question_num=12,
                    kind="location",
                    text_values=("北京", "北京", "东城区"),
                    record_type="text",
                )
            ],
        )

        assert result.failed == (12,)
        assert driver.payload is None
        assert "const confirmLocation" not in driver.script
        assert "applyLocation(root, action.textValues)" not in driver.script

    @pytest.mark.asyncio
    async def test_apply_answer_actions_excludes_order_action_script(self) -> None:
        class _Driver:
            def __init__(self) -> None:
                self.payload = None
                self.script = ""

            async def execute_script(self, script, payload):
                self.script = script
                self.payload = payload
                return {"applied": [8], "failed": []}

        driver = _Driver()
        result = await runtime_answerers.apply_answer_actions(
            driver,
            [runtime_answerers.AnswerAction(question_num=8, kind="order", selected_indices=(2, 0, 1), record_type="order")],
        )

        assert result.failed == (8,)
        assert driver.payload is None
        assert "const applyOrder" not in driver.script
        assert "applyOrder(root, action.selectedIndices" not in driver.script
        assert "const isMarked" not in driver.script
        assert "rankMarked" not in driver.script

    @pytest.mark.asyncio
    async def test_build_answer_action_skips_unavailable_questions_and_dispatches_helpers(self, monkeypatch) -> None:
        ctx = _ctx(question_config_index_map={1: ("single", 0), 7: ("location", -1), 8: ("order", -1)})
        ctx.config.location_parts = {7: ["北京", "北京", "东城区"]}
        question = _question(1)

        assert await runtime_answerers.build_answer_action(object(), _question(2, has_jump=True), ctx, psycho_plan=None) is None
        assert await runtime_answerers.build_answer_action(object(), _question(3, has_dependent_display_logic=True), ctx, psycho_plan=None) is None
        assert await runtime_answerers.build_answer_action(object(), _question(99), ctx, psycho_plan=None) is None
        assert await runtime_answerers.build_answer_action(object(), _question(7), ctx, psycho_plan=None) is None
        monkeypatch.setattr(runtime_answerers, "_resolve_runtime_option_texts", _async_result(["甲", "乙", "丙"]))
        monkeypatch.setattr(runtime_answerers.random, "shuffle", lambda values: values.reverse())
        assert await runtime_answerers.build_answer_action(object(), _question(8), ctx, psycho_plan=None) == runtime_answerers.AnswerAction(
            question_num=8,
            kind="order",
            selected_indices=(2, 1, 0),
            selected_texts=("丙", "乙", "甲"),
            record_type="order",
        )

        sentinel = runtime_answerers.AnswerAction(question_num=1, kind="choice", input_type="radio")

        async def _build_single(*_args, **_kwargs):
            return sentinel

        monkeypatch.setattr(runtime_answerers, "_build_wjx_single_action", _build_single)
        assert await runtime_answerers.build_answer_action(object(), question, ctx, psycho_plan="plan") is sentinel

    @pytest.mark.asyncio
    async def test_build_wjx_action_helpers_cover_single_dropdown_text_matrix_multiple_and_slider(self, monkeypatch) -> None:
        recorded_ai_prompts: list[str] = []
        monkeypatch.setattr(runtime_answerers, "_resolve_runtime_option_texts", _async_result(["甲", "乙", "丙"]))
        monkeypatch.setattr(runtime_answerers, "resolve_runtime_option_fill_text_from_config", _async_result("补充"))
        monkeypatch.setattr(runtime_answerers, "normalize_droplist_probs", lambda weights, count: [0.2, 0.8, 0.0][:count])
        monkeypatch.setattr(runtime_answerers, "apply_persona_boost", lambda texts, probs: probs)
        monkeypatch.setattr(runtime_answerers, "apply_single_like_consistency", lambda probs, _current: probs)
        monkeypatch.setattr(runtime_answerers, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: probs)
        monkeypatch.setattr(runtime_answerers, "enforce_reference_rank_order", lambda probs, _reference: probs)
        monkeypatch.setattr(runtime_answerers, "weighted_index", lambda _probs: 1)
        monkeypatch.setattr(runtime_answerers, "get_tendency_index", lambda *_args, **_kwargs: 2)
        monkeypatch.setattr(runtime_answerers, "is_strict_ratio_question", lambda _ctx, current: current in {1, 4})
        monkeypatch.setattr(runtime_answerers, "resolve_current_reverse_fill_answer", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(runtime_answerers, "resolve_runtime_text_values_from_config", lambda *_args, **_kwargs: ["甲", "乙"])
        monkeypatch.setattr(runtime_answerers, "apply_matrix_row_consistency", lambda probs, _current, _row_index: probs)
        monkeypatch.setattr(runtime_answerers, "get_multiple_rule_constraint", lambda *_args, **_kwargs: ({0}, {3}, None))
        monkeypatch.setattr(runtime_answerers, "_normalize_selected_indices", lambda values, count: list(dict.fromkeys(v for v in values if 0 <= v < count)))
        monkeypatch.setattr(runtime_answerers.random, "randint", lambda _start, _end: 1)
        monkeypatch.setattr(runtime_answerers.random, "sample", lambda population, count: list(population)[:count])
        monkeypatch.setattr(runtime_answerers, "stochastic_round", lambda _value: 1)
        monkeypatch.setattr(runtime_answerers, "weighted_sample_without_replacement", lambda candidates, _weights, count: list(candidates)[:count])

        async def _fake_ai(prompt: str, **_kwargs):
            recorded_ai_prompts.append(prompt)
            return ["AI答案"]

        monkeypatch.setattr(runtime_answerers, "agenerate_ai_answer", _fake_ai)

        ctx = _ctx(
            text_ai_flags=[True],
            texts=[["配置文本"]],
            texts_prob=[[1.0]],
            question_dimension_map={2: "D2", 4: "D4"},
            multiple_prob=[[-1]],
            slider_targets=["bad"],
        )

        single_action = await runtime_answerers._build_wjx_single_action(object(), _question(1), 0, ctx)
        dropdown_action = await runtime_answerers._build_wjx_dropdown_action(object(), _question(2), 0, ctx, psycho_plan="plan")
        text_action = await runtime_answerers._build_wjx_text_action(object(), _question(3, title="标题", description="说明", text_inputs=2), 0, ctx)
        matrix_action = await runtime_answerers._build_wjx_matrix_action(_question(4, rows=2, options=3), 0, ctx, psycho_plan="plan")
        multiple_action = await runtime_answerers._build_wjx_multiple_action(object(), _question(5, options=4, multi_min_limit=2, multi_max_limit=3), 0, ctx)
        slider_action = await runtime_answerers._build_wjx_slider_action(_question(6), 0, ctx)

        assert single_action == runtime_answerers.AnswerAction(
            question_num=1,
            kind="choice",
            input_type="radio",
            selected_indices=(1,),
            option_fill_texts=((1, "补充"),),
            selected_texts=("乙 / 补充",),
            record_type="single",
            pending_distribution_choices=((1, 3, None),),
        )
        assert dropdown_action == runtime_answerers.AnswerAction(
            question_num=2,
            kind="select",
            selected_indices=(2,),
            option_fill_texts=((2, "补充"),),
            selected_texts=("丙 / 补充",),
            record_type="dropdown",
            pending_distribution_choices=((2, 3, None),),
        )
        assert text_action == runtime_answerers.AnswerAction(
            question_num=3,
            kind="text",
            text_values=("AI答案", "AI答案"),
            record_type="text",
        )
        assert matrix_action == runtime_answerers.AnswerAction(
            question_num=4,
            kind="matrix",
            matrix_indices=(2, 2),
            record_type="matrix",
            pending_distribution_choices=((2, 3, 0), (2, 3, 1)),
        )
        assert multiple_action == runtime_answerers.AnswerAction(
            question_num=5,
            kind="choice",
            input_type="checkbox",
            selected_indices=(0, 1),
            option_fill_texts=((0, "补充"), (1, "补充")),
            selected_texts=("甲 / 补充", "乙 / 补充"),
            record_type="multiple",
        )
        assert slider_action == runtime_answerers.AnswerAction(
            question_num=6,
            kind="slider",
            slider_value=50.0,
            record_type="slider",
        )
        assert recorded_ai_prompts == ["标题\n补充说明：说明"]


def _async_result(value):
    async def _runner(*_args, **_kwargs):
        return value

    return _runner

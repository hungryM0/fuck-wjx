from __future__ import annotations

from types import SimpleNamespace

import pytest

from tencent.provider import runtime_answerers
from software.core.questions import runtime_async
from software.core.questions.schema import _TEXT_RANDOM_INTEGER


def _question(num: int, **overrides):
    payload = {
        "num": num,
        "provider_question_id": f"q{num}",
        "option_texts": ["A", "B", "C"],
        "options": 3,
        "rows": 2,
        "title": f"Q{num}",
        "description": "",
        "multi_min_limit": 1,
        "multi_max_limit": 3,
        "provider_type": "matrix",
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
        "scale_prob": [[0, 100, 0], [100, 0, 0], [10, 90]],
        "matrix_prob": [[60, 40, 0], [0, 100, 0]],
        "multiple_prob": [[-1]],
        "multiple_option_fill_texts": [["多选补充"]],
        "question_dimension_map": {},
    }
    config.update(config_overrides)
    return SimpleNamespace(config=SimpleNamespace(**config))


class TencentRuntimeAnswerersTests:
    def test_matrix_weight_helpers_cover_numeric_and_fallback_values(self, caplog) -> None:
        assert runtime_answerers._format_matrix_weight_value(2.0) == "2"
        assert runtime_answerers._format_matrix_weight_value(2.5) == "2.5"
        assert runtime_answerers._format_matrix_weight_value(float("inf")) == "随机"
        assert runtime_answerers._resolve_selected_weight_text(1, [0.1, 0.2], [1, 2]) == "0.2"
        assert runtime_answerers._resolve_selected_weight_text(1, None, [1, 2]) == "2"
        assert runtime_answerers._resolve_selected_weight_text(9, None, None) == "随机"

        with caplog.at_level("INFO"):
            runtime_answerers._log_qq_matrix_row_choice(3, 2, 1, ["差", "好"], [0.2, 0.8], [20, 80])
        assert "矩阵题作答" not in caplog.text

    @pytest.mark.asyncio
    async def test_answer_qq_single_handles_normal_and_strict_ratio_paths(self, monkeypatch) -> None:
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

        await runtime_answerers._answer_qq_single(object(), question, 0, ctx)

        assert fills
        assert pending == []
        assert recorded == [((3, "single"), {"selected_indices": [1], "selected_texts": ["乙 / 补充"]})]

        recorded.clear()
        pending.clear()
        monkeypatch.setattr(runtime_answerers, "is_strict_ratio_question", lambda _ctx, _current: True)
        monkeypatch.setattr(runtime_answerers, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: [0.3, 0.7, 0.0])
        monkeypatch.setattr(runtime_answerers, "enforce_reference_rank_order", lambda probs, _reference: probs)
        await runtime_answerers._answer_qq_single(object(), question, 0, ctx)
        assert pending == [(ctx, 3, 1, 3)]
        assert recorded[-1][1]["selected_indices"] == [1]

    @pytest.mark.asyncio
    async def test_answer_qq_single_uses_psychometric_plan_when_dimensioned(self, monkeypatch) -> None:
        ctx = _ctx(question_dimension_map={3: "D1"})
        question = _question(3, option_texts=["差", "中", "好"])
        selected: list[int] = []
        monkeypatch.setattr(runtime_answerers, "normalize_droplist_probs", lambda weights, count: [0.2, 0.3, 0.5][:count])
        monkeypatch.setattr(runtime_answerers, "apply_persona_boost", lambda texts, probs: probs)
        monkeypatch.setattr(runtime_answerers, "is_strict_ratio_question", lambda _ctx, _current: False)
        monkeypatch.setattr(runtime_answerers, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: probs)
        monkeypatch.setattr(runtime_answerers, "enforce_reference_rank_order", lambda probs, _reference: probs)
        monkeypatch.setattr(runtime_answerers, "get_tendency_index", lambda *_args, **_kwargs: 2)

        async def _click_choice_input(_driver, _question_id, _input_type, selected_index):
            selected.append(selected_index)
            return True

        async def _resolve_fill(*_args, **_kwargs):
            return None

        monkeypatch.setattr(runtime_answerers, "_click_choice_input", _click_choice_input)
        monkeypatch.setattr(runtime_answerers, "resolve_runtime_option_fill_text_from_config", _resolve_fill)
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(runtime_answerers, "record_pending_distribution_choice", lambda *_args, **_kwargs: None)

        await runtime_answerers._answer_qq_single(object(), question, 0, ctx, psycho_plan=object())

        assert selected == [2]

    @pytest.mark.asyncio
    async def test_answer_qq_single_and_score_like_skip_when_click_fails(self, monkeypatch, caplog) -> None:
        ctx = _ctx(scale_prob=[[100, 0]])
        question = _question(5, option_texts=["A", "B"], options=2)
        monkeypatch.setattr(runtime_answerers, "normalize_droplist_probs", lambda weights, count: [1.0, 0.0][:count])
        monkeypatch.setattr(runtime_answerers, "apply_persona_boost", lambda texts, probs: probs)
        monkeypatch.setattr(runtime_answerers, "apply_single_like_consistency", lambda probs, _current: probs)
        monkeypatch.setattr(runtime_answerers, "is_strict_ratio_question", lambda _ctx, _current: False)
        monkeypatch.setattr(runtime_answerers, "weighted_index", lambda _probs: 0)
        async def _click_choice_input(*_args, **_kwargs):
            return False
        monkeypatch.setattr(runtime_answerers, "_click_choice_input", _click_choice_input)
        monkeypatch.setattr(runtime_answerers, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: probs)
        monkeypatch.setattr(runtime_answerers, "get_tendency_index", lambda *_args, **_kwargs: 0)

        with caplog.at_level("WARNING"):
            await runtime_answerers._answer_qq_single(object(), question, 0, ctx)
            await runtime_answerers._answer_qq_score_like(object(), question, 0, ctx, psycho_plan=None)

        assert "点击未生效" in caplog.text

    @pytest.mark.asyncio
    async def test_answer_qq_dropdown_retries_open_and_records_distribution_when_dimension_active(self, monkeypatch) -> None:
        ctx = _ctx(question_dimension_map={7: "D1"})
        question = _question(7, option_texts=["一", "二", "三"])
        calls: list[str] = []
        pending: list[tuple[object, ...]] = []
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        open_results = iter([False, True])
        monkeypatch.setattr(runtime_answerers, "normalize_droplist_probs", lambda weights, count: [0.2, 0.8, 0.0][:count])
        monkeypatch.setattr(runtime_answerers, "is_strict_ratio_question", lambda _ctx, _current: False)
        monkeypatch.setattr(runtime_answerers, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: [0.1, 0.9, 0.0])
        monkeypatch.setattr(runtime_answerers, "get_tendency_index", lambda *_args, **_kwargs: 1)
        async def _prepare(*_args, **_kwargs):
            calls.append("prepare")
            return None
        async def _open(*_args, **_kwargs):
            return next(open_results)
        async def _select(*_args, **_kwargs):
            calls.append("select")
            return True
        async def _describe(*_args, **_kwargs):
            return "state"
        async def _resolve_fill(*_args, **_kwargs):
            return None
        monkeypatch.setattr(runtime_answerers, "_prepare_question_interaction", _prepare)
        monkeypatch.setattr(runtime_answerers, "_open_dropdown", _open)
        monkeypatch.setattr(runtime_answerers, "_select_dropdown_option", _select)
        monkeypatch.setattr(runtime_answerers, "_describe_dropdown_state", _describe)
        monkeypatch.setattr(runtime_answerers, "resolve_runtime_option_fill_text_from_config", _resolve_fill)
        monkeypatch.setattr(runtime_answerers, "record_pending_distribution_choice", lambda *args: pending.append(args))
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs)))

        await runtime_answerers._answer_qq_dropdown(object(), question, 0, ctx, psycho_plan="plan")

        assert calls == ["prepare", "prepare", "select"]
        assert pending == [(ctx, 7, 1, 3)]
        assert recorded == [((7, "dropdown"), {"selected_indices": [1], "selected_texts": ["二"]})]

    @pytest.mark.asyncio
    async def test_answer_qq_dropdown_logs_and_returns_when_open_or_select_fails(self, monkeypatch, caplog) -> None:
        ctx = _ctx()
        question = _question(8, option_texts=["一", "二"])
        monkeypatch.setattr(runtime_answerers, "normalize_droplist_probs", lambda weights, count: [1.0, 0.0][:count])
        monkeypatch.setattr(runtime_answerers, "is_strict_ratio_question", lambda _ctx, _current: False)
        monkeypatch.setattr(runtime_answerers, "weighted_index", lambda _probs: 0)
        async def _prepare(*_args, **_kwargs):
            return None
        async def _open_fail(*_args, **_kwargs):
            return False
        async def _open_ok(*_args, **_kwargs):
            return True
        async def _describe(*_args, **_kwargs):
            return "state"
        async def _select_fail(*_args, **_kwargs):
            return False
        monkeypatch.setattr(runtime_answerers, "_prepare_question_interaction", _prepare)
        monkeypatch.setattr(runtime_answerers, "_open_dropdown", _open_fail)
        monkeypatch.setattr(runtime_answerers, "_describe_dropdown_state", _describe)

        with caplog.at_level("WARNING"):
            await runtime_answerers._answer_qq_dropdown(object(), question, 0, ctx, psycho_plan=None)
        assert "无法打开选项面板" in caplog.text

        monkeypatch.setattr(runtime_answerers, "_open_dropdown", _open_ok)
        monkeypatch.setattr(runtime_answerers, "_select_dropdown_option", _select_fail)
        with caplog.at_level("WARNING"):
            await runtime_answerers._answer_qq_dropdown(object(), question, 0, ctx, psycho_plan=None)
        assert "无法选中选项" in caplog.text

    @pytest.mark.asyncio
    async def test_answer_qq_text_covers_config_ai_and_failure_paths(self, monkeypatch) -> None:
        ctx = _ctx(texts=[["静态配置", "__TOKEN__"]], texts_prob=[[1.0]], text_ai_flags=[False])
        question = _question(9, title="标题", description="说明")
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        monkeypatch.setattr(runtime_async, "normalize_probabilities", lambda probs: [1.0] * len(probs))
        monkeypatch.setattr(runtime_async, "resolve_dynamic_text_token", lambda value: "动态值" if value == "__TOKEN__" else value)
        monkeypatch.setattr(runtime_async, "weighted_index", lambda _probs: 0)
        async def _fill_text(*_args, **_kwargs):
            return True
        monkeypatch.setattr(runtime_answerers, "_fill_text_question", _fill_text)
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs)))

        await runtime_answerers._answer_qq_text(object(), question, 0, ctx)
        assert recorded == [((9, "text"), {"text_answer": "静态配置"})]

        recorded.clear()
        ctx_ai = _ctx(texts=[["配置"]], texts_prob=[[1.0]], text_ai_flags=[True])
        async def _ai_answer(*_args, **_kwargs):
            return ["AI答案"]
        monkeypatch.setattr(runtime_answerers, "agenerate_ai_answer", _ai_answer)
        await runtime_answerers._answer_qq_text(object(), question, 0, ctx_ai)
        assert recorded == [((9, "text"), {"text_answer": "AI答案"})]

        async def _ai_fail(*_args, **_kwargs):
            raise runtime_answerers.AIRuntimeError("boom")
        monkeypatch.setattr(runtime_answerers, "agenerate_ai_answer", _ai_fail)
        with pytest.raises(runtime_answerers.AIRuntimeError, match="腾讯问卷第9题 AI 生成失败"):
            await runtime_answerers._answer_qq_text(object(), question, 0, ctx_ai)

    @pytest.mark.asyncio
    async def test_answer_qq_text_splits_multi_text_answer_group_and_random_blank(self, monkeypatch) -> None:
        ctx = _ctx(
            texts=[["甲||乙"]],
            texts_prob=[[1.0]],
            text_ai_flags=[False],
            text_entry_types=["multi_text"],
            multi_text_blank_modes=[["none", _TEXT_RANDOM_INTEGER]],
            multi_text_blank_int_ranges=[[[], [3, 9]]],
        )
        question = _question(12, text_inputs=2)
        filled: list[object] = []
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        monkeypatch.setattr(runtime_async, "weighted_index", lambda _probs: 0)
        monkeypatch.setattr(
            runtime_async,
            "resolve_dynamic_text_token",
            lambda value: "5" if str(value).startswith("__RANDOM_INT__:") else str(value),
        )

        async def _fill_text(_driver, _question_id, value):
            filled.append(value)
            return True

        monkeypatch.setattr(runtime_answerers, "_fill_text_question", _fill_text)
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs)))

        await runtime_answerers._answer_qq_text(object(), question, 0, ctx)

        assert filled == [["甲", "5"]]
        assert recorded == [((12, "text"), {"text_answer": "甲 | 5"})]

    @pytest.mark.asyncio
    async def test_answer_qq_matrix_and_star_cover_row_flow_and_return_next_index(self, monkeypatch) -> None:
        ctx = _ctx(question_dimension_map={10: "D10"})
        question = _question(10, option_texts=["差", "中", "好"], options=3, rows=2)
        pending: list[tuple[object, ...]] = []
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        clicks = iter([True, False])
        monkeypatch.setattr(runtime_answerers, "is_strict_ratio_question", lambda _ctx, _current: True)
        monkeypatch.setattr(runtime_answerers, "apply_matrix_row_consistency", lambda probs, _current, _row_index: probs)
        monkeypatch.setattr(runtime_answerers, "resolve_distribution_probabilities", lambda probs, *_args, **_kwargs: probs if isinstance(probs, list) else [1.0, 0.0, 0.0])
        monkeypatch.setattr(runtime_answerers, "enforce_reference_rank_order", lambda probs, _reference: probs)
        monkeypatch.setattr(runtime_answerers, "get_tendency_index", lambda *_args, **_kwargs: 0)
        async def _click_matrix(*_args, **_kwargs):
            return next(clicks)
        async def _click_star(*_args, **_kwargs):
            return True
        monkeypatch.setattr(runtime_answerers, "_click_matrix_cell", _click_matrix)
        monkeypatch.setattr(runtime_answerers, "_click_star_cell", _click_star)
        monkeypatch.setattr(runtime_answerers, "record_pending_distribution_choice", lambda *args, **kwargs: pending.append(args))
        monkeypatch.setattr(runtime_answerers, "record_answer", lambda *args, **kwargs: recorded.append((args, kwargs)))

        next_index = await runtime_answerers._answer_qq_matrix(object(), question, 0, ctx, psycho_plan=None)
        assert next_index == 2
        assert pending == [(ctx, 10, 0, 3)]
        assert recorded[0][1]["row_index"] == 0

        pending.clear()
        recorded.clear()
        next_star = await runtime_answerers._answer_qq_matrix_star(object(), question, 0, ctx, psycho_plan=None)
        assert next_star == 2
        assert len(pending) == 2
        assert len(recorded) == 2

    @pytest.mark.asyncio
    async def test_answer_qq_multiple_covers_random_and_probability_modes(self, monkeypatch) -> None:
        question = _question(11, option_texts=["甲", "乙", "丙", "丁"], options=4, multi_min_limit=2, multi_max_limit=3)
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        fill_calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(runtime_answerers, "get_multiple_rule_constraint", lambda *_args, **_kwargs: ({0}, {3}, None))
        monkeypatch.setattr(runtime_answerers, "_normalize_selected_indices", lambda values, _count: list(dict.fromkeys(v for v in values if 0 <= v < _count)))
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
        monkeypatch.setattr(runtime_answerers, "_apply_multiple_constraints", lambda selected, *_args, **_kwargs: selected)
        monkeypatch.setattr(runtime_answerers.random, "randint", lambda _start, _end: 1)
        monkeypatch.setattr(runtime_answerers.random, "sample", lambda population, count: list(population)[:count])

        ctx_random = _ctx(multiple_prob=[[-1]], multiple_option_fill_texts=[["填"]])
        await runtime_answerers._answer_qq_multiple(object(), question, 0, ctx_random)
        assert recorded[0][1]["selected_indices"] == [0, 1]
        assert fill_calls

        recorded.clear()
        fill_calls.clear()
        ctx_prob = _ctx(multiple_prob=[[100, 60, 0, 10]])
        monkeypatch.setattr(runtime_answerers, "is_strict_ratio_question", lambda _ctx, _current: True)
        monkeypatch.setattr(runtime_answerers, "stochastic_round", lambda _value: 1)
        monkeypatch.setattr(runtime_answerers, "weighted_sample_without_replacement", lambda candidates, _weights, count: list(candidates)[:count])
        await runtime_answerers._answer_qq_multiple(object(), question, 0, ctx_prob)
        assert recorded[0][1]["selected_indices"][0] == 0

    @pytest.mark.asyncio
    async def test_answer_page_batch_skips_dropdown_and_records_applied(self, monkeypatch) -> None:
        ctx = _ctx(question_config_index_map={1: ("single", 0), 2: ("dropdown", 0)})
        recorded: list[tuple[tuple[object, ...], dict[str, object]]] = []
        action = runtime_answerers.AnswerAction(
            question_num=1,
            question_id="q1",
            kind="choice",
            input_type="radio",
            selected_indices=(1,),
            selected_texts=("B",),
            record_type="single",
        )

        async def _build(_driver, question, _ctx, *, psycho_plan):
            assert psycho_plan == "plan"
            return action if int(question.num) == 1 else None

        async def _apply(_driver, actions):
            assert [item.question_num for item in actions] == [1]
            return runtime_answerers.BatchFillResult(applied=(1,), failed=())

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
        assert result.skipped == (2,)
        assert recorded == [((1, "single"), {"selected_indices": [1], "selected_texts": ["B"]})]

    @pytest.mark.asyncio
    async def test_apply_answer_actions_returns_failed_without_page(self) -> None:
        class _Driver:
            async def page(self):
                return None

        result = await runtime_answerers.apply_answer_actions(
            _Driver(),
            [runtime_answerers.AnswerAction(question_num=4, question_id="q4", kind="choice", selected_indices=(0,))],
        )

        assert result.failed == (4,)

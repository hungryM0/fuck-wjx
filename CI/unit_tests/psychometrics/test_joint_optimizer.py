from __future__ import annotations
from unittest.mock import patch
from software.core.psychometrics.joint_optimizer import build_joint_psychometric_answer_plan, build_psychometric_blueprint
from software.core.task import ExecutionConfig

class JointOptimizerTests:

    def test_build_psychometric_blueprint_splits_matrix_rows_and_resolves_bias(self) -> None:
        config = ExecutionConfig(question_config_index_map={1: ('scale', 0), 2: ('dropdown', 0), 3: ('matrix', 0)}, question_dimension_map={1: 'mood', 2: 'career', 3: 'mood'}, question_psycho_bias_map={1: 'left', 2: 'custom', 3: ['right', 'bad-value']}, questions_metadata={1: {'options': 5}, 2: {'options': 4}, 3: {'options': 5, 'rows': 2}}, scale_prob=[-1], droplist_prob=[[0, 0, 0, 1]], matrix_prob=[[0, 0, 1, 3, 9], -1])
        grouped = build_psychometric_blueprint(config)
        mood_items = grouped['mood']
        career_items = grouped['career']
        assert len(mood_items) == 3
        assert len(career_items) == 1
        assert mood_items[0].choice_key == 'q:1'
        assert mood_items[0].bias == 'left'
        assert mood_items[1].choice_key == 'q:3:row:0'
        assert mood_items[1].bias == 'right'
        assert mood_items[2].choice_key == 'q:3:row:1'
        assert mood_items[2].bias == 'center'
        assert career_items[0].bias == 'right'

    def test_build_psychometric_blueprint_includes_only_mapped_ordinal_single(self) -> None:
        config = ExecutionConfig(
            question_config_index_map={1: ('single', 0), 2: ('single', 1)},
            question_dimension_map={1: 'mood', 2: 'mood'},
            question_psycho_bias_map={1: 'custom', 2: 'custom'},
            question_ordinal_score_map={1: [4, 3, 2, 1, 0]},
            questions_metadata={1: {'options': 5}, 2: {'options': 2}},
            single_prob=[[1, 1, 1, 1, 1], [1, 1]],
        )

        grouped = build_psychometric_blueprint(config)

        assert list(grouped.keys()) == ['mood']
        assert len(grouped['mood']) == 1
        assert grouped['mood'][0].question_type == 'single'
        assert grouped['mood'][0].score_by_choice_index == [4, 3, 2, 1, 0]
        assert grouped['mood'][0].choice_index_for_score(4) == 0

    def test_build_joint_psychometric_answer_plan_returns_choices_and_skip_diagnostics(self) -> None:
        config = ExecutionConfig(target_num=4, psycho_target_alpha=0.9, question_config_index_map={1: ('scale', 0), 2: ('scale', 1), 3: ('scale', 2), 4: ('scale', 3)}, question_dimension_map={1: 'stress', 2: 'stress', 3: 'stress', 4: 'single-item'}, question_psycho_bias_map={1: 'custom', 2: 'custom', 3: 'custom', 4: 'custom'}, questions_metadata={1: {'options': 5}, 2: {'options': 5}, 3: {'options': 5}, 4: {'options': 5}}, scale_prob=[[1, 0, 0, 0, 0], [1, 0, 0, 0, 0], [0, 0, 0, 0, 1], [0, 1, 0, 0, 0]])
        with patch('software.core.psychometrics.joint_optimizer.randn', return_value=0.0):
            plan = build_joint_psychometric_answer_plan(config)
        assert plan is not None
        assert plan is not None
        assert plan.sample_count == 4
        assert set(plan.answers_by_sample.keys()) == {0, 1, 2, 3}
        assert plan.item_dimension_map['q:1'] == 'stress'
        assert plan.item_dimension_map['q:2'] == 'stress'
        assert plan.item_dimension_map['q:3'] == 'stress'
        assert plan.diagnostics_by_dimension['single-item'].skipped
        assert plan.diagnostics_by_dimension['stress'].reverse_item_count == 1
        assert not plan.diagnostics_by_dimension['stress'].ambiguous_anchor
        for sample_index in range(plan.sample_count):
            q1_choice = plan.get_choice(sample_index, 1)
            q3_choice = plan.get_choice(sample_index, 3)
            assert q1_choice is not None
            assert q3_choice is not None
            assert int(q1_choice) in range(5)
            assert int(q3_choice) in range(5)
        sample_plan = plan.build_sample_plan(0)
        assert sample_plan is not None
        assert sample_plan is not None
        assert sample_plan.is_distribution_locked(1)
        assert sample_plan.diagnostics_by_dimension['stress'].anchor_direction == 'left'

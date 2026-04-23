from __future__ import annotations

import unittest
from unittest.mock import patch

from software.core.psychometrics.joint_optimizer import (
    build_joint_psychometric_answer_plan,
    build_psychometric_blueprint,
)
from software.core.task import ExecutionConfig


class JointOptimizerTests(unittest.TestCase):
    def test_build_psychometric_blueprint_splits_matrix_rows_and_resolves_bias(self) -> None:
        config = ExecutionConfig(
            question_config_index_map={
                1: ("scale", 0),
                2: ("dropdown", 0),
                3: ("matrix", 0),
            },
            question_dimension_map={
                1: "mood",
                2: "career",
                3: "mood",
            },
            question_psycho_bias_map={
                1: "left",
                2: "custom",
                3: ["right", "bad-value"],
            },
            questions_metadata={
                1: {"options": 5},
                2: {"options": 4},
                3: {"options": 5, "rows": 2},
            },
            scale_prob=[-1],
            droplist_prob=[[0, 0, 0, 1]],
            matrix_prob=[
                [0, 0, 1, 3, 9],
                -1,
            ],
        )

        grouped = build_psychometric_blueprint(config)

        mood_items = grouped["mood"]
        career_items = grouped["career"]
        self.assertEqual(len(mood_items), 3)
        self.assertEqual(len(career_items), 1)
        self.assertEqual(mood_items[0].choice_key, "q:1")
        self.assertEqual(mood_items[0].bias, "left")
        self.assertEqual(mood_items[1].choice_key, "q:3:row:0")
        self.assertEqual(mood_items[1].bias, "right")
        self.assertEqual(mood_items[2].choice_key, "q:3:row:1")
        self.assertEqual(mood_items[2].bias, "center")
        self.assertEqual(career_items[0].bias, "right")

    def test_build_joint_psychometric_answer_plan_returns_choices_and_skip_diagnostics(self) -> None:
        config = ExecutionConfig(
            target_num=4,
            psycho_target_alpha=0.9,
            question_config_index_map={
                1: ("scale", 0),
                2: ("scale", 1),
                3: ("scale", 2),
                4: ("scale", 3),
            },
            question_dimension_map={
                1: "stress",
                2: "stress",
                3: "stress",
                4: "single-item",
            },
            question_psycho_bias_map={
                1: "custom",
                2: "custom",
                3: "custom",
                4: "custom",
            },
            questions_metadata={
                1: {"options": 5},
                2: {"options": 5},
                3: {"options": 5},
                4: {"options": 5},
            },
            scale_prob=[
                [1, 0, 0, 0, 0],
                [1, 0, 0, 0, 0],
                [0, 0, 0, 0, 1],
                [0, 1, 0, 0, 0],
            ],
        )

        with patch("software.core.psychometrics.joint_optimizer.randn", return_value=0.0):
            plan = build_joint_psychometric_answer_plan(config)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.sample_count, 4)
        self.assertEqual(set(plan.answers_by_sample.keys()), {0, 1, 2, 3})
        self.assertEqual(plan.item_dimension_map["q:1"], "stress")
        self.assertEqual(plan.item_dimension_map["q:2"], "stress")
        self.assertEqual(plan.item_dimension_map["q:3"], "stress")
        self.assertTrue(plan.diagnostics_by_dimension["single-item"].skipped)
        self.assertEqual(plan.diagnostics_by_dimension["stress"].reverse_item_count, 1)
        self.assertFalse(plan.diagnostics_by_dimension["stress"].ambiguous_anchor)

        for sample_index in range(plan.sample_count):
            q1_choice = plan.get_choice(sample_index, 1)
            q3_choice = plan.get_choice(sample_index, 3)
            self.assertIsNotNone(q1_choice)
            self.assertIsNotNone(q3_choice)
            self.assertIn(int(q1_choice), range(5))
            self.assertIn(int(q3_choice), range(5))

        sample_plan = plan.build_sample_plan(0)
        self.assertIsNotNone(sample_plan)
        assert sample_plan is not None
        self.assertTrue(sample_plan.is_distribution_locked(1))
        self.assertEqual(sample_plan.diagnostics_by_dimension["stress"].anchor_direction, "left")


if __name__ == "__main__":
    unittest.main()

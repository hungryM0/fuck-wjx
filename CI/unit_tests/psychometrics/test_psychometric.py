from __future__ import annotations

import unittest
from unittest.mock import patch

from software.core.psychometrics.psychometric import (
    PsychometricItem,
    build_dimension_psychometric_plan,
    build_psychometric_plan,
)


class PsychometricPlanTests(unittest.TestCase):
    def test_build_psychometric_plan_returns_none_when_item_count_is_too_small(self) -> None:
        plan = build_psychometric_plan(
            [
                PsychometricItem(
                    kind="scale",
                    question_index=1,
                    option_count=5,
                    bias="center",
                    target_probabilities=[1, 1, 1, 1, 1],
                )
            ]
        )

        self.assertIsNone(plan)

    def test_build_psychometric_plan_applies_reverse_item_inference(self) -> None:
        items = [
            PsychometricItem(
                kind="scale",
                question_index=1,
                option_count=5,
                bias="left",
                target_probabilities=[1, 0, 0, 0, 0],
            ),
            PsychometricItem(
                kind="scale",
                question_index=2,
                option_count=5,
                bias="left",
                target_probabilities=[1, 0, 0, 0, 0],
            ),
            PsychometricItem(
                kind="scale",
                question_index=3,
                option_count=5,
                bias="right",
                target_probabilities=[0, 0, 0, 0, 1],
            ),
        ]

        with patch("software.core.psychometrics.psychometric.randn", side_effect=[1.0, 0.0, 0.0, 0.0]):
            plan = build_psychometric_plan(items, target_alpha=0.9)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(set(plan.choices.keys()), {"q:1", "q:2", "q:3"})
        self.assertEqual(plan.get_choice(1), 3)
        self.assertEqual(plan.get_choice(2), 3)
        self.assertEqual(plan.get_choice(3), 1)
        self.assertGreater(plan.get_choice(1), plan.get_choice(3))

    def test_build_dimension_psychometric_plan_skips_small_dimension_and_exposes_choices(self) -> None:
        grouped_items = {
            "engagement": [
                PsychometricItem(
                    kind="scale",
                    question_index=1,
                    option_count=5,
                    bias="center",
                    target_probabilities=[1, 1, 1, 1, 1],
                ),
                PsychometricItem(
                    kind="scale",
                    question_index=2,
                    option_count=5,
                    bias="center",
                    target_probabilities=[1, 1, 1, 1, 1],
                ),
            ],
            "single-item": [
                PsychometricItem(
                    kind="scale",
                    question_index=9,
                    option_count=5,
                    bias="center",
                    target_probabilities=[1, 1, 1, 1, 1],
                )
            ],
        }

        with patch("software.core.psychometrics.psychometric.randn", return_value=0.0):
            plan = build_dimension_psychometric_plan(grouped_items, target_alpha=0.9)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertIn("engagement", plan.plans)
        self.assertEqual(plan.skipped_dimensions, {"single-item": 1})
        self.assertEqual(plan.item_dimension_map["q:1"], "engagement")
        self.assertEqual(plan.item_dimension_map["q:2"], "engagement")
        self.assertIsNotNone(plan.get_choice(1))
        self.assertIsNotNone(plan.get_choice(2))
        self.assertIsNone(plan.get_choice(9))


if __name__ == "__main__":
    unittest.main()

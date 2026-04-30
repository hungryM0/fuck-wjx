from __future__ import annotations

import unittest

from software.core.task import ExecutionConfig, ExecutionState


class ExecutionStateConfigGuardTests(unittest.TestCase):
    def test_setting_config_field_on_state_raises_clear_error(self) -> None:
        state = ExecutionState(config=ExecutionConfig())

        with self.assertRaisesRegex(AttributeError, "state.config.target_num"):
            state.target_num = 10


if __name__ == "__main__":
    unittest.main()

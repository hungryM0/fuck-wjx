"""引擎拆分模块聚合导出。"""

from wjx.core.engine.answering import brush
from wjx.core.engine.dom_helpers import (
    _count_choice_inputs_driver,
    _driver_question_looks_like_rating,
    _driver_question_looks_like_reorder,
)
from wjx.core.engine.driver_factory import create_playwright_driver
from wjx.core.engine.full_simulation import (
    _build_per_question_delay_plan,
    _calculate_full_simulation_run_target,
    _full_simulation_active,
    _prepare_full_simulation_schedule,
    _reset_full_simulation_runtime_state,
    _simulate_answer_duration_delay,
    _sync_full_sim_state_from_globals,
    _wait_for_next_full_simulation_slot,
)
from wjx.core.engine.navigation import (
    _click_next_page_button,
    _human_scroll_after_question,
    dismiss_resume_dialog_if_present,
    try_click_start_answer_button,
)
from wjx.core.engine.question_detection import detect
from wjx.core.engine.runner import run
from wjx.core.engine.runtime_control import (
    _handle_submission_failure,
    _is_fast_mode,
    _sleep_with_stop,
    _timed_mode_active,
    _trigger_target_reached_stop,
    _wait_if_paused,
)
from wjx.core.engine.submission import (
    _click_submit_button,
    _is_device_quota_limit_page,
    _is_wjx_domain,
    _looks_like_wjx_survey_url,
    _normalize_url_for_compare,
    _page_looks_like_wjx_questionnaire,
    submit,
)
from wjx.core.survey.parser import (
    _normalize_html_text,
    _normalize_question_type_code,
    extract_survey_title_from_html as _extract_survey_title_from_html,
    parse_survey_questions_from_html,
)

__all__ = [
    "parse_survey_questions_from_html",
    "_extract_survey_title_from_html",
    "_normalize_html_text",
    "_normalize_question_type_code",
    "create_playwright_driver",
    "_is_fast_mode",
    "_timed_mode_active",
    "_handle_submission_failure",
    "_wait_if_paused",
    "_trigger_target_reached_stop",
    "_sync_full_sim_state_from_globals",
    "_driver_question_looks_like_rating",
    "_driver_question_looks_like_reorder",
    "_count_choice_inputs_driver",
    "try_click_start_answer_button",
    "dismiss_resume_dialog_if_present",
    "detect",
    "_full_simulation_active",
    "_reset_full_simulation_runtime_state",
    "_prepare_full_simulation_schedule",
    "_wait_for_next_full_simulation_slot",
    "_calculate_full_simulation_run_target",
    "_build_per_question_delay_plan",
    "_simulate_answer_duration_delay",
    "_human_scroll_after_question",
    "_click_next_page_button",
    "_click_submit_button",
    "_sleep_with_stop",
    "brush",
    "submit",
    "_normalize_url_for_compare",
    "_is_wjx_domain",
    "_looks_like_wjx_survey_url",
    "_page_looks_like_wjx_questionnaire",
    "_is_device_quota_limit_page",
    "run",
]

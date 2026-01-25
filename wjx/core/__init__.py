"""核心功能模块"""
from wjx.core.survey.parser import (
    parse_survey_questions_from_html,
    extract_survey_title_from_html,
)
from wjx.core.captcha.handler import (
    AliyunCaptchaBypassError,
    EmptySurveySubmissionError,
    handle_aliyun_captcha,
    reset_captcha_popup_state,
)

# 题型处理共享工具
from wjx.core.questions.utils import (
    weighted_index,
    normalize_probabilities,
    normalize_droplist_probs,
    normalize_single_like_prob_config,
    normalize_option_fill_texts,
    smooth_scroll_to_element,
    fill_option_additional_text,
    get_fill_text_from_config,
    resolve_dynamic_text_token,
    extract_text_from_element,
    generate_random_chinese_name,
    generate_random_mobile,
    generate_random_generic_text,
)
from wjx.core.questions.types.text import (
    vacant,
    MULTI_TEXT_DELIMITER,
    fill_text_question_input,
    fill_contenteditable_element,
    count_prefixed_text_inputs,
    count_visible_text_inputs,
    infer_text_entry_type,
    driver_question_is_location,
    should_mark_as_multi_text,
    should_treat_as_text_like,
)
from wjx.core.questions.types.single import single
from wjx.core.questions.types.multiple import (
    multiple,
    detect_multiple_choice_limit,
    detect_multiple_choice_limit_range,
)
from wjx.core.questions.types.dropdown import droplist
from wjx.core.questions.types.matrix import matrix
from wjx.core.questions.types.scale import scale
from wjx.core.questions.types.slider import slider_question, _resolve_slider_score
from wjx.core.questions.types.reorder import reorder, detect_reorder_required_count

__all__ = [
    # survey_parser
    "parse_survey_questions_from_html",
    "extract_survey_title_from_html",
    # captcha_handler
    "AliyunCaptchaBypassError",
    "EmptySurveySubmissionError",
    "handle_aliyun_captcha",
    "reset_captcha_popup_state",
    # question_utils
    "weighted_index",
    "normalize_probabilities",
    "normalize_droplist_probs",
    "normalize_single_like_prob_config",
    "normalize_option_fill_texts",
    "smooth_scroll_to_element",
    "fill_option_additional_text",
    "get_fill_text_from_config",
    "resolve_dynamic_text_token",
    "extract_text_from_element",
    "generate_random_chinese_name",
    "generate_random_mobile",
    "generate_random_generic_text",
    # question_text
    "vacant",
    "MULTI_TEXT_DELIMITER",
    "fill_text_question_input",
    "fill_contenteditable_element",
    "count_prefixed_text_inputs",
    "count_visible_text_inputs",
    "infer_text_entry_type",
    "driver_question_is_location",
    "should_mark_as_multi_text",
    "should_treat_as_text_like",
    # question_single
    "single",
    # question_multiple
    "multiple",
    "detect_multiple_choice_limit",
    "detect_multiple_choice_limit_range",
    # question_dropdown
    "droplist",
    # question_matrix
    "matrix",
    # question_scale
    "scale",
    # question_slider
    "slider_question",
    "_resolve_slider_score",
    # question_reorder
    "reorder",
    "detect_reorder_required_count",
]

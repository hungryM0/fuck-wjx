"""题目配置门面导出。"""

from software.core.questions.default_builder import build_default_question_entries
from software.core.questions.normalization import configure_probabilities
from software.core.questions.schema import (
    GLOBAL_RELIABILITY_DIMENSION,
    QuestionEntry,
    _TEXT_RANDOM_ID_CARD,
    _TEXT_RANDOM_ID_CARD_TOKEN,
    _TEXT_RANDOM_INTEGER,
    _TEXT_RANDOM_MOBILE,
    _TEXT_RANDOM_MOBILE_TOKEN,
    _TEXT_RANDOM_NAME,
    _TEXT_RANDOM_NAME_TOKEN,
    _TEXT_RANDOM_NONE,
    _infer_option_count,
)
from software.core.questions.validation import validate_question_config

__all__ = [
    "GLOBAL_RELIABILITY_DIMENSION",
    "QuestionEntry",
    "_TEXT_RANDOM_ID_CARD",
    "_TEXT_RANDOM_ID_CARD_TOKEN",
    "_TEXT_RANDOM_INTEGER",
    "_TEXT_RANDOM_MOBILE",
    "_TEXT_RANDOM_MOBILE_TOKEN",
    "_TEXT_RANDOM_NAME",
    "_TEXT_RANDOM_NAME_TOKEN",
    "_TEXT_RANDOM_NONE",
    "_infer_option_count",
    "build_default_question_entries",
    "configure_probabilities",
    "validate_question_config",
]

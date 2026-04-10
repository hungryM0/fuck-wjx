"""WizardSectionsMixin：各题型配置区 UI 构建方法，供 QuestionWizardDialog 通过多继承引入。"""
from typing import Any, Dict, List, Tuple

from .wizard_sections_common import (
    WizardSectionsCommonMixin,
    _TEXT_RANDOM_ID_CARD,
    _TEXT_RANDOM_ID_CARD_TOKEN,
    _TEXT_RANDOM_INTEGER,
    _TEXT_RANDOM_MOBILE,
    _TEXT_RANDOM_MOBILE_TOKEN,
    _TEXT_RANDOM_NAME,
    _TEXT_RANDOM_NAME_TOKEN,
    _TEXT_RANDOM_NONE,
    _apply_ai_label_state_style,
)
from .wizard_sections_matrix import WizardSectionsMatrixMixin
from .wizard_sections_slider import WizardSectionsSliderMixin
from .wizard_sections_text import WizardSectionsTextMixin


class WizardSectionsMixin(
    WizardSectionsCommonMixin,
    WizardSectionsTextMixin,
    WizardSectionsMatrixMixin,
    WizardSectionsSliderMixin,
):
    """各题型配置区 UI 构建方法。依赖 QuestionWizardDialog 的 state dict。"""

    text_container_map: Dict[int, Any]
    text_add_btn_map: Dict[int, Any]
    text_random_group_map: Dict[int, Any]
    text_random_list_radio_map: Dict[int, Any]
    text_random_name_check_map: Dict[int, Any]
    text_random_mobile_check_map: Dict[int, Any]
    text_random_id_card_check_map: Dict[int, Any]
    text_random_integer_check_map: Dict[int, Any]
    text_random_int_min_edit_map: Dict[int, Any]
    text_random_int_max_edit_map: Dict[int, Any]
    ai_check_map: Dict[int, Any]
    ai_label_map: Dict[int, Any]
    text_random_mode_map: Dict[int, str]
    text_edit_map: Dict[int, Any]
    info: List[Any]
    reliability_mode_enabled: bool
    matrix_row_slider_map: Dict[int, Any]
    entries: List[Any]
    slider_map: Dict[int, Any]
    bias_preset_map: Dict[int, Any]
    option_fill_edit_map: Dict[int, Any]
    option_fill_state_map: Dict[int, Any]

    def _get_entry_info(self, idx: int) -> Dict[str, Any]: ...
    def _resolve_matrix_weights(self, entry: Any, rows: int, columns: int) -> List[List[float]]: ...
    def _resolve_slider_bounds(self, idx: int, entry: Any) -> Tuple[int, int]: ...


__all__ = [
    "WizardSectionsMixin",
    "_TEXT_RANDOM_ID_CARD",
    "_TEXT_RANDOM_ID_CARD_TOKEN",
    "_TEXT_RANDOM_INTEGER",
    "_TEXT_RANDOM_MOBILE",
    "_TEXT_RANDOM_MOBILE_TOKEN",
    "_TEXT_RANDOM_NAME",
    "_TEXT_RANDOM_NAME_TOKEN",
    "_TEXT_RANDOM_NONE",
    "_apply_ai_label_state_style",
]

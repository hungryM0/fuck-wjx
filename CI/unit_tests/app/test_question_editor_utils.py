from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QLabel

from software.core.questions.config import QuestionEntry
from software.providers.contracts import SurveyQuestionMeta
from software.ui.pages.workbench.question_editor import utils as editor_utils
from software.ui.pages.workbench.question_editor import location_options


class _ColorLabel(QLabel):
    def __init__(self) -> None:
        super().__init__()
        self.colors = None

    def setTextColor(self, light, dark) -> None:
        self.colors = (light.name(), dark.name())

_APP = QApplication.instance() or QApplication([])


class QuestionEditorUtilsTests:
    def test_text_helpers_and_display_question_num(self) -> None:
        assert editor_utils._shorten_text("", 4) == ""
        assert editor_utils._shorten_text("abc", 4) == "abc"
        assert editor_utils._shorten_text("abcdef", 4) == "abc…"

        assert editor_utils._normalize_question_num("12") == 12
        assert editor_utils._normalize_question_num(None) is None
        assert editor_utils._normalize_question_num("x") is None

        assert editor_utils.resolve_display_question_num({"display_num": "9"}, fallback=1) == 9
        assert editor_utils.resolve_display_question_num({"num": "7"}, fallback=1) == 7
        assert editor_utils.resolve_display_question_num(SimpleNamespace(num="5"), fallback=1) == 5
        assert editor_utils.resolve_display_question_num({}, fallback="3") == 3

        assert editor_utils._normalize_question_title("  A B \n C\t") == "ABC"
        assert editor_utils._normalize_question_title(None) == ""

        assert editor_utils._normalize_provider_key("wjx", "qid") == ("wjx", "qid")
        assert editor_utils._normalize_provider_key("wjx", "") is None

    def test_apply_label_color_and_wrapped_text_label(self) -> None:
        label = _ColorLabel()
        editor_utils._apply_label_color(label, "#111111", "#222222")
        assert label.colors == ("#111111", "#222222")

        plain = QLabel()
        plain.setStyleSheet("font-size: 12px")
        editor_utils._apply_label_color(plain, "#333333", "#444444")
        assert "color: #333333;" in plain.styleSheet()

        editor_utils._configure_wrapped_text_label(plain, 88)
        assert plain.wordWrap() is True
        assert plain.width() == 88

    def test_build_entry_info_fallback_handles_text_and_fillable_options(self) -> None:
        entry = QuestionEntry(
            question_type="multi_text",
            probabilities=[1.0],
            texts=["a"],
            rows=2,
            option_count=4,
            distribution_mode="random",
            custom_weights=None,
            question_num=8,
            survey_provider="tencent",
            provider_question_id="qid-1",
            provider_page_id="page-1",
        )
        entry.question_title = "标题"
        entry.display_question_num = 88
        entry.fillable_option_indices = [1, 2, 2, -1, 7]
        entry.multi_text_blank_modes = ["a", "b", "c"]
        entry.multi_text_blank_ai_flags = [True]
        entry.multi_text_blank_int_ranges = []
        info = editor_utils._build_entry_info_fallback(entry)
        assert info.provider == "wjx"
        assert info.title == "标题"
        assert info.text_inputs == 3
        assert info.fillable_options == [1, 2]
        assert info.display_num == 88
        assert info.provider_question_id == "qid-1"
        assert info.provider_page_id == "page-1"

        text_entry = QuestionEntry(
            question_type="text",
            probabilities=[1.0],
            texts=["a"],
            rows=1,
            option_count=0,
            distribution_mode="random",
            custom_weights=None,
            question_num=2,
        )
        text_entry.question_title = "文本题"
        text_info = editor_utils._build_entry_info_fallback(text_entry)
        assert text_info.text_inputs == 1
        assert text_info.is_text_like is True

        location_entry = QuestionEntry(
            question_type="text",
            probabilities=[1.0],
            texts=["a"],
            rows=1,
            option_count=1,
            distribution_mode="random",
            custom_weights=None,
            question_num=3,
            is_location=True,
        )
        location_info = editor_utils._build_entry_info_fallback(location_entry)
        assert location_info.is_location is True
        assert location_info.text_inputs == 0
        assert location_info.is_text_like is False

    def test_build_entry_info_list_prefers_provider_num_title_then_fallback(self) -> None:
        entry1 = QuestionEntry(
            question_type="single",
            probabilities=[1.0],
            texts=None,
            rows=1,
            option_count=3,
            distribution_mode="random",
            custom_weights=None,
            question_num=1,
            survey_provider="wjx",
            provider_question_id="qid-1",
        )
        entry1.question_title = "题目一"

        entry2 = QuestionEntry(
            question_type="text",
            probabilities=[1.0],
            texts=["a"],
            rows=1,
            option_count=1,
            distribution_mode="random",
            custom_weights=None,
            question_num=2,
        )
        entry2.question_title = "题目二"

        entry3 = QuestionEntry(
            question_type="multiple",
            probabilities=[1.0],
            texts=None,
            rows=1,
            option_count=2,
            distribution_mode="random",
            custom_weights=None,
            question_num=9,
        )
        entry3.question_title = "题目 三"

        info_by_provider = SurveyQuestionMeta(
            num=99,
            title="别的",
            provider="wjx",
            provider_question_id="qid-1",
        )
        info_by_num = SurveyQuestionMeta(num=2, title="二号题")
        info_by_title = SurveyQuestionMeta(num=8, title="题目三")
        skipped_description = SurveyQuestionMeta(num=7, title="描述", is_description=True)
        aligned = editor_utils.build_entry_info_list(
            [entry1, entry2, entry3],
            [info_by_provider, info_by_num, info_by_title, skipped_description],
        )
        assert aligned[0].provider_question_id == "qid-1"
        assert aligned[1].num == 2
        assert aligned[2].title == "题目三"

        fallback = editor_utils.build_entry_info_list([entry3], None)
        assert fallback[0].title == "题目 三"

    def test_load_location_provinces_includes_three_level_tree(self) -> None:
        provinces = location_options.load_location_provinces()
        beijing = next(item for item in provinces if item["name"] == "北京市")
        assert beijing["display_name"] == "北京"
        assert len(beijing["cities"]) == 1
        city = beijing["cities"][0]
        assert city["display_name"] == "北京市"
        assert len(city["areas"]) == 16
        assert city["areas"][0]["name"] == "东城区"

    def test_load_location_provinces_uses_cache_and_returns_isolated_copy(self, monkeypatch) -> None:
        calls: list[object] = []
        payload = [
            {
                "code": "110000",
                "name": "北京市",
                "children": [{"name": "东城区"}],
            }
        ]
        location_options._load_location_provinces_cached.cache_clear()
        monkeypatch.setattr(location_options, "_read_location_tree", lambda: calls.append(object()) or payload)

        first = location_options.load_location_provinces()
        first[0]["name"] = "已污染"
        second = location_options.load_location_provinces()

        assert len(calls) == 1
        assert second[0]["name"] == "北京市"
        location_options._load_location_provinces_cached.cache_clear()

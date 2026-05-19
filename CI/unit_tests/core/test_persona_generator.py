from __future__ import annotations

from software.core.persona import generator
from software.core.persona.generator import Persona


class PersonaGeneratorTests:
    def test_persona_keyword_map_and_description_cover_all_attributes(self) -> None:
        persona = Persona(
            gender="女",
            age_group="26-35",
            education="研究生及以上",
            occupation="自由职业",
            income_level="高",
            marital_status="已婚",
            has_children=True,
        )

        mapping = persona.to_keyword_map()
        description = persona.to_description()

        assert "女性" in mapping["gender"]
        assert "30岁" in mapping["age_group"]
        assert "硕士" in mapping["education"]
        assert "个体户" in mapping["occupation"]
        assert "高收入" in mapping["income_level"]
        assert "结婚" in mapping["marital_status"]
        assert "有子女" in mapping["has_children"]
        assert description == "女性、26-35岁、学历研究生及以上、自由职业、收入较高、已婚、有孩子"

    def test_persona_defaults_return_empty_mapping_and_generic_description(self) -> None:
        persona = Persona()

        assert persona.to_keyword_map() == {"no_children": ["无子女", "无孩子", "未育", "没有孩子", "没有小孩"]}
        assert persona.to_description() == "一名普通用户"

    def test_generate_persona_respects_young_student_constraints(self, monkeypatch) -> None:
        choices = iter(["18-25", "本科", "学生", "低", "未婚"])
        monkeypatch.setattr(generator.random, "choice", lambda values: values[0])
        monkeypatch.setattr(generator.random, "choices", lambda *_args, **_kwargs: [next(choices)])
        monkeypatch.setattr(generator.random, "random", lambda: 0.5)
        monkeypatch.setattr(generator.random, "gauss", lambda *_args: 0.02)

        persona = generator.generate_persona()

        assert persona.gender == "男"
        assert persona.age_group == "18-25"
        assert persona.occupation == "学生"
        assert persona.income_level == "低"
        assert persona.marital_status == "未婚"
        assert persona.has_children is False
        assert persona.satisfaction_tendency == 0.1

    def test_generate_persona_respects_older_retired_constraints(self, monkeypatch) -> None:
        choices = iter(["46-60", "高中及以下", "退休", "中", "已婚"])
        monkeypatch.setattr(generator.random, "choice", lambda values: values[-1])
        monkeypatch.setattr(generator.random, "choices", lambda *_args, **_kwargs: [next(choices)])
        monkeypatch.setattr(generator.random, "random", lambda: 0.01)
        monkeypatch.setattr(generator.random, "gauss", lambda *_args: 2.0)

        persona = generator.generate_persona()

        assert persona.gender == "女"
        assert persona.age_group == "46-60"
        assert persona.occupation == "退休"
        assert persona.income_level == "中"
        assert persona.marital_status == "已婚"
        assert persona.has_children is True
        assert persona.satisfaction_tendency == 0.9

    def test_thread_local_persona_lifecycle(self) -> None:
        generator.reset_persona()
        assert generator.get_current_persona() is None

        persona = Persona(gender="男")
        generator.set_current_persona(persona)
        assert generator.get_current_persona() is persona

        generator.reset_persona()
        assert generator.get_current_persona() is None

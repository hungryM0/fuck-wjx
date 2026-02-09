"""虚拟画像生成器 - 每份问卷自动生成一个逻辑自洽的虚拟人物

画像在每份问卷开始时随机生成，各属性之间有逻辑约束，
确保不会出现"18岁已退休"或"未婚有三个孩子"这类矛盾。
"""
import random
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Persona:
    """虚拟人物画像"""
    gender: str = ""                    # "男" / "女"
    age_group: str = ""                 # "18-25" / "26-35" / "36-45" / "46-60"
    education: str = ""                 # "高中及以下" / "大专" / "本科" / "研究生及以上"
    occupation: str = ""                # "学生" / "上班族" / "自由职业" / "退休"
    income_level: str = ""              # "低" / "中" / "高"
    marital_status: str = ""            # "未婚" / "已婚"
    has_children: bool = False
    satisfaction_tendency: float = 0.5  # 整体满意倾向 0.0~1.0（越高越倾向正面评价）

    def to_keyword_map(self) -> Dict[str, List[str]]:
        """将画像转换为关键词映射表，用于与选项文本匹配。

        返回 {属性名: [该属性对应的关键词列表]}。
        """
        mapping: Dict[str, List[str]] = {}
        if self.gender:
            mapping["gender"] = (
                ["男", "男性", "先生", "男生"]
                if self.gender == "男"
                else ["女", "女性", "女士", "女生"]
            )
        if self.age_group:
            age_keywords = {
                "18-25": ["18", "19", "20", "21", "22", "23", "24", "25",
                           "18-25", "18~25", "18岁", "20岁", "大学", "青年"],
                "26-35": ["26", "27", "28", "29", "30", "31", "32", "33", "34", "35",
                           "26-35", "26~35", "30岁", "青年", "中青年"],
                "36-45": ["36", "37", "38", "39", "40", "41", "42", "43", "44", "45",
                           "36-45", "36~45", "40岁", "中年"],
                "46-60": ["46", "47", "48", "49", "50", "51", "52", "53", "54", "55",
                           "56", "57", "58", "59", "60",
                           "46-60", "46~60", "50岁", "中年", "中老年"],
            }
            mapping["age_group"] = age_keywords.get(self.age_group, [])
        if self.education:
            edu_keywords = {
                "高中及以下": ["高中", "初中", "中专", "职高", "小学", "高中及以下",
                             "高中以下", "中学"],
                "大专": ["大专", "专科", "高职"],
                "本科": ["本科", "大学", "学士", "大学本科"],
                "研究生及以上": ["研究生", "硕士", "博士", "博士后", "研究生及以上",
                              "硕士及以上"],
            }
            mapping["education"] = edu_keywords.get(self.education, [])
        if self.occupation:
            occ_keywords = {
                "学生": ["学生", "在校", "在读", "校园"],
                "上班族": ["上班", "在职", "企业", "公司", "职员", "白领",
                          "员工", "工作", "在职人员"],
                "自由职业": ["自由职业", "自由", "个体", "创业", "自营",
                           "个体户", "自由职业者"],
                "退休": ["退休", "离退休", "退休人员"],
            }
            mapping["occupation"] = occ_keywords.get(self.occupation, [])
        if self.income_level:
            income_keywords = {
                "低": ["3000以下", "3000元以下", "5000以下", "5000元以下",
                       "低收入", "无收入", "2000以下"],
                "中": ["5000-10000", "5000~10000", "5001-10000",
                       "10000-20000", "10000~20000", "万元", "中等收入",
                       "1万", "一万"],
                "高": ["20000以上", "20000元以上", "2万以上", "3万以上",
                       "50000以上", "高收入", "5万"],
            }
            mapping["income_level"] = income_keywords.get(self.income_level, [])
        if self.marital_status:
            mapping["marital_status"] = (
                ["未婚", "单身", "恋爱", "未婚/单身"]
                if self.marital_status == "未婚"
                else ["已婚", "已婚已育", "已婚未育", "结婚"]
            )
        # 子女
        if self.has_children:
            mapping["has_children"] = ["有孩子", "有子女", "已育", "有小孩"]
        else:
            mapping["no_children"] = ["无子女", "无孩子", "未育", "没有孩子", "没有小孩"]
        return mapping

    def to_description(self) -> str:
        """生成画像的自然语言描述，用于 AI prompt。"""
        parts = []
        if self.gender:
            parts.append(f"{self.gender}性")
        if self.age_group:
            parts.append(f"{self.age_group}岁")
        if self.education:
            parts.append(f"学历{self.education}")
        if self.occupation:
            parts.append(self.occupation)
        if self.income_level:
            income_text = {"低": "收入较低", "中": "收入中等", "高": "收入较高"}
            parts.append(income_text.get(self.income_level, ""))
        if self.marital_status:
            parts.append(self.marital_status)
        if self.has_children:
            parts.append("有孩子")
        if not parts:
            return "一名普通用户"
        return "、".join(parts)


# ── 画像生成 ──────────────────────────────────────────────


def generate_persona() -> Persona:
    """随机生成一个逻辑自洽的虚拟人物画像。

    属性之间的约束规则：
    - 18-25岁大概率是学生或初入职场，低收入，未婚无子女
    - 26-35岁可能已婚可能未婚，收入中等
    - 36-45岁大概率已婚，可能有子女
    - 46-60岁大概率已婚有子女，可能退休
    - 学生一般低收入
    - 退休一般46-60岁
    """
    p = Persona()

    # 性别
    p.gender = random.choice(["男", "女"])

    # 年龄组（加权：年轻人更多一些）
    p.age_group = random.choices(
        ["18-25", "26-35", "36-45", "46-60"],
        weights=[35, 35, 20, 10],
        k=1,
    )[0]

    # 学历（受年龄影响）
    if p.age_group == "18-25":
        p.education = random.choices(
            ["高中及以下", "大专", "本科", "研究生及以上"],
            weights=[15, 20, 50, 15],
            k=1,
        )[0]
    elif p.age_group in ("26-35", "36-45"):
        p.education = random.choices(
            ["高中及以下", "大专", "本科", "研究生及以上"],
            weights=[10, 20, 45, 25],
            k=1,
        )[0]
    else:
        p.education = random.choices(
            ["高中及以下", "大专", "本科", "研究生及以上"],
            weights=[25, 25, 35, 15],
            k=1,
        )[0]

    # 职业（受年龄影响）
    if p.age_group == "18-25":
        p.occupation = random.choices(
            ["学生", "上班族", "自由职业"],
            weights=[55, 35, 10],
            k=1,
        )[0]
    elif p.age_group == "46-60":
        p.occupation = random.choices(
            ["上班族", "自由职业", "退休"],
            weights=[50, 25, 25],
            k=1,
        )[0]
    else:
        p.occupation = random.choices(
            ["上班族", "自由职业"],
            weights=[75, 25],
            k=1,
        )[0]

    # 收入（受职业和年龄影响）
    if p.occupation == "学生":
        p.income_level = random.choices(["低", "中"], weights=[85, 15], k=1)[0]
    elif p.occupation == "退休":
        p.income_level = random.choices(["低", "中", "高"], weights=[30, 50, 20], k=1)[0]
    elif p.age_group in ("36-45", "46-60"):
        p.income_level = random.choices(["低", "中", "高"], weights=[15, 45, 40], k=1)[0]
    elif p.age_group == "26-35":
        p.income_level = random.choices(["低", "中", "高"], weights=[20, 50, 30], k=1)[0]
    else:
        p.income_level = random.choices(["低", "中", "高"], weights=[40, 45, 15], k=1)[0]

    # 婚姻状况（受年龄影响）
    if p.age_group == "18-25":
        p.marital_status = random.choices(["未婚", "已婚"], weights=[90, 10], k=1)[0]
    elif p.age_group == "26-35":
        p.marital_status = random.choices(["未婚", "已婚"], weights=[45, 55], k=1)[0]
    elif p.age_group == "36-45":
        p.marital_status = random.choices(["未婚", "已婚"], weights=[15, 85], k=1)[0]
    else:
        p.marital_status = random.choices(["未婚", "已婚"], weights=[10, 90], k=1)[0]

    # 子女（受婚姻和年龄影响）
    if p.marital_status == "未婚":
        p.has_children = random.random() < 0.03  # 极小概率
    elif p.age_group in ("36-45", "46-60"):
        p.has_children = random.random() < 0.90
    elif p.age_group == "26-35":
        p.has_children = random.random() < 0.50
    else:
        p.has_children = random.random() < 0.10

    # 满意度倾向（正态分布，均值0.6，偏向中等偏上）
    raw = random.gauss(0.6, 0.15)
    p.satisfaction_tendency = max(0.1, min(0.9, raw))

    return p


# ── 线程局部画像管理 ────────────────────────────────────────

_thread_local = threading.local()


def set_current_persona(persona: Persona) -> None:
    """为当前线程设置画像（每份问卷开始时调用）。"""
    _thread_local.persona = persona


def get_current_persona() -> Optional[Persona]:
    """获取当前线程的画像。"""
    return getattr(_thread_local, "persona", None)


def reset_persona() -> None:
    """清除当前线程的画像（问卷结束后调用）。"""
    _thread_local.persona = None

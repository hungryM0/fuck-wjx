# Excel 数据处理模块

数据反填功能的核心数据处理层，负责 Excel 文件读取、题目映射、答案标准化和样本校验。

## 模块结构

```
software/io/excel/
├── __init__.py          # 模块导出
├── schema.py            # 数据结构定义
├── reader.py            # Excel 文件读取器
├── mapper.py            # 题目映射器
├── normalizer.py        # 答案标准化器
├── validator.py         # 样本校验器
└── README.md            # 本文档
```

## 核心功能

### 1. ExcelReader - Excel 文件读取

读取 Excel 文件，第一行为列头（题目标题），后续行为样本数据。

```python
from software.io.excel import ExcelReader

reader = ExcelReader()
samples = reader.read("data.xlsx")

# samples: list[SampleRow]
# 每个 SampleRow 包含：
# - row_no: 行号
# - values: {列名: 单元格值}
# - status: "pending" / "running" / "success" / "failed"
```

### 2. QuestionMatcher - 题目自动映射

按优先级自动匹配 Excel 列到问卷题目：

1. **题号匹配**（置信度 1.0）：Q1、1、、1. 等
2. **标题精确匹配**（置信度 0.98）：标准化后完全一致
3. **模糊匹配**（置信度 ≥ 0.9）：相似度 ≥ 90%
4. **否则报错**：不猜测，直接阻止执行

```python
from software.io.excel import QuestionMatcher

matcher = QuestionMatcher(fuzzy_threshold=90.0)
plan = matcher.build_mapping(excel_columns, survey_schema)

# plan.items: list[MappingItem]
# 每个 MappingItem 包含：
# - excel_col: Excel 列名
# - survey_qid: 问卷题目 ID
# - mode: "by_index" / "by_title_exact" / "by_title_fuzzy"
# - confidence: 匹配置信度
```

### 3. AnswerNormalizer - 答案标准化

按优先级标准化答案：

1. **选项文本精确匹配**
2. **别名表匹配**（选项自定义别名）
3. **全局别名映射**（内置常见别名）
4. **量表数值映射**（7 级 / 5 级量表）
5. **模糊匹配**（相似度 ≥ 90%）
6. **否则报错**

```python
from software.io.excel import AnswerNormalizer

normalizer = AnswerNormalizer(fuzzy_threshold=90.0)
answer = normalizer.normalize_answer(question, raw_value)

# 支持的题型：
# - single_choice: 单选题
# - multi_choice: 多选题（逗号、分号、顿号分隔）
# - scale: 量表题
# - text: 文本题
```

#### 内置别名

```python
# 是/否
"是" -> ["是", "yes", "y", "1", "true", "对"]
"否" -> ["否", "no", "n", "0", "false", "错"]

# 性别
"男" -> ["男", "male", "m", "先生", "boy"]
"女" -> ["女", "female", "f", "女士", "girl"]

# 7 级量表（同意度）
1 -> "非常不同意"
2 -> "不同意"
3 -> "有点不同意"
4 -> "中立"
5 -> "有点同意"
6 -> "同意"
7 -> "非常同意"

# 5 级量表（满意度）
1 -> "非常不满意"
2 -> "不满意"
3 -> "一般"
4 -> "满意"
5 -> "非常满意"
```

### 4. SampleValidator - 样本校验

校验并标准化所有样本，支持资格题逻辑。

```python
from software.io.excel import SampleValidator

validator = SampleValidator(normalizer)

# 校验并标准化
validator.validate_and_normalize(
    samples, 
    survey_schema, 
    mapping_plan,
    qualification_rules={"Q1": ["否"], "Q2": ["否"]}  # 可选
)

# 获取摘要
summary = validator.get_validation_summary(samples)
# {
#     "total": 100,
#     "success": 95,
#     "failed": 5,
#     "failed_details": [...]
# }
```

## 数据结构

### SurveySchema - 问卷结构

```python
from software.io.excel import SurveySchema, QuestionSchema, OptionSchema

survey = SurveySchema(
    title="测试问卷",
    questions=[
        QuestionSchema(
            qid="Q1",
            index=1,
            title="您的性别",
            qtype="single_choice",
            required=True,
            options=[
                OptionSchema(text="男", aliases=["male", "m"]),
                OptionSchema(text="女", aliases=["female", "f"]),
            ]
        ),
        # ...
    ]
)
```

### SampleRow - 样本行

```python
from software.io.excel import SampleRow

sample = SampleRow(
    row_no=2,
    values={"Q1": "男", "Q2": "18-25岁"},
    normalized_answers={},  # 标准化后填充
    status="pending",       # pending / running / success / failed
    error=None              # 错误信息
)
```

## 使用示例

完整工作流程：

```python
from software.io.excel import (
    ExcelReader,
    QuestionMatcher,
    AnswerNormalizer,
    SampleValidator,
)

# 1. 读取 Excel
reader = ExcelReader()
samples = reader.read("data.xlsx")

# 2. 建立映射
matcher = QuestionMatcher()
excel_columns = list(samples[0].values.keys())
plan = matcher.build_mapping(excel_columns, survey_schema)

# 3. 校验并标准化
normalizer = AnswerNormalizer()
validator = SampleValidator(normalizer)
validator.validate_and_normalize(samples, survey_schema, plan)

# 4. 获取结果
success_samples = [s for s in samples if s.status == "pending"]
failed_samples = [s for s in samples if s.status == "failed"]

print(f"成功: {len(success_samples)}, 失败: {len(failed_samples)}")
```

## 测试

运行单元测试：

```bash
# 激活环境
conda activate spider

# 运行所有测试
python tests/test_excel_reader.py
python tests/test_mapper.py
python tests/test_normalizer.py
python tests/test_validator.py

# 运行完整工作流程测试
python tests/test_full_workflow.py
```

## 依赖

- `openpyxl`: Excel 文件读写
- `rapidfuzz`: 模糊字符串匹配

已添加到 `requirements.txt`。

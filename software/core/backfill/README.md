# 数据反填模块

数据反填功能的样本分发层，负责线程安全的样本分配和状态管理。

## 模块结构

```
software/core/backfill/
├── __init__.py          # 模块导出
├── dispatcher.py        # 样本分发器
└── README.md            # 本文档
```

## 核心功能

### SampleDispatcher - 样本分发器

线程安全地分发样本，确保每行只被消费一次。支持并发场景下的样本分配、状态更新和统计。

#### 初始化

```python
from software.core.backfill import SampleDispatcher
from software.io.excel import SampleRow

# 创建待处理样本列表
samples = [
    SampleRow(row_no=2, values={"Q1": "A"}, status="pending"),
    SampleRow(row_no=3, values={"Q1": "B"}, status="pending"),
    # ...
]

# 创建分发器
dispatcher = SampleDispatcher(samples)
```

#### 基本操作

```python
# 1. 取下一个待处理样本（线程安全）
sample = dispatcher.next_sample()
if sample is None:
    # 没有待处理样本了
    break

# 此时 sample.status 已自动从 "pending" 改为 "running"

# 2. 标记成功
dispatcher.mark_success(sample)

# 3. 标记失败（不重试）
dispatcher.mark_failed(sample, "错误信息", retry=False)

# 4. 标记失败（允许重试）
dispatcher.mark_failed(sample, "错误信息", retry=True)
```

#### 统计信息

```python
# 获取实时统计
stats = dispatcher.get_stats()
# {
#     "total": 100,        # 总样本数
#     "pending": 20,       # 待处理数
#     "running": 5,        # 运行中数
#     "success": 70,       # 成功数
#     "failed": 5,         # 失败数
#     "progress": 75.0     # 进度百分比（0-100）
# }
```

#### 辅助方法

```python
# 检查是否还有待处理样本
if dispatcher.has_pending():
    print("还有样本待处理")

# 检查是否所有样本都已完成
if dispatcher.is_completed():
    print("所有样本已处理完成")

# 获取失败样本列表
failed_samples = dispatcher.get_failed_samples()

# 获取成功样本列表
success_samples = dispatcher.get_success_samples()

# 重置失败样本为待处理状态（用于重试）
dispatcher.reset_failed_samples()
```

## 线程安全性

`SampleDispatcher` 使用 `threading.Lock` 确保所有操作都是线程安全的：

- `next_sample()`: 原子性地取出样本并标记为 running
- `mark_success()` / `mark_failed()`: 原子性地更新样本状态
- `get_stats()`: 原子性地读取统计信息
- 所有辅助方法都是线程安全的

### 并发使用示例

```python
import threading
from software.core.backfill import SampleDispatcher

def worker(dispatcher: SampleDispatcher, thread_id: int):
    """工作线程函数。"""
    while True:
        # 线程安全地取样本
        sample = dispatcher.next_sample()
        if sample is None:
            break
        
        try:
            # 处理样本
            process_sample(sample)
            
            # 标记成功
            dispatcher.mark_success(sample)
        except Exception as e:
            # 标记失败
            dispatcher.mark_failed(sample, str(e), retry=False)

# 创建分发器
dispatcher = SampleDispatcher(samples)

# 启动多个工作线程
threads = []
for i in range(10):
    t = threading.Thread(target=worker, args=(dispatcher, i))
    t.start()
    threads.append(t)

# 等待所有线程完成
for t in threads:
    t.join()

# 获取最终统计
stats = dispatcher.get_stats()
print(f"成功: {stats['success']}, 失败: {stats['failed']}")
```

## 状态转换

样本状态的转换流程：

```
pending → running → success
                 → failed
                 → pending (retry=True)
```

- `pending`: 待处理
- `running`: 正在处理
- `success`: 处理成功
- `failed`: 处理失败

## 重试机制

支持两种失败处理方式：

1. **不重试**：`mark_failed(sample, error, retry=False)`
   - 样本状态变为 `failed`
   - 不会再被 `next_sample()` 返回

2. **允许重试**：`mark_failed(sample, error, retry=True)`
   - 样本状态变回 `pending`
   - 会被 `next_sample()` 再次返回

3. **批量重置**：`reset_failed_samples()`
   - 将所有 `failed` 样本重置为 `pending`
   - 用于全局重试失败样本

## 进度追踪

进度计算公式：

```python
progress = (success + failed) / total * 100
```

- 只有 `success` 和 `failed` 状态的样本才算完成
- `pending` 和 `running` 状态的样本不算完成
- 进度范围：0.0 - 100.0

## 测试

运行测试：

```bash
conda activate spider
python tests/test_dispatcher.py
```

测试覆盖：
- ✓ 基本操作（取样本、标记状态、统计）
- ✓ 线程安全性（10 个线程并发处理 100 个样本）
- ✓ 重试机制（失败重试、批量重置）
- ✓ 辅助方法（has_pending、is_completed、get_failed_samples 等）

## 性能

在测试中，10 个线程并发处理 100 个样本：
- 耗时：约 0.02 秒
- 无重复处理
- 无样本丢失
- 线程间负载均衡

## 使用场景

`SampleDispatcher` 适用于以下场景：

1. **多线程填写问卷**：多个浏览器实例并发填写
2. **失败重试**：自动或手动重试失败样本
3. **进度监控**：实时显示处理进度
4. **结果统计**：统计成功/失败数量

## 与其他模块的集成

```python
from software.io.excel import (
    ExcelReader,
    QuestionMatcher,
    AnswerNormalizer,
    SampleValidator,
)
from software.core.backfill import SampleDispatcher

# 1. 读取并校验样本
reader = ExcelReader()
samples = reader.read("data.xlsx")

matcher = QuestionMatcher()
plan = matcher.build_mapping(excel_columns, survey_schema)

normalizer = AnswerNormalizer()
validator = SampleValidator(normalizer)
validator.validate_and_normalize(samples, survey_schema, plan)

# 2. 创建分发器（只包含成功校验的样本）
valid_samples = [s for s in samples if s.status == "pending"]
dispatcher = SampleDispatcher(valid_samples)

# 3. 多线程处理
# ... (见上面的并发使用示例)
```

## 注意事项

1. **初始状态**：传入的样本应该都是 `status="pending"` 的
2. **线程安全**：所有方法都是线程安全的，可以放心在多线程环境使用
3. **状态一致性**：不要在外部直接修改样本状态，应该通过分发器的方法修改
4. **内存占用**：所有样本都保存在内存中，大量样本时注意内存使用

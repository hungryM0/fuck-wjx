# 问卷星网页结构与解析指南

本文档供 SurveyController 项目贡献者参考。当需要修改问卷星解析逻辑、新增题型支持或调试配置识别问题时，请按此文档指导逐步排查。

## 核心原则

问卷星页面识别不能只看单一层面，必须同时验证**三个维度**：

| 维度 | 检查内容 | 直接影响 |
|------|---------|---------|
| **页面骨架** | 是否多页、题目所在容器 | 分页逻辑是否正确 |
| **题目节点** | DOM 中的 `type`、`topic`、选项结构 | 题型识别是否准确 |
| **逻辑属性** | `jumpto`、`hasjump`、`relation` 等 | 分支流程是否拓扑正确 |

**忽视任何一层都容易引入错误。** 下文逐层说明。

---

## 章1：顶层结构识别

### 1.1 主容器与检查清单

问卷题目的主要 HTML 容器是：

```html
<div id="divQuestion">
  <!-- 单页：题目直接在此 -->
  <!-- 多页：题目分别在各 fieldset 中 -->
</div>
```

**快速检查：** 打开浏览器控制台执行：
```javascript
document.querySelector('#divQuestion') // 应返回元素，而非 null
```

**找不到 `#divQuestion` 时的诊断：**

| 症状 | 可能原因 | 解决方案 |
|------|---------|---------|
| null 返回 | 页面仍在加载 | 等待 DOM 完全加载后重试 |
| null 返回 | 模板版本过新 | 更新解析规则以适配新模板 |
| null 返回 | 非答题页 | 确认当前页面是否为答题正文 |

详见代码：[html_parser.py L1456](../wjx/provider/html_parser.py#L1456)

### 1.2 多页问卷的分页标记

问卷星采用 `fieldset` 元素实现分页：

```html
<div id="divQuestion">
  <fieldset id="fieldset1"><!-- 第1页题目 --></fieldset>
  <fieldset id="fieldset2"><!-- 第2页题目 --></fieldset>
  <fieldset id="fieldset3"><!-- 第3页题目 --></fieldset>
</div>
```

**关键规则：**
- 每个 `fieldset` 代表问卷的一个独立页面
- 通过 `fieldset` 元素的数量可直接获得总页数
- 相同 `fieldset` 内所有题目必然属于同一页

**实现位置：**
- 🔍 静态解析：[html_parser.py L1459](../wjx/provider/html_parser.py#L1459)
- ⚙️ 运行时检测：[detection.py L11](../wjx/provider/detection.py#L11)

**错误分页的后果（改之前 vs 改之后）：**
- ❌ 改之前：把所有题当成一页 → 误判页数 → 下一页按钮逻辑乱掉
- ✅ 改之后：按 `fieldset` 切页 → 配置向导和运行时都能正确识别"第几页有几题"

### 1.3 动态页面的回退识别

并非所有问卷都提供完整的 `fieldset` 标记。少数页面采用动态渲染或非标准模板。此时需按优先级回退：

**识别优先级：**
1. **首选** — `fieldset` 元素统计
2. **其次** — 扫描所有含 `[topic]` 属性的元素
3. **保底** — 识别 `.div_question`、`.question`、`.wjx_question` 等通用题型容器

代码逻辑：[detection.py L20](../wjx/provider/detection.py#L20)

**设计原则** — 防止页面布局细微变化导致错误判定为空问卷。

---

## 章2：单题节点识别

### 2.1 基本属性与 DOM 结构

单个题目在 DOM 中的典型结构：

```html
<div class="field" topic="1" id="div1" type="3" req="0" relation="" hasjump="0">
  <!-- 题干内容 -->
  <!-- 选项节点 -->
</div>
```

**属性速查表：**

| 属性 | 含义 | 值例 | 用途 |
|------|------|------|------|
| `topic` | 题目编号 | 1, 2, ... | 唯一标识题目（最可靠） |
| `id` | 元素ID | div1, div2 | 样式和脚本绑定 |
| `type` | 题型代码 | 3~8 等 | 初步判断题型（见章3） |
| `req` | 必填标记 | 0, 1 | 题目是否强制作答 |
| `relation` | 显示条件 | 6,1;2 | 该题何时显示（见章6） |
| `hasjump` | 跳题标记 | 0, 1 | 是否包含跳转逻辑（见章6） |

解析实现：[html_parser.py L1461](../wjx/provider/html_parser.py#L1461)

### 2.2 为什么优先用 `topic` 而非视觉题号

**❌ 错误做法：** 从题干文本中提取"第1题、第2题"

**✓ 正确做法：** 优先读 `topic` 属性

**理由：**
- 问卷常含**说明文本**、**分割线**、**媒体展示**等非题目内容
- 显示的题号与实际题号**可能不一致**（尤其是有逻辑跳转时）
- 富文本格式可能将题号编号打散（如"1."被拆成多个 HTML 节点）

**项目实践：**
```python
# 第一步：提取编号
actual_topic = div.get_attribute('topic')  # "1", "2", ...

# 第二步：补充显示题号（可选）
display_num = extract_display_number_from_text(title)  # "1.", "2.", ...
```

代码参考：[html_parser.py L1465](../wjx/provider/html_parser.py#L1465)

---

## 章3：题型识别规则

### 3.1 第一层：`type` 属性的初步判断

大多数题型可从题根节点的 `type` 属性初步推断：

| type 值 | 常见对应题型 | 说明 |
|---------|------------|------|
| 3 | 单选题 | 单一选择 |
| 4 | 多选题 | 多项勾选 |
| 5 | 量表/评价题 | 星级、满意度等 |
| 6 | 矩阵类 | 行列结构 |
| 8 | 滑块题 | 数值输入 |
| 其他 | 需结合 DOM 特征 | 见3.2 |

**⚠️ 重要提醒：** `type` **不是绝对真理**。问卷星同一个 `type` 值下可能长出不同的视觉结构。仅靠数字判断会导致误认。

### 3.2 第二层：选项与特征节点的兜底判断

当 `type` 与实际页面结构有歧义时，通过**特征元素**做更精准的判断：

**兜底识别规则：**

| 题型 | 检查的特征节点 | 代码位置 |
|------|-------------|---------|
| 排序题 | `.sortnum`、`.order-index`、`.ui-sortable` | [L1438](../wjx/provider/html_parser.py#L1438) |
| 数字量表/NPS | 大量数字刻度 + 两端文字标签 | [L1264](../wjx/provider/html_parser.py#L1264) |
| 星级评价 | `.rate-off`、`.rate-on`、`.evaluateTagWrap` | [L1381](../wjx/provider/html_parser.py#L1381) |
| 滑块矩阵 | 矩阵容器 + `<input type="range">` | [L1438](../wjx/provider/html_parser.py#L1438) |

**诊断顺序（强烈推荐）：**
1. 查看题根节点的 `type` 值
2. 查看该题内是否包含单选、多选、矩阵、滑块、排序的**特征元素**
3. 若 `type` 与 DOM 特征冲突，**优先相信更具体的 DOM 特征**

**反例（常见错误）：**
- ❌ 题目 type=5，但含 `.ui-sortable`→ 应识别为排序题，不是量表
- ❌ 题目 type=4，但只有单个 `<input type="radio">`→ 应识别为单选题，不是多选

### 3.3 识别单选/多选时的隐藏 Input 陷阱

问卷星移动端常将真实的 `<input>` 元素隐藏，外层包裹样式壳：

```html
<!-- 隐藏的实际 input -->
<input type="radio" class="hidden" />

<!-- 可见的样式壳（用户看到并点击的） -->
<label class="ui-radio">选项A</label>
<label class="ui-radio">选项B</label>
```

**影响范围：**
- ✓ 静态 HTML 解析：直接读 `<input>` 即可识别
- ❌ 自动化点击：不能假设 `<input>` 本身可见可点

**正确做法：**
- 解析阶段：扫描实际的 `<input>` 元素获得 true/false 信息
- 点击阶段：点击**包裹元素**（`.ui-radio`、`.ui-checkbox`）而非 input 本身

---

## 章4：问卷结构识别

### 4.1 静态 HTML 解析的基础流程

项目的静态 HTML 解析采用以下步骤：

```text
1. 定位 #divQuestion 容器
   ↓
2. 扫描所有 <fieldset> 标签（确定页数）
   ↓
3. 对每个 fieldset
   ├─ 找所有带 [topic] 属性的题目节点
   └─ 对每道题提取：
      ├─ 题号（topic）
      ├─ 显示题号（提取自题干文本）
      ├─ 标题
      ├─ 原始 type
      ├─ 选项数和选项文本
      ├─ 所属页码
      ├─ 跳题逻辑（有无）
      ├─ 条件显示逻辑（有无）
      └─ ...其他属性
```

代码实现：[html_parser.py L1448](../wjx/provider/html_parser.py#L1448)

### 4.2 为什么每题都要记录 page 字段
`page` 字段不是装饰，直接影响运行时行为：

**会被用到的场景：**
- 🔧 **配置向导** — 告诉用户"这题在第几页"
- ⚙️ **运行时引擎** — 知道应该什么时候翻页取题
- 🐛 **排查问题** — 诊断"为什么翻页后没看到题"

**改之前 vs 改之后：**
- ❌ 改之前：不保存 page → 配置看着正常 → 运行时在错的时机找题 → 用户看"脚本卡住了"
- ✅ 改之后：精确记录 page → 各模块知道题的确切位置 → 流程通畅

---

## 章5：复杂逻辑识别

本章分**两类**逻辑。理解区别至关重要。

### 5.1 硬跳题：直接跳离某些题目

**定义：** 用户选择某个选项后，直接跳到别的题/结束问卷，中间题目被跳过。

**DOM标记：**
- 题节点上：`hasjump='1'`
- 选项节点上：`jumpto` 或 `data-jumpto` 属性

**代码位置：** [html_parser.py L1013](../wjx/provider/html_parser.py#L1013)

**提取结果落到：**
- `has_jump` — 布尔值，该题有无跳转
- `jump_rules` — 跳转规则集合

**实际效果示例：**

```text
用户选了"否" → 直接跳到第15题
用户选了"是" → 直接提交问卷，结束
```

### 5.2 条件显示：不是跳走，而是题目出现或隐藏

**定义：** 根据前面的选择，后续题目的**显示/隐藏**发生变化，但不会改变答题路径。

**DOM标记：**
- 题节点上：`relation` 属性

**relation 的格式规律：**

```javascript
relation='6,1'         // 当题6选了第1项时，该题显示
relation='10,1;2;3'    // 当题10选了第1/2/3项之一时，该题显示
relation='5,2;8,3'     // 当题5选2 OR 题8选3时，该题显示
```

**代码位置：** 
- 识别规则：[html_parser.py L1048](../wjx/provider/html_parser.py#L1048)
- 详细解析：[html_parser.py L1097](../wjx/provider/html_parser.py#L1097)

**提取结果落到：**
- `has_display_condition` — 布尔值
- `display_conditions` — 条件集合
- `has_dependent_display_logic` — 标记位
- `controls_display_targets` — 该题控制哪些后续题的显示

**实际效果示例：**

```text
选"使用过支付宝" → 第7-9题显示（关于支付宝体验）
选"未使用支付宝" → 第7-9题隐藏
答题流程不变，但用户只看到相关的题
```

### 5.3 为什么必须分开建模

**这两类逻辑在用户体验和贡献者排查上有本质区别：**

| 维度 | 硬跳题 | 条件显示 |
|------|--------|---------|
| 用户看到的效果 | **传送门** — 直接跳页 | **开关门** — 题目出现/消失 |
| 改变答题路径？ | ✓ 会彻底跳过中间题 | ✗ 不改变路径 |
| 对做题的影响 | 大（可能跳过大片题目） | 中等（题出现才需要作答） |
| 配置向导如何标注 | 在题目间画箭头 | 在题目旁标记条件 |

**粗暴混淆的后果：** 贡献者会误认为问卷无分支逻辑 → 配置错误 → 运行时全乱。

---

## 章6：多页导航识别

### 6.1 翻页按钮的常见形式

问卷星多页常见按钮和触发方法：

**HTML按钮（按优先级）：**

```html
<button id="divNext">下一页</button>
<button id="ctlNext">下一页</button>
<a class="button mainBgColor" onclick="show_next_page()">下一页</a>
<a href="javascript:nextPage()">下一页</a>
```

**JS函数触发：**

```javascript
show_next_page()
next_page()
nextPage()
```

### 6.2 导航兼容逻辑

项目的导航实现采用**分层降级**策略：

**第1层** — 尝试显示隐藏的按钮（有些按钮被 CSS 隐藏或被模态框遮挡）
**第2层** — 按多个选择器依次尝试点击
**第3层** — 若 DOM 点击失败，直接调用页面上的 JS 函数

代码参考：[navigation.py L252](../wjx/provider/navigation.py#L252)

**设计理由：**
- 问卷星模板众多且不规范
- 有些按钮表面可见但被遮罩或 disabled
- 有些页面不靠正常 DOM click，而是 inline JavaScript

---

## 章7：贡献者排查指南

遇到问题时，按以下**顺序**排查，不要乱。

### 7.1 菜单式诊断

**症状：题型识别错误**

```text
1. 查看配置向导里该题的显示类型
2. 打开浏览器控制台查看题根节点的 type 值
3. 查看题内是否有排序(.ui-sortable)、评价(.rate-off)、矩阵 等特征元素
4. 若 type 和 DOM 冲突，检查 html_parser.py 的兜底规则 ← 改这里
5. 若兜底规则缺失，补充新规则
```

**症状：页数不对**

```text
1. 检查目标问卷有多少个 <fieldset>
   → 少于预期？可能动态渲染了，改 detection.py
   → 等于预期？继续看2
2. 检查 html_parser.py 是否正确扫描了每个 fieldset
3. 检查运行时 detection.py 对页数的识别
4. 不确定？在 html_parser.py 的分页逻辑里加 debug 输出
```

**症状：逻辑没识别（条件显示/跳题）**

```text
1. 查看目标题的 relation / hasjump / jumpto 属性值
   → 为空？可能页面还在动态渲染
   → 有值？继续看2
2. 检查 html_parser.py 是否正确解析了这些属性
3. 检查配置向导是否标注出来了（UI问题还是解析问题？）
4. 不确定？加 debug、截图分析 DOM
```

### 7.2 改哪个文件的速查表

| 问题类型 | 优先检查 | 次要检查 |
|---------|---------|---------|
| 题型显示错 | [html_parser.py](../wjx/provider/html_parser.py) | [detection.py](../wjx/provider/detection.py) |
| 页数识别错 | [detection.py](../wjx/provider/detection.py) | [html_parser.py](../wjx/provider/html_parser.py) |
| 逻辑识别缺失 | [html_parser.py](../wjx/provider/html_parser.py) | [detection.py](../wjx/provider/detection.py) |
| 翻页卡顿 | [navigation.py](../wjx/provider/navigation.py) | [runtime.py](../wjx/provider/runtime.py) |
| 点击无响应 | [runtime.py](../wjx/provider/runtime.py) | [navigation.py](../wjx/provider/navigation.py) |

---

## 章8：实例分析

### 8.1 条件显示 vs 硬跳题的对比

以真实问卷结构为例，区分这两类逻辑：

**场景一：条件显示（最常见）**

```text
第6题：使用过第三方支付吗？
       ├─ 选"是" → 
       │   第7-9题显示（支付宝体验问卷）
       │   第10-12题显示（微信支付体验问卷）
       │
       └─ 选"否" →
           第7-12题全部隐藏
           直接跳到第13题（其他渠道调查）

[ 分析 ]
第6题有 relation 属性
第7-12题上都标着 relation='6,1'(是) 或 relation='6,2'(否)
```

**场景二：硬跳题（修改问卷路径）**

```text
第10题：您的满意度如何？
       ├─ 选"非常不满意" → 
       │   hasjump=1 且 jumpto=next_survey
       │   直接结束，提交不满意反馈
       │
       └─ 选其他 →
           跳到第11题

[ 分析 ]
第10题的部分选项上标记 jumpto 属性
中间的若干题被跳过
```

**区别小结：**
- 条件显示用 `relation` — 题目显示/隐藏，路径不变
- 硬跳题用 `jumpto`/`hasjump` — 直接改变作答路径

---

## 章9：编码规范与底线

新增、修改解析规则时的**必须遵守**的原则：

1. **不能只靠题干文字猜题型** — 文本可能被改，DOM 属性才是真相
2. **不能把 `type` 当唯一真理** — 总要结合 DOM 特征双重确认
3. **不能混淆硬跳题和条件显示** — 它们的影响范围和处理方式完全不同
4. **不能为了兼容一个奇葩模板而伤害正常模板** — 先改特例规则，再考虑通用化
5. **修改前必须用真实问卷验证** — 截图、打开调试工具，确认 DOM 结构

**最后的话：** 问卷星这套前端不够规范，很多模板写法混乱。不要幻想"一条规则统一天下"。老老实实按 **DOM 事实** 说话，该兜底就兜底。

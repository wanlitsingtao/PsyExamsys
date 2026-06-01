# Bug修复与改进记录 V2.1

> 日期：2026-05-27  
> 涉及版本：V2.0 → V2.1  
> 修改人：AI 自动分析修复

---

## Bug1：背题模块答案无法缓存

### 问题描述
背题模块答题过程中，用户选择答案后点击"下一题"再返回"上一题"，已选择的答案变为空。

### 根因分析
`pages/study.py` 中使用 `st.radio` 和 `st.checkbox` 时：
1. **单选/判断题**：`st.radio` 的 `index=None` 始终从无选中状态开始，没有读取 `study_answers[qid]` 中的已有答案来设置 `index`
2. **多选题**：`st.checkbox` 没有设置 `value` 参数，默认始终为 False

### 修复方案
在渲染单选/判断题时，从 `study_answers[qid]` 读取已有答案，计算对应的 `index` 传入 `st.radio`；在多选 checkbox 中传入 `value=(k in user_ans)` 恢复已选状态。

### 影响范围
- `pages/study.py` 第 180-214 行的选项渲染逻辑

### 验证方法
1. 选择一道单选题的答案
2. 点击"下一题"
3. 点击"上一题"回到原题 → 答案应恢复显示

---

## Bug2：题目导航色块不随答题进度变化

### 问题描述
背题、模拟考试、错题本三个模块中，底部导航网格的色块不随答题进度变化，始终为灰色。

### 根因分析
CSS 注入的样式选择器 `div[data-testid="column"]:nth-child({col_idx+1}) button[key="nav_{q_idx}"]` 在多行网格中不准确：
- Streamlit 的 `st.columns()` 每次调用会重新创建 column 容器
- 在多层循环中，`nth-child` 选择器相对于父容器的位置可能因之前的 CSS 注入导致选择器错位
- `key` 选择器虽然能匹配按钮，但 CSS 是通过 `style` 标签注入的，多个 style 标签的渲染顺序可能导致后面的覆盖前面的

### 修复方案
改用 **内联 style 属性** 直接设置在 button 元素上（通过 `unsafe_allow_html` 包装整个按钮），而非通过 CSS 选择器注入。使用 `st.markdown` + HTML 直接构建导航按钮，确保每个按钮的背景色样式直接绑定。

### 影响范围
- `pages/study.py` 导航网格（第 257-312 行）
- `pages/exam.py` 答题卡（第 306-338 行）
- `pages/wrongbook.py` 导航网格

### 验证方法
1. 在背题模块选择并提交一道题
2. 观察底部导航网格中该题号颜色是否变为绿色（正确）或红色（错误）
3. 切到未选题，观察颜色是否为黄色（已选未提交）或灰色（未答）

---

## 改进1：题目属性细化到10个模块

### 改进描述
将知识板块从原来的"基础理论/咨询实务"2个大类，细化为11个具体模块（心理学导论、社会心理学、人格心理学、发展心理学、异常心理学、咨询心理学、心理咨询会谈技术、情绪调节与压力管理、心理危机识别、家庭教育与心理健康科普、心理咨询专业伦理与相关法律规范）。

### 变更内容
1. `utils/data_manager.py`：更新 `CATEGORY_MAP`，每个 source_file 映射到具体模块名
2. `utils/parser.py`：同步更新 `CATEGORY_MAP`，解析时直接使用具体模块名
3. `data/questions.json`：重新计算所有题目的 category 字段
4. 所有页面的知识板块展示自动更新（使用 category 字段值）

### 影响范围
- `utils/data_manager.py`
- `utils/parser.py`
- `data/questions.json`（重新生成 category）
- 所有页面文件（无需改代码，category 字段自动显示新值）
- 需求文档

---

## 改进2：背题模块每道题可随时查看答案

### 改进描述
背题模块中，每道题（无论是否已提交）都增加"📖 查看答案"按钮，点击后以展开面板显示正确答案和解析。

### 变更内容
`pages/study.py`：在操作按钮区域增加"查看答案"按钮，点击后显示正确选项和解析。

### 影响范围
- `pages/study.py` 操作按钮区域

---

## 改进3：新增专项训练模块 V2.2

### 改进描述
增加"专项训练"模块，用户可从11个知识板块中选择要训练的板块，系统从该板块中随机抽取60道题（30单选+20多选+10判断），训练完成后结果更新错题本。

### 设计要点
1. **用户选择板块**：开始界面用卡片网格展示11个知识板块，显示每个板块的题数统计
2. **智能检测**：板块题目不足时按钮禁用，显示缺少的题型和数量（如"单选缺5"）
3. **固定60题**：每轮固定 30单选 + 20多选 + 10判断
4. **统一提交模式**：与背题系统一致的界面风格，全部答完后一并提交
5. **查看答案**：同背题系统，做题过程中可随时查看正确答案和解析
6. **答题卡导航**：底部答题卡支持快速跳转，已答黄色高亮
7. **结果更新错题本**：答错题自动加入错题库，答对题从错题库移除（以最后一次为准）

### 变更内容
1. **新增 `pages/specialized.py`**：完整的专项训练页面，包含：
   - `show_specialized()` - 主入口，状态路由
   - `_show_spec_start()` - 知识板块选择界面（卡片网格）
   - `_start_specialized()` - 开始训练（按板块抽取60题）
   - `_show_spec_running()` - 答题进行中界面（与背题系统统一）
   - `_finish_specialized()` - 提交答案、计算成绩、更新错题本
   - `_show_spec_result()` - 成绩报告界面（含分题型统计和答题卡）
2. **修改 `utils/data_manager.py`**：新增两个函数
   - `extract_questions_by_category()` - 按知识板块和题型数量抽取题目
   - `get_all_categories()` - 获取所有知识板块及题数统计
3. **修改 `app.py`**：
   - 导航菜单增加"专项训练"入口（🎯 图标）
   - 路由配置增加 `pages.specialized` 的引用

### 影响范围
- `pages/specialized.py`（新文件）
- `utils/data_manager.py`
- `app.py`
- 错题库自动联动（答错+1，答对移除）

### 验证方法
1. 启动应用，侧边栏导航应出现"专项训练"
2. 点击后显示11个知识板块卡片，显示题数统计
3. 题目不足的板块显示"⚠️"提示并禁用按钮
4. 选择板块后进入答题界面，60题按 单选→多选→判断 顺序
5. 可随时查看答案，可答题卡导航
6. 提交后显示成绩报告，错题进入错题本

---

## 修复1：模拟考试抽题范围按超类限定

### 问题描述
模拟考试的两科（心理学综合/咨询实务）抽取题目时，直接从全部题库混抽，没有按超类限定范围。心理学综合应只从基础理论模块（心理学导论、社会心理学、人格心理学、发展心理学、异常心理学、咨询心理学）出题；咨询实务应只从咨询实务模块（心理咨询会谈技术、情绪调节与压力管理、心理危机识别、家庭教育与心理健康科普、心理咨询专业伦理与相关法律规范）出题。

### 修复方案
1. `utils/data_manager.py`：新增 `SUPER_CATEGORY_MAP`（超类→子模块映射）和 `extract_questions_by_super()` 函数
2. `pages/mock_exam.py`：`_start_subject()` 改用 `extract_questions_by_super()` 按超类过滤后抽题

### 影响范围
- `utils/data_manager.py`（新增 SUPER_CATEGORY_MAP + extract_questions_by_super）
- `pages/mock_exam.py`（import 和 _start_subject 修改）

---

## 修复2：专项训练增加"上次答对/答错"标记

### 问题描述
专项训练答题时，题目旁边没有显示该题上次答题结果是正确还是错误，用户无法针对性地重点关注。

### 修复方案
1. `utils/data_manager.py`：`_update_question_stats()` 增加 `last_correct` 字段（True/False/None），`get_question_stats()` 默认值同步更新
2. `pages/specialized.py`：在 `_show_spec_running()` 中读取 `last_correct`，显示 🟢 上次答对 / 🔴 上次答错 标签

### 影响范围
- `utils/data_manager.py`
- `pages/specialized.py`

---

## 修复3：模拟考试选项增加1.5倍行距

### 问题描述
模拟考试界面中单选/判断的 radio 选项和多项选择的 checkbox 选项排列紧凑，可读性差。

### 修复方案
`pages/mock_exam.py` 的 `_show_exam_subject()` 中，在渲染 radio 和 checkbox 组件前注入 CSS 样式：
- radio: `gap: 0.75em` + `padding: 0.3em 0`
- checkbox: `padding: 0.3em 0`

### 影响范围
- `pages/mock_exam.py`

---

## 修复4：错题回顾显示全部错题

### 问题描述
模拟考试提交后的错题回顾区域仅显示前10题（`wrong_details[:10]`），剩余错题仅显示"还有 N 题错题"提示，无法展开查看。

### 修复方案
`pages/mock_exam.py` 的 `_show_subject_result()` 中：
- 将 `wrong_details[:10]` 改为 `wrong_details`，遍历全部错题
- 删除 `if len(wrong_details) > 10: ...` 的截断提示

### 影响范围
- `pages/mock_exam.py`

---

## 修复5：模拟考试提交性能优化（批量操作）

### 问题描述
模拟考试提交试卷时，对每题依次调用 `add_wrong_record` / `add_correct_record` / `add_answer_record`，每次调用都执行一次 JSON 文件读取+写入，250题的试卷约产生 500+ 次文件 I/O，导致提交过程明显卡顿。

### 修复方案
`utils/data_manager.py` 新增两个批量函数：
1. `batch_update_wrong_and_stats(wrong_qids, correct_qids, stats_updates)` — 批量更新错题库（答错添加/更新、答对移除）和题目答题统计（单次读取+单次写入）
2. `batch_add_answer_records(records)` — 批量追加答题过程记录（单次读取+单次写入）

`pages/mock_exam.py` 和 `pages/specialized.py` 的提交函数改为：先收集所有操作数据，再调用批量函数一次性写入。

优化效果：250题提交从 ~500+ 次 I/O 降至 ~6 次 I/O，性能提升近百倍。

### 影响范围
- `utils/data_manager.py`（新增 batch_update_wrong_and_stats + batch_add_answer_records）
- `pages/mock_exam.py`（_finish_subject 重构）
- `pages/specialized.py`（_finish_specialized 同步重构）

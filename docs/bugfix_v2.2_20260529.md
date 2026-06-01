# Bug修复与改进记录 V2.2

> 日期：2026-05-29
> 涉及版本：V2.1 → V2.2
> 修改人：AI 自动分析修复

---

## 一、架构改进

### 改进1：错题库数据结构简化（重大变更）

#### 问题描述
V2.1 错题库以对象列表格式存储 `[{question_id, wrong_count, last_wrong_time, wrong_records}]`，其中 `wrong_count` 与 `question_stats.json` 中的 `wrong_count` 存在语义差异和数据冗余——两个地方维护同一指标的副本，容易不一致。

#### 改进方案
将 `wrong_questions.json` 从对象列表格式简化为**纯题号ID列表**：
```json
// 旧格式 (v2.1)
[{"question_id": "xxx", "wrong_count": 3, "last_wrong_time": "...", "wrong_records": [...]}]

// 新格式 (v2.2)
["020920cc799c", "02631b85c794", "03ef6a1e3d3b"]
```

#### 变更内容
1. `utils/data_manager.py`：
   - 新增 `_extract_qids_from_wrong_list()` 兼容函数，同时支持新旧两种格式的读取
   - 重写 `add_wrong_record()`：仅操作 qid 列表，规则判断从 question_stats 读取
   - 重写 `add_correct_record()`：仅操作 qid 列表
   - 简化 `batch_update_wrong_and_stats()` 错题库部分（约30行→约10行）
   - 重写 `get_top_wrong_questions()`、`get_wrong_stats()`、`get_all_wrong_with_stats()`：所有统计数据从 question_stats.json 读取
   - 重写 `remove_wrong_question()`：兼容新格式
2. `pages/statistics.py`：`_show_wrong_stats()` 改用 `_extract_qids_from_wrong_list()` 读取
3. `data/wrong_questions.json`：格式已迁移，135个 qid

#### 影响范围
- `utils/data_manager.py`（约6个函数重写）
- `pages/statistics.py`
- `data/wrong_questions.json`

---

### 改进2：错题判断规则修正

#### 问题描述
V2.1 规则为"以最后一次答题结果为准"——本次答错即加入错题本，本次答对即移除。这导致：
1. 一道历史答对10次、仅最后一次答错的题，被标记为错题（不合理）
2. 与页面显示的累计统计（wc=5, cc=3）脱节

#### 改进方案
改为**基于累计统计的判断规则**：

| 场景 | 规则 | 结果 |
|------|------|------|
| 答错，且 wc >= cc，至少答过一次 | 入错题本 | qid 加入列表 |
| 答错，但 wc < cc | 历史答对较多 | 不加入 |
| 答对，且 cc > wc | 出错题本 | qid 从列表移除 |
| 答对，但 wc >= cc | 仍为错题 | 保持在列表中 |
| wc=0, cc=0 | 从未答过 | 确保不加入 |

#### 变更内容
- `add_wrong_record()`：增加 `wc >= cc` 判断 + `(wc > 0 or cc > 0)` 守卫
- `add_correct_record()`：改用 `cc > wc` 判断是否移出
- `batch_update_wrong_and_stats()`：同步上述规则修改

#### 影响范围
- `utils/data_manager.py`（add_wrong_record / add_correct_record / batch_update_wrong_and_stats）

---

## 二、Bug修复

### Bug1：wc=0, cc=0 边界条件导致未答题错误入本

#### 问题描述
`wc >= cc` 判断中，当 `wc=0` 且 `cc=0` 时 `0 >= 0` 为 True，导致从未答过的题目被错误加入错题本。

#### 修复方案
在所有入本判断处增加守卫条件 `(wc > 0 or cc > 0)`，确保至少答过一次才参与判断。

#### 修复位置
- `add_wrong_record()`：第1处
- `batch_update_wrong_and_stats()`：第2处（显式判断）
- `batch_update_wrong_and_stats()`：第3处（elif 分支）

#### 影响范围
- `utils/data_manager.py`（3处代码修改）

---

### Bug2：孤立错题数据清理

#### 问题描述
`wrong_questions.json` 中存在7条错题记录，但 `question_stats.json` 中没有对应的统计数据（可能由历史格式迁移或手动操作导致）。

#### 修复方案
编写清理脚本，遍历 wrong_questions.json 中的每个 qid，检查 question_stats.json 是否有关联记录，无关联记录的条目从列表中移除。

#### 影响范围
- `data/wrong_questions.json`（142条 → 135条）

---

### Bug3：专项训练成绩报告缺少题目解析

#### 问题描述
专项训练提交后的成绩报告（`_show_spec_result()`）中，每道题的详情区域只显示题目和答案正误，没有显示解析内容（explanation）。

#### 根因分析
`_finish_specialized()` 在构建 details 字典时，未将 `options` 和 `explanation` 字段加入：
```python
# 修复前
detail = {
    "index": ..., "type": ..., "question": ...,
    "answer": ..., "user_answer": ..., "correct": ...
}
```

#### 修复方案
在 details 字典中增加 `"options": q.get("options", {})` 和 `"explanation": q.get("explanation", "")` 字段。`_show_spec_result()` 中直接读取 `d["explanation"]` 展示。

#### 影响范围
- `pages/specialized.py`（_finish_specialized + _show_spec_result）

---

### Bug4：专项训练解析展示格式优化

#### 问题描述
成绩报告中解析内容前有分割线和"解析"标题，视觉上占用空间、不够简洁。用户期望正确答案后直接跟解析文字。

#### 修复方案
移除解析前的分割线和标题，将解析内容直接以普通文本形式展示在正确答案行之后。

#### 影响范围
- `pages/specialized.py`（_show_spec_result）

---

### Bug5：stats 索引键不匹配

#### 问题描述
某些旧的查询代码中使用 `d["index"]`（题号）而非 `q["id"]`（题目唯一ID）作为 stats 查询键，由于 index 在不同文件中可能重复，导致查询到错误的统计数据。

#### 修复方案
统一所有 stats 查询使用题目 `id`（MD5前12位）作为键值。

#### 影响范围
- `pages/mock_exam.py`（_show_subject_result）
- `pages/study.py`（第508行，[遗留]旧版代码）

---

### Bug6：模拟考试按钮失效修复

#### 问题描述
模拟考试页面中部分按钮在多次点击后失效或行为异常。

#### 修复方案
为所有按钮添加显式 `key` 参数，确保 Streamlit 正确区分不同状态下的按钮实例，避免 key 冲突导致的按钮失效。

#### 影响范围
- `pages/mock_exam.py`（各按钮区域）

---

### Bug7：查看答案改为 Toggle 模式

#### 问题描述
专项训练中"查看答案"是独立按钮，点击后展开答案面板但无法方便地收起，且按钮状态语义不清晰。

#### 修复方案
将"查看答案"从独立 Button 改为 Toggle 按钮，展开时显示"📖 隐藏答案 ▲"，收起时显示"📖 查看答案 ▼"，状态清晰且操作便捷。

#### 影响范围
- `pages/specialized.py`（_show_spec_running）

---

## 三、性能优化

### 优化1：专项训练结果页统计缓存

#### 问题描述
`_show_spec_result()` 中每道题目遍历时都调用 `get_question_stats(d["id"])` 查询统计数据，60道题产生60次 JSON 文件读取，导致结果页加载明显延迟。

#### 优化方案
在 `_finish_specialized()` 提交完成后，一次性加载 `question_stats.json` 并存入 `st.session_state.spec_stats_cache`。`_show_spec_result()` 改为从缓存中读取：
```python
# 修复前：每道题1次I/O
stats = get_question_stats(d["id"], data_dir)

# 修复后：从缓存读取，0次I/O
stats = st.session_state.spec_stats_cache.get(d["id"], {})
```

#### 优化效果
60题结果展示从 60+ 次文件读取降至 1 次（提交时加载），响应时间显著缩短。

#### 影响范围
- `pages/specialized.py`（_finish_specialized + _show_spec_result）

---

### 优化2：模拟考试统计展示性能

#### 问题描述
`_show_subject_result()` 中每道错题遍历时调用 `get_question_stats()`，产生大量重复I/O。

#### 优化方案
在科目完成时一次性加载 stats 到 session_state，结果页从缓存读取。

#### 影响范围
- `pages/mock_exam.py`（_finish_subject + _show_subject_result）

---

## 四、数据一致性

### 数据清理摘要

| 操作 | 说明 | 数量 |
|------|------|------|
| 错题库格式迁移 | 对象列表 → 纯qid列表 | 全部135条 |
| 孤立记录清理 | 无 stats 对应的 qid 移除 | 7条 |
| 边界条件防护 | wc=0,cc=0 不会加入错题 | 3处代码 |

---

## 五、验证清单

| 验证项 | 方法 |
|--------|------|
| 错题库格式正确 | 检查 `wrong_questions.json` 为纯字符串数组 |
| 错题规则正确 | 答对历史多于答错的题 → 不出现/从错题本移除 |
| wc=0,cc=0 不入本 | 从未答过的题不会出现在错题本 |
| 专项训练有解析 | 提交后在结果页查看错题 → 显示解析内容 |
| 解析无分割线 | 解析紧跟在正确答案之后，无标题和分割线 |
| stats 索引正确 | 同一 index 不同文件的题，stats 各自独立 |
| 按钮正常 | 反复切换题目后按钮依然响应 |
| 查看答案 Toggle | 点击切换展开/收起，状态正确 |
| 结果页加载快 | 60题结果页秒开，无卡顿 |

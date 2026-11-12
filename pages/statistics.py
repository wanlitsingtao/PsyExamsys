"""
数据统计 - 独立的功能模块
从配置管理中拆分出来，展示系统各项数据的统计与分析
"""
import streamlit as st
import pandas as pd
from utils.data_manager import (
    load_wrong_questions, get_wrong_stats,
    load_exam_records, load_mock_exam_records,
    load_answer_records, load_question_stats,
    _extract_qids_from_wrong_list,
    get_mastery_distribution, MASTERY_LABELS, get_retention_threshold,
)

# 考试记录「错题回顾」右侧栏（session_state 驱动，原生按钮触发，无页面跳转）：
# sx_review_panel = {"section": "spec|consol|wb|mock", "session_id": ..., "date": ...}
PANEL_KEY = "sx_review_panel"


def _get_cached_stats(exam_type):
    """缓存所有统计数据，仅在 _data_version 变化或 exam_type 变化时重新加载（减少 8→1 次 JSON 读取）"""
    version = st.session_state.get("_data_version", 0)
    cache = st.session_state.get("_stats_cache", {})
    if cache.get("_version") == version and cache.get("_exam_type") == exam_type:
        return (
            cache["wrong_list"], cache["wrong_stats"],
            cache["exam_records"], cache["mock_records"],
            cache["answer_records"], cache["question_stats"],
        )

    # 版本过期，重新加载所有数据（1 次批量 I/O）
    wrong_list = load_wrong_questions(exam_type=exam_type)
    wrong_stats = get_wrong_stats(exam_type)
    exam_records = load_exam_records(exam_type=exam_type)
    mock_records = load_mock_exam_records(exam_type=exam_type)
    answer_records = load_answer_records(exam_type=exam_type)
    question_stats = load_question_stats(exam_type=exam_type)

    st.session_state._stats_cache = {
        "_version": version,
        "_exam_type": exam_type,
        "wrong_list": wrong_list,
        "wrong_stats": wrong_stats,
        "exam_records": exam_records,
        "mock_records": mock_records,
        "answer_records": answer_records,
        "question_stats": question_stats,
    }
    return wrong_list, wrong_stats, exam_records, mock_records, answer_records, question_stats


def show_statistics():
    st.markdown("### 📊 数据统计")
    st.markdown("---")

    # 加载所有数据（使用缓存，仅在版本变化时重新读盘）
    exam_type = st.session_state.get("exam_type")
    questions = st.session_state.questions
    wrong_list, wrong_stats, exam_records, mock_records, answer_records, question_stats = \
        _get_cached_stats(exam_type)

    # 错题回顾右侧栏（CSS position:fixed 停靠页面右侧，与主内容并排）
    _render_review_panel(exam_records, mock_records, answer_records, questions)

    # 视图切换：用 segmented_control 替代 st.tabs。
    # 🩸 原因（实测）：st.tabs 的激活状态存在前端组件里，页面内任何兄弟结构的
    # 挂载/卸载（如错题回顾面板）都会导致 tabs 组件重建、激活 tab 重置回第一个；
    # segmented_control 的选中值存在 session_state，不受元素增删影响。
    # 附带收益：st.tabs 每次 rerun 渲染全部 5 个 tab 的内容，分段选择器只渲染
    # 当前视图，首页 rerun 开销进一步下降。
    _VIEWS = [
        "📕 错题统计", "🧠 知识掌握情况分析",
        "📝 答题统计", "📈 相关性分析", "📋 考试记录",
    ]
    view = st.segmented_control(
        "统计视图", _VIEWS, key="stats_view",
        selection_mode="single", default=_VIEWS[0], label_visibility="collapsed",
    ) or _VIEWS[0]

    if view == "📕 错题统计":
        _show_wrong_stats(questions, wrong_list, wrong_stats, question_stats)
    elif view == "🧠 知识掌握情况分析":
        _show_mastery_analysis(questions, exam_type)
    elif view == "📝 答题统计":
        _show_answer_stats(questions, answer_records, question_stats, exam_type)
    elif view == "📈 相关性分析":
        from pages.correlation import show_correlation
        show_correlation()
    elif view == "📋 考试记录":
        _show_exam_stats(exam_records, mock_records)


def _show_wrong_stats(questions, wrong_list, wrong_stats, question_stats):
    """错题统计 — 统计数字统一从 question_stats 表读取"""
    st.markdown("### 📕 错题统计")
    wrong_qids = _extract_qids_from_wrong_list(wrong_list)

    if wrong_stats["total"] == 0:
        st.success("🎉 太棒了！错题本为空，继续加油！")
        return

    col1, col2, col3 = st.columns(3)
    col1.metric("📕 错题总数", wrong_stats["total"])
    col2.metric("🏆 最高答错次数", wrong_stats["most_wrong"])
    col3.metric("📊 错题占比",
                f"{wrong_stats['total']/len(questions)*100:.1f}%" if questions else "0%")

    st.markdown("---")

    # 错题按知识板块分布
    st.markdown("### 📂 错题知识板块分布")

    q_map = {q["id"]: q for q in questions}
    cat_wrong = {}
    for qid in wrong_qids:
        q = q_map.get(qid)
        if q:
            cat = q.get("category", "未知")
        else:
            cat = "未知（题目已删除）"
        if cat not in cat_wrong:
            cat_wrong[cat] = {"count": 0, "total_wrong": 0}
        cat_wrong[cat]["count"] += 1
        ws = question_stats.get(qid, {})
        cat_wrong[cat]["total_wrong"] += ws.get("wrong_count", 0)

    if cat_wrong:
        # 统计每个知识板块的题目总数
        cat_total = {}
        for q in questions:
            cat = q.get("category", "未知")
            cat_total[cat] = cat_total.get(cat, 0) + 1

        cat_data = []
        for cat, stats_data in sorted(cat_wrong.items(), key=lambda x: x[1]["count"], reverse=True):
            total_q = cat_total.get(cat, 0)
            ratio = stats_data["count"] / total_q * 100 if total_q > 0 else 0
            cat_data.append({
                "知识板块": cat,
                "错题数": stats_data["count"],
                "错题比率": f"{ratio:.1f}%",
                "累计答错次数": stats_data["total_wrong"],
                "平均答错次数": f"{stats_data['total_wrong']/stats_data['count']:.1f}",
            })
        df = pd.DataFrame(cat_data)
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # 错题列表（按答错次数排序，从 stats 读取）
    st.markdown("### 🔝 高频错题 TOP 20")
    st.caption("口径：当前题库**所有答过的题**（含已移出错题本的），按历史累计答错次数降序")

    # 全量口径（2026-09-26）：不再限定当前错题本，而是所有答过的题中
    # 答错次数 > 0 的题目，按 wrong_count 降序 —— 与「最高答错次数」口径一致
    answered_qids = [qid for qid, ws in question_stats.items() if ws.get("wrong_count", 0) > 0]
    sorted_qids = sorted(answered_qids, key=lambda qid: question_stats.get(qid, {}).get("wrong_count", 0), reverse=True)
    top_data = []
    for i, qid in enumerate(sorted_qids[:20]):
        q = q_map.get(qid)
        ws = question_stats.get(qid, {})
        if q:
            question_text = q.get("question", "")[:50] + "..."
            cat = q.get("category", "未知")
        else:
            question_text = "（题目已删除）"
            cat = "未知"
        top_data.append({
            "排名": i + 1,
            "题目": question_text,
            "答错次数": ws.get("wrong_count", 0),
            "最后答错时间": ws.get("last_answer_time", "")[:16],
            "知识板块": cat,
        })

    if top_data:
        df_top = pd.DataFrame(top_data)
        st.dataframe(df_top, use_container_width=True, hide_index=True)
    else:
        st.info("暂无错题数据")


def _show_answer_stats(questions, answer_records, question_stats, exam_type=None):
    """答题统计"""
    st.markdown("### 📝 答题统计")

    if not answer_records and not question_stats:
        st.info("📢 暂无答题数据，开始答题后这里将展示统计数据。")
        return

    # 总体统计
    total_records = len(answer_records)
    correct_records = sum(1 for r in answer_records if r.get("is_correct"))
    wrong_records = total_records - correct_records

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📝 总答题次数", total_records)
    col2.metric("✅ 答对次数", correct_records)
    col3.metric("❌ 答错次数", wrong_records)
    col4.metric("📊 正确率",
                f"{correct_records/total_records*100:.1f}%" if total_records > 0 else "0%")

    st.markdown("---")

    # 按训练类型统计（仅展示三种类型；综合训练合并 exam + study；隐藏 wrongbook/consolidation）
    st.markdown("### 🗂️ 各训练类型统计")

    MODE_LABELS = {
        "specialized": "专项训练",
        "mock_exam": "模拟考试",
        "comprehensive": "综合训练",
    }

    from collections import defaultdict

    # 一次遍历收集所有统计：按 mode，以及 specialized 各 category
    mode_stats = defaultdict(lambda: {"sessions": set(), "total": 0, "correct": 0})
    spec_cat_stats = defaultdict(lambda: {"sessions": set(), "total": 0, "correct": 0})
    for r in answer_records:
        mode = r.get("mode", "未知")
        sid = r.get("session_id", "")
        mode_stats[mode]["sessions"].add(sid)
        mode_stats[mode]["total"] += 1
        if r.get("is_correct"):
            mode_stats[mode]["correct"] += 1
        # 专项训练按知识板块细分
        if mode == "specialized":
            cat = r.get("category", "未知")
            spec_cat_stats[cat]["sessions"].add(sid)
            spec_cat_stats[cat]["total"] += 1
            if r.get("is_correct"):
                spec_cat_stats[cat]["correct"] += 1

    # 合并：exam + study → comprehensive
    for src_mode in ("exam", "study"):
        if src_mode in mode_stats:
            s = mode_stats[src_mode]
            mode_stats["comprehensive"]["sessions"].update(s["sessions"])
            mode_stats["comprehensive"]["total"] += s["total"]
            mode_stats["comprehensive"]["correct"] += s["correct"]
            del mode_stats[src_mode]

    def _row(label, s, indent=False):
        t = s["total"]
        c = s["correct"]
        sessions = len(s["sessions"])
        pct = c / t * 100 if t > 0 else 0
        prefix = "　↳ " if indent else ""
        return {
            "训练类型": prefix + label,
            "训练次数": sessions,
            "答题总数": t,
            "答对数": c,
            "答错数": t - c,
            "正确率": f"{pct:.1f}%",
        }

    mode_data = []
    for mode in ["specialized", "mock_exam", "comprehensive"]:
        if mode not in mode_stats:
            continue
        mode_data.append(_row(MODE_LABELS[mode], mode_stats[mode]))
        # 专项训练后展开各知识板块子行
        if mode == "specialized" and spec_cat_stats:
            for cat in sorted(spec_cat_stats.keys(), key=lambda k: spec_cat_stats[k]["total"], reverse=True):
                mode_data.append(_row(cat, spec_cat_stats[cat], indent=True))

    if mode_data:
        df_mode = pd.DataFrame(mode_data)
        st.dataframe(df_mode, use_container_width=True, hide_index=True)

    st.markdown("---")

    # 按知识板块统计答题情况

    cat_answer_stats = {}
    for r in answer_records:
        cat = r.get("category", "未知")
        if cat not in cat_answer_stats:
            cat_answer_stats[cat] = {"total": 0, "correct": 0}
        cat_answer_stats[cat]["total"] += 1
        if r.get("is_correct"):
            cat_answer_stats[cat]["correct"] += 1

    if cat_answer_stats:
        cat_data = []
        for cat, stats in sorted(cat_answer_stats.items(), key=lambda x: x[1]["total"], reverse=True):
            pct = stats["correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
            cat_data.append({
                "知识板块": cat,
                "答题次数": stats["total"],
                "答对次数": stats["correct"],
                "正确率": f"{pct:.1f}%",
            })
        df = pd.DataFrame(cat_data)
        st.dataframe(df, use_container_width=True, hide_index=True)


def _show_mastery_analysis(questions, exam_type=None):
    """
    掌握度分析看板
    - 掌握度等级：0=未学习 1=初识 2=学习中 3=基本掌握 4=掌握 5=熟练
    - 置信度：0.0-1.0，低样本量或走势波动 → 低置信度
    - 不牢靠：答对过又答错（消退型）或交替答对答错（波动型）
    - 遗忘预警：上次答对后超过阈值天数，提示需要复习（当前阈值可在系统设置中配置）
    """
    st.markdown("### 🧠 知识掌握情况分析")

    # 缓存掌握度分布（457ms 重计算，仅在 _data_version 或题库变化时重算）
    # _data_version + exam_type 双键：_data_version 不会因切题库递增，
    # 必须显式比对 exam_type，否则会残留上一题库的掌握度（曾显示为全 0 / 错库数据）
    version = st.session_state.get("_data_version", 0)
    cache_key = f"_mastery_cache_{exam_type}"
    cache = st.session_state.get(cache_key, {})
    if cache.get("_version") == version and cache.get("_exam_type") == exam_type:
        mastery_data = cache["data"]
    else:
        mastery_data = get_mastery_distribution(questions, exam_type)
        st.session_state[cache_key] = {"_version": version, "_exam_type": exam_type,
                                       "data": mastery_data}
    by_cat = mastery_data["by_category"]
    retention_list = mastery_data["retention_list"]
    unstable_list = mastery_data.get("unstable_list", [])

    if not by_cat:
        st.info("📢 暂无掌握度数据，开始答题后这里将展示分析。")
        return

    # ---- 全局概览 ----
    all_counts = [0] * 6
    total_qs = 0
    total_retention = 0
    total_unstable = 0
    for d in by_cat.values():
        mc = d["mastery_counts"]
        for i in range(6):
            all_counts[i] += mc[i]
        total_qs += d["total"]
        total_retention += d["retention_due"]
        total_unstable += d.get("unstable", 0)

    studied = sum(all_counts[1:])
    m5_m4 = all_counts[5] + all_counts[4]
    # 低置信度题数：confidence < 0.5
    low_conf_count = len([item for item in unstable_list if item["confidence"] < 0.5])

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("📚 总题数", total_qs)
    col2.metric("📖 已学题数", studied,
                help="掌握等级 ≥ 1（至少答过一次）")
    col3.metric("✅ 掌握/熟练题数", m5_m4,
                help="掌握等级 4（掌握）或 5（熟练）")
    col4.metric("⚠️ 不牢靠", total_unstable,
                help=f"其中低置信度(conf<0.5) {low_conf_count} 题")
    col5.metric("⏰ 需要复习", total_retention,
                help="上次答对后超过7天，建议复习")

    st.markdown("---")

    # ---- 各知识板块掌握度明细表 ----
    st.markdown("#### 📊 各知识板块掌握度分布")

    LEVEL_NAMES = ["未学习", "初识", "学习中", "基本掌握", "掌握", "熟练"]
    cat_rows = []
    for cat, d in by_cat.items():
        mc = d["mastery_counts"]
        total = d["total"]
        studied_n = sum(mc[1:])
        row = {
            "知识板块": cat,
            "总题数": total,
            "已学率": f"{d['studied_rate']:.0f}%",
            "未学习": mc[0],
            "初识": mc[1],
            "学习中": mc[2],
            "基本掌握": mc[3],
            "掌握": mc[4],
            "熟练": mc[5],
            "平均等级": f"{d['avg_mastery']:.1f}",
            "⚠️不牢靠": d.get("unstable", 0),
            "⏰需复习": d.get("retention_due", 0),
        }
        cat_rows.append(row)

    if cat_rows:
        df_cat = pd.DataFrame(cat_rows)
        st.dataframe(df_cat, use_container_width=True, hide_index=True)

    # ---- 掌握度等级说明 ----
    with st.expander("📖 等级 & 置信度说明"):
        st.markdown("""
| 等级 | 标签 | 判断条件 |
|------|------|---------|
| 0 | 未学习 | 从未答过 |
| 1 | 初识 | 答题≤2次 且 正确率<60% |
| 2 | 学习中 | 答题>2次 且 正确率<60% |
| 3 | 基本掌握 | 正确率 60%–79% |
| 4 | 掌握 | 正确率 ≥80% 且 答题≥3次 |
| 5 | 熟练 | 正确率 ≥90% 且 答题≥5次 且 最近3次全对 |

**📊 置信度 (confidence)**：0.0–1.0，衡量等级的可靠程度。
- 答题次数越多、走势越稳定 → 置信度越高
- 只答过 1–2 次，即使全对，置信度也很低（可能是蒙的）

**⚠️ 不牢靠 (unstable)**：两种触发类型：
- **消退型**：曾经答对过，最近一次却答错了 → 知识遗忘/混淆
- **波动型**：答题历史出现 2 次以上对错交替 → 掌握不稳定

**⏰ 需要复习**：上次答对后超过 **7天** 未练习。
""")

    # ---- 遗忘预警列表 ----
    if retention_list:
        st.markdown("---")
        st.markdown(f"#### ⏰ 遗忘预警题目（共 {len(retention_list)} 题）")
        st.caption("以下题目上次答对后已超过7天，建议优先复习。")

        ret_data = []
        for item in retention_list[:30]:
            ret_data.append({
                "知识板块": item["category"],
                "题目": item["question"] + ("..." if len(item["question"]) >= 50 else ""),
                "距上次答对(天)": item["days_since_correct"],
                "当前等级": f"{item['mastery_level']} {MASTERY_LABELS.get(item['mastery_level'], '')}",
            })
        df_ret = pd.DataFrame(ret_data)
        st.dataframe(df_ret, use_container_width=True, hide_index=True)

    # ---- 不牢靠题目列表 ----
    if unstable_list:
        st.markdown("---")
        st.markdown(f"#### ⚠️ 掌握不牢靠题目（共 {total_unstable} 题）")
        st.caption("答对过又答错（消退型）或反复波动（波动型），建议加强练习。按置信度从低到高排列。")

        uns_data = []
        for item in unstable_list[:30]:
            history_str = "→".join(["✅" if h else "❌" for h in item["history"]])
            uns_data.append({
                "知识板块": item["category"],
                "题目": item["question"] + ("..." if len(item["question"]) >= 50 else ""),
                "类型": item["unstable_type"],
                "答题序列": history_str,
                "置信度": f"{item['confidence']:.2f}",
                "当前等级": f"{item['mastery_level']} {MASTERY_LABELS.get(item['mastery_level'], '')}",
            })
        df_uns = pd.DataFrame(uns_data)
        st.dataframe(df_uns, use_container_width=True, hide_index=True)


def _show_exam_stats(exam_records, mock_records):
    """考试记录统计 — 四类记录：专项训练、模拟考试、巩固练习、错题练习

    每条记录附原生「错题回顾」按钮：点击后在页面右侧展开回顾栏
    （session_state 驱动，不跳转新页面、tabs 状态不丢失）。
    逐题明细来自 answer_records：新记录带 session_id 精确关联；
    老记录按 mode + 提交时间（分钟）匹配（见 _match_session_records）。
    """

    TYPE_LABELS = {
        "exam": "综合训练",
        "specialized": "专项训练",
        "comprehensive": "综合训练",
        "consolidation": "巩固练习",
        "wrongbook": "错题练习",
        "study": "背题",
    }

    # 给旧记录（无 type 字段）补上 type="exam"
    for r in exam_records:
        if "type" not in r:
            r["type"] = "exam"

    # ================================================================
    #  1. 专项训练记录（包含综合训练记录）
    # ================================================================
    st.markdown("### 🎯 专项训练记录（含综合训练）")

    spec_records = [r for r in exam_records if r.get("type") in ("exam", "specialized", "comprehensive")]
    _render_record_section(spec_records, TYPE_LABELS, default_label="综合训练",
                           section_key="spec")

    # ================================================================
    #  2. 模拟考试记录
    # ================================================================
    st.markdown("---")
    st.markdown("### 📝 模拟考试记录")

    if not mock_records:
        st.info("暂无模拟考试记录。")
    else:
        exam_sessions = {}
        for r in mock_records:
            sid = r.get("session_id", "")
            if sid not in exam_sessions:
                exam_sessions[sid] = []
            exam_sessions[sid].append(r)

        cols = st.columns(3)
        cols[0].metric("🎯 模拟考试次数", len(exam_sessions))
        cols[1].metric("📋 科目记录数", len(mock_records))

        recent_sessions = _recent_mock_sessions(mock_records)

        if recent_sessions:
            h1, h2, h3, h4 = st.columns([1.3, 1.7, 2.6, 1.0])
            h1.markdown("**考试日期**")
            h2.markdown("**类型**")
            h3.markdown("**总分**")
            h4.markdown("**错题回顾**")
            for i, (sid, records) in enumerate(recent_sessions):
                date = max(r.get("date", "") for r in records)
                psy = next((r for r in records if r.get("subject") == "psychology"), None)
                cou = next((r for r in records if r.get("subject") == "counseling"), None)

                types = []
                if psy:
                    types.append("心理学综合")
                if cou:
                    types.append("咨询实务")
                type_str = " + ".join(types) if types else "—"

                total_score = (psy.get("score", 0) if psy else 0) + (cou.get("score", 0) if cou else 0)
                total_max = (psy.get("max_score", 0) if psy else 0) + (cou.get("max_score", 0) if cou else 0)
                pct = total_score / total_max * 100 if total_max else 0
                color = "#22c55e" if pct >= 60 else "#ef4444"
                total_html = (
                    f'<div style="display:flex;align-items:center;gap:8px;">'
                    f'<span style="font-weight:700;font-size:16px;min-width:42px;">{total_score:.0f}</span>'
                    f'<span style="color:#999;">/ {total_max:.0f}</span>'
                    f'<div style="flex:1;background:#e5e7eb;border-radius:4px;height:8px;min-width:50px;">'
                    f'<div style="width:{pct:.0f}%;height:100%;background:{color};border-radius:4px;min-width:3px;"></div>'
                    f'</div>'
                    f'<span style="font-size:13px;color:{color};min-width:36px;">{pct:.0f}%</span>'
                    f'</div>'
                ) if total_max else '<span style="color:#999;">—</span>'

                c1, c2, c3, c4 = st.columns([1.3, 1.7, 2.6, 1.0])
                c1.markdown(
                    f'<span style="color:#555;font-size:14px;">{date[:16] if date else ""}</span>',
                    unsafe_allow_html=True)
                c2.markdown(f"**{type_str}**")
                c3.markdown(total_html, unsafe_allow_html=True)
                c4.button("回顾", key=f"rvbtn_mock_{i}",
                          on_click=_open_review,
                          args=("mock", sid, date),
                          use_container_width=True)
        else:
            st.info("暂无模拟考试记录")

    # ================================================================
    #  3. 巩固练习记录
    # ================================================================
    st.markdown("---")
    st.markdown("### 🔁 巩固练习记录")

    consol_records = [r for r in exam_records if r.get("type") == "consolidation"]
    _render_record_section(consol_records, TYPE_LABELS, default_label="巩固练习",
                           section_key="consol")

    # ================================================================
    #  4. 错题练习记录
    # ================================================================
    st.markdown("---")
    st.markdown("### 📕 错题练习记录")

    wb_records = [r for r in exam_records if r.get("type") == "wrongbook"]
    _render_record_section(wb_records, TYPE_LABELS, default_label="错题练习",
                           section_key="wb")


def _render_record_section(records, type_labels, default_label="训练",
                           section_key=""):
    """渲染一段考试记录：汇总指标 + 最近记录列表（每行「错题回顾」原生按钮）"""
    if not records:
        st.info(f"暂无{default_label}记录。")
        return

    cols = st.columns(3)
    cols[0].metric("📋 总训练次数", len(records))
    avg_accuracy = sum(
        float(r.get("accuracy", "0%").replace("%", ""))
        for r in records if r.get("accuracy")
    ) / len(records) if records else 0
    cols[1].metric("📊 平均正确率", f"{avg_accuracy:.1f}%")
    best = max(
        (float(r.get("accuracy", "0%").replace("%", "")) for r in records if r.get("accuracy")),
        default=0
    )
    cols[2].metric("🏆 最高正确率", f"{best:.1f}%")

    # 最近 10 条记录（行按钮的 args 携带 session_id/日期，定位不依赖展示序号）
    recent = _recent_records(records)

    h1, h2, h3, h4 = st.columns([1.2, 2.1, 1.6, 0.95])
    h1.markdown("**日期**")
    h2.markdown("**类型**")
    h3.markdown("**正确率**")
    h4.markdown("**错题回顾**")

    for i, r in enumerate(recent):
        date = r.get("date", "")[:16]
        rtype = r.get("type", "")
        # 展开类型标签
        if rtype == "specialized" and r.get("category"):
            type_str = f"专项训练 · {r['category']}"
        elif rtype == "comprehensive" and r.get("category"):
            type_str = f"综合训练 · {r['category']}"
        else:
            type_str = type_labels.get(rtype, default_label)
        accuracy = r.get("accuracy", "")
        pct_val = float(accuracy.replace("%", "")) if accuracy else 0
        correct = r.get("correct", 0)
        total = r.get("total", 0)
        color = "#22c55e" if pct_val >= 60 else "#ef4444"

        c1, c2, c3, c4 = st.columns([1.2, 2.1, 1.6, 0.95])
        c1.markdown(
            f'<span style="color:#555;font-size:14px;">{date}</span>',
            unsafe_allow_html=True)
        c2.markdown(f"**{type_str}**")
        c3.markdown(
            f'<span style="color:{color};font-weight:600;">{correct}/{total}</span>'
            f'<span style="color:#999;margin-left:8px;font-size:13px;">{accuracy}</span>',
            unsafe_allow_html=True)
        c4.button("回顾", key=f"rvbtn_{section_key}_{i}",
                  on_click=_open_review,
                  args=(section_key, r.get("session_id", ""), r.get("date", "")),
                  use_container_width=True)


# ---- 错题回顾：定位当次明细 + 渲染 ----

def _recent_records(records):
    """考试记录列表展示的「最近 10 条」。"""
    return sorted(records, key=lambda r: r.get("date", ""), reverse=True)[:10]


def _recent_mock_sessions(mock_records):
    """模拟考按 session 聚合后的「最近 5 场」。"""
    sessions = {}
    for r in mock_records:
        sessions.setdefault(r.get("session_id", ""), []).append(r)
    return sorted(
        sessions.items(),
        key=lambda x: max(r.get("date", "") for r in x[1]),
        reverse=True,
    )[:5]


def _open_review(section, session_id, date):
    """点击「错题回顾」按钮：记录要回顾的那次考试（session_state，无页面跳转）"""
    st.session_state[PANEL_KEY] = {
        "section": section,
        "session_id": session_id or "",
        "date": date or "",
    }


def _close_review():
    """关闭右侧回顾栏：清掉状态即可，主内容恢复全宽"""
    st.session_state.pop(PANEL_KEY, None)


# 右侧回顾栏停靠样式：把含锚点的容器固定到页面右侧（类似左侧栏的停靠面板），
# 主内容整体左移避让；窄屏降级为全宽覆盖（不再挤压主内容）。
# ⚠️ 四个实测依据（Streamlit 1.57 + 本项目 app.py 的全局 CSS）：
#   1. st.container(border=True) 渲染为 stLayoutWrapper > div[stVerticalBlock]（带边框），
#      不存在 stVerticalBlockBorderWrapper testid —— 停靠选择器以此 DOM 为准；
#   2. app.py 给 .block-container 设了 width + max-width: min(1280px, 72vw) !important
#      + margin: 0 auto，主内容不会因 margin-right 自动让位 —— 必须同步压缩 max-width。
#      这里的 1280px / 72vw 与 app.py 的 MAX_CONTENT_WIDTH_PX / CONTENT_WIDTH_RATIO
#      保持一致，改动其中一处需同步另一处；窄屏恢复值同理（92vw / 100% 来自 app.py
#      的 ≤1200px / ≤900px 媒体查询）；
#   3. Streamlit 头部是 position:absolute 白条（高 3.75rem），面板需从其下方停靠；
#   4. 避让/停靠规则都用 :has(#sx-review-anchor) 守卫 —— 锚点只在面板打开时存在，
#      CSS 未注入或锚点缺失时所有规则零副作用。
_REVIEW_DOCK_CSS = """
<style>
div[data-testid="stLayoutWrapper"]:has(#sx-review-anchor) {
    position: fixed !important;
    /* 从 Streamlit 头部白条（3.75rem + 4px 余量，与 app.py padding-top 同款算法）下方开始停靠 */
    top: calc(3.75rem + 4px); right: 0;
    height: calc(100vh - 3.75rem - 4px);
    width: 460px; max-width: 92vw;
    overflow-y: auto;
    background: #ffffff;
    z-index: 99990;
    box-shadow: -8px 0 24px rgba(15, 23, 42, 0.10);
}
div[data-testid="stLayoutWrapper"]:has(#sx-review-anchor) > div {
    border: none !important;
    border-left: 1px solid #e5e7eb !important;
    border-radius: 0 !important;
    height: auto;
}
section[data-testid="stMain"]:has(#sx-review-anchor) div[data-testid="stMainBlockContainer"] {
    margin-right: 480px !important;
    max-width: calc(min(1280px, 72vw) - 480px) !important;
}
@media (max-width: 1100px) {
    /* 窄屏：面板降级为全宽覆盖，主内容不避让 */
    div[data-testid="stLayoutWrapper"]:has(#sx-review-anchor) {
        width: 92vw;
        box-shadow: -8px 0 24px rgba(15, 23, 42, 0.20);
    }
    section[data-testid="stMain"]:has(#sx-review-anchor) div[data-testid="stMainBlockContainer"] {
        margin-right: 0 !important;
        max-width: min(1280px, 92vw) !important;
    }
}
@media (max-width: 900px) {
    section[data-testid="stMain"]:has(#sx-review-anchor) div[data-testid="stMainBlockContainer"] {
        max-width: 100% !important;
    }
}
</style>
"""


def _render_review_panel(exam_records, mock_records, answer_records, questions):
    """右侧错题回顾栏：PANEL_KEY 有值时渲染，CSS 固定停靠在页面右侧。

    点击另一条记录的「回顾」按钮时 PANEL_KEY 被覆盖 → 栏内容随之刷新；
    点「关闭回顾」清掉 PANEL_KEY → 右侧栏消失、主内容恢复全宽。
    视图切换用 segmented_control（选中值在 session_state），面板挂载/卸载
    不会像 st.tabs 那样被重置。
    定位优先 session_id（新记录精确关联），旧记录按日期兜底；
    逐题明细定位复用 _match_session_records。
    """
    panel = st.session_state.get(PANEL_KEY)
    if not panel:
        return
    section = panel.get("section", "")
    sid = panel.get("session_id", "")
    date = (panel.get("date", "") or "")[:16]

    with st.container():
        # 与 _show_exam_stats 相同的归一化 + 分节
        for r in exam_records:
            if "type" not in r:
                r["type"] = "exam"
        type_labels = {
            "exam": "综合训练", "specialized": "专项训练", "comprehensive": "综合训练",
            "consolidation": "巩固练习", "wrongbook": "错题练习",
        }

        # entries = [(子标题或 None, record)]；模拟考一场含多科
        entries = []
        title_type = ""
        title_date = ""
        found = False

        if section == "mock":
            groups = {}
            for r in mock_records:
                groups.setdefault(r.get("session_id", ""), []).append(r)
            recs = groups.get(sid) if sid else None
            if recs is None and date:
                # 旧记录没有 session_id：按场次日期兜底
                for rs in groups.values():
                    if max(x.get("date", "") for x in rs)[:16] == date:
                        recs = rs
                        break
            if recs:
                found = True
                title_type = "模拟考试"
                title_date = max(r.get("date", "") for r in recs)
                entries = [(r.get("subject_name", "科目"), r)
                           for r in sorted(recs, key=lambda x: x.get("date", ""))]
        elif section in ("spec", "consol", "wb"):
            section_types = {
                "spec": ("exam", "specialized", "comprehensive"),
                "consol": ("consolidation",),
                "wb": ("wrongbook",),
            }
            records = [r for r in exam_records if r.get("type") in section_types[section]]
            rec = None
            if sid:
                rec = next((r for r in records if r.get("session_id") == sid), None)
            if rec is None and date:
                rec = next((r for r in records if (r.get("date", "") or "")[:16] == date), None)
            if rec:
                found = True
                title_type = type_labels.get(rec.get("type", ""), "训练")
                title_date = rec.get("date", "")
                # 老的综合训练记录 category 存的就是"综合训练"本身，拼接会重复
                if (rec.get("type") in ("specialized", "comprehensive")
                        and rec.get("category") and rec["category"] not in ("综合训练", "专项训练")):
                    title_type += f" · {rec['category']}"
                entries = [(None, rec)]

        # 停靠锚点：CSS 靠它把本容器固定到页面右侧（也是所有避让规则的开关）
        st.markdown('<div id="sx-review-anchor" style="display:none;"></div>',
                    unsafe_allow_html=True)
        if not found:
            st.markdown("#### 📌 错题回顾")
            st.info("该记录已不存在或无法定位，请从记录列表重新点开。")
        else:
            st.markdown(f"#### 📌 错题回顾 · {str(title_date)[:16]} {title_type}")
            for sub, rec in entries:
                if len(entries) > 1:
                    st.markdown(f"**{sub}**（答对 {rec.get('correct', 0)}/{rec.get('total', 0)}）")
                rows = _match_session_records(rec, answer_records)
                _render_record_review(rec, rows, questions, key_prefix="rv")
                if len(entries) > 1:
                    st.markdown("---")
        st.button("✕ 关闭回顾", key="rv_close_btn", on_click=_close_review,
                  use_container_width=True)

    st.markdown(_REVIEW_DOCK_CSS, unsafe_allow_html=True)


# ---- 错题回顾：定位当次明细（answer_records 行） ----

# 考试记录 type → answer_records.mode 的候选（老记录 type="exam" 的明细 mode 可能是
# exam/study/或综合训练；v2.9.17 之前提交的记录没有 session_id，只能按 mode+时间匹配）
_RECORD_MODES = {
    "specialized": ("specialized",),
    "comprehensive": ("comprehensive",),
    "consolidation": ("consolidation",),
    "wrongbook": ("wrongbook",),
    "exam": ("exam", "comprehensive", "study"),
}


def _match_session_records(record, answer_records):
    """定位一条考试记录对应的逐题答题明细（answer_records 的行）。

    优先级：
    ① v2.9.17 起四类提交都把 session_id 写进了考试记录 → 直接按 session_id 取
       （模拟考同一 session 的两科共用 session_id，需再按提交分钟切到本科）；
    ② 老记录没有 session_id → 按 mode + 提交时间（分钟）匹配；同一分钟内同类型
       提交了多次时，再按 total/错题数挑出最吻合的一组。
    匹配不到返回空列表（调用方提示「无法回顾」）。
    """
    rtype = record.get("type") or ("mock" if record.get("subject") else "")
    if rtype == "mock":
        modes = ("mock_exam",)
    else:
        modes = _RECORD_MODES.get(rtype, (rtype,))
    sid = record.get("session_id", "")
    date = (record.get("date") or "")[:16]

    def _minute_of(ts):
        """timestamp(ISO 带 T) → 与记录 date 同格式的 'YYYY-MM-DD HH:MM'（空格分隔）。"""
        return (ts or "")[:16].replace("T", " ")

    # ① session_id 直连
    if sid:
        rows = [r for r in answer_records if r.get("session_id") == sid]
        if rtype == "mock" and date:
            rows = [r for r in rows if _minute_of(r.get("timestamp")) == date]
        if rows:
            return rows

    # ② 老记录回退：mode + 分钟
    if not date:
        return []
    rows = [r for r in answer_records
            if r.get("mode") in modes and _minute_of(r.get("timestamp")) == date]
    # 同一分钟内同类型多次提交：按 total/错题数挑最吻合的一组（按 session_id 分组）
    if rows and len({r.get("session_id") for r in rows}) > 1:
        want_total = record.get("total")
        want_wrong = (want_total - record.get("correct", 0)) if want_total else None
        groups = {}
        for r in rows:
            groups.setdefault(r.get("session_id"), []).append(r)
        for g in groups.values():
            if (want_total is not None and len(g) == want_total
                    and want_wrong is not None
                    and sum(1 for x in g if not x.get("is_correct")) == want_wrong):
                return g
    return rows


def _fmt_review_answer(qtype, ans):
    """把存储的作答（A/B/ABD 之类的串）转成可读文本。"""
    if ans is None or str(ans).strip() == "":
        return "未作答"
    s = str(ans).strip()
    if qtype == "judge":
        return "正确" if s[:1].upper() == "A" else "错误"
    if qtype in ("multi", "案例题"):
        return "、".join(sorted(s.upper()))
    return s.upper()


def _render_record_review(record, rows, questions, key_prefix="rv"):
    """渲染一次训练/考试的错题回顾：题干 + 选项 + 你的答案 + 正确答案 + 解析。"""
    if not rows:
        st.info("未能定位本次的逐题答题明细（记录较早或明细已被清空），无法回顾错题。")
        return
    q_map = {q["id"]: q for q in questions}
    wrong_rows = [r for r in rows if not r.get("is_correct")]
    if not wrong_rows:
        st.success("🎉 本次全对，没有错题！")
        return
    st.markdown(f"**本次答错 {len(wrong_rows)} 题**（点击题目展开题干、选项与解析）")
    for i, r in enumerate(wrong_rows, 1):
        q = q_map.get(r.get("question_id"))
        if q is None:
            with st.expander(f"❌ 第{i}题 · 题目已不在当前题库"):
                st.markdown(f"你的答案：{_fmt_review_answer('', r.get('user_answer'))}（题目已被删除，无从比对）")
            continue
        tp = q.get("type", "")
        tp_name = {"single": "单选题", "multi": "多选题", "judge": "判断题",
                   "案例题": "案例题", "indefinite": "不定项选择题"}.get(tp, tp)
        yours = _fmt_review_answer(tp, r.get("user_answer"))
        correct = _fmt_review_answer(tp, q.get("answer", ""))
        with st.expander(f"❌ 第{i}题 · {tp_name} · 你答「{yours}」，正确「{correct}」"):
            if q.get("case_background"):
                st.markdown(f"**案例背景**：{q['case_background']}")
            st.markdown(q.get("question", ""))
            for opt_key in sorted((q.get("options") or {}).keys()):
                st.markdown(f"- **{opt_key}**. {q['options'][opt_key]}")
            st.markdown(f"**你的答案**：{yours}　｜　**正确答案**：{correct}")
            st.markdown(f"**解析**：{q.get('explanation') or '（暂无解析）'}")

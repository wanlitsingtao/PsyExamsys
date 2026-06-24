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
    wrong_list = load_wrong_questions()
    wrong_stats = get_wrong_stats(exam_type)
    exam_records = load_exam_records()
    mock_records = load_mock_exam_records()
    answer_records = load_answer_records()
    question_stats = load_question_stats()

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
    st.markdown("# 📊 数据统计")
    st.markdown("---")

    # 加载所有数据（使用缓存，仅在版本变化时重新读盘）
    exam_type = st.session_state.get("exam_type")
    questions = st.session_state.questions
    wrong_list, wrong_stats, exam_records, mock_records, answer_records, question_stats = \
        _get_cached_stats(exam_type)

    # 使用 Tab 组织各类统计
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📕 错题统计", "🧠 知识掌握情况分析",
        "📝 答题统计", "📈 相关性分析", "📋 考试记录"
    ])

    with tab1:
        _show_wrong_stats(questions, wrong_list, wrong_stats, question_stats)

    with tab2:
        _show_mastery_analysis(questions, exam_type)

    with tab3:
        _show_answer_stats(questions, answer_records, question_stats, exam_type)

    with tab4:
        from pages.correlation import show_correlation
        show_correlation()

    with tab5:
        _show_exam_stats(exam_records, mock_records)


def _show_wrong_stats(questions, wrong_list, wrong_stats, question_stats):
    """错题统计 — 统计数字统一从 question_stats.json 读取"""
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

    # 按 wrong_count 降序排列
    sorted_qids = sorted(wrong_qids, key=lambda qid: question_stats.get(qid, {}).get("wrong_count", 0), reverse=True)
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

    mastery_data = get_mastery_distribution(questions, exam_type)
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
    """考试记录统计 — 四类记录：专项训练、模拟考试、巩固练习、错题练习"""

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

    # 全局表格样式（mock + 其他三类共用）
    st.markdown("""
    <style>
    .exam-records-table { width:100%; border-collapse:collapse; font-size:15px; }
    .exam-records-table th {
        background:#f3f4f6; color:#374151; font-weight:600;
        padding:12px 16px; text-align:left; border-bottom:2px solid #e5e7eb;
        white-space:nowrap;
    }
    .exam-records-table td { border-bottom:1px solid #f3f4f6; }
    .exam-records-table tr:hover td { background:#f9fafb; }
    </style>
    """, unsafe_allow_html=True)

    # ================================================================
    #  1. 专项训练记录（包含综合训练记录）
    # ================================================================
    st.markdown("### 🎯 专项训练记录（含综合训练）")

    spec_records = [r for r in exam_records if r.get("type") in ("exam", "specialized", "comprehensive")]
    _render_record_section(spec_records, TYPE_LABELS, default_label="综合训练")

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

        recent_sessions = sorted(
            exam_sessions.items(),
            key=lambda x: max(r.get("date", "") for r in x[1]),
            reverse=True
        )[:5]

        if recent_sessions:
            rows_html = ""
            for sid, records in recent_sessions:
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

                rows_html += (
                    f'<tr>'
                    f'<td style="white-space:nowrap;padding:12px 16px;color:#555;font-size:14px;">{date[:16] if date else ""}</td>'
                    f'<td style="padding:12px 16px;font-weight:500;">{type_str}</td>'
                    f'<td style="padding:12px 16px;">{total_html}</td>'
                    f'</tr>'
                )

            table_html = f"""
            <table class="exam-records-table">
            <thead><tr>
                <th style="width:150px;">考试日期</th>
                <th style="width:200px;">类型</th>
                <th>总分</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
            </table>
            """
            st.markdown(table_html, unsafe_allow_html=True)
        else:
            st.info("暂无模拟考试记录")

    # ================================================================
    #  3. 巩固练习记录
    # ================================================================
    st.markdown("---")
    st.markdown("### 🔁 巩固练习记录")

    consol_records = [r for r in exam_records if r.get("type") == "consolidation"]
    _render_record_section(consol_records, TYPE_LABELS, default_label="巩固练习")

    # ================================================================
    #  4. 错题练习记录
    # ================================================================
    st.markdown("---")
    st.markdown("### 📕 错题练习记录")

    wb_records = [r for r in exam_records if r.get("type") == "wrongbook"]
    _render_record_section(wb_records, TYPE_LABELS, default_label="错题练习")


def _render_record_section(records, type_labels, default_label="训练"):
    """渲染一段考试记录：汇总指标 + 最近记录表格"""
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

    # 最近 10 条记录
    recent = sorted(records, key=lambda r: r.get("date", ""), reverse=True)[:10]

    rows_html = ""
    for r in recent:
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

        rows_html += (
            f'<tr>'
            f'<td style="white-space:nowrap;padding:12px 16px;color:#555;font-size:14px;">{date}</td>'
            f'<td style="padding:12px 16px;font-weight:500;">{type_str}</td>'
            f'<td style="padding:12px 16px;">'
            f'<span style="color:{color};font-weight:600;">{correct}/{total}</span>'
            f'<span style="color:#999;margin-left:8px;font-size:13px;">{accuracy}</span>'
            f'</td>'
            f'</tr>'
        )

    table_html = f"""
    <table class="exam-records-table">
    <thead><tr>
        <th style="width:150px;">日期</th>
        <th style="width:220px;">类型</th>
        <th>正确率</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
    </table>
    """
    st.markdown(table_html, unsafe_allow_html=True)

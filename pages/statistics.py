"""
数据统计 - 独立的功能模块
从配置管理中拆分出来，展示系统各项数据的统计与分析
"""
import streamlit as st
import pandas as pd
from pathlib import Path
from utils.data_manager import (
    load_questions, load_wrong_questions, get_wrong_stats,
    load_exam_records, load_study_records, load_mock_exam_records,
    load_answer_records, load_question_stats,
    get_all_categories, get_category_count, _extract_qids_from_wrong_list,
)


def show_statistics():
    st.markdown("# 📊 数据统计")
    st.markdown("---")

    # 加载所有数据
    exam_type = st.session_state.get("exam_type")
    questions = st.session_state.questions
    wrong_list = load_wrong_questions()
    wrong_stats = get_wrong_stats(exam_type)
    exam_records = load_exam_records()
    study_records = load_study_records()
    mock_records = load_mock_exam_records()
    answer_records = load_answer_records()
    question_stats = load_question_stats()

    # 使用 Tab 组织各类统计
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📚 题库统计", "📕 错题统计", "📝 答题统计",
        "📋 考试记录", "📖 学习记录"
    ])

    with tab1:
        _show_question_stats(questions)

    with tab2:
        _show_wrong_stats(questions, wrong_list, wrong_stats)

    with tab3:
        _show_answer_stats(questions, answer_records, question_stats)

    with tab4:
        _show_exam_stats(exam_records, mock_records)

    with tab5:
        _show_study_stats(study_records)


def _show_question_stats(questions):
    """题库统计"""
    st.markdown("### 📚 题库总览")

    if not questions:
        st.info("📢 题库为空，请在配置管理中导入题库。")
        return

    # 总体统计
    total = len(questions)
    single_c = sum(1 for q in questions if q["type"] == "single")
    multi_c = sum(1 for q in questions if q["type"] == "multi")
    judge_c = sum(1 for q in questions if q["type"] == "judge")
    indefinite_c = sum(1 for q in questions if q["type"] == "indefinite")

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("📚 总题数", total)
    col2.metric("📝 单选题", single_c)
    col3.metric("📋 多选题", multi_c)
    col4.metric("⭕ 判断题", judge_c)
    if indefinite_c > 0:
        col5.metric("🟣 不定项", indefinite_c)

    st.markdown("---")

    # 知识板块分布
    cat_counts = get_category_count()
    if cat_counts:
        st.markdown("### 📂 知识板块分布")

        # 按指定顺序展示
        cat_order = [
            "心理学导论", "社会心理学", "人格心理学",
            "发展心理学", "异常心理学", "咨询心理学",
            "心理咨询会谈技术", "情绪调节与压力管理",
            "心理危机识别", "家庭教育与心理健康科普",
            "心理咨询专业伦理与相关法律规范",
        ]
        available_cats = [c for c in cat_order if c in cat_counts]
        for c in sorted(cat_counts.keys()):
            if c not in available_cats:
                available_cats.append(c)

        # 表格展示
        data = []
        for cat in available_cats:
            cnt = cat_counts[cat]
            # 统计该板块的题型分布
            single = sum(1 for q in questions if q.get("category", "") == cat and q["type"] == "single")
            multi = sum(1 for q in questions if q.get("category", "") == cat and q["type"] == "multi")
            judge = sum(1 for q in questions if q.get("category", "") == cat and q["type"] == "judge")
            data.append({
                "知识板块": cat,
                "总题数": cnt,
                "单选": single,
                "多选": multi,
                "判断": judge,
            })

        df = pd.DataFrame(data)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # 饼图/条形图展示
        st.markdown("#### 📊 各板块题量对比")
        cat_data = pd.DataFrame({
            "知识板块": list(available_cats),
            "题数": [cat_counts[c] for c in available_cats],
        })
        st.bar_chart(cat_data.set_index("知识板块"))

    st.markdown("---")

    # 题库来源文件统计
    st.markdown("### 📂 题库来源文件")

    files = {}
    for q in questions:
        fname = q.get("source_file", "未知")
        if fname not in files:
            files[fname] = {"single": 0, "multi": 0, "judge": 0, "total": 0}
        files[fname][q["type"]] = files[fname].get(q["type"], 0) + 1
        files[fname]["total"] += 1

    file_data = []
    for fname, stats in sorted(files.items()):
        file_data.append({
            "文件名": fname,
            "总题数": stats["total"],
            "单选": stats.get("single", 0),
            "多选": stats.get("multi", 0),
            "判断": stats.get("judge", 0),
        })

    df_files = pd.DataFrame(file_data)
    st.dataframe(df_files, use_container_width=True, hide_index=True)


def _show_wrong_stats(questions, wrong_list, wrong_stats):
    """错题统计 — 统计数字统一从 question_stats.json 读取"""
    st.markdown("### 📕 错题统计")
    question_stats = load_question_stats()
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


def _show_answer_stats(questions, answer_records, question_stats):
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

    # 按答题模式统计
    st.markdown("### 📋 各模式答题统计")

    mode_stats = {}
    for r in answer_records:
        mode = r.get("mode", "unknown")
        if mode not in mode_stats:
            mode_stats[mode] = {"total": 0, "correct": 0}
        mode_stats[mode]["total"] += 1
        if r.get("is_correct"):
            mode_stats[mode]["correct"] += 1

    mode_names = {
        "study": "背题系统",
        "exam": "综合训练",
        "specialized": "专项训练",
        "comprehensive": "综合训练",
        "mock_exam": "模拟考试",
        "wrongbook": "错题本",
    }

    if mode_stats:
        mode_data = []
        for mode, stats in sorted(mode_stats.items()):
            pct = stats["correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
            mode_data.append({
                "答题模式": mode_names.get(mode, mode),
                "答题次数": stats["total"],
                "答对次数": stats["correct"],
                "正确率": f"{pct:.1f}%",
            })
        df = pd.DataFrame(mode_data)
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # 按知识板块统计答题情况
    st.markdown("### 📂 各知识板块答题统计")

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

    # 最近答题记录
    st.markdown("---")
    st.markdown("### 📋 最近答题记录")

    if answer_records:
        recent = answer_records[-50:]
        recent.reverse()

        q_map = {q["id"]: q for q in questions}
        recent_data = []
        for r in recent:
            qid = r.get("question_id", "")
            q = q_map.get(qid)
            question_text = q.get("question", "")[:40] + "..." if q else f"(ID: {qid})"
            recent_data.append({
                "时间": r.get("timestamp", "")[11:19],
                "题目": question_text,
                "结果": "✅" if r.get("is_correct") else "❌",
                "模式": mode_names.get(r.get("mode", ""), r.get("mode", "")),
                "知识板块": r.get("category", ""),
            })

        if recent_data:
            df_recent = pd.DataFrame(recent_data)
            st.dataframe(df_recent, use_container_width=True, hide_index=True)


def _show_exam_stats(exam_records, mock_records):
    """考试记录统计"""
    st.markdown("### 📋 综合训练记录")

    # 综合训练记录（从 exam_records 中筛选 practice 模式）
    practice_records = [r for r in exam_records if r.get("mode") != "mock_exam"]

    if not practice_records:
        st.info("暂无综合训练记录。")
    else:
        cols = st.columns(3)
        cols[0].metric("📋 总训练次数", len(practice_records))
        avg_accuracy = sum(
            float(r.get("accuracy", "0%").replace("%", ""))
            for r in practice_records if r.get("accuracy")
        ) / len(practice_records) if practice_records else 0
        cols[1].metric("📊 平均正确率", f"{avg_accuracy:.1f}%")
        best = max(
            (float(r.get("accuracy", "0%").replace("%", "")) for r in practice_records if r.get("accuracy")),
            default=0
        )
        cols[2].metric("🏆 最高正确率", f"{best:.1f}%")

        # 最近记录
        st.markdown("#### 最近训练记录")
        recent = practice_records[-10:]
        recent.reverse()

        practice_data = []
        for r in recent:
            practice_data.append({
                "日期": r.get("date", "")[:16],
                "正确": f"{r.get('correct', 0)}/{r.get('total', 0)}",
                "正确率": r.get("accuracy", ""),
                "用时": r.get("duration", ""),
            })
        if practice_data:
            df = pd.DataFrame(practice_data)
            st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### 🎯 模拟考试记录")

    if not mock_records:
        st.info("暂无模拟考试记录。")
    else:
        # 按考试分组（一次完整考试=心理学综合+咨询实务）
        exam_sessions = {}
        for r in mock_records:
            sid = r.get("session_id", "")
            if sid not in exam_sessions:
                exam_sessions[sid] = []
            exam_sessions[sid].append(r)

        cols = st.columns(3)
        cols[0].metric("🎯 模拟考试次数", len(exam_sessions))
        cols[1].metric("📋 科目记录数", len(mock_records))

        # 最近考试
        st.markdown("#### 最近模拟考试记录")
        recent_sessions = sorted(
            exam_sessions.items(),
            key=lambda x: max(r.get("date", "") for r in x[1]),
            reverse=True
        )[:5]

        session_data = []
        for sid, records in recent_sessions:
            date = max(r.get("date", "") for r in records)
            psy = next((r for r in records if r.get("subject") == "psychology"), None)
            cou = next((r for r in records if r.get("subject") == "counseling"), None)

            psy_str = f"{psy.get('score', 0):.0f}/{psy.get('max_score', 0):.0f}" if psy else "未考"
            cou_str = f"{cou.get('score', 0):.0f}/{cou.get('max_score', 0):.0f}" if cou else "未考"

            total_score = (psy.get('score', 0) if psy else 0) + (cou.get('score', 0) if cou else 0)
            total_max = (psy.get('max_score', 0) if psy else 0) + (cou.get('max_score', 0) if cou else 0)

            session_data.append({
                "考试日期": date[:16] if date else "",
                "心理学综合": psy_str,
                "咨询实务": cou_str,
                "总分": f"{total_score:.0f}/{total_max:.0f}",
            })

        if session_data:
            df = pd.DataFrame(session_data)
            st.dataframe(df, use_container_width=True, hide_index=True)


def _show_study_stats(study_records):
    """学习记录统计"""
    st.markdown("### 📖 学习记录")

    if not study_records:
        st.info("暂无学习记录。")
        return

    # 筛选出背题模式（mode == "study"）的记录
    study_only = [r for r in study_records if r.get("mode") == "study"]
    practice_only = [r for r in study_records if r.get("mode") == "practice"]

    col1, col2, col3 = st.columns(3)
    col1.metric("📖 背题会话数", len(study_only))
    col2.metric("📝 训练会话数", len(practice_only))
    col3.metric("📋 总记录数", len(study_records))

    st.markdown("---")

    # 背题记录
    if study_only:
        st.markdown("#### 📖 背题记录")
        recent_study = study_only[-10:]
        recent_study.reverse()

        study_data = []
        for r in recent_study:
            status = "✅ 已完成" if r.get("status") == "completed" else "⏳ 进行中" if r.get("status") == "in_progress" else "❌ 已放弃"
            study_data.append({
                "时间": r.get("created_at", "")[:16],
                "状态": status,
                "总题数": r.get("total", 0),
                "正确": r.get("correct", "-"),
                "模式": "背题" if r.get("mode") == "study" else "训练",
            })

        df = pd.DataFrame(study_data)
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # 按天统计学习量
    st.markdown("#### 📅 每日学习量")

    daily_stats = {}
    for r in study_records:
        date_str = r.get("created_at", "")[:10]
        if not date_str:
            continue
        if date_str not in daily_stats:
            daily_stats[date_str] = {"sessions": 0, "total_questions": 0}
        daily_stats[date_str]["sessions"] += 1
        daily_stats[date_str]["total_questions"] += r.get("total", 0)

    if daily_stats:
        daily_data = []
        for date_str in sorted(daily_stats.keys(), reverse=True)[:30]:
            stats = daily_stats[date_str]
            daily_data.append({
                "日期": date_str,
                "学习次数": stats["sessions"],
                "学习题数": stats["total_questions"],
            })

        if daily_data:
            df = pd.DataFrame(daily_data)
            st.dataframe(df, use_container_width=True, hide_index=True)

            # 折线图
            st.markdown("#### 📈 学习趋势")
            chart_data = pd.DataFrame(daily_data)
            chart_data = chart_data.set_index("日期")
            st.line_chart(chart_data["学习题数"])

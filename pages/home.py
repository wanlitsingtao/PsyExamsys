"""
首页 - 系统概览
"""
import streamlit as st
from utils.data_manager import (
    load_questions, get_wrong_stats, load_exam_records,
    get_category_count, infer_category, load_study_records,
)


def show_home():
    st.markdown("# 🏠 心理咨询师考试背题系统")
    st.markdown("---")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("### 📊 学习概览")

        questions = st.session_state.questions
        if not questions:
            st.info("📢 题库为空！请先在左侧 **配置管理** 中导入题库文件。")
            return

        # 题库统计
        single_c = sum(1 for q in questions if q["type"] == "single")
        multi_c = sum(1 for q in questions if q["type"] == "multi")
        judge_c = sum(1 for q in questions if q["type"] == "judge")

        metrics_cols = st.columns(4)
        metrics_cols[0].metric("📚 题库总题", len(questions))
        metrics_cols[1].metric("📝 单选题", single_c)
        metrics_cols[2].metric("📋 多选题", multi_c)
        metrics_cols[3].metric("⭕ 判断题", judge_c)

        # 知识板块统计
        cat_counts = get_category_count()
        if cat_counts:
            st.markdown("**📂 知识板块分布**")
            cat_cols = st.columns(len(cat_counts))
            for i, (cat, cnt) in enumerate(sorted(cat_counts.items())):
                cat_cols[i].metric(cat, cnt)

        # 错题统计
        wrong_stats = get_wrong_stats()
        exam_records = load_exam_records()
        study_records = load_study_records()

        m_cols = st.columns(4)
        m_cols[0].metric("📕 错题总数", wrong_stats["total"])
        m_cols[1].metric("🏆 最高错题次数", wrong_stats["most_wrong"])
        m_cols[2].metric("📋 考试记录", len(exam_records))
        m_cols[3].metric("📖 背题记录", len([r for r in study_records if r.get("mode") == "study"]))

    with col2:
        st.markdown("### 🚀 快速入口")
        st.markdown("---")

        if st.button("📖 开始背题", use_container_width=True, type="primary"):
            st.session_state.nav_to = "专项训练"
            st.rerun()

        if st.button("📝 模拟考试", use_container_width=True, type="primary"):
            st.session_state.nav_to = "模拟考试"
            st.rerun()

        if st.button("📕 错题复习", use_container_width=True):
            st.session_state.nav_to = "错题本"
            st.rerun()

        if st.button("📊 数据统计", use_container_width=True):
            st.session_state.nav_to = "数据统计"
            st.rerun()

    # 题库来源
    st.markdown("---")
    st.markdown("### 📂 题库来源")

    # 统计来源文件
    if questions:
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

        # 显示来源文件表格
        import pandas as pd
        df = pd.DataFrame(file_data)
        st.dataframe(df, use_container_width=True, hide_index=True)

    # 考试记录
    if exam_records:
        st.markdown("---")
        st.markdown("### 📋 最近考试记录")
        recents = exam_records[-5:]
        recents.reverse()
        for r in recents:
            score = r.get("score", 0)
            total = r.get("total", 100)
            pct = f"{score/total*100:.1f}%" if total else "N/A"
            st.markdown(f"- {r.get('date','')}  |  得分 **{score}/{total}** ({pct})  |  用时 {r.get('duration','')}")

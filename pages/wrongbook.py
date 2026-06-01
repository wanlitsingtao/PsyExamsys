"""
错题本 v2.2 - 双入口模式
  1. 错题解析：按易错程度排序，左侧列表 + 右侧逐条解析
  2. 做错题：统一提交答题模式（原错题本功能）
"""
import streamlit as st
import uuid
from datetime import datetime
from utils.data_manager import (
    get_top_wrong_questions, check_answer, get_answer_display,
    add_wrong_record, add_correct_record, add_answer_record,
    remove_wrong_question, clear_all_wrong, get_wrong_stats,
    load_questions, infer_category, get_question_stats,
    get_all_wrong_with_stats,
)


def show_wrongbook():
    """错题本入口 — 根据模式路由"""
    mode = st.session_state.get("wb_mode", None)

    if mode is None:
        _show_wrongbook_home()
    elif mode == "analysis":
        _show_wrong_analysis()
    elif mode == "practice":
        _show_wrong_practice()


# ============================
#  主页 — 双入口
# ============================

def _show_wrongbook_home():
    st.markdown("# 📕 错题本")
    st.markdown("---")

    wrong_stats = get_wrong_stats(st.session_state.get("exam_type"))

    if wrong_stats["total"] == 0:
        # 清空练习模式缓存
        for key in ["wb_questions", "wb_wrong_counts", "wb_answers", "wb_submitted", "wb_results"]:
            st.session_state.pop(key, None)
        st.success("🎉 太棒了！错题本为空，继续加油！")
        return

    st.markdown(f"错题总数：**{wrong_stats['total']}**  |  最高答错次数：**{wrong_stats['most_wrong']}** 次")
    st.markdown("---")

    st.markdown("### 📖 错题解析")
    st.markdown(
        "按易错程度（答错次数 - 答对次数）由高到低排序，"
        "逐条查看题目、全部选项、正确答案和详细解析。"
        "适合深度理解错题背后的知识点。"
    )
    if st.button("📖 进入错题解析", key="btn_analysis", use_container_width=True, type="primary"):
        st.session_state.wb_mode = "analysis"
        st.session_state.wa_selected_idx = 0
        st.rerun()

    st.markdown("---")

    st.markdown("### ✏️ 做错题")
    st.markdown(
        "重新作答高频错题，检验知识掌握程度。"
        "提交后可以看到每道题的选项标记和正确答案。"
        "掌握后可移出错题本。"
    )
    if st.button("✏️ 进入做错题", key="btn_practice", use_container_width=True, type="primary"):
        st.session_state.wb_mode = "practice"
        st.session_state.wb_regenerate = True
        st.rerun()


# ============================
#  错题解析模式
# ============================

def _show_wrong_analysis():
    st.markdown("# 📖 错题解析")

    all_wrong = get_all_wrong_with_stats(st.session_state.get("exam_type"))

    if not all_wrong:
        st.success("🎉 没有错题！")
        return

    total = len(all_wrong)

    # 顶部导航栏
    top_cols = st.columns([3, 1])
    with top_cols[0]:
        st.markdown(f"共 **{total}** 题 · 按易错程度（答错次数 - 答对次数）由高到低排列")

    st.markdown("---")

    # 确保选中索引有效
    if "wa_selected_idx" not in st.session_state:
        st.session_state.wa_selected_idx = 0
    if st.session_state.wa_selected_idx >= total:
        st.session_state.wa_selected_idx = 0

    # ====== 左右布局 ======
    col_left, col_right = st.columns([1.5, 2])

    # ---- 左侧：错题列表 ----
    with col_left:
        st.markdown("#### 📋 错题列表")

        cur_idx = st.session_state.wa_selected_idx

        # 已选提示
        cur_item = all_wrong[cur_idx]
        st.markdown(
            f"<div style='background:#e3f2fd;padding:4px 8px;border-radius:4px;font-size:13px;margin:4px 0;'>"
            f"📍 第 {cur_idx+1}/{total} 题 · 易错指数 <b>{cur_item['diff']}</b> "
            f"（错{cur_item['wrong_count']}/对{cur_item['correct_count']}）</div>",
            unsafe_allow_html=True,
        )

        # 上一题 / 下一题快捷导航
        nav_c1, nav_c2 = st.columns(2)
        if nav_c1.button("◀ 上一题", use_container_width=True,
                         disabled=(cur_idx == 0)):
            st.session_state.wa_selected_idx -= 1
            st.rerun()
        if nav_c2.button("下一题 ▶", use_container_width=True,
                         disabled=(cur_idx >= total - 1)):
            st.session_state.wa_selected_idx += 1
            st.rerun()

        # 单选列表：直接点击题目切换
        st.caption(f"共 {total} 题，点击列表直接跳转：")
        option_labels = []
        for i, item in enumerate(all_wrong):
            wc = item["wrong_count"]
            cc = item["correct_count"]
            diff = item["diff"]
            q_short = item["question"][:35] + "..." if len(item["question"]) > 35 else item["question"]
            diff_icon = "🔴" if diff >= 3 else ("🟠" if diff >= 2 else "🟡")
            option_labels.append(
                f"{diff_icon} {i+1}. 错{wc}/对{cc} [{item['type_label']}] {q_short}"
            )

        with st.container(height=480):
            selected = st.radio(
                "错题清单",
                options=list(range(total)),
                format_func=lambda i: option_labels[i],
                index=cur_idx,
                key="wa_radio_list",
                label_visibility="collapsed",
            )

        if selected != cur_idx:
            st.session_state.wa_selected_idx = selected
            st.rerun()

    # ---- 右侧：解析详情 ----
    with col_right:
        _render_analysis_detail(all_wrong[cur_idx], cur_idx, total)


def _render_analysis_detail(item, idx, total):
    """渲染错题解析详情（右侧面板）"""
    st.markdown(f"#### 第 {idx+1}/{total} 题")

    # 题型 + 板块
    st.markdown(
        f"**{item['type_label']}** · 📂 {item.get('category', '未知')}  "
        f"|  ⚠️ 答错 {item['wrong_count']} 次  |  ✅ 答对 {item['correct_count']} 次  "
        f"|  易错指数：{item['diff']}"
    )

    # 题目
    st.markdown("---")
    st.markdown(f"**📝 题目：** {item['question']}")

    # 全部选项（正确答案用绿色标注）
    st.markdown("**选项：**")
    options = item["options"]
    opt_keys = sorted(options.keys())
    correct_ans = item["answer"].strip().upper()

    for k in opt_keys:
        is_correct = k in correct_ans
        if is_correct:
            st.markdown(f'<p style="color:green;font-weight:bold;">✅ {k}: {options[k]}</p>',
                        unsafe_allow_html=True)
        else:
            st.markdown(f'{k}: {options[k]}')

    # 正确答案
    correct_display = get_answer_display(item["type"], correct_ans, options)
    st.info(f"**✅ 正确答案**：{correct_display}")

    # 解析
    explanation = item.get("explanation", "")
    if explanation:
        with st.expander("📖 题目解析", expanded=True):
            st.markdown(explanation)

    # 底部操作
    st.markdown("---")
    op_cols = st.columns([1, 1])
    if op_cols[0].button("◀ 上一题", key="detail_prev_btn", use_container_width=True,
                         disabled=(idx == 0)):
        st.session_state.wa_selected_idx -= 1
        st.rerun()
    if op_cols[1].button("下一题 ▶", key="detail_next_btn", use_container_width=True,
                         disabled=(idx >= total - 1)):
        st.session_state.wa_selected_idx += 1
        st.rerun()


# ============================
#  做错题模式（原错题本答题功能）
# ============================

def _show_wrong_practice():
    st.markdown("# ✏️ 做错题")

    wrong_stats = get_wrong_stats(st.session_state.get("exam_type"))
    config = st.session_state.config

    if wrong_stats["total"] == 0:
        for key in ["wb_questions", "wb_wrong_counts", "wb_answers", "wb_submitted", "wb_results"]:
            st.session_state.pop(key, None)
        st.success("🎉 太棒了！错题本为空，继续加油！")
        return

    # 返回按钮
    top_cols = st.columns([1])
    with top_cols[0]:
        st.markdown(f"错题总数: **{wrong_stats['total']}**  |  最高答错次数: **{wrong_stats['most_wrong']}** 次")

    # 检测文件数据是否已变化（其他模块可能已更新错题库）
    cached_total = st.session_state.get("wb_cached_total", -1)
    if cached_total != wrong_stats["total"]:
        st.session_state.wb_regenerate = True

    # 初始化错题学习状态
    if "wb_questions" not in st.session_state or st.session_state.get("wb_regenerate"):
        count = config["wrongbook_extract_count"]
        top_wrong = get_top_wrong_questions(count, st.session_state.get("exam_type"))

        if not top_wrong:
            st.warning("⚠️ 没有可提取的错题")
            return

        st.session_state.wb_questions = [item[0] for item in top_wrong]
        st.session_state.wb_wrong_counts = {item[0]["id"]: item[1] for item in top_wrong}
        st.session_state.wb_current = 0
        st.session_state.wb_answers = {}
        st.session_state.wb_submitted = False
        st.session_state.wb_results = {}
        st.session_state.wb_regenerate = False
        st.session_state.wb_cached_total = wrong_stats["total"]

    wq = st.session_state.wb_questions
    if not wq:
        st.info("错题已全部掌握！")
        return

    total_q = len(wq)
    idx = st.session_state.wb_current
    q = wq[idx]
    qid = q["id"]
    is_submitted = st.session_state.wb_submitted

    # ---- 顶部信息 ----
    wrong_count = st.session_state.wb_wrong_counts.get(qid, 0)
    answered = len(st.session_state.wb_answers)
    correct_count = sum(1 for v in st.session_state.wb_results.values() if v.get("correct"))

    progress = answered / total_q if total_q > 0 else 0
    st.progress(progress, text=f"进度: {answered}/{total_q}")

    meta_cols = st.columns([1, 1, 1, 2])
    meta_cols[0].markdown(f"**进度**: {answered}/{total_q}")
    if is_submitted:
        meta_cols[1].markdown(f"**正确**: {correct_count}")
        meta_cols[2].markdown(f"**正确率**: {correct_count/max(answered,1)*100:.1f}%")
    else:
        meta_cols[1].markdown(f"**已答**: {answered}")
        meta_cols[2].markdown(f"**未答**: {total_q - answered}")

    with meta_cols[3]:
        col_r1, col_r2 = st.columns(2)
        if col_r1.button("🔄 重新组卷", use_container_width=True, disabled=not is_submitted):
            st.session_state.wb_regenerate = True
            st.rerun()
        if col_r2.button("🗑️ 清空错题", use_container_width=True, disabled=not is_submitted):
            st.session_state.wb_confirm_clear = True

    if st.session_state.get("wb_confirm_clear"):
        st.warning("⚠️ 确认清空所有错题吗？此操作不可恢复！")
        c1, c2 = st.columns(2)
        if c1.button("✅ 确认清空", use_container_width=True):
            clear_all_wrong()
            st.session_state.wb_questions = []
            st.session_state.wb_confirm_clear = False
            st.rerun()
        if c2.button("❌ 取消", use_container_width=True):
            st.session_state.wb_confirm_clear = False
            st.rerun()

    st.markdown("---")

    if is_submitted:
        # ======== 已提交状态：显示结果 ========
        result = st.session_state.wb_results.get(qid, {})
        correct = result.get("correct", False)

        type_labels = {"single": "🔵 单选题", "multi": "🟢 多选题", "judge": "🟠 判断题"}
        st.markdown(f"### 第 {idx+1}/{total_q} 题  |  ⚠️ 答错 {wrong_count} 次")
        st.markdown(f"**{type_labels[q['type']]}**"
                    f"{' · 📂 ' + q.get('category', infer_category(q.get('source_file', ''))) if q.get('category') or q.get('source_file') else ''}")
        st.markdown(f"**{q['question']}**")

        # 获取本题完整历史答题统计
        q_stats = get_question_stats(qid)
        stats_parts = []
        if q_stats["correct_count"] > 0 or q_stats["wrong_count"] > 0:
            stats_parts.append(f"答对 {q_stats['correct_count']} 次 / 答错 {q_stats['wrong_count']} 次")
        last_correct = q_stats.get("last_correct")
        if last_correct is True:
            stats_parts.append("🟢 上次答对")
        elif last_correct is False:
            stats_parts.append("🔴 上次答错")
        if stats_parts:
            st.caption("📊 " + " · ".join(stats_parts))

        options = q["options"]
        opt_keys = sorted(options.keys())

        if correct:
            st.success("✅ **回答正确！**")
        else:
            st.error("❌ **回答错误！**")

        for k in opt_keys:
            user_ans = st.session_state.wb_answers.get(qid, "")
            is_selected = k in user_ans
            is_correct_key = k in q["answer"]

            if q["type"] == "multi":
                if is_selected and is_correct_key:
                    st.markdown(f'<p style="color:green;font-weight:bold;">✅ {k}: {options[k]}</p>',
                                unsafe_allow_html=True)
                elif is_selected and not is_correct_key:
                    st.markdown(f'<p style="color:red;font-weight:bold;">❌ {k}: {options[k]}</p>',
                                unsafe_allow_html=True)
                elif not is_selected and is_correct_key:
                    st.markdown(f'<p style="color:green;">{k}: {options[k]} (漏选)</p>',
                                unsafe_allow_html=True)
                else:
                    st.markdown(f'{k}: {options[k]}')
            else:
                if is_selected and is_correct_key:
                    st.markdown(f'<p style="color:green;font-weight:bold;">✅ {k}: {options[k]}</p>',
                                unsafe_allow_html=True)
                elif is_selected and not is_correct_key:
                    st.markdown(f'<p style="color:red;font-weight:bold;">❌ {k}: {options[k]}</p>',
                                unsafe_allow_html=True)
                elif not is_selected and is_correct_key:
                    st.markdown(f'<p style="color:green;font-weight:bold;">✅ {k}: {options[k]}</p>',
                                unsafe_allow_html=True)
                else:
                    st.markdown(f'{k}: {options[k]}')

        correct_display = get_answer_display(q["type"], q["answer"], options)
        st.info(f"**正确答案**: {q['answer']} - {correct_display}")

        if q.get("explanation"):
            with st.expander("📖 查看解析", expanded=True):
                st.markdown(q["explanation"])

        if st.button("✅ 我已掌握本题（从错题本移除）", use_container_width=True):
            remove_wrong_question(qid)
            wq_updated = [w for w in st.session_state.wb_questions if w["id"] != qid]
            st.session_state.wb_questions = wq_updated
            if not wq_updated:
                st.session_state.wb_submitted = False
            if st.session_state.wb_current >= len(st.session_state.wb_questions):
                st.session_state.wb_current = max(0, len(st.session_state.wb_questions) - 1)
            st.rerun()

    else:
        # ======== 未提交状态：答题模式 ========
        type_labels = {"single": "🔵 单选题", "multi": "🟢 多选题", "judge": "🟠 判断题"}
        st.markdown(f"### 第 {idx+1}/{total_q} 题  |  ⚠️ 答错 {wrong_count} 次")
        st.markdown(f"**{type_labels[q['type']]}**"
                    f"{' · 📂 ' + q.get('category', infer_category(q.get('source_file', ''))) if q.get('category') or q.get('source_file') else ''}")
        st.markdown(f"**{q['question']}**")

        # 获取本题完整历史答题统计
        q_stats = get_question_stats(qid)
        stats_parts = []
        if q_stats["correct_count"] > 0 or q_stats["wrong_count"] > 0:
            stats_parts.append(f"答对 {q_stats['correct_count']} 次 / 答错 {q_stats['wrong_count']} 次")
        last_correct = q_stats.get("last_correct")
        if last_correct is True:
            stats_parts.append("🟢 上次答对")
        elif last_correct is False:
            stats_parts.append("🔴 上次答错")
        if stats_parts:
            st.caption("📊 " + " · ".join(stats_parts))

        options = q["options"]
        opt_keys = sorted(options.keys())
        user_ans = st.session_state.wb_answers.get(qid, "")

        if q["type"] in ("single", "judge"):
            options_list = [f"{k}: {options[k]}" for k in opt_keys]
            idx_in_list = None
            for i, opt in enumerate(options_list):
                if opt.startswith(user_ans + ":"):
                    idx_in_list = i
                    break

            selected_opt = st.radio(
                "请选择答案：",
                options_list,
                key=f"wb_radio_{qid}",
                index=idx_in_list,
                label_visibility="collapsed",
            )
            if selected_opt:
                selected_key = selected_opt.split(":")[0]
                if st.session_state.wb_answers.get(qid) != selected_key:
                    st.session_state.wb_answers[qid] = selected_key

        elif q["type"] == "multi":
            cols = st.columns(2)
            selected_keys = []
            for i, k in enumerate(opt_keys):
                col = cols[i % 2]
                checked = col.checkbox(
                    f"{k}: {options[k]}",
                    key=f"wb_cb_{qid}_{k}",
                    value=(k in user_ans),
                )
                if checked:
                    selected_keys.append(k)

            if selected_keys:
                ans_str = "".join(sorted(selected_keys))
                if st.session_state.wb_answers.get(qid) != ans_str:
                    st.session_state.wb_answers[qid] = ans_str
                st.caption(f"已选: {', '.join(selected_keys)}")
            else:
                st.caption("请选择至少一个选项")

    st.markdown("---")

    # ---- 操作按钮 ----
    nav_cols = st.columns([1, 1, 1])

    if not is_submitted:
        if nav_cols[0].button("📤 提交全部答案", type="primary", use_container_width=True):
            _submit_wrongbook()
            st.rerun()
    else:
        if nav_cols[0].button("🔄 重新组卷", use_container_width=True):
            st.session_state.wb_regenerate = True
            st.rerun()

    if nav_cols[1].button("◀ 上一题", use_container_width=True, disabled=(idx == 0)):
        st.session_state.wb_current = idx - 1
        st.rerun()

    if nav_cols[2].button("下一题 ▶", use_container_width=True, disabled=(idx >= total_q - 1)):
        st.session_state.wb_current = idx + 1
        st.rerun()

    # ---- 底部导航网格 ----
    st.markdown("---")
    st.markdown("#### 📌 题目导航")

    cols_per_row = 10
    rows = (total_q + cols_per_row - 1) // cols_per_row

    nav_html = '<div style="display:flex;flex-direction:column;gap:2px;">'
    for row in range(rows):
        nav_html += '<div style="display:flex;gap:2px;">'
        for col_idx in range(cols_per_row):
            q_idx = row * cols_per_row + col_idx
            if q_idx >= total_q:
                nav_html += '<div style="flex:1;min-width:0;"></div>'
                continue
            q_item = wq[q_idx]
            q_id = q_item["id"]

            if is_submitted:
                is_correct_q = st.session_state.wb_results.get(q_id, {}).get("correct", False)
                bg = "#2e7d32" if is_correct_q else "#c62828"
                text_color = "white"
            else:
                if q_id in st.session_state.wb_answers:
                    bg = "#f9a825"
                    text_color = "white"
                else:
                    bg = "#ffffff"
                    text_color = "#333"

            border = "2px solid #1976d2" if q_idx == idx else "1px solid #ddd"

            nav_html += f'''
            <div style="flex:1;min-width:0;">
                <span onclick="var p=new URLSearchParams(window.location.search);p.set('nav_wb_to','{q_idx}');window.location.search=p.toString();"
                   style="display:block;width:100%;background:{bg};color:{text_color};border:{border};
                          border-radius:3px;font-size:12px;min-height:30px;line-height:30px;
                          text-align:center;text-decoration:none;cursor:pointer;">
                    {q_idx + 1}
                </span>
            </div>'''
        nav_html += '</div>'
    nav_html += '</div>'

    st.markdown(nav_html, unsafe_allow_html=True)

    # 用 query params 做导航
    params = st.query_params
    nav_target = params.get("nav_wb_to")
    if nav_target is not None:
        try:
            target_idx = int(nav_target)
            if 0 <= target_idx < total_q and target_idx != idx:
                st.session_state.wb_current = target_idx
                del params["nav_wb_to"]
                st.query_params = params
                st.rerun()
        except (ValueError, KeyError):
            pass

    # 完成提示
    if is_submitted and total_q > 0:
        st.markdown("---")
        pct = correct_count / total_q * 100
        if pct >= 80:
            st.balloons()
            st.success(f"🎉 **错题复习完成！** 正确率: {pct:.1f}%")
        else:
            st.info(f"📖 **错题复习完成！** 正确率: {pct:.1f}%。继续加油！")


def _submit_wrongbook():
    """统一提交所有错题答案"""
    wq = st.session_state.wb_questions
    answers = st.session_state.wb_answers
    results = {}
    session_id = str(uuid.uuid4())[:8]

    for q in wq:
        qid = q["id"]
        user_ans = answers.get(qid, "")
        is_correct = check_answer(q["type"], user_ans, q["answer"])

        results[qid] = {"correct": is_correct}

        add_answer_record(
            question_id=qid,
            user_answer=user_ans,
            is_correct=is_correct,
            mode="wrongbook",
            session_id=session_id,
        )

        if is_correct:
            add_correct_record(qid)
        else:
            add_wrong_record(qid, user_ans)

    st.session_state.wb_results = results
    st.session_state.wb_submitted = True

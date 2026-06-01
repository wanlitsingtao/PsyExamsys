"""
专项训练 - 按知识板块选择训练 + 综合训练（全模块随机抽题）
统一提交模式，更新错题本

功能：
1. 综合训练：从全部知识模块题库中随机抽取60题（30单选+20多选+10判断）
2. 知识板块专项训练：共11个知识板块，用户选择后从该板块抽60题（30单选+20多选+10判断）
"""
import streamlit as st
import uuid
from datetime import datetime
from utils.data_manager import (
    extract_questions_by_category, extract_questions, check_answer, get_answer_display,
    batch_update_wrong_and_stats, batch_add_answer_records,
    get_all_categories, infer_category, get_question_stats,
    load_config, get_category_training_stats, load_question_stats,
)


def show_specialized():
    st.markdown("# 🎯 专项训练")
    st.markdown("---")

    questions = st.session_state.questions
    if not questions:
        st.warning("⚠️ 题库为空，请先在配置管理中导入题库！")
        return

    # 初始化状态
    if "spec_state" not in st.session_state:
        st.session_state.spec_state = "idle"

    # ======== 状态路由 ========
    if st.session_state.spec_state == "idle":
        _show_spec_start(questions)
        return

    if st.session_state.spec_state == "running":
        _show_spec_running()
        return

    if st.session_state.spec_state == "finished":
        _show_spec_result()
        return


def _clear_spec_show_ans():
    """清除所有题目的答案展开状态（新训练开始时调用）"""
    keys_to_clear = [k for k in st.session_state if k.startswith("spec_show_ans_")]
    for k in keys_to_clear:
        del st.session_state[k]


def _show_spec_start(questions):
    """显示专项训练开始界面——选择模式"""
    config = load_config()

    # 获取所有知识板块统计
    cats = get_all_categories(questions)
    if not cats:
        st.warning("⚠️ 题库为空，无法进行专项训练")
        return

    # 获取各板块答题统计
    cat_stats = get_category_training_stats(questions)

    spec_single = config.get("spec_single_count", 30)
    spec_multi = config.get("spec_multi_count", 20)
    spec_judge = config.get("spec_judge_count", 10)
    comp_single = config.get("comp_single_count", 30)
    comp_multi = config.get("comp_multi_count", 20)
    comp_judge = config.get("comp_judge_count", 10)

    # 综合训练统计数据
    comp_total_all = sum(info["total"] for info in cats.values())
    comp_actual_single = min(comp_single, sum(info["single"] for info in cats.values()))
    comp_actual_multi = min(comp_multi, sum(info["multi"] for info in cats.values()))
    comp_actual_judge = min(comp_judge, sum(info["judge"] for info in cats.values()))
    comp_actual_total = comp_actual_single + comp_actual_multi + comp_actual_judge

    # 综合训练答题统计（汇总所有板块）
    comp_answered = sum(cs.get("answered", 0) for cs in cat_stats.values())
    comp_correct = sum(cs.get("correct", 0) for cs in cat_stats.values())
    comp_wrong = sum(cs.get("wrong", 0) for cs in cat_stats.values())

    # 将11个板块按顺序展示：基础理论6个 + 咨询实务5个
    cat_order = [
        "心理学导论", "社会心理学", "人格心理学",
        "发展心理学", "异常心理学", "咨询心理学",
        "心理咨询会谈技术", "情绪调节与压力管理",
        "心理危机识别", "家庭教育与心理健康科普",
        "心理咨询专业伦理与相关法律规范",
    ]

    # 过滤出实际存在的板块
    available_cats = [c for c in cat_order if c in cats]
    # 加上可能存在但不在顺序中的板块
    for c in sorted(cats.keys()):
        if c not in available_cats:
            available_cats.append(c)

    # ---------- 注入 CSS：所有按钮红底白字（Streamlit 原生红色）----------
    st.markdown("""
    <style>
    /* 所有按钮：红底白字 */
    div[data-testid="stButton"] button {
        background-color: #ff4b4b !important;
        border-color: #ff4b4b !important;
        color: #ffffff !important;
    }
    /* 悬停状态：稍深的红色 */
    div[data-testid="stButton"] button:hover {
        background-color: #e03e3e !important;
        border-color: #e03e3e !important;
        color: #ffffff !important;
    }
    /* 禁用按钮：浅红背景，灰色边框 */
    div[data-testid="stButton"] button:disabled {
        background-color: #ffadad !important;
        border-color: #ccc !important;
        color: #888 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # 分两列展示选择卡片（综合训练 + 各知识板块）
    col1, col2 = st.columns(2)

    selected_mode = None  # "comprehensive" or category_name
    idx = 0

    # ---- 综合训练卡片（放在最前面） ----
    with col1:
        with st.container(border=True):
            st.markdown("**✅ 📊 综合训练**")
            st.caption(f"总 {comp_total_all} 题 | 已答 {comp_answered} 题 | 对 {comp_correct} 题 | 错 {comp_wrong} 题")
            if st.button("🚀 开始综合训练",
                        use_container_width=True,
                        type="primary",
                        key="spec_start_comprehensive"):
                selected_mode = "comprehensive"
    idx += 1

    # ---- 各知识板块卡片 ----
    for cat in available_cats:
        info = cats[cat]
        col = col1 if idx % 2 == 0 else col2
        idx += 1

        # 计算实际可抽取的各题型数量（最多不超过配置数）
        actual_single = min(info["single"], spec_single)
        actual_multi = min(info["multi"], spec_multi)
        actual_judge = min(info["judge"], spec_judge)
        actual_total = actual_single + actual_multi + actual_judge

        # 只要该板块有题目就可以开始训练（不再强制三类题型都满足最低数量）
        can_start = actual_total > 0

        # 判断是否有题型不足，给出提示
        all_full = (info["single"] >= spec_single and
                    info["multi"] >= spec_multi and
                    info["judge"] >= spec_judge)
        status_icon = "✅" if all_full else "⚠️"

        # 获取该板块的答题统计
        cs = cat_stats.get(cat, {"total": info["total"], "answered": 0, "correct": 0, "wrong": 0})

        with col.container(border=True):
            st.markdown(f"**{status_icon} {cat}**")
            st.caption(f"总 {info['total']} 题 | "
                       f"已答 {cs['answered']} 题 | "
                       f"对 {cs['correct']} 题 | "
                       f"错 {cs['wrong']} 题")
            if st.button(f"🚀 开始训练「{cat}」",
                        use_container_width=True,
                        disabled=not can_start,
                        key=f"spec_start_{cat}"):
                selected_mode = cat

    st.markdown("---")

    # 处理选择
    if selected_mode == "comprehensive":
        _start_comprehensive(questions)
    elif selected_mode:
        _start_specialized(questions, selected_mode)


def _start_comprehensive(questions):
    """开始综合训练（从全部模块随机抽题）"""
    _clear_spec_show_ans()
    config = load_config()

    # 使用配置中的题数（默认 30单选 + 20多选 + 10判断 = 60题）
    comp_single = config.get("comp_single_count", 30)
    comp_multi = config.get("comp_multi_count", 20)
    comp_judge = config.get("comp_judge_count", 10)

    selected = extract_questions(
        questions,
        dan_count=comp_single,
        duo_count=comp_multi,
        pan_count=comp_judge,
        shuffle_types=False,
    )

    if not selected:
        st.error("❌ 没有可用的题目")
        st.session_state.spec_state = "idle"
        return

    session_id = str(uuid.uuid4())[:8]

    single_end = sum(1 for q in selected if q["type"] == "single")
    multi_end = single_end + sum(1 for q in selected if q["type"] == "multi")

    st.session_state.spec_questions = selected
    st.session_state.spec_current = 0
    st.session_state.spec_answers = {}
    st.session_state.spec_state = "running"
    st.session_state.spec_session_id = session_id
    st.session_state.spec_category = "综合训练"
    st.session_state.spec_confirm_submit = False
    st.session_state.spec_type_boundaries = {
        "single_end": single_end,
        "multi_end": multi_end,
    }
    st.session_state.spec_mode = "comprehensive"
    st.rerun()


def _start_specialized(questions, category):
    """开始专项训练"""
    _clear_spec_show_ans()
    config = load_config()
    # 使用配置中的题数（默认 30单选 + 20多选 + 10判断 = 60题）
    spec_single = config.get("spec_single_count", 30)
    spec_multi = config.get("spec_multi_count", 20)
    spec_judge = config.get("spec_judge_count", 10)

    selected = extract_questions_by_category(
        questions,
        category=category,
        dan_count=spec_single,
        duo_count=spec_multi,
        pan_count=spec_judge,
    )

    if not selected:
        st.error(f"❌ 板块「{category}」没有可用的题目")
        st.session_state.spec_state = "idle"
        return

    session_id = str(uuid.uuid4())[:8]

    single_end = sum(1 for q in selected if q["type"] == "single")
    multi_end = single_end + sum(1 for q in selected if q["type"] == "multi")

    st.session_state.spec_questions = selected
    st.session_state.spec_current = 0
    st.session_state.spec_answers = {}
    st.session_state.spec_state = "running"
    st.session_state.spec_session_id = session_id
    st.session_state.spec_category = category
    st.session_state.spec_confirm_submit = False
    st.session_state.spec_type_boundaries = {
        "single_end": single_end,
        "multi_end": multi_end,
    }
    st.session_state.spec_mode = "specialized"
    st.rerun()


def _show_spec_running():
    """显示专项训练进行中的界面（与背题系统统一）"""
    sq = st.session_state.spec_questions
    total_q = len(sq)
    idx = st.session_state.spec_current
    q = sq[idx]
    qid = q["id"]
    boundaries = st.session_state.spec_type_boundaries
    category = st.session_state.spec_category
    mode = st.session_state.get("spec_mode", "specialized")

    # 缓存答题统计（避免每次渲染读文件）
    if "spec_stats_cache" not in st.session_state:
        st.session_state.spec_stats_cache = load_question_stats()

    # 标题行 + 返回按钮（同行居右）
    mode_label = "综合训练" if mode == "comprehensive" else "专项训练"
    title_col, back_col = st.columns([5, 1])
    with title_col:
        st.markdown(f"### 🎯 {mode_label}：**{category}**")
    with back_col:
        if st.button("← 返回训练选择", key="spec_back_to_start", use_container_width=True):
            st.session_state.spec_state = "idle"
            keys_to_clear = [k for k in st.session_state if k.startswith("spec_")]
            for key in keys_to_clear:
                del st.session_state[key]
            st.rerun()
    st.markdown("---")

    # 已答/未答统计
    answered = len(st.session_state.spec_answers)
    unanswered = total_q - answered

    meta_cols = st.columns([1, 1, 1, 1, 2])
    meta_cols[0].markdown(f"**已答**: {answered}")
    meta_cols[1].markdown(f"**未答**: {unanswered}")
    meta_cols[2].markdown(f"**进度**: {answered}/{total_q}")

    # 题型段标签
    se = boundaries["single_end"]
    me = boundaries["multi_end"]
    meta_cols[3].markdown(
        f"🔵 {se}题 / 🟢 {me-se}题 / 🟠 {total_q-me}题",
        help="蓝色=单选题 | 绿色=多选题 | 橙色=判断题"
    )

    submit_check = meta_cols[4].button("📤 提交所有答案", use_container_width=True, type="primary")
    if submit_check:
        st.session_state.spec_confirm_submit = True

    if st.session_state.get("spec_confirm_submit"):
        st.warning(f"⚠️ 还有 {unanswered} 题未答，确认提交吗？未答题将计为错误。")
        col_c1, col_c2 = st.columns(2)
        if col_c1.button("✅ 确认提交", use_container_width=True):
            _finish_specialized()
            return
        if col_c2.button("❌ 继续答题", use_container_width=True):
            st.session_state.spec_confirm_submit = False
            st.rerun()

    st.markdown("---")

    # 全局选项样式（注入一次，避免每次渲染重复）
    st.markdown("""
    <style>
    div[data-testid="stRadio"] > div { gap: 0.5em; }
    div[data-testid="stRadio"] > div > label { padding: 0.3em 0; }
    div[data-testid="stCheckbox"] > label { padding: 0.3em 0; }
    </style>
    """, unsafe_allow_html=True)

    # ---- 题目显示 ----
    type_labels = {"single": "🔵 单选题", "multi": "🟢 多选题", "judge": "🟠 判断题"}

    # 获取本题答题统计（从缓存读取，避免每次渲染读文件）
    q_stats = st.session_state.spec_stats_cache.get(qid, {"correct_count": 0, "wrong_count": 0, "last_answer_time": None, "last_correct": None})

    # 题号行：左侧题号，右侧历史统计 + 上次对错
    title_cols = st.columns([1, 2])
    with title_cols[0]:
        st.markdown(f"### 第 {idx+1}/{total_q} 题")
    with title_cols[1]:
        stats_parts = []
        if q_stats["correct_count"] > 0 or q_stats["wrong_count"] > 0:
            stats_parts.append(f"📊 答对 {q_stats['correct_count']} 次 / 答错 {q_stats['wrong_count']} 次")
        last_correct = q_stats.get("last_correct")
        if last_correct is True:
            stats_parts.append("🟢 上次答对")
        elif last_correct is False:
            stats_parts.append("🔴 上次答错")
        if stats_parts:
            st.markdown(f"<div style='text-align:right;padding-top:0.5em;color:#888;font-size:16px;'>{'&nbsp;&nbsp;|&nbsp;&nbsp;'.join(stats_parts)}</div>", unsafe_allow_html=True)

    st.markdown(f"**{type_labels[q['type']]}**"
                f" · 📂 {q.get('category', category)}")
    st.markdown(f"**{q['question']}**")

    options = q["options"]
    opt_keys = sorted(options.keys())

    user_ans = st.session_state.spec_answers.get(qid, "")

    if q["type"] == "single" or q["type"] == "judge":
        options_list = [f"{k}: {options[k]}" for k in opt_keys]
        idx_in_list = None
        for i, opt in enumerate(options_list):
            if opt.startswith(user_ans + ":"):
                idx_in_list = i
                break

        selected_opt = st.radio(
            "请选择答案：",
            options_list,
            key=f"spec_radio_{qid}",
            index=idx_in_list,
            label_visibility="collapsed",
        )
        if selected_opt:
            selected_key = selected_opt.split(":")[0]
            if st.session_state.spec_answers.get(qid) != selected_key:
                st.session_state.spec_answers[qid] = selected_key

    elif q["type"] == "multi":
        cols = st.columns(2)
        selected_keys = []
        for i, k in enumerate(opt_keys):
            col = cols[i % 2]
            checked = col.checkbox(
                f"{k}: {options[k]}",
                key=f"spec_cb_{qid}_{k}",
                value=(k in user_ans),
            )
            if checked:
                selected_keys.append(k)

        if selected_keys:
            ans_str = "".join(sorted(selected_keys))
            if st.session_state.spec_answers.get(qid) != ans_str:
                st.session_state.spec_answers[qid] = ans_str
            st.caption(f"已选: {', '.join(selected_keys)}")
        else:
            st.caption("请选择至少一个选项")

    # 查看答案功能（切换式：展开/收起）
    st.markdown("---")
    show_answer_key = f"spec_show_ans_{qid}"
    showing = st.session_state.get(show_answer_key, False)
    btn_label = "🙈 收起答案" if showing else "📖 查看答案"
    btn_key = f"spec_toggle_ans_{qid}"

    # 使用 on_click 回调避免双重 rerun：状态在脚本体之前更新
    def _toggle_answer():
        st.session_state[show_answer_key] = not st.session_state.get(show_answer_key, False)

    st.button(btn_label, key=btn_key, use_container_width=False, on_click=_toggle_answer)
    if showing:
        correct_display = get_answer_display(q["type"], q["answer"], options)
        st.info(f"**正确答案**: {q['answer']} - {correct_display}")
        if q.get("explanation"):
            with st.expander("📖 查看解析", expanded=True):
                st.markdown(q["explanation"])

    st.markdown("---")

    # 导航按钮（使用 on_click 回调避免双重 rerun）
    nav_cols = st.columns([1, 2, 1])

    def _go_prev():
        st.session_state.spec_current = max(0, st.session_state.spec_current - 1)

    def _go_next():
        st.session_state.spec_current = min(total_q - 1, st.session_state.spec_current + 1)

    nav_cols[0].button("◀ 上一题", use_container_width=True,
                       disabled=(idx == 0), on_click=_go_prev)
    nav_cols[2].button("下一题 ▶", use_container_width=True,
                       disabled=(idx >= total_q - 1), on_click=_go_next)

    # ---- 答题卡 ----
    st.markdown("---")
    st.markdown("#### 📌 答题卡")

    st.progress(answered / total_q, text=f"已答 {answered}/{total_q}")

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
            q_item = sq[q_idx]
            q_id = q_item["id"]

            bg = "#f9a825" if q_id in st.session_state.spec_answers else "#ffffff"
            border = "2px solid #1976d2" if q_idx == idx else "1px solid #ddd"
            text_color = "#333" if bg == "#ffffff" else "white"

            nav_html += f'''
            <div style="flex:1;min-width:0;">
                <span onclick="var p=new URLSearchParams(window.location.search);p.set('nav_spec_to','{q_idx}');window.location.search=p.toString();"
                   style="display:block;width:100%;background:{bg};color:{text_color};border:{border};
                          border-radius:3px;font-size:12px;min-height:30px;line-height:30px;
                          text-align:center;text-decoration:none;cursor:pointer;">
                    {q_idx + 1}
                </span>
            </div>'''
        nav_html += '</div>'
    nav_html += '</div>'

    st.markdown(nav_html, unsafe_allow_html=True)

    # query params 导航
    params = st.query_params
    nav_target = params.get("nav_spec_to")
    if nav_target is not None:
        try:
            target_idx = int(nav_target)
            if 0 <= target_idx < total_q and target_idx != idx:
                st.session_state.spec_current = target_idx
                del params["nav_spec_to"]
                st.query_params = params
                st.rerun()
        except (ValueError, KeyError):
            pass


def _finish_specialized():
    """结束专项训练，计算成绩并更新错题本"""
    sq = st.session_state.spec_questions
    total_q = len(sq)
    answers = st.session_state.spec_answers
    category = st.session_state.spec_category
    mode = st.session_state.get("spec_mode", "specialized")

    correct_count = 0
    details = []
    wrong_qids = []      # 收集答错的
    correct_qids = []    # 收集答对的
    answer_records = []  # 收集答题记录

    for q in sq:
        qid = q["id"]
        user_ans = answers.get(qid, "")
        is_correct = check_answer(q["type"], user_ans, q["answer"])

        if is_correct:
            correct_count += 1
            correct_qids.append(qid)
        else:
            wrong_qids.append((qid, user_ans))

        # 收集答题记录
        answer_records.append({
            "question_id": qid,
            "user_answer": user_ans,
            "is_correct": is_correct,
            "mode": "specialized" if mode == "specialized" else "comprehensive",
            "session_id": st.session_state.get("spec_session_id", ""),
        })

        details.append({
            "id": q["id"],
            "index": q["index"],
            "type": q["type"],
            "question": q["question"],
            "options": q.get("options", {}),
            "explanation": q.get("explanation", ""),
            "user_answer": user_ans,
            "correct_answer": q["answer"],
            "is_correct": is_correct,
            "category": q.get("category", category),
        })

    # 批量更新错题库和答题统计（单次读取+单次写入）
    stats_updates = [(qid, True) for qid in correct_qids] + [(qid, False) for qid, _ in wrong_qids]
    batch_update_wrong_and_stats(wrong_qids, correct_qids, stats_updates)

    # 刷新统计缓存，确保结果页读到最新数据
    st.session_state.spec_stats_cache = load_question_stats()

    # 批量追加答题记录
    batch_add_answer_records(answer_records)

    # 分题型统计
    type_stats = {}
    for d in details:
        tp = d["type"]
        if tp not in type_stats:
            type_stats[tp] = {"total": 0, "correct": 0}
        type_stats[tp]["total"] += 1
        if d["is_correct"]:
            type_stats[tp]["correct"] += 1

    # 按知识板块统计
    cat_stats = {}
    for d in details:
        cat = d.get("category", "未知")
        if cat not in cat_stats:
            cat_stats[cat] = {"total": 0, "correct": 0}
        cat_stats[cat]["total"] += 1
        if d["is_correct"]:
            cat_stats[cat]["correct"] += 1

    # 保存结果到 session
    st.session_state.spec_result = {
        "total": total_q,
        "correct": correct_count,
        "accuracy": f"{correct_count/total_q*100:.1f}%",
        "category": category,
        "details": details,
        "type_stats": type_stats,
        "category_stats": cat_stats,
        "mode": mode,
    }
    st.session_state.spec_state = "finished"
    st.rerun()


def _show_spec_result():
    """显示专项训练结果"""
    result = st.session_state.spec_result
    total = result["total"]
    correct = result["correct"]
    accuracy = result["accuracy"]
    category = result["category"]
    details = result["details"]
    type_stats = result.get("type_stats", {})
    cat_stats = result.get("category_stats", {})
    mode = result.get("mode", "specialized")

    mode_label = "综合训练" if mode == "comprehensive" else "专项训练"
    st.markdown(f"# 📊 {mode_label}报告：**{category}**")
    st.markdown("---")

    cols = st.columns(3)
    cols[0].metric("✅ 正确", f"{correct}/{total}")
    cols[1].metric("📊 正确率", accuracy)
    cols[2].metric("❌ 错误", f"{total - correct}")

    # 分题型统计
    st.markdown("---")
    st.markdown("### 分题型统计")

    type_names = {"single": "单选题", "multi": "多选题", "judge": "判断题"}

    for tp, stats in type_stats.items():
        pct = stats["correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
        st.markdown(f"**{type_names[tp]}**: {stats['correct']}/{stats['total']} 正确 ({pct:.1f}%)")
        st.progress(stats["correct"] / max(stats["total"], 1))

    # 知识板块统计（综合训练时展示各板块正确率）
    if cat_stats and mode == "comprehensive":
        st.markdown("---")
        st.markdown("### 📂 知识板块分析")
        for cat, stats in sorted(cat_stats.items()):
            pct = stats["correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
            st.markdown(f"**{cat}**: {stats['correct']}/{stats['total']} 正确 ({pct:.1f}%)")
            st.progress(stats["correct"] / max(stats["total"], 1))

    # 每题详情
    st.markdown("---")
    st.markdown("### 📋 题目详情")

    for i, d in enumerate(details):
        tp_label = {"single": "单选", "multi": "多选", "judge": "判断"}[d["type"]]
        status_icon = "✅" if d["is_correct"] else "❌"
        user_label = d.get("user_answer", "未答") or "未答"
        correct_display = get_answer_display(
            d["type"], d["correct_answer"], d.get("options", {})
        )
        with st.expander(f"{i+1}. {status_icon} [{tp_label}] {d['question'][:60]}...", expanded=not d["is_correct"]):
            st.markdown(f"**题目**: {d['question']}")
            # 显示所有选项
            options = d.get("options", {})
            for k, v in sorted(options.items()):
                st.markdown(f"{k}: {v}")
            st.markdown(f"**你的答案**: {user_label}")
            st.markdown(f"**正确答案**: {d['correct_answer']} - {correct_display}")
            # 解析（直接跟在正确答案后面）
            explanation = d.get("explanation", "")
            if explanation:
                st.markdown(explanation)
            st.markdown(f"**知识板块**: {d.get('category', category)}")
            q_stats = st.session_state.spec_stats_cache.get(
                d.get("id", ""), {"correct_count": 0, "wrong_count": 0}
            )
            st.caption(f"📊 答题统计：答对 {q_stats['correct_count']} 次 / 答错 {q_stats['wrong_count']} 次")

    # 答题卡
    st.markdown("---")
    st.markdown("#### 📌 答题卡（🟢=正确 🔴=错误/漏答）")
    sq = st.session_state.spec_questions
    total_q = len(sq)
    cols_per_row = 10
    rows = (total_q + cols_per_row - 1) // cols_per_row
    details_by_idx = {d["index"]: d for d in details}
    nav_html = '<div style="display:flex;flex-direction:column;gap:2px;">'
    for row in range(rows):
        nav_html += '<div style="display:flex;gap:2px;">'
        for col_idx in range(cols_per_row):
            q_idx = row * cols_per_row + col_idx
            if q_idx >= total_q:
                nav_html += '<div style="flex:1;min-width:0;"></div>'
                continue
            q_item = sq[q_idx]
            d = details_by_idx.get(q_item["index"], {})
            is_correct = d.get("is_correct", False)
            bg = "#2e7d32" if is_correct else "#c62828"
            nav_html += f'''
            <div style="flex:1;min-width:0;">
                <div style="display:block;width:100%;background:{bg};color:white;border:1px solid #555;
                          border-radius:3px;font-size:12px;min-height:30px;line-height:30px;
                          text-align:center;">
                    {q_idx + 1}
                </div>
            </div>'''
        nav_html += '</div>'
    nav_html += '</div>'
    st.markdown(nav_html, unsafe_allow_html=True)

    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    if col1.button("🔄 再来一次", key="spec_result_retry", use_container_width=True):
        st.session_state.spec_state = "idle"
        # 保留 spec_selected_category 以便回到分类选择页
        keep_keys = {"spec_selected_category"}
        keys_to_clear = [k for k in st.session_state if k.startswith("spec_") and k not in keep_keys]
        for key in keys_to_clear:
            del st.session_state[key]
        st.rerun()
    if col2.button("🏠 返回首页", key="spec_result_home", use_container_width=True, type="primary"):
        st.session_state.spec_state = "idle"
        # 清除全部 spec_ 状态，彻底返回首页
        keys_to_clear = [k for k in st.session_state if k.startswith("spec_")]
        for key in keys_to_clear:
            del st.session_state[key]
        st.rerun()

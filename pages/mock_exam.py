"""
模拟考试系统 - 实际考试模型（固定规则，不可配置）
两科独立计时、独立提交：
  1. 心理学综合（上午）：150单选×0.4 + 50多选×0.6 + 50判断×0.2 = 120分钟
  2. 咨询实务（下午）：140单选×0.4 + 60多选×0.6 + 10不定项×0.8 = 120分钟
"""
import streamlit as st
import time
import uuid
from datetime import datetime
from utils.data_manager import (
    MOCK_EXAM_CONFIG, extract_questions_by_super, check_answer, get_answer_display,
    batch_update_wrong_and_stats, batch_add_answer_records,
    save_mock_exam_record, infer_category, get_question_stats,
)


def show_mock_exam():
    """模拟考试入口"""
    st.markdown("# 🎯 模拟考试")

    questions = st.session_state.questions
    if not questions:
        st.warning("⚠️ 题库为空，请先在配置管理中导入题库！")
        return

    # 初始化状态
    if "mock_state" not in st.session_state:
        st.session_state.mock_state = "idle"

    if st.session_state.mock_state == "idle":
        _show_mock_start()
    elif st.session_state.mock_state == "psychology":
        _show_exam_subject("psychology")
    elif st.session_state.mock_state == "psychology_finished":
        _show_subject_result("psychology")
    elif st.session_state.mock_state == "counseling":
        _show_exam_subject("counseling")
    elif st.session_state.mock_state == "counseling_finished":
        _show_subject_result("counseling")
    elif st.session_state.mock_state == "all_finished":
        _show_final_result()


def _show_mock_start():
    """显示模拟考试开始界面"""
    psy = MOCK_EXAM_CONFIG["psychology"]
    cou = MOCK_EXAM_CONFIG["counseling"]

    st.markdown("---")
    st.markdown("### 🚀 选择考试科目")
    st.markdown("请选择先考的科目（两科独立计时、独立提交）：")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### 📘 第一科：心理学综合")
        st.markdown(f"- 单选 {psy['single_count']} 题（每题 {psy['single_score']} 分）")
        st.markdown(f"- 多选 {psy['multi_count']} 题（每题 {psy['multi_score']} 分）")
        st.markdown(f"- 判断 {psy['judge_count']} 题（每题 {psy['judge_score']} 分）")
        st.markdown(f"- 时间：{psy['time_minutes']} 分钟")
        st.markdown("---")
        if st.button("📘 开始心理学综合", use_container_width=True, type="primary", key="start_psy"):
            _start_subject("psychology")

    with col_b:
        st.markdown("#### 📗 第二科：咨询实务")
        st.markdown(f"- 单选 {cou['single_count']} 题（每题 {cou['single_score']} 分）")
        st.markdown(f"- 多选 {cou['multi_count']} 题（每题 {cou['multi_score']} 分）")
        if cou["judge_count"] > 0:
            st.markdown(f"- 判断 {cou['judge_count']} 题（每题 {cou['judge_score']} 分）")
        if cou.get("indefinite_count", 0) > 0:
            st.markdown(f"- 不定项 {cou['indefinite_count']} 题（每题 {cou['indefinite_score']} 分）")
        st.markdown(f"- 时间：{cou['time_minutes']} 分钟")
        st.markdown("---")
        if st.button("📗 开始咨询实务", use_container_width=True, type="primary", key="start_cou"):
            _start_subject("counseling")

    st.markdown("---")
    st.markdown("### 📋 考试规则")

    # 心理学综合
    st.markdown("#### 📘 第一科：心理学综合（9:30—11:30）")
    psy_total = psy["single_count"] + psy["multi_count"] + psy["judge_count"]
    psy_max = psy["single_count"] * psy["single_score"] + psy["multi_count"] * psy["multi_score"] + psy["judge_count"] * psy["judge_score"]
    st.markdown(f"- 共 **{psy_total}** 题 | 满分 **{psy_max:.0f}** 分 | 时间 **{psy['time_minutes']}** 分钟")
    st.markdown(f"  - 单选题 {psy['single_count']} 题（每题 {psy['single_score']} 分）")
    st.markdown(f"  - 多选题 {psy['multi_count']} 题（每题 {psy['multi_score']} 分）")
    st.markdown(f"  - 判断题 {psy['judge_count']} 题（每题 {psy['judge_score']} 分）")
    st.markdown(f"  - 出题顺序：**单选题 → 多选题 → 判断题**")
    st.markdown("")

    # 咨询实务
    st.markdown("#### 📗 第二科：咨询实务（13:00—15:00）")
    cou_total = cou["single_count"] + cou["multi_count"] + cou["judge_count"] + cou["indefinite_count"]
    cou_max = cou["single_count"] * cou["single_score"] + cou["multi_count"] * cou["multi_score"] + cou["judge_count"] * cou["judge_score"] + cou["indefinite_count"] * cou["indefinite_score"]
    st.markdown(f"- 共 **{cou_total}** 题 | 满分 **{cou_max:.0f}** 分 | 时间 **{cou['time_minutes']}** 分钟")
    st.markdown(f"  - 单选题 {cou['single_count']} 题（每题 {cou['single_score']} 分）")
    st.markdown(f"  - 多选题 {cou['multi_count']} 题（每题 {cou['multi_score']} 分）")
    if cou["indefinite_count"] > 0:
        st.markdown(f"  - 不定项选择题 {cou['indefinite_count']} 题（每题 {cou['indefinite_score']} 分）")
    st.markdown(f"  - 出题顺序：**单选题 → 多选题 → 不定项选择题**")
    st.markdown("")

    st.markdown("**规则说明：**")
    st.markdown("- 两科独立计时、独立提交")
    st.markdown("- 先考心理学综合，提交后方可进入咨询实务")
    st.markdown("- 多选题/不定项选择题需**完全选对**才得分（漏选/多选均不得分）")
    st.markdown("- 未答题目视为错误")
    st.markdown("- 答错自动计入错题本（以最后一次答题结果为准）")
    st.markdown("- 中途退出**不会**保存进度")


def _start_subject(subject_key):
    """开始某一科的考试"""
    # 清除上一科的答案展开状态
    keys_to_clear = [k for k in st.session_state if k.startswith("mock_show_ans_")]
    for k in keys_to_clear:
        del st.session_state[k]

    # 如果切换到下一科，先把当前科的成绩保存到 prev
    if subject_key != st.session_state.get("mock_subject"):
        current_result = st.session_state.get("mock_result")
        if current_result is not None:
            st.session_state.mock_prev_result = current_result

    cfg = MOCK_EXAM_CONFIG[subject_key]
    session_id = str(uuid.uuid4())[:8]

    # 根据科目映射到超类进行题目抽取
    super_category_map = {"psychology": "心理学综合", "counseling": "咨询实务"}
    super_cat = super_category_map.get(subject_key, "")

    indefinite_count = cfg.get("indefinite_count", 0)
    selected = extract_questions_by_super(
        st.session_state.questions,
        super_category=super_cat,
        dan_count=cfg["single_count"],
        duo_count=cfg["multi_count"],
        pan_count=cfg["judge_count"],
        indefinite_count=indefinite_count,
        shuffle_types=False,
    )

    # 计算各题型边界
    single_end = sum(1 for q in selected if q["type"] == "single")
    multi_end = single_end + sum(1 for q in selected if q["type"] == "multi")
    judge_end = multi_end + sum(1 for q in selected if q["type"] == "judge")

    st.session_state.mock_subject = subject_key
    st.session_state.mock_questions = selected
    st.session_state.mock_current = 0
    st.session_state.mock_answers = {}
    st.session_state.mock_marked = set()
    st.session_state.mock_start_time = time.time()
    st.session_state.mock_end_time = time.time() + cfg["time_minutes"] * 60
    st.session_state.mock_confirm_submit = False
    st.session_state.mock_session_id = session_id
    st.session_state.mock_type_boundaries = {
        "single_end": single_end,
        "multi_end": multi_end,
        "judge_end": judge_end,
    }
    st.session_state.mock_state = subject_key
    st.rerun()


def _show_exam_subject(subject_key):
    """显示某一科的考试进行中界面"""
    cfg = MOCK_EXAM_CONFIG[subject_key]
    eq = st.session_state.mock_questions
    total_q = len(eq)
    idx = st.session_state.mock_current
    q = eq[idx]
    qid = q["id"]
    boundaries = st.session_state.mock_type_boundaries

    # 标题行 + 返回按钮（同行居右）
    cfg_name = cfg["name"]
    title_col, back_col = st.columns([5, 1])
    with title_col:
        st.markdown(f"## 🎯 模拟考试 — {cfg_name}")
    with back_col:
        if st.button("← 返回科目选择", key="mock_back_to_start", use_container_width=True):
            st.session_state.mock_state = "idle"
            keys_to_clear = [
                "mock_subject", "mock_questions", "mock_current",
                "mock_answers", "mock_start_time", "mock_end_time",
                "mock_confirm_submit", "mock_session_id", "mock_type_boundaries",
                "mock_result", "mock_prev_result",
            ]
            for key in keys_to_clear:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()

    # 倒计时
    now = time.time()
    remaining = st.session_state.mock_end_time - now

    if remaining <= 0:
        _finish_subject(subject_key)
        return

    mins = int(remaining // 60)
    secs = int(remaining % 60)
    time_str = f"{mins:02d}:{secs:02d}"

    if remaining < 300:
        st.error(f"⏰ **{time_str}** (⚠️ 时间不足5分钟！)")
    elif remaining < 600:
        st.warning(f"⏰ **{time_str}**")
    else:
        st.info(f"⏰ 剩余时间: **{time_str}**")

    # 已答/未答统计
    answered = len(st.session_state.mock_answers)
    unanswered = total_q - answered

    meta_cols = st.columns([1, 1, 1, 1, 2])
    meta_cols[0].markdown(f"**已答**: {answered}")
    meta_cols[1].markdown(f"**未答**: {unanswered}")
    meta_cols[2].markdown(f"**进度**: {answered}/{total_q}")

    # 题型段标签
    se = boundaries["single_end"]
    me = boundaries["multi_end"]
    je = boundaries["judge_end"]
    type_labels_parts = [f"🔵 {se}题"]
    if me - se > 0:
        type_labels_parts.append(f"🟢 {me-se}题")
    if je - me > 0:
        type_labels_parts.append(f"🟠 {je-me}题")
    if total_q - je > 0:
        type_labels_parts.append(f"🟣 {total_q-je}题")
    meta_cols[3].markdown(
        " / ".join(type_labels_parts),
        help="🔵=单选 🟢=多选 🟠=判断 🟣=不定项"
    )

    submit_check = meta_cols[4].button("📤 提交试卷", use_container_width=True, type="primary")
    if submit_check:
        st.session_state.mock_confirm_submit = True

    if st.session_state.get("mock_confirm_submit"):
        st.warning(f"⚠️ 还有 {unanswered} 题未答，确认提交吗？未答题将计为错误。")
        col_c1, col_c2 = st.columns(2)
        if col_c1.button("✅ 确认提交", use_container_width=True):
            _finish_subject(subject_key)
            return
        if col_c2.button("❌ 继续答题", use_container_width=True):
            st.session_state.mock_confirm_submit = False
            st.rerun()

    st.markdown("---")

    # 全局选项样式（注入一次，避免每次渲染重复）
    st.markdown("""
    <style>
    div[data-testid="stRadio"] > div { gap: 0.75em; }
    div[data-testid="stRadio"] > div > label { padding: 0.3em 0; }
    div[data-testid="stCheckbox"] > label { padding: 0.3em 0; }
    </style>
    """, unsafe_allow_html=True)

    # 题目显示
    type_labels = {"single": "🔵 单选题", "multi": "🟢 多选题", "judge": "🟠 判断题", "indefinite": "🟣 不定项选择题"}
    
    st.markdown(f"### 第 {idx+1}/{total_q} 题")
    
    category = q.get('category', infer_category(q.get('source_file', '')))
    
    title_col1, title_col2 = st.columns([8, 2])
    with title_col1:
        st.markdown(f"**{type_labels.get(q['type'], q['type'])}**"
                    f"{' · 📂 ' + category if category else ''}")
    with title_col2:
        marked = qid in st.session_state.mock_marked
        if st.button("⭐ 标记" if marked else "☆ 标记",
                     key=f"mock_mark_{qid}",
                     help="取消标记" if marked else "标记此题",
                     use_container_width=True):
            if qid in st.session_state.mock_marked:
                st.session_state.mock_marked.discard(qid)
            else:
                st.session_state.mock_marked.add(qid)
            st.rerun()
    
    st.markdown(f"**{q['question']}**")

    # 获取本题历史答题统计
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
    user_ans = st.session_state.mock_answers.get(qid, "")

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
            key=f"mock_radio_{qid}",
            index=idx_in_list,
            label_visibility="collapsed",
        )
        if selected_opt:
            selected_key = selected_opt.split(":")[0]
            if st.session_state.mock_answers.get(qid) != selected_key:
                st.session_state.mock_answers[qid] = selected_key
    elif q["type"] in ("multi", "indefinite"):
        cols = st.columns(2)
        selected_keys = []
        for i, k in enumerate(opt_keys):
            col = cols[i % 2]
            checked = col.checkbox(
                f"{k}: {options[k]}",
                key=f"mock_cb_{qid}_{k}",
                value=(k in user_ans),
            )
            if checked:
                selected_keys.append(k)

        if selected_keys:
            ans_str = "".join(sorted(selected_keys))
            if st.session_state.mock_answers.get(qid) != ans_str:
                st.session_state.mock_answers[qid] = ans_str
            st.caption(f"已选: {', '.join(selected_keys)}")
        else:
            st.caption("请选择至少一个选项")

    st.markdown("---")

    # 查看答案功能（切换式：展开/收起）
    show_answer_key = f"mock_show_ans_{qid}"
    showing = st.session_state.get(show_answer_key, False)
    btn_label = "🙈 收起答案" if showing else "📖 查看答案"
    if st.button(btn_label, key=f"mock_toggle_ans_{qid}", use_container_width=False):
        st.session_state[show_answer_key] = not showing
        st.rerun()
    if showing:
        correct_display = get_answer_display(q["type"], q["answer"], options)
        st.markdown(
            f'<div style="background:#e8f5e9;border-left:4px solid #1b5e20;padding:8px 12px;'
            f'border-radius:4px;margin:4px 0;">'
            f'<span style="color:#1b5e20;font-weight:bold;">✅ 正确答案：{q["answer"]} - {correct_display}</span></div>',
            unsafe_allow_html=True,
        )
        if q.get("explanation"):
            with st.expander("📖 查看解析", expanded=True):
                st.markdown(q["explanation"])

    # 导航按钮
    nav_cols = st.columns([1, 2, 1])
    if nav_cols[0].button("◀ 上一题", use_container_width=True, disabled=(idx == 0)):
        st.session_state.mock_current = idx - 1
        st.rerun()

    if nav_cols[2].button("下一题 ▶", use_container_width=True, disabled=(idx >= total_q - 1)):
        st.session_state.mock_current = idx + 1
        st.rerun()

    # 答题卡
    st.markdown("---")
    st.markdown("#### 📌 答题卡")

    # 筛选按钮
    filter_key = "mock_card_filter"
    if filter_key not in st.session_state:
        st.session_state[filter_key] = "all"

    fc1, fc2, fc3, fc4 = st.columns(4)
    if fc1.button("📋 全部", key="mock_filter_all", use_container_width=True,
                  type="primary" if st.session_state[filter_key] == "all" else "secondary"):
        st.session_state[filter_key] = "all"
        st.rerun()
    if fc2.button("✅ 已答", key="mock_filter_answered", use_container_width=True,
                  type="primary" if st.session_state[filter_key] == "answered" else "secondary"):
        st.session_state[filter_key] = "answered"
        st.rerun()
    if fc3.button("⬜ 未答", key="mock_filter_unanswered", use_container_width=True,
                  type="primary" if st.session_state[filter_key] == "unanswered" else "secondary"):
        st.session_state[filter_key] = "unanswered"
        st.rerun()
    if fc4.button("⭐ 已标记", key="mock_filter_marked", use_container_width=True,
                  type="primary" if st.session_state[filter_key] == "marked" else "secondary"):
        st.session_state[filter_key] = "marked"
        st.rerun()

    filter_mode = st.session_state[filter_key]
    marked_count = len(st.session_state.mock_marked)
    st.progress(answered / total_q, text=f"已答 {answered}/{total_q}" + (f" · 已标记 {marked_count}" if marked_count else ""))

    cols_per_row = 10
    rows = (total_q + cols_per_row - 1) // cols_per_row

    for row in range(rows):
        cols = st.columns(cols_per_row)
        for col_idx in range(cols_per_row):
            q_idx = row * cols_per_row + col_idx
            with cols[col_idx]:
                if q_idx >= total_q:
                    st.empty()
                    continue
                q_item = eq[q_idx]
                q_id = q_item["id"]

                # 筛选逻辑
                show = True
                if filter_mode == "answered" and q_id not in st.session_state.mock_answers:
                    show = False
                if filter_mode == "unanswered" and q_id in st.session_state.mock_answers:
                    show = False
                if filter_mode == "marked" and q_id not in st.session_state.mock_marked:
                    show = False

                if not show:
                    st.empty()
                    continue

                is_answered = q_id in st.session_state.mock_answers
                is_marked = q_id in st.session_state.mock_marked
                is_current = q_idx == idx

                label = str(q_idx + 1)

                btn_type = "primary" if is_answered else "secondary"

                # 当前题高亮
                if is_current:
                    st.markdown(
                        '<div style="border:2px solid #1565c0;border-radius:6px;background:#e3f2fd;padding:1px 2px;">',
                        unsafe_allow_html=True
                    )

                badge_color = "#ff9800" if is_marked else "transparent"
                badge_char = "★" if is_marked else "&nbsp;"
                st.markdown(
                    f'<div style="text-align:right;font-size:10px;color:{badge_color};'
                    f'height:14px;line-height:14px;margin-bottom:-4px;">{badge_char}</div>',
                    unsafe_allow_html=True
                )

                if st.button(label, key=f"mock_nav_{q_idx}", use_container_width=True, type=btn_type):
                    st.session_state.mock_current = q_idx
                    st.rerun()

                if is_current:
                    st.markdown('</div>', unsafe_allow_html=True)


def _finish_subject(subject_key):
    """结束某一科考试，计算成绩"""
    cfg = MOCK_EXAM_CONFIG[subject_key]
    eq = st.session_state.mock_questions
    total_q = len(eq)
    answers = st.session_state.mock_answers
    start_time = st.session_state.mock_start_time
    duration = time.time() - start_time

    # 计分
    correct_count = 0
    total_score = 0.0
    details = []
    wrong_qids = []      # 收集答错的 (qid, user_ans)
    correct_qids = []    # 收集答对的 qid
    answer_records = []  # 收集答题记录

    for q in eq:
        qid = q["id"]
        user_ans = answers.get(qid, "")
        is_correct = check_answer(q["type"], user_ans, q["answer"])
        score = 0
        if is_correct:
            if q["type"] == "single":
                score = cfg["single_score"]
            elif q["type"] == "multi":
                score = cfg["multi_score"]
            elif q["type"] == "judge":
                score = cfg["judge_score"]
            elif q["type"] == "indefinite":
                score = cfg["indefinite_score"]
            correct_count += 1
            total_score += score
            correct_qids.append(qid)
        else:
            wrong_qids.append((qid, user_ans))

        answer_records.append({
            "question_id": qid,
            "user_answer": user_ans,
            "is_correct": is_correct,
            "mode": "mock_exam",
            "session_id": st.session_state.get("mock_session_id", ""),
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
            "score": score,
            "category": q.get("category", infer_category(q.get("source_file", ""))),
        })

    # 批量更新错题库和答题统计（单次读取+单次写入）
    stats_updates = [(qid, True) for qid in correct_qids] + [(qid, False) for qid, _ in wrong_qids]
    batch_update_wrong_and_stats(wrong_qids, correct_qids, stats_updates)

    # 批量追加答题记录
    batch_add_answer_records(answer_records)

    duration_str = f"{int(duration // 60)}分{int(duration % 60)}秒"

    # 按知识板块统计
    cat_stats = {}
    for d in details:
        cat = d.get("category", "未知")
        if cat not in cat_stats:
            cat_stats[cat] = {"total": 0, "correct": 0}
        cat_stats[cat]["total"] += 1
        if d["is_correct"]:
            cat_stats[cat]["correct"] += 1

    # 计算满分
    max_score = (
        cfg["single_count"] * cfg["single_score"]
        + cfg["multi_count"] * cfg["multi_score"]
        + cfg["judge_count"] * cfg["judge_score"]
        + cfg.get("indefinite_count", 0) * cfg.get("indefinite_score", 0)
    )

    result = {
        "total": total_q,
        "correct": correct_count,
        "score": round(total_score, 1),
        "max_score": round(max_score, 1),
        "duration": duration_str,
        "accuracy": f"{correct_count/total_q*100:.1f}%",
        "details": details,
        "category_stats": cat_stats,
    }

    st.session_state.mock_result = result

    # 保存记录
    record = {
        "subject": subject_key,
        "subject_name": cfg["name"],
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": total_q,
        "correct": correct_count,
        "score": round(total_score, 1),
        "max_score": round(max_score, 1),
        "duration": duration_str,
        "accuracy": f"{correct_count/total_q*100:.1f}%",
        "status": "completed",
        "session_id": st.session_state.get("mock_session_id", ""),
        "category_stats": cat_stats,
    }
    save_mock_exam_record(record)

    st.session_state.mock_state = f"{subject_key}_finished"
    st.rerun()


def _show_subject_result(subject_key):
    """显示某一科的成绩"""
    cfg = MOCK_EXAM_CONFIG[subject_key]
    result = st.session_state.mock_result
    total = result["total"]
    correct = result["correct"]
    score = result["score"]
    max_score = result["max_score"]
    duration = result["duration"]
    details = result["details"]
    cat_stats = result.get("category_stats", {})

    accuracy = correct / total * 100

    st.markdown(f"# 📊 {cfg['name']} - 成绩报告")
    st.markdown("---")

    cols = st.columns(4)
    cols[0].metric("✅ 正确", f"{correct}/{total}", f"{accuracy:.1f}%")
    cols[1].metric("📊 得分", f"{score:.1f} / {max_score:.1f}")
    cols[2].metric("⏱️ 用时", duration)
    cols[3].metric("📈 准确率", f"{accuracy:.1f}%")

    # 分题型统计
    st.markdown("---")
    st.markdown("### 分题型统计")

    type_stats = {}
    for d in details:
        tp = d["type"]
        if tp not in type_stats:
            type_stats[tp] = {"total": 0, "correct": 0, "score": 0.0}
        type_stats[tp]["total"] += 1
        if d["is_correct"]:
            type_stats[tp]["correct"] += 1
            type_stats[tp]["score"] += d["score"]

    type_names = {"single": "单选题", "multi": "多选题", "judge": "判断题", "indefinite": "不定项选择题"}

    for tp, stats in type_stats.items():
        pct = stats["correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
        st.markdown(f"**{type_names.get(tp, tp)}**: {stats['correct']}/{stats['total']} 正确 ({pct:.1f}%)")
        st.progress(stats["correct"] / max(stats["total"], 1))

    # 知识板块统计
    if cat_stats:
        st.markdown("---")
        st.markdown("### 📂 知识板块分析")
        for cat, stats in sorted(cat_stats.items()):
            pct = stats["correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
            st.markdown(f"**{cat}**: {stats['correct']}/{stats['total']} 正确 ({pct:.1f}%)")
            st.progress(stats["correct"] / max(stats["total"], 1))

    # 错题回顾
    st.markdown("---")
    wrong_details = [d for d in details if not d["is_correct"]]
    if wrong_details:
        st.markdown(f"### ❌ 错题回顾 ({len(wrong_details)}题)")
        for i, d in enumerate(wrong_details):
            tp_label = {"single": "单选", "multi": "多选", "judge": "判断", "indefinite": "不定项"}.get(d["type"], d["type"])
            cat_label = d.get("category", "")
            user_ans = d.get("user_answer", "").strip().upper()
            correct_ans = d["correct_answer"].strip().upper()
            options = d.get("options", {})
            opt_keys = sorted(options.keys())

            with st.expander(f"{i+1}. [{tp_label}] {d['question'][:60]}...", expanded=True):
                st.markdown(f"**题目**: {d['question']}")

                # 显示所有选项，用颜色标记
                for k in opt_keys:
                    is_user_selected = k in user_ans
                    is_correct_key = k in correct_ans

                    if d["type"] in ("multi", "indefinite"):
                        if is_user_selected and is_correct_key:
                            st.markdown(f'<p style="color:#1b5e20;font-weight:bold;">✅ {k}: {options[k]}</p>',
                                        unsafe_allow_html=True)
                        elif is_user_selected and not is_correct_key:
                            st.markdown(f'<p style="color:#b71c1c;font-weight:bold;">❌️ {k}: {options[k]} (错选)</p>',
                                        unsafe_allow_html=True)
                        elif not is_user_selected and is_correct_key:
                            st.markdown(f'<p style="color:#1b5e20;font-weight:bold;">✅ {k}: {options[k]} (漏选)</p>',
                                        unsafe_allow_html=True)
                        else:
                            st.markdown(f'{k}: {options[k]}')
                    else:
                        if is_user_selected and is_correct_key:
                            st.markdown(f'<p style="color:#1b5e20;font-weight:bold;">✅ {k}: {options[k]}</p>',
                                        unsafe_allow_html=True)
                        elif is_user_selected and not is_correct_key:
                            st.markdown(f'{k}: {options[k]}')
                        elif not is_user_selected and is_correct_key:
                            st.markdown(f'<p style="color:#1b5e20;font-weight:bold;">✅ {k}: {options[k]}</p>',
                                        unsafe_allow_html=True)
                        else:
                            st.markdown(f'{k}: {options[k]}')

                # 你的答案（含选项内容）
                if user_ans:
                    user_display = get_answer_display(d["type"], user_ans, options)
                    st.error(f"**你的答案**：{user_display}")
                else:
                    st.error("**你的答案**：未作答")

                # 正确答案（含选项内容）
                correct_display = get_answer_display(d["type"], correct_ans, options)
                st.markdown(
                    f'<div style="background:#e8f5e9;border-left:4px solid #1b5e20;padding:8px 12px;'
                    f'border-radius:4px;margin:4px 0;">'
                    f'<span style="color:#1b5e20;font-weight:bold;">✅ 正确答案：{correct_display}</span></div>',
                    unsafe_allow_html=True,
                )

                # 解析（直接跟在正确答案后面）
                explanation = d.get("explanation", "")
                if explanation:
                    st.markdown(explanation)

                if cat_label:
                    st.markdown(f"**知识板块**：{cat_label}")

                q_stats = get_question_stats(d.get("id", ""))
                st.caption(f"📊 答题统计：答对 {q_stats['correct_count']} 次 / 答错 {q_stats['wrong_count']} 次")

    # 答题卡
    st.markdown("---")
    st.markdown("#### 📌 答题卡（🟢=正确 🔴=错误/漏答）")
    eq = st.session_state.mock_questions
    total_q = len(eq)
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
            q_item = eq[q_idx]
            d = details_by_idx.get(q_item["index"], {})
            is_correct = d.get("is_correct", False)
            bg = "#c8e6c9" if is_correct else "#ffcdd2"
            tc = "#1b5e20" if is_correct else "#b71c1c"
            
            # 标记题角标
            is_marked = q_item["id"] in st.session_state.mock_marked
            marker = '<sup style="font-size:8px;">⭐</sup>' if is_marked else ''
            border_style = "2px solid #ff9800" if is_marked else "1px solid #ddd"
            
            nav_html += f'''
            <div style="flex:1;min-width:0;">
                <div style="display:block;width:100%;background:{bg};color:{tc};border:{border_style};
                          border-radius:3px;font-size:12px;min-height:30px;line-height:30px;
                          text-align:center;position:relative;">
                    {q_idx + 1}{marker}
                </div>
            </div>'''
        nav_html += '</div>'
    nav_html += '</div>'
    st.markdown(nav_html, unsafe_allow_html=True)

    # 下一科 / 返回
    st.markdown("---")
    if subject_key == "psychology":
        col1, col2, col3 = st.columns([1, 2, 1])
        if col2.button("📗 进入咨询实务", key="mock_go_counseling", use_container_width=True, type="primary"):
            _start_subject("counseling")
    else:
        col1, col2, col3 = st.columns(3)
        if col2.button("🏠 查看总成绩", key="mock_view_final", use_container_width=True, type="primary"):
            _aggregate_final_result()
        if col3.button("🔄 重新考试", key="mock_retry_exam", use_container_width=True):
            _reset_mock_exam()


def _aggregate_final_result():
    """汇总两科成绩"""
    # 当前科为咨询实务（已考完），前一科为心理学综合
    current_result = st.session_state.mock_result       # 咨询实务成绩
    prev_result = st.session_state.get("mock_prev_result")  # 心理学综合成绩

    st.session_state.mock_final_results = {
        "psychology": prev_result,
        "counseling": current_result,
    }
    st.session_state.mock_state = "all_finished"
    st.rerun()


def _show_final_result():
    """显示总成绩"""
    results = st.session_state.mock_final_results

    st.markdown("# 🏆 模拟考试 - 总成绩")
    st.markdown("---")

    total_score = 0
    total_max = 0
    total_correct = 0
    total_questions = 0

    cols = st.columns(2)
    for i, (key, cfg_key) in enumerate([("psychology", "psychology"), ("counseling", "counseling")]):
        res = results.get(key)
        cfg = MOCK_EXAM_CONFIG[cfg_key]
        if res:
            total_score += res.get("score", 0)
            total_max += res.get("max_score", 0)
            total_correct += res.get("correct", 0)
            total_questions += res.get("total", 0)

            with cols[i]:
                accuracy = res["correct"] / res["total"] * 100 if res["total"] > 0 else 0
                st.metric(
                    f"📘 {cfg['name']}",
                    f"{res['score']:.1f}/{res['max_score']:.1f}",
                    f"{accuracy:.1f}% 正确率"
                )
                st.markdown(f"正确: {res['correct']}/{res['total']} | 用时: {res.get('duration', '')}")

    st.markdown("---")
    overall_accuracy = total_correct / total_questions * 100 if total_questions > 0 else 0
    st.markdown(f"### 📊 总评")
    st.markdown(f"- **总分**: {total_score:.1f} / {total_max:.1f}")
    st.markdown(f"- **总正确**: {total_correct}/{total_questions} ({overall_accuracy:.1f}%)")
    st.progress(total_correct / max(total_questions, 1))

    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    if col1.button("🔄 重新考试", key="mock_final_retry", use_container_width=True):
        _reset_mock_exam()
    if col3.button("🏠 返回首页", key="mock_final_home", use_container_width=True, type="primary"):
        _reset_mock_exam()
        st.session_state.pop("nav_to", None)
        st.rerun()


def _reset_mock_exam():
    """重置模拟考试状态"""
    keys_to_clear = [
        "mock_state", "mock_subject", "mock_questions", "mock_current",
        "mock_answers", "mock_start_time", "mock_end_time",
        "mock_confirm_submit", "mock_session_id", "mock_type_boundaries",
        "mock_result", "mock_prev_result", "mock_final_results",
    ]
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    # 清除所有答案展开状态
    for k in [key for key in st.session_state if key.startswith("mock_show_ans_")]:
        del st.session_state[k]
    st.rerun()

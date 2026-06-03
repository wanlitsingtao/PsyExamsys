"""
综合训练系统 - 与考试系统统一界面，全部答完后一并提交
比考试系统多一个「查看答案」功能，无时间限制
"""
import streamlit as st
import time
import uuid
from datetime import datetime
from utils.data_manager import (
    extract_questions, check_answer, get_answer_display,
    add_wrong_record, add_correct_record, add_answer_record,
    save_exam_record, load_config, load_exam_records,
    update_study_record, save_study_record, find_study_record,
    infer_category, get_question_stats,
)


def show_exam():
    st.markdown("# 📝 综合训练")
    st.markdown("---")

    questions = st.session_state.questions
    if not questions:
        st.warning("⚠️ 题库为空，请先在配置管理中导入题库！")
        return

    config = load_config()

    # 初始化训练状态
    if "exam_state" not in st.session_state:
        # 检查是否有未完成的训练记录
        records = load_exam_records()
        unfinished = [r for r in records if r.get("status") == "in_progress" and r.get("mode") == "practice"]
        if unfinished:
            latest = sorted(unfinished, key=lambda r: r.get("updated_at", ""), reverse=True)[0]
            st.session_state.exam_state = "idle"
            st.session_state._exam_resume_data = latest
        else:
            st.session_state.exam_state = "idle"

    # ======== 空闲状态 - 显示开始页面 ========
    if st.session_state.exam_state == "idle":
        _show_exam_start(config)
        return

    # ======== 运行中状态 ========
    if st.session_state.exam_state == "running":
        _show_exam_running(config)
        return

    # ======== 完成状态 - 显示成绩 ========
    if st.session_state.exam_state == "finished":
        _show_exam_result()
        return


def _show_exam_start(config):
    """显示训练开始界面"""
    st.markdown("### 📖 准备开始综合训练")
    st.markdown("---")

    # 检查是否有未完成的训练
    resume_data = st.session_state.pop("_exam_resume_data", None)
    if resume_data:
        st.info(f"📂 检测到上次未完成的训练（{resume_data.get('created_at','')[:16]}），是否继续？")
        col_r1, col_r2 = st.columns(2)
        if col_r1.button("✅ 继续上次训练", use_container_width=True, type="primary"):
            _resume_exam(resume_data)
            return
        if col_r2.button("🔄 重新开始", use_container_width=True):
            update_study_record(resume_data["session_id"], {"status": "abandoned"})
            st.rerun()
        st.markdown("---")

    st.markdown("**训练规则：**")
    study_single = config.get("study_single_count", 40)
    study_multi = config.get("study_multi_count", 30)
    study_judge = config.get("study_judge_count", 30)
    total_q = study_single + study_multi + study_judge
    st.markdown(f"- 共 **{total_q}** 题")
    st.markdown(f"  - 单选题 {study_single} 题")
    st.markdown(f"  - 多选题 {study_multi} 题")
    st.markdown(f"  - 判断题 {study_judge} 题")
    st.markdown(f"  - ⚠️ 出题顺序：**单选题 → 多选题 → 判断题**")
    st.markdown(f"- 全部作答后统一提交")
    st.markdown(f"- 提交后可查看每题的正确答案和解析")
    st.markdown(f"- 多选题需完全选对才得分（漏选/多选均不得分）")
    st.markdown(f"- 未答题目视为错误")
    st.markdown(f"- 中途退出自动保存进度，可继续训练")
    st.markdown("---")

    col1, col2, col3 = st.columns([1, 2, 1])
    if col2.button("🚀 开始训练", use_container_width=True, type="primary"):
        _start_new_exam(config)


def _start_new_exam(config):
    """开始新训练"""
    session_id = str(uuid.uuid4())[:8]

    selected = extract_questions(
        st.session_state.questions,
        dan_count=config.get("study_single_count", 40),
        duo_count=config.get("study_multi_count", 30),
        pan_count=config.get("study_judge_count", 30),
        shuffle_types=False,  # 固定顺序：单选→多选→判断
    )

    single_end = sum(1 for q in selected if q["type"] == "single")
    multi_end = single_end + sum(1 for q in selected if q["type"] == "multi")

    st.session_state.exam_questions = selected
    st.session_state.exam_current = 0
    st.session_state.exam_answers = {}
    st.session_state.exam_marked = set()
    st.session_state.exam_state = "running"
    st.session_state.exam_session_id = session_id
    st.session_state.exam_type_boundaries = {
        "single_end": single_end,
        "multi_end": multi_end,
    }
    st.session_state.exam_confirm_submit = False

    # 创建持久化训练记录（初始状态）
    save_study_record({
        "session_id": session_id,
        "mode": "practice",
        "total": len(selected),
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "status": "in_progress",
        "answers": {},
        "config": {
            "study_single_count": config.get("study_single_count", 40),
            "study_multi_count": config.get("study_multi_count", 30),
            "study_judge_count": config.get("study_judge_count", 30),
        },
    })
    st.rerun()


def _resume_exam(record):
    """恢复上次未完成的训练"""
    config = st.session_state.config

    # 重新抽取题目（使用保存的配置）
    selected = extract_questions(
        st.session_state.questions,
        dan_count=record.get("config", {}).get("study_single_count", config.get("study_single_count", 40)),
        duo_count=record.get("config", {}).get("study_multi_count", config.get("study_multi_count", 30)),
        pan_count=record.get("config", {}).get("study_judge_count", config.get("study_judge_count", 30)),
        shuffle_types=False,
    )

    single_end = sum(1 for q in selected if q["type"] == "single")
    multi_end = single_end + sum(1 for q in selected if q["type"] == "multi")

    st.session_state.exam_questions = selected
    st.session_state.exam_current = record.get("current_index", 0)
    st.session_state.exam_answers = record.get("answers", {})
    st.session_state.exam_marked = set(record.get("marked", []))
    st.session_state.exam_state = "running"
    st.session_state.exam_session_id = record["session_id"]
    st.session_state.exam_type_boundaries = {
        "single_end": single_end,
        "multi_end": multi_end,
    }
    st.session_state.exam_confirm_submit = False
    st.rerun()


def _show_exam_running(config):
    """显示考试进行中的界面"""
    eq = st.session_state.exam_questions
    total_q = len(eq)
    idx = st.session_state.exam_current
    q = eq[idx]
    qid = q["id"]
    boundaries = st.session_state.exam_type_boundaries

    # ---- 倒计时 ----
    now = time.time()
    remaining = st.session_state.exam_end_time - now

    if remaining <= 0:
        _finish_exam()
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
    answered = len(st.session_state.exam_answers)
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

    submit_check = meta_cols[4].button("📤 提交试卷", use_container_width=True, type="primary")
    if submit_check:
        st.session_state.exam_confirm_submit = True

    if st.session_state.get("exam_confirm_submit"):
        st.warning(f"⚠️ 还有 {unanswered} 题未答，确认提交吗？未答题将计为错误。")
        col_c1, col_c2 = st.columns(2)
        if col_c1.button("✅ 确认提交", use_container_width=True):
            _finish_exam()
            return
        if col_c2.button("❌ 继续答题", use_container_width=True):
            st.session_state.exam_confirm_submit = False
            st.rerun()

    st.markdown("---")

    # ---- 题目显示 ----
    type_labels = {"single": "🔵 单选题", "multi": "🟢 多选题", "judge": "🟠 判断题"}
    
    st.markdown(f"### 第 {idx+1}/{total_q} 题")
    
    category = q.get('category', infer_category(q.get('source_file', '')))
    
    title_col1, title_col2 = st.columns([8, 2])
    with title_col1:
        st.markdown(f"**{type_labels[q['type']]}**"
                    f"{' · 📂 ' + category if category else ''}")
    with title_col2:
        marked = qid in st.session_state.exam_marked
        if st.button("⭐ 标记" if marked else "☆ 标记",
                     key=f"exam_mark_{qid}",
                     help="取消标记" if marked else "标记此题",
                     use_container_width=True):
            if qid in st.session_state.exam_marked:
                st.session_state.exam_marked.discard(qid)
            else:
                st.session_state.exam_marked.add(qid)
            _sync_exam_to_db()
            st.rerun()
    
    st.markdown(f"**{q['question']}**")

    options = q["options"]
    opt_keys = sorted(options.keys())

    user_ans = st.session_state.exam_answers.get(qid, "")

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
            key=f"exam_radio_{qid}",
            index=idx_in_list,
            label_visibility="collapsed",
        )
        if selected_opt:
            selected_key = selected_opt.split(":")[0]
            if st.session_state.exam_answers.get(qid) != selected_key:
                st.session_state.exam_answers[qid] = selected_key
                _sync_exam_to_db()
    elif q["type"] == "multi":
        cols = st.columns(2)
        selected_keys = []
        for i, k in enumerate(opt_keys):
            col = cols[i % 2]
            checked = col.checkbox(
                f"{k}: {options[k]}",
                key=f"exam_cb_{qid}_{k}",
                value=(k in user_ans),
            )
            if checked:
                selected_keys.append(k)

        if selected_keys:
            ans_str = "".join(sorted(selected_keys))
            if st.session_state.exam_answers.get(qid) != ans_str:
                st.session_state.exam_answers[qid] = ans_str
                _sync_exam_to_db()
            st.caption(f"已选: {', '.join(selected_keys)}")
        else:
            st.caption("请选择至少一个选项")

    st.markdown("---")

    # 导航按钮
    nav_cols = st.columns([1, 2, 1])
    if nav_cols[0].button("◀ 上一题", use_container_width=True, disabled=(idx == 0)):
        st.session_state.exam_current = idx - 1
        st.rerun()

    if nav_cols[2].button("下一题 ▶", use_container_width=True, disabled=(idx >= total_q - 1)):
        st.session_state.exam_current = idx + 1
        st.rerun()

    # ---- 答题卡 ----
    st.markdown("---")
    st.markdown("#### 📌 答题卡")

    # 筛选按钮
    filter_key = "exam_card_filter"
    if filter_key not in st.session_state:
        st.session_state[filter_key] = "all"

    fc1, fc2, fc3, fc4 = st.columns(4)
    if fc1.button("📋 全部", key="exam_filter_all", use_container_width=True,
                  type="primary" if st.session_state[filter_key] == "all" else "secondary"):
        st.session_state[filter_key] = "all"
        st.rerun()
    if fc2.button("✅ 已答", key="exam_filter_answered", use_container_width=True,
                  type="primary" if st.session_state[filter_key] == "answered" else "secondary"):
        st.session_state[filter_key] = "answered"
        st.rerun()
    if fc3.button("⬜ 未答", key="exam_filter_unanswered", use_container_width=True,
                  type="primary" if st.session_state[filter_key] == "unanswered" else "secondary"):
        st.session_state[filter_key] = "unanswered"
        st.rerun()
    if fc4.button("⭐ 已标记", key="exam_filter_marked", use_container_width=True,
                  type="primary" if st.session_state[filter_key] == "marked" else "secondary"):
        st.session_state[filter_key] = "marked"
        st.rerun()

    filter_mode = st.session_state[filter_key]
    marked_count = len(st.session_state.exam_marked)
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
                if filter_mode == "answered" and q_id not in st.session_state.exam_answers:
                    show = False
                if filter_mode == "unanswered" and q_id in st.session_state.exam_answers:
                    show = False
                if filter_mode == "marked" and q_id not in st.session_state.exam_marked:
                    show = False

                if not show:
                    st.empty()
                    continue

                is_answered = q_id in st.session_state.exam_answers
                is_marked = q_id in st.session_state.exam_marked
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

                if st.button(label, key=f"exam_nav_{q_idx}", use_container_width=True, type=btn_type):
                    st.session_state.exam_current = q_idx
                    st.rerun()

                if is_current:
                    st.markdown('</div>', unsafe_allow_html=True)


def _sync_exam_to_db(status=None):
    """将当前考试状态同步到持久化JSON"""
    session_id = st.session_state.get("exam_session_id", "")
    if not session_id:
        return

    update_data = {
        "updated_at": datetime.now().isoformat(),
        "answers": st.session_state.get("exam_answers", {}),
        "current_index": st.session_state.get("exam_current", 0),
        "marked": list(st.session_state.get("exam_marked", set())),
    }
    if status:
        update_data["status"] = status
    update_study_record(session_id, update_data)


def _finish_exam():
    """结束考试，计算成绩"""
    eq = st.session_state.exam_questions
    total_q = len(eq)
    answers = st.session_state.exam_answers
    start_time = st.session_state.exam_start_time
    duration = time.time() - start_time

    # 计分
    correct_count = 0
    total_score = 0.0
    details = []

    for q in eq:
        qid = q["id"]
        user_ans = answers.get(qid, "")
        is_correct = check_answer(q["type"], user_ans, q["answer"])
        score = 0
        if is_correct:
            if q["type"] == "single":
                score = 1.0
            elif q["type"] == "multi":
                score = 1.5
            else:
                score = 0.5
            correct_count += 1
            total_score += score
            # 答对：从错题库移除（以最后一次为准）
            add_correct_record(qid)
        else:
            add_wrong_record(qid, user_ans)

        # 记录答题过程（无论对错）
        add_answer_record(
            question_id=qid,
            user_answer=user_ans,
            is_correct=is_correct,
            mode="exam",
            session_id=st.session_state.get("exam_session_id", ""),
        )

        details.append({
            "index": q["index"],
            "type": q["type"],
            "question": q["question"],
            "user_answer": user_ans,
            "correct_answer": q["answer"],
            "is_correct": is_correct,
            "score": score,
            "category": q.get("category", infer_category(q.get("source_file", ""))),
        })

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

    # 保存考试记录
    record = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": total_q,
        "correct": correct_count,
        "score": round(total_score, 1),
        "duration": duration_str,
        "accuracy": f"{correct_count/total_q*100:.1f}%",
        "status": "completed",
        "session_id": st.session_state.get("exam_session_id", ""),
        "category_stats": cat_stats,
    }
    save_exam_record(record)

    # 更新考试会话记录
    session_id = st.session_state.get("exam_session_id", "")
    if session_id:
        update_study_record(session_id, {
            "status": "completed",
            "updated_at": datetime.now().isoformat(),
            "score": round(total_score, 1),
            "correct": correct_count,
        })

    # 保存结果到 session
    st.session_state.exam_result = {
        "total": total_q,
        "correct": correct_count,
        "score": round(total_score, 1),
        "max_score": total_q * 0.5 + 30 * 1.0,
        "duration": duration_str,
        "details": details,
        "category_stats": cat_stats,
    }
    st.session_state.exam_state = "finished"
    st.rerun()


def _show_exam_result():
    """显示考试成绩"""
    result = st.session_state.exam_result
    total = result["total"]
    correct = result["correct"]
    score = result["score"]
    duration = result["duration"]
    details = result["details"]
    cat_stats = result.get("category_stats", {})

    st.markdown("# 📊 考试成绩报告")
    st.markdown("---")

    accuracy = correct / total * 100

    cols = st.columns(4)
    cols[0].metric("✅ 正确", f"{correct}/{total}", f"{accuracy:.1f}%")
    cols[1].metric("📊 得分", f"{score:.1f}分")
    cols[2].metric("⏱️ 用时", duration)
    cols[3].metric("📈 综合准确率", f"{accuracy:.1f}%")

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

    type_names = {"single": "单选题", "multi": "多选题", "judge": "判断题"}

    for tp, stats in type_stats.items():
        pct = stats["correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
        st.markdown(f"**{type_names[tp]}**: {stats['correct']}/{stats['total']} 正确 ({pct:.1f}%)")
        st.progress(stats["correct"] / max(stats["total"], 1))

    # 知识板块统计
    if cat_stats:
        st.markdown("---")
        st.markdown("### 📂 知识板块分析")
        for cat, stats in sorted(cat_stats.items()):
            pct = stats["correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
            st.markdown(f"**{cat}**: {stats['correct']}/{stats['total']} 正确 ({pct:.1f}%)")
            st.progress(stats["correct"] / max(stats["total"], 1))

    # 错题列表
    st.markdown("---")
    wrong_details = [d for d in details if not d["is_correct"]]
    if wrong_details:
        st.markdown(f"### ❌ 错题回顾 ({len(wrong_details)}题)")
        for i, d in enumerate(wrong_details[:10]):
            tp_label = {"single": "单选", "multi": "多选", "judge": "判断"}[d["type"]]
            user_label = d.get("user_answer", "未答")
            cat_label = d.get("category", "")
            with st.expander(f"{i+1}. [{tp_label}] {d['question'][:60]}..."):
                st.markdown(f"**题目**: {d['question']}")
                st.markdown(f'<p style="color:red;font-weight:bold;">你的答案: {user_label}</p>', unsafe_allow_html=True)
                st.markdown(
                    f'<div style="background:#e8f5e9;border-left:4px solid #1b5e20;padding:8px 12px;'
                    f'border-radius:4px;margin:4px 0;">'
                    f'<span style="color:#1b5e20;font-weight:bold;">✅ 正确答案：{d["correct_answer"]}</span></div>',
                    unsafe_allow_html=True,
                )
                if cat_label:
                    st.markdown(f"**知识板块**: {cat_label}")

        if len(wrong_details) > 10:
            st.markdown(f"... 还有 {len(wrong_details) - 10} 题错题")

    # 提交后的答题卡：显示每道题的对错颜色
    st.markdown("---")
    st.markdown("#### 📌 答题卡（🟢=正确 🔴=错误/漏答）")
    eq = st.session_state.exam_questions
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
            
            is_marked = q_item["id"] in st.session_state.get("exam_marked", set())
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

    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    if col2.button("🏠 返回首页", use_container_width=True, type="primary"):
        st.session_state.exam_state = "idle"
        for key in ["exam_questions", "exam_answers", "exam_result"]:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

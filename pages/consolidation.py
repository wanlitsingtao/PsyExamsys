"""
巩固练习 - 掌握不牢靠 + 遗忘预警题目
独立模块，与错题本并列
"""
import streamlit as st
import uuid
import time
from datetime import datetime

from utils.data_manager import (
    check_answer, get_answer_display,
    batch_update_wrong_and_stats, batch_add_answer_records,
    load_questions, load_question_stats, infer_category,
    get_mastery_distribution, save_draft, load_drafts, delete_draft,
)


def _get_cached_qstats(qid):
    """从 session_state 缓存获取题目统计，带默认值"""
    cache = st.session_state.get("consol_stats_cache", {})
    return cache.get(qid, {"correct_count": 0, "wrong_count": 0, "last_answer_time": None, "last_correct": None})


def show_consolidation():
    """巩固练习入口 — 三态状态机：idle / running / submitted"""
    # 初始化状态
    if "consol_state" not in st.session_state:
        st.session_state.consol_state = "idle"
    if "consol_submitted" not in st.session_state:
        st.session_state.consol_submitted = False
    if "consol_questions" not in st.session_state:
        st.session_state.consol_questions = []
    if "consol_confirm_submit" not in st.session_state:
        st.session_state.consol_confirm_submit = False

    # 路由
    if st.session_state.consol_state == "idle":
        _show_consol_start()
    elif st.session_state.consol_submitted:
        _show_consolidation_result()
    else:
        _show_consolidation_running()


# ============================
#  题目生成 + Start 页面
# ============================

def _generate_consol_questions():
    """加载并筛选需要巩固的题目，写入 session_state"""
    questions = load_questions()
    q_map = {q["id"]: q for q in questions}
    mastery = get_mastery_distribution(questions, st.session_state.get("exam_type"))
    retention_list = mastery.get("retention_list", [])
    unstable_list = mastery.get("unstable_list", [])

    # 去重合并：消退型优先 → 遗忘预警（上次答对）→ 波动型
    seen = set()
    combined = []
    # 1. 消退型（答对过又答错，最需关注）
    for item in unstable_list:
        if item.get("unstable_type") != "消退型":
            continue
        qid = item["question_id"]
        if qid not in seen:
            seen.add(qid)
            combined.append(item)
    # 2. 遗忘预警（上次答对，复习到期）
    for item in retention_list:
        qid = item["question_id"]
        if qid not in seen:
            seen.add(qid)
            combined.append(item)
    # 3. 波动型（对错交替，掌握不稳定，放到上次答对之后）
    for item in unstable_list:
        if item.get("unstable_type") != "波动型":
            continue
        qid = item["question_id"]
        if qid not in seen:
            seen.add(qid)
            combined.append(item)

    # 取最多 60 题
    count = min(len(combined), 60)
    selected = []
    tags = {}
    for item in combined[:count]:
        q = q_map.get(item["question_id"])
        if q:
            tag = item.get("unstable_type") or "遗忘预警"
            q_copy = dict(q)
            q_copy["_tag"] = tag
            selected.append(q_copy)
            tags[item["question_id"]] = tag

    st.session_state.consol_questions = selected
    st.session_state.consol_tags = tags
    st.session_state.consol_current = 0
    st.session_state.consol_answers = {}
    st.session_state.consol_marked = set()
    st.session_state.consol_uncertain = set()
    st.session_state.consol_submitted = False
    st.session_state.consol_results = {}
    st.session_state.consol_confirm_submit = False
    st.session_state.consol_state = "running"
    st.session_state.consol_last_auto_save = time.time()  # 自动保存计时起点
    if "consol_card_filter" in st.session_state:
        del st.session_state.consol_card_filter
    # 新练习清除旧草稿 ID
    if "consol_draft_id" in st.session_state:
        del st.session_state.consol_draft_id


def _show_consol_start():
    """巩固练习开始页面 — 开始练习 + 未完成草稿列表"""
    st.markdown("# 🎯 巩固练习")
    st.markdown("针对掌握不牢靠（消退型/波动型）和遗忘预警的题目进行专项巩固。")

    # ---- 开始练习 ----
    st.markdown("---")
    if st.button("🚀 开始巩固练习", use_container_width=True, type="primary", key="consol_start_new"):
        _generate_consol_questions()
        st.rerun()

    # ---- 未完成的练习 ----
    drafts = load_drafts("consol")
    if drafts:
        st.markdown("---")
        st.markdown("### 📂 未完成的巩固练习（点击继续作答）")
        for draft in drafts:
            d_id = draft.get("draft_id", "")
            d_answered = len(draft.get("answers", {}))
            d_total = len(draft.get("question_ids", []))
            d_saved = draft.get("saved_at", "")
            dcol1, dcol2, dcol3 = st.columns([5, 2, 1])
            dcol1.markdown(
                f"已答 **{d_answered}/{d_total}** 题　🕐 {d_saved}"
            )
            if dcol2.button("▶ 继续作答", key=f"consol_resume_{d_id}", use_container_width=True, type="primary"):
                _resume_consol_draft(draft)
            if dcol3.button("🗑", key=f"consol_del_draft_{d_id}", use_container_width=True, help="删除此草稿"):
                delete_draft("consol", d_id)
                st.rerun()


def _resume_consol_draft(draft: dict):
    """从草稿恢复巩固练习状态"""
    q_map = {q["id"]: q for q in load_questions()}
    restored_questions = [q_map[qid] for qid in draft.get("question_ids", []) if qid in q_map]
    if not restored_questions:
        st.error("❌ 草稿中的题目已不存在于题库中，无法恢复。")
        return

    st.session_state.consol_questions = restored_questions
    st.session_state.consol_answers = draft.get("answers", {})
    st.session_state.consol_marked = set(draft.get("marked", []))
    st.session_state.consol_uncertain = set(draft.get("uncertain", []))
    st.session_state.consol_current = draft.get("current_idx", 0)
    st.session_state.consol_submitted = False
    st.session_state.consol_confirm_submit = False
    st.session_state.consol_draft_id = draft.get("draft_id", "")
    st.session_state.consol_state = "running"
    st.session_state.consol_last_auto_save = time.time()  # 自动保存计时起点
    st.rerun()


# ============================
#  答题模式
# ============================

def _show_consolidation_running():
    """巩固练习答题模式（操作元素与其他答题页面一致）"""
    # ---- 自动保存：每 5 分钟静默保存 ----
    _now = time.time()
    if _now - st.session_state.get("consol_last_auto_save", _now) >= 300:
        _save_consol_draft(auto_save=True)
        st.session_state.consol_last_auto_save = _now

    cq = st.session_state.consol_questions
    total_q = len(cq)
    idx = st.session_state.consol_current
    q = cq[idx]
    qid = q["id"]
    tag = q.get("_tag", "")

    # 缓存答题统计（避免每题渲染时重复读盘）
    if "consol_stats_cache" not in st.session_state:
        st.session_state.consol_stats_cache = load_question_stats()

    answered = len(st.session_state.consol_answers)
    unanswered = total_q - answered

    # ---- 标题行 + 返回（保存按钮已移至导航行） ----
    title_col, back_col = st.columns([5, 1])
    with title_col:
        st.markdown("## 🎯 巩固练习")
    with back_col:
        if st.button("返回", key="consol_back_running", use_container_width=True):
            st.session_state.consol_state = "idle"
            st.rerun()
    # 保存成功提示
    if st.session_state.pop("consol_draft_saved", False):
        st.success("✅ 进度已保存，可在本页未完成练习中继续作答。", icon="💾")

    st.markdown("---")

    # ---- 题目区（个性化内容：含掌握状态标签） ----
    type_labels = {"single": "🔵 单选题", "multi": "🟢 多选题", "judge": "🟠 判断题", "案例题": "🟣 案例题", "indefinite": "🟡 不定项选择题"}
    type_str = type_labels.get(q["type"], q["type"])
    cat_str = q.get("category", infer_category(q.get("source_file", "")))

    # 题号行：左侧题号，右侧历史统计（含巩固类型标签）
    title_cols = st.columns([1, 2])
    with title_cols[0]:
        st.markdown(f"##### 第 {idx+1}/{total_q} 题")
    with title_cols[1]:
        q_stats = _get_cached_qstats(qid)
        stats_parts = []
        if q_stats["correct_count"] > 0 or q_stats["wrong_count"] > 0:
            stats_parts.append(f"📊 答对 {q_stats['correct_count']} 次 / 答错 {q_stats['wrong_count']} 次")
        last_correct = q_stats.get("last_correct")
        if last_correct is True:
            stats_parts.append("🟢 上次答对")
        elif last_correct is False:
            stats_parts.append("🔴 上次答错")
        if tag:
            tag_emoji = "⚠️" if tag in ("消退型", "波动型") else "⏰"
            stats_parts.append(f"{tag_emoji} {tag}")
        if stats_parts:
            st.markdown(f"<div style='text-align:right;padding-top:0.5em;color:#888;font-size:16px;'>{'&nbsp;&nbsp;|&nbsp;&nbsp;'.join(stats_parts)}</div>", unsafe_allow_html=True)

    # 题型标签 + 不确定按钮 + 标记按钮 同行
    title_col1, title_col2, title_col3 = st.columns([6, 2, 2])
    with title_col1:
        title_parts = [f"**{type_str}**"]
        if cat_str:
            title_parts.append(f"📂 {cat_str}")
        st.markdown(" · ".join(title_parts))
    # 答过 3 次以上才显示「不确定」开关
    total_answers = q_stats["correct_count"] + q_stats["wrong_count"]
    with title_col2:
        if total_answers >= 3:
            toggle_key = f"consol_uncertain_toggle_{qid}"
            if toggle_key not in st.session_state:
                st.session_state[toggle_key] = qid in st.session_state.consol_uncertain

            def _on_consol_uncertain_toggle():
                if st.session_state[toggle_key]:
                    st.session_state.consol_uncertain.add(qid)
                else:
                    st.session_state.consol_uncertain.discard(qid)

            st.toggle("不确定",
                      key=toggle_key,
                      value=qid in st.session_state.consol_uncertain,
                      help="标记此题为不确定",
                      on_change=_on_consol_uncertain_toggle)
    with title_col3:
        marked = qid in st.session_state.consol_marked
        if st.button("⭐ 标记" if marked else "☆ 标记",
                     key=f"consol_mark_{qid}",
                     help="取消标记" if marked else "标记此题",
                     use_container_width=True):
            if qid in st.session_state.consol_marked:
                st.session_state.consol_marked.discard(qid)
            else:
                st.session_state.consol_marked.add(qid)
            st.rerun()

    # 案例题子题：在题目上方展示案例背景
    case_bg = q.get("case_background", "")
    if case_bg:
        with st.expander("📋 **案例背景**", expanded=True):
            st.markdown(case_bg)

    st.markdown(f"**{q['question']}**")

    # 选项样式（与模拟考试/专项训练一致）
    st.markdown("""
    <style>
    div[data-testid="stRadio"] > div { gap: 0.75em; }
    div[data-testid="stRadio"] > div > label { padding: 0.3em 0; }
    div[data-testid="stCheckbox"] > label { padding: 0.3em 0; }
    /* 正文区按钮字号与不确定开关一致（答题卡区有 10px 覆盖） */
    div.stButton > button {
        font-size: 13px !important;
    }
    </style>
    """, unsafe_allow_html=True)

    options = q["options"]
    opt_keys = sorted(options.keys())
    user_ans = st.session_state.consol_answers.get(qid, "")

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
            key=f"consol_radio_{qid}",
            index=idx_in_list,
            label_visibility="collapsed",
        )
        if selected_opt:
            selected_key = selected_opt.split(":")[0]
            if st.session_state.consol_answers.get(qid) != selected_key:
                st.session_state.consol_answers[qid] = selected_key

    elif q["type"] in ("multi", "案例题", "indefinite"):
        cols = st.columns(2)
        selected_keys = []
        for i, k in enumerate(opt_keys):
            col = cols[i % 2]
            checked = col.checkbox(
                f"{k}: {options[k]}",
                key=f"consol_cb_{qid}_{k}",
                value=(k in user_ans),
            )
            if checked:
                selected_keys.append(k)

        if selected_keys:
            ans_str = "".join(sorted(selected_keys))
            if st.session_state.consol_answers.get(qid) != ans_str:
                st.session_state.consol_answers[qid] = ans_str
            st.caption(f"已选: {', '.join(selected_keys)}")
        else:
            st.caption("请选择至少一个选项")

    # 查看答案功能（切换式：展开/收起）
    st.markdown("---")
    show_answer_key = f"consol_show_ans_{qid}"
    showing = st.session_state.get(show_answer_key, False)
    btn_label = "🙈 收起答案" if showing else "📖 查看答案"
    btn_key = f"consol_toggle_ans_{qid}"

    # 使用 on_click 回调避免双重 rerun：状态在脚本体之前更新
    def _toggle_answer():
        st.session_state[show_answer_key] = not st.session_state.get(show_answer_key, False)

    st.button(btn_label, key=btn_key, use_container_width=False, on_click=_toggle_answer)
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

    st.markdown("---")

    # ---- 导航按钮（上一题、下一题、保存、提交按钮同行） ----
    nav_cols = st.columns([1, 1, 1, 1])
    if nav_cols[0].button("◀ 上一题", use_container_width=True, disabled=(idx == 0)):
        st.session_state.consol_current = idx - 1
        st.rerun()

    if nav_cols[1].button("下一题 ▶", use_container_width=True, disabled=(idx >= total_q - 1)):
        st.session_state.consol_current = idx + 1
        st.rerun()

    if nav_cols[2].button("💾 保存", use_container_width=True):
        _save_consol_draft()

    if nav_cols[3].button("📤 提交所有答案", use_container_width=True, type="primary"):
        st.session_state.consol_confirm_submit = True

    if st.session_state.get("consol_confirm_submit"):
        answered = len(st.session_state.consol_answers)
        unanswered = total_q - answered
        st.warning(f"⚠️ 还有 {unanswered} 题未答，确认提交吗？未答题将计为错误。")
        col_c1, col_c2 = st.columns(2)
        if col_c1.button("✅ 确认提交", use_container_width=True):
            _submit_consolidation()
            st.rerun()
        if col_c2.button("❌ 继续答题", use_container_width=True):
            st.session_state.consol_confirm_submit = False
            st.rerun()

    # ---- 答题卡 ----
    st.markdown("---")
    st.markdown("#### 📌 答题卡")

    filter_key = "consol_card_filter"
    if filter_key not in st.session_state:
        st.session_state[filter_key] = "all"

    fc1, fc2, fc3, fc4, fc5 = st.columns(5)
    if fc1.button("📋 全部", key="consol_filter_all", use_container_width=True,
                  type="primary" if st.session_state[filter_key] == "all" else "secondary"):
        st.session_state[filter_key] = "all"
        st.rerun()
    if fc2.button("✅ 已答", key="consol_filter_answered", use_container_width=True,
                  type="primary" if st.session_state[filter_key] == "answered" else "secondary"):
        st.session_state[filter_key] = "answered"
        st.rerun()
    if fc3.button("⬜ 未答", key="consol_filter_unanswered", use_container_width=True,
                  type="primary" if st.session_state[filter_key] == "unanswered" else "secondary"):
        st.session_state[filter_key] = "unanswered"
        st.rerun()
    if fc4.button("⭐ 已标记", key="consol_filter_marked", use_container_width=True,
                  type="primary" if st.session_state[filter_key] == "marked" else "secondary"):
        st.session_state[filter_key] = "marked"
        st.rerun()
    if fc5.button("不确定", key="consol_filter_uncertain", use_container_width=True,
                  type="primary" if st.session_state[filter_key] == "uncertain" else "secondary"):
        st.session_state[filter_key] = "uncertain"
        st.rerun()

    filter_mode = st.session_state[filter_key]
    answered = len(st.session_state.consol_answers)
    marked_count = len(st.session_state.consol_marked)
    uncertain_count = len(st.session_state.consol_uncertain)
    st.progress(answered / total_q, text=f"已答 {answered}/{total_q}"
        + (f" · 已标记 {marked_count}" if marked_count else "")
        + (f" · 不确定 {uncertain_count}" if uncertain_count else ""))

    # 答题卡导航格子（Streamlit 原生按钮，不会打开新标签页）
    st.markdown("""
    <style>
    div.stButton > button {
        font-size: 10px !important; white-space: nowrap !important;
        padding-left: 0px !important; padding-right: 0px !important;
        min-height: 22px !important;
    }
    </style>
    """, unsafe_allow_html=True)
    _cols = 10
    for _row in range((total_q + _cols - 1) // _cols):
        _rcols = st.columns(_cols)
        for _ci in range(_cols):
            _qi = _row * _cols + _ci
            with _rcols[_ci]:
                if _qi >= total_q:
                    st.markdown("&nbsp;", unsafe_allow_html=True)
                    continue
                _qit = cq[_qi]
                _qid = _qit["id"]

                _vis = True
                if filter_mode == "answered" and _qid not in st.session_state.consol_answers:
                    _vis = False
                if filter_mode == "unanswered" and _qid in st.session_state.consol_answers:
                    _vis = False
                if filter_mode == "marked" and _qid not in st.session_state.consol_marked:
                    _vis = False
                if filter_mode == "uncertain" and _qid not in st.session_state.consol_uncertain:
                    _vis = False
                if not _vis:
                    st.markdown("&nbsp;", unsafe_allow_html=True)
                    continue

                _answered = _qid in st.session_state.consol_answers
                _marked = _qid in st.session_state.consol_marked
                _uncertain = _qid in st.session_state.consol_uncertain
                _current = _qi == idx

                _label = str(_qi + 1)
                if _current:
                    _label = f"▶{_label}"

                _btype = "primary" if _answered else "secondary"
                # 标记/不确定：固定高度角标行（所有按钮对齐）
                _badges = []
                if _marked:
                    _badges.append('<span style="font-size:8px;color:#ff9800;">⭐</span>')
                if _uncertain:
                    _badges.append('<span style="font-size:8px;color:#ff9800;">?</span>')
                st.markdown(
                    f'<div style="text-align:right;height:11px;line-height:11px;overflow:hidden;">{"".join(_badges)}</div>',
                    unsafe_allow_html=True,
                )
                if st.button(_label, key=f"consol_card_{_qi}",
                             use_container_width=True, type=_btype):
                    st.session_state.consol_current = _qi
                    st.rerun()


def _save_consol_draft(auto_save: bool = False):
    """保存巩固练习进度到草稿（复用已有 draft_id 做覆盖保存）
    
    auto_save=True: 后台静默保存，不显示提示
    """
    draft_id = st.session_state.get("consol_draft_id", str(uuid.uuid4()))
    draft_data = {
        "question_ids": [q["id"] for q in st.session_state.consol_questions],
        "answers": dict(st.session_state.consol_answers),
        "marked": list(st.session_state.consol_marked),
        "uncertain": list(st.session_state.consol_uncertain),
        "current_idx": st.session_state.consol_current,
    }
    save_draft("consol", draft_id, draft_data)
    st.session_state.consol_draft_id = draft_id
    if not auto_save:
        st.session_state.consol_draft_saved = True


def _submit_consolidation():
    """统一提交巩固练习答案（批量 I/O 优化）"""
    cq = st.session_state.consol_questions
    answers = st.session_state.consol_answers
    uncertain_set = st.session_state.consol_uncertain
    session_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    # 1. 先纯计算所有结果（无 I/O）
    results = {}
    wrong_qids = []     # (qid, user_answer)
    correct_qids = []   # qid
    stats_updates = []  # (qid, is_correct)
    uncertain_map = {}  # {qid: bool}
    answer_records = [] # 批量答题记录

    for q in cq:
        qid = q["id"]
        user_ans = answers.get(qid, "")

        # 防御性校验：单选/判断题的 answer 应为单个字母
        effective_answer = q["answer"]
        if q["type"] in ("single", "judge") and len(effective_answer) != 1:
            from utils.data_access import get_data_access
            fresh = get_data_access().load_question_by_id(qid)
            if fresh and len(fresh.get("answer", "")) == 1:
                effective_answer = fresh["answer"]

        is_correct = check_answer(q["type"], user_ans, effective_answer)
        is_uncertain = qid in uncertain_set

        results[qid] = {"correct": is_correct}

        if is_correct:
            correct_qids.append(qid)
        else:
            wrong_qids.append((qid, user_ans))
        stats_updates.append((qid, is_correct))
        if is_uncertain:
            uncertain_map[qid] = True

        answer_records.append({
            "question_id": qid,
            "user_answer": user_ans,
            "is_correct": is_correct,
            "mode": "consolidation",
            "session_id": session_id,
            "is_uncertain": is_uncertain,
            "timestamp": now,
        })

    # 2. 批量 I/O：统计 + 错题本 + 考试记录（单个事务）
    correct_count = sum(1 for v in results.values() if v.get("correct"))
    exam_record = {
        "type": "consolidation",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": len(cq),
        "correct": correct_count,
        "accuracy": f"{correct_count/len(cq)*100:.1f}%" if len(cq) > 0 else "0%",
    }
    batch_update_wrong_and_stats(
        wrong_qids, correct_qids, stats_updates,
        uncertain_map, exam_record=exam_record,
    )

    # 3. 批量 I/O：答题过程记录（单个连接）
    batch_add_answer_records(answer_records)

    # 标记数据已变更，触发首页统计缓存刷新
    st.session_state._data_version = st.session_state.get("_data_version", 0) + 1
    # 清除巩固练习自身的统计缓存
    st.session_state.pop("consol_stats_cache", None)

    st.session_state.consol_results = results
    st.session_state.consol_submitted = True

    # 提交成功后删除对应草稿
    draft_id = st.session_state.pop("consol_draft_id", None)
    if draft_id:
        delete_draft("consol", draft_id)


# ============================
#  结果展示
# ============================

def _show_consolidation_result():
    """提交后：展示结果 + 逐题回顾 + 答题卡"""
    # 守卫初始化：防止页面刷新后 session state 丢失
    if "consol_marked" not in st.session_state:
        st.session_state.consol_marked = set()
    if "consol_uncertain" not in st.session_state:
        st.session_state.consol_uncertain = set()

    st.markdown("# 🎯 巩固练习 - 成绩报告")

    cq = st.session_state.consol_questions
    total_q = len(cq)
    results = st.session_state.consol_results
    correct_count = sum(1 for v in results.values() if v.get("correct"))
    pct = correct_count / total_q * 100 if total_q else 0

    st.markdown("---")

    cols = st.columns(4)
    cols[0].metric("✅ 正确", f"{correct_count}/{total_q}", f"{pct:.1f}%")
    cols[1].metric("❌ 错误", f"{total_q - correct_count}/{total_q}")
    cols[2].metric("⭐ 已标记", f"{len(st.session_state.consol_marked)}")
    cols[3].metric("📈 正确率", f"{pct:.1f}%")

    # 完成提示
    if pct >= 80:
        st.success(f"🎉 **巩固练习完成！** 正确率: {pct:.1f}%")
    elif pct >= 60:
        st.info(f"📖 **巩固练习完成！** 正确率: {pct:.1f}%。继续加油！")
    else:
        st.warning(f"📚 **巩固练习完成！** 正确率: {pct:.1f}%。需要更多练习。")

    st.markdown("---")

    # ---- 答题卡 ----
    st.markdown("#### 📌 答题卡（🟢=正确 🔴=错误/漏答）")

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
            q_item = cq[q_idx]
            q_id = q_item["id"]
            is_correct = results.get(q_id, {}).get("correct", False)
            bg = "#c8e6c9" if is_correct else "#ffcdd2"
            tc = "#1b5e20" if is_correct else "#b71c1c"

            is_marked = q_id in st.session_state.consol_marked
            is_uncertain = q_id in st.session_state.consol_uncertain
            if is_uncertain:
                indicators = '<sup style="font-size:8px;color:#9c27b0;">❓</sup>'
                border_style = "1px solid #ddd"
            elif is_marked:
                indicators = '<sup style="font-size:8px;">⭐</sup>'
                border_style = "2px solid #ff9800"
            else:
                indicators = ''
                border_style = "1px solid #ddd"

            nav_html += f'''
            <div style="flex:1;min-width:0;">
                <div style="display:block;width:100%;background:{bg};color:{tc};border:{border_style};
                          border-radius:3px;font-size:12px;min-height:30px;line-height:30px;
                          text-align:center;position:relative;">
                    {q_idx + 1}{indicators}
                </div>
            </div>'''
        nav_html += "</div>"
    nav_html += "</div>"
    st.markdown(nav_html, unsafe_allow_html=True)

    # ---- 错题回顾（与模拟考试/专项训练格式一致） ----
    wrong_items = [(i, q) for i, q in enumerate(cq) if not results.get(q["id"], {}).get("correct")]
    if wrong_items:
        st.markdown("---")
        st.markdown(f"### ❌ 错题回顾 ({len(wrong_items)}题)")

        for i, (qi, q) in enumerate(wrong_items):
            qid = q["id"]
            tag = q.get("_tag", "")
            options = q["options"]
            cat_str = q.get("category", infer_category(q.get("source_file", "")))
            user_ans_str = st.session_state.consol_answers.get(qid, "")
            tp_label = {"single": "单选", "multi": "多选", "judge": "判断"}.get(q["type"], q["type"])

            expander_title = f"{i+1}. [{tp_label}] {q['question'][:60]}..."
            if tag:
                tag_emoji = "⚠️" if tag in ("消退型", "波动型") else "⏰"
                expander_title += f" {tag_emoji}{tag}"

            with st.expander(expander_title, expanded=True):
                # 案例背景
                case_bg = q.get("case_background", "")
                if case_bg:
                    st.markdown(f"**📋 案例背景**：{case_bg[:200]}{'...' if len(case_bg) > 200 else ''}")

                st.markdown(f"**题目**: {q['question']}")

                for k in sorted(options.keys()):
                    is_user_selected = k in user_ans_str
                    is_correct_key = k in q["answer"]

                    if q["type"] in ("multi", "案例题", "indefinite"):
                        if is_user_selected and is_correct_key:
                            st.markdown(f'<p style="color:#1b5e20;font-weight:bold;">✅ {k}: {options[k]}</p>',
                                        unsafe_allow_html=True)
                        elif is_user_selected and not is_correct_key:
                            st.markdown(f'<p style="color:#b71c1c;font-weight:bold;">❌ {k}: {options[k]} (错选)</p>',
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
                            st.markdown(f'<p style="color:#b71c1c;font-weight:bold;">❌ {k}: {options[k]} (错选)</p>',
                                        unsafe_allow_html=True)
                        elif not is_user_selected and is_correct_key:
                            st.markdown(f'<p style="color:#1b5e20;font-weight:bold;">✅ {k}: {options[k]}</p>',
                                        unsafe_allow_html=True)
                        else:
                            st.markdown(f'{k}: {options[k]}')

                # 用户答案（使用 st.error 统一样式）
                if user_ans_str:
                    user_display = get_answer_display(q["type"], user_ans_str, options)
                    st.error(f"**你的答案**：{user_display}")
                else:
                    st.error("**你的答案**：未作答")

                # 正确答案
                correct_display = get_answer_display(q["type"], q["answer"], options)
                st.markdown(
                    f'<div style="background:#e8f5e9;border-left:4px solid #1b5e20;padding:8px 12px;'
                    f'border-radius:4px;margin:4px 0;">'
                    f'<span style="color:#1b5e20;font-weight:bold;">✅ 正确答案：{correct_display}</span></div>',
                    unsafe_allow_html=True,
                )

                # 解析
                if q.get("explanation"):
                    st.markdown(q["explanation"])

                # 知识板块 + 答题统计
                if cat_str:
                    st.markdown(f"**知识板块**：{cat_str}")
                q_stats = _get_cached_qstats(qid)
                st.caption(f"📊 答题统计：答对 {q_stats['correct_count']} 次 / 答错 {q_stats['wrong_count']} 次")

    # ---- 操作按钮 ----
    st.markdown("---")
    c1, c2 = st.columns(2)
    if c1.button("🔄 重新练习", key="consol_retry", use_container_width=True, type="primary"):
        st.session_state.consol_state = "idle"
        st.rerun()
    if c2.button("返回", key="consol_back", use_container_width=True):
        st.session_state.consol_state = "idle"
        st.rerun()

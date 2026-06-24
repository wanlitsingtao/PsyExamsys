"""
模拟考试系统 - 实际考试模型（固定规则，不可配置）
两科独立计时、独立提交：
  1. 心理学综合（上午）：150单选×0.4 + 50多选×0.6 + 50判断×0.2 = 120分钟
  2. 咨询实务（下午）：140单选×0.4 + 60多选×0.6 + 10案例题（不定项）×0.8 = 120分钟
"""
import streamlit as st
import time
import uuid
from datetime import datetime
from utils.data_manager import (
    MOCK_EXAM_CONFIG, SUPER_CATEGORY_MAP, extract_questions, check_answer, get_answer_display,
    batch_update_wrong_and_stats, batch_add_answer_records,
    save_mock_exam_record, infer_category, load_question_stats,
    save_draft, load_drafts, delete_draft,
    load_case_studies, get_case_sub_questions,
)


def show_mock_exam():
    """模拟考试入口"""
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
        if cou.get("indefinite_count", 0) > 0:
            st.markdown(f"- 案例题 {cou['indefinite_count']} 题（每题 {cou['indefinite_score']} 分）")
        st.markdown(f"- 时间：{cou['time_minutes']} 分钟")
        st.markdown("---")
        if st.button("📗 开始咨询实务", use_container_width=True, type="primary", key="start_cou"):
            _start_subject("counseling")

    st.markdown("---")

    # ---- 历史草稿列表（如有） ----
    mock_drafts = load_drafts("mock")
    if mock_drafts:
        st.markdown("### 📂 未完成的考试（点击继续作答）")
        SUBJECT_LABELS = {"psychology": "心理学综合", "counseling": "咨询实务"}
        for draft in mock_drafts:
            d_id = draft.get("draft_id", "")
            d_sub = SUBJECT_LABELS.get(draft.get("subject_key", ""), draft.get("subject_key", ""))
            d_answered = len(draft.get("answers", {}))
            d_total = len(draft.get("question_ids", []))
            remaining_sec = draft.get("remaining_seconds", 0)
            remaining_str = f"{int(remaining_sec)//60:02d}:{int(remaining_sec)%60:02d}"
            d_saved = draft.get("saved_at", "")
            dcol1, dcol2, dcol3 = st.columns([5, 2, 1])
            dcol1.markdown(
                f"**{d_sub}**　已答 {d_answered}/{d_total} 题　"
                f"剩余时间 {remaining_str}　🕐 {d_saved}"
            )
            if dcol2.button("▶ 继续作答", key=f"mock_resume_{d_id}", use_container_width=True, type="primary"):
                _resume_mock_draft(draft)
            if dcol3.button("🗑", key=f"mock_del_draft_{d_id}", use_container_width=True, help="删除此草稿"):
                delete_draft("mock", d_id)
                st.rerun()
        st.markdown("---")

    st.markdown("### 📋 考试规则")
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
        st.markdown(f"  - 案例题 {cou['indefinite_count']} 题（每题 {cou['indefinite_score']} 分，围绕一个案例背景出题）")
    st.markdown(f"  - 出题顺序：**单选题 → 多选题 → 案例题**")
    st.markdown("")

    st.markdown("**规则说明：**")
    st.markdown("- 两科独立计时、独立提交")
    st.markdown("- 先考心理学综合，提交后方可进入咨询实务")
    st.markdown("- 多选题/案例题需**完全选对**才得分（漏选/多选均不得分）")
    st.markdown("- 案例题为咨询实务特有的不定项选择题，基于真实案例情境，部分题目只有一个正确答案，部分题目有多个正确答案")
    st.markdown("- 未答题目视为错误")
    st.markdown("- 答错自动计入错题本（以最后一次答题结果为准）")
    st.markdown("- 中途退出**不会**保存进度")


def _start_subject(subject_key):
    """开始某一科的考试"""
    # 如果切换到下一科，先把当前科的成绩保存到 prev
    if subject_key != st.session_state.get("mock_subject"):
        current_result = st.session_state.get("mock_result")
        if current_result is not None:
            st.session_state.mock_prev_result = current_result

    cfg = MOCK_EXAM_CONFIG[subject_key]
    session_id = str(uuid.uuid4())[:8]

    # 根据科目映射到超类过滤题目，再按优先级抽取（与专项训练完全一致）
    super_category_map = {"psychology": "心理学综合", "counseling": "咨询实务"}
    super_cat = super_category_map.get(subject_key, "")
    sub_categories = SUPER_CATEGORY_MAP.get(super_cat, [])
    filtered = [q for q in st.session_state.questions if q.get("category", "") in sub_categories]

    indefinite_count = cfg.get("indefinite_count", 0)
    # 案例题按案例单位抽取：
    # 每个案例包含背景文本 + 多道子题，子题按 index_num 排序
    case_backgrounds = {}  # {case_id: background_text} 用于 UI 展示
    case_subs_selected = []  # 被选中的案例子题列表
    if indefinite_count > 0 and subject_key == "counseling":
        cases = load_case_studies()
        if cases:
            # 按案例为单位随机选取，直到子题总数 >= indefinite_count
            import random
            random.shuffle(cases)
            selected_cases = []
            total_subs = 0
            for cs in cases:
                selected_cases.append(cs)
                total_subs += cs.get("question_count", 0)
                if total_subs >= indefinite_count:
                    break
            # 收集被选案例的全部子题（按 index_num 排序）
            for cs in selected_cases:
                subs = get_case_sub_questions(cs["id"])
                for sub in subs:
                    sub["case_study_id"] = cs["id"]
                    case_subs_selected.append(sub)
                # 缓存案例背景（用于 UI 子题页面上方展示）
                # 案例背景文本存储在 case_studies.title 中，优先使用
                bg_text = cs.get("title", "")
                if bg_text:
                    case_backgrounds[cs["id"]] = bg_text

    # 预加载统计，避免 extract_questions 内重复全量加载
    _stats = load_question_stats()
    selected = extract_questions(
        filtered,
        dan_count=cfg["single_count"],
        duo_count=cfg["multi_count"],
        pan_count=cfg["judge_count"],
        indefinite_count=0,  # 案例题过滤掉，下面单独追加
        shuffle_types=False,
        stats=_stats,
    )

    # 案例题子题追加到试卷末尾
    if case_subs_selected:
        selected.extend(case_subs_selected)

    # 计算各题型边界
    single_end = sum(1 for q in selected if q["type"] == "single")
    multi_end = single_end + sum(1 for q in selected if q["type"] == "multi")
    judge_end = multi_end + sum(1 for q in selected if q["type"] == "judge")

    st.session_state.mock_subject = subject_key
    st.session_state.mock_questions = selected
    st.session_state.mock_current = 0
    st.session_state.mock_answers = {}
    st.session_state.mock_marked = set()
    st.session_state.mock_uncertain = set()
    st.session_state.mock_start_time = time.time()
    st.session_state.mock_end_time = time.time() + cfg["time_minutes"] * 60
    st.session_state.mock_last_auto_save = time.time()  # 自动保存计时起点
    st.session_state.mock_confirm_submit = False
    st.session_state.mock_session_id = session_id
    st.session_state.mock_type_boundaries = {
        "single_end": single_end,
        "multi_end": multi_end,
        "judge_end": judge_end,
    }
    st.session_state.mock_case_backgrounds = case_backgrounds  # 案例背景缓存
    st.session_state.mock_state = subject_key
    st.session_state.pop("mock_draft_id", None)  # 新考试清除旧草稿ID
    st.session_state.pop("mock_paused_at", None)  # 清除暂停状态
    st.session_state.pop("mock_remaining_at_pause", None)
    st.rerun()


def _resume_mock_draft(draft: dict):
    """从草稿恢复模拟考试状态"""
    questions = st.session_state.questions
    q_map = {q["id"]: q for q in questions}
    restored_questions = [q_map[qid] for qid in draft.get("question_ids", []) if qid in q_map]
    if not restored_questions:
        st.error("❌ 草稿中的题目已不存在于题库中，无法恢复。")
        return

    subject_key = draft.get("subject_key", "psychology")
    remaining_seconds = draft.get("remaining_seconds", 0)

    # 重建案例背景缓存
    case_backgrounds = {}
    from utils.data_manager import load_case_studies, get_case_sub_questions
    all_cases = load_case_studies()
    case_ids_in_exam = set(q.get("case_study_id", "") for q in restored_questions if q.get("case_study_id"))
    for cs in all_cases:
        if cs["id"] in case_ids_in_exam:
            bg_text = cs.get("title", "")
            if bg_text:
                case_backgrounds[cs["id"]] = bg_text
    st.session_state.mock_case_backgrounds = case_backgrounds

    # 保存上一科成绩（如有）
    current_result = st.session_state.get("mock_result")
    if current_result is not None:
        st.session_state.mock_prev_result = current_result

    st.session_state.mock_subject = subject_key
    st.session_state.mock_questions = restored_questions
    st.session_state.mock_answers = draft.get("answers", {})
    st.session_state.mock_marked = set(draft.get("marked", []))
    st.session_state.mock_uncertain = set(draft.get("uncertain", []))
    st.session_state.mock_current = draft.get("current_idx", 0)
    st.session_state.mock_session_id = draft.get("session_id", "")
    st.session_state.mock_type_boundaries = draft.get("type_boundaries", {"single_end": 0, "multi_end": 0, "judge_end": 0})
    st.session_state.mock_start_time = time.time()
    # 恢复剩余时间：end_time = 当前时间 + 剩余秒数
    st.session_state.mock_end_time = time.time() + max(remaining_seconds, 60)
    st.session_state.mock_last_auto_save = time.time()  # 自动保存计时起点
    st.session_state.mock_confirm_submit = False
    st.session_state.mock_state = subject_key
    # 标记草稿ID，提交时删除
    st.session_state.mock_draft_id = draft.get("draft_id", "")
    st.rerun()


def _show_exam_subject(subject_key):
    """显示某一科的考试进行中界面"""
    # ---- 自动保存：每 5 分钟静默保存 ----
    _now = time.time()
    if _now - st.session_state.get("mock_last_auto_save", _now) >= 300:
        _save_mock_draft(subject_key, auto_save=True)
        st.session_state.mock_last_auto_save = _now

    cfg = MOCK_EXAM_CONFIG[subject_key]
    eq = st.session_state.mock_questions
    total_q = len(eq)
    idx = st.session_state.mock_current

    q = eq[idx]
    qid = q["id"]
    boundaries = st.session_state.mock_type_boundaries

    # 缓存答题统计（避免每次渲染读文件，与专项训练一致）
    if "mock_stats_cache" not in st.session_state:
        st.session_state.mock_stats_cache = load_question_stats()

    # 标题行 + 返回按钮（同行居右；保存按钮已移至导航行）
    cfg_name = cfg["name"]
    title_col, back_col = st.columns([5, 1])
    with title_col:
        st.markdown(f"#### 🎯 模拟考试 — {cfg_name}")
    with back_col:
        if st.button("返回", key="mock_back_to_start", use_container_width=True):
            st.session_state.mock_state = "idle"
            keys_to_clear = [
                "mock_subject", "mock_questions", "mock_current",
                "mock_answers", "mock_marked", "mock_start_time", "mock_end_time",
                "mock_confirm_submit", "mock_session_id", "mock_type_boundaries",
                "mock_result", "mock_prev_result", "mock_stats_cache",
                "mock_case_backgrounds",
            ]
            for key in keys_to_clear:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()
    # 保存成功提示（提前读取标志，供倒计时暂停/恢复判断）
    _post_save = st.session_state.pop("mock_draft_saved", False)
    if _post_save:
        st.success("✅ 进度已保存，倒计时已暂停。继续作答将自动恢复倒计时。", icon="💾")

    # 倒计时（时间耗尽后不强制提交，允许继续作答）
    # 暂停/恢复机制：保存后暂停，用户继续交互时自动恢复
    if st.session_state.get("mock_paused_at"):
        if _post_save:
            # 刚保存完的重渲染：保持暂停，显示冻结时间
            remaining = st.session_state.get("mock_remaining_at_pause", 0)
        else:
            # 用户做了其他操作（答题/翻题等）→ 恢复倒计时
            paused_elapsed = time.time() - st.session_state.pop("mock_paused_at")
            st.session_state.mock_end_time += paused_elapsed
            st.session_state.pop("mock_remaining_at_pause", None)
            remaining = st.session_state.mock_end_time - time.time()
    else:
        remaining = st.session_state.mock_end_time - time.time()

    if remaining > 0:
        mins = int(remaining // 60)
        secs = int(remaining % 60)
        time_str = f"{mins:02d}:{secs:02d}"

        if st.session_state.get("mock_paused_at"):
            st.warning(f"⏸️ **{time_str}** (倒计时已暂停)")
        elif remaining < 300:
            st.error(f"⏰ **{time_str}** (⚠️ 时间不足5分钟！)")
        elif remaining < 600:
            st.warning(f"⏰ **{time_str}**")
        else:
            st.info(f"⏰ 剩余时间: **{time_str}**")
    else:
        # 时间已耗尽，显示警告但允许继续作答
        exceeded = int(abs(remaining))
        if st.session_state.get("mock_paused_at"):
            st.warning(f"⏸️ **时间已到！** 倒计时已暂停。")
        else:
            st.error(f"⏰ **时间已到！** 已超时 {exceeded // 60}分{exceeded % 60}秒，但仍可继续作答。答完后请点击「📤 提交试卷」。")

    # 题型段标签
    se = boundaries["single_end"]
    me = boundaries["multi_end"]
    je = boundaries["judge_end"]
    type_labels_parts = [f"🔵 单选 {se}题"]
    if me - se > 0:
        type_labels_parts.append(f"🟢 多选 {me-se}题")
    if je - me > 0:
        type_labels_parts.append(f"🟠 判断 {je-me}题")
    case_count = total_q - je
    if case_count > 0:
        case_qids = [eq[i]["id"] for i in range(je, total_q)]
        case_study_ids = set(eq[i].get("case_study_id", "") for i in range(je, total_q))
        case_count_label = f"🟣 案例 {case_count}题 ({len(case_study_ids)}个案例)"
        type_labels_parts.append(case_count_label)
    st.markdown(" / ".join(type_labels_parts))

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
    type_labels = {"single": "🔵 单选题", "multi": "🟢 多选题", "judge": "🟠 判断题", "案例题": "🟣 案例题", "indefinite": "🟡 不定项选择题"}
    category = q.get('category', infer_category(q.get('source_file', '')))

    # 案例题子题：在题目上方展示案例背景
    case_study_id = q.get("case_study_id", "")
    if case_study_id:
        bg_text = st.session_state.get("mock_case_backgrounds", {}).get(case_study_id, "")
        if bg_text:
            with st.expander("📋 **案例背景**", expanded=True):
                st.markdown(
                    f"""<div style="background:#f3e5f5;padding:14px 16px;border-radius:8px;
                    border-left:5px solid #9c27b0;font-size:16px;line-height:1.8;">{bg_text}</div>""",
                    unsafe_allow_html=True,
                )

    # 获取本题答题统计（从缓存读取，与专项训练一致）
    q_stats = st.session_state.mock_stats_cache.get(qid, {"correct_count": 0, "wrong_count": 0, "last_answer_time": None, "last_correct": None})

    # 题号行：左侧题号，右侧历史统计（与专项训练布局一致）
    title_cols = st.columns([1, 2])
    with title_cols[0]:
        st.markdown(f"##### 第 {idx+1}/{total_q} 题")
    with title_cols[1]:
        stats_parts = []
        if q_stats["correct_count"] > 0 or q_stats["wrong_count"] > 0:
            stats_parts.append(f"📊 答对 {q_stats['correct_count']} 次 / 答错 {q_stats['wrong_count']} 次")
        last_correct = q_stats.get("last_correct")
        if last_correct is True:
            stats_parts.append("🟢 上次答对")
        elif last_correct is False:
            stats_parts.append("🔴 上次答错")
        # 掌握状态标签
        if q_stats.get("retention_due"):
            stats_parts.append("⏰ 遗忘预警")
        if q_stats.get("unstable"):
            history = q_stats.get("answer_history", [])
            if history and not history[-1]:
                stats_parts.append("⚠️ 消退型")
            else:
                stats_parts.append("⚠️ 波动型")
        if stats_parts:
            st.markdown(f"<div style='text-align:right;padding-top:0.5em;color:#888;font-size:16px;'>{'&nbsp;&nbsp;|&nbsp;&nbsp;'.join(stats_parts)}</div>", unsafe_allow_html=True)
    
    # 题型标签 + 不确定按钮 + 标记按钮 同行
    title_col1, title_col2, title_col3 = st.columns([6, 2, 2])
    # 答过 3 次以上才显示「不确定」开关
    total_answers = q_stats["correct_count"] + q_stats["wrong_count"]
    with title_col1:
        st.markdown(f"**{type_labels.get(q['type'], q['type'])}**"
                    f"{' · 📂 ' + category if category else ''}")
    with title_col2:
        if total_answers >= 3:
            toggle_key = f"mock_uncertain_toggle_{qid}"
            if toggle_key not in st.session_state:
                st.session_state[toggle_key] = qid in st.session_state.mock_uncertain

            def _on_mock_uncertain_toggle():
                if st.session_state[toggle_key]:
                    st.session_state.mock_uncertain.add(qid)
                else:
                    st.session_state.mock_uncertain.discard(qid)

            st.toggle("不确定",
                      key=toggle_key,
                      value=qid in st.session_state.mock_uncertain,
                      help="标记此题为不确定",
                      on_change=_on_mock_uncertain_toggle)
    with title_col3:
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

    # 选项行距：1.5倍
    st.markdown("""
    <style>
    div[data-testid="stRadio"] label,
    div[data-testid="stCheckbox"] label {
        line-height: 1.5;
    }
    /* 正文区按钮字号与不确定开关一致（答题卡区有 10px 覆盖） */
    div.stButton > button {
        font-size: 13px !important;
    }
    </style>
    """, unsafe_allow_html=True)

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
    elif q["type"] in ("multi", "案例题", "indefinite"):
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

    # 导航按钮（上一题、下一题、保存、提交按钮同行）
    nav_cols = st.columns([1, 1, 1, 1])
    if nav_cols[0].button("◀ 上一题", use_container_width=True, disabled=(idx == 0)):
        st.session_state.mock_current = idx - 1
        st.rerun()

    if nav_cols[1].button("下一题 ▶", use_container_width=True, disabled=(idx >= total_q - 1)):
        st.session_state.mock_current = idx + 1
        st.rerun()

    if nav_cols[2].button("💾 保存", use_container_width=True):
        _save_mock_draft(subject_key)

    if nav_cols[3].button("📤 提交试卷", use_container_width=True, type="primary"):
        st.session_state.mock_confirm_submit = True

    if st.session_state.get("mock_confirm_submit"):
        unanswered = total_q - len(st.session_state.mock_answers)
        st.warning(f"⚠️ 还有 {unanswered} 题未答，确认提交吗？（未答题不计为错题，但本题不得分）")
        col_c1, col_c2 = st.columns(2)
        if col_c1.button("✅ 确认提交", use_container_width=True):
            _finish_subject(subject_key)
            return
        if col_c2.button("❌ 继续答题", use_container_width=True):
            st.session_state.mock_confirm_submit = False
            st.rerun()

    # 答题卡
    st.markdown("---")
    st.markdown("#### 📌 答题卡")

    # 筛选按钮
    filter_key = "mock_card_filter"
    if filter_key not in st.session_state:
        st.session_state[filter_key] = "all"

    fc1, fc2, fc3, fc4, fc5 = st.columns(5)
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
    if fc5.button("不确定", key="mock_filter_uncertain", use_container_width=True,
                  type="primary" if st.session_state[filter_key] == "uncertain" else "secondary"):
        st.session_state[filter_key] = "uncertain"
        st.rerun()

    filter_mode = st.session_state[filter_key]
    answered = len(st.session_state.mock_answers)
    marked_count = len(st.session_state.mock_marked)
    uncertain_count = len(st.session_state.mock_uncertain)
    st.progress(answered / total_q, text=f"已答 {answered}/{total_q}"
        + (f" · 已标记 {marked_count}" if marked_count else "")
        + (f" · 不确定 {uncertain_count}" if uncertain_count else ""))

    # 答题卡导航格子（Streamlit 原生按钮，不会打开新标签页）
    st.markdown("""
    <style>
    /* 答题卡按钮小字号不换行 */
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
                _qit = eq[_qi]
                _qid = _qit["id"]

                # 筛选逻辑
                _vis = True
                if filter_mode == "answered" and _qid not in st.session_state.mock_answers:
                    _vis = False
                if filter_mode == "unanswered" and _qid in st.session_state.mock_answers:
                    _vis = False
                if filter_mode == "marked" and _qid not in st.session_state.mock_marked:
                    _vis = False
                if filter_mode == "uncertain" and _qid not in st.session_state.mock_uncertain:
                    _vis = False
                if not _vis:
                    st.markdown("&nbsp;", unsafe_allow_html=True)
                    continue

                _answered = _qid in st.session_state.mock_answers
                _marked = _qid in st.session_state.mock_marked
                _uncertain = _qid in st.session_state.mock_uncertain
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
                if st.button(_label, key=f"mock_card_{_qi}",
                             use_container_width=True, type=_btype):
                    st.session_state.mock_current = _qi
                    st.rerun()



def _save_mock_draft(subject_key: str, auto_save: bool = False):
    """将当前模拟考试状态保存为草稿
    
    auto_save=True: 后台静默保存，不暂停倒计时，不rerun，不显示提示
    """
    session_id = st.session_state.get("mock_session_id", "")
    now = time.time()
    remaining_seconds = max(0, st.session_state.get("mock_end_time", now) - now)
    draft_data = {
        "subject_key": subject_key,
        "question_ids": [q["id"] for q in st.session_state.get("mock_questions", [])],
        "answers": dict(st.session_state.get("mock_answers", {})),
        "marked": list(st.session_state.get("mock_marked", set())),
        "uncertain": list(st.session_state.get("mock_uncertain", set())),
        "current_idx": st.session_state.get("mock_current", 0),
        "session_id": session_id,
        "type_boundaries": dict(st.session_state.get("mock_type_boundaries", {})),
        "remaining_seconds": remaining_seconds,
    }
    save_draft("mock", session_id, draft_data)
    st.session_state.mock_draft_id = session_id
    if auto_save:
        return  # 静默保存，不暂停，不rerun
    st.session_state.mock_draft_saved = True
    # 暂停倒计时
    st.session_state.mock_paused_at = now
    st.session_state.mock_remaining_at_pause = remaining_seconds
    st.rerun()


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
    wrong_qids = []        # 收集答错的 (qid, user_ans) — 只含实际作答的
    correct_qids = []      # 收集答对的 qid
    answer_records = []    # 收集答题记录
    uncertain_map = {}     # 答题者自评不确定性 {qid: bool}

    for qi, q in enumerate(eq):
        qid = q["id"]
        user_ans = answers.get(qid, "")
        is_answered = user_ans != ""  # 是否实际作答
        is_uncertain = qid in st.session_state.mock_uncertain

        if not is_answered:
            # 未作答：不计分，不计入错题/统计
            is_correct = False
            score = 0
        else:
            # 防御性校验：单选/判断题的 answer 应为单个字母
            # 如果内存数据异常（如被多选题答案污染），从数据库重新读取
            effective_answer = q["answer"]
            if q["type"] in ("single", "judge") and len(effective_answer) != 1:
                from utils.data_access import get_data_access
                fresh = get_data_access().load_question_by_id(qid)
                if fresh and len(fresh.get("answer", "")) == 1:
                    effective_answer = fresh["answer"]

            is_correct = check_answer(q["type"], user_ans, effective_answer)
            score = 0
            if is_correct:
                if q["type"] == "single":
                    score = cfg["single_score"]
                elif q["type"] == "multi":
                    score = cfg["multi_score"]
                elif q["type"] == "judge":
                    score = cfg["judge_score"]
                elif q["type"] in ("案例题", "indefinite"):
                    score = cfg["indefinite_score"]
                correct_count += 1
                total_score += score
                correct_qids.append(qid)
            else:
                wrong_qids.append((qid, user_ans))

        uncertain_map[qid] = is_uncertain

        answer_records.append({
            "question_id": qid,
            "user_answer": user_ans,
            "is_correct": is_correct,
            "mode": "mock_exam",
            "session_id": st.session_state.get("mock_session_id", ""),
            "is_uncertain": is_uncertain,
        })

        details.append({
            "id": q["id"],
            "index": qi + 1,
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
    batch_update_wrong_and_stats(wrong_qids, correct_qids, stats_updates, uncertain_map)

    # 批量追加答题记录
    batch_add_answer_records(answer_records)

    # 标记数据已变更，触发首页统计缓存刷新
    st.session_state._data_version = st.session_state.get("_data_version", 0) + 1

    # 刷新统计缓存，确保后续页面读到最新数据
    st.session_state.mock_stats_cache = load_question_stats()

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

    # 提交成功后删除对应草稿
    draft_id = st.session_state.pop("mock_draft_id", None)
    if draft_id:
        delete_draft("mock", draft_id)

    st.session_state.mock_state = f"{subject_key}_finished"
    st.rerun()


def _show_subject_result(subject_key):
    """显示某一科的成绩"""
    # 守卫初始化：防止页面刷新后 session state 丢失
    if "mock_marked" not in st.session_state:
        st.session_state.mock_marked = set()
    if "mock_uncertain" not in st.session_state:
        st.session_state.mock_uncertain = set()

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

    cols = st.columns([1.2, 1.8, 1, 1])
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

    type_names = {"single": "单选题", "multi": "多选题", "judge": "判断题", "案例题": "案例题"}

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
            tp_label = {"single": "单选", "multi": "多选", "judge": "判断", "案例题": "案例题"}.get(d["type"], d["type"])
            cat_label = d.get("category", "")
            user_ans = d.get("user_answer", "").strip().upper()
            correct_ans = d["correct_answer"].strip().upper()
            options = d.get("options", {})
            opt_keys = sorted(options.keys())

            with st.expander(f"{i+1}. [{tp_label}] {d['question'][:60]}...", expanded=True):
                st.markdown(f"**题目**: {d['question']}")

                # 显示所有选项，用颜色标记
                # 注意：单选/判断题 correct_ans 是单个字母（如 "A"），必须用 ==不能用 in
                # 多选/案例题 correct_ans 是多个字母（如 "ABC"），用 in 判断
                is_multi = d["type"] in ("multi", "案例题", "indefinite")
                for k in opt_keys:
                    is_user_selected = k in user_ans
                    is_correct_key = (k in correct_ans) if is_multi else (k == correct_ans)

                    if is_multi:
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

                q_stats = st.session_state.mock_stats_cache.get(d.get("id", ""), {"correct_count": 0, "wrong_count": 0})
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
            d = details_by_idx.get(q_idx + 1, {})
            is_correct = d.get("is_correct", False)
            bg = "#c8e6c9" if is_correct else "#ffcdd2"
            tc = "#1b5e20" if is_correct else "#b71c1c"
            
            # 案例题子题：左侧紫色竖条标记
            case_border = ""
            if q_item.get("case_study_id"):
                case_border = "border-left:4px solid #9c27b0 !important;"
            
            # 标记题角标 + 不确定角标
            is_marked = q_item["id"] in st.session_state.mock_marked
            is_uncertain = q_item["id"] in st.session_state.mock_uncertain
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
                          text-align:center;position:relative;{case_border}">
                    {q_idx + 1}{indicators}
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
    if col3.button("返回", key="mock_final_home", use_container_width=True, type="primary"):
        _reset_mock_exam()
        st.session_state.pop("nav_to", None)
        st.rerun()


def _reset_mock_exam():
    """重置模拟考试状态，返回模拟考试首页"""
    keys_to_clear = [
        "mock_state", "mock_subject", "mock_questions", "mock_current",
        "mock_answers", "mock_start_time", "mock_end_time",
        "mock_confirm_submit", "mock_session_id", "mock_type_boundaries",
        "mock_result", "mock_prev_result", "mock_final_results",
        "mock_stats_cache", "mock_case_backgrounds",
        "mock_marked", "mock_uncertain", "mock_draft_id",
        "mock_paused_at", "mock_remaining_at_pause", "mock_last_auto_save",
        "mock_draft_saved",
    ]
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    # 显式设置状态为 idle，确保下次渲染进入首页
    st.session_state.mock_state = "idle"
    st.rerun()

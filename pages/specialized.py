"""
专项训练 - 按知识板块选择训练 + 综合训练（全模块随机抽题）
统一提交模式，更新错题本

功能：
1. 综合训练：从全部知识模块题库中随机抽取60题（30单选+20多选+10判断）
2. 知识板块专项训练：共11个知识板块，用户选择后从该板块抽60题（30单选+20多选+10判断）
"""
import streamlit as st
import uuid
import time
from datetime import datetime
from utils.data_manager import (
    extract_questions_by_category, extract_questions, check_answer, get_answer_display,
    batch_update_wrong_and_stats, batch_add_answer_records,
    get_all_categories, infer_category, get_question_stats,
    load_config, get_category_training_stats, load_question_stats,
    save_draft, load_drafts, delete_draft, save_exam_record,
)

# 知识板块标题图标映射（指示标题含义，不用对号/警告图标）
CATEGORY_ICONS = {
    "心理学导论": "🧠",
    "社会心理学": "👥",
    "人格心理学": "🎭",
    "发展心理学": "🌱",
    "异常心理学": "🔎",
    "咨询心理学": "💬",
    "心理咨询会谈技术": "🎙️",
    "情绪调节与压力管理": "🧘",
    "心理危机识别": "🆘",
    "家庭教育与心理健康科普": "🏠",
    "心理咨询专业伦理与相关法律规范": "⚖️",
}


def _get_cached_qstats(qid):
    """从 session_state 缓存获取题目统计；缓存缺失时回查数据库，避免切换考试类型后显示 0/0"""
    cache = st.session_state.get("spec_stats_cache", {})
    if qid in cache:
        return cache[qid]
    return get_question_stats(qid)


def show_specialized():
    questions = st.session_state.questions
    if not questions:
        st.markdown("# 🎯 专项训练")
        st.markdown("---")
        st.warning("⚠️ 题库为空，请先在配置管理中导入题库！")
        return

    # 初始化状态
    if "spec_state" not in st.session_state:
        st.session_state.spec_state = "idle"

    # 只在非答题状态显示总标题
    if st.session_state.spec_state != "running":
        st.markdown("# 🎯 专项训练")
        st.markdown("---")

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

    # 需要从界面隐藏的板块（题型或其他非知识板块）
    hidden_categories = {"案例题", ""}

    # 过滤出实际存在的板块
    available_cats = [c for c in cat_order if c in cats and c not in hidden_categories]
    # 加上可能存在但不在顺序中的板块（排除需要隐藏的）
    for c in sorted(cats.keys()):
        if c not in available_cats and c not in hidden_categories:
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
            st.markdown("**📚 综合训练**")
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

        # 获取该板块的答题统计
        cs = cat_stats.get(cat, {"total": info["total"], "answered": 0, "correct": 0, "wrong": 0})

        cat_icon = CATEGORY_ICONS.get(cat, "📖")

        with col.container(border=True):
            st.markdown(f"**{cat_icon} {cat}**")
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

    # ---- 历史草稿列表（如有，仅显示当前题库的草稿） ----
    _cur_exam_type = st.session_state.get("exam_type", "")
    drafts = [d for d in load_drafts("spec")
              if not d.get("exam_type") or d.get("exam_type") == _cur_exam_type]
    if drafts:
        st.markdown("### 📂 未完成的训练（点击继续作答）")
        for draft in drafts:
            d_id = draft.get("draft_id", "")
            d_cat = draft.get("category", "未知板块")
            d_mode = draft.get("mode", "specialized")
            d_mode_label = "综合训练" if d_mode == "comprehensive" else "专项训练"
            d_answered = len(draft.get("answers", {}))
            d_total = len(draft.get("question_ids", []))
            d_saved = draft.get("saved_at", "")
            dcol1, dcol2, dcol3 = st.columns([5, 2, 1])
            dcol1.markdown(
                f"**{d_mode_label}·{d_cat}**　"
                f"已答 {d_answered}/{d_total} 题　"
                f"🕐 {d_saved}"
            )
            if dcol2.button("▶ 继续作答", key=f"spec_resume_{d_id}", use_container_width=True, type="primary"):
                _resume_spec_draft(draft, questions)
            if dcol3.button("🗑", key=f"spec_del_draft_{d_id}", use_container_width=True, help="删除此草稿"):
                delete_draft("spec", d_id)
                st.rerun()
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

    # 预填不确定开关：历史标记为不确定的题目默认打开
    _stats_c = load_question_stats(exam_type=st.session_state.get("exam_type", "心理学会咨询师四级"))
    _pre_uncertain_c = {qid for qid, s in _stats_c.items() if s.get("self_uncertainty", 0) > 0}

    st.session_state.spec_questions = selected
    st.session_state.spec_current = 0
    st.session_state.spec_answers = {}
    st.session_state.spec_marked = set()
    st.session_state.spec_uncertain = {q["id"] for q in selected if q["id"] in _pre_uncertain_c}
    st.session_state.spec_state = "running"
    st.session_state.spec_session_id = session_id
    st.session_state.spec_last_auto_save = time.time()  # 自动保存计时起点
    st.session_state.spec_category = "综合训练"
    st.session_state.spec_confirm_submit = False
    st.session_state.spec_type_boundaries = {
        "single_end": single_end,
        "multi_end": multi_end,
    }
    st.session_state.spec_mode = "comprehensive"
    st.session_state.pop("spec_draft_id", None)  # 新训练清除旧草稿ID
    st.rerun()


def _start_specialized(questions, category):
    """开始专项训练（按指定板块抽题）"""
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

    # 预填不确定开关：历史标记为不确定的题目默认打开
    _stats_s = load_question_stats(exam_type=st.session_state.get("exam_type", "心理学会咨询师四级"))
    _pre_uncertain_s = {qid for qid, s in _stats_s.items() if s.get("self_uncertainty", 0) > 0}

    st.session_state.spec_questions = selected
    st.session_state.spec_current = 0
    st.session_state.spec_answers = {}
    st.session_state.spec_marked = set()
    st.session_state.spec_uncertain = {q["id"] for q in selected if q["id"] in _pre_uncertain_s}
    st.session_state.spec_state = "running"
    st.session_state.spec_session_id = session_id
    st.session_state.spec_last_auto_save = time.time()  # 自动保存计时起点
    st.session_state.spec_category = category
    st.session_state.spec_confirm_submit = False
    st.session_state.spec_type_boundaries = {
        "single_end": single_end,
        "multi_end": multi_end,
    }
    st.session_state.spec_mode = "specialized"
    st.session_state.pop("spec_draft_id", None)  # 新训练清除旧草稿ID
    st.rerun()


def _resume_spec_draft(draft, questions):
    """恢复专项训练草稿"""
    _clear_spec_show_ans()
    # 按 question_ids 还原题目对象（按顺序）
    q_map = {q["id"]: q for q in questions}
    restored_questions = [q_map[qid] for qid in draft.get("question_ids", []) if qid in q_map]
    if not restored_questions:
        st.error("❌ 草稿中的题目已不存在于题库中，无法恢复。")
        return

    st.session_state.spec_questions = restored_questions
    st.session_state.spec_answers = draft.get("answers", {})
    # marked 草稿存为 list，恢复时转回 set
    st.session_state.spec_marked = set(draft.get("marked", []))
    st.session_state.spec_uncertain = set(draft.get("uncertain", []))
    st.session_state.spec_current = draft.get("current_idx", 0)
    st.session_state.spec_session_id = draft.get("session_id", "")
    st.session_state.spec_category = draft.get("category", "综合训练")
    st.session_state.spec_mode = draft.get("mode", "specialized")
    st.session_state.spec_type_boundaries = draft.get("type_boundaries", {"single_end": 0, "multi_end": 0})
    st.session_state.spec_confirm_submit = False
    st.session_state.spec_state = "running"
    st.session_state.spec_last_auto_save = time.time()  # 自动保存计时起点
    # 标记当前是从草稿恢复的，用于提交时删除草稿
    st.session_state.spec_draft_id = draft.get("draft_id", "")
    st.rerun()


@st.fragment
def _show_spec_running():
    """显示专项训练进行中的界面（与背题系统统一）

    性能：@st.fragment 片段化——答题区内交互仅重跑本片段，不整页刷新；
    返回/提交等状态切换内部 st.rerun() 仍为整页，行为不变。
    """
    _exam_type = st.session_state.get("exam_type", "心理学会咨询师四级")
    # ---- 自动保存：每 5 分钟静默保存 ----
    _now = time.time()
    if _now - st.session_state.get("spec_last_auto_save", _now) >= 300:
        _save_spec_draft(auto_save=True)
        st.session_state.spec_last_auto_save = _now

    sq = st.session_state.spec_questions
    idx = st.session_state.spec_current
    if not sq or idx >= len(sq):
        st.warning("⚠️ 没有可作答的题目，请返回首页重新开始。")
        if st.button("返回", key="spec_running_empty_back", use_container_width=True):
            st.session_state.spec_state = "idle"
            for key in [k for k in st.session_state if k.startswith("spec_")]:
                del st.session_state[key]
            st.rerun()
        return
    total_q = len(sq)

    q = sq[idx]
    qid = q["id"]
    boundaries = st.session_state.spec_type_boundaries
    category = st.session_state.spec_category
    mode = st.session_state.get("spec_mode", "specialized")

    # 缓存答题统计（避免每次渲染读文件），同时按 exam_type 隔离并在切换后刷新
    if ("spec_stats_cache" not in st.session_state or
            st.session_state.get("spec_stats_cache_exam_type") != _exam_type):
        st.session_state.spec_stats_cache = load_question_stats(exam_type=_exam_type)
        st.session_state.spec_stats_cache_exam_type = _exam_type

    # 标题行 + 返回按钮（同行居右；保存按钮已移至导航行）
    mode_label = "综合训练" if mode == "comprehensive" else "专项训练"
    title_col, back_col = st.columns([5, 1])
    with title_col:
        st.markdown(f"### 🎯 {mode_label}：**{category}**")
    with back_col:
        if st.button("返回", key="spec_back_to_start", use_container_width=True):
            st.session_state.spec_state = "idle"
            keys_to_clear = [k for k in st.session_state if k.startswith("spec_")]
            for key in keys_to_clear:
                del st.session_state[key]
            st.rerun()
    # 保存成功提示
    if st.session_state.pop("spec_draft_saved", False):
        st.success("✅ 进度已保存，下次可在首页继续作答。", icon="💾")
    st.markdown("---")

    # 题型段标签
    se = boundaries["single_end"]
    me = boundaries["multi_end"]
    st.markdown(
        f"🔵 单选 {se}题 / 🟢 多选 {me-se}题 / 🟠 判断 {total_q-me}题"
    )

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
    type_labels = {"single": "🔵 单选题", "multi": "🟢 多选题", "judge": "🟠 判断题", "案例题": "🟣 案例题", "indefinite": "🟡 不定项选择题"}

    # 获取本题答题统计（从缓存读取，避免每次渲染读文件）
    q_stats = _get_cached_qstats(qid)

    # 题号行：左侧题号，右侧历史统计
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
    type_col1, type_col2, type_col3 = st.columns([6, 2, 2])
    # 答过 3 次以上才显示「不确定」开关
    total_answers = q_stats["correct_count"] + q_stats["wrong_count"]
    with type_col1:
        st.markdown(f"**{type_labels[q['type']]}**"
                    f" · 📂 {q.get('category', category)}")
    with type_col2:
        if total_answers >= 3:
            toggle_key = f"spec_uncertain_toggle_{qid}"
            if toggle_key not in st.session_state:
                st.session_state[toggle_key] = qid in st.session_state.spec_uncertain

            def _on_spec_uncertain_toggle():
                if st.session_state[toggle_key]:
                    st.session_state.spec_uncertain.add(qid)
                else:
                    st.session_state.spec_uncertain.discard(qid)

            st.toggle("不确定",
                      key=toggle_key,
                      value=qid in st.session_state.spec_uncertain,
                      help="标记此题为不确定",
                      on_change=_on_spec_uncertain_toggle)
    with type_col3:
        marked = qid in st.session_state.spec_marked

        def _toggle_mark(q=qid):
            if q in st.session_state.spec_marked:
                st.session_state.spec_marked.discard(q)
            else:
                st.session_state.spec_marked.add(q)

        st.button("⭐ 标记" if marked else "☆ 标记",
                  key=f"spec_mark_{qid}",
                  help="取消标记" if marked else "标记此题",
                  use_container_width=True,
                  on_click=_toggle_mark)
    
    # 案例题子题：在题目上方展示案例背景
    case_bg = q.get("case_background", "")
    if case_bg:
        with st.expander("📋 **案例背景**", expanded=True):
            st.markdown(case_bg)

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

    elif q["type"] in ("multi", "案例题", "indefinite"):
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
        st.markdown(
            f'<div style="background:#e8f5e9;border-left:4px solid #1b5e20;padding:8px 12px;'
            f'border-radius:4px;margin:4px 0;">'
            f'<span style="color:#1b5e20;font-weight:bold;">✅ 正确答案：{q["answer"]} - {correct_display}</span></div>',
            unsafe_allow_html=True,
        )
        if q.get("explanation"):
            with st.expander("📖 查看解析", expanded=True):
                st.markdown(q["explanation"])

    # 导航按钮（上一题、下一题、保存、提交按钮同行，使用 on_click 回调避免双重 rerun）
    nav_cols = st.columns([1, 1, 1, 1])

    def _go_prev():
        st.session_state.spec_current = max(0, st.session_state.spec_current - 1)

    def _go_next():
        st.session_state.spec_current = min(total_q - 1, st.session_state.spec_current + 1)

    def _save_callback():
        _save_spec_draft()

    def _confirm_submit():
        st.session_state.spec_confirm_submit = True

    nav_cols[0].button("◀ 上一题", use_container_width=True,
                       disabled=(idx == 0), on_click=_go_prev)
    nav_cols[1].button("下一题 ▶", use_container_width=True,
                       disabled=(idx >= total_q - 1), on_click=_go_next)
    nav_cols[2].button("💾 保存", use_container_width=True, on_click=_save_callback)
    nav_cols[3].button("📤 提交所有答案", use_container_width=True,
                       type="primary", on_click=_confirm_submit)

    if st.session_state.get("spec_confirm_submit"):
        unanswered = total_q - len(st.session_state.spec_answers)
        st.warning(f"⚠️ 还有 {unanswered} 题未答，确认提交吗？未答题将计为错误。")
        col_c1, col_c2 = st.columns(2)
        if col_c1.button("✅ 确认提交", use_container_width=True):
            _finish_specialized()
            st.rerun()
        col_c2.button("❌ 继续答题", use_container_width=True,
                      on_click=lambda: st.session_state.update(spec_confirm_submit=False))

    # ---- 答题卡 ----
    st.markdown("---")
    st.markdown("#### 📌 答题卡")

    # 筛选按钮
    filter_key = "spec_card_filter"
    if filter_key not in st.session_state:
        st.session_state[filter_key] = "all"

    def _card_filter(v):
        def _cb():
            st.session_state[filter_key] = v
        return _cb

    fc1, fc2, fc3, fc4, fc5 = st.columns(5)
    fc1.button("📋 全部", key="spec_filter_all", use_container_width=True,
               type="primary" if st.session_state[filter_key] == "all" else "secondary",
               on_click=_card_filter("all"))
    fc2.button("✅ 已答", key="spec_filter_answered", use_container_width=True,
               type="primary" if st.session_state[filter_key] == "answered" else "secondary",
               on_click=_card_filter("answered"))
    fc3.button("⬜ 未答", key="spec_filter_unanswered", use_container_width=True,
               type="primary" if st.session_state[filter_key] == "unanswered" else "secondary",
               on_click=_card_filter("unanswered"))
    fc4.button("⭐ 已标记", key="spec_filter_marked", use_container_width=True,
               type="primary" if st.session_state[filter_key] == "marked" else "secondary",
               on_click=_card_filter("marked"))
    fc5.button("不确定", key="spec_filter_uncertain", use_container_width=True,
               type="primary" if st.session_state[filter_key] == "uncertain" else "secondary",
               on_click=_card_filter("uncertain"))

    filter_mode = st.session_state[filter_key]
    answered = len(st.session_state.spec_answers)
    marked_count = len(st.session_state.spec_marked)
    uncertain_count = len(st.session_state.spec_uncertain)
    st.progress(answered / total_q, text=f"已答 {answered}/{total_q}"
        + (f" · 已标记 {marked_count}" if marked_count else "")
        + (f" · 不确定 {uncertain_count}" if uncertain_count else ""))

    # 答题卡导航格子（Streamlit 原生按钮，不会打开新标签页）
    st.markdown("""
    <style>
    div.stButton > button {
        font-size: 10px !important; white-space: nowrap !important;
        padding-left: 0px !important; padding-right: 0px !important;
        min-height: 18px !important;
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
                _qit = sq[_qi]
                _qid = _qit["id"]

                _vis = True
                if filter_mode == "answered" and _qid not in st.session_state.spec_answers:
                    _vis = False
                if filter_mode == "unanswered" and _qid in st.session_state.spec_answers:
                    _vis = False
                if filter_mode == "marked" and _qid not in st.session_state.spec_marked:
                    _vis = False
                if filter_mode == "uncertain" and _qid not in st.session_state.spec_uncertain:
                    _vis = False
                if not _vis:
                    st.markdown("&nbsp;", unsafe_allow_html=True)
                    continue

                _answered = _qid in st.session_state.spec_answers
                _marked = _qid in st.session_state.spec_marked
                _uncertain = _qid in st.session_state.spec_uncertain
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
                    f'<div style="text-align:right;height:14px;line-height:14px;">{"".join(_badges)}</div>',
                    unsafe_allow_html=True,
                )
                st.button(_label, key=f"spec_card_{_qi}",
                          use_container_width=True, type=_btype,
                          on_click=lambda i=_qi: setattr(
                              st.session_state, "spec_current", i))



def _save_spec_draft(auto_save: bool = False):
    """将当前专项训练/综合训练状态保存为草稿
    
    auto_save=True: 后台静默保存，不rerun，不显示提示
    """
    session_id = st.session_state.get("spec_session_id", "")
    draft_data = {
        "exam_type": st.session_state.get("exam_type", ""),
        "category": st.session_state.get("spec_category", ""),
        "mode": st.session_state.get("spec_mode", "specialized"),
        "question_ids": [q["id"] for q in st.session_state.get("spec_questions", [])],
        "answers": dict(st.session_state.get("spec_answers", {})),
        "marked": list(st.session_state.get("spec_marked", set())),
        "uncertain": list(st.session_state.get("spec_uncertain", set())),
        "current_idx": st.session_state.get("spec_current", 0),
        "session_id": session_id,
        "type_boundaries": dict(st.session_state.get("spec_type_boundaries", {})),
    }
    save_draft("spec", session_id, draft_data)
    st.session_state.spec_draft_id = session_id
    if auto_save:
        return  # 静默保存
    st.session_state.spec_draft_saved = True

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
    uncertain_map = {}   # 答题者自评不确定性 {qid: bool}

    for q in sq:
        qid = q["id"]
        user_ans = answers.get(qid, "")
        is_correct = check_answer(q["type"], user_ans, q["answer"])
        is_uncertain = qid in st.session_state.spec_uncertain

        if is_correct:
            correct_count += 1
            correct_qids.append(qid)
        else:
            wrong_qids.append((qid, user_ans))

        uncertain_map[qid] = is_uncertain

        # 收集答题记录
        answer_records.append({
            "question_id": qid,
            "user_answer": user_ans,
            "is_correct": is_correct,
            "mode": "specialized" if mode == "specialized" else "comprehensive",
            "session_id": st.session_state.get("spec_session_id", ""),
            "is_uncertain": is_uncertain,
        })

        details.append({
            "id": q["id"],
            "index": q.get("index", q.get("index_num", 0)),
            "type": q["type"],
            "question": q["question"],
            "options": q.get("options", {}),
            "explanation": q.get("explanation", ""),
            "user_answer": user_ans,
            "correct_answer": q["answer"],
            "is_correct": is_correct,
            "category": q.get("category", category),
            "case_background": q.get("case_background", ""),
        })

    # 批量更新错题库和答题统计（单次读取+单次写入）
    stats_updates = [(qid, True) for qid in correct_qids] + [(qid, False) for qid, _ in wrong_qids]
    batch_update_wrong_and_stats(wrong_qids, correct_qids, stats_updates, uncertain_map)

    # 刷新统计缓存，确保结果页读到最新数据
    _exam_type = st.session_state.get("exam_type", "心理学会咨询师四级")
    st.session_state.spec_stats_cache = load_question_stats(exam_type=_exam_type)
    st.session_state.spec_stats_cache_exam_type = _exam_type

    # 批量追加答题记录
    batch_add_answer_records(answer_records, exam_type=st.session_state.get("exam_type", "心理学会咨询师四级"))

    # 标记数据已变更，触发首页统计缓存刷新
    st.session_state._data_version = st.session_state.get("_data_version", 0) + 1

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

    # 保存考试记录到数据库
    save_exam_record({
        "type": mode,  # "specialized" 或 "comprehensive"
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": total_q,
        "correct": correct_count,
        "accuracy": f"{correct_count/total_q*100:.1f}%",
        "category": category,
    }, exam_type=st.session_state.get("exam_type", "心理学会咨询师四级"))

    # 提交成功后删除对应草稿（如果本次是从草稿恢复的，或曾保存过进度）
    draft_id = st.session_state.pop("spec_draft_id", None)
    if draft_id:
        delete_draft("spec", draft_id)
    st.rerun()


def _show_spec_result():
    """显示专项训练结果"""
    _exam_type = st.session_state.get("exam_type", "心理学会咨询师四级")
    # 守卫初始化：防止页面刷新后 session state 丢失
    if ("spec_stats_cache" not in st.session_state or
            st.session_state.get("spec_stats_cache_exam_type") != _exam_type):
        st.session_state.spec_stats_cache = load_question_stats(exam_type=_exam_type)
        st.session_state.spec_stats_cache_exam_type = _exam_type
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

    # 错题回顾
    st.markdown("---")
    wrong_details = [d for d in details if not d["is_correct"]]
    if wrong_details:
        st.markdown(f"### ❌ 错题回顾 ({len(wrong_details)}题)")

        for i, d in enumerate(wrong_details):
            tp_label = {"single": "单选", "multi": "多选", "judge": "判断"}[d["type"]]
            user_label = d.get("user_answer", "未答") or "未答"
            correct_display = get_answer_display(
                d["type"], d["correct_answer"], d.get("options", {})
            )
            with st.expander(f"{i+1}. [{tp_label}] {d['question'][:60]}...", expanded=True):
                # 案例背景
                case_bg = d.get("case_background", "")
                if case_bg:
                    st.markdown(f"**📋 案例背景**：{case_bg[:200]}{'...' if len(case_bg) > 200 else ''}")

                st.markdown(f"**题目**: {d['question']}")
                # 显示所有选项，用颜色标记
                options = d.get("options", {})
                user_ans = d.get("user_answer", "") or ""
                correct_ans = d.get("correct_answer", "")
                for k, v in sorted(options.items()):
                    is_user_selected = k in user_ans
                    is_correct_key = k in correct_ans

                    if d["type"] in ("multi", "案例题", "indefinite"):
                        if is_user_selected and is_correct_key:
                            st.markdown(f'<p style="color:#1b5e20;font-weight:bold;">✅ {k}: {v}</p>',
                                        unsafe_allow_html=True)
                        elif is_user_selected and not is_correct_key:
                                st.markdown(f'<p style="color:#b71c1c;font-weight:bold;">❌️ {k}: {v} (错选)</p>',
                                            unsafe_allow_html=True)
                        elif not is_user_selected and is_correct_key:
                            st.markdown(f'<p style="color:#1b5e20;font-weight:bold;">✅ {k}: {v} (漏选)</p>',
                                        unsafe_allow_html=True)
                        else:
                            st.markdown(f'{k}: {v}')
                    else:
                        if is_user_selected and is_correct_key:
                            st.markdown(f'<p style="color:#1b5e20;font-weight:bold;">✅ {k}: {v}</p>',
                                        unsafe_allow_html=True)
                        elif is_user_selected and not is_correct_key:
                                st.markdown(f'<p style="color:#b71c1c;font-weight:bold;">❌️ {k}: {v} (错选)</p>',
                                            unsafe_allow_html=True)
                        elif not is_user_selected and is_correct_key:
                            st.markdown(f'<p style="color:#1b5e20;font-weight:bold;">✅ {k}: {v}</p>',
                                        unsafe_allow_html=True)
                        else:
                            st.markdown(f'{k}: {v}')
                st.markdown(f'<p style="color:red;font-weight:bold;">你的答案: {user_label}</p>', unsafe_allow_html=True)
                st.markdown(
                    f'<div style="background:#e8f5e9;border-left:4px solid #1b5e20;padding:8px 12px;'
                    f'border-radius:4px;margin:4px 0;">'
                    f'<span style="color:#1b5e20;font-weight:bold;">✅ 正确答案：{d["correct_answer"]} - {correct_display}</span></div>',
                    unsafe_allow_html=True,
                )
                # 解析（直接跟在正确答案后面）
                explanation = d.get("explanation", "")
                if explanation:
                    st.markdown(explanation)
                st.markdown(f"**知识板块**: {d.get('category', category)}")
                q_stats = _get_cached_qstats(d.get("id", ""))
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
            d = details_by_idx.get(q_item.get("index", q_item.get("index_num", 0)), {})
            is_correct = d.get("is_correct", False)
            bg = "#c8e6c9" if is_correct else "#ffcdd2"
            tc = "#1b5e20" if is_correct else "#b71c1c"
            
            is_marked = q_item["id"] in st.session_state.get("spec_marked", set())
            is_uncertain = q_item["id"] in st.session_state.get("spec_uncertain", set())
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
    if col2.button("返回", key="spec_result_home", use_container_width=True, type="primary"):
        st.session_state.spec_state = "idle"
        # 清除全部 spec_ 状态，彻底返回首页
        keys_to_clear = [k for k in st.session_state if k.startswith("spec_")]
        for key in keys_to_clear:
            del st.session_state[key]
        st.rerun()

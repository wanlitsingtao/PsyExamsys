"""
错题本 v2.3 - 双入口模式 + 统一答题界面
  1. 错题解析：按易错程度排序，左侧列表 + 右侧逐条解析
  2. 做错题：统一提交答题模式，操作元素与其他答题页面一致
"""
import streamlit as st
import uuid
import time
from datetime import datetime

from utils.data_manager import (
    get_top_wrong_questions, check_answer, get_answer_display,
    batch_update_wrong_and_stats, batch_add_answer_records,
    remove_wrong_question, clear_all_wrong, get_wrong_stats,
    load_questions, load_question_stats, infer_category,
    get_all_wrong_with_stats, save_exam_record, save_draft,
)


def _get_cached_qstats(qid):
    """从 session_state 缓存获取题目统计，带默认值"""
    cache = st.session_state.get("wb_stats_cache", {})
    return cache.get(qid, {"correct_count": 0, "wrong_count": 0, "last_answer_time": None, "last_correct": None})


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

    # ---- 错题本状态 ----
    wrong_stats = get_wrong_stats(st.session_state.get("exam_type"))

    if wrong_stats["total"] == 0:
        # 清空练习模式缓存
        for key in ["wb_questions", "wb_wrong_counts", "wb_answers", "wb_submitted", "wb_results", "wb_marked", "wb_uncertain"]:
            st.session_state.pop(key, None)
        st.success("🎉 太棒了！错题本为空，继续加油！")
        return

    # ---- 错题解析 ----
    st.markdown("### 📖 错题解析")
    st.markdown(
        "按易错程度（答错次数 - 答对次数）由高到低排序，"
        "逐条查看题目、全部选项、正确答案和详细解析。"
        "适合深度理解错题背后的知识点。"
    )
    if st.button("📖 进入错题解析", key="btn_analysis", use_container_width=True, type="primary"):
        st.session_state.wb_mode = "analysis"
        st.session_state.wa_selected_idx = 0
        st.session_state.pop("wa_all_wrong", None)   # 强制刷新缓存
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

    _cur = st.session_state.get("_data_version", 0)

    # 1. 缓存错题列表（带 _data_version 版本号）
    _wa_all_vkey = "wa_all_wrong_v"
    if _cur != st.session_state.get(_wa_all_vkey, -1) or "wa_all_wrong" not in st.session_state:
        st.session_state.wa_all_wrong = get_all_wrong_with_stats(st.session_state.get("exam_type"))
        st.session_state[_wa_all_vkey] = _cur
    all_wrong = st.session_state.wa_all_wrong

    # 2. 从 wa_all_wrong 构建 stats 缓存（避免全表加载）
    _wa_stats_vkey = "wa_stats_cache_v"
    if _cur != st.session_state.get(_wa_stats_vkey, -1) or "wb_stats_cache" not in st.session_state:
        cache = {}
        for item in all_wrong:
            qid = item["question_id"]
            cache[qid] = {
                "correct_count": item["correct_count"],
                "wrong_count": item["wrong_count"],
                "last_answer_time": item.get("last_answer_time"),
                "last_correct": item.get("last_correct"),
                "mastery_level": item.get("mastery_level", "未掌握"),
                "confidence": item.get("confidence", 0),
            }
        st.session_state.wb_stats_cache = cache
        st.session_state[_wa_stats_vkey] = _cur

    if not all_wrong:
        st.success("🎉 没有错题！")
        return

    total = len(all_wrong)

    # 顶部导航栏
    top_cols = st.columns([3, 1])
    with top_cols[0]:
        st.markdown(f"共 **{total}** 题 · 按易错程度（答错次数 - 答对次数）由高到低排列")
    with top_cols[1]:
        if st.button("返回", key="wa_back", use_container_width=True):
            st.session_state.pop("wa_all_wrong", None)
            st.session_state.pop("wb_stats_cache", None)
            st.session_state.pop("wa_stats_cache_v", None)
            st.session_state.pop("wa_all_wrong_v", None)
            st.session_state.pop("wb_mode", None)
            st.rerun()

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
                key=f"wa_radio_list_{cur_idx}",
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

    # 案例题：在题目上方显示案例背景
    case_bg = item.get("case_background", "")
    if case_bg:
        with st.expander("📋 案例背景", expanded=True):
            st.markdown(case_bg)

    # 题目
    st.markdown("---")
    st.markdown(f"**📝 题目：** {item['question']}")

    # 全部选项（正确答案用深绿色标注）
    st.markdown("**选项：**")
    options = item["options"]
    opt_keys = sorted(options.keys())
    correct_ans = item["answer"].strip().upper()

    for k in opt_keys:
        is_correct = k in correct_ans
        if is_correct:
            st.markdown(f'<p style="color:#1b5e20;font-weight:bold;">✅ {k}: {options[k]}</p>',
                        unsafe_allow_html=True)
        else:
            st.markdown(f'{k}: {options[k]}')

    # 正确答案
    correct_display = get_answer_display(item["type"], correct_ans, options)
    st.markdown(
        f'<div style="background:#e8f5e9;border-left:4px solid #1b5e20;padding:8px 12px;'
        f'border-radius:4px;margin:4px 0;">'
        f'<span style="color:#1b5e20;font-weight:bold;">✅ 正确答案：{correct_display}</span></div>',
        unsafe_allow_html=True,
    )

    # 解析
    explanation = item.get("explanation", "")
    if explanation:
        with st.expander("📖 题目解析", expanded=True):
            st.markdown(explanation)

    # 底部导航：切换至相邻题目
    st.markdown("---")
    op_c1, op_c2, op_c3 = st.columns([1, 1, 1])
    with op_c1:
        if st.button("◀ 上一题", key=f"wa_detail_prev_{idx}",
                     use_container_width=True, disabled=(idx == 0)):
            st.session_state.wa_selected_idx = idx - 1
            st.rerun()
    with op_c2:
        st.caption(f"第 {idx+1} / {total} 题")
    with op_c3:
        if st.button("下一题 ▶", key=f"wa_detail_next_{idx}",
                     use_container_width=True, disabled=(idx >= total - 1)):
            st.session_state.wa_selected_idx = idx + 1
            st.rerun()


# ============================
#  做错题模式（原错题本答题功能）
# ============================

def _show_wrong_practice():
    # 缓存答题统计（避免每题渲染时重复读盘）
    if "wb_stats_cache" not in st.session_state:
        st.session_state.wb_stats_cache = load_question_stats()

    wrong_stats = get_wrong_stats(st.session_state.get("exam_type"))
    config = st.session_state.config
    type_labels = {"single": "🔵 单选题", "multi": "🟢 多选题", "judge": "🟠 判断题", "案例题": "🟣 案例题", "indefinite": "🟡 不定项选择题"}

    if wrong_stats["total"] == 0:
        for key in ["wb_questions", "wb_wrong_counts", "wb_answers", "wb_submitted", "wb_results", "wb_marked", "wb_uncertain"]:
            st.session_state.pop(key, None)
        st.success("🎉 太棒了！错题本为空，继续加油！")
        return

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
        st.session_state.wb_marked = set()
        st.session_state.wb_uncertain = set()
        st.session_state.wb_submitted = False
        st.session_state.wb_results = {}
        st.session_state.wb_regenerate = False
        st.session_state.wb_cached_total = wrong_stats["total"]
        st.session_state.wb_confirm_submit = False
        st.session_state.wb_last_auto_save = time.time()  # 自动保存计时起点

    wq = st.session_state.wb_questions
    if not wq:
        st.info("错题已全部掌握！")
        return

    total_q = len(wq)
    idx = st.session_state.wb_current
    q = wq[idx]
    qid = q["id"]
    is_submitted = st.session_state.wb_submitted
    # ---- 自动保存：每 5 分钟静默保存（仅答题中） ----
    if not is_submitted:
        if "wb_last_auto_save" not in st.session_state:
            st.session_state.wb_last_auto_save = time.time()
        _now = time.time()
        if _now - st.session_state.wb_last_auto_save >= 300:
            _save_wrongbook_draft(auto_save=True)
            st.session_state.wb_last_auto_save = _now
    wrong_count = st.session_state.wb_wrong_counts.get(qid, 0)
    correct_count = sum(1 for v in st.session_state.wb_results.values() if v.get("correct", False))

    # 确保 wb_marked / wb_uncertain 始终存在（从草稿恢复时可能缺失）
    if "wb_marked" not in st.session_state:
        st.session_state.wb_marked = set()
    if "wb_uncertain" not in st.session_state:
        st.session_state.wb_uncertain = set()

    # ---- 标题行 + 返回（保存按钮已移至导航行） ----
    if is_submitted:
        title_col, back_col = st.columns([5, 1])
        with title_col:
            st.markdown(f"## ✏️ 做错题 — 结果")
    else:
        title_col, back_col = st.columns([5, 1])
        with title_col:
            st.markdown("## ✏️ 做错题")

    with back_col:
        if st.button("返回", key="wb_back_practice", use_container_width=True):
            for key in ["wb_mode", "wb_questions", "wb_wrong_counts", "wb_answers", "wb_submitted", "wb_results",
                         "wb_marked", "wb_uncertain", "wb_current", "wb_regenerate", "wb_confirm_submit", "wb_confirm_clear",
                         "wb_card_filter"]:
                st.session_state.pop(key, None)
            st.rerun()

    # 保存成功提示
    if st.session_state.pop("wb_draft_saved", False):
        st.success("✅ 进度已保存，下次可在首页继续作答。", icon="💾")

    st.markdown("---")

    if is_submitted:
        # ======== 已提交状态：显示结果 ========
        result = st.session_state.wb_results.get(qid, {})
        correct = result.get("correct", False)

        # 选项间距（与 mock_exam 一致）
        st.markdown("""
        <style>
        div[data-testid="stRadio"] > div { gap: 0.75em; }
        div[data-testid="stRadio"] > div > label { padding: 0.3em 0; }
        div[data-testid="stCheckbox"] > label { padding: 0.3em 0; }
        </style>
        """, unsafe_allow_html=True)

        # 题号行：左侧题号，右侧历史统计（与 mock_exam 一致）
        title_cols = st.columns([1, 2])
        with title_cols[0]:
            st.markdown(f"##### 第 {idx+1}/{total_q} 题")
        with title_cols[1]:
            q_stats = _get_cached_qstats(qid)
            stats_parts = []
            if q_stats["correct_count"] > 0 or q_stats["wrong_count"] > 0:
                stats_parts.append(f"答对 {q_stats['correct_count']} 次 / 答错 {q_stats['wrong_count']} 次")
            last_correct = q_stats.get("last_correct")
            if last_correct is True:
                stats_parts.append("🟢 上次答对")
            elif last_correct is False:
                stats_parts.append("🔴 上次答错")
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

        # 题型标签行
        st.markdown(f"**{type_labels[q['type']]}**"
                    f"{' · 📂 ' + q.get('category', infer_category(q.get('source_file', ''))) if q.get('category') or q.get('source_file') else ''}")

        # 案例题子题：在题目上方展示案例背景
        case_bg = q.get("case_background", "")
        if case_bg:
            with st.expander("📋 **案例背景**", expanded=True):
                st.markdown(case_bg)

        st.markdown(f"**{q['question']}**")

        if correct:
            st.success("✅ **回答正确！**")
        else:
            st.error("❌ **回答错误！**")

        options = q["options"]
        opt_keys = sorted(options.keys())

        for k in opt_keys:
            user_ans = st.session_state.wb_answers.get(qid, "")
            is_selected = k in user_ans
            is_correct_key = k in q["answer"]

            if q["type"] in ("multi", "案例题", "indefinite"):
                if is_selected and is_correct_key:
                    st.markdown(f'<p style="color:#1b5e20;font-weight:bold;">✅ {k}: {options[k]}</p>',
                                unsafe_allow_html=True)
                elif is_selected and not is_correct_key:
                    st.markdown(f'{k}: {options[k]}')
                elif not is_selected and is_correct_key:
                    st.markdown(f'<p style="color:#1b5e20;font-weight:bold;">✅ {k}: {options[k]} (漏选)</p>',
                                unsafe_allow_html=True)
                else:
                    st.markdown(f'{k}: {options[k]}')
            else:
                if is_selected and is_correct_key:
                    st.markdown(f'<p style="color:#1b5e20;font-weight:bold;">✅ {k}: {options[k]}</p>',
                                unsafe_allow_html=True)
                elif is_selected and not is_correct_key:
                    st.markdown(f'<p style="color:#b71c1c;font-weight:bold;">❌ {k}: {options[k]} (错选)</p>',
                                unsafe_allow_html=True)
                elif not is_selected and is_correct_key:
                    st.markdown(f'<p style="color:#1b5e20;font-weight:bold;">✅ {k}: {options[k]}</p>',
                                unsafe_allow_html=True)
                else:
                    st.markdown(f'{k}: {options[k]}')

        correct_display = get_answer_display(q["type"], q["answer"], options)
        st.markdown(
            f'<div style="background:#e8f5e9;border-left:4px solid #1b5e20;padding:8px 12px;'
            f'border-radius:4px;margin:4px 0;">'
            f'<span style="color:#1b5e20;font-weight:bold;">✅ 正确答案：{correct_display}</span></div>',
            unsafe_allow_html=True,
        )

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
        # 获取答题统计（提前到不确定开关之前）
        q_stats = _get_cached_qstats(qid)
        total_answers = q_stats["correct_count"] + q_stats["wrong_count"]

        # 题型标签 + 不确定按钮 + 标记按钮 同行
        title_col1, title_col2, title_col3 = st.columns([6, 2, 2])
        with title_col1:
            st.markdown(f"##### 第 {idx+1}/{total_q} 题  |  ⚠️ 答错 {wrong_count} 次")
            st.markdown(f"**{type_labels[q['type']]}**"
                        f"{' · 📂 ' + q.get('category', infer_category(q.get('source_file', ''))) if q.get('category') or q.get('source_file') else ''}")
        with title_col2:
            if total_answers >= 3:
                if "wb_uncertain" not in st.session_state:
                    st.session_state.wb_uncertain = set()

                toggle_key = f"wb_uncertain_toggle_{qid}"
                if toggle_key not in st.session_state:
                    st.session_state[toggle_key] = qid in st.session_state.wb_uncertain

                def _on_wb_uncertain_toggle():
                    if st.session_state[toggle_key]:
                        st.session_state.wb_uncertain.add(qid)
                    else:
                        st.session_state.wb_uncertain.discard(qid)

                st.toggle("不确定",
                          key=toggle_key,
                          value=qid in st.session_state.wb_uncertain,
                          help="标记此题为不确定",
                          on_change=_on_wb_uncertain_toggle)
        with title_col3:
            marked = qid in st.session_state.get("wb_marked", set())
            if st.button("⭐ 标记" if marked else "☆ 标记",
                         key=f"wb_mark_{qid}",
                         help="取消标记" if marked else "标记此题",
                         use_container_width=True):
                if "wb_marked" not in st.session_state:
                    st.session_state.wb_marked = set()
                if qid in st.session_state.wb_marked:
                    st.session_state.wb_marked.discard(qid)
                else:
                    st.session_state.wb_marked.add(qid)
                st.rerun()
        # 案例题子题：在题目上方展示案例背景
        case_bg = q.get("case_background", "")
        if case_bg:
            with st.expander("📋 **案例背景**", expanded=True):
                st.markdown(case_bg)
        st.markdown(f"**{q['question']}**")
        # 正文区按钮字号与不确定开关一致（答题卡区有 10px 覆盖）
        st.markdown("""
        <style>
        div.stButton > button {
            font-size: 13px !important;
        }
        </style>
        """, unsafe_allow_html=True)
        stats_parts = []
        if q_stats["correct_count"] > 0 or q_stats["wrong_count"] > 0:
            stats_parts.append(f"答对 {q_stats['correct_count']} 次 / 答错 {q_stats['wrong_count']} 次")
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

        elif q["type"] in ("multi", "案例题", "indefinite"):
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

    # ---- 导航按钮（上一题、下一题、保存、提交按钮同行） ----
    nav_cols = st.columns([1, 1, 1, 1])

    if nav_cols[0].button("◀ 上一题", use_container_width=True, disabled=(idx == 0)):
        st.session_state.wb_current = idx - 1
        st.rerun()

    if nav_cols[1].button("下一题 ▶", use_container_width=True, disabled=(idx >= total_q - 1)):
        st.session_state.wb_current = idx + 1
        st.rerun()

    if not is_submitted:
        if nav_cols[2].button("💾 保存", use_container_width=True):
            _save_wrongbook_draft()

        if nav_cols[3].button("📤 提交全部答案", use_container_width=True, type="primary"):
            st.session_state.wb_confirm_submit = True

    if st.session_state.get("wb_confirm_submit"):
        unanswered = total_q - len(st.session_state.wb_answers)
        st.warning(f"⚠️ 还有 {unanswered} 题未答，确认提交吗？未答题将计为错误。")
        col_c1, col_c2 = st.columns(2)
        if col_c1.button("✅ 确认提交", use_container_width=True):
            _submit_wrongbook()
            st.rerun()
        if col_c2.button("❌ 继续答题", use_container_width=True):
            st.session_state.wb_confirm_submit = False
            st.rerun()

    # ---- 答题卡 ----
    st.markdown("---")
    st.markdown("#### 📌 答题卡" + ("（🟢=正确 🔴=错误/漏答）" if is_submitted else ""))

    # 筛选 + 进度（仅答题中出现）
    if not is_submitted:
        filter_key = "wb_card_filter"
        if filter_key not in st.session_state:
            st.session_state[filter_key] = "all"

        fc1, fc2, fc3, fc4, fc5 = st.columns(5)
        if fc1.button("📋 全部", key="wb_filter_all", use_container_width=True,
                      type="primary" if st.session_state[filter_key] == "all" else "secondary"):
            st.session_state[filter_key] = "all"
            st.rerun()
        if fc2.button("✅ 已答", key="wb_filter_answered", use_container_width=True,
                      type="primary" if st.session_state[filter_key] == "answered" else "secondary"):
            st.session_state[filter_key] = "answered"
            st.rerun()
        if fc3.button("⬜ 未答", key="wb_filter_unanswered", use_container_width=True,
                      type="primary" if st.session_state[filter_key] == "unanswered" else "secondary"):
            st.session_state[filter_key] = "unanswered"
            st.rerun()
        if fc4.button("⭐ 已标记", key="wb_filter_marked", use_container_width=True,
                      type="primary" if st.session_state[filter_key] == "marked" else "secondary"):
            st.session_state[filter_key] = "marked"
            st.rerun()
        if fc5.button("不确定", key="wb_filter_uncertain", use_container_width=True,
                      type="primary" if st.session_state[filter_key] == "uncertain" else "secondary"):
            st.session_state[filter_key] = "uncertain"
            st.rerun()

        filter_mode = st.session_state[filter_key]
        answered = len(st.session_state.wb_answers)
        marked_count = len(st.session_state.get("wb_marked", set()))
        uncertain_count = len(st.session_state.get("wb_uncertain", set()))
        st.progress(answered / total_q, text=f"已答 {answered}/{total_q}"
            + (f" · 已标记 {marked_count}" if marked_count else "")
            + (f" · 不确定 {uncertain_count}" if uncertain_count else ""))
    else:
        filter_mode = "all"

    # ======== 答题卡网格（Streamlit 原生按钮，不会打开新标签页）========
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
                _qit = wq[_qi]
                _qid = _qit["id"]

                _vis = True
                if filter_mode == "answered" and _qid not in st.session_state.wb_answers:
                    _vis = False
                if filter_mode == "unanswered" and _qid in st.session_state.wb_answers:
                    _vis = False
                if filter_mode == "marked" and _qid not in st.session_state.get("wb_marked", set()):
                    _vis = False
                if filter_mode == "uncertain" and _qid not in st.session_state.get("wb_uncertain", set()):
                    _vis = False
                if not _vis:
                    st.markdown("&nbsp;", unsafe_allow_html=True)
                    continue

                _answered = _qid in st.session_state.wb_answers
                _marked = _qid in st.session_state.get("wb_marked", set())
                _uncertain = _qid in st.session_state.get("wb_uncertain", set())
                _current = _qi == idx
                _is_correct = st.session_state.wb_results.get(_qid, {}).get("correct", False)

                _label = str(_qi + 1)
                if _current:
                    _label = f"▶{_label}"

                if is_submitted:
                    _btype = "primary" if _is_correct else "secondary"
                else:
                    _btype = "primary" if _answered else "secondary"
                # 标记/不确定：固定高度角标行（所有按钮对齐，提交后不显示）
                _badges = []
                if _marked and not is_submitted:
                    _badges.append('<span style="font-size:8px;color:#ff9800;">⭐</span>')
                if _uncertain and not is_submitted:
                    _badges.append('<span style="font-size:8px;color:#ff9800;">?</span>')
                st.markdown(
                    f'<div style="text-align:right;height:11px;line-height:11px;overflow:hidden;">{"".join(_badges)}</div>',
                    unsafe_allow_html=True,
                )
                if st.button(_label, key=f"wb_card_{_qi}",
                             use_container_width=True, type=_btype):
                    st.session_state.wb_current = _qi
                    st.rerun()

    # 完成提示
    if is_submitted and total_q > 0:
        # ======== 错题回顾 ========
        wrong_qs = []
        for _q in wq:
            _qid = _q["id"]
            _result = st.session_state.wb_results.get(_qid, {})
            if not _result.get("correct", True):
                wrong_qs.append((_q, _result.get("user_answer", "")))
        
        if wrong_qs:
            st.markdown("---")
            st.markdown(f"### ❌ 错题回顾 ({len(wrong_qs)}题)")
            for wi, (_wq, _user_ans) in enumerate(wrong_qs):
                _wqid = _wq["id"]
                _wtype = _wq["type"]
                _woptions = _wq["options"]
                _wopt_keys = sorted(_woptions.keys())
                _wcorrect_ans = _wq["answer"].strip().upper()
                _wuser_ans = _user_ans.strip().upper()
                _is_multi = _wtype in ("multi", "案例题", "indefinite")
                
                _review_tp_labels = {"single": "单选", "multi": "多选", "judge": "判断", "案例题": "案例题", "indefinite": "不定项选择题"}
                with st.expander(f"{wi+1}. [{_review_tp_labels.get(_wtype, _wtype)}] {_wq['question'][:60]}...", expanded=True):
                    # 案例背景
                    _wcase_bg = _wq.get("case_background", "")
                    if _wcase_bg:
                        st.markdown(f"**📋 案例背景**：{_wcase_bg[:200]}{'...' if len(_wcase_bg) > 200 else ''}")
                    
                    st.markdown(f"**题目**: {_wq['question']}")
                    
                    # 显示所有选项，用颜色标记（与 mock_exam 一致）
                    for _k in _wopt_keys:
                        _is_user_sel = _k in _wuser_ans
                        _is_correct_key = (_k in _wcorrect_ans) if _is_multi else (_k == _wcorrect_ans)
                        
                        if _is_multi:
                            if _is_user_sel and _is_correct_key:
                                st.markdown(f'<p style="color:#1b5e20;font-weight:bold;">✅ {_k}: {_woptions[_k]}</p>', unsafe_allow_html=True)
                            elif _is_user_sel and not _is_correct_key:
                                st.markdown(f'<p style="color:#b71c1c;font-weight:bold;">❌ {_k}: {_woptions[_k]} (错选)</p>', unsafe_allow_html=True)
                            elif not _is_user_sel and _is_correct_key:
                                st.markdown(f'<p style="color:#1b5e20;font-weight:bold;">✅ {_k}: {_woptions[_k]} (漏选)</p>', unsafe_allow_html=True)
                            else:
                                st.markdown(f'{_k}: {_woptions[_k]}')
                        else:
                            if _is_user_sel and _is_correct_key:
                                st.markdown(f'<p style="color:#1b5e20;font-weight:bold;">✅ {_k}: {_woptions[_k]}</p>', unsafe_allow_html=True)
                            elif _is_user_sel and not _is_correct_key:
                                st.markdown(f'<p style="color:#b71c1c;font-weight:bold;">❌ {_k}: {_woptions[_k]} (错选)</p>', unsafe_allow_html=True)
                            elif not _is_user_sel and _is_correct_key:
                                st.markdown(f'<p style="color:#1b5e20;font-weight:bold;">✅ {_k}: {_woptions[_k]}</p>', unsafe_allow_html=True)
                            else:
                                st.markdown(f'{_k}: {_woptions[_k]}')
                    
                    # 你的答案
                    if _wuser_ans:
                        _user_display = get_answer_display(_wtype, _wuser_ans, _woptions)
                        st.error(f"**你的答案**：{_user_display}")
                    else:
                        st.error("**你的答案**：未作答")
                    
                    # 正确答案
                    _correct_display = get_answer_display(_wtype, _wcorrect_ans, _woptions)
                    st.markdown(
                        f'<div style="background:#e8f5e9;border-left:4px solid #1b5e20;padding:8px 12px;'
                        f'border-radius:4px;margin:4px 0;">'
                        f'<span style="color:#1b5e20;font-weight:bold;">✅ 正确答案：{_correct_display}</span></div>',
                        unsafe_allow_html=True,
                    )
                    
                    # 解析
                    _wexplanation = _wq.get("explanation", "")
                    if _wexplanation:
                        st.markdown(_wexplanation)
                    
                    _wcat = _wq.get("category", "") or infer_category(_wq.get("source_file", ""))
                    if _wcat:
                        st.markdown(f"**知识板块**：{_wcat}")
                    
                    _wstats = _get_cached_qstats(_wqid)
                    st.caption(f"📊 答题统计：答对 {_wstats['correct_count']} 次 / 答错 {_wstats['wrong_count']} 次")
        
        st.markdown("---")
        pct = correct_count / total_q * 100
        if pct >= 80:
            st.balloons()
            st.success(f"🎉 **错题复习完成！** 正确率: {pct:.1f}%")
        else:
            st.info(f"📖 **错题复习完成！** 正确率: {pct:.1f}%。继续加油！")

        # 操作按钮
        op_col1, op_col2 = st.columns(2)
        if op_col1.button("🔄 重新组卷", key="wb_regenerate_btn", use_container_width=True, type="primary"):
            st.session_state.wb_regenerate = True
            st.rerun()
        if op_col2.button("🗑️ 清空错题", key="wb_clear_btn", use_container_width=True):
            st.session_state.wb_confirm_clear = True

    # 清空确认
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


def _save_wrongbook_draft(auto_save: bool = False):
    """保存错题练习草稿
    
    auto_save=True: 后台静默保存，不显示提示
    """
    draft_id = st.session_state.get("wb_session_id", str(uuid.uuid4()))
    if "wb_session_id" not in st.session_state:
        st.session_state.wb_session_id = draft_id
    save_draft("wrongbook", draft_id, {
        "questions": st.session_state.wb_questions,
        "current": st.session_state.wb_current,
        "answers": st.session_state.wb_answers,
        "marked": list(st.session_state.wb_marked),
        "uncertain": list(st.session_state.wb_uncertain),
        "wrong_counts": st.session_state.wb_wrong_counts,
    })
    if not auto_save:
        st.session_state.wb_draft_saved = True


def _submit_wrongbook():
    """统一提交所有错题答案（批量 I/O 优化）"""
    wq = st.session_state.wb_questions
    answers = st.session_state.wb_answers
    session_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()

    # 1. 纯计算所有结果（无 I/O）
    results = {}
    wrong_qids = []
    correct_qids = []
    stats_updates = []
    uncertain_map = {}
    answer_records = []

    for q in wq:
        qid = q["id"]
        user_ans = answers.get(qid, "")
        is_correct = check_answer(q["type"], user_ans, q["answer"])
        is_uncertain = qid in st.session_state.get("wb_uncertain", set())

        results[qid] = {"correct": is_correct, "user_answer": user_ans}

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
            "mode": "wrongbook",
            "session_id": session_id,
            "is_uncertain": is_uncertain,
            "timestamp": now,
        })

    # 2. 批量 I/O：统计 + 错题本（1 次读 + 1 次写）
    batch_update_wrong_and_stats(wrong_qids, correct_qids, stats_updates, uncertain_map)

    # 3. 批量 I/O：答题过程记录（1 次读 + 1 次写）
    batch_add_answer_records(answer_records)

    st.session_state.wb_results = results
    st.session_state.wb_submitted = True

    # 标记数据已变更，触发首页统计缓存刷新
    st.session_state._data_version = st.session_state.get("_data_version", 0) + 1
    # 清除错题本自身的统计缓存
    st.session_state.pop("wb_stats_cache", None)

    # 保存考试记录到 exam_records.json
    correct_count = sum(1 for v in results.values() if v.get("correct"))
    save_exam_record({
        "type": "wrongbook",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": len(wq),
        "correct": correct_count,
        "accuracy": f"{correct_count/len(wq)*100:.1f}%" if len(wq) > 0 else "0%",
    })

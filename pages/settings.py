"""
配置管理 - 题库管理、系统设置、用户管理

题库分两层（单库多租户）：
  · 公共题库（owner_id = '__public__'）：初始题库，**只有管理员**能导入/清空，
    改动对所有用户立即生效；
  · 我的题库（owner_id = 当前 user_id）：任何用户可自行导入/清空，只影响自己。

用户的可见题集 = 公共题库 ∪ 我的题库。
"""
import streamlit as st
from pathlib import Path
from utils.data_manager import (
    load_config, save_config, load_questions, import_questions, clear_questions,
    count_questions, get_question_count, backup_data,
    load_case_studies, save_case_studies, clear_exam_records, invalidate_rerun_cache,
    EXAM_TYPE_LABELS, DEFAULT_EXAM_TYPE, PUBLIC_OWNER,
)
from utils.account_manager import is_admin, list_users, ROLE_ADMIN
from utils.parser import batch_parse


def show_settings():
    st.markdown("# ⚙️ 配置管理")
    st.markdown("---")

    _is_adm = is_admin(st.session_state.get("_user_id") or "")
    if _is_adm:
        tab1, tab2, tab3 = st.tabs(["📚 题库管理", "⚙️ 系统设置", "👥 用户管理"])
        with tab1:
            _show_tab_questions(is_admin_user=True)
        with tab2:
            _show_tab_config()
        with tab3:
            _show_tab_users()
    else:
        tab1, tab2 = st.tabs(["📚 题库管理", "⚙️ 系统设置"])
        with tab1:
            _show_tab_questions(is_admin_user=False)
        with tab2:
            _show_tab_config()


# ============================
# 题库管理
# ============================

def _show_tab_questions(is_admin_user: bool):
    """题库管理标签页（按角色分区）"""
    st.markdown("### 📚 题库管理")
    st.markdown("")

    visible = len(load_questions())
    public_n = count_questions(owner_id=PUBLIC_OWNER)
    mine_n = count_questions()
    stats = get_question_count()

    if is_admin_user:
        c1, c2, c3 = st.columns(3)
        c1.metric("可见题库", f"{visible} 题")
        c2.metric("公共题库", f"{public_n} 题", help="对所有用户可见，只有管理员能改")
        c3.metric("我的题库", f"{mine_n} 题", help="只有你自己可见")
    else:
        st.markdown(f"**可见题库**: 共 {visible} 题（公共 {public_n} 题 + 我的 {mine_n} 题）")

    if stats["total"] > 0:
        col1, col2, col3 = st.columns(3)
        col1.metric("单选题", stats["single"])
        col2.metric("多选题", stats["multi"])
        col3.metric("判断题", stats["judge"])

    st.markdown("---")

    # ---- 导入目标 ----
    st.markdown("#### 📂 导入目标")
    if is_admin_user:
        _target = st.radio(
            "题目导入到哪个范围",
            ["我的题库（只有自己可见）", "公共题库（所有用户都会看到）"],
            horizontal=True,
            key="import_owner_choice",
            help="公共题库只有管理员能改，改动立即对所有用户生效。",
        )
        import_to_public = _target.startswith("公共")
    else:
        st.caption("导入的题目只会进入 **我的题库**，不影响其他用户。")
        import_to_public = False
    import_owner_id = PUBLIC_OWNER if import_to_public else None

    if import_to_public:
        st.warning("⚠️ 你正在向 **公共题库** 导入，所有用户都会看到这些题目。")
        _public_ack = st.checkbox("我确认导入公共题库", key="ack_public_import")
    else:
        _public_ack = True

    # 目标 exam_type
    exam_options = list(EXAM_TYPE_LABELS.keys())
    exam_labels_display = [EXAM_TYPE_LABELS[k] for k in exam_options]
    default_idx = exam_options.index(DEFAULT_EXAM_TYPE) if DEFAULT_EXAM_TYPE in exam_options else 0
    selected_target = st.selectbox(
        "选择题目归属的题库类型",
        exam_labels_display,
        index=default_idx,
        key="import_exam_target",
        help="新导入的题目将标记为此题库类型",
    )
    target_exam_type = exam_options[exam_labels_display.index(selected_target)]

    st.markdown("---")

    # ---- 导入题库 ----
    st.markdown("#### 📥 导入题库文件")
    st.markdown("从 `exmbase` 目录导入 docx 文件，或上传新的 docx 文件")
    st.caption("导入为**增量更新**：内容相同的题会跳过；改动过的题会按题干相似度对上原题、"
               "**保留原 ID 并更新内容**，因此用户的答题统计与错题历史不会断链。")

    base_dir = Path(__file__).resolve().parent.parent / "exmbase"
    docx_files = sorted(f for f in base_dir.rglob("*.docx") if not f.name.startswith("~$"))

    if docx_files:
        st.markdown(f"**`exmbase` 目录中检测到 {len(docx_files)} 个题库文件：**")
        for f in docx_files:
            size = f.stat().st_size
            st.markdown(f"- {str(f.relative_to(base_dir))} ({size / 1024:.1f} KB)")

        col_i1, col_i2 = st.columns([1, 3])
        if col_i1.button("🚀 批量导入所有文件", use_container_width=True, type="primary",
                         disabled=not _public_ack):
            with st.spinner("正在解析题库文件..."):
                progress_bar = st.progress(0, text="准备解析...")
                log_area = st.empty()

                def progress_cb(current, total, filename, stats):
                    progress_bar.progress(current / total, text=f"[{current}/{total}] 正在解析: {filename}")
                    if stats.get("error"):
                        log_area.markdown(
                            (log_area.markdown or "") + f"\n- ❌ {filename}: 解析失败 - {stats['error']}")
                    else:
                        log_area.markdown(
                            (log_area.markdown or "")
                            + f"\n- ✅ {filename}: {stats['total']}题 (单{stats['single']} 多{stats['multi']} 判{stats['judge']})")

                new_questions, file_stats, case_backgrounds = batch_parse(base_dir, progress_cb)
                for q in new_questions:
                    q["exam_type"] = target_exam_type

                case_studies_to_save = _build_case_studies(new_questions, case_backgrounds, target_exam_type)
                report = _import_and_report(new_questions, case_studies_to_save,
                                            import_owner_id, target_exam_type)

                progress_bar.empty()
                log_area.empty()
                _render_report(report, target_exam_type, import_to_public)
                backup_data()
                st.rerun()

    st.markdown("---")

    # ---- 上传文件导入 ----
    st.markdown("#### 📤 上传 docx 文件")
    uploaded = st.file_uploader(
        "选择docx题库文件", type=["docx"], accept_multiple_files=True, key="uploader",
    )

    if uploaded:
        if st.button("解析并导入上传的文件", use_container_width=True, disabled=not _public_ack):
            with st.spinner("正在解析上传的文件..."):
                import tempfile
                import os

                all_new = []
                for uf in uploaded:
                    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
                        tmp.write(uf.getvalue())
                        tmp_path = tmp.name
                    try:
                        from utils.parser import parse_docx
                        qs = parse_docx(tmp_path)
                        for q in qs:
                            q["source_file"] = f"[上传] {uf.name}"
                        all_new.extend(qs)
                        st.info(f"✅ {uf.name}: 解析 {len(qs)} 题")
                    except Exception as e:
                        st.error(f"❌ {uf.name}: 解析失败 - {e}")
                    finally:
                        os.unlink(tmp_path)

                if all_new:
                    for q in all_new:
                        q["exam_type"] = target_exam_type
                    report = _import_and_report(all_new, [], import_owner_id, target_exam_type)
                    _render_report(report, target_exam_type, import_to_public)
                    backup_data()
                    st.rerun()

    st.markdown("---")

    # ---- 题库管理操作 ----
    st.markdown("#### 🗑️ 题库管理操作")
    current_exam = st.session_state.get("exam_type", DEFAULT_EXAM_TYPE)
    col_d1, col_d2 = st.columns(2)

    if col_d1.button("🔄 刷新题库缓存", use_container_width=True):
        st.session_state.questions = load_questions()
        st.success(f"✅ 已刷新，当前可见题库 {len(st.session_state.questions)} 题")
        st.rerun()

    if col_d2.button("🧹 清空答题记录", use_container_width=True,
                     disabled=(visible == 0),
                     help=f"仅清空「{EXAM_TYPE_LABELS.get(current_exam, current_exam)}」下你自己的答题记录，"
                          f"保留题目，其他题库不受影响。"):
        st.session_state.confirm_clear_records = current_exam

    st.markdown("")
    _show_clear_questions_block(is_admin_user, mine_n, public_n)

    # 清空答题记录确认
    if st.session_state.get("confirm_clear_records"):
        target_exam = st.session_state.confirm_clear_records
        target_label = EXAM_TYPE_LABELS.get(target_exam, target_exam)
        st.error(f"⚠️ 确认清空「{target_label}」下你自己的所有答题记录吗？")
        st.markdown("**将被清除的数据（保留题目）：**")
        st.markdown("- 答题记录（answer_records）")
        st.markdown("- 题目统计（question_stats，正确/错误次数等）")
        st.markdown("- 错题本（wrong_questions）")
        st.markdown("- 考试记录（exam_records）")
        st.markdown("- 模拟考试记录（mock_exam_records）")
        st.markdown("- 学习记录（study_records）")
        st.markdown("- 答题草稿（drafts）")
        st.markdown("**只影响你自己的数据，其他用户与题库本身都不受影响。**")

        cr1, cr2 = st.columns(2)
        if cr1.button("✅ 确认清空答题记录", use_container_width=True):
            result = clear_exam_records(target_exam)
            total_cleared = sum(result.values())
            invalidate_rerun_cache()
            st.session_state.questions = load_questions()
            st.session_state._data_version = st.session_state.get("_data_version", 0) + 1
            st.session_state.confirm_clear_records = False
            st.success(f"✅ 已清空「{target_label}」下你的 {total_cleared} 条答题记录（题目保留）")
            st.rerun()
        if cr2.button("❌ 取消", use_container_width=True):
            st.session_state.confirm_clear_records = False
            st.rerun()


def _build_case_studies(new_questions, case_backgrounds, target_exam_type):
    """把解析出的案例背景转成 case_studies 记录，并回填子题的 case_study_id"""
    case_studies_to_save = []
    for cbg in case_backgrounds:
        sub_count = 0
        for q in new_questions:
            if (q["source_file"] == cbg["source_file"]
                    and cbg["start_num"] < q.get("index", q.get("index_num", 0)) <= cbg["end_num"]):
                q["case_study_id"] = cbg["case_id"]
                sub_count += 1
        case_studies_to_save.append({
            "case_id": cbg["case_id"],
            "title": cbg["title"],
            "background_id": "",
            "question_count": sub_count,
            "exam_type": target_exam_type,
        })
    return case_studies_to_save


def _import_and_report(questions, case_studies_to_save, owner_id, target_exam_type):
    """执行导入：先落案例背景，再 upsert 题目；返回导入报告"""
    if case_studies_to_save:
        existing_cs = {cs["id"] for cs in load_case_studies()}
        new_cs = [cs for cs in case_studies_to_save if cs["case_id"] not in existing_cs]
        if new_cs:
            save_case_studies(new_cs, owner_id=owner_id)
    return import_questions(questions, owner_id=owner_id, mode="append", exam_type=target_exam_type)


def _render_report(report, target_exam_type, import_to_public):
    scope = "公共题库" if import_to_public else "我的题库"
    st.success(
        f"✅ 导入完成（{scope}）：新增 **{report['added']}** 题，"
        f"更新 **{report['updated']}** 题，未变 {report['unchanged']} 题，"
        f"跳过重复 {report['skipped']} 题"
    )
    logs = report.get("log") or []
    if logs:
        with st.expander(f"导入明细（{len(logs)} 条）"):
            for line in logs[:50]:
                st.markdown(line)
            if len(logs) > 50:
                st.markdown(f"... 还有 {len(logs) - 50} 条")


def _show_clear_questions_block(is_admin_user: bool, mine_n: int, public_n: int):
    """清空题库操作：普通用户只清自己的；管理员可选清公共题库"""
    if not is_admin_user:
        st.caption(f"清空只作用于 **我的题库**（当前 {mine_n} 题），公共题库不受影响。")
        if st.button("🗑️ 清空我的题库", use_container_width=True, disabled=(mine_n == 0)):
            st.session_state.confirm_clear_questions = "mine"
        target_label = "我的题库"
        owner_id = None
    else:
        st.caption(f"公共题库当前 {public_n} 题；我的题库当前 {mine_n} 题。")
        cc0, cc1 = st.columns(2)
        if cc0.button("🗑️ 清空我的题库", use_container_width=True, disabled=(mine_n == 0)):
            st.session_state.confirm_clear_questions = "mine"
        if cc1.button("⚠️ 清空公共题库", use_container_width=True,
                      disabled=(public_n == 0),
                      help="会影响所有用户，请谨慎操作。"):
            st.session_state.confirm_clear_questions = "public"
        target_label = "公共题库" if st.session_state.get("confirm_clear_questions") == "public" else "我的题库"
        owner_id = PUBLIC_OWNER if st.session_state.get("confirm_clear_questions") == "public" else None

    if st.session_state.get("confirm_clear_questions"):
        is_public = st.session_state.get("confirm_clear_questions") == "public"
        if is_public:
            st.error("⚠️⚠️ 确认清空 **公共题库** 吗？所有用户都会立刻看不到这些题目，"
                     "且此操作不可恢复！（用户的答题统计与错题记录会保留，不会丢失）")
        else:
            st.error("⚠️ 确认清空 **我的题库** 吗？此操作不可恢复！"
                     "（公共题库与你的答题记录都会保留）")
        cc1, cc2 = st.columns(2)
        if cc1.button("✅ 确认清空", type="primary", use_container_width=True):
            n = clear_questions(owner_id=owner_id)
            st.session_state.questions = load_questions()
            st.session_state._data_version = st.session_state.get("_data_version", 0) + 1
            st.session_state.confirm_clear_questions = False
            st.success(f"✅ 已清空{target_label}的 {n} 道题")
            st.rerun()
        if cc2.button("❌ 取消", use_container_width=True):
            st.session_state.confirm_clear_questions = False
            st.rerun()


# ============================
# 用户管理（管理员）
# ============================

def _show_tab_users():
    st.markdown("### 👥 用户管理")
    users = list_users()
    st.markdown(f"共 **{len(users)}** 个用户")
    st.caption("账号与设备身份存放在同一个数据库里（users / user_devices 表）。")

    rows = []
    for u in users:
        rows.append({
            "用户ID": u.get("user_id") or "",
            "用户名": u.get("username") or "（访客）",
            "角色": "管理员" if u.get("role") == ROLE_ADMIN else "普通用户",
            "绑定设备数": u.get("device_count", 0),
            "创建时间": (u.get("created_at") or "")[:19],
            "最后登录": (u.get("last_login") or "")[:19],
        })
    if rows:
        st.dataframe(rows, use_container_width=True)


# ============================
# 系统设置
# ============================

def _show_tab_config():
    """系统设置标签页（配置按用户隔离，改的是你自己的设置）"""
    st.markdown("### ⚙️ 系统设置")
    st.caption("以下配置保存在你自己的用户配置里，不影响其他用户。")
    config = load_config()

    st.markdown("---")
    st.markdown("**专项训练设置**")
    st.markdown("专项训练固定每轮出 **60 题**（30 单选 + 20 多选 + 10 判断），可在此调整题数配置。")

    spec_per_round = st.number_input(
        "每轮专项训练总数", min_value=10, max_value=200, value=config.get("spec_per_round", 60),
        help="专项训练每轮抽取的总题数", key="cfg_spec_total")
    spec_single = st.number_input(
        "其中单选题数", min_value=0, max_value=100, value=config.get("spec_single_count", 30),
        key="cfg_spec_single")
    spec_multi = st.number_input(
        "其中多选题数", min_value=0, max_value=100, value=config.get("spec_multi_count", 20),
        key="cfg_spec_multi")
    spec_judge = st.number_input(
        "其中判断题数", min_value=0, max_value=100, value=config.get("spec_judge_count", 10),
        key="cfg_spec_judge")

    st.markdown("---")
    st.markdown("**模拟考试设置**")
    exam_time = st.number_input(
        "考试时间（分钟）", min_value=30, max_value=180, value=config["exam_time_minutes"],
        key="cfg_exam_time")
    exam_single = st.number_input(
        "单选题数", min_value=0, max_value=100, value=config["exam_single_count"], key="cfg_exam_single")
    exam_multi = st.number_input(
        "多选题数", min_value=0, max_value=100, value=config["exam_multi_count"], key="cfg_exam_multi")
    exam_judge = st.number_input(
        "判断题数", min_value=0, max_value=100, value=config["exam_judge_count"], key="cfg_exam_judge")

    st.markdown("---")
    st.markdown("**错题本设置**")
    wrong_count = st.number_input(
        "每次提取错题数", min_value=10, max_value=200, value=config["wrongbook_extract_count"],
        help="从错题库中优先提取答错次数最多的N道题", key="cfg_wrong_count")

    st.markdown("---")
    st.markdown("**遗忘预警设置**")
    retention_threshold = st.number_input(
        "遗忘预警阈值（天）", min_value=1, max_value=30,
        value=config.get("retention_days_threshold", 5),
        help="距上次答对超过此天数后，触发遗忘预警标签，提示需要复习",
        key="cfg_retention_threshold")

    st.markdown("---")

    if st.button("💾 保存设置", use_container_width=True, type="primary"):
        config.update({
            "spec_per_round": spec_per_round,
            "spec_single_count": spec_single,
            "spec_multi_count": spec_multi,
            "spec_judge_count": spec_judge,
            "exam_time_minutes": exam_time,
            "exam_single_count": exam_single,
            "exam_multi_count": exam_multi,
            "exam_judge_count": exam_judge,
            "wrongbook_extract_count": wrong_count,
            "retention_days_threshold": retention_threshold,
        })
        save_config(config)
        st.session_state.config = config
        st.success("✅ 设置已保存！")

    st.markdown("---")
    st.markdown("**数据备份**")
    if st.button("📦 立即备份所有数据", use_container_width=True):
        ts = backup_data()
        st.success(f"✅ 数据已备份到 data/backup/ 目录 (时间戳: {ts})")

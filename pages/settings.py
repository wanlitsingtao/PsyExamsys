"""
配置管理 - 题库管理、系统设置
"""
import streamlit as st
from pathlib import Path
from utils.data_manager import (
    load_config, save_config, load_questions, save_questions,
    dedup_import, get_question_count, backup_data,
    load_case_studies, save_case_studies,
    EXAM_TYPE_LABELS, DEFAULT_EXAM_TYPE,
)
from utils.parser import batch_parse


def show_settings():
    st.markdown("# ⚙️ 配置管理")
    st.markdown("---")

    tab1, tab2 = st.tabs(["📚 题库管理", "⚙️ 系统设置"])

    with tab1:
        _show_tab_questions()
    with tab2:
        _show_tab_config()


def _show_tab_questions():
    """题库管理标签页"""
    st.markdown("### 📚 题库管理")
    st.markdown("")

    # 当前题库统计
    questions = st.session_state.questions
    stats = get_question_count()

    st.markdown(f"**当前题库**: 共 {stats['total']} 题")
    if stats["total"] > 0:
        col1, col2, col3 = st.columns(3)
        col1.metric("单选题", stats["single"])
        col2.metric("多选题", stats["multi"])
        col3.metric("判断题", stats["judge"])

    st.markdown("---")

    # 目标题库选择（导入时使用）
    st.markdown("#### 📂 导入目标题库")
    exam_options = list(EXAM_TYPE_LABELS.keys())
    exam_labels_display = [EXAM_TYPE_LABELS[k] for k in exam_options]
    default_idx = exam_options.index(DEFAULT_EXAM_TYPE) if DEFAULT_EXAM_TYPE in exam_options else 0
    selected_target = st.selectbox(
        "选择题目导入到哪个题库",
        exam_labels_display,
        index=default_idx,
        key="import_exam_target",
        help="新导入的题目将标记为此题库类型"
    )
    target_exam_type = exam_options[exam_labels_display.index(selected_target)]

    st.markdown("---")

    # 导入题库
    st.markdown("#### 📥 导入题库文件")
    st.markdown("从 `exmbase` 目录导入 docx 文件，或上传新的 docx 文件")

    # 方法1：批量导入exmbase目录（递归扫描子目录）
    base_dir = Path(__file__).resolve().parent.parent / "exmbase"
    docx_files = sorted(f for f in base_dir.rglob("*.docx") if not f.name.startswith("~$"))

    if docx_files:
        st.markdown(f"**`exmbase` 目录中检测到 {len(docx_files)} 个题库文件：**")
        for f in docx_files:
            size = f.stat().st_size
            size_str = f"{size / 1024:.1f} KB"
            rel_path = str(f.relative_to(base_dir))
            st.markdown(f"- {rel_path} ({size_str})")

        col_i1, col_i2 = st.columns([1, 3])
        if col_i1.button("🚀 批量导入所有文件", use_container_width=True, type="primary"):
            with st.spinner("正在解析题库文件..."):
                progress_bar = st.progress(0, text="准备解析...")
                log_area = st.empty()

                def progress_cb(current, total, filename, stats):
                    progress_bar.progress(current / total,
                                          text=f"[{current}/{total}] 正在解析: {filename}")
                    if stats.get("error"):
                        log_area.markdown(
                            log_area.markdown or ""
                            + f"\n- ❌ {filename}: 解析失败 - {stats['error']}"
                        )
                    else:
                        log_area.markdown(
                            (log_area.markdown or "")
                            + f"\n- ✅ {filename}: {stats['total']}题 (单{stats['single']} 多{stats['multi']} 判{stats['judge']})"
                        )

                new_questions, file_stats, case_backgrounds = batch_parse(base_dir, progress_cb)

                # 标记目标题库
                for q in new_questions:
                    q["exam_type"] = target_exam_type

                # --- 处理案例题：关联 case_study_id ---
                case_studies_to_save = []
                for cbg in case_backgrounds:
                    # 查找该案例范围的子题，设置 case_study_id
                    sub_count = 0
                    for q in new_questions:
                        if (q["source_file"] == cbg["source_file"]
                                and cbg["start_num"] < q["index"] <= cbg["end_num"]):
                            q["case_study_id"] = cbg["case_id"]
                            sub_count += 1
                    case_studies_to_save.append({
                        "case_id": cbg["case_id"],
                        "title": cbg["title"],
                        "background_id": "",
                        "question_count": sub_count,
                        "exam_type": target_exam_type,
                    })

                # 合并已有案例（避免覆盖）
                if case_studies_to_save:
                    existing_cs = {cs["id"] for cs in load_case_studies()}
                    new_cs = [cs for cs in case_studies_to_save if cs["case_id"] not in existing_cs]
                    if new_cs:
                        save_case_studies(new_cs)

                # 去重合并
                merged, added, skipped, logs = dedup_import(
                    load_questions(), new_questions
                )

                save_questions(merged)
                st.session_state.questions = merged
                st.session_state._data_version = st.session_state.get("_data_version", 0) + 1

                progress_bar.empty()
                log_area.empty()

                st.success(f"✅ 导入完成！新增 {added} 题，跳过 {skipped} 题（重复）")

                if logs:
                    with st.expander(f"⏭️ 跳过的重复题 ({len(logs)}条)"):
                        for log in logs[:20]:
                            st.markdown(log)
                        if len(logs) > 20:
                            st.markdown(f"... 还有 {len(logs) - 20} 条")

                # 备份
                backup_data()
                st.rerun()

    st.markdown("---")

    # 方法2：上传文件
    st.markdown("#### 📤 上传 docx 文件")
    uploaded = st.file_uploader(
        "选择docx题库文件",
        type=["docx"],
        accept_multiple_files=True,
        key="uploader",
    )

    if uploaded:
        if st.button("解析并导入上传的文件", use_container_width=True):
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
                    # 标记目标题库
                    for q in all_new:
                        q["exam_type"] = target_exam_type

                    existing = load_questions()
                    merged, added, skipped, logs = dedup_import(existing, all_new)
                    save_questions(merged)
                    st.session_state.questions = merged
                    st.session_state._data_version = st.session_state.get("_data_version", 0) + 1

                    st.success(f"✅ 上传导入完成！新增 {added} 题，跳过 {skipped} 题（重复）")
                    backup_data()
                    st.rerun()

    st.markdown("---")

    # 题库管理操作
    st.markdown("#### 🗑️ 题库管理操作")
    col_d1, col_d2, col_d3 = st.columns(3)

    if col_d1.button("🔄 刷新题库缓存", use_container_width=True):
        questions = load_questions()
        st.session_state.questions = questions
        st.success(f"✅ 已刷新，当前题库 {len(questions)} 题")
        st.rerun()

    if col_d3.button("⚠️ 清空题库", use_container_width=True, disabled=(len(questions) == 0)):
        st.session_state.confirm_clear_questions = True

    if st.session_state.get("confirm_clear_questions"):
        st.error("⚠️⚠️ 确认清空整个题库吗？此操作不可恢复！")
        cc1, cc2 = st.columns(2)
        if cc1.button("✅ 确认清空", use_container_width=True):
            save_questions([])
            st.session_state.questions = []
            st.session_state._data_version = st.session_state.get("_data_version", 0) + 1
            st.session_state.confirm_clear_questions = False
            st.success("✅ 题库已清空")
            st.rerun()
        if cc2.button("❌ 取消", use_container_width=True):
            st.session_state.confirm_clear_questions = False
            st.rerun()


def _show_tab_config():
    """系统设置标签页"""
    st.markdown("### ⚙️ 系统设置")
    config = load_config()

    st.markdown("---")
    st.markdown("**专项训练设置**")

    st.markdown("专项训练固定每轮出 **60 题**（30 单选 + 20 多选 + 10 判断），可在此调整题数配置。")

    spec_per_round = st.number_input(
        "每轮专项训练总数",
        min_value=10, max_value=200, value=config.get("spec_per_round", 60),
        help="专项训练每轮抽取的总题数",
        key="cfg_spec_total",
    )
    spec_single = st.number_input(
        "其中单选题数",
        min_value=0, max_value=100, value=config.get("spec_single_count", 30),
        key="cfg_spec_single",
    )
    spec_multi = st.number_input(
        "其中多选题数",
        min_value=0, max_value=100, value=config.get("spec_multi_count", 20),
        key="cfg_spec_multi",
    )
    spec_judge = st.number_input(
        "其中判断题数",
        min_value=0, max_value=100, value=config.get("spec_judge_count", 10),
        key="cfg_spec_judge",
    )

    st.markdown("---")
    st.markdown("**模拟考试设置**")

    exam_time = st.number_input(
        "考试时间（分钟）",
        min_value=30, max_value=180, value=config["exam_time_minutes"],
        key="cfg_exam_time",
    )
    exam_single = st.number_input(
        "单选题数",
        min_value=0, max_value=100, value=config["exam_single_count"],
        key="cfg_exam_single",
    )
    exam_multi = st.number_input(
        "多选题数",
        min_value=0, max_value=100, value=config["exam_multi_count"],
        key="cfg_exam_multi",
    )
    exam_judge = st.number_input(
        "判断题数",
        min_value=0, max_value=100, value=config["exam_judge_count"],
        key="cfg_exam_judge",
    )

    st.markdown("---")
    st.markdown("**错题本设置**")

    wrong_count = st.number_input(
        "每次提取错题数",
        min_value=10, max_value=200, value=config["wrongbook_extract_count"],
        help="从错题库中优先提取答错次数最多的N道题",
        key="cfg_wrong_count",
    )

    st.markdown("---")
    st.markdown("**遗忘预警设置**")

    retention_threshold = st.number_input(
        "遗忘预警阈值（天）",
        min_value=1, max_value=30, value=config.get("retention_days_threshold", 5),
        help="距上次答对超过此天数后，触发遗忘预警标签，提示需要复习",
        key="cfg_retention_threshold",
    )

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

    # 数据备份
    st.markdown("---")
    st.markdown("**数据备份**")
    if st.button("📦 立即备份所有数据", use_container_width=True):
        ts = backup_data()
        st.success(f"✅ 数据已备份到 data/backup/ 目录 (时间戳: {ts})")




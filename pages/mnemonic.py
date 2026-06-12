"""
助记助学 - 数字记忆表 + 人名速查
将题库中涉及数字答案和人名答案的题目整理为速查表格，方便考前冲刺记忆。
"""
import re
import streamlit as st
from utils.data_manager import load_questions, load_config


def _filter_number_questions(questions):
    """
    从题库中筛选涉及数字答案的题目。

    筛选条件：
    1. 题目文本包含数量/数字关键词
    2. 至少2个选项含有数字
    3. 答案中含数字
    """
    quantity_keywords = [
        '条目数', '条目', '几岁', '年龄', '几分', '几级', '几类',
        '几个', '几次', '多少', '几年', '几月', '几周', '几天',
        '量表有', '量表共', '包括', '维度', '因素', '项目', '题数',
        '划分为', '分为', '阶段', '过程', '比例', '百分',
        '时长', '分钟', '小时', '天', '周', '月', '年',
        '标准', '常模', '版本', '频率', '临界值', '适宜', '通常',
        # 百分数/小数/分数 题型
        '率',        # 患病率/遗传率/发生率/比率
        '效应量',
        '约为',      # 脑重约为、视敏度约为
        '约占',      # 约占样本
    ]

    results = []
    for q in questions:
        qtext = q.get("question", "")
        opts = q.get("options", {})
        ans_key = q.get("answer", "")
        q_type = q.get("type", "single")

        if not opts or not ans_key:
            continue

        # 处理多选题答案（answer="AB" → 拼接 A/B 选项值）
        if q_type == "multi" and len(ans_key) > 1:
            ans_texts = [str(opts.get(k, "")) for k in ans_key if k in opts]
            ans_text = "; ".join(ans_texts) if ans_texts else ""
        else:
            ans_text = str(opts.get(ans_key, ""))

        # 1. 问题含数量关键词 — 或答案/选项自动放行
        has_kw = any(kw in qtext for kw in quantity_keywords)
        is_pct_frac_dec = bool(re.search(r'%|％|\d+/\d+|\d+\.\d+', ans_text))
        is_age = '岁' in ans_text
        # 选项含数字范围（如 8~14分、15-21分、50～59分）自动放行
        score_range_opts = sum(
            1 for v in opts.values()
            if re.search(r'\d+\s*[~\-～—]\s*\d+', str(v))
        )
        is_score_range = score_range_opts >= 2
        if not has_kw and not is_pct_frac_dec and not is_age and not is_score_range:
            continue

        # 2. 至少2个选项含数字
        digit_count = sum(
            1 for v in opts.values()
            if re.search(r'\d+|[一二三四五六七八九十百]+', str(v))
        )
        if digit_count < 2:
            continue

        # 3. 答案中含数字（排除书籍/标准名称等伪数字答案）
        if "《" in ans_text:
            continue
        if not re.search(r'\d+|[一二三四五六七八九十百]+', ans_text):
            continue

        results.append({
            "id": q.get("id", ""),
            "question": qtext,
            "answer": ans_text,
            "category": q.get("category", ""),
            "type": q.get("type", "single"),
        })

    return results


def _filter_person_questions(questions):
    """
    从题库中筛选人名相关题目。

    筛选条件：
    1. 所有选项都是 2-4 字纯中文（不含数字/符号/英文）
    2. 题干含"谁提出的/谁创立的/编制者是"等人物关联关键词
    """
    who_keywords = [
        '提出者', '创始人', '编制者', '创立者', '首创者',
        '的心理学家', '的创始人是', '的教育家', '的思想家',
        '的代表人物', '的倡导者', '的发现者',
        # 边缘 case：问某概念的来源/出处
        '出自（', '来自（',
        # "明确这一概念的是" 等
        '这一概念',
        # "这是（  ）的观点"
        '的观点',
        # 缺漏 case：X 提出的 / X 提出了 Y / X 编制16PF
        '提出的概念', '提出的', '提出了', '编制16PF',
    ]

    # 当题干已明确包含某个心理学家的名字时，问的一般是"WHAT"不是"WHO"
    # 例如："弗洛伊德提出的性心理发展阶段包括" → 答案不是人名
    _known_psych_names_in_question = [
        '弗洛伊德', '荣格', '阿德勒', '马斯洛', '罗杰斯', '华生',
        '斯金纳', '班杜拉', '皮亚杰', '维果茨基', '维果斯基',
        '埃里克森', '艾里克森', '巴甫洛夫', '塞利格曼', '卡特尔',
        '艾森克', '奥尔波特', '希波克拉底', '格罗斯', '斯蒂文',
        '斯蒂文·芬克', '布朗芬布伦纳', '霍尔', '斯科特', '安德森',
        '马西亚', '里斯曼', '威廉森', '本杰明', '库尔特', '贝克',
        '埃利斯', '梅肯鲍姆', '罗杰斯',
    ]

    # 排除词：选项为概念词（非人名）时，即使命题含关键词也不收录
    exclude_options = {
        '正确', '错误',  # 判断题
    }

    # 概念后缀词：选项以这些词结尾时不是人名（如 准备阶段/介绍阶段）
    concept_suffixes = (
        '阶段', '类型', '特质', '原则', '能力', '关系', '倾向',
        '过程', '因素', '系统', '障碍', '技术', '方式', '反应',
        '功能', '品质', '发展', '冲突', '作用', '方法', '距离',
    )

    results = []
    for q in questions:
        qtext = q.get("question", "")
        opts = q.get("options", {})
        ans_key = q.get("answer", "")

        if not opts or not ans_key:
            continue

        q_type = q.get("type", "single")

        # 处理多选题答案（answer="AB" → 拼接 A/B 选项值）
        if q_type == "multi" and len(ans_key) > 1:
            ans_texts = [str(opts.get(k, "")) for k in ans_key if k in opts]
            ans_text = "; ".join(ans_texts) if ans_texts else ""
        else:
            ans_text = str(opts.get(ans_key, ""))

        opt_values = [str(v).strip() for v in opts.values()]

        # 所有选项都是 2-4 字纯中文
        is_zh = re.compile(r'^[\u4e00-\u9fa5]{2,4}$')
        if not all(is_zh.match(v) for v in opt_values):
            continue

        # 排除判断题（正确/错误）
        if any(v in exclude_options for v in opt_values):
            continue

        # 排除选项以概念后缀结尾的题（如 准备阶段/介绍阶段）
        if any(v.endswith(concept_suffixes) for v in opt_values):
            continue

        # 排除"X提出的Y是"型——题干已含人名，答案不是人（是概念/阶段/特质）
        if any(kw in qtext for kw in ['提出的', '提出了', '提出 ']):
            if any(name in qtext for name in _known_psych_names_in_question):
                continue

        # 题干含 WHO 关键词才收录
        has_who = any(kw in qtext for kw in who_keywords)
        if not has_who:
            continue

        results.append({
            "id": q.get("id", ""),
            "question": qtext,
            "answer": ans_text,
            "category": q.get("category", ""),
            "type": q.get("type", "single"),
        })

    return results


def _clean_question(text):
    """清理题目文本中的填空括号"""
    return text.replace("（    ）", "（）").replace("（   ）", "（）").strip()


def _render_items(items, show_answer, search=""):
    """通用的按分类分组渲染函数，返回实际展示数"""
    from collections import Counter
    cat_counts = Counter(item["category"] for item in items)

    if not items:
        return 0

    displayed = 0
    sorted_cats = sorted(cat_counts.items(), key=lambda x: -x[1])
    if search.strip():
        sorted_cats = [(k, v) for k, v in sorted_cats]

    for cat, _ in sorted_cats:
        cat_items = [i for i in items if i["category"] == cat]
        if not cat_items:
            continue

        # 搜索过滤
        if search.strip():
            kw = search.strip().lower()
            cat_items = [
                i for i in cat_items
                if kw in i["question"].lower() or kw in i["answer"].lower()
            ]
            if not cat_items:
                continue

        # 展开状态管理
        all_expanded = st.session_state.get("mnemonic_all_expanded", True)
        if "mnemonic_expanded" not in st.session_state:
            st.session_state.mnemonic_expanded = {}
        expanded = st.session_state.mnemonic_expanded.get(cat, all_expanded)

        with st.expander(
            f"📂 {cat}（{len(cat_items)} 题）",
            expanded=expanded
        ):
            st.session_state.mnemonic_expanded[cat] = True

            md_lines = ["| # | 知识点 | 答案 |", "|---|--------|------|"]
            for idx, item in enumerate(cat_items, 1):
                q_clean = _clean_question(item["question"])
                if show_answer:
                    answer_display = f'<b style="color:#FF4B4B;">{item["answer"]}</b>'
                else:
                    answer_display = '<span style="color:#aaa;">???</span>'
                q_clean = q_clean.replace("|", "\\|")
                md_lines.append(f"| {idx} | {q_clean} | {answer_display} |")

            st.markdown("\n".join(md_lines), unsafe_allow_html=True)
            displayed += len(cat_items)

    # 搜索无结果提示
    if search.strip() and displayed == 0:
        st.warning(f"未找到包含「{search.strip()}」的题目")

    return displayed


def show_mnemonic():
    """助记助学主页面 — 数字相关 / 人名相关 双 Tab"""
    st.title("🧠 助记助学")
    st.markdown("将题库中涉及**数字答案**和**人名答案**的题目整理为速查表格，便于考前集中记忆。")

    # 加载题库
    exam_type = st.session_state.get("exam_type", "")
    questions = [
        q for q in load_questions()
        if q.get("exam_type") == exam_type
    ]

    # 预筛选
    number_items = _filter_number_questions(questions)
    person_items = _filter_person_questions(questions)

    # ---- 显示模式（全局） ----
    mode_col1, mode_col2, _ = st.columns([1, 1, 2])
    with mode_col1:
        show_answer = st.checkbox("显示答案", value=True)
    with mode_col2:
        btn_label = "全部展开" if not st.session_state.get("mnemonic_all_expanded", False) else "全部折叠"
        if st.button(btn_label, use_container_width=True):
            st.session_state.mnemonic_all_expanded = (
                not st.session_state.get("mnemonic_all_expanded", False)
            )
            st.rerun()

    # ---- 双 Tab ----
    tab1, tab2 = st.tabs([
        f"🔢 数字相关（{len(number_items)}）",
        f"👤 人名相关（{len(person_items)}）",
    ])

    # ========== Tab 1: 数字相关 ==========
    with tab1:
        if len(number_items) == 0:
            st.info("当前题库未检测到数字记忆题，请确认题库已导入。")
        else:
            from collections import Counter
            cat_counts = Counter(item["category"] for item in number_items)
            search = st.text_input(
                "🔍 搜索数字题", placeholder="例如：量表、条目、年龄...",
                label_visibility="collapsed", key="search_number"
            )

            st.caption(
                f"当前题库共 {len(number_items)} 道数字记忆题，覆盖 {len(cat_counts)} 个知识板块"
            )
            st.markdown("---")

            _render_items(number_items, show_answer, search)

            st.markdown("---")
            st.caption(
                f"共 {len(number_items)} 题 · 覆盖 {len(cat_counts)} 个板块"
            )

    # ========== Tab 2: 人名相关 ==========
    with tab2:
        if len(person_items) == 0:
            st.info("当前题库未检测到人名记忆题。")
        else:
            from collections import Counter
            cat_counts = Counter(item["category"] for item in person_items)
            search = st.text_input(
                "🔍 搜索人名题", placeholder="例如：弗洛伊德、量表编制者...",
                label_visibility="collapsed", key="search_person"
            )

            st.caption(
                f"当前题库共 {len(person_items)} 道人名记忆题，覆盖 {len(cat_counts)} 个知识板块"
            )
            st.markdown("---")

            _render_items(person_items, show_answer, search)

            st.markdown("---")
            st.caption(
                f"共 {len(person_items)} 题 · 覆盖 {len(cat_counts)} 个板块"
            )

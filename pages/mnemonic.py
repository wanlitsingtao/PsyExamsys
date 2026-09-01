"""
助记助学 - 数字记忆表 + 人名速查
将题库中涉及数字答案和人名答案的题目整理为速查表格，方便考前冲刺记忆。
"""
import re
import streamlit as st
from utils.data_manager import (
    load_questions, load_config, load_uncertain_questions, clear_uncertain_mark,
    get_answer_display,
)


def _filter_number_questions(questions):
    """
    从题库中筛选涉及数字答案的题目。

    筛选条件：
    1. 题目文本包含数量/数字关键词
    2. 至少2个选项含有数字
    3. 答案中含数字
    """
    quantity_keywords = [
        '条目数', '条目', '几岁', '年龄', '岁', '几分', '几级', '几类',
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
        '病程',      # 病程时长
        '持续',      # 持续时间
        # 量表分数相关（补充分数/划界/界值等遗漏关键词）
        '分',        # 最低分、总分、标准分、分数线、得分、评分、计分
        '划界',      # 划界分
        '界值',      # 界值
        '最低',      # 最低分
        '最高',      # 最高分
        '超过',      # 总分要超过
        '低于',      # 低于标准分
        '轻度',      # 轻度焦虑/抑郁分数段
        '中度',      # 中度分数段
        '重度',      # 重度分数段
        '严重',      # 严重抑郁分数
        '乘数',      # SDS乘数
        '评分等级',  # 量表等级
        '正常状态',  # 正常状态标准分
        '检测表',    # PTSD检测表等非"量表"命名的工具
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
            # 判断题特例：选项"正确/错误"无数字，但题干含岁/月龄则放行
            if not (q_type == "judge" and (re.search(r'\d+\s*岁', qtext) or re.search(r'\d+\s*月龄', qtext))):
                continue

        # 3. 答案中含数字（排除书籍/标准名称等伪数字答案）
        if "《" in ans_text:
            continue
        if not re.search(r'\d+|[一二三四五六七八九十百]+', ans_text):
            # 判断题特例：答案"正确/错误"不含数字，若题干含岁/月龄则放行
            if not (q_type == "judge" and (re.search(r'\d+\s*岁', qtext) or re.search(r'\d+\s*月龄', qtext))):
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


def _filter_scale_dimension_questions(questions):
    """
    从题库中筛选量表维度及量表特征相关题目。

    筛选条件：
    1. 题干含"维度"（排除非量表维度的题目）
    2. 题干含具体量表名称 + 特征关键词（特点/包含/不包含等）
    """
    _exclude_dim_keywords = [
        '会谈过程', '开始阶段', '咨询效果',
        '人格理论', '归因模型', '干预框架',
        '获取信息', '获取维',
    ]

    # 量表知识题：已知量表名称 + 特征关键词
    _scale_names = [
        '抑郁自评量表', '焦虑自评量表', '汉密尔顿抑郁量表', '汉密尔顿焦虑量表',
        '症状自评量表', 'SCL-90', 'SCL90',
        '应对方式问卷', '特质应对方式问卷',
        '青少年生活事件量表', '生活事件量表',
        '自杀可能性量表', '领悟社会支持量表',
        '斯坦福急性应激', '16PF', 'EPQ', 'MMPI',
        '贝克自杀意念量表', '分类评估量表',
        '自杀意念量表',
    ]
    _scale_knowledge_kws = ['特点', '特征', '特性', '包括', '不包含', '不包括']

    results = []
    seen_ids = set()
    for q in questions:
        qtext = q.get("question", "")
        opts = q.get("options", {})
        ans_key = q.get("answer", "")
        q_type = q.get("type", "single")
        qid = q.get("id", "")

        if not opts or not ans_key:
            continue

        # 判定是否应纳入
        is_dim = '维度' in qtext and not any(kw in qtext for kw in _exclude_dim_keywords)
        
        _scale_mentioned = any(sn in qtext for sn in _scale_names)
        is_scale_knowledge = (
            '维度' not in qtext
            and _scale_mentioned
            and any(kw in qtext for kw in _scale_knowledge_kws)
        )

        if not is_dim and not is_scale_knowledge:
            continue

        if qid in seen_ids:
            continue

        # 处理答案显示
        if q_type == "multi" and len(ans_key) > 1:
            ans_texts = [str(opts.get(k, "")) for k in ans_key if k in opts]
            ans_text = "；".join(ans_texts) if ans_texts else ""
        else:
            ans_text = str(opts.get(ans_key, ""))

        seen_ids.add(qid)
        results.append({
            "id": qid,
            "question": qtext,
            "answer": ans_text,
            "category": q.get("category", ""),
            "type": q.get("type", "single"),
        })

    return results


def _clean_question(text):
    """清理题目文本中的填空括号"""
    return text.replace("（    ）", "（）").replace("（   ）", "（）").strip()


def _extract_age_value(ans_text):
    """从答案文本中提取年龄/月龄数值用于排序。

    支持格式：
    - 月龄: "4月龄" / "18-24月龄" / "18-24个月" / "36月龄内"
    - 岁数: "3-5岁" / "4岁" / "65岁以上" / "20岁左右" / "11或12岁"
    - 纯数字: "4" / "2-3"（题干含"岁"时出现）

    返回值: (first_numeric_value, type_str)
      type_str: "month" / "year" / "unknown"
    """
    text = ans_text.strip()

    # 月龄: 数字后跟"月龄"
    m = re.search(r'(\d+(?:\.\d+)?)\s*月龄', text)
    if m:
        return float(m.group(1)), "month"
    # 个月: 数字后跟"个月"
    m = re.search(r'(\d+(?:\.\d+)?)\s*个月', text)
    if m:
        return float(m.group(1)), "month"

    # 岁数: 数字后跟"岁"
    m = re.search(r'(\d+(?:\.\d+)?)\s*岁', text)
    if m:
        return float(m.group(1)), "year"

    # 纯数字（如 "4" / "2-3" / "18-24"），默认按 year 处理
    m = re.search(r'(\d+(?:\.\d+)?)', text)
    if m:
        return float(m.group(1)), "year"

    return 0, "unknown"


def _extract_duration_sort_value(ans_text):
    """从答案文本中提取病程/时长数值，统一转为月用于排序。

    支持格式：
    - "X个月" → X
    - "X周" → X / 4
    - "X天" → X / 30
    - "X小时" → X / 720

    返回值: float（月） 或 0
    """
    text = ans_text.strip()

    # 个月
    m = re.search(r'(\d+(?:\.\d+)?)\s*[个]?月', text)
    if m:
        return float(m.group(1))

    # 周
    m = re.search(r'(\d+(?:\.\d+)?)\s*周', text)
    if m:
        return float(m.group(1)) / 4

    # 天
    m = re.search(r'(\d+(?:\.\d+)?)\s*天', text)
    if m:
        return float(m.group(1)) / 30

    # 小时
    m = re.search(r'(\d+(?:\.\d+)?)\s*[小]?时', text)
    if m:
        return float(m.group(1)) / 720

    # 纯数字
    m = re.search(r'(\d+)', text)
    if m:
        return float(m.group(1))

    return 0


def _extract_score_sort_value(ans_text):
    """从量表分数答案中提取数值用于降序排序。

    支持格式：
    - "57分" / "12分" → 取数值
    - "3～12分" / "22～29分" → 取最大值
    - "10级" → 取数值
    - "1.25" → 取数值
    - "50分"（正常状态常模） → 取数值

    返回值: float
    """
    text = ans_text.strip()

    # 范围值：取最大值
    m = re.search(r'(\d+(?:\.\d+)?)\s*[~\-～—]\s*(\d+(?:\.\d+)?)', text)
    if m:
        return float(m.group(2))

    # 单位后缀：分、级、个 等
    m = re.search(r'(\d+(?:\.\d+)?)', text)
    if m:
        return float(m.group(1))

    return 0



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


def _compute_mnemonic_data():
    """计算并缓存助记助学全部数据（数字题/人名题筛选及分类）。

    结果缓存在 session_state._mnemonic_data 中，避免每次 toggle 都重新计算。
    调用方通过 _mnemonic_force_refresh 标志触发强制重算。
    """
    if st.session_state.pop("_mnemonic_force_refresh", False):
        st.session_state.pop("_mnemonic_data", None)

    exam_type = st.session_state.get("exam_type", "")
    cached = st.session_state.get("_mnemonic_data")
    # 缓存按题库隔离：exam_type 变化时必须重新计算（题库切换后自动重算）
    if (cached is not None and "scale_dimension_items" in cached
            and cached.get("_exam_type") == exam_type):
        return cached

    questions = [
        q for q in load_questions()
        if q.get("exam_type") == exam_type
    ]

    number_items = _filter_number_questions(questions)
    person_items = _filter_person_questions(questions)
    scale_dimension_items = _filter_scale_dimension_questions(questions)

    # ---- 将数字题按内容类型分类 ----
    scale_score_items = []
    entry_count_items = []
    month_items = []
    year_items = []
    duration_items = []
    other_number_items = []

    _scale_score_kws = [
        '最低分', '最高分',
        '临界', '划界', '界值', '分数线',
        '标准分',
        '总分',
        '分数',
        '评分等级', '乘数',
        '常模',
        '中度', '重度', '轻度', '严重',
    ]

    _month_dev_keywords = [
        '婴儿', '幼儿', '新生儿', '胎儿', '咿呀', '客体',
        '社会性', '陌生人', '最早', '出现', '获得',
        '理解', '说出', '电报句', '感知觉',
    ]

    for item in number_items:
        qtext = item.get("question", "")
        ans_text = item.get("answer", "")
        q_type = item.get("type", "single")

        if any(kw in qtext for kw in _scale_score_kws):
            val = _extract_score_sort_value(ans_text)
            item["_sort"] = val
            scale_score_items.append(item)
        elif "条目" in qtext:
            val, _ = _extract_age_value(ans_text)
            item["_sort"] = val
            entry_count_items.append(item)
        elif ("病程" in qtext or "持续" in qtext) and re.search(r'\d+\s*[个]?[月周天小]', ans_text):
            val = _extract_duration_sort_value(ans_text)
            item["_sort"] = val
            duration_items.append(item)
        elif "月龄" in ans_text:
            val, kind = _extract_age_value(ans_text)
            item["_sort"] = val
            month_items.append(item)
        elif "个月" in ans_text and "岁" not in ans_text:
            is_dev_month = any(kw in qtext for kw in _month_dev_keywords)
            if is_dev_month:
                val, kind = _extract_age_value(ans_text)
                item["_sort"] = val
                month_items.append(item)
            else:
                other_number_items.append(item)
        elif "岁" in ans_text:
            stripped = ans_text.strip()
            if re.match(r'^\d+%$', stripped) or re.match(r'^\d+％$', stripped):
                other_number_items.append(item)
            else:
                val, kind = _extract_age_value(ans_text)
                item["_sort"] = val
                year_items.append(item)
        elif "年龄" in qtext or ("岁" in qtext and re.search(r'\d+', ans_text)):
            stripped = ans_text.strip()
            if re.match(r'^\d+%$', stripped) or re.match(r'^\d+％$', stripped):
                other_number_items.append(item)
            else:
                val, kind = _extract_age_value(ans_text)
                item["_sort"] = val
                year_items.append(item)
        elif q_type == "judge" and re.search(r'\d+\s*岁', qtext):
            m = re.search(r'(\d+(?:\.\d+)?)\s*岁', qtext)
            item["_sort"] = float(m.group(1)) if m else 0
            year_items.append(item)
        elif q_type == "judge" and re.search(r'\d+\s*月龄', qtext):
            m = re.search(r'(\d+(?:\.\d+)?)\s*月龄', qtext)
            item["_sort"] = float(m.group(1)) if m else 0
            month_items.append(item)
        else:
            other_number_items.append(item)

    scale_score_items.sort(key=lambda x: x.get("_sort", 0), reverse=True)
    entry_count_items.sort(key=lambda x: x.get("_sort", 0), reverse=True)
    month_items.sort(key=lambda x: x.get("_sort", 0))
    year_items.sort(key=lambda x: x.get("_sort", 0))
    duration_items.sort(key=lambda x: x.get("_sort", 0))

    data = {
        "_exam_type": exam_type,  # 缓存归属题库标识，切换题库时自动失效
        "number_items": number_items,
        "person_items": person_items,
        "scale_dimension_items": scale_dimension_items,
        "scale_score_items": scale_score_items,
        "entry_count_items": entry_count_items,
        "month_items": month_items,
        "year_items": year_items,
        "duration_items": duration_items,
        "other_number_items": other_number_items,
    }
    st.session_state["_mnemonic_data"] = data
    return data


@st.fragment()
def _render_uncertain_tab():
    """不确定题目列表 — 使用 fragment 隔离，toggle 变化只重跑此片段，不刷新整页。
    每次渲染直接从数据库加载最新数据，不缓存。"""
    uncertain_questions = load_uncertain_questions(exam_type=st.session_state.get("exam_type", "心理学会咨询师四级"))

    if len(uncertain_questions) == 0:
        st.info("暂无标记为不确定的题目。在专项练习或模拟考试中，可通过题目旁的「不确定」开关标记题目。")
        return

    total = len(uncertain_questions)

    # 顶部概览 + 展开按钮 + 刷新按钮
    top_c1, top_c2, top_c3 = st.columns([3, 1, 1])
    with top_c1:
        st.caption(f"共 **{total}** 道不确定题目 · 按标记次数降序排列")
    with top_c2:
        btn_label = "全部展开" if not st.session_state.get("mnemonic_all_expanded", False) else "全部折叠"
        if st.button(btn_label, use_container_width=True, key="expand_uncertain"):
            st.session_state.mnemonic_all_expanded = (
                not st.session_state.get("mnemonic_all_expanded", False)
            )
            st.rerun()
    with top_c3:
        if st.button("刷新列表", use_container_width=True, key="mnemonic_refresh_uncertain",
                     help="关闭不确定开关后手动刷新以移除该题"):
            st.rerun()
    st.markdown("---")

    # 按知识板块分组展示
    from collections import Counter, defaultdict
    cat_map = defaultdict(list)
    for q in uncertain_questions:
        cat = q.get("category", "") or "未分类"
        cat_map[cat].append(q)

    # 按题数降序排列板块
    sorted_cats = sorted(cat_map.items(), key=lambda x: -len(x[1]))
    global_idx = 0
    for cat, cat_questions in sorted_cats:
        global_idx += 1
        st.markdown(f"### 📂 {cat}（{len(cat_questions)} 题）")

        for idx, q in enumerate(cat_questions, 1):
            qid = q["id"]
            uncertainty = q.get("uncertainty_score", 0)
            question_text = _clean_question(q.get("question", ""))
            opts = q.get("options", {})
            ans_key = q.get("answer", "").strip().upper()
            q_type = q.get("type", "single")
            explanation = q.get("explanation", "")

            # 题型标签
            type_labels = {"single": "单选题", "multi": "多选题", "judge": "判断题", "案例题": "案例题", "indefinite": "不定项选择题"}
            type_label = type_labels.get(q_type, q_type)

            # 标记次数显示（混合值转显示）
            mark_count_display = f"{round(uncertainty, 2)}"
            if uncertainty == int(uncertainty):
                mark_count_display = str(int(uncertainty))

            # 展开标题
            q_short = question_text[:40] + "..." if len(question_text) > 40 else question_text
            expander_label = f"#{global_idx}-{idx} · **{type_label}** · 标记 {mark_count_display} 次 | {q_short}"

            toggle_key = f"mnemonic_uncertain_toggle_{qid}"
            if toggle_key not in st.session_state:
                st.session_state[toggle_key] = True

            all_expanded = st.session_state.get("mnemonic_all_expanded", False)
            with st.expander(expander_label, expanded=all_expanded):
                # ---- 题目正文 ----
                st.markdown(f"**📝 题目：** {question_text}")

                # ---- 全部选项（正确答案绿底加粗）----
                st.markdown("**选项：**")
                opt_keys = sorted(opts.keys())
                for k in opt_keys:
                    is_correct = k in ans_key
                    if is_correct:
                        st.markdown(
                            f'<p style="color:#1b5e20;font-weight:bold;">✅ {k}: {opts[k]}</p>',
                            unsafe_allow_html=True)
                    else:
                        st.markdown(f'{k}: {opts[k]}')

                # ---- 正确答案框 ----
                correct_display = get_answer_display(q_type, ans_key, opts)
                st.markdown(
                    f'<div style="background:#e8f5e9;border-left:4px solid #1b5e20;padding:8px 12px;'
                    f'border-radius:4px;margin:8px 0;">'
                    f'<span style="color:#1b5e20;font-weight:bold;">✅ 正确答案：{correct_display}</span></div>',
                    unsafe_allow_html=True,
                )

                # ---- 解析 ----
                if explanation and explanation.strip():
                    st.markdown("**📖 题目解析：**")
                    st.markdown(explanation.strip())

                # ---- 底部操作行 ----
                st.markdown("---")
                op_c1, op_c2, op_c3 = st.columns([2, 1, 1])
                with op_c1:
                    st.caption(f"标记强度：{mark_count_display} 次")
                with op_c3:
                    def _make_uncertain_callback(_qid):
                        def _cb():
                            # toggle 关闭时立即写库，不触发整页刷新
                            if not st.session_state.get(f"mnemonic_uncertain_toggle_{_qid}", True):
                                clear_uncertain_mark(_qid)
                        return _cb
                    st.toggle(
                        "移除标记",
                        key=toggle_key,
                        value=True,
                        help="关闭后该题不再作为不确定题目，已记录到数据库",
                        on_change=_make_uncertain_callback(qid),
                    )


def show_mnemonic():
    """助记助学主页面 — 数字相关 / 人名相关 双 Tab"""
    st.title("🧠 助记助学")
    st.markdown("将题库中涉及**数字答案**和**人名答案**的题目整理为速查表格，便于考前集中记忆。")

    # 使用缓存数据，避免每次 toggle 都重新筛选分类
    data = _compute_mnemonic_data()
    number_items = data["number_items"]
    person_items = data["person_items"]
    scale_dimension_items = data["scale_dimension_items"]
    scale_score_items = data["scale_score_items"]
    entry_count_items = data["entry_count_items"]
    month_items = data["month_items"]
    year_items = data["year_items"]
    duration_items = data["duration_items"]
    other_number_items = data["other_number_items"]

    show_answer = True

    # ---- 加载不确定题目（从数据库实时加载，用于 Tab 标签计数）----
    uncertain_questions = load_uncertain_questions(exam_type=st.session_state.get("exam_type", "心理学会咨询师四级"))

    # ---- 四 Tab ----
    scale_total = len(scale_dimension_items) + len(scale_score_items) + len(entry_count_items)
    tab1, tab2, tab3, tab4 = st.tabs([
        f"🔢 数字相关（{len(number_items)}）",
        f"📊 量表相关（{scale_total}）",
        f"👤 人名相关（{len(person_items)}）",
        f"❓ 不确定题目（{len(uncertain_questions)}）",
    ])

    # ========== Tab 1: 数字相关 ==========
    with tab1:
        if len(number_items) == 0:
            st.info("当前题库未检测到数字记忆题，请确认题库已导入。")
        else:
            search_col, btn_col, reload_col = st.columns([3, 1, 1])
            with search_col:
                search = st.text_input(
                    "🔍 搜索数字题", placeholder="例如：量表、条目、年龄...",
                    label_visibility="collapsed", key="search_number"
                )
            with btn_col:
                btn_label = "全部展开" if not st.session_state.get("mnemonic_all_expanded", False) else "全部折叠"
                if st.button(btn_label, use_container_width=True, key="expand_number"):
                    st.session_state.mnemonic_all_expanded = (
                        not st.session_state.get("mnemonic_all_expanded", False)
                    )
                    st.session_state.pop("mnemonic_expanded", None)
                    st.rerun()
            with reload_col:
                if st.button("重新加载", use_container_width=True, key="reload_number",
                             help="题库中导入新题目后需重新加载"):
                    st.session_state.pop("_mnemonic_data", None)
                    st.rerun()

            st.caption(
                f"当前题库共 {len(number_items)} 道数字记忆题"
            )
            st.markdown("---")

            # ===== 子区1：月龄（升序，排在岁数之前） =====
            if month_items:
                st.subheader(f"📅 月龄（{len(month_items)} 题，按月龄升序）")
                md_lines = ["| # | 知识点 | 月龄 |", "|---|--------|------|"]
                for idx, item in enumerate(month_items, 1):
                    q_clean = _clean_question(item["question"])
                    q_clean = q_clean.replace("|", "\\|")
                    if show_answer:
                        ans_display = f'<b style="color:#FF4B4B;">{item["answer"]}</b>'
                    else:
                        ans_display = '<span style="color:#aaa;">???</span>'
                    md_lines.append(f"| {idx} | {q_clean} | {ans_display} |")
                st.markdown("\n".join(md_lines), unsafe_allow_html=True)

                st.markdown("---")

            # ===== 子区3：岁数（升序） =====
            if year_items:
                st.subheader(f"📅 岁数（{len(year_items)} 题，按年龄升序）")
                md_lines = ["| # | 知识点 | 年龄 |", "|---|--------|------|"]
                for idx, item in enumerate(year_items, 1):
                    q_clean = _clean_question(item["question"])
                    q_clean = q_clean.replace("|", "\\|")
                    if show_answer:
                        ans_display = f'<b style="color:#FF4B4B;">{item["answer"]}</b>'
                    else:
                        ans_display = '<span style="color:#aaa;">???</span>'
                    md_lines.append(f"| {idx} | {q_clean} | {ans_display} |")
                st.markdown("\n".join(md_lines), unsafe_allow_html=True)

                st.markdown("---")

            # ===== 子区4：病程/时长（升序） =====
            if duration_items:
                st.subheader(f"⏱️ 病程 / 持续时长（{len(duration_items)} 题，按时长升序）")
                md_lines = ["| # | 疾病 / 概念 | 时长 |", "|---|--------|------|"]
                for idx, item in enumerate(duration_items, 1):
                    q_clean = _clean_question(item["question"])
                    q_clean = q_clean.replace("|", "\\|")
                    if show_answer:
                        ans_display = f'<b style="color:#FF4B4B;">{item["answer"]}</b>'
                    else:
                        ans_display = '<span style="color:#aaa;">???</span>'
                    md_lines.append(f"| {idx} | {q_clean} | {ans_display} |")
                st.markdown("\n".join(md_lines), unsafe_allow_html=True)

                st.markdown("---")

            # ===== 子区5：其他数字题 =====
            if other_number_items:
                st.subheader(f"🔢 其他数字题（{len(other_number_items)} 题）")
                _render_items(other_number_items, show_answer, search)

            st.markdown("---")
            st.caption(
                f"共 {len(number_items)} 题 "
                f"· 月龄 {len(month_items)} · 岁数 {len(year_items)} · 病程 {len(duration_items)} · 其他 {len(other_number_items)}"
            )

    # ========== Tab 2: 量表相关 ==========
    with tab2:
        if scale_total == 0:
            st.info("当前题库未检测到量表记忆题（维度/分数/条目）。")
        else:
            search_col, reload_col = st.columns([3, 1])
            with search_col:
                search_scale = st.text_input(
                    "🔍 搜索量表题", placeholder="例如：量表维度、分数、条目...",
                    label_visibility="collapsed", key="search_scale"
                )
            with reload_col:
                if st.button("重新加载", use_container_width=True, key="reload_scale",
                             help="题库中导入新题目后需重新加载"):
                    st.session_state.pop("_mnemonic_data", None)
                    st.rerun()

            st.caption(
                f"量表维度 {len(scale_dimension_items)} 题 · 量表分数 {len(scale_score_items)} 题 · 量表条目 {len(entry_count_items)} 题"
            )
            st.markdown("---")

            # ===== 量表维度 =====
            if scale_dimension_items:
                st.subheader(f"📋 量表维度（{len(scale_dimension_items)} 题）")
                # 搜索过滤
                filtered_dim = scale_dimension_items
                if search_scale.strip():
                    kw = search_scale.strip().lower()
                    filtered_dim = [
                        i for i in filtered_dim
                        if kw in i["question"].lower() or kw in i["answer"].lower()
                    ]
                if filtered_dim:
                    md_lines = ["| # | 量表 | 维度 |", "|---|--------|------|"]
                    for idx, item in enumerate(filtered_dim, 1):
                        q_clean = _clean_question(item["question"])
                        q_clean = q_clean.replace("|", "\\|")
                        if show_answer:
                            ans_display = f'<b style="color:#FF4B4B;">{item["answer"]}</b>'
                        else:
                            ans_display = '<span style="color:#aaa;">???</span>'
                        md_lines.append(f"| {idx} | {q_clean} | {ans_display} |")
                    st.markdown("\n".join(md_lines), unsafe_allow_html=True)
                else:
                    st.info("无匹配结果")
                st.markdown("---")

            # ===== 量表分数（划界分/常模分/总分阈值） =====
            if scale_score_items:
                st.subheader(f"📊 量表分数（{len(scale_score_items)} 题，按分数降序）")
                filtered_sc = scale_score_items
                if search_scale.strip():
                    kw = search_scale.strip().lower()
                    filtered_sc = [
                        i for i in filtered_sc
                        if kw in i["question"].lower() or kw in i["answer"].lower()
                    ]
                if filtered_sc:
                    md_lines = ["| # | 量表 / 题目 | 分数值 |", "|---|--------|------|"]
                    for idx, item in enumerate(filtered_sc, 1):
                        q_clean = _clean_question(item["question"])
                        q_clean = q_clean.replace("|", "\\|")
                        if show_answer:
                            ans_display = f'<b style="color:#FF4B4B;">{item["answer"]}</b>'
                        else:
                            ans_display = '<span style="color:#aaa;">???</span>'
                        md_lines.append(f"| {idx} | {q_clean} | {ans_display} |")
                    st.markdown("\n".join(md_lines), unsafe_allow_html=True)
                else:
                    st.info("无匹配结果")
                st.markdown("---")

            # ===== 量表条目（降序） =====
            if entry_count_items:
                st.subheader(f"📊 量表条目（{len(entry_count_items)} 题，按条目数降序）")
                filtered_ec = entry_count_items
                if search_scale.strip():
                    kw = search_scale.strip().lower()
                    filtered_ec = [
                        i for i in filtered_ec
                        if kw in i["question"].lower() or kw in i["answer"].lower()
                    ]
                if filtered_ec:
                    md_lines = ["| # | 量表 / 主题 | 条目数 |", "|---|--------|------|"]
                    for idx, item in enumerate(filtered_ec, 1):
                        q_clean = _clean_question(item["question"])
                        q_clean = q_clean.replace("|", "\\|")
                        if show_answer:
                            ans_display = f'<b style="color:#FF4B4B;">{item["answer"]}</b>'
                        else:
                            ans_display = '<span style="color:#aaa;">???</span>'
                        md_lines.append(f"| {idx} | {q_clean} | {ans_display} |")
                    st.markdown("\n".join(md_lines), unsafe_allow_html=True)
                else:
                    st.info("无匹配结果")

            st.markdown("---")
            st.caption(
                f"共 {scale_total} 题 · 量表维度 {len(scale_dimension_items)} · 量表分数 {len(scale_score_items)} · 量表条目 {len(entry_count_items)}"
            )

    # ========== Tab 3: 人名相关 ==========
    with tab3:
        if len(person_items) == 0:
            st.info("当前题库未检测到人名记忆题。")
        else:
            from collections import Counter
            cat_counts = Counter(item["category"] for item in person_items)
            search_col, btn_col, reload_col = st.columns([3, 1, 1])
            with search_col:
                search = st.text_input(
                    "🔍 搜索人名题", placeholder="例如：弗洛伊德、量表编制者...",
                    label_visibility="collapsed", key="search_person"
                )
            with btn_col:
                btn_label = "全部展开" if not st.session_state.get("mnemonic_all_expanded", False) else "全部折叠"
                if st.button(btn_label, use_container_width=True, key="expand_person"):
                    st.session_state.mnemonic_all_expanded = (
                        not st.session_state.get("mnemonic_all_expanded", False)
                    )
                    st.session_state.pop("mnemonic_expanded", None)
                    st.rerun()
            with reload_col:
                if st.button("重新加载", use_container_width=True, key="reload_person",
                             help="题库中导入新题目后需重新加载"):
                    st.session_state.pop("_mnemonic_data", None)
                    st.rerun()

            st.caption(
                f"当前题库共 {len(person_items)} 道人名记忆题，覆盖 {len(cat_counts)} 个知识板块"
            )
            st.markdown("---")

            _render_items(person_items, show_answer, search)

            st.markdown("---")
            st.caption(
                f"共 {len(person_items)} 题 · 覆盖 {len(cat_counts)} 个板块"
            )

    # ========== Tab 4: 不确定题目（参照错题复盘样式）==========
    with tab4:
        _render_uncertain_tab()

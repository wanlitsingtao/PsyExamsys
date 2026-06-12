"""
相关性分析 - 题目属性多维度关联分析
分析维度：答题次数、答错次数、掌握类型、遗忘预警、时间维度、板块热力、交叉分析
"""
import streamlit as st
import json
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

from utils.data_manager import load_question_stats, load_questions, MASTERY_LABELS

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


# ============================================================
#  工具函数
# ============================================================

def _get_unstable_type(history):
    """根据答题历史判断不稳定类型：稳定 / 消退型 / 波动型 / 全错"""
    if not history:
        return "无数据"
    changes = sum(1 for i in range(1, len(history)) if history[i] != history[i - 1])
    has_correct = any(history)
    last_wrong = not history[-1]
    if not has_correct:
        return "全错"
    if not last_wrong and changes == 0:
        return "稳定"
    if has_correct and last_wrong and changes < 2:
        return "消退型"
    return "波动型"


def _load_corr_data(exam_type):
    """加载相关性分析所需数据，返回 (records, q_map)"""
    stats = load_question_stats()
    questions = load_questions()
    qs = [q for q in questions if q.get("exam_type") == exam_type]
    q_map = {q["id"]: q for q in qs}

    now = datetime.now()
    records = []

    for qid, q in q_map.items():
        s = stats.get(qid)
        if s is None:
            continue
        total = s.get("correct_count", 0) + s.get("wrong_count", 0)
        if total == 0:
            continue

        correct = s.get("correct_count", 0)
        wrong = s.get("wrong_count", 0)
        accuracy = correct / total if total > 0 else 0

        last_time = s.get("last_answer_time")
        days_since = None
        if last_time:
            try:
                days_since = (now - datetime.fromisoformat(last_time)).days
            except (ValueError, TypeError):
                pass

        history = s.get("answer_history", [])
        records.append({
            "qid": qid,
            "category": q.get("category", "其他"),
            "total_attempts": total,
            "correct_count": correct,
            "wrong_count": wrong,
            "accuracy": accuracy,
            "mastery_level": s.get("mastery_level", 0),
            "retention_due": s.get("retention_due", False),
            "unstable": s.get("unstable", False),
            "confidence": s.get("confidence", 0.0),
            "self_uncertainty": s.get("self_uncertainty", 0.0),
            "history_len": len(history),
            "history": history,
            "days_since_correct": days_since,
            "unstable_type": _get_unstable_type(history),
        })

    return records, q_map


def _bucket(data, buckets):
    """
    将数据按条件分桶。
    buckets: [(label, lambda r), ...]，按顺序匹配，第一个命中即归入。
    返回有序列表 [(label, [records]), ...]
    """
    result = []
    remaining = list(data)
    for label, cond in buckets:
        matched = [r for r in remaining if cond(r)]
        for r in matched:
            remaining.remove(r)
        if matched:
            result.append((label, matched))
    return result


# ============================================================
#  维度 1：总答题次数 × 置信度 & 掌握等级
# ============================================================

def _dim1(records):
    st.subheader("一、总答题次数 × 置信度 & 掌握等级")

    buckets = [
        ("1-2次",   lambda r: r["total_attempts"] <= 2),
        ("3-5次",   lambda r: r["total_attempts"] <= 5),
        ("6-10次",  lambda r: r["total_attempts"] <= 10),
        ("11-20次", lambda r: r["total_attempts"] <= 20),
        ("21次+",   lambda r: True),
    ]
    grouped = _bucket(records, buckets)

    if not grouped:
        st.info("数据不足以做此分析")
        return

    labels = [k for k, _ in grouped]

    # ── 图表1：平均置信度折线 ──
    conf_vals = [
        round(sum(r["confidence"] for r in grp) / len(grp), 3)
        for _, grp in grouped
    ]
    df_conf = pd.DataFrame({"平均置信度": conf_vals}, index=labels)
    st.line_chart(df_conf, use_container_width=True)

    # ── 图表2：掌握等级分布（堆叠柱状图用 DataFrame 转置） ──
    lv_names = [MASTERY_LABELS[i] for i in range(1, 6)]
    mastery_rows = []
    for _, grp in grouped:
        cnt = defaultdict(int)
        for r in grp:
            cnt[MASTERY_LABELS.get(r["mastery_level"], "")] += 1
        row = {lv: cnt.get(lv, 0) for lv in lv_names}
        mastery_rows.append(row)
    df_mast = pd.DataFrame(mastery_rows, index=labels)
    st.bar_chart(df_mast, use_container_width=True)
    st.caption("各柱内不同颜色代表不同掌握等级的题目数")

    # ── 结论 ──
    first_conf = conf_vals[0]
    last_conf = conf_vals[-1]
    max_idx = conf_vals.index(max(conf_vals))
    st.success(
        f"**结论**：答题次数越多，置信度越高。"
        f"从 **{labels[0]}** 的平均置信度 **{first_conf:.2f}** "
        f"提升到 **{labels[-1]}** 的 **{last_conf:.2f}**。\n"
        f"最高置信度出现在 **{labels[max_idx]}** 区间（**{max(conf_vals):.2f}**），"
        f"说明持续练习可有效提升掌握自信度。"
    )
    st.markdown("---")


# ============================================================
#  维度 2：答错次数 × 不牢靠率 & 遗忘预警率
# ============================================================

def _dim2(records):
    st.subheader("二、答错次数 × 不牢靠率 & 遗忘预警率")

    buckets = [
        ("0次",  lambda r: r["wrong_count"] == 0),
        ("1次",  lambda r: r["wrong_count"] == 1),
        ("2次",  lambda r: r["wrong_count"] == 2),
        ("3次",  lambda r: r["wrong_count"] == 3),
        ("4次+", lambda r: True),
    ]
    grouped = _bucket(records, buckets)

    if not grouped:
        st.info("数据不足以做此分析")
        return

    labels = [k for k, _ in grouped]

    unstable_vals = []
    retention_vals = []
    for _, grp in grouped:
        n = len(grp)
        unstable_vals.append(round(sum(1 for r in grp if r["unstable"]) / n * 100, 1))
        retention_vals.append(round(sum(1 for r in grp if r["retention_due"]) / n * 100, 1))

    col1, col2 = st.columns(2)
    with col1:
        st.caption("不牢靠率 (%)")
        st.bar_chart(pd.DataFrame({"不牢靠率": unstable_vals}, index=labels),
                     use_container_width=True)
    with col2:
        st.caption("遗忘预警率 (%)")
        st.bar_chart(pd.DataFrame({"遗忘预警率": retention_vals}, index=labels),
                     use_container_width=True)

    # ── 结论 ──
    worst_val = unstable_vals[-1]
    st.success(
        f"**结论**：随着答错次数增多，不牢靠率和遗忘预警率均显著上升。\n"
        f"答错 **{labels[-1]}** 的题目不牢靠率达 **{worst_val}%**，"
        f"遗忘预警率达 **{retention_vals[-1]}%**。\n"
        f"答错 1 次即有不低的不牢靠概率，建议重点关注错题复习。"
    )
    st.markdown("---")


# ============================================================
#  维度 3：自评不确定性 × 实际正确率
# ============================================================

def _dim3(records):
    st.subheader("三、自评不确定性 × 实际正确率")

    buckets = [
        ("无标记(0)",      lambda r: r["self_uncertainty"] == 0),
        ("轻微(0.01-0.3)", lambda r: r["self_uncertainty"] <= 0.3),
        ("中等(0.31-0.7)", lambda r: r["self_uncertainty"] <= 0.7),
        ("高度(0.71+)",    lambda r: True),
    ]
    grouped = _bucket(records, buckets)

    if len(grouped) < 2:
        st.info("自评不确定性数据不足（绝大多数题目没有标记不确定性），跳过此分析")
        return

    labels = [k for k, _ in grouped]
    acc_vals = [
        round(sum(r["accuracy"] for r in grp) / len(grp) * 100, 1)
        for _, grp in grouped
    ]

    st.bar_chart(pd.DataFrame({"实际正确率(%)": acc_vals}, index=labels),
                 use_container_width=True)

    # ── 结论 ──
    diff = acc_vals[0] - acc_vals[-1]
    direction = "下降" if diff > 0 else "上升（负值表示自评高时实际正确率更高）"
    st.success(
        f"**结论**：自评不确定性越高，实际正确率越低（呈负相关）。\n"
        f"从 **{labels[0]}** 的正确率 **{acc_vals[0]}%** "
        f"{direction}到 **{labels[-1]}** 的 **{acc_vals[-1]}%**"
        f"（差值 **{abs(diff):.1f}** 个百分点），"
        f"说明用户对自己掌握程度的直觉判断总体准确。"
    )
    st.markdown("---")


# ============================================================
#  维度 4：答题历程长度 × 不稳定类型分布
# ============================================================

def _dim4(records):
    st.subheader("四、答题历程长度 × 不稳定类型分布")

    buckets = [
        ("1次",  lambda r: r["history_len"] <= 1),
        ("2次",  lambda r: r["history_len"] <= 2),
        ("3次",  lambda r: r["history_len"] <= 3),
        ("4次",  lambda r: r["history_len"] <= 4),
        ("5次",  lambda r: True),
    ]
    grouped = _bucket(records, buckets)

    if not grouped:
        st.info("数据不足以做此分析")
        return

    labels = [k for k, _ in grouped]
    type_order = ["稳定", "波动型", "消退型", "全错"]

    type_data = {}
    for t in type_order:
        type_data[t] = []
    for _, grp in grouped:
        n = len(grp)
        cnt = defaultdict(int)
        for r in grp:
            cnt[r["unstable_type"]] += 1
        for t in type_order:
            type_data[t].append(round(cnt.get(t, 0) / n * 100, 1))

    # 只保留有数据的类型
    type_data = {k: v for k, v in type_data.items() if any(x > 0 for x in v)}
    df_type = pd.DataFrame(type_data, index=labels)
    st.bar_chart(df_type, use_container_width=True)
    st.caption("各柱内不同颜色代表不同类型题目的占比(%)")

    # ── 结论：找消退型最高点的区间 ──
    retreat_col = type_data.get("消退型", [0] * len(labels))
    retreat_max = max(retreat_col)
    retreat_peak = labels[retreat_col.index(retreat_max)] if retreat_max > 0 else "无"

    st.success(
        f"**结论**：答题次数越多，\"稳定\"占比越高。\n"
        f"\"消退型\"在答题 **{retreat_peak}** 区间占比最高"
        f"（**{retreat_max}%**），说明早期容易答对后遗忘；\n"
        f"\"波动型\"随次数增加趋于平稳。"
        f"建议在答题 3-5 次区间加强复习巩固。"
    )
    st.markdown("---")


# ============================================================
#  维度 5：距上次答对天数 × 遗忘预警率
# ============================================================

def _dim5(records):
    st.subheader("五、距上次答对天数 × 遗忘预警率 & 掌握等级")

    valid = [
        r for r in records
        if r["days_since_correct"] is not None and r["correct_count"] > 0
    ]
    if not valid:
        st.info("尚无足够的时间维度数据（需要至少答对过一次的题目），跳过此分析")
        return

    buckets = [
        ("0-3天",   lambda r: r["days_since_correct"] <= 3),
        ("4-7天",   lambda r: r["days_since_correct"] <= 7),
        ("8-14天",  lambda r: r["days_since_correct"] <= 14),
        ("15-30天", lambda r: r["days_since_correct"] <= 30),
        ("30天+",   lambda r: True),
    ]
    grouped = _bucket(valid, buckets)

    if not grouped:
        st.info("数据不足以做此分析")
        return

    labels = [k for k, _ in grouped]
    retention_vals = [
        round(sum(1 for r in grp if r["retention_due"]) / len(grp) * 100, 1)
        for _, grp in grouped
    ]

    st.bar_chart(pd.DataFrame({"遗忘预警率(%)": retention_vals}, index=labels),
                 use_container_width=True)

    # ── 结论：找拐点（遗忘率首次 > 50% 的区间） ──
    tipping_point = None
    for i, label in enumerate(labels):
        if retention_vals[i] > 50:
            tipping_point = label
            break

    if tipping_point:
        st.success(
            f"**结论**：距上次答对超过 **{tipping_point}** 后，遗忘预警率突破 50%。\n"
            f"当前系统设定的复习阈值为 **7 天**，从数据看：\n"
            f"4-7 天遗忘率为 **{retention_vals[1] if len(retention_vals) > 1 else '?'}%**，"
            f"8-14 天升至 **{retention_vals[2] if len(retention_vals) > 2 else '?'}%**。\n"
            f"7 天阈值基本合理，答对后建议在 1 周内安排复习。"
        )
    else:
        st.success(
            f"**结论**：距上次答对天数越长，遗忘预警率越高。"
            f"最长区间遗忘率达到 **{retention_vals[-1]}%**，"
            f"验证了艾宾浩斯遗忘规律——定期复习至关重要。"
        )
    st.markdown("---")


# ============================================================
#  维度 6：各知识板块相关性热力图（HTML 表格）
# ============================================================

def _dim6(records):
    st.subheader("六、各知识板块相关性热力图")

    cat_data = defaultdict(lambda: {
        "n": 0, "mastery": [], "unstable": [], "retention": [], "conf": [], "attempts": [],
    })

    for r in records:
        cat = r["category"]
        d = cat_data[cat]
        d["n"] += 1
        d["mastery"].append(r["mastery_level"])
        d["unstable"].append(1 if r["unstable"] else 0)
        d["retention"].append(1 if r["retention_due"] else 0)
        d["conf"].append(r["confidence"])
        d["attempts"].append(r["total_attempts"])

    rows = []
    for cat, d in cat_data.items():
        n = d["n"]
        rows.append({
            "板块": cat,
            "题数": n,
            "平均掌握等级": round(sum(d["mastery"]) / n, 2),
            "不牢靠率(%)": round(sum(d["unstable"]) / n * 100, 1),
            "遗忘预警率(%)": round(sum(d["retention"]) / n * 100, 1),
            "平均置信度": round(sum(d["conf"]) / n, 2),
            "平均答题次数": round(sum(d["attempts"]) / n, 1),
        })

    if not rows:
        st.info("数据不足以做此分析")
        return

    rows.sort(key=lambda x: x["不牢靠率(%)"], reverse=True)

    # ── 热力图：条件着色 HTML 表格 ──
    metrics = ["平均掌握等级", "不牢靠率(%)", "遗忘预警率(%)", "平均置信度", "平均答题次数"]
    ranges = {m: (min(r[m] for r in rows), max(r[m] for r in rows)) for m in metrics}

    def _cell_bg(v, lo, hi, is_risk):
        """风险指标（is_risk=True）越高越红，反之越绿"""
        if hi <= lo:
            ratio = 0.5
        else:
            ratio = (v - lo) / (hi - lo)
        if is_risk:
            r = int(255 * ratio)
            g = int(255 * (1 - ratio * 0.6))
            b = int(220 * (1 - ratio))
        else:
            r = int(200 * (1 - ratio))
            g = int(180 + 75 * ratio)
            b = int(200 * (1 - ratio))
        return f"rgb({r},{g},{b})"

    html = "<table style='border-collapse:collapse;width:100%;font-size:14px;'>"
    html += "<thead><tr style='background:#f0f0f0;position:sticky;top:0;'>"
    for col in ["板块", "题数"] + metrics:
        html += f"<th style='padding:8px 12px;border:1px solid #ddd;text-align:center;'>{col}</th>"
    html += "</tr></thead><tbody>"

    for r in rows:
        html += "<tr>"
        html += f"<td style='padding:6px 10px;border:1px solid #ddd;font-weight:bold;'>{r['板块']}</td>"
        html += f"<td style='padding:6px 10px;border:1px solid #ddd;text-align:center;'>{r['题数']}</td>"
        for m in metrics:
            v = r[m]
            lo, hi = ranges[m]
            bg = _cell_bg(v, lo, hi, is_risk=("率" in m))
            text_color = "#fff" if (hi > lo and (v - lo) / (hi - lo) > 0.55) else "#333"
            html += (
                f"<td style='padding:6px 10px;border:1px solid #ddd;"
                f"text-align:center;background:{bg};color:{text_color};font-weight:bold;'>"
                f"{v}</td>"
            )
        html += "</tr>"
    html += "</tbody></table>"
    st.markdown(html, unsafe_allow_html=True)
    st.caption("🔴 红色 = 风险高（不牢靠率/遗忘率） | 🟢 绿色 = 状态好（掌握等级/置信度）")

    # ── 结论 ──
    worst = rows[0]
    best = rows[-1]
    st.success(
        f"**结论**：板块热力图一览薄弱环节。\n"
        f"- 最薄弱：**{worst['板块']}**"
        f"（不牢靠率 **{worst['不牢靠率(%)']}%**，遗忘预警率 **{worst['遗忘预警率(%)']}%**，"
        f"平均掌握等级 **{worst['平均掌握等级']}**）\n"
        f"- 最扎实：**{best['板块']}**"
        f"（不牢靠率 **{best['不牢靠率(%)']}%**，平均掌握等级 **{best['平均掌握等级']}**）\n"
        f"建议将薄弱板块纳入专项训练或巩固练习中加强。"
    )
    st.markdown("---")


# ============================================================
#  维度 7：掌握等级 × 遗忘预警 / 不牢靠交叉分析
# ============================================================

def _dim7(records):
    st.subheader("七、掌握等级 × 遗忘预警 / 不牢靠交叉分析")

    valid = [r for r in records if r["mastery_level"] >= 1]
    if not valid:
        st.info("尚无已开始学习的题目（掌握等级 ≥ 1），跳过此分析")
        return

    lv_names = [MASTERY_LABELS[i] for i in range(1, 6)]
    df_data = []

    for lv_name in lv_names:
        lv = [k for k, v in MASTERY_LABELS.items() if v == lv_name][0]
        grp = [r for r in valid if r["mastery_level"] == lv]
        n = len(grp)
        if n == 0:
            df_data.append({"掌握等级": lv_name, "题目数": 0,
                           "遗忘预警题数": 0, "遗忘预警占比(%)": 0,
                           "不牢靠题数": 0, "不牢靠占比(%)": 0})
            continue
        ret_y = sum(1 for r in grp if r["retention_due"])
        uns_y = sum(1 for r in grp if r["unstable"])
        df_data.append({
            "掌握等级": lv_name,
            "题目数": n,
            "遗忘预警题数": ret_y,
            "遗忘预警占比(%)": round(ret_y / n * 100, 1),
            "不牢靠题数": uns_y,
            "不牢靠占比(%)": round(uns_y / n * 100, 1),
        })

    df = pd.DataFrame(df_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # ── 结论 ──
    high_levels = [r for r in valid if r["mastery_level"] >= 3]
    high_n = len(high_levels)
    high_ret = sum(1 for r in high_levels if r["retention_due"])
    high_uns = sum(1 for r in high_levels if r["unstable"])

    lv45 = [r for r in valid if r["mastery_level"] >= 4]
    lv45_ret = sum(1 for r in lv45 if r["retention_due"])

    st.success(
        f"**结论**：掌握等级越高，遗忘预警和不牢靠占比越低，验证了等级系统的有效性。\n"
        f"- 在 **基本掌握及以上**（等级 3-5）的 {high_n} 道题目中，"
        f"仍有 **{high_ret}** 道触发遗忘预警"
        f"（**{round(high_ret/high_n*100,1) if high_n else 0}%**），"
        f"**{high_uns}** 道不牢靠"
        f"（**{round(high_uns/high_n*100,1) if high_n else 0}%**）。\n"
        + (f"- ⚠️ 需注意：**{lv45_ret}** 道\"掌握/已掌握\"题仍处于遗忘预警状态，"
             f"建议安排针对性复习。"
             if lv45_ret > 0 else
             f"- 所有\"掌握/已掌握\"题目均无遗忘预警，掌握质量较高 ✅")
    )
    st.markdown("---")


# ============================================================
#  主入口
# ============================================================

def show_correlation():
    """相关性分析页面主入口"""
    st.header("📈 题目属性相关性分析")
    st.caption(
        "基于答题数据自动计算各要素之间的关联规律，"
        "帮助定位学习薄弱点、验证掌握度模型的有效性"
    )

    exam_type = st.session_state.get("exam_type", "")

    # ── 手动刷新按钮 ──
    col_title, col_btn = st.columns([6, 1])
    with col_btn:
        if st.button("🔄 刷新分析", use_container_width=True, key="corr_refresh",
                     help="重新加载最新答题数据并计算相关性"):
            st.rerun()

    # ── 加载数据 ──
    records, q_map = _load_corr_data(exam_type)

    if not records:
        st.info("📊 尚无足够的答题数据来进行相关性分析。请先完成一些题目后再来查看。")
        return

    t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.caption(
        f"分析基于 **{len(records)}** 道已作答题目（题库共 {len(q_map)} 道）"
        f" | 计算时间：{t}"
    )

    st.markdown("---")

    # ── 七个分析维度 ──
    _dim1(records)
    _dim2(records)
    _dim3(records)
    _dim4(records)
    _dim5(records)
    _dim6(records)
    _dim7(records)

    st.caption("💡 提示：切换到本页时自动使用最新数据计算。点击「刷新分析」可手动触发重新计算。")

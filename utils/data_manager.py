"""
数据管理器 - 管理题库、错题库、配置、答题记录、考试记录的JSON持久化
"""
import json
import random
import shutil
import time
from pathlib import Path
from datetime import datetime


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
QUESTIONS_FILE = DATA_DIR / "questions.json"
WRONG_FILE = DATA_DIR / "wrong_questions.json"
CONFIG_FILE = DATA_DIR / "config.json"
EXAM_RECORDS_FILE = DATA_DIR / "exam_records.json"
STUDY_RECORDS_FILE = DATA_DIR / "study_records.json"    # 背题历史记录
ANSWER_RECORDS_FILE = DATA_DIR / "answer_records.json"  # 每题答题过程记录
BACKUP_DIR = DATA_DIR / "backup"

# 题库类型映射（短码 → 显示名）
EXAM_TYPE_LABELS = {
    "心理学会咨询师四级": "中国心理学会咨询师四级",
    "心理学会咨询师三级": "中国心理学会咨询师三级",
    "心理协会四级": "中国心理协会四级",
    "心理协会三级": "中国心理协会三级",
}

# 默认题库
DEFAULT_EXAM_TYPE = "心理学会咨询师四级"

# 默认配置
DEFAULT_CONFIG = {
    "study_per_round": 50,
    "study_single_count": 20,
    "study_multi_count": 10,
    "study_judge_count": 10,
    "spec_per_round": 60,
    "spec_single_count": 30,
    "spec_multi_count": 20,
    "spec_judge_count": 10,
    "comp_per_round": 60,
    "comp_single_count": 30,
    "comp_multi_count": 20,
    "comp_judge_count": 10,
    "exam_time_minutes": 90,
    "exam_single_count": 20,
    "exam_multi_count": 20,
    "exam_judge_count": 20,
    "wrongbook_extract_count": 50,
    "last_import_files": [],
}

# 模拟考试固定配置（实际考试模型，不可配置）
MOCK_EXAM_CONFIG = {
    "psychology": {
        "name": "心理学综合",
        "time_minutes": 120,  # 9:30—11:30 = 2小时
        "single_count": 150,
        "single_score": 0.4,
        "multi_count": 50,
        "multi_score": 0.6,
        "judge_count": 50,
        "judge_score": 0.2,
        "indefinite_count": 0,
        "indefinite_score": 0,
    },
    "counseling": {
        "name": "咨询实务",
        "time_minutes": 120,  # 13:00—15:00 = 2小时
        "single_count": 140,
        "single_score": 0.4,
        "multi_count": 60,
        "multi_score": 0.6,
        "judge_count": 0,
        "judge_score": 0,
        "indefinite_count": 10,
        "indefinite_score": 0.8,
    },
}


def ensure_dirs():
    """确保数据和备份目录存在"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


# ============================
# 题库管理
# ============================

def load_questions():
    """加载题库"""
    ensure_dirs()
    if QUESTIONS_FILE.exists():
        with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_questions(questions):
    """保存题库"""
    ensure_dirs()
    with open(QUESTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)


def get_question_count(exam_type=None):
    """获取题库统计，可按 exam_type 过滤"""
    qs = load_questions()
    if exam_type:
        qs = [q for q in qs if q.get("exam_type") == exam_type]
    return {
        "total": len(qs),
        "single": sum(1 for q in qs if q["type"] == "single"),
        "multi": sum(1 for q in qs if q["type"] == "multi"),
        "judge": sum(1 for q in qs if q["type"] == "judge"),
        "indefinite": sum(1 for q in qs if q["type"] == "indefinite"),
    }


def get_questions_by_type(question_type, exam_type=None):
    """按题型获取题目，可按 exam_type 过滤"""
    qs = load_questions()
    if exam_type:
        qs = [q for q in qs if q.get("exam_type") == exam_type]
    return [q for q in qs if q["type"] == question_type]


def get_available_exam_types():
    """获取题库中所有可用的 exam_type，返回 [(code, label), ...] 列表"""
    qs = load_questions()
    types = set(q.get("exam_type", "") for q in qs if q.get("exam_type"))
    result = []
    for t in sorted(types):
        label = EXAM_TYPE_LABELS.get(t, t)
        result.append((t, label))
    return result


def get_questions_by_exam_type(exam_type):
    """获取指定 exam_type 的全部题目"""
    qs = load_questions()
    return [q for q in qs if q.get("exam_type") == exam_type]


# ============================
# 智能去重
# ============================

def dedup_import(existing_questions, new_questions):
    """
    智能去重导入
    返回: (合并后题库, added_count, skipped_count, 详细日志)
    """
    existing_md5s = {q["md5"] for q in existing_questions}
    added = 0
    skipped = 0
    log = []

    for q in new_questions:
        if q["md5"] in existing_md5s:
            skipped += 1
            log.append(f"  ⏭️ 跳过重复题: [{q['source_file']}] 第{q['index']}题 - {q['question'][:30]}...")
        else:
            existing_questions.append(q)
            existing_md5s.add(q["md5"])
            added += 1

    return existing_questions, added, skipped, log


# ============================
# 错题库管理
# ============================

def load_wrong_questions():
    """加载错题库"""
    ensure_dirs()
    if WRONG_FILE.exists():
        with open(WRONG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_wrong_questions(wrong_list):
    """保存错题库"""
    ensure_dirs()
    with open(WRONG_FILE, "w", encoding="utf-8") as f:
        json.dump(wrong_list, f, ensure_ascii=False, indent=2)


def add_wrong_record(question_id, user_answer):
    """
    记录错题 - 以最后一次答题为准
    新规则：答错次数 >= 答对次数 才记入错题本
    错题库仅存储 question_id 列表，统计数字统一从 question_stats.json 读取
    """
    now = datetime.now().isoformat()

    # 1. 更新题目答题统计（答错+1）
    stats = load_question_stats()
    if question_id not in stats:
        stats[question_id] = {
            "correct_count": 0,
            "wrong_count": 0,
            "last_answer_time": None,
            "last_correct": None,
        }
    stats[question_id]["wrong_count"] += 1
    stats[question_id]["last_correct"] = False
    stats[question_id]["last_answer_time"] = now
    save_question_stats(stats)

    s = stats[question_id]

    # 2. 新规则：答错次数 >= 答对次数（且至少答过一次）→ 加入错题本
    wc, cc = s["wrong_count"], s["correct_count"]
    wrong_qids = _extract_qids_from_wrong_list(load_wrong_questions())
    if wc >= cc and (wc > 0 or cc > 0):
        if question_id not in wrong_qids:
            wrong_qids.append(question_id)
    elif question_id in wrong_qids:
        if question_id in wrong_qids:
            wrong_qids.remove(question_id)
    save_wrong_questions(wrong_qids)


def add_correct_record(question_id):
    """
    记录答对 - 以最后一次答题为准
    新规则：答对后若 答错次数 < 答对次数，从错题本移除
    错题库仅存储 question_id 列表
    """
    now = datetime.now().isoformat()

    # 1. 更新题目答题统计（答对+1）
    stats = load_question_stats()
    if question_id not in stats:
        stats[question_id] = {
            "correct_count": 0,
            "wrong_count": 0,
            "last_answer_time": None,
            "last_correct": None,
        }
    stats[question_id]["correct_count"] += 1
    stats[question_id]["last_correct"] = True
    stats[question_id]["last_answer_time"] = now
    save_question_stats(stats)

    s = stats[question_id]

    # 2. 新规则：答错次数 < 答对次数 → 从错题本移除
    if s["wrong_count"] < s["correct_count"]:
        wrong_qids = _extract_qids_from_wrong_list(load_wrong_questions())
        if question_id in wrong_qids:
            wrong_qids.remove(question_id)
            save_wrong_questions(wrong_qids)


# ============================
# 批量操作 - 减少 JSON I/O 次数，提升性能
# ============================

def _extract_qids_from_wrong_list(wrong_list):
    """兼容新旧格式：从错题库提取 question_id 列表"""
    if not wrong_list:
        return []
    if isinstance(wrong_list[0], dict):
        # 旧格式：[{"question_id": "...", "wrong_count": N, ...}]
        return [w["question_id"] for w in wrong_list]
    # 新格式：["qid1", "qid2", ...]
    return wrong_list


def batch_update_wrong_and_stats(wrong_qids, correct_qids, stats_updates):
    """
    批量更新错题库和题目答题统计（单次读+单次写）
    新规则：答错次数 >= 答对次数 → 记入错题本
    - wrong_qids: list of (question_id, user_answer) 本次答错的
    - correct_qids: list of question_id 本次答对的
    - stats_updates: list of (question_id, is_correct) 需要更新统计的
    """
    now = datetime.now().isoformat()

    # 1. 先加载并更新题目答题统计，计算每组题的新答对/答错次数
    stats = load_question_stats()
    qid_user_ans = dict(wrong_qids)  # qid -> user_answer

    # 预计算所有受影响的 qid 的新统计
    affected_qids = set()
    for qid, is_correct in stats_updates:
        affected_qids.add(qid)
    affected_qids.update(qid_user_ans.keys())
    affected_qids.update(correct_qids)

    new_counts = {}
    for qid in affected_qids:
        s = stats.get(qid, {"correct_count": 0, "wrong_count": 0})
        cc = s.get("correct_count", 0)
        wc = s.get("wrong_count", 0)

        # 应用本次更新
        for _qid, is_correct in stats_updates:
            if _qid == qid:
                if is_correct:
                    cc += 1
                else:
                    wc += 1

        new_counts[qid] = (cc, wc)

        # 同步更新 stats 字典
        if qid not in stats:
            stats[qid] = {
                "correct_count": 0,
                "wrong_count": 0,
                "last_answer_time": None,
                "last_correct": None,
            }
        stats[qid]["correct_count"] = cc
        stats[qid]["wrong_count"] = wc
        stats[qid]["last_answer_time"] = now
        # last_correct: True if last updated answer was correct
        last_is_correct = None
        for _qid, _is_correct in reversed(stats_updates):
            if _qid == qid:
                last_is_correct = _is_correct
                break
        if last_is_correct is not None:
            stats[qid]["last_correct"] = last_is_correct

    save_question_stats(stats)

    # 2. 根据新规则重建错题库：答错次数 >= 答对次数（且至少答过一次）→ 记入错题
    # 错题库仅存储 question_id 列表，统计数字统一从 question_stats.json 读取
    old_qids = _extract_qids_from_wrong_list(load_wrong_questions())

    # 收集所有满足 wc >= cc 且至少答过一次的 qid
    new_wrong_qids = set()
    for qid, (cc, wc) in new_counts.items():
        if wc >= cc and (wc > 0 or cc > 0):
            new_wrong_qids.add(qid)

    # 保留未被本次答题影响的原错题（这些题不影响判断，直接保留）
    for qid in old_qids:
        if qid not in affected_qids:
            new_wrong_qids.add(qid)

    save_wrong_questions(list(new_wrong_qids))


def batch_add_answer_records(records):
    """
    批量追加答题过程记录（单次读+单次写）
    - records: list of dict，每项包含 question_id, user_answer, is_correct, mode, session_id
    """
    existing = load_answer_records()
    now = datetime.now().isoformat()

    # 获取题目信息（只需加载一次）
    questions = load_questions()
    q_map = {q["id"]: q for q in questions}

    for rec in records:
        qid = rec.get("question_id", "")
        q_info = q_map.get(qid)
        category = "未知"
        if q_info:
            category = q_info.get("category", infer_category(q_info.get("source_file", "")))

        existing.append({
            "question_id": qid,
            "user_answer": rec.get("user_answer", ""),
            "is_correct": rec.get("is_correct", False),
            "mode": rec.get("mode", "mock_exam"),
            "session_id": rec.get("session_id", ""),
            "category": category,
            "timestamp": rec.get("timestamp", now),
        })

    save_answer_records(existing)


def get_top_wrong_questions(count=50, exam_type=None):
    """
    获取答错次数最多的N道题（含完整题目信息）
    可按 exam_type 过滤
    统计数字从 question_stats.json 统一读取
    返回: list[tuple(question_dict, wrong_count)]
    """
    wrong_qids = _extract_qids_from_wrong_list(load_wrong_questions())
    questions = load_questions()
    stats = load_question_stats()

    q_map = {q["id"]: q for q in questions}
    result = []

    for qid in wrong_qids:
        if qid not in q_map:
            continue
        q = q_map[qid]
        if exam_type and q.get("exam_type") != exam_type:
            continue
        wc = stats.get(qid, {}).get("wrong_count", 0)
        result.append((q, wc))

    # 按答错次数降序排列
    result.sort(key=lambda x: x[1], reverse=True)
    return result[:count]


def remove_wrong_question(question_id):
    """从错题库移除某题（兼容新旧格式）"""
    wrong_qids = _extract_qids_from_wrong_list(load_wrong_questions())
    if question_id in wrong_qids:
        wrong_qids.remove(question_id)
    save_wrong_questions(wrong_qids)


def clear_all_wrong():
    """清空错题库"""
    save_wrong_questions([])


def get_wrong_stats(exam_type=None):
    """获取错题统计，可按 exam_type 过滤
    统计数字统一从 question_stats.json 读取"""
    wrong_qids = _extract_qids_from_wrong_list(load_wrong_questions())
    questions = load_questions()
    stats = load_question_stats()
    q_map = {q["id"]: q for q in questions}

    if exam_type:
        wrong_qids = [
            qid for qid in wrong_qids
            if qid in q_map and q_map[qid].get("exam_type") == exam_type
        ]

    if not wrong_qids:
        return {"total": 0, "most_wrong": 0}

    max_wc = max(stats.get(qid, {}).get("wrong_count", 0) for qid in wrong_qids)
    return {
        "total": len(wrong_qids),
        "most_wrong": max_wc,
    }


def get_all_wrong_with_stats(exam_type=None):
    """
    获取所有错题，附带答题统计，按易错程度排序
    排序规则：(wrong_count - correct_count) 由大到小
    可按 exam_type 过滤
    统计数字统一从 question_stats.json 读取
    返回: list[dict]，每项包含完整题目信息 + wrong_count / correct_count / diff
    """
    wrong_qids = _extract_qids_from_wrong_list(load_wrong_questions())
    questions = load_questions()
    q_map = {q["id"]: q for q in questions}
    stats = load_question_stats()

    type_labels = {"single": "单选", "multi": "多选", "judge": "判断", "indefinite": "不定项"}

    result = []
    for qid in wrong_qids:
        if qid not in q_map:
            continue
        q = q_map[qid]
        if exam_type and q.get("exam_type") != exam_type:
            continue
        s = stats.get(qid, {})
        wc = s.get("wrong_count", 0)
        cc = s.get("correct_count", 0)
        diff = wc - cc

        result.append({
            "question_id": qid,
            "question": q["question"],
            "type": q["type"],
            "type_label": type_labels.get(q["type"], q["type"]),
            "options": q.get("options", {}),
            "answer": q["answer"],
            "explanation": q.get("explanation", ""),
            "category": q.get("category", infer_category(q.get("source_file", ""))),
            "wrong_count": wc,
            "correct_count": cc,
            "diff": diff,
        })

    # 按 (wrong_count - correct_count) 降序排列
    result.sort(key=lambda x: x["diff"], reverse=True)
    return result


# ============================
# 配置管理
# ============================

def load_config():
    """加载配置"""
    ensure_dirs()
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    save_config(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)


def save_config(config):
    """保存配置"""
    ensure_dirs()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# ============================
# 知识板块推断
# ============================

CATEGORY_MAP = {
    # 咨询实务模块（5个）
    "咨询实务1": "心理咨询会谈技术",
    "咨询实务2": "情绪调节与压力管理",
    "咨询实务3": "心理危机识别",
    "咨询实务4": "家庭教育与心理健康科普",
    "咨询实务5": "心理咨询专业伦理与相关法律规范",
    # 基础理论模块（6个）
    "基础理论1": "心理学导论",
    "基础理论2": "社会心理学",
    "基础理论3": "人格心理学",
    "基础理论4": "发展心理学",
    "基础理论5": "异常心理学",
    "基础理论6": "咨询心理学",
}

# 模拟考试两大科目的超类 → 具体模块映射
SUPER_CATEGORY_MAP = {
    "心理学综合": [
        "心理学导论", "社会心理学", "人格心理学",
        "发展心理学", "异常心理学", "咨询心理学",
    ],
    "咨询实务": [
        "心理咨询会谈技术", "情绪调节与压力管理",
        "心理危机识别", "家庭教育与心理健康科普",
        "心理咨询专业伦理与相关法律规范",
    ],
}


def infer_category(source_file):
    """
    根据 source_file 推断知识板块（细化到具体模块）
    文件名格式如: 【咨询实务1】心理咨询会谈技术.docx 或 【基础理论3】人格心理学.docx
    返回具体模块名: "心理学导论" | "社会心理学" | "人格心理学" | ...
    """
    if not source_file:
        return "其他"
    for key, cat in CATEGORY_MAP.items():
        if key in source_file:
            return cat
    return "其他"


def get_category_count():
    """获取各知识板块的题目统计"""
    qs = load_questions()
    cats = {}
    for q in qs:
        cat = q.get("category", infer_category(q.get("source_file", "")))
        cats[cat] = cats.get(cat, 0) + 1
    return cats


def get_category_training_stats(questions):
    """
    获取每个知识板块的答题统计（用于专项训练首页展示）
    返回: dict {板块名: {"total": N, "answered": N, "correct": N, "wrong": N}}
      - total: 该板块总题数
      - answered: 已答过至少一次的题数（correct_count + wrong_count > 0）
      - correct: 已答题中不在错题库的题数（已掌握）
      - wrong: 已答题中仍在错题库的题数
      保证: answered = correct + wrong（每道已答题只归入一边）
    """
    stats = load_question_stats()
    wrong_list = load_wrong_questions()

    # 构建 qid -> category 映射
    qid_to_cat = {}
    for q in questions:
        qid_to_cat[q.get("id", "")] = q.get("category", "其他")

    # 构建错题 qid 集合（O(1) 查找）
    wrong_qids = set(_extract_qids_from_wrong_list(wrong_list))

    # 初始化结果
    result = {}
    for q in questions:
        cat = q.get("category", "其他")
        if cat not in result:
            result[cat] = {"total": 0, "answered": 0, "correct": 0, "wrong": 0}
        result[cat]["total"] += 1

    # 单次遍历：基于同一数据源统一判定 answered / correct / wrong
    for qid, s in stats.items():
        cat = qid_to_cat.get(qid)
        if cat is None:
            continue
        if cat not in result:
            result[cat] = {"total": 0, "answered": 0, "correct": 0, "wrong": 0}
        # 有答题记录才算已答
        if s.get("correct_count", 0) + s.get("wrong_count", 0) > 0:
            result[cat]["answered"] += 1
            # 对/错由错题库判定（保证二选一，无重叠无遗漏）
            if qid in wrong_qids:
                result[cat]["wrong"] += 1
            else:
                result[cat]["correct"] += 1

    return result


# ============================
# 答题过程记录（每题的全量记录）
# ============================

def load_answer_records():
    """加载答题过程记录"""
    ensure_dirs()
    if ANSWER_RECORDS_FILE.exists():
        with open(ANSWER_RECORDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_answer_records(records):
    """保存答题过程记录"""
    ensure_dirs()
    with open(ANSWER_RECORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def add_answer_record(question_id, user_answer, is_correct, mode="study", session_id=""):
    """
    记录每次答题的过程，无论对错
    - question_id: 题目ID
    - user_answer: 用户选择的答案
    - is_correct: 是否正确
    - mode: 答题模式 (study/exam/wrongbook)
    - session_id: 会话ID，用于关联同一次答题
    """
    records = load_answer_records()
    now = datetime.now().isoformat()

    # 获取题目信息（含知识板块）
    questions = load_questions()
    q_info = None
    for q in questions:
        if q["id"] == question_id:
            q_info = q
            break

    category = "未知"
    if q_info:
        category = q_info.get("category", infer_category(q_info.get("source_file", "")))

    record = {
        "question_id": question_id,
        "user_answer": user_answer,
        "is_correct": is_correct,
        "mode": mode,
        "session_id": session_id,
        "category": category,
        "timestamp": now,
    }
    records.append(record)
    save_answer_records(records)
    return record


# ============================
# 考试记录
# ============================

def load_exam_records():
    """加载考试记录"""
    ensure_dirs()
    if EXAM_RECORDS_FILE.exists():
        with open(EXAM_RECORDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_exam_record(record):
    """保存一条考试记录"""
    records = load_exam_records()
    records.append(record)
    with open(EXAM_RECORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


# ============================
# 背题历史记录（每次背题会话的持久化）
# ============================

def load_study_records():
    """加载背题历史记录"""
    ensure_dirs()
    if STUDY_RECORDS_FILE.exists():
        with open(STUDY_RECORDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_study_record(record):
    """保存一条背题历史记录（追加）"""
    records = load_study_records()
    records.append(record)
    with open(STUDY_RECORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def update_study_record(session_id, update_data):
    """更新指定背题会话的记录（如进度、答案等）"""
    records = load_study_records()
    for rec in records:
        if rec.get("session_id") == session_id:
            rec.update(update_data)
            break
    with open(STUDY_RECORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def find_study_record(session_id):
    """查找指定会话的背题记录"""
    records = load_study_records()
    for rec in records:
        if rec.get("session_id") == session_id:
            return rec
    return None


# ============================
# 模拟考试记录（固定两科，不可配置）
# ============================

MOCK_EXAM_RECORDS_FILE = DATA_DIR / "mock_exam_records.json"


def load_mock_exam_records():
    """加载模拟考试记录"""
    ensure_dirs()
    if MOCK_EXAM_RECORDS_FILE.exists():
        with open(MOCK_EXAM_RECORDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_mock_exam_record(record):
    """保存一条模拟考试记录"""
    records = load_mock_exam_records()
    records.append(record)
    with open(MOCK_EXAM_RECORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


# ============================
# 备份
# ============================

def backup_data():
    """备份所有数据文件"""
    ensure_dirs()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for fname in ["questions.json", "wrong_questions.json", "config.json", "exam_records.json"]:
        src = DATA_DIR / fname
        if src.exists():
            dst = BACKUP_DIR / f"{timestamp}_{fname}"
            shutil.copy2(src, dst)
    return timestamp


# ============================
# 题目抽取工具
# ============================

def _priority_sample(question_list, count, wrong_ids=None, stats=None):
    """
    按优先级从题目列表中抽取 count 道题
    优先级规则（tier 主导，与错题本规则一致）：
      tier0（答错过）> tier1（新题+可能猜对题）> tier2（稳定掌握题）
      tier1 包含：
        - 从未答过的题目（wrong=0, correct=0）
        - 答对但从未答错，且尝试次数≤2 的题目（可能猜对，需要重测）
      tier2 仅包含：多次答对且正确率>50%（已稳定掌握，仅用于补齐）

    tier0/tier1/tier2 内部排序：
      1. 正确率升序（低正确率优先）
      2. 同等正确率时：尝试次数升序（答题次数少=可能蒙对，优先复检）
      3. 同等尝试次数时：wrong 次数降序（曾经错过更多次的优先）
      4. 其余随机打散
    """
    if not question_list or count <= 0:
        return []

    # 加载辅助数据（允许外部传入以复用，减少 I/O）
    if stats is None:
        stats = load_question_stats()

    # 计算每道题的优先级分数
    scored = []
    for q in question_list:
        qid = q.get("id", "")
        s = stats.get(qid, {"correct_count": 0, "wrong_count": 0})
        wrong = s.get("wrong_count", 0)
        correct = s.get("correct_count", 0)

        # 层级（与错题本规则一致）：
        #   0=答错过(wrong>0且wrong>=correct)     ——仍在错题本，最高优先
        #   1=新题或可能猜对(wrong==0, correct<=2) ——从未答过或仅答对1-2次从未答错
        #   2=稳定掌握(correct>wrong, wrong>0 或 correct>2) ——已移出错题本，仅用于补齐
        if wrong > 0 and wrong >= correct:
            tier = 0  # 最高优先：答错过
        elif correct == 0:
            tier = 1  # 新题：从未答过
        elif wrong == 0 and correct <= 2:
            tier = 1  # 可能猜对：答对1-2次但从未答错，需重测
        else:
            tier = 2  # 稳定掌握：多次正确或有过错后正确率>50%

        # 内部排序指标：正确率（升序=低正确率优先）
        # tier0/tier1/tier2 的 accuracy 参与 tier 内同层排序
        total_ans = wrong + correct
        accuracy = correct / total_ans if total_ans > 0 else 0.0

        scored.append((tier, accuracy, total_ans, -wrong, random.random(), q))

    # 排序：tier升序 → accuracy升序 → total_ans升序 → wrong降序 → random
    scored.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4]))

    return [q for _, _, _, _, _, q in scored[:count]]


def _balanced_sample_by_type(questions_by_cat, total_count, wrong_ids=None, stats=None):
    """
    从各子类别中均匀分配配额抽取题目（含优先级排序）
    - questions_by_cat: {类别名: [题目列表]}
    - 每类别分配 base = total_count // n 道，前 extra 个类别多 1 道
    - 配额未用完时从剩余题目中补齐（仍按优先级）
    """
    if total_count <= 0:
        return []

    # 过滤非空类别
    active = {cat: qs for cat, qs in questions_by_cat.items() if qs}
    if not active:
        return []

    cats = list(active.keys())
    random.shuffle(cats)
    n = len(cats)

    base = total_count // n
    extra = total_count % n

    selected = []
    selected_ids = set()
    remaining = total_count

    # 第一轮：每类别分配配额
    for i, cat in enumerate(cats):
        available = active[cat]
        quota = base + (1 if i < extra else 0)
        quota = min(quota, len(available), remaining)

        if quota > 0:
            picked = _priority_sample(available, quota, wrong_ids, stats)
            selected.extend(picked)
            for q in picked:
                selected_ids.add(q.get("id", ""))
            remaining -= quota

    # 第二轮：配额未用完，从各板块剩余题目中补齐
    if remaining > 0:
        leftover = []
        for cat in cats:
            for q in active[cat]:
                if q.get("id", "") not in selected_ids:
                    leftover.append(q)
        extra_picked = _priority_sample(leftover, min(remaining, len(leftover)), wrong_ids, stats)
        selected.extend(extra_picked)

    return selected


def extract_questions(questions, dan_count=40, duo_count=30, pan_count=30,
                      indefinite_count=0, shuffle_types=False):
    """
    从题库中按题型比例抽取题目（含优先级排序：错题 > 未做题 > 答对题）
    - 按指定数量抽取每种题型
    - 不足时全部抽取
    - 默认按 单选→多选→判断→不定项 顺序排列（不混排）
    - shuffle_types=True 时打乱题型顺序（保持同类题内部连续）
    - 支持不定项选择题 (indefinite)
    """
    # 预加载辅助数据（各题型抽取复用同一份，减少 I/O）
    stats = load_question_stats()

    singles = [q for q in questions if q["type"] == "single"]
    multis = [q for q in questions if q["type"] == "multi"]
    judges = [q for q in questions if q["type"] == "judge"]
    indefinites = [q for q in questions if q["type"] == "indefinite"]

    selected_s = _priority_sample(singles, min(dan_count, len(singles)), None, stats)
    selected_m = _priority_sample(multis, min(duo_count, len(multis)), None, stats)
    selected_j = _priority_sample(judges, min(pan_count, len(judges)), None, stats)
    selected_i = _priority_sample(indefinites, min(indefinite_count, len(indefinites)), None, stats)

    if shuffle_types:
        blocks = []
        if selected_s:
            blocks.append(("single", selected_s))
        if selected_m:
            blocks.append(("multi", selected_m))
        if selected_j:
            blocks.append(("judge", selected_j))
        if selected_i:
            blocks.append(("indefinite", selected_i))
        random.shuffle(blocks)
        selected = []
        for _, block in blocks:
            selected.extend(block)
    else:
        selected = selected_s + selected_m + selected_j + selected_i

    return selected


# ============================
# 题目答题统计（每道题存储答对和答错次数）
# ============================

QUESTION_STATS_FILE = DATA_DIR / "question_stats.json"


def load_question_stats():
    """加载题目答题统计"""
    ensure_dirs()
    if QUESTION_STATS_FILE.exists():
        with open(QUESTION_STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_question_stats(stats):
    """保存题目答题统计"""
    ensure_dirs()
    with open(QUESTION_STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

def get_question_stats(question_id):
    """获取某道题的答题统计"""
    stats = load_question_stats()
    return stats.get(question_id, {"correct_count": 0, "wrong_count": 0, "last_answer_time": None, "last_correct": None})


def get_all_question_stats():
    """获取所有题的答题统计"""
    return load_question_stats()


def clear_question_stats(question_id=None):
    """清空答题统计（指定ID或全部）"""
    if question_id:
        stats = load_question_stats()
        stats.pop(question_id, None)
        save_question_stats(stats)
    else:
        save_question_stats({})


# ============================
# 专项训练 - 按知识板块抽取题目
# ============================

def extract_questions_by_category(questions, category, dan_count=30, duo_count=20, pan_count=10):
    """
    从指定知识板块中按题型抽取题目（含优先级排序：错题 > 新题 > 旧题）
    - category: 知识板块名称（如"心理学导论"）
    - dan_count: 单选题数
    - duo_count: 多选题数
    - pan_count: 判断题数
    返回: list[dict] 按 单选→多选→判断 顺序排列
    """
    # 筛选指定板块的题目
    cat_questions = [
        q for q in questions
        if q.get("category", "") == category
    ]

    if not cat_questions:
        return []

    # 预加载辅助数据
    stats = load_question_stats()

    singles = [q for q in cat_questions if q["type"] == "single"]
    multis = [q for q in cat_questions if q["type"] == "multi"]
    judges = [q for q in cat_questions if q["type"] == "judge"]

    selected_s = _priority_sample(singles, min(dan_count, len(singles)), None, stats)
    selected_m = _priority_sample(multis, min(duo_count, len(multis)), None, stats)
    selected_j = _priority_sample(judges, min(pan_count, len(judges)), None, stats)

    return selected_s + selected_m + selected_j


def get_all_categories(questions):
    """
    获取所有知识板块及其题数统计
    返回: dict {板块名: {total, single, multi, judge}}
    """
    cats = {}
    for q in questions:
        cat = q.get("category", "其他")
        if cat not in cats:
            cats[cat] = {"total": 0, "single": 0, "multi": 0, "judge": 0}
        cats[cat]["total"] += 1
        if q["type"] == "single":
            cats[cat]["single"] += 1
        elif q["type"] == "multi":
            cats[cat]["multi"] += 1
        elif q["type"] == "judge":
            cats[cat]["judge"] += 1
    return cats


def extract_questions_by_super(questions, super_category, dan_count=30, duo_count=20, pan_count=30,
                                indefinite_count=0, shuffle_types=False):
    """
    按超类（心理学综合/咨询实务）从题库中按题型抽取题目
    - 各子知识板块均匀分配配额，避免题库大的板块挤压小板块
    - 板块内按优先级排序：错题 > 新题 > 旧题
    - super_category: "心理学综合" 或 "咨询实务"
    """
    sub_categories = SUPER_CATEGORY_MAP.get(super_category, [])
    if not sub_categories:
        return []

    # 筛选属于该超类的所有题目
    filtered = [
        q for q in questions
        if q.get("category", "") in sub_categories
    ]
    if not filtered:
        return []

    # 预加载辅助数据（所有题型复用同一份）
    stats = load_question_stats()

    # 按题型分到各板块
    singles_by_cat = {}
    multis_by_cat = {}
    judges_by_cat = {}
    indefinites_by_cat = {}

    for q in filtered:
        cat = q.get("category", "")
        if q["type"] == "single":
            singles_by_cat.setdefault(cat, []).append(q)
        elif q["type"] == "multi":
            multis_by_cat.setdefault(cat, []).append(q)
        elif q["type"] == "judge":
            judges_by_cat.setdefault(cat, []).append(q)
        elif q["type"] == "indefinite":
            indefinites_by_cat.setdefault(cat, []).append(q)

    # 确保所有子类别都有 key（即使该类别没有该题型）
    for cat in sub_categories:
        singles_by_cat.setdefault(cat, [])
        multis_by_cat.setdefault(cat, [])
        judges_by_cat.setdefault(cat, [])
        indefinites_by_cat.setdefault(cat, [])

    selected_s = _balanced_sample_by_type(singles_by_cat, min(dan_count, sum(len(v) for v in singles_by_cat.values())), None, stats)
    selected_m = _balanced_sample_by_type(multis_by_cat, min(duo_count, sum(len(v) for v in multis_by_cat.values())), None, stats)
    selected_j = _balanced_sample_by_type(judges_by_cat, min(pan_count, sum(len(v) for v in judges_by_cat.values())), None, stats)
    selected_i = _balanced_sample_by_type(indefinites_by_cat, min(indefinite_count, sum(len(v) for v in indefinites_by_cat.values())), None, stats)

    if shuffle_types:
        blocks = []
        if selected_s:
            blocks.append(("single", selected_s))
        if selected_m:
            blocks.append(("multi", selected_m))
        if selected_j:
            blocks.append(("judge", selected_j))
        if selected_i:
            blocks.append(("indefinite", selected_i))
        random.shuffle(blocks)
        selected = []
        for _, block in blocks:
            selected.extend(block)
    else:
        selected = selected_s + selected_m + selected_j + selected_i

    return selected


def check_answer(question_type, user_answer, correct_answer):
    """
    判断答案是否正确
    返回: (是否正确, 详细信息)
    """
    if question_type in ("single", "judge"):
        return user_answer.strip().upper() == correct_answer.strip().upper()
    elif question_type in ("multi", "indefinite"):
        user_set = set(user_answer.strip().upper().replace(" ", ""))
        correct_set = set(correct_answer.strip().upper().replace(" ", ""))
        return user_set == correct_set
    return False


def get_answer_display(question_type, correct_answer, options):
    """
    获取正确答案的显示文本
    """
    if question_type == "judge":
        return "正确" if correct_answer == "A" else "错误"
    elif question_type in ("multi", "indefinite"):
        parts = []
        for k in correct_answer:
            if k in options:
                parts.append(f"{k}: {options[k]}")
        return "、".join(parts)
    else:
        return f"{correct_answer}: {options.get(correct_answer, '')}"

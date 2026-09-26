"""
数据管理器 - 管理题库、错题库、配置、答题记录、考试记录
            通过 DataAccess 抽象层访问数据（当前使用 SQLite）

单库多租户（2026-09-24 起）：
  全系统只连一个库 data/exmsys.db，不再有「每用户一个 db 文件」。
  用户隔离靠 DataAccess 内部的 user_id / owner_id，路由由 set_current_user() 完成。
"""
import os
import random
import shutil
import time
from pathlib import Path
from datetime import datetime

from utils.data_access import get_data_access, SQLITE_DB, PUBLIC_OWNER

# 延迟初始化的 DAO 对象（单库，进程内单例）
_dao = None

# ---- 多用户支持：当前用户（同一库内按 user_id 隔离）----
_current_user_id = None


def set_current_user(user_id: str):
    """切换当前用户（登录/建号后调用）：把用户上下文写入 DAO，并重置缓存。

    单库多租户下不再「切库文件」，而是把 user_id 交给 DataAccess —— 所有读写
    自动带上该用户的条件，用户之间互不可见。

    ⚠️ 幂等设计（2026-09-14）：若当前**已经**是同一用户，则直接返回，
    不重建 DAO、不清缓存。这样 app.py 可以在**每一帧**安全地调用它，用于
    校正跨 session 的模块级全局变量（_current_user_id 会被其他 session 覆盖），
    同时不带来任何额外开销。

    为什么必须每帧校正：_current_user_id 是模块级全局变量，Streamlit 多个
    session（多标签页/多浏览器）共享同一进程，会互相覆盖；且代码热重载会
    把它重置为 None。任一情况都会让后续读库落到「无用户」上下文，表现为"题库为空"。
    """
    global _current_user_id, _dao
    if _current_user_id == user_id and _dao is not None:
        return  # 已就位，保持缓存与 DAO 复用（避免每帧读盘/重建）
    _current_user_id = user_id
    _dao = get_data_access(user_id=user_id)  # 单例；此处顺带同步用户上下文
    invalidate_rerun_cache()
    _invalidate_version_cache()


def get_current_user_id():
    """当前用户 ID（未设置时返回 None）"""
    return _current_user_id


def get_current_db_path():
    """当前数据库路径（单库模式下恒定；保留供备份/调试使用）"""
    return str(SQLITE_DB)


def _get_dao():
    """获取数据访问单例（已绑定当前用户上下文）"""
    global _dao
    if _dao is None:
        _dao = get_data_access(user_id=_current_user_id)
    return _dao


# ---- 题库版本号（全局，per-rerun 缓存）----
# 版本号只在题库写操作（导入/替换/清空）时递增，答题/统计过程不变。
# 改造前是「每次 rerun 都实时读盘」（每次新建连接 + 4 条 PRAGMA + SELECT，
# 实测约 259ms/次，是勾选答案卡顿的头号元凶）。
# 现在缓存到本次 rerun 结束 —— 由 invalidate_rerun_cache() 在每个渲染帧开始时清空。
# 这样做的关键收益：**任何人对题库的改动，别人下一次刷新（rerun）就能看到**。
_version_cache_value = None


def get_questions_version() -> int:
    """获取当前题库数据版本号（供 app.py 检测题库是否变更）"""
    global _version_cache_value
    if _version_cache_value is None:
        _version_cache_value = _get_dao().get_questions_version()
    return _version_cache_value


def _invalidate_version_cache():
    """题库版本号缓存失效（题库写操作 / set_current_user 时调用）"""
    global _version_cache_value
    _version_cache_value = None


# ---- per-rerun 缓存（同一 rerun 内复用全量数据，避免重复 I/O）----
# 注意：这些是**模块级全局变量**，Streamlit 多 session（多标签页/多浏览器）在同一
# 进程内共享，彼此会互相覆盖。因此每个缓存都记录其归属的 user_id（*_user），
# 读取时校验用户一致才复用，避免串号（读到别人的题库/统计）。
_rerun_cache_questions = None
_rerun_cache_questions_user = None
_rerun_cache_stats = {}  # 按 exam_type 分别缓存
_rerun_cache_stats_user = None
_rerun_cache_version = 0


def invalidate_rerun_cache():
    """每次 Streamlit rerun 开始时调用，清除数据缓存"""
    global _rerun_cache_questions, _rerun_cache_questions_user
    global _rerun_cache_stats, _rerun_cache_stats_user, _rerun_cache_version
    global _version_cache_value
    _rerun_cache_questions = None
    _rerun_cache_questions_user = None
    _rerun_cache_stats = {}
    _rerun_cache_stats_user = None
    _rerun_cache_version += 1
    _version_cache_value = None  # 每帧重新读一次题库版本号（跨用户改动可见）


# 数据目录（可用 EXMSYS_DATA_DIR 覆盖，与 data_access 保持一致：
# 云端部署挂载卷、自动化测试用副本时靠它改道）
DATA_DIR = Path(os.environ.get("EXMSYS_DATA_DIR") or
                (Path(__file__).resolve().parent.parent / "data"))
BACKUP_DIR = DATA_DIR / "backup"
DRAFTS_DIR = DATA_DIR / "drafts"

# 题库类型映射（短码 → 显示名）
EXAM_TYPE_LABELS = {
    "心理学会咨询师四级": "心理学会咨询师四级",
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
    "retention_days_threshold": 5,
    "last_import_files": [],
}


def get_retention_threshold():
    """获取遗忘预警阈值（距上次答对 > 此天数触发预警）"""
    config = load_config()
    return config.get("retention_days_threshold", 5)


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
    # 心理协会咨询师初级专用（单科制）
    "junior_psychology": {
        "name": "心理学综合",
        "time_minutes": 120,
        "single_count": 200,
        "single_score": 0.2,
        "multi_count": 100,
        "multi_score": 0.6,
        "judge_count": 0,
        "judge_score": 0,
        "indefinite_count": 0,
        "indefinite_score": 0,
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
    """加载用户可见题库（公共题库 ∪ 自己的私人题库），per-rerun 缓存

    缓存按 user_id 校验：若缓存来自别的用户（模块级全局变量被其他 session
    覆盖），则强制重读，避免串号或读到空题库。
    """
    global _rerun_cache_questions, _rerun_cache_questions_user
    if _rerun_cache_questions is not None and _rerun_cache_questions_user == _current_user_id:
        return _rerun_cache_questions
    _rerun_cache_questions = _get_dao().load_questions()
    _rerun_cache_questions_user = _current_user_id
    return _rerun_cache_questions


def import_questions(questions, owner_id=None, mode="append", exam_type=None):
    """导入题目（按 owner 作用域 upsert，不再全量重建题库）

    Args:
        questions: 解析出的题目列表（含 md5）
        owner_id: 目标 owner。None = 当前用户的私人题库；
                  PUBLIC_OWNER（'__public__'）= 公共题库，仅管理员使用。
        mode: 'append' 只新增与更新（默认，安全）；'replace' 额外删除未匹配到的旧题。
        exam_type: 题目未自带 exam_type 时的兜底题库类型。

    Returns:
        {"added": n, "updated": n, "unchanged": n, "removed": n, "skipped": n, "log": [...]}
    """
    report = _get_dao().import_questions(questions, owner_id=owner_id, mode=mode, exam_type=exam_type)
    invalidate_rerun_cache()
    _invalidate_version_cache()
    return report


def clear_questions(owner_id=None, exam_type=None):
    """清空指定 owner 的题库，返回删除行数

    owner_id=None → 只清空当前用户自己的题（公共题库不受影响）；
    owner_id=PUBLIC_OWNER → 清空公共题库（管理员专用，影响所有用户）。
    """
    n = _get_dao().clear_questions(owner_id=owner_id, exam_type=exam_type)
    invalidate_rerun_cache()
    _invalidate_version_cache()
    return n


def count_questions(owner_id=None, exam_type=None):
    """统计指定 owner 的题目数（owner_id=PUBLIC_OWNER 可查公共题库）"""
    return _get_dao().count_questions(owner_id=owner_id, exam_type=exam_type)


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
        "案例题": sum(1 for q in qs if q["type"] == "案例题"),
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
# 案例题管理
# ============================

def load_case_studies(exam_type=None):
    """加载案例（可按 exam_type 过滤）"""
    return _get_dao().load_case_studies(exam_type=exam_type)


def save_case_studies(case_studies, owner_id=None):
    """批量保存案例背景（owner_id=None 表示当前用户自己的题库）"""
    return _get_dao().save_case_studies(case_studies, owner_id=owner_id)


def get_case_sub_questions(case_id):
    """获取某个案例的全部子题"""
    return _get_dao().get_case_sub_questions(case_id)


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

def load_wrong_questions(exam_type=None):
    """加载错题库（通过 DataAccess 抽象层）
    
    Args:
        exam_type: 考试类型过滤。None 时返回全部。
    """
    return _get_dao().load_wrong_questions(exam_type=exam_type)


def save_wrong_questions(wrong_list, exam_type=None):
    """保存错题库（通过 DataAccess 抽象层）
    
    Args:
        wrong_list: 错题 ID 列表（元素可以是 str 或 (qid, exam_type) 元组）
        exam_type: 考试类型。若 wrong_list 元素是 str，则此参数用于自动填充。
    """
    _get_dao().save_wrong_questions(wrong_list, exam_type=exam_type)


def add_wrong_record(question_id, user_answer):
    """
    记录错题 - 以最后一次答题为准
    新规则：答错次数 >= 答对次数 才记入错题本
    错题库仅存储 question_id 列表，统计数字统一从 question_stats 表读取

    实现上委托给 batch_update_wrong_and_stats，确保错题库和统计在同一事务内更新。
    """
    batch_update_wrong_and_stats(
        wrong_qids=[(question_id, user_answer)],
        correct_qids=[],
        stats_updates=[(question_id, False)],
    )


def add_correct_record(question_id):
    """
    记录答对 - 以最后一次答题为准
    新规则：答对后若 答错次数 < 答对次数，从错题本移除
    错题库仅存储 question_id 列表

    实现上委托给 batch_update_wrong_and_stats，确保错题库和统计在同一事务内更新。
    """
    batch_update_wrong_and_stats(
        wrong_qids=[],
        correct_qids=[question_id],
        stats_updates=[(question_id, True)],
    )


# ============================
# 批量操作 - 减少数据库 I/O 次数，提升性能
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


def batch_update_wrong_and_stats(wrong_qids, correct_qids, stats_updates,
                                      uncertain_map=None, exam_record=None):
    """
    批量更新错题库和题目答题统计（委托 DAO 单事务完成）。
    新规则：答错次数 >= 答对次数 → 记入错题本
    - wrong_qids: list of (question_id, user_answer) 本次答错的
    - correct_qids: list of question_id 本次答对的
    - stats_updates: list of (question_id, is_correct) 需要更新统计的
    - uncertain_map: dict {qid: bool} 答题者自评不确定性标记
    - exam_record: 可选，考试记录 dict，在同一事务内写入
    """
    global _rerun_cache_stats
    _get_dao().batch_update_wrong_and_stats(
        wrong_qids, correct_qids, stats_updates,
        uncertain_map=uncertain_map,
        exam_record=exam_record,
    )
    # 写入后立即清除 rerun 缓存，确保下次 load_question_stats() 读到最新数据
    _rerun_cache_stats = {}


def _recalc_mastery_fields(stats_entry):
    """
    根据答题统计重新计算掌握度等级、置信度、不稳定标记
    直接修改传入的 stats_entry 字典
    """
    cc = stats_entry.get("correct_count", 0)
    wc = stats_entry.get("wrong_count", 0)
    total = cc + wc
    history = stats_entry.get("answer_history", [])

    if total == 0:
        stats_entry["mastery_level"] = 0
        stats_entry["confidence"] = 0.0
        stats_entry["unstable"] = False
        stats_entry["retention_due"] = False
        return

    accuracy = cc / total if total > 0 else 0

    # ---- 掌握度等级 ----
    if accuracy >= 0.9 and total >= 5 and len(history) >= 3 and all(history[-3:]):
        level = 5
    elif accuracy >= 0.8 and total >= 3:
        level = 4
    elif accuracy >= 0.6:
        level = 3
    elif total > 2:
        level = 2
    else:
        level = 1

    stats_entry["mastery_level"] = level

    # ---- 置信度 (0.0–1.0) ----
    sample_factor = min(total / 10, 1.0)
    changes = sum(1 for i in range(1, len(history)) if history[i] != history[i - 1])
    stability = 1.0 - min(changes / max(len(history), 1), 1.0)
    confidence = round(sample_factor * 0.6 + stability * 0.4, 2)
    stats_entry["confidence"] = confidence

    # ---- 不稳定检测 ----
    has_correct = any(h for h in history)
    last_wrong = len(history) > 0 and not history[-1]
    changes_count = sum(1 for i in range(1, len(history)) if history[i] != history[i - 1])
    unstable = False
    if has_correct and last_wrong and changes_count < 2:
        unstable = True  # 消退型
    elif changes_count >= 2:
        unstable = True  # 波动型
    stats_entry["unstable"] = unstable


def batch_add_answer_records(records, exam_type=None):
    """
    批量追加答题过程记录（通过 DataAccess 抽象层）
    """
    _get_dao().batch_add_answer_records(records, exam_type=exam_type)


def get_top_wrong_questions(count=50, exam_type=None):
    """
    获取答错次数最多的N道题（含完整题目信息）
    改为直接调用 DAO 的 SQL 层排序+Limit，避免三重全量加载
    返回: list[tuple(question_dict, wrong_count)]
    """
    items = _get_dao().get_all_wrong_with_stats(exam_type, limit=count)
    result = []
    for item in items:
        q = {
            "id": item["question_id"],
            "question": item["question"],
            "type": item["type"],
            "options": item["options"],
            "answer": item["answer"],
            "explanation": item.get("explanation", ""),
            "category": item.get("category", ""),
            "exam_type": exam_type or "心理学会咨询师四级",
            "case_study_id": item.get("case_study_id"),
            "case_background": item.get("case_background", ""),
        }
        result.append((q, item["wrong_count"]))
    return result


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
    委托 DAO 层单连接 SQL JOIN 版本，避免三重全量加载"""
    return _get_dao().get_wrong_stats(exam_type)


def get_all_wrong_with_stats(exam_type=None):
    """
    获取所有错题，附带答题统计，按易错程度排序
    排序规则：(wrong_count - correct_count) 由大到小
    可按 exam_type 过滤
    统计数字统一从 question_stats 表读取
    返回: list[dict]，每项包含完整题目信息 + wrong_count / correct_count / diff
    """
    wrong_qids = _extract_qids_from_wrong_list(load_wrong_questions())
    questions = load_questions()
    q_map = {q["id"]: q for q in questions}
    stats = load_question_stats()

    type_labels = {"single": "单选", "multi": "多选", "judge": "判断", "案例题": "案例题", "indefinite": "不定项"}

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
            "case_study_id": q.get("case_study_id"),
            "case_background": q.get("case_background") or "",
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
    """加载配置（通过 DataAccess 抽象层）"""
    return _get_dao().load_config()


def save_config(config):
    """保存配置（通过 DataAccess 抽象层）"""
    _get_dao().save_config(config)


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
        # 三级题库板块
        "心理咨询通用技术", "心理测量与心理评估",
        "认知行为咨询方法", "人本主义咨询方法",
        "团体心理辅导", "心理咨询伦理", "心理危机干预",
    ],
}

# 掌握度等级标签（0-5）
MASTERY_LABELS = {
    0: "未学习",
    1: "初识",
    2: "学习中",
    3: "基本掌握",
    4: "掌握",
    5: "熟练",
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

def load_answer_records(exam_type=None):
    """加载答题过程记录（通过 DataAccess 抽象层）"""
    return _get_dao().load_answer_records(exam_type=exam_type)


def save_answer_records(records):
    """保存答题过程记录（通过 DataAccess 抽象层）"""
    _get_dao().save_answer_records(records)


def add_answer_record(question_id, user_answer, is_correct, mode="study", session_id=""):
    """
    记录每次答题的过程，无论对错（通过 DataAccess 抽象层）
    """
    _get_dao().batch_add_answer_records([{
        "question_id": question_id,
        "user_answer": user_answer,
        "is_correct": is_correct,
        "mode": mode,
        "session_id": session_id,
    }])


# ============================
# 考试记录
# ============================

def load_exam_records(exam_type=None):
    """加载考试记录（通过 DataAccess 抽象层）
    
    Args:
        exam_type: 考试类型过滤。None 时返回全部。
    """
    return _get_dao().load_exam_records(exam_type=exam_type)


def save_exam_record(record, exam_type=None):
    """保存一条考试记录（通过 DataAccess 抽象层）"""
    _get_dao().append_exam_record(record, exam_type=exam_type)


# ============================
# 背题历史记录（每次背题会话的持久化）
# ============================

def load_study_records(exam_type=None):
    """加载背题历史记录（通过 DataAccess 抽象层）"""
    return _get_dao().load_study_records(exam_type=exam_type)


def save_study_record(record, exam_type=None):
    """保存一条背题历史记录（通过 DataAccess 抽象层）"""
    _get_dao().append_study_record(record, exam_type=exam_type)


def update_study_record(session_id, update_data):
    """更新指定背题会话的记录（通过 DataAccess 抽象层）"""
    _get_dao().update_study_record(session_id, update_data)


def find_study_record(session_id):
    """查找指定会话的背题记录（通过 DataAccess 抽象层）"""
    return _get_dao().find_study_record(session_id)


# ============================
# 模拟考试记录（固定两科，不可配置）
# ============================


def load_mock_exam_records(exam_type=None):
    """加载模拟考试记录（通过 DataAccess 抽象层）
    
    Args:
        exam_type: 考试类型过滤。None 时返回全部。
    """
    return _get_dao().load_mock_exam_records(exam_type=exam_type)


def save_mock_exam_record(record, exam_type=None):
    """保存一条模拟考试记录（通过 DataAccess 抽象层）"""
    _get_dao().append_mock_exam_record(record, exam_type=exam_type)


# ============================
# 备份
# ============================

def backup_data():
    """备份数据库文件（单库模式：备份整个 exmsys.db）"""
    ensure_dirs()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    src = Path(SQLITE_DB)
    if src.exists():
        dst = BACKUP_DIR / f"{timestamp}_exmsys.db"
        shutil.copy2(src, dst)
    return timestamp


# ============================
# 题目抽取工具
# ============================

def _priority_sample(question_list, count, wrong_ids=None, stats=None):
    """
    按优先级从题目列表中抽取 count 道题。
    四级分组：
      Group 0（答错≥答对，仍在错题本）> Group 1（从未答过）> Group 2（仅答对1次/猜对防护）> Group 3（其余）
      Group 3 内部四级子排序：
        sub=0 遗忘预警（retention_due=True，距上次答对>=阈值天）> 
        sub=1 不稳定（消退型/波动型）> 
        sub=2 上次答错 > 
        sub=3 普通

    同级内部排序：正确率升序（低优先） → 答题次数升序（少优先） → wrong降序 → random
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
        total_ans = wrong + correct

        # 四级分组
        if wrong > 0 and wrong >= correct:
            group = 0  # 仍在错题本
        elif correct == 0 and wrong == 0:
            group = 1  # 从未答过
        elif correct == 1 and wrong == 0:
            group = 2  # 猜对防护（仅答对1次）
        else:
            group = 3  # 其余

        # Group 3 内部子排序
        sub = 3  # 默认普通
        if group == 3:
            retention_due = s.get("retention_due", False)
            unstable = s.get("unstable", False)
            last_correct = s.get("last_correct")
            if retention_due:
                sub = 0  # 遗忘预警最高
            elif unstable:
                sub = 1  # 不稳定次之
            elif last_correct is False:
                sub = 2  # 上次答错
            else:
                sub = 3

        accuracy = correct / total_ans if total_ans > 0 else 0.0

        # 排序: group → sub → accuracy↑ → total_ans↑ → -wrong↓ → random
        scored.append((group, sub, accuracy, total_ans, -wrong, random.random(), q))

    scored.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4], x[5]))

    return [q for _, _, _, _, _, _, q in scored[:count]]


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
                      indefinite_count=0, shuffle_types=False, stats=None):
    """
    从题库中按题型比例抽取题目（含优先级排序：错题 > 未做题 > 答对题）
    - 按指定数量抽取每种题型
    - 不足时全部抽取
    - 默认按 单选→多选→判断→案例题 顺序排列（不混排）
    - shuffle_types=True 时打乱题型顺序（保持同类题内部连续）
    - 支持案例题 (案例题)
    - stats: 可选，预加载的答题统计，避免重复加载
    """
    # 复用已加载的统计（避免重复 I/O）
    if stats is None:
        stats = load_question_stats()

    singles = [q for q in questions if q["type"] == "single"]
    multis = [q for q in questions if q["type"] == "multi"]
    judges = [q for q in questions if q["type"] == "judge"]
    indefinites = [q for q in questions if q["type"] == "案例题"]

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
            blocks.append(("案例题", selected_i))
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


def load_question_stats(exam_type=None):
    """加载题目答题统计（通过 DataAccess 抽象层，per-rerun 缓存按 exam_type 隔离）

    缓存同时按 user_id 校验，防止模块级全局缓存被其他 session 覆盖后
    读到别的用户的统计（串号）。
    """
    global _rerun_cache_stats, _rerun_cache_stats_user
    # 防御性初始化：如果缓存被意外设为 None，自动恢复为空字典
    if _rerun_cache_stats is None:
        _rerun_cache_stats = {}
    # 用户切换（含跨 session 覆盖）时，丢弃旧用户的统计缓存
    if _rerun_cache_stats_user != _current_user_id:
        _rerun_cache_stats = {}
        _rerun_cache_stats_user = _current_user_id
    cache_key = exam_type or "__all__"
    if cache_key in _rerun_cache_stats:
        return _rerun_cache_stats[cache_key]
    _rerun_cache_stats[cache_key] = _get_dao().load_question_stats(exam_type=exam_type)
    return _rerun_cache_stats[cache_key]


def save_question_stats(stats, exam_type=None):
    """保存题目答题统计（通过 DataAccess 抽象层）"""
    global _rerun_cache_stats
    _get_dao().save_question_stats(stats, exam_type=exam_type)
    # 写入后清除缓存，确保下次读到最新数据
    _rerun_cache_stats = {}

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


def load_uncertain_questions(exam_type=None):
    """加载所有标记为不确定的题目，按 self_uncertainty 降序"""
    return _get_dao().load_uncertain_questions(exam_type=exam_type)


def clear_uncertain_mark(question_id):
    """清除某道题的不确定标记（设置 self_uncertainty = 0）"""
    _get_dao().clear_uncertain_mark(question_id)


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
        elif q["type"] == "案例题":
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
            blocks.append(("案例题", selected_i))
        random.shuffle(blocks)
        selected = []
        for _, block in blocks:
            selected.extend(block)
    else:
        selected = selected_s + selected_m + selected_j + selected_i

    return selected



def _sanitize_answer(text):
    """清洗答案中的不可见/干扰字符（零宽空格、BOM等），防止 Word 文档导入时的格式污染"""
    if not text:
        return ""
    # 移除零宽空格和其他常见不可见干扰字符
    text = text.replace("\u200b", "")  # zero-width space
    text = text.replace("\u200c", "")  # zero-width non-joiner
    text = text.replace("\u200d", "")  # zero-width joiner
    text = text.replace("\u200e", "")  # left-to-right mark
    text = text.replace("\u200f", "")  # right-to-left mark
    text = text.replace("\ufeff", "")  # BOM / zero-width no-break space
    text = text.replace("\ufe0f", "")  # variation selector
    # 不换行空格 → 普通空格
    text = text.replace("\u00a0", " ")
    return text


def check_answer(question_type, user_answer, correct_answer):
    """
    判断答案是否正确
    返回: (是否正确, 详细信息)
    """
    user_answer = _sanitize_answer(user_answer)
    correct_answer = _sanitize_answer(correct_answer)
    if question_type in ("single", "judge"):
        return user_answer.strip().upper() == correct_answer.strip().upper()
    elif question_type in ("multi", "案例题"):
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
    elif question_type in ("multi", "案例题"):
        parts = []
        for k in correct_answer:
            if k in options:
                parts.append(f"{k}: {options[k]}")
        return "、".join(parts)
    else:
        return f"{correct_answer}: {options.get(correct_answer, '')}"


# ============================
# 草稿系统（答题中途保存/恢复）
# ============================

def _ensure_drafts_dir():
    """确保草稿目录存在"""
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)


def save_draft(prefix, draft_id, data, exam_type=None):
    """保存/覆盖答题草稿（通过 DataAccess 抽象层）"""
    _get_dao().save_draft(prefix, draft_id, data, exam_type=exam_type)


def load_drafts(prefix, exam_type=None):
    """加载指定前缀的所有草稿（通过 DataAccess 抽象层）"""
    return _get_dao().load_drafts(prefix, exam_type=exam_type)


def delete_draft(prefix, draft_id):
    """删除指定草稿（通过 DataAccess 抽象层）"""
    _get_dao().delete_draft(prefix, draft_id)


# ============================
# 掌握度分布分析
# ============================

def get_mastery_distribution(questions, exam_type=None):
    """
    计算各知识板块的掌握度分布。
    返回:
      {
        "by_category": {cat: {total, mastery_counts, studied_rate, avg_mastery, retention_due, unstable}},
        "retention_list": [{question_id, question, category, days_since_correct, mastery_level}],
        "unstable_list": [{question_id, question, category, unstable_type, history, confidence, mastery_level}],
      }
    """
    from datetime import datetime as dt

    if exam_type:
        questions = [q for q in questions if q.get("exam_type") == exam_type]

    stats = load_question_stats()
    now = dt.now()

    # 初始化各板块
    cats = {}
    qid_to_cat = {}
    for q in questions:
        cat = q.get("category", "其他")
        qid_to_cat[q.get("id", "")] = cat
        if cat not in cats:
            cats[cat] = {"total": 0, "mastery_counts": [0] * 6,
                         "retention_due": 0, "unstable": 0}

    for q in questions:
        qid = q.get("id", "")
        cat = qid_to_cat.get(qid, "其他")
        if cat in cats:
            cats[cat]["total"] += 1

    retention_list = []
    unstable_list = []

    # 一次遍历计算所有统计
    for q in questions:
        qid = q.get("id", "")
        cat = qid_to_cat.get(qid, "其他")
        s = stats.get(qid)

        # 掌握度等级（从 stats 读取，batch_update 已预计算）
        level = s.get("mastery_level", 0) if s else 0
        if cat in cats:
            cats[cat]["mastery_counts"][level] += 1

        # retention_due（动态值）
        if s and s.get("retention_due"):
            if cat in cats:
                cats[cat]["retention_due"] += 1
            days_since = 0
            last_time = s.get("last_answer_time")
            if last_time:
                try:
                    days_since = (now - dt.fromisoformat(last_time)).days
                except (ValueError, TypeError):
                    pass
            retention_list.append({
                "question_id": qid,
                "question": q.get("question", "")[:50],
                "category": cat,
                "days_since_correct": days_since,
                "mastery_level": level,
            })

        # unstable
        if s and s.get("unstable"):
            if cat in cats:
                cats[cat]["unstable"] += 1
            history = s.get("answer_history", [])
            unstable_type = "消退型" if any(history) and (len(history) > 0 and not history[-1]) else "波动型"
            changes = sum(1 for i in range(1, len(history)) if history[i] != history[i - 1])
            if not any(history):
                unstable_type = "全错"
            elif not history[-1] and changes < 2:
                unstable_type = "消退型"
            unstable_list.append({
                "question_id": qid,
                "question": q.get("question", "")[:50],
                "category": cat,
                "unstable_type": unstable_type,
                "history": history,
                "confidence": s.get("confidence", 0.0),
                "mastery_level": level,
            })

    # 后处理：计算 studied_rate, avg_mastery
    by_category = {}
    for cat, d in cats.items():
        total = d["total"]
        counts = d["mastery_counts"]
        studied = sum(counts[1:])
        studied_rate = studied / total * 100 if total > 0 else 0
        avg_mastery = sum(i * counts[i] for i in range(6)) / max(total, 1)
        by_category[cat] = {
            "total": total,
            "mastery_counts": counts,
            "studied_rate": studied_rate,
            "avg_mastery": round(avg_mastery, 1),
            "retention_due": d["retention_due"],
            "unstable": d["unstable"],
        }

    # 排序：retention_list 按天数降序，unstable_list 按置信度升序
    retention_list.sort(key=lambda x: x["days_since_correct"], reverse=True)
    unstable_list.sort(key=lambda x: x["confidence"])

    return {
        "by_category": by_category,
        "retention_list": retention_list,
        "unstable_list": unstable_list,
    }


def clear_exam_records(exam_type: str) -> dict:
    """清空指定题库的所有答题记录（保留题目不变）

    清除范围：answer_records, question_stats, wrong_questions,
              exam_records, mock_exam_records, study_records, drafts

    Args:
        exam_type: 题库类型，如 "心理协会咨询师初级"

    Returns:
        dict: 各表删除的行数
    """
    return _get_dao().clear_exam_records(exam_type)

"""
数据访问层 — 抽象数据源，支持 SQLite / Supabase 切换

单库多租户架构（2026-09-24 起）
================================================================
· 全系统只有【一个】数据库 data/exmsys.db，程序只连这一个库。
· 题库分层：questions.owner_id = '__public__' → 公共题库（初始题库，仅管理员可改）；
           questions.owner_id = '<user_id>'  → 该用户的私人题库（可自行导入/清空）。
           用户可见题集 = 公共题库 ∪ 自己的私人题库。
· 用户数据（统计 / 错题 / 答题记录 / 考试记录 / 背题记录 / 草稿 / 配置）
  全部通过 user_id 列隔离，同库共存、互不可见。
· 题目 ID 一经分配【永不变更】：管理员直接改库修改题目内容不会影响任何用户的
  统计、错题与历史记录 —— 这是「用户题库通过 ID 关联初始题库、初始题库修改后
  用户端自动跟随」的实现基础。

为什么公共 owner 用哨兵值 '__public__' 而不是 NULL：
  SQLite 中 NULL 互不相等，UNIQUE(owner_id, md5) 会因此失效（公共题库去重坏掉）。
"""

import difflib
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from datetime import datetime

# 常量（本地定义，避免循环导入）
# 数据目录可用环境变量 EXMSYS_DATA_DIR 覆盖 —— 两个用途：
#   1. 云端部署时把数据放到挂载卷/容器外部（不必改代码）
#   2. 自动化测试指向一份**副本**，避免把测试用户写进真实库
DATA_DIR = Path(os.environ.get("EXMSYS_DATA_DIR") or
                (Path(__file__).resolve().parent.parent / "data"))

# SQLite 数据库路径（单库：全系统唯一）
SQLITE_DB = DATA_DIR / "exmsys.db"

# 公共题库 owner 哨兵值
PUBLIC_OWNER = "__public__"

# 默认题库类型
DEFAULT_EXAM_TYPE = "心理学会咨询师四级"

# 题库数据版本号的 config 键名（存 app_config，全局共享）
QUESTIONS_VERSION_KEY = "_questions_data_version"

# 遗忘预警阈值缓存（按 (库路径, 用户) 隔离）
_retention_threshold_cache: dict = {}


def get_retention_threshold(db_path=None, user_id=None):
    """从数据库 user_config 读取遗忘预警阈值（距上次答对 > 此天数触发预警）

    Args:
        db_path: 库路径；None 时使用单库默认路径。
        user_id: 用户 ID（配置按用户隔离）。
    """
    path = str(db_path) if db_path else str(SQLITE_DB)
    key = (path, user_id or "")
    if key in _retention_threshold_cache:
        return _retention_threshold_cache[key]
    try:
        conn = sqlite3.connect(path, timeout=5)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT value FROM user_config WHERE user_id = ? AND key = 'retention_days_threshold'",
                (user_id or "",),
            )
            row = cur.fetchone()
            value = json.loads(row[0]) if (row and row[0]) else 5
            _retention_threshold_cache[key] = int(value)
            return _retention_threshold_cache[key]
        finally:
            conn.close()
    except Exception:
        return 5  # 默认值


def invalidate_retention_cache():
    """清空遗忘阈值缓存（保存配置后调用）"""
    global _retention_threshold_cache
    _retention_threshold_cache = {}


# ========================================
# 题目内容指纹与稳定 ID
# ========================================

def _options_dict(value) -> dict:
    """把 options 归一成 dict —— 兼容两种来源：

      · parser 解析出来的题目：options 已经是 dict
      · 从 questions 表读回来的行：options 是 JSON 字符串

    缺了这一步，用数据库行去算内容指纹会直接 TypeError（str 没有 .items()）。
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            o = json.loads(value)
            return o if isinstance(o, dict) else {}
        except Exception:
            return {}
    return {}


def question_md5(q: dict) -> str:
    """题目内容指纹（与 utils/parser.py::_finalize_question 完全一致）

    用于判定「这是不是同一道题」。**两侧都要用它现算**：
    管理员直接改库修改内容后，questions.md5 列会与内容不一致
    （master 库里就有 2417/5118 条是这样的历史遗留），
    若拿「新题算出的 md5」去比「库里陈旧的 md5」会大面积漏配，
    导致重新导入时给旧题换新 ID、把用户历史打断。
    """
    content = ((q.get("question") or "") + str(sorted(_options_dict(q.get("options")).items()))
               + (q.get("answer") or ""))
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def make_question_id(owner_id: str, q: dict) -> str:
    """按 owner 作用域生成题目稳定 ID

    把 owner 一并纳入哈希，避免「用户导入的题」与「公共题库同一道题」
    （内容 md5 相同）产生 ID 撞车。
    """
    content = ((q.get("question") or "") + str(sorted(_options_dict(q.get("options")).items()))
               + (q.get("answer") or ""))
    return hashlib.md5(f"{owner_id}|{content}".encode("utf-8")).hexdigest()[:12]


# ========================================
# 抽象基类
# ========================================

class DataAccess:
    """数据访问抽象基类 — 所有数据操作接口

    说明：涉及题库的方法用 owner_id/user_id 限定作用域；None 表示「当前用户」。
    """

    # ---- 题库（owner 作用域）----
    def load_questions(self, exam_type=None, user_id=None) -> list:
        raise NotImplementedError

    def import_questions(self, questions: list, owner_id=None, mode: str = "append",
                         exam_type: str = None) -> dict:
        raise NotImplementedError

    def clear_questions(self, owner_id=None, exam_type: str = None) -> int:
        raise NotImplementedError

    def get_question_count(self, exam_type=None, user_id=None) -> dict:
        raise NotImplementedError

    def get_questions_by_type(self, question_type, exam_type=None, user_id=None) -> list:
        raise NotImplementedError

    def get_available_exam_types(self, user_id=None) -> list:
        raise NotImplementedError

    def get_questions_by_exam_type(self, exam_type, user_id=None) -> list:
        raise NotImplementedError

    # ---- 案例题 ----
    def load_case_studies(self, exam_type=None, user_id=None) -> list:
        raise NotImplementedError

    def save_case_studies(self, case_studies: list, owner_id=None) -> None:
        raise NotImplementedError

    def get_case_sub_questions(self, case_id: str, user_id=None) -> list:
        raise NotImplementedError

    # ---- 错题 ----
    def load_wrong_questions(self, exam_type=None, user_id=None) -> list:
        raise NotImplementedError

    def save_wrong_questions(self, wrong_list, exam_type=None, user_id=None) -> None:
        raise NotImplementedError

    def batch_update_wrong_and_stats(self, wrong_qids, correct_qids, stats_updates,
                                     uncertain_map=None, exam_record=None,
                                     exam_type=None, user_id=None) -> None:
        raise NotImplementedError

    def get_top_wrong_questions(self, count=50, exam_type=None, user_id=None) -> list:
        raise NotImplementedError

    def remove_wrong_question(self, question_id, user_id=None) -> None:
        raise NotImplementedError

    def clear_all_wrong(self, user_id=None) -> None:
        raise NotImplementedError

    def get_wrong_stats(self, exam_type=None, user_id=None) -> dict:
        raise NotImplementedError

    def get_all_wrong_with_stats(self, exam_type=None, limit=None, user_id=None) -> list:
        raise NotImplementedError

    # ---- 答题统计 ----
    def load_question_stats(self, exam_type=None, user_id=None) -> dict:
        raise NotImplementedError

    def save_question_stats(self, stats: dict, exam_type=None, user_id=None) -> None:
        raise NotImplementedError

    def get_question_stats(self, question_id, user_id=None) -> dict:
        raise NotImplementedError

    def clear_question_stats(self, question_id=None, user_id=None) -> None:
        raise NotImplementedError

    def load_uncertain_questions(self, exam_type=None, user_id=None) -> list:
        raise NotImplementedError

    def clear_uncertain_mark(self, question_id, user_id=None) -> None:
        raise NotImplementedError

    # ---- 答题记录 ----
    def load_answer_records(self, exam_type=None, user_id=None) -> list:
        raise NotImplementedError

    def save_answer_records(self, records: list, user_id=None) -> None:
        raise NotImplementedError

    def batch_add_answer_records(self, records: list, exam_type=None, user_id=None) -> None:
        raise NotImplementedError

    # ---- 考试记录 / 背题记录 / 模拟考试记录 ----
    def load_exam_records(self, exam_type=None, user_id=None) -> list:
        raise NotImplementedError

    def append_exam_record(self, record: dict, exam_type=None, user_id=None) -> None:
        raise NotImplementedError

    def load_study_records(self, exam_type=None, user_id=None) -> list:
        raise NotImplementedError

    def append_study_record(self, record: dict, exam_type=None, user_id=None) -> None:
        raise NotImplementedError

    def update_study_record(self, session_id: str, data: dict, user_id=None) -> None:
        raise NotImplementedError

    def find_study_record(self, session_id: str, user_id=None) -> dict:
        raise NotImplementedError

    def load_mock_exam_records(self, exam_type=None, user_id=None) -> list:
        raise NotImplementedError

    def append_mock_exam_record(self, record: dict, exam_type=None, user_id=None) -> None:
        raise NotImplementedError

    # ---- 配置 ----
    def load_config(self, user_id=None) -> dict:
        raise NotImplementedError

    def save_config(self, config: dict, user_id=None) -> None:
        raise NotImplementedError

    def get_app_config(self, key, default=None):
        raise NotImplementedError

    def set_app_config(self, key, value) -> None:
        raise NotImplementedError

    # ---- 草稿 ----
    def save_draft(self, prefix: str, draft_id: str, data: dict,
                   exam_type=None, user_id=None) -> None:
        raise NotImplementedError

    def load_drafts(self, prefix: str, exam_type=None, user_id=None) -> list:
        raise NotImplementedError

    def delete_draft(self, prefix: str, draft_id: str, user_id=None) -> None:
        raise NotImplementedError

    def clear_exam_records(self, exam_type: str, user_id=None) -> dict:
        raise NotImplementedError

    # ---- 身份（users / user_devices）----
    def get_user(self, user_id) -> dict:
        raise NotImplementedError

    def get_user_by_username(self, username) -> dict:
        raise NotImplementedError

    def list_users(self) -> list:
        raise NotImplementedError

    def upsert_user(self, user_id, username=None, password_hash=None,
                    role="user", display_name=None) -> None:
        raise NotImplementedError

    def set_user_password(self, user_id, password_hash) -> None:
        raise NotImplementedError

    def clear_user_account(self, user_id) -> None:
        raise NotImplementedError

    def touch_user_login(self, user_id, ts=None) -> None:
        raise NotImplementedError

    def get_device_user(self, device_fp) -> str:
        raise NotImplementedError

    def bind_device(self, device_fp, user_id) -> None:
        raise NotImplementedError

    def unbind_device(self, device_fp) -> None:
        raise NotImplementedError

    def list_devices(self, user_id) -> list:
        raise NotImplementedError


# ========================================
# SQLite 实现
# ========================================

class SQLiteDataAccess(DataAccess):
    """SQLite 数据库实现（单库多租户）

    user_id 是「当前用户」的路由上下文：多用户共用一个 DAO 实例，
    由 data_manager.set_current_user() 每帧校正（与改造前同样的幂等策略，
    解决 Streamlit 模块级全局被其他 session 覆盖的问题）。
    """

    def __init__(self, db_path=None, user_id=None):
        self.db_path = str(db_path) if db_path else str(SQLITE_DB)
        self.user_id = user_id or ""
        _ensure_parent_dir(self.db_path)
        self._init_db()

    # ---- 上下文 ----

    def set_user_id(self, user_id):
        """切换当前用户（由 data_manager.set_current_user 调用）"""
        self.user_id = user_id or ""

    def _uid(self, user_id=None):
        """解析生效的 user_id：显式传入优先，否则用当前上下文"""
        return user_id if user_id else self.user_id

    def _owner(self, owner_id=None):
        """解析生效的 owner：显式传入优先，否则用当前用户（写自己的私人题库）"""
        return owner_id if owner_id else self.user_id

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        # WAL 模式 + 性能优化：大幅提升并发读写性能
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-4000")
        return conn

    def _get_light_conn(self):
        """轻量连接：不做 WAL/PRAGMA 设置，仅供「每次 rerun 都要读一眼」的小查询使用。

        为什么需要：PRAGMA journal_mode=WAL 需要取写锁，代价远高于一次普通 SELECT。
        改造前 get_questions_version() 每帧都走 _get_conn()，实测约 259ms/次。
        """
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # 题型中文→英文映射（兼容图片/PDF导入时可能使用中文类型名）
    _TYPE_NORMALIZE_MAP = {
        "单选题": "single",
        "多选题": "multi",
        "判断题": "judge",
        "不定项选择题": "indefinite",
    }

    @staticmethod
    def _normalize_question(q: dict) -> dict:
        """标准化题目字典：确保 index_num/index 双键共存，并标准化题型为英文"""
        if "index_num" in q and "index" not in q:
            q["index"] = q["index_num"]
        elif "index" in q and "index_num" not in q:
            q["index_num"] = q["index"]
        # 标准化题型：中文→英文
        t = q.get("type", "")
        if t in SQLiteDataAccess._TYPE_NORMALIZE_MAP:
            q["type"] = SQLiteDataAccess._TYPE_NORMALIZE_MAP[t]
        return q

    # ---------- 建表 ----------

    def _init_db(self):
        """初始化数据库表结构（单库多租户）"""
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            # ---- 题库（公共 + 用户私有，靠 owner_id 分层）----
            cur.execute("""
                CREATE TABLE IF NOT EXISTS questions (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL DEFAULT '__public__',
                    source_file TEXT,
                    index_num INTEGER,
                    type TEXT NOT NULL,
                    question TEXT NOT NULL,
                    options TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    explanation TEXT,
                    md5 TEXT NOT NULL,
                    category TEXT,
                    exam_type TEXT,
                    case_study_id TEXT,
                    is_case_background INTEGER DEFAULT 0
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_questions_owner ON questions(owner_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_questions_exam_type ON questions(exam_type)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_questions_category ON questions(category)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_questions_type ON questions(type)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_questions_case ON questions(case_study_id)")

            # ---- 案例（同样分层）----
            cur.execute("""
                CREATE TABLE IF NOT EXISTS case_studies (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL DEFAULT '__public__',
                    title TEXT,
                    background_id TEXT NOT NULL DEFAULT '',
                    question_count INTEGER DEFAULT 0,
                    exam_type TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_case_studies_owner ON case_studies(owner_id)")

            # ---- 存量旧库守卫 ----
            # 若拿到的是改造前的旧库（questions 没有 owner_id / 还是 config 表），
            # 明确报错而不是静默跑成「题库为空」。
            self._assert_schema_ready(cur)

            # 题目内容唯一性限定在 owner 作用域内（公共题与用户私题互不干扰）
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uniq_questions_owner_md5
                ON questions(owner_id, md5)
            """)

            # ---- 答题统计（复合主键：题目 × 用户）----
            cur.execute("""
                CREATE TABLE IF NOT EXISTS question_stats (
                    question_id TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT '',
                    correct_count INTEGER DEFAULT 0,
                    wrong_count INTEGER DEFAULT 0,
                    last_answer_time TEXT,
                    last_correct INTEGER,
                    answer_history TEXT,
                    mastery_level INTEGER DEFAULT 0,
                    confidence REAL DEFAULT 0.0,
                    unstable INTEGER DEFAULT 0,
                    self_uncertainty REAL DEFAULT 0.0,
                    first_answer_time TEXT,
                    exam_type TEXT,
                    PRIMARY KEY (question_id, user_id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_question_stats_user ON question_stats(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_question_stats_exam_type ON question_stats(exam_type)")

            # ---- 错题本（复合主键：题目 × 用户）----
            cur.execute("""
                CREATE TABLE IF NOT EXISTS wrong_questions (
                    question_id TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT '',
                    exam_type TEXT,
                    PRIMARY KEY (question_id, user_id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_wrong_questions_user ON wrong_questions(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_wrong_questions_exam_type ON wrong_questions(exam_type)")

            # ---- 答题记录 ----
            cur.execute("""
                CREATE TABLE IF NOT EXISTS answer_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL DEFAULT '',
                    question_id TEXT NOT NULL,
                    user_answer TEXT,
                    is_correct INTEGER NOT NULL,
                    mode TEXT,
                    session_id TEXT,
                    category TEXT,
                    timestamp TEXT NOT NULL,
                    exam_type TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_answer_records_user ON answer_records(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_answer_records_qid ON answer_records(question_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_answer_records_session ON answer_records(session_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_answer_records_timestamp ON answer_records(timestamp)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_answer_records_exam_type ON answer_records(exam_type)")

            # ---- 考试记录 ----
            cur.execute("""
                CREATE TABLE IF NOT EXISTS exam_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL DEFAULT '',
                    data TEXT NOT NULL,
                    exam_type TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_exam_records_user ON exam_records(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_exam_records_exam_type ON exam_records(exam_type)")

            # ---- 背题记录 ----
            cur.execute("""
                CREATE TABLE IF NOT EXISTS study_records (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT '',
                    mode TEXT,
                    total INTEGER,
                    answered INTEGER,
                    correct INTEGER,
                    wrong INTEGER,
                    start_time TEXT,
                    end_time TEXT,
                    details TEXT,
                    exam_type TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_study_records_user ON study_records(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_study_records_exam_type ON study_records(exam_type)")

            # ---- 模拟考试记录 ----
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mock_exam_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL DEFAULT '',
                    data TEXT NOT NULL,
                    exam_type TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_mock_exam_records_user ON mock_exam_records(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_mock_exam_records_exam_type ON mock_exam_records(exam_type)")

            # ---- 草稿 ----
            cur.execute("""
                CREATE TABLE IF NOT EXISTS drafts (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT '',
                    prefix TEXT NOT NULL,
                    draft_id TEXT NOT NULL,
                    data TEXT NOT NULL,
                    saved_at TEXT NOT NULL,
                    exam_type TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_drafts_user ON drafts(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_drafts_prefix ON drafts(prefix)")

            # ---- 配置：全局 + 每用户 ----
            cur.execute("""
                CREATE TABLE IF NOT EXISTS app_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_config (
                    user_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT,
                    PRIMARY KEY (user_id, key)
                )
            """)
            # 确保题库版本号记录存在
            cur.execute("SELECT value FROM app_config WHERE key = ?", (QUESTIONS_VERSION_KEY,))
            if cur.fetchone() is None:
                cur.execute(
                    "INSERT OR IGNORE INTO app_config (key, value) VALUES (?, ?)",
                    (QUESTIONS_VERSION_KEY, json.dumps(0))
                )

            # ---- 身份：用户 + 设备 ----
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT UNIQUE,
                    password_hash TEXT,
                    role TEXT NOT NULL DEFAULT 'user',
                    display_name TEXT,
                    created_at TEXT,
                    last_login TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_devices (
                    device_fp TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    first_seen TEXT,
                    last_seen TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_devices_user ON user_devices(user_id)")

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _assert_schema_ready(cur):
        """旧库守卫：确保拿到的是单库新结构。

        改造前的库没有 owner_id 列（题库）与 user_id 列（个人表），
        直接跑会得到「题库为空」这类假象，所以这里明确报错并给出修复指引。

        注意：本方法在「建表过程中」被调用（早于 question_stats 建表），
        因此**表不存在时必须放行**——全新库的正常路径就是先无表、后建表；
        只有「表已存在却缺列」才是旧库。这一点写错会导致全新库无法初始化。
        """

        def _existing(name):
            cur.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
            return cur.fetchone() is not None

        cur.execute("PRAGMA table_info(questions)")
        q_cols = {r[1] for r in cur.fetchall()}
        if q_cols and "owner_id" not in q_cols:
            raise RuntimeError(
                "数据库结构过旧：questions 表缺少 owner_id 列。\n"
                "这是单库改造前的旧库（每用户一个 db 文件）。\n"
                "请先执行：python scripts/migrate_to_single_db.py "
                "（脚本会自动备份，并生成新的 data/exmsys.db）"
            )
        if _existing("question_stats"):
            cur.execute("PRAGMA table_info(question_stats)")
            s_cols = {r[1] for r in cur.fetchall()}
            if "user_id" not in s_cols:
                raise RuntimeError(
                    "数据库结构过旧：question_stats 表缺少 user_id 列。请先执行 "
                    "python scripts/migrate_to_single_db.py"
                )

    # ---------- 题库版本号（全局）----------

    def get_questions_version(self) -> int:
        """获取题库数据版本号（app_config 表中维护，任何题库变更时递增）

        刻意使用轻量连接：本方法在每次 rerun 都会被调用，必须廉价。
        """
        conn = self._get_light_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT value FROM app_config WHERE key = ?", (QUESTIONS_VERSION_KEY,))
            row = cur.fetchone()
            return int(json.loads(row[0])) if row else 0
        finally:
            conn.close()

    def _increment_questions_version_in_conn(self, conn) -> None:
        """在已有连接上递增题库版本号（供题目写操作内部调用）"""
        cur = conn.cursor()
        cur.execute("SELECT value FROM app_config WHERE key = ?", (QUESTIONS_VERSION_KEY,))
        row = cur.fetchone()
        version = (int(json.loads(row[0])) + 1) if row else 1
        cur.execute(
            "INSERT OR REPLACE INTO app_config (key, value) VALUES (?, ?)",
            (QUESTIONS_VERSION_KEY, json.dumps(version))
        )

    # ---------- 题库 ----------

    def load_questions(self, exam_type=None, user_id=None) -> list:
        """加载用户可见题集 = 公共题库 ∪ 自己的私人题库（可按 exam_type 过滤）"""
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            sql = """
                SELECT q.*, cs.title AS case_background
                FROM questions q
                LEFT JOIN case_studies cs ON q.case_study_id = cs.id
                WHERE (q.owner_id = ? OR q.owner_id = ?)
            """
            params = [PUBLIC_OWNER, uid]
            if exam_type:
                sql += " AND q.exam_type = ?"
                params.append(exam_type)
            cur.execute(sql, tuple(params))
            questions = []
            for row in cur.fetchall():
                q = dict(row)
                q["options"] = json.loads(q["options"])
                self._normalize_question(q)
                questions.append(q)
            return questions
        finally:
            conn.close()

    def load_question_by_id(self, question_id: str) -> dict:
        """按 ID 查询单道题目（用于防御性校验，避免加载全量表）

        不限定 owner：题目 ID 全局唯一，任何可见范围内的题目都可查到。
        """
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM questions WHERE id = ?", (question_id,))
            row = cur.fetchone()
            if not row:
                return {}
            q = dict(row)
            q["options"] = json.loads(q["options"])
            self._normalize_question(q)
            return q
        finally:
            conn.close()

    # ---- 题目导入的相似度工具 ----

    @staticmethod
    def _content_fp(row_or_q: dict) -> str:
        """行的内容指纹 —— 与 question_md5 同算法，但吃「数据库行」也吃「解析结果」"""
        return question_md5(row_or_q)

    @staticmethod
    def _same_content(old_row: dict, new_q: dict) -> bool:
        """「新题与旧行在所有会被写入的字段上都相同」吗？

        只比内容指纹不够：指纹里没有 explanation/type/category/exam_type/来源信息。
        漏掉它们会让「管理员补了解析」这种更新被误判成 unchanged 而丢掉。
        """
        return (
            SQLiteDataAccess._content_fp(old_row) == SQLiteDataAccess._content_fp(new_q)
            and (old_row.get("explanation") or "") == (new_q.get("explanation") or "")
            and (old_row.get("type") or "") == (new_q.get("type") or "")
            and (old_row.get("category") or "") == (new_q.get("category") or "")
            and (old_row.get("source_file") or "") == (new_q.get("source_file") or "")
            and (old_row.get("index_num") or 0) == (new_q.get("index_num", new_q.get("index", 0)) or 0)
            and (old_row.get("case_study_id") or "") == (new_q.get("case_study_id") or "")
            and bool(old_row.get("is_case_background")) == bool(new_q.get("is_case_background"))
        )

    @staticmethod
    def _norm_text(s) -> str:
        return re.sub(r"\s+", "", (s or "")).lower()

    def _similar(self, a, b, threshold=0.60) -> float:
        """归一化后的题干相似度；低于 threshold 直接返回 0（省掉昂贵的完整比对）

        real_quick_ratio / quick_ratio 是 difflib 提供的廉价上界预筛，
        在大批量导入时可把完整 ratio() 的调用次数降一个数量级。
        """
        a, b = self._norm_text(a), self._norm_text(b)
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        sm = difflib.SequenceMatcher(None, a, b)
        if sm.real_quick_ratio() < threshold:
            return 0.0
        if sm.quick_ratio() < threshold:
            return 0.0
        r = sm.ratio()
        return r if r >= threshold else 0.0

    def _match_questions(self, new_qs, old_rows, log=None):
        """把新导入的题与库中已有题配对，尽量复用旧 ID（保住用户历史）。

        信号优先级：
          1. **内容指纹**（题干+选项+答案，两侧现算）相同 → 同一题
             先用内容指纹、后看 md5 列，因为 md5 列可能是陈旧的
             （管理员直接改库后不会自动同步），拿它当主键会漏配。
          2. (source_file, index_num, type) 相同   → 同一题（题号可靠时）
          3. 同一 source_file 内，文本相似度最高且 ≥ 0.60 → 同一题（题干被改过）

        返回 (pairs, unmatched_new)；pairs 为 [(new_q, old_row), ...]
        """
        log = log if log is not None else []
        by_fp, by_md5, by_key = {}, {}, {}
        for r in old_rows:
            by_fp.setdefault(self._content_fp(r), []).append(r)
            by_md5.setdefault(r.get("md5") or "", []).append(r)
            if r.get("index_num"):
                by_key.setdefault((r.get("source_file") or "", r["index_num"], r.get("type") or ""), []).append(r)

        used = set()
        pairs = []

        def take(bucket, key):
            for r in bucket.get(key, []):
                if r["id"] not in used:
                    used.add(r["id"])
                    return r
            return None

        # 1) 内容指纹（两侧现算）→ 退回库中 md5 列
        pending = []
        for q in new_qs:
            r = take(by_fp, question_md5(q)) or take(by_md5, q.get("md5") or "")
            if r:
                pairs.append((q, r))
            else:
                pending.append(q)

        # 2) 同 (source_file, index_num, type)
        still = []
        for q in pending:
            idx = q.get("index_num", q.get("index"))
            if idx:
                r = take(by_key, (q.get("source_file") or "", idx, q.get("type") or ""))
            else:
                r = None
            if r:
                pairs.append((q, r))
            else:
                still.append(q)
        pending = still

        # 3) 同文件内文本相似度
        new_by_src, old_by_src = {}, {}
        for q in pending:
            new_by_src.setdefault(q.get("source_file") or "", []).append(q)
        for r in old_rows:
            if r["id"] not in used:
                old_by_src.setdefault(r.get("source_file") or "", []).append(r)

        # 每个文件内的两两比较是有上限的（O(n·m)）：给一个预算，超了就停止模糊配对，
        # 剩下的按新题插入 —— 宁可多几道新题，也不让导入卡死。
        COMPARE_BUDGET = 200000
        unmatched = []
        for src, qs in new_by_src.items():
            cands = old_by_src.get(src, [])
            spent = 0
            exhausted = False
            for q in qs:
                best, best_sim = None, 0.0
                for r in cands:
                    if r["id"] in used:
                        continue
                    if spent >= COMPARE_BUDGET:
                        exhausted = True
                        break
                    spent += 1
                    sim = self._similar(q.get("question"), r.get("question"))
                    if sim > best_sim:
                        best, best_sim = r, sim
                if best is not None and best_sim >= 0.60:
                    used.add(best["id"])
                    pairs.append((q, best))
                    log.append(f"  🔗 按题干相似度 {best_sim:.2f} 对齐: {str(q.get('question'))[:28]}...")
                else:
                    unmatched.append(q)
                if exhausted:
                    break
            if exhausted:
                log.append(f"  ⚠️ [{src}] 题目过多，已跳过剩余模糊配对（作为新题导入）")
        return pairs, unmatched

    def import_questions(self, questions: list, owner_id=None, mode: str = "append",
                         exam_type: str = None) -> dict:
        """导入题目到指定 owner 作用域（upsert，不再全量重建题库）

        与改造前的关键差异：
          · 旧实现是 DELETE FROM questions + 全量重插 → 每次导入整个题库重建；
          · 现在是按 owner 作用域的 upsert：能对上旧题的 **复用原 ID**（内容更新），
            用户已有的统计/错题/答题记录因此不会断链。

        Args:
            questions: 解析出的题目列表（需含 md5，可由 parser 生成）。
            owner_id: 目标 owner；None 表示当前用户的私人题库；
                      PUBLIC_OWNER 表示公共题库（管理员专用）。
            mode: 'append' 只新增与更新，不删除（默认，安全）；
                  'replace' 视为该 owner 的完整题库，删除未匹配到的旧题。
            exam_type: 未在题目里指定时的兜底题库类型。

        Returns:
            {"added": n, "updated": n, "unchanged": n, "removed": n, "skipped": n, "log": [...]}
        """
        owner = self._owner(owner_id)
        if not owner:
            raise ValueError("import_questions 需要 owner_id（用户未登录时无法导入）")
        report = {"added": 0, "updated": 0, "unchanged": 0, "removed": 0, "skipped": 0, "log": []}
        if not questions:
            return report

        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, source_file, index_num, type, question, options, answer, explanation, "
                "md5, category, exam_type, case_study_id, is_case_background "
                "FROM questions WHERE owner_id = ?", (owner,)
            )
            old_rows = [dict(r) for r in cur.fetchall()]

            pairs, unmatched = self._match_questions(questions, old_rows, report["log"])

            # used_ids：库中已存在的全部 ID，防止新题生成时撞车（只增不减）
            used_ids = {r["id"] for r in old_rows}
            # matched_ids：本次导入匹配上的旧题 ID（replace 模式据此判定要删哪些）
            matched_ids = {r["id"] for _, r in pairs}
            seen_md5 = {r["md5"] for r in old_rows}

            # a) 更新已匹配的旧题 —— 保留原 ID，只刷新内容
            for q, r in pairs:
                # 全字段一致 → 连 md5 都不动。
                # 为什么不顺手把陈旧的 md5 改成内容指纹：库里有大量「内容重复但 ID 不同」的题
                # （master 就有 1237 组 / 2474 题），改写 md5 会撞上 UNIQUE(owner_id, md5)。
                if self._same_content(r, q):
                    report["unchanged"] += 1
                    continue
                new_md5 = q.get("md5") or question_md5(q)
                old_md5 = r.get("md5") or ""
                if new_md5 in seen_md5 and new_md5 != old_md5:
                    # 该指纹已被同 owner 的另一道题占用 → 保留本行原 md5，绝不触发唯一索引冲突
                    report["log"].append(
                        f"  ⚠️ md5 已被同题库另一题占用，保留原值: {str(q.get('question'))[:28]}...")
                    new_md5 = old_md5 or question_md5(q)
                cur.execute("""
                    UPDATE questions SET
                        source_file = ?, index_num = ?, type = ?, question = ?, options = ?,
                        answer = ?, explanation = ?, md5 = ?, category = ?, exam_type = ?,
                        case_study_id = ?, is_case_background = ?
                    WHERE id = ?
                """, (
                    q.get("source_file", ""),
                    q.get("index_num", q.get("index", 0)),
                    q.get("type", "single"),
                    q.get("question", ""),
                    json.dumps(_options_dict(q.get("options")), ensure_ascii=False),
                    q.get("answer", ""),
                    q.get("explanation", ""),
                    new_md5,
                    q.get("category", ""),
                    q.get("exam_type") or exam_type or DEFAULT_EXAM_TYPE,
                    q.get("case_study_id", ""),
                    q.get("is_case_background", 0),
                    r["id"],
                ))
                if old_md5 != new_md5:
                    seen_md5.discard(old_md5)
                    seen_md5.add(new_md5)
                report["updated"] += 1

            # b) 插入新题 —— ID 按 owner 作用域生成，且不得与已有内容指纹重复
            for q in unmatched:
                fp = question_md5(q)
                q_md5 = q.get("md5") or fp
                if q_md5 in seen_md5 or fp in seen_md5:
                    report["skipped"] += 1
                    report["log"].append(f"  ⏭️ 跳过重复题: [{q.get('source_file','')}] 第{q.get('index_num', q.get('index',''))}题")
                    continue
                qid = make_question_id(owner, q)
                n = 1
                base = qid
                while qid in used_ids:
                    qid = hashlib.md5(f"{owner}|{base}|{n}".encode("utf-8")).hexdigest()[:12]
                    n += 1
                cur.execute("""
                    INSERT INTO questions
                    (id, owner_id, source_file, index_num, type, question, options, answer,
                     explanation, md5, category, exam_type, case_study_id, is_case_background)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    qid,
                    owner,
                    q.get("source_file", ""),
                    q.get("index_num", q.get("index", 0)),
                    q.get("type", "single"),
                    q.get("question", ""),
                    json.dumps(_options_dict(q.get("options")), ensure_ascii=False),
                    q.get("answer", ""),
                    q.get("explanation", ""),
                    q_md5,
                    q.get("category", ""),
                    q.get("exam_type") or exam_type or DEFAULT_EXAM_TYPE,
                    q.get("case_study_id", ""),
                    q.get("is_case_background", 0),
                ))
                used_ids.add(qid)
                seen_md5.add(q_md5)
                report["added"] += 1

            # c) replace 模式：删除本次未匹配到的旧题（匹配上的已保留原 ID）
            if mode == "replace":
                leftovers = [r["id"] for r in old_rows if r["id"] not in matched_ids]
                if leftovers:
                    cur.executemany("DELETE FROM questions WHERE id = ?", [(i,) for i in leftovers])
                    report["removed"] = len(leftovers)

            self._increment_questions_version_in_conn(conn)
            conn.commit()
            return report
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def clear_questions(self, owner_id=None, exam_type: str = None) -> int:
        """清空指定 owner 的题库（可只清某个 exam_type）。返回删除行数。

        默认只清空「当前用户的私人题库」；清空公共题库必须显式传 PUBLIC_OWNER。
        """
        owner = self._owner(owner_id)
        if not owner:
            raise ValueError("clear_questions 需要 owner_id")
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute("DELETE FROM questions WHERE owner_id = ? AND exam_type = ?", (owner, exam_type))
            else:
                cur.execute("DELETE FROM questions WHERE owner_id = ?", (owner,))
            n = cur.rowcount
            self._increment_questions_version_in_conn(conn)
            conn.commit()
            return n
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def count_questions(self, owner_id=None, exam_type=None) -> int:
        """统计指定 owner 的题目数（owner_id=None 表示当前用户私有题库）"""
        owner = self._owner(owner_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute("SELECT COUNT(*) FROM questions WHERE owner_id = ? AND exam_type = ?", (owner, exam_type))
            else:
                cur.execute("SELECT COUNT(*) FROM questions WHERE owner_id = ?", (owner,))
            return int(cur.fetchone()[0])
        finally:
            conn.close()

    def get_question_count(self, exam_type=None, user_id=None) -> dict:
        """获取可见题库统计，可按 exam_type 过滤"""
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            sql = ("SELECT type, COUNT(*) AS c FROM questions "
                   "WHERE (owner_id = ? OR owner_id = ?)")
            params = [PUBLIC_OWNER, uid]
            if exam_type:
                sql += " AND exam_type = ?"
                params.append(exam_type)
            sql += " GROUP BY type"
            cur.execute(sql, tuple(params))
            result = {"total": 0, "single": 0, "multi": 0, "judge": 0, "案例题": 0}
            for row in cur.fetchall():
                t, cnt = row["type"], row["c"]
                result[t] = cnt
                result["total"] += cnt
            return result
        finally:
            conn.close()

    def get_questions_by_type(self, question_type, exam_type=None, user_id=None) -> list:
        """按题型获取可见题目（question_type 为空表示不限题型）"""
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            sql = "SELECT * FROM questions WHERE (owner_id = ? OR owner_id = ?)"
            params = [PUBLIC_OWNER, uid]
            if question_type:
                sql += " AND type = ?"
                params.append(question_type)
            if exam_type:
                sql += " AND exam_type = ?"
                params.append(exam_type)
            cur.execute(sql, tuple(params))
            questions = []
            for row in cur.fetchall():
                q = dict(row)
                q["options"] = json.loads(q["options"])
                self._normalize_question(q)
                questions.append(q)
            return questions
        finally:
            conn.close()

    def get_available_exam_types(self, user_id=None) -> list:
        """获取可见题库中所有 exam_type，返回 [(code, label), ...]"""
        from utils.data_manager import EXAM_TYPE_LABELS
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT exam_type FROM questions "
                "WHERE exam_type IS NOT NULL AND exam_type != '' AND (owner_id = ? OR owner_id = ?)",
                (PUBLIC_OWNER, uid)
            )
            types = [row["exam_type"] for row in cur.fetchall()]
            result = []
            for t in sorted(types):
                result.append((t, EXAM_TYPE_LABELS.get(t, t)))
            return result
        finally:
            conn.close()

    def get_questions_by_exam_type(self, exam_type, user_id=None) -> list:
        return self.get_questions_by_type("", exam_type, user_id)

    # ---------- 案例题 ----------

    def load_case_studies(self, exam_type=None, user_id=None) -> list:
        """加载用户可见案例（case_studies 表）"""
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            sql = "SELECT * FROM case_studies WHERE (owner_id = ? OR owner_id = ?)"
            params = [PUBLIC_OWNER, uid]
            if exam_type:
                sql += " AND exam_type = ?"
                params.append(exam_type)
            sql += " ORDER BY id"
            cur.execute(sql, tuple(params))
            return [dict(row) for row in cur.fetchall()]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    def save_case_studies(self, case_studies: list, owner_id=None) -> None:
        """批量保存案例背景（INSERT OR REPLACE，按 owner 归属）"""
        if not case_studies:
            return
        owner = self._owner(owner_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            for cs in case_studies:
                cur.execute("""
                    INSERT OR REPLACE INTO case_studies
                    (id, owner_id, title, background_id, question_count, exam_type)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    cs.get("case_id", cs.get("id", "")),
                    owner,
                    cs.get("title", ""),
                    cs.get("background_id", ""),
                    cs.get("question_count", 0),
                    cs.get("exam_type") or DEFAULT_EXAM_TYPE,
                ))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_case_sub_questions(self, case_id: str, user_id=None) -> list:
        """获取某案例的全部子题（排除背景题，按 index_num 排序）"""
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM questions
                WHERE case_study_id = ? AND is_case_background = 0
                  AND (owner_id = ? OR owner_id = ?)
                ORDER BY index_num
            """, (case_id, PUBLIC_OWNER, uid))
            questions = []
            for row in cur.fetchall():
                q = dict(row)
                q["options"] = json.loads(q["options"])
                self._normalize_question(q)
                questions.append(q)
            return questions
        finally:
            conn.close()

    def dedup_import(self, existing_questions, new_questions) -> tuple:
        """按 md5 去重（保留供脚本/兼容使用；实际导入走 import_questions）"""
        existing_md5s = {q.get("md5") for q in existing_questions}
        added, skipped, log = 0, 0, []
        for q in new_questions:
            if q.get("md5") in existing_md5s:
                skipped += 1
                log.append(f"  ⏭️ 跳过重复题: [{q.get('source_file','')}] 第{q.get('index', q.get('index_num',''))}题")
            else:
                existing_questions.append(q)
                existing_md5s.add(q.get("md5"))
                added += 1
        return existing_questions, added, skipped, log

    # ---------- 错题本 ----------

    def _extract_qids_from_wrong_list(self, wrong_list):
        return wrong_list  # SQLite 版直接返回 qid 列表

    def load_wrong_questions(self, exam_type=None, user_id=None) -> list:
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute("""
                    SELECT w.question_id FROM wrong_questions w
                    JOIN questions q ON w.question_id = q.id
                    WHERE w.user_id = ? AND q.exam_type = ?
                """, (uid, exam_type))
            else:
                cur.execute("SELECT question_id FROM wrong_questions WHERE user_id = ?", (uid,))
            return [row["question_id"] for row in cur.fetchall()]
        finally:
            conn.close()

    def save_wrong_questions(self, wrong_list, exam_type=None, user_id=None) -> None:
        """保存错题列表（整体替换当前用户的错题本）

        wrong_list 元素可以是 qid 字符串，或 (qid, exam_type) 元组。
        """
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM wrong_questions WHERE user_id = ?", (uid,))
            for item in wrong_list:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    qid, et = item[0], item[1]
                else:
                    qid = item
                    cur2 = conn.cursor()
                    cur2.execute("SELECT exam_type FROM questions WHERE id = ?", (qid,))
                    row = cur2.fetchone()
                    et = row[0] if row else (exam_type or DEFAULT_EXAM_TYPE)
                cur.execute(
                    "INSERT OR IGNORE INTO wrong_questions (question_id, user_id, exam_type) VALUES (?, ?, ?)",
                    (qid, uid, et)
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def add_wrong_record(self, question_id, user_answer) -> None:
        now = datetime.now().isoformat()
        stats = self.load_question_stats()
        if question_id not in stats:
            stats[question_id] = {
                "correct_count": 0, "wrong_count": 0,
                "last_answer_time": None, "last_correct": None,
            }
        stats[question_id]["wrong_count"] += 1
        stats[question_id]["last_correct"] = False
        stats[question_id]["last_answer_time"] = now
        self.save_question_stats(stats)

        s = stats[question_id]
        wc, cc = s["wrong_count"], s["correct_count"]
        wrong_qids = self.load_wrong_questions()
        if wc >= cc and (wc > 0 or cc > 0):
            if question_id not in wrong_qids:
                wrong_qids.append(question_id)
        elif question_id in wrong_qids:
            wrong_qids.remove(question_id)
        self.save_wrong_questions(wrong_qids)

    def add_correct_record(self, question_id) -> None:
        now = datetime.now().isoformat()
        stats = self.load_question_stats()
        if question_id not in stats:
            stats[question_id] = {
                "correct_count": 0, "wrong_count": 0,
                "last_answer_time": None, "last_correct": None,
            }
        stats[question_id]["correct_count"] += 1
        stats[question_id]["last_correct"] = True
        stats[question_id]["last_answer_time"] = now
        self.save_question_stats(stats)

        s = stats[question_id]
        if s["wrong_count"] < s["correct_count"]:
            wrong_qids = self.load_wrong_questions()
            if question_id in wrong_qids:
                wrong_qids.remove(question_id)
                self.save_wrong_questions(wrong_qids)

    def batch_update_wrong_and_stats(self, wrong_qids, correct_qids, stats_updates,
                                     uncertain_map=None, exam_record=None,
                                     exam_type=None, user_id=None) -> None:
        """增量更新：只查询和写入受影响的题目统计，单个事务内完成。

        可选参数 exam_record: 若提供，则在同一事务内写入考试记录，减少一次连接开销。
        """
        from utils.data_manager import _recalc_mastery_fields
        uid = self._uid(user_id)
        now = datetime.now().isoformat()
        uncertain_map = uncertain_map or {}

        qid_user_ans = dict(wrong_qids)
        correct_qids_set = set(correct_qids)

        # 构建 affected_qids + stats_updates 索引（O(1) 查找）
        stats_updates_by_qid = {}
        affected_qids = set()
        for qid, is_correct in stats_updates:
            affected_qids.add(qid)
            stats_updates_by_qid.setdefault(qid, []).append(is_correct)
        affected_qids.update(qid_user_ans.keys())
        affected_qids.update(correct_qids_set)

        if not affected_qids:
            return

        conn = self._get_conn()
        try:
            cur = conn.cursor()

            # 1) 只查询受影响的题目统计（限当前用户）
            placeholders = ",".join("?" for _ in affected_qids)
            cur.execute(
                f"SELECT * FROM question_stats WHERE user_id = ? AND question_id IN ({placeholders})",
                (uid,) + tuple(affected_qids)
            )
            stats = {}
            for row in cur.fetchall():
                qid = row["question_id"]
                stats[qid] = {
                    "correct_count": row["correct_count"],
                    "wrong_count": row["wrong_count"],
                    "last_answer_time": row["last_answer_time"],
                    "last_correct": bool(row["last_correct"]) if row["last_correct"] is not None else None,
                    "answer_history": json.loads(row["answer_history"]) if row["answer_history"] else [],
                    "mastery_level": row["mastery_level"],
                    "confidence": row["confidence"],
                    "unstable": bool(row["unstable"]),
                    "self_uncertainty": row["self_uncertainty"],
                    "first_answer_time": row["first_answer_time"],
                }

            new_counts = {}
            for qid in affected_qids:
                s = stats.get(qid, {"correct_count": 0, "wrong_count": 0})
                cc = s.get("correct_count", 0)
                wc = s.get("wrong_count", 0)
                for is_correct in stats_updates_by_qid.get(qid, []):
                    if is_correct:
                        cc += 1
                    else:
                        wc += 1
                new_counts[qid] = (cc, wc)

                if qid not in stats:
                    stats[qid] = {
                        "correct_count": 0, "wrong_count": 0,
                        "last_answer_time": None, "last_correct": None,
                        "answer_history": [], "mastery_level": 0,
                        "confidence": 0.0, "unstable": False,
                        "self_uncertainty": 0.0, "first_answer_time": None,
                    }
                stats[qid]["correct_count"] = cc
                stats[qid]["wrong_count"] = wc
                stats[qid]["last_answer_time"] = now

                # 最后一次作答正确性
                last_is_correct = None
                for _qid, _is_correct in reversed(stats_updates):
                    if _qid == qid:
                        last_is_correct = _is_correct
                        break
                if last_is_correct is not None:
                    stats[qid]["last_correct"] = last_is_correct

                history = list(stats[qid].get("answer_history", []))
                history.append(last_is_correct if last_is_correct is not None else False)
                stats[qid]["answer_history"] = history

                old_unc = stats[qid].get("self_uncertainty", 0.0)
                if qid in uncertain_map and uncertain_map[qid] is False:
                    # 用户本次主动关闭不确定开关 → 立即清零
                    stats[qid]["self_uncertainty"] = 0.0
                else:
                    new_unc = 1.0 if uncertain_map.get(qid) else 0.0
                    if old_unc > 0 or new_unc > 0:
                        stats[qid]["self_uncertainty"] = round(0.3 * new_unc + 0.7 * old_unc, 3)
                    else:
                        stats[qid]["self_uncertainty"] = 0.0

                _recalc_mastery_fields(stats[qid])

            # 2) 批量 upsert 受影响的统计行（带 exam_type）
            _placeholders = ",".join("?" for _ in affected_qids)
            _cur2 = conn.cursor()
            _cur2.execute(
                f"SELECT id, exam_type FROM questions WHERE id IN ({_placeholders})",
                tuple(affected_qids)
            )
            _type_map = {row["id"]: row["exam_type"] for row in _cur2.fetchall()}

            cur.executemany("""
                INSERT OR REPLACE INTO question_stats
                (question_id, user_id, correct_count, wrong_count, last_answer_time, last_correct,
                 answer_history, mastery_level, confidence, unstable,
                 self_uncertainty, first_answer_time, exam_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    qid,
                    uid,
                    stats[qid].get("correct_count", 0),
                    stats[qid].get("wrong_count", 0),
                    stats[qid].get("last_answer_time"),
                    stats[qid].get("last_correct"),
                    json.dumps(stats[qid].get("answer_history", []), ensure_ascii=False),
                    stats[qid].get("mastery_level", 0),
                    stats[qid].get("confidence", 0.0),
                    stats[qid].get("unstable", 0),
                    stats[qid].get("self_uncertainty", 0.0),
                    stats[qid].get("first_answer_time"),
                    _type_map.get(qid) or exam_type or DEFAULT_EXAM_TYPE,
                )
                for qid in affected_qids
            ])

            # 3) 更新错题本（同一事务内）—— 增量更新，仅修改变化的行
            cur.execute("SELECT question_id FROM wrong_questions WHERE user_id = ?", (uid,))
            old_qids = set(row["question_id"] for row in cur.fetchall())
            new_wrong = set()
            for qid, (cc, wc) in new_counts.items():
                if wc >= cc and (wc > 0 or cc > 0):
                    new_wrong.add(qid)
            for qid in old_qids:
                if qid not in affected_qids:
                    new_wrong.add(qid)

            # 只删除不再属于错题本的
            to_remove = old_qids - new_wrong
            if to_remove:
                cur.executemany(
                    "DELETE FROM wrong_questions WHERE question_id = ? AND user_id = ?",
                    [(qid, uid) for qid in to_remove]
                )
            # 只插入新增的错题（带 exam_type）
            to_add = new_wrong - old_qids
            if to_add:
                _ph = ",".join("?" for _ in to_add)
                _cur3 = conn.cursor()
                _cur3.execute(
                    f"SELECT id, exam_type FROM questions WHERE id IN ({_ph})",
                    tuple(to_add)
                )
                _et_map = {row["id"]: row["exam_type"] for row in _cur3.fetchall()}
                cur.executemany(
                    "INSERT INTO wrong_questions (question_id, user_id, exam_type) VALUES (?, ?, ?)",
                    [(qid, uid, _et_map.get(qid) or exam_type or DEFAULT_EXAM_TYPE) for qid in to_add]
                )

            # 4) 考试记录（可选，同一事务内完成）
            if exam_record:
                cur.execute(
                    "INSERT INTO exam_records (user_id, data, exam_type) VALUES (?, ?, ?)",
                    (uid, json.dumps(exam_record, ensure_ascii=False),
                     exam_type or DEFAULT_EXAM_TYPE)
                )

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_top_wrong_questions(self, count=50, exam_type=None, user_id=None) -> list:
        wrong_qids = self.load_wrong_questions(user_id=user_id)
        questions = self.load_questions(user_id=user_id)
        stats = self.load_question_stats(user_id=user_id)
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
        result.sort(key=lambda x: x[1], reverse=True)
        return result[:count]

    def remove_wrong_question(self, question_id, user_id=None) -> None:
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM wrong_questions WHERE question_id = ? AND user_id = ?", (question_id, uid))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def clear_all_wrong(self, user_id=None) -> None:
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM wrong_questions WHERE user_id = ?", (uid,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_wrong_stats(self, exam_type=None, user_id=None) -> dict:
        """错题统计，可按 exam_type 过滤

        口径说明（2026-09-26 修正）：
        - total: 当前错题本内的题目数（答错次数 >= 答对次数 的题）
        - most_wrong: 当前题库**所有答过的题**中历史最高答错次数。
          不再限定"当前还在错题本里"——已因答对较多被移出错题本的题，
          其历史答错次数同样计入，否则该指标会随题目"洗白"而失真偏低。
        """
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            # 1) 错题本内题目数
            if exam_type:
                cur.execute("""
                    SELECT COUNT(*)
                    FROM wrong_questions w
                    JOIN questions q ON w.question_id = q.id
                    WHERE w.user_id = ? AND q.exam_type = ?
                """, (uid, exam_type))
            else:
                cur.execute("""
                    SELECT COUNT(*)
                    FROM wrong_questions w
                    WHERE w.user_id = ?
                """, (uid,))
            total = cur.fetchone()[0]
            # 2) 全量最高答错次数（从 question_stats 出发，不限错题本）
            if exam_type:
                cur.execute("""
                    SELECT COALESCE(MAX(s.wrong_count), 0)
                    FROM question_stats s
                    JOIN questions q ON s.question_id = q.id
                    WHERE s.user_id = ? AND q.exam_type = ? AND s.wrong_count > 0
                """, (uid, exam_type))
            else:
                cur.execute("""
                    SELECT COALESCE(MAX(s.wrong_count), 0)
                    FROM question_stats s
                    WHERE s.user_id = ? AND s.wrong_count > 0
                """, (uid,))
            most_wrong = cur.fetchone()[0] or 0
            if total == 0 and most_wrong == 0:
                return {"total": 0, "most_wrong": 0}
            return {"total": total, "most_wrong": most_wrong}
        finally:
            conn.close()

    def get_all_wrong_with_stats(self, exam_type=None, limit=None, user_id=None) -> list:
        """获取所有错题，附带答题统计，按易错程度降序（SQL 层排序）"""
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            base = """
                SELECT
                    q.id          AS question_id,
                    q.question,
                    q.type,
                    q.options,
                    q.answer,
                    q.explanation,
                    q.category,
                    q.case_study_id,
                    COALESCE(s.wrong_count, 0)    AS wrong_count,
                    COALESCE(s.correct_count, 0)  AS correct_count,
                    s.last_answer_time,
                    s.last_correct,
                    s.mastery_level,
                    s.confidence,
                    cs.title                          AS case_background
                FROM wrong_questions w
                JOIN questions q ON w.question_id = q.id
                LEFT JOIN question_stats s ON w.question_id = s.question_id AND s.user_id = w.user_id
                LEFT JOIN case_studies cs ON q.case_study_id = cs.id
                WHERE w.user_id = ?
            """
            params = [uid]
            if exam_type:
                base += " AND q.exam_type = ?"
                params.append(exam_type)
            base += " ORDER BY (COALESCE(s.wrong_count, 0) - COALESCE(s.correct_count, 0)) DESC"
            if limit is not None:
                base += " LIMIT ?"
                params.append(limit)
            cur.execute(base, tuple(params))
            rows = cur.fetchall()
            type_labels = {"single": "单选", "multi": "多选", "judge": "判断", "案例题": "案例题", "indefinite": "不定项"}
            result = []
            for row in rows:
                q = dict(row)
                q["options"] = json.loads(q["options"])
                wc = q.get("wrong_count") or 0
                cc = q.get("correct_count") or 0
                result.append({
                    "question_id": q["question_id"],
                    "question": q["question"],
                    "type": q["type"],
                    "type_label": type_labels.get(q["type"], q["type"]),
                    "options": q.get("options", {}),
                    "answer": q["answer"],
                    "explanation": q.get("explanation", ""),
                    "category": q.get("category", ""),
                    "case_study_id": q.get("case_study_id"),
                    "wrong_count": wc,
                    "correct_count": cc,
                    "diff": wc - cc,
                    "last_answer_time": q.get("last_answer_time"),
                    "last_correct": bool(q["last_correct"]) if q.get("last_correct") is not None else None,
                    "mastery_level": q.get("mastery_level", 0),
                    "confidence": q.get("confidence", 0),
                    "case_background": q.get("case_background") or "",
                })
            return result
        finally:
            conn.close()

    # ---------- 答题统计 ----------

    def load_question_stats(self, exam_type=None, user_id=None) -> dict:
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute("SELECT * FROM question_stats WHERE user_id = ? AND exam_type = ?", (uid, exam_type))
            else:
                cur.execute("SELECT * FROM question_stats WHERE user_id = ?", (uid,))
            rows = cur.fetchall()
            stats = {}
            now = datetime.now()
            threshold = get_retention_threshold(self.db_path, uid)
            for row in rows:
                qid = row["question_id"]
                s = {
                    "correct_count": row["correct_count"],
                    "wrong_count": row["wrong_count"],
                    "last_answer_time": row["last_answer_time"],
                    "last_correct": bool(row["last_correct"]) if row["last_correct"] is not None else None,
                    "answer_history": json.loads(row["answer_history"]) if row["answer_history"] else [],
                    "mastery_level": row["mastery_level"],
                    "confidence": row["confidence"],
                    "unstable": bool(row["unstable"]),
                    "self_uncertainty": row["self_uncertainty"],
                    "first_answer_time": row["first_answer_time"],
                }
                # 动态计算 retention_due
                if s["last_correct"] is True and s["last_answer_time"]:
                    try:
                        last_time = datetime.fromisoformat(s["last_answer_time"])
                        days_since = (now - last_time).days
                        s["retention_due"] = days_since > threshold
                    except (ValueError, TypeError):
                        s["retention_due"] = False
                else:
                    s["retention_due"] = False
                stats[qid] = s
            return stats
        finally:
            conn.close()

    def save_question_stats(self, stats: dict, exam_type=None, user_id=None) -> None:
        """批量 upsert 题目统计（executemany 一次性写入）"""
        if not stats:
            return
        uid = self._uid(user_id)
        # 自动补填 exam_type（批量查一次，避免 N 次查询）
        if exam_type is None:
            qids = list(stats.keys())
            _type_map = {}
            if qids:
                placeholders = ",".join("?" for _ in qids)
                _conn = self._get_conn()
                try:
                    _cur = _conn.cursor()
                    _cur.execute(
                        f"SELECT id, exam_type FROM questions WHERE id IN ({placeholders})",
                        tuple(qids)
                    )
                    _type_map = {row["id"]: row["exam_type"] for row in _cur.fetchall()}
                finally:
                    _conn.close()
        else:
            _type_map = {qid: exam_type for qid in stats}

        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.executemany("""
                INSERT OR REPLACE INTO question_stats
                (question_id, user_id, correct_count, wrong_count, last_answer_time, last_correct,
                 answer_history, mastery_level, confidence, unstable,
                 self_uncertainty, first_answer_time, exam_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    qid,
                    uid,
                    s.get("correct_count", 0),
                    s.get("wrong_count", 0),
                    s.get("last_answer_time"),
                    s.get("last_correct"),
                    json.dumps(s.get("answer_history", []), ensure_ascii=False),
                    s.get("mastery_level", 0),
                    s.get("confidence", 0.0),
                    s.get("unstable", 0),
                    s.get("self_uncertainty", 0.0),
                    s.get("first_answer_time"),
                    _type_map.get(qid) or exam_type or DEFAULT_EXAM_TYPE,
                )
                for qid, s in stats.items()
            ])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_question_stats(self, question_id, user_id=None) -> dict:
        """按需查询单条统计，不再加载全量"""
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM question_stats WHERE question_id = ? AND user_id = ?", (question_id, uid))
            row = cur.fetchone()
            if row is None:
                return {
                    "correct_count": 0, "wrong_count": 0,
                    "last_answer_time": None, "last_correct": None,
                    "answer_history": [], "mastery_level": 0,
                    "confidence": 0.0, "unstable": False,
                    "self_uncertainty": 0.0, "first_answer_time": None,
                }
            s = {
                "correct_count": row["correct_count"],
                "wrong_count": row["wrong_count"],
                "last_answer_time": row["last_answer_time"],
                "last_correct": bool(row["last_correct"]) if row["last_correct"] is not None else None,
                "answer_history": json.loads(row["answer_history"]) if row["answer_history"] else [],
                "mastery_level": row["mastery_level"],
                "confidence": row["confidence"],
                "unstable": bool(row["unstable"]),
                "self_uncertainty": row["self_uncertainty"],
                "first_answer_time": row["first_answer_time"],
            }
            now = datetime.now()
            threshold = get_retention_threshold(self.db_path, uid)
            if s["last_correct"] is True and s["last_answer_time"]:
                try:
                    last_time = datetime.fromisoformat(s["last_answer_time"])
                    s["retention_due"] = (now - last_time).days > threshold
                except (ValueError, TypeError):
                    s["retention_due"] = False
            else:
                s["retention_due"] = False
            return s
        finally:
            conn.close()

    def get_all_question_stats(self, exam_type=None, user_id=None) -> dict:
        return self.load_question_stats(exam_type=exam_type, user_id=user_id)

    def clear_question_stats(self, question_id=None, user_id=None) -> None:
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if question_id:
                cur.execute("DELETE FROM question_stats WHERE question_id = ? AND user_id = ?", (question_id, uid))
            else:
                cur.execute("DELETE FROM question_stats WHERE user_id = ?", (uid,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def load_uncertain_questions(self, exam_type=None, user_id=None) -> list:
        """加载当前用户标记为不确定的题目，按 self_uncertainty 降序"""
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute("""
                    SELECT q.*, qs.self_uncertainty
                    FROM question_stats qs
                    JOIN questions q ON qs.question_id = q.id
                    WHERE qs.user_id = ? AND qs.self_uncertainty > 0 AND q.exam_type = ?
                    ORDER BY qs.self_uncertainty DESC
                """, (uid, exam_type))
            else:
                cur.execute("""
                    SELECT q.*, qs.self_uncertainty
                    FROM question_stats qs
                    JOIN questions q ON qs.question_id = q.id
                    WHERE qs.user_id = ? AND qs.self_uncertainty > 0
                    ORDER BY qs.self_uncertainty DESC
                """, (uid,))
            result = []
            for row in cur.fetchall():
                d = dict(row)
                d["options"] = json.loads(d["options"]) if d["options"] else {}
                d["uncertainty_score"] = d["self_uncertainty"]
                result.append(d)
            return result
        finally:
            conn.close()

    def clear_uncertain_mark(self, question_id, user_id=None) -> None:
        """清除某道题的不确定标记（设置 self_uncertainty = 0）"""
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE question_stats SET self_uncertainty = 0 WHERE question_id = ? AND user_id = ?",
                (question_id, uid)
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---------- 答题记录 ----------

    def load_answer_records(self, exam_type=None, user_id=None) -> list:
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute(
                    "SELECT * FROM answer_records WHERE user_id = ? AND exam_type = ? ORDER BY id",
                    (uid, exam_type))
            else:
                cur.execute("SELECT * FROM answer_records WHERE user_id = ? ORDER BY id", (uid,))
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def save_answer_records(self, records: list, user_id=None) -> None:
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM answer_records WHERE user_id = ?", (uid,))
            for rec in records:
                cur.execute("""
                    INSERT INTO answer_records
                    (user_id, question_id, user_answer, is_correct, mode, session_id, category, timestamp, exam_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    uid,
                    rec.get("question_id", ""),
                    rec.get("user_answer", ""),
                    1 if rec.get("is_correct") else 0,
                    rec.get("mode", ""),
                    rec.get("session_id", ""),
                    rec.get("category", ""),
                    rec.get("timestamp", ""),
                    rec.get("exam_type") or DEFAULT_EXAM_TYPE,
                ))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def append_answer_records(self, records: list, user_id=None) -> None:
        """批量插入答题记录（executemany 一次性写入）"""
        if not records:
            return
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.executemany("""
                INSERT INTO answer_records
                (user_id, question_id, user_answer, is_correct, mode, session_id, category, timestamp, exam_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    uid,
                    rec.get("question_id", ""),
                    rec.get("user_answer", ""),
                    1 if rec.get("is_correct") else 0,
                    rec.get("mode", ""),
                    rec.get("session_id", ""),
                    rec.get("category", ""),
                    rec.get("timestamp", ""),
                    rec.get("exam_type") or DEFAULT_EXAM_TYPE,
                )
                for rec in records
            ])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def batch_add_answer_records(self, records: list, exam_type=None, user_id=None) -> None:
        """批量添加答题记录——查询 category + 批量插入在单个连接内完成"""
        from utils.data_manager import infer_category
        uid = self._uid(user_id)
        now = datetime.now().isoformat()
        if not records:
            return

        qids = list(set(rec.get("question_id", "") for rec in records if rec.get("question_id")))
        placeholders = ",".join("?" for _ in qids) if qids else ""

        conn = self._get_conn()
        try:
            q_map = {}
            if qids:
                cur = conn.cursor()
                cur.execute(
                    f"SELECT id, category, source_file, exam_type FROM questions WHERE id IN ({placeholders})",
                    tuple(qids)
                )
                for row in cur.fetchall():
                    q_map[row["id"]] = {
                        "category": row["category"],
                        "source_file": row["source_file"],
                        "exam_type": row["exam_type"],
                    }

            rows = []
            for rec in records:
                qid = rec.get("question_id", "")
                q_info = q_map.get(qid)
                category = "未知"
                et = exam_type or DEFAULT_EXAM_TYPE
                if q_info:
                    category = q_info.get("category") or infer_category(q_info.get("source_file", ""))
                    et = q_info.get("exam_type") or et
                rows.append((
                    uid,
                    qid,
                    rec.get("user_answer", ""),
                    1 if rec.get("is_correct") else 0,
                    rec.get("mode", "mock_exam"),
                    rec.get("session_id", ""),
                    category,
                    rec.get("timestamp", now),
                    et,
                ))

            cur = conn.cursor()
            cur.executemany("""
                INSERT INTO answer_records
                (user_id, question_id, user_answer, is_correct, mode, session_id, category, timestamp, exam_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---------- 考试记录 / 背题记录 / 模拟考试记录 ----------

    def load_exam_records(self, exam_type=None, user_id=None) -> list:
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute("SELECT data FROM exam_records WHERE user_id = ? AND exam_type = ? ORDER BY id",
                            (uid, exam_type))
            else:
                cur.execute("SELECT data FROM exam_records WHERE user_id = ? ORDER BY id", (uid,))
            return [json.loads(row["data"]) for row in cur.fetchall()]
        finally:
            conn.close()

    def append_exam_record(self, record: dict, exam_type=None, user_id=None) -> None:
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO exam_records (user_id, data, exam_type) VALUES (?, ?, ?)",
                (uid, json.dumps(record, ensure_ascii=False), exam_type or DEFAULT_EXAM_TYPE)
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def load_study_records(self, exam_type=None, user_id=None) -> list:
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute("SELECT * FROM study_records WHERE user_id = ? AND exam_type = ? ORDER BY session_id",
                            (uid, exam_type))
            else:
                cur.execute("SELECT * FROM study_records WHERE user_id = ? ORDER BY session_id", (uid,))
            records = []
            for row in cur.fetchall():
                r = dict(row)
                if r.get("details"):
                    r["details"] = json.loads(r["details"])
                records.append(r)
            return records
        finally:
            conn.close()

    def append_study_record(self, record: dict, exam_type=None, user_id=None) -> None:
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO study_records
                (session_id, user_id, mode, total, answered, correct, wrong, start_time, end_time, details, exam_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.get("session_id", ""),
                uid,
                record.get("mode", ""),
                record.get("total", 0),
                record.get("answered", 0),
                record.get("correct", 0),
                record.get("wrong", 0),
                record.get("start_time", ""),
                record.get("end_time", ""),
                json.dumps(record.get("details", []), ensure_ascii=False),
                exam_type or DEFAULT_EXAM_TYPE,
            ))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_study_record(self, session_id: str, data: dict, user_id=None) -> None:
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            set_clauses = []
            values = []
            for key, value in data.items():
                set_clauses.append(f"{key} = ?")
                values.append(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value)
            values.extend([session_id, uid])
            sql = f"UPDATE study_records SET {', '.join(set_clauses)} WHERE session_id = ? AND user_id = ?"
            cur.execute(sql, values)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def find_study_record(self, session_id: str, user_id=None) -> dict:
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM study_records WHERE session_id = ? AND user_id = ?", (session_id, uid))
            row = cur.fetchone()
            if row:
                r = dict(row)
                if r.get("details"):
                    r["details"] = json.loads(r["details"])
                return r
            return None
        finally:
            conn.close()

    def load_mock_exam_records(self, exam_type=None, user_id=None) -> list:
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute("SELECT data FROM mock_exam_records WHERE user_id = ? AND exam_type = ? ORDER BY id",
                            (uid, exam_type))
            else:
                cur.execute("SELECT data FROM mock_exam_records WHERE user_id = ? ORDER BY id", (uid,))
            return [json.loads(row["data"]) for row in cur.fetchall()]
        finally:
            conn.close()

    def append_mock_exam_record(self, record: dict, exam_type=None, user_id=None) -> None:
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO mock_exam_records (user_id, data, exam_type) VALUES (?, ?, ?)",
                (uid, json.dumps(record, ensure_ascii=False), exam_type or DEFAULT_EXAM_TYPE)
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---------- 配置 ----------

    def load_config(self, user_id=None) -> dict:
        """加载当前用户的配置（DEFAULT_CONFIG 兜底）"""
        from utils.data_manager import DEFAULT_CONFIG
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM user_config WHERE user_id = ?", (uid,))
            config = dict(DEFAULT_CONFIG)
            for row in cur.fetchall():
                config[row["key"]] = json.loads(row["value"]) if row["value"] else None
            return config
        finally:
            conn.close()

    def save_config(self, config: dict, user_id=None) -> None:
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            for key, value in config.items():
                cur.execute("""
                    INSERT OR REPLACE INTO user_config (user_id, key, value)
                    VALUES (?, ?, ?)
                """, (uid, key, json.dumps(value, ensure_ascii=False)))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_app_config(self, key, default=None):
        """读取全局配置（所有用户共享）"""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT value FROM app_config WHERE key = ?", (key,))
            row = cur.fetchone()
            if row is None or row[0] is None:
                return default
            try:
                return json.loads(row[0])
            except Exception:
                return row[0]
        finally:
            conn.close()

    def set_app_config(self, key, value) -> None:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO app_config (key, value) VALUES (?, ?)",
                (key, json.dumps(value, ensure_ascii=False))
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---------- 草稿 ----------

    @staticmethod
    def _draft_pk(user_id, prefix, draft_id) -> str:
        """草稿主键：必须带 user_id，否则不同用户的同名草稿会互相覆盖"""
        return f"{user_id}|{prefix}|{draft_id}"

    def save_draft(self, prefix: str, draft_id: str, data: dict, exam_type=None, user_id=None) -> None:
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO drafts (id, user_id, prefix, draft_id, data, saved_at, exam_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                self._draft_pk(uid, prefix, draft_id),
                uid,
                prefix,
                draft_id,
                json.dumps(data, ensure_ascii=False, indent=2),
                datetime.now().isoformat(),
                exam_type or DEFAULT_EXAM_TYPE,
            ))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def load_drafts(self, prefix: str, exam_type=None, user_id=None) -> list:
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute(
                    "SELECT draft_id, data, saved_at FROM drafts "
                    "WHERE user_id = ? AND prefix = ? AND exam_type = ? ORDER BY saved_at DESC",
                    (uid, prefix, exam_type)
                )
            else:
                cur.execute(
                    "SELECT draft_id, data, saved_at FROM drafts "
                    "WHERE user_id = ? AND prefix = ? ORDER BY saved_at DESC",
                    (uid, prefix)
                )
            results = []
            for row in cur.fetchall():
                record = json.loads(row["data"])
                record["draft_id"] = row["draft_id"]
                record["saved_at"] = row["saved_at"]
                results.append(record)
            return results
        finally:
            conn.close()

    def delete_draft(self, prefix: str, draft_id: str, user_id=None) -> None:
        uid = self._uid(user_id)
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM drafts WHERE id = ?", (self._draft_pk(uid, prefix, draft_id),))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def clear_exam_records(self, exam_type: str, user_id=None) -> dict:
        """清空当前用户在指定题库下的所有答题记录（保留题目不变）

        Returns:
            dict: 各表删除的行数 {"answer_records": N, "question_stats": N, ...}
        """
        uid = self._uid(user_id)
        tables = [
            "answer_records",
            "question_stats",
            "wrong_questions",
            "exam_records",
            "mock_exam_records",
            "study_records",
            "drafts",
        ]
        result = {}
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            for t in tables:
                cur.execute(f'DELETE FROM "{t}" WHERE user_id = ? AND exam_type = ?', (uid, exam_type))
                result[t] = cur.rowcount
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return result

    # ---------- 身份：用户与设备 ----------

    def get_user(self, user_id) -> dict:
        if not user_id:
            return {}
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            return dict(row) if row else {}
        finally:
            conn.close()

    def get_user_by_username(self, username) -> dict:
        if not username:
            return {}
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE LOWER(username) = ?", (str(username).strip().lower(),))
            row = cur.fetchone()
            return dict(row) if row else {}
        finally:
            conn.close()

    def list_users(self) -> list:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT u.*,
                       (SELECT COUNT(*) FROM user_devices d WHERE d.user_id = u.user_id) AS device_count
                FROM users u ORDER BY u.created_at
            """)
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def upsert_user(self, user_id, username=None, password_hash=None,
                    role="user", display_name=None) -> None:
        """插入或更新用户（只覆盖显式传入的字段，不丢既有数据）"""
        if not user_id:
            raise ValueError("upsert_user 需要 user_id")
        now = datetime.now().isoformat()
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
            exists = cur.fetchone() is not None
            if exists:
                sets, vals = [], []
                if username is not None:
                    sets.append("username = ?"); vals.append(username)
                if password_hash is not None:
                    sets.append("password_hash = ?"); vals.append(password_hash)
                if role is not None:
                    sets.append("role = ?"); vals.append(role)
                if display_name is not None:
                    sets.append("display_name = ?"); vals.append(display_name)
                if sets:
                    vals.append(user_id)
                    cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE user_id = ?", vals)
            else:
                cur.execute("""
                    INSERT INTO users (user_id, username, password_hash, role, display_name, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (user_id, username, password_hash, role or "user", display_name, now))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def set_user_password(self, user_id, password_hash) -> None:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE users SET password_hash = ? WHERE user_id = ?", (password_hash, user_id))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def clear_user_account(self, user_id) -> None:
        """解除账号绑定：清空用户名与密码，用户回退为匿名设备用户（数据保留）"""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET username = NULL, password_hash = NULL, role = 'user' WHERE user_id = ?",
                (user_id,)
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def touch_user_login(self, user_id, ts=None) -> None:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE users SET last_login = ? WHERE user_id = ?",
                        (ts or datetime.now().isoformat(), user_id))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_device_user(self, device_fp) -> str:
        if not device_fp:
            return ""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM user_devices WHERE device_fp = ?", (device_fp,))
            row = cur.fetchone()
            return row["user_id"] if row else ""
        finally:
            conn.close()

    def bind_device(self, device_fp, user_id) -> None:
        if not device_fp or not user_id:
            return
        now = datetime.now().isoformat()
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO user_devices (device_fp, user_id, first_seen, last_seen)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(device_fp) DO UPDATE SET user_id = excluded.user_id, last_seen = excluded.last_seen
            """, (device_fp, user_id, now, now))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def unbind_device(self, device_fp) -> None:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM user_devices WHERE device_fp = ?", (device_fp,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def list_devices(self, user_id) -> list:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM user_devices WHERE user_id = ? ORDER BY first_seen", (user_id,))
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()


def _ensure_parent_dir(db_path: str) -> None:
    """确保数据库所在目录存在（sqlite 自己不会创建父目录）"""
    try:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


# ========================================
# 工厂函数
# ========================================

_DAO_SINGLETON = None


def get_data_access(db_path=None, user_id=None) -> DataAccess:
    """返回数据访问对象（单库，进程内单例）

    单库多租户：全系统只有一个 data/exmsys.db，用户隔离靠 SQL 里的 user_id/owner_id。
    DAO 持有「当前用户」上下文，由 data_manager.set_current_user() 每帧校正
    （解决 Streamlit 多 session 共享模块级全局变量导致的串号问题）。
    """
    global _DAO_SINGLETON
    if _DAO_SINGLETON is None:
        _DAO_SINGLETON = SQLiteDataAccess(db_path=db_path, user_id=user_id)
    elif user_id is not None:
        _DAO_SINGLETON.set_user_id(user_id)
    return _DAO_SINGLETON


def reset_data_access():
    """丢弃单例（测试或库切换时使用）"""
    global _DAO_SINGLETON
    _DAO_SINGLETON = None

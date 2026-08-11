"""
数据访问层 — 抽象数据源，支持 SQLite / Supabase 切换
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime

# 常量（本地定义，避免循环导入）
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# SQLite 数据库路径
SQLITE_DB = DATA_DIR / "exmsys.db"

# 遗忘预警阈值缓存
_retention_threshold_cache = None

# 题库数据版本号的 config 键名
QUESTIONS_VERSION_KEY = "_questions_data_version"


def get_retention_threshold():
    """从数据库配置读取遗忘预警阈值（距上次答对 > 此天数触发预警）"""
    global _retention_threshold_cache
    try:
        # 直接读取数据库中的 config 表
        import sqlite3
        conn = sqlite3.connect(str(SQLITE_DB), timeout=5)
        try:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM config WHERE key = 'retention_days_threshold'")
            row = cur.fetchone()
            if row:
                value = json.loads(row[1]) if row[1] else 5
                _retention_threshold_cache = int(value)
            else:
                _retention_threshold_cache = 5  # 默认值
            return _retention_threshold_cache
        finally:
            conn.close()
    except Exception:
        return 5  # 默认值



# ========================================
# 抽象基类
# ========================================

class DataAccess:
    """数据访问抽象基类 — 所有数据操作接口"""

    # ---- 题库 ----
    def load_questions(self) -> list:
        raise NotImplementedError

    def save_questions(self, questions: list) -> None:
        raise NotImplementedError

    def get_question_count(self, exam_type=None) -> dict:
        raise NotImplementedError

    def get_questions_by_type(self, question_type, exam_type=None) -> list:
        raise NotImplementedError

    def get_available_exam_types(self) -> list:
        raise NotImplementedError

    def get_questions_by_exam_type(self, exam_type) -> list:
        raise NotImplementedError

    # ---- 案例题 ----
    def load_case_studies(self, exam_type=None) -> list:
        raise NotImplementedError

    def save_case_studies(self, case_studies: list) -> None:
        raise NotImplementedError

    def get_case_sub_questions(self, case_id: str) -> list:
        raise NotImplementedError

    def dedup_import(self, existing_questions, new_questions) -> tuple:
        raise NotImplementedError

    # ---- 错题 ----
    def load_wrong_questions(self, exam_type=None) -> list:
        raise NotImplementedError

    def save_wrong_questions(self, wrong_list) -> None:
        raise NotImplementedError

    def add_wrong_record(self, question_id, user_answer) -> None:
        raise NotImplementedError

    def add_correct_record(self, question_id) -> None:
        raise NotImplementedError

    def batch_update_wrong_and_stats(self, wrong_qids, correct_qids,
                                      stats_updates, uncertain_map=None,
                                      exam_record=None) -> None:
        raise NotImplementedError

    def get_top_wrong_questions(self, count=50, exam_type=None) -> list:
        raise NotImplementedError

    def remove_wrong_question(self, question_id) -> None:
        raise NotImplementedError

    def clear_all_wrong(self) -> None:
        raise NotImplementedError

    def get_wrong_stats(self, exam_type=None) -> dict:
        raise NotImplementedError

    def get_all_wrong_with_stats(self, exam_type=None, limit=None) -> list:
        raise NotImplementedError

    # ---- 答题统计 ----
    def load_question_stats(self, exam_type=None) -> dict:
        raise NotImplementedError

    def save_question_stats(self, stats: dict) -> None:
        raise NotImplementedError

    def get_question_stats(self, question_id) -> dict:
        raise NotImplementedError

    def get_all_question_stats(self, exam_type=None) -> dict:
        raise NotImplementedError

    def clear_question_stats(self, question_id=None) -> None:
        raise NotImplementedError

    def load_uncertain_questions(self, exam_type=None) -> list:
        """加载所有标记为不确定的题目，按 self_uncertainty 降序"""
        raise NotImplementedError

    def clear_uncertain_mark(self, question_id) -> None:
        """清除某道题的不确定标记（设置 self_uncertainty = 0）"""
        raise NotImplementedError

    # ---- 答题记录 ----
    def load_answer_records(self, exam_type=None) -> list:
        raise NotImplementedError

    def save_answer_records(self, records: list) -> None:
        raise NotImplementedError

    def append_answer_records(self, records: list) -> None:
        raise NotImplementedError

    def batch_add_answer_records(self, records: list) -> None:
        raise NotImplementedError

    # ---- 考试记录 ----
    def load_exam_records(self, exam_type=None) -> list:
        raise NotImplementedError

    def append_exam_record(self, record: dict) -> None:
        raise NotImplementedError

    # ---- 背题记录 ----
    def load_study_records(self, exam_type=None) -> list:
        raise NotImplementedError

    def append_study_record(self, record: dict) -> None:
        raise NotImplementedError

    def update_study_record(self, session_id: str, data: dict) -> None:
        raise NotImplementedError

    def find_study_record(self, session_id: str) -> dict:
        raise NotImplementedError

    # ---- 模拟考试记录 ----
    def load_mock_exam_records(self, exam_type=None) -> list:
        raise NotImplementedError

    def append_mock_exam_record(self, record: dict) -> None:
        raise NotImplementedError

    # ---- 配置 ----
    def load_config(self) -> dict:
        raise NotImplementedError

    def save_config(self, config: dict) -> None:
        raise NotImplementedError

    # ---- 草稿 ----
    def save_draft(self, prefix: str, draft_id: str, data: dict, exam_type: str = None) -> None:
        raise NotImplementedError

    def load_drafts(self, prefix: str, exam_type: str = None) -> list:
        raise NotImplementedError

    def delete_draft(self, prefix: str, draft_id: str) -> None:
        raise NotImplementedError


# ========================================
# SQLite 实现
# ========================================

class SQLiteDataAccess(DataAccess):
    """SQLite 数据库实现"""

    def __init__(self):
        self.db_path = str(SQLITE_DB)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        # WAL 模式 + 性能优化：大幅提升并发读写性能
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-4000")
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

    def _init_db(self):
        """初始化数据库表结构"""
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            # 题库表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS questions (
                    id TEXT PRIMARY KEY,
                    source_file TEXT,
                    index_num INTEGER,
                    type TEXT NOT NULL,
                    question TEXT NOT NULL,
                    options TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    explanation TEXT,
                    md5 TEXT UNIQUE NOT NULL,
                    category TEXT,
                    exam_type TEXT DEFAULT '心理学会咨询师四级'
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_questions_exam_type ON questions(exam_type)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_questions_category ON questions(category)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_questions_type ON questions(type)")

            # 案例题新增列（兼容旧结构，重复执行不报错）
            for col, col_def in [
                ("case_study_id", "TEXT"),
                ("is_case_background", "INTEGER DEFAULT 0"),
            ]:
                try:
                    cur.execute(f"ALTER TABLE questions ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass  # 列已存在，跳过

            # 兼容旧库：为早期缺少 exam_type 的表补列（重复执行不报错）
            for table, col, col_def in [
                ("question_stats", "exam_type", "TEXT DEFAULT '心理学会咨询师四级'"),
                ("answer_records", "exam_type", "TEXT DEFAULT '心理学会咨询师四级'"),
                ("wrong_questions", "exam_type", "TEXT DEFAULT '心理学会咨询师四级'"),
                ("exam_records", "exam_type", "TEXT DEFAULT '心理学会咨询师四级'"),
                ("study_records", "exam_type", "TEXT DEFAULT '心理学会咨询师四级'"),
                ("mock_exam_records", "exam_type", "TEXT DEFAULT '心理学会咨询师四级'"),
                ("drafts", "exam_type", "TEXT DEFAULT '心理学会咨询师四级'"),
            ]:
                try:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass  # 列已存在，跳过

            # 案例表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS case_studies (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    background_id TEXT NOT NULL,
                    question_count INTEGER DEFAULT 0,
                    exam_type TEXT DEFAULT '心理学会咨询师四级',
                    FOREIGN KEY (background_id) REFERENCES questions(id)
                )
            """)

            # 答题统计表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS question_stats (
                    question_id TEXT PRIMARY KEY,
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
                    exam_type TEXT DEFAULT '心理学会咨询师四级',
                    FOREIGN KEY (question_id) REFERENCES questions(id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_question_stats_exam_type ON question_stats(exam_type)")

            # 答题记录表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS answer_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_id TEXT NOT NULL,
                    user_answer TEXT,
                    is_correct INTEGER NOT NULL,
                    mode TEXT,
                    session_id TEXT,
                    category TEXT,
                    timestamp TEXT NOT NULL,
                    exam_type TEXT DEFAULT '心理学会咨询师四级',
                    FOREIGN KEY (question_id) REFERENCES questions(id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_answer_records_qid ON answer_records(question_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_answer_records_session ON answer_records(session_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_answer_records_timestamp ON answer_records(timestamp)")

            # 错题库表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS wrong_questions (
                    question_id TEXT PRIMARY KEY,
                    exam_type TEXT DEFAULT '心理学会咨询师四级',
                    FOREIGN KEY (question_id) REFERENCES questions(id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_wrong_questions_exam_type ON wrong_questions(exam_type)")

            # 考试记录表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS exam_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT NOT NULL,
                    exam_type TEXT DEFAULT '心理学会咨询师四级'
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_exam_records_exam_type ON exam_records(exam_type)")

            # 背题记录表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS study_records (
                    session_id TEXT PRIMARY KEY,
                    mode TEXT,
                    total INTEGER,
                    answered INTEGER,
                    correct INTEGER,
                    wrong INTEGER,
                    start_time TEXT,
                    end_time TEXT,
                    details TEXT,
                    exam_type TEXT DEFAULT '心理学会咨询师四级'
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_study_records_exam_type ON study_records(exam_type)")

            # 模拟考试记录表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mock_exam_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT NOT NULL,
                    exam_type TEXT DEFAULT '心理学会咨询师四级'
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_mock_exam_records_exam_type ON mock_exam_records(exam_type)")

            # 配置表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            # 确保题库版本号记录存在（首次创建时初始化为0）
            cur.execute("SELECT value FROM config WHERE key = ?", (QUESTIONS_VERSION_KEY,))
            if cur.fetchone() is None:
                cur.execute(
                    "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)",
                    (QUESTIONS_VERSION_KEY, json.dumps(0))
                )

            # 草稿表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS drafts (
                    id TEXT PRIMARY KEY,
                    prefix TEXT NOT NULL,
                    draft_id TEXT NOT NULL,
                    data TEXT NOT NULL,
                    saved_at TEXT NOT NULL,
                    exam_type TEXT DEFAULT '心理学会咨询师四级'
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_drafts_prefix ON drafts(prefix)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_drafts_exam_type ON drafts(exam_type)")

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---- 题库版本号（用于检测题库是否被外部修改） ----

    def get_questions_version(self) -> int:
        """获取当前题库版本号（config表中维护，仅 save_questions 时递增）"""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT value FROM config WHERE key = ?", (QUESTIONS_VERSION_KEY,))
            row = cur.fetchone()
            return int(json.loads(row[0])) if row else 0
        finally:
            conn.close()

    def _increment_questions_version_in_conn(self, conn) -> None:
        """在已有连接上递增题库版本号（供 save_questions 内部调用）"""
        cur = conn.cursor()
        cur.execute("SELECT value FROM config WHERE key = ?", (QUESTIONS_VERSION_KEY,))
        row = cur.fetchone()
        version = (int(json.loads(row[0])) + 1) if row else 1
        cur.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (QUESTIONS_VERSION_KEY, json.dumps(version))
        )

    # ---- 题库 ----

    def load_questions(self) -> list:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT q.*, cs.title AS case_background
                FROM questions q
                LEFT JOIN case_studies cs ON q.case_study_id = cs.id
            """)
            rows = cur.fetchall()
            questions = []
            for row in rows:
                q = dict(row)
                q["options"] = json.loads(q["options"])
                self._normalize_question(q)
                questions.append(q)
            return questions
        finally:
            conn.close()

    def load_question_by_id(self, question_id: str) -> dict:
        """按 ID 查询单道题目（用于防御性校验，避免加载全量表）"""
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

    def save_questions(self, questions: list) -> None:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM questions")
            for q in questions:
                cur.execute("""
                    INSERT INTO questions
                    (id, source_file, index_num, type, question, options, answer, explanation, md5, category, exam_type, case_study_id, is_case_background)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    q.get("id", ""),
                    q.get("source_file", ""),
                    q.get("index_num", q.get("index", 0)),
                    q.get("type", "single"),
                    q.get("question", ""),
                    json.dumps(q.get("options", {}), ensure_ascii=False),
                    q.get("answer", ""),
                    q.get("explanation", ""),
                    q.get("md5", ""),
                    q.get("category", ""),
                    q.get("exam_type", "心理学会咨询师四级"),
                    q.get("case_study_id", ""),
                    q.get("is_case_background", 0),
                ))
            # 题库被替换，递增版本号（通知 app.py 刷新缓存）
            self._increment_questions_version_in_conn(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_question_count(self, exam_type=None) -> dict:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute("SELECT type, COUNT(*) FROM questions WHERE exam_type = ? GROUP BY type", (exam_type,))
            else:
                cur.execute("SELECT type, COUNT(*) FROM questions GROUP BY type")
            rows = cur.fetchall()
            result = {"total": 0, "single": 0, "multi": 0, "judge": 0, "案例题": 0}
            for row in rows:
                t, cnt = row["type"], row["COUNT(*)"]
                result[t] = cnt
                result["total"] += cnt
            return result
        finally:
            conn.close()

    def get_questions_by_type(self, question_type, exam_type=None) -> list:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute("SELECT * FROM questions WHERE type = ? AND exam_type = ?", (question_type, exam_type))
            else:
                cur.execute("SELECT * FROM questions WHERE type = ?", (question_type,))
            rows = cur.fetchall()
            questions = []
            for row in rows:
                q = dict(row)
                q["options"] = json.loads(q["options"])
                self._normalize_question(q)
                questions.append(q)
            return questions
        finally:
            conn.close()

    # ---- 案例题 ----

    def load_case_studies(self, exam_type=None) -> list:
        """加载所有案例（case_studies 表）"""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute("SELECT * FROM case_studies WHERE exam_type = ? ORDER BY id", (exam_type,))
            else:
                cur.execute("SELECT * FROM case_studies ORDER BY id")
            rows = cur.fetchall()
            return [dict(row) for row in rows]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    def save_case_studies(self, case_studies: list) -> None:
        """批量保存案例背景（INSERT OR REPLACE）"""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            for cs in case_studies:
                cur.execute("""
                    INSERT OR REPLACE INTO case_studies
                    (id, title, background_id, question_count, exam_type)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    cs.get("case_id", ""),
                    cs.get("title", ""),
                    cs.get("background_id", ""),
                    cs.get("question_count", 0),
                    cs.get("exam_type", "心理学会咨询师四级"),
                ))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_case_sub_questions(self, case_id: str) -> list:
        """获取某案例的全部子题（排除背景题，按 index_num 排序）"""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM questions
                WHERE case_study_id = ? AND is_case_background = 0
                ORDER BY index_num
            """, (case_id,))
            rows = cur.fetchall()
            questions = []
            for row in rows:
                q = dict(row)
                q["options"] = json.loads(q["options"])
                self._normalize_question(q)
                questions.append(q)
            return questions
        finally:
            conn.close()

    def get_available_exam_types(self) -> list:
        from utils.data_manager import EXAM_TYPE_LABELS
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT exam_type FROM questions WHERE exam_type != ''")
            types = [row["exam_type"] for row in cur.fetchall()]
            result = []
            for t in sorted(types):
                label = EXAM_TYPE_LABELS.get(t, t)
                result.append((t, label))
            return result
        finally:
            conn.close()

    def get_questions_by_exam_type(self, exam_type) -> list:
        return self.get_questions_by_type("", exam_type)  # 获取所有题型

    def dedup_import(self, existing_questions, new_questions) -> tuple:
        from utils.data_manager import DEFAULT_CONFIG
        existing_md5s = {q["md5"] for q in existing_questions}
        added = 0
        skipped = 0
        log = []
        for q in new_questions:
            if q["md5"] in existing_md5s:
                skipped += 1
                log.append(f"  ⏭️ 跳过重复题: [{q['source_file']}] 第{q['index']}题")
            else:
                existing_questions.append(q)
                existing_md5s.add(q["md5"])
                added += 1
        return existing_questions, added, skipped, log

    # ---- 错题 ----

    def _extract_qids_from_wrong_list(self, wrong_list):
        return wrong_list  # SQLite 版直接返回 qid 列表

    def load_wrong_questions(self, exam_type=None) -> list:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute("""
                    SELECT w.question_id FROM wrong_questions w
                    JOIN questions q ON w.question_id = q.id
                    WHERE q.exam_type = ?
                """, (exam_type,))
            else:
                cur.execute("SELECT question_id FROM wrong_questions")
            return [row["question_id"] for row in cur.fetchall()]
        finally:
            conn.close()

    def save_wrong_questions(self, wrong_list, exam_type: str = None) -> None:
        """保存错题列表，自动带 exam_type。
        wrong_list 元素可以是 qid 字符串，或 (qid, exam_type) 元组。
        """
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM wrong_questions")
            for item in wrong_list:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    qid, et = item[0], item[1]
                else:
                    qid = item
                    # 自动查找 exam_type
                    cur2 = conn.cursor()
                    cur2.execute("SELECT exam_type FROM questions WHERE id = ?", (qid,))
                    row = cur2.fetchone()
                    et = row[0] if row else (exam_type or "心理学会咨询师四级")
                cur.execute(
                    "INSERT OR IGNORE INTO wrong_questions (question_id, exam_type) VALUES (?, ?)",
                    (qid, et)
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def add_wrong_record(self, question_id, user_answer) -> None:
        from utils.data_manager import _recalc_mastery_fields
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
        from utils.data_manager import _recalc_mastery_fields
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

    def batch_update_wrong_and_stats(self, wrong_qids, correct_qids,
                                      stats_updates, uncertain_map=None,
                                      exam_record=None) -> None:
        """增量更新：只查询和写入受影响的题目统计，单个事务内完成。
        可选参数 exam_record: 若提供，则在同一事务内写入考试记录，减少一次连接开销。"""
        from utils.data_manager import _recalc_mastery_fields
        now = datetime.now().isoformat()
        uncertain_map = uncertain_map or {}

        qid_user_ans = dict(wrong_qids)
        correct_qids_set = set(correct_qids)

        # 构建 affected_qids + stats_updates 索引（O(1) 查找）
        stats_updates_by_qid = {}
        affected_qids = set()
        for qid, is_correct in stats_updates:
            affected_qids.add(qid)
            if qid not in stats_updates_by_qid:
                stats_updates_by_qid[qid] = []
            stats_updates_by_qid[qid].append(is_correct)
        affected_qids.update(qid_user_ans.keys())
        affected_qids.update(correct_qids_set)

        if not affected_qids:
            return

        conn = self._get_conn()
        try:
            cur = conn.cursor()

            # 1) 只查询受影响的题目统计
            placeholders = ",".join("?" for _ in affected_qids)
            cur.execute(
                f"SELECT * FROM question_stats WHERE question_id IN ({placeholders})",
                tuple(affected_qids)
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
                        stats[qid]["self_uncertainty"] = round(
                            0.3 * new_unc + 0.7 * old_unc, 3)
                    else:
                        stats[qid]["self_uncertainty"] = 0.0

                _recalc_mastery_fields(stats[qid])

            # 2) 批量 upsert 受影响的统计行（带 exam_type）
            # 先批量查 exam_type
            if affected_qids:
                _placeholders = ",".join("?" for _ in affected_qids)
                _cur2 = conn.cursor()
                _cur2.execute(
                    f"SELECT id, exam_type FROM questions WHERE id IN ({_placeholders})",
                    tuple(affected_qids)
                )
                _type_map = {row["id"]: row["exam_type"] for row in _cur2.fetchall()}
            else:
                _type_map = {}

            cur.executemany("""
                INSERT OR REPLACE INTO question_stats
                (question_id, correct_count, wrong_count, last_answer_time, last_correct,
                 answer_history, mastery_level, confidence, unstable,
                 self_uncertainty, first_answer_time, exam_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    qid,
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
                    _type_map.get(qid, "心理学会咨询师四级"),
                )
                for qid in affected_qids
            ])

            # 3) 更新错题本（同一事务内）—— 增量更新，仅修改变化的行
            cur.execute("SELECT question_id FROM wrong_questions")
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
                    "DELETE FROM wrong_questions WHERE question_id = ?",
                    [(qid,) for qid in to_remove]
                )
            # 只插入新增的错题（带 exam_type）
            to_add = new_wrong - old_qids
            if to_add:
                _placeholders = ",".join("?" for _ in to_add)
                _cur2 = conn.cursor()
                _cur2.execute(
                    f"SELECT id, exam_type FROM questions WHERE id IN ({_placeholders})",
                    tuple(to_add)
                )
                _et_map = {row["id"]: row["exam_type"] for row in _cur2.fetchall()}
                cur.executemany(
                    "INSERT INTO wrong_questions (question_id, exam_type) VALUES (?, ?)",
                    [(qid, _et_map.get(qid, "心理学会咨询师四级")) for qid in to_add]
                )

            # 4) 考试记录（可选，同一事务内完成）
            if exam_record:
                cur.execute(
                    "INSERT INTO exam_records (data) VALUES (?)",
                    (json.dumps(exam_record, ensure_ascii=False),)
                )

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_top_wrong_questions(self, count=50, exam_type=None) -> list:
        from utils.data_manager import infer_category
        wrong_qids = self.load_wrong_questions()
        questions = self.load_questions()
        stats = self.load_question_stats()
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

    def remove_wrong_question(self, question_id) -> None:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM wrong_questions WHERE question_id = ?", (question_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def clear_all_wrong(self) -> None:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM wrong_questions")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_wrong_stats(self, exam_type=None) -> dict:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute("""
                    SELECT COUNT(*), COALESCE(MAX(s.wrong_count), 0)
                    FROM wrong_questions w
                    JOIN questions q ON w.question_id = q.id
                    LEFT JOIN question_stats s ON w.question_id = s.question_id
                    WHERE q.exam_type = ?
                """, (exam_type,))
            else:
                cur.execute("SELECT COUNT(*), COALESCE(MAX(s.wrong_count), 0) FROM wrong_questions w LEFT JOIN question_stats s ON w.question_id = s.question_id")
            row = cur.fetchone()
            if row[0] == 0:
                return {"total": 0, "most_wrong": 0}
            return {"total": row[0], "most_wrong": row[1] or 0}
        finally:
            conn.close()

    def get_all_wrong_with_stats(self, exam_type=None, limit=None) -> list:
        """获取所有错题，附带答题统计，按易错程度降序（SQL 层排序）

        Args:
            exam_type: 考试类型过滤
            limit: 限制返回数量（用于分页或 Top-N）
        """
        from utils.data_manager import infer_category
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
                LEFT JOIN question_stats s ON w.question_id = s.question_id
                LEFT JOIN case_studies cs ON q.case_study_id = cs.id
            """
            params = ()
            if exam_type:
                base += " WHERE q.exam_type = ?"
                params = (exam_type,)
            base += " ORDER BY (COALESCE(s.wrong_count, 0) - COALESCE(s.correct_count, 0)) DESC"
            if limit is not None:
                base += " LIMIT ?"
                params += (limit,)
            cur.execute(base, params)
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
                    "mastery_level": q.get("mastery_level", "未掌握"),
                    "confidence": q.get("confidence", 0),
                    "case_background": q.get("case_background") or "",
                })
            return result
        finally:
            conn.close()

    # ---- 答题统计 ----

    def load_question_stats(self, exam_type=None) -> dict:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute("SELECT * FROM question_stats WHERE exam_type = ?", (exam_type,))
            else:
                cur.execute("SELECT * FROM question_stats")
            rows = cur.fetchall()
            stats = {}
            now = datetime.now()
            threshold = get_retention_threshold()  # 提到循环外，避免每次迭代开连接
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

    def save_question_stats(self, stats: dict, exam_type: str = None) -> None:
        """批量 upsert 题目统计（executemany 一次性写入）
        
        Args:
            stats: {question_id: stats_dict}
            exam_type: 题库类型。若提供则直接写入；若 None 则自动从 questions 表查找。
                       为兼容旧调用，两个来源都尝试。
        """
        if not stats:
            return
        # 自动补填 exam_type（批量查一次，避免 N 次查询）
        if exam_type is None:
            qids = list(stats.keys())
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
                _type_map = {}
        else:
            _type_map = {qid: exam_type for qid in stats}

        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.executemany("""
                INSERT OR REPLACE INTO question_stats
                (question_id, correct_count, wrong_count, last_answer_time, last_correct,
                 answer_history, mastery_level, confidence, unstable,
                 self_uncertainty, first_answer_time, exam_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    qid,
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
                    _type_map.get(qid, "心理学会咨询师四级"),
                )
                for qid, s in stats.items()
            ])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_question_stats(self, question_id) -> dict:
        """按需查询单条统计，不再加载全量"""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM question_stats WHERE question_id = ?", (question_id,))
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
            threshold = get_retention_threshold()
            if s["last_correct"] is True and s["last_answer_time"]:
                try:
                    last_time = datetime.fromisoformat(s["last_answer_time"])
                    days_since = (now - last_time).days
                    s["retention_due"] = days_since > threshold
                except (ValueError, TypeError):
                    s["retention_due"] = False
            else:
                s["retention_due"] = False
            return s
        finally:
            conn.close()

    def get_all_question_stats(self, exam_type=None) -> dict:
        return self.load_question_stats(exam_type=exam_type)

    def clear_question_stats(self, question_id=None) -> None:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if question_id:
                cur.execute("DELETE FROM question_stats WHERE question_id = ?", (question_id,))
            else:
                cur.execute("DELETE FROM question_stats")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def load_uncertain_questions(self, exam_type=None) -> list:
        """加载所有标记为不确定的题目，按 self_uncertainty 降序"""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute("""
                    SELECT q.*, qs.self_uncertainty
                    FROM question_stats qs
                    JOIN questions q ON qs.question_id = q.id
                    WHERE qs.self_uncertainty > 0 AND q.exam_type = ?
                    ORDER BY qs.self_uncertainty DESC
                """, (exam_type,))
            else:
                cur.execute("""
                    SELECT q.*, qs.self_uncertainty
                    FROM question_stats qs
                    JOIN questions q ON qs.question_id = q.id
                    WHERE qs.self_uncertainty > 0
                    ORDER BY qs.self_uncertainty DESC
                """)
            rows = cur.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d["options"] = json.loads(d["options"]) if d["options"] else {}
                d["uncertainty_score"] = d["self_uncertainty"]
                result.append(d)
            return result
        finally:
            conn.close()

    def clear_uncertain_mark(self, question_id) -> None:
        """清除某道题的不确定标记（设置 self_uncertainty = 0）"""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE question_stats SET self_uncertainty = 0 WHERE question_id = ?",
                (question_id,)
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---- 答题记录 ----

    def load_answer_records(self, exam_type=None) -> list:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute("SELECT * FROM answer_records WHERE exam_type = ? ORDER BY id", (exam_type,))
            else:
                cur.execute("SELECT * FROM answer_records ORDER BY id")
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def save_answer_records(self, records: list) -> None:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM answer_records")
            for rec in records:
                cur.execute("""
                    INSERT INTO answer_records
                    (question_id, user_answer, is_correct, mode, session_id, category, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    rec.get("question_id", ""),
                    rec.get("user_answer", ""),
                    1 if rec.get("is_correct") else 0,
                    rec.get("mode", ""),
                    rec.get("session_id", ""),
                    rec.get("category", ""),
                    rec.get("timestamp", ""),
                ))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def append_answer_records(self, records: list) -> None:
        """批量插入答题记录（executemany 一次性写入）"""
        if not records:
            return
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.executemany("""
                INSERT INTO answer_records
                (question_id, user_answer, is_correct, mode, session_id, category, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    rec.get("question_id", ""),
                    rec.get("user_answer", ""),
                    1 if rec.get("is_correct") else 0,
                    rec.get("mode", ""),
                    rec.get("session_id", ""),
                    rec.get("category", ""),
                    rec.get("timestamp", ""),
                )
                for rec in records
            ])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def batch_add_answer_records(self, records: list, exam_type: str = None) -> None:
        """批量添加答题记录——查询 category + 批量插入在单个连接内完成
        
        Args:
            records: 答题记录列表
            exam_type: 题库类型。若提供则直接写入；若 None 则自动从 questions 表查找。
        """
        from utils.data_manager import infer_category
        now = datetime.now().isoformat()
        if not records:
            return

        # 只查出需要的题目 category + exam_type，不加载全部题目
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

            # 组装 + 批量插入（同一连接）
            rows = []
            for rec in records:
                qid = rec.get("question_id", "")
                q_info = q_map.get(qid)
                category = "未知"
                et = exam_type or "心理学会咨询师四级"
                if q_info:
                    category = q_info.get("category") or infer_category(q_info.get("source_file", ""))
                    et = q_info.get("exam_type") or et
                rows.append((
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
                (question_id, user_answer, is_correct, mode, session_id, category, timestamp, exam_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---- 考试记录 ----

    def load_exam_records(self, exam_type=None) -> list:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute("SELECT data FROM exam_records WHERE exam_type = ? ORDER BY id", (exam_type,))
            else:
                cur.execute("SELECT data FROM exam_records ORDER BY id")
            rows = cur.fetchall()
            return [json.loads(row["data"]) for row in rows]
        finally:
            conn.close()

    def append_exam_record(self, record: dict, exam_type: str = None) -> None:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO exam_records (data, exam_type) VALUES (?, ?)",
                (json.dumps(record, ensure_ascii=False), exam_type or "心理学会咨询师四级")
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---- 背题记录 ----

    def load_study_records(self, exam_type=None) -> list:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute("SELECT * FROM study_records WHERE exam_type = ? ORDER BY session_id", (exam_type,))
            else:
                cur.execute("SELECT * FROM study_records ORDER BY session_id")
            rows = cur.fetchall()
            records = []
            for row in rows:
                r = dict(row)
                if r.get("details"):
                    r["details"] = json.loads(r["details"])
                records.append(r)
            return records
        finally:
            conn.close()

    def append_study_record(self, record: dict, exam_type: str = None) -> None:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO study_records
                (session_id, mode, total, answered, correct, wrong, start_time, end_time, details, exam_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.get("session_id", ""),
                record.get("mode", ""),
                record.get("total", 0),
                record.get("answered", 0),
                record.get("correct", 0),
                record.get("wrong", 0),
                record.get("start_time", ""),
                record.get("end_time", ""),
                json.dumps(record.get("details", []), ensure_ascii=False),
                exam_type or "心理学会咨询师四级",
            ))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_study_record(self, session_id: str, data: dict) -> None:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            set_clauses = []
            values = []
            for key, value in data.items():
                set_clauses.append(f"{key} = ?")
                values.append(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value)
            values.append(session_id)
            sql = f"UPDATE study_records SET {', '.join(set_clauses)} WHERE session_id = ?"
            cur.execute(sql, values)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def find_study_record(self, session_id: str) -> dict:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM study_records WHERE session_id = ?", (session_id,))
            row = cur.fetchone()
            if row:
                r = dict(row)
                if r.get("details"):
                    r["details"] = json.loads(r["details"])
                return r
            return None
        finally:
            conn.close()

    # ---- 模拟考试记录 ----

    def load_mock_exam_records(self, exam_type=None) -> list:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute("SELECT data FROM mock_exam_records WHERE exam_type = ? ORDER BY id", (exam_type,))
            else:
                cur.execute("SELECT data FROM mock_exam_records ORDER BY id")
            rows = cur.fetchall()
            return [json.loads(row["data"]) for row in rows]
        finally:
            conn.close()

    def append_mock_exam_record(self, record: dict, exam_type: str = None) -> None:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO mock_exam_records (data, exam_type) VALUES (?, ?)",
                (json.dumps(record, ensure_ascii=False), exam_type or "心理学会咨询师四级")
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---- 配置 ----

    def load_config(self) -> dict:
        from utils.data_manager import DEFAULT_CONFIG
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM config")
            rows = cur.fetchall()
            config = dict(DEFAULT_CONFIG)
            for row in rows:
                config[row["key"]] = json.loads(row["value"]) if row["value"] else None
            return config
        finally:
            conn.close()

    def save_config(self, config: dict) -> None:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            for key, value in config.items():
                cur.execute("""
                    INSERT OR REPLACE INTO config (key, value)
                    VALUES (?, ?)
                """, (key, json.dumps(value, ensure_ascii=False)))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---- 草稿 ----

    def save_draft(self, prefix: str, draft_id: str, data: dict, exam_type: str = None) -> None:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO drafts (id, prefix, draft_id, data, saved_at, exam_type)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                f"{prefix}_{draft_id}",
                prefix,
                draft_id,
                json.dumps(data, ensure_ascii=False, indent=2),
                datetime.now().isoformat(),
                exam_type or "心理学会咨询师四级",
            ))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def load_drafts(self, prefix: str, exam_type: str = None) -> list:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            if exam_type:
                cur.execute(
                    "SELECT draft_id, data, saved_at FROM drafts WHERE prefix = ? AND exam_type = ? ORDER BY saved_at DESC",
                    (prefix, exam_type)
                )
            else:
                cur.execute(
                    "SELECT draft_id, data, saved_at FROM drafts WHERE prefix = ? ORDER BY saved_at DESC",
                    (prefix,)
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

    def delete_draft(self, prefix: str, draft_id: str) -> None:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM drafts WHERE id = ?", (f"{prefix}_{draft_id}",))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def clear_exam_records(self, exam_type: str) -> dict:
        """清空指定题库的所有答题记录（保留题目不变）

        Args:
            exam_type: 题库类型，如 "心理协会咨询师初级"

        Returns:
            dict: 各表删除的行数 {"answer_records": N, "question_stats": N, ...}
        """
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
                cur.execute(f'DELETE FROM "{t}" WHERE exam_type = ?', (exam_type,))
                result[t] = cur.rowcount
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return result


# ========================================
# 工厂函数
# ========================================

def get_data_access() -> DataAccess:
    """
    返回数据访问对象。

    当前固定使用 SQLite 数据库存储。
    JSON 数据源选项已移除。
    """
    return SQLiteDataAccess()

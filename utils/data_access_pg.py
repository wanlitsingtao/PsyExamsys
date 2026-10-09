# -*- coding: utf-8 -*-
"""
PostgreSQL / Supabase 数据访问实现 —— 靠【方言翻译】复用 SQLite 版的全部业务 SQL

设计取舍（重要，看完再改）
================================================================
本项目有 131 条业务 SQL、共 109 个 `?` 占位符，全部写在 `SQLiteDataAccess` 里。
把 Postgres 版另写一遍（手抄 2000 行 SQL）的代价是：
  · 一次性抄写风险极高（漏列、错列、错顺序都是静默数据损坏）
  · 以后每次改功能都要改两处，必然漂移

所以这里采用【一个方言翻译层】：
    PostgresDataAccess(SQLiteDataAccess)  —— 继承全部业务逻辑，SQL 一个字不改
    只覆盖 5 个与存储引擎直接相关的方法：
        __init__ / _get_conn / _get_light_conn / _init_db / _assert_schema_ready
    由 PgCursor 在 execute 时把 SQLite 方言翻成 Postgres 方言。

**好处：SQL 只有一份来源，不存在漂移。**
代价：多了一层"魔法"，所以翻译规则必须完整、可测 —— 见 scripts/test_pg_dialect.py
（它把 data_access.py 里 129 条 SQL 全抽出来逐条翻译 + 用 postgres 方言解析校验）。

翻译规则（只有 4 条，已穷举扫描确认无遗漏）
================================================================
1. `?`                      -> `%s`
   已扫描确认：全项目 SQL 的字符串字面量里没有「引号内的 ?」，可安全直替。
2. `INSERT OR REPLACE INTO t (cols) ...`
   -> `INSERT INTO t (cols) ... ON CONFLICT (<主键/唯一键>) DO UPDATE SET c=EXCLUDED.c, ...`
   ⚠️ 语义差异说明：SQLite 的 REPLACE 是「先删后插」，未列出的列会被重置为默认值；
      Postgres 的 DO UPDATE 是「更新」，未列出的列保持原值。
      本项目 9 处 REPLACE 全部**列出了该表的全部列**，两种语义完全等价
      （test_pg_dialect.py 里有断言守住这一前提）。
3. `INSERT OR IGNORE INTO t ...` -> `INSERT INTO t ... ON CONFLICT DO NOTHING`
4. `PRAGMA ...` / `sqlite_master` -> 映射到 information_schema（见 _translate）
   · `PRAGMA journal_mode=WAL` / `synchronous` / `cache_size` 这类调优语句在 PG 下直接吞掉
     （PG 由服务端管理，客户端没有对应概念）
   · `PRAGMA table_info(x)` -> information_schema.columns，且**保持 SQLite 的列序**
     （cid, name, type, notnull, dflt_value, pk），因为调用方用 `r[1]` 取列名
   · `SELECT 1 FROM sqlite_master WHERE type='table' AND name=?` -> information_schema.tables

连接方式
================================================================
· 走连接池（Streamlit 每次 rerun 都要读库，不池化会打爆 Supabase 免费版的 15 连接上限）
· 归还连接前强制 rollback，避免"带着未结束事务的连接"回到池里
· 空闲超过 60 秒的连接在取出时先探活一次（云数据库会掐掉长时间空闲的 TCP）

目标 schema（同一实例多应用隔离）
================================================================
一个云实例（一个 Supabase 项目）就是一个 PostgreSQL 实例，可以建多个 schema
让不同应用各占一个：别人的应用留在 public，本项目用 psych_exm。

实现方式：**不动业务 SQL**（131 条 SQL 里表名都是不带 schema 前缀的裸名），
改为在每条物理连接建立后执行一次 `SET search_path TO <schema>`，
让裸表名解析到目标 schema。

⚠️ search_path **只放目标 schema，刻意不放 public**：
   另一个应用的表就在 public 里（users / drafts 这类名字两边都可能存在），
   一旦某个表名写错，只放目标 schema 会**立刻报 "relation does not exist"**；
   若把 public 也放进去，就会**静默读到别人的表** —— 那是灾难级的错。
   13 张表由 preflight.py 与应用启动自检（_init_db）双重确认，不会漏。

⚠️ `SET search_path` 是**会话级**语句，因此：
   · 只支持 Session pooler（Supabase :5432）与直连，不支持 transaction pooler（:6543）
   · 不能用 `options=-c search_path=...` 走启动参数 —— pgbouncer 会把它丢掉
"""

import os
import re
import threading
import time

import psycopg2
import psycopg2.extensions
import psycopg2.extras
from psycopg2 import pool as _pgpool

# 复用 SQLite 版的全部业务实现
from utils.data_access import SQLiteDataAccess, DEFAULT_PG_SCHEMA


# ==========================================================
# 行对象：同时支持 row[0]（下标）与 row["col"]（列名）
# ==========================================================

class PgRow(tuple):
    """对齐 sqlite3.Row 的用法。

    项目里两种访问方式都有：`r[1]`（取 PRAGMA 列名）与 `row["question_id"]`。
    另外 `dict(row)` 也用得很广 —— 它走 keys() 这条映射协议，所以必须实现 keys()。
    自己实现而不用 psycopg2 的 DictRow，是为了让行为完全确定、可离线单测。
    """

    # 注意：tuple 子类不允许非空 __slots__，所以这里不声明 __slots__，
    # 实例会带一个 __dict__ 存 _idx（每行几十字节开销，可接受）。
    def __new__(cls, values, idx):
        self = super().__new__(cls, values)
        self._idx = idx
        return self

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return tuple.__getitem__(self, self._idx[key])
            except KeyError:
                raise KeyError(f"列名不存在: {key}；可用列: {list(self._idx)}")
        if isinstance(key, int):
            if -len(self) <= key < len(self):
                return tuple.__getitem__(self, key)
            raise IndexError(f"行下标越界: {key}")
        return tuple.__getitem__(self, key)  # slice

    def keys(self):
        return list(self._idx.keys())

    def values(self):
        return list(self)

    def items(self):
        return [(k, tuple.__getitem__(self, i)) for k, i in self._idx.items()]

    def get(self, key, default=None):
        return self[key] if key in self._idx else default

    def __contains__(self, key):
        return key in self._idx

    def copy(self):
        return {k: tuple.__getitem__(self, i) for k, i in self._idx.items()}


# ==========================================================
# 方言翻译
# ==========================================================

# 表 -> 冲突目标（= 该表的主键或唯一键）
_CONFLICT_TARGETS = {
    "app_config":         ["key"],
    "case_studies":       ["id"],
    "drafts":             ["id"],
    "question_stats":     ["question_id", "user_id"],
    "questions":          ["id"],
    "study_records":      ["session_id"],
    "user_config":        ["user_id", "key"],
    "user_devices":       ["device_fp"],
    "users":              ["user_id"],
    "wrong_questions":    ["question_id", "user_id"],
}

# INSERT OR (REPLACE|IGNORE) INTO <table> (<cols>)
_UPSERT_RE = re.compile(
    r"^\s*INSERT\s+OR\s+(REPLACE|IGNORE)\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)",
    re.IGNORECASE | re.DOTALL,
)

# 客户端侧无意义的 PRAGMA（PG 由服务端管理），直接吞掉
_PRAGMA_NOOP_RE = re.compile(
    r"^\s*PRAGMA\s+(journal_mode|synchronous|cache_size|foreign_keys|"
    r"busy_timeout|temp_store|mmap_size|wal_autocheckpoint)\b",
    re.IGNORECASE,
)

_PRAGMA_TABLE_INFO_RE = re.compile(
    r"^\s*PRAGMA\s+table_info\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*$",
    re.IGNORECASE,
)

_SQLITE_MASTER_RE = re.compile(
    r"SELECT\s+1\s+FROM\s+sqlite_master\s+WHERE\s+type\s*=\s*'table'\s+AND\s+name\s*=\s*\?",
    re.IGNORECASE,
)

# PRAGMA table_info 的等价查询。**刻意保持与 SQLite 相同的列序与列名**：
# SQLite 返回 (cid, name, type, notnull, dflt_value, pk)，调用方用 r[1] 取列名。
_TABLE_INFO_SQL = """
    SELECT (c.ordinal_position - 1)::int                                   AS cid,
           c.column_name                                                   AS name,
           c.data_type                                                     AS type,
           CASE WHEN c.is_nullable = 'NO' THEN 1 ELSE 0 END                AS notnull,
           c.column_default                                                AS dflt_value,
           (SELECT count(*)
              FROM pg_index i
              JOIN pg_attribute a
                ON a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey)
             WHERE i.indrelid = (quote_ident(c.table_schema) || '.' ||
                                 quote_ident(c.table_name))::regclass
               AND i.indisprimary
               AND a.attname = c.column_name)                              AS pk
      FROM information_schema.columns c
     WHERE c.table_schema = %s AND c.table_name = %s
     ORDER BY c.ordinal_position
"""

_SQLITE_MASTER_SQL = """
    SELECT 1 FROM information_schema.tables
     WHERE table_name = %s AND table_schema = %s AND table_type = 'BASE TABLE'
"""

# ⚠️ 两个常量里的 %s 顺序不能随意调 —— PgCursor.execute 的参数规则是
#    「调用方参数在前，extra_params 在后」（见 PgCursor.execute）：
#      PRAGMA table_info(x)                 调用方无参数     -> 顺序 (schema, 表名)
#      sqlite_master ... WHERE name=?       调用方带 1 个表名 -> 顺序 (表名, schema)


class TranslatedSQL(str):
    """翻译结果 + 是否需要特殊参数（目前只有 table_info 用到）"""

    kind = "sql"
    extra_params = ()


def translate_sql(sql: str, schema: str = DEFAULT_PG_SCHEMA):
    """把 SQLite 方言翻成 Postgres 方言。

    schema 只影响两条把 SQLite 元数据映射到 information_schema 的查询
    （PRAGMA table_info / sqlite_master）；业务 SQL 一个字都不用改 ——
    业务表名都是裸名，靠连接上的 search_path 解析到目标 schema。

    返回 TranslatedSQL（str 子类，带 .kind / .extra_params）。
    """
    if not isinstance(sql, str):
        raise TypeError(f"translate_sql 只接受 str，收到 {type(sql)}")

    s = sql

    # ---- PRAGMA ----
    if _PRAGMA_NOOP_RE.match(s):
        # 客户端侧的无意义调优语句：换成一条一定返回空结果集的查询，
        # 保证 fetchone() -> None、fetchall() -> [] 的调用方行为不变。
        out = TranslatedSQL("SELECT NULL WHERE FALSE")
        out.kind = "noop"
        return out

    m = _PRAGMA_TABLE_INFO_RE.match(s)
    if m:
        out = TranslatedSQL(_TABLE_INFO_SQL)
        out.kind = "sql"
        # 参数顺序必须与 SQL 里 %s 出现的顺序一致：先 schema，后表名
        out.extra_params = (schema, m.group(1).lower())
        return out

    if re.match(r"^\s*PRAGMA\b", s, re.IGNORECASE):
        raise NotImplementedError(f"未支持的 PRAGMA 语句，请补充翻译规则：{s[:120]}")

    # ---- upsert ----
    m = _UPSERT_RE.match(s)
    if m:
        kind = m.group(1).upper()
        table = m.group(2).lower()
        col_list = m.group(3)
        rest = s[m.end():].rstrip().rstrip(";")
        if kind == "IGNORE":
            s = f"INSERT INTO {table} ({col_list}) {rest} ON CONFLICT DO NOTHING"
        else:
            target = _CONFLICT_TARGETS.get(table)
            if not target:
                raise NotImplementedError(
                    f"表 {table} 没有登记冲突目标，无法翻译 INSERT OR REPLACE。"
                    f"请在 _CONFLICT_TARGETS 中补上它的主键/唯一键。"
                )
            cols = [c.strip().strip('"') for c in col_list.split(",") if c.strip()]
            if not cols:
                raise ValueError(f"解析不出列名：{s[:120]}")
            sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
            s = (f"INSERT INTO {table} ({col_list}) {rest} "
                 f"ON CONFLICT ({', '.join(target)}) DO UPDATE SET {sets}")

    # ---- sqlite_master ----
    if "sqlite_master" in s:
        s, n = _SQLITE_MASTER_RE.subn(_SQLITE_MASTER_SQL, s)
        if n == 0:
            raise NotImplementedError(f"未支持的 sqlite_master 查询：{s[:160]}")
        out = TranslatedSQL(s)
        out.kind = "sql"
        out.extra_params = (schema,)
        return out

    # ---- 占位符 ----
    s = s.replace("?", "%s")

    out = TranslatedSQL(s)
    out.kind = "sql"
    return out


# ==========================================================
# 连接池
# ==========================================================

# 免费版 Supabase 的 Session pooler 总连接上限是 15。
# 注意：如果同一个云实例上还跑着别的应用，这 15 个连接是**两个应用共享**的，
# 因此上限做成可配置（EXMSYS_DB_POOL_MAX），撞上限时不用改代码就能调小。
# 池是惰性扩容的（ThreadedConnectionPool(1, N)），只有真的并发上来才会占用到 N。
DEFAULT_POOL_MAX = 15


def _pool_max() -> int:
    raw = (os.environ.get("EXMSYS_DB_POOL_MAX") or "").strip()
    if raw:
        try:
            n = int(raw)
            if 1 <= n <= 200:
                return n
        except ValueError:
            pass
    return DEFAULT_POOL_MAX


# 空闲超过这么久，取出时先探活（云数据库会掐掉长时间空闲的 TCP）
IDLE_PROBE_SECONDS = 60

CONNECT_KW = dict(
    connect_timeout=15,
    application_name="exmsys",
    keepalives=1,
    keepalives_idle=30,
    keepalives_interval=10,
    keepalives_count=5,
)

_POOLS = {}
_POOLS_LOCK = threading.Lock()


class PgPool:
    """带探活的线程安全连接池（按 DSN + schema 各建一个池）"""

    def __init__(self, dsn, schema=DEFAULT_PG_SCHEMA):
        self.dsn = dsn
        self.schema = schema or DEFAULT_PG_SCHEMA
        self._pool = _pgpool.ThreadedConnectionPool(1, _pool_max(), dsn, **CONNECT_KW)
        self._idle_since = {}
        # 已经 SET 过 search_path 的物理连接（id -> conn）
        # 存强引用是刻意的：防止对象被回收后 id() 被复用，导致新连接被误判成"已配置"
        self._configured = {}
        self._lock = threading.Lock()

    # ---- search_path ----

    def _apply_search_path(self, conn):
        """给一条物理连接设好目标 schema。

        只放目标 schema、**刻意不放 public** —— 详见文件头「目标 schema」一节：
        放 public 会让写错的表名静默读到别的应用的表，宁可直接报错。

        schema 名已在 detect_pg_schema()/normalize_pg_schema() 做过标识符白名单校验，
        这里可以直接拼接（PG 不接受 schema 名做绑定参数，SET 的值必须是字面量）。
        """
        cur = conn.cursor()
        try:
            cur.execute(f'SET search_path TO "{self.schema}"')
        finally:
            cur.close()
        conn.commit()

    def _ensure_configured(self, conn):
        """确保这条物理连接已设好 search_path；失败则丢弃并换一条新的重试一次"""
        if id(conn) in self._configured:
            return conn
        for attempt in (1, 2):
            try:
                self._apply_search_path(conn)
                self._configured[id(conn)] = conn
                return conn
            except Exception:
                if attempt == 2:
                    raise
                # 这条连接不可用（可能已被服务端关掉）：丢掉换一条
                try:
                    self._pool.putconn(conn, close=True)
                except Exception:
                    pass
                self._configured.pop(id(conn), None)
                conn = self._pool.getconn()
        return conn

    def acquire(self):
        conn = self._pool.getconn()
        with self._lock:
            t = self._idle_since.pop(id(conn), None)
        if t is not None and (time.monotonic() - t) > IDLE_PROBE_SECONDS:
            try:
                if conn.closed:
                    raise psycopg2.OperationalError("连接已被服务端关闭")
                cur = conn.cursor()
                try:
                    cur.execute("SELECT 1")
                finally:
                    cur.close()
                conn.rollback()
            except Exception:
                # 探活失败：丢掉这条，换一条新的
                try:
                    self._pool.putconn(conn, close=True)
                except Exception:
                    pass
                self._configured.pop(id(conn), None)
                conn = self._pool.getconn()
        # 新建的连接（含探活失败后换的那条）需要补上 search_path
        return self._ensure_configured(conn)

    def release(self, conn):
        try:
            if not conn.closed and \
                    conn.info.transaction_status != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                conn.rollback()
        except Exception:
            pass
        with self._lock:
            self._idle_since[id(conn)] = time.monotonic()
        try:
            self._pool.putconn(conn)
        except Exception:
            pass

    def close_all(self):
        try:
            self._pool.closeall()
        except Exception:
            pass


def get_pool(dsn: str, schema: str = None) -> PgPool:
    """按 (DSN, schema) 取（或建）连接池

    schema 为 None 时按 detect_pg_schema() 解析（环境变量 / secrets / .env），
    这样所有调用方（应用、迁移脚本、preflight）都只认一份配置。
    """
    if schema is None:
        from utils.data_access import detect_pg_schema
        schema = detect_pg_schema()
    key = (dsn, schema)
    with _POOLS_LOCK:
        p = _POOLS.get(key)
        if p is None:
            p = PgPool(dsn, schema)
            _POOLS[key] = p
        return p


def reset_pools():
    """丢弃全部连接池（测试 / 切库用）"""
    with _POOLS_LOCK:
        for p in _POOLS.values():
            p.close_all()
        _POOLS.clear()


# ==========================================================
# 游标 / 连接代理
# ==========================================================

def _normalize_params(params):
    """把 Python `bool` 参数归一成 `0` / `1` 整数，其它类型原样透传。

    SQLite 用 `INTEGER` 列存布尔（True/False 落库就是 1/0），PG 侧的表结构是
    **逐字照搬 SQLite** 的 —— `psych_exm` 里同样一个 `boolean` 列都没有，
    整库靠 `integer` 模拟布尔。

    但 psycopg2 会把 Python `bool` 适配成 PG 的 `boolean` 类型，而
    **PostgreSQL 不做 boolean → integer 的隐式转换**，写进去就报
    `DatatypeMismatch: column "x" is of type integer but expression is of type boolean`
    （2026-10-09 真实事故：`question_stats.unstable` 与 `last_correct`，
    因为 `_recalc_mastery_fields()` 赋 bool、读库时又 `bool(row[...])`）。

    在方言层统一收口，好处是**一处覆盖 13 张表的所有写入路径**（含将来新增的），
    且与 SQLite 的存储语义逐位一致。注意 `bool` 是 `int` 的子类，
    所以判断要精确到 `isinstance(v, bool)`，不能写成 `isinstance(v, int)`。
    """
    if not params:
        return params
    return tuple(int(v) if isinstance(v, bool) else v for v in params)


class PgCursor:
    """把 SQLite 方言 SQL 翻译后交给 psycopg2 执行，并把行包成 PgRow"""

    def __init__(self, raw_cursor, schema=DEFAULT_PG_SCHEMA):
        self._cur = raw_cursor
        self._schema = schema or DEFAULT_PG_SCHEMA
        self._cols = None

    # ---- 执行 ----

    def execute(self, sql, params=()):
        t = translate_sql(sql, self._schema)
        p = _normalize_params(params)
        if t.extra_params:
            self._cur.execute(str(t), tuple(p or ()) + tuple(t.extra_params))
        else:
            self._cur.execute(str(t), p or None)
        self._cols = None
        return self

    def executemany(self, sql, seq_of_params):
        t = translate_sql(sql, self._schema)
        if t.extra_params:
            raise NotImplementedError("带额外参数的语句不支持 executemany")
        self._cur.executemany(str(t), [_normalize_params(p) for p in seq_of_params])
        self._cols = None
        return self

    # ---- 取行 ----

    def _index(self):
        if self._cols is None:
            desc = self._cur.description
            self._cols = ({d[0]: i for i, d in enumerate(desc)} if desc else {})
        return self._cols

    def fetchone(self):
        row = self._cur.fetchone()
        return None if row is None else PgRow(row, self._index())

    def fetchall(self):
        idx = self._index()
        return [PgRow(r, idx) for r in self._cur.fetchall()]

    def fetchmany(self, size=None):
        idx = self._index()
        rows = self._cur.fetchmany(size) if size else self._cur.fetchmany()
        return [PgRow(r, idx) for r in rows]

    # ---- 其它 ----

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    @property
    def closed(self):
        return self._cur.closed

    def close(self):
        try:
            self._cur.close()
        except Exception:
            pass

    def __iter__(self):
        idx = self._index()
        for r in self._cur:
            yield PgRow(r, idx)


class PgConnection:
    """与 sqlite3.Connection 用法对齐的连接代理。

    调用方惯用 `conn = self._get_conn(); try: ... finally: conn.close()`，
    所以 close() 的语义是「归还连接池」，不是真关。
    """

    def __init__(self, pool: PgPool):
        self._pool = pool
        self._conn = pool.acquire()
        self._conn.autocommit = False
        self._released = False
        # 兼容 SQLite 侧的 `conn.row_factory = sqlite3.Row`
        # （行对象已经统一是 PgRow，这里只是个哑属性）
        self.row_factory = PgRow

    @property
    def raw(self):
        return self._conn

    def cursor(self, *args, **kwargs):
        return PgCursor(self._conn.cursor(*args, **kwargs), self._pool.schema)

    def execute(self, sql, params=()):
        cur = self.cursor()
        return cur.execute(sql, params)

    def executemany(self, sql, seq_of_params):
        cur = self.cursor()
        return cur.executemany(sql, seq_of_params)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    @property
    def closed(self):
        return self._released or self._conn.closed

    def close(self):
        """归还连接池（幂等）。归还前把未结束的事务回滚掉。"""
        if self._released:
            return
        self._released = True
        self._pool.release(self._conn)

    # 便于 with 语句
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            try:
                self.rollback()
            except Exception:
                pass
        self.close()
        return False


# ==========================================================
# 数据访问实现
# ==========================================================

# 结构自检用：必须存在的表
REQUIRED_TABLES = [
    "users", "user_devices", "app_config", "user_config",
    "questions", "case_studies", "question_stats", "wrong_questions",
    "answer_records", "exam_records", "mock_exam_records",
    "study_records", "drafts",
]


class PostgresDataAccess(SQLiteDataAccess):
    """PostgreSQL / Supabase 实现。

    继承 SQLiteDataAccess 的**全部业务方法**，只覆盖 4 个与存储引擎耦合的方法：
      __init__ / _get_conn / _get_light_conn / _init_db
    业务 SQL 一行都不用改 —— 由 PgCursor 在 execute 时翻译方言。
    """

    db_kind = "postgres"

    def __init__(self, dsn=None, user_id=None, schema=None):
        from utils.data_access import detect_pg_dsn, detect_pg_schema
        if dsn is None:
            dsn = detect_pg_dsn()
        if not dsn:
            raise RuntimeError(
                "未配置数据库连接串。请设置环境变量 EXMSYS_DB_URL，"
                "或写入 .streamlit/secrets.toml 的 [supabase] url。"
            )
        self.dsn = dsn
        # 目标 schema（同一实例多应用隔离）。None 时按配置文件解析，兜底 'public'。
        self.schema = detect_pg_schema() if schema is None else schema
        # 关键：父类里有 get_retention_threshold(self.db_path, uid) 这样的调用，
        # 把 db_path 指向 DSN，模块级函数会据此走 Postgres 分支。
        self.db_path = dsn
        self.user_id = user_id or ""
        self._init_db()

    # ---- 连接 ----

    def _get_conn(self):
        return PgConnection(get_pool(self.dsn, self.schema))

    def _get_light_conn(self):
        # 有连接池，取连接本身就足够廉价，无需区分轻量连接
        return self._get_conn()

    # ---- 建表：PG 侧不建表 ----

    def _init_db(self):
        """PG 模式下不建表（表由 deploy/supabase/01_schema.sql 创建），只做结构自检。

        为什么不做「自动建表」：Postgres 建表要顺带处理唯一索引、identity 序列、
        RLS 等一堆配置，散在应用启动路径里既不可控也不可审计；
        集中放在 01_schema.sql 里，跑一次、可复核、可幂等重跑。

        自检按 self.schema 查 —— 同一实例上可能还有别的应用，绝不能只看 public。
        """
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            sch = self.schema
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
                (sch,),
            )
            have = {r["table_name"] for r in cur.fetchall()}
            missing = [t for t in REQUIRED_TABLES if t not in have]

            if missing:
                cur.execute(
                    "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
                    (sch,),
                )
                schema_exists = cur.fetchone() is not None
                if schema_exists:
                    raise RuntimeError(
                        f"云端数据库 schema「{sch}」结构不完整，缺少这些表：\n"
                        f"  {missing}\n\n"
                        "修复方法：打开云数据库控制台的 SQL 编辑器，\n"
                        "把项目里的 deploy/supabase/01_schema.sql 【整段一次性】粘贴执行。\n"
                        "（脚本是幂等的，重复执行不会破坏已有数据。）"
                    )
                raise RuntimeError(
                    f"云端数据库里没有 schema「{sch}」。\n"
                    "  1) 确认 .streamlit/secrets.toml（或 EXMSYS_DB_SCHEMA）里的 schema 名对不对；\n"
                    "  2) 若确实还没建，把 deploy/supabase/01_schema.sql 整段一次性执行。\n"
                    "  ⚠️ 该脚本依赖脚本内的 set search_path，必须整段执行，\n"
                    "     不要逐条选中执行，否则表会建到 public 去。"
                )

            # 关键索引检查：没有它公共题库去重会静默失效
            cur.execute(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = %s AND tablename = 'questions' "
                "AND indexname = 'uniq_questions_owner_md5'",
                (sch,),
            )
            if cur.fetchone() is None:
                raise RuntimeError(
                    f"云端库 schema「{sch}」缺少唯一索引 uniq_questions_owner_md5"
                    "（questions.owner_id + md5）。\n"
                    "缺了它公共题库会重复导入，且历史答题统计可能与错题串位。\n"
                    "修复：重新执行 deploy/supabase/01_schema.sql。"
                )
        finally:
            conn.close()

    def _assert_schema_ready(self, cur):
        """父类 _init_db 会调它；PG 侧的结构校验已在 _init_db 里做完，这里放行。"""
        return

    # ---- 便捷：暴露给界面显示（打码，绝不带密码）----

    def safe_dsn(self) -> str:
        from utils.data_access import mask_dsn
        return mask_dsn(self.dsn)


# ==========================================================
# 给模块级函数用的小工具
# ==========================================================

def fetch_one(dsn, sql, params=()):
    """在 DSN 上跑一条查询取一行（供 utils.data_access 的模块级函数复用）"""
    conn = PgConnection(get_pool(dsn))
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        return tuple(row) if row is not None else None
    finally:
        conn.close()


def ping(dsn) -> tuple:
    """连通性自检：返回 (是否成功, 说明文字)"""
    try:
        conn = PgConnection(get_pool(dsn))
        try:
            cur = conn.cursor()
            cur.execute("SELECT current_database() AS db, current_user AS usr, "
                        "version() AS ver")
            row = cur.fetchone()
            return True, f"数据库={row['db']} 用户={row['usr']} | {row['ver'][:60]}"
        finally:
            conn.close()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

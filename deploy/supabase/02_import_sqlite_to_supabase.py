#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
exmsys · 本地 SQLite  ->  云端 PostgreSQL  数据导入 / 逐行校验脚本
         （Supabase / Neon / Aiven 通用）

配套文件
    deploy/supabase/01_schema.sql   先在云端建表（必须先执行；Neon/Aiven 用【直连】端点）
    deploy/supabase/03_verify.sql   纯 SQL 的巡检查询（可选）

--------------------------------------------------------------------------
用法
--------------------------------------------------------------------------
# 1) 只体检，绝不写库
python 02_import_sqlite_to_supabase.py --dsn "$SUPABASE_DB_URL" --dry-run

# 2) 正式导入：清空目标表 -> COPY 批量灌入 -> 对齐自增序列 -> 逐行校验
python 02_import_sqlite_to_supabase.py --dsn "$SUPABASE_DB_URL" --mode replace

# 3) 只做校验（导入后复核 / 以后线上巡检）
python 02_import_sqlite_to_supabase.py --dsn "$SUPABASE_DB_URL" --verify-only

目标 schema：
    默认从配置读取（.streamlit/secrets.toml 的 [supabase] schema，或环境变量
    EXMSYS_DB_SCHEMA），都没有则用 public。本项目通常配成独立 schema（如 psych_exm），
    以便和同一实例上的其他应用隔离 —— 此时 01_schema.sql 也要整段执行来建这个 schema。
    临时覆盖：--schema psych_exm

连接串也可以放环境变量，省得每次手打：
    set SUPABASE_DB_URL=postgresql://postgres.<ref>:<pwd>@aws-0-<region>.pooler.supabase.com:5432/postgres
    （PowerShell: $env:SUPABASE_DB_URL = "postgresql://..."）

--------------------------------------------------------------------------
安全承诺
--------------------------------------------------------------------------
· 对本地 SQLite 库【只读】：全程只执行 SELECT，绝不写 data/exmsys.db。
· 写 PostgreSQL 前会先打印「将要清空的表 + 行数」，除非显式加 --yes，否则交互确认。
· --mode append 时不做任何删除操作。
· 导入整体包在一个事务里，任何一步失败全部回滚，不会留半截数据。

--------------------------------------------------------------------------
注意：连接方式选型
--------------------------------------------------------------------------
· Supabase 的【直连】(db.<ref>.supabase.co:5432) 只解析 IPv6，家用网络多半连不上；
  统一推荐【Session pooler】(aws-0-<region>.pooler.supabase.com:5432)，
  注意它的用户名是 postgres.<project-ref>（带项目后缀），不是裸 postgres。
· 不要用 transaction pooler（6543 端口）：那是给无状态 serverless 用的，
  不支持会话级特性，长连接应用容易出怪问题。
"""

import argparse
import csv
import io
import os
import sqlite3
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# 表清单： (表名, 需要搬运的列, 主键列(仅用于排序/比对), 自增列)
# 顺序同时是导入顺序（本库无外键，顺序其实无关，写出来只为可读）
# ---------------------------------------------------------------------------
TABLES = [
    ("users",
     ["user_id", "username", "password_hash", "role", "display_name",
      "created_at", "last_login"],
     ["user_id"], None),

    ("user_devices",
     ["device_fp", "user_id", "first_seen", "last_seen"],
     ["device_fp"], None),

    ("app_config",
     ["key", "value"],
     ["key"], None),

    ("user_config",
     ["user_id", "key", "value"],
     ["user_id", "key"], None),

    ("questions",
     ["id", "owner_id", "source_file", "index_num", "type", "question", "options",
      "answer", "explanation", "md5", "category", "exam_type", "case_study_id",
      "is_case_background"],
     ["id"], None),

    ("case_studies",
     ["id", "owner_id", "title", "background_id", "question_count", "exam_type"],
     ["id"], None),

    ("question_stats",
     ["question_id", "user_id", "correct_count", "wrong_count", "last_answer_time",
      "last_correct", "answer_history", "mastery_level", "confidence", "unstable",
      "self_uncertainty", "first_answer_time", "exam_type"],
     ["question_id", "user_id"], None),

    ("wrong_questions",
     ["question_id", "user_id", "exam_type"],
     ["question_id", "user_id"], None),

    ("answer_records",
     ["id", "user_id", "question_id", "user_answer", "is_correct", "mode",
      "session_id", "category", "timestamp", "exam_type"],
     ["id"], "id"),

    ("exam_records",
     ["id", "user_id", "data", "exam_type"],
     ["id"], "id"),

    ("mock_exam_records",
     ["id", "user_id", "data", "exam_type"],
     ["id"], "id"),

    ("study_records",
     ["session_id", "user_id", "mode", "total", "answered", "correct", "wrong",
      "start_time", "end_time", "details", "exam_type"],
     ["session_id"], None),

    ("drafts",
     ["id", "user_id", "prefix", "draft_id", "data", "saved_at", "exam_type"],
     ["id"], None),
]

TABLE_NAMES = [t[0] for t in TABLES]

# NULL 在 CSV 里的占位符。必须用显式标记，不能用「空字段 = NULL」——
# 本库同时存在 NULL 与空字符串，且二者语义不同。实测：
#   questions.case_study_id    5078 行是空串 ''
#   answer_records.user_answer  158 行是空串 ''
#   users.username               4 行是 NULL
# 若把空串当 NULL 灌进去，这些行的语义就被改坏了。
NULL_TOKEN = "\\N"


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def log(msg=""):
    print(msg, flush=True)


def q_ident(name):
    """SQLite 标识符加引号"""
    return '"' + name.replace('"', '""') + '"'


def _norm(v):
    """把两侧驱动返回的值归一化，避免「类型不同但语义相同」被判成差异"""
    if v is None:
        return None
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).decode("utf-8", "replace")
    if isinstance(v, bool):
        return int(v)
    return v


def ensure_sslmode(dsn, sslmode):
    """没写 sslmode 就补上（云端 Postgres 基本都强制 SSL）"""
    if "sslmode=" in dsn:
        return dsn
    sep = "&" if "?" in dsn else "?"
    return f"{dsn}{sep}sslmode={sslmode}"


def mask_dsn(dsn):
    """打印连接串时把密码打码"""
    try:
        head, tail = dsn.split("://", 1)
        cred, rest = tail.split("@", 1)
        user = cred.split(":", 1)[0]
        return f"{head}://{user}:***@{rest.split('?')[0]}"
    except Exception:
        return "***"


def warn_if_transaction_pooler(dsn):
    """检测到 transaction 模式的连接池端点时给出提醒。

    为什么重要：transaction 模式下连接在每次事务后就被回收，会话级语义全部失效
    （SET / LISTEN / 临时表 / 会话级锁 / PREPARE 都不行，PgBouncer 的
    max_prepared_statements 直接是 0）。建表（DDL）与批量 COPY 导入都属于
    「长事务 / 需要稳定会话」的操作，走这种端点容易中途失败，而且报错不会提到
    连接池，极难排查。所以这里主动提醒改用直连。

    - Neon：主机名带 -pooler 即 transaction 模式
    - Supabase：6543 端口是 Transaction pooler；5432 是 Session pooler（会话模式，可用）
    """
    try:
        rest = dsn.split("://", 1)[-1]
        host_port = rest.split("@", 1)[-1].split("/", 1)[0]
        if "-pooler" in host_port and ".neon.tech" in host_port:
            log("")
            log("[提示] 检测到 Neon 连接池端点（-pooler，PgBouncer transaction 模式）。")
            log("       建表与批量导入请改用【不带 -pooler 的直连串】：")
            log("       postgresql://<user>:<pwd>@ep-xxx.<region>.aws.neon.tech/neondb?sslmode=require")
            log("       应用运行时再用连接池串，两者是同一个库，只是接入方式不同。")
            log("")
        elif ":6543" in host_port:
            log("")
            log("[提示] 检测到 Supabase Transaction pooler（6543 端口，无状态模式）。")
            log("       建表与批量导入请改用 Session pooler（5432 端口）。")
            log("")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 读取侧（SQLite）
# ---------------------------------------------------------------------------

def sqlite_count(conn, table):
    return conn.execute(f"select count(*) from {q_ident(table)}").fetchone()[0]


def sqlite_rows(conn, table, cols, pk):
    sel = ", ".join(q_ident(c) for c in cols)
    order = ", ".join(q_ident(c) for c in pk)
    return conn.execute(
        f"select {sel} from {q_ident(table)} order by {order}"
    ).fetchall()


# ---------------------------------------------------------------------------
# 写入侧（PostgreSQL）
# ---------------------------------------------------------------------------

def pg_fetch_map(pg_cur, table, cols, pk, schema):
    """从 PostgreSQL 读出整表，按主键做成 {pk_tuple: row_tuple}"""
    sel = ", ".join(f'"{c}"' for c in cols)
    order = ", ".join(f'"{c}"' for c in pk)
    pg_cur.execute(f'select {sel} from "{schema}"."{table}" order by {order}')
    pk_idx = [cols.index(c) for c in pk]
    out = {}
    dup = []
    for row in pg_cur.fetchall():
        row = tuple(_norm(v) for v in row)
        key = tuple(row[i] for i in pk_idx)
        if key in out:
            dup.append(key)
        out[key] = row
    return out, dup


def copy_table(pg_cur, sqlite_conn, table, cols, pk, schema):
    """用 COPY FROM STDIN 批量灌入（比逐条 INSERT 快一到两个数量级）"""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    n = 0
    for row in sqlite_rows(sqlite_conn, table, cols, pk):
        out = []
        for v in row:
            if v is None:
                out.append(NULL_TOKEN)
            else:
                if v == NULL_TOKEN:
                    raise RuntimeError(
                        f"{table} 存在字面量 '{NULL_TOKEN}' 的值，与 NULL 占位符冲突，"
                        "请改用其它 NULL_TOKEN 后重跑"
                    )
                out.append(v)
        writer.writerow(out)
        n += 1
    buf.seek(0)

    collist = ", ".join(f'"{c}"' for c in cols)
    pg_cur.copy_expert(
        f'copy "{schema}"."{table}" ({collist}) from stdin '
        f"with (format csv, null '{NULL_TOKEN}')",
        buf,
    )
    return n


def reset_identity(pg_cur, table, col, schema):
    """把自增序列推到 max(id)，否则应用下一条 INSERT 会撞主键"""
    pg_cur.execute(
        f"""
        select setval(
            pg_get_serial_sequence('"{schema}"."{table}"', '{col}'),
            coalesce((select max("{col}") from "{schema}"."{table}"), 1),
            (select max("{col}") from "{schema}"."{table}") is not null
        )
        """
    )


# ---------------------------------------------------------------------------
# 逐行校验
# ---------------------------------------------------------------------------

def verify_all(sqlite_conn, pg_cur, schema, show_diff=5):
    """逐行比对：条数 -> 主键集合 -> 逐列取值。只比条数会漏掉字段错位。"""
    log("")
    log("=" * 78)
    log(f"逐行校验  (SQLite  vs  {schema} schema@云端 PostgreSQL)")
    log("=" * 78)
    log(f"{'表名':<20}{'SQLite':>9}{'云端':>8}   结果")
    log("-" * 78)

    ok = True
    for table, cols, pk, _ident in TABLES:
        s_rows = sqlite_rows(sqlite_conn, table, cols, pk)
        s_cnt = len(s_rows)
        pk_idx = [cols.index(c) for c in pk]

        s_map = {}
        s_dup = []
        for r in s_rows:
            r = tuple(_norm(v) for v in r)
            k = tuple(r[i] for i in pk_idx)
            if k in s_map:
                s_dup.append(k)
            s_map[k] = r

        p_map, p_dup = pg_fetch_map(pg_cur, table, cols, pk, schema)
        p_cnt = len(p_map)

        problems = []
        if s_cnt != p_cnt:
            problems.append(f"条数不符 {s_cnt} vs {p_cnt}")
        missing = [k for k in s_map if k not in p_map]
        extra = [k for k in p_map if k not in s_map]
        if missing:
            problems.append(f"云端缺 {len(missing)} 行，例：{missing[:3]}")
        if extra:
            problems.append(f"云端多 {len(extra)} 行，例：{extra[:3]}")
        if s_dup:
            problems.append(f"源库主键重复 {len(s_dup)} 个（源库自身问题）")
        if p_dup:
            problems.append(f"目标库主键重复 {len(p_dup)} 个")

        mismatched = []
        for k in s_map:
            p = p_map.get(k)
            if p is None:
                continue
            if s_map[k] != p:
                bad = [cols[i] for i in range(len(cols)) if s_map[k][i] != p[i]]
                mismatched.append((k, bad, s_map[k], p))
        if mismatched:
            problems.append(f"字段值不一致 {len(mismatched)} 行")

        if problems:
            ok = False
            log(f"{table:<20}{s_cnt:>9}{p_cnt:>10}   FAIL")
            for p in problems:
                log(f"{'':<20}{'':>9}{'':>10}   - {p}")
            for k, bad, s_row, p_row in mismatched[:show_diff]:
                log(f"{'':<20}{'':>9}{'':>10}   - pk={k} 差异列={bad}")
                for i in range(len(cols)):
                    if s_row[i] != p_row[i]:
                        log(f"{'':<30}       {cols[i]}: "
                            f"sqlite={s_row[i]!r}  pg={p_row[i]!r}")
        else:
            log(f"{table:<20}{s_cnt:>9}{p_cnt:>10}   OK")

    log("-" * 78)
    log("校验结果：" + ("全部一致 ✔" if ok else "存在差异 ✘"))
    return ok


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="exmsys: 本地 SQLite -> 云端 PostgreSQL 导入与校验",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--sqlite", default=None,
                    help="本地 SQLite 库路径，默认 <项目>/data/exmsys.db")
    ap.add_argument("--dsn", default=None,
                    help="数据库连接串。不传时自动从 "
                         "①环境变量 EXMSYS_DB_URL / SUPABASE_DB_URL  "
                         "②.streamlit/secrets.toml 的 [supabase] url  "
                         "③项目根目录 .env 读取")
    ap.add_argument("--mode", choices=["replace", "append"], default="replace",
                    help="replace=先清空目标表再灌（默认）；append=只追加")
    ap.add_argument("--schema", default=None,
                    help="目标 schema（默认从 .streamlit/secrets.toml 的 [supabase] schema "
                         "或环境变量 EXMSYS_DB_SCHEMA 读取；都没有则 public）")
    ap.add_argument("--sslmode", default="require",
                    help="连接串未指定 sslmode 时补此值，默认 require")
    ap.add_argument("--dry-run", action="store_true",
                    help="只读体检：检查连通性、目标表是否存在、源库各表行数，不写任何数据")
    ap.add_argument("--verify-only", action="store_true",
                    help="只做逐行校验，不导入")
    ap.add_argument("--yes", action="store_true",
                    help="跳过「确认清空目标表」的交互确认")
    ap.add_argument("--no-verify", action="store_true",
                    help="导入后不跑逐行校验（不推荐）")
    args = ap.parse_args()

    # ---- 定位源库 ----
    if args.sqlite:
        sqlite_path = Path(args.sqlite).expanduser().resolve()
    else:
        sqlite_path = Path(__file__).resolve().parents[2] / "data" / "exmsys.db"
    if not sqlite_path.exists():
        log(f"[错误] 找不到本地 SQLite 库：{sqlite_path}")
        return 2

    if not args.dsn:
        # 复用应用同一套配置解析：环境变量 → secrets.toml → .env
        # 好处是「一份配置全场景通用」，导入脚本不用单独维护连接串。
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
            from utils.data_access import detect_pg_dsn
            args.dsn = detect_pg_dsn() or None
        except Exception:
            args.dsn = os.environ.get("SUPABASE_DB_URL") or None

    if not args.dsn:
        log("[错误] 未找到数据库连接串。任选一种方式配置：")
        log('       1) .streamlit/secrets.toml 里写  [supabase]  url = "postgresql://..."')
        log("       2) 设置环境变量 EXMSYS_DB_URL")
        log("       3) 项目根目录建 .env，写 EXMSYS_DB_URL=postgresql://...")
        log("       4) 命令行显式传 --dsn \"postgresql://...\"")
        log("")
        log("       三家连接串格式（都从控制台复制，别手打）：")
        log("       Supabase  postgresql://postgres.<ref>:<pwd>@aws-0-<region>.pooler.supabase.com:5432/postgres")
        log("       Neon      postgresql://<user>:<pwd>@ep-xxx.<region>.aws.neon.tech/neondb?sslmode=require")
        log("                 ^ 导入请用【不带 -pooler 的直连串】")
        log("       Aiven     postgresql://avnadmin:<pwd>@pg-xxx.aivencloud.com:<port>/defaultdb?sslmode=require")
        return 2

    # ---- 目标 schema ----
    if args.schema:
        schema = args.schema.strip()
        # 命令行传入的也要过一遍白名单校验（防注入 + 防手误）
        import re as _re
        if not _re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$", schema):
            log(f"[错误] --schema 不是合法的标识符：{schema!r}")
            log("      只允许字母/数字/下划线，且不以数字开头")
            return 2
    else:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
            from utils.data_access import detect_pg_schema
            schema = detect_pg_schema()
        except Exception as e:
            log(f"[错误] 读取 schema 配置失败：{type(e).__name__}: {e}")
            return 2

    dsn = ensure_sslmode(args.dsn, args.sslmode)
    warn_if_transaction_pooler(dsn)

    try:
        import psycopg2
    except ImportError:
        log("[错误] 缺少 psycopg2。请执行：")
        log('       python -m pip install "psycopg2-binary>=2.9"')
        return 2

    log("=" * 78)
    log("exmsys  SQLite -> 云端 PostgreSQL 数据搬运")
    log("=" * 78)
    log(f"源库(SQLite) : {sqlite_path}")
    log(f"源库大小     : {sqlite_path.stat().st_size / 1048576:.2f} MB")
    log(f"目标(PG)     : {mask_dsn(dsn)}")
    log(f"目标 schema  : {schema}"
        + ("  ⚠️ 这是 public —— 与同实例其他应用共用命名空间，确认是你想要的"
           if schema == "public" else "  （独立命名空间，与同实例其他应用隔离）"))
    log(f"模式         : {args.mode}"
        + ("   [dry-run 只体检]" if args.dry_run else "")
        + ("   [仅校验]" if args.verify_only else ""))

    t0 = time.time()
    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = None

    log("")
    log("源库各表行数：")
    for t in TABLE_NAMES:
        log(f"    {t:<20}{sqlite_count(sqlite_conn, t):>9}")

    try:
        pg_conn = psycopg2.connect(dsn, connect_timeout=20,
                                   application_name="exmsys-migrate")
    except Exception as e:
        log("")
        log(f"[错误] 连接数据库失败：{e}")
        log("       排查顺序：")
        log("       1. 主机名 / 端口抄对没有（从控制台复制，别手打）")
        log("            Supabase  aws-0-<region>.pooler.supabase.com:5432（不是 db.<ref>.supabase.co）")
        log("            Neon      ep-xxx.<region>.aws.neon.tech（导入用不带 -pooler 的直连）")
        log("            Aiven     pg-xxx.aivencloud.com:<控制台给的端口>（不是 5432）")
        log("       2. 用户名 / 库名抄对没有")
        log("            Supabase  postgres.<project-ref>（带项目后缀）")
        log("            Neon      控制台随机用户名 + 库名 neondb")
        log("            Aiven     avnadmin + 库名 defaultdb")
        log("       3. 密码是否含有 @ : / ? # 等字符 —— 需要 URL 编码")
        log("       4. 连接串是否带 ?sslmode=require（Neon / Aiven 强制 TLS）")
        log("       5. 实例是否被暂停 / 关机（免费版闲置会被暂停或关机，控制台恢复或开机）")
        return 3

    pg_conn.autocommit = False
    pg_cur = pg_conn.cursor()

    try:
        # ---- 目标侧体检 ----
        # 先确认 schema 存在，否则信息不足时容易误判成"表没建"
        pg_cur.execute(
            "select 1 from information_schema.schemata where schema_name = %s",
            (schema,),
        )
        if pg_cur.fetchone() is None:
            log("")
            log(f"[错误] 目标库里没有 schema「{schema}」")
            log("       请把 deploy/supabase/01_schema.sql 【整段一次性】在 SQL Editor 执行")
            log("       （脚本自带 create schema + set search_path，必须整段执行，")
            log("         逐条选中执行会把表建到 public 去）")
            pg_conn.rollback()
            return 4

        pg_cur.execute(
            "select table_name from information_schema.tables "
            "where table_schema = %s and table_type = 'BASE TABLE'",
            (schema,),
        )
        existing = {r[0] for r in pg_cur.fetchall()}
        missing_tables = [t for t in TABLE_NAMES if t not in existing]
        if missing_tables:
            log("")
            log(f"[错误] schema「{schema}」缺少这些表：{missing_tables}")
            log("       请先在云端控制台的 SQL Editor 执行 deploy/supabase/01_schema.sql")
            pg_conn.rollback()
            return 4

        log("")
        log(f"目标库各表行数（导入前，schema={schema}）：")
        for t in TABLE_NAMES:
            pg_cur.execute(f'select count(*) from "{schema}"."{t}"')
            log(f"    {t:<20}{pg_cur.fetchone()[0]:>9}")

        if args.dry_run:
            pg_conn.rollback()
            log("")
            log(f"[dry-run] 连通性 OK，schema「{schema}」表结构 OK，未写入任何数据。")
            return 0

        if args.verify_only:
            pg_conn.rollback()
            ok = verify_all(sqlite_conn, pg_cur, schema)
            return 0 if ok else 1

        # ---- 清空 ----
        if args.mode == "replace":
            if not args.yes:
                log("")
                log(f"即将【清空】目标库 schema「{schema}」下的以下表，再灌入本地数据：")
                for t in TABLE_NAMES:
                    log(f"    - {schema}.{t}")
                log("")
                log("       注意：只影响这个 schema，同实例上其他应用的 public.xxx 不受影响。")
                log("")
                ans = input("确认继续？输入 yes 回车：").strip().lower()
                if ans != "yes":
                    log("已取消。")
                    pg_conn.rollback()
                    return 0
            collist = ", ".join(f'"{schema}"."{t}"' for t in TABLE_NAMES)
            pg_cur.execute(f"truncate table {collist} restart identity")
            log("")
            log("已清空目标表（含自增序列重置）。")

        # ---- 灌数 ----
        log("")
        log("开始导入：")
        for table, cols, pk, ident in TABLES:
            t1 = time.time()
            n = copy_table(pg_cur, sqlite_conn, table, cols, pk, schema)
            if ident:
                reset_identity(pg_cur, table, ident, schema)
            pg_cur.execute(f'select count(*) from "{schema}"."{table}"')
            after = pg_cur.fetchone()[0]
            log(f"    {table:<20} 写入 {n:>7} 行 -> 目标现有 {after:>7} 行"
                f"  ({time.time() - t1:.2f}s)")

        pg_conn.commit()
        log("")
        log(f"导入事务已提交，用时 {time.time() - t0:.1f}s")

    except Exception as e:
        pg_conn.rollback()
        log("")
        log(f"[失败] 已回滚，目标库未被改动：{type(e).__name__}: {e}")
        return 5
    finally:
        pg_cur.close()
        pg_conn.close()

    # ---- 校验（新开连接，确保读到的是真正落盘的数据）----
    if args.no_verify:
        log("已跳过逐行校验（--no-verify）")
        return 0

    pg_conn = psycopg2.connect(dsn, connect_timeout=20,
                               application_name="exmsys-migrate-verify")
    pg_cur = pg_conn.cursor()
    try:
        ok = verify_all(sqlite_conn, pg_cur, schema)
    finally:
        pg_cur.close()
        pg_conn.close()
        sqlite_conn.close()

    log(f"总用时 {time.time() - t0:.1f}s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

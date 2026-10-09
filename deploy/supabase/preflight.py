#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
exmsys · 云端 PostgreSQL 连接自检（preflight）

适用于 Supabase / Neon / Aiven 等任何托管 PostgreSQL —— 自检逻辑与平台无关，
只在提示文案上针对主机名做区分（目录名 deploy/supabase 是历史遗留，别被名字误导）。

启动云端模式之前先跑这一遍，把「配错了、表没建、序列没对齐」这类问题
在启动前就挡住，而不是等用户点开页面报一堆奇怪的错。

用法：
    python deploy/supabase/preflight.py            # 完整自检
    python deploy/supabase/preflight.py --quiet    # 只输出结论（给批处理调用）

自检的 schema 由配置决定（.streamlit/secrets.toml 的 [supabase] schema、
或环境变量 EXMSYS_DB_SCHEMA），默认 public。本项目通常为独立 schema
（如 psych_exm），用于和同一实例上的其他应用隔离。

返回值（退出码）：
    0  全部通过
    2  找不到连接串 / 连接串非法
    3  psycopg2 缺失
    4  连不上数据库
    5  schema 不存在或表结构不完整
    6  唯一索引缺失
    7  自增序列没对齐（会导致应用一写入就主键冲突）
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

OK = "[ OK ]"
BAD = "[FAIL]"
WARN = "[WARN]"


class Report:
    def __init__(self, quiet=False):
        self.quiet = quiet
        self.failed = False

    def ok(self, msg):
        print(f"{OK} {msg}")

    def info(self, msg):
        if not self.quiet:
            print(f"      {msg}")

    def bad(self, msg):
        self.failed = True
        print(f"{BAD} {msg}")

    def warn(self, msg):
        print(f"{WARN} {msg}")


def main():
    ap = argparse.ArgumentParser(description="exmsys 云端 PostgreSQL 连接自检")
    ap.add_argument("--quiet", action="store_true", help="只输出结论")
    ap.add_argument("--dsn", default=None, help="直接指定连接串（覆盖配置文件）")
    args = ap.parse_args()
    quiet = args.quiet
    r = Report(quiet)

    if not quiet:
        print("=" * 70)
        print("exmsys  云端 PostgreSQL 连接自检")
        print("=" * 70)

    # ---- 1. 连接串 ----
    from utils.data_access import _looks_like_dsn, detect_pg_dsn, mask_dsn
    if args.dsn:
        if not _looks_like_dsn(args.dsn):
            r.bad(f"--dsn 不是合法的 Postgres 连接串：{args.dsn[:60]}")
            print('  连接串必须以 postgresql:// 或 postgres:// 开头')
            return 2
        dsn = args.dsn.strip()
    else:
        dsn = detect_pg_dsn()

    if not dsn:
        r.bad("找不到数据库连接串")
        print()
        print("  请任选一种方式配置（推荐第一种）：")
        print("  1) 在 .streamlit/secrets.toml 里写：")
        print("       [supabase]")
        print('       url = "postgresql://..."')
        print("  2) 设置环境变量 EXMSYS_DB_URL")
        print("  3) 在项目根目录建 .env，写 EXMSYS_DB_URL=postgresql://...")
        print()
        print("  连接串从云端控制台复制，别手打。三家格式：")
        print("    Supabase  postgresql://postgres.<ref>:<密码>@aws-0-<区域>.pooler.supabase.com:5432/postgres")
        print("    Neon      postgresql://<用户名>:<密码>@ep-xxx-pooler.<区域>.aws.neon.tech/neondb?sslmode=require")
        print("    Aiven     postgresql://avnadmin:<密码>@pg-xxx.aivencloud.com:<端口>/defaultdb?sslmode=require")
        return 2

    from utils.data_access import mask_dsn
    r.ok(f"连接串已找到：{mask_dsn(dsn)}")
    host = dsn.split("://", 1)[-1].split("@")[-1]
    if "pooler.supabase.com" in dsn:
        r.info("识别为 Supabase Session pooler（IPv4，推荐）")
    elif ".supabase.co" in dsn:
        r.warn("识别为 Supabase 直连地址 —— 它只解析 IPv6，家用宽带通常连不上；"
               "建议改用 Session pooler（aws-0-<区域>.pooler.supabase.com:5432）")
    elif ".neon.tech" in dsn:
        if "-pooler" in dsn:
            r.info("识别为 Neon 连接池端点（-pooler）—— 应用运行时用它；"
                   "建表 / 导入数据请换【不带 -pooler 的直连串】")
        else:
            r.info("识别为 Neon 直连端点 —— 建表 / 导入数据用它；"
                   "应用运行时建议换【带 -pooler 的连接池串】")
    elif "aivencloud.com" in dsn:
        r.info("识别为 Aiven 实例（注意端口不是 5432，且必须带 ?sslmode=require）")
    else:
        r.info("未识别的托管商 —— 按普通 PostgreSQL 处理")
    if (".neon.tech" in host or "aivencloud.com" in host) and "sslmode=" not in dsn:
        r.warn("连接串里没有 sslmode —— 该平台强制 TLS，缺失会报 "
               "\"connection requires SSL\"；请在末尾补 ?sslmode=require")
    if dsn.split("://", 1)[-1].split("@")[0].count(":") > 1:
        r.warn("密码里可能有未做 URL 编码的 @ （@ → %40），会导致解析出错")

    # ---- 1.5 schema ----
    from utils.data_access import detect_pg_schema
    schema = detect_pg_schema()   # 非法标识符会在此直接抛错，防注入
    r.ok(f"目标 schema：{schema}"
         + ("（public = 与同实例其他应用共用，确认这是你要的）" if schema == "public"
            else "（独立命名空间，与同实例其他应用隔离）"))

    # ---- 2. 驱动 ----
    try:
        import psycopg2  # noqa: F401
        r.ok(f"psycopg2 已安装（{psycopg2.__version__.split()[0]}）")
    except ImportError:
        r.bad("未安装 psycopg2 —— 请执行：python -m pip install \"psycopg2-binary>=2.9\"")
        return 3

    # ---- 3. 连接 ----
    from utils.data_access_pg import get_pool, PgConnection, REQUIRED_TABLES
    try:
        conn = PgConnection(get_pool(dsn, schema))
    except Exception as e:
        r.bad(f"连接数据库失败：{type(e).__name__}: {e}")
        print()
        print("  排查顺序：")
        print("  1. 主机名 / 端口抄对没有（从控制台复制，别手打）")
        print("       Supabase  aws-0-<区域>.pooler.supabase.com:5432  ← 不是 db.<ref>.supabase.co")
        print("       Neon      ep-xxx[-pooler].<区域>.aws.neon.tech")
        print("       Aiven     pg-xxx.aivencloud.com:<控制台给的端口>  ← 不是 5432")
        print("  2. 用户名 / 库名抄对没有")
        print("       Supabase  postgres.<项目ref>（**带项目后缀**，不是裸 postgres）")
        print("       Neon      控制台随机生成的用户名 + 库名 neondb")
        print("       Aiven     avnadmin + 库名 defaultdb")
        print("  3. 密码是否正确；含 @ : / ? # 时要 URL 编码")
        print("  4. 连接串是否带 ?sslmode=require（Neon / Aiven 强制 TLS）")
        print("  5. 实例是否被暂停 / 关机（免费版闲置会被暂停或关机，去控制台恢复或开机）")
        print("  6. 网络是否通（Supabase 的直连地址只解析 IPv6，家用宽带连不上）")
        return 4

    try:
        cur = conn.cursor()
        cur.execute("SELECT current_database() AS db, current_user AS usr, version() AS ver, "
                    "current_schema() AS sch")
        row = cur.fetchone()
        r.ok(f"连接成功：库={row['db']} 用户={row['usr']} 当前 schema={row['sch']}")
        r.info(row["ver"][:70])
        if row["sch"] != schema:
            r.warn(f"连接后的 current_schema()={row['sch']}，与配置的 {schema} 不一致 ——"
                   " 应用已自动 SET search_path，若持续如此请检查连接池是否为 transaction 模式")

        # ---- 4. schema 是否存在 ----
        cur.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
            (schema,),
        )
        if cur.fetchone() is None:
            r.bad(f"数据库里没有 schema「{schema}」")
            print(f"  修复：把 deploy/supabase/01_schema.sql 【整段一次性】在 SQL Editor 执行")
            print(f"        （该脚本自带 create schema {schema} + set search_path，")
            print("          必须整段执行，不要逐条选中执行）")
            return 5

        # ---- 5. 表结构 ----
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
            (schema,),
        )
        have = {x["table_name"] for x in cur.fetchall()}
        missing = [t for t in REQUIRED_TABLES if t not in have]
        if missing:
            r.bad(f"schema「{schema}」缺少 {len(missing)} 张表：{missing}")
            print("  修复：到云端控制台的 SQL Editor，把 deploy/supabase/01_schema.sql")
            print("        【整段一次性】执行（Neon / Aiven 请用【直连】端点，别用连接池端点）")
            return 5
        r.ok(f"表结构完整（{len(REQUIRED_TABLES)} 张表齐全，位于 schema「{schema}」）")

        # ---- 6. 唯一索引 ----
        cur.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = %s "
            "AND tablename = 'questions' AND indexname = 'uniq_questions_owner_md5'",
            (schema,),
        )
        if cur.fetchone() is None:
            r.bad("缺少唯一索引 uniq_questions_owner_md5（公共题库去重靠它）")
            print("  修复：重新执行 deploy/supabase/01_schema.sql")
            return 6
        r.ok("唯一索引 uniq_questions_owner_md5 存在")

        # ---- 7. 自增序列对齐（用 Navicat/手工导入最容易漏的一步）----
        misaligned = []
        for tbl in ("answer_records", "exam_records", "mock_exam_records"):
            cur.execute(
                f"SELECT coalesce(max(id), 0) AS m, "
                f"(SELECT last_value FROM pg_sequences WHERE schemaname = %s "
                f" AND sequencename = '{tbl}_id_seq') AS seq FROM {schema}.{tbl}",
                (schema,),
            )
            row = cur.fetchone()
            if row["m"] and (row["seq"] is None or row["seq"] < row["m"]):
                misaligned.append((tbl, row["m"], row["seq"]))
        if misaligned:
            r.bad("自增序列没对齐，应用一写入就会主键冲突：")
            for tbl, m, seq in misaligned:
                print(f"        {tbl}: max(id)={m} 但序列 last_value={seq}")
            print("  修复（在 SQL Editor 执行，注意带 schema 前缀）：")
            for tbl, _m, _s in misaligned:
                print(f"        SELECT setval(pg_get_serial_sequence('{schema}.{tbl}','id'),"
                      f" (SELECT max(id) FROM {schema}.{tbl}));")
            return 7
        r.ok("自增序列已对齐")

        # ---- 8. 数据概览 ----
        cur.execute(f"SELECT count(*) AS n FROM {schema}.questions")
        qn = cur.fetchone()["n"]
        cur.execute(f"SELECT count(*) AS n FROM {schema}.answer_records")
        an = cur.fetchone()["n"]
        cur.execute(f"SELECT count(*) AS n FROM {schema}.users")
        un = cur.fetchone()["n"]
        if qn == 0:
            r.warn("questions 表是空的 —— 还没导入数据？"
                   " 见 README 第 4 步（02_import_sqlite_to_supabase.py）")
        else:
            r.ok(f"数据概览：题目 {qn} 条 / 答题记录 {an} 条 / 用户 {un} 个")

        # ---- 9. 安全 ----
        cur.execute(
            "SELECT c.relname AS t, c.relrowsecurity AS rls FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relkind='r' "
            "AND c.relname = ANY(%s)",
            (schema, REQUIRED_TABLES),
        )
        no_rls = [x["t"] for x in cur.fetchall() if not x["rls"]]
        if no_rls:
            r.warn(f"这些表没开 RLS：{no_rls}")
            print("  说明：Supabase 上 RLS 是必需的（否则 anon key 能读数据）；"
                  "其他平台无 PostgREST 暴露，属可选加固。")
            print("  修复：重新执行 deploy/supabase/01_schema.sql 的第 6 节")
        else:
            r.ok(f"安全：{len(REQUIRED_TABLES)} 张表均已开启 RLS")
    finally:
        conn.close()

    print()
    if r.failed:
        print("自检结论：存在必须修复的问题 ✘")
        return 1
    print("自检结论：全部通过，可以启动云端模式 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())

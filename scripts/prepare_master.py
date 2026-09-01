# -*- coding: utf-8 -*-
"""
初始化题库模板生成脚本（多用户模式）

作用：
  1. 备份当前 data/exmsys.db（含历史答题记录，将迁移给首个用户）
  2. 生成 data/master/exmsys.db —— 干净模板：保留全部题目/案例/配置，
     清空所有个人记录表，删除历史遗留的备份表

安全说明：
  - 本脚本只在【副本】上执行 DELETE/DROP，绝不触碰 data/exmsys.db 本身
  - 运行前自动备份
用法：
  C:/Users/wanli/AppData/Local/Python/pythoncore-3.14-64/python.exe scripts/prepare_master.py
"""
import shutil
import sqlite3
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SRC_DB = DATA_DIR / "exmsys.db"
MASTER_DIR = DATA_DIR / "master"
MASTER_DB = MASTER_DIR / "exmsys.db"
BACKUP_DIR = DATA_DIR / "backup"

# 个人记录表（模板中必须清空）
RECORD_TABLES = [
    "answer_records", "study_records", "wrong_questions", "drafts",
    "exam_records", "mock_exam_records", "question_stats",
]

# 历史遗留的备份/修复表（模板中直接删除）
JUNK_TABLES = [
    "_answer_backup", "_dedup_backup_answer_records", "_dedup_backup_question_stats",
    "_dedup_backup_questions", "_md5_rebuild_answer_records",
    "_md5_rebuild_question_stats", "_md5_rebuild_questions", "_question_stats_backup",
]


def main():
    if not SRC_DB.exists():
        print(f"❌ 源数据库不存在: {SRC_DB}")
        return 1

    # 1. 备份源库
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"{ts}_pre_master_exmsys.db"
    shutil.copy2(SRC_DB, backup_path)
    print(f"✅ 已备份源库 → {backup_path}")

    # 2. 复制为模板
    MASTER_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC_DB, MASTER_DB)
    print(f"✅ 已复制模板 → {MASTER_DB}")

    # 3. 在模板上清空记录表 / 删除遗留表
    conn = sqlite3.connect(str(MASTER_DB))
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        cur = conn.cursor()
        for t in RECORD_TABLES:
            n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            if n > 0:
                cur.execute(f"DELETE FROM {t}")
                print(f"  🧹 清空 {t}: {n} 条")
            else:
                print(f"  · {t}: 已为空")
        for t in JUNK_TABLES:
            exists = cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)
            ).fetchone()
            if exists:
                cur.execute(f"DROP TABLE {t}")
                print(f"  🗑️ 删除遗留表 {t}")
        conn.commit()
    finally:
        conn.close()

    # 4. 校验
    conn = sqlite3.connect(str(MASTER_DB))
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    by_type = cur.execute(
        "SELECT exam_type, COUNT(*) FROM questions GROUP BY exam_type ORDER BY COUNT(*) DESC"
    ).fetchall()
    cases = cur.execute("SELECT COUNT(*) FROM case_studies").fetchone()[0]
    cfg = cur.execute("SELECT COUNT(*) FROM config").fetchone()[0]
    leftover = []
    for t in RECORD_TABLES:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        if n:
            leftover.append(f"{t}={n}")
    conn.close()
    print(f"\n📊 模板校验: 共 {total} 题（{', '.join(f'{e}={c}' for e, c in by_type)}），案例 {cases}，配置 {cfg} 项")
    if leftover:
        print(f"⚠️ 仍有记录残留: {leftover}")
        return 1
    print("✅ 模板生成完成，记录表全部清空")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

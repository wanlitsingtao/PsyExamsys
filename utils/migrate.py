"""
JSON → SQLite 数据迁移脚本
"""
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime

# 添加项目路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.data_access import SQLiteDataAccess, SQLITE_DB, DataAccess
from utils.data_manager import (
    load_questions, load_question_stats, load_wrong_questions,
    load_answer_records, load_exam_records, load_study_records,
    load_mock_exam_records, load_config,
    _extract_qids_from_wrong_list,
)


def backup_json_files():
    """迁移前备份所有 JSON 文件"""
    data_dir = Path(__file__).resolve().parent.parent / "data"
    backup_dir = data_dir / "backup_before_sqlite"
    backup_dir.mkdir(parents=True, exist_ok=True)

    json_files = [
        "questions.json", "question_stats.json", "wrong_questions.json",
        "answer_records.json", "exam_records.json", "study_records.json",
        "mock_exam_records.json", "config.json",
    ]
    for fname in json_files:
        src = data_dir / fname
        if src.exists():
            dst = backup_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{fname}"
            import shutil
            shutil.copy2(src, dst)
            print(f"  ✅ 已备份: {fname} → {dst.name}")

    # 备份草稿目录
    drafts_dir = data_dir / "drafts"
    if drafts_dir.exists():
        import shutil
        backup_drafts = backup_dir / "drafts"
        if backup_drafts.exists():
            shutil.rmtree(backup_drafts)
        shutil.copytree(drafts_dir, backup_drafts)
        print(f"  ✅ 已备份: drafts/ → backup_before_sqlite/drafts/")


def migrate():
    """执行迁移：JSON → SQLite"""
    print("=" * 60)
    print("JSON → SQLite 数据迁移")
    print("=" * 60)

    # 1. 备份
    print("\n【第1步】备份 JSON 文件...")
    backup_json_files()

    # 2. 创建 SQLite 数据库（表结构在 __init__ 中自动创建）
    print("\n【第2步】创建 SQLite 数据库...")
    dao = SQLiteDataAccess()
    print(f"  ✅ 数据库已创建: {SQLITE_DB}")

    # 3. 迁移题库
    print("\n【第3步】迁移题库 (questions.json)...")
    questions = load_questions()
    dao.save_questions(questions)
    print(f"  ✅ 已导入 {len(questions)} 道题")

    # 4. 迁移答题统计
    print("\n【第4步】迁移答题统计 (question_stats.json)...")
    stats = load_question_stats()
    dao.save_question_stats(stats)
    print(f"  ✅ 已导入 {len(stats)} 条统计")

    # 5. 迁移错题
    print("\n【第5步】迁移错题库 (wrong_questions.json)...")
    wrong_list = load_wrong_questions()
    wrong_qids = _extract_qids_from_wrong_list(wrong_list)
    dao.save_wrong_questions(wrong_qids)
    print(f"  ✅ 已导入 {len(wrong_qids)} 道错题")

    # 6. 迁移答题记录
    print("\n【第6步】迁移答题记录 (answer_records.json)...")
    records = load_answer_records()
    dao.save_answer_records(records)
    print(f"  ✅ 已导入 {len(records)} 条答题记录")

    # 7. 迁移考试记录
    print("\n【第7步】迁移考试记录 (exam_records.json)...")
    exam_records = load_exam_records()
    for rec in exam_records:
        dao.append_exam_record(rec)
    print(f"  ✅ 已导入 {len(exam_records)} 条考试记录")

    # 8. 迁移背题记录
    print("\n【第8步】迁移背题记录 (study_records.json)...")
    study_records = load_study_records()
    for rec in study_records:
        dao.append_study_record(rec)
    print(f"  ✅ 已导入 {len(study_records)} 条背题记录")

    # 9. 迁移模拟考试记录
    print("\n【第9步】迁移模拟考试记录 (mock_exam_records.json)...")
    mock_records = load_mock_exam_records()
    for rec in mock_records:
        dao.append_mock_exam_record(rec)
    print(f"  ✅ 已导入 {len(mock_records)} 条模拟考试记录")

    # 10. 迁移配置
    print("\n【第10步】迁移配置 (config.json)...")
    config = load_config()
    dao.save_config(config)
    print(f"  ✅ 已导入配置")

    # 11. 迁移草稿
    print("\n【第11步】迁移草稿 (drafts/)...")
    import os
    drafts_dir = Path(__file__).resolve().parent.parent / "data" / "drafts"
    if drafts_dir.exists():
        draft_count = 0
        for draft_file in drafts_dir.glob("*.json"):
            try:
                with open(draft_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                draft_id = data.get("draft_id", draft_file.stem.split("_", 1)[1] if "_" in draft_file.stem else draft_file.stem)
                prefix = draft_file.stem.split("_")[0] if "_" in draft_file.stem else "unknown"
                # 移除 draft_id 和 saved_at（save_draft 会自动加）
                data_to_save = {k: v for k, v in data.items() if k not in ("draft_id", "saved_at")}
                dao.save_draft(prefix, draft_id, data_to_save)
                draft_count += 1
            except Exception as e:
                print(f"  ⚠️ 跳过损坏的草稿: {draft_file.name} ({e})")
        print(f"  ✅ 已导入 {draft_count} 个草稿")

    print("\n" + "=" * 60)
    print("✅ 迁移完成！")
    print(f"   数据库: {SQLITE_DB}")
    print("=" * 60)


if __name__ == "__main__":
    migrate()

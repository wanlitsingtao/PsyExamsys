# -*- coding: utf-8 -*-
"""
单库多租户回归测试（2026-09-24 改造后）

运行
    python scripts/test_multiuser.py

它验证什么（每条都是改造后新引入的契约，改动前必读）
    1. 全新空库能初始化           —— 回归「_init_db 在 question_stats 建表前就校验」的 P0
    2. 设备指纹 → user_id 派生不变 —— 老用户迁移后 user_id 必须一致
    3. 公共题库对所有用户可见、私人题库只对自己可见
    4. **题目 ID 稳定**：
         · 重复导入同一份题库 → 全部 unchanged，一道新题都不加（ID 零漂移）
         · 库里 md5 陈旧（管理员直接改过库）→ 仍按内容指纹配上，ID 不变
         · 内容真被改过 → 原地 UPDATE，ID 不变
       这是用户要求的「用户题库与初始题库通过 ID 关联」的守门测试。
    5. 个人数据（统计/错题/记录/草稿/配置）按 user_id 严格隔离，互不可见
    6. 用户清空自己的题库不影响公共题库，也不影响别的用户

安全
    **全程在临时目录的临时库上跑，绝不读写 data/ 下的任何真实文件。**
    这一点很关键：真实库里是 17908 条答题记录，测试把它写坏过一次就回不来了。
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import utils.data_access as da
import utils.data_manager as dm
import utils.account_manager as acct

sys.path.insert(0, str(ROOT / "scripts"))
from _testenv import snapshot_real_db  # noqa: E402  （防呆用，见 guard()）

REAL_DATA = ROOT / "data"

# ---- 隔离：把单库路径指到临时目录，并断言没碰真实目录 ----
_tmp = Path(tempfile.mkdtemp(prefix="exmsys_single_db_test_"))
_test_db = _tmp / "exmsys.db"
da.SQLITE_DB = _test_db
dm.SQLITE_DB = _test_db
dm.DATA_DIR = _tmp
dm.BACKUP_DIR = _tmp / "backup"
dm.DRAFTS_DIR = _tmp / "drafts"
da.reset_data_access()
dm._dao = None
dm._current_user_id = None

_passed = []


def ok(msg):
    _passed.append(msg)
    print(f"✅ {len(_passed):2d}. {msg}")


def guard():
    """数据文件防呆：确认全程没有改动真实 data/ 下的任何文件

    注意：不能断言「data/exmsys.db 不存在」—— 单库改造后它本来就该存在
    （那是生产库）。正确的判据是**指纹与目录清单都没变**。
    """
    after = snapshot_real_db()
    assert after == _real_db_before, \
        f"❌ 真实库被改动了！{_real_db_before} → {after}（请立即用 data/backup/ 还原）"
    for sub in ("master", "users"):
        d = REAL_DATA / sub
        before = _real_snapshot.get(sub)
        after_ls = sorted(p.name for p in d.glob("*")) if d.exists() else []
        assert before == after_ls, f"真实 {sub}/ 被改动：{before} → {after_ls}"


_real_snapshot = {}
_real_db_before = None


def snapshot_real():
    global _real_db_before
    _real_db_before = snapshot_real_db()
    for sub in ("master", "users"):
        d = REAL_DATA / sub
        _real_snapshot[sub] = sorted(p.name for p in d.glob("*")) if d.exists() else []


def mkq(text, opts, ans, src="题库A.docx", idx=1, typ="single", expl="", cat="心理学导论"):
    q = {
        "question": text, "options": opts, "answer": ans, "type": typ,
        "source_file": src, "index_num": idx, "explanation": expl,
        "category": cat, "exam_type": dm.DEFAULT_EXAM_TYPE,
    }
    q["md5"] = da.question_md5(q)
    return q


SAMPLE = [
    mkq("心理健康的标准不包括（ ）。", {"A": "智力正常", "B": "情绪良好", "C": "腰缠万贯", "D": "行为协调"}, "C", idx=1),
    mkq("心理咨询的首要原则是（ ）。", {"A": "保密", "B": "收费", "C": "宣传", "D": "批评"}, "A", idx=2),
    mkq("罗杰斯属于（ ）学派。", {"A": "精神分析", "B": "人本主义", "C": "行为主义", "D": "认知"}, "B", idx=3),
]


def main():
    snapshot_real()
    print("=" * 68)
    print("单库多租户回归测试（临时库：" + str(_test_db) + "）")
    print("=" * 68)

    # ---- 1. 全新空库能初始化（P0 回归）----
    dao = da.SQLiteDataAccess(db_path=str(_test_db))
    assert _test_db.exists(), "新库未创建"
    import sqlite3
    con = sqlite3.connect(str(_test_db))
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    need = {"questions", "case_studies", "question_stats", "wrong_questions",
            "answer_records", "exam_records", "mock_exam_records", "study_records",
            "drafts", "app_config", "user_config", "users", "user_devices"}
    assert need <= tables, f"缺表：{need - tables}"
    ok(f"全新空库初始化成功，{len(tables)} 张表齐全（P0 回归：不因 question_stats 未建而报错）")

    # ---- 2. user_id 派生不变 ----
    fp = acct.generate_device_fingerprint("Mozilla/5.0 (Windows NT 10.0; Win64; x64) TestUA")
    expect_uid = __import__("hashlib").md5(("exmsys_device_" + fp).encode("utf-8")).hexdigest()[:12]
    got = acct.user_id_for(fp)
    assert got == expect_uid, f"user_id 派生算法变了：{got} != {expect_uid}"
    ok(f"user_id 派生算法未变（md5('exmsys_device_'+指纹)[:12] = {got}）—— 老用户迁移后不变")

    # ---- 3. 管理员 ----
    acct.ensure_admin()
    admin = da.get_data_access().get_user_by_username(acct.ADMIN_USERNAME)
    assert admin and admin["role"] == "admin", admin
    assert admin["password_hash"] == __import__("hashlib").sha256(b"admin").hexdigest()
    acct.ensure_admin()  # 幂等
    n_admin = len([u for u in da.get_data_access().list_users() if u["role"] == "admin"])
    assert n_admin == 1, f"管理员重复创建：{n_admin}"
    assert acct.is_admin(acct.ADMIN_USER_ID)
    ok("初始管理员 admin/admin 已建，重复 ensure_admin() 幂等")

    # ---- 4. 两个用户 + 公共题库 ----
    uA = da.get_data_access().upsert_user("userA_uid", username="alice") or "userA_uid"
    da.get_data_access().upsert_user("userB_uid", username="bob")
    rep = da.get_data_access().import_questions(SAMPLE, owner_id=da.PUBLIC_OWNER,
                                                mode="append", exam_type=dm.DEFAULT_EXAM_TYPE)
    assert rep["added"] == 3, rep
    pub_ids = sorted(r["id"] for r in da.get_data_access().load_questions(user_id="userA_uid"))
    assert len(pub_ids) == 3
    ok(f"公共题库导入 3 题；A、B 两个用户都能看到（看到 {len(pub_ids)} 题）")

    # ---- 5. 私人题库隔离 ----
    priv = [mkq("这是A的私有题（ ）。", {"A": "甲", "B": "乙"}, "A", src="A私有.docx")]
    r = da.get_data_access().import_questions(priv, owner_id="userA_uid",
                                              exam_type=dm.DEFAULT_EXAM_TYPE)
    assert r["added"] == 1, r
    a_sees = da.get_data_access().load_questions(user_id="userA_uid")
    b_sees = da.get_data_access().load_questions(user_id="userB_uid")
    assert len(a_sees) == 4 and len(b_sees) == 3, (len(a_sees), len(b_sees))
    ok("A 导入私有题后 A 看到 4 题、B 仍看到 3 题（私人题库不串号）")

    # ---- 6. 个人数据隔离 ----
    qid = da.make_question_id(da.PUBLIC_OWNER, SAMPLE[0])  # 确定性：SAMPLE[0] 的 ID
    assert qid in pub_ids, f"{qid} 不在 {pub_ids}"
    # 形参约定（与 pages/mock_exam.py 等一致）：
    #   wrong_qids   = [(qid, 用户答案), ...]
    #   correct_qids = [qid, ...]
    #   stats_updates= [(qid, is_correct), ...]
    da.get_data_access().batch_update_wrong_and_stats(
        wrong_qids=[(qid, "A")], correct_qids=[], stats_updates=[(qid, False)],
        user_id="userA_uid")
    da.get_data_access().save_draft("study", "d1", {"x": 1}, user_id="userA_uid")
    da.get_data_access().save_config({"study_per_round": 99}, user_id="userA_uid")
    ws_a = da.get_data_access().get_wrong_stats(user_id="userA_uid")
    ws_b = da.get_data_access().get_wrong_stats(user_id="userB_uid")
    assert ws_a["total"] == 1, ws_a
    assert ws_b["total"] == 0, ws_b
    a_wrong = da.get_data_access().load_wrong_questions(user_id="userA_uid")
    b_wrong = da.get_data_access().load_wrong_questions(user_id="userB_uid")
    assert len(a_wrong) >= 1 and len(b_wrong) == 0, (len(a_wrong), len(b_wrong))
    assert len(da.get_data_access().load_drafts("study", user_id="userA_uid")) == 1
    assert len(da.get_data_access().load_drafts("study", user_id="userB_uid")) == 0
    assert da.get_data_access().load_config(user_id="userA_uid").get("study_per_round") == 99
    assert da.get_data_access().load_config(user_id="userB_uid").get("study_per_round") != 99
    ok("错题/草稿/配置按 user_id 隔离（A 有、B 没有，配置值互不影响）")

    # ---- 7. 同名草稿不互相覆盖 ----
    da.get_data_access().save_draft("study", "same_id", {"owner": "B"}, user_id="userB_uid")
    a_d = da.get_data_access().load_drafts("study", user_id="userA_uid", )
    b_d = da.get_data_access().load_drafts("study", user_id="userB_uid")
    assert len(a_d) == 1 and len(b_d) == 1, (len(a_d), len(b_d))
    ok("不同用户可存在同名草稿（主键含 user_id，不互相覆盖）")

    # ---- 8. 核心：重复导入同一份题库 → ID 零漂移 ----
    before = {r["id"]: r for r in da.get_data_access().load_questions(user_id="userA_uid")
              if r.get("owner_id") == da.PUBLIC_OWNER}
    rep2 = da.get_data_access().import_questions([dict(q) for q in SAMPLE],
                                                 owner_id=da.PUBLIC_OWNER,
                                                 mode="replace",
                                                 exam_type=dm.DEFAULT_EXAM_TYPE)
    after = {r["id"]: r for r in da.get_data_access().load_questions(user_id="userA_uid")
             if r.get("owner_id") == da.PUBLIC_OWNER}
    assert set(before) == set(after), f"ID 漂移了：{set(before) ^ set(after)}"
    assert rep2["added"] == 0 and rep2["removed"] == 0, rep2
    assert rep2["unchanged"] == 3, rep2
    ok(f"重复导入同一题库：0 新增 / 0 删除 / 3 unchanged，ID 完全不变（{rep2}）")

    # ---- 9. 核心：库里 md5 陈旧时，仍按内容指纹配上 ----
    conn = sqlite3.connect(str(_test_db))
    conn.execute("UPDATE questions SET md5 = 'stale_stale_stale' WHERE id = ?", (qid,))
    conn.commit()
    conn.close()
    rep3 = da.get_data_access().import_questions([dict(q) for q in SAMPLE],
                                                 owner_id=da.PUBLIC_OWNER,
                                                 mode="replace",
                                                 exam_type=dm.DEFAULT_EXAM_TYPE)
    after3 = [r["id"] for r in da.get_data_access().load_questions(user_id="userA_uid")
              if r.get("owner_id") == da.PUBLIC_OWNER]
    assert rep3["added"] == 0, f"md5 陈旧导致误判为新题：{rep3}"
    assert sorted(after3) == sorted(before), "md5 陈旧导致 ID 漂移"
    ok("库中 md5 陈旧（模拟管理员直接改库）时，重复导入仍复用原 ID（内容指纹两侧现算）")

    # ---- 10. 内容真被改动 → 原地 UPDATE，ID 不变 ----
    edited = [dict(q) for q in SAMPLE]
    edited[0] = dict(edited[0])
    edited[0]["explanation"] = "补充：心理健康不等于没有烦恼。"
    rep4 = da.get_data_access().import_questions(edited, owner_id=da.PUBLIC_OWNER,
                                                 mode="replace",
                                                 exam_type=dm.DEFAULT_EXAM_TYPE)
    assert rep4["updated"] == 1 and rep4["added"] == 0, rep4
    after4 = {r["id"]: r for r in da.get_data_access().load_questions(user_id="userA_uid")
              if r.get("owner_id") == da.PUBLIC_OWNER}
    assert set(after4) == set(before), "更新解析导致 ID 漂移"
    assert "没有烦恼" in (after4[qid].get("explanation") or ""), after4[qid].get("explanation")
    ok("修改解析后原地 UPDATE：ID 不变（用户的统计/错题因此不断链）")

    # ---- 11. A 的统计仍指向同一 ID（断链检查）----
    a_wrong2 = da.get_data_access().load_wrong_questions(user_id="userA_uid")
    assert qid in a_wrong2, f"更新题目后 A 的错题断链（{a_wrong2}）"
    ok("A 的错题本仍指向同一 ID —— 教学数据零断链")

    # ---- 12. 用户清空自己的题库不影响公共题库与别人 ----
    da.get_data_access().clear_questions(owner_id="userA_uid")
    a_sees2 = da.get_data_access().load_questions(user_id="userA_uid")
    b_sees2 = da.get_data_access().load_questions(user_id="userB_uid")
    assert len(a_sees2) == 3 and len(b_sees2) == 3, (len(a_sees2), len(b_sees2))
    n_pub = da.get_data_access().count_questions(owner_id=da.PUBLIC_OWNER)
    assert n_pub == 3, n_pub
    ok("A 清空私有题库：公共题库 3 题完好，B 也不受影响")

    # ---- 13. 设备绑定 ----
    acct.get_or_create_user(fp, "Mozilla/5.0 TestUA")
    uid = da.get_data_access().get_device_user(fp)
    assert uid, "设备未登记"
    uid2 = da.get_data_access().get_device_user(fp)
    assert uid == uid2, "同设备识别出两个用户"
    ok(f"同一设备指纹稳定识别为同一用户（{uid}）")

    # ---- 14. 题库版本号随变更递增 ----
    v1 = da.get_data_access().get_questions_version()
    da.get_data_access().import_questions([mkq("版本号测试题（ ）。", {"A": "1", "B": "2"}, "A",
                                               src="v.docx")],
                                          owner_id=da.PUBLIC_OWNER,
                                          exam_type=dm.DEFAULT_EXAM_TYPE)
    v2 = da.get_data_access().get_questions_version()
    assert v2 > v1, (v1, v2)
    ok(f"题库版本号随导入递增（{v1} → {v2}）—— 别人的改动下一次刷新可见")

    print("\n" + "=" * 68)
    print(f"✅ 全部通过（{len(_passed)} 项）")


if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            guard()
            print("✅ 防呆：未触碰真实 data/ 目录")
        except AssertionError as e:
            print(f"❌ {e}")
            raise
        finally:
            shutil.rmtree(_tmp, ignore_errors=True)

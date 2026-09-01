# -*- coding: utf-8 -*-
"""多用户系统端到端测试 —— 全部在临时数据目录中运行，不触碰真实数据"""
import sys, json, shutil, sqlite3, tempfile
from pathlib import Path

sys.path.insert(0, "E:/LingMa/psych-exm/exmsys-dev")

import utils.account_manager as acct
import utils.data_manager as dm
import utils.data_access as da

REAL_MASTER = "E:/LingMa/psych-exm/exmsys-dev/data/master/exmsys.db"
tmp = Path(tempfile.mkdtemp(prefix="exmsys_multi_test_"))

# ---- 构造测试数据目录: master(干净模板) + legacy(带标记记录) ----
(tmp / "master").mkdir(parents=True)
shutil.copy2(REAL_MASTER, tmp / "master" / "exmsys.db")
shutil.copy2(tmp / "master" / "exmsys.db", tmp / "exmsys.db")
conn = sqlite3.connect(str(tmp / "exmsys.db"))
conn.execute("INSERT INTO config(key,value) VALUES('_test_marker','\"legacy_data\"')")
conn.commit()
conn.close()

# ---- 打补丁到临时目录 ----
acct.DATA_DIR = tmp
acct.MASTER_DB = tmp / "master" / "exmsys.db"
acct.USERS_DIR = tmp / "users"
acct.ARCHIVE_DIR = tmp / "archive"
acct.ACCOUNTS_FILE = tmp / "accounts.json"
acct.USER_MAPPING_FILE = tmp / "user_mapping.json"
acct.LEGACY_DB = tmp / "exmsys.db"
dm.USERS_DIR = tmp / "users"


def qcount(user_id):
    dm.set_current_user(user_id)
    return len(dm.load_questions())


# ---- 1. 指纹生成稳定 ----
fp1 = acct.generate_device_fingerprint("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
fp1b = acct.generate_device_fingerprint("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
assert fp1 == fp1b and len(fp1) == 32
print("✅ 1. 指纹生成稳定（同 UA 同指纹，32位）")

# ---- 2. 首个用户迁移遗留库 ----
u1 = acct.get_or_create_user(fp1, "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
assert u1["created"] and u1["source"] == "migrated", u1
assert not acct.LEGACY_DB.exists(), "遗留库应已归档"
uid1 = u1["user_id"]
assert (tmp / "users" / f"{uid1}.db").exists()
conn = sqlite3.connect(str(tmp / "users" / f"{uid1}.db"))
row = conn.execute("SELECT value FROM config WHERE key='_test_marker'").fetchone()
conn.close()
assert row and json.loads(row[0]) == "legacy_data", "首用户应保留遗留记录"
print(f"✅ 2. 首个用户迁移遗留库（uid={uid1}，历史记录保留）")

# ---- 3. 相同指纹 → 同一用户 ----
u1b = acct.get_or_create_user(fp1, "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
assert (not u1b["created"]) and u1b["user_id"] == uid1
print("✅ 3. 同指纹识别同一用户（稳定对应关系）")

# ---- 4. 新用户克隆干净模板 ----
fp2 = acct.generate_device_fingerprint("Other-Device-UA-987")
u2 = acct.get_or_create_user(fp2, "Other-Device-UA-987")
assert u2["created"] and u2["source"] == "cloned", u2
uid2 = u2["user_id"]
assert uid2 != uid1
conn = sqlite3.connect(str(tmp / "users" / f"{uid2}.db"))
row = conn.execute("SELECT value FROM config WHERE key='_test_marker'").fetchone()
conn.close()
assert row is None, "克隆用户不应有遗留标记"
print(f"✅ 4. 新用户克隆干净模板（uid={uid2}，无历史记录）")

# ---- 5. data_manager 路由：两用户初始题量一致 ----
n1, n2 = qcount(uid1), qcount(uid2)
assert n1 == n2 == 5119, (n1, n2)
print(f"✅ 5. 两用户初始题库一致（各 {n1} 题）")

# ---- 6. 用户隔离：用户1加题不影响用户2 ----
dm.set_current_user(uid1)
q_all = dm.load_questions()
new_q = dict(q_all[0])
new_q["id"] = "test_q_0001"
new_q["md5"] = "test_md5_0001_unique"  # 真实导入会重算 md5，测试需避开 UNIQUE 约束
new_q["question"] = "【隔离测试】只属于用户1的题"
new_q["exam_type"] = "心理学会咨询师四级"
dm.save_questions(q_all + [new_q])
assert qcount(uid1) == 5120, "用户1加题后应为 5120"
assert qcount(uid2) == 5119, "用户2不受影响"
print("✅ 6. 用户题库互相隔离（用户1=5120，用户2=5119）")

# ---- 7. 账号绑定 ----
am = acct.AccountManager()
ok, msg = am.bind_account(fp1, "TestUser", "pass123")
assert ok, msg
ok, _ = am.bind_account(fp1, "Other", "x")
assert not ok, "一设备只能绑一账号"
ok, msg, uid = am.login_account("testuser", "pass123")
assert ok and uid == uid1, (msg, uid)
ok, _, _ = am.login_account("testuser", "wrong")
assert not ok
info = am.get_bound_account(fp1)
assert info and info["username"] == "TestUser"
print("✅ 7. 账号绑定/登录（SHA-256，大小写不敏感，一设备一账号）")

# ---- 8. 跨设备登录切换回原用户 ----
fp_new = acct.generate_device_fingerprint("Brand-New-Device")
u3 = acct.get_or_create_user(fp_new, "Brand-New-Device")
uid3 = u3["user_id"]
assert uid3 != uid1
ok, msg, uid = am.login_account("TestUser", "pass123")
assert ok and uid == uid1, "跨设备登录应回到绑定账号的原用户"
print("✅ 8. 跨设备登录切换回原用户库")

# ---- 9. 遗忘阈值按用户库隔离 ----
dm.set_current_user(uid1)
conn = sqlite3.connect(str(dm.get_current_db_path()))
conn.execute("INSERT OR REPLACE INTO config(key,value) VALUES('retention_days_threshold','9')")
conn.commit()
conn.close()
da._retention_threshold_cache.clear()
assert dm.get_retention_threshold() == 9
dm.set_current_user(uid2)
da._retention_threshold_cache.clear()
assert dm.get_retention_threshold() == 5
print("✅ 9. 遗忘预警阈值按用户库隔离（用户1=9天，用户2=5天）")

# ---- 10. 解绑 ----
ok, msg = am.unbind_account(fp1)
assert ok
assert am.get_bound_account(fp1) is None
print("✅ 10. 账号解绑")

print()
print("ALL PASS ✅ 多用户系统核心功能全部验证通过")

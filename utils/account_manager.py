# -*- coding: utf-8 -*-
"""
多用户账户管理模块（单库多租户版，2026-09-24 起）

架构变更要点
================================================================
· 全系统只连一个库 data/exmsys.db，**身份也存库里**（users / user_devices 两张表）；
  不再有 accounts.json / user_mapping.json，也没有「每用户一个 db 文件」。
· user_id 派生算法保持不变：md5("exmsys_device_" + 设备指纹)[:12]，
  因此改造前的老用户迁移后 user_id 不变，会话与数据都不受影响。

轨道一：设备指纹（零门槛，自动分配用户）
  首次访问 → 生成设备指纹 → 自动创建用户（role='user'）→ 登记设备
  同一浏览器再次访问 → 指纹不变 → 自动识别同一用户

轨道二：账号绑定/登录（可选，跨设备恢复）
  用户名/密码（SHA-256 哈希）。一个账号可绑定多个设备；登录会自动登记当前设备。

管理员：
  ensure_admin() 保证存在 username='admin' 的账号（初始密码 admin，role='admin'）。
  管理员可维护公共题库、查看用户列表。
"""

import hashlib
from typing import Optional, Tuple

from utils.data_access import get_data_access

# 角色
ROLE_ADMIN = "admin"
ROLE_USER = "user"

# 初始管理员
ADMIN_USERNAME = "admin"
ADMIN_DEFAULT_PASSWORD = "admin"
# 管理员 user_id 独立命名空间（与设备派生的 user_id 不冲突）
ADMIN_USER_ID = hashlib.md5(b"exmsys_admin_account").hexdigest()[:12]


def _hash_password(password: str) -> str:
    """SHA-256 哈希密码"""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def generate_device_fingerprint(user_agent: str) -> str:
    """生成设备指纹（32位 MD5）—— 同浏览器/UA 稳定不变"""
    return hashlib.md5((user_agent or "unknown-device").encode("utf-8")).hexdigest()[:32]


def user_id_for(fingerprint: str) -> str:
    """由设备指纹派生用户 id（12位）

    ⚠️ 本算法是**兼容性契约**：改造前的老库就是用它生成 user_id 的，
    必须保持不变，否则迁移后老用户会「换号」看到空数据。
    """
    return hashlib.md5(f"exmsys_device_{fingerprint}".encode("utf-8")).hexdigest()[:12]


def _dao():
    return get_data_access()


# ============================
# 管理员
# ============================

def ensure_admin() -> dict:
    """确保存在初始管理员账号（username=admin / 初始密码 admin，role=admin）。

    幂等：已存在则直接返回，不会覆盖已改过的密码。
    """
    dao = _dao()
    existing = dao.get_user_by_username(ADMIN_USERNAME)
    if existing:
        return existing
    existing_by_id = dao.get_user(ADMIN_USER_ID)
    if existing_by_id:
        # 同 id 的行已存在（可能是匿名行）→ 补上管理员身份
        dao.upsert_user(ADMIN_USER_ID, username=ADMIN_USERNAME,
                        password_hash=_hash_password(ADMIN_DEFAULT_PASSWORD),
                        role=ROLE_ADMIN, display_name="系统管理员")
    else:
        dao.upsert_user(ADMIN_USER_ID, username=ADMIN_USERNAME,
                        password_hash=_hash_password(ADMIN_DEFAULT_PASSWORD),
                        role=ROLE_ADMIN, display_name="系统管理员")
    return dao.get_user(ADMIN_USER_ID)


def is_admin(user_id: str) -> bool:
    """当前用户是否为管理员"""
    if not user_id:
        return False
    u = _dao().get_user(user_id)
    return bool(u) and u.get("role") == ROLE_ADMIN


def get_role(user_id: str) -> str:
    """取用户角色（未知用户按普通用户处理）"""
    if not user_id:
        return ROLE_USER
    u = _dao().get_user(user_id)
    return (u or {}).get("role") or ROLE_USER


def get_display_name(user_id: str) -> str:
    """取用户显示名（用户名 / 自定义显示名 / user_id 短码）"""
    if not user_id:
        return ""
    u = _dao().get_user(user_id) or {}
    return u.get("display_name") or u.get("username") or user_id


def list_users() -> list:
    """列出全部用户（管理员视图用）"""
    return _dao().list_users()


def is_admin_password_default() -> bool:
    """管理员是否仍在使用初始密码（用于首页安全提示）"""
    u = _dao().get_user_by_username(ADMIN_USERNAME)
    if not u:
        return False
    return u.get("password_hash") == _hash_password(ADMIN_DEFAULT_PASSWORD)


# ============================
# 设备 → 用户
# ============================

def get_or_create_user(fingerprint: str, user_agent: str = None) -> dict:
    """通过设备指纹获取或创建用户（统一入口）。

    Returns:
        {"user_id": str, "created": bool, "source": "existing"|"created"|"reused",
         "role": "admin"|"user"}
    """
    fingerprint = (fingerprint or "").strip()
    if not fingerprint:
        fingerprint = generate_device_fingerprint(user_agent)

    dao = _dao()

    # 1) 设备已登记 → 直接返回该用户
    uid = dao.get_device_user(fingerprint)
    if uid:
        u = dao.get_user(uid)
        if not u:
            # 半截数据（设备表有、用户表无）→ 补建用户行
            dao.upsert_user(uid, role=ROLE_USER)
            u = dao.get_user(uid) or {}
        return {
            "user_id": uid,
            "created": False,
            "source": "existing",
            "role": u.get("role") or ROLE_USER,
        }

    # 2) 设备未登记 → 按指纹派生 user_id 并登记
    uid = user_id_for(fingerprint)
    existed = bool(dao.get_user(uid))
    if not existed:
        dao.upsert_user(uid, role=ROLE_USER)
    dao.bind_device(fingerprint, uid)
    return {
        "user_id": uid,
        "created": not existed,
        "source": "created" if not existed else "reused",
        "role": ROLE_USER,
    }


# ============================
# 账号绑定 / 登录（轨道二）
# ============================

class AccountManager:
    """账号绑定/登录管理器（身份存数据库）"""

    def __init__(self):
        self._dao = _dao()

    # ---- 查询 ----

    def get_bound_account(self, device_fingerprint: str) -> Optional[dict]:
        """查询设备当前绑定的账号信息 {"username", "created_at"} 或 None"""
        uid = self._dao.get_device_user(device_fingerprint)
        if not uid:
            return None
        u = self._dao.get_user(uid) or {}
        if u.get("username"):
            return {"username": u["username"], "created_at": u.get("created_at", "")}
        return None

    def is_username_taken(self, username: str) -> bool:
        """用户名是否已被占用（不区分大小写）"""
        return bool(self._dao.get_user_by_username(username))

    def get_user_id_for_username(self, username: str) -> Optional[str]:
        """通过用户名获取 user_id"""
        u = self._dao.get_user_by_username(username)
        return u.get("user_id") if u else None

    def get_account_for_user_id(self, user_id: str) -> Optional[dict]:
        """通过 user_id 反查账号信息（用于账号面板显示）"""
        if not user_id:
            return None
        u = self._dao.get_user(user_id) or {}
        if not u.get("username"):
            return None
        devices = self._dao.list_devices(user_id)
        return {
            "username": u["username"],
            "bound_device": devices[0]["device_fp"] if devices else "",
            "created_at": u.get("created_at", ""),
            "role": u.get("role") or ROLE_USER,
        }

    # ---- 绑定 / 登录 / 解绑 ----

    def bind_account(self, device_fingerprint: str, username: str, password: str) -> Tuple[bool, str]:
        """将当前设备对应的用户绑定到用户名/密码。一个设备只能绑定一个账号。"""
        username = (username or "").strip()
        if not username:
            return False, "用户名不能为空"
        if not password:
            return False, "密码不能为空"
        if not device_fingerprint:
            return False, "设备指纹缺失，无法绑定"

        uid = self._dao.get_device_user(device_fingerprint)
        if not uid:
            # 设备还没登记用户 → 兜底创建，避免"绑定失败：设备未知"
            uid = user_id_for(device_fingerprint)
            self._dao.upsert_user(uid, role=ROLE_USER)
            self._dao.bind_device(device_fingerprint, uid)

        cur_user = self._dao.get_user(uid) or {}
        if cur_user.get("username"):
            return False, f"该设备已绑定账号「{cur_user['username']}」，一个设备只能绑定一个账号"
        if username.lower() == ADMIN_USERNAME or self.is_username_taken(username):
            return False, f"用户名「{username}」已被使用，请更换"

        self._dao.upsert_user(uid, username=username, password_hash=_hash_password(password))
        return True, f"账号「{username}」绑定成功！"

    def login_account(self, username: str, password: str,
                      device_fingerprint: str = "") -> Tuple[bool, str, Optional[str]]:
        """用户名/密码登录，成功返回 (True, msg, user_id)。

        成功后**自动把当前设备登记到该账号**，解决「在新设备登录后下次浏览器
        自动识别仍落到匿名用户」的问题。一个账号可绑定多个设备。
        """
        username = (username or "").strip()
        if not username or not password:
            return False, "用户名和密码不能为空", None

        u = self._dao.get_user_by_username(username)
        if not u or u.get("password_hash") != _hash_password(password):
            return False, "用户名或密码错误", None

        uid = u["user_id"]
        self._dao.touch_user_login(uid)

        if device_fingerprint and self._dao.get_device_user(device_fingerprint) != uid:
            old_uid = self._dao.get_device_user(device_fingerprint)
            self._dao.bind_device(device_fingerprint, uid)
            suffix = f"（已自动将当前设备登记到该账号，原用户：{old_uid or '无'}）" if old_uid else "（已自动登记当前设备）"
            return True, f"登录成功，欢迎 {u.get('username')}！{suffix}", uid

        return True, f"登录成功，欢迎 {u.get('username')}！", uid

    def unbind_account(self, device_fingerprint: str) -> Tuple[bool, str]:
        """解除账号绑定（用户数据保留，回退为匿名设备用户）"""
        uid = self._dao.get_device_user(device_fingerprint)
        if not uid:
            return False, "该设备未绑定任何账号"
        u = self._dao.get_user(uid) or {}
        if not u.get("username"):
            return False, "该设备未绑定任何账号"
        if u.get("role") == ROLE_ADMIN:
            return False, "管理员账号不可解绑"
        self._dao.clear_user_account(uid)
        return True, "账号解绑成功（学习数据已保留）"

    def change_password(self, user_id: str, old_password: str, new_password: str) -> Tuple[bool, str]:
        """修改当前用户密码"""
        if not new_password or len(new_password) < 3:
            return False, "新密码至少 3 位"
        u = self._dao.get_user(user_id) or {}
        if not u.get("username"):
            return False, "当前用户尚未绑定账号"
        if u.get("password_hash") != _hash_password(old_password or ""):
            return False, "原密码不正确"
        self._dao.set_user_password(user_id, _hash_password(new_password))
        return True, "密码已更新"

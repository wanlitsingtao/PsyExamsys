# -*- coding: utf-8 -*-
"""
多用户账户管理模块（参考 WordStyle-Pub 双轨制，适配 exmsys 考试系统）

轨道一：设备指纹（零门槛，自动分配用户）
  首次访问 → 生成设备指纹 → 自动创建用户 → 克隆初始化题库模板作为该用户私有库
  同一浏览器再次访问 → 指纹不变 → 自动识别同一用户（稳定对应关系）

轨道二：账号绑定/登录（可选，跨设备恢复）
  用户名/密码（SHA-256 哈希存储），一个设备指纹只能绑定一个账号
  在其他设备登录后，切换回绑定账号对应的用户库

存储结构 (local 模式):
    data/master/exmsys.db     初始化题库模板（只读，克隆用）
    data/users/<user_id>.db   每用户私有库（user_id = md5("exmsys_device_<指纹>")[:12]）
    data/accounts.json        {"by_device": {指纹: 用户名}, "accounts": {用户名: {账号信息}}}
    data/user_mapping.json    {设备指纹: user_id}
    data/exmsys.db            遗留单机库（首次建用户时整体迁移给首个用户，随后归档）
"""
import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

# 数据目录（测试可用环境变量覆盖）
DATA_DIR = Path(os.environ.get("EXMSYS_DATA_DIR", "")) if os.environ.get("EXMSYS_DATA_DIR") \
    else Path(__file__).resolve().parent.parent / "data"
MASTER_DB = DATA_DIR / "master" / "exmsys.db"
USERS_DIR = DATA_DIR / "users"
ARCHIVE_DIR = DATA_DIR / "archive"
ACCOUNTS_FILE = DATA_DIR / "accounts.json"
USER_MAPPING_FILE = DATA_DIR / "user_mapping.json"
LEGACY_DB = DATA_DIR / "exmsys.db"  # 遗留单机库（首个用户迁移源）


def _hash_password(password: str) -> str:
    """SHA-256 哈希密码"""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def generate_device_fingerprint(user_agent: str) -> str:
    """生成设备指纹（32位 MD5）—— 同浏览器/UA 稳定不变"""
    return hashlib.md5((user_agent or "unknown-device").encode("utf-8")).hexdigest()[:32]


def user_id_for(fingerprint: str) -> str:
    """由设备指纹派生用户 id（12位），与 WordStyle 同模式"""
    return hashlib.md5(f"exmsys_device_{fingerprint}".encode("utf-8")).hexdigest()[:12]


def get_user_db_path(user_id: str) -> Path:
    """用户私有库路径"""
    return USERS_DIR / f"{user_id}.db"


def _load_json(path: Path, default):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return default


def _save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def _create_user_db(user_id: str) -> str:
    """创建用户私有库：首个用户迁移遗留库，其余克隆模板。返回来源标识"""
    USERS_DIR.mkdir(parents=True, exist_ok=True)
    user_db = get_user_db_path(user_id)

    # 首个用户：迁移遗留单机库（保留历史答题记录），随后归档防止重复迁移
    if LEGACY_DB.exists():
        shutil.copy2(LEGACY_DB, user_db)
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        legacy_archived = ARCHIVE_DIR / f"exmsys_legacy_{ts}.db"
        LEGACY_DB.rename(legacy_archived)
        return "migrated"

    # 其余用户：克隆初始化模板
    if not MASTER_DB.exists():
        raise FileNotFoundError(
            f"初始化题库模板缺失: {MASTER_DB}。请先运行 scripts/prepare_master.py 生成模板。"
        )
    shutil.copy2(MASTER_DB, user_db)
    return "cloned"


def get_or_create_user(fingerprint: str, user_agent: str = None) -> dict:
    """
    通过设备指纹获取或创建用户（统一入口）。

    Returns:
        {"user_id": str, "created": bool, "source": "existing"|"migrated"|"cloned",
         "db_path": str}
    """
    fingerprint = (fingerprint or "").strip()
    if not fingerprint:
        fingerprint = generate_device_fingerprint(user_agent)

    mapping = _load_json(USER_MAPPING_FILE, {})
    user_id = mapping.get(fingerprint)
    if user_id:
        return {
            "user_id": user_id,
            "created": False,
            "source": "existing",
            "db_path": str(get_user_db_path(user_id)),
        }

    user_id = user_id_for(fingerprint)
    source = _create_user_db(user_id)
    mapping[fingerprint] = user_id
    _save_json(USER_MAPPING_FILE, mapping)
    return {
        "user_id": user_id,
        "created": True,
        "source": source,
        "db_path": str(get_user_db_path(user_id)),
    }


class AccountManager:
    """账号绑定/登录管理器（local 模式，双轨制的轨道二）"""

    def __init__(self):
        self._accounts_file = ACCOUNTS_FILE
        self._mapping_file = USER_MAPPING_FILE

    # ---- 查询 ----

    def get_bound_account(self, device_fingerprint: str) -> Optional[dict]:
        """查询设备指纹绑定的账号信息 {"username", "created_at"} 或 None"""
        data = _load_json(self._accounts_file, {})
        username_lower = data.get("by_device", {}).get(device_fingerprint)
        if username_lower and username_lower in data.get("accounts", {}):
            acct = data["accounts"][username_lower]
            return {"username": acct["username"], "created_at": acct["created_at"]}
        return None

    def is_username_taken(self, username: str) -> bool:
        """用户名是否已被占用（不区分大小写）"""
        data = _load_json(self._accounts_file, {})
        return username.strip().lower() in data.get("accounts", {})

    def get_user_id_for_username(self, username: str) -> Optional[str]:
        """通过用户名获取其绑定设备对应的 user_id"""
        data = _load_json(self._accounts_file, {})
        username_lower = username.strip().lower()
        acct = data.get("accounts", {}).get(username_lower)
        if not acct:
            return None
        mapping = _load_json(self._mapping_file, {})
        return mapping.get(acct.get("bound_device", ""))

    # ---- 绑定 / 登录 ----

    def bind_account(self, device_fingerprint: str, username: str, password: str) -> Tuple[bool, str]:
        """将设备指纹绑定到用户名/密码。一个指纹只能绑定一个账号。"""
        username = (username or "").strip()
        username_lower = username.lower()
        if not username_lower:
            return False, "用户名不能为空"
        if not password:
            return False, "密码不能为空"
        if not device_fingerprint:
            return False, "设备指纹缺失，无法绑定"

        data = _load_json(self._accounts_file, {})
        data.setdefault("by_device", {})
        data.setdefault("accounts", {})

        if device_fingerprint in data["by_device"]:
            return False, f"该设备已绑定账号「{data['by_device'][device_fingerprint]}」，一个设备只能绑定一个账号"
        if username_lower in data["accounts"]:
            return False, f"用户名「{username}」已被使用，请更换"

        data["by_device"][device_fingerprint] = username_lower
        data["accounts"][username_lower] = {
            "username": username,
            "password_hash": _hash_password(password),
            "bound_device": device_fingerprint,
            "created_at": datetime.now().isoformat(),
        }
        _save_json(self._accounts_file, data)
        return True, f"账号「{username}」绑定成功！"

    def login_account(self, username: str, password: str) -> Tuple[bool, str, Optional[str]]:
        """用户名/密码登录，成功返回 (True, msg, user_id)"""
        username_lower = (username or "").strip().lower()
        if not username_lower or not password:
            return False, "用户名和密码不能为空", None

        data = _load_json(self._accounts_file, {})
        acct = data.get("accounts", {}).get(username_lower)
        if not acct or acct.get("password_hash") != _hash_password(password):
            return False, "用户名或密码错误", None

        user_id = self.get_user_id_for_username(username_lower)
        if not user_id:
            return False, "账号数据异常，请联系管理员", None
        return True, f"登录成功，欢迎 {acct['username']}！", user_id

    def unbind_account(self, device_fingerprint: str) -> Tuple[bool, str]:
        """解除设备指纹与账号的绑定"""
        data = _load_json(self._accounts_file, {})
        username_lower = data.get("by_device", {}).get(device_fingerprint)
        if not username_lower:
            return False, "该设备未绑定任何账号"
        data["by_device"].pop(device_fingerprint, None)
        data.get("accounts", {}).pop(username_lower, None)
        _save_json(self._accounts_file, data)
        return True, "账号解绑成功"

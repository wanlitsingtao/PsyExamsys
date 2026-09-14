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


def _db_question_count(db_path: Path) -> int:
    """安全读取库中的题目数：库不存在 / 无 questions 表 / 读取出错一律返回 0。

    用于判定一个库是否真的包含题库（避免把空壳库当作可用数据源）。
    """
    import sqlite3
    try:
        if not db_path.exists():
            return 0
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute("SELECT COUNT(*) FROM questions").fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except Exception:
        return 0


def _create_user_db(user_id: str) -> str:
    """创建用户私有库：遗留库含题目时迁移给首个用户，其余克隆模板。返回来源标识"""
    USERS_DIR.mkdir(parents=True, exist_ok=True)
    user_db = get_user_db_path(user_id)

    # 首个用户：迁移遗留单机库（保留历史答题记录），随后归档防止重复迁移。
    #
    # ⚠️ 2026-09-14 重要修复（"题库为空"根因）：
    #   此前只要 data/exmsys.db 存在就无条件迁移。但该文件可能被"某处用默认库
    #   路径访问数据库"的行为由 SQLite 自动创建为**空库**（只有表结构、0 道题），
    #   于是每个新设备用户都被喂了一个空库 → 表现为"新用户题库为空"。
    #   现在只有**确认含题目**才迁移；空壳遗留库直接删除，彻底杜绝毒害新用户。
    if LEGACY_DB.exists():
        if _db_question_count(LEGACY_DB) > 0:
            shutil.copy2(LEGACY_DB, user_db)
            ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            legacy_archived = ARCHIVE_DIR / f"exmsys_legacy_{ts}.db"
            try:
                LEGACY_DB.rename(legacy_archived)
            except Exception:
                pass
            return "migrated"
        # 空壳遗留库：删除，不允许作为迁移源
        try:
            LEGACY_DB.unlink()
        except Exception:
            pass

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


def ensure_user_db_initialized(user_id: str) -> dict:
    """兜底：若用户私有库是「从未真正被使用过」的残留空库，自动从 master 模板克隆。

    为什么需要这个函数：
      get_or_create_user 在设备指纹已映射到 user_id 时不会再次调用 _create_user_db，
      直接返回 existing。但 user_db 可能因为历史原因（早期未完成的克隆、调试残留、
      误删 questions 表等）成为空库——此时 load_questions() 返回 []，app 报"题库为空"。

    区分"残留空库"与"用户主动清空题库"的关键：
      - 主动清空（settings.py:262 的 save_questions([])）只清空 questions / answer_records
        / question_stats 等数据表，**config 表里保留了大量「曾经使用过」的 key**
        （study_per_round、spec_per_round、last_import_files 等），以及递增过的
        _questions_data_version。
      - 残留空库则从未被正常使用过：config 表里只有 _questions_data_version 一个 key
        （且值为初始 0），不存在任何已使用配置。

    Args:
        user_id: 当前用户 ID。

    Returns:
        {"initialized": bool, "reason": str, "from_questions": int, "to_questions": int}
    """
    import sqlite3
    user_db = get_user_db_path(user_id)
    if not user_db.exists():
        # 用户库文件都不存在，不在此兜底；调用方应走 get_or_create_user 重新创建
        return {"initialized": False, "reason": "user_db_missing", "from_questions": 0, "to_questions": 0}

    if not MASTER_DB.exists() or not MASTER_DB.is_file():
        # 没有模板可克隆，无法兜底
        return {"initialized": False, "reason": "master_missing", "from_questions": 0, "to_questions": 0}

    # 先读现状
    conn = sqlite3.connect(str(user_db))
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM questions")
        qcount = cur.fetchone()[0]
        # config 表 keys
        cur.execute("SELECT key FROM config")
        cfg_keys = {r[0] for r in cur.fetchall()}
        # 用户主动清空题库的标记（save_questions([]) 写入 _user_cleared_db=true）。
        # 有该标记说明是用户主动行为，绝不兜底克隆。
        cleared_flag = any(
            k == "_user_cleared_db" for k in cfg_keys
        )
        # 兼容历史：旧库可能 _user_cleared_db 已写为 false（题库非空时），
        # 此时仍按"已使用过"处理不克隆。
        cleared_value = None
        if cleared_flag:
            try:
                cleared_value = conn.execute(
                    "SELECT value FROM config WHERE key='_user_cleared_db'"
                ).fetchone()
                cleared_value = cleared_value[0] if cleared_value else None
            except Exception:
                cleared_value = None
    finally:
        conn.close()

    # 判断是否"从未真正被使用过"：题库为空且 config 中不存在任何已使用配置 key
    used_cfg_keys = {
        "study_per_round", "study_single_count", "study_multi_count", "study_judge_count",
        "spec_per_round", "spec_single_count", "spec_multi_count", "spec_judge_count",
        "comp_per_round", "comp_single_count", "comp_multi_count", "comp_judge_count",
        "exam_time_minutes", "exam_single_count", "exam_multi_count", "exam_judge_count",
        "wrongbook_extract_count", "retention_days_threshold", "last_import_files",
        "data_source",
    }
    is_residual_empty = (qcount == 0) and not (cfg_keys & used_cfg_keys)
    # 关键防御（2026-09-14 升级）：
    # 如果题库为空，**除非用户明确清空过**（_user_cleared_db=true），
    # 否则一律从 master 克隆兜底，让"题库为空"从根本消失。
    # 这样：新用户、克隆失败的残留空库、debug 误删等情况都能自动恢复。
    is_user_cleared = (qcount == 0 and cleared_value == "true")

    if not is_residual_empty and not (qcount == 0 and not is_user_cleared):
        # 题库非空，或虽然为空但已被用户主动清空过（_user_cleared_db=true）
        return {"initialized": False, "reason": "already_used_or_user_cleared",
                "from_questions": qcount, "to_questions": qcount}

    # 残留空库：从 master 模板克隆
    try:
        shutil.copy2(str(MASTER_DB), str(user_db))
    except Exception as e:
        return {"initialized": False, "reason": f"copy_failed:{e}", "from_questions": 0, "to_questions": 0}

    conn = sqlite3.connect(str(user_db))
    try:
        to_qcount = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    finally:
        conn.close()

    return {"initialized": True, "reason": "residual_empty_cloned_from_master",
            "from_questions": 0, "to_questions": to_qcount}


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

    def get_account_for_user_id(self, user_id: str) -> Optional[dict]:
        """通过 user_id 反查账号信息（用于账号面板显示）。

        账号的 bound_device 在 by_device 中以「设备指纹: 用户名」反向保存，
        我们遍历 accounts 找出 bound_device == user_id 对应 mapping 项的账号。

        Args:
            user_id: 12 位 user_id。

        Returns:
            {"username": str, "bound_device": str, "created_at": str} 或 None。
        """
        if not user_id:
            return None
        mapping = _load_json(self._mapping_file, {})
        accounts_data = _load_json(self._accounts_file, {}).get("accounts", {})
        # 找到 user_id 对应的设备指纹
        for fp, mapped_uid in mapping.items():
            if mapped_uid == user_id:
                # 再从 accounts.json 找到该指纹绑定的账号
                username_lower = accounts_data and next(
                    (u for u, a in accounts_data.items() if a.get("bound_device") == fp),
                    None,
                )
                if username_lower:
                    acct = accounts_data[username_lower]
                    return {
                        "username": acct["username"],
                        "bound_device": fp,
                        "created_at": acct.get("created_at", ""),
                    }
        return None

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

    def login_account(self, username: str, password: str,
                      device_fingerprint: str = "") -> Tuple[bool, str, Optional[str]]:
        """用户名/密码登录，成功返回 (True, msg, user_id)。

        行为升级（2026-09-14）：
        - 成功后**自动把当前设备指纹登记到该账号的 by_device**（如果还没登记）。
          解决了用户在新设备登录后下次浏览器自动识别仍落到空库的痛点。
        - 一个账号可绑定多个设备指纹（不同设备登录同一账号都会自动登记）。
        - 不会破坏原绑定设备指纹。
        """
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

        # 自动登记当前设备指纹到该账号（首次登录新设备时）
        if device_fingerprint and data.get("by_device", {}).get(device_fingerprint) != username_lower:
            data.setdefault("by_device", {})
            # 如果该设备指纹已绑别的账号，则先解绑（强制一对一映射）
            old_username = data["by_device"].get(device_fingerprint)
            data["by_device"][device_fingerprint] = username_lower
            # 同步 user_mapping.json：让 get_or_create_user 下次识别该设备直接返回该 user_id
            try:
                mp = _load_json(self._mapping_file, {})
                mp[device_fingerprint] = user_id
                _save_json(self._mapping_file, mp)
            except Exception:
                pass
            _save_json(self._accounts_file, data)
            suffix = f"（已自动将当前设备登记到该账号，原绑定：{old_username or '无'}）" if old_username else "（已自动登记当前设备）"
            return True, f"登录成功，欢迎 {acct['username']}！{suffix}", user_id

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

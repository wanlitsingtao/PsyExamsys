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
import hmac
import os
import re
import uuid
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
# 身份持久化令牌（Cookie 承载，2026-10-11）
# ============================
# 要解决的问题（2026-10-10 用户报障，两个症状同源）：
#   ① 设备指纹 = md5(User-Agent|Sec-CH-UA-Platform)[:32]。浏览器升级、客户端提示
#      (Client Hints) 策略变化、隐私模式等都会让指纹漂移 → 自动识别落到**新的匿名用户**，
#      表现为"昨天做过的题今天显示没做过""上次明明答错了却说答对"。
#   ② Streamlit 会话被回收（长时间不操作/网络断开重连）后，新会话的 session_state 是空的，
#      只能重新按指纹识别 → 回到"重新登录后的初始页"。
#
# 方案：把当前身份签成短令牌（`<user_id>.<hmac16>`）存进**浏览器 Cookie**，
# 会话重置/重连时用它恢复身份，不再依赖指纹稳定性。
#   · HMAC 签名 + 校验"该 user_id 在 users 表中真实存在"，防手工改 cookie 冒充
#     （尤其防冒充管理员 ADMIN_USER_ID）。
#   · 签名密钥首次生成后存 app_config（全局、跨设备/跨重启稳定），
#     同一份部署内签发的令牌可互认。
#
# 🩸 为什么是 Cookie 而不是 URL（v2.9.6 的教训，用户 2026-10-11 报障）：
#    令牌里含**明文 user_id**，且**签名本身就是凭证** —— 放 URL query param 等于
#    地址栏长期挂着身份凭证，转发/截图/收藏夹/浏览器历史都会把它带出去，
#    拿到该链接的人可直接以该身份进入系统。Cookie 不出现在地址栏与分享链接里，
#    也不随 User-Agent 变化（比设备指纹更稳）。
#    ⚠️ 仍要求：当前设备指纹「未登记」或「登记的正是该身份」——已绑定其他账号的
#    设备不会因为 cookie 而被换号。
# 兼容：历史上签发过的 `?u=` 令牌仍会被**读取一次**（老链接/老书签不失效），
#      恢复身份后立即把该参数从地址栏清除。

IDENTITY_TOKEN_PARAM = "u"            # 历史遗留的 URL query param（只读兼容，不再写入）
IDENTITY_COOKIE_NAME = "exmsys_uid"   # 身份令牌的 Cookie 名
_IDENTITY_COOKIE_MAX_AGE = 31536000   # Cookie 有效期 1 年
_IDENTITY_KEY_NAME = "identity_signing_key"
_identity_key_cache = None
# 令牌字符白名单：`<user_id>.<sig>`，两侧都是十六进制。用于把令牌安全拼进 JS。
_IDENTITY_TOKEN_RE = re.compile(r"^[0-9a-f]{6,64}\.[0-9a-f]{8,64}$")


def _identity_signing_key() -> Optional[str]:
    """取（或首次生成）身份签名密钥。失败返回 None → 上层降级为「不持久化身份」。"""
    global _identity_key_cache
    if _identity_key_cache:
        return _identity_key_cache
    try:
        dao = _dao()
        key = dao.get_app_config(_IDENTITY_KEY_NAME)
        if not key:
            key = hashlib.sha256(os.urandom(32)).hexdigest()
            dao.set_app_config(_IDENTITY_KEY_NAME, key)
        _identity_key_cache = key
    except Exception:
        return None
    return _identity_key_cache


def _identity_sig(user_id: str) -> Optional[str]:
    key = _identity_signing_key()
    if not key or not user_id:
        return None
    return hmac.new(key.encode("utf-8"), user_id.encode("utf-8"),
                    hashlib.sha256).hexdigest()[:16]


def sign_user_id(user_id: str) -> Optional[str]:
    """签发身份令牌 "<user_id>.<sig>"；密钥不可用时返回 None（调用方跳过持久化）"""
    sig = _identity_sig(user_id)
    return f"{user_id}.{sig}" if sig else None


def verify_user_token(token: str) -> Optional[str]:
    """校验身份令牌，通过则返回 user_id，否则 None。

    只接受「签名正确 **且** user_id 在 users 表中真实存在」的令牌。
    """
    if not token or "." not in token:
        return None
    user_id, _, sig = token.partition(".")
    if not user_id or not sig:
        return None
    expect = _identity_sig(user_id)
    if not expect or not hmac.compare_digest(sig, expect):
        return None
    try:
        if not _dao().get_user(user_id):
            return None
    except Exception:
        return None
    return user_id


def _token_cookie_pair(token: str, max_age: int = _IDENTITY_COOKIE_MAX_AGE) -> str:
    """拼出身份令牌的 document.cookie 赋值串（含 path / max-age / SameSite）。"""
    return (f"{IDENTITY_COOKIE_NAME}={token};path=/;"
            f"max-age={max_age};SameSite=Lax")


def identity_cookie_script(token: str) -> Optional[str]:
    """生成「把身份令牌写进浏览器 Cookie」的 HTML/JS 片段；令牌不合法则返回 None。

    ⚠️ 只做**白名单字符校验**后再拼接 —— 绝不把未校验内容注入脚本。
    不设 `Secure` 标志：本机 `http://localhost:8511` 与云端 `https` 都必须能写。
    """
    if not token or not _IDENTITY_TOKEN_RE.match(token):
        return None
    value = _token_cookie_pair(token)
    return f"<script>try{{document.cookie={value!r};}}catch(e){{}}</script>"


# ============================
# 身份 v2：浏览器持久化随机 ID（bid），2026-10-26
# ============================
# 要解决的问题（线上 Supabase 实证）：
#   v1 设备指纹 = md5(User-Agent|Sec-CH-UA-Platform)，而 UA 里带着浏览器大版本号，
#   浏览器自动升级 / Client Hints 策略变化都会让它漂移 → 落到**新的匿名用户**，
#   表现为"昨天做的题今天显示没做过"。
#   生产证据：主账号 ee9dad99522c 一个月内累计 **8 个不同指纹**（9-24 ~ 10-26），
#   并在 users 表留下 11 个零业务数据的空壳用户。
#
# 方案（与 bid-buddy-dev 的 IDENTITY v2 对齐 —— 2026-10-26 横向对比后采纳）：
#   身份主键改为**浏览器端持久化随机 ID**（cookie `exmsys_bid`，UUID4，2 年），
#   设备指纹 = md5("exs2|" + bid)，与 UA 彻底解耦。由此同时修掉：
#     · 漂移 —— 浏览器/系统升级不再换号
#     · 撞车 —— 不同用户必得不同 bid，不会再共用一行 users
#   ⚠️ 刻意**不动** `user_id_for()` 的派生算法：老用户的 user_id 仍是
#   md5("exmsys_device_" + v1 指纹)，该算法是老库契约，改了等于给所有人换号。
#   切换期靠「历史账号认领」（见 app.py）：首次带 bid 访问时，用本次 UA 的 v1 指纹
#   查到老 user_id，再把 v2 指纹绑到它上面 —— **老用户零迁移、数据一条不丢**。
#
# 灰度：`IDENTITY_MODE`
#   · "v1"   —— 完全回到旧行为（不读 bid），紧急回滚用
#   · "dual" —— 默认。有 bid 用 v2 指纹；无 bid 本次仍按 v1 指纹跑完（保证老用户本次
#               不丢数据），同时写入 bid，下次访问即切到 v2 并认领历史账号

IDENTITY_BID_COOKIE_NAME = "exmsys_bid"
_IDENTITY_BID_MAX_AGE = 63072000  # 2 年（秒）
_BID_RE = re.compile(r"^[0-9a-f]{32}$")
_V2_FP_PREFIX = "exs2|"

IDENTITY_MODE = "v1"      # "dual" | "v1"
IDENTITY_MODE_V1 = "v1"


def new_bid() -> str:
    """生成浏览器持久化 ID（32 位小写 hex，即 UUID4 去掉连字符）。"""
    return uuid.uuid4().hex


def is_valid_bid(value) -> bool:
    """bid 白名单校验：32 位**小写**十六进制。**先校验再拼进 JS**，防 cookie 注入。

    ⚠️ 刻意**不**做 lower() 宽容处理：与令牌的 `_IDENTITY_TOKEN_RE` 同一标准。
    万一浏览器把 cookie 值变了大小写，宁可当作「没有 bid」（回落本次 UA 指纹），
    也不能让 `fingerprint_from_bid` 算出另一个指纹 → 那才是真的换号。
    """
    return isinstance(value, str) and bool(_BID_RE.match(value))


def fingerprint_from_bid(bid: str) -> str:
    """v2 指纹：md5("exs2|" + bid)。与 User-Agent 完全解耦，浏览器升级也不变。"""
    return hashlib.md5((_V2_FP_PREFIX + (bid or "")).encode("utf-8")).hexdigest()[:32]


def _bid_cookie_pair(value: str, max_age: int = _IDENTITY_BID_MAX_AGE) -> str:
    """拼出 bid 的 document.cookie 赋值串。不设 Secure：本机 http 与云端 https 都要能写。"""
    return (f"{IDENTITY_BID_COOKIE_NAME}={value};path=/;"
            f"max-age={max_age};SameSite=Lax")


def identity_bid_script(bid: str, max_age: int = _IDENTITY_BID_MAX_AGE) -> Optional[str]:
    """生成「把 bid 写进浏览器 Cookie」的 HTML/JS 片段；bid 不合法则返回 None。"""
    if not is_valid_bid(bid):
        return None
    value = _bid_cookie_pair(bid, max_age)
    return f"<script>try{{document.cookie={value!r};}}catch(e){{}}</script>"


def identity_cookies_script(token: str = None, bid: str = None) -> Optional[str]:
    """把「身份令牌 + bid」合成**一个** <script>：一次组件渲染即可，不多一个 iframe。

    ⚠️ 两个值都要先过白名单才拼接 —— 绝不把未校验内容注入脚本。
    """
    assigns = []
    if token and _IDENTITY_TOKEN_RE.match(token):
        assigns.append(f"document.cookie={_token_cookie_pair(token)!r};")
    if bid and _BID_RE.match(bid):
        assigns.append(f"document.cookie={_bid_cookie_pair(bid)!r};")
    if not assigns:
        return None
    body = "".join(assigns)
    return f"<script>try{{{body}}}catch(e){{}}</script>"


def device_bound_user_id(device_fingerprint: str) -> Optional[str]:
    """当前设备指纹已登记的 user_id（未登记返回 None）。**只读，不建号不绑定。**

    ⚠️ 必须把空值归一为 None：DAO 的 get_device_user 未命中时返回的是**空字符串**，
    直接拿去判断 `is None` 会恒为 False（2026-10-11 踩坑：导致凭令牌恢复身份的分支永不进入）。
    """
    if not device_fingerprint:
        return None
    try:
        return _dao().get_device_user(device_fingerprint) or None
    except Exception:
        return None


def claim_legacy_identity(v2_fingerprint: str, raw_ua: str) -> Optional[str]:
    """身份 v2 切换期的「历史账号认领」：把 v2 指纹挂到老 user_id 上。

    为什么必须有这一步：
        老用户的 user_id = md5("exmsys_device_" + v1 指纹)，而 `user_id_for()` 是
        **老库契约、不能改**。切到 v2 后设备指纹变成 md5("exs2|" + bid)，
        若直接拿它去建号，就会派生出一个全新的 user_id → 老数据全部失联。
        所以首次带着 bid 访问时，先用本次 UA 的 v1 指纹查出老 user_id，
        再把 v2 指纹绑到它上面 —— **老用户零迁移、数据一条不丢**。

    「恰好一次」怎么保证：绑上之后 v2 指纹即为「已登记」，
    下次进来本函数在第一步就直接返回 None，不会重复绑、也不会改绑。

    Returns:
        认领到的 user_id；没有可认领的老账号（新访客 / UA 取不到）则返回 None。
    """
    if not v2_fingerprint or not raw_ua:
        return None
    if device_bound_user_id(v2_fingerprint):
        return None                                  # v2 指纹已登记 → 无需认领
    legacy_uid = device_bound_user_id(generate_device_fingerprint(raw_ua))
    if not legacy_uid:
        return None                                  # 新访客 → 交给调用方按指纹建号
    bind_device_if_absent(v2_fingerprint, legacy_uid)
    return legacy_uid


def bind_device_if_absent(device_fingerprint: str, user_id: str) -> bool:
    """把设备指纹登记到指定身份，**仅在未登记时**。

    用于「凭令牌恢复身份」后顺手补登记：新设备 / 浏览器升级导致指纹漂移时，
    下次即使没有令牌（从收藏夹打开、手动输入域名）也能落到同一身份。
    已登记到别的账号时**保持不动** —— 避免点击别人的链接就把自己的设备改绑。
    """
    if not device_fingerprint or not user_id:
        return False
    try:
        dao = _dao()
        if dao.get_device_user(device_fingerprint):
            return False
        dao.bind_device(device_fingerprint, user_id)
        return True
    except Exception:
        return False


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

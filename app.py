"""
心理咨询师考试背题系统 - 主入口
本地 C/S 版 (Streamlit 单机应用)
"""
import streamlit as st
import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 仅首次加载时调用 set_page_config，避免每次 st.rerun() 触发 tab 标题闪烁
if "_app_initialized" not in st.session_state:
    st.set_page_config(
        page_title="心理咨询师考试背题系统",
        page_icon="📚",
        layout="centered",
        initial_sidebar_state="expanded",
    )
    st.session_state._app_initialized = True

# 将主内容区域做成“自适应 70% + 最大宽度上限”的布局，
# 这样在浏览器 100% 下也能保持比较舒适的阅读体验
CONTENT_WIDTH_RATIO = 0.72
MAX_CONTENT_WIDTH_PX = 1280
st.markdown(f"""
<style>
    .block-container {{
        max-width: min({MAX_CONTENT_WIDTH_PX}px, {CONTENT_WIDTH_RATIO * 100:.0f}vw) !important;
        width: min(100%, {MAX_CONTENT_WIDTH_PX}px);
        margin: 0 auto;
        padding-left: clamp(0.75rem, 2vw, 1.25rem);
        padding-right: clamp(0.75rem, 2vw, 1.25rem);
    }}
    /* ============ 侧边栏整体布局（适配 Streamlit 1.57 DOM） ============ */
    /* 说明：不再强制 width，保留原生 300px 默认 + 拖拽记忆（localStorage sidebarWidth） */
    /* 说明：全局根字号 18px 会把 Streamlit 内部 rem 间距放大（1rem=18px），
       此处用固定 px 收紧头部/留白，避免顶部空隙与底部死区 */
    /* 头部：固定高度收起（默认 3.75rem 被 18px 根字号放大到 67.5px），去掉下方 1rem 空隙 */
    section[data-testid="stSidebar"][aria-expanded="true"] [data-testid="stSidebarHeader"] {{
        height: 46px !important;
        min-height: 46px !important;
        max-height: 46px !important;
        padding: 0 0.5rem !important;
        margin-bottom: 0 !important;
        align-items: center !important;
    }}
    /* 折叠按钮自身不再占用上下大 margin */
    section[data-testid="stSidebar"][aria-expanded="true"] [data-testid="stSidebarCollapseButton"] {{
        margin: 0 !important;
    }}
    /* 无 st.logo 时隐藏占位块，标题区更紧凑 */
    [data-testid="stLogoSpacer"] {{ display: none !important; }}
    /* header 固定顶部；stSidebarUserContent 单独滚动（内容超高不裁底、不滚动走头部） */
    [data-testid="stSidebarContent"] {{
        display: flex !important;
        flex-direction: column !important;
        overflow: hidden !important;
    }}
    [data-testid="stSidebarUserContent"] {{
        flex: 1 1 auto !important;
        min-height: 0 !important;
        display: flex !important;
        flex-direction: column !important;
        overflow-y: auto !important;
        overflow-x: hidden !important;
        scrollbar-width: thin !important;
        /* 原默认 padding-bottom 6rem(=108px) 是底部死区，收紧 */
        padding-bottom: 0.75rem !important;
    }}
    /* 1.57 实际结构：uc > 匿名div(st-emotion) > stVerticalBlock > 顶层元素
       逐层改为纵向 flex 并撑满高度，供最后一个块（账号容器）吸底 */
    [data-testid="stSidebarUserContent"] > div {{
        flex: 1 1 auto !important;
        min-height: 0 !important;
        display: flex !important;
        flex-direction: column !important;
    }}
    [data-testid="stSidebarUserContent"] > div > div[data-testid="stVerticalBlock"] {{
        flex: 1 1 auto !important;
        min-height: 0 !important;
        display: flex !important;
        flex-direction: column !important;
    }}
    /* 顶层元素不允许纵向压缩：空间不足时应滚动而非挤压内容 */
    [data-testid="stSidebarUserContent"] > div > div[data-testid="stVerticalBlock"] > * {{
        flex-shrink: 0 !important;
    }}
    /* 账号容器（顶层最后一个块）吸底：空间足够贴底，不足时随内容滚动
       overflow:hidden 用于裁掉「折叠 expander 隐藏内容」造成的幽灵滚动溢出（约5px） */
    [data-testid="stSidebarUserContent"] > div > div[data-testid="stVerticalBlock"] > :last-child {{
        margin-top: auto !important;
        overflow: hidden !important;
    }}
    /* 账号信息卡片 */
    .sx-user-card {{
        border: 1px solid rgba(148, 163, 184, 0.4) !important;
        border-radius: 0.7rem !important;
        padding: 0.5rem 0.75rem !important;
        background: linear-gradient(180deg, #f8fafc, #f1f5f9) !important;
        margin: 0.1rem 0 0.35rem !important;
        line-height: 1.5 !important;
    }}
    /* 侧边栏内导航 radio 紧凑化 */
    [data-testid="stSidebarUserContent"] div[data-testid="stRadio"] label {{
        padding: 0.18rem 0.2rem !important;
    }}
    /* 侧边栏标题紧凑：单行不换行（默认 H2 在 300px 宽下会折两行） */
    [data-testid="stSidebarUserContent"] h2 {{
        font-size: 0.95rem !important;
        line-height: 1.3 !important;
        margin: 0.1rem 0 0.3rem !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }}
    /* 侧边栏内 hr 缩小间距 */
    [data-testid="stSidebarUserContent"] hr {{
        margin: 0.35rem 0 !important;
    }}
    /* 侧边栏 selectbox/selectboxLabel 紧凑 */
    [data-testid="stSidebarUserContent"] .stSelectbox {{
        margin-bottom: 0.1rem !important;
    }}
    [data-testid="stSidebarUserContent"] [data-testid="stWidgetLabel"] {{
        font-size: 0.92rem !important;
        margin-bottom: 0.15rem !important;
    }}

    /* 统一按钮间距与圆角 */
    div[data-testid="stButton"] button {{
        border-radius: 0.7rem !important;
        padding: 0.45rem 0.9rem !important;
        margin: 0.15rem 0 !important;
    }}

    /* 统一标题、正文、选项、答案区的排版 */
    h1, h2, h3, h4, h5, h6 {{
        line-height: 1.25 !important;
        margin-top: 0.25rem !important;
        margin-bottom: 0.45rem !important;
        letter-spacing: 0.01em !important;
    }}
    p, li, .stMarkdown {{
        line-height: 1.6 !important;
        font-size: 1rem !important;
    }}
    .stTextInput > div > div > input,
    .stTextArea > div > textarea,
    .stSelectbox > div > div {{
        font-size: 0.98rem !important;
    }}
    .stRadio > label,
    .stCheckbox > label,
    .stSelectbox label,
    .stTextInput label,
    .stTextArea label {{
        font-size: 0.98rem !important;
        line-height: 1.5 !important;
    }}
    .stAlert, .stSuccess, .stWarning, .stError, .stInfo {{
        font-size: 0.96rem !important;
        line-height: 1.55 !important;
    }}

    /* 题目选项区更清晰 */
    div[data-testid="stRadio"] label,
    div[data-testid="stCheckbox"] label {{
        font-size: 1rem !important;
        line-height: 1.6 !important;
        padding: 0.2rem 0 !important;
    }}

    /* 答案区强调 */
    .answer-highlight {{
        background: #f1f8e9 !important;
        border-left: 4px solid #2e7d32 !important;
        border-radius: 0.6rem !important;
        padding: 0.75rem 0.9rem !important;
        margin: 0.35rem 0 0.6rem !important;
        line-height: 1.6 !important;
    }}

    /* 统一卡片/容器间距 */
    div[data-testid="stVerticalBlockBorderWrapper"] {{
        border-radius: 0.8rem !important;
        padding: 0.8rem 0.95rem !important;
        margin-bottom: 0.6rem !important;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06) !important;
    }}

    /* 让垂直/水平块之间的间距更自然 */
    div[data-testid="stVerticalBlock"] {{
        gap: 0.35rem !important;
    }}
    div[data-testid="stHorizontalBlock"] {{
        gap: 0.35rem !important;
    }}

    /* 表格更好看 */
    div[data-testid="stDataFrame"] {{
        border-radius: 0.7rem !important;
        overflow: hidden !important;
        border: 1px solid rgba(0, 0, 0, 0.08) !important;
    }}
    div[data-testid="stDataFrame"] .dataframe {{
        font-size: 0.95rem !important;
    }}

    /* 题目区域更像考试系统界面 */
    .question-card {{
        background: linear-gradient(180deg, #ffffff 0%, #fafcff 100%) !important;
        border: 1px solid #e5eaf2 !important;
        border-left: 4px solid #2563eb !important;
        border-radius: 0.95rem !important;
        padding: 1rem 1.1rem !important;
        margin: 0.6rem 0 0.9rem !important;
        box-shadow: 0 2px 8px rgba(37, 99, 235, 0.06) !important;
    }}
    .question-title {{
        font-size: 1.08rem !important;
        font-weight: 700 !important;
        color: #172033 !important;
        line-height: 1.6 !important;
        margin-bottom: 0.45rem !important;
    }}
    .question-meta {{
        display: inline-block !important;
        background: #eef4ff !important;
        color: #2453c5 !important;
        border-radius: 999px !important;
        padding: 0.22rem 0.65rem !important;
        font-size: 0.9rem !important;
        font-weight: 600 !important;
        margin-bottom: 0.6rem !important;
    }}
    .option-item {{
        border: 1px solid #e7ebf0 !important;
        border-radius: 0.7rem !important;
        padding: 0.6rem 0.75rem !important;
        margin: 0.35rem 0 !important;
        background: #ffffff !important;
        transition: all 0.2s ease !important;
    }}
    .option-item:hover {{
        border-color: #93b9ff !important;
        box-shadow: 0 1px 4px rgba(37, 99, 235, 0.08) !important;
    }}
    .answer-box {{
        background: #f6fbf3 !important;
        border: 1px solid #d9ebd3 !important;
        border-left: 4px solid #2f8f3f !important;
        border-radius: 0.8rem !important;
        padding: 0.8rem 0.95rem !important;
        margin-top: 0.7rem !important;
        line-height: 1.6 !important;
    }}

    .question-index {{
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        min-width: 3.2rem !important;
        height: 3.2rem !important;
        border-radius: 50% !important;
        background: linear-gradient(135deg, #2563eb, #3b82f6) !important;
        color: #ffffff !important;
        font-weight: 700 !important;
        box-shadow: 0 4px 12px rgba(37, 99, 235, 0.18) !important;
        margin-right: 0.9rem !important;
        font-size: 1rem !important;
    }}

    .question-meta-tag {{
        font-size: 0.9rem !important;
        font-weight: 600 !important;
        color: #ffffff !important;
        background: #1d4ed8 !important;
        border-radius: 999px !important;
        padding: 0.28rem 0.65rem !important;
        margin-left: 0.5rem !important;
    }}

    .question-nav-bar {{
        display: flex !important;
        gap: 0.7rem !important;
        align-items: center !important;
        justify-content: space-between !important;
        margin: 1rem 0 0.7rem !important;
        padding: 0.85rem 0.95rem !important;
        border-radius: 0.85rem !important;
        background: #f8fafc !important;
        border: 1px solid rgba(148, 163, 184, 0.25) !important;
    }}

    .question-nav-button {{
        border-radius: 0.85rem !important;
        padding: 0.68rem 1rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.01em !important;
        transition: transform 0.15s ease, box-shadow 0.15s ease !important;
    }}
    .question-nav-button:hover {{
        transform: translateY(-1px) !important;
        box-shadow: 0 6px 18px rgba(37, 99, 235, 0.14) !important;
    }}

    .question-status-chip {{
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        border-radius: 999px !important;
        padding: 0.25rem 0.7rem !important;
        font-size: 0.88rem !important;
        font-weight: 700 !important;
    }}

    .status-correct {{
        background: #dcfce7 !important;
        color: #166534 !important;
        border: 1px solid #86efac !important;
    }}
    .status-wrong {{
        background: #fee2e2 !important;
        color: #991b1b !important;
        border: 1px solid #fecaca !important;
    }}
    .status-unanswered {{
        background: #e2e8f0 !important;
        color: #1e293b !important;
        border: 1px solid #cbd5e1 !important;
    }}

    /* 答题卡导航按钮高亮 */
    .question-card + .question-nav-bar {{
        margin-top: 0.9rem !important;
    }}
    .question-card {{
        margin-bottom: 1rem !important;
    }}

    div.stButton > button {{
        border-radius: 0.85rem !important;
        padding: 0.75rem 1rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.01em !important;
        transition: transform 0.16s ease, box-shadow 0.16s ease, background 0.16s ease !important;
    }}
    div.stButton > button:hover {{
        transform: translateY(-1px) !important;
        box-shadow: 0 6px 18px rgba(37, 99, 235, 0.14) !important;
    }}
    div.stButton > button:disabled {{
        opacity: 0.65 !important;
        cursor: not-allowed !important;
    }}

    div.stButton > button[type="primary"] {{
        background: linear-gradient(135deg, #2563eb, #3b82f6) !important;
        color: #ffffff !important;
        border-color: transparent !important;
        box-shadow: 0 8px 20px rgba(37, 99, 235, 0.18) !important;
    }}
    div.stButton > button[type="secondary"] {{
        background: #f8fafc !important;
        color: #0f172a !important;
        border: 1px solid rgba(148, 163, 184, 0.35) !important;
    }}
    div.stButton > button[type="secondary"]:hover {{
        background: #eff6ff !important;
    }}

    .question-nav-bar button {{
        border-radius: 0.85rem !important;
    }}

    @media (max-width: 1200px) {{
        .block-container {{
            max-width: 92vw !important;
            width: 92vw;
        }}
    }}
    @media (max-width: 900px) {{
        .block-container {{
            max-width: 100% !important;
            width: 100%;
            padding-left: 0.5rem;
            padding-right: 0.5rem;
        }}
        /* 窄屏抽屉：仅展开态占满全宽；折叠态保持原生窄轨（1.57 中 stSidebar 为 <section>） */
        section[data-testid="stSidebar"][aria-expanded="true"] {{
            width: 100% !important;
            min-width: 100% !important;
            max-width: 100% !important;
        }}
    }}
    /* 隐藏 Streamlit 默认多页面导航（放首块 CSS 尽早生效，配合 config.toml 双重保险） */
    [data-testid="stSidebarNav"] {{ display: none !important; }}
    [data-testid="stSidebarNavItems"] {{ display: none !important; }}
    [data-testid="stSidebarNavSeparator"] {{ display: none !important; }}
</style>
""", unsafe_allow_html=True)

# 初始化 session_state
from utils.data_manager import load_config, load_questions, get_available_exam_types, DEFAULT_EXAM_TYPE, invalidate_rerun_cache, get_questions_version, set_current_user
from utils.account_manager import generate_device_fingerprint, get_or_create_user

# 每次 rerun 开始时清除数据缓存，确保使用最新数据
invalidate_rerun_cache()

# ============================
# 多用户身份识别（设备指纹 → 用户私有题库）
# 首次访问：自动生成指纹 → 创建用户 → 克隆初始化题库模板
# 再次访问：同一浏览器指纹不变 → 自动识别同一用户（稳定绑定）
# ============================

def _resolve_current_user():
    """解析设备指纹并绑定/创建当前用户。每个用户拥有独立题库库文件。"""
    if "_user_id" in st.session_state:
        return
    try:
        headers = st.context.headers
        ua = headers.get("User-Agent", "") or ""
        platform = (headers.get("Sec-CH-UA-Platform", "")
                    or headers.get("sec-ch-ua-platform", "") or "")
    except Exception:
        ua, platform = "", ""
    raw_ua = f"{ua}|{platform}".strip("|")
    fingerprint = generate_device_fingerprint(raw_ua)
    user = get_or_create_user(fingerprint, raw_ua)
    st.session_state._user_id = user["user_id"]
    st.session_state._device_fp = fingerprint
    set_current_user(user["user_id"])
    # 首次进入/切换用户：强制重载该用户自己的题库与配置
    for key in ["questions", "config", "_cache_available_exams",
                "_db_questions_version", "_data_version", "_mnemonic_data"]:
        st.session_state.pop(key, None)


_resolve_current_user()

# 检测题库数据版本号是否变更（仅在 save_questions 导入/替换题库时递增），
# 答题过程中的自动保存、统计更新等不会触发，避免页面答题中途被刷出
_db_version = get_questions_version()
if "_db_questions_version" not in st.session_state or st.session_state._db_questions_version != _db_version:
    st.session_state._db_questions_version = _db_version
    # 题库版本号变了，才是真正需要刷新题库缓存
    for key in ["questions", "_cache_available_exams"]:
        st.session_state.pop(key, None)

if "config" not in st.session_state:
    st.session_state.config = load_config()
if "exam_type" not in st.session_state:
    # 检测可用题库，默认选第一个
    available = get_available_exam_types()
    if available:
        st.session_state.exam_type = available[0][0]  # 使用短码
    else:
        st.session_state.exam_type = DEFAULT_EXAM_TYPE
if "questions" not in st.session_state:
    st.session_state.questions = load_questions()
if "_data_version" not in st.session_state:
    st.session_state._data_version = 0


# ============================
# 题库切换辅助（考试进行中确认 + 状态重置）
# ============================

# 模拟考试"进行中"的状态值（对应 MOCK_EXAM_CONFIG 的科目 key）
_MOCK_ACTIVE_STATES = ("psychology", "counseling", "junior_psychology")
_MOCK_SUBJECT_LABELS = {
    "psychology": "心理学综合",
    "counseling": "咨询实务",
    "junior_psychology": "心理学综合",
}


def _get_active_exam_sessions():
    """检测进行中的模拟考试/专项训练，返回 [(类型, 描述)] 列表"""
    active = []
    mock_state = st.session_state.get("mock_state", "idle")
    if mock_state in _MOCK_ACTIVE_STATES:
        active.append(("mock", f"模拟考试（{_MOCK_SUBJECT_LABELS.get(mock_state, mock_state)}）"))
    if st.session_state.get("spec_state") == "running":
        mode = st.session_state.get("spec_mode", "specialized")
        if mode == "comprehensive":
            active.append(("spec", "综合训练"))
        else:
            active.append(("spec", f"专项训练（{st.session_state.get('spec_category', '')}）"))
    return active


def _save_active_exam_drafts():
    """将进行中的模拟考试/专项训练进度静默保存为草稿"""
    mock_state = st.session_state.get("mock_state", "idle")
    if mock_state in _MOCK_ACTIVE_STATES:
        from pages.mock_exam import _save_mock_draft
        subject_key = st.session_state.get("mock_subject", mock_state)
        _save_mock_draft(subject_key, auto_save=True)
    if st.session_state.get("spec_state") == "running":
        from pages.specialized import _save_spec_draft
        _save_spec_draft(auto_save=True)


def _reset_exam_states_for_switch():
    """题库切换时彻底清理模拟考试/专项训练的全部会话状态"""
    for k in [k for k in list(st.session_state) if k.startswith("mock_")]:
        del st.session_state[k]
    st.session_state.mock_state = "idle"
    for k in [k for k in list(st.session_state) if k.startswith("spec_")]:
        del st.session_state[k]
    st.session_state.spec_state = "idle"


def _perform_exam_switch(new_code):
    """执行题库切换：更新 exam_type、清缓存、重置考试状态、导航回首页"""
    st.session_state.exam_type = new_code
    # 清除旧数据缓存，强制重新加载（含助记助学缓存，保证按新题库生成）
    for key in ["questions", "wb_questions", "wb_wrong_counts", "wb_answers",
                "wb_submitted", "wb_results", "wb_mode", "wa_selected_idx",
                "_cache_available_exams", "_mnemonic_data"]:
        st.session_state.pop(key, None)
    _reset_exam_states_for_switch()
    # 导航焦点切回首页（问题1修复：切换后主页面显示首页，导航焦点也应在首页）
    st.session_state.nav = "🏠 首页"
    st.rerun()


def _switch_user(new_user_id):
    """账号登录/切换用户：重置当前用户库与全部会话缓存"""
    set_current_user(new_user_id)
    st.session_state._user_id = new_user_id
    for key in ["questions", "config", "_cache_available_exams",
                "_db_questions_version", "_data_version", "_mnemonic_data",
                "_cache_wrong_stats"]:
        st.session_state.pop(key, None)
    _reset_exam_states_for_switch()
    st.session_state.nav = "🏠 首页"
    st.rerun()


@st.dialog("⚠️ 考试正在进行中")
def _exam_switch_confirm_dialog(active_sessions, new_code, new_label):
    """考试进行中切换题库的确认弹窗"""
    descs = "、".join(desc for _, desc in active_sessions)
    st.markdown(f"当前有进行中的 **{descs}**（题库：{st.session_state.exam_type}）。")
    st.markdown(f"是否切换到 **{new_label}** 并保存当前考试进度？")
    st.caption("选「是」：自动保存考试进度（之后可在原题库的「未完成的考试/训练」列表中继续作答）并切换题库；"
               "选「否」：不切换，继续当前考试。")
    col_yes, col_no = st.columns(2)
    if col_yes.button("✅ 是，保存进度并切换", type="primary", use_container_width=True):
        _save_active_exam_drafts()
        _perform_exam_switch(new_code)
    if col_no.button("❌ 否，继续当前考试", use_container_width=True):
        st.rerun()


# ============================
# 侧边栏导航（自定义，不使用 Streamlit 默认多页面标签）
# ============================

st.sidebar.markdown("## 📚 心理咨询师考试背题系统")
st.sidebar.markdown("---")

if len(st.session_state.questions) == 0:
    st.sidebar.warning("⚠️ 题库为空，请先在配置管理中导入题库")

# 题库选择器（缓存 available_exams，仅在导入题目后刷新）
if "_cache_available_exams" not in st.session_state:
    st.session_state._cache_available_exams = get_available_exam_types()
available_exams = st.session_state._cache_available_exams
if available_exams:
    # 构建标签列表用于显示
    exam_labels = [label for _, label in available_exams]
    exam_codes = [code for code, _ in available_exams]
    current_idx = 0
    if st.session_state.exam_type in exam_codes:
        current_idx = exam_codes.index(st.session_state.exam_type)

    # 注意：不绑定 widget key。用户在确认弹窗中选「否」不切换后，
    # 下一轮 rerun 时选择框会自动回退显示当前题库（index=current_idx），
    # 避免选择框显示与新题库不一致的问题。
    selected_label = st.sidebar.selectbox(
        "📂 题库选择",
        exam_labels,
        index=current_idx,
    )
    selected_code = exam_codes[exam_labels.index(selected_label)]
    if selected_code != st.session_state.exam_type:
        active_sessions = _get_active_exam_sessions()
        if active_sessions:
            # 考试/训练进行中：弹窗确认是否保存进度并切换题库；
            # 用户未确认前不修改 exam_type，页面继续渲染当前题库的考试页面
            _exam_switch_confirm_dialog(active_sessions, selected_code, selected_label)
        else:
            _perform_exam_switch(selected_code)

# 根据当前 exam_type 过滤题目
all_qs = st.session_state.questions if st.session_state.questions else load_questions()
st.session_state.questions = [q for q in all_qs if q.get("exam_type") == st.session_state.exam_type]
st.sidebar.markdown("---")

# 导航菜单
menu_items = {
    "首页": "🏠",
    "专项训练": "🎯",
    "模拟考试": "📝",
    "巩固练习": "🔁",
    "错题本": "📕",
    "助记助学": "🧠",
    "配置管理": "⚙️",
}

# 检测错题本是否有角标（缓存，仅在数据版本变化时重新加载）
from utils.data_manager import get_wrong_stats
_cache_key = f"_cache_wrong_stats_{st.session_state.exam_type}"
_vkey = f"_cache_wrong_stats_v_{st.session_state.exam_type}"
_cur = st.session_state.get("_data_version", 0)
if _cur != st.session_state.get(_vkey, -1) or _cache_key not in st.session_state:
    st.session_state[_cache_key] = get_wrong_stats(st.session_state.exam_type)
    st.session_state[_vkey] = _cur
wrong_stats = st.session_state[_cache_key]
wrong_badge = f" ({wrong_stats['total']})" if wrong_stats['total'] > 0 else ""

nav_labels = []
nav_keys = []
for key, icon in menu_items.items():
    if key == "错题本":
        nav_labels.append(f"{icon} {key}{wrong_badge}")
    else:
        nav_labels.append(f"{icon} {key}")
    nav_keys.append(key)

# 支持从按钮跳转（快速入口）
nav_key_from_button = st.session_state.pop("nav_to", None)
nav_default_index = 0
if nav_key_from_button:
    for i, k in enumerate(nav_keys):
        if k == nav_key_from_button:
            nav_default_index = i
            break

selected = st.sidebar.radio("导航", nav_labels, key="nav", index=nav_default_index)

# 映射回 key
selected_key = nav_keys[nav_labels.index(selected)]

st.sidebar.markdown("---")

# ---- 账号面板（置于导航之后；CSS 让整个容器吸底显示）----
# 统一放入 st.container()：便于整组贴底 + 后续整体美化
with st.sidebar.container():
    from utils.account_manager import AccountManager
    _acct_mgr = AccountManager()
    _bound_acct = _acct_mgr.get_bound_account(st.session_state._device_fp)
    _user_short = st.session_state._user_id
    if _bound_acct:
        st.markdown(
            f"<div class='sx-user-card'>"
            f"<div style='font-weight:600;'>👤 {_bound_acct['username']}</div>"
            f"<div style='font-size:0.78rem;color:#7a8aa5;'>ID {_user_short} · 已绑定，可跨设备同步</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        if st.button("🔓 解绑账号", key="unbind_btn", use_container_width=True):
            _acct_mgr.unbind_account(st.session_state._device_fp)
            st.rerun()
    else:
        st.markdown(
            f"<div class='sx-user-card'>"
            f"<div style='font-weight:600;'>👤 访客 {_user_short}</div>"
            f"<div style='font-size:0.78rem;color:#7a8aa5;'>本机临时账号 · 可绑定后跨设备同步</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        with st.expander("🔑 绑定 / 登录账号", expanded=False):
            bind_tab, login_tab = st.tabs(["绑定账号", "登录账号"])
            with bind_tab:
                _b_user = st.text_input("用户名", key="bind_username")
                _b_pwd = st.text_input("密码", type="password", key="bind_password")
                if st.button("绑定", key="bind_btn", use_container_width=True):
                    _ok, _msg = _acct_mgr.bind_account(
                        st.session_state._device_fp, _b_user, _b_pwd)
                    if _ok:
                        st.success(_msg)
                        st.rerun()
                    else:
                        st.error(_msg)
            with login_tab:
                _l_user = st.text_input("用户名", key="login_username")
                _l_pwd = st.text_input("密码", type="password", key="login_password")
                if st.button("登录", key="login_btn", use_container_width=True):
                    _ok, _msg, _uid = _acct_mgr.login_account(_l_user, _l_pwd)
                    if _ok and _uid:
                        st.success(_msg)
                        _switch_user(_uid)
                    else:
                        st.error(_msg)
    st.caption("心理咨询师考试背题系统 v2.0")

# ============================
# 页面路由（隐藏 Streamlit 默认的 pages/ 标签）
# ============================

# 隐藏 Streamlit 默认的多页面导航标签（每次 rerun 都需注入，CSS本身不会导致闪烁）
st.markdown("""
<style>
/* 全局：基础字号从16px提升为18px */
html { font-size: 18px; }
/* Streamlit 内置14px字号元素 → 16px（tab标签、caption等） */
button[data-baseweb="tab"], .stTabs [data-baseweb="tab"] p,
div[data-testid="stTabs"] button[role="tab"],
.st-emotion-cache-16idsys p {
    font-size: 16px !important;
}
/* 隐藏 Streamlit 默认的多页面导航 —— 覆盖 1.42+ 多个版本的选择器 */
[data-testid="stSidebarNav"] { display: none !important; }
[data-testid="stSidebarNavItems"] { display: none !important; }
[data-testid="stSidebarNavSeparator"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

if selected_key == "首页":
    from pages.statistics import show_statistics
    show_statistics()
elif selected_key == "专项训练":
    from pages.specialized import show_specialized
    show_specialized()
elif selected_key == "模拟考试":
    from pages.mock_exam import show_mock_exam
    show_mock_exam()
elif selected_key == "巩固练习":
    from pages.consolidation import show_consolidation
    show_consolidation()
elif selected_key == "错题本":
    from pages.wrongbook import show_wrongbook
    show_wrongbook()
elif selected_key == "助记助学":
    from pages.mnemonic import show_mnemonic
    show_mnemonic()
elif selected_key == "配置管理":
    from pages.settings import show_settings
    show_settings()

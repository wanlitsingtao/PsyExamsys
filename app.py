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
    div[data-testid="stSidebar"] {{
        width: 20rem !important;
        min-width: 20rem !important;
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
        div[data-testid="stSidebar"] {{
            width: 18rem !important;
            min-width: 18rem !important;
        }}
    }}
    @media (max-width: 900px) {{
        .block-container {{
            max-width: 100% !important;
            width: 100%;
            padding-left: 0.5rem;
            padding-right: 0.5rem;
        }}
        div[data-testid="stSidebar"] {{
            width: 100% !important;
            min-width: 100% !important;
        }}
    }}
</style>
""", unsafe_allow_html=True)

# 初始化 session_state
from utils.data_manager import load_config, load_questions, get_available_exam_types, DEFAULT_EXAM_TYPE, invalidate_rerun_cache

# 每次 rerun 开始时清除数据缓存，确保使用最新数据
invalidate_rerun_cache()

# 检测数据库文件是否被外部更新（如导入脚本、其他进程写入），自动刷新题目缓存
_DB_PATH = Path(__file__).resolve().parent / "data" / "exmsys.db"
_current_db_mtime = _DB_PATH.stat().st_mtime if _DB_PATH.exists() else 0
if "_db_last_modified" not in st.session_state or st.session_state._db_last_modified != _current_db_mtime:
    st.session_state._db_last_modified = _current_db_mtime
    # 清除旧缓存，强制重新加载题库和可用题库列表
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

    selected_label = st.sidebar.selectbox(
        "📂 题库选择",
        exam_labels,
        index=current_idx,
        key="exam_selector"
    )
    selected_code = exam_codes[exam_labels.index(selected_label)]
    if selected_code != st.session_state.exam_type:
        st.session_state.exam_type = selected_code
        # 清除旧数据缓存，强制重新加载
        for key in ["questions", "wb_questions", "wb_wrong_counts", "wb_answers",
                     "wb_submitted", "wb_results", "wb_mode", "wa_selected_idx",
                     "_cache_available_exams"]:
            st.session_state.pop(key, None)
        st.rerun()

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
st.sidebar.caption("心理咨询师考试背题系统 v2.0")

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

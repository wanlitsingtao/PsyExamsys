"""
心理咨询师考试背题系统 - 主入口
本地 C/S 版 (Streamlit 单机应用)
"""
import streamlit as st
import sys
from pathlib import Path

# 将项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

st.set_page_config(
#    page_title="心理咨询师考试背题系统",
    page_icon="📚",
    layout="centered",
    initial_sidebar_state="expanded",
)

# 初始化 session_state
from utils.data_manager import load_config, load_questions, get_available_exam_types, DEFAULT_EXAM_TYPE

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

# ============================
# 侧边栏导航（自定义，不使用 Streamlit 默认多页面标签）
# ============================

#st.sidebar.markdown("## 📚 心理咨询师考试背题系统")
st.sidebar.markdown("---")

if len(st.session_state.questions) == 0:
    st.sidebar.warning("⚠️ 题库为空，请先在配置管理中导入题库")

# 题库选择器
available_exams = get_available_exam_types()
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
                     "wb_submitted", "wb_results", "wb_mode", "wa_selected_idx"]:
            st.session_state.pop(key, None)
        st.rerun()

# 根据当前 exam_type 过滤题目
all_qs = st.session_state.questions if st.session_state.questions else load_questions()
st.session_state.questions = [q for q in all_qs if q.get("exam_type") == st.session_state.exam_type]
st.sidebar.markdown("---")

# 导航菜单
menu_items = {
    "专项训练": "🎯",
    "模拟考试": "📝",
    "错题本": "📕",
    "数据统计": "📊",
    "配置管理": "⚙️",
}

# 检测错题本是否有角标
from utils.data_manager import get_wrong_stats
wrong_stats = get_wrong_stats(st.session_state.exam_type)
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

# 隐藏 Streamlit 默认的多页面导航标签
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
/* 隐藏 Streamlit 默认的多页面导航 */
section[data-testid="stSidebar"] div[data-testid="stSidebarNav"] {
    display: none !important;
}
</style>
""", unsafe_allow_html=True)

if selected_key == "专项训练":
    from pages.specialized import show_specialized
    show_specialized()
elif selected_key == "模拟考试":
    from pages.mock_exam import show_mock_exam
    show_mock_exam()
elif selected_key == "错题本":
    from pages.wrongbook import show_wrongbook
    show_wrongbook()
elif selected_key == "数据统计":
    from pages.statistics import show_statistics
    show_statistics()
elif selected_key == "配置管理":
    from pages.settings import show_settings
    show_settings()

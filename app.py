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
        /* 主内容区顶部留白：默认 6rem(=108px@18px根字号) 过大，对齐侧边栏头部 46px */
        padding-top: 46px !important;
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
        padding: 0.55rem 0.75rem !important;
        background: linear-gradient(180deg, #f8fafc, #f1f5f9) !important;
        /* 底部留白拉大，避免与下方操作按钮边界相撞 */
        margin: 0.15rem 0 0.55rem !important;
        line-height: 1.5 !important;
    }}
    /* 卡片之后的按钮组补足上间距（与卡片 margin 叠加，双重保障） */
    [data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.sx-user-card) {{
        margin-bottom: 0.3rem !important;
    }}
    /* 渐变色头像方块（首字母），借鉴 bid-buddy-dev */
    .sx-user-avatar {{
        display: inline-flex;
        width: 1.7rem; height: 1.7rem;
        border-radius: 8px;
        background: linear-gradient(135deg, #4f46e5, #8b5cf6);
        color: white;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        font-size: 0.95rem;
        flex-shrink: 0;
    }}
    /* 副信息：user_id / 状态文案 */
    .sx-user-sub {{
        font-size: 0.74rem;
        color: #64748b;
        margin-top: 2px;
    }}
    /* KPI 网格：答题数 / 错题数（两列） */
    .sx-kpi-grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 0.45rem;
        margin: 0.4rem 0 0.55rem;
    }}
    .sx-kpi-box {{
        background: rgba(255, 255, 255, 0.7);
        border: 1px solid #dbe5f2;
        border-radius: 8px;
        padding: 0.4rem 0.55rem;
        text-align: center;
    }}
    .sx-kpi-label {{
        color: #64748b;
        font-size: 0.72rem;
        line-height: 1.2;
    }}
    .sx-kpi-value {{
        color: #1f2937;
        font-size: 1.05rem;
        font-weight: 700;
        line-height: 1.25;
        margin-top: 1px;
    }}
    /* ============ 侧边栏账号按钮：固定配色，不跟随主题/页面变化 ============ */
    /* 说明：不能用 st.markdown("<div class='...'>") 做包裹容器——Streamlit 每个元素独立渲染，
       那个 div 是封闭空元素，包不住后面的按钮。必须用真实存在的容器做作用域：[data-testid="stSidebar"]。
       选择器用后代（不带 >），因为 button 外面还套了一层 wrapper 组件。
       specificity (0,2,1) 高于专项训练红色 CSS 的 (0,1,2)，可稳定压制。 */
    [data-testid="stSidebar"] [data-testid="stButton"] button {{
        background: #ffffff !important;
        background-image: none !important;
        color: #0f172a !important;
        border: 1px solid rgba(148, 163, 184, 0.4) !important;
        box-shadow: none !important;
    }}
    [data-testid="stSidebar"] [data-testid="stButton"] button:hover {{
        background: #f1f5f9 !important;
        background-image: none !important;
        color: #0f172a !important;
        border-color: rgba(100, 116, 139, 0.5) !important;
    }}
    /* 「确认解绑」是 primary，但故意不做主题色高亮，仍用中性灰蓝（避免破坏整体协调） */
    [data-testid="stSidebar"] [data-testid="stButton"] button[data-testid="baseButton-primary"] {{
        background: linear-gradient(135deg, #475569, #334155) !important;
        background-image: linear-gradient(135deg, #475569, #334155) !important;
        color: #ffffff !important;
        border: 1px solid transparent !important;
    }}
    [data-testid="stSidebar"] [data-testid="stButton"] button[data-testid="baseButton-primary"]:hover {{
        background: linear-gradient(135deg, #334155, #1e293b) !important;
        background-image: linear-gradient(135deg, #334155, #1e293b) !important;
    }}

    /* 账号操作按钮组：两列等宽 */
    .sx-action-row {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 0.4rem;
        margin: 0.35rem 0;
    }}
    /* 解绑二次确认区 */
    .sx-unbind-confirm {{
        background: #fff7ed;
        border: 1px solid #fed7aa;
        border-radius: 8px;
        padding: 0.45rem 0.55rem;
        margin: 0.3rem 0 0.4rem;
        font-size: 0.78rem;
        color: #9a3412;
    }}
    /* 表单弹窗：缩小 padding、紧凑 */
    [data-testid="stSidebar"] [data-testid="stExpander"] details {{
        border: 1px solid #dbe5f2 !important;
        border-radius: 10px !important;
        background: rgba(255, 255, 255, 0.55) !important;
    }}
    [data-testid="stSidebar"] [data-testid="stExpander"] summary {{
        font-weight: 600 !important;
        font-size: 0.92rem !important;
    }}
    /* 底部版本号居中 */
    .sx-footer {{
        text-align: center;
        color: #94a3b8;
        font-size: 0.75rem;
        margin-top: 0.5rem;
        letter-spacing: 0.02em;
    }}
    /* sidebar 内的 text_input / password_input 字号略缩 */
    [data-testid="stSidebar"] input[type="text"],
    [data-testid="stSidebar"] input[type="password"] {{
        font-size: 0.88rem !important;
    }}
    /* sidebar 内 form_submit_button 紧凑 */
    [data-testid="stSidebar"] [data-testid="stFormSubmitButton"] button {{
        min-height: 2.2rem !important;
        font-size: 0.88rem !important;
    }}
    /* 账号面板按钮：单行显示，去掉换行（中文+emoji 容易撑爆容器宽度） */
    [data-testid="stSidebar"] button[kind="secondary"],
    [data-testid="stSidebar"] button[kind="primary"] {{
        white-space: nowrap !important;
        padding-left: 0.4rem !important;
        padding-right: 0.4rem !important;
        font-size: 0.86rem !important;
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
    /* 侧边栏 widget 标签字号 */
    [data-testid="stSidebarUserContent"] [data-testid="stWidgetLabel"] {{
        font-size: 0.92rem !important;
    }}
    /* 题库选择(selectbox)：与上方分割线、下方下拉列表的间距适当放宽 */
    [data-testid="stSidebarUserContent"] .stSelectbox {{
        margin-top: 0.5rem !important;
        margin-bottom: 0.42rem !important;
    }}
    [data-testid="stSidebarUserContent"] .stSelectbox [data-testid="stWidgetLabel"] {{
        margin-bottom: 0.45rem !important;
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

    /* 主区按钮美化（Streamlit 1.57 button container 实际是 div[data-testid="stButton"]，
       这里用 class 选择器 div.stButton 是历史遗留错误选择器，本来就一直未生效。
       保持原状，不动 selector，避免引入意外样式变化。） */
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
from utils.account_manager import generate_device_fingerprint, get_or_create_user, ensure_user_db_initialized

# 每次 rerun 开始时清除数据缓存，确保使用最新数据
invalidate_rerun_cache()

# ============================
# 多用户身份识别（设备指纹 → 用户私有题库）
# 首次访问：自动生成指纹 → 创建用户 → 克隆初始化题库模板
# 再次访问：同一浏览器指纹不变 → 自动识别同一用户（稳定绑定）
# ============================

def _resolve_current_user():
    """解析设备指纹并绑定/创建当前用户。每个用户拥有独立题库库文件。

    ⚠️ 2026-09-14 关键修复：本函数**每一帧都会执行路由同步**，不再因为
    session 里已有 _user_id 就整体跳过。

    原因：data_manager 的 _current_db_path 是**模块级全局变量**，
      (a) 会被其他 session（多标签页/多浏览器，同进程共享）覆盖；
      (b) 代码热重载时会被重置为 None；
    而旧逻辑 "_user_id 已存在 → 直接 return" 会跳过 set_current_user，
    于是后续所有读库都落到默认空库 data/exmsys.db → 页面报"题库为空"。

    现在拆成两段：
      1) 身份解析（生成/查找 user_id）—— 仅首次执行；
      2) 数据路由同步 —— 每帧无条件执行（set_current_user 已幂等，无额外开销）。
    """
    if "_user_id" not in st.session_state:
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
        # 首次进入/切换用户：强制重载该用户自己的题库与配置
        for key in ["questions", "config", "_cache_available_exams",
                    "_db_questions_version", "_data_version", "_mnemonic_data"]:
            st.session_state.pop(key, None)

    # 每帧同步数据路由（幂等）：修复跨 session 全局变量污染 / 热重载丢路由
    set_current_user(st.session_state._user_id)


_resolve_current_user()

# 兜底：若当前用户私有库是「残留空库」（从未真正使用过），自动从 master 模板克隆题库。
# 区分主动清空题库（config 有大量已用 key）的关键：这里不会破坏用户主动清空的意图。
# 初始化完成时清掉 session 里的题库与配置缓存，让后续 load_questions 读到新克隆的数据。
_init_res = ensure_user_db_initialized(st.session_state._user_id)
if _init_res.get("initialized"):
    for key in ["questions", "config", "_cache_available_exams",
                "_db_questions_version", "_data_version", "_mnemonic_data"]:
        st.session_state.pop(key, None)

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
    """执行题库切换：保留当前模块不变，仅切换题库。

    实现要点：
    1) 在 pop 缓存前先记录当前 nav（即用户当前所在模块）；
    2) 切题库后显式把 nav 恢复回该模块，避免 Streamlit 在 value 不在 options 时
       自动重置 nav 导致跳到首页/错位。
    考试/训练进行中切题库时，会先由 _exam_switch_confirm_dialog 保存进度。
    """
    # 1) 记录当前模块（与 2) 的恢复是双重保险）
    _preserved_nav = st.session_state.get("nav", "首页")
    # 2) 切换题库
    st.session_state.exam_type = new_code
    # 清除旧数据缓存，强制重新加载（含助记助学缓存，保证按新题库生成）
    for key in ["questions", "wb_questions", "wb_wrong_counts", "wb_answers",
                "wb_submitted", "wb_results", "wb_mode", "wa_selected_idx",
                "_cache_available_exams", "_mnemonic_data"]:
        st.session_state.pop(key, None)
    _reset_exam_states_for_switch()
    # 3) 显式恢复 nav，确保切题库后导航按钮和右侧页面都不变
    st.session_state.nav = _preserved_nav
    st.rerun()


def _switch_user(new_user_id):
    """账号登录/切换用户：重置当前用户库与全部会话缓存"""
    set_current_user(new_user_id)
    st.session_state._user_id = new_user_id
    for key in ["questions", "config", "_cache_available_exams",
                "_db_questions_version", "_data_version", "_mnemonic_data",
                "_cache_wrong_stats"]:
        st.session_state.pop(key, None)
    # 关闭账号面板的展开态
    for k in ("sx_show_bind", "sx_show_login", "sx_show_unbind_confirm"):
        st.session_state.pop(k, None)
    # 清掉旧登录身份缓存（下一个渲染帧会按新 user_id 重新反查）
    st.session_state.pop("_current_username", None)
    st.session_state.pop("_current_user_bound_fp", None)
    _reset_exam_states_for_switch()
    # 切账号后导航回首页。⚠️ sidebar.radio(key="nav") 在本帧已实例化，
    # 不能直接 st.session_state.nav = ...（会触发 StreamlitAPIException）。
    # 改用 nav_to 标志位，让 rerun 后到下一帧通过 nav_default_index 选中目标模块。
    st.session_state.nav_to = "首页"
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

# 根据当前 exam_type 过滤题目（供各页面使用；st.session_state.questions 始终为该题库的题）
all_qs = st.session_state.questions if st.session_state.questions else load_questions()
st.session_state.questions = [q for q in all_qs if q.get("exam_type") == st.session_state.exam_type]

# 失配自愈：若按当前 exam_type 过滤结果为空但全量题库非空，说明 st.session_state.questions
# 残留了上一个题库（或当前 exam_type 已失效，如导入题库/切换后），强制用全量重新过滤并校正
# exam_type，避免误报「题库为空」。正常情况（过滤结果非空）不会走这里，无额外 I/O 开销。
if not st.session_state.questions:
    _all_full = load_questions()
    if _all_full:
        _avail = get_available_exam_types()
        if st.session_state.exam_type not in [c for c, _ in _avail] and _avail:
            # exam_type 在当前题库中已不存在：回退到第一个可用题库，避免页面指向空库
            st.session_state.exam_type = _avail[0][0]
        st.session_state.questions = [q for q in _all_full if q.get("exam_type") == st.session_state.exam_type]

# —— 空题库提示（放在「过滤 + 自愈」之后，避免缓存/时序导致的误报）——
# 只有走完上面两步后仍为空，才说明当前用户库确实没有题目。
if len(st.session_state.questions) == 0:
    st.sidebar.warning("⚠️ 题库为空，请先在配置管理中导入题库")
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

nav_keys = list(menu_items.keys())

# 归一化旧 session 的 nav 值：上一版 radio 的 value 是带图标的 label（如"🎯 专项训练"），
# 新版改为模块 key（如"专项训练"），旧 value 不在 options 时 Streamlit 会自动重置 nav 为
# options[0]（即"首页"），导致切题库后右侧跳回首页。这里逐项匹配模块名子串，把旧值
# 规整成模块 key，消除 Streamlit 的自动重置，确保切题库不改变当前模块。
if "nav" in st.session_state and st.session_state.nav not in nav_keys:
    _old_nav = st.session_state.nav
    for _k in nav_keys:
        if _k in _old_nav:
            st.session_state.nav = _k
            break
    else:
        # 旧值无法识别，fallback 到首页（与首次访问默认一致）
        st.session_state.nav = nav_keys[0]

# 用模块 key 作为导航 radio 的值，format_func 负责显示带角标的标签。
# 这样当切换题库保留当前模块时，即使"错题本"角标数量变化，导航值(模块 key)也不会失效。
def _nav_label(key: str) -> str:
    icon = menu_items[key]
    if key == "错题本":
        return f"{icon} {key}{wrong_badge}"
    return f"{icon} {key}"

# 支持从按钮跳转（快速入口）
nav_key_from_button = st.session_state.pop("nav_to", None)
nav_default_index = 0
if nav_key_from_button:
    for i, k in enumerate(nav_keys):
        if k == nav_key_from_button:
            nav_default_index = i
            break

selected_key = st.sidebar.radio(
    "导航", nav_keys, key="nav", index=nav_default_index,
    format_func=_nav_label,
)

st.sidebar.markdown("---")

# ---- 账号面板（置于导航之后；CSS 让整个容器吸底显示）----
# 参考 bid-buddy-dev 的设计语言重做：渐变头像 + 两列按钮 + 表单弹窗 + 解绑二次确认。
# 关键设计（2026-09-14 升级）：
#   「已登录用户」≠「设备已绑定」。
#   - 已登录用户 = st.session_state._current_username 有值（来自 login/bind）
#   - 设备已绑定 = 当前设备指纹出现在 by_device 中
#   登录成功后会同步把当前设备指纹登记到该账号，下次浏览器自动识别也是该用户。
#   显示策略：已登录 → "用户 wanli" + 绑定的原始指纹 + "可跨设备同步"；
#           未登录 → "访客 xxx"。
with st.sidebar.container():
    from utils.account_manager import AccountManager
    _acct_mgr = AccountManager()
    _bound_acct = _acct_mgr.get_bound_account(st.session_state._device_fp)

    # 当前用户身份（优先用 session_state 缓存，未登录时按 user_id 反查）
    _current_username = st.session_state.get("_current_username")
    _current_user_bound_fp = st.session_state.get("_current_user_bound_fp", "")
    if not _current_username:
        # session 干净时（如首次访问），按 user_id 反查
        _acct_by_uid = _acct_mgr.get_account_for_user_id(st.session_state._user_id or "")
        if _acct_by_uid:
            _current_username = _acct_by_uid["username"]
            _current_user_bound_fp = _acct_by_uid["bound_device"]
            # 回填 session_state，避免每帧重查
            st.session_state._current_username = _current_username
            st.session_state._current_user_bound_fp = _current_user_bound_fp

    _user_short = st.session_state._user_id or "未分配"

    # ============ 用户卡片（借鉴 bid-buddy-dev 渐变头像）============
    if _current_username:
        # 已登录：显示 "用户 wanli"，副标题用 ID 而非指纹
        _disp_name = _current_username
        _avatar_letter = "U"   # 固定 U = user（已登录）
        _sub_text = f"ID {_user_short}"
    else:
        # 未登录（仅访客）
        _disp_name = f"访客 {_user_short[:8]}"
        _avatar_letter = "V"   # 固定 V = visitor（未登录）
        _sub_text = f"ID {_user_short}"

    st.markdown(
        f"<div class='sx-user-card'>"
        f"<div style='display:flex;align-items:center;gap:0.5rem;'>"
        f"<div class='sx-user-avatar'>{_avatar_letter}</div>"
        f"<div style='min-width:0;'>"
        f"<div style='font-weight:700;font-size:0.98rem;color:#1f2937;'>"
        f"{_disp_name}</div>"
        f"<div class='sx-user-sub'>{_sub_text}</div>"
        f"</div>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ============ 状态化标志：解绑二次确认 / 表单展开 ============
    _show_bind = st.session_state.get("sx_show_bind", False)
    _show_login = st.session_state.get("sx_show_login", False)
    _show_unbind_confirm = st.session_state.get("sx_show_unbind_confirm", False)

    # ============ 账号操作按钮组 ============
    if _current_username:
        # 已登录：两列 [解绑] [切换]
        with st.container():
            st.markdown("<div class='sx-acct-btns'>", unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            with c1:
                if st.button("解绑", key="btn_unbind", use_container_width=True):
                    st.session_state.sx_show_unbind_confirm = True
                    st.session_state.sx_show_bind = False
                    st.session_state.sx_show_login = False
                    st.rerun()
            with c2:
                if st.button("切换", key="btn_switch_acct", use_container_width=True):
                    # 切换等同于先解绑再绑别的：直接展开登录表单即可（不立即解绑）
                    st.session_state.sx_show_login = True
                    st.session_state.sx_show_bind = False
                    st.session_state.sx_show_unbind_confirm = False
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        # 解绑二次确认（黄色警告区）
        if _show_unbind_confirm:
            st.markdown(
                "<div class='sx-unbind-confirm'>"
                "⚠️ 解绑后当前设备不再关联账号 <b>{}</b>，账号和密码数据将被清除，"
                "但 <b>题库答题数据保留</b>（需在另一设备登录同名账号才能看到）。"
                "</div>".format(_current_username),
                unsafe_allow_html=True,
            )
            with st.container():
                st.markdown("<div class='sx-acct-btns'>", unsafe_allow_html=True)
                cu1, cu2 = st.columns(2)
                with cu1:
                    if st.button("确认解绑", key="btn_confirm_unbind", type="primary", use_container_width=True):
                        # 解绑账号：清掉当前设备的 by_device 记录，并清 session_state 用户身份
                        _acct_mgr.unbind_account(st.session_state._device_fp)
                        st.session_state._current_username = None
                        st.session_state._current_user_bound_fp = ""
                        st.session_state.sx_show_unbind_confirm = False
                        st.success("已解绑")
                        st.rerun()
                with cu2:
                    if st.button("取消", key="btn_cancel_unbind", use_container_width=True):
                        st.session_state.sx_show_unbind_confirm = False
                        st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)
    else:
        # 未绑定：两列 [绑定账号] [账号登录]
        with st.container():
            st.markdown("<div class='sx-acct-btns'>", unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            with c1:
                if st.button("绑定账号", key="btn_show_bind", use_container_width=True):
                    st.session_state.sx_show_bind = not _show_bind
                    st.session_state.sx_show_login = False
                    st.rerun()
            with c2:
                if st.button("账号登录", key="btn_show_login", use_container_width=True):
                    st.session_state.sx_show_login = not _show_login
                    st.session_state.sx_show_bind = False
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        # ---- 绑定账号表单（双密码校验）----
        if _show_bind:
            with st.expander("绑定账号", expanded=True):
                st.markdown("将当前设备与一个易记的用户名绑定，方便跨设备登录。")
                with st.form("sx_bind_form", clear_on_submit=False):
                    _b_user = st.text_input("用户名", key="bind_username")
                    _b_pwd = st.text_input("密码", type="password", key="bind_password")
                    _b_pwd2 = st.text_input("确认密码", type="password", key="bind_password2")
                    _b_submitted = st.form_submit_button("确定绑定", use_container_width=True)
                if _b_submitted:
                    if not _b_user or not _b_pwd:
                        st.error("用户名和密码不能为空")
                    elif _b_pwd != _b_pwd2:
                        st.error("两次输入的密码不一致")
                    else:
                        _ok, _msg = _acct_mgr.bind_account(
                            st.session_state._device_fp, _b_user, _b_pwd
                        )
                        if _ok:
                            # 绑定成功后即视为已登录，写入 session_state
                            st.session_state._current_username = _b_user.strip()
                            st.session_state._current_user_bound_fp = st.session_state._device_fp
                            st.session_state.sx_show_bind = False
                            st.success(_msg + " 已自动登录。")
                            st.rerun()
                        else:
                            st.error(_msg)

        # ---- 账号登录表单 ----
        if _show_login:
            with st.expander("账号登录", expanded=True):
                st.markdown("使用已绑定的用户名和密码登录。")
                with st.form("sx_login_form", clear_on_submit=False):
                    _l_user = st.text_input("用户名", key="login_username")
                    _l_pwd = st.text_input("密码", type="password", key="login_password")
                    _l_submitted = st.form_submit_button("登录", use_container_width=True)
                if _l_submitted:
                    if not _l_user or not _l_pwd:
                        st.error("用户名和密码不能为空")
                    else:
                        # login_account 自动登记当前设备指纹到该账号
                        _ok, _msg, _uid = _acct_mgr.login_account(
                            _l_user, _l_pwd, device_fingerprint=st.session_state._device_fp
                        )
                        if _ok and _uid:
                            # 写入 session_state：登录身份 + 该账号原始绑定指纹
                            st.session_state._current_username = _l_user.strip()
                            _acct_info = _acct_mgr.get_account_for_user_id(_uid)
                            if _acct_info:
                                st.session_state._current_user_bound_fp = _acct_info["bound_device"]
                            st.session_state.sx_show_login = False
                            st.success(_msg)
                            _switch_user(_uid)
                        else:
                            st.error(_msg)

    # ============ 底部版本号（居中）============
    st.markdown(
        "<div class='sx-footer'>心理咨询师考试背题系统 v2.0</div>",
        unsafe_allow_html=True,
    )

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

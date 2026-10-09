"""答题卡右栏组件 —— 模拟考试 / 专项训练 / 巩固练习 / 错题本 共用

设计要点（已用真实浏览器实测验证）：
1. 布局：答题页拆成「左栏题目区 + 右栏答题卡」，右栏与左栏等高、
   不超过视口，页面滚动时自动粘住，答题卡永远看得见。
2. 网格：用 CSS Grid `repeat(auto-fill, minmax(46px, 1fr))` 自适应填充，
   容器多宽就排多少列，格子宽度恒在 46px 以上 ——
   250 题（3 位数题号）叠加 ★ / ? 双标记也不会截断。
3. 标记体系（4 页统一）：
       描边      当前题（不占文字宽度，避免挤压题号）
       ★         已标记
       ?         不确定
       ✓ / ✗     提交后答对 / 答错
4. 容器 key 固定（SIDE_KEY / SCROLL_KEY / GRID_KEY）：同一时刻一个页面
   只渲染一个答题卡，故 4 页共用同一套 CSS；按钮 key 用调用方传入的
   前缀，与历史 session_state / 草稿保持兼容。
5. 结果页（提交后）：submitted=True → 改按 ✓/✗ 着色，筛选项换成
   「全部 / 答对 / 答错 / ★ / ?」，并用独立的 filter_state_key / target_key /
   filter_reset_key 与答题阶段的筛选、当前题彻底隔离；
   左栏回顾列表用 pick_review() 按同一口径挑题，做到左右联动。
"""
import streamlit as st

# 固定容器 key（CSS 只写一份，见 app.py 的 CARD_CSS）
SIDE_KEY = "answer_card_side"
SCROLL_KEY = "answer_card_scroll"
GRID_KEY = "answer_card_grid"

# 筛选按钮文案。答题中用「已答/未答」，结果页用「答对/答错」，
# 两套合用同一张表，靠 filter_kinds 决定这一屏渲染哪几个。
FILTER_LABELS = {
    "all": "全部",
    "answered": "已答",
    "unanswered": "未答",
    "correct": "✓答对",
    "wrong": "✗答错",
    "marked": "★已标记",
    "uncertain": "?不确定",
}
# 答题中 / 提交后（结果页）各自可用的筛选项
ANSWER_FILTER_KINDS = ("all", "answered", "unanswered", "marked", "uncertain")
RESULT_FILTER_KINDS = ("all", "correct", "wrong", "marked", "uncertain")

# 答题卡专用 CSS。放在组件内，由 app.py 统一注入一次。
CARD_CSS = """
<style>
/* ============ 右栏所在列：固定宽度，不随屏幕等比缩水 ============ */
/* 旧版用 st.columns([3.05, 1]) 的柔性比例 → 1366 屏右栏只剩 229px（4 列），
   题号被挤成一条。现在改为固定 340px，任何屏幕下都保证 6 列。 */
[data-testid="stColumn"]:has(div[class*="st-key-answer_card_side"]) {
    flex: 0 0 340px !important;
    width: 340px !important;
    min-width: 340px !important;
    max-width: 340px !important;
}
/* 左右栏之间的呼吸间隙：Streamlit 的 gap 参数在本页会被列宽吃掉（实测仅 6px），
   导致左栏右对齐的答题统计直接顶在「答题卡」标题上，这里直接锁死。 */
[data-testid="stHorizontalBlock"]:has(div[class*="st-key-answer_card_side"]) {
    gap: 24px !important;
}
/* 左栏（题目区）吃剩余宽度，允许压缩，避免整行溢出 */
[data-testid="stHorizontalBlock"]:has(div[class*="st-key-answer_card_side"])
    > [data-testid="stColumn"]:not(:has(div[class*="st-key-answer_card_side"])) {
    flex: 1 1 0 !important;
    min-width: 0 !important;
}

/* ============ 右栏面板：视口内尽量高 + 滚动时粘住 ============ */
/* 先让「布局包装层」撑满列高，否则它被压成与面板等高，粘性就没有滑动空间 */
[data-testid="stLayoutWrapper"]:has(> div[class*="st-key-answer_card_side"]) {
    height: 100% !important;
    min-height: 0 !important;
}
div[class*="st-key-answer_card_side"] {
    position: sticky !important;
    top: 56px !important;
    align-self: flex-start !important;
    height: 100% !important;
    max-height: calc(100vh - 110px) !important;
    min-height: 440px !important;
    display: flex !important;
    flex-direction: column !important;
    gap: 4px !important;
}
/* 关键：除网格外的所有块「不参与压缩」。
   否则 flex 会按 basis 加权把网格容器压没（旧版正是这样被压到 16px）。*/
div[class*="st-key-answer_card_side"] > *:not(:has(div[class*="st-key-answer_card_scroll"])) {
    flex: 0 0 auto !important;
}
/* 网格容器：吃掉全部剩余高度，且保底 260px（约 9 行）*/
div[class*="st-key-answer_card_side"] > div:has(div[class*="st-key-answer_card_scroll"]) {
    flex: 1 1 auto !important;
    min-height: 260px !important;
    display: flex !important;
    flex-direction: column !important;
}
/* 网格滚动区：撑满容器并内部滚动（题多时不再撑长整页）*/
div[class*="st-key-answer_card_scroll"] {
    flex: 1 1 auto !important;
    min-height: 0 !important;
    overflow-y: auto !important;
    overflow-x: hidden !important;
    padding: 6px !important;
}

/* ============ 关键修复：顶部文字重叠 ============ */
/* Streamlit 1.57 在右栏（flex 纵列）里给「直接的元素容器」算出的高度异常小：
   实测标题容器只有 4.2px、进度容器 7.8px，而内容分别有 22px / 26px，
   内容溢出后压在相邻元素上 —— 就是「答题卡顶部文字重叠」。
   已逐项实测：flex-shrink=0、height:auto、min-height:fit-content、max-content、
   改 display:flex 全部无效；**只有像素值 min-height 能撑开（4.2px → 26px）**。 */
div[class*="st-key-answer_card_side"] > [data-testid="stElementContainer"] {
    min-height: 24px !important;   /* 标题行（h4 实测 22px） */
}
div[class*="st-key-answer_card_side"] > [data-testid="stElementContainer"]:has(.ac-progress) {
    min-height: 32px !important;   /* 进度区（文字 17 + 间距 3 + 条 6） */
}

/* ============ 辅助控件瘦身：把高度让给题号网格 ============ */
div[class*="st-key-answer_card_side"] h4 {
    font-size: 0.95rem !important; margin: 0 !important; padding: 0 !important;
    line-height: 1.3 !important; white-space: nowrap !important;
}
/* ============ 进度区：自绘 ============ */
/* 不用 st.progress —— 它的文字与进度条是两个不同层级的节点，改字号/条高后
   文字会溢出自己容器、和相邻标题叠在一起（实测截图可见）。
   自绘在同一个 markdown 元素内，高度完全可控。 */
div[class*="st-key-answer_card_side"] .ac-progress { margin: 0 !important; }
div[class*="st-key-answer_card_side"] .ac-progress-text {
    font-size: 0.72rem !important; line-height: 1.3 !important;
    opacity: 0.8; white-space: nowrap !important;
    overflow: hidden !important; text-overflow: ellipsis !important;
    margin: 0 0 3px 0 !important;
}
div[class*="st-key-answer_card_side"] .ac-progress-track {
    height: 6px !important; border-radius: 999px !important;
    background: rgba(128, 128, 128, 0.25) !important;
    overflow: hidden !important;
}
div[class*="st-key-answer_card_side"] .ac-progress-fill {
    height: 100% !important; border-radius: 999px !important;
    background: var(--primary-color, #FF4B4B) !important;
}
/* 筛选行（只作用于 stHorizontalBlock，不影响网格按钮）*/
div[class*="st-key-answer_card_side"] [data-testid="stHorizontalBlock"] { gap: 4px !important; }
div[class*="st-key-answer_card_side"] [data-testid="stHorizontalBlock"] [data-testid="stButton"] button {
    min-height: 30px !important; height: 30px !important; padding: 0 4px !important;
}
div[class*="st-key-answer_card_side"] [data-testid="stHorizontalBlock"] [data-testid="stButton"] button p {
    font-size: 0.74rem !important; line-height: 1 !important; margin: 0 !important;
    white-space: nowrap !important;
}

/* ============ 题号网格：自适应填充，永不溢出 ============ */
div[class*="st-key-answer_card_grid"] {
    display: grid !important;
    grid-template-columns: repeat(auto-fill, minmax(46px, 1fr)) !important;
    gap: 4px !important;
    align-content: start !important;
}
div[class*="st-key-answer_card_grid"] [data-testid="stElementContainer"] {
    min-width: 0 !important;
    width: auto !important;
}
div[class*="st-key-answer_card_grid"] button {
    min-height: 26px !important;
    height: 26px !important;
    padding: 0 2px !important;
    border-radius: 6px !important;
    font-size: 11.5px !important;
    line-height: 1 !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}
div[class*="st-key-answer_card_grid"] button p {
    font-size: 11.5px !important;
    line-height: 1 !important;
    margin: 0 !important;
    letter-spacing: -0.2px !important;
    white-space: nowrap !important;
}

/* ============ 左栏（题目区）窄栏排版兜底 ============ */
/* 右栏固定占掉 340px 后左栏会变窄。左栏内部的行（题号行 / 题型行）默认
   min-width:auto，长文本（答题统计串）会把列撑破、直接压在右栏答题卡上。
   这里让所有内层列可收缩、文本可断行。 */
[data-testid="stHorizontalBlock"]:has(div[class*="st-key-answer_card_side"])
    [data-testid="stColumn"],
[data-testid="stHorizontalBlock"]:has(div[class*="st-key-answer_card_side"])
    [data-testid="stElementContainer"] {
    min-width: 0 !important;
}
[data-testid="stHorizontalBlock"]:has(div[class*="st-key-answer_card_side"])
    [data-testid="stMarkdownContainer"] {
    overflow-wrap: anywhere !important;
}
/* 注：「不确定」开关折成竖排的问题由页面侧列宽解决
   （题型行 st.columns([6,2,2]) → [5,2.5,2.5]）。
   CSS 里无法可靠命中 st.toggle 内部结构，故不用选择器 hack。 */

/* ============ 中等屏幕：右栏收窄一点，保证左栏仍有阅读宽度 ============ */
@media (max-width: 1250px) and (min-width: 901px) {
    [data-testid="stColumn"]:has(div[class*="st-key-answer_card_side"]) {
        flex: 0 0 290px !important;
        width: 290px !important;
        min-width: 290px !important;
        max-width: 290px !important;
    }
}

/* ============ 窄屏兜底：右栏回到整宽、取消粘性 ============ */
@media (max-width: 900px) {
    [data-testid="stColumn"]:has(div[class*="st-key-answer_card_side"]) {
        flex: 1 1 100% !important; width: 100% !important;
        min-width: 0 !important; max-width: 100% !important;
    }
    div[class*="st-key-answer_card_side"] {
        position: static !important; max-height: none !important; min-height: 0 !important;
    }
}
</style>
"""


def card_label(number, marked=False, uncertain=False, result=None):
    """组装格子文字（顺序：题号 → 对错 → ★ → ?）。

    当前题不在此处加前缀符号 —— 改用 CSS 描边（见 _inject_current_css），
    这样 3 位数题号 + ★ + ? 的最宽形态也只需约 29px，
    远小于 46px 的最小格宽，任何屏宽下都不会显示不全。
    """
    parts = [str(number)]
    if result == "correct":
        parts.append("✓")
    elif result == "wrong":
        parts.append("✗")
    if marked:
        parts.append("★")
    if uncertain:
        parts.append("?")
    return "".join(parts)


def _inject_current_css(btn_prefix, current_idx):
    """只注入 1 条规则，精确给当前题描边。

    Streamlit 会给带 key 的 widget 容器加 `st-key-<key>` class，
    因此这条规则能精确命中，不会影响别的格子。
    """
    st.markdown(
        f"<style>div.st-key-{btn_prefix}_{current_idx} button{{"
        f"box-shadow:inset 0 0 0 2px #1e293b !important;font-weight:700 !important;}}</style>",
        unsafe_allow_html=True,
    )


def _is_visible(filter_mode, *, answered, marked, uncertain, correct):
    """按筛选条件判断格子是否显示（隐藏的题不占位，网格自动重排）

    「答对/答错」由 correct（results 里的判定结果）决定，仅在提交后端可用。
    """
    if filter_mode == "answered":
        return answered
    if filter_mode == "unanswered":
        return not answered
    if filter_mode == "marked":
        return marked
    if filter_mode == "uncertain":
        return uncertain
    if filter_mode == "correct":
        return correct
    if filter_mode == "wrong":
        return not correct
    return True


def _filter_cb(filter_key, value, reset_key=None):
    """切筛选。reset_key 非空时同时把它清掉（结果页用来退出「单题回顾」）。"""
    def _cb():
        st.session_state[filter_key] = value
        if reset_key:
            st.session_state[reset_key] = None
    return _cb


def _jump_cb(current_key, target, total):
    def _cb():
        st.session_state[current_key] = max(0, min(total - 1, int(target) - 1))
    return _cb


def _norm_results(results):
    """提交后的对错表：允许 {qid: {"correct": bool}} 或 {qid: bool} 两种写法"""
    out = {}
    for key, val in (results or {}).items():
        out[key] = bool(val.get("correct")) if isinstance(val, dict) else bool(val)
    return out


# 结果页左栏回顾标题（与右栏筛选项一一对应）
REVIEW_TITLES = {
    "all": "📋 逐题回顾",
    "answered": "已答题回顾",
    "unanswered": "未答题回顾",
    "correct": "✅ 答对题回顾",
    "wrong": "❌ 错题回顾",
    "marked": "★ 已标记题回顾",
    "uncertain": "? 不确定题回顾",
}


def pick_review(questions, *, correct_map, mode="wrong", review_idx=None,
                marked=None, uncertain=None):
    """挑出结果页左栏要回顾的题 —— 与右栏筛选保持同一套口径。

    参数
    ----
    questions   : 题目列表（需含 "id"）
    correct_map : {qid: bool}，提交后的对错判定
    mode        : 与右栏筛选项同名（all / correct / wrong / marked / uncertain）
    review_idx  : 非 None 时只看这一题（下标）—— 右栏点题号「定位到该题」
    marked      : 已标记 qid 集合
    uncertain   : 不确定 qid 集合

    返回 (下标列表, 标题)。下标统一相对 questions，左右栏因此能一一对应。
    """
    marked = marked or set()
    uncertain = uncertain or set()
    total = len(questions)

    if review_idx is not None and 0 <= review_idx < total:
        return [review_idx], f"### 📄 第 {review_idx + 1} 题回顾"

    if mode == "correct":
        idxs = [i for i, q in enumerate(questions) if correct_map.get(q.get("id"))]
    elif mode == "wrong":
        idxs = [i for i, q in enumerate(questions) if not correct_map.get(q.get("id"))]
    elif mode == "marked":
        idxs = [i for i, q in enumerate(questions) if q.get("id") in marked]
    elif mode == "uncertain":
        idxs = [i for i, q in enumerate(questions) if q.get("id") in uncertain]
    else:
        idxs = list(range(total))
    return idxs, REVIEW_TITLES.get(mode, REVIEW_TITLES["all"])


def render_answer_card(
    *,
    state_prefix,
    questions,
    answers,
    marked=None,
    uncertain=None,
    current_idx=None,
    filter_mode=None,
    results=None,
    submitted=False,
    show_filters=True,
    filter_kinds=None,
    filter_state_key=None,
    target_key=None,
    filter_reset_key=None,
):
    """渲染右栏答题卡。

    参数
    ----
    state_prefix     : "mock" / "spec" / "consol" / "wb"，用于拼 session_state 键与按钮 key
    questions        : 题目列表（需含 "id"）
    answers          : {qid: 答案}，用于判断「已答」与进度
    marked           : 已标记 qid 集合
    uncertain        : 不确定 qid 集合
    current_idx      : 当前题下标（描边）；None = 不描边（结果页未选中时用）
    filter_mode      : 当前筛选；None = 从 filter_state_key 读，读不到则 "all"
    results          : 提交后 {qid: {"correct": bool}}，用于 ✓/✗ 与对错配色
    submitted        : 是否已提交（改按对错着色，筛选项换成「答对/答错」）
    show_filters     : 是否显示筛选按钮
    filter_kinds     : 这一屏渲染哪几个筛选项；默认按 submitted 自动选
    filter_state_key : 筛选状态写入的 session 键，默认 f"{state_prefix}_card_filter"。
                       结果页传独立键，避免沿用答题中残留的筛选。
    target_key       : 点题号 / 跳转时写入的「当前题」session 键，
                       默认 f"{state_prefix}_current"。结果页传独立键做「定位到某题」。
    filter_reset_key : 切筛选时把它重置为 None（结果页用来退出「单题回顾」）
    """
    marked = marked or set()
    uncertain = uncertain or set()
    correct_map = _norm_results(results)
    total = len(questions)
    btn_prefix = f"{state_prefix}_card"
    filter_key = filter_state_key or f"{state_prefix}_card_filter"
    current_key = target_key or f"{state_prefix}_current"
    if filter_mode is None:
        filter_mode = st.session_state.get(filter_key, "all")
    if filter_kinds is None:
        filter_kinds = RESULT_FILTER_KINDS if submitted else ANSWER_FILTER_KINDS

    answered = len(answers)
    marked_count = len(marked)
    uncertain_count = len(uncertain)
    correct_count = sum(1 for q in questions if correct_map.get(q.get("id")))

    with st.container(key=SIDE_KEY):
        # 标题行只放标题。图例已删（筛选按钮上的「★已标记 / ?不确定 / ✓答对」
        # 本身就是图例），避免这一行被撑成长文本、与进度行挤成重叠。
        st.markdown("#### 📌 答题卡")
        # 进度区自绘：一个 markdown 元素内完成，高度可控（st.progress 会溢出重叠）
        if submitted:
            _pct = (correct_count / total * 100) if total else 0
            _ptext = (f"正确 {correct_count}/{total}"
                      + (f" · ★{marked_count}" if marked_count else "")
                      + (f" · ?{uncertain_count}" if uncertain_count else ""))
        else:
            _pct = (answered / total * 100) if total else 0
            _ptext = (f"已答 {answered}/{total}"
                      + (f" · ★{marked_count}" if marked_count else "")
                      + (f" · ?{uncertain_count}" if uncertain_count else ""))
        st.markdown(
            f"<div class='ac-progress'>"
            f"<div class='ac-progress-text'>{_ptext}</div>"
            f"<div class='ac-progress-track'>"
            f"<div class='ac-progress-fill' style='width:{_pct:.1f}%'></div>"
            f"</div></div>",
            unsafe_allow_html=True,
        )

        # ---- 筛选：每行 3 个（窄栏里再多会被压成两行文字）----
        if show_filters:
            for start in range(0, len(filter_kinds), 3):
                kinds = filter_kinds[start:start + 3]
                row = st.columns(len(kinds), gap="xxsmall")
                for cell, kind in zip(row, kinds):
                    cell.button(
                        FILTER_LABELS[kind], key=f"{state_prefix}_filter_{kind}",
                        use_container_width=True,
                        type="primary" if filter_mode == kind else "secondary",
                        on_click=_filter_cb(filter_key, kind, filter_reset_key),
                    )

        # ---- 题号网格（内部滚动）----
        with st.container(key=SCROLL_KEY, border=True):
            with st.container(key=GRID_KEY):
                for i, q in enumerate(questions):
                    qid = q.get("id")
                    is_answered = qid in answers
                    is_marked = qid in marked
                    is_uncertain = qid in uncertain
                    is_correct = bool(correct_map.get(qid, False))
                    if not _is_visible(filter_mode, answered=is_answered, marked=is_marked,
                                       uncertain=is_uncertain, correct=is_correct):
                        continue

                    if submitted:
                        label = card_label(i + 1, marked=is_marked, uncertain=is_uncertain,
                                           result="correct" if is_correct else "wrong")
                        btype = "primary" if is_correct else "secondary"
                    else:
                        label = card_label(i + 1, marked=is_marked, uncertain=is_uncertain)
                        btype = "primary" if is_answered else "secondary"

                    st.button(label, key=f"{btn_prefix}_{i}",
                              use_container_width=True, type=btype,
                              on_click=_jump_cb(current_key, i + 1, max(total, 1)))

    # 当前题描边（必须在按钮渲染后注入，key 才存在）
    if current_idx is not None and 0 <= current_idx < total:
        _inject_current_css(btn_prefix, current_idx)



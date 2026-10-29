"""隐藏 Streamlit Community Cloud 外壳里的「Manage app」入口。

为什么应用内 CSS 做不到
------------------------
`xxx.streamlit.app` 返回的不是 Streamlit 本体页面，而是**社区云自己的外壳**，
外壳用一个同源 iframe 装载我们的应用：

    <iframe title="streamlitApp" sandbox="... allow-same-origin ..."></iframe>

右下角的「Manage app」按钮由**外壳**渲染，是那个 iframe 的**兄弟节点**。
CSS 不跨文档 → `st.markdown` 里的选择器永远碰不到它，只能从应用内部注入脚本、
跨到 `window.parent.document` 去隐藏（同 `bid-buddy-dev/cloud_badge.py` 的思路）。

补充事实（用户问「普通用户会不会看到」）
--------------------------------------
Streamlit 官方文档 *Manage your app* 明确：要先 `signed in to Community Cloud`
再访问应用，右下角才会出现「Manage app」。**未登录的访客看不到**，它只对
有该应用权限的开发者（也就是你自己）出现。所以本模块的作用是「自己看着干净」，
而不是「挡掉用户能看到的东西」。

安全约束（与 cloud_badge.py 同源，均为线上实测结论）
--------------------------------------------------
1. 必须用 `<script>` 标签包裹后交给 `st.html`：Streamlit 前端只重建并执行
   `querySelectorAll('script')` 命中的元素；裸 JS 文本不执行，还会被当 HTML
   渲染成页面上可见的源码。
2. 脚本正文不能出现「`<` + `[A-Za-z0-9_!/]`」：DOMPurify 命中时会把整条 script
   连内容一起丢掉（不报错）。因此比较运算符一律写成 `a < b`（`<` 后留空格），
   注释里也不写标签字面量。
3. 只隐藏、不 remove()：节点由 React 管理，直接删除可能触发
   "Failed to execute 'removeChild'" 白屏；改 class + 样式表更安全。
4. 只在「我们确实装在那个 streamlitApp iframe 里」时才动手；本地
   `streamlit run` 没有父文档，脚本自然成为空操作。

自检
----
浏览器控制台（应用 iframe 内）输入 `__exsChromeHide`：
    {ran: 1, top: "reached", frame: true, hidden: true}
`top=reached` 表示爬到了外壳文档，`hidden` 表示确实隐藏到了按钮。
"""

import re
from typing import Optional

# 与 bid-buddy 的 cloud_badge 保持同名约定，便于两套代码互相对照
_MARK_CLASS = "exs-manage-app-off"
_STYLE_ID = "exs-manage-app-hide-style"

# `<script>` 是 raw-text 元素：内容里出现 `</script` 会把它提前闭合
_SCRIPT_BREAK = re.compile(r"</\s*script", re.IGNORECASE)
# DOMPurify 3.x：命中即整条 script 被丢弃（实测，见 cloud_badge.py 的逐字符记录）
_PURIFY_KILLER = re.compile(r"<[A-Za-z0-9_!/]")

# 行为要点：
#   * 只认 `<button>` / `<a>` / `[role="button"]` 这三类**可交互**元素，
#     且文本严格等于 "manage app"。不按 div 泛匹配 —— 否则会把已经打开的
#     日志面板标题一起藏掉。
#   * 同时兼容 data-testid（Cloud 改版时文案可能变，但 testid 相对稳定）。
#   * MutationObserver + 兜底轮询：外壳是 React，重渲染会把按钮挂回来。
_MANAGE_APP_JS = r"""
(function () {
    'use strict';
    var MARK = 'exs-manage-app-off';
    var STYLE_ID = 'exs-manage-app-hide-style';

    var mark = window.__exsChromeHide || (window.__exsChromeHide = { ran: 0, top: 'none', frame: false, hidden: false });
    mark.ran += 1;

    try {
        // ---- 0. 爬到最外层文档（同源才有；跨源会抛，停在哪层算哪层）----
        var topWin = window, parentDoc = null;
        while (topWin.parent && topWin.parent !== topWin) {
            var upDoc = null;
            try { upDoc = topWin.parent.document; } catch (e) { upDoc = null; }
            if (!upDoc) { break; }
            topWin = topWin.parent;
            parentDoc = upDoc;
        }
        if (!parentDoc) { return; }
        mark.top = 'reached';

        // ---- 0b. 确认 streamlitApp iframe 里装的就是我们（或我们的祖先）----
        var box = parentDoc.querySelector('iframe[title="streamlitApp"]');
        if (!box) { return; }
        var boxWin = null;
        try { boxWin = box.contentWindow; } catch (e) { boxWin = null; }
        if (!boxWin) { return; }
        var w = window, guard = 0, onChain = false;
        while (w && guard++ < 6) {
            if (w === boxWin) { onChain = true; break; }
            if (w === w.parent) { break; }
            try { w = w.parent; } catch (e) { break; }
        }
        if (!onChain) { return; }
        mark.frame = true;

        // ---- 1. 样式表（class 隐藏，React 重渲染后依然有效）----
        if (!parentDoc.getElementById(STYLE_ID)) {
            var style = parentDoc.createElement('style');
            style.id = STYLE_ID;
            style.textContent = '.' + MARK + '{display:none !important;visibility:hidden !important;}';
            (parentDoc.head || parentDoc.documentElement).appendChild(style);
        }

        function norm(t) {
            return (t || '').replace(/\s+/g, ' ').trim().toLowerCase();
        }

        function hide(el) {
            if (!el || !el.classList) { return false; }
            if (el.classList.contains(MARK)) { return false; }
            el.classList.add(MARK);
            el.setAttribute('data-exs-chrome-off', '1');
            return true;
        }

        // ---- 2. 按文案定位：右下角那颗「Manage app」按钮 ----
        function hideByText() {
            var changed = false;
            var nodes = parentDoc.querySelectorAll('button, a, [role="button"]');
            for (var i = 0; i < nodes.length; i++) {
                if (norm(nodes[i].textContent) !== 'manage app') { continue; }
                if (hide(nodes[i])) { changed = true; }
            }
            return changed;
        }

        // ---- 3. 按 testid 兜底（外壳改文案时仍能命中）----
        function hideByTestId() {
            var changed = false;
            var nodes = parentDoc.querySelectorAll(
                '[data-testid*="manage-app"], [data-testid*="manageApp"], [aria-label="Manage app"]'
            );
            for (var i = 0; i < nodes.length; i++) {
                if (hide(nodes[i])) { changed = true; }
            }
            return changed;
        }

        function sweep() {
            try {
                var a = hideByText();
                var b = hideByTestId();
                if (a || b) { mark.hidden = true; }
            } catch (e) { /* 忽略 */ }
        }

        sweep();

        // ---- 4. 外壳重渲染会把按钮挂回来 → 持续盯住 ----
        try {
            var pending = null;
            var observer = new MutationObserver(function () {
                if (pending) { return; }
                pending = setTimeout(function () { pending = null; sweep(); }, 120);
            });
            observer.observe(parentDoc.body, { childList: true, subtree: true });
        } catch (e) { /* 老浏览器没有 MutationObserver */ }

        // ---- 5. 兜底轮询：按钮可能比本脚本晚渲染 ----
        var ticks = 0;
        var timer = setInterval(function () {
            sweep();
            ticks += 1;
            if (ticks >= 30) { clearInterval(timer); }
        }, 1000);
    } catch (e) { /* 任何异常都不允许影响应用本体 */ }
})();
"""


class ChromeScriptUnsafe(ValueError):
    """脚本含无法内联的序列，拒绝注入（宁可功能不生效，也不往页面吐源码）。"""


def chrome_hider_script() -> str:
    """返回裸脚本源码（仅供测试把它当字符串检查/执行）。"""
    return _MANAGE_APP_JS


def chrome_hider_html() -> str:
    """返回补好 `<script>` 外壳、可直接交给 `st.html` 的负载。

    Raises:
        ChromeScriptUnsafe: 出现 `</script`（内联会提前闭合），或出现
            「`<` + `[A-Za-z0-9_!/]`」（DOMPurify 会把整条丢光）。
    """
    if _SCRIPT_BREAK.search(_MANAGE_APP_JS):
        raise ChromeScriptUnsafe("脚本里出现了 `</script`：内联会被提前闭合。")
    killer = _PURIFY_KILLER.search(_MANAGE_APP_JS)
    if killer:
        around = _MANAGE_APP_JS[max(0, killer.start() - 30):killer.start() + 30].replace("\n", " ")
        raise ChromeScriptUnsafe(
            "脚本里出现了 DOMPurify 会整条丢弃的序列 "
            + repr(killer.group(0)) + "（附近：..." + around + "...）"
        )
    return "<script>\n" + _MANAGE_APP_JS + "\n</script>"


def hide_manage_app() -> Optional[str]:
    """把隐藏脚本注入页面；返回实际使用的注入方式（"st.html" / "components" / None）。

    与 cloud_badge 的双路径一致，但**顺序相反**：这里优先 `components.html(height=0)`。
    原因：`st.html` 会在主内容流里留一个空元素，Streamlit 的 stVerticalBlock 有
    ~1rem 的 `gap`，即使高度为 0 也会把整页内容下推一格（本应用对顶部留白是
    逐像素调过的）。而 `components.html` 的 0 高度 iframe 已被 app.py 里那条
    `:has(> iframe[title="st.iframe"])` 规则彻底 `display:none`，**不占布局**；
    隐藏 iframe 仍会执行脚本（写身份 Cookie 早已端到端复验），srcdoc iframe
    与父页面同源，跨文档爬升照样成立。
    `st.html(unsafe_allow_javascript=True)` 仅作老版本兜底（components 不可用时）。
    """
    try:
        import streamlit as st
    except Exception:
        return None

    try:
        payload = chrome_hider_html()
    except ChromeScriptUnsafe:
        return None

    try:
        from streamlit.components.v1 import html as _components_html
        _components_html(payload, height=0)
        return "components"
    except Exception:
        pass

    try:
        st.html(payload, unsafe_allow_javascript=True)
        return "st.html"
    except Exception:
        return None

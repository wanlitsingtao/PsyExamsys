# -*- coding: utf-8 -*-
"""页面头部版式回归（v2.9.15）：去掉四个模块的页内大标题与多余分割线。

用户 2026-11-09 反馈（手机/PC 截图）
    1. 专项训练 / 巩固练习 / 错题本 / 助记助学 顶部的「大标题 + 分割线」是多余的
       —— 左侧栏已经高亮当前模块，标题重复且把内容往下推；
    2. 首页「📊 数据统计」是 h1，比「🚀 选择考试科目」(h3) 大太多，要统一成 h3；
    3. 「选择考试科目」上方那条分割线多余（页面最顶部，本就没有上文）；
    4. 右侧主界面与左侧栏的首行没有顶对齐。

根因（第 4 条）
    首页标题是 <h3> 吗？不是 —— 真正让两边差 14~24px 的是三件事：
      · Streamlit 给 heading 加了 13.5px 的 padding-top（锚点偏移），正文 <p> 没有；
      · 主内容 stVerticalBlock 前面有多个高度 0 的注入容器（Cookie 写入 iframe、
        云宿主净化脚本…），它们仍各占一个 6.3px 的 flex gap；
      · .block-container 的 padding-top 与侧栏头部高度不成比例。
    三者叠加 → 标题页比正文页低，整体又比侧栏低/高。修法见 app.py 的 CSS 注释。

检查项（20 项，含 5 条阴性对照）
    A. 四个模块不再渲染页面级标题（AST 取函数体判断）+ 4 条阴性对照
    B. 首页标题降为 h3，与「选择考试科目」同级 + 阴性对照
    C. 模拟考两个开始页的顶部分割线已删 + 阴性对照
    D. 顶对齐三条 CSS 规则都在（padding 必须 > 白底 header 3.75rem / heading 归零 / 空 style 容器不占位）+ 阴性对照
    E. 行为：AppTest 打开首页，第一个 markdown 就是 "### 📊 数据统计"
    F. 四个「成绩报告 / 总成绩」结果页标题是 h3（v2.9.16：原 h1 在 18px 根字号下是 49.5px 大字）+ 阴性对照

运行：python scripts/test_page_header_layout.py
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

PAGES = ROOT / "pages"
APP = ROOT / "app.py"
_passed = []


def ok(msg):
    _passed.append(msg)
    print(f"✅ {len(_passed):2d}. {msg}")


def func_src(src: str, name: str) -> str:
    """取指定函数的源码段（找不到返回空串）。"""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    return ""


def has_page_heading(src: str, name: str, heading: str) -> bool:
    """函数体里是否还渲染着页面级标题（h1 的 markdown / st.title）。"""
    body = func_src(src, name)
    return (f'st.markdown("{heading}")' in body) or (f"st.title({heading!r})" in body) \
        or (f'st.title("{heading}")' in body)


def main():
    spec_src = (PAGES / "specialized.py").read_text(encoding="utf-8")
    consol_src = (PAGES / "consolidation.py").read_text(encoding="utf-8")
    wb_src = (PAGES / "wrongbook.py").read_text(encoding="utf-8")
    mn_src = (PAGES / "mnemonic.py").read_text(encoding="utf-8")
    stat_src = (PAGES / "statistics.py").read_text(encoding="utf-8")
    mock_src = (PAGES / "mock_exam.py").read_text(encoding="utf-8")
    app_src = APP.read_text(encoding="utf-8")

    print("=" * 70)
    print("页面头部版式：标题去除 / h3 统一 / 顶对齐")
    print("=" * 70)

    # ---------------- A. 四个模块的页面标题已删 ----------------
    checks = [
        ("专项训练", spec_src, "_show_spec_start", "# 🎯 专项训练"),
        ("巩固练习", consol_src, "_show_consol_start", "# 🎯 巩固练习"),
        ("错题本", wb_src, "_show_wrongbook_home", "# 📕 错题本"),
        ("助记助学", mn_src, "show_mnemonic", "🧠 助记助学"),
    ]
    for label, src, fn, heading in checks:
        assert func_src(src, fn), f"没找到函数 {fn}（源码结构变了？）"
        assert not has_page_heading(src, fn, heading), \
            f"{label} 的页面级标题没删掉（{fn} 里仍在渲染 {heading}）"
        ok(f"{label}：{fn} 不再渲染页面级标题")

    # 阴性对照：把标题塞回函数体（2026-11-10 说明文案扩写成多行 markdown，
    # 锚点改用取配置那一行，避免在字符串拼接中间插语句导致语法错误）
    nc = consol_src.replace(
        '    _per_round = int(load_config().get("consol_per_round", 60) or 60)',
        '    st.markdown("# 🎯 巩固练习")\n'
        '    _per_round = int(load_config().get("consol_per_round", 60) or 60)',
        1,
    )
    assert nc != consol_src, "阴性对照锚点没匹配上（巩固练习首行变了？）"
    assert has_page_heading(nc, "_show_consol_start", "# 🎯 巩固练习"), \
        "阴性对照失效：塞回标题后检查函数仍判定为「已删除」"
    ok("阴性对照：把标题塞回巩固练习 → A 的检查变红")

    # ---------------- B. 首页标题降为 h3 ----------------
    assert 'st.markdown("### 📊 数据统计")' in stat_src, \
        "首页标题不是 h3（应与「选择考试科目」同级）"
    assert 'st.markdown("# 📊 数据统计")' not in stat_src, \
        "statistics.py 里还残留 h1 版「数据统计」"
    ok("首页「📊 数据统计」为 h3，与模拟考「🚀 选择考试科目」同级")

    nc_b = stat_src.replace('st.markdown("### 📊 数据统计")', 'st.markdown("# 📊 数据统计")', 1)
    assert nc_b != stat_src
    assert 'st.markdown("### 📊 数据统计")' not in nc_b, "阴性对照失效：改回 h1 后仍被判为 h3"
    ok("阴性对照：把首页标题改回 h1 → B 变红")

    # ---------------- C. 模拟考开始页顶部分割线已删 ----------------
    for fn in ("_show_mock_start_four", "_show_mock_start_junior"):
        body = func_src(mock_src, fn)
        assert body, f"没找到 {fn}"
        # 函数体里第一处 markdown 若是 "---" 就是多余的顶部分割线
        first_md = next((ln.strip() for ln in body.splitlines()
                         if 'st.markdown(' in ln and ln.strip().startswith('st.markdown(')), "")
        assert 'st.markdown("---")' != first_md, \
            f"{fn} 的首个 markdown 仍是分割线（页面顶部那条）"
        ok(f"{fn}：页面顶部不再有分割线")

    nc_c = mock_src.replace(
        '    st.markdown("### 🚀 选择考试科目")',
        '    st.markdown("---")\n    st.markdown("### 🚀 选择考试科目")', 1)
    assert nc_c != mock_src
    _body = func_src(nc_c, "_show_mock_start_four")
    _first = next((ln.strip() for ln in _body.splitlines()
                   if ln.strip().startswith('st.markdown(')), "")
    assert _first == 'st.markdown("---")', "阴性对照失效：插回分割线后首个 markdown 不是 ---"
    ok("阴性对照：把分割线插回「选择考试科目」上方 → C 变红")

    # ---------------- D. 顶对齐的三条 CSS ----------------
    flat = app_src.replace("{{", "{").replace("}}", "}")
    flat = __import__("re").sub(r"/\*.*?\*/", "", flat, flags=__import__("re").S)

    # ① 顶部留白：Streamlit 的 header 是 position:absolute + 白底 + z-index:999990，
    #    高度 3.75rem —— 本项目根字号 18px ⇒ 67.5px。写死 62px 时首个卡片的顶边框
    #    有 5.5px 被白条盖住（用户 2026-11-10 反馈「遮挡一点文字或卡片边框」）。
    pad_m = __import__("re").search(r"padding-top:\s*(calc\(\s*3\.75rem\s*\+\s*\d+(?:\.\d+)?px\s*\))\s*!important", flat)
    assert pad_m, "找不到 .block-container 的 `padding-top: calc(3.75rem + Npx) !important`"
    pad_val = pad_m.group(1).strip()
    pm = __import__("re").search(r"3\.75rem\s*\+\s*(\d+(?:\.\d+)?)px", pad_val)
    assert pm, f"padding-top 里没有 Npx 余量（现为 {pad_val!r}）"
    pad_px = 3.75 * 18 + float(pm.group(1))   # 本项目根字号 18px
    header_px = 3.75 * 18                     # header 高度（同 rem）
    assert pad_px > header_px, \
        f"顶部留白 {pad_px}px 未超过白底 header {header_px}px，首个元素会被遮住一截"
    ok(f".block-container padding-top = {pad_px:g}px > header {header_px:g}px（首个元素不被白条遮挡）")

    heading_rule = __import__("re").search(
        r"\.block-container h1,\s*\.block-container h2,\s*\.block-container h3,\s*\.block-container h4\s*\{[^}]*padding-top:\s*0", flat)
    assert heading_rule, "缺少「主内容标题 padding-top 归零」规则（标题页会比正文页低 13.5px）"
    ok("主内容 h1~h4 的锚点内边距已归零（标题页与正文页同基线）")

    style_rule = __import__("re").search(
        r'\[data-testid="stElementContainer"\]:has\(style\)[^{]*\{[^}]*display:\s*none', flat)
    assert style_rule, "缺少「只含 <style> 的空容器不占位」规则（专项训练页会低 24px）"
    ok("只含 <style> 的 0 高度容器已不参与布局")

    nc_d = app_src.replace("calc(3.75rem + 4px)", "62px", 1)
    assert nc_d != app_src, "阴性对照锚点没匹配上（padding-top 写法变了？）"
    assert "calc(3.75rem + 4px)" not in nc_d, "阴性对照失效：改回 62px 后断言仍通过"
    ok("阴性对照：把 padding-top 改回 62px → D 变红")

    # ---------------- E. 行为：首页首个 markdown ----------------
    from _testenv import point_app_at_copy, snapshot_real_db, assert_real_db_untouched, cleanup
    before = snapshot_real_db()
    tmp = point_app_at_copy()
    try:
        import utils.data_access as da
        import utils.data_manager as dm
        da.SQLITE_DB = tmp / "exmsys.db"
        dm.SQLITE_DB = da.SQLITE_DB
        dm.DATA_DIR = tmp
        dm.BACKUP_DIR = tmp / "backup"
        dm.DRAFTS_DIR = tmp / "drafts"
        da.reset_data_access()
        dm._dao = None
        dm._current_user_id = None

        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(APP), default_timeout=240)
        at.run()
        assert not at.exception, f"应用起不来：{[str(e.value) for e in at.exception]}"
        values = [str(getattr(m, "value", "")) for m in at.markdown]
        assert "### 📊 数据统计" in values, "首页没有渲染 h3 版「数据统计」"
        assert "# 📊 数据统计" not in values, "首页仍渲染 h1 版「数据统计」"
        ok("AppTest：首页实际渲染的第一个标题是 h3「📊 数据统计」")

        assert_real_db_untouched(*before)
    finally:
        if str(tmp) != str(ROOT / "data"):
            cleanup(tmp)

    # ---------------- F. 结果页（成绩报告 / 总成绩）标题降为 h3 ----------------
    # 18px 根字号下 h1 = 49.5px、h3 = 31.5px。用户 2026-11-09 反馈成绩报告标题太大，
    # 与答题页的「### 🎯 巩固练习」不一致 → 四个结果页标题统一 h3（v2.9.16）。
    report_heads = [
        ("巩固练习成绩报告", consol_src,
         'st.markdown("### 🎯 巩固练习 - 成绩报告")',
         'st.markdown("# 🎯 巩固练习 - 成绩报告")'),
        ("综合/专项训练报告", spec_src,
         'st.markdown(f"### 📊 {mode_label}报告：**{category}**")',
         'st.markdown(f"# 📊 {mode_label}报告：**{category}**")'),
        ("模拟考单科成绩报告", mock_src,
         'st.markdown(f"### 📊 {cfg[\'name\']} - 成绩报告")',
         'st.markdown(f"# 📊 {cfg[\'name\']} - 成绩报告")'),
        ("模拟考总成绩", mock_src,
         'st.markdown("### 🏆 模拟考试 - 总成绩")',
         'st.markdown("# 🏆 模拟考试 - 总成绩")'),
    ]
    for label, src, h3_md, h1_md in report_heads:
        assert h3_md in src, f"{label} 标题不是 h3（h1 在 18px 根字号下是 49.5px 大字）"
        assert h1_md not in src, f"{label} 仍残留 h1 版标题"
        ok(f"{label}：标题为 h3")

    nc_f = consol_src.replace(
        'st.markdown("### 🎯 巩固练习 - 成绩报告")',
        'st.markdown("# 🎯 巩固练习 - 成绩报告")', 1)
    assert nc_f != consol_src, "阴性对照锚点没匹配上（成绩报告标题又变了？）"
    assert 'st.markdown("### 🎯 巩固练习 - 成绩报告")' not in nc_f, \
        "阴性对照失效：改回 h1 后仍被判为 h3"
    ok("阴性对照：把成绩报告标题改回 h1 → F 变红")

    print("\n" + "=" * 70)
    print(f"✅ 全部通过（{len(_passed)} 项）")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print(f"\n❌ 验收失败：{e}")
        raise SystemExit(1)

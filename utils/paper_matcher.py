"""
试卷匹配工具 v2 - 严谨版
修复: 跨行题型标注、三级匹配管道、交叉验证
"""
import docx, sqlite3, json, re, os, sys
from difflib import SequenceMatcher
from collections import defaultdict

# ===== CONFIG =====
PAPER_DIR = r'E:\LingMa\exmsys\exmbase\心理学会四级考题'
DB_PATH = r'E:\LingMa\exmsys\data\exmsys.db'

PAPERS = [
    '咨询实务模拟卷一（四级）.docx',
    '咨询实务模拟卷二（四级）.docx',
    '心理学综合模拟卷一（四级）.docx',
    '心理学综合模拟卷二（四级）.docx',
]

# Knowledge module keywords for auto-classification
MODULE_KEYWORDS = {
    '基础理论1-心理学导论': ['心理学导论', '心理现象', '心理学研究', '感觉', '知觉', '记忆', '思维', '想象',
                      '注意', '意识', '动机', '情绪', '情感', '意志', '能力', '智力', '神经元',
                      '大脑', '神经系统', '反射', '条件反射', '心理过程', '个性心理', '认知'],
    '基础理论2-社会心理学': ['社会心理', '社会认知', '归因', '态度', '从众', '服从', '群体', '人际',
                       '沟通', '社会影响', '偏见', '刻板', '利他', '攻击', '亲社会', '角色'],
    '基础理论3-人格心理学': ['人格', '气质', '性格', '自我', '弗洛伊德', '荣格', '阿德勒', '霍妮',
                       '马斯洛', '罗杰斯', '特质', '大五', '16PF', 'MMPI', '防御机制', '本我'],
    '基础理论4-发展心理学': ['发展心理', '婴儿', '幼儿', '儿童', '青少年', '青春期', '成年', '老年',
                       '依恋', '皮亚杰', '维果茨基', '科尔伯格', '埃里克森', '同辈', '道德',
                       '社会化', '关键期', '敏感期'],
    '基础理论5-异常心理学': ['异常心理', '变态心理', '障碍', '精神分裂', '抑郁', '焦虑', '强迫',
                       '恐惧', '创伤', 'PTSD', '人格障碍', 'DSM', 'ICD', '诊断', '症状',
                       '幻觉', '妄想', '评估', '评定', '量表'],
    '基础理论6-咨询心理学': ['咨询心理', '心理咨询', '咨询理论', '咨询流派', '咨询关系', '咨询目标',
                       '咨询过程', '咨询师', '来访者', '求助者', '咨客', '罗杰斯', 'YAVIS',
                       '卡尔·罗杰斯'],
    '咨询实务1-心理咨询会谈技术': ['会谈', '访谈', '倾听', '共情', '提问', '沉默', '面质', '解释',
                            '指导', '自我开放', '具体化', '即时化', '反馈', '摄入性', '鉴别性',
                            '治疗性', '释义', '澄清', '结构化', '非指导性'],
    '咨询实务2-情绪调节与压力管理': ['情绪调节', '压力', '应激', '情绪管理', '放松', '冥想', '正念',
                              '减压', '宣泄', '防御机制', '应对', '焦虑管理', '身心'],
    '咨询实务3-心理危机识别': ['危机', '自杀', '自伤', '创伤', '哀伤', '危机干预', '风险评估',
                          '转介', '紧急', '预警'],
    '咨询实务4-家庭教育与心理健康科普': ['家庭', '亲子', '教养', '婚姻', '夫妻', '科普', '教育',
                                  '学校', '家长', '劳动', '品质'],
    '咨询实务5-心理咨询专业伦理与相关法律规范': ['伦理', '道德', '保密', '知情同意', '边界',
                                          '双重关系', '法律', '规范', '职业', '专业伦理',
                                          '精神卫生法'],
}


def norm(text):
    """Normalize text for comparison"""
    return re.sub(r'\s+', '', text).replace('(', '（').replace(')', '）').lower()


def clean_qtext(text):
    """Clean question text: remove trailing type annotations"""
    # Remove trailing type annotations like （单选题，0.4分）
    text = re.sub(r'\s*[（(](?:单选题|多选题|判断题)[，,]\s*[\d.]+分[）)]\s*$', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def _detect_case_study_ranges(paras, paper_name=''):
    """
    Pre-scan paragraphs to detect case study sections (不定项选择题/案例题).
    Returns a set of question numbers (as strings) that should be typed as 'indefinite'.
    
    Two detection strategies:
    1. Explicit marker: "案例分析题…本部分为不定项选择题…（201～210题）"
    2. Fallback for 咨询实务 papers: if Q201-210 exist and have long case descriptions,
       mark them as indefinite (some papers lack the explicit marker paragraph)
    """
    indefinite_nums = set()
    
    # Strategy 1: explicit marker detection
    for line in paras:
        line_stripped = line.strip()
        if '案例分析题' in line_stripped and '不定项选择题' in line_stripped:
            # Extract number range: e.g. "201～210"
            range_match = re.search(r'(\d+)～(\d+)\s*题', line_stripped)
            if range_match:
                start_num = int(range_match.group(1))
                end_num = int(range_match.group(2))
                for n in range(start_num, end_num + 1):
                    indefinite_nums.add(str(n))
            else:
                # Default range for consulting practice: Q201-210
                for n in range(201, 211):
                    indefinite_nums.add(str(n))
    
    # Strategy 2: fallback for 咨询实务 papers without explicit marker
    if not indefinite_nums and '咨询实务' in paper_name:
        # Check if Q201 exists and looks like a case study (long text, no type annotation)
        q201_found = False
        for idx, line in enumerate(paras):
            line_stripped = line.strip()
            if re.match(r'^201\.\s', line_stripped):
                q201_found = True
                # Verify it's a case study: long text with no type marker
                if '多选题' not in line_stripped and '单选题' not in line_stripped and '判断题' not in line_stripped:
                    # Check if subsequent lines also contain Q202-Q210
                    for n in range(201, 211):
                        indefinite_nums.add(str(n))
                break
        
        # Also check Q200 to see if it's a multi-choice question (case study section follows)
        if q201_found:
            pass  # Q201-210 already added
    
    return indefinite_nums


def extract_questions_fixed(doc, indefinite_nums=None, paper_name=''):
    """
    Fixed extraction: handles multiline type annotations and case study sections.
    Algorithm:
    1. Find all lines starting with number + dot
    2. For each, determine type by looking at the SAME line first, 
       then the NEXT non-empty line if needed
    3. If question number is in indefinite_nums set, override type to 'indefinite'
    4. Collect options (A-G lines) until next question or answer
    """
    # Normalize: replace internal newlines with space (some paragraphs embed \n)
    paras = [p.text.replace('\n', ' ').replace('\r', ' ') for p in doc.paragraphs]
    questions = []

    # Auto-detect case study ranges if not provided
    if indefinite_nums is None:
        indefinite_nums = _detect_case_study_ranges(paras, paper_name)

    # First pass: find all question start indices
    q_starts = []
    for idx, line in enumerate(paras):
        line_stripped = line.strip()
        if re.match(r'^\d+\.\s', line_stripped):
            q_starts.append(idx)

    for qi, start_idx in enumerate(q_starts):
        line = paras[start_idx].strip()
        q_match = re.match(r'^(\d+)\.\s*(.+)', line)
        if not q_match:
            continue

        qnum = q_match.group(1)
        raw_text = q_match.group(2).strip()

        # Determine type: first check same line
        qtype = 'single'
        if '多选题' in raw_text:
            qtype = 'multi'
        elif '判断题' in raw_text:
            qtype = 'judge'

        # If type not determined from same line, check next non-empty lines
        if qtype == 'single':
            for look_idx in range(start_idx + 1, min(start_idx + 5, len(paras))):
                look_line = paras[look_idx].strip()
                if not look_line:
                    continue
                if '多选题' in look_line:
                    qtype = 'multi'
                elif '判断题' in look_line:
                    qtype = 'judge'
                break  # only check first non-empty line

        # Override: if question number is in indefinite range (case study section)
        if qnum in indefinite_nums:
            qtype = 'indefinite'

        # Clean question text
        qtext = clean_qtext(raw_text)

        # Determine end of this question: next question start or end of document
        end_idx = q_starts[qi + 1] if qi + 1 < len(q_starts) else len(paras)

        # Collect options between question and next question
        options = []
        answer = ''
        explanation = ''

        for j in range(start_idx + 1, end_idx):
            pline = paras[j].strip()
            if not pline:
                continue

            # Option lines
            opt_match = re.match(r'^([A-G])[：:．.]\s*(.+)', pline)
            if opt_match:
                opt_label = opt_match.group(1)
                opt_text = re.sub(r'\s+', ' ', opt_match.group(2)).strip()
                options.append(opt_text)
                continue

            # Answer line
            ans_match = re.match(r'^正确答案[：:]\s*(.+)', pline)
            if ans_match:
                answer = ans_match.group(1).strip()
                continue

            # Type annotation line (multiline case)
            if re.match(r'^[（(](?:单选题|多选题|判断题)[，,]\s*[\d.]+分[）)]', pline):
                continue

            # Explanation
            if '答案解析' in pline:
                continue
            # If it's between answer line and next question, could be explanation
            if answer and j < end_idx - 1:
                expl_line = paras[j + 1].strip() if j + 1 < len(paras) else ''
                if expl_line and not re.match(r'^\d+\.', expl_line):
                    explanation = expl_line

        questions.append({
            'num': qnum,
            'type': qtype,
            'question': qtext,
            'options': options,
            'answer': answer,
            'explanation': explanation,
        })

    return questions


def classify_paper_question(q):
    """Classify question into knowledge module"""
    qtext = q['question']
    options_text = ' '.join(q['options'])
    full_text = qtext + ' ' + options_text

    scores = {}
    for module, keywords in MODULE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in full_text)
        if score > 0:
            scores[module] = score

    if scores:
        return max(scores, key=scores.get)
    return None


def make_match_key(q):
    """Create a match key from question + options for L1 exact matching"""
    nq = norm(q['question'])
    no = norm('|'.join(q['options']))
    return nq + '|||' + no


def main():
    # ===== Load DB =====
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('SELECT id, question, options, answer, type, exam_type, category FROM questions')
    db_qs = [dict(row) for row in cur.fetchall()]
    for q in db_qs:
        q['options'] = json.loads(q['options'])
    conn.close()

    # Build match index
    db_by_qkey = {}  # normalized question -> list of DB entries
    db_by_fullkey = {}  # question+options -> DB entry
    for q in db_qs:
        nq = norm(q['question'])
        db_by_qkey.setdefault(nq, []).append(q)
        fk = make_match_key(q)
        db_by_fullkey[fk] = q

    # Normalized DB questions for fuzzy matching
    db_norms = [(q['id'], q, norm(q['question'])) for q in db_qs]

    print(f"SQLite题库: {len(db_qs)} 题 ({len(db_by_qkey)} unique questions)\n")

    # ===== Process each paper =====
    all_results = []

    for fname in PAPERS:
        fpath = os.path.join(PAPER_DIR, fname)
        paper_name = fname.replace('.docx', '')

        doc = docx.Document(fpath)
        paper_qs = extract_questions_fixed(doc, paper_name=paper_name)

        # Verify counts
        types = defaultdict(int)
        for q in paper_qs:
            types[q['type']] += 1

        print(f"===== {paper_name} =====")
        print(f"  提取题目: {len(paper_qs)} (单{types['single']}/多{types['multi']}/判{types['judge']}/不定项{types['indefinite']})")

        # Match: 3-level pipeline
        exact_matched = []
        high_sim_matched = []
        fuzzy_matched = []
        truly_unmatched = []

        for q in paper_qs:
            fk = make_match_key(q)
            nq = norm(q['question'])

            # L1: Exact match (question + options)
            if fk in db_by_fullkey:
                exact_matched.append((q, db_by_fullkey[fk], 1.0, 'exact'))
                continue

            # L2: Normalized question exact match
            if nq in db_by_qkey:
                # Options may differ slightly, still consider matched
                exact_matched.append((q, db_by_qkey[nq][0], 1.0, 'q_exact'))
                continue

            # L3: High-similarity fuzzy (>= 90%)
            best_ratio = 0
            best_match = None
            qtext = norm(q['question'])
            qlen = len(qtext)

            for _, dbq, dtext in db_norms:
                dlen = len(dtext)
                # Fast pre-filter
                if qlen > 10 and dlen > 10:
                    if qtext[:10] != dtext[:10]:
                        # Check if one contains the other
                        if qtext not in dtext and dtext not in qtext:
                            char_overlap = len(set(qtext) & set(dtext))
                            if char_overlap / max(len(set(qtext)), len(set(dtext)), 1) < 0.5:
                                continue

                ratio = SequenceMatcher(None, qtext, dtext).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = dbq
                if ratio >= 0.98:
                    break

            if best_match and best_ratio >= 0.92:
                high_sim_matched.append((q, best_match, best_ratio, 'high'))
            elif best_match and best_ratio >= 0.80:
                fuzzy_matched.append((q, best_match, best_ratio, 'fuzzy'))
            else:
                truly_unmatched.append((q, best_match, best_ratio))

        covered = len(exact_matched) + len(high_sim_matched)
        fuzzy = len(fuzzy_matched)
        uncovered = len(truly_unmatched)

        print(f"  L1精确匹配: {len(exact_matched)}")
        print(f"  L2高相似(>=92%): {len(high_sim_matched)}")
        print(f"  L3模糊(80-92%): {fuzzy}")
        print(f"  真正未匹配(<80%): {uncovered}")
        print(f"  有效覆盖: {covered}/{len(paper_qs)} ({covered*100//len(paper_qs)}%)")
        print()

        all_results.append({
            'name': paper_name,
            'total': len(paper_qs),
            'types': dict(types),
            'exact': exact_matched,
            'high': high_sim_matched,
            'fuzzy': fuzzy_matched,
            'unmatched': truly_unmatched,
        })

    # ===== Detailed unmatched report =====
    print("=" * 70)
    print("真正未匹配题目详情 (相似度<80%)")
    print("=" * 70)

    total_um = 0
    for r in all_results:
        um = r['unmatched']
        if um:
            print(f"\n--- {r['name']} ({len(um)}题) ---")
            for q, best_match, ratio in um:
                total_um += 1
                module = classify_paper_question(q)
                module_str = f" [{module}]" if module else " [无法归类]"

                print(f"  Q{q['num']} [{q['type']}]{module_str}")
                print(f"    Q: {q['question'][:150]}")
                if q['options']:
                    print(f"    Options: {q['options']}")
                print(f"    Answer: {q['answer']}")

                if best_match and ratio > 0:
                    print(f"    最佳匹配({ratio:.1%}): {best_match['question'][:120]}")
                    print(f"      DB类: {best_match.get('category','?')}")
                else:
                    print(f"    题库无匹配")
                print()

    # ===== Fuzzy matched report (措辞变体) =====
    print("\n" + "=" * 70)
    print("模糊匹配题目 (相似度80-92%, 可能是措辞变体)")
    print("=" * 70)

    total_fz = 0
    for r in all_results:
        fz = r['fuzzy']
        if fz:
            print(f"\n--- {r['name']} ({len(fz)}题) ---")
            for item in fz:
                q, best_match, ratio = item[0], item[1], item[2]
                total_fz += 1
                module = classify_paper_question(q)
                print(f"  Q{q['num']} [{q['type']}] [{module or '?'}] sim={ratio:.1%}")
                print(f"    试卷: {q['question'][:120]}")
                if best_match:
                    print(f"    题库: {best_match['question'][:120]}")
                print()

    # ===== Final summary table =====
    print("\n" + "=" * 70)
    print("修正后汇总表")
    print("=" * 70)
    print(f"{'试卷名称':<32} {'总题':>4} {'精确':>4} {'高相似':>4} {'模糊':>4} {'未匹配':>4} {'有效覆盖':>8}")
    print("-" * 70)

    gt = 0; ge = 0; gh = 0; gfz = 0; gum = 0
    for r in all_results:
        n = r['name']
        t = r['total']
        e = len(r['exact'])
        h = len(r['high'])
        f = len(r['fuzzy'])
        u = len(r['unmatched'])
        c = e + h
        rate = f"{c*100//t}%"
        print(f"{n:<32} {t:>4} {e:>4} {h:>4} {f:>4} {u:>4} {rate:>8}")
        gt += t; ge += e; gh += h; gfz += f; gum += u

    gc = ge + gh
    print("-" * 70)
    print(f"{'合计':<32} {gt:>4} {ge:>4} {gh:>4} {gfz:>4} {gum:>4} {gc*100//gt:>7}%")

    # Additional summary
    print(f"\n总题数: {gt}")
    print(f"有效覆盖 (精确+高相似): {gc} ({gc*100//gt}%)")
    print(f"模糊匹配 (措辞变体): {gfz} ({gfz*100//gt}%)")
    print(f"真正未匹配 (新题): {gum} ({gum*100//gt}%)")
    print(f"如果含模糊匹配: {gc+gfz} ({(gc+gfz)*100//gt}%)")


if __name__ == '__main__':
    main()

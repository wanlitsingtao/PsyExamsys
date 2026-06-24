"""
新题导入脚本：从4套模拟试卷中提取184道未匹配题，分类到知识板块，写入SQLite题库。

集成 paper_matcher 三级匹配管道（精确→高相似→模糊→未匹配），
仅导入 similarity < 80% 的确认新题。

用法：python utils/import_new_questions.py
  --dry-run  仅显示将要导入的题目，不实际写入
  --yes       跳过确认直接导入
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import docx
import json
import hashlib
import re
from collections import defaultdict
from difflib import SequenceMatcher

# Reuse paper_matcher modules
from utils.paper_matcher import (
    extract_questions_fixed, classify_paper_question, make_match_key,
    norm, clean_qtext, MODULE_KEYWORDS, PAPER_DIR, PAPERS,
)
from utils.data_manager import _get_dao

# ===== Module key to clean name mapping =====
MODULE_KEY_TO_NAME = {}
for key in MODULE_KEYWORDS:
    parts = key.split('-', 1)
    MODULE_KEY_TO_NAME[key] = parts[1] if len(parts) > 1 else key


def list_to_dict_options(options_list):
    """Convert options list ['textA', 'textB', ...] to dict {'A': 'textA', 'B': 'textB', ...}"""
    result = {}
    for i, opt in enumerate(options_list):
        key = chr(ord('A') + i)
        result[key] = opt
    return result


def derive_module_name(module_key):
    """Convert module key to clean module name"""
    return MODULE_KEY_TO_NAME.get(module_key, module_key)


def _sanitize_answer(text):
    """清洗答案中的不可见/干扰字符（零宽空格、BOM等），与 parser._sanitize_answer 保持一致"""
    if not text:
        return ""
    text = text.replace("\u200b", "")
    text = text.replace("\u200c", "")
    text = text.replace("\u200d", "")
    text = text.replace("\u200e", "")
    text = text.replace("\u200f", "")
    text = text.replace("\ufeff", "")
    text = text.replace("\ufe0f", "")
    text = text.replace("\u00a0", " ")
    return text


def finalize_question(q):
    """Generate ID/MD5 and normalize (reuses parser._finalize_question logic)"""
    q['type'] = q.get('type', 'single')
    
    if q['type'] == 'judge' and not q.get('options'):
        q['options'] = {'A': '正确', 'B': '错误'}
    
    if q['type'] == 'judge':
        ans = q.get('answer', '').strip()
        if ans in ('A', '正确', '对', '\u221a', 'true', 'True'):
            q['answer'] = 'A'
        elif ans in ('B', '错误', '错', '\u00d7', 'false', 'False'):
            q['answer'] = 'B'
    
    if q['type'] in ('multi', 'indefinite'):
        ans = q.get('answer', '').upper().replace(' ', '').replace('\uff0c', '').replace(',', '')
        ans = ''.join(sorted(set(ans)))
        q['answer'] = ans
    
    if q['type'] == 'single':
        q['answer'] = q.get('answer', '').strip().upper()
    
    # 清洗答案中的不可见字符（与 parser._finalize_question 保持一致）
    q['answer'] = _sanitize_answer(q['answer'])
    
    options_items = sorted(q.get('options', {}).items())
    content = q.get('question', '') + str(options_items) + q.get('answer', '')
    md5_hash = hashlib.md5(content.encode('utf-8')).hexdigest()
    q['md5'] = md5_hash
    q['id'] = md5_hash[:12]
    
    return q


def build_match_index(db_questions):
    """Build match index from DB questions"""
    db_by_qkey = {}
    db_by_fullkey = {}
    for q in db_questions:
        nq = norm(q['question'])
        db_by_qkey.setdefault(nq, []).append(q)
        fk = make_match_key(q)
        db_by_fullkey[fk] = q
    
    db_norms = [(q['id'], q, norm(q['question'])) for q in db_questions]
    
    return db_by_qkey, db_by_fullkey, db_norms


def match_paper_question(paper_q, db_by_qkey, db_by_fullkey, db_norms):
    """
    Match a paper question against DB using 3-level pipeline.
    Returns: (match_status, db_match, similarity)
      match_status: 'exact' | 'high' | 'fuzzy' | 'unmatched'
    """
    fk = make_match_key(paper_q)
    nq = norm(paper_q['question'])
    
    # L1: Exact match
    if fk in db_by_fullkey:
        return 'exact', db_by_fullkey[fk], 1.0
    
    if nq in db_by_qkey:
        return 'exact', db_by_qkey[nq][0], 1.0
    
    # L2-L4: Fuzzy match
    best_ratio = 0
    best_match = None
    qtext = norm(paper_q['question'])
    qlen = len(qtext)
    
    for _, dbq, dtext in db_norms:
        dlen = len(dtext)
        if qlen > 10 and dlen > 10:
            if qtext[:10] != dtext[:10]:
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
        return 'high', best_match, best_ratio
    elif best_match and best_ratio >= 0.80:
        return 'fuzzy', best_match, best_ratio
    else:
        return 'unmatched', best_match, best_ratio


def main(dry_run=False, auto_confirm=False):
    print("=" * 70)
    print("新题导入脚本：三级匹配管道 -> 仅导入确认新题(sim<80%)")
    print("=" * 70)
    
    # ===== Load existing DB questions =====
    existing = load_db_questions()
    print(f"\n现有题库: {len(existing)} 题")
    
    # ===== Build match index =====
    db_by_qkey, db_by_fullkey, db_norms = build_match_index(existing)
    
    # ===== Process each paper =====
    all_unmatched = []
    paper_summary = {}
    total_stats = {'exact': 0, 'high': 0, 'fuzzy': 0, 'unmatched': 0}
    
    for fname in PAPERS:
        fpath = os.path.join(PAPER_DIR, fname)
        paper_name = fname.replace('.docx', '')
        
        doc = docx.Document(fpath)
        paper_qs = extract_questions_fixed(doc, paper_name=paper_name)
        
        # Match each question
        unmatched = []
        exact = high = fuzzy = unm = 0
        types_count = defaultdict(int)
        
        for q in paper_qs:
            types_count[q['type']] += 1
            
            status, db_match, sim = match_paper_question(
                q, db_by_qkey, db_by_fullkey, db_norms
            )
            
            if status == 'exact':
                exact += 1
            elif status == 'high':
                high += 1
            elif status == 'fuzzy':
                fuzzy += 1
            else:  # unmatched -> new question
                unm += 1
                
                # Determine module
                module_key = classify_paper_question(q)
                module_name = derive_module_name(module_key) if module_key else ''
                
                # Convert options to dict
                options_dict = list_to_dict_options(q['options'])
                
                # Build question record
                record = {
                    'source_file': fname,
                    'index': int(q['num']),
                    'type': q['type'],
                    'question': q['question'],
                    'options': options_dict,
                    'answer': q['answer'],
                    'explanation': q.get('explanation', ''),
                    'category': module_name,
                    'exam_type': '心理学会咨询师四级',
                }
                finalize_question(record)
                
                # Additional dedup: check MD5 against already processed
                record_key = (record['md5'])
                
                unmatched.append(record)
        
        total_stats['exact'] += exact
        total_stats['high'] += high
        total_stats['fuzzy'] += fuzzy
        total_stats['unmatched'] += unm
        
        types_str = ', '.join(f'{t}:{c}' for t, c in sorted(types_count.items()))
        covered = exact + high
        rate = f"{covered*100//len(paper_qs)}%"
        print(f"\n{paper_name}:")
        print(f"  提取: {len(paper_qs)} ({types_str})")
        print(f"  精确:{exact} 高相似:{high} 模糊:{fuzzy} 新题:{unm}")
        print(f"  有效覆盖: {covered}/{len(paper_qs)} ({rate})")
        
        all_unmatched.extend(unmatched)
    
    # ===== Dedup across papers =====
    seen_md5s = set()
    unique_unmatched = []
    dupes = 0
    for q in all_unmatched:
        if q['md5'] in seen_md5s:
            dupes += 1
            continue
        seen_md5s.add(q['md5'])
        unique_unmatched.append(q)
    
    print(f"\n{'='*70}")
    print(f"汇总: 精确{total_stats['exact']} + 高相似{total_stats['high']} + 模糊{total_stats['fuzzy']} + 新题{total_stats['unmatched']} = {sum(total_stats.values())}")
    print(f"确认新题: {len(unique_unmatched)} 题 ({dupes} 跨卷重复)")
    
    # ===== Statistics =====
    type_stats = defaultdict(int)
    module_stats = defaultdict(int)
    for q in unique_unmatched:
        type_stats[q['type']] += 1
        cat = q.get('category', '无分类')
        module_stats[cat] += 1
    
    print(f"\n按题型分布:")
    type_names = {'single': '单选题', 'multi': '多选题', 'judge': '判断题', 'indefinite': '不定项(案例题)'}
    for t, c in sorted(type_stats.items()):
        print(f"  {type_names.get(t, t)}: {c}")
    
    print(f"\n按知识板块分布:")
    for m, c in sorted(module_stats.items(), key=lambda x: -x[1]):
        print(f"  {m}: {c}")
    
    # ===== Show sample =====
    print(f"\n{'='*70}")
    print(f"示例题目 (前5题):")
    for i, q in enumerate(unique_unmatched[:5]):
        tp = type_names.get(q['type'], q['type'])
        cat = q.get('category', '?')
        print(f"\n  [{i+1}] [{tp}] [{cat}]")
        print(f"  Q: {q['question'][:100]}")
        print(f"  A: {q['answer']}")
        print(f"  ID: {q['id']}")
    
    # ===== Confirm =====
    if dry_run:
        print(f"\n{'='*70}")
        print(f"[DRY RUN] 将要导入 {len(unique_unmatched)} 题，实际未写入。")
        return unique_unmatched
    
    if not auto_confirm:
        print(f"\n{'='*70}")
        resp = input(f"\n确认导入 {len(unique_unmatched)} 题到SQLite题库? (y/n): ")
        if resp.lower() != 'y':
            print("已取消。")
            return unique_unmatched
    
    # ===== Write =====
    dao = _get_dao()
    all_questions = existing + unique_unmatched
    dao.save_questions(all_questions)
    
    print(f"\n✅ 导入成功!")
    print(f"  导入前: {len(existing)} 题")
    print(f"  新增:   {len(unique_unmatched)} 题")
    print(f"  导入后: {len(all_questions)} 题")
    
    # Verify
    verify = load_db_questions()
    print(f"  验证:   {len(verify)} 题 (预期 {len(all_questions)})")
    if len(verify) == len(all_questions):
        print("  ✅ 数据一致性验证通过")
    else:
        print(f"  ⚠️ 数据不一致! 差 {len(verify) - len(all_questions)} 题")
    
    return unique_unmatched


def load_db_questions():
    dao = _get_dao()
    return dao.load_questions()


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    auto_confirm = '--yes' in sys.argv
    main(dry_run=dry_run, auto_confirm=auto_confirm)

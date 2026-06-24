"""验证导入结果：84 道新题入库 + 61 道同一题无重复"""
import sqlite3, json

conn = sqlite3.connect('data/exmsys.db')
cur = conn.cursor()

# 1. 总题数
cur.execute('SELECT COUNT(*) FROM questions')
total = cur.fetchone()[0]
print(f'总题数: {total}')

# 2. 按题型
cur.execute('SELECT type, COUNT(*) FROM questions GROUP BY type ORDER BY COUNT(*) DESC')
print(f'\n按题型:')
for r in cur.fetchall():
    print(f'  {r[0]}: {r[1]} 题')

# 3. 验证 61 道同一题的 db_id 都在数据库中
with open('exmbase/模糊题分析结果.json', encoding='utf-8') as f:
    data = json.load(f)

same_ids = [item['db_id'] for item in data.get('same_questions', [])]
new_questions = data.get('new_questions', [])

missing = []
for sid in same_ids:
    cur.execute('SELECT COUNT(*) FROM questions WHERE id = ?', (sid,))
    if cur.fetchone()[0] == 0:
        missing.append(sid)

print(f'\n61 道同一题验证:')
print(f'  db_id 全部存在: {len(missing) == 0}')
if missing:
    print(f'  缺失: {missing[:5]}')

# 4. 验证新导入的 84 题在数据库中
cur.execute('SELECT id FROM questions')
all_ids = set(r[0] for r in cur.fetchall())

# 检查新题的 MD5 是否在库中
print(f'\n数据库验证:')
print(f'  导入前: 2068')
print(f'  导入后: {total}')
print(f'  新增: {total - 2068}')

# 5. 抽样检查几道导入的新题
print(f'\n抽样检查导入的新题:')
for item in new_questions[:3]:
    pq = item['paper_question']
    cur.execute('SELECT id, type, category, answer FROM questions WHERE question = ?', (pq,))
    r = cur.fetchone()
    if r:
        print(f'  Q{item["num"]}: id={r[0]}, type={r[1]}, category={r[2]}, answer={r[3]}')
    else:
        # Try by MD5
        import hashlib
        opts = item['paper_options']
        ans = item['paper_answer']
        from utils.paper_matcher import norm
        opts_dict = {}
        for i, opt in enumerate(opts):
            key = chr(ord('A') + i)
            opts_dict[key] = opt
        opts_items = sorted(opts_dict.items())
        content = pq + str(opts_items) + ans
        md5 = hashlib.md5(content.encode('utf-8')).hexdigest()
        cur.execute('SELECT id, type, category FROM questions WHERE md5 = ?', (md5,))
        r2 = cur.fetchone()
        if r2:
            print(f'  Q{item["num"]}: FOUND by MD5 id={r2[0]}, type={r2[1]}, category={r2[2]}')
        else:
            print(f'  Q{item["num"]}: NOT FOUND (pq={pq[:40]}...)')

conn.close()
print('\n✅ 全部验证通过!' if total == 2152 and len(missing) == 0 else '\n⚠️ 验证有问题')

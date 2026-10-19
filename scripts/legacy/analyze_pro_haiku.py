import json, os
from collections import OrderedDict
TAG = 'prohaiku100'
METHODS = [('base_haiku', 'Base Coding Agent (haiku)'), ('repo_context_haiku', 'Repository Context Retrieval'), ('pr_retrieval_haiku', 'Existing PR Retrieval'), ('static_haiku', 'Static Repository Skill Library'), ('append_haiku', 'Append-Only Skill Memory'), ('full_haiku', 'Skill Dreaming (Full)')]

def load(m):
    f = f'records_{m}_{TAG}.jsonl'
    if not os.path.exists(f):
        return None
    d = OrderedDict()
    for l in open(f):
        l = l.strip()
        if not l:
            continue
        r = json.loads(l)
        d[r['instance_id']] = r
    return d

def ok(r):
    return bool(r.get('task_success_strict'))

def allpass(v):
    v = str(v)
    if not v or v in ('?/0', '0/0', '', 'None'):
        return False
    try:
        (a, b) = v.split('/')
        return int(a) == int(b) and int(b) > 0
    except:
        return False
rows = {}
for (m, label) in METHODS:
    d = load(m)
    if not d:
        print(f'{label}: MISSING')
        continue
    n = len(d)
    k = sum((ok(r) for r in d.values()))
    empty = sum((bool(r.get('empty_patch')) for r in d.values()))
    applied = sum((bool(r.get('patch_applied')) for r in d.values()))
    gold = sum((allpass(r.get('f2p')) for r in d.values()))
    exist = sum((allpass(r.get('p2p')) for r in d.values()))
    tok = sum((r.get('tokens', 0) or 0 for r in d.values()))
    walls = [r.get('gen_wall', 0) or 0 for r in d.values()]
    tps = int(tok / k) if k else 0
    mw = sum(walls) / len(walls) if walls else 0
    rows[m] = d
    print(f'| {label} | official docker | {k / n:.3f} ({k}/{n}) | {exist / n:.3f} ({exist}) | {gold / n:.3f} ({gold}) | {empty} | {applied} | {tps:,} | {mw:.1f}s |')
if 'base_haiku' in rows:
    b = rows['base_haiku']
    print('\n=== paired vs base_haiku (single-seed WIN if other>base) ===')
    for (m, label) in METHODS:
        if m == 'base_haiku' or m not in rows:
            continue
        o = rows[m]
        ids = [i for i in o if i in b]
        kb = sum((ok(b[i]) for i in ids))
        ko = sum((ok(o[i]) for i in ids))
        bo = sum((1 for i in ids if ok(b[i]) and (not ok(o[i]))))
        oo = sum((1 for i in ids if ok(o[i]) and (not ok(b[i]))))
        both = sum((1 for i in ids if ok(b[i]) and ok(o[i])))
        verdict = 'WIN' if ko > kb else 'TIE' if ko == kb else 'LOSE'
        print(f'{label:38s} base={kb} other={ko} delta={(ko - kb) / len(ids):+.3f} both={both} base_only={bo} other_only={oo} [{verdict}]')

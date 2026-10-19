import json, os

def g(r, *ks):
    for k in ks:
        if k in r and r[k] is not None:
            return r[k]
    return None

def res(r):
    return bool(g(r, 'task_success_strict', 'resolved'))

def etp(r):
    p2p = g(r, 'p2p')
    if isinstance(p2p, str) and '/' in p2p:
        (a, b) = p2p.split('/')
        try:
            a = int(a)
            b = int(b)
            return b > 0 and a == b
        except:
            return None
    return None

def goldpr(r):
    f2p = g(r, 'f2p')
    if isinstance(f2p, str) and '/' in f2p:
        (a, b) = f2p.split('/')
        try:
            a = int(a)
            b = int(b)
            return b > 0 and a == b
        except:
            return None
    return None

def toks(r):
    return g(r, 'tokens') or 0
TABLES = {'T1_sonnet_Verified': ('v100', 101, [('base_v2', 'Base'), ('repo_context_v2', 'Repo'), ('pr_retrieval_v2', 'PR'), ('static_skill_v2', 'Static'), ('append_only_v2', 'Append'), ('full_v2', 'Full')]), 'T2_sonnet_Pro': ('pro100', 100, [('base_v2', 'Base'), ('repo_context_v2', 'Repo'), ('pr_retrieval_v2', 'PR'), ('static_skill_v2', 'Static'), ('append_only_v2', 'Append'), ('full_v2', 'Full')]), 'T3_haiku_Verified': ('haikuv101', 101, [('base_haiku', 'Base'), ('repo_context_haiku', 'Repo'), ('pr_retrieval_haiku', 'PR'), ('static_haiku', 'Static'), ('append_haiku', 'Append'), ('full_haiku', 'Full')]), 'T4_haiku_Pro': ('prohaiku100', 100, [('base_haiku', 'Base'), ('repo_context_haiku', 'Repo'), ('pr_retrieval_haiku', 'PR'), ('static_haiku', 'Static'), ('append_haiku', 'Append'), ('full_haiku', 'Full')])}
data = {}
for (tname, (tag, tgt, methods)) in TABLES.items():
    print('\n===== %s =====' % tname)
    rowsdata = {}
    for (m, short) in methods:
        f = 'records_%s_%s.jsonl' % (m, tag)
        rows = [json.loads(l) for l in open(f) if l.strip()]
        n = len(rows)
        rr = sum((1 for r in rows if res(r)))
        et = sum((1 for r in rows if etp(r)))
        gp = sum((1 for r in rows if goldpr(r)))
        avg = int(sum((toks(r) for r in rows)) / max(1, n))
        tps = int(sum((toks(r) for r in rows)) / max(1, rr)) if rr else 0
        rowsdata[m] = {r['instance_id']: res(r) for r in rows}
        print('  %-8s n=%d resolved=%d(%.3f) ETP=%d(%.3f) GoldPR=%d(%.3f) avgTok=%d tokPerSucc=%d' % (short, n, rr, rr / n, et, et / n, gp, gp / n, avg, tps))
    data[tname] = rowsdata
for (tname, (tag, tgt, methods)) in TABLES.items():
    rd = data[tname]
    base = rd[methods[0][0]]
    full = rd[methods[5][0]]
    ids = set(base) & set(full)
    both = sum((1 for i in ids if base[i] and full[i]))
    bonly = sum((1 for i in ids if base[i] and (not full[i])))
    fonly = sum((1 for i in ids if not base[i] and full[i]))
    print('\n%s paired full-vs-base: both=%d base_only=%d full_only=%d (delta=%+d)' % (tname, both, bonly, fonly, fonly - bonly))

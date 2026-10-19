import json, os

def res(r):
    for k in ('task_success_strict', 'resolved'):
        if k in r:
            return bool(r[k])
    return False
TABLES = {'T1_sonnet_Verified': ('v100', 101, ['base_v2', 'repo_context_v2', 'pr_retrieval_v2', 'static_skill_v2', 'append_only_v2', 'full_v2']), 'T2_sonnet_Pro': ('pro100', 100, ['base_v2', 'repo_context_v2', 'pr_retrieval_v2', 'static_skill_v2', 'append_only_v2', 'full_v2']), 'T3_haiku_Verified': ('haikuv101', 101, ['base_haiku', 'repo_context_haiku', 'pr_retrieval_haiku', 'static_haiku', 'append_haiku', 'full_haiku']), 'T4_haiku_Pro': ('prohaiku100', 100, ['base_haiku', 'repo_context_haiku', 'pr_retrieval_haiku', 'static_haiku', 'append_haiku', 'full_haiku'])}
for (tname, (tag, target, methods)) in TABLES.items():
    print('\n===== %s (tag=%s target=%d) =====' % (tname, tag, target))
    for m in methods:
        f = 'records_%s_%s.jsonl' % (m, tag)
        if not os.path.exists(f):
            print('  %-22s MISSING FILE' % m)
            continue
        rows = [json.loads(l) for l in open(f) if l.strip()]
        ids = [r['instance_id'] for r in rows]
        uniq = len(set(ids))
        rres = sum((1 for r in rows if res(r)))
        f429 = sum((1 for r in rows if not res(r) and r.get('n_candidates') == 0))
        dup = len(ids) - uniq
        flag = '' if uniq == target and f429 == 0 else '  <-- INCOMPLETE' if uniq < target else '  <-- 429!' if f429 else ''
        print('  %-22s n=%d uniq=%d res=%d false429=%d dup=%d%s' % (m, len(rows), uniq, rres, f429, dup, flag))

import json, os

def res(r):
    for k in ('task_success_strict', 'resolved'):
        if k in r:
            return bool(r[k])
    return False
TABLES = {'T1_sonnet_Verified': ('v2', 'v100', ['base_v2', 'repo_context_v2', 'pr_retrieval_v2', 'static_skill_v2', 'append_only_v2', 'full_v2']), 'T2_sonnet_Pro': (None, 'pro100', ['base_v2', 'repo_context_v2', 'pr_retrieval_v2', 'static_skill_v2', 'append_only_v2', 'full_v2']), 'T3_haiku_Verified': (None, 'haikuv101', ['base_haiku', 'repo_context_haiku', 'pr_retrieval_haiku', 'static_haiku', 'append_haiku', 'full_haiku']), 'T4_haiku_Pro': (None, 'prohaiku100', ['base_haiku', 'repo_context_haiku', 'pr_retrieval_haiku', 'static_haiku', 'append_haiku', 'full_haiku'])}
grand = {}
for (tname, (_, tag, methods)) in TABLES.items():
    print('\n===== %s (tag=%s) =====' % (tname, tag))
    tot = 0
    for m in methods:
        f = 'records_%s_%s.jsonl' % (m, tag)
        if not os.path.exists(f):
            print('  MISSING %s' % f)
            continue
        rows = [json.loads(l) for l in open(f) if l.strip()]
        fe = [r['instance_id'] for r in rows if not res(r) and r.get('n_candidates') == 0]
        n = len(rows)
        rres = sum((1 for r in rows if res(r)))
        print('  %-22s file=%-42s n=%d res=%d false429=%d' % (m, f, n, rres, len(fe)))
        if fe:
            grand[f] = fe
            tot += len(fe)
    print('  --> table false429 total:', tot)
json.dump(grand, open('_main4_false429.json', 'w'), indent=1)
print('\nGRAND TOTAL false429 in 4 main tables:', sum((len(v) for v in grand.values())))
print('files:', list(grand.keys()))

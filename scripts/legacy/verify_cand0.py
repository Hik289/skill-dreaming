import json, os, time
FIX_TS = 1787080000

def res(r):
    for k in ('task_success_strict', 'resolved'):
        if k in r:
            return bool(r[k])
    return False
files = {'v100': ['base_v2', 'repo_context_v2', 'pr_retrieval_v2', 'static_skill_v2', 'append_only_v2', 'full_v2'], 'pro100': ['base_v2', 'repo_context_v2', 'pr_retrieval_v2', 'static_skill_v2', 'append_only_v2', 'full_v2'], 'prohaiku100': ['base_haiku', 'repo_context_haiku', 'pr_retrieval_haiku', 'static_haiku', 'append_haiku', 'full_haiku'], 'haikuv101': ['base_haiku', 'repo_context_haiku', 'pr_retrieval_haiku', 'static_haiku', 'append_haiku', 'full_haiku']}
tot = 0
old = 0
for (tag, methods) in files.items():
    for m in methods:
        f = 'records_%s_%s.jsonl' % (m, tag)
        if not os.path.exists(f):
            continue
        for l in open(f):
            r = json.loads(l)
            if not res(r) and r.get('n_candidates') == 0:
                ts = r.get('ts', 0)
                fresh = ts >= FIX_TS
                tot += 1
                if not fresh:
                    old += 1
                print('%-28s %-16s %-45s ts=%d %s tok=%s' % (m, tag, r['instance_id'][:45], ts, 'FRESH' if fresh else 'OLD!!', r.get('tokens')))
print('\nTotal cand0 unresolved:', tot, ' | regenerated OLD(pre-fix):', old)

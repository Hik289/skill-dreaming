import json, random

def res(r):
    for k in ('task_success_strict', 'resolved'):
        if k in r:
            return bool(r[k])
    return False

def load(f):
    d = {}
    for l in open(f):
        if l.strip():
            r = json.loads(l)
            d[r['instance_id']] = res(r)
    return d

def boot(base, other, ids, n=10000):
    ids = list(ids)
    deltas = []
    obs = sum((other[i] - base[i] for i in ids)) / len(ids)
    random.seed(0)
    for _ in range(n):
        s = [ids[random.randrange(len(ids))] for _ in ids]
        deltas.append(sum((other[i] - base[i] for i in s)) / len(s))
    deltas.sort()
    lo = deltas[int(0.025 * n)]
    hi = deltas[int(0.975 * n)]
    return (obs, lo, hi)
for (tag, methods, label) in [('v100', ['base_v2', 'repo_context_v2', 'pr_retrieval_v2', 'static_skill_v2', 'append_only_v2', 'full_v2'], 'Verified'), ('pro100', ['base_v2', 'repo_context_v2', 'pr_retrieval_v2', 'static_skill_v2', 'append_only_v2', 'full_v2'], 'Pro')]:
    print('\n=== %s (tag=%s) paired vs base ===' % (label, tag))
    base = load('records_%s_%s.jsonl' % (methods[0], tag))
    for m in methods[1:]:
        o = load('records_%s_%s.jsonl' % (m, tag))
        ids = set(base) & set(o)
        (obs, lo, hi) = boot(base, o, ids)
        both = sum((1 for i in ids if base[i] and o[i]))
        bo = sum((1 for i in ids if base[i] and (not o[i])))
        fo = sum((1 for i in ids if not base[i] and o[i]))
        sig = 'CROSSES0' if lo <= 0 <= hi else 'SIG'
        print('  %-18s delta=%+.3f [%.3f,%.3f] %s | both=%d base_only=%d other_only=%d' % (m, obs, lo, hi, sig, both, bo, fo))

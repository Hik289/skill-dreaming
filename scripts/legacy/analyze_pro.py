import json, os, sys, math
from collections import OrderedDict
METHODS = ['base_v2', 'repo_context_v2', 'pr_retrieval_v2', 'static_skill_v2', 'append_only_v2', 'full_v2']
TAG = 'pro100'

def load(m):
    f = f'records_{m}_{TAG}.jsonl'
    if not os.path.exists(f):
        return None
    d = OrderedDict()
    for line in open(f):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        d[r['instance_id']] = r
    return d

def wilson(k, n, z=1.96):
    if n == 0:
        return (0, 0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (c - h, c + h)

def resolved(r):
    return bool(r.get('task_success_strict'))

def summ(m, d):
    n = len(d)
    k = sum((resolved(r) for r in d.values()))
    empty = sum((bool(r.get('empty_patch')) for r in d.values()))
    applied = sum((bool(r.get('patch_applied')) for r in d.values()))
    (lo, hi) = wilson(k, n)
    p2p = sum((1 for r in d.values() if str(r.get('p2p', '')).count('/') == 1 and r['p2p'].split('/')[0] == r['p2p'].split('/')[1] and (r['p2p'] != '0/0')))
    print(f'{m:20s} n={n:3d} resolved={k:3d} ({k / n:.3f}) Wilson[{lo:.3f},{hi:.3f}] empty={empty} applied={applied}')
    return d

def paired_delta(base, other, name):
    ids = [i for i in other if i in base]
    n = len(ids)
    b_only = sum((1 for i in ids if resolved(base[i]) and (not resolved(other[i]))))
    o_only = sum((1 for i in ids if resolved(other[i]) and (not resolved(base[i]))))
    both = sum((1 for i in ids if resolved(base[i]) and resolved(other[i])))
    neither = n - both - b_only - o_only
    kb = sum((resolved(base[i]) for i in ids))
    ko = sum((resolved(other[i]) for i in ids))
    delta = (ko - kb) / n if n else 0
    import random
    random.seed(0)
    diffs = [(1 if resolved(other[i]) else 0) - (1 if resolved(base[i]) else 0) for i in ids]
    boots = []
    for _ in range(10000):
        s = sum((diffs[random.randrange(n)] for _ in range(n))) / n
        boots.append(s)
    boots.sort()
    clo = boots[int(0.025 * len(boots))]
    chi = boots[int(0.975 * len(boots))]
    cross0 = clo <= 0 <= chi
    tag = 'CROSSES0' if cross0 else 'SIG'
    print(f'{name:20s} vs base paired n={n} base={kb} other={ko} delta={delta:+.3f} boot95[{clo:+.3f},{chi:+.3f}] {tag} | base_only={b_only} other_only={o_only} both={both} neither={neither}')
data = {}
for m in METHODS:
    d = load(m)
    if d is None:
        print(f'{m:20s} MISSING')
        continue
    data[m] = summ(m, d)
print('---- paired deltas vs base_v2 ----')
base = data.get('base_v2')
if base:
    for m in METHODS[1:]:
        if m in data:
            paired_delta(base, data[m], m)

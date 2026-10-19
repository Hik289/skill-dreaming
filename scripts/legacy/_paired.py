import json, os

def load(f):
    d = {}
    if not os.path.exists(f):
        return d
    for l in open(f):
        try:
            x = json.loads(l)
        except:
            continue
        d[x['instance_id']] = x
    return d

def sol(d):
    return set((k for (k, x) in d.items() if x.get('task_success_strict')))
dev = set(json.load(open('_denoise_dev.json')))
base = load('records_base_v2_v100.jsonl')
base_dev_sol = sol({k: v for (k, v) in base.items() if k in dev})
print(f'BASE on dev32: solved={len(base_dev_sol)}/{len(dev & set(base))}')
variants = ['dn_current', 'dn_top1', 'dn_top2', 'dn_filt02', 'dn_filt04', 'dn_filt06']
for t in variants:
    d = load(f'records_{t}.jsonl')
    d = {k: v for (k, v) in d.items() if k in dev}
    if not d:
        print(f'{t}: (empty)')
        continue
    s = sol(d)
    done = set(d)
    b = base_dev_sol & done
    kept = len(s & b)
    newly = len(s - b)
    broken = len(b - s)
    nc0 = sum((1 for x in d.values() if x.get('n_candidates', 0) == 0))
    print(f'{t}: n={len(d)} resolved={len(s)} | vs base(on done={len(done)}, base_sol={len(b)}): kept={kept} newly-solved={newly} newly-broken={broken} | ncand0={nc0}')

import json, sys, os

def load(tag):
    f = f'records_{tag}.jsonl'
    if not os.path.exists(f):
        return {}
    d = {}
    for l in open(f):
        try:
            x = json.loads(l)
        except:
            continue
        d[x['instance_id']] = x
    return d

def solved(d):
    return set((k for (k, x) in d.items() if x.get('task_success_strict')))

def ncand0(d):
    return set((k for (k, x) in d.items() if x.get('n_candidates', 0) == 0))
tags = sys.argv[1:] if len(sys.argv) > 1 else ['dn_current', 'dn_top1', 'dn_top2', 'dn_filt02', 'dn_filt04', 'dn_filt06']
dev = set(json.load(open('_denoise_dev.json')))
for t in tags:
    d = load(t)
    n = len(d)
    s = solved(d)
    z = ncand0(d)
    print(f'{t}: n={n} resolved={len(s)} ncand0={len(z)}')

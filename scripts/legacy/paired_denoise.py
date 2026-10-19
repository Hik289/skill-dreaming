import json, os, sys
DEV = json.load(open('_denoise_dev.json'))
devset = set(DEV)

def load(f):
    d = {}
    if not os.path.exists(f):
        return d
    for l in open(f):
        l = l.strip()
        if not l:
            continue
        r = json.loads(l)
        d[r['instance_id']] = bool(r.get('task_success_strict'))
    return d
base_all = load('records_base_v100.jsonl')
full_all = load('records_full_v100.jsonl')
base = {k: v for (k, v) in base_all.items() if k in devset}
full = {k: v for (k, v) in full_all.items() if k in devset}
print('dev32 coverage: base=%d full=%d (of %d)' % (len(base), len(full), len(devset)))
base_res = sum(base.values())
full_res = sum(full.values())
print('REF on dev32: base_resolved=%d  full(current-main)_resolved=%d' % (base_res, full_res))
print()
variants = [('dn_current', 'records_dn_current.jsonl'), ('dn_top1', 'records_dn_top1.jsonl'), ('dn_top2', 'records_dn_top2.jsonl'), ('dn_filt02', 'records_dn_filt02.jsonl'), ('dn_filt04', 'records_dn_filt04.jsonl'), ('dn_filt06', 'records_dn_filt06.jsonl')]
print('%-12s %5s %5s | vs BASE: kept new broken | vs FULL: kept new broken' % ('variant', 'n', 'res'))
for (tag, f) in variants:
    v = load(f)
    v = {k: val for (k, val) in v.items() if k in devset}
    if not v:
        print('%-12s   (no data yet)' % tag)
        continue
    ids = [i for i in devset if i in v]
    res = sum((v[i] for i in ids))
    kb = sum((1 for i in ids if i in base and base[i] and v[i]))
    nb = sum((1 for i in ids if i in base and (not base[i]) and v[i]))
    brb = sum((1 for i in ids if i in base and base[i] and (not v[i])))
    kf = sum((1 for i in ids if i in full and full[i] and v[i]))
    nf = sum((1 for i in ids if i in full and (not full[i]) and v[i]))
    brf = sum((1 for i in ids if i in full and full[i] and (not v[i])))
    print('%-12s %5d %5d | vsBASE k=%d n=%d b=%d | vsFULL k=%d n=%d b=%d' % (tag, len(ids), res, kb, nb, brb, kf, nf, brf))
